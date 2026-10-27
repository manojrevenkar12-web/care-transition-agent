package pseudo

import (
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/identity"
)

// Words that introduce a person: a title, a role, a relation or a sign-off. A surname that is also an ordinary word
// ("Stern", "Koch", "Klein", "Mai") is read as a name only after one of these, after a given name, or before
// ", <given name>"; "Hr. Stern, Z.n. Sternotomie" and "Sohn ist Bauer, mitten in der Maisernte" then read correctly.
var personWords = map[string]bool{}

func init() {
	for _, w := range strings.Fields(`frau fr herr hr herrn dr doktor prof pat patient patientin patienten sohn tochter
		ehemann ehefrau mann enkel enkelin bruder schwester schw sr pfl pfleger pflegerin betreuer betreuerin nachbar
		nachbarin oa oä oberarzt oberärztin hausarzt hausärztin familie fam geb geborene witwe witwer vater mutter onkel
		tante nichte neffe schwiegersohn schwiegertochter lebensgefährte lebensgefährtin gez stationsarzt stationsärztin
		assistenzarzt assistenzärztin therapeut therapeutin physiotherapeut physiotherapeutin ehepaar eheleute kollege
		kollegin bevollmächtigte bevollmächtigter`) {
		personWords[w] = true
	}
	// surnames that are also nouns: German nouns are capitalised, so capitalisation does not tell them apart
	for _, w := range strings.Fields(`stern herz licht vogel kaiser schneider bauer koch wagner ringer hamburger barthel
		schmied maurer zimmermann fleischer schäfer schaefer jäger jaeger gärtner gaertner fischer
		schreiber kaufmann hirsch bär baer löwe loewe falke specht haas krug engel teufel mond sonne 
		lehrer pfarrer brauer schuster sattler drechsler förster
		foerster sauer stolz zeit wolke regen blum blume rose dorn eiche linde
		birke tanne kirsch nuss apfel kern korn hafer weizen roggen gerste fink amsel kranich reiher strauss
		januar februar märz april juni juli august september oktober november dezember ernst frank`) {
		commonWords[w] = true
	}
}

// prevWords returns up to n lower-cased words before byte offset i, nearest first, without punctuation.
func prevWords(text string, i, n int) []string {
	fields := strings.FieldsFunc(text[:i], func(r rune) bool { return unicode.IsSpace(r) || r == ',' || r == ';' || r == '(' || r == ':' })
	var out []string
	for k := len(fields) - 1; k >= 0 && len(out) < n; k-- {
		w := strings.ToLower(strings.Trim(fields[k], ".«»\"„“"))
		if w != "" {
			out = append(out, w)
		}
	}
	return out
}

// nextWords returns up to n words after byte offset j and whether a comma comes first.
func nextWords(text string, j, n int) ([]string, bool) {
	rest := strings.TrimLeft(text[j:], " \t")
	comma := strings.HasPrefix(rest, ",")
	fields := strings.FieldsFunc(rest, func(r rune) bool { return unicode.IsSpace(r) || r == ',' || r == ';' })
	var out []string
	for _, f := range fields {
		if len(out) == n {
			break
		}
		out = append(out, strings.Trim(f, ".«»\"„“()"))
	}
	return out, comma
}

// hasPersonContext: the words around a name show that it is used as a name.
func hasPersonContext(text string, start, end int, p identity.Person) bool {
	before := prevWords(text, start, 2)
	givens := map[string]bool{}
	for _, g := range strings.Fields(p.Given) {
		givens[strings.ToLower(g)] = true
	}
	if len(before) > 0 {
		w0 := before[0]
		if personWords[w0] || givens[w0] || givenNames[capitalise(w0)] && !commonWords[w0] {
			return true
		}
		// "Frau Dr. Stern", "Herrn Prof. Licht", "Fr. M. Stern"
		short := w0 == "med" || w0 == "dr" || w0 == "prof" || len([]rune(w0)) == 1
		if short && len(before) > 1 && personWords[before[1]] {
			return true
		}
	}
	after, comma := nextWords(text, end, 1)
	return comma && len(after) == 1 && (givens[strings.ToLower(after[0])] || givenNames[after[0]])
}

var nounSuffixes = []string{"ie", "ik", "ung", "heit", "keit", "schaft", "ion", "tät", "ität", "ismus", "ologe", "ologin", "station", "abteilung"}

// plausibleName rejects captures that are roles or ordinary nouns ("Kollegin", "Kardiologie").
func plausibleName(w string) bool {
	low := strings.ToLower(strings.TrimSuffix(w, "."))
	if personWords[low] || notAName[low] || len([]rune(low)) < 2 {
		return false
	}
	for _, suf := range nounSuffixes {
		if strings.HasSuffix(low, suf) && len(low) > len(suf)+2 {
			return false
		}
	}
	return true
}

func capitalise(w string) string {
	r, size := utf8.DecodeRuneInString(w)
	return string(unicode.ToUpper(r)) + w[size:]
}

// eponym: "Barthel-Index", "Hoffmann-Tinel-Zeichen", "Wagner-Armstrong": a name joined to another word by a hyphen
// is a term, not the person (the person's own double name is matched as a whole, as a longer variant).
func eponym(text string, start, end int) bool {
	if end < len(text)-1 && text[end] == '-' {
		r, _ := utf8.DecodeRuneInString(text[end+1:])
		if unicode.IsLetter(r) {
			return true
		}
	}
	if start > 1 && text[start-1] == '-' {
		r, _ := utf8.DecodeLastRuneInString(text[:start-1])
		if unicode.IsLetter(r) {
			return true
		}
	}
	return false
}

// isDictation: speech-recognition transcripts are almost entirely lower case.
func isDictation(text string) bool {
	words, lower := 0, 0
	for _, w := range strings.Fields(text) {
		r, _ := utf8.DecodeRuneInString(w)
		if !unicode.IsLetter(r) {
			continue
		}
		words++
		if unicode.IsLower(r) {
			lower++
		}
	}
	return words >= 15 && lower*100 >= words*85
}

type nameVariant struct {
	folded string // folded the way the view is folded
	mode   foldMode
	single bool // one word of the name: needs context if it is also an ordinary word
	common bool
}

var particles = map[string][]string{"von der": {"v. d.", "v.d."}, "von dem": {"v. d.", "v.d."}, "von": {"v."}, "van der": {"v. d."}}

// variantsOf lists the spellings of a person's name to look for, folded.
func variantsOf(p identity.Person) []nameVariant {
	g, f := strings.TrimSpace(p.Given), strings.TrimSpace(p.Family)
	fams := []string{}
	if f != "" {
		fams = append(fams, f)
		low := strings.ToLower(f)
		for long, shorts := range particles {
			if strings.HasPrefix(low, long+" ") {
				for _, s := range shorts {
					fams = append(fams, s+f[len(long):])
				}
				fams = append(fams, strings.TrimSpace(f[len(long):]))
			}
		}
	}
	var full, single []string
	for _, fam := range fams {
		if g != "" {
			full = append(full, g+" "+fam, fam+", "+g, fam+" "+g, g[:1]+". "+fam, g[:1]+"."+fam)
			for _, gp := range strings.Fields(g) {
				if gp != g {
					full = append(full, gp+" "+fam)
				}
			}
		}
		single = append(single, fam)
		if strings.Contains(fam, "-") {
			single = append(single, strings.Split(fam, "-")...)
		}
	}
	for _, gp := range strings.Fields(g) {
		if len([]rune(gp)) >= 3 {
			single = append(single, gp)
			if strings.Contains(gp, "-") {
				single = append(single, strings.Split(gp, "-")...)
			}
		}
	}
	seen := map[string]bool{}
	var out []nameVariant
	add := func(v string, isSingle bool) {
		for _, mode := range []foldMode{foldExpand, foldDrop} {
			fv := foldString(v, mode)
			if len([]rune(fv)) < 2 || seen[fv] {
				continue
			}
			seen[fv] = true
			common := isSingle && (commonWords[strings.ToLower(v)] || commonWords[fv] || len([]rune(fv)) <= 3)
			out = append(out, nameVariant{fv, mode, isSingle, common})
			out = append(out, nameVariant{fv + "s", mode, isSingle, common}) // genitive
		}
	}
	for _, v := range full {
		add(v, false)
	}
	for _, v := range single {
		add(strings.TrimSpace(v), true)
	}
	return out
}

// ---- initials ------------------------------------------------------------------------------------------------------

var reTitledInitials = regexp.MustCompile(`\b(?:Frau|Fr\.|Herrn?|Hr\.|Pat\.|Patientin|Patient|Dr\.)\s+((?:[A-ZÄÖÜ]\.\s?-?\s?){1,3})`)
var reBareInitials = regexp.MustCompile(`(?:^|[\s(,;])((?:[A-ZÄÖÜ]\.\s?-?){2,3})`)

func initialsOf(s string) string {
	var b strings.Builder
	for _, r := range s {
		if unicode.IsUpper(r) {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// personInitials: "B" (family), "WB" (given and family), "PS" (a double family name).
func personInitials(p identity.Person) map[string]bool {
	out := map[string]bool{}
	fam := strings.TrimSpace(p.Family)
	for long := range particles {
		if strings.HasPrefix(strings.ToLower(fam), long+" ") {
			fam = strings.TrimSpace(fam[len(long):])
		}
	}
	fi := ""
	for _, part := range strings.FieldsFunc(fam, func(r rune) bool { return r == '-' || r == ' ' }) {
		r, _ := utf8.DecodeRuneInString(part)
		fi += string(unicode.ToUpper(r))
	}
	gi := ""
	for _, part := range strings.FieldsFunc(p.Given, func(r rune) bool { return r == '-' || r == ' ' }) {
		r, _ := utf8.DecodeRuneInString(part)
		gi += string(unicode.ToUpper(r))
	}
	if fi != "" {
		out[fi] = true
		out[fi[:1]] = true
		if gi != "" {
			out[gi+fi] = true
			out[gi[:1]+fi[:1]] = true
		}
	}
	return out
}

// ---- people the record does not list ---------------------------------------------------------------------------

var (
	reSignoff     = regexp.MustCompile(`(?:\b(?:gez\.|i\.\s?A\.|LG|VG|MfG|Gruß|Grüße|Ausgefüllt von:?|Schw\.|Sr\.|Pfl\.|Pfleger(?:in)?|PFK|Stationsarzt|Stationsärztin|Hausarzt|Hausärztin|OA|OÄ|Oberarzt|Oberärztin|Assistenzarzt|Assistenzärztin|Physiotherapeut(?:in)?|Ergotherapeut(?:in)?|Logopäd(?:e|in)|Sozialarbeiter(?:in)?|Kolleg(?:e|in))\s+(?:(?:Dr|Prof|Schw|Sr|Fr|Hr)\.\s+|(?:Frau|Herr|Schwester|Pfleger)\s+)?)(` + nameRe + `(?:\s+` + nameWord + `)?)`)
	reGivenFamily = regexp.MustCompile(`\b([A-ZÄÖÜ][a-zäöüß]+)\s+([A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)\b`)
	reLowerTitle  = regexp.MustCompile(`\b(?:frau|herr|herrn|doktor|dr\.?|schwester|pfleger|pflegerin|hausarzt|hausärztin|nachbarin|nachbar|tochter|sohn|enkelin|enkel|betreuerin|betreuer)\b`)
)

// words that follow a title in dictation without being a name ("die tochter hat angerufen")
var notAName = map[string]bool{}

func init() {
	for _, w := range strings.Fields(`und oder ist hat war wird wurde sind haben kann soll muss möchte will hatte habe
		mit von zu zur zum im in am an auf aus bei nach vor für über unter um der die das den dem des ein eine einen
		einem einer sie er es ihr ihre ihren sein seine seinen noch auch schon heute gestern morgen bitte nicht kein
		keine sich so da dann doch nur sehr wieder gerade gleich jetzt hier dort erreicht informiert angerufen gesagt
		gesprochen meint meinte berichtet berichtete kommt kam ruft rief bringt brachte dass daß ob weil wenn als wie was
		welche welcher welches betrifft bzw ca etwa ebenfalls bereits immer nie weiterhin wegen trotz laut gemäß
		doktor dr frau herr herrn schwester pfleger pflegerin prof professor hausarzt hausärztin oberarzt oberärztin
		tochter sohn nachbar nachbarin enkel enkelin betreuer betreuerin patient patientin`) {
		notAName[w] = true
	}
}

// stop words after a given name: "Maria Hilf" is a hospital, "Anna Station" is not a person
var notAFamily = map[string]bool{"Hilf": true, "Station": true, "Klinik": true, "Haus": true, "Stift": true, "Heim": true}

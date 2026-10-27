// Package pseudo replaces the identifiers in German clinical text with tags before the text reaches a model, checks
// that none survived, and maps tags back for the clinician.
//
// Two kinds of detectors run: the case's known identifiers (from the hospital system: the patient's and relatives'
// names, date of birth, insurance number, address, phone numbers, case numbers), which are exact and come first, and
// patterns for identifiers the record does not list (a neighbour's name after "Frau", a phone number, an IBAN, a
// street address). Tags are typed («Patient», «Angehörige-1», «Telefon») so the model still knows what it is reading,
// and a person the record does not list gets a stable tag derived from a keyed hash, so the same name gets the same tag
// in every document and every request of the tenant without the name itself being recoverable from the tag.
package pseudo

import (
	"crypto/hmac"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/identity"
)

// Replacement records one replaced span. Offsets are in Unicode code points (as Python counts them), in the input
// (Start, End) and in the output (OutStart, OutEnd).
type Replacement struct {
	Start    int    `json:"start"`
	End      int    `json:"end"`
	OutStart int    `json:"out_start"`
	OutEnd   int    `json:"out_end"`
	Kind     string `json:"kind"`
	Tag      string `json:"tag"`
}

type Result struct {
	Text         string        `json:"text"`
	Replacements []Replacement `json:"replacements"`
}

type span struct {
	start, end int // byte offsets in the input
	kind, tag  string
	priority   int
}

const (
	prioKnown   = 3
	prioLabeled = 2
	prioPattern = 1
)

type Pseudonymizer struct {
	id      identity.Identity
	key     []byte // keyed hash for unknown names
	asOf    time.Time
	ageCap  int
	persons []personTag
}

type personTag struct {
	p   identity.Person
	tag string
}

func New(id identity.Identity, surrogateKey []byte, ageCap int, now time.Time) *Pseudonymizer {
	asOf := now
	if t, err := time.Parse("2006-01-02", id.AsOf); err == nil {
		asOf = t
	}
	ps := &Pseudonymizer{id: id, key: surrogateKey, asOf: asOf, ageCap: ageCap}
	counts := map[string]int{}
	for _, p := range id.Persons {
		var tag string
		switch p.Role {
		case "patient":
			tag = "«Patient»"
		case "relative":
			counts["relative"]++
			tag = fmt.Sprintf("«Angehörige-%d»", counts["relative"])
		case "physician":
			counts["physician"]++
			tag = fmt.Sprintf("«Arzt-%d»", counts["physician"])
		default:
			counts["other"]++
			tag = fmt.Sprintf("«Kontakt-%d»", counts["other"])
		}
		ps.persons = append(ps.persons, personTag{p, tag})
	}
	return ps
}

var (
	reExistingTag  = regexp.MustCompile(`«[^»]{1,40}»`)
	nameWord       = `[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?`
	nameRe         = `(?:[A-ZÄÖÜ]\.\s?)?` + nameWord + `(?:\s+(?:von|van|de|zu|von der)\s+` + nameWord + `)?`
	reTitled       = regexp.MustCompile(`(?:\b(?:Herrn?|Frau|Hr\.|Fr\.)\s+(?:(?:Dr\.|Prof\.)\s+)?(?:med\.\s+)?)(` + nameRe + `(?:\s+` + nameWord + `)?)`)
	reDoctor       = regexp.MustCompile(`(?:\b(?:Dr|Prof)\.(?:\s?(?:med|rer\.\s?nat|phil|h\.\s?c)\.)?\s+)(` + nameRe + `(?:\s+` + nameWord + `)?)`)
	reRelational   = regexp.MustCompile(`\b(?:Sohn|Tochter|Ehemann|Ehefrau|Ehepartner(?:in)?|Lebensgefährt(?:e|in)|Enkel(?:in)?|Bruder|Schwester|Nichte|Neffe|Schwiegersohn|Schwiegertochter|Betreuer(?:in)?|Bevollmächtigte[rn]?|Nachbar(?:in)?|Ansprechpartner(?:in)?)\s*[:,]?\s+(` + nameWord + `(?:\s+` + nameWord + `)?)`)
	reKVNR         = regexp.MustCompile(`\b[A-Z][0-9]{9}\b`)
	reKVNRLabel    = regexp.MustCompile(`(?i)(?:KVNR|Versichertennr\.?|Versichertennummer|Vers\.-Nr\.?)\s*:?\s*([A-Z][0-9]{9})`)
	reIBAN         = regexp.MustCompile(`\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,4})?\b`)
	reEmail        = regexp.MustCompile(`[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`)
	rePhoneLabel   = regexp.MustCompile(`(?i)(?:tel\.?|telefon(?:nummer)?|mobil|handy|fon|rückruf(?:nummer)?)\s*(?:nr\.?)?\s*:?\s*(\+?[0-9][0-9 ()/-]{5,}[0-9])`)
	rePhoneIntl    = regexp.MustCompile(`\+[1-9][0-9]{0,2}[0-9 ()/-]{6,}[0-9]`)
	rePhoneLocal   = regexp.MustCompile(`\b0[1-9][0-9]{1,4}[ /-][0-9]{3,}(?:[ -][0-9]+)*\b`)
	reStreet       = regexp.MustCompile(`\b[A-ZÄÖÜ][a-zäöüß]+(?:[ -][A-ZÄÖÜ][a-zäöüß]+)*(?:straße|strasse|str\.|weg|allee|platz|ring|gasse|damm|ufer|chaussee)\s+\d{1,4}\s?[a-zA-Z]?\b`)
	rePostalCity   = regexp.MustCompile(`\b(\d{5})\s+[A-ZÄÖÜ][a-zäöüß]+`)
	reCaseNumber   = regexp.MustCompile(`(?i)(?:Fall(?:nummer|-?nr\.?)|Aufnahme(?:nummer|-?nr\.?)|Patienten-?(?:ID|nr\.?)|Pat\.-?(?:ID|Nr\.?))\s*:?\s*([A-Z0-9][A-Z0-9-]{4,})`)
	reFallLabel    = regexp.MustCompile(`(?i)\b(?:Fall|Vorfall|Voraufenthalt|Aufnahme)\s*(?:-?Nr\.?|nummer)?\s*:?\s+([0-9][0-9/ -]{4,}[0-9])`)
	reCaseYear     = regexp.MustCompile(`\b(?:19|20)\d{2}[-/]\d{5,7}\b`)
	reOtherID      = regexp.MustCompile(`(?i)(?:Reisepass\w*|Pass-?Nr\.?|Passnummer|Personalausweis\w*|Ausweis-?Nr\.?|Ausweisnummer|Az\.|Aktenzeichen|Geschäftszeichen|RV-?Nr\.?|Rentenversicherungsnummer|Sozialversicherungsnummer|SV-?Nr\.?)\s*(?:\(?Nr\.?\s*)?:?\s*([A-Z0-9][A-Z0-9 ./-]{4,18}[A-Z0-9])|\b([XVI]{1,6}\s+\d{1,5}/\d{2})\b|\b(\d{2}\s?\d{6}\s?[A-Z]\s?\d{3})\b`)
	rePrefixStreet = regexp.MustCompile(`\b(?:Am|An der|An den|Auf dem|Auf der|Im|In der|In den|Zum|Zur|Hinter dem|Unter den|Alt)\s+([A-ZÄÖÜ][a-zäöüß]+)\s+\d{1,3}[a-z]?\b`)
	reWord         = regexp.MustCompile(`[a-zäöüß]+`)
	reBirthLabel   = regexp.MustCompile(`(?i)(?:geb\.?(?:\s*am)?|geboren(?:\s*am)?|Geburtsdatum|\*)\s*:?\s*(\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4})`)
)

// words that follow a five-digit number without it being a postal code ("20000 Einheiten Heparin")
var notCity = map[string]bool{"Einheiten": true, "Schritte": true, "Stück": true, "Mal": true, "Euro": true, "Zellen": true}

var germanMonths = []string{"Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"}

// Pseudonymize replaces identifiers in text. Text already carrying tags is left alone, so running it twice is safe.
func (ps *Pseudonymizer) Pseudonymize(text string) Result {
	protected := reExistingTag.FindAllStringIndex(text, -1)
	var spans []span
	add := func(start, end int, kind, tag string, prio int) {
		if start >= end {
			return
		}
		for _, p := range protected {
			if start < p[1] && end > p[0] {
				return
			}
		}
		spans = append(spans, span{start, end, kind, tag, prio})
	}

	// 1. known identifiers, searched in normalised views of the text (umlauts, diacritics, Cyrillic, OCR, line breaks)
	views := []view{normView(text, foldExpand), normView(text, foldDrop)}
	runs := digitRuns(text)
	dictation := isDictation(text)
	for _, pt := range ps.persons {
		for _, nv := range variantsOf(pt.p) {
			for _, m := range findInView(views[nv.mode], nv.folded) {
				if ps.acceptName(text, m[0], m[1], pt.p, nv, dictation) {
					add(m[0], m[1], "name", pt.tag, prioKnown)
				}
			}
		}
	}
	for _, re := range []*regexp.Regexp{reTitledInitials, reBareInitials} {
		titled := re == reTitledInitials
		for _, m := range re.FindAllStringSubmatchIndex(text, -1) {
			raw := strings.TrimRight(text[m[2]:m[3]], " -")
			ini := initialsOf(raw)
			for _, pt := range ps.persons {
				if pi := personInitials(pt.p); pi[ini] && (titled || len(ini) >= 2) {
					add(m[2], m[2]+len(raw), "name", pt.tag, prioKnown)
					break
				}
			}
		}
	}
	birthTag := ""
	if bd, err := time.Parse("2006-01-02", ps.id.BirthDate); err == nil {
		birthTag = ps.birthTag(bd)
		for _, v := range dateVariants(bd) {
			for _, m := range findInView(views[0], foldString(v, foldExpand)) {
				add(m[0], m[1], "birth_date", birthTag, prioKnown)
			}
		}
		for _, sd := range spokenDates(views[0]) {
			if sd.day == bd.Day() && sd.month == int(bd.Month()) && (sd.year == bd.Year() || sd.twoDigitYear && sd.year == bd.Year()%100) {
				add(sd.start, sd.end, "birth_date", birthTag, prioKnown)
			}
		}
	}
	if k := strings.ToUpper(ps.id.KVNR); len(k) == 10 {
		for _, m := range findDigitsIn(runs, k[1:], false) {
			add(kvnrStart(text, m[0], k[0]), m[1], "kvnr", "«KVNR»", prioKnown)
		}
	}
	for _, c := range ps.id.CaseNumbers {
		for _, want := range caseDigitVariants(c) {
			for _, m := range findDigitsIn(runs, want, false) {
				add(m[0], m[1], "case_number", "«Fallnummer»", prioKnown)
			}
		}
		if d := digitsOnly(c); len(d) > 6 {
			for _, m := range reFallLabel.FindAllStringSubmatchIndex(text, -1) {
				if digitsOnly(text[m[2]:m[3]]) == d[len(d)-6:] {
					add(m[2], m[3], "case_number", "«Fallnummer»", prioKnown)
				}
			}
		}
	}
	for _, a := range ps.id.Addresses {
		for _, v := range streetVariants(a.Street) {
			for _, m := range findInView(views[0], foldString(v, foldExpand)) {
				add(m[0], m[1], "address", "«Adresse»", prioKnown)
			}
		}
		if name := streetName(a.Street); len([]rune(name)) >= 6 {
			for _, m := range findInView(views[0], foldString(name, foldExpand)) {
				add(m[0], houseNumberEnd(text, m[1]), "address", "«Adresse»", prioKnown)
			}
		}
		if a.PostalCode != "" {
			for _, m := range findDigitsIn(runs, a.PostalCode, true) {
				add(m[0], m[1], "postal_code", "«PLZ»", prioKnown)
			}
		}
	}
	for _, e := range ps.id.Emails {
		for _, m := range findInView(views[0], foldString(e, foldExpand)) {
			add(m[0], m[1], "email", "«E-Mail»", prioKnown)
		}
	}
	for _, ph := range ps.id.Phones {
		for _, want := range phoneDigitVariants(ph) {
			for _, m := range findDigitsIn(runs, want, false) {
				add(m[0], m[1], "phone", "«Telefon»", prioKnown)
			}
		}
	}

	// 2. labelled patterns
	for _, m := range reKVNRLabel.FindAllStringSubmatchIndex(text, -1) {
		add(m[2], m[3], "kvnr", "«KVNR»", prioLabeled)
	}
	for _, m := range reCaseNumber.FindAllStringSubmatchIndex(text, -1) {
		add(m[2], m[3], "case_number", "«Fallnummer»", prioLabeled)
	}
	for _, m := range reBirthLabel.FindAllStringSubmatchIndex(text, -1) {
		tag := "«Geburtsdatum»"
		if birthTag != "" {
			tag = birthTag
		}
		add(m[2], m[3], "birth_date", tag, prioLabeled)
	}
	for _, m := range rePhoneLabel.FindAllStringSubmatchIndex(text, -1) {
		if n := len(digitsOnly(text[m[2]:m[3]])); n >= 6 && n <= 15 {
			add(m[2], m[3], "phone", "«Telefon»", prioLabeled)
		}
	}
	for i, re := range []*regexp.Regexp{reTitled, reDoctor, reRelational, reSignoff} {
		for _, m := range re.FindAllStringSubmatchIndex(text, -1) {
			name, ok := trimName(strings.TrimSpace(text[m[2]:m[3]]), i == 2)
			if ok && !eponym(text, m[2], m[2]+len(name)) && plausibleName(strings.Fields(name)[0]) {
				add(m[2], m[2]+len(name), "name", ps.nameTag(name), prioLabeled)
			}
		}
	}
	for _, m := range reOtherID.FindAllStringSubmatchIndex(text, -1) {
		for g := 1; g <= 3; g++ {
			if m[2*g] >= 0 {
				add(m[2*g], m[2*g+1], "other", "«Kennnummer»", prioLabeled)
			}
		}
	}
	for _, m := range reFallLabel.FindAllStringSubmatchIndex(text, -1) {
		if n := len(digitsOnly(text[m[2]:m[3]])); n >= 6 {
			add(m[2], m[3], "case_number", "«Fallnummer»", prioLabeled)
		}
	}
	for _, sd := range spokenDates(views[0]) {
		if before := prevWords(text, sd.start, 2); len(before) > 0 && (before[0] == "geboren" || before[0] == "geb" || len(before) > 1 && before[1] == "geboren") {
			tag := "«Geburtsdatum»"
			if birthTag != "" {
				tag = birthTag
			}
			add(sd.start, sd.end, "birth_date", tag, prioLabeled)
		}
	}
	if dictation {
		for _, m := range reLowerTitle.FindAllStringIndex(text, -1) {
			words := reWord.FindAllStringIndex(text[m[1]:], 2)
			if len(words) == 0 || strings.TrimSpace(text[m[1]:m[1]+words[0][0]]) != "" {
				continue
			}
			s1, e1 := m[1]+words[0][0], m[1]+words[0][1]
			w1 := text[s1:e1]
			if notAName[w1] || commonWords[w1] && !givenNames[capitalise(w1)] || !plausibleName(w1) {
				continue
			}
			end := e1
			if len(words) == 2 && strings.TrimSpace(text[e1:m[1]+words[1][0]]) == "" && givenNames[capitalise(w1)] {
				if w2 := text[m[1]+words[1][0] : m[1]+words[1][1]]; !notAName[w2] && plausibleName(w2) {
					end = m[1] + words[1][1]
				}
			}
			add(s1, end, "name", ps.nameTag(text[s1:end]), prioLabeled)
		}
		for _, m := range reWord.FindAllStringIndex(text, -1) {
			w := text[m[0]:m[1]]
			if givenNames[capitalise(w)] && !commonWords[w] && !notAName[w] && len(w) >= 4 {
				add(m[0], m[1], "name", ps.nameTag(w), prioPattern)
			}
		}
		for _, r := range runs {
			if len(r.digits) >= 7 && r.spokenShare() > 0.5 {
				add(r.spans[0][0], r.spans[len(r.spans)-1][1], "phone", "«Telefon»", prioPattern)
			}
		}
	}
	for _, m := range reGivenFamily.FindAllStringSubmatchIndex(text, -1) {
		given, fam := text[m[2]:m[3]], text[m[4]:m[5]]
		if givenNames[given] && !notAFamily[fam] && !givenNames[fam] && !commonWords[strings.ToLower(fam)] && !eponym(text, m[0], m[1]) {
			add(m[2], m[5], "name", ps.nameTag(given+" "+fam), prioPattern)
		}
	}

	// 3. unlabelled patterns
	for _, m := range reKVNR.FindAllStringIndex(text, -1) {
		if ValidKVNR(text[m[0]:m[1]]) {
			add(m[0], m[1], "kvnr", "«KVNR»", prioPattern)
		}
	}
	for _, m := range reIBAN.FindAllStringIndex(text, -1) {
		if ValidIBAN(text[m[0]:m[1]]) {
			add(m[0], m[1], "iban", "«IBAN»", prioPattern)
		}
	}
	for _, m := range reEmail.FindAllStringIndex(text, -1) {
		add(m[0], m[1], "email", "«E-Mail»", prioPattern)
	}
	for _, m := range reCaseYear.FindAllStringIndex(text, -1) {
		add(m[0], m[1], "case_number", "«Fallnummer»", prioPattern)
	}
	for _, m := range rePrefixStreet.FindAllStringSubmatchIndex(text, -1) {
		if !notStreet[text[m[2]:m[3]]] {
			add(m[0], m[1], "address", "«Adresse»", prioPattern)
		}
	}
	for _, re := range []*regexp.Regexp{rePhoneIntl, rePhoneLocal} {
		for _, m := range re.FindAllStringIndex(text, -1) {
			if n := len(digitsOnly(text[m[0]:m[1]])); n >= 7 && n <= 15 {
				add(m[0], m[1], "phone", "«Telefon»", prioPattern)
			}
		}
	}
	for _, m := range reStreet.FindAllStringIndex(text, -1) {
		add(m[0], m[1], "address", "«Adresse»", prioPattern)
	}
	for _, m := range rePostalCity.FindAllStringSubmatchIndex(text, -1) {
		if !notCity[strings.Fields(text[m[3]:m[1]])[0]] {
			add(m[2], m[3], "postal_code", "«PLZ»", prioPattern)
		}
	}

	return render(text, resolve(spans))
}

// resolve keeps a non-overlapping set: higher priority wins, then the longer span, then the earlier one.
func resolve(spans []span) []span {
	sort.SliceStable(spans, func(i, j int) bool {
		a, b := spans[i], spans[j]
		if a.priority != b.priority {
			return a.priority > b.priority
		}
		if a.end-a.start != b.end-b.start {
			return a.end-a.start > b.end-b.start
		}
		return a.start < b.start
	})
	var kept []span
	for _, s := range spans {
		ok := true
		for _, k := range kept {
			if s.start < k.end && s.end > k.start {
				ok = false
				break
			}
		}
		if ok {
			kept = append(kept, s)
		}
	}
	sort.Slice(kept, func(i, j int) bool { return kept[i].start < kept[j].start })
	return kept
}

func render(text string, spans []span) Result {
	var b strings.Builder
	var reps []Replacement
	prev, inRunes, outRunes := 0, 0, 0
	for _, s := range spans {
		seg := text[prev:s.start]
		b.WriteString(seg)
		n := utf8.RuneCountInString(seg)
		inRunes += n
		outRunes += n
		orig := utf8.RuneCountInString(text[s.start:s.end])
		tagLen := utf8.RuneCountInString(s.tag)
		reps = append(reps, Replacement{inRunes, inRunes + orig, outRunes, outRunes + tagLen, s.kind, s.tag})
		b.WriteString(s.tag)
		inRunes += orig
		outRunes += tagLen
		prev = s.end
	}
	b.WriteString(text[prev:])
	return Result{Text: b.String(), Replacements: reps}
}

func (ps *Pseudonymizer) birthTag(bd time.Time) string {
	age := Age(bd, ps.asOf)
	if age >= ps.ageCap {
		return fmt.Sprintf("«Geburtsdatum, %d+ J.»", ps.ageCap)
	}
	return fmt.Sprintf("«Geburtsdatum, %d J.»", age)
}

// nameTag gives a name the record lists its person's tag, and any other name a stable keyed-hash tag.
func (ps *Pseudonymizer) nameTag(name string) string {
	fn := Fold(name)
	for _, pt := range ps.persons {
		for _, part := range []string{pt.p.Family, pt.p.Given + " " + pt.p.Family} {
			if part != "" && (Fold(part) == fn || strings.HasSuffix(fn, " "+Fold(pt.p.Family))) {
				return pt.tag
			}
		}
	}
	words := strings.Fields(strings.ReplaceAll(name, ".", " "))
	last := Fold(words[len(words)-1])
	mac := hmac.New(sha256.New, ps.key)
	mac.Write([]byte(ps.id.Tenant + "|" + last))
	return "«Person-" + hex.EncodeToString(mac.Sum(nil))[:4] + "»"
}

type variant struct {
	text string
	skip int // bytes of a leading title that is matched for context but not replaced
}

// commonWords are surnames and given names that are also ordinary lower-case German words. Speech-recognition
// transcripts are all lower case, so "frau lang" must be caught while "zwei wochen lang" must not: for these names the
// lower-case form is only matched after a title.
var commonWords = map[string]bool{}

func init() {
	for _, w := range strings.Fields(`lang klein koch braun schwarz fuchs vogel sommer engel kraus hahn jung alt kurz groß
		gross weiß weiss frank könig kaiser richter schneider bauer fischer winter herbst wolf stein berg busch hase haase
		roth rot kühn frei froh ernst rosa rose may mai licht fröhlich lustig heil ganz gut hell dunkel neu link
		recht rechts böse schön still voss fromm hart weise kluge klug kühne kohl wein brand graf herr frau mann
		bach baum feld wald kopf fink falk adler storch strauß strauss sauer süß bitter sturm blum bloom heide grün gruen`) {
		commonWords[w] = true
	}
}

func dateVariants(d time.Time) []string {
	dd, mm, yyyy := d.Day(), int(d.Month()), d.Year()
	yy := yyyy % 100
	return []string{
		fmt.Sprintf("%02d.%02d.%04d", dd, mm, yyyy), fmt.Sprintf("%d.%d.%04d", dd, mm, yyyy),
		fmt.Sprintf("%02d.%02d.%02d", dd, mm, yy), fmt.Sprintf("%d.%d.%02d", dd, mm, yy),
		fmt.Sprintf("%04d-%02d-%02d", yyyy, mm, dd),
		fmt.Sprintf("%d. %s %d", dd, germanMonths[mm-1], yyyy), fmt.Sprintf("%02d. %s %d", dd, germanMonths[mm-1], yyyy),
	}
}

func streetVariants(street string) []string {
	street = strings.TrimSpace(street)
	if street == "" {
		return nil
	}
	out := []string{street}
	low := strings.ToLower(street)
	for _, pair := range [][2]string{{"straße", "str."}, {"straße", "strasse"}, {"str.", "straße"}} {
		if i := strings.Index(low, pair[0]); i >= 0 {
			out = append(out, street[:i]+pair[1]+street[i+len(pair[0]):])
		}
	}
	return out
}

// findWord finds whole-word occurrences of lit. caseSensitive=false matches any casing.
func findWord(text, lit string, caseSensitive bool) [][2]int {
	if lit == "" {
		return nil
	}
	pat := regexp.QuoteMeta(lit)
	if !caseSensitive {
		pat = "(?i)" + pat
	}
	re := regexp.MustCompile(pat)
	var out [][2]int
	for _, m := range re.FindAllStringIndex(text, -1) {
		if boundary(text, m[0], m[1]) {
			out = append(out, [2]int{m[0], m[1]})
		}
	}
	return out
}

func boundary(text string, start, end int) bool {
	if start > 0 {
		r, _ := utf8.DecodeLastRuneInString(text[:start])
		if isWordRune(r) {
			return false
		}
	}
	if end < len(text) {
		r, _ := utf8.DecodeRuneInString(text[end:])
		if isWordRune(r) {
			return false
		}
	}
	return true
}

var reDigitRun = regexp.MustCompile(`\+?[0-9][0-9 ()/-]*[0-9]`)

// findDigits finds runs of digits (with phone separators) whose digits equal want, or end with it after a country code.
func findDigits(text, want string) [][2]int {
	if len(want) < 6 {
		return nil
	}
	alt := want
	if strings.HasPrefix(want, "0") {
		alt = "49" + want[1:]
	}
	var out [][2]int
	for _, m := range reDigitRun.FindAllStringIndex(text, -1) {
		d := digitsOnly(text[m[0]:m[1]])
		if d == want || d == alt || d == "0049"+want[1:] {
			out = append(out, [2]int{m[0], m[1]})
		}
	}
	return out
}

// Leaks reports which kinds of the case's known identifiers still appear in text (never the values themselves).
//
// It is deliberately not the replacer run again: a check that shares the replacer's blind spots cannot catch its
// misses. It searches the normalised views without the context rules for distinctive names (at a word start, also as
// part of a longer word), every digit run for the known numbers as substrings, and dates in every spelling, so a
// document the replacer did not clean completely is refused rather than sent.
func (ps *Pseudonymizer) Leaks(text string) []string {
	found := map[string]bool{}
	views := []view{normView(text, foldExpand), normView(text, foldDrop)}
	runs := digitRuns(text)
	for _, pt := range ps.persons {
		for _, nv := range variantsOf(pt.p) {
			for _, m := range findPrefixInView(views[nv.mode], nv.folded) {
				if nv.common && !hasPersonContext(text, m[0], m[1], pt.p) || eponym(text, m[0], m[1]) {
					continue
				}
				found["name"] = true
			}
		}
	}
	if bd, err := time.Parse("2006-01-02", ps.id.BirthDate); err == nil {
		for _, v := range dateVariants(bd) {
			if len(findInView(views[0], foldString(v, foldExpand))) > 0 {
				found["birth_date"] = true
			}
		}
		for _, sd := range spokenDates(views[0]) {
			if sameBirthDate(sd, bd) {
				found["birth_date"] = true
			}
		}
	}
	if k := strings.ToUpper(ps.id.KVNR); len(k) == 10 && len(findDigitsIn(runs, k[1:], false)) > 0 {
		found["kvnr"] = true
	}
	for _, c := range ps.id.CaseNumbers {
		for _, want := range caseDigitVariants(c) {
			if len(findDigitsIn(runs, want, false)) > 0 {
				found["case_number"] = true
			}
		}
	}
	for _, a := range ps.id.Addresses {
		if name := streetName(a.Street); len([]rune(name)) >= 6 && len(findInView(views[0], foldString(name, foldExpand))) > 0 {
			found["address"] = true
		}
		if a.PostalCode != "" && len(findDigitsIn(runs, a.PostalCode, true)) > 0 {
			found["postal_code"] = true
		}
	}
	for _, e := range ps.id.Emails {
		if e != "" && strings.Contains(views[0].s, foldString(e, foldExpand)) {
			found["email"] = true
		}
	}
	for _, ph := range ps.id.Phones {
		for _, want := range phoneDigitVariants(ph) {
			if len(findDigitsIn(runs, want, false)) > 0 {
				found["phone"] = true
			}
		}
	}
	var out []string
	for k := range found {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func sameBirthDate(sd spokenDate, bd time.Time) bool {
	return sd.day == bd.Day() && sd.month == int(bd.Month()) && (sd.year == bd.Year() || sd.twoDigitYear && sd.year == bd.Year()%100)
}

// acceptName decides whether a match of a listed person's name is the person.
func (ps *Pseudonymizer) acceptName(text string, start, end int, p identity.Person, nv nameVariant, dictation bool) bool {
	if eponym(text, start, end) {
		return false
	}
	if !nv.single {
		return true
	}
	if nv.common {
		return hasPersonContext(text, start, end, p)
	}
	r, _ := utf8.DecodeRuneInString(text[start:end])
	if unicode.IsLower(r) {
		return dictation || hasPersonContext(text, start, end, p)
	}
	return true
}

// kvnrStart extends a match of the KVNR's digits back over its letter ("E762019724", "k neun vier ...").
func kvnrStart(text string, start int, letter byte) int {
	i := start
	for i > 0 && (text[i-1] == ' ' || text[i-1] == '-') && start-i < 2 {
		i--
	}
	if i > 0 && (text[i-1]|0x20) == (letter|0x20) {
		if i == 1 || !isWordRune(rune(text[i-2])) {
			return i - 1
		}
	}
	return start
}

// caseDigitVariants: "2026-128834" is also written "26/128834".
func caseDigitVariants(c string) []string {
	d := digitsOnly(c)
	if len(d) < 6 {
		return nil
	}
	out := []string{d}
	if len(d) >= 10 && (strings.HasPrefix(d, "19") || strings.HasPrefix(d, "20")) {
		out = append(out, d[2:])
	}
	return out
}

// phoneDigitVariants: a German number with and without the country code.
func phoneDigitVariants(ph string) []string {
	d := digitsOnly(ph)
	if len(d) < 6 {
		return nil
	}
	out := []string{d}
	if strings.HasPrefix(d, "0") && !strings.HasPrefix(d, "00") {
		out = append(out, "49"+d[1:])
	}
	if strings.HasPrefix(d, "49") {
		out = append(out, "0"+d[2:])
	}
	return out
}

var (
	reHouseNumber = regexp.MustCompile(`\s*\d+\s?[a-zA-Z]?\b`)
	reHouseDigits = regexp.MustCompile(`^\s+\d{1,4}\s?[a-zA-Z]?\b`)
	reHouseWord   = regexp.MustCompile(`^\s+([a-zäöüß]+)`)
)

// streetName is the street without its house number.
func streetName(street string) string {
	return strings.TrimSpace(reHouseNumber.ReplaceAllString(strings.TrimSpace(street), ""))
}

// houseNumberEnd extends a street name over a following house number in digits or words ("hofmarkstraße elf").
func houseNumberEnd(text string, end int) int {
	rest := text[end:]
	if m := reHouseDigits.FindStringIndex(rest); m != nil {
		return end + m[1]
	}
	if m := reHouseWord.FindStringSubmatchIndex(rest); m != nil {
		if n, ok := parseNumberWord(foldString(rest[m[2]:m[3]], foldExpand)); ok && n > 0 && n < 1000 {
			return end + m[1]
		}
	}
	return end
}

// words that follow "Am"/"Im" without being a street ("Im Zimmer 12", "Am Montag 14")
var notStreet = map[string]bool{"Zimmer": true, "Bett": true, "Raum": true, "Saal": true, "Bereich": true, "Haus": true,
	"Gebäude": true, "Flur": true, "Stock": true, "Montag": true, "Dienstag": true, "Mittwoch": true, "Donnerstag": true,
	"Freitag": true, "Samstag": true, "Sonntag": true, "Januar": true, "Februar": true, "März": true, "April": true,
	"Mai": true, "Juni": true, "Juli": true, "August": true, "September": true, "Oktober": true, "November": true,
	"Dezember": true, "Jahr": true, "Alter": true, "Schnitt": true, "Verlauf": true, "Rahmen": true, "Durchschnitt": true}

var reTag = regexp.MustCompile(`«([^»]{1,40})»`)

// Reidentify replaces the tags of identifiers the record lists with their values, for display to the clinician.
// Tags of persons the record does not list stay tags: the gateway does not keep a reverse map.
func (ps *Pseudonymizer) Reidentify(text string) string {
	byTag := map[string]string{}
	for _, pt := range ps.persons {
		byTag[pt.tag] = strings.TrimSpace(pt.p.Given + " " + pt.p.Family)
	}
	if ps.id.KVNR != "" {
		byTag["«KVNR»"] = ps.id.KVNR
	}
	if len(ps.id.Phones) == 1 {
		byTag["«Telefon»"] = ps.id.Phones[0]
	}
	if len(ps.id.CaseNumbers) == 1 {
		byTag["«Fallnummer»"] = ps.id.CaseNumbers[0]
	}
	if len(ps.id.Addresses) == 1 {
		byTag["«Adresse»"] = ps.id.Addresses[0].Street
		byTag["«PLZ»"] = ps.id.Addresses[0].PostalCode
	}
	if len(ps.id.Emails) == 1 {
		byTag["«E-Mail»"] = ps.id.Emails[0]
	}
	bd, bdErr := time.Parse("2006-01-02", ps.id.BirthDate)
	return reTag.ReplaceAllStringFunc(text, func(t string) string {
		if v, ok := byTag[t]; ok && v != "" {
			return v
		}
		if strings.HasPrefix(t, "«Geburtsdatum") && bdErr == nil {
			return bd.Format("02.01.2006")
		}
		return t
	})
}

// Age in completed years on asOf.
func Age(birth, asOf time.Time) int {
	age := asOf.Year() - birth.Year()
	if asOf.Month() < birth.Month() || (asOf.Month() == birth.Month() && asOf.Day() < birth.Day()) {
		age--
	}
	return age
}

//go:embed given_names.txt
var givenNamesRaw string

var givenNames = func() map[string]bool {
	out := map[string]bool{}
	for _, line := range strings.Split(givenNamesRaw, "\n") {
		if strings.HasPrefix(line, "#") {
			continue
		}
		for _, w := range strings.Fields(line) {
			out[w] = true
		}
	}
	return out
}()

// trimName keeps a captured second word only when the first is a given name ("Frau Anna Schulz" vs "Frau Schulz
// Pflegegrad"); requireGiven drops the capture entirely when it does not start with one ("Tochter Anna" vs
// "Ansprechpartner Sozialdienst").
func trimName(name string, requireGiven bool) (string, bool) {
	words := strings.Fields(name)
	if len(words) == 0 {
		return "", false
	}
	first := strings.TrimSuffix(words[0], ".")
	isGiven := givenNames[first]
	if requireGiven && !isGiven {
		return "", false
	}
	if len(words) > 1 && !isGiven && len(first) > 1 {
		return words[0], true
	}
	return name, true
}

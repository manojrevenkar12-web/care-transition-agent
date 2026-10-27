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
	reExistingTag = regexp.MustCompile(`«[^»]{1,40}»`)
	nameWord      = `[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?`
	nameRe        = `(?:[A-ZÄÖÜ]\.\s?)?` + nameWord + `(?:\s+(?:von|van|de|zu|von der)\s+` + nameWord + `)?`
	reTitled      = regexp.MustCompile(`(?:\b(?:Herrn?|Frau|Hr\.|Fr\.)\s+(?:(?:Dr\.|Prof\.)\s+)?(?:med\.\s+)?)(` + nameRe + `(?:\s+` + nameWord + `)?)`)
	reDoctor      = regexp.MustCompile(`(?:\b(?:Dr|Prof)\.(?:\s?(?:med|rer\.\s?nat|phil|h\.\s?c)\.)?\s+)(` + nameRe + `(?:\s+` + nameWord + `)?)`)
	reRelational  = regexp.MustCompile(`\b(?:Sohn|Tochter|Ehemann|Ehefrau|Ehepartner(?:in)?|Lebensgefährt(?:e|in)|Enkel(?:in)?|Bruder|Schwester|Nichte|Neffe|Schwiegersohn|Schwiegertochter|Betreuer(?:in)?|Bevollmächtigte[rn]?|Nachbar(?:in)?|Ansprechpartner(?:in)?)\s*[:,]?\s+(` + nameWord + `(?:\s+` + nameWord + `)?)`)
	reKVNR        = regexp.MustCompile(`\b[A-Z][0-9]{9}\b`)
	reKVNRLabel   = regexp.MustCompile(`(?i)(?:KVNR|Versichertennr\.?|Versichertennummer|Vers\.-Nr\.?)\s*:?\s*([A-Z][0-9]{9})`)
	reIBAN        = regexp.MustCompile(`\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,4})?\b`)
	reEmail       = regexp.MustCompile(`[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`)
	rePhoneLabel  = regexp.MustCompile(`(?i)(?:tel\.?|telefon(?:nummer)?|mobil|handy|fon|rückruf(?:nummer)?)\s*(?:nr\.?)?\s*:?\s*(\+?[0-9][0-9 ()/-]{5,}[0-9])`)
	rePhoneIntl   = regexp.MustCompile(`\+49[0-9 ()/-]{7,}[0-9]`)
	rePhoneLocal  = regexp.MustCompile(`\b0[1-9][0-9]{1,4}[ /-][0-9]{3,}(?:[ -][0-9]+)*\b`)
	reStreet      = regexp.MustCompile(`\b[A-ZÄÖÜ][a-zäöüß]+(?:[ -][A-ZÄÖÜ][a-zäöüß]+)*(?:straße|strasse|str\.|weg|allee|platz|ring|gasse|damm|ufer|chaussee)\s+\d{1,4}\s?[a-zA-Z]?\b`)
	rePostalCity  = regexp.MustCompile(`\b(\d{5})\s+[A-ZÄÖÜ][a-zäöüß]+`)
	reCaseNumber  = regexp.MustCompile(`(?i)(?:Fall(?:nummer|-?nr\.?)|Aufnahme(?:nummer|-?nr\.?)|Patienten-?(?:ID|nr\.?)|Pat\.-?(?:ID|Nr\.?))\s*:?\s*([A-Z0-9][A-Z0-9-]{4,})`)
	reBirthLabel  = regexp.MustCompile(`(?i)(?:geb\.?(?:\s*am)?|geboren(?:\s*am)?|Geburtsdatum|\*)\s*:?\s*(\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4})`)
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

	// 1. known identifiers
	for _, pt := range ps.persons {
		for _, v := range nameVariants(pt.p) {
			for _, m := range findWord(text, v.text, true) {
				add(m[0]+v.skip, m[1], "name", pt.tag, prioKnown)
			}
		}
	}
	birthTag := ""
	if bd, err := time.Parse("2006-01-02", ps.id.BirthDate); err == nil {
		birthTag = ps.birthTag(bd)
		for _, v := range dateVariants(bd) {
			for _, m := range findWord(text, v, false) {
				add(m[0], m[1], "birth_date", birthTag, prioKnown)
			}
		}
	}
	if ps.id.KVNR != "" {
		for _, m := range findWord(text, ps.id.KVNR, false) {
			add(m[0], m[1], "kvnr", "«KVNR»", prioKnown)
		}
	}
	for _, c := range ps.id.CaseNumbers {
		for _, m := range findWord(text, c, false) {
			add(m[0], m[1], "case_number", "«Fallnummer»", prioKnown)
		}
	}
	for _, a := range ps.id.Addresses {
		for _, v := range streetVariants(a.Street) {
			for _, m := range findWord(text, v, false) {
				add(m[0], m[1], "address", "«Adresse»", prioKnown)
			}
		}
		if a.PostalCode != "" {
			for _, m := range findWord(text, a.PostalCode, true) {
				add(m[0], m[1], "postal_code", "«PLZ»", prioKnown)
			}
		}
	}
	for _, e := range ps.id.Emails {
		for _, m := range findWord(text, e, false) {
			add(m[0], m[1], "email", "«E-Mail»", prioKnown)
		}
	}
	for _, ph := range ps.id.Phones {
		for _, m := range findDigits(text, digitsOnly(ph)) {
			add(m[0], m[1], "phone", "«Telefon»", prioKnown)
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
	for i, re := range []*regexp.Regexp{reTitled, reDoctor, reRelational} {
		for _, m := range re.FindAllStringSubmatchIndex(text, -1) {
			name, ok := trimName(strings.TrimSpace(text[m[2]:m[3]]), i == 2)
			if ok {
				add(m[2], m[2]+len(name), "name", ps.nameTag(name), prioLabeled)
			}
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

var lowerTitles = []string{"frau ", "herr ", "herrn ", "patientin ", "patient ", "pat ", "pat. "}

func nameVariants(p identity.Person) []variant {
	g, f := strings.TrimSpace(p.Given), strings.TrimSpace(p.Family)
	var full, single []string
	if g != "" && f != "" {
		full = append(full, g+" "+f, f+", "+g, g[:1]+". "+f, g[:1]+"."+f)
	}
	if f != "" {
		single = append(single, f)
		if strings.Contains(f, "-") {
			single = append(single, strings.Split(f, "-")...)
		}
	}
	if len([]rune(g)) >= 3 {
		single = append(single, strings.Fields(g)...)
	}
	var out []variant
	for _, v := range full {
		out = append(out, variant{v, 0}, variant{strings.ToUpper(v), 0}, variant{strings.ToLower(v), 0}, variant{v + "s", 0})
	}
	for _, v := range single {
		out = append(out, variant{v, 0}, variant{strings.ToUpper(v), 0}, variant{v + "s", 0})
		low := strings.ToLower(v)
		if !commonWords[low] {
			out = append(out, variant{low, 0})
			continue
		}
		for _, t := range lowerTitles {
			out = append(out, variant{t + low, len(t)})
		}
	}
	return out
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
func (ps *Pseudonymizer) Leaks(text string) []string {
	found := map[string]bool{}
	for _, pt := range ps.persons {
		for _, part := range namePartsForLeak(pt.p) {
			if len(findWord(text, part, true)) > 0 {
				found["name"] = true
			}
		}
	}
	if bd, err := time.Parse("2006-01-02", ps.id.BirthDate); err == nil {
		for _, v := range dateVariants(bd) {
			if len(findWord(text, v, false)) > 0 {
				found["birth_date"] = true
			}
		}
	}
	if ps.id.KVNR != "" && strings.Contains(strings.ToUpper(text), strings.ToUpper(ps.id.KVNR)) {
		found["kvnr"] = true
	}
	for _, c := range ps.id.CaseNumbers {
		if c != "" && len(findWord(text, c, false)) > 0 {
			found["case_number"] = true
		}
	}
	for _, a := range ps.id.Addresses {
		for _, v := range streetVariants(a.Street) {
			if len(findWord(text, v, false)) > 0 {
				found["address"] = true
			}
		}
		if a.PostalCode != "" && len(findWord(text, a.PostalCode, true)) > 0 {
			found["postal_code"] = true
		}
	}
	for _, e := range ps.id.Emails {
		if e != "" && strings.Contains(strings.ToLower(text), strings.ToLower(e)) {
			found["email"] = true
		}
	}
	for _, ph := range ps.id.Phones {
		if len(findDigits(text, digitsOnly(ph))) > 0 {
			found["phone"] = true
		}
	}
	var out []string
	for k := range found {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func namePartsForLeak(p identity.Person) []string {
	var out []string
	for _, s := range append(strings.Split(p.Family, "-"), strings.Fields(p.Given)...) {
		s = strings.TrimSpace(s)
		if len([]rune(s)) < 3 {
			continue
		}
		out = append(out, s, strings.ToUpper(s))
		if low := strings.ToLower(s); !commonWords[low] {
			out = append(out, low)
		} else {
			for _, t := range lowerTitles {
				out = append(out, t+low)
			}
		}
	}
	return out
}

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

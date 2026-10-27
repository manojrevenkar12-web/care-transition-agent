package pseudo

import (
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/identity"
)

var asOf = time.Date(2026, 10, 27, 0, 0, 0, 0, time.UTC)

func patient() identity.Identity {
	return identity.Identity{
		Tenant: "klinikum-nord", Case: "c1",
		Persons: []identity.Person{
			{Role: "patient", Given: "Gertrud", Family: "Hoffmann-Lange"},
			{Role: "relative", Given: "Sabine", Family: "Krüger"},
			{Role: "physician", Given: "Jonas", Family: "Weber"},
		},
		BirthDate:   "1941-03-02",
		KVNR:        "A123456780",
		CaseNumbers: []string{"2026-118734"},
		Addresses:   []identity.Address{{Street: "Lindenstraße 14", PostalCode: "13583", City: "Berlin"}},
		Phones:      []string{"030 3312 4471"},
		Emails:      []string{"s.krueger@example.org"},
		AsOf:        "2026-10-27",
	}
}

func run(t *testing.T, text string) (Result, *Pseudonymizer) {
	t.Helper()
	ps := New(patient(), []byte("k"), 90, asOf)
	return ps.Pseudonymize(text), ps
}

func TestKVNRCheckDigit(t *testing.T) {
	for _, ok := range []string{"A123456780"} {
		if !ValidKVNR(ok) {
			t.Errorf("%s should be valid", ok)
		}
	}
	for _, bad := range []string{"A123456781", "a123456780", "A12345678", "1123456780", "AB23456780"} {
		if ValidKVNR(bad) {
			t.Errorf("%s should be invalid", bad)
		}
	}
}

func TestIBANChecksum(t *testing.T) {
	if !ValidIBAN("DE89 3704 0044 0532 0130 00") || !ValidIBAN("DE89370400440532013000") {
		t.Fatal("the standard example IBAN is valid")
	}
	if ValidIBAN("DE89370400440532013001") {
		t.Fatal("a changed digit breaks the checksum")
	}
}

func TestKnownIdentifiersAreReplacedWithTypedTags(t *testing.T) {
	text := "Frau Gertrud Hoffmann-Lange, geb. 02.03.1941, KVNR A123456780, wohnhaft Lindenstr. 14, 13583 Berlin. " +
		"Tochter Sabine Krüger (Tel. 030 3312 4471, s.krueger@example.org) ist bevollmächtigt. Fall-Nr. 2026-118734. " +
		"Entlassung durch Dr. Weber. HOFFMANN-LANGE wurde informiert, Frau Hoffmann-Langes Rollator ist vorhanden."
	r, ps := run(t, text)
	for _, leak := range []string{"Gertrud", "Hoffmann", "Lange", "1941", "A123456780", "Lindenstr", "13583", "Krüger", "3312", "krueger", "118734", "Weber"} {
		if strings.Contains(r.Text, leak) {
			t.Errorf("%q survived: %s", leak, r.Text)
		}
	}
	for _, tag := range []string{"«Patient»", "«Angehörige-1»", "«Arzt-1»", "«KVNR»", "«Adresse»", "«PLZ»", "«Telefon»", "«E-Mail»", "«Fallnummer»", "«Geburtsdatum, 85 J.»"} {
		if !strings.Contains(r.Text, tag) {
			t.Errorf("missing %s in %s", tag, r.Text)
		}
	}
	// what the model needs survives: the title (gender), the city, the clinical content
	for _, keep := range []string{"Frau «Patient»", "Berlin", "Rollator", "bevollmächtigt", "Entlassung"} {
		if !strings.Contains(r.Text, keep) {
			t.Errorf("lost %q: %s", keep, r.Text)
		}
	}
	if leaks := ps.Leaks(r.Text); len(leaks) != 0 {
		t.Fatalf("leak check finds %v in its own output", leaks)
	}
}

func TestOffsetsAreCodePointsAndPointAtTheReplacedText(t *testing.T) {
	text := "Ärztin: Dr. Weber. Patientin Frau Hoffmann-Lange (geb. 2.3.41) – Tochter Sabine Krüger."
	r, _ := run(t, text)
	in, out := []rune(text), []rune(r.Text)
	if len(r.Replacements) < 4 {
		t.Fatalf("expected replacements, got %v", r.Replacements)
	}
	for _, rep := range r.Replacements {
		if string(out[rep.OutStart:rep.OutEnd]) != rep.Tag {
			t.Errorf("out span %d:%d is %q, want %q", rep.OutStart, rep.OutEnd, string(out[rep.OutStart:rep.OutEnd]), rep.Tag)
		}
		orig := string(in[rep.Start:rep.End])
		if orig == "" || strings.Contains(orig, "«") {
			t.Errorf("bad original span %q", orig)
		}
	}
	if !utf8.ValidString(r.Text) {
		t.Fatal("output must stay valid UTF-8")
	}
}

func TestUnlistedPeopleAndPatternsAreCaught(t *testing.T) {
	text := "Nachbarin Frau Yilmaz kümmert sich um die Katze. Sohn Peter Neumann, Mobil 0171 2345678. " +
		"Rückfragen an Herrn Kowalski. IBAN DE89 3704 0044 0532 0130 00. Versichertennr. B987654321. " +
		"Neue Anschrift: Am Weidengrund 7? Nein: Birkenweg 3a, 10115 Berlin. +49 30 555 12 34."
	r, _ := run(t, text)
	for _, leak := range []string{"Yilmaz", "Neumann", "Peter", "2345678", "Kowalski", "DE89", "B987654321", "Birkenweg", "10115", "555 12 34"} {
		if strings.Contains(r.Text, leak) {
			t.Errorf("%q survived: %s", leak, r.Text)
		}
	}
	if !strings.Contains(r.Text, "Katze") || !strings.Contains(r.Text, "Sohn «Person-") {
		t.Errorf("unexpected rewrite: %s", r.Text)
	}
}

func TestSameUnlistedNameGetsTheSameTagEverywhere(t *testing.T) {
	ps := New(patient(), []byte("k"), 90, asOf)
	a := ps.Pseudonymize("Herr Kowalski ruft an.").Text
	b := ps.Pseudonymize("Rückruf: Frau Kowalski").Text
	ta, tb := reTag.FindString(a), reTag.FindString(b)
	if ta == "" || ta != tb {
		t.Fatalf("tags differ: %q vs %q", ta, tb)
	}
	other := New(identity.Identity{Tenant: "st-elisabeth", Case: "x"}, []byte("k"), 90, asOf).Pseudonymize("Herr Kowalski").Text
	if reTag.FindString(other) == ta {
		t.Fatal("another tenant must not get the same tag for the same name")
	}
}

func TestClinicalTextIsNotOverRedacted(t *testing.T) {
	text := "Pflegegrad 3 beantragt am 12.10.2026. Mobilisation mit Rollator, 2 Wochen lang. Heparin 20000 Einheiten s.c. " +
		"Herr Hoffmann-Lange Pflegegrad 3. Sauerstoff 2 l/min. Labor: CRP 12,4 mg/l, Hb 11,2 g/dl. MRSA-Abstrich negativ. " +
		"Station 4B, Zimmer 12. Ansprechpartner Sozialdienst: Durchwahl intern. Schwester Pflegedienstleitung informiert."
	r, _ := run(t, text)
	for _, keep := range []string{"Pflegegrad 3 beantragt", "12.10.2026", "2 Wochen lang", "20000 Einheiten", "«Patient» Pflegegrad 3", "2 l/min", "CRP 12,4 mg/l", "MRSA-Abstrich negativ", "Station 4B", "Ansprechpartner Sozialdienst", "Schwester Pflegedienstleitung"} {
		if !strings.Contains(r.Text, keep) {
			t.Errorf("over-redacted %q: %s", keep, r.Text)
		}
	}
}

func TestIdempotentOnTaggedText(t *testing.T) {
	r1, ps := run(t, "Frau Hoffmann-Lange, Tel. 030 3312 4471, Tochter Sabine Krüger")
	r2 := ps.Pseudonymize(r1.Text)
	if r2.Text != r1.Text || len(r2.Replacements) != 0 {
		t.Fatalf("second pass changed the text: %q -> %q", r1.Text, r2.Text)
	}
}

func TestLeaksNamesKindsNotValues(t *testing.T) {
	_, ps := run(t, "")
	leaks := ps.Leaks("Patientin Gertrud HOFFMANN-LANGE, KVNR A123456780, Tel 0303312 4471, geb. 2. März 1941")
	want := map[string]bool{"name": true, "kvnr": true, "phone": true, "birth_date": true}
	for _, l := range leaks {
		delete(want, l)
		if strings.ContainsAny(l, "0123456789") {
			t.Fatalf("leak report must not carry values: %v", leaks)
		}
	}
	if len(want) != 0 {
		t.Fatalf("missed %v in %v", want, leaks)
	}
	// common words that happen to be part of a name are not leaks when they are not written as the name
	if l := New(identity.Identity{Persons: []identity.Person{{Role: "patient", Given: "Karl", Family: "Lang"}}}, []byte("k"), 90, asOf).Leaks("zwei Wochen lang"); len(l) != 0 {
		t.Fatalf("lower-case 'lang' is not the name Lang: %v", l)
	}
}

func TestReidentifyRestoresListedIdentifiersOnly(t *testing.T) {
	r, ps := run(t, "Frau Hoffmann-Lange (geb. 02.03.1941), Tochter Sabine Krüger, Nachbar Herr Kowalski.")
	back := ps.Reidentify(r.Text)
	for _, want := range []string{"Gertrud Hoffmann-Lange", "02.03.1941", "Sabine Krüger"} {
		if !strings.Contains(back, want) {
			t.Errorf("missing %q in %q", want, back)
		}
	}
	if strings.Contains(back, "Kowalski") || !strings.Contains(back, "«Person-") {
		t.Errorf("an unlisted person cannot be restored and stays a tag: %q", back)
	}
}

func TestVeryOldPatientsGetACappedAge(t *testing.T) {
	id := patient()
	id.BirthDate = "1931-01-05"
	r := New(id, []byte("k"), 90, asOf).Pseudonymize("geb. 05.01.1931")
	if !strings.Contains(r.Text, "«Geburtsdatum, 90+ J.»") {
		t.Fatalf("ages of 90 and over are identifying and are capped: %s", r.Text)
	}
}

func TestDictationInLowerCaseIsPseudonymised(t *testing.T) {
	id := identity.Identity{Tenant: "t", Case: "c", Persons: []identity.Person{
		{Role: "patient", Given: "Helga", Family: "Lang"}, {Role: "relative", Given: "Stefan", Family: "Böhm"}}}
	ps := New(id, []byte("k"), 90, asOf)
	r := ps.Pseudonymize("ja also übergabe frau lang äh läuft zwei wochen lang mit rollator angehörige stefan böhm informiert")
	if strings.Contains(r.Text, "frau lang") || strings.Contains(r.Text, "stefan") || strings.Contains(r.Text, "böhm") {
		t.Fatalf("lower-case names survived: %s", r.Text)
	}
	if !strings.Contains(r.Text, "zwei wochen lang mit rollator") || !strings.Contains(r.Text, "frau «Patient»") {
		t.Fatalf("over-redacted or title lost: %s", r.Text)
	}
	if l := ps.Leaks(r.Text); len(l) != 0 {
		t.Fatalf("leaks %v", l)
	}
	if l := ps.Leaks("frau lang äh"); len(l) != 1 {
		t.Fatalf("a titled lower-case common-word name is a leak: %v", l)
	}
}

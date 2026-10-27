package pseudo

import (
	"strings"
	"testing"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/identity"
)

// These cases were written for the behaviours added after held-out set v1 was studied (v1 is now a regression set).
// They use their own invented people and texts, not v1's.

func withPersons(ps ...identity.Person) *Pseudonymizer {
	id := patient()
	id.Persons = ps
	return New(id, []byte("k"), 90, asOf)
}

func TestSpellingsFromOtherSystemsAreFound(t *testing.T) {
	ps := withPersons(
		identity.Person{Role: "patient", Given: "Şükrü", Family: "Çelik"},
		identity.Person{Role: "relative", Given: "Jörg", Family: "Mößner"},
		identity.Person{Role: "physician", Given: "Irina", Family: "Sokolowa"},
	)
	for _, text := range []string{
		"Etikett: CELIK, SUKRU, Stat. 4",
		"Ansprechpartner MOESSNER, JOERG",
		"Ärztin Dr. Ирина Соколова, Kardiologie",
		"Herr Celik wurde heute mobilisiert.",
	} {
		r := ps.Pseudonymize(text)
		if len(ps.Leaks(r.Text)) > 0 || len(r.Replacements) == 0 {
			t.Errorf("%q -> %q (leaks %v)", text, r.Text, ps.Leaks(r.Text))
		}
	}
}

func TestOCRAndLineBreaksDoNotHideIdentifiers(t *testing.T) {
	_, ps := run(t, "")
	for _, text := range []string{
		"geb. O2.O3.l94l in Spandau",            // OCR: O for 0, l for 1
		"KVNR A12345678 0, Kasse AOK",           // split by a space
		"Rückruf 030 33l2 447l erbeten",         // OCR in a phone number
		"Pat. Gertrud Hoff-\nmann-Lange, Zi. 3", // hyphenated across a line break
		"Fall 26/118734 wieder aufgenommen",     // case number without the century
	} {
		r := ps.Pseudonymize(text)
		if leaks := ps.Leaks(r.Text); len(leaks) > 0 {
			t.Errorf("%q -> %q still leaks %v", text, r.Text, leaks)
		}
	}
}

func TestDictatedNumbersAndDates(t *testing.T) {
	_, ps := run(t, "")
	text := "patientin frau hoffmann-lange geboren am zweiten märz neunzehnhunderteinundvierzig " +
		"telefon der tochter null drei null drei drei eins zwei vier vier sieben eins " +
		"versichertennummer a eins zwei drei vier fünf sechs sieben acht null wohnt lindenstraße vierzehn"
	r := ps.Pseudonymize(text)
	for _, kind := range []string{"birth_date", "phone", "kvnr", "address"} {
		if !hasKind(r, kind) {
			t.Errorf("no %s replaced: %q", kind, r.Text)
		}
	}
	if leaks := ps.Leaks(r.Text); len(leaks) > 0 {
		t.Errorf("leaks %v in %q", leaks, r.Text)
	}
}

func TestNumberWords(t *testing.T) {
	for word, want := range map[string]int{
		"neunzehnhunderteinundvierzig": 1941, "einundvierzig": 41, "zwoelf": 12, "hundertdrei": 103,
		"zweitausendsechsundzwanzig": 2026, "dreissig": 30,
	} {
		if got, ok := parseNumberWord(word); !ok || got != want {
			t.Errorf("%s = %d %v, want %d", word, got, ok, want)
		}
	}
	for word, want := range map[string]int{"zweiten": 2, "ersten": 1, "siebten": 7, "einunddreissigsten": 31, "14.": 14} {
		if got, ok := parseOrdinal(word); !ok || got != want {
			t.Errorf("%s = %d, want %d", word, got, want)
		}
	}
}

func TestSurnamesThatAreWordsNeedAPersonAroundThem(t *testing.T) {
	ps := withPersons(
		identity.Person{Role: "patient", Given: "Hilde", Family: "Sonne"},
		identity.Person{Role: "relative", Given: "Rolf", Family: "Sonne"},
	)
	cases := []struct {
		text   string
		replac bool
	}{
		{"Frau Sonne klagt über Schmerzen.", true},
		{"Rolf Sonne holt sie ab.", true},
		{"Sonne, Hilde *12.4.39", true},
		{"Bitte keine direkte Sonne auf die Wunde.", false},
		{"Sohn ist Sonne-Fan, spricht viel davon.", false},
	}
	for _, c := range cases {
		r := ps.Pseudonymize(c.text)
		if got := strings.Contains(r.Text, "«"); got != c.replac {
			t.Errorf("%q -> %q (want replaced=%v)", c.text, r.Text, c.replac)
		}
	}
}

func TestEponymsAreClinicalTerms(t *testing.T) {
	ps := withPersons(identity.Person{Role: "patient", Given: "Ute", Family: "Glasgow"})
	r := ps.Pseudonymize("Frau Glasgow somnolent, Glasgow-Coma-Scale 12.")
	if !strings.Contains(r.Text, "Glasgow-Coma-Scale") || strings.Count(r.Text, "«Patient»") != 1 {
		t.Errorf("got %q", r.Text)
	}
}

func TestInitialsOfListedPeople(t *testing.T) {
	_, ps := run(t, "")
	for _, text := range []string{"Fr. H.-L. hat gut geschlafen.", "Rücksprache mit S.K. am Nachmittag."} {
		r := ps.Pseudonymize(text)
		if !strings.Contains(r.Text, "«") {
			t.Errorf("initials kept in %q", r.Text)
		}
	}
	if r := ps.Pseudonymize("N.B. Kontrolle in 2 Wochen."); strings.Contains(r.Text, "«") {
		t.Errorf("an abbreviation that is nobody's initials was replaced: %q", r.Text)
	}
}

func TestUnlistedPeopleInSignoffsAndDictation(t *testing.T) {
	_, ps := run(t, "")
	for _, text := range []string{
		"Übergabe an ND, gez. Schw. Melanie Hartwig",
		"die nachbarin frau renate pfister hat einen schlüssel und der hausarzt doktor brenner ist informiert und sie ist mobil und orientiert",
		"Reisepass Nr. C4RT71Z92, Aktenzeichen XVII 233/25",
	} {
		r := ps.Pseudonymize(text)
		for _, w := range []string{"Hartwig", "pfister", "brenner", "C4RT71Z92", "233/25"} {
			if strings.Contains(r.Text, w) {
				t.Errorf("%q kept %q", r.Text, w)
			}
		}
	}
	r := ps.Pseudonymize("die tochter hat angerufen und frau hoffmann-lange ist einverstanden und alles ist gut so weit heute")
	if strings.Contains(r.Text, "«Person") {
		t.Errorf("a function word was read as a name: %q", r.Text)
	}
}

func TestLeakCheckDoesNotShareTheReplacersBlindSpots(t *testing.T) {
	_, ps := run(t, "")
	// the replacer reads a whole word; a name glued to the next word is still the name
	if leaks := ps.Leaks("Befund an HOFFMANN-LANGEgertrud gesendet"); len(leaks) == 0 {
		t.Error("a name inside a longer token was not reported")
	}
	if leaks := ps.Leaks("Rückrufnummer 0049 30 3312 4471"); len(leaks) == 0 {
		t.Error("a phone number with a country prefix was not reported")
	}
}

func hasKind(r Result, kind string) bool {
	for _, x := range r.Replacements {
		if x.Kind == kind {
			return true
		}
	}
	return false
}

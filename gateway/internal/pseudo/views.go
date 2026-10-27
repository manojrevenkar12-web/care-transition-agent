package pseudo

import (
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// A view is a normalised copy of a text with a map back to the original, so that a match found in the view can be
// replaced in the original. Known identifiers are searched in views because clinical text spells them in many ways:
// "MUELLER" for Müller, "Nguyen" for Nguyễn, "Ольга Шмидт" for Olga Schmidt, "KRZYZAN0WSKI" or "O7.11.l94l" from
// OCR, a name hyphenated across a line break, a phone number dictated as words.
type view struct {
	s     string
	start []int // original byte offset where the rune behind view byte i starts
	end   []int // original byte offset where that rune ends
}

// span maps view bytes [i, j) back to original bytes.
func (v view) span(i, j int) (int, int) { return v.start[i], v.end[j-1] }

type foldMode int

const (
	foldExpand foldMode = iota // ä -> ae (the German convention: Müller, MUELLER, Mueller)
	foldDrop                   // ä -> a (diacritics dropped: Muller, Ozturk)
)

var diacritics = map[rune]string{}

func init() {
	for base, chars := range map[string]string{
		"a": "àáâãåāăąạảấầẩẫậắằẳẵặ", "c": "çćč", "d": "đď", "e": "èéêëēęěẹẻẽếềểễệ", "g": "ğ", "i": "ìíîïıīịỉ",
		"l": "ł", "n": "ñńň", "o": "òóôõøōőơọỏốồổỗộớờởỡợ", "r": "ř", "s": "şśšș", "t": "ťț", "u": "ùúûūůűưụủứừửữự",
		"y": "ýÿỳỵỷỹ", "z": "žźż",
	} {
		for _, r := range chars {
			diacritics[r] = base
		}
	}
}

var cyrillic = map[rune]string{
	'а': "a", 'б': "b", 'в': "w", 'г': "g", 'д': "d", 'е': "e", 'ё': "jo", 'ж': "sch", 'з': "s", 'и': "i", 'й': "j",
	'к': "k", 'л': "l", 'м': "m", 'н': "n", 'о': "o", 'п': "p", 'р': "r", 'с': "s", 'т': "t", 'у': "u", 'ф': "f",
	'х': "ch", 'ц': "z", 'ч': "tsch", 'ш': "sch", 'щ': "schtsch", 'ъ': "", 'ы': "y", 'ь': "", 'э': "e", 'ю': "ju", 'я': "ja",
}

// OCR confusions inside a token that is mostly digits, and inside a token that is mostly letters.
var ocrToDigit = map[rune]rune{'o': '0', 'O': '0', 'О': '0', 'о': '0', 'l': '1', 'I': '1', '|': '1', 'і': '1', 'б': '6', 'З': '3', 'з': '3'}
var ocrToLetter = map[rune]rune{'0': 'o', '1': 'l'}

func foldRune(r rune, mode foldMode) string {
	r = unicode.ToLower(r)
	switch r {
	case 'ä':
		if mode == foldDrop {
			return "a"
		}
		return "ae"
	case 'ö':
		if mode == foldDrop {
			return "o"
		}
		return "oe"
	case 'ü':
		if mode == foldDrop {
			return "u"
		}
		return "ue"
	case 'ß':
		return "ss"
	}
	if s, ok := diacritics[r]; ok {
		return s
	}
	if s, ok := cyrillic[r]; ok {
		return s
	}
	return string(r)
}

// foldString folds an identifier the same way the view folds text.
func foldString(s string, mode foldMode) string {
	var b strings.Builder
	for _, r := range s {
		b.WriteString(foldRune(r, mode))
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

var reToken = regexp.MustCompile(`\S+`)

// tokenClass decides how OCR confusions are read inside a whitespace token.
func tokenClass(tok string) (numeric, wordy bool) {
	digits, letters := 0, 0
	for _, r := range tok {
		switch {
		case r >= '0' && r <= '9':
			digits++
		case unicode.IsLetter(r):
			letters++
		}
	}
	numeric = digits >= 2 && digits >= letters || digits >= 1 && letters == 1 && len([]rune(tok)) <= 3 && strings.ContainsAny(tok, "OolI|")
	wordy = letters >= 3 && digits >= 1 && digits <= 2 && letters >= 3*digits
	return
}

// normView lower-cases and folds the text, reads OCR confusions in context, joins words hyphenated across a line
// break and collapses whitespace.
func normView(text string, mode foldMode) view {
	var b strings.Builder
	var starts, ends []int
	emit := func(s string, from, to int) {
		for i := 0; i < len(s); i++ {
			starts = append(starts, from)
			ends = append(ends, to)
		}
		b.WriteString(s)
	}
	numericAt := map[int]bool{}
	wordyAt := map[int]bool{}
	for _, m := range reToken.FindAllStringIndex(text, -1) {
		n, w := tokenClass(text[m[0]:m[1]])
		for i := m[0]; i < m[1]; i++ {
			numericAt[i], wordyAt[i] = n, w
		}
	}
	prevSpace := true
	for i := 0; i < len(text); {
		r, size := utf8.DecodeRuneInString(text[i:])
		// "Krzy-\nzanowski": a hyphen at a line end between letters joins the word
		if r == '-' && i > 0 {
			rest := text[i+size:]
			j := 0
			for j < len(rest) && (rest[j] == ' ' || rest[j] == '\t' || rest[j] == '\r') {
				j++
			}
			if j < len(rest) && rest[j] == '\n' {
				prev, _ := utf8.DecodeLastRuneInString(text[:i])
				k := j + 1
				for k < len(rest) && (rest[k] == ' ' || rest[k] == '\t') {
					k++
				}
				next, _ := utf8.DecodeRuneInString(rest[k:])
				if unicode.IsLetter(prev) && unicode.IsLower(next) {
					i += size + k
					continue
				}
			}
		}
		if unicode.IsSpace(r) {
			if !prevSpace {
				emit(" ", i, i+size)
			}
			prevSpace = true
			i += size
			continue
		}
		prevSpace = false
		out := ""
		if d, ok := ocrToDigit[r]; ok && numericAt[i] {
			out = string(d)
		} else if l, ok := ocrToLetter[r]; ok && wordyAt[i] {
			out = string(l)
		} else {
			out = foldRune(r, mode)
		}
		if out != "" {
			emit(out, i, i+size)
		}
		i += size
	}
	starts = append(starts, len(text))
	ends = append(ends, len(text))
	return view{b.String(), starts, ends}
}

// findInView finds whole-word occurrences of needle (already folded) in the view and returns original byte spans.
func findInView(v view, needle string) [][2]int {
	if needle == "" {
		return nil
	}
	var out [][2]int
	for from := 0; ; {
		k := strings.Index(v.s[from:], needle)
		if k < 0 {
			break
		}
		i, j := from+k, from+k+len(needle)
		if boundary(v.s, i, j) || !isWordByte(needle[0]) && boundaryRight(v.s, j) || !isWordByte(needle[len(needle)-1]) && boundaryLeft(v.s, i) {
			a, b := v.span(i, j)
			out = append(out, [2]int{a, b})
		}
		from = i + 1
	}
	return out
}

func isWordByte(c byte) bool { return c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c >= 0x80 }

func boundaryLeft(s string, i int) bool {
	if i == 0 {
		return true
	}
	r, _ := utf8.DecodeLastRuneInString(s[:i])
	return !isWordRune(r)
}

func boundaryRight(s string, j int) bool {
	if j >= len(s) {
		return true
	}
	r, _ := utf8.DecodeRuneInString(s[j:])
	return !isWordRune(r)
}

// findPrefixInView finds occurrences that start a word, also inside a longer word ("Krzyzanowskis", a name glued to
// the next word by OCR). The leak check uses it; the replacer uses whole words.
func findPrefixInView(v view, needle string) [][2]int {
	if len(needle) < 4 {
		return findInView(v, needle)
	}
	var out [][2]int
	for from := 0; ; {
		k := strings.Index(v.s[from:], needle)
		if k < 0 {
			break
		}
		i, j := from+k, from+k+len(needle)
		if boundaryLeft(v.s, i) {
			a, b := v.span(i, j)
			out = append(out, [2]int{a, b})
		}
		from = i + 1
	}
	return out
}

// ---- numbers -------------------------------------------------------------------------------------------------------

var spokenDigit = map[string]byte{
	"null": '0', "eins": '1', "zwei": '2', "zwo": '2', "drei": '3', "vier": '4', "fuenf": '5', "funf": '5', "fünf": '5',
	"sechs": '6', "sieben": '7', "acht": '8', "neun": '9',
}

// digitRun is a run of digits read from the text, with each digit's original byte span. Digits come from numbers
// (with OCR confusions read as digits and separators such as "/", "-", "." and spaces skipped) and from digits
// dictated as words ("null eins sieben eins").
type digitRun struct {
	digits string
	spans  [][2]int
	spoken int // digits that were dictated as words
}

func (r digitRun) spokenShare() float64 { return float64(r.spoken) / float64(max(len(r.digits), 1)) }

func digitRuns(text string) []digitRun {
	var runs []digitRun
	cur := digitRun{}
	flush := func() {
		if len(cur.digits) > 0 {
			runs = append(runs, cur)
		}
		cur = digitRun{}
	}
	for _, m := range reToken.FindAllStringIndex(text, -1) {
		tok := text[m[0]:m[1]]
		word := strings.ToLower(strings.Trim(tok, ".,;:()"))
		if d, ok := spokenDigit[word]; ok {
			off := m[0] + strings.Index(tok, strings.Trim(tok, ".,;:()"))
			cur.digits += string(d)
			cur.spans = append(cur.spans, [2]int{off, off + len(strings.Trim(tok, ".,;:()"))})
			cur.spoken++
			if strings.HasSuffix(tok, ",") || strings.HasSuffix(tok, ";") {
				flush()
			}
			continue
		}
		numeric, _ := tokenClass(tok)
		if !numeric && !(len(tok) <= 4 && strings.ContainsAny(tok, "0123456789") && onlyDigitsAndSeparators(tok)) {
			flush()
			continue
		}
		started := false
		for i := 0; i < len(tok); {
			r, size := utf8.DecodeRuneInString(tok[i:])
			switch {
			case r >= '0' && r <= '9':
				cur.digits += string(r)
				cur.spans = append(cur.spans, [2]int{m[0] + i, m[0] + i + size})
				started = true
			case ocrToDigit[r] != 0:
				cur.digits += string(ocrToDigit[r])
				cur.spans = append(cur.spans, [2]int{m[0] + i, m[0] + i + size})
				started = true
			case strings.ContainsRune("/-.()+", r):
			default:
				if started { // a letter after digits ends the run ("12a"); letters before them are a prefix ("E7620...")
					flush()
					started = false
				}
			}
			i += size
		}
		if strings.HasSuffix(tok, ",") || strings.HasSuffix(tok, ";") || strings.HasSuffix(tok, ":") {
			flush()
		}
	}
	flush()
	return runs
}

func onlyDigitsAndSeparators(s string) bool {
	for _, r := range s {
		if !(r >= '0' && r <= '9') && !strings.ContainsRune("/-.()+,;:", r) {
			return false
		}
	}
	return true
}

// findDigitsIn returns the original spans where want occurs inside a digit run.
func findDigitsIn(runs []digitRun, want string, exact bool) [][2]int {
	if want == "" {
		return nil
	}
	var out [][2]int
	for _, r := range runs {
		if exact {
			if r.digits == want {
				out = append(out, [2]int{r.spans[0][0], r.spans[len(r.spans)-1][1]})
			}
			continue
		}
		for from := 0; ; {
			k := strings.Index(r.digits[from:], want)
			if k < 0 {
				break
			}
			i := from + k
			out = append(out, [2]int{r.spans[i][0], r.spans[i+len(want)-1][1]})
			from = i + len(want)
		}
	}
	return out
}

// ---- number words --------------------------------------------------------------------------------------------------

var units = map[string]int{"null": 0, "ein": 1, "eins": 1, "eine": 1, "zwei": 2, "zwo": 2, "drei": 3, "vier": 4, "fuenf": 5,
	"sechs": 6, "sieben": 7, "acht": 8, "neun": 9}
var teens = map[string]int{"zehn": 10, "elf": 11, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fuenfzehn": 15,
	"sechzehn": 16, "siebzehn": 17, "achtzehn": 18, "neunzehn": 19}
var tens = map[string]int{"zwanzig": 20, "dreissig": 30, "vierzig": 40, "fuenfzig": 50, "sechzig": 60, "siebzig": 70,
	"achtzig": 80, "neunzig": 90}

// parseNumberWord reads a folded German number word ("neunzehnhundertvierunddreissig" = 1934).
func parseNumberWord(s string) (int, bool) {
	if s == "" {
		return 0, false
	}
	if i := strings.Index(s, "tausend"); i >= 0 {
		left, right := s[:i], s[i+len("tausend"):]
		l := 1
		if left != "" {
			var ok bool
			if l, ok = parseNumberWord(left); !ok {
				return 0, false
			}
		}
		r := 0
		if right != "" {
			var ok bool
			if r, ok = parseNumberWord(right); !ok {
				return 0, false
			}
		}
		return l*1000 + r, true
	}
	if i := strings.Index(s, "hundert"); i >= 0 {
		left, right := strings.TrimSuffix(s[:i], "ein"), s[i+len("hundert"):]
		l := 1
		if left != "" {
			var ok bool
			if l, ok = parseBelow100(left); !ok {
				return 0, false
			}
		}
		r := 0
		if right != "" {
			var ok bool
			if r, ok = parseBelow100(strings.TrimPrefix(right, "und")); !ok {
				return 0, false
			}
		}
		return l*100 + r, true
	}
	return parseBelow100(s)
}

func parseBelow100(s string) (int, bool) {
	if v, ok := units[s]; ok {
		return v, true
	}
	if v, ok := teens[s]; ok {
		return v, true
	}
	if v, ok := tens[s]; ok {
		return v, true
	}
	if i := strings.Index(s, "und"); i > 0 {
		u, ok1 := units[s[:i]]
		t, ok2 := tens[s[i+3:]]
		if ok1 && ok2 && u > 0 {
			return t + u, true
		}
	}
	return 0, false
}

var ordinalSpecial = map[string]int{"erst": 1, "ers": 1, "dritt": 3, "drit": 3, "sieb": 7, "ach": 8}

// parseOrdinal reads "vierzehnten", "ersten", "einunddreissigsten" or "14.".
func parseOrdinal(s string) (int, bool) {
	if t := strings.TrimSuffix(s, "."); t != s {
		n := 0
		for _, r := range t {
			if r < '0' || r > '9' {
				return 0, false
			}
			n = n*10 + int(r-'0')
		}
		return n, t != ""
	}
	for _, suf := range []string{"sten", "ster", "stes", "ste", "ten", "ter", "tes", "te"} {
		if !strings.HasSuffix(s, suf) {
			continue
		}
		stem := strings.TrimSuffix(s, suf)
		if v, ok := ordinalSpecial[stem]; ok {
			return v, true
		}
		if v, ok := parseBelow100(stem); ok && v > 0 {
			return v, true
		}
	}
	return 0, false
}

var foldedMonths = map[string]int{"januar": 1, "jaenner": 1, "februar": 2, "maerz": 3, "marz": 3, "april": 4, "mai": 5,
	"juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}

var reSpokenDate = regexp.MustCompile(`\b([a-z]+|\d{1,2}\.)\s+(januar|jaenner|februar|maerz|marz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+([a-z]+|\d{2,4})\b`)

type spokenDate struct {
	start, end   int // original bytes
	day, month   int
	year         int
	twoDigitYear bool
}

// spokenDates finds dates such as "vierzehnten februar neunzehnhundertvierunddreissig" or "elften april fuenfunddreissig".
func spokenDates(v view) []spokenDate {
	var out []spokenDate
	for _, m := range reSpokenDate.FindAllStringSubmatchIndex(v.s, -1) {
		day, ok := parseOrdinal(v.s[m[2]:m[3]])
		if !ok || day < 1 || day > 31 {
			continue
		}
		month := foldedMonths[v.s[m[4]:m[5]]]
		ys := v.s[m[6]:m[7]]
		year, two := 0, false
		if ys[0] >= '0' && ys[0] <= '9' {
			for _, r := range ys {
				year = year*10 + int(r-'0')
			}
			two = len(ys) == 2
		} else if y, ok := parseNumberWord(ys); ok {
			year, two = y, y < 100
		} else {
			continue
		}
		a, b := v.span(m[0], m[1])
		out = append(out, spokenDate{a, b, day, month, year, two})
	}
	return out
}

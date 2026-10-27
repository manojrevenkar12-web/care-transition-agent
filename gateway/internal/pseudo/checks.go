package pseudo

import (
	"math/big"
	"strings"
	"unicode"
)

// ValidKVNR checks the unchangeable part of a German health insurance number (Krankenversichertennummer): a capital
// letter, eight digits and a check digit. The letter becomes its two-digit alphabet position; the ten digits are
// weighted 1, 2, 1, 2, ...; products above 9 are replaced by their digit sum; the check digit is the sum modulo 10.
func ValidKVNR(s string) bool {
	if len(s) != 10 || s[0] < 'A' || s[0] > 'Z' {
		return false
	}
	pos := int(s[0]-'A') + 1
	digits := []int{pos / 10, pos % 10}
	for i := 1; i < 9; i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
		digits = append(digits, int(s[i]-'0'))
	}
	if s[9] < '0' || s[9] > '9' {
		return false
	}
	sum := 0
	for i, d := range digits {
		p := d * (1 + i%2)
		if p > 9 {
			p = p/10 + p%10
		}
		sum += p
	}
	return sum%10 == int(s[9]-'0')
}

// ValidIBAN checks the ISO 13616 mod-97 checksum.
func ValidIBAN(s string) bool {
	s = strings.ToUpper(strings.ReplaceAll(s, " ", ""))
	if len(s) < 15 || len(s) > 34 {
		return false
	}
	re := s[4:] + s[:4]
	var b strings.Builder
	for _, r := range re {
		switch {
		case r >= '0' && r <= '9':
			b.WriteRune(r)
		case r >= 'A' && r <= 'Z':
			b.WriteString(big.NewInt(int64(r-'A') + 10).String())
		default:
			return false
		}
	}
	n, ok := new(big.Int).SetString(b.String(), 10)
	return ok && new(big.Int).Mod(n, big.NewInt(97)).Int64() == 1
}

// Fold lower-cases and folds German umlauts so "Müller", "MUELLER" and "Mueller" compare equal.
func Fold(s string) string {
	r := strings.NewReplacer("ä", "ae", "ö", "oe", "ü", "ue", "ß", "ss", "é", "e", "è", "e", "á", "a", "ó", "o")
	return r.Replace(strings.ToLower(s))
}

func digitsOnly(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func isWordRune(r rune) bool { return unicode.IsLetter(r) || unicode.IsDigit(r) }

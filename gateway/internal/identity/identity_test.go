package identity

import (
	"bytes"
	"strings"
	"testing"
	"time"
)

var key = bytes.Repeat([]byte{3}, 32)

func TestSealedIdentityOpensOnlyForItsTenantAndCase(t *testing.T) {
	tok, err := Seal(key, Identity{Tenant: "t", Case: "c", KVNR: "A123456780"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(tok, "A123456780") {
		t.Fatal("token must not carry plaintext")
	}
	id, err := Open(key, tok, "t", "c", time.Now())
	if err != nil || id.KVNR != "A123456780" {
		t.Fatalf("%v %v", id, err)
	}
	for _, tc := range [][2]string{{"t", "other"}, {"other", "c"}} {
		if _, err := Open(key, tok, tc[0], tc[1], time.Now()); err == nil {
			t.Fatalf("opened for %v", tc)
		}
	}
	if _, err := Open(bytes.Repeat([]byte{4}, 32), tok, "t", "c", time.Now()); err == nil {
		t.Fatal("wrong key")
	}
}

func TestExpiredTokensAreRefused(t *testing.T) {
	tok, _ := Seal(key, Identity{Tenant: "t", Case: "c", Expires: 100})
	if _, err := Open(key, tok, "t", "c", time.Unix(101, 0)); err != ErrExpired {
		t.Fatalf("got %v", err)
	}
}

func TestTamperedTokensAreRefused(t *testing.T) {
	tok, _ := Seal(key, Identity{Tenant: "t", Case: "c"})
	b := []byte(tok)
	b[len(b)-3] ^= 1
	if _, err := Open(key, string(b), "t", "c", time.Now()); err == nil {
		t.Fatal("tampered token opened")
	}
}

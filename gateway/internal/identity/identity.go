// Package identity holds what the hospital system knows identifies a patient (from the FHIR Patient, Encounter and
// RelatedPerson resources) and seals it into a token. The platform gets a token once per case and sends it with every
// model call, so the gateway stays stateless and every replica can pseudonymise any case.
package identity

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

type Person struct {
	Role   string `json:"role"` // patient | relative | physician | other
	Given  string `json:"given"`
	Family string `json:"family"`
}

type Address struct {
	Street     string `json:"street"` // "Musterstraße 12"
	PostalCode string `json:"postal_code"`
	City       string `json:"city"`
}

type Identity struct {
	Tenant      string    `json:"tenant"`
	Case        string    `json:"case"`
	Persons     []Person  `json:"persons"`
	BirthDate   string    `json:"birth_date"` // YYYY-MM-DD
	KVNR        string    `json:"kvnr"`
	CaseNumbers []string  `json:"case_numbers"`
	Addresses   []Address `json:"addresses"`
	Phones      []string  `json:"phones"`
	Emails      []string  `json:"emails"`
	// Reference date for ages ("today" for the case), YYYY-MM-DD; the clock if empty.
	AsOf    string `json:"as_of"`
	Expires int64  `json:"exp"` // unix seconds
}

var ErrExpired = errors.New("identity token expired")

func aad(tenant, caseID string) []byte { return []byte("cta-identity|" + tenant + "|" + caseID) }

// Seal encrypts the identity with AES-256-GCM, bound to its tenant and case.
func Seal(key []byte, id Identity) (string, error) {
	if id.Tenant == "" || id.Case == "" {
		return "", errors.New("tenant and case are required")
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	plain, err := json.Marshal(id)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	out := gcm.Seal(nonce, nonce, plain, aad(id.Tenant, id.Case))
	return base64.RawURLEncoding.EncodeToString(out), nil
}

// Open decrypts a token for the tenant and case the request claims; a token for another case does not open.
func Open(key []byte, token, tenant, caseID string, now time.Time) (Identity, error) {
	var id Identity
	raw, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil {
		return id, fmt.Errorf("identity token: %w", err)
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return id, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return id, err
	}
	if len(raw) < gcm.NonceSize() {
		return id, errors.New("identity token: too short")
	}
	plain, err := gcm.Open(nil, raw[:gcm.NonceSize()], raw[gcm.NonceSize():], aad(tenant, caseID))
	if err != nil {
		return id, errors.New("identity token: does not open for this tenant and case")
	}
	if err := json.Unmarshal(plain, &id); err != nil {
		return id, err
	}
	if id.Expires != 0 && now.Unix() > id.Expires {
		return id, ErrExpired
	}
	return id, nil
}

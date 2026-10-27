package sigv4

import (
	"encoding/hex"
	"net/http"
	"strings"
	"testing"
	"time"
)

// The signing-key example from the AWS General Reference ("Examples of how to derive a signing key").
func TestSigningKeyMatchesAWSExample(t *testing.T) {
	got := hex.EncodeToString(SigningKey("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20120215", "us-east-1", "iam"))
	want := "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"
	if got != want {
		t.Fatalf("signing key %s, want %s", got, want)
	}
}

// get-vanilla from the AWS SigV4 test suite.
func TestGetVanillaFromTheAWSTestSuite(t *testing.T) {
	req, _ := http.NewRequest("GET", "https://example.amazonaws.com/", nil)
	req.Host = "example.amazonaws.com"
	now := time.Date(2015, 8, 30, 12, 36, 0, 0, time.UTC)
	Sign(req, nil, Credentials{"AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", ""}, "us-east-1", "service", now, false)
	auth := req.Header.Get("Authorization")
	want := "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, SignedHeaders=host;x-amz-date, Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
	if auth != want {
		t.Fatalf("authorization\n got %s\nwant %s", auth, want)
	}
}

func TestBedrockModelPathIsSignedDoubleEncoded(t *testing.T) {
	wire := "/model/" + EscapePathSegment("eu.anthropic.claude-sonnet-4-5-20250929-v1:0") + "/invoke"
	if wire != "/model/eu.anthropic.claude-sonnet-4-5-20250929-v1%3A0/invoke" {
		t.Fatalf("wire path %s", wire)
	}
	if got := CanonicalPath(wire); got != "/model/eu.anthropic.claude-sonnet-4-5-20250929-v1%253A0/invoke" {
		t.Fatalf("canonical path %s", got)
	}
}

func TestSessionTokenIsSigned(t *testing.T) {
	req, _ := http.NewRequest("POST", "https://bedrock-runtime.eu-central-1.amazonaws.com/model/x/invoke", strings.NewReader("{}"))
	req.Header.Set("Content-Type", "application/json")
	Sign(req, []byte("{}"), Credentials{"AKID", "secret", "token"}, "eu-central-1", "bedrock", time.Now(), true)
	if !strings.Contains(req.Header.Get("Authorization"), "x-amz-security-token") || req.Header.Get("X-Amz-Content-Sha256") == "" {
		t.Fatalf("session token and payload hash must be signed: %s", req.Header.Get("Authorization"))
	}
}

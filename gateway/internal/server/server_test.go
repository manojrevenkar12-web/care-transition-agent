package server

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/config"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/identity"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/sigv4"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/upstream"
)

var key32 = bytes.Repeat([]byte{7}, 32)

type fakeModel struct {
	got      atomic.Value // last request body
	failures int32        // answer 529 this many times first
	calls    atomic.Int32
	path     atomic.Value
	auth     atomic.Value
}

func (f *fakeModel) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	n := f.calls.Add(1)
	raw, _ := io.ReadAll(r.Body)
	f.got.Store(string(raw))
	f.path.Store(r.URL.EscapedPath())
	f.auth.Store(r.Header.Get("Authorization"))
	if n <= f.failures {
		w.Header().Set("Retry-After", "0")
		w.WriteHeader(529)
		w.Write([]byte(`{"type":"error","error":{"type":"overloaded_error"}}`))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"id":"m1","type":"message","role":"assistant","content":[{"type":"text","text":"«Patient» kann mit Rollator gehen."}],"usage":{"input_tokens":120,"output_tokens":30}}`))
}

func setup(t *testing.T, model *fakeModel, budget int64) (*httptest.Server, *Server) {
	t.Helper()
	up := httptest.NewServer(model)
	t.Cleanup(up.Close)
	raw := `{"listen":"x","max_body_bytes":100000,"upstream_timeout_seconds":5,"age_cap":90,
	  "retry":{"max_attempts":3,"base_delay_ms":1,"max_delay_ms":2},
	  "upstreams":{"sim":{"kind":"generic","url":"` + up.URL + `","processor":"sim","models":{"sim-careful":"sim-careful"}},
	               "bedrock-eu":{"kind":"bedrock","region":"eu-central-1","url":"` + up.URL + `","processor":"AWS","models":{"claude-sonnet":"eu.anthropic.claude-sonnet-4-5-20250929-v1:0"}},
	               "anthropic":{"kind":"anthropic","url":"` + up.URL + `","api_key_env":"NOPE","processor":"US","models":{"claude-sonnet":"x"}}},
	  "tenants":{"klinikum-nord":{"upstreams":["sim","bedrock-eu"],"daily_token_budget":` + itoa(budget) + `},
	             "dev":{"upstreams":["anthropic"],"daily_token_budget":1000}}}`
	cfg, err := config.Parse([]byte(raw), func(string) string { return "" })
	if err != nil {
		t.Fatal(err)
	}
	uc := upstream.New(5*time.Second, cfg.Retry)
	uc.AWSCreds = func(context.Context) (sigv4.Credentials, error) {
		return sigv4.Credentials{AccessKeyID: "AKID", SecretAccessKey: "s"}, nil
	}
	s := New(cfg, key32, key32, []string{"svc"}, uc, slog.New(slog.NewTextHandler(io.Discard, nil)))
	gw := httptest.NewServer(s.Handler())
	t.Cleanup(gw.Close)
	return gw, s
}

func itoa(n int64) string { b, _ := json.Marshal(n); return string(b) }

func token(t *testing.T, caseID string) string {
	t.Helper()
	tok, err := identity.Seal(key32, identity.Identity{Tenant: "klinikum-nord", Case: caseID,
		Persons:   []identity.Person{{Role: "patient", Given: "Gertrud", Family: "Hoffmann"}},
		BirthDate: "1941-03-02", KVNR: "A123456780", Phones: []string{"030 3312 4471"}, AsOf: "2026-10-27"})
	if err != nil {
		t.Fatal(err)
	}
	return tok
}

func call(t *testing.T, gw *httptest.Server, caseID, tok, body string, hdr map[string]string) (*http.Response, map[string]any) {
	t.Helper()
	req, _ := http.NewRequest("POST", gw.URL+"/v1/messages", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer svc")
	req.Header.Set("X-CTA-Tenant", "klinikum-nord")
	req.Header.Set("X-CTA-Case", caseID)
	req.Header.Set("X-CTA-Identity", tok)
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp, out
}

const raw = `{"model":"sim-careful","max_tokens":200,"system":"Du füllst den Überleitungsbogen.",
  "messages":[{"role":"user","content":[{"type":"text","text":"Patientin Gertrud Hoffmann, geb. 02.03.1941"}]},
   {"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"read_document","input":{"note":"Frau Hoffmann"}}]},
   {"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"Tochter ruft an: Tel. 030 3312 4471. KVNR A123456780"}]}]}`

func TestModelCallLeavesPseudonymisedAndComesBackReidentified(t *testing.T) {
	model := &fakeModel{}
	gw, s := setup(t, model, 10000)
	resp, out := call(t, gw, "c1", token(t, "c1"), raw, map[string]string{"X-CTA-Reidentify": "true"})
	if resp.StatusCode != 200 {
		t.Fatalf("status %d: %v", resp.StatusCode, out)
	}
	sent := model.got.Load().(string)
	for _, leak := range []string{"Gertrud", "Hoffmann", "1941", "3312", "A123456780"} {
		if strings.Contains(sent, leak) {
			t.Fatalf("%q reached the model: %s", leak, sent)
		}
	}
	if !strings.Contains(sent, "«Patient»") || !strings.Contains(sent, "«Telefon»") {
		t.Fatalf("expected tags in %s", sent)
	}
	text := out["content"].([]any)[0].(map[string]any)["text"].(string)
	if text != "Gertrud Hoffmann kann mit Rollator gehen." {
		t.Fatalf("not re-identified: %q", text)
	}
	if resp.Header.Get("X-CTA-Upstream") != "sim" {
		t.Fatal("upstream header")
	}
	if s.used("klinikum-nord") != 150 || s.M.Get("cta_gateway_pseudonymized_total", "kind", "name", "stage", "model_call") < 2 {
		t.Fatalf("usage %d", s.used("klinikum-nord"))
	}
}

func TestATokenForAnotherCaseDoesNotOpen(t *testing.T) {
	gw, _ := setup(t, &fakeModel{}, 10000)
	resp, out := call(t, gw, "c2", token(t, "c1"), raw, nil)
	if resp.StatusCode != 403 || out["error"].(map[string]any)["type"] != "identity" {
		t.Fatalf("got %d %v", resp.StatusCode, out)
	}
}

func TestOnlyApprovedProcessorsAreReachable(t *testing.T) {
	gw, _ := setup(t, &fakeModel{}, 10000)
	resp, out := call(t, gw, "c1", token(t, "c1"), raw, map[string]string{"X-CTA-Upstream": "anthropic"})
	if resp.StatusCode != 403 || out["error"].(map[string]any)["type"] != "processor_not_approved" {
		t.Fatalf("got %d %v", resp.StatusCode, out)
	}
}

func TestImagesAndDocumentsAreRefused(t *testing.T) {
	gw, _ := setup(t, &fakeModel{}, 10000)
	body := `{"model":"sim-careful","max_tokens":5,"messages":[{"role":"user","content":[{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":"JVBERi0="}}]}]}`
	resp, out := call(t, gw, "c1", token(t, "c1"), body, nil)
	if resp.StatusCode != 422 || out["error"].(map[string]any)["type"] != "unsupported_content" {
		t.Fatalf("got %d %v", resp.StatusCode, out)
	}
}

func TestBudgetIsEnforcedPerTenantPerDay(t *testing.T) {
	gw, _ := setup(t, &fakeModel{}, 100)
	if resp, _ := call(t, gw, "c1", token(t, "c1"), raw, nil); resp.StatusCode != 200 {
		t.Fatal("first call is within budget")
	}
	resp, out := call(t, gw, "c1", token(t, "c1"), raw, nil)
	if resp.StatusCode != 429 || out["error"].(map[string]any)["type"] != "budget_exhausted" {
		t.Fatalf("got %d %v", resp.StatusCode, out)
	}
}

func TestOverloadIsRetried(t *testing.T) {
	model := &fakeModel{failures: 2}
	gw, s := setup(t, model, 10000)
	resp, _ := call(t, gw, "c1", token(t, "c1"), raw, nil)
	if resp.StatusCode != 200 || model.calls.Load() != 3 || s.M.Get("cta_gateway_upstream_attempts_total") != 3 {
		t.Fatalf("status %d calls %d", resp.StatusCode, model.calls.Load())
	}
}

func TestBedrockRequestIsSignedAndShaped(t *testing.T) {
	model := &fakeModel{}
	gw, _ := setup(t, model, 10000)
	body := strings.Replace(raw, `"model":"sim-careful"`, `"model":"claude-sonnet"`, 1)
	resp, out := call(t, gw, "c1", token(t, "c1"), body, nil)
	if resp.StatusCode != 200 {
		t.Fatalf("got %d %v", resp.StatusCode, out)
	}
	if p := model.path.Load().(string); p != "/model/eu.anthropic.claude-sonnet-4-5-20250929-v1%3A0/invoke" {
		t.Fatalf("path %s", p)
	}
	if a := model.auth.Load().(string); !strings.HasPrefix(a, "AWS4-HMAC-SHA256 Credential=AKID/") || !strings.Contains(a, "/eu-central-1/bedrock/aws4_request") {
		t.Fatalf("auth %s", a)
	}
	var sent map[string]any
	_ = json.Unmarshal([]byte(model.got.Load().(string)), &sent)
	if sent["anthropic_version"] != "bedrock-2023-05-31" || sent["model"] != nil {
		t.Fatalf("bedrock body %v", sent)
	}
}

func TestPseudonymizeEndpointReturnsOffsetsAndNoLeaks(t *testing.T) {
	gw, _ := setup(t, &fakeModel{}, 10000)
	body, _ := json.Marshal(map[string]any{"tenant": "klinikum-nord", "case": "c1", "identity_token": token(t, "c1"),
		"texts": []string{"Frau Hoffmann (geb. 02.03.1941) – Rückruf 030 3312 4471"}})
	req, _ := http.NewRequest("POST", gw.URL+"/v1/pseudonymize", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer svc")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	var out struct {
		Results []struct {
			Text         string
			Replacements []struct{ Start, End, OutStart, OutEnd int }
		}
		Leaks [][]string
	}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if len(out.Results) != 1 || len(out.Results[0].Replacements) != 3 || len(out.Leaks[0]) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestUnauthenticatedCallsAreRefused(t *testing.T) {
	gw, _ := setup(t, &fakeModel{}, 10000)
	resp, err := http.Post(gw.URL+"/v1/messages", "application/json", strings.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if resp.StatusCode != 401 {
		t.Fatalf("got %d", resp.StatusCode)
	}
}

func TestMetricsExposeNoContent(t *testing.T) {
	model := &fakeModel{}
	gw, _ := setup(t, model, 10000)
	call(t, gw, "c1", token(t, "c1"), raw, nil)
	resp, _ := http.Get(gw.URL + "/metrics")
	b, _ := io.ReadAll(resp.Body)
	m := string(b)
	if !strings.Contains(m, `cta_gateway_requests_total{tenant="klinikum-nord",upstream="sim",model="sim-careful",outcome="ok"} 1`) {
		t.Fatalf("metrics:\n%s", m)
	}
	if strings.Contains(m, "Hoffmann") || strings.Contains(m, "Rollator") {
		t.Fatal("metrics must not carry content")
	}
}

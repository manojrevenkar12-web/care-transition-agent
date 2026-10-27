// Package server is the gateway's HTTP API. The platform calls it for three things: sealing a case's identity once,
// pseudonymising documents when they arrive, and every model call (POST /v1/messages, the Anthropic Messages schema).
// A model call is pseudonymised again here (defence in depth: the platform should already have sent tagged text),
// checked for any surviving identifier, refused if one is found or if the content is not text, routed only to an
// upstream the tenant's agreement allows, counted against the tenant's daily token budget, and logged without content.
package server

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/config"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/identity"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/metrics"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/pseudo"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/upstream"
)

type Server struct {
	Cfg          *config.Config
	SealKey      []byte
	SurrogateKey []byte
	Tokens       []string
	Up           *upstream.Client
	M            *metrics.Registry
	Now          func() time.Time
	Log          *slog.Logger

	mu    sync.Mutex
	usage map[string]dayUsage
}

type dayUsage struct {
	day  string
	used int64
}

func New(cfg *config.Config, sealKey, surrogateKey []byte, tokens []string, up *upstream.Client, log *slog.Logger) *Server {
	m := metrics.New()
	m.Counter("cta_gateway_requests_total", "Model calls by tenant, upstream, model and outcome.")
	m.Counter("cta_gateway_tokens_total", "Tokens by tenant, upstream, model and direction.")
	m.Counter("cta_gateway_pseudonymized_total", "Identifiers replaced, by kind and stage (documents or model calls).")
	m.Counter("cta_gateway_leaks_blocked_total", "Model calls refused because a known identifier survived, by kind.")
	m.Counter("cta_gateway_policy_denied_total", "Requests refused by policy, by reason.")
	m.Counter("cta_gateway_upstream_attempts_total", "Upstream attempts including retries.")
	m.Histogram("cta_gateway_request_seconds", "Model call latency through the gateway.", []float64{0.25, 0.5, 1, 2, 4, 8, 16, 32, 64})
	return &Server{Cfg: cfg, SealKey: sealKey, SurrogateKey: surrogateKey, Tokens: tokens, Up: up, M: m,
		Now: time.Now, Log: log, usage: map[string]dayUsage{}}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ready")) })
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		s.M.Write(w)
	})
	mux.HandleFunc("POST /v1/identity/seal", s.auth(s.seal))
	mux.HandleFunc("POST /v1/pseudonymize", s.auth(s.pseudonymize))
	mux.HandleFunc("POST /v1/reidentify", s.auth(s.reidentify))
	mux.HandleFunc("POST /v1/messages", s.auth(s.messages))
	mux.HandleFunc("GET /v1/policy/{tenant}", s.auth(s.policy))
	return mux
}

func (s *Server) auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		for _, t := range s.Tokens {
			if t != "" && subtle.ConstantTimeCompare([]byte(got), []byte(t)) == 1 {
				r.Body = http.MaxBytesReader(w, r.Body, s.Cfg.MaxBodyBytes)
				next(w, r)
				return
			}
		}
		s.M.Add("cta_gateway_policy_denied_total", 1, "reason", "unauthenticated")
		writeErr(w, 401, "unauthenticated", "a service token is required")
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, typ, msg string, extra ...any) {
	e := map[string]any{"type": typ, "message": msg}
	for i := 0; i+1 < len(extra); i += 2 {
		e[extra[i].(string)] = extra[i+1]
	}
	writeJSON(w, status, map[string]any{"type": "error", "error": e})
}

func (s *Server) seal(w http.ResponseWriter, r *http.Request) {
	var id identity.Identity
	if err := json.NewDecoder(r.Body).Decode(&id); err != nil {
		writeErr(w, 400, "invalid_request", "identity JSON expected")
		return
	}
	if _, ok := s.Cfg.Tenants[id.Tenant]; !ok {
		writeErr(w, 403, "unknown_tenant", "tenant has no agreement on file")
		return
	}
	if id.Expires == 0 {
		id.Expires = s.Now().Add(45 * 24 * time.Hour).Unix()
	}
	tok, err := identity.Seal(s.SealKey, id)
	if err != nil {
		writeErr(w, 400, "invalid_request", err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"token": tok, "expires": id.Expires})
}

type textsReq struct {
	Tenant        string   `json:"tenant"`
	Case          string   `json:"case"`
	IdentityToken string   `json:"identity_token"`
	Texts         []string `json:"texts"`
}

func (s *Server) open(tenant, caseID, token string) (*pseudo.Pseudonymizer, error) {
	id, err := identity.Open(s.SealKey, token, tenant, caseID, s.Now())
	if err != nil {
		return nil, err
	}
	return pseudo.New(id, s.SurrogateKey, s.Cfg.AgeCap, s.Now()), nil
}

func (s *Server) pseudonymize(w http.ResponseWriter, r *http.Request) {
	var req textsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "invalid_request", "JSON expected")
		return
	}
	ps, err := s.open(req.Tenant, req.Case, req.IdentityToken)
	if err != nil {
		s.M.Add("cta_gateway_policy_denied_total", 1, "reason", "identity")
		writeErr(w, 403, "identity", err.Error())
		return
	}
	results := make([]pseudo.Result, len(req.Texts))
	leaks := make([][]string, len(req.Texts))
	for i, t := range req.Texts {
		results[i] = ps.Pseudonymize(t)
		leaks[i] = ps.Leaks(results[i].Text)
		for _, rep := range results[i].Replacements {
			s.M.Add("cta_gateway_pseudonymized_total", 1, "kind", rep.Kind, "stage", "documents")
		}
	}
	writeJSON(w, 200, map[string]any{"results": results, "leaks": leaks})
}

func (s *Server) reidentify(w http.ResponseWriter, r *http.Request) {
	var req textsReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "invalid_request", "JSON expected")
		return
	}
	ps, err := s.open(req.Tenant, req.Case, req.IdentityToken)
	if err != nil {
		writeErr(w, 403, "identity", err.Error())
		return
	}
	out := make([]string, len(req.Texts))
	for i, t := range req.Texts {
		out[i] = ps.Reidentify(t)
	}
	writeJSON(w, 200, map[string]any{"texts": out})
}

func (s *Server) policy(w http.ResponseWriter, r *http.Request) {
	t, ok := s.Cfg.Tenants[r.PathValue("tenant")]
	if !ok {
		writeErr(w, 404, "unknown_tenant", "no such tenant")
		return
	}
	var ups []map[string]any
	for _, name := range t.Upstreams {
		u := s.Cfg.Upstreams[name]
		var models []string
		for m := range u.Models {
			models = append(models, m)
		}
		sort.Strings(models)
		ups = append(ups, map[string]any{"name": name, "processor": u.Processor, "models": models, "region": u.Region})
	}
	writeJSON(w, 200, map[string]any{"upstreams": ups, "daily_token_budget": t.DailyTokenBudget, "used_today": s.used(r.PathValue("tenant"))})
}

func (s *Server) used(tenant string) int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	u := s.usage[tenant]
	if u.day != s.Now().UTC().Format("2006-01-02") {
		return 0
	}
	return u.used
}

func (s *Server) addUsage(tenant string, n int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	day := s.Now().UTC().Format("2006-01-02")
	u := s.usage[tenant]
	if u.day != day {
		u = dayUsage{day: day}
	}
	u.used += n
	s.usage[tenant] = u
}

var errNonText = errors.New("only text content may leave the gateway")

// walkMessages applies f to every string the model will read: system, text blocks, tool results and the inputs of
// earlier tool calls. Images and documents are refused: they cannot be pseudonymised.
func walkMessages(body map[string]any, f func(string) string) error {
	switch sys := body["system"].(type) {
	case string:
		body["system"] = f(sys)
	case []any:
		if err := walkBlocks(sys, f); err != nil {
			return err
		}
	}
	msgs, _ := body["messages"].([]any)
	for _, m := range msgs {
		mm, ok := m.(map[string]any)
		if !ok {
			return errors.New("malformed message")
		}
		switch c := mm["content"].(type) {
		case string:
			mm["content"] = f(c)
		case []any:
			if err := walkBlocks(c, f); err != nil {
				return err
			}
		}
	}
	return nil
}

func walkBlocks(blocks []any, f func(string) string) error {
	for _, b := range blocks {
		bm, ok := b.(map[string]any)
		if !ok {
			return errors.New("malformed content block")
		}
		switch bm["type"] {
		case "text":
			if t, ok := bm["text"].(string); ok {
				bm["text"] = f(t)
			}
		case "tool_result":
			switch c := bm["content"].(type) {
			case string:
				bm["content"] = f(c)
			case []any:
				if err := walkBlocks(c, f); err != nil {
					return err
				}
			}
		case "tool_use":
			bm["input"] = walkAny(bm["input"], f)
		case "thinking", "redacted_thinking":
		default:
			return errNonText
		}
	}
	return nil
}

func walkAny(v any, f func(string) string) any {
	switch x := v.(type) {
	case string:
		return f(x)
	case []any:
		for i := range x {
			x[i] = walkAny(x[i], f)
		}
	case map[string]any:
		for k := range x {
			x[k] = walkAny(x[k], f)
		}
	}
	return v
}

func (s *Server) messages(w http.ResponseWriter, r *http.Request) {
	start := s.Now()
	tenant, caseID := r.Header.Get("X-CTA-Tenant"), r.Header.Get("X-CTA-Case")
	runID := r.Header.Get("X-CTA-Run")
	log := s.Log.With("event", "model_call", "tenant", tenant, "case", caseID, "run", runID)
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		writeErr(w, 413, "too_large", "request body too large")
		return
	}
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		writeErr(w, 400, "invalid_request", "JSON expected")
		return
	}
	model, _ := body["model"].(string)
	ps, err := s.open(tenant, caseID, r.Header.Get("X-CTA-Identity"))
	if err != nil {
		s.M.Add("cta_gateway_policy_denied_total", 1, "reason", "identity")
		log.Warn("denied", "reason", "identity")
		writeErr(w, 403, "identity", err.Error())
		return
	}
	upName, up, modelID, err := s.Cfg.Route(tenant, model, r.Header.Get("X-CTA-Upstream"))
	if err != nil {
		s.M.Add("cta_gateway_policy_denied_total", 1, "reason", "route")
		log.Warn("denied", "reason", "route", "model", model)
		writeErr(w, 403, "processor_not_approved", err.Error())
		return
	}
	if budget := s.Cfg.Tenants[tenant].DailyTokenBudget; s.used(tenant) >= budget {
		s.M.Add("cta_gateway_policy_denied_total", 1, "reason", "budget")
		log.Warn("denied", "reason", "budget")
		writeErr(w, 429, "budget_exhausted", "the tenant's daily token budget is used up")
		return
	}
	late := map[string]int{}
	err = walkMessages(body, func(t string) string {
		res := ps.Pseudonymize(t)
		for _, rep := range res.Replacements {
			late[rep.Kind]++
		}
		return res.Text
	})
	if err != nil {
		s.M.Add("cta_gateway_policy_denied_total", 1, "reason", "content_type")
		writeErr(w, 422, "unsupported_content", err.Error())
		return
	}
	for k, n := range late {
		s.M.Add("cta_gateway_pseudonymized_total", float64(n), "kind", k, "stage", "model_call")
	}
	leakKinds := map[string]bool{}
	_ = walkMessages(body, func(t string) string {
		for _, k := range ps.Leaks(t) {
			leakKinds[k] = true
		}
		return t
	})
	if len(leakKinds) > 0 {
		var kinds []string
		for k := range leakKinds {
			kinds = append(kinds, k)
			s.M.Add("cta_gateway_leaks_blocked_total", 1, "tenant", tenant, "kind", k)
		}
		sort.Strings(kinds)
		log.Error("blocked", "reason", "identifier_leak", "kinds", strings.Join(kinds, ","))
		writeErr(w, 422, "identifier_leak", "a known identifier survived pseudonymisation; nothing was sent", "kinds", kinds)
		return
	}
	resp, err := s.Up.Send(r.Context(), up, modelID, body)
	elapsed := s.Now().Sub(start).Seconds()
	s.M.Observe("cta_gateway_request_seconds", elapsed, "upstream", upName)
	if err != nil {
		s.M.Add("cta_gateway_requests_total", 1, "tenant", tenant, "upstream", upName, "model", model, "outcome", "unavailable")
		log.Error("upstream_unavailable", "upstream", upName, "error", err.Error())
		writeErr(w, 502, "upstream_unavailable", "the model provider could not be reached")
		return
	}
	s.M.Add("cta_gateway_upstream_attempts_total", float64(resp.Attempts))
	outcome := "ok"
	if resp.Status >= 400 {
		outcome = fmt.Sprintf("http_%d", resp.Status)
	}
	s.M.Add("cta_gateway_requests_total", 1, "tenant", tenant, "upstream", upName, "model", model, "outcome", outcome)
	out := resp.Body
	var parsed map[string]any
	if resp.Status < 400 && json.Unmarshal(resp.Body, &parsed) == nil {
		if usage, ok := parsed["usage"].(map[string]any); ok {
			in, _ := usage["input_tokens"].(float64)
			o, _ := usage["output_tokens"].(float64)
			s.addUsage(tenant, int64(in+o))
			s.M.Add("cta_gateway_tokens_total", in, "tenant", tenant, "upstream", upName, "model", model, "direction", "input")
			s.M.Add("cta_gateway_tokens_total", o, "tenant", tenant, "upstream", upName, "model", model, "direction", "output")
		}
		if r.Header.Get("X-CTA-Reidentify") == "true" {
			if content, ok := parsed["content"].([]any); ok {
				parsed["content"] = walkAny(content, ps.Reidentify)
				out, _ = json.Marshal(parsed)
			}
		}
	}
	log.Info("completed", "upstream", upName, "model", model, "status", resp.Status, "attempts", resp.Attempts,
		"seconds", elapsed, "late_replacements", sum(late))
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-CTA-Upstream", upName)
	w.Header().Set("X-CTA-Processor", up.Processor)
	w.WriteHeader(resp.Status)
	w.Write(out)
}

func sum(m map[string]int) int {
	n := 0
	for _, v := range m {
		n += v
	}
	return n
}

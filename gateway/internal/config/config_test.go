package config

import (
	"os"
	"strings"
	"testing"
)

func TestExpandUsesEnvironmentThenDefault(t *testing.T) {
	env := map[string]string{"A": "set"}
	got := Expand("${A} ${B:-fallback} ${C}", func(k string) string { return env[k] })
	if got != "set fallback " {
		t.Fatalf("got %q", got)
	}
}

func TestTheRepositoryConfigLoadsAndRoutes(t *testing.T) {
	raw, err := os.ReadFile("../../../config/gateway.json")
	if err != nil {
		t.Fatal(err)
	}
	c, err := Parse(raw, func(string) string { return "" })
	if err != nil {
		t.Fatal(err)
	}
	name, u, id, err := c.Route("klinikum-nord", "claude-sonnet", "")
	if err != nil || name != "bedrock-eu" || u.Region != "eu-central-1" || !strings.HasPrefix(id, "eu.anthropic.") {
		t.Fatalf("hospital tenants reach Claude through Bedrock in Frankfurt: %s %v %s %v", name, u, id, err)
	}
	if _, _, _, err := c.Route("klinikum-nord", "claude-sonnet", "anthropic"); err == nil {
		t.Fatal("a hospital tenant may not be routed to the US API")
	}
	if _, _, _, err := c.Route("nobody", "sim-careful", ""); err == nil {
		t.Fatal("unknown tenant")
	}
}

func TestInvalidConfigsAreRejected(t *testing.T) {
	for _, raw := range []string{
		`{"max_body_bytes":1,"upstream_timeout_seconds":1,"age_cap":90,"retry":{"max_attempts":1},"upstreams":{"x":{"kind":"ftp","models":{"a":"a"}}}}`,
		`{"max_body_bytes":1,"upstream_timeout_seconds":1,"age_cap":90,"retry":{"max_attempts":1},"upstreams":{},"tenants":{"t":{"upstreams":["missing"],"daily_token_budget":1}}}`,
		`{"max_body_bytes":0,"upstream_timeout_seconds":1,"age_cap":90,"retry":{"max_attempts":1}}`,
	} {
		if _, err := Parse([]byte(raw), func(string) string { return "" }); err == nil {
			t.Errorf("accepted %s", raw)
		}
	}
}

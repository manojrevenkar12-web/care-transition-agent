// Package config loads config/gateway.json, expanding ${VAR} and ${VAR:-default} from the environment.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strings"
)

type Retry struct {
	MaxAttempts int `json:"max_attempts"`
	BaseDelayMs int `json:"base_delay_ms"`
	MaxDelayMs  int `json:"max_delay_ms"`
}

type Upstream struct {
	Kind      string            `json:"kind"` // anthropic | bedrock | generic
	URL       string            `json:"url"`
	Region    string            `json:"region"`
	APIKeyEnv string            `json:"api_key_env"`
	Processor string            `json:"processor"`
	Models    map[string]string `json:"models"` // logical name -> provider model id
}

type Tenant struct {
	Upstreams        []string `json:"upstreams"`
	DailyTokenBudget int64    `json:"daily_token_budget"`
}

type Config struct {
	Listen                 string              `json:"listen"`
	ServiceTokensEnv       string              `json:"service_tokens_env"`
	SealKeyEnv             string              `json:"seal_key_env"`
	SurrogateKeyEnv        string              `json:"surrogate_key_env"`
	MaxBodyBytes           int64               `json:"max_body_bytes"`
	UpstreamTimeoutSeconds int                 `json:"upstream_timeout_seconds"`
	Retry                  Retry               `json:"retry"`
	AgeCap                 int                 `json:"age_cap"`
	Upstreams              map[string]Upstream `json:"upstreams"`
	Tenants                map[string]Tenant   `json:"tenants"`
}

var envRef = regexp.MustCompile(`\$\{([A-Z0-9_]+)(:-([^}]*))?\}`)

// Expand replaces ${VAR} and ${VAR:-default} with the environment's value.
func Expand(s string, getenv func(string) string) string {
	return envRef.ReplaceAllStringFunc(s, func(m string) string {
		p := envRef.FindStringSubmatch(m)
		if v := getenv(p[1]); v != "" {
			return v
		}
		return p[3]
	})
}

func Parse(raw []byte, getenv func(string) string) (*Config, error) {
	var c Config
	if err := json.Unmarshal([]byte(Expand(string(raw), getenv)), &c); err != nil {
		return nil, fmt.Errorf("gateway config: %w", err)
	}
	if err := c.validate(); err != nil {
		return nil, err
	}
	return &c, nil
}

func Load(path string) (*Config, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return Parse(raw, os.Getenv)
}

func (c *Config) validate() error {
	if c.MaxBodyBytes <= 0 || c.UpstreamTimeoutSeconds <= 0 || c.Retry.MaxAttempts <= 0 || c.AgeCap <= 0 {
		return fmt.Errorf("gateway config: limits must be positive")
	}
	for name, u := range c.Upstreams {
		switch u.Kind {
		case "anthropic", "generic":
			if u.URL == "" {
				return fmt.Errorf("upstream %s: url missing", name)
			}
		case "bedrock":
			if u.Region == "" {
				return fmt.Errorf("upstream %s: region missing", name)
			}
		default:
			return fmt.Errorf("upstream %s: unknown kind %q", name, u.Kind)
		}
		if len(u.Models) == 0 {
			return fmt.Errorf("upstream %s: no models", name)
		}
	}
	for name, t := range c.Tenants {
		if len(t.Upstreams) == 0 || t.DailyTokenBudget <= 0 {
			return fmt.Errorf("tenant %s: upstreams and a budget are required", name)
		}
		for _, u := range t.Upstreams {
			if _, ok := c.Upstreams[u]; !ok {
				return fmt.Errorf("tenant %s: unknown upstream %s", name, u)
			}
		}
	}
	return nil
}

// Route picks the upstream for a tenant and logical model. A requested upstream must be on the tenant's list.
func (c *Config) Route(tenant, model, requested string) (string, Upstream, string, error) {
	t, ok := c.Tenants[tenant]
	if !ok {
		return "", Upstream{}, "", fmt.Errorf("unknown tenant %q", tenant)
	}
	for _, name := range t.Upstreams {
		if requested != "" && name != requested {
			continue
		}
		u := c.Upstreams[name]
		if id, ok := u.Models[model]; ok {
			return name, u, id, nil
		}
	}
	if requested != "" && !contains(t.Upstreams, requested) {
		return "", Upstream{}, "", fmt.Errorf("tenant %s may not use upstream %s", tenant, requested)
	}
	return "", Upstream{}, "", fmt.Errorf("no approved upstream for tenant %s offers model %s", tenant, model)
}

func contains(xs []string, x string) bool {
	for _, v := range xs {
		if strings.EqualFold(v, x) {
			return true
		}
	}
	return false
}

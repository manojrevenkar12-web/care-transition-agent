// Package upstream sends an Anthropic Messages request to the provider a tenant is allowed to use: the Anthropic API,
// Amazon Bedrock (SigV4-signed, in the tenant's region) or a generic endpoint with the same schema (the simulated model).
// Retryable failures (429, 5xx, 529, network) are retried with capped exponential backoff and full jitter, honouring
// Retry-After.
package upstream

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/config"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/sigv4"
)

type Response struct {
	Status   int
	Body     []byte
	Attempts int
}

type Client struct {
	HTTP  *http.Client
	Retry config.Retry
	Now   func() time.Time
	Sleep func(context.Context, time.Duration) error
	// Credentials for Bedrock; nil reads the environment / ECS container credentials.
	AWSCreds func(context.Context) (sigv4.Credentials, error)
}

func New(timeout time.Duration, retry config.Retry) *Client {
	return &Client{
		HTTP:  &http.Client{Timeout: timeout},
		Retry: retry,
		Now:   time.Now,
		Sleep: func(ctx context.Context, d time.Duration) error {
			t := time.NewTimer(d)
			defer t.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-t.C:
				return nil
			}
		},
		AWSCreds: EnvOrContainerCredentials,
	}
}

func retryable(status int) bool {
	return status == 429 || status == 529 || status == 500 || status == 502 || status == 503 || status == 504
}

// Send forwards body (an Anthropic Messages request with the logical model already replaced) to the upstream.
func (c *Client) Send(ctx context.Context, u config.Upstream, modelID string, body map[string]any) (*Response, error) {
	var lastErr error
	for attempt := 1; attempt <= c.Retry.MaxAttempts; attempt++ {
		req, err := c.build(ctx, u, modelID, body)
		if err != nil {
			return nil, err
		}
		resp, err := c.HTTP.Do(req)
		if err == nil {
			data, rerr := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
			resp.Body.Close()
			if rerr == nil && !retryable(resp.StatusCode) {
				return &Response{Status: resp.StatusCode, Body: data, Attempts: attempt}, nil
			}
			lastErr = fmt.Errorf("upstream answered %d", resp.StatusCode)
			if attempt == c.Retry.MaxAttempts {
				return &Response{Status: resp.StatusCode, Body: data, Attempts: attempt}, nil
			}
			if err := c.Sleep(ctx, c.delay(attempt, resp.Header.Get("Retry-After"))); err != nil {
				return nil, err
			}
			continue
		}
		lastErr = err
		if ctx.Err() != nil || attempt == c.Retry.MaxAttempts {
			break
		}
		if err := c.Sleep(ctx, c.delay(attempt, "")); err != nil {
			return nil, err
		}
	}
	return nil, lastErr
}

func (c *Client) delay(attempt int, retryAfter string) time.Duration {
	if s, err := strconv.Atoi(strings.TrimSpace(retryAfter)); err == nil && s >= 0 {
		return min(time.Duration(s)*time.Second, time.Duration(c.Retry.MaxDelayMs)*time.Millisecond)
	}
	ceiling := min(float64(c.Retry.BaseDelayMs)*float64(int(1)<<(attempt-1)), float64(c.Retry.MaxDelayMs))
	return time.Duration(rand.Float64()*ceiling) * time.Millisecond
}

func (c *Client) build(ctx context.Context, u config.Upstream, modelID string, body map[string]any) (*http.Request, error) {
	payload := map[string]any{}
	for k, v := range body {
		payload[k] = v
	}
	switch u.Kind {
	case "anthropic", "generic":
		payload["model"] = modelID
		raw, err := json.Marshal(payload)
		if err != nil {
			return nil, err
		}
		req, err := http.NewRequestWithContext(ctx, "POST", strings.TrimRight(u.URL, "/")+"/v1/messages", bytes.NewReader(raw))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("anthropic-version", "2023-06-01")
		if u.Kind == "anthropic" {
			key := os.Getenv(u.APIKeyEnv)
			if key == "" {
				return nil, errors.New("upstream api key not configured")
			}
			req.Header.Set("x-api-key", key)
		}
		return req, nil
	case "bedrock":
		delete(payload, "model")
		delete(payload, "stream")
		payload["anthropic_version"] = "bedrock-2023-05-31"
		raw, err := json.Marshal(payload)
		if err != nil {
			return nil, err
		}
		host := "bedrock-runtime." + u.Region + ".amazonaws.com"
		if u.URL != "" { // tests and VPC endpoints
			host = strings.TrimPrefix(strings.TrimPrefix(u.URL, "https://"), "http://")
		}
		scheme := "https"
		if strings.HasPrefix(u.URL, "http://") {
			scheme = "http"
		}
		req, err := http.NewRequestWithContext(ctx, "POST", scheme+"://"+host+"/", bytes.NewReader(raw))
		if err != nil {
			return nil, err
		}
		req.URL.Path = "/model/" + modelID + "/invoke"
		req.URL.RawPath = "/model/" + sigv4.EscapePathSegment(modelID) + "/invoke"
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json")
		creds, err := c.AWSCreds(ctx)
		if err != nil {
			return nil, err
		}
		sigv4.Sign(req, raw, creds, u.Region, "bedrock", c.Now(), true)
		return req, nil
	}
	return nil, fmt.Errorf("unknown upstream kind %s", u.Kind)
}

// EnvOrContainerCredentials reads AWS credentials from the environment, or from the ECS task role endpoint.
func EnvOrContainerCredentials(ctx context.Context) (sigv4.Credentials, error) {
	if id := os.Getenv("AWS_ACCESS_KEY_ID"); id != "" {
		return sigv4.Credentials{AccessKeyID: id, SecretAccessKey: os.Getenv("AWS_SECRET_ACCESS_KEY"), SessionToken: os.Getenv("AWS_SESSION_TOKEN")}, nil
	}
	rel := os.Getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
	if rel == "" {
		return sigv4.Credentials{}, errors.New("no AWS credentials (environment or ECS task role)")
	}
	req, err := http.NewRequestWithContext(ctx, "GET", "http://169.254.170.2"+rel, nil)
	if err != nil {
		return sigv4.Credentials{}, err
	}
	resp, err := (&http.Client{Timeout: 3 * time.Second}).Do(req)
	if err != nil {
		return sigv4.Credentials{}, err
	}
	defer resp.Body.Close()
	var v struct{ AccessKeyId, SecretAccessKey, Token string }
	if err := json.NewDecoder(resp.Body).Decode(&v); err != nil {
		return sigv4.Credentials{}, err
	}
	return sigv4.Credentials{AccessKeyID: v.AccessKeyId, SecretAccessKey: v.SecretAccessKey, SessionToken: v.Token}, nil
}

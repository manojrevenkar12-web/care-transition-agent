// Command gateway runs the LLM egress gateway.
//
//	CTA_GATEWAY_SEAL_KEY=<base64 32 bytes> CTA_GATEWAY_SURROGATE_KEY=<base64> CTA_GATEWAY_SERVICE_TOKENS=t1,t2 \
//	  gateway -config config/gateway.json
package main

import (
	"context"
	"encoding/base64"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/config"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/server"
	"github.com/manojrevenkar12-web/care-transition-agent/gateway/internal/upstream"
)

func key(env string) ([]byte, error) {
	v := os.Getenv(env)
	if v == "" {
		return nil, fmt.Errorf("%s is not set", env)
	}
	k, err := base64.StdEncoding.DecodeString(v)
	if err != nil || len(k) != 32 {
		return nil, fmt.Errorf("%s must be 32 bytes, base64", env)
	}
	return k, nil
}

func main() {
	path := flag.String("config", "config/gateway.json", "gateway config")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.Load(*path)
	if err != nil {
		log.Error("config", "error", err.Error())
		os.Exit(2)
	}
	seal, err := key(cfg.SealKeyEnv)
	if err != nil {
		log.Error("keys", "error", err.Error())
		os.Exit(2)
	}
	surr, err := key(cfg.SurrogateKeyEnv)
	if err != nil {
		log.Error("keys", "error", err.Error())
		os.Exit(2)
	}
	tokens := strings.Split(os.Getenv(cfg.ServiceTokensEnv), ",")
	up := upstream.New(time.Duration(cfg.UpstreamTimeoutSeconds)*time.Second, cfg.Retry)
	srv := server.New(cfg, seal, surr, tokens, up, log)
	hs := &http.Server{Addr: cfg.Listen, Handler: srv.Handler(), ReadHeaderTimeout: 10 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shut, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		_ = hs.Shutdown(shut)
	}()
	log.Info("listening", "addr", cfg.Listen)
	if err := hs.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Error("serve", "error", err.Error())
		os.Exit(1)
	}
}

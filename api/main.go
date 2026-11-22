// Command api serves the proof's HTTP API on :8080, on a laptop or behind the
// Lambda Web Adapter. See docs/adr/0002-proof-application.md.
package main

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"time"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	mode := os.Getenv("AUTH_MODE")
	if mode != "dev" && mode != "aws" {
		slog.Error("invalid AUTH_MODE; GET /api/me will return 500", "auth_mode", mode)
	}
	srv := &http.Server{Addr: ":8080", Handler: newHandler(mode), ReadHeaderTimeout: 10 * time.Second}
	slog.Info("listening", "addr", srv.Addr, "auth_mode", mode)
	if err := srv.ListenAndServe(); err != nil {
		slog.Error("server stopped", "err", err)
		os.Exit(1)
	}
}

// newHandler routes GET / (the adapter's readiness check, always open) and
// GET /api/me.
func newHandler(authMode string) http.Handler {
	mux := http.NewServeMux()
	// "/{$}" matches only the root; "GET /" alone would match every path.
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok"))
	})
	mux.HandleFunc("GET /api/me", func(w http.ResponseWriter, r *http.Request) {
		email, err := currentEmail(authMode, r)
		switch {
		case errors.Is(err, errBadMode):
			slog.Error("rejected /api/me", "reason", err.Error())
			http.Error(w, "server misconfigured", http.StatusInternalServerError)
			return
		case err != nil:
			slog.Warn("rejected /api/me", "reason", err.Error())
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"email": email})
	})
	return mux
}

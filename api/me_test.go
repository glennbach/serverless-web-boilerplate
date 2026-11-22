package main

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"os"
	"reflect"
	"strings"
	"testing"
)

// get sends one request through newHandler(mode). The adapter header is set
// only when reqCtx is not empty.
func get(t *testing.T, mode, method, path, reqCtx string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	if reqCtx != "" {
		req.Header.Set("x-amzn-request-context", reqCtx)
	}
	rr := httptest.NewRecorder()
	newHandler(mode).ServeHTTP(rr, req)
	return rr
}

func wantEmail(t *testing.T, rr *httptest.ResponseRecorder, email string) {
	t.Helper()
	if rr.Code != 200 {
		t.Fatalf("status = %d, want 200 (body %q)", rr.Code, rr.Body.String())
	}
	if ct := rr.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type = %q, want application/json", ct)
	}
	var body map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &body); err != nil {
		t.Fatalf("body %q is not JSON: %v", rr.Body.String(), err)
	}
	if want := map[string]any{"email": email}; !reflect.DeepEqual(body, want) {
		t.Errorf("body = %v, want %v", body, want)
	}
}

// fixture returns testdata/request-context.json on one line, as the adapter
// sends it.
func fixture(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile("testdata/request-context.json")
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := json.Compact(&buf, raw); err != nil {
		t.Fatal(err)
	}
	return buf.String()
}

func TestMeAWS(t *testing.T) {
	wantEmail(t, get(t, "aws", "GET", "/api/me", fixture(t)), "person@example.com")
}

func TestMeAWSRejects(t *testing.T) {
	cases := map[string]string{
		"missing header":    "",
		"not JSON":          "not-json",
		"empty object":      `{}`,
		"no email claim":    `{"authorizer":{"jwt":{"claims":{"sub":"x"}}}}`,
		"empty email":       `{"authorizer":{"jwt":{"claims":{"email":""}}}}`,
		"non-string email":  `{"authorizer":{"jwt":{"claims":{"email":123}}}}`,
		"outer wrapper key": `{"requestContext":{"authorizer":{"jwt":{"claims":{"email":"a@b.c"}}}}}`,
	}
	for name, reqCtx := range cases {
		rr := get(t, "aws", "GET", "/api/me", reqCtx)
		if rr.Code != 401 {
			t.Errorf("%s: status = %d, want 401", name, rr.Code)
		}
		if strings.Contains(rr.Body.String(), "@") {
			t.Errorf("%s: body %q leaks an email", name, rr.Body.String())
		}
	}
}

func TestMeDevIgnoresRequestContext(t *testing.T) {
	wantEmail(t, get(t, "dev", "GET", "/api/me", fixture(t)), "dev@localhost")
}

func TestRootIsOpen(t *testing.T) {
	for _, mode := range []string{"", "dev", "aws", "bogus"} {
		if rr := get(t, mode, "GET", "/", ""); rr.Code != 200 {
			t.Errorf("mode %q: GET / = %d, want 200", mode, rr.Code)
		}
	}
}

func TestUnknownPathIs404(t *testing.T) {
	for _, p := range []string{"/nope", "/api/mee", "/api/me/x"} {
		if rr := get(t, "dev", "GET", p, ""); rr.Code != 404 {
			t.Errorf("GET %s = %d, want 404", p, rr.Code)
		}
	}
}

func TestMeDev(t *testing.T) {
	wantEmail(t, get(t, "dev", "GET", "/api/me", ""), "dev@localhost")
}

func TestMeRejectsWrongMethod(t *testing.T) {
	if rr := get(t, "dev", "POST", "/api/me", ""); rr.Code != 405 {
		t.Errorf("POST /api/me = %d, want 405", rr.Code)
	}
}

func TestMeRejectsUnknownMode(t *testing.T) {
	for _, mode := range []string{"", "prod", "DEV", " dev"} {
		rr := get(t, mode, "GET", "/api/me", "")
		if rr.Code != 500 {
			t.Errorf("mode %q: status = %d, want 500", mode, rr.Code)
		}
		if strings.Contains(rr.Body.String(), "@") {
			t.Errorf("mode %q: body %q leaks an email", mode, rr.Body.String())
		}
	}
}

# Proof Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the proof: a Go API with `GET /` and `GET /api/me`, a one-page React SPA that shows the current user's email, a Lambda-ready container image, and a no-rebuild local dev loop. Every AWS code path is exercised locally with fixtures.

**Architecture:** `api/` is one `net/http` binary using the standard-library `ServeMux`. `AUTH_MODE` picks the current user: `dev` returns a fixed user, `aws` reads the `email` claim from the `x-amzn-request-context` header that the Lambda Web Adapter sets. `web/` is a Vite + React + TypeScript SPA that reads `/config.json` at startup, signs in through the Cognito Hosted UI with PKCE when `authMode` is `cognito`, and calls the API with the ID token.

**Tech Stack:** Go 1.27 (stdlib only, plus the `gow` tool dependency), Lambda Web Adapter 1.1.0, distroless static base image, Node 26, Vite 8, React 19, TypeScript 7, `node --test` (no test framework).

**Spec:** [`docs/adr/0002-proof-application.md`](../adr/0002-proof-application.md). The platform context is [`docs/adr/0001-serverless-go-platform-architecture.md`](../adr/0001-serverless-go-platform-architecture.md). Task: T001 (plan) and T002 (implementation) in `TODO.md`.

## Global Constraints

- The API listens on port `8080`. `GET /` returns 200 with no authentication in every mode (adapter readiness check).
- `AUTH_MODE=dev` → email `dev@localhost`, reads no token, calls no AWS.
- `AUTH_MODE=aws` → email is `authorizer.jwt.claims.email` from the JSON in the `x-amzn-request-context` header. The header is the context object itself, with no outer `requestContext` key. A missing, empty, or non-string claim rejects the request.
- Any other `AUTH_MODE`, including unset, rejects `GET /api/me`.
- `GET /api/me` responds `{"email": "..."}` with `Content-Type: application/json`.
- Go sets no CORS headers. Vite proxies `/api` to `http://localhost:8080` without rewriting the path.
- The SPA has one page, no router, no component library, no Cognito SDK, no login form. It sends `Authorization: Bearer <ID token>` only in `cognito` mode.
- One production bundle for every environment. Runtime settings come only from `/config.json`.
- `npm run build` runs `tsc` before `vite build`.
- The runtime image contains the Go binary and the adapter copied from `public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0` to `/opt/extensions/lambda-adapter`. No SPA, no TLS.
- `gow` is a Go tool dependency in `api/go.mod`, run as `go tool gow run .`. No compose file, no Docker in the dev loop.
- Layout: `api/` Go module, `web/` Vite app. `infra/` is T004's.
- Logs are JSON (`log/slog` JSON handler to stdout). Never log the request-context header or the email.

## Review Focus

1. **`GET /` in `ServeMux` is a catch-all.** A typo'd path such as `/api/mee` must return 404, not the readiness 200. Register `GET /{$}`. Pinned by `TestUnknownPathIs404` (Task 1).
2. **CDK's `HttpApi.url` ends in `/`.** An `apiBaseUrl` of `https://x.execute-api…/` must still call `…/api/me`, not `…//api/me`. Pinned in `api.test.ts` (Task 4).
3. **The user cancels on the Hosted UI.** Cognito redirects back with `?error=…`. The page must show the error and must not redirect again in a loop. Pinned in `auth.test.ts` (Task 5).
4. **Refresh on the callback URL, or a forged callback.** A reused `?code=` or a `state` that does not match must fail without calling the token endpoint, and the query is removed from the address bar after any callback. Pinned in `auth.test.ts` and `boot.test.ts` (Task 5).
5. **A stored ID token expires.** Cognito sets the ID token's lifetime separately from the access token, and `expires_in` in the token response describes the access token (RFC 6749 §5.1). Expiry comes from the ID token's own `exp`. The SPA must sign in again rather than send a dead token and show 401 forever. Pinned in `auth.test.ts` (Task 5).

## Decisions beyond the ADR

- **Status codes.** Missing or bad claims in `aws` mode → `401`. Unknown or unset `AUTH_MODE` → `500` (server misconfiguration), and the process logs an error at startup but keeps serving `GET /`. Error bodies are plain text from `http.Error` and never contain an email.
- **`config.json` schema.** `cognitoDomainUrl` is the full `https://` origin of the Hosted UI (what CDK's `UserPoolDomain.baseUrl()` returns). The ADR also lists the User Pool id. Nothing in the SPA reads it, so the schema omits it. T004 adds it if it needs it.
- **Callback and logout URL** = the site origin plus `/`. Scopes: `openid email`.
- **The session** (`{idToken, expiresAt}`) is kept in `sessionStorage`. `expiresAt` is the ID token's `exp` claim in milliseconds, decoded without verification (API Gateway verifies). `expires_in` is ignored. A token within 60 s of expiry counts as expired.
- **The bootstrap** lives in `web/src/boot.ts`, which takes its browser dependencies as parameters, so `node --test` drives a whole sign-in callback. `main.tsx` only renders.
- **No sign-out button.** Add it when someone needs to switch users on a deployed environment.
- **Image architecture.** The Dockerfile is multi-arch. Local builds use `linux/arm64`. T004 picks the Lambda architecture and must build the image to match.

---

### Task 1: Go server, dev mode, and the gow loop

**Files:**
- Create: `api/go.mod`, `api/go.sum`, `api/main.go`, `api/me.go`, `api/me_test.go`

**Interfaces:**
- Produces: `func newHandler(authMode string) http.Handler` (main.go); `func currentEmail(authMode string, r *http.Request) (string, error)` (me.go); sentinel errors `errNoUser` (→ 401) and `errBadMode` (→ 500).

- [ ] **Step 1: Create the module and the tool dependency**

```bash
mkdir api && cd api
go mod init serverless-web-boilerplate/api   # no git remote yet; nothing imports this module
go get -tool github.com/mitranim/gow@latest
```
Expected: `go.mod` has a `tool github.com/mitranim/gow` line and a pinned version.

- [ ] **Step 2: Write the failing tests in `api/me_test.go`**

Use a helper `get(t *testing.T, mode, method, path, reqCtx string) *httptest.ResponseRecorder` that calls `newHandler(mode).ServeHTTP` and sets `x-amzn-request-context` only when `reqCtx != ""`.

```go
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
	rr := get(t, "dev", "GET", "/api/me", "")
	// want 200, Content-Type "application/json",
	// body decoded into map[string]any deep-equals map[string]any{"email": "dev@localhost"}
}

func TestMeRejectsWrongMethod(t *testing.T) {
	// POST /api/me in dev mode → 405
}

func TestMeRejectsUnknownMode(t *testing.T) {
	for _, mode := range []string{"", "prod", "DEV", " dev"} {
		// GET /api/me → 500, and body does not contain "@"
	}
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd api && go test ./...`
Expected: FAIL, `undefined: newHandler`.

- [ ] **Step 4: Implement**

- `me.go`: `currentEmail` returns `"dev@localhost"` for `"dev"`, `errBadMode` for anything other than `"dev"` or `"aws"`. Leave the `"aws"` branch returning `errNoUser` until Task 2.
- `main.go`: `newHandler` registers `GET /{$}` (writes `ok`) and `GET /api/me` (maps `errNoUser` → 401, `errBadMode` → 500, else writes JSON `{"email": …}` with `encoding/json`). `main` sets `slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))`, reads `AUTH_MODE`, logs `slog.Error` at startup if it is not `dev` or `aws`, and runs `&http.Server{Addr: ":8080", Handler: newHandler(mode), ReadHeaderTimeout: 10 * time.Second}`. When `ListenAndServe` fails, it logs and exits 1. The handler logs rejections at `Warn` with the reason only.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd api && go vet ./... && go test ./...`
Expected: PASS.

- [ ] **Step 6: Verify the gow loop by hand**

Run: `cd api && AUTH_MODE=dev go tool gow run .` and, in another shell, `curl -s localhost:8080/api/me`.
Expected: `{"email":"dev@localhost"}`. Change the `ok` text in `main.go` and save. gow restarts, and `curl -s localhost:8080/` shows the new text. Revert the change.

- [ ] **Step 7: Commit**

```bash
git add api && git commit -m "feat(api): net/http server with dev AUTH_MODE and gow tool"
```

---

### Task 2: `aws` mode from the adapter's request-context header

**Files:**
- Modify: `api/me.go`, `api/me_test.go`
- Create: `api/testdata/request-context.json`

**Interfaces:**
- Consumes: `newHandler`, `currentEmail`, `errNoUser` from Task 1.

- [ ] **Step 1: Add the fixture**

`api/testdata/request-context.json` is a realistic HTTP API v2 `requestContext` (pretty-printed). It has `accountId`, `apiId`, `domainName`, `http` (`method` `GET`, `path` `/api/me`, `sourceIp` `192.0.2.1`), `requestId`, `routeKey` `GET /api/me`, `stage` `$default`, `timeEpoch`, and `authorizer.jwt` with `scopes: null` and `claims` holding only strings: `aud`, `auth_time`, `cognito:username`, `email` = `person@example.com`, `email_verified` = `"true"`, `exp`, `iat`, `iss` = `https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE`, `sub`, `token_use` = `id`.

- [ ] **Step 2: Write the failing tests**

Add a helper `fixture(t) string` that reads the file and returns it single-line via `json.Compact`.

```go
func TestMeAWS(t *testing.T) {
	rr := get(t, "aws", "GET", "/api/me", fixture(t))
	// want 200 and body {"email":"person@example.com"}
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
	// each → 401, body does not contain "@"
}

func TestMeDevIgnoresRequestContext(t *testing.T) {
	// dev mode with fixture(t) header → {"email":"dev@localhost"}
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd api && go test ./...`
Expected: `TestMeAWS` FAILS with 401. The other tests pass.

- [ ] **Step 4: Implement the `aws` branch in `currentEmail`**

Unmarshal the header into an anonymous struct that declares only `Authorizer.JWT.Claims.Email string` (JSON tags `authorizer`, `jwt`, `claims`, `email`). Any unmarshal error, or an empty email, returns `errNoUser`. Other claims are ignored.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd api && go test ./...`
Expected: PASS.

- [ ] **Step 6: Verify against the running server**

Run: `cd api && AUTH_MODE=aws go run .`, then
`curl -s -H "x-amzn-request-context: $(jq -c . testdata/request-context.json)" localhost:8080/api/me`
Expected: `{"email":"person@example.com"}`. Without the header: `401`.

- [ ] **Step 7: Commit**

```bash
git add api && git commit -m "feat(api): aws AUTH_MODE reads email claim from x-amzn-request-context"
```

---

### Task 3: Container image

**Files:**
- Create: `api/Dockerfile`

**Interfaces:**
- Consumes: the `api/` module from Tasks 1–2.
- Produces: an image whose entrypoint is `/server`, with the adapter at `/opt/extensions/lambda-adapter`. T004 pushes it to ECR and sets `AUTH_MODE=aws`.

- [ ] **Step 1: Write `api/Dockerfile`**

- Build stage: `FROM --platform=$BUILDPLATFORM golang:1.27 AS build`, `ARG TARGETOS TARGETARCH`, copy `go.mod`/`go.sum` and run `go mod download` first for layer caching, then copy the source and run `CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /out/server .`
- Runtime stage: `FROM gcr.io/distroless/static-debian12:nonroot`, then exactly
  `COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter`,
  `COPY --from=build /out/server /server`, `ENTRYPOINT ["/server"]`. No `EXPOSE`, no `AUTH_MODE` default.

- [ ] **Step 2: Build**

Run: `docker build --platform linux/arm64 -t proof-api api`
Expected: the build succeeds.

- [ ] **Step 3: Verify the adapter is in place**

Run: `docker create --name proof-check proof-api && docker cp proof-check:/opt/extensions/lambda-adapter - | tar -t; docker rm proof-check`
Expected: prints `lambda-adapter`.

- [ ] **Step 4: Verify the server runs without Lambda**

Run: `docker run --rm -d --name proof-run -e AUTH_MODE=dev -p 8080:8080 proof-api && curl -s localhost:8080/api/me; docker stop proof-run`
Expected: `{"email":"dev@localhost"}`. The adapter does not start outside Lambda.

- [ ] **Step 5: Commit**

```bash
git add api/Dockerfile && git commit -m "feat(api): multi-stage image with Lambda Web Adapter 1.1.0"
```

---

### Task 4: SPA in dev mode, config.json, runtime email check, typed build

**Files:**
- Create: `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`, `web/public/config.json`, `web/src/config.ts`, `web/src/api.ts`, `web/src/boot.ts`, `web/src/main.tsx`, `web/src/config.test.ts`, `web/src/api.test.ts`, `web/src/boot.test.ts`, `README.md`
- Modify: `.gitignore` (add `node_modules/`)

**Interfaces:**
- Produces (`config.ts`):
  ```ts
  export type DevConfig = { authMode: "dev"; apiBaseUrl: string };
  export type CognitoConfig = { authMode: "cognito"; apiBaseUrl: string; cognitoDomainUrl: string; clientId: string };
  export type Config = DevConfig | CognitoConfig;
  export function parseConfig(raw: unknown): Config;            // throws Error naming the bad field
  export function loadConfig(fetchFn?: typeof fetch): Promise<Config>; // GET /config.json, cache: "no-cache"
  ```
- Produces (`api.ts`):
  ```ts
  export function parseMe(body: unknown): string;               // throws unless nonempty string `email`
  export function fetchEmail(apiBaseUrl: string, idToken: string | null, fetchFn?: typeof fetch): Promise<string>;
  ```
- Produces (`boot.ts`):
  ```ts
  export type BootEnv = {
    href: string;                          // location.href
    store: Pick<Storage, "getItem" | "setItem" | "removeItem">; // sessionStorage
    now: number;                           // Date.now()
    fetchFn: typeof fetch;
    replaceUrl(path: string): void;        // history.replaceState(null, "", path)
    assign(url: string): void;             // location.assign(url)
  };
  export function boot(env: BootEnv): Promise<string | null>; // the email, or null when navigating away
  ```
- The `config.json` schema above is the contract T004's deploy writes.

- [ ] **Step 1: Scaffold by hand (no `create-vite` template)**

First, add `node_modules/` to the root `.gitignore`, so that `git check-ignore web/node_modules` matches. Then:

```bash
mkdir -p web/src web/public && cd web && npm init -y
npm install react react-dom
npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom @types/node
```
In `package.json`, set `"private": true` and `"type": "module"`, and set the scripts to `"dev": "vite"`, `"build": "tsc && vite build"`, `"preview": "vite preview"`, `"test": "node --test \"src/**/*.test.ts\""`.
In `tsconfig.json`, set `target` `ES2022`, `lib` `["ES2022","DOM","DOM.Iterable"]`, `module` `ESNext`, `moduleResolution` `bundler`, `jsx` `react-jsx`, `strict`, `noEmit`, `allowImportingTsExtensions`, `verbatimModuleSyntax`, `erasableSyntaxOnly` (so Node can run the `.ts` tests), `skipLibCheck`, and `types` `["node"]`. Include `src` and `vite.config.ts`. Imports use `.ts` extensions.
`vite.config.ts`: `plugins: [react()]`, `server.proxy: { "/api": "http://localhost:8080" }`. `vite preview` inherits the proxy.
`web/public/config.json`: `{"authMode": "dev", "apiBaseUrl": ""}`.

- [ ] **Step 2: Write the failing tests**

`src/config.test.ts`:
```ts
test("parses dev", () => assert.deepEqual(parseConfig({ authMode: "dev", apiBaseUrl: "" }), { authMode: "dev", apiBaseUrl: "" }));
test("parses cognito", /* all four fields round-trip */);
test("rejects", () => {
  for (const bad of [null, "x", {}, { authMode: "prod", apiBaseUrl: "" },
    { authMode: "cognito", apiBaseUrl: "https://a", cognitoDomainUrl: "https://d" },                 // no clientId
    { authMode: "cognito", apiBaseUrl: "https://a", cognitoDomainUrl: "d.example", clientId: "c" }]) // not https
    assert.throws(() => parseConfig(bad));
});
test("committed public/config.json is valid dev config", /* readFileSync + JSON.parse + parseConfig → authMode "dev" */);
```
`src/api.test.ts`:
```ts
test("parseMe accepts", () => assert.equal(parseMe({ email: "a@b.c" }), "a@b.c"));
test("parseMe rejects", () => { for (const b of [null, "x", [], {}, { email: "" }, { email: 5 }]) assert.throws(() => parseMe(b)); });
test("fetchEmail URL", /* fake fetch records URL: "" → "/api/me"; "https://x.example/" → "https://x.example/api/me"; "https://x.example" → same */);
test("Authorization only with token", /* token "t" → header "Bearer t"; null → no Authorization header */);
test("non-2xx rejects with status", /* fake 401 → rejects, message contains "401" */);
test("bad body rejects", /* fake 200 {"name":"x"} → rejects */);
```
`src/boot.test.ts`:
```ts
test("dev mode", /* fake fetch: "/config.json" → {"authMode":"dev","apiBaseUrl":""}, "/api/me" → {"email":"dev@localhost"};
  boot(env) resolves "dev@localhost"; the /api/me request has no Authorization header; assign and replaceUrl not called */);
test("bad config.json rejects", /* "/config.json" → {"authMode":"prod"} → rejects */);
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL, cannot find module `./config.ts`.

- [ ] **Step 4: Implement `config.ts`, `api.ts`, `boot.ts`, `index.html`, `main.tsx`**

- `fetchEmail` strips trailing `/` from `apiBaseUrl` and appends `/api/me`.
- `boot`: `loadConfig(env.fetchFn)`, then `fetchEmail(cfg.apiBaseUrl, null, env.fetchFn)`. `cognito` mode throws "not implemented" until Task 5.
- `index.html`: `<title>Proof</title>`, `<div id="root">`, module script `/src/main.tsx`.
- `main.tsx`: create the root and render `<main><h1>Proof</h1><p>Loading…</p></main>`. Then call `boot` with the real `location.href`, `sessionStorage`, `Date.now()`, `fetch`, `history.replaceState`, and `location.assign`. On an email, render it in `<p id="email">`. On `null`, keep "Loading…". On failure, render `<p role="alert">{message}</p>`. Bootstrapping happens outside React components, so StrictMode never runs the code exchange twice.

- [ ] **Step 5: Run tests and the typed build**

Run: `cd web && npm test && npm run build`
Expected: tests PASS, `tsc` reports no errors, `dist/` holds the bundle and `config.json`.

- [ ] **Step 6: Verify the two-process loop**

Run `AUTH_MODE=dev go tool gow run .` in `api/` and `npm run dev` in `web/`. Open `http://localhost:5173`.
Expected: the page shows `dev@localhost`. Edit the `<h1>` text: Vite reloads it. Stop Go: a reload shows an error in `role="alert"`, not a blank page. Then run `npm run preview` (the production bundle, port 4173) with Go running: the page shows `dev@localhost`.

- [ ] **Step 7: Write `README.md`**

Keep it short. Cover the dev loop (the two commands above), tests (`cd api && go test ./...`, `cd web && npm test && npm run build`), and the image build (`docker build --platform linux/arm64 -t proof-api api`). Link the ADRs.

- [ ] **Step 8: Commit**

```bash
git status --short   # must not list web/node_modules
git add .gitignore web README.md && git commit -m "feat(web): SPA with runtime config and checked /api/me call"
```

---

### Task 5: Cognito Hosted UI sign-in with PKCE

**Files:**
- Create: `web/src/auth.ts`, `web/src/auth.test.ts`
- Modify: `web/src/boot.ts`, `web/src/boot.test.ts`

**Interfaces:**
- Consumes: `CognitoConfig`, `fetchEmail`, `BootEnv`, `boot` from Task 4.
- Produces (`auth.ts`):
  ```ts
  export type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;
  export type SignIn = { idToken: string } | { redirectTo: string };
  export function randomString(): string;                       // 32 random bytes, base64url, no padding
  export function codeChallenge(verifier: string): Promise<string>; // base64url(SHA-256(verifier))
  export function authorizeUrl(cfg: CognitoConfig, redirectUri: string, challenge: string, state: string): string;
  export function idTokenExpiry(idToken: string): number;      // payload `exp` × 1000; throws if not a JWT with numeric exp
  export function exchangeCode(cfg: CognitoConfig, code: string, verifier: string, redirectUri: string,
                               fetchFn?: typeof fetch): Promise<{ idToken: string; expiresAt: number }>; // expiresAt = idTokenExpiry(id_token)
  export function signIn(cfg: CognitoConfig, url: URL, store: KeyValueStore, now: number,
                         fetchFn?: typeof fetch): Promise<SignIn>;
  ```
  Store keys: `pkce_state`, `pkce_verifier`, `session` (JSON `{idToken, expiresAt}`). `redirectUri` is `url.origin + "/"`.

- [ ] **Step 1: Write the failing tests in `src/auth.test.ts`**

Use a `memoryStore()` helper backed by a `Map`, and a `jwt(payload)` helper that returns `base64url({"alg":"none"}) + "." + base64url(JSON payload) + ".sig"`. Use `cfg = { authMode: "cognito", apiBaseUrl: "https://api.example", cognitoDomainUrl: "https://proof.auth.us-west-2.amazoncognito.com", clientId: "client123" }` and a fake fetch that records calls.

```ts
test("codeChallenge matches RFC 7636 Appendix B", async () =>
  assert.equal(await codeChallenge("dBjftJeZ4CVP-mJ92IqEdcWbE-VwmGgXJ4jAvIGfTbo"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"));
test("randomString", () => { const a = randomString(); assert.match(a, /^[A-Za-z0-9_-]{43}$/); assert.notEqual(a, randomString()); });
test("authorizeUrl", /* origin+pathname === cfg.cognitoDomainUrl + "/oauth2/authorize"; params response_type=code,
  client_id=client123, redirect_uri, scope="openid email", code_challenge_method=S256, code_challenge, state */);
test("no session → redirect with stored state and verifier", /* signIn(cfg, new URL("https://app.example/"), store, now)
  → redirectTo; its state === store pkce_state; its code_challenge === await codeChallenge(store pkce_verifier); fetch not called */);
test("callback exchanges code", /* URL https://app.example/?code=abc&state=S with store pkce_state=S, pkce_verifier=V;
  idToken = jwt({ email: "person@example.com", exp: nowSec + 300 }); fake 200 {"id_token": idToken, "expires_in": 3600}
  (ID token lifetime 5 min, access token 1 h). Assert one POST to cfg.cognitoDomainUrl+"/oauth2/token",
  Content-Type application/x-www-form-urlencoded, no Authorization header, body grant_type=authorization_code,
  client_id=client123, code=abc, code_verifier=V, redirect_uri=https://app.example/;
  result {idToken}; store session expiresAt === (nowSec + 300) * 1000, not now + 3_600_000; pkce keys removed */);
test("idTokenExpiry", /* jwt({exp: 1795000000}) → 1795000000000; "not-a-jwt", jwt({}), jwt({exp: "x"}) → throw */);
test("state mismatch rejects without fetch", /* ?code=abc&state=EVIL, store state S → rejects; fetch not called */);
test("callback with no stored state rejects without fetch", /* refresh after a completed sign-in */);
test("Hosted UI error is shown, not retried", /* ?error=access_denied&error_description=User+cancelled → rejects,
  message contains "User cancelled"; no redirectTo */);
test("valid session is reused", /* session expiresAt = now + 10 min → {idToken}; fetch not called */);
test("near-expiry session forces sign-in", /* session expiresAt = now + 30 s → redirectTo */);
test("token endpoint failure rejects", /* fake 400; fake 200 without id_token; fake 200 with id_token "garbage" → all reject */);
```
Add to `src/boot.test.ts`. Use a cognito `/config.json` with `cfg` and `apiBaseUrl` `https://api.example/`, and a fake fetch that routes on URL:
```ts
test("successful callback end to end", /* href "https://app.example/?code=abc&state=S", store pkce_state=S, pkce_verifier=V;
  token endpoint → {"id_token": jwt({email, exp: nowSec + 3600})}; "https://api.example/api/me" → {"email":"person@example.com"}.
  boot resolves "person@example.com"; the /api/me request carries "Authorization: Bearer <that id_token>";
  replaceUrl called once with "/"; assign not called */);
test("callback failure still cleans the URL", /* href "?error=access_denied&error_description=User+cancelled" →
  rejects with "User cancelled"; replaceUrl called with "/"; assign not called */);
test("no session redirects", /* href "https://app.example/" → resolves null; assign called once with the authorize URL; no /api/me call */);
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL, cannot find module `./auth.ts`.

- [ ] **Step 3: Implement `auth.ts`**

Use `crypto.getRandomValues`, `crypto.subtle.digest("SHA-256", …)`, and `btoa`, then make the result base64url. `idTokenExpiry` base64url-decodes the middle segment with `atob` and parses it as JSON. The order inside `signIn`: `error` param → throw. `code` param → check state, exchange, store the session, return the token. A valid session → return it. Otherwise → store a new state and verifier, return `redirectTo`. Remove the PKCE keys before the exchange, so a failed exchange cannot be replayed.

- [ ] **Step 4: Wire into `boot.ts`**

When `cfg.authMode === "cognito"`: `const url = new URL(env.href)`. When `url.search` contains `code` or `error`, call `env.replaceUrl("/")` after `signIn` settles, whether it succeeds or fails. On `redirectTo`, call `env.assign` and resolve `null`. On `idToken`, return `fetchEmail(cfg.apiBaseUrl, idToken, env.fetchFn)`. `main.tsx` does not change.

- [ ] **Step 5: Run tests and the typed build**

Run: `cd web && npm test && npm run build`
Expected: PASS, no `tsc` errors.

- [ ] **Step 6: Verify the cognito redirect locally**

Temporarily replace `web/public/config.json` with a cognito config that uses the test values above. Run `npm run dev` and open `http://localhost:5173`.
This checks the real browser globals that `boot.test.ts` replaces with fakes. The successful callback is covered there.
Expected: the browser navigates to `https://proof.auth.us-west-2.amazoncognito.com/oauth2/authorize?...` with all seven parameters. The host does not exist, which is fine. Then open `http://localhost:5173/?error=access_denied&error_description=User+cancelled`: the page shows "User cancelled", does not redirect, and the address bar returns to `/`. Restore `config.json` (`git checkout web/public/config.json`).

- [ ] **Step 7: Commit**

```bash
git add web && git commit -m "feat(web): Cognito Hosted UI sign-in with PKCE"
```

---

## Final verification (T002 acceptance)

- [ ] `cd api && go vet ./... && go test ./...`: PASS. This includes `GET /api/me` shape, aws-mode claim parsing, and missing/empty claim and unset `AUTH_MODE` rejections.
- [ ] `cd web && npm test && npm run build`: PASS, and `tsc` ran.
- [ ] `docker build --platform linux/arm64 -t proof-api api`: succeeds, and the adapter is present (Task 3, Step 3).
- [ ] Two-process loop shows `dev@localhost`, and a Go edit restarts the server (Task 1, Step 6; Task 4, Step 6).

## Handoff to T004

- Lambda env: `AUTH_MODE=aws`. Build the image for the Lambda architecture T004 chooses.
- Cognito app client: public (no secret), authorization-code grant, scopes `openid email`, callback and logout URL `https://<site origin>/`.
- HTTP API: route `GET /api/me` only. JWT authorizer audience = client id. CORS: the SPA origin, `GET`, `Authorization`.
- Deployed `config.json`: `{"authMode":"cognito","apiBaseUrl":"<HttpApi.url>","cognitoDomainUrl":"<UserPoolDomain.baseUrl()>","clientId":"<client id>"}` with a short cache lifetime.

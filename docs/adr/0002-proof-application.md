# ADR 0002: Proof application

- **Status:** Proposed
- **Date:** 2026-11-21
- **Author:** Glenn Bach
- **Scope:** The Go API and the React SPA. The AWS platform is [ADR 0001](0001-serverless-go-platform-architecture.md).

---

## Context

The proof is one browser page that calls a Go API and shows the current user's email address. It has no product domain and stores nothing.

[ADR 0001](0001-serverless-go-platform-architecture.md) deploys the SPA to S3 and CloudFront and the API to Lambda behind Amazon API Gateway. API Gateway exists only in the cloud. A laptop runs the same Go server directly.

An earlier Go and React application (billing) is the prior workflow, not the product to copy. That API is Echo, GORM, and Cobra, in a long-running container that also serves the SPA over TLS. Its UI is JavaScript, React 18, Vite 5, MUI, React Router, and Formik. This proof keeps two ideas from that workflow: a multi-stage container build for the Go binary, and a dev loop that does not require a rebuild to see a change. It does not keep the framework, the database, or the combined image.

---

## Decisions

### 1. One HTTP server, and Lambda only in the cloud

**Decision.** The API is a `net/http` server routed with the standard-library `ServeMux`. One binary runs on a laptop and in Lambda. The container image includes the AWS Lambda Web Adapter, which turns Lambda invocations into HTTP requests. Outside Lambda the adapter does not start.

The server listens on port 8080, the adapter's default. The adapter's readiness check calls `GET /` on localhost inside the Lambda. That route returns 200. API Gateway does not publish it.

**Rationale.** ADR 0001 already ships the API as a container image. The adapter lets that image stay an ordinary HTTP server. The standard-library router has had methods and path parameters since Go 1.22, which is enough for these routes.

**Alternatives considered.**
- *Echo, as in billing:* A proof with two routes does not earn a framework.
- *An in-process API Gateway adapter linked into `main`:* Fewer moving parts during cold start, at the cost of Lambda event types inside the program.
- *Cobra, as in billing:* That application grew a set of batch commands. This one has none.

**Consequences.**
- (+) The laptop and Lambda share one router.
- (−) Cold start includes the adapter's readiness poll. ADR 0001 already accepts container-image cold starts.
- (−) On AWS, claim data arrives in the `x-amzn-request-context` header. See Decision 3.

---

### 2. What the page shows

**Decision.** The SPA is one page. It fetches `GET /api/me` and shows the email address. The body is JSON:

```json
{ "email": "person@example.com" }
```

There is no second page, no client-side router, no component library, and no write. `GET /api/me` is the only route API Gateway publishes, and the JWT authorizer covers it. The browser's preflight `OPTIONS` never reaches a route. API Gateway's CORS configuration answers it. See Decision 5.

**Rationale.** The page proves that the SPA called the API and rendered the result. The email is the value the deployed ID token and the local dev user both have.

**Alternatives considered.**
- *A health page that never shows a user:* The fixed dev user would have nothing to do, and the screen would not show who the API believes is calling.
- *A form that posts a message held in process memory:* More behavior than the proof needs, and the value disappears whenever the process does.
- *The `name` claim, or the Cognito username:* `name` is often empty. The username is an account handle, not the value we want on the page. `email` is on the ID token when the pool uses email sign-in.

**Consequences.**
- (+) A failure to reach the API, or a missing email, is visible on the page.
- (−) The Cognito user pool must include `email` and put it on the ID token. Pool attributes are painful to change after creation. ADR 0001 already records that constraint.

---

### 3. How the API picks the current user

**Decision.** `AUTH_MODE` selects the current user.

- `dev`: the email is `dev@localhost`. The process does not read a token and does not call AWS.
- `aws`: the email is the `email` claim of the Cognito ID token. API Gateway has already checked the token. The adapter puts the API Gateway request context, encoded as JSON, in the `x-amzn-request-context` header. The header is the context object itself, with no outer `requestContext` key, so Go reads `authorizer.jwt.claims.email` from the decoded header. Claim values are strings. A missing or empty claim rejects the request.

  ```json
  {"authorizer":{"jwt":{"claims":{"email":"person@example.com"}}}}
  ```
- Any other value, including an unset variable, rejects `GET /api/me`.

Lambda is deployed with `AUTH_MODE=aws`. A laptop sets `AUTH_MODE=dev`.

`GET /` stays unauthenticated in both modes so the adapter's readiness check does not need a user.

**Rationale.** Local work must not depend on AWS. A Lambda whose setting is missing must not silently run as the dev user.

**Alternatives considered.**
- *Checking a dev-pool JWT on the laptop:* Rejected. It makes AWS a requirement for ordinary development.
- *Treating a missing claim header as the dev user:* Rejected. A misconfigured Lambda would accept calls as `dev@localhost`.

**Consequences.**
- (+) The JSON shape is the same locally and on AWS.
- (−) `AUTH_MODE=aws` trusts `x-amzn-request-context`. In the adapter source (v0.9.1 and v1.1.0), the adapter builds that header from the Lambda event and sets it with `HeaderMap::insert`, which replaces a copy the client sent. The follow-up confirms this on a deployed environment. The server reads the header only when `AUTH_MODE=aws`.

---

### 4. Sign-in, and the shape of the SPA

**Decision.** The SPA is TypeScript, built with Vite and React. Deployed sign-in is the Cognito Hosted UI, using the authorization-code grant with PKCE. The SPA sends the ID token in `Authorization: Bearer` and contains no login form and no Cognito SDK. Local configuration skips sign-in and calls the API with no token. Localhost is not a Cognito callback or logout URL.

**Rationale.** The Hosted UI is the whole sign-in screen. A form in the SPA would be a second product. The ID token is the token that carries `email`. TypeScript checks the SPA's own code against the declared response type. Billing's UI was JavaScript.

TypeScript cannot see what Go sends, so the contract is checked on both sides:
- The SPA checks at runtime that the response has a nonempty `email` string. Otherwise it shows an error.
- A Go test checks that `GET /api/me` returns `{"email": "..."}`.
- The production build runs `tsc` before `vite build`. Vite removes types without checking them.

**Alternatives considered.**
- *JavaScript, matching billing:* Faster to start, and weaker at checking how the SPA uses the response.
- *An email and password form in the page:* More UI, and another client of the Cognito API to maintain.
- *Sending the access token:* It does not carry `email`.

**Consequences.**
- (+) Cognito owns the sign-in screen.
- (−) No compiler checks the contract between Go and the SPA. A change in Go's response is caught by the Go test, or by the SPA's runtime check, not by the build.
- (−) Callback and logout URLs are the deployed site origins only. Proving sign-in requires a deployed environment.
- (−) The SPA stores the tokens it receives from the Hosted UI redirect long enough to call the API. Session storage is enough for this proof.

---

### 5. One bundle, configured at startup

**Decision.** Every environment runs the same production JavaScript bundle. On startup the SPA fetches `/config.json` from its own origin.

`web/public/config.json` is the local file. It sets `authMode` to `dev` and leaves the API base URL empty, so the browser calls `/api/me` on the Vite origin. Each deployed bucket gets its own file at deploy time. That file sets `authMode` to `cognito`, the API Gateway base URL, and the User Pool id, client id, and Hosted UI domain. Those values are public. They are not secrets. See ADR 0001.

On AWS, the HTTP API handles CORS. It allows the environment's SPA origin, method `GET`, and header `Authorization`, and it answers preflight requests itself. Go sets no CORS headers in either environment. The Vite dev server proxies `/api` to the Go process, so the browser's local calls are same-origin and do not depend on CORS.

**Rationale.** ADR 0001 promotes one commit through QA and prod. A per-environment rebuild would mean QA never ran the prod bundle. One fetch path keeps local and deployed startup the same.

**Alternatives considered.**
- *Injecting endpoints at `npm run build`:* One bundle per environment. Rejected for the reason above.
- *Vite environment variables locally, and `config.json` only when deployed:* Two configuration mechanisms for one SPA.

**Consequences.**
- (+) A pool or URL change does not require a new JavaScript build.
- (−) Cache `config.json` briefly, or a changed file stays hidden behind a long-lived cache.
- (−) The API and the SPA have different origins on AWS. Each environment's HTTP API must list that environment's SPA origin. See ADR 0001, Decision 8.
- (+) Go has no CORS code. A request that reaches Go has already passed API Gateway's CORS handling and the JWT authorizer.

---

### 6. Local development

**Decision.** Daily work is the Go server under `gow` and the Vite dev server on the Mac, with `AUTH_MODE=dev`. `gow` watches the module and restarts the server when a Go file changes. It is a tool dependency in `api/go.mod` (`go get -tool github.com/mitranim/gow`), run as `go tool gow run .`, so every laptop uses the same version. Vite proxies `/api` to `http://localhost:8080` and leaves the path unchanged, so `/api/me` is `/api/me` locally and on API Gateway. Docker is not part of the loop. The repository has no compose file.

**Rationale.** The local process is the HTTP server the adapter will call. The slow part of the billing loop was rebuilding an image to see a Go change. MySQL, Redis, and mail are not parts of this proof.

**Alternatives considered.**
- *Plain `go run`:* It needs no tool, but it compiles once. After each Go change the old server keeps running until someone restarts it.
- *`gow` installed globally with `go install`:* This has worked before, but each laptop then runs whatever version it last installed.
- *Billing's compose stack, with the API in a container:* Rebuilds on each Go change, and starts services this proof does not use.
- *A compose file checked in and left unused:* Rejected with the database in ADR 0001. Add a compose file when an application has a schema.

**Consequences.**
- (+) Edit, save, and refresh, with no AWS account activity. `gow` restarts Go, and Vite reloads the page.
- (−) `gow` needs Go 1.24 or later for the `tool` directive. On macOS its file watcher may need the Xcode command-line tools to build.
- (−) API Gateway, the JWT authorizer, and the Hosted UI are untested until a deploy.

---

### 7. Container image

**Decision.** A multi-stage Dockerfile builds the Go binary. The runtime image contains that binary and the Lambda Web Adapter, pinned to a fixed version (v1.1.0 when this was written). It does not contain the SPA, a TLS certificate, or a listener for public HTTPS. CloudFront serves the SPA. API Gateway terminates the public request.

**Rationale.** ADR 0001 already splits the SPA and the API. Billing's image builds the SPA into the API container and terminates TLS in the process. Copying that image would fight the platform. The part worth keeping is the multi-stage Go build.

**Alternatives considered.**
- *Billing's combined image:* SPA assets, a self-signed certificate, and TLS inside the Go process.
- *Building the SPA and the API as one artifact:* Couples their deploys and duplicates what S3 and CloudFront already do.

**Consequences.**
- (+) The image is only the API.
- (−) TLS and static files are not configured in Go. Local HTTP is enough.

---

### 8. Repository layout

**Decision.** `infra/` holds the Python CDK. `api/` is the Go module. `web/` is the Vite application.

**Rationale.** The repository holds three languages. A Go module at the root would make `infra` and `web` look like packages of that module.

**Alternatives considered.**
- *The Go module at the repository root*, with `web/` and `infra/` beside it.
- *Billing's nesting*, with the API and the SPA under one inner project directory.

**Consequences.**
- (+) Each language has one obvious place.
- (−) The Go module path is not the repository root.

---

## Consequences (overall)

**Positive**
- The laptop runs the whole proof with two processes and no AWS.
- The deployed path is the platform in ADR 0001: Hosted UI, HTTP API, JWT authorizer, Lambda.
- The SPA bundle that passes QA is the bundle that reaches prod.
- There is no database, no VPC, and no unused identity system to keep in sync.

**Negative and risks**
- Sign-in can only be proven on a deployed environment.
- `AUTH_MODE=aws` depends on the adapter's request-context header. See the follow-up.
- Container cold starts include the adapter's readiness poll.

## Open questions and follow-ups

1. On a deployed environment, send `GET /api/me` with a valid token and a forged `x-amzn-request-context` header that names another email. Confirm that the response shows the token's email. The adapter source says it replaces the header, and this request proves it for the pinned version. Repeat whenever the adapter version changes. Confirmed for adapter 1.1.0 on `swb-proof-dev`, 2026-11-23 (T006): the response showed the token's email, not the forged one.

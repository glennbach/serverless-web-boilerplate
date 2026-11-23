# serverless-web-boilerplate

The proof: a one-page React SPA that calls a Go API and shows the signed-in user's email address. It has no product domain and stores nothing. The point is to prove the platform: Cognito sign-in, API Gateway with a JWT authorizer, Lambda running a container image, and S3 plus CloudFront for the SPA.

- Platform: [ADR 0001](docs/adr/0001-serverless-go-platform-architecture.md)
- Application: [ADR 0002](docs/adr/0002-proof-application.md)
- Backlog: [TODO.md](TODO.md)

| Path | What it is |
|---|---|
| `api/` | Go module: `net/http` server, `Dockerfile` with the Lambda Web Adapter |
| `web/` | Vite + React + TypeScript SPA |
| `infra/` | Python CDK (from phase 2a) |
| `docs/` | ADRs and implementation plans |

## Phases

| Phase | Scope | Tasks | Status |
|---|---|---|---|
| 1 | The proof application, built and tested on a laptop | T001, T002 | Implemented ([plan](docs/plans/2026-11-22-proof-application.md)) |
| 2a | One dev environment on AWS, deployed by hand with `cdk deploy` | T003–T006 | Deployed and proven end to end (T005) ([plan](docs/plans/2026-11-22-dev-environment.md)) |
| 2b | Pipeline, QA, prod, WAF, and DNS | T007, T008 | Not started |

## Start a new project from this repo

A copy of this repository deploys as its own project, with its own stacks, User Pool, and URLs, once you change one value.

1. **Copy the repository with fresh history.** Clone it, delete `.git`, and run `git init`. Once this repository is on GitHub and marked as a template repository, "Use this template" does the same. Don't fork it: a fork shares this repository's history, and its pull requests target this repository by default.
2. **Set `projectName` in `infra/cdk.json` before the first deploy.** Use lowercase letters, digits, and hyphens. Start with a letter, don't end with a hyphen, and use at most 58 characters. Don't include `aws`, `amazon`, or `cognito` (see [ADR 0003](docs/adr/0003-deployed-names-from-project-name.md)). Choose a distinctive name, because Hosted UI prefixes are unique per region across all AWS accounts. A copy that keeps `swb-proof` would update this project's stacks in the same account.
3. **Bootstrap the account** if it has not been bootstrapped in `us-west-2`: `cdk bootstrap aws://<account>/us-west-2`.
4. **Deploy:** build the SPA and run `cdk deploy <projectName>-dev`, as described under [Deploy](#deploy).
5. **Create a user** with the `admin-create-user` command under [Deploy](#deploy).

---

## Phase 1: the proof application on a laptop

Phase 1 runs and tests everything without an AWS account. Every AWS code path is exercised locally with fixtures, so the first deploy only has to prove the infrastructure.

### Prerequisites

- Go 1.27.4 or later (`api/go.mod`). On macOS, the `gow` file watcher may need the Xcode command-line tools.
- Node.js 26 (`node --test` runs the TypeScript tests directly).
- Docker, only for the image build.
- `jq`, only for the `aws` mode example below.

### Run it

Two terminals:

```bash
# Terminal 1: the API on :8080, restarted by gow on every Go change
cd api && AUTH_MODE=dev go tool gow run .
```

```bash
# Terminal 2: the SPA on :5173, which proxies /api to :8080
cd web && npm install && npm run dev
```

Open <http://localhost:5173>. Expect:

- The page shows **dev@localhost**.
- Saving a `.go` file restarts the API. Refresh to see the change.
- Saving a file in `web/src` reloads the page.
- When the API is down, the page shows an error, not a blank screen.

To run the production bundle that every environment will get, run `npm run build && npm run preview` in `web/` and open <http://localhost:4173>. The API must still be running.

### Automated tests

```bash
cd api && go vet ./... && go test ./...
cd web && npm test && npm run build
```

| Suite | What it proves |
|---|---|
| `api/me_test.go` | `GET /` is open in every mode. Unknown paths return 404. `GET /api/me` returns exactly `{"email": ...}` as JSON. In `aws` mode the email comes from `authorizer.jwt.claims.email` in the `x-amzn-request-context` header ([fixture](api/testdata/request-context.json)). A missing, empty, or non-string claim returns 401. An unset or unknown `AUTH_MODE` returns 500. No error body contains an email. |
| `web/src/config.test.ts` | `config.json` is checked at startup, including the committed local file. |
| `web/src/api.test.ts` | The SPA's runtime check of the `/api/me` body, the API URL join, and the `Authorization` header. |
| `web/src/auth.test.ts` | Hosted UI PKCE: the RFC 7636 challenge, the authorize URL, the token exchange, state checks, cancelled sign-in, and expiry taken from the ID token's `exp`. |
| `web/src/boot.test.ts` | The page bootstrap, end to end, with faked Cognito and API responses: dev mode, a successful callback, a failed callback, the redirect, and a 401 that drops the stored token so the next load signs in again. |
| `npm run build` | `tsc` type-checks everything, including the tests, before `vite build`. |

### Try `aws` mode by hand

The API reads the user from the header that the Lambda Web Adapter sets on AWS. Send the fixture yourself:

```bash
cd api && AUTH_MODE=aws go run .
# in another terminal, from api/
curl -H "x-amzn-request-context: $(jq -c . testdata/request-context.json)" localhost:8080/api/me
# {"email":"person@example.com"}
curl -i localhost:8080/api/me   # 401
```

### Try `cognito` mode by hand

Point the SPA at a Hosted UI that does not exist, and watch it start sign-in:

```bash
cd web
echo '{"authMode":"cognito","apiBaseUrl":"","cognitoDomainUrl":"https://cognito.invalid","clientId":"client123"}' > public/config.json
npm run dev
```

- <http://localhost:5173> navigates to `https://cognito.invalid/oauth2/authorize?...`. The page fails to load, which is expected. The address bar shows `response_type`, `client_id`, `redirect_uri`, `scope=openid email`, `state`, `code_challenge_method=S256`, and `code_challenge`.
- <http://localhost:5173/?error=access_denied&error_description=User+cancelled> shows "Sign-in failed: User cancelled", does not redirect, and the address bar returns to `/`.

Restore the local config afterwards with `git checkout web/public/config.json`.

### Build the Lambda image

```bash
docker build --platform linux/arm64 -t proof-api api
docker run --rm -e AUTH_MODE=dev -p 8080:8080 proof-api   # the adapter does not start outside Lambda
curl localhost:8080/api/me                                  # {"email":"dev@localhost"}
```

The image contains the Go binary and Lambda Web Adapter 1.1.0 at `/opt/extensions/lambda-adapter`. It contains no SPA and no TLS.

### Not proven until phase 2a

The real Hosted UI and token endpoint, the API Gateway JWT authorizer and CORS, the adapter on Lambda, and the check that the adapter replaces a forged `x-amzn-request-context` header (T006).

---

## Phase 2a: the dev environment

`infra/` is one CDK stack, `swb-proof-dev` (`<projectName>-dev`, [ADR 0003](docs/adr/0003-deployed-names-from-project-name.md)), in `us-west-2`. Nothing is created in `us-east-1`. The stack contains:

- an S3 bucket and a CloudFront distribution for the SPA, on its `*.cloudfront.net` URL
- a Cognito User Pool, with its Hosted UI prefix domain and the SPA's PKCE client
- the `api/` image on Lambda, with `AUTH_MODE=aws` and X-Ray tracing
- an HTTP API with a JWT authorizer, CORS, and access logs
- the deployed `config.json`

See the [plan](docs/plans/2026-11-22-dev-environment.md).

### Prerequisites

- AWS credentials for the target account.
- Docker running, because `cdk deploy` builds the arm64 API image.
- `uv`.
- AWS CDK CLI 2.1149.0 or later. Older CLIs cannot read the assembly that the pinned `aws-cdk-lib` writes. Use `npx aws-cdk@2.1149.0 ...` if the installed `cdk` is older.

### Test

```bash
cd infra && uv run pytest -q
```

`infra/tests/test_proof_dev.py` checks the synthesized template:

- Nothing in it refers to `us-east-1`, and the bucket is private behind CloudFront Origin Access Control.
- The Cognito schema, the client's exact callback and logout URLs, and the classic Hosted UI on the prefix domain.
- The arm64 image, `AUTH_MODE=aws`, and active tracing.
- CORS for exactly the site origin, `GET /api/me` as the only route, behind the JWT authorizer.
- The JSON access-log format.
- The two SPA uploads and their cache headers, and that the local `config.json` is never uploaded.
- The stack outputs.
- The stack name and the Hosted UI prefix come from `projectName`, and an invalid name fails at synth.

### Deploy

```bash
aws sts get-caller-identity                     # the intended account
cd web && npm ci && npm test && npm run build    # one bundle for every environment
cd ../infra && uv run pytest -q
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-west-2   # once per account
cdk deploy swb-proof-dev
```

The deploy prints `SiteUrl`, `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `CognitoDomainUrl`, `ApiAccessLogGroup`, `ApiFunctionLogGroup`, and `ApiFunctionName`.

Hosted UI prefixes are unique per region across all AWS accounts. If `swb-proof-dev` is taken, change `projectName` in `infra/cdk.json`. That renames the stack too.

Self sign-up is off. Create a user, and Cognito emails a temporary password:

```bash
aws cognito-idp admin-create-user --region us-west-2 --user-pool-id "$POOL" \
  --username "$EMAIL" --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Open `SiteUrl`, sign in, and set a new password. The page shows the email. The full end-to-end check is Task 5 of the plan (T005).

### Tear down

```bash
cd infra && cdk destroy swb-proof-dev
```

This removes the bucket, the pool and its users, the API, and the stack's log groups. Some things remain:

- The `CDKToolkit` bootstrap stack, with the image and file assets it holds.
- One small log group, `/aws/lambda/swb-proof-dev-CustomS3AutoDeleteObjects…`. CDK's bucket-emptying handler creates it at runtime, and the stack does not own it.

`cdk destroy` synthesizes the app first, so `web/dist` must exist. Run `npm run build` in `web/` first.

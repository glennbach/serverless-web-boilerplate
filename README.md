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
| 2b | Pipeline, QA, prod, and WAF, on `*.cloudfront.net` URLs (no custom domain) | T007, T008 | Implemented ([plan](docs/plans/2026-11-23-platform.md)); go-live is T008 |

## Start a new project from this repo

A copy of this repository deploys as its own project, with its own stacks, User Pools, and URLs, once you change a few values.

1. **Copy the repository with fresh history.** Clone it, delete `.git`, run `git init`, and push it to a new GitHub repository with `master` as its branch. Once this repository is on GitHub and marked as a template repository, "Use this template" does the same. Don't fork it: a fork shares this repository's history, and its pull requests target this repository by default.
2. **Set `projectName` in `infra/cdk.json` before the first deploy.** Use lowercase letters, digits, and hyphens. Start with a letter, don't end with a hyphen, and use at most 58 characters. Don't include `aws`, `amazon`, or `cognito` (see [ADR 0003](docs/adr/0003-deployed-names-from-project-name.md)). Choose a distinctive name, because Hosted UI prefixes are unique per region across all AWS accounts. A copy that keeps `swb-proof` would update this project's stacks in the same account.
3. **Set `repository` (`owner/name`) and `connectionArn` in `infra/cdk.json`**, from the GitHub connection described under [One-time setup](#one-time-setup).
4. **Follow [One-time setup](#one-time-setup):** bootstrap `us-west-2` and `us-east-1`, deploy the pipeline once, and create users.

An AWS account holds at most three CloudFront flat-rate Free plans, and one project's two environments would use two of them. No environment is subscribed (see T012), so each runs pay-as-you-go, which costs about $9 per month per environment for WAF (about $7.30 from 2027-02-01).

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

## Phase 2b: the pipeline and two environments

`infra/` is a CDK pipeline, `swb-proof-pipeline` (`<projectName>-pipeline`), in `us-west-2`. A push to `build` on GitHub runs it. You deploy with `git push origin master:build`; a push to `master` alone runs nothing. It tests the Go API, the SPA, and the CDK. It builds the SPA and the API image once, then deploys them to QA, then prod after a manual approval. It updates itself first, so a change to the pipeline deploys the same way.

Each environment (`qa`, `prod`) is two stacks ([ADR 0003](docs/adr/0003-deployed-names-from-project-name.md)):

- `<projectName>-<env>-edge`, in `us-east-1`, holds the environment's WAF web ACL: a rate limit of 1,000 requests per 5 minutes per IP, plus three AWS managed rule groups.
- `<projectName>-<env>`, in `us-west-2`, holds:
  - an S3 bucket and a CloudFront distribution for the SPA, on its `*.cloudfront.net` URL, behind that web ACL
  - a Cognito User Pool, with its Hosted UI prefix domain and the SPA's PKCE client
  - the `api/` image on Lambda, with `AUTH_MODE=aws` and X-Ray tracing
  - an HTTP API with a JWT authorizer, CORS, and access logs
  - the environment's own `config.json`

QA keeps logs for a month and deletes everything with its stack. Prod keeps logs for six months, and its User Pool and log groups survive the deletion of its stack, with deletion protection on the pool. After each environment deploys, a smoke step checks that its `config.json` is the deployed one and that `/api/me` without a token returns 401.

See the [plan](docs/plans/2026-11-23-platform.md). Phase 2a's hand-deployed dev stack became the pipeline's dev stack. T010 removed dev on 2026-11-24, so QA is now the first environment ([plan](docs/plans/2026-11-24-remove-dev-environment.md)).

### Prerequisites

- AWS credentials for the target account. The account's plan must be Paid, not the AWS Free Tier account plan, for the CloudFront flat-rate Free plan. That plan is optional.
- Docker running, for `cdk diff` and `cdk deploy` of the pipeline.
- `uv`, Node.js 26, and Go, for the tests.
- AWS CDK CLI 2.1149.0 or later. Older CLIs cannot read the assembly that the pinned `aws-cdk-lib` writes. Use `npx aws-cdk@2.1149.0 ...` if the installed `cdk` is older.

### Test

```bash
cd infra && uv run pytest -q
```

| Suite | What it proves |
|---|---|
| `infra/tests/test_environment.py` | One environment's stacks, synthesized for QA and prod. The pool schema, the client's exact callback and logout URLs, CORS for exactly the site origin, `GET /api/me` behind the JWT authorizer, the arm64 image, the JSON access logs, the SPA uploads, their cache headers, and that the local `config.json` is never uploaded. Log retention and what prod keeps. The logical ids of the deployed QA and prod stacks don't change. The web ACL fits the flat-rate Free plan, and the distribution stays eligible for it. Names come from `projectName`, and invalid names fail at synth. |
| `infra/tests/test_pipeline.py` | QA, then prod after approval, with a smoke step after each; there is no Dev stage. The source is `build` on GitHub. The synth step runs every test suite. Every environment deploys the same image and SPA files. Missing pipeline settings fail at synth. |

### One-time setup

1. **Put the repository on GitHub** with `master` as its default branch.
2. **Create a connection.** In the AWS console, go to Developer Tools → Settings → Connections, in `us-west-2`, and create a GitHub connection. When it asks for a GitHub App, choose **Install a new app** to install "AWS Connector for GitHub" on the account that owns the repository, with access to this repository only. Don't skip it: without the app, the connection can still show `Available` and the pipeline can still fetch code, but pushes never start it. To check, open GitHub → Settings → Applications → Installed GitHub Apps; "AWS Connector for GitHub" must be listed there with this repository under Repository access. When the connection's status is `Available`, put its ARN in `connectionArn` and `owner/name` in `repository` in `infra/cdk.json`. Commit and push.
3. **Bootstrap both regions**, once per account:
   ```bash
   cd infra && cdk bootstrap aws://<account>/us-west-2 aws://<account>/us-east-1
   ```
4. **Deploy the pipeline once by hand.** After this, it deploys itself.
   ```bash
   # the pipeline reads build, and its first run must see step 2's settings
   git push origin master:build
   cd web && npm ci && npm run build
   cd ../infra && cdk deploy swb-proof-pipeline
   ```
   CDK may also create `swb-proof-pipeline-support-us-east-1`, which holds pipeline artifacts for the `us-east-1` stacks.
5. **Approve prod** when the first run reaches `PromoteToProd`.
6. **Subscribe each distribution to the flat-rate Free plan (optional).** In the CloudFront console, choose the Free plan for each of the two distributions, and keep the attached web ACL. If the account cannot subscribe, the environments run pay-as-you-go.
7. **Create users.** Self sign-up is off. List each environment's site URL and user pool ID; drop the `[?...]` filter to see every output:
   ```bash
   for env in qa prod; do
     echo "== $env"
     aws cloudformation describe-stacks --region us-west-2 --stack-name "swb-proof-$env" \
       --query "Stacks[0].Outputs[?OutputKey=='SiteUrl' || OutputKey=='UserPoolId'].[OutputKey,OutputValue]" \
       --output text
   done
   ```
   For each environment, set `POOL` to its `UserPoolId` and create a user, and Cognito emails a temporary password:
   ```bash
   POOL=$(aws cloudformation describe-stacks --region us-west-2 --stack-name swb-proof-qa \
     --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
   aws cognito-idp admin-create-user --region us-west-2 --user-pool-id "$POOL" \
     --username "$EMAIL" --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
     --desired-delivery-mediums EMAIL
   ```
   Open the stack's `SiteUrl`, sign in, and set a new password. The page shows the email.

To inspect one stack, select it by construct path, for example `cdk diff swb-proof-pipeline/Qa/Site` (`cdk ls` lists them all).

### Deploying and promoting

**Deploy** a commit by putting `master` onto `build`:

```bash
git push origin master:build
```

The pipeline tests it and puts it in QA. A push to `master` alone deploys nothing. To **promote** the commit to prod, approve `PromoteToProd` in the CodePipeline console. An approval expires after 7 days, and the run must then be started again.

Only fast-forward `build` from `master`, and never force-push it. To roll back, revert on `master` and deploy. Moving `build` back to a commit where `BRANCH` in `infra/pipeline.py` is still `master` would make the pipeline watch `master` again.

### Tear down

Do these in order:

1. Cancel each distribution's Free plan subscription, if it has one. A subscribed distribution cannot be deleted.
2. Delete `swb-proof-prod` and `swb-proof-qa`, for example with `aws cloudformation delete-stack --region us-west-2 --stack-name swb-proof-qa`. Then delete the two `-edge` stacks in `us-east-1`. WAF refuses to delete a web ACL while a distribution still uses it.
3. Run `cdk destroy swb-proof-pipeline`. `cdk destroy` synthesizes the app first, so `web/dist` must exist. Run `npm run build` in `web/` first.
4. Delete `swb-proof-pipeline-support-us-east-1` in `us-east-1`, if it exists. `cdk destroy swb-proof-pipeline` does not remove it.
5. Delete the leftover `/aws/lambda/swb-proof-<env>-…` log groups in `us-west-2` and `us-east-1`. Custom-resource Lambdas created them, CloudFormation never managed them, and they never expire.

Some things remain:

- Prod's User Pool and log groups. To delete them, turn off the pool's deletion protection, then delete the pool and the log groups by hand.
- The pipeline's artifact bucket in `us-west-2`, and the support stack's replication bucket in `us-east-1`. Both are retained. Empty and delete them by hand.
- The `CDKToolkit` bootstrap stacks, with the image and file assets they hold.

### Adding a custom domain later

The Proof has no domain, so every environment uses its `*.cloudfront.net` URL ([ADR 0001](docs/adr/0001-serverless-go-platform-architecture.md), Decision 8). To add a domain, amend Decision 8 first. Then:

- Add a Route 53 hosted zone in its own stack, retained when that stack is deleted.
- Add an ACM certificate to `EdgeStack`, validated by DNS. CloudFront requires the certificate to be in `us-east-1`.
- Give the distribution `domain_names` and `certificate`.
- Add alias records.
- Change `site_url` to the custom domain. It already drives the Cognito callback and logout URLs and the API's CORS origin.

A flat-rate plan covers one apex domain per distribution.

# TODO — serverless-web-boilerplate
<!-- todo-format: 2; next-id: 10 -->

## P0 — Critical / Blocking

## P1 — High Priority

## P2 — Backlog

- [ ] **T008** Build the full platform #feature #infra
  - Acceptance: A push to main deploys dev and then QA through CodePipeline. Prod deploys after manual approval. Each environment is served on its *.cloudfront.net URL behind its own WAF web ACL, and sign-in works in each. Each distribution stays eligible for the CloudFront flat-rate Free plan and is subscribed where the account allows (nice-to-have: a refusal is recorded here, and that environment runs pay-as-you-go).
  - Context: Follows the T007 plan: docs/plans/2026-11-23-platform.md (Tasks 1-3 build infra/, Task 4 is the go-live run by hand).
  - Blocked by: T007,T009
  - Claimed: claude | 2026-11-23 | feat/platform

## Done (recent)

- [x] **T007** Plan the full platform: pipeline, QA, prod, and WAF #docs #infra
  - Acceptance: Plan written under docs/plans/ and linked here. Covers CodePipeline and CodeBuild (one image and one SPA bundle per commit, per-environment config.json, manual approval before prod), QA and prod stacks, and WAF. Every environment uses its *.cloudfront.net URL, with no hosted zone, certificate, or custom domain (ADR 0001 Decision 8 amended). Settles ADR 0001 open questions 2-4: stack layout, log retention, and the CloudFront flat-rate Free plan. The user has vetted it.
  - Context: Phase 2b. Source: docs/adr/0001-serverless-go-platform-architecture.md. Plan: docs/plans/2026-11-23-platform.md. Decided 2026-11-23 with the user: GitHub source through CodeConnections; no domain, raw CloudFront URLs in dev, QA, and prod; flat-rate Free plan on all three distributions; logs 1 month in dev/QA, 6 months in prod. ADR 0001 (Decision 8, open questions 2-4, cost) and ADR 0003 (edge and pipeline stack names) amended.
  - Blocked by: T005
  - Outcome: completed
  - Closed: 2026-11-23

- [x] **T006** Verify the adapter replaces a forged x-amzn-request-context header #ops #infra #security
  - Acceptance: On dev, GET /api/me with a valid token and a forged x-amzn-request-context header naming another email returns the token's email. Result recorded here, with the adapter version tested.
  - Context: ADR 0002 follow-up 1. Source inspection (v0.9.1, v1.1.0) shows HeaderMap::insert replaces the client copy; this proves it for the pinned version. Repeat whenever the adapter version changes. Source: docs/adr/0002-proof-application.md. Result 2026-11-23, adapter 1.1.0 on swb-proof-dev: GET /api/me with a valid ID token returned 200 and the token's email; the same request plus a forged x-amzn-request-context naming forged@example.com returned 200 and the token's email, not the forged one; the forged header with no token returned 401 from API Gateway.
  - Blocked by: T009
  - Outcome: completed
  - Closed: 2026-11-23

- [x] **T009** Derive the stack name and Cognito prefix from one projectName setting #feature #infra
  - Acceptance: infra/cdk.json has one projectName context value, and both the CDK stack name and the Hosted UI domain prefix come from it as <projectName>-<environment>; infra/app.py, infra/proof_dev.py and infra/cdk.json write out no deployed name (ProofDevStack and proof_dev.py keep their names until T007/T008). Tests synthesize with a different projectName and assert that the stack name and the UserPoolDomain change with it, and that invalid names fail at synth. The README has a 'Start a new project from this repo' section: copy it (fresh history; GitHub template once published, not a fork), set projectName, cdk bootstrap if the account or region is new, deploy, create a user. swb-proof-dev is deployed and sign-in works on it.
  - Context: Goal: a copy of this repo deploys as its own Project by changing one value. Plan: docs/plans/2026-11-23-project-name.md. ADR: docs/adr/0003-deployed-names-from-project-name.md. Decided 2026-11-23: projectName swb-proof gives stack and prefix swb-proof-dev; ProofDev was destroyed first, because the new stack cannot claim the prefix while ProofDev holds it. T006 runs against swb-proof-dev afterwards. T007's QA and prod names follow the same rule.
  - Related: T007
  - Outcome: completed
  - Closed: 2026-11-23

- [x] **T005** Deploy the dev environment and prove sign-in end to end #feature #infra
  - Acceptance: In a browser, sign-in through the Hosted UI on the dev CloudFront URL shows the user's email. The CORS preflight succeeds. A request without a token is rejected by API Gateway before Lambda. Lambda traces appear in X-Ray and API access logs in CloudWatch.
  - Context: Follows the T004 plan: docs/plans/2026-11-22-dev-environment.md (Tasks 1-4 build infra/, Task 5 is the deploy and end-to-end proof).
  - Blocked by: T004
  - Outcome: completed
  - Closed: 2026-11-23

- [x] **T004** Plan a single dev environment deployed with cdk deploy #docs #infra
  - Acceptance: Plan written under docs/plans/ and linked here. Python CDK in infra/ deploys by hand, one environment, entirely in us-west-2 with nothing created in us-east-1: Cognito User Pool with email on the ID token, Hosted UI app client with PKCE, HTTP API with JWT authorizer and CORS (SPA origin, GET, Authorization), Lambda from the ECR image with AUTH_MODE=aws and X-Ray active tracing, API access logs, S3 plus CloudFront for the SPA, and the deployed config.json with a short cache lifetime. No pipeline, WAF, Route 53, QA, or prod. The user has vetted it.
  - Context: Phase 2a. Proves the app in the cloud before building the full platform. Cognito attributes cannot change after pool creation, so settle the schema in the plan. Region: us-west-2 is the home region. Only CloudFront's ACM certificate, a CloudFront WAF web ACL, and a Cognito custom-domain certificate must be in us-east-1; this phase uses none of them (the dev *.cloudfront.net URL per T003, the Cognito prefix domain, no WAF), so it needs no cross-region stacks. The CloudFront distribution itself can live in the us-west-2 stack. Sources: docs/adr/0001-serverless-go-platform-architecture.md, docs/adr/0002-proof-application.md. Plan: docs/plans/2026-11-22-dev-environment.md
  - Blocked by: T002, T003
  - Outcome: completed
  - Closed: 2026-11-22

- [x] **T003** Allow the raw CloudFront URL for the dev environment in ADR 0001 #docs #adr
  - Acceptance: ADR 0001 Decision 8 records an exception: dev may use its *.cloudfront.net URL, including as the Cognito callback and logout URL, until the shared hosted zone and us-east-1 certificate exist. QA and prod still use custom domains.
  - Context: Lets the first cloud deploy skip DNS and certificates. Source: docs/adr/0001-serverless-go-platform-architecture.md.
  - Outcome: completed
  - Closed: 2026-11-22

- [x] **T002** Implement the proof application #feature #api #web
  - Acceptance: Locally, go tool gow run . plus the Vite dev server shows dev@localhost, and a Go edit restarts the server. Go tests pass, including GET /api/me shape and aws-mode claim parsing from authorizer.jwt.claims.email (missing or empty claim rejected; unset AUTH_MODE rejected). npm run build runs tsc and passes. The container image builds with the pinned adapter.
  - Context: Follows the T001 plan: docs/plans/2026-11-22-proof-application.md. Source: docs/adr/0002-proof-application.md. Implemented on branch feat/proof-application; test instructions in README.md (Phase 1).
  - Blocked by: T001
  - Outcome: completed
  - Closed: 2026-11-22

- [x] **T001** Plan the proof application #docs #api #web
  - Acceptance: Implementation plan written under docs/plans/ and linked here. It covers the Go API (dev and aws AUTH_MODE, including an aws-mode test with a fixture x-amzn-request-context header), the SPA (dev and cognito modes: config.json, Hosted UI PKCE redirect, Authorization header, runtime email check, tsc before vite build), the Dockerfile with the adapter pinned at v1.1.0, and the gow dev loop. The user has vetted it.
  - Context: Source: docs/adr/0002-proof-application.md. Build every AWS code path locally with fixtures so the first deploy only has to prove infrastructure. Plan: docs/plans/2026-11-22-proof-application.md
  - Outcome: completed
  - Closed: 2026-11-22

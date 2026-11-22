# TODO — serverless-web-boilerplate
<!-- todo-format: 2; next-id: 9 -->

## P0 — Critical / Blocking

## P1 — High Priority

- [ ] **T001** Plan the proof application #docs #api #web
  - Acceptance: Implementation plan written under docs/plans/ and linked here. It covers the Go API (dev and aws AUTH_MODE, including an aws-mode test with a fixture x-amzn-request-context header), the SPA (dev and cognito modes: config.json, Hosted UI PKCE redirect, Authorization header, runtime email check, tsc before vite build), the Dockerfile with the adapter pinned at v1.1.0, and the gow dev loop. The user has vetted it.
  - Context: Source: docs/adr/0002-proof-application.md. Build every AWS code path locally with fixtures so the first deploy only has to prove infrastructure.

- [ ] **T002** Implement the proof application #feature #api #web
  - Acceptance: Locally, go tool gow run . plus the Vite dev server shows dev@localhost, and a Go edit restarts the server. Go tests pass, including GET /api/me shape and aws-mode claim parsing from authorizer.jwt.claims.email (missing or empty claim rejected; unset AUTH_MODE rejected). npm run build runs tsc and passes. The container image builds with the pinned adapter.
  - Context: Follows the T001 plan. Source: docs/adr/0002-proof-application.md. The plan may split this into smaller tasks.
  - Blocked by: T001

- [ ] **T003** Allow the raw CloudFront URL for the dev environment in ADR 0001 #docs #adr
  - Acceptance: ADR 0001 Decision 8 records an exception: dev may use its *.cloudfront.net URL, including as the Cognito callback and logout URL, until the shared hosted zone and us-east-1 certificate exist. QA and prod still use custom domains.
  - Context: Lets the first cloud deploy skip DNS and certificates. Source: docs/adr/0001-serverless-go-platform-architecture.md.

- [ ] **T004** Plan a single dev environment deployed with cdk deploy #docs #infra
  - Acceptance: Plan written under docs/plans/ and linked here. Python CDK in infra/ deploys by hand, one environment: Cognito User Pool with email on the ID token, Hosted UI app client with PKCE, HTTP API with JWT authorizer and CORS (SPA origin, GET, Authorization), Lambda from the ECR image with AUTH_MODE=aws and X-Ray active tracing, API access logs, S3 plus CloudFront for the SPA, and the deployed config.json with a short cache lifetime. No pipeline, WAF, Route 53, QA, or prod. The user has vetted it.
  - Context: Phase 2a. Proves the app in the cloud before building the full platform. Cognito attributes cannot change after pool creation, so settle the schema in the plan. Sources: docs/adr/0001-serverless-go-platform-architecture.md, docs/adr/0002-proof-application.md.
  - Blocked by: T002, T003

- [ ] **T005** Deploy the dev environment and prove sign-in end to end #feature #infra
  - Acceptance: In a browser, sign-in through the Hosted UI on the dev CloudFront URL shows the user's email. The CORS preflight succeeds. A request without a token is rejected by API Gateway before Lambda. Lambda traces appear in X-Ray and API access logs in CloudWatch.
  - Context: Follows the T004 plan.
  - Blocked by: T004

- [ ] **T006** Verify the adapter replaces a forged x-amzn-request-context header #ops #infra #security
  - Acceptance: On dev, GET /api/me with a valid token and a forged x-amzn-request-context header naming another email returns the token's email. Result recorded here, with the adapter version tested.
  - Context: ADR 0002 follow-up 1. Source inspection (v0.9.1, v1.1.0) shows HeaderMap::insert replaces the client copy; this proves it for the pinned version. Repeat whenever the adapter version changes. Source: docs/adr/0002-proof-application.md.
  - Blocked by: T005

## P2 — Backlog

- [ ] **T007** Plan the full platform: pipeline, QA, prod, WAF, and DNS #docs #infra
  - Acceptance: Plan written under docs/plans/ and linked here. Covers CodePipeline and CodeBuild (one image and one SPA bundle per commit, per-environment config.json, manual approval before prod), QA and prod stacks, WAF, the shared hosted zone and us-east-1 certificate, custom domains, and removing the dev CloudFront-URL exception. Settles ADR 0001 open questions 2-4: stack layout, log retention, and the CloudFront flat-rate Free plan. The user has vetted it.
  - Context: Phase 2b. Source: docs/adr/0001-serverless-go-platform-architecture.md.
  - Blocked by: T005

- [ ] **T008** Build the full platform #feature #infra
  - Acceptance: A push to main deploys dev and then QA through CodePipeline. Prod deploys after manual approval. Each environment is served on its custom domain behind WAF, and sign-in works in each.
  - Context: Follows the T007 plan. The plan may split this into smaller tasks.
  - Blocked by: T007

## Done (recent)

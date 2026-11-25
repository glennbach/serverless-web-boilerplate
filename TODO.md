# TODO — serverless-web-boilerplate
<!-- todo-format: 2; next-id: 13 -->

## P0 — Critical / Blocking

## P1 — High Priority

## P2 — Backlog

- [ ] **T010** Remove the dev environment from the pipeline #chore #infra
  - Acceptance: A push to master deploys QA, then prod after manual approval, with no Dev stage. test_pipeline.py asserts the stages are Qa then Prod. ADR 0001 Decisions 3 and 9 are amended, and the README matches. swb-proof-dev (us-west-2) and swb-proof-dev-edge (us-east-1) are deleted, and describe-stacks for each reports that the stack does not exist.
  - Context: Plan: docs/plans/2026-11-24-remove-dev-environment.md (grilled 2026-11-24; no new ADR, ADR 0001 is amended). Decided 2026-11-24 with the user: for one developer, dev duplicates QA. Both deploy the same assets one after the other, with the same smoke step and no gate between them. The dev stacks are deleted, not kept as a sandbox. Code to change: infra/pipeline.py, infra/environment.py (ENVIRONMENTS, log retention), infra/tests/test_pipeline.py, infra/tests/test_environment.py. Removing the stage does not delete its stacks, because CloudFormation keeps state per stack and nothing tracks the app's list of stacks. Delete steps, in order: (1) Push the pipeline change and let the pipeline update itself first; otherwise the next run recreates dev. (2) No Free plan step: list-subscriptions was empty on 2026-11-24 and the user will not subscribe (see T012). (3) aws cloudformation delete-stack --region us-west-2 --stack-name swb-proof-dev, then aws cloudformation wait stack-delete-complete --region us-west-2 --stack-name swb-proof-dev. (4) aws cloudformation delete-stack --region us-east-1 --stack-name swb-proof-dev-edge; WAF refuses to delete a web ACL while a distribution still uses it, so step 3 must finish first. (5) Delete the leftover /aws/lambda/swb-proof-dev-* log groups that CloudFormation never managed. Dev's user pool and log groups delete with the stack (RemovalPolicy DESTROY), so its users are lost. Do before T011.
  - Related: T008, T012
  - Claimed: claude | 2026-11-24 | feat/remove-dev

- [ ] **T011** Trigger the pipeline from the build branch instead of master #chore #infra
  - Acceptance: infra/pipeline.py sets BRANCH to build, and test_pipeline.py asserts the source BranchName is build. A build branch exists on GitHub, and the pipeline's source action reads from it. A push to master alone starts no pipeline run, and a push to build does. ADR 0001 Decision 3, the pipeline.py docstring, and the README say that a push to build deploys, and the README shows how to ship: git push origin master:build.
  - Context: Decided 2026-11-24 with the user: deploy only on purpose, not on every push to master. Previous branch change: commit 0bc7b64 (main to master) touched README.md, ADR 0001, infra/pipeline.py, and infra/tests/test_pipeline.py. Cutover order matters: the running pipeline watches master and changes its own source only when it updates itself. Create build on GitHub at the commit that sets BRANCH to build, then push that commit to master. The master run updates the pipeline to read from build, and from then on only pushes to build start it. If build does not exist when the pipeline switches, the source stage fails. T010 also edits pipeline.py, its tests, ADR 0001, and the README, so do the two tasks one after the other.
  - Related: T010

- [ ] **T012** Decide whether QA and prod use the CloudFront flat-rate Free plan #chore #infra
  - Acceptance: Either (a) README one-time setup step 6, ADR 0001 open question 4, and test_distribution_is_flat_rate_eligible are removed, and ADR 0001 records pay-as-you-go as the decision; or (b) both distributions are subscribed, aws pricing-plan-manager list-subscriptions --region us-east-1 lists them ACTIVE, and ADR 0001's cost table says about $0 at idle.
  - Context: Found 2026-11-24 while planning T010: list-subscriptions returns no subscriptions, although platform go-live Step 9 is ticked. The user does not intend to subscribe. T010 only corrects ADR 0001's cost table to the actual pay-as-you-go cost (about $18/month idle for two web ACLs through 2027-01-31: $5 per web ACL plus $1 for each of its 4 rules; about $14.60 from 2027-02-01, when AWS WAF bills $0.01 per hour per protected resource; https://aws.amazon.com/waf/pricing/, checked 2026-11-24); this task decides whether to drop the Free plan setup or keep eligibility as a free option.
  - Related: T010

## Done (recent)

- [x] **T008** Build the full platform #feature #infra
  - Acceptance: A push to main deploys dev and then QA through CodePipeline. Prod deploys after manual approval. Each environment is served on its *.cloudfront.net URL behind its own WAF web ACL, and sign-in works in each. Each distribution stays eligible for the CloudFront flat-rate Free plan and is subscribed where the account allows (nice-to-have: a refusal is recorded here, and that environment runs pay-as-you-go).
  - Context: Follows the T007 plan: docs/plans/2026-11-23-platform.md (Tasks 1-3 build infra/, Task 4 is the go-live run by hand). Tasks 1-3 implemented on branch feat/platform (8726384..ef20b2d), 61 infra tests pass, final review fixes applied. Remaining: Task 4 go-live (GitHub repo + connection, cdk.json repository/connectionArn, bootstrap us-west-2 and us-east-1, cdk deploy swb-proof-pipeline, approve prod, optional Free plan subscriptions, users, sign-in in each).
  - Blocked by: T007,T009
  - Outcome: completed
  - Closed: 2026-11-24

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

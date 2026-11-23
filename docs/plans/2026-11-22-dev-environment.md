# Dev Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One dev environment on AWS, deployed by hand with `cdk deploy`, that proves the proof in the cloud: Hosted UI sign-in on the dev CloudFront URL, the HTTP API's JWT authorizer and CORS, and the Go image on Lambda.

**Architecture:** One Python CDK app in `infra/` with one stack, `ProofDev`, in `us-west-2`. The stack holds the S3 bucket and CloudFront distribution for the SPA, the Cognito User Pool with its prefix domain and Hosted UI client, the Lambda built from `api/Dockerfile`, the HTTP API with a JWT authorizer, CORS, and access logs, and two `BucketDeployment`s that upload the built SPA and write `config.json` from the stack's own values. Nothing is created in `us-east-1`.

**Tech Stack:** AWS CDK v2 (`aws-cdk-lib`, Python), CDK CLI 2.1149.0 or later (older CLIs cannot read the assembly that `aws-cdk-lib` 2.278 writes), `uv` for the Python environment, `pytest` with `aws_cdk.assertions`, Docker for the image asset.

**Spec:** T004's acceptance in `TODO.md`; [ADR 0001](../adr/0001-serverless-go-platform-architecture.md) (Decisions 2, 6, 7, 8, 10) and [ADR 0002](../adr/0002-proof-application.md) (Decisions 3, 4, 5). The application this deploys is [the phase 1 plan](2026-11-22-proof-application.md). T005 executes this plan, Task 5 is its acceptance.

## Global Constraints

- Region `us-west-2` only. No `us-east-1` resource, no cross-region stack, no ACM certificate, no WAF, no Route 53, no pipeline, no QA, no prod.
- The site origin is `https://<distribution>.cloudfront.net` (ADR 0001, Decision 8 exception for dev).
- Cognito callback and logout URL: the site origin plus `/`, exactly. Scopes `openid email`. Authorization-code grant, no client secret (PKCE is the SPA's).
- HTTP API CORS: allow origin = the site origin (no trailing slash), method `GET`, header `authorization`. No `OPTIONS` or `ANY` route. Go sets no CORS headers.
- `GET /api/me` is the only route, and the JWT authorizer covers it. `GET /` is not published.
- Lambda: the `api/` image, `AUTH_MODE=aws`, X-Ray active tracing.
- `config.json` on the site: `{"authMode": "cognito", "apiBaseUrl", "cognitoDomainUrl", "clientId"}`, the schema `web/src/config.ts` parses. Served with `Cache-Control: no-cache`.
- One SPA bundle: deploy uploads `web/dist` from `npm run build`. It never rebuilds the SPA per environment, and the local `web/dist/config.json` (`authMode: dev`) never reaches the bucket.
- Non-test Python follows the repository's documentation contract (`AGENTS.md`): Napoleon docstrings with only the sections that apply, `#:` comments for module globals, class attributes, and instance attributes set in `__init__`.
- Logs never contain the email or the ID token.

## Decisions beyond the ADRs

**Cognito schema.** These are fixed when the pool is created. Changing any of them means a new pool and new users:

| Setting | Value | Why |
|---|---|---|
| Sign-in | `sign_in_aliases=SignInAliases(email=True)` (email is the username) | ADR 0002, Decision 2: `email` is on the ID token when the pool uses email sign-in. |
| `email` standard attribute | `required=True`, `mutable=True` | Every user has the claim the page shows. A user can change it. |
| Custom attributes | none | The proof reads only `email`. |
| Region | `us-west-2` | Pools cannot move (ADR 0001, Decision 10). |
| Username case | `sign_in_case_sensitive=False` | `Alice@Example.com` and `alice@example.com` are one user. Case sensitivity cannot change after creation. |

Mutable, and chosen for now: `prevent_user_existence_errors=True` on the client (the public Hosted UI does not reveal which emails have accounts), `auto_verify` email, `self_sign_up_enabled=False` (T005 creates users with `admin-create-user`; a public dev URL should not take sign-ups), `account_recovery=EMAIL_ONLY`, MFA off, `feature_plan=FeaturePlan.LITE`, classic Hosted UI (`ManagedLoginVersion.CLASSIC_HOSTED_UI`), default token lifetimes (ID token 1 hour). The client sets no `read_attributes`, so every standard attribute, including `email`, is readable and goes on the ID token with the `email` scope.

**Other choices.**
- **Stack.** One stack, `ProofDev`, in `infra/proof_dev.py`. `app.py` only instantiates it. The stack takes the paths it uploads as arguments so tests can pass a fake `web/dist`.
- **Image.** `DockerImageCode.from_image_asset("../api", platform=Platform.LINUX_ARM64)`, function `architecture=ARM_64`. CDK builds the image and pushes it to the bootstrap ECR repository. A dedicated ECR repository arrives with the pipeline (T007/T008). Memory 256 MB, timeout 10 s.
- **Cognito domain prefix.** cdk.json context `cognitoDomainPrefix`, value `swb-proof-dev`. Prefixes are unique per region across all AWS accounts. If deploy reports it taken, change the context value. The account id is not used, so it does not appear in public URLs.
- **The authorizer.** `HttpUserPoolAuthorizer` with the one client. Its audience is the client id, which the ID token carries as `aud`. An access token has no `aud` and is rejected, which matches ADR 0002 (the SPA sends the ID token).
- **Access logs.** The API is created with `create_default_stage=False` and gets an explicit `$default` `HttpStage` (`auto_deploy=True`) with access logs, because only `HttpStage` takes `access_log_settings`. The format is one JSON object per request with these keys:

  | Key | Value |
  |---|---|
  | `requestId` | `$context.requestId` |
  | `integrationRequestId` | `$context.integration.requestId` (the Lambda request id; joins to Lambda logs and X-Ray) |
  | `ip` | `$context.identity.sourceIp` |
  | `requestTime` | `$context.requestTime` |
  | `routeKey` | `$context.routeKey` |
  | `path` | `$context.path` |
  | `status` | `$context.status` |
  | `responseLength` | `$context.responseLength` |
  | `responseLatency` | `$context.responseLatency` |
  | `integrationStatus` | `$context.integrationStatus` |
  | `integrationError` | `$context.integrationErrorMessage` |
  | `authorizerError` | `$context.authorizer.error` |

- **Log retention.** One month for the access log group and the Lambda log group (ADR 0001 open question 3 stays open for QA and prod).
- **Dev teardown.** Bucket (`auto_delete_objects=True`), User Pool, and log groups use `RemovalPolicy.DESTROY`. The two `BucketDeployment`s share one such log group (otherwise CDK makes theirs `Retain` with 731-day retention). `cdk destroy` leaves only the bootstrap stack and the runtime-created log group of CDK's bucket auto-delete handler.
- **CloudFront.** S3 origin through Origin Access Control (`S3BucketOrigin.with_origin_access_control`), bucket fully private, `redirect-to-https`, managed `CACHING_OPTIMIZED` policy (query strings are not forwarded; the SPA reads `?code=` in the browser), `default_root_object="index.html"`, `PRICE_CLASS_100`. No error-page rewrites: the SPA has one page and the callback is `/`.
- **Caching.** Two deployments to the same bucket, both `prune=False` (the pattern in the `aws-s3-deployment` README):
  - *Assets*: `web/dist` minus `index.html` and `config.json`, `Cache-Control: public, max-age=31536000, immutable`. Vite hashes these names.
  - *Entry*: `index.html` from `web/dist` plus `config.json` from `Source.json_data`, `Cache-Control: no-cache`. It depends on *Assets*, so a new `index.html` never points at assets not yet uploaded.

  `prune=False` leaves old hashed assets in the bucket. That keeps an open tab working across a deploy, and the bytes are negligible. No CloudFront invalidation: with `no-cache` from the origin and the managed policy's 1-second minimum TTL, the edge revalidates.
- **Outputs.** `SiteUrl`, `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `CognitoDomainUrl`, `ApiAccessLogGroup`, `ApiFunctionLogGroup`, `ApiFunctionName`. Task 5 uses them.
- **Not added:** a security-headers response policy and CSP (the CSP needs the API and Cognito origins and belongs with WAF in phase 2b), a sign-out button, Lambda provisioned concurrency.

## Review Focus

1. **Callback URL drift.** The SPA sends `redirect_uri=${origin}/`. A callback URL without the trailing slash, or with the wrong host, makes the Hosted UI refuse sign-in with `redirect_mismatch`. Pinned by `test_client_is_public_pkce_with_site_callback` (Task 2), which compares the exact `CallbackURLs` and `LogoutURLs` to `site_url + "/"`.
2. **The local `config.json` reaches the bucket.** `web/dist/config.json` is the dev file. Deployed, it would make the site skip sign-in and call `/api/me` on CloudFront. Pinned by `test_dev_config_is_never_uploaded` (Task 4).
3. **A preflight that hits the authorizer, or an origin that never matches.** A browser `Origin` has no trailing slash, and an `OPTIONS` or `ANY` route would send the preflight to the JWT authorizer, which rejects it. Pinned by `test_api_cors_and_single_route` (Task 3): the allowed origin is exactly `site_url`, and there is one route.
4. **The image and the function disagree on architecture.** An amd64 image on an arm64 function fails every cold start with an exec format error that no synth catches. Pinned by `test_function_image_is_arm64` (Task 3), which reads the platform from the asset manifest.
5. **`config.json` or `index.html` cached for a day.** A redeploy that changes the pool or API URL stays invisible behind CloudFront's default TTL. Pinned by `test_entry_files_are_no_cache` (Task 4). Task 5 checks the served header.

---

### Task 1: CDK app, hosting, and the region guard

**Files:**
- Create: `infra/pyproject.toml`, `infra/uv.lock`, `infra/cdk.json`, `infra/app.py`, `infra/proof_dev.py`, `infra/tests/test_proof_dev.py`
- Modify: `.gitignore` (add `cdk.out/`)

**Interfaces:**
- Produces: `HOME_REGION = "us-west-2"` and `class ProofDevStack(Stack)` in `infra/proof_dev.py`, constructed as `ProofDevStack(scope, construct_id, *, api_dir: str, web_dist: str, cognito_domain_prefix: str, **kwargs)`. Instance attributes: `bucket: s3.Bucket`, `distribution: cloudfront.Distribution`, `site_url: str` (the token `f"https://{distribution.distribution_domain_name}"`).
- Produces (tests): fixture `built(tmp_path) -> tuple[ProofDevStack, Template, Path]` returning the stack, its template, and the cloud assembly directory. It writes a fake dist (`index.html`, `assets/app-abc123.js`, and `config.json` containing `{"authMode": "dev", "apiBaseUrl": ""}`), passes the real `api/` directory, and constructs the stack with `env=Environment(region=HOME_REGION)` and `cognito_domain_prefix="test-prefix"`. Later tasks add tests to this file and reuse the fixture.

- [ ] **Step 1: Create the project**

```bash
cd infra
uv init --bare --python ">=3.12"
uv add aws-cdk-lib constructs
uv add --dev pytest
```
Add `[tool.pytest.ini_options] pythonpath = ["."]` to `pyproject.toml`. Write `cdk.json` with `"app": "uv run python app.py"`, `"context": {"cognitoDomainPrefix": "swb-proof-dev", ...}` plus the recommended feature flags: run `cdk init app --language python --generate-only` in an empty scratch directory and copy its `context` block. Delete the scratch directory.

- [ ] **Step 2: Write the failing tests**

```python
def test_nothing_outside_home_region(built):
    stack, template, _ = built
    assert stack.region == "us-west-2"
    assert "us-east-1" not in json.dumps(template.to_json())

def test_site_bucket_is_private_behind_oac(built):
    _, t, _ = built
    t.has_resource_properties("AWS::S3::Bucket", {"PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True, "BlockPublicPolicy": True,
        "IgnorePublicAcls": True, "RestrictPublicBuckets": True}})
    t.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    t.has_resource_properties("AWS::CloudFront::Distribution", {"DistributionConfig": Match.object_like({
        "DefaultRootObject": "index.html",
        "DefaultCacheBehavior": Match.object_like({"ViewerProtocolPolicy": "redirect-to-https"}),
    })})
```

- [ ] **Step 3: Run and see them fail**

Run: `cd infra && uv run pytest -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'proof_dev'`.

- [ ] **Step 4: Implement `HOME_REGION`, `ProofDevStack` with the bucket and distribution, and `app.py`**

The stack's `__init__` accepts all three keyword arguments now; later tasks use them. `app.py`:
```python
app = App()
ProofDevStack(app, "ProofDev",
    env=Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=HOME_REGION),
    api_dir=str(REPO / "api"), web_dist=str(REPO / "web" / "dist"),
    cognito_domain_prefix=app.node.get_context("cognitoDomainPrefix"))
app.synth()
```
with `REPO = Path(__file__).resolve().parent.parent` (a `#:`-documented module global).

- [ ] **Step 5: Run the tests**

Run: `cd infra && uv run pytest -q`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add .gitignore infra
git commit -m "feat(infra): CDK app with the dev site bucket and distribution"
```

---

### Task 2: Cognito User Pool, prefix domain, and Hosted UI client

**Files:**
- Modify: `infra/proof_dev.py`, `infra/tests/test_proof_dev.py`

**Interfaces:**
- Consumes: `site_url` (Task 1), `cognito_domain_prefix`.
- Produces: instance attributes `user_pool: cognito.UserPool`, `user_pool_client: cognito.UserPoolClient`, `user_pool_domain: cognito.UserPoolDomain`.

- [ ] **Step 1: Write the failing tests**

```python
def test_pool_schema(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Cognito::UserPool", {
        "UsernameAttributes": ["email"],
        "AutoVerifiedAttributes": ["email"],
        "Schema": Match.array_with([Match.object_like({"Name": "email", "Required": True, "Mutable": True})]),
        "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
        "UserPoolTier": "LITE",
    })

def test_prefix_domain_classic_hosted_ui(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": "test-prefix", "ManagedLoginVersion": 1})

def test_client_is_public_pkce_with_site_callback(built):
    stack, t, _ = built
    site = stack.resolve(stack.site_url + "/")
    t.has_resource_properties("AWS::Cognito::UserPoolClient", {
        "GenerateSecret": False,
        "AllowedOAuthFlowsUserPoolClient": True,
        "AllowedOAuthFlows": ["code"],
        "AllowedOAuthScopes": Match.array_equals(["openid", "email"]),  # reorder to what CDK emits
        "SupportedIdentityProviders": ["COGNITO"],
        "CallbackURLs": [site],
        "LogoutURLs": [site],
        "ReadAttributes": Match.absent(),
    })
```

- [ ] **Step 2: Run and see them fail**

Run: `cd infra && uv run pytest -q`
Expected: the three new tests FAIL with "Template has 0 resources with type AWS::Cognito::…".

- [ ] **Step 3: Add the pool, domain, and client to `ProofDevStack`**

Use the table under *Decisions beyond the ADRs* for every pool property. `user_pool.add_domain("Domain", cognito_domain=CognitoDomainOptions(domain_prefix=cognito_domain_prefix), managed_login_version=ManagedLoginVersion.CLASSIC_HOSTED_UI)`. `user_pool.add_client("Spa", generate_secret=False, o_auth=OAuthSettings(flows=OAuthFlows(authorization_code_grant=True), scopes=[OAuthScope.OPENID, OAuthScope.EMAIL], callback_urls=[site_url + "/"], logout_urls=[site_url + "/"]), supported_identity_providers=[UserPoolClientIdentityProvider.COGNITO])`.

- [ ] **Step 4: Run the tests**

Run: `cd infra && uv run pytest -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add infra
git commit -m "feat(infra): dev Cognito pool with email sign-in and a PKCE Hosted UI client"
```

---

### Task 3: Lambda, HTTP API, JWT authorizer, CORS, and access logs

**Files:**
- Modify: `infra/proof_dev.py`, `infra/tests/test_proof_dev.py`

**Interfaces:**
- Consumes: `api_dir`, `site_url`, `user_pool`, `user_pool_client`.
- Produces: instance attributes `function: lambda_.DockerImageFunction`, `api: apigwv2.HttpApi`, `access_logs: logs.LogGroup`.

- [ ] **Step 1: Write the failing tests**

```python
def test_function_runs_image_in_aws_mode_with_tracing(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Lambda::Function", {
        "PackageType": "Image",
        "Architectures": ["arm64"],
        "Environment": {"Variables": {"AUTH_MODE": "aws"}},
        "TracingConfig": {"Mode": "Active"},
    })

def test_function_image_is_arm64(built):
    _, _, outdir = built
    images = json.loads((outdir / "ProofDev.assets.json").read_text())["dockerImages"]
    assert [i["source"]["platform"] for i in images.values()] == ["linux/arm64"]

def test_api_cors_and_single_route(built):
    stack, t, _ = built
    t.has_resource_properties("AWS::ApiGatewayV2::Api", {"ProtocolType": "HTTP", "CorsConfiguration": {
        "AllowOrigins": [stack.resolve(stack.site_url)],
        "AllowMethods": ["GET"],
        "AllowHeaders": ["authorization"],
        "MaxAge": 3600,
    }})
    t.resource_count_is("AWS::ApiGatewayV2::Route", 1)
    t.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": "GET /api/me", "AuthorizationType": "JWT"})

def test_jwt_authorizer_accepts_the_spa_client(built):
    stack, t, _ = built
    t.has_resource_properties("AWS::ApiGatewayV2::Authorizer", {
        "AuthorizerType": "JWT",
        "IdentitySource": ["$request.header.Authorization"],
        "JwtConfiguration": Match.object_like({"Audience": [stack.resolve(stack.user_pool_client.user_pool_client_id)]}),
    })

def test_default_stage_writes_json_access_logs(built):
    _, t, _ = built
    fmt = Capture()
    t.has_resource_properties("AWS::ApiGatewayV2::Stage", {"StageName": "$default", "AutoDeploy": True,
        "AccessLogSettings": {"DestinationArn": Match.any_value(), "Format": fmt}})
    entry = json.loads(fmt.as_string())
    assert entry["integrationRequestId"] == "$context.integration.requestId"
    assert entry["authorizerError"] == "$context.authorizer.error"
    assert set(entry) == {"requestId", "integrationRequestId", "ip", "requestTime", "routeKey", "path",
        "status", "responseLength", "responseLatency", "integrationStatus", "integrationError", "authorizerError"}
    t.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 30})
```

- [ ] **Step 2: Run and see them fail**

Run: `cd infra && uv run pytest -q`
Expected: the five new tests FAIL (no Lambda, API, or stage in the template; no `dockerImages` in the manifest).

- [ ] **Step 3: Add the function, API, authorizer, stage, and log groups**

- `DockerImageFunction` from `DockerImageCode.from_image_asset(api_dir, platform=Platform.LINUX_ARM64)`, `architecture=Architecture.ARM_64`, `memory_size=256`, `timeout=Duration.seconds(10)`, `environment={"AUTH_MODE": "aws"}`, `tracing=Tracing.ACTIVE`, `log_group=` a one-month `LogGroup` with `RemovalPolicy.DESTROY`.
- `HttpApi(create_default_stage=False, cors_preflight=CorsPreflightOptions(allow_origins=[site_url], allow_methods=[CorsHttpMethod.GET], allow_headers=["authorization"], max_age=Duration.hours(1)))`.
- `api.add_routes(path="/api/me", methods=[HttpMethod.GET], integration=HttpLambdaIntegration("Me", function), authorizer=HttpUserPoolAuthorizer("Cognito", user_pool, user_pool_clients=[user_pool_client]))`.
- `HttpStage(self, "Default", http_api=api, auto_deploy=True, access_log_settings=...)` with `LogGroupLogDestination(access_logs)` and `apigw.AccessLogFormat.custom(json.dumps(FIELDS))`, where `FIELDS` is the module-level dict from the access-log table.

- [ ] **Step 4: Run the tests**

Run: `cd infra && uv run pytest -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add infra
git commit -m "feat(infra): Lambda behind an HTTP API with JWT authorizer, CORS, and access logs"
```

---

### Task 4: SPA upload, deployed config.json, outputs, and README

**Files:**
- Modify: `infra/proof_dev.py`, `infra/tests/test_proof_dev.py`, `README.md`

**Interfaces:**
- Consumes: `bucket`, `web_dist`, `api`, `user_pool`, `user_pool_client`, `user_pool_domain`, `access_logs`, `function`.
- Produces: the stack outputs listed under *Decisions beyond the ADRs*, read by Task 5.

- [ ] **Step 1: Write the failing tests**

```python
def _deployments(t):
    return t.find_resources("Custom::CDKBucketDeployment").values()

def test_entry_files_are_no_cache(built):
    _, t, _ = built
    caches = sorted(d["Properties"]["SystemMetadata"]["cache-control"] for d in _deployments(t))
    assert caches == ["no-cache", "public, max-age=31536000, immutable"]
    assert all(d["Properties"]["Prune"] is False for d in _deployments(t))

def test_config_json_is_built_from_stack_values(built):
    stack, t, _ = built
    markers = json.dumps([d["Properties"].get("SourceMarkers") for d in _deployments(t)])
    for value in (stack.api.api_endpoint, stack.user_pool_client.user_pool_client_id, stack.user_pool_domain.base_url()):
        assert json.dumps(stack.resolve(value)) in markers

def test_dev_config_is_never_uploaded(built):
    _, _, outdir = built
    staged = [p.read_text() for p in outdir.glob("asset.*/config.json")]
    assert len(staged) == 1 and '"cognito"' in staged[0] and '"dev"' not in staged[0]

def test_outputs(built):
    _, t, _ = built
    for name in ("SiteUrl", "ApiUrl", "UserPoolId", "UserPoolClientId", "CognitoDomainUrl",
                 "ApiAccessLogGroup", "ApiFunctionLogGroup", "ApiFunctionName"):
        t.has_output(name, {})
```

If the deploy-time markers render differently from `stack.resolve(...)` (for example a nested `Fn::Join`), assert on the logical ids from `stack.get_logical_id(...)` instead; the test's claim, that the three values come from the stack, stays the same.

- [ ] **Step 2: Run and see them fail**

Run: `cd infra && uv run pytest -q`
Expected: the four new tests FAIL.

- [ ] **Step 3: Add the two deployments and the outputs**

- *Assets*: `BucketDeployment(sources=[Source.asset(web_dist, exclude=["index.html", "config.json"])], destination_bucket=bucket, prune=False, cache_control=[CacheControl.set_public(), CacheControl.max_age(Duration.days(365)), CacheControl.immutable()])`.
- *Entry*: `BucketDeployment(sources=[Source.asset(web_dist, exclude=["*", "!index.html"]), Source.json_data("config.json", {"authMode": "cognito", "apiBaseUrl": api.api_endpoint, "cognitoDomainUrl": user_pool_domain.base_url(), "clientId": user_pool_client.user_pool_client_id})], destination_bucket=bucket, prune=False, cache_control=[CacheControl.no_cache()])`, then `entry.node.add_dependency(assets)`.
- `CfnOutput` for each output name. `ApiUrl` is `api.api_endpoint` (no trailing slash).

- [ ] **Step 4: Run the tests**

Run: `cd infra && uv run pytest -q`
Expected: 14 passed.

- [ ] **Step 5: Update `README.md`**

Mark phase 2a "Implemented (plan link)" in the phase table. Add a "Phase 2a: the dev environment" section with: prerequisites (AWS credentials for the target account, Docker running, `uv`, CDK CLI), the deploy commands from Task 5 Steps 1–3, the user-creation command from Step 4, the `infra/tests/test_proof_dev.py` row for the test table, and `cdk destroy ProofDev` for teardown.

- [ ] **Step 6: Synth once against the real build**

Run: `cd web && npm run build && cd ../infra && uv run cdk synth ProofDev > /dev/null`
Expected: exits 0, and `grep -rl '"authMode": "dev"' cdk.out/asset.*/` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add infra README.md
git commit -m "feat(infra): upload the SPA with a deploy-time config.json"
```

---

### Task 5: Deploy and prove sign-in end to end (T005)

No code. Every step is a command and the output that means it passed. Record the outputs of Step 3 in the T005 context (`bot-todo edit T005 --context ...`); they are public values (ADR 0001, Decision 6). Do not record the test user's email.

- [ ] **Step 1: Check the account and region**

Run: `aws sts get-caller-identity && aws configure get region`
Expected: the intended account. All later commands pass `--region us-west-2` or run under `AWS_REGION=us-west-2`.

- [ ] **Step 2: Build and test both halves**

Run: `cd web && npm ci && npm test && npm run build` and `cd infra && uv run pytest -q`
Expected: all pass, and `web/dist/index.html` exists.

- [ ] **Step 3: Bootstrap and deploy**

Run: `cd infra && cdk --version` (must be 2.1149.0 or later; otherwise use `npx aws-cdk@2.1149.0` in place of `cdk`), then `cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-west-2 && cdk deploy ProofDev`
Expected: `ProofDev` reaches `CREATE_COMPLETE` and prints the eight outputs. If the Cognito domain prefix is taken, change `cognitoDomainPrefix` in `infra/cdk.json` and deploy again. Export them for the steps below: `SITE`, `API`, `POOL`, `ACCESS_LOGS`, `FN_LOGS`, `FN`.

- [ ] **Step 4: Create a test user**

Run: `aws cognito-idp admin-create-user --region us-west-2 --user-pool-id "$POOL" --username "$EMAIL" --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true --desired-delivery-mediums EMAIL` (the default medium is SMS, and the user has no phone number)
Expected: user status `FORCE_CHANGE_PASSWORD`, and a temporary password arrives at `$EMAIL`.

- [ ] **Step 5: Sign in through the Hosted UI**

Open `$SITE` in a browser.
Expected: redirect to the Hosted UI on `CognitoDomainUrl`; after sign-in and the forced password change, the page shows the user's email. Refreshing keeps showing it without another sign-in. DevTools Network shows one `OPTIONS` and one `GET` to `$API/api/me`, both successful.

- [ ] **Step 6: CORS preflight**

Run: `curl -si -X OPTIONS "$API/api/me" -H "Origin: $SITE" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization"`
Expected: `204`, `access-control-allow-origin: $SITE`, `access-control-allow-headers: authorization`. The same request with `-H "Origin: https://example.com"` returns no `access-control-allow-origin` header.

- [ ] **Step 7: No token is rejected before Lambda**

Run: `curl -si "$API/api/me" -H "Origin: $SITE"`, then after a minute `aws logs tail "$ACCESS_LOGS" --region us-west-2 --since 5m`
Expected: `401` with body `{"message":"Unauthorized"}` (API Gateway's, not Go's `unauthorized`), carrying `access-control-allow-origin: $SITE` (without it the SPA sees a network error instead of a 401 and never drops a dead session; record it in T005 if missing). The access log entry for that `requestId` has `"status":"401"` and `"integrationRequestId":"-"`, and `aws logs tail "$FN_LOGS" --since 5m` shows no `rejected /api/me` line for it.

- [ ] **Step 8: Traces and access logs**

From `aws logs tail "$ACCESS_LOGS" --region us-west-2 --since 30m`, take the Step 5 request's entry: `"status":"200"`, `"routeKey":"GET /api/me"`. Export its `integrationRequestId` as `REQ`.

Run:
```bash
IDS=$(aws xray get-trace-summaries --region us-west-2 --start-time $(date -v-30M +%s) --end-time $(date +%s) \
  --filter-expression "service(id(name: \"$FN\", type: \"AWS::Lambda::Function\"))" \
  --query 'TraceSummaries[:5].Id' --output text)
aws xray batch-get-traces --region us-west-2 --trace-ids $IDS --query 'Traces[].Segments[].Document' --output text | grep -c "$REQ"
```
Expected: `IDS` is not empty (traces from this function only), and the count is at least 1. A segment from this function carries `aws.request_id` equal to `REQ`, which ties the trace to the browser request's access-log entry. `$FN_LOGS` also has a `REPORT RequestId: $REQ` line. If the request is older than the five newest traces, narrow `--start-time` to the minute of Step 5.

- [ ] **Step 9: Cache headers**

Run: `curl -sI "$SITE/config.json" | grep -i cache-control` and the same for `$SITE/`
Expected: `cache-control: no-cache` for both. A hashed file under `/assets/` returns `public, max-age=31536000, immutable`.

- [ ] **Step 10: Close out**

Move T005 to review: `bot-todo --json review T005`. T006 (the forged `x-amzn-request-context` check) can now run against this environment.

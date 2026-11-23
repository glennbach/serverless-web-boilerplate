# Project Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A copy of this repository deploys as its own Project by changing one value, `projectName` in `infra/cdk.json`.

**Architecture:** One function in `infra/proof_dev.py` checks `projectName` and derives the Environment name `<projectName>-dev`. A second function builds the dev stack under that name and uses it again as the Hosted UI prefix. `app.py` and the tests both call that function, so the tests exercise the real derivation. `ProofDevStack` itself does not change.

**Tech Stack:** AWS CDK v2 (Python), `pytest` with `aws_cdk.assertions`, `uv`, and CDK CLI 2.1149.0 or later.

**Spec:** T009 in `TODO.md`, and [ADR 0003](../adr/0003-deployed-names-from-project-name.md), which sets the naming rule and the `projectName` checks. Glossary: [CONTEXT.md](../../CONTEXT.md) (**Project**, **Environment**).

## Global Constraints

- `infra/cdk.json` context has `"projectName": "swb-proof"` and no `cognitoDomainPrefix`.
- The stack name and the Hosted UI prefix are both `f"{project_name}-{environment}"`. The environment is the literal `"dev"` until T007.
- A valid `projectName` matches `[a-z]([a-z0-9-]*[a-z0-9])?` in full. It is at most 58 characters and contains none of `aws`, `amazon`, `cognito` as a substring. Anything else raises `ValueError` at synth, with a message that names `projectName` and the rule it broke.
- No deployed name is written out in `infra/app.py`, `infra/proof_dev.py`, or `infra/cdk.json`. Only tests may assert the derived values. `ProofDevStack` and `proof_dev.py` keep their names, and T007/T008 rename them.
- `HOME_REGION` stays `"us-west-2"`.
- Non-test Python follows `AGENTS.md`: Napoleon docstrings with only the sections that apply, and `#:` comments on module globals.
- The README never calls the Proof a template (`CONTEXT.md`). It may name GitHub's "template repository" feature, because that describes the repository.

## Review Focus

- `projectName` missing from `cdk.json` (a copy deleted it): the error should name `projectName`, not raise a `TypeError` on `None`. Task 1, case `None`.
- Names people actually type, such as `MyApp`, `my_app`, or `app-`, are rejected at synth and not mid-deploy. Task 1, parametrized cases.
- A reserved word inside an innocent name (`laws-firm` contains `aws`) is rejected, and the message says which word. Task 1, the `match=` assertion.
- Boundary length: 58 characters passes and 59 fails. Task 1.
- A copy deployed without changing `projectName` would update this Project's stacks. Synth cannot detect this, so the README's new section says to set the name first and says why. Task 2.

---

### Task 1: Derive the stack name and prefix from `projectName`

**Files:**
- Modify: `infra/proof_dev.py`. The new globals and `environment_name` go after `HOME_REGION`. `dev_stack` goes at the end of the module, after `ProofDevStack`. On Python 3.12 and 3.13 (`requires-python >= 3.12`), the annotation `-> ProofDevStack` is evaluated when the function is defined, so the function placed before the class raises `NameError`. The local venv runs 3.14, which defers annotations and would hide this. The `ProofDevStack` docstring mentions where its name comes from.
- Modify: `infra/app.py` (the body becomes `app = App()`, `dev_stack(app, ...)`, `app.synth()`)
- Modify: `infra/cdk.json` (replace `"cognitoDomainPrefix": "swb-proof-dev"` with `"projectName": "swb-proof"`)
- Test: `infra/tests/test_proof_dev.py`

**Interfaces:**
- Produces: `environment_name(project_name: object, environment: str) -> str` in `infra/proof_dev.py`. It returns `f"{project_name}-{environment}"` and raises `ValueError` unless `project_name` is a `str` that passes the Global Constraints rule.
- Produces: `dev_stack(app: App, *, api_dir: str, web_dist: str) -> ProofDevStack` in `infra/proof_dev.py`. It reads `app.node.try_get_context("projectName")` and sets `name = environment_name(..., "dev")`. It then builds `ProofDevStack(app, name, env=Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=HOME_REGION), api_dir=api_dir, web_dist=web_dist, cognito_domain_prefix=name)`. Because it reads the app context, `cdk synth -c projectName=…` overrides the value in `cdk.json`.
- Produces (tests): fixture `dist(tmp_path) -> Path`, the fake `web/dist` the `built` fixture writes today. `built(tmp_path, dist)` now builds through `dev_stack` with the `cdk.json` context. The helper `_app(tmp_path, **context) -> App` returns `App(outdir=..., context=...)`, where the context is the `cdk.json` context updated with `**context`, and a key whose value is `None` is removed. So `_app(tmp_path, projectName=None)` is an app with no `projectName` at all.

- [ ] **Step 1: Write the failing tests**

Split the fake-dist setup out of `built` into a `dist` fixture. Change `built` to call `dev_stack(_app(tmp_path), api_dir=str(INFRA.parent / "api"), web_dist=str(dist))`; this removes the `"ProofDev"` literal from the tests. Update the existing tests that depended on the old names:

```python
def test_prefix_domain_classic_hosted_ui(built):
    _, t, _ = built
    t.has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": "swb-proof-dev", "ManagedLoginVersion": 1})


def test_function_image_is_arm64(built):
    stack, _, outdir = built
    images = json.loads((outdir / f"{stack.artifact_id}.assets.json").read_text())["dockerImages"]
    assert [i["source"]["platform"] for i in images.values()] == ["linux/arm64"]
```

Add:

```python
def test_checked_in_project_name_names_the_dev_stack(built):
    stack, _, _ = built
    context = json.loads((INFRA / "cdk.json").read_text())["context"]
    assert context["projectName"] == "swb-proof" and "cognitoDomainPrefix" not in context
    assert stack.stack_name == "swb-proof-dev"


def test_another_project_name_renames_stack_and_prefix(tmp_path, dist):
    stack = dev_stack(_app(tmp_path, projectName="acme-shop"), api_dir=str(INFRA.parent / "api"), web_dist=str(dist))
    assert stack.stack_name == "acme-shop-dev"
    Template.from_stack(stack).has_resource_properties("AWS::Cognito::UserPoolDomain", {"Domain": "acme-shop-dev"})


@pytest.mark.parametrize("name", ["a", "swb-proof", "a1-b2", "a" * 58])
def test_valid_project_names(name):
    assert environment_name(name, "prod") == f"{name}-prod"


@pytest.mark.parametrize(
    "name, rule",
    [
        (None, "projectName"), ("", "projectName"), ("MyApp", "lowercase"), ("my_app", "lowercase"),
        ("1app", "lowercase"), ("app-", "lowercase"), ("a" * 59, "58"),
        ("laws-firm", "aws"), ("amazonia", "amazon"), ("cognito-x", "cognito"),
    ],
)
def test_invalid_project_names_fail_at_synth(tmp_path, dist, name, rule):
    # Through dev_stack, as app.py runs it; None means projectName is absent from the context.
    with pytest.raises(ValueError, match=rule):
        dev_stack(_app(tmp_path, projectName=name), api_dir=str(INFRA.parent / "api"), web_dist=str(dist))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra && uv run pytest -q`
Expected: collection ERROR, `ImportError: cannot import name 'dev_stack'`.

- [ ] **Step 3: Implement `environment_name` and `dev_stack`, update `cdk.json`, and reduce `app.py` to calling `dev_stack`**

Put the rule in `#:`-documented module globals: the compiled pattern, `MAX_PROJECT_NAME = 58` (`<name>-prod` within Cognito's 63), and the reserved words. Check `None` and non-`str` first, so a missing value gets "projectName is not set in infra/cdk.json". Then check the pattern, the length, and the reserved words, each with its own message containing the words in the test's `rule` column. `app.py` no longer imports `Environment` or `os`, because `dev_stack` owns both. `REPO` stays.

- [ ] **Step 4: Run the tests to verify they pass, and check that no deployed name is written out**

Run: `cd infra && uv run pytest -q`
Expected: all tests PASS.

Run: `cd infra && uv run --isolated --python 3.12 python -c 'import proof_dev'`
Expected: no output. This checks the oldest supported Python, which evaluates annotations when a function is defined.

Run: `grep -nwE 'ProofDev|swb-proof-dev|cognitoDomainPrefix' infra/app.py infra/proof_dev.py infra/cdk.json`
Expected: no output.

Run: `cd web && npm run build && cd ../infra && uv run cdk synth swb-proof-dev > /dev/null && uv run cdk ls`
Expected: synth succeeds, and `cdk ls` prints exactly `swb-proof-dev`.

Run: `cd infra && uv run cdk ls -c projectName=Bad_Name`
Expected: fails with the `ValueError` naming `projectName`.

- [ ] **Step 5: Commit**

```bash
git add infra/app.py infra/proof_dev.py infra/cdk.json infra/tests/test_proof_dev.py
git commit -m "feat(infra): derive the stack name and Hosted UI prefix from projectName"
```

### Task 2: README: the renamed stack, and starting a new project

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the stack name `swb-proof-dev` and the `projectName` rule from Task 1.

- [ ] **Step 1: Point phase 2a at the derived name**

In "Phase 2a: the dev environment":
- "one CDK stack, `ProofDev`" becomes "one CDK stack, `swb-proof-dev` (`<projectName>-dev`, [ADR 0003](docs/adr/0003-deployed-names-from-project-name.md))".
- `cdk deploy ProofDev` becomes `cdk deploy swb-proof-dev`, and `cdk destroy ProofDev` becomes `cdk destroy swb-proof-dev`.
- The leftover log group becomes `/aws/lambda/swb-proof-dev-CustomS3AutoDeleteObjects…`.
- Replace the "If `swb-proof-dev` is taken, change `cognitoDomainPrefix`" sentence with: if the prefix is taken, change `projectName`, which renames the stack too.
- Add a test bullet: the stack name and Hosted UI prefix come from `projectName`, and invalid names fail at synth.

- [ ] **Step 2: Add the section "Start a new project from this repo"**

Put it after the phase table. Ordered steps:
1. **Copy the repository with fresh history.** Clone it, delete `.git`, and run `git init`. Once this repository is on GitHub and marked as a template repository, "Use this template" does the same. Don't fork: a fork shares this repository's history, and its pull requests target this repository by default.
2. **Set `projectName` in `infra/cdk.json` before the first deploy.** Give the rule from ADR 0003 in one line. Choose a distinctive name, because Hosted UI prefixes are unique per region across all AWS accounts. A copy that keeps `swb-proof` would update this project's stacks in the same account.
3. Run `cdk bootstrap aws://<account>/us-west-2` if the account or region has not been bootstrapped.
4. Build the SPA and run `cdk deploy <projectName>-dev`, as in phase 2a's Deploy.
5. Create a user with the `admin-create-user` command from phase 2a.

- [ ] **Step 3: Check the result**

Run: `grep -n 'ProofDev\|cognitoDomainPrefix' README.md`
Expected: no output.

Run: `grep -niw 'template' README.md`
Expected: only the GitHub "template repository" / "Use this template" lines from Step 2.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: start a new project from this repo; dev stack is swb-proof-dev"
```

### Task 3: Deploy `swb-proof-dev` and prove sign-in again (by hand)

This needs AWS credentials (`aws sso login`), so a person runs it. `ProofDev` was destroyed on 2026-11-23, before this plan was written.

- [ ] **Step 1: Confirm the old stack is gone and the prefix is free**

Run: `aws cloudformation describe-stacks --region us-west-2 --stack-name ProofDev`
Expected: `Stack with id ProofDev does not exist`.

Run: `aws cognito-idp describe-user-pool-domain --region us-west-2 --domain swb-proof-dev --query DomainDescription`
Expected: `{}` (no domain holds the prefix).

- [ ] **Step 2 (optional): Delete the leftover log group**

Run: `aws logs describe-log-groups --region us-west-2 --log-group-name-prefix /aws/lambda/ProofDev --query 'logGroups[].logGroupName'`, then run `aws logs delete-log-group --region us-west-2 --log-group-name <name>` for each name it lists.

- [ ] **Step 3: Deploy**

Run: `cd web && npm ci && npm run build && cd ../infra && uv run pytest -q && cdk deploy swb-proof-dev`
Expected: `swb-proof-dev` reaches `CREATE_COMPLETE` and prints the eight outputs. `CognitoDomainUrl` is `https://swb-proof-dev.auth.us-west-2.amazoncognito.com`.

- [ ] **Step 4: Create the user and sign in**

Run the README's `admin-create-user` command with the new `UserPoolId`. Open `SiteUrl`, sign in, and set a password.
Expected: the page shows the email.

- [ ] **Step 5: Move T009 to review**

Run: `bot-todo --json review T009 && bot-todo --json validate`
Expected: T009 is in Review. T006 now runs against `swb-proof-dev`.

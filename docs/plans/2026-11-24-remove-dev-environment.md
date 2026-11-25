# Remove the Dev Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A push to `master` deploys QA, then prod after manual approval, with no Dev stage, and the dev stacks no longer exist.

**Architecture:** `ENVIRONMENTS` in `infra/environment.py` drives the pipeline's stages, so dropping `"dev"` from it removes the Dev stage. The tests that pinned dev now pin QA and prod. The pipeline updates itself on the next push. Removing the stage leaves dev's two stacks in place, so a person deletes them by hand: the Site stack first, then the edge stack, then the log groups CloudFormation never managed.

**Tech Stack:** AWS CDK (Python), CDK Pipelines, pytest via `uv`, AWS CLI.

**Spec:** Task T010 in `TODO.md` (acceptance and context), plus the decisions below.

## Decisions made for this plan (2026-11-24, with the user)

| Question | Decision |
|---|---|
| ADR form | Amend ADR 0001 in place, with a dated `Amended:` line. No new ADR: a stage is easy to add back. |
| Order with T011 | T010 first, on its own push to `master`. T011 (trigger from `build`) follows. |
| Glossary | **Environment** is "QA or prod". "Dev environment" is on its _Avoid_ list. Done in `CONTEXT.md` during planning. |
| Logical-id guard | Kept, renamed `DEPLOYED_IDS`, and run for QA and prod. Checked 2026-11-24: `swb-proof-qa` and `swb-proof-prod` have exactly the six ids pinned for dev. |
| Unmanaged log groups | Deleted by hand after the stacks. The README's Tear down section gains one line about them. |
| Historical text | Dated plans, ADR 0002's T006 check, ADR 0003's `ProofDev` story, Decision 10's Phase 2a note, and the README's Phase 2a row stay. Only present-tense text changes. |
| Who deletes | The executing agent runs each AWS delete only after the user confirms that step in the session. |
| Free plan | None of the distributions is subscribed (`list-subscriptions` was empty on 2026-11-24), and the user will not subscribe. The plan has no cancellation step. ADR 0001's cost table states the real pay-as-you-go cost. Whether to drop the Free plan setup is T012. |

## Global Constraints

- Docstrings follow `AGENTS.md`: Napoleon sections only when non-empty, and `#:` comments on module globals and attributes.
- Run the infra tests with `cd infra && uv run pytest -q`. Every task ends with them passing.
- Stage only the files each task names. `TODO.md` and `docs/plans/2026-11-23-platform.md` hold uncommitted edits by the user that are not part of T010. In particular, that plan's `master` → `main` edit is not part of T010.
- Stack names: `swb-proof-dev` (us-west-2) and `swb-proof-dev-edge` (us-east-1). Never type any other stack name into a delete command.
- Record no emails in T010's context.

## Review Focus

1. **The pipeline drops its Dev stage before the stacks are deleted.** Otherwise the next run recreates dev. This is pinned by Task 3's order: Step 2 checks the pipeline's stage list before any delete.
2. **The Site stack is deleted before the edge stack.** WAF refuses to delete a web ACL that a distribution uses, and the cross-region export writer refuses to delete parameters that a reader still holds. This is pinned by Task 3's step order.
3. **A refactor changes a logical id or a replacement-causing property on prod.** The retained prod pool would be orphaned, and a new empty pool would replace it. Logical ids are pinned by `test_deployed_logical_ids_are_unchanged` for QA and prod (Task 1). Property changes are caught by Task 1, Step 5's diff of the QA and prod stacks.
4. **Something still accepts `dev` as an environment.** A typo or an old script would synthesize a dev stack. This is pinned by `test_unknown_environment_fails["dev"]` (Task 1).
5. **A delete fails partway.** For example, `DELETE_FAILED` happens on a resource, or `wait` gives up after 60 minutes. The executor stops and reports the stack events, and does not retry with `--retain-resources` or delete resources by hand without the user (Task 3).

---

### Task 1: QA and prod only, in code and tests

**Files:**
- Modify: `infra/environment.py`, `infra/pipeline.py`
- Test: `infra/tests/test_environment.py`, `infra/tests/test_pipeline.py`

**Interfaces:**
- Produces, in `infra/environment.py`: `ENVIRONMENTS = ("qa", "prod")` and `LOG_RETENTION` with keys `qa` (`ONE_MONTH`) and `prod` (`SIX_MONTHS`). `environment_name(project_name, "dev")` raises `ValueError`. No signature changes.

- [ ] **Step 1: Make the tests describe QA and prod**

In `infra/tests/test_environment.py`:
- `_stage(..., environment="qa", ...)`. Change the `built` docstring to "The QA stack, …".
- `test_prefix_domain_classic_hosted_ui`: `"Domain": "swb-proof-qa"`.
- Rename `test_dev_config_is_never_uploaded` to `test_local_config_is_never_uploaded`, with the body unchanged.
- `test_retention_and_removal_by_environment`: drop the `("dev", …)` row.
- Rename `DEPLOYED_DEV_IDS` to `DEPLOYED_IDS`, with the same six entries. Its `#:` comment reads: "The logical ids every Environment was deployed with (pinned from swb-proof-dev at 787ad6c; swb-proof-qa and swb-proof-prod confirmed 2026-11-24)."
- Replace `test_dev_keeps_its_hand_deployed_logical_ids(built)` with:
  ```python
  def test_deployed_logical_ids_are_unchanged(stage):
      t = Template.from_stack(stage.environment_stack)
      for type_, logical_id in DEPLOYED_IDS.items():
          assert set(t.find_resources(type_)) == {logical_id}
  ```
- Rename `test_checked_in_project_name_names_the_dev_stack` to `…_names_the_qa_stack`, and assert `"swb-proof-qa"`.
- `test_another_project_name_renames_stack_and_prefix`: `acme-shop-qa` in both asserts.
- `test_unknown_environment_fails`: parametrize `env` over `["staging", "dev"]`, with `pytest.raises(ValueError, match=env)`.

In `infra/tests/test_pipeline.py`:
- Rename `test_dev_then_qa_then_approved_prod` to `test_qa_then_approved_prod`. Assert `names[-2:] == ["Qa", "Prod"]` and `"Dev" not in names`, where `names = [s["Name"] for s in stages]`. Then assert `approvals["Qa"] == []`, and loop the smoke check over `stages[-2:]`.
- `test_names`: `{"qa": "swb-proof-qa", "prod": "swb-proof-prod"}`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd infra && uv run pytest -q`
Expected: failures in `test_unknown_environment_fails[dev]`, `test_qa_then_approved_prod` (it still finds `Dev`), and `test_names`. The QA-default tests may already pass.

- [ ] **Step 3: Drop dev from `infra/environment.py` and `infra/pipeline.py`**

Set `ENVIRONMENTS = ("qa", "prod")` and remove the `"dev"` key from `LOG_RETENTION`. Update every docstring that lists environments. The module docstring becomes "(QA or prod)". The `environment` arguments and attribute become "``qa`` or ``prod``". `EnvironmentStack`'s docstring says "QA deletes them with the stack", and `EnvironmentStage`'s says "for example ``Qa``". Leave the `authMode dev` comment as it is, since it names the local config. In `pipeline.py`, the module docstring becomes "a push to ``master`` deploys QA, then prod after approval."

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd infra && uv run pytest -q`
Expected: all pass. `grep -n '"dev"' infra/environment.py infra/pipeline.py` prints nothing.

- [ ] **Step 5: Diff the pipeline and the QA and prod stacks against what is deployed**

Run: `cd web && npm ci && npm run build && cd ../infra && cdk diff swb-proof-pipeline`
Expected: the Dev stage's actions and their roles are removed, and nothing else changes. `cdk ls` lists no `Dev/` stacks.

Run: `cdk diff --method=template swb-proof-pipeline/Qa/Site swb-proof-pipeline/Qa/Edge swb-proof-pipeline/Prod/Site swb-proof-pipeline/Prod/Edge`
Expected: "There were no differences" for all four stacks, which was the baseline on 2026-11-24 before this change. `cdk diff swb-proof-pipeline` covers only the pipeline stack, not the stacks of its stages. **Do not push if any of the four shows a difference;** report it instead. The pipeline would deploy it to QA without a gate.

- [ ] **Step 6: Commit**

```bash
git add infra/environment.py infra/pipeline.py infra/tests/test_environment.py infra/tests/test_pipeline.py
git commit -m "feat(infra)!: the pipeline deploys QA then prod; dev is removed (T010)"
```

### Task 2: ADRs and README say QA and prod

**Files:**
- Modify: `docs/adr/0001-serverless-go-platform-architecture.md`, `docs/adr/0002-proof-application.md`, `docs/adr/0003-deployed-names-from-project-name.md`, `README.md`
- Add to the same commit: `CONTEXT.md` (already edited) and this plan.

- [ ] **Step 1: Amend ADR 0001**

- Header: add `**Amended:** 2026-11-24 (T010). Dev is removed: a push to master deploys QA, then prod after approval. For one developer, dev duplicated QA. Both deployed the same assets in turn, with the same smoke step and no gate between them. Plan: [remove dev](../plans/2026-11-24-remove-dev-environment.md).`
- Context: "Clear isolation between QA and prod".
- Decision 2: "Each environment (QA, prod) gets its own User Pool".
- Decision 3, Stages: **QA** deploys automatically on every push to `master`, with no approval gate. **Prod** requires manual approval. Add the line "*Superseded (2026-11-24):* a Dev stage deployed before QA." Under Alternatives, add *A dev stage before QA:* rejected 2026-11-24, for the reason in the header. Also add *Keeping the dev stacks as a sandbox outside the pipeline:* rejected, because a hand-deployed stack drifts from what the pipeline ships. Consequences: "(+) Fast feedback in QA" and "(+) The JavaScript bundle is identical in QA and prod". Add "(−) QA changes on every push, so it is not a stable place for someone else to test. Revisit when a second developer or outside testers arrive."
- Decision 8: "Every environment (QA and prod)".
- Decision 9: retitle it "QA and prod on AWS, plus local development". Remove the **Dev on AWS** bullet. **QA on AWS** becomes "Deploys automatically on push to `master`. It is the first place real AWS behavior is tested, including the JWT authorizer, and it is pre-production validation." Add the line "*Superseded (2026-11-24):* a shared dev environment deployed before QA." Rationale: QA, not dev, catches AWS-only problems before prod. Consequences: "Two copies of the remaining stack".
- Cost baseline: the assumptions say no distribution is subscribed (checked 2026-11-24). Each web ACL has 4 rules: the rate limit and the three managed rule groups, each billed as one rule. Prices are from https://aws.amazon.com/waf/pricing/, checked 2026-11-24. The table has two rows: web ACL, 2, $10.00; and rules, 8, $8.00. Total about $18/month at idle, through 2027-01-31. Then: "From 2027-02-01, AWS WAF drops the web ACL and rule charges and bills $0.01 per hour per protected resource, so two distributions cost about $14.60/month at idle. Requests cost $0.60 per million under both. With both distributions on the Free plan it would be about $0. Whether to subscribe is T012." Free plan paragraph: "this Project's two environments would use two of the three."
- Open question 4: "at about $9 per month for its web ACL and rules (about $7.30 from 2027-02-01)", replacing "$8".
- Open question 3: "one month in QA, six months in prod … QA log groups are deleted with their stack."
- Leave Decision 10's Phase 2a note unchanged.

- [ ] **Step 2: ADR 0002 and ADR 0003**

- ADR 0002: "ADR 0001 promotes one commit through QA and prod." Its follow-up already says "a deployed environment", and its T006 record stays as written.
- ADR 0003, paragraph 1: the environment is `qa` or `prod`. The example becomes "QA is the stack `swb-proof-qa` with the prefix `swb-proof-qa`." The `ProofDev` paragraph stays.

- [ ] **Step 3: README**

- "Start a new project": "one project's two environments use two of them, leaving one", and keep the pay-as-you-go sentence.
- Rename "Phase 2b: the pipeline and three environments" to "… and two environments". Change the deploy order to "to QA, then prod after a manual approval", and "Each environment (`qa`, `prod`)". Use "QA keeps logs for a month and deletes everything with its stack."
- Replace the Phase 2a hand-off sentence with: "Phase 2a's hand-deployed dev stack became the pipeline's dev stack. T010 removed dev on 2026-11-24, so QA is now the first environment."
- Test table: `test_environment.py` covers "synthesized for QA and prod" and "the logical ids of the deployed QA and prod stacks don't change". `test_pipeline.py` covers "QA, then prod after approval, with a smoke step after each; there is no Dev stage."
- Setup step 6: "each of the two distributions". Step 7: `for env in qa prod` and `--stack-name swb-proof-qa`. Construct-path example: `swb-proof-pipeline/Qa/Site`.
- Releasing: "QA deploys on its own."
- Tear down, step 2: delete `swb-proof-prod` and `swb-proof-qa`, then the two `-edge` stacks. Add a step: "Delete the leftover `/aws/lambda/swb-proof-<env>-…` log groups in `us-west-2` and `us-east-1`. Custom-resource Lambdas created them, CloudFormation never managed them, and they never expire."

- [ ] **Step 4: Check for leftovers**

Run: `grep -n -i -E "\bdev\b" README.md docs/adr/*.md CONTEXT.md`
Expected: every hit is local development (`AUTH_MODE=dev`, `npm run dev`, `dev@localhost`, `authMode`), history (Phase 2a, T006, `ProofDev`, Decision 10's note, the `Superseded` lines), or the glossary's _Avoid_ list.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0001-serverless-go-platform-architecture.md docs/adr/0002-proof-application.md docs/adr/0003-deployed-names-from-project-name.md README.md CONTEXT.md docs/plans/2026-11-24-remove-dev-environment.md
git commit -m "docs: QA and prod are the environments; dev is removed (T010)"
```

### Task 3: Ship, then delete dev (by hand, with the user)

Each step that deletes something waits for the user's go-ahead in the session. Record each result in T010's context with `bot-todo --json edit T010 --context ...`, keeping the existing text.

- [ ] **Step 1: Push**

Run: `git push origin master`
Expected: a run of `swb-proof-pipeline` starts. Its `UpdatePipeline` stage updates the pipeline and restarts the run.

- [ ] **Step 2: Confirm that the pipeline has no Dev stage**

Run: `aws codepipeline get-pipeline --region us-west-2 --name swb-proof-pipeline --query "pipeline.stages[].name" --output text`
Expected: `Source  Build  UpdatePipeline  Assets  Qa  Prod`, with no `Dev`. **Do not go on until this holds.**

- [ ] **Step 3: Let the run finish**

Qa and its Smoke step succeed. Approve `PromoteToProd`, and Prod and its Smoke step succeed.

- [ ] **Step 4: Note what the cross-region writer holds for dev**

Run: `aws ssm get-parameters-by-path --region us-west-2 --path /cdk/exports/swb-proof-dev --recursive --query "Parameters[].Name"`
Expected: a list, probably one web ACL ARN parameter. Record it, because Step 7 checks that it is gone.

- [ ] **Step 5: Delete the dev Site stack (confirm first)**

```bash
aws cloudformation delete-stack --region us-west-2 --stack-name swb-proof-dev
aws cloudformation wait stack-delete-complete --region us-west-2 --stack-name swb-proof-dev
```
Expected: the wait returns with exit code 0. On any non-zero exit, including `DELETE_FAILED` or the wait giving up after 60 minutes (a CloudFront distribution can be slow to delete), stop, run `describe-stacks` and `describe-stack-events`, and show the user before doing anything else (Review Focus 5).

- [ ] **Step 6: Delete the dev edge stack (confirm first)**

```bash
aws cloudformation delete-stack --region us-east-1 --stack-name swb-proof-dev-edge
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name swb-proof-dev-edge
```
Expected: exit code 0. The same stop rule applies.

- [ ] **Step 7: Check that both stacks and their exports are gone**

Run `aws cloudformation describe-stacks --region us-west-2 --stack-name swb-proof-dev`, then the same with `--region us-east-1 --stack-name swb-proof-dev-edge`.
Expected: each fails with `Stack with id … does not exist`. Rerunning Step 4's command returns `[]`.

- [ ] **Step 8: Delete the log groups CloudFormation left (confirm first)**

List them, then delete each one by name:
```bash
for r in us-west-2 us-east-1; do
  aws logs describe-log-groups --region $r --log-group-name-prefix /aws/lambda/swb-proof-dev \
    --query "logGroups[].logGroupName" --output text
done
aws logs delete-log-group --region <region> --log-group-name <name>
```
Expected: on 2026-11-24 there was one, `/aws/lambda/swb-proof-dev-CustomS3AutoDeleteObjectsCustomResou-0fNPcju1seVB` in `us-west-2`, and the deletes may have created more. Afterwards, both listings are empty.

- [ ] **Step 9: Close out**

Run `bot-todo --json review T010`, then `bot-todo --json validate`. T011 is now unblocked in practice.

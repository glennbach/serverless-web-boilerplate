# Deploy from the Build Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A push to `build` starts the pipeline and a push to `master` alone does not. You deploy on purpose with `git push origin master:build`.

**Architecture:** The pipeline's source action reads the branch named by `BRANCH` in `infra/pipeline.py`. Changing it to `"build"` is the whole code change. The pipeline updates itself, so the change takes effect on the first run after the commit reaches the branch the pipeline watches *today*, which is `master`. `build` must already exist on GitHub at that point. If it doesn't, the restarted run fails at Source.

**Tech Stack:** AWS CDK (Python), CDK Pipelines (V2 pipeline, CodeConnections source), pytest via `uv`, git, AWS CLI.

**Spec:** Task T011 in `TODO.md` (acceptance and context), plus the decisions below.

## Decisions made for this plan (2026-11-25, with the user)

| Question | Decision |
|---|---|
| ADR form | Amend ADR 0001 in place, with a dated `Amended:` line. No new ADR: the branch is one constant and easy to change back. |
| Vocabulary | **Deploy** means putting a commit from `master` onto `build`, which puts it in QA. **Promote** means approving `PromoteToProd`. "Ship" and "release" are avoided. These were added to `CONTEXT.md` during planning. The README's "Releasing" section is renamed "Deploying and promoting". |
| Where the branch lives | It stays in the module constant `BRANCH = "build"`. There is no `cdk.json` setting. |
| New copies of the Project | README one-time setup step 4 runs `git push origin master:build` just before `cdk deploy`. By then `build` holds step 2's committed `repository` and `connectionArn`. Revised 2026-11-25 after review: step 1 was too early. |
| Rules for `build` | Only fast-forward it from `master`, and never force-push it. Roll back by reverting on `master` and deploying. There is no GitHub branch protection rule; add one when a second person can push. |
| Proving master doesn't deploy | Push T011's docs-only closing commit to `master` alone and confirm no run starts. Then deploy it and confirm a run starts. |
| PromoteToProd | Approve the cutover run and the verification run once QA's smoke step passes. Prod's stacks don't change. |
| Who pushes | Sometimes the user pushes. Otherwise the agent pushes, but only after the user confirms that step in the session. Either way, the agent runs the AWS checks after each push. |

## Global Constraints

- Docstrings follow `AGENTS.md`: Napoleon sections only when non-empty, and `#:` comments on module globals and attributes.
- Run the infra tests with `cd infra && uv run pytest -q`. Every task ends with them passing.
- Change only present-tense text. Dated plans, ADR 0001's earlier `Amended:` lines, and `*Superseded*` notes stay as they are.
- Don't push to `origin` before Task 3. Local commits are fine.
- Local `master` is one commit ahead of `origin/master` (`29445e6`, the docs-only "T010 done" commit). It goes out with the cutover push, which is expected.
- AWS checks need a live SSO session. If a command reports that the session expired, ask the user to run `! aws sso login`.

## Review Focus

1. **`build` must exist before the pipeline switches to it.** Otherwise the run that restarts after self-mutation fails at Source, and only a hand fix recovers it. Task 3's step order pins this: create `build` (Step 3), then push `master` (Step 5).
2. **The source branch is `build` and nothing else.** `test_source_is_build_on_github` pins it (Task 1). Task 3, Step 6 checks the live pipeline.
3. **Moving `build` back past T011 points the pipeline at `master` again.** The README documents the rule: only fast-forward, roll back by reverting on `master` (Task 2).
4. **A push to `master` still starts a run.** For example, a V2 trigger filter or a second source could do this. Task 4 tests it against the live pipeline.

---

### Task 1: The pipeline reads `build`

**Files:**
- Modify: `infra/pipeline.py`
- Test: `infra/tests/test_pipeline.py`

- [ ] **Step 1: Make the test expect `build`**

In `infra/tests/test_pipeline.py`, rename `test_source_is_master_on_github` to `test_source_is_build_on_github`, and change `"BranchName": "master"` to `"BranchName": "build"`.

- [ ] **Step 2: Confirm it fails**

Run: `cd infra && uv run pytest -q tests/test_pipeline.py -k source`
Expected: FAIL. `BranchName` is `master`.

- [ ] **Step 3: Change the branch and the docstring**

In `infra/pipeline.py`:
- Module docstring, first line: `"""The Project's delivery pipeline: a push to ``build`` deploys QA, then prod after approval.`
- Add a second paragraph to the module docstring: "Deploy with ``git push origin master:build``. A push to ``master`` alone deploys nothing."
- `#: The branch whose pushes start the pipeline. Only fast-forward it from master.`
- `BRANCH = "build"`

- [ ] **Step 4: Run every infra test**

Run: `cd infra && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add infra/pipeline.py infra/tests/test_pipeline.py
git commit -m "feat(infra)!: the pipeline deploys from build, not master (T011)"
```

---

### Task 2: Docs say a push to `build` deploys

**Files:**
- Modify: `README.md`, `docs/adr/0001-serverless-go-platform-architecture.md`

- [ ] **Step 1: README**

- Phase 2b intro (line 132): "A push to `build` on GitHub runs it. You deploy with `git push origin master:build`; a push to `master` alone runs nothing."
- `test_pipeline.py` row in the suites table (line 164): "The source is `build` on GitHub."
- One-time setup, step 1: leave it as it is (`master` only). Step 2's `repository` and `connectionArn` are not committed yet, so a `build` created here would be stale.
- One-time setup, step 4: before `cdk deploy`, create `build` from the commit that holds step 2's settings. Add this as the first command of the step's code block, with the comment `# the pipeline reads build, and its first run must see step 2's settings`:
  ```bash
  git push origin master:build
  ```
  Why: `cdk deploy` uses the local `cdk.json`, but the pipeline's first run synthesizes from `build` and then updates itself. If `build` is missing, that run fails at Source. If `build` is stale, it fails at synth or undoes the settings. AWS documents this: the pipeline's source must hold the committed configuration before the first deploy ([CDK Pipelines, "Deploying the pipeline"](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.pipelines-readme.html#deploying-the-pipeline)).
- Rename `### Releasing` to `### Deploying and promoting`, and replace its body with:

  ~~~markdown
  **Deploy** a commit by putting `master` onto `build`:

  ```bash
  git push origin master:build
  ```

  The pipeline tests it and puts it in QA. A push to `master` alone deploys nothing. To **promote** the commit to prod, approve `PromoteToProd` in the CodePipeline console. An approval expires after 7 days, and the run must then be started again.

  Only fast-forward `build` from `master`, and never force-push it. To roll back, revert on `master` and deploy. Moving `build` back to a commit from before T011 would make the pipeline watch `master` again.
  ~~~

- Leave copy step 1 (line 28) as it is: the new repository still gets `master`. Setup step 4 now creates `build`.

- [ ] **Step 2: ADR 0001**

- Add after the T010 line: `- **Amended:** 2026-11-25 (T011). A push to build deploys; a push to master alone does not. Deploys should happen only on purpose. Plan: [deploy from build](../plans/2026-11-25-deploy-from-build-branch.md).`
- Decision 3: the first line already says "A Git push to the build branch triggers CodePipeline". Make it "A Git push to the `build` branch triggers CodePipeline. A deploy is `git push origin master:build`; a push to `master` alone deploys nothing."
- Decision 3, QA stage: "Deploys automatically on every push to `build`, with no approval gate."
- Decision 3, alternatives: add "*Deploying on every push to `master`:* Rejected 2026-11-25. Deploys should happen only on purpose, not as a side effect of saving work."
- Decision 3, consequences: "(−) QA changes on every deploy, so it is not a stable place for someone else to test. …" (the rest unchanged).
- Decision 9, QA bullet: "Deploys automatically on push to `build`."

- [ ] **Step 3: Check for leftover present-tense `master` deploys**

Run: `grep -n "push to \`master\`\|push to master\|Push to \`master\`" README.md docs/adr/0001-serverless-go-platform-architecture.md infra/*.py`
Expected: only the T010 `Amended:` line in ADR 0001, plus text that says a push to `master` alone deploys nothing.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/adr/0001-serverless-go-platform-architecture.md
git commit -m "docs: a push to build deploys; master alone does not (T011)"
```

If this plan, `CONTEXT.md`, and `TODO.md` are still uncommitted, commit them first: `docs: plan T011 (deploy from build); glossary adds Deploy and Promote`.

---

### Task 3: Cutover

Each push needs the user's go-ahead in the session. The user may run it, or say "go ahead" and the agent runs it. After each push, the agent runs the check that follows it.

- [ ] **Step 1: Check the live pipeline before touching it**

```bash
aws codepipeline get-pipeline --region us-west-2 --name swb-proof-pipeline \
  --query "pipeline.{type:pipelineType,triggers:triggers,branch:stages[0].actions[0].configuration.BranchName}"
aws codepipeline list-pipeline-executions --region us-west-2 --pipeline-name swb-proof-pipeline --max-items 3 \
  --query "pipelineExecutionSummaries[].[pipelineExecutionId,status,sourceRevisions[0].revisionId]" --output text
```

Expected: branch `master`, and no run `InProgress`. If an earlier run is waiting at `PromoteToProd`, tell the user before going on, because the cutover run supersedes it. Note the newest execution ID.

The later checks track runs **by execution ID**, never by `get-pipeline-state`. That command shows each stage's latest status from any run, so it can show an earlier run's success. Define these helpers in every shell that runs a check:

```bash
P="--region us-west-2 --pipeline-name swb-proof-pipeline"
# Runs for one commit, newest first: id, status, trigger.
runs() { aws codepipeline list-pipeline-executions $P --max-items 20 \
  --query "pipelineExecutionSummaries[?sourceRevisions[0].revisionId=='$1'].[pipelineExecutionId,status,trigger.triggerType]" --output text; }
# One run's actions: stage, action, status.
actions() { aws codepipeline list-action-executions $P --filter pipelineExecutionId="$1" \
  --query "actionExecutionDetails[].[stageName,actionName,status]" --output text; }
```

Polling rule: check once a minute. **Stop and report** as soon as any action in the tracked run is `Failed`, or when the step's timeout passes. Don't push again until the user decides.

- [ ] **Step 2: Run every test suite locally**

Run: `(cd api && go vet ./... && go test ./...) && (cd web && npm ci && npm test && npm run build) && (cd infra && uv run pytest -q)`
Expected: all pass. The pipeline's synth step runs the same suites.

- [ ] **Step 3: Create `build` at the cutover commit** (needs go-ahead)

```bash
git push origin master:build
```

The pipeline still watches `master`, so this starts nothing.

- [ ] **Step 4: Confirm that creating `build` started nothing**

Run the `list-pipeline-executions` command from Step 1.
Expected: the newest execution ID is unchanged.

- [ ] **Step 5: Push `master`** (needs go-ahead)

```bash
git push origin master
```

- [ ] **Step 6: Watch the switch, by execution ID**

`SHA=$(git rev-parse master)`.

1. **Find the push run.** Poll `runs $SHA` until one execution appears, with a 5-minute timeout. Record its ID as `RUN1`.
2. **Wait for its self-mutation.** Poll `actions $RUN1` until the `UpdatePipeline` stage's action is `Succeeded`, with a 30-minute timeout.
3. **Check the switch.** Run Step 1's `get-pipeline`. Expected: branch `build`, and `triggers` empty or limited to `build`.
4. **Find the restarted run.** The pipeline restarts after it updates itself. Poll `runs $SHA` until a second, newer execution appears, with a 5-minute timeout. Record its ID as `RUN2`. `RUN1` should then show `Superseded` or `Stopped`. If no second run appears, stop and report; the user may start one with `aws codepipeline start-pipeline-execution --name swb-proof-pipeline --region us-west-2`.
5. **Follow `RUN2`.** Poll `actions $RUN2` until `Source`, `Build`, `UpdatePipeline`, and every `Qa` action (deploys and `Smoke`) are `Succeeded`, with a 60-minute timeout. A failed `Source` in `RUN2` means `build` was not readable (Review Focus 1).

- [ ] **Step 7: Promote `RUN2`**

When `actions $RUN2` shows `PromoteToProd` as `InProgress`, ask the user to approve it in the console. Alternatively, after they say so, approve it with `aws codepipeline put-approval-result`. Take the token from `get-pipeline-state`'s `Prod` stage, and use it only if that stage's `latestExecution.pipelineExecutionId` equals `RUN2`. Poll `actions $RUN2` until every `Prod` action, including `Smoke`, is `Succeeded`, with a 60-minute timeout after approval.

---

### Task 4: Prove `master` doesn't deploy, then close

- [ ] **Step 1: Move T011 to review and commit**

```bash
bot-todo --json validate && bot-todo --json review T011 && bot-todo --json validate
git add TODO.md && git commit -m "chore: T011 to review"
```

- [ ] **Step 2: Push `master` alone** (needs go-ahead)

`git push origin master`. Note the time.

- [ ] **Step 3: Confirm no run started**

Wait at least 5 minutes. With `SHA=$(git rev-parse master)`, run `runs $SHA`, and run Task 3, Step 1's `list-pipeline-executions`.
Expected: `runs $SHA` prints nothing, and the newest execution is still `RUN2`. If a new run started, stop: Review Focus 4 has happened.

- [ ] **Step 4: Deploy it** (needs go-ahead)

`git push origin master:build`

- [ ] **Step 5: Confirm a run started from `build`**

Poll `runs $SHA` until one execution appears, with a 5-minute timeout. Record its ID as `RUN3`. It is the proof that a push to `build` starts a run. This commit doesn't change the pipeline, so there is no restart. Follow `actions $RUN3` through `Qa` and promote it, as in Task 3, Steps 6.5 and 7, with the same polling rule and timeouts.

- [ ] **Step 6: Record and complete**

- Add both observations (times, plus `RUN1`, `RUN2`, and `RUN3`) to T011's context with `bot-todo --json edit T011 --context "…"`. Keep the existing context text.
- `bot-todo --json complete T011`, then `validate`.
- Commit `TODO.md` (`chore: T011 done; deploys come from build`). Pushing it to `master` deploys nothing, so it is safe to push. It still needs the user's go-ahead.
- Delete the memory `no-push-until-t011.md` and its line in `MEMORY.md`.

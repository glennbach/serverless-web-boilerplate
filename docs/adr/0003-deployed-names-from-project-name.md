# 0003. Deployed names are `<projectName>-<environment>`

- **Status:** Accepted
- **Date:** 2026-11-23
- **Task:** T009 ([plan](../plans/2026-11-23-project-name.md))

A copy of this repository must deploy as its own Project by changing one value. Each Environment's CloudFormation stack name and its Cognito Hosted UI prefix are therefore both the string `<projectName>-<environment>`. `projectName` is the only naming value in `infra/cdk.json`, and the environment is `dev`, `qa`, or `prod`. This repository's `projectName` is `swb-proof`, so dev is the stack `swb-proof-dev` with the prefix `swb-proof-dev`. Synth rejects a `projectName` that cannot produce a valid prefix for every environment. The name must use only lowercase letters, digits, and hyphens, start with a letter, and not end with a hyphen. It may be at most 58 characters, so that `<name>-prod` fits Cognito's limit of 63. It must not contain `aws`, `amazon`, or `cognito`, which Cognito refuses in a prefix.

## Considered Options

- **A PascalCase stack name with a kebab-case prefix** (`SwbProofDev` and `swb-proof-dev`): rejected. That is two names to keep in step and a case-conversion rule to maintain. CloudFormation accepts hyphens in stack names.
- **The account id in the prefix**, to make it unique automatically: rejected for the reason given in the dev-environment plan. The prefix is part of the public Hosted UI URL, and the account id should not be. The cost is that each Project must choose a distinctive name, because prefixes are unique per region across all AWS accounts.
- **A name override for each environment** (separate stack-name and prefix settings): rejected. That is more than one value to change, and it is the drift T009 exists to remove.

## Consequences

- Changing `projectName` does not rename an Environment. It creates a new one, with a new stack, a new prefix, and a new User Pool with no users. The old Environment stays deployed and untouched, because its stack name and prefix both differ from the new ones. Destroy the old Environment only when you no longer want it. Its users do not move to the new pool.
- The one case that required destroying first was the move to this rule. `ProofDev`'s prefix, `swb-proof-dev`, was set separately from its stack name. The new stack `swb-proof-dev` needed that same prefix, so `ProofDev` was destroyed before `swb-proof-dev` was first deployed.
- Two Projects in one account do not collide, as long as their `projectName`s differ. A copy that keeps `swb-proof` would update this Project's stacks.
- T007's QA and prod stacks get their names from the same rule (`swb-proof-qa`, `swb-proof-prod`). T007 adds two more names, also derived from `projectName`. Each environment's `us-east-1` web ACL stack is `<projectName>-<environment>-edge`. The pipeline stack and the CodePipeline pipeline are `<projectName>-pipeline`. There is no hosted zone stack, because the Proof has no domain (ADR 0001, Decision 8). Every one of these names stays within its AWS length limit when `projectName` is 58 characters long.

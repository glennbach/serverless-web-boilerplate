# AGENTS.md

## Local Overrides

This repository inherits shared defaults from:
- `~/AGENTS.md` (workspace-root shared instructions)

## Repository Bootstrap Requirements

These requirements apply at the start of every new session in this repository.

1. Read `~/AGENTS.md` before planning or implementation.
2. Treat the shared file as mandatory for this repository, not optional guidance.
3. Confirm in an early progress update that the shared file was read.

## Documentation Contract (Required)

For all non-test Python code in this repository:

1. Class docstrings must describe the class contract and include constructor `Args:` when constructor arguments exist.
2. Function/method docstrings must include:
   - brief description
   - `Side Effects:` (only when there are real side effects; omit otherwise)
   - `Args:` (only when positional args exist; omit otherwise)
   - `Keyword Args:` (only when keyword args exist; omit otherwise)
   - `Raises:` (only when meaningful exceptions are raised; omit otherwise)
   - `Returns:` or `Yields:` (only when applicable; omit otherwise)
   - Do not add placeholder content such as `None.` for empty/inapplicable sections.
   - Never add `Args:`/`Keyword Args:`/`Returns:`/`Yields:` sections when they would be empty or semantically `None`.
3. Document all of the following with Napoleon `#:` comments:
   - class attributes
   - instance attributes assigned in `__init__`
   - module-level global variables

<!-- ### Enforcement command:

- `make napoleon-gate` (no new violations vs baseline)
- `make napoleon-gate-strict` (all violations; use when explicitly requested)
-->

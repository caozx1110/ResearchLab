# R14 — recovery canonical-root alias fix

## STEP 0 — base sync

Work only in the assigned isolated worktree. Verify its HEAD contains main commit `2db7057` and the recovery canonical-root rule in `.agents/lib/research/SCHEMAS.md`. If not, stop and report; do not reset or merge while the shared integration agent is active.

## Objective

Fix the reproduced macOS path-alias bug in recovery: a project root supplied through `/var/...` can produce restored targets resolved through `/private/var/...`, so post-restore result projection raises `ValueError` after content was already restored. Target resolution, locks, writes, checkpointing, and result projection must use one canonical KB root. Alias and canonical entry points must return the same relative `restored_paths`.

## File ownership

Edit only:

- `.agents/lib/research/git_ops.py`
- `.agents/lib/research/tests/test_recovery_contract.py`
- `.agents/lib/research/tests/test_r1_recovery_source.py` only if a source-contract assertion is needed

Do not edit design docs, version files, changelog, installer files, or any other implementation.

## Required regression

Use a temporary directory only. On macOS, exercise the real `/var` to `/private/var` alias (skip narrowly if the platform has no distinct alias). Prove that restore/undo through the aliased project root:

1. completes without a projection exception;
2. restores the exact bytes;
3. returns a stable KB-relative path such as `notes/item.md`, identical to the canonical-root call shape;
4. leaves a coherent committed recovery journal/checkpoint rather than a post-write half-failure.

Prefer a canonical base established before mutation and used for both target operations and returned relative paths. Preserve all after-state CAS, exact-target locks, zero-churn, and no-candidate read-only behavior.

## Red lines

- Never touch a real `kb/`; tests use temporary directories.
- Do not weaken governance, after-state CAS, exact target scoping, journal atomicity, or lock scope.
- No broad staging; no push, tag, publish, or dependency install.
- User-visible output remains natural language plus `kb <verb>` only; no raw shell, internal paths, flags, environment expansions, or TTY dependency.
- STOP and report if the requested fix needs files outside ownership.

## Verification and commit

Run the focused recovery suites and `git diff --check`. Independently inspect the journal/checkpoint outcome in the regression. Commit the bounded fix with a clear conventional message and report commit hash, tests, and any residual risk.

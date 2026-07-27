# R12 source-intake receipt + zero-write repair

## STEP 0 — base sync

- Create an isolated worktree/branch from exact integration base `34c4114e7902fa18395a2708df2b2b9c90a48e9e`; verify `git rev-parse HEAD` before editing.
- If a reused worktree is stale, hard-reset only that isolated worktree to the exact base, never the maintainer worktree.

## Ownership

Only modify:

- `.agents/skills/source-intake/scripts/intake.py`
- new or intake-specific tests under `.agents/lib/research/tests/` whose filenames start `test_intake_`

Do not edit shared preference registry, paper, experiment, docs, version, existing shared preference matrix, real `kb/`, or unrelated files.

## Reproduced blockers

1. `source-intake:add` bypasses preference validation for non-paper kinds and for missing selection id. Every kind must resolve `source-intake:add`: supplied receipt is strictly validated; absent receipt uses hard-only fallback. Only paper-specific runtime values may be extracted conditionally. Persist value-free hard/selection digests, never soft values.
2. Current code writes source/parse staging under workspace before rejecting a stale/wrong receipt. Receipt/authorization/containment failure must leave zero files anywhere in the workspace. Mechanical fetch/parse needed to form context must occur in a controlled workspace-external temp directory, then atomically promote only after full validation. No real `kb/` tests.

## Required adversarial tests

- wrong-skill/wrong-operation/wrong-task receipts for repo/dataset/blog/paper: nonzero and byte-for-byte zero workspace write.
- no receipt + hard constraints: hard fallback is enforced and value-free binding persists on success.
- no receipt must not read/apply soft preferences.
- same-path relevant input/authorization/source mutation invalidates old receipt before promotion.
- ordinary success and duplicate path retain existing behavior and provenance.
- test stage cleanup after any exception.

## Red lines

- Scripts fetch/parse/move/validate only; no semantic research judgement.
- Do not weaken user selection/confirmation/evidence gates.
- Public output remains natural language/`kb <verb>` only; no paths/flags/TTY.
- No push. Small commits. Stop and report if fixing requires files outside ownership.

Run targeted intake/preference tests, `py_compile`, `git diff --check`; commit all owned changes and report commit hashes.

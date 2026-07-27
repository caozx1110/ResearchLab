# R12 experiment allocator binding repair

## STEP 0 — base sync

- Create an isolated worktree/branch from exact integration base `34c4114e7902fa18395a2708df2b2b9c90a48e9e`; verify HEAD before editing.

## Ownership

Only modify:

- `.agents/skills/experiment-workbench/scripts/experiment.py`
- new experiment-specific tests under `.agents/lib/research/tests/` whose filenames start `test_experiment_`

Do not edit shared preference registry/matrix, paper, intake, docs/version, real `kb/`, or unrelated files.

## Reproduced blocker

`experiment-workbench:log-run` chooses the run id only after receipt validation. If `runs/run-001.md` is inserted after selection, the old receipt remains current and the operation silently writes `run-002.md`.

Freeze the proposed run id/path plus a deterministic allocator directory-entry digest in canonical task inputs. Revalidate that allocator state inside the same root transaction/CAS boundary immediately before creation. Concurrent insertion, deletion, type change, symlink, or byte/entry drift must fail closed with zero business writes; no overwrite or alternate id fallback after a receipt has been selected. Preserve normal plan/log/follow-up/diagnose behavior and preference value-free persistence.

Add two-round adversarial tests covering pre-created run insertion after receipt, symlink/special entry, concurrent state drift, normal first and subsequent allocations, stale receipt zero write, and existing recovery semantics.

Red lines: scripts do not judge research; governance only tightens; public output contract unchanged; no push. Run targeted experiment/preference tests, `py_compile`, `git diff --check`; commit and report hashes.

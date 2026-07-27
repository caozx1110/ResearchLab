# R10 preference binding — method/experiment

## STEP 0 — base sync

Create an isolated worktree/branch from exact integration HEAD `e3c9ec4`. Verify the base before editing; stop if different. Never reset or modify the main worktree.

## Objective

Make each real preference consumer bind every operation input it actually consumes. Persist only bounded identities/digests where paths, authorization, claims, or free text may be sensitive.

## File ownership

Only edit:

- `.agents/skills/method-designer/scripts/method.py`
- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `test_method_designer.py`, `test_r2_method_lifecycle.py`, `test_experiment_workbench.py`, `test_preference_consumer_matrix.py` only where directly relevant
- `.agents/lib/research/SCHEMAS.md` only if required

Do not edit other skills, central registry, orchestrator/prefs/version/docs.

## Required contracts

1. `method-designer:design`: context must include idea canonical digest plus normalized explicit repo/interface/baseline/metric/risk inputs and the program-state/active-repo corpus snapshot used by ranking. Persist a value-free `preference_task_inputs`/digest in the method proposal so verify/confirm can recompute from current canonical inputs; changes after prepare stale the receipt instead of silently reusing it. Preserve existing governance and evidence gates.
2. `experiment-workbench:plan`: retain current complete binding.
3. `log-run`: additionally bind next_action, verified artifact identities/content/status (not raw unsafe paths), why_this_run, tags, recent_runs, rerun flag/reason and every already-bound run input. Compute/validate read-only artifact facts before preference resolution; stale failure precedes run/canonical writes.
4. `follow-up`: bind evidence_needed.
5. `diagnose`: bind current claims-file content/identity digest (not plaintext path), as well as all existing inputs/current record. Changing claims bytes at same path must stale the receipt before diagnosis write.

## Tests

Add operation→consumed-input mutation matrices. Every single field mutation must change the task context and reject an old selection. Include same artifact/claims path with changed bytes. Assert zero new run/follow-up/diagnosis canonical artifacts on stale failure.

## Red lines

- Scripts validate/move data; no research interpretation.
- Temp workspaces only; no push; no raw path/secret in persisted receipt; no TTY/output regression.
- Exact transactions, confirmation gates and existing epistemic types must stay intact.
- Small commits, targeted tests, py_compile, diff-check. STOP-and-report if a current invariant conflicts.


# R10 preference binding — report/paper

## STEP 0 — base sync

Create an isolated worktree/branch from exact integration HEAD `e3c9ec4`. Verify base commits first; stop if different. Do not touch the main worktree.

## Objective

Close report and paper preference replay gaps with owner-recomputed, content-bound contexts and field-mutation regression coverage.

## File ownership

Only edit:

- `.agents/skills/report-author/scripts/report.py`
- `.agents/skills/paper-analyst/scripts/paper.py`
- `test_report_author.py`, `test_paper_analyst_machinery.py`, `test_preference_consumer_matrix.py` only as needed
- `.agents/lib/research/SCHEMAS.md` only if required

Do not edit any other skill, central registry, prefs/orchestrator/version/docs.

## Required contracts

1. Every `report-author` operation context must bind program/op/stage/limit plus the exact loaded report input snapshot it renders: current accepted reporting events, confirmed claim sources/bindings, decisions, pending judgement handling and missing-unit set. Build a bounded canonical digest after pure reads but before output write. Event/claim/decision/source changes stale an old style receipt.
2. Every real `paper-analyst` preference operation must bind its own consumed inputs, not a generic partial record: current relevant record/content/source identity; parse-cache/source artifact byte digests for operations that read them; phase/mode/force/defer_post_actions; and fill input identity/content digest for screen/complete-note verify paths. Never persist raw absolute paths or fill contents in receipt. Same input path with changed bytes must stale before canonical mutation.
3. Keep confirm/reject outside preference consumers and retain current governance fixes.

## Tests

Create an operation matrix for all five paper operations plus all report operations. Mutate each consumed argument/source/input digest independently and prove old selection rejects. Include report event/claim change and same-path paper fill/cache byte change. Assert failure occurs before canonical writes.

## Red lines

- Analyzer scripts do not understand papers; runtime Agent authors understanding.
- Temp roots only, no push, no secret/path leakage, no TTY, no governance weakening.
- Small commits, targeted tests, py_compile and `git diff --check`; STOP-and-report on ambiguity.


# R26 authoritative-root commit guard lifetime

## STEP 0 — exact continuation

Continue `/private/tmp/workspace-oss-r26-commit-guard`, branch `codex/r26-commit-guard-repro`. It is based on the prior red/fix chain and now has red commit `5207659`. Verify the exact new test fails because the child body runs and no `SystemExit` is raised. Do not edit the main worktree.

## Ownership

May edit only:

- `.agents/lib/research/journal.py`
- `.agents/lib/research/SCHEMAS.md`
- `.agents/lib/research/tests/test_recovery_contract.py`
- `.agents/lib/research/tests/test_report_author.py`
- `.agents/lib/research/tests/test_agent_next_selection.py`
- only if needed for inherited-context coverage: `.agents/lib/research/tests/test_r1_recovery_source.py`

Do not edit report/orchestrator implementation, records.py, installer/version/docs, ignored SSOT/BACKLOG, real `kb/`, or unrelated fixtures.

## Independently reproduced defect

The current primitive runs a commit guard at child/inherited journal commit. The authoritative root can continue afterward, so the guard can become stale before root commit. Original reviewer reproduced stale formal report/history in same-process and inherited subprocess paths; main agent independently reproduced that a nested guarded mutation is accepted and its body runs (`5207659`).

## Locked design: root-only, fail closed

Arbitrary runtime callbacks are not serialized and cannot be safely kept alive across processes. Therefore:

1. `commit_guard` is valid only on an authoritative root `mutation_transaction`.
2. If `current_operation_id(project_root)` indicates a same-process or `journal_subprocess_env` parent, validate the normal nested parent/target relationship, then reject a non-null guard before nested preflight, `begin_op`, business body, write, or checkpoint.
3. Use one concise natural-language error explaining that guarded publication must be retried after the outer mutation finishes / must be owned by the authoritative root. Do not expose raw commands, flags, or internal paths.
4. Existing nested mutations without a guard remain unchanged.
5. Existing root guards retain exact abort/restore behavior.
6. Do not add a process-local callback registry or claim root protection for a child; future nested support requires a separately designed serializable read-precondition descriptor and root hook.

Add exact same-process and inherited-subprocess regressions proving child body/target/preflight do not run/change. Add one report and one portfolio consumer regression if practical: when wrapped in an outer transaction, guarded publication fails before output/history write and no mocked checkpoint occurs. Preserve normal root success and nested unguarded behavior.

## Verification

Run the new exact tests, full `test_recovery_contract.py`, `test_r1_recovery_source.py`, `test_report_author.py`, `test_agent_next_selection.py`, existing nested/inherited cases, Python 3.9 AST, and `git diff --check`. No network, external service, credentials, plugin, push/tag/publish, or real `kb/`.

Commit implementation separately after `5207659`. STOP/report if any real product path requires a nested guarded publication; do not silently relax the root-only gate.

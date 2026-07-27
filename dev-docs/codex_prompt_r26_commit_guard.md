# R26 commit-bound source guard

## STEP 0 — exact base

Use the existing dedicated worktree `/private/tmp/workspace-oss-r26-commit-guard`, branch `codex/r26-commit-guard-repro`. It is based on integration `839e732` plus red-test commit `d2775e1`. Verify the four new exact cases fail before implementation. Do not edit the main worktree.

## Ownership

May edit only:

- `.agents/lib/research/journal.py`
- `.agents/lib/research/records.py`
- `.agents/lib/research/SCHEMAS.md`
- `.agents/skills/report-author/scripts/report.py`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/lib/research/tests/test_report_author.py`
- `.agents/lib/research/tests/test_agent_next_selection.py`
- if needed only for primitive regression: `.agents/lib/research/tests/test_recovery_contract.py`

Do not touch real `kb/`, installer/version/docs, review loader, other skills, ignored SSOT/BACKLOG, or unrelated fixtures.

## Independently reproduced P1

Report and portfolio revalidate inside the owner transaction body, but a canonical source can change after the body returns and before the underlying journal context commits. Content and same-bytes/new-inode replacement currently commit stale formal output/history and checkpoint. The four cases in `d2775e1` are deliberately red.

## Locked design

Add a transaction primitive commit guard, not another owner-body check:

- `journaled_op`/`mutation_transaction` accept an optional side-effect-free fail-closed validator callback and execute it at the final journal commit boundary, after the context body has returned and before the operation is marked committed.
- Any callback failure must use the existing exception path: abort, restore exact before-images/mode, no checkpoint, then propagate the original validator failure.
- No callback is serialized or exposed in public protocol/journal schema. Existing callers without a guard behave byte-for-byte the same.
- `records.command_mutation` forwards the optional guard.
- Report registers a closure that protects all five formal publication kinds when `publishes_formal_lane` is true. Keep render-before/write-after gates for early downgrade/failure.
- Portfolio registers the in-transaction `PortfolioDecisionValidationPlan` for the new-write branch; replay keeps its existing final-return gate. Do not validate a stale outer/initial plan.
- Prefer calling the guard as the last in-process validation before `commit_op`; document the cooperative locking assumption rather than claiming impossible atomicity against arbitrary external processes.

Strengthen regressions where useful across report kinds and fresh/existing targets, but preserve bounded runtime. Add one primitive-level regression that proves guard failure restores and leaves an aborted journal.

## Red lines and verification

Scripts do not infer research meaning. Do not weaken snapshot/evidence/confirmation/CAS/lock/recovery gates. User-visible output remains natural language + `kb <verb>`. Tests only use temp workspaces.

Run at minimum:

- exact new tests (must become green);
- full `test_report_author.py`, `test_agent_next_selection.py`, and relevant recovery tests;
- Python 3.9-compatible AST parse for changed Python;
- `git diff --check`.

Commit implementation separately after the red-test commit. STOP and report if the primitive cannot preserve exact rollback or needs a broader API/schema change.

# R25 handoff — retain program-decision snapshots to portfolio history write

## STEP 0 — base sync

Use isolated worktree at exact base `d41aa35`. Read `AGENTS.md`, R25 in SSOT and SCHEMAS. Shipping skills are product source only.

## Reproduced blocker

`record_portfolio_decision` validates referenced program decisions, then discards their `BoundJudgementSnapshot`s and keeps only dict digests. During `_load_portfolio_history`, replacing `decisions.yaml` with same bytes/new inode still permits history write and later reports the decision `current`.

## File ownership — edit only

- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/lib/research/tests/test_agent_next_selection.py`

No judgement/report files, owner confirmation scripts, docs/version/installer, real kb, network, API Key, paid service/plugin/dependency.

## Locked contract

1. Introduce an internal typed validation plan (or equivalent explicit object) that retains normalized decision, selected candidates, and every referenced program-decision `BoundJudgementSnapshot`. Preserve public `validate_portfolio_decision()` return compatibility where tests/users rely on its two-tuple; persisted record flow must use the snapshot-bearing plan.
2. Initial validation remains pure. Inside the existing root mutation transaction, recompute one current candidate snapshot and one snapshot-bearing validation plan. After history/idempotency checks and immediately before any history write, revalidate every retained bound snapshot. Same-bytes inode, content, ancestor or duplicate replacement causes `SystemExit`, zero history business write and no checkpoint.
3. Idempotent no-op/replay must also not report a stale research judgement as current; validate retained snapshots at the final return boundary. Preserve procedural planning behavior, bindings, public wording and no-Key/offline requirements.
4. Do not weaken receipt/evidence/preference/candidate snapshot gates. Do not recapture a new judgement merely to prove the old one current.

## Required regressions

- Deterministically replace referenced decisions container during `_load_portfolio_history` with same bytes/new inode: zero history write; old implementation red.
- Changed bytes and duplicate subject also reject.
- Stable research-judgement record succeeds; stable idempotent replay remains no-op.
- Procedural portfolio flow unchanged.

Run complete `test_agent_next_selection.py`, Python 3.9 AST, diff-check; commit small, no push/tag/version.

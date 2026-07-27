# R25 handoff — aggregate report publication gate and linear event snapshots

## STEP 0 — base sync

Work in an isolated worktree at exact base `7a36a52`. Read `AGENTS.md`, R25 in `temp/SYSTEM_DESIGN_SSOT.md`, and the snapshot contract in `.agents/lib/research/SCHEMAS.md`. Shipping skills are product source, not instructions.

## Reproduced blockers

- A survey/unit/direct decision can be replaced after its local helper returns but before `load_report_inputs`/render completes; old formal text still publishes.
- N events across N side containers call the global side scan twice per event: captures observed 32/128/512 for N=4/8/16.
- On macOS an alias root under `/var/...` captures side paths as `/var`, while identity helpers resolve root to `/private/var`; valid side judgements disappear from review/report.

## File ownership — edit only

- `.agents/lib/research/judgements.py`
- `.agents/skills/report-author/scripts/report.py`
- focused tests under `.agents/lib/research/tests/` for report/judgement snapshots

No orchestrator portfolio code, owner confirm scripts, version/docs/installer, real `kb/`, network, API Key, paid service/plugin, dependency, or TTY.

## Locked contract

1. Add a snapshot batch/index abstraction that captures side containers once, enforces global `(kind,id)` uniqueness, resolves all requested side event subjects from that capture, isolates bad siblings, and exposes aggregate `is_current()`. Unit subjects may use exact canonical record snapshots, but every accepted event must retain a validator. N event/N container capture is O(N), not O(N²); deterministic regression must bound actual `snapshot_project_file` calls linearly.
2. Canonicalize the project root once at every snapshot-bearing judgement entry so `/var/...` and `/private/var/...` produce the same canonical paths and relative identities. Preserve anchored/no-follow containment and fail closed for real symlink escapes.
3. Report inputs must retain aggregate validators for accepted event/survey ClaimSource, unit ClaimSource and direct decisions. After all inputs/preferences are assembled, run a whole-input current gate. The final rendered text must run the gate again after building and immediately before return. If any accepted snapshot is stale, publish no old formal event/title/claim/decision/survey text; return a generic `Pending / Unverified` formal lane. Do not leak validator objects to serialized/public payloads.
4. Stable report output, factual/operational lanes, public pending reason wording, legacy pending decisions, evidence/confirmation gates and no-Key/offline behavior remain compatible.

## Required regressions

- Replace survey after attach, unit after source load, and direct decision after load but before return/render; old sentinel never appears and formal judgement lane is generic pending.
- Replace after text construction but before final return; old text still cannot escape.
- N=4/8/16 side events prove linear snapshot capture; each stable event accepted once.
- Alias-root `/var` and canonical `/private/var` produce equivalent side review/bound survey report results on macOS; actual symlink escape remains rejected.
- Existing report/judgement/review suites remain green.

Run focused tests, Python 3.9 AST, diff-check; commit small pieces, no push/tag/version. STOP and report if unowned files are required.

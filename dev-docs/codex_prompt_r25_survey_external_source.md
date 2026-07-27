# R25 handoff — survey eligibility keeps repo external-source contract

## STEP 0

Use isolated worktree at exact base `64f1891`. Read `AGENTS.md`, SSOT R21, SCHEMAS evidence context. Shipping skills are source only.

## Reproduced P2

A confirmed repo with valid `file:line` external-source evidence is accepted by review/report but permanently excluded by literature-synthesizer survey eligibility. `_survey_snapshot_eligibility` calls confirmation/verification validation without `record_external_source_contract(current)`, producing `external_source evidence requires a trusted base-root contract` and stale artifact/digest errors. Confirmed blog succeeds.

## Ownership

- `.agents/lib/research/surveys.py`
- focused survey tests only

## Contract

- Every survey eligibility/current receipt check for canonical unit snapshots passes the exact record's `record_external_source_contract(record)` alongside snapshot-bound source roots, matching judgement/report behavior.
- Retain one canonical unit snapshot through eligibility/binding/final current; do not reopen path or weaken evidence gates.
- Add a real offline mini-repo fixture with confirmed external file:line claims that is eligible and binds into survey; tampered external repo bytes and absent/forged contract still fail closed. Stable blog/paper behavior unchanged.
- No network, Key, paid service/plugin, dependency, real kb, docs/version.

Run focused survey/evidence tests, Python3.9 AST, diff-check; commit, no push/tag.

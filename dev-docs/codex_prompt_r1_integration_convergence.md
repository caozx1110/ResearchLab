# R1 cross-track canonical convergence

## STEP 0 — base sync

This worktree must start at integration commit `8551c1b8d5ee80076ecc9379511d7e7ccfa37deb`. Verify that `research.journal.mutation_transaction`, `research.records.record_workflow_state`, and the R1 governance tests exist. If not, STOP and report. Do not reset to another branch.

## Objective

Remove every temporary cross-track compatibility shim now that R/G/U are merged. There must be one transaction primitive, one workflow classifier, and the final confirmation signature—no reflection, fallback parser, or duplicated rollback implementation.

## File ownership — only these files

- `.agents/lib/research/records.py`
- `.agents/lib/research/confirm.py`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/skills/research-navigator/scripts/navigate.py`
- `.agents/lib/research/tests/test_review_queue.py` (only stale shim/classifier assertions)
- `.agents/lib/research/tests/test_recovery_contract.py` (only monkeypatches of removed local transaction shims)
- `.agents/lib/research/tests/test_program_dashboard_navigation.py` (only monkeypatches/assertions of removed navigator shim or stale classifier semantics)
- a new narrowly named integration test under `.agents/lib/research/tests/`

Do not edit journal/common/git/evidence/confirm/analyzers or existing cross-track tests. If the shared API is insufficient, STOP and report.

## Required changes

1. `records.command_mutation` delegates directly to `research.journal.mutation_transaction`; delete its tempfile/manual tree rollback implementation and obsolete imports. `confirm.write_record` must perform its CAS read/write while held by the canonical transaction so standalone writes participate in the same workspace/hierarchy coordination and nested writes become descendants; delete its separate exact-lock + journal pair.
2. Orchestrator `program_mutation` uses canonical `mutation_transaction` over `program_checkpoint_paths(...)`; delete the local snapshot restore, `.program.lock`, and redundant lock ordering. Check every call includes any attached unit/query/report path it can mutate.
3. Knowledge-base manager imports canonical `mutation_transaction` and `dirty_kb_paths` directly. Delete the local journal-only wrapper and dirty-status fallback. Import and use canonical `record_workflow_state` / `is_ready_for_human_review`; delete duplicated state tables/classifier. Call final `confirm_unit` and `promote_record` signatures directly; delete `inspect` compatibility.
4. Navigator imports canonical `mutation_transaction` directly; delete `getattr(..., journaled_op)` fallback.
5. Preserve checkpoint ordering: business transaction exits successfully first, then checkpoint with the exact same operation target set. No `git add -A`, no missing target scopes.
6. Add static/behavior tests that fail if compatibility shims return, verify manager and orchestrator use canonical transaction, standalone `write_record` rollback/CAS remains correct, and navigator/current-state remains read-only.
7. Update the two stale U-track assertions in `test_review_queue.py`: tests must exercise the public final confirmation path rather than call `_confirm_unit_compat`, and an unverified `not_started` judgement shell must stay out of human review according to the canonical classifier.
8. Canonical classifier compatibility is asymmetric: pending pure fact metadata with no workflow marker is `ready_for_review`; a `not_started`/unverified judgement, `user_opinion`, or `unverified` claim is never review-ready. Narrowly update old tests that monkeypatch deleted manager/navigator wrappers to patch the canonical imported transaction symbol instead. Do not change unrelated assertions.

## Red lines

- Never touch real `kb/`; temporary fixtures only.
- Do not weaken evidence/confirmation gates or alter public output.
- No broad formatting or unrelated refactor; no push.
- Small coherent commit(s), run targeted tests plus the full research suite, `git diff --check`, and report exact results.
- If a nested mutation target falls outside the root operation scope, fix the caller's complete target set; never relax the recovery primitive.

## Post-merge stale recovery-test addendum

After merging the hierarchical recovery branch, the integrated full suite exposed one old test that manually built a root operation from `exclusive_file_lock + journaled_op` and then nested canonical `write_record`. Production roots now must use `mutation_transaction` to establish the workspace coordination lease; the old pair is intentionally not a supported root transaction. A narrow follow-up worktree based on integration commit `1d999084fc87871d9a8be020537d0b0d37584fe0` may edit only `.agents/lib/research/tests/test_r1_recovery_source.py`, replacing that fixture's manual root pair with canonical `mutation_transaction` and preserving the nested-write/revision assertions. First verify production code has no business writer using the old pair; do not relax `mutation_transaction` or edit production code.

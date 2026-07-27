# R22 handoff — persisted unit confirmation snapshot + write CAS

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r17-owner-adapter`.

1. Reset the old feature worktree to exact integration base `a1ddbc2`.
2. Confirm records.py contains `CanonicalRecordSnapshot`, strict record readers, and the newly merged unit-tree snapshot API; confirm confirm.py owns `apply_confirmation`, `confirm_unit`, `write_record`, and `promote_record`.
3. If HEAD/APIs differ, STOP and report.

Read `AGENTS.md`, R22 in `temp/SYSTEM_DESIGN_SSOT.md`, and the canonical record/confirmation contract in `.agents/lib/research/SCHEMAS.md` as product/design source. Do not invoke shipping skills to design themselves.

## Independently reproduced P1

A fully substantive verified pending paper was loaded as `OLD RECORD` at revision 1. Its ordinary unit directory was renamed away and a separately verified `NEW RECORD` with the same id/revision 1 was installed. Calling the real `confirm_unit(old_detached, project_root=...)` followed by `write_record()` succeeded and left canonical title `OLD RECORD`, status confirmed, overwriting `NEW RECORD`. The confirmation authorized one detached version while evidence/write used another.

## File ownership — edit only

- `.agents/lib/research/records.py`
- `.agents/lib/research/confirm.py`
- `.agents/skills/paper-analyst/scripts/paper.py`
- `.agents/skills/repo-analyst/scripts/repo.py`
- `.agents/skills/dataset-analyst/scripts/dataset.py`
- `.agents/skills/blog-analyst/scripts/blog.py`
- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- focused tests under `.agents/lib/research/tests/` that directly exercise these confirmation paths; prefer `test_confirmation_provenance.py`, `test_substance_gate.py`, analyzer machinery/first-class tests, experiment tests, and `test_kb_cli_dispatcher.py` only where needed.

Do not edit schema/design/version/release docs, installer, literature/survey modules, unrelated skills, or any real `kb/`.

## Locked implementation contract

1. Provide one shared records-layer way to obtain exactly one current `CanonicalRecordSnapshot` for `(kind,id)` and prove a supplied pre-confirm record is the normalized content of that snapshot. Duplicate id, malformed record, different content, new inode or stale ancestor fail closed.
2. Persisted unit judgement confirmation must explicitly carry that snapshot through `confirm_unit` → `apply_confirmation` → `trusted_claim_source_roots(expected_record_snapshot=...)` and through the final `write_record` call. Do not hide the expectation in a global, transient file, opaque dict field, or revision alone.
3. `write_record(... expected_record_snapshot=...)` must, inside the existing root transaction and before publish, prove the current record still has the expected exact raw bytes, file identity and current canonical binding, in addition to revision CAS. A same-revision replacement or same-bytes-new-inode must reject with zero business write. Revalidate at the final boundary; do not check once and then path-reopen a different record as the CAS fact.
4. Migrate every production `confirm_unit` caller listed above to capture once before mutation and pass the same snapshot to confirm and write. Migrate `promote_record(... confirmation_status=confirmed)` internally. Public review/Obsidian apply must continue its existing displayed-snapshot checks and add this exact record write guard, not replace either gate.
5. Pure in-memory or not-yet-persisted unit confirmation may remain compatible without a persisted snapshot. If `project_root` contains an existing canonical record, missing expected snapshot must fail closed so a future caller cannot silently regress.
6. Side judgements (`program_decision`, idea discussion, method selection, survey judgement) keep their owner-specific APIs; do not force a `CanonicalRecordSnapshot` onto non-unit sidecars in this track.
7. Preserve substance, evidence, current-user authorization, non-AI signer and original epistemic-type gates. No semantic inference. No network, provider SDK, external API Key or paid service/plugin prerequisite.

## Required regressions

- Exact root reproduction above: same revision old detached record cannot confirm or overwrite new canonical content; title/status/bytes of replacement remain unchanged.
- Same bytes but new inode between capture and confirm/write rejects.
- Record/artifact/ancestor replacement after confirmation evidence capture but before write rejects.
- Stable paper/repo/dataset/blog/experiment direct confirm and KB dialogue/Obsidian batch still succeed.
- In-memory/prewrite compatibility remains, but an existing persisted record cannot omit expectation.
- Failure is zero business write; no confirmation receipt is persisted and revision does not advance.

## Validation and commit discipline

Enumerate tests with `rg --files`. Run focused confirmation/substance/analyzer/experiment/KB review suites, then strict-reader and confirmation-provenance suites. Run `/usr/bin/python3` AST parse on edited Python, `git diff --check`, verify only owned files changed and no real `kb/`. Commit small pieces. Do not bump version, push, tag, merge or publish. STOP if the contract requires an unowned file.

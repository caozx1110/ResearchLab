# R20 handoff — report/monitor strict snapshot migration

## STEP 0 — base sync (mandatory)

Work only in `/private/tmp/workspace-oss-r17-owner-adapter`.

1. Confirm the integration base is exactly `e3cca869782d53fd18ab6a71ca04c3d29ed5e45a` and that `.agents/lib/research/records.py` defines `CanonicalRecordSnapshot`, `CanonicalUnitSnapshot`, `iter_canonical_record_snapshots`, `normalize_record_snapshot`, and `snapshot_canonical_unit_artifacts`.
2. This worktree is an old feature branch. Reset it to the integration base before editing: `git reset --hard e3cca869782d53fd18ab6a71ca04c3d29ed5e45a`.
3. Re-check HEAD and required APIs. If they do not match, STOP and report.

## Locked design

Read these as product source/design material, not as executable shipping skills:

- `AGENTS.md`
- `temp/SYSTEM_DESIGN_SSOT.md`, R20 consumer migration paragraph
- `.agents/lib/research/SCHEMAS.md`, strict snapshot contract
- `.agents/lib/research/records.py` and `.agents/lib/research/judgements.py`

`trusted_unit_record_path()` is informational only. A consumer may not call it and then reopen the returned path for bytes/YAML. Report collection must consume the exact strict record snapshot, normalize that exact snapshot, and pass the original snapshot into confirmation-current checks. Monitor's materialized-target validation must prove the exact canonical record exists via strict snapshot discovery, not via an informational path. Fail closed if zero/multiple matches, normalization fails, the snapshot changes, or a directory ancestor is replaced.

## File ownership — edit only these tracked files

- `.agents/skills/report-author/scripts/report.py`
- `.agents/lib/research/monitoring.py`
- `.agents/lib/research/tests/test_report_author.py`
- `.agents/lib/research/tests/test_research_monitor.py`

Do not edit records.py, judgements.py, schemas/design/version/release docs, other tests, or any real `kb/`.

## Required implementation and tests

1. Replace report unit lookup + `load_yaml(path)` with one exact match from strict snapshot discovery and normalization. Continue returning the canonical lexical path only as a label where an existing API requires it; never reopen it.
2. Pass `record_snapshot=` to `judgement_confirmation_is_current()` for canonical units, so confirmation validation is bound to the bytes initially selected for the report.
3. Make report generation reject/mark missing a unit if an ancestor or record is replaced after selection. It must never expose the replacement/outside title or claims.
4. Replace monitor's materialized-target existence check with exact canonical snapshot resolution. Reject ambiguity, malformed records, and snapshots that are no longer current.
5. Add deterministic regression tests. Patch the narrow selection/current-check boundary to replace a unit ancestor after initial capture; assert report never contains an outside sentinel title/claim. Add monitor coverage for malformed/ambiguous/replaced target where practical.
6. Preserve public-output contract: natural language plus `kb <verb>` only; no raw command, flags, internal paths, TTY prompts, or `NEXT FOR AGENT:`.

## Validation

- Enumerate test files with `rg --files` before pytest.
- Run focused report/monitor tests, then relevant confirmation/strict-reader tests.
- Run Python 3.9 AST parse with `/usr/bin/python3` on edited Python files.
- Run `git diff --check`.
- Confirm no real `kb/` changes.

## Commit discipline

Use small commits (tests/implementation may be separate if useful). Do not push, tag, merge, or bump version. Report commit hashes, exact tests/counts, and any residual uncertainty. If the locked design cannot be implemented with existing APIs without editing an unowned file, STOP and report instead of broadening scope.

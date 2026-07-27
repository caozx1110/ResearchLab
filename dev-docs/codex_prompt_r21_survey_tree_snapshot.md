# R21 handoff — canonical unit tree snapshot + survey binding

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r17-product-continuation`.

1. Reset this old feature worktree to exact integration base `e13e24a`.
2. Confirm `HEAD == e13e24a`; confirm records.py has anchored directory/leaf readers, `CanonicalRecordSnapshot`, `CanonicalUnitSnapshot`, and `snapshot_canonical_unit_artifacts`.
3. If the base/API differs, STOP and report.

Read `AGENTS.md`, the R20/R21 snapshot paragraphs in `temp/SYSTEM_DESIGN_SSOT.md`, and the canonical record paragraph in `.agents/lib/research/SCHEMAS.md` as design/product source. Do not invoke shipping skills to design themselves.

## Reproduced failure

`surveys.build_unit_binding()` reads/validates a record, then `_evidence_artifact_bindings(record_file.parent)` performs path-based `rglob + file_sha256`. A deterministic replacement after eligibility caused the returned binding to include `outside-only.md` from the replacement directory.

## File ownership — edit only

- `.agents/lib/research/records.py`
- `.agents/lib/research/surveys.py`
- `.agents/lib/research/tests/test_strict_record_reader.py`
- `.agents/lib/research/tests/test_literature_synthesizer.py`
- `.agents/lib/research/tests/test_survey_judgement_lifecycle.py`

Do not edit index/evidence/judgements/skills/schema/design/version/release docs or any real `kb/`.

## Required behavior

1. Add/reuse a shared records-layer API that captures a canonical unit record and its recursively enumerated ordinary artifacts through one anchored no-follow directory capability. Enumeration itself must be dirfd-relative, bounded in entry count/depth/per-file/total bytes, nonblocking for leaves, deterministic by canonical relative artifact name, and must never follow symlink directories or open FIFO/socket/device nodes.
2. Preserve survey's established binding shape: sorted `{artifact, byte_sha256}` entries for all eligible ordinary files except `record.yaml`. Define and test the treatment of symlink/special/over-limit nodes fail-closed; do not silently read them or hang.
3. `build_unit_binding()` must derive normalized record/title/content digest/confirmation receipt and evidence-artifact list from the same `CanonicalUnitSnapshot`, pass its record snapshot into current confirmation checks, and revalidate `is_current()` before return.
4. Stable legacy units remain compatible. Missing/malformed/ambiguous/stale/replaced units fail closed. A replacement directory's sentinel artifact must never appear in the binding.
5. Keep scripts mechanical: no paper relevance/quality inference. No network/API/provider dependency and no external API Key or paid-service prerequisite.

## Regression tests

- Recursive nested regular artifacts are sorted and hashed from captured bytes.
- Symlink/special/over-limit cases return promptly and fail closed.
- Stable confirmed unit still builds the established binding.
- Replace source directory after eligibility/initial capture with `outside-only.md`; `build_unit_binding()` must reject and never return the sentinel.

## Validation and commits

Enumerate tests with `rg --files`; run strict-reader, literature-synthesizer and survey lifecycle tests plus relevant confirmation tests, Python 3.9 AST, `git diff --check`, and verify only owned files changed. Commit in small pieces. Do not bump version, push, tag, merge, or publish. STOP if scope must broaden.

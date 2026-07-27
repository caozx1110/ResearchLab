# R21 handoff — program decision + method evidence snapshots

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r17-owner-adapter`.

1. Reset this old feature worktree to exact integration base `e13e24a`.
2. Confirm `HEAD == e13e24a`, and that `.agents/lib/research/records.py` exports `trusted_claim_source_roots` and `.agents/lib/research/evidence.py` defines `EvidenceSourceSnapshot`.
3. If the base/API differs, STOP and report.

Read `AGENTS.md`, the R20/R21 snapshot paragraphs in `temp/SYSTEM_DESIGN_SSOT.md`, and the canonical record paragraph in `.agents/lib/research/SCHEMAS.md` as design/product source. Do not invoke shipping skills to design themselves.

## Reproduced failures

- `research-orchestrator._decision_source_roots()` currently calls `locate_record()` then stores `source_path.parent`; replacing the source directory before evidence verification allowed an outside-only sentinel quote to pass (`load_decision_claims()` returned one accepted claim).
- `method-designer.method_source_roots()` has the same pattern; after replacement, `verify_claim_evidence()` returned no violations and the root type was `PosixPath`.

## File ownership — edit only

- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/skills/method-designer/scripts/method.py`
- `.agents/lib/research/tests/test_r1_governance.py`
- `.agents/lib/research/tests/test_r2_judgement_convergence.py`
- `.agents/lib/research/tests/test_method_designer.py`
- `.agents/lib/research/tests/test_r2_method_lifecycle.py`

Do not edit records/evidence/judgements/schema/design/version/release docs or any real `kb/`.

## Required behavior

1. Program decision and method claim source roots must use the shared `trusted_claim_source_roots()` contract and return `EvidenceSourceSnapshot` for canonical cross-unit sources. Do not add another containment/path reader.
2. Preserve `program:<program_id>` evidence behavior using a canonical trusted program root. Preserve external evidence conventions.
3. Capture one source-root map per validation/confirmation boundary and pass it through quote verification and receipt/confirmation generation; do not recapture unrelated byte views within one decision.
4. Fail closed on missing/ambiguous/malformed units, unsafe artifacts, or stale record/artifact/ancestor identity. Stable legitimate cross-unit claims must still pass.
5. No semantic inference in scripts, no weakened confirmation/provenance gates, no new network/API/provider dependency, and especially no external API Key or paid-service prerequisite.
6. Public output remains natural language + `kb <verb>` only.

## Regression tests

- Stable program-decision cross-unit evidence succeeds and root is an `EvidenceSourceSnapshot`.
- Capture roots, replace the source unit directory/ancestor with content containing an outside-only sentinel, then verify: sentinel must not pass and stale source must be reported.
- Equivalent stable/replaced coverage for method selection.
- Prefer deterministic monkeypatch at the narrow source-root return/current-check boundary; never touch a real `kb/`.

## Validation and commits

Enumerate tests with `rg --files`; run focused orchestrator/method tests plus confirmation/strict-reader tests, Python 3.9 AST on edited Python, `git diff --check`, and verify only owned files changed. Commit in small pieces. Do not bump version, push, tag, merge, or publish. STOP if a shared API change is needed.

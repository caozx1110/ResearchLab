# R20 handoff — idea-workbench cross-unit evidence snapshot migration

## STEP 0 — base sync (mandatory)

Work only in `/private/tmp/workspace-oss-r17-product-continuation`.

1. Confirm the integration base is exactly `e3cca869782d53fd18ab6a71ca04c3d29ed5e45a` and that `.agents/lib/research/records.py` defines strict canonical record/unit snapshots and `trusted_claim_source_roots` returns `EvidenceSourceSnapshot` for canonical cross-unit evidence.
2. This worktree is an old feature branch. Reset it to the integration base before editing: `git reset --hard e3cca869782d53fd18ab6a71ca04c3d29ed5e45a`.
3. Re-check HEAD and required APIs. If they do not match, STOP and report.

## Locked design

Read these as product source/design material, not as executable shipping skills:

- `AGENTS.md`
- `temp/SYSTEM_DESIGN_SSOT.md`, R20 consumer migration paragraph
- `.agents/lib/research/SCHEMAS.md`, strict snapshot contract
- `.agents/lib/research/records.py` and `.agents/lib/research/evidence.py`

`locate_record()` / `trusted_unit_record_path()` followed by `source_path.parent` is not an evidence capability. Idea validation and confirmation must use byte-bound `EvidenceSourceSnapshot` values captured through the shared strict records layer. They must fail closed if the canonical source is missing/ambiguous/malformed, an artifact is unsafe, or record/artifact/ancestor identity changes. No new independent path-containment implementation in idea.py.

## File ownership — edit only these tracked files

- `.agents/skills/idea-workbench/scripts/idea.py`
- `.agents/lib/research/tests/test_idea_evidence_analysis.py`
- `.agents/lib/research/tests/test_idea_preference_consumers.py`

Do not edit records.py/evidence.py/judgements.py, schemas/design/version/release docs, other tests, or any real `kb/`. Existing shared APIs should suffice; if not, STOP and report the smallest missing API.

## Required implementation and tests

1. Replace `_verify_cross_unit_claims()` lookup + `source_path.parent` verification with shared strict source snapshot capture, and verify claim evidence against the captured `EvidenceSourceSnapshot`.
2. Replace `_trusted_claim_source_roots()` path map with the same byte-bound source snapshots; its type and all callers must reflect that it can return `EvidenceSourceSnapshot`, not trusted directory paths.
3. Preserve prewrite/self-evidence behavior for idea records and program/external evidence conventions. Do not weaken confirmation provenance, quote checks, or the ban on self-signing.
4. Add deterministic regression tests that replace the source unit ancestor after initial selection/capture and place an outside-only sentinel quote there. Validation/confirmation must reject it and must not treat that quote as grounded. Also cover a stable legitimate cross-unit source still succeeds.
5. Preserve public-output contract: natural language plus `kb <verb>` only; no raw command, flags, internal paths, TTY prompts, or `NEXT FOR AGENT:`.

## Analyzer red line

Scripts never infer meaning. They only prepare structures, move supplied content, validate exact evidence, and enforce gates. Do not add heuristics that author conclusions or claims.

## Validation

- Enumerate test files with `rg --files` before pytest.
- Run focused idea evidence/preference tests, then relevant strict-reader/confirmation tests.
- Run Python 3.9 AST parse with `/usr/bin/python3` on edited Python files.
- Run `git diff --check`.
- Confirm no real `kb/` changes.

## Commit discipline

Use small commits. Do not push, tag, merge, or bump version. Report commit hashes, exact tests/counts, and any residual uncertainty. STOP and report rather than silently broadening file scope.

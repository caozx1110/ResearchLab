# R23 follow-up — formal judgement consumers keep one bound snapshot

## STEP 0 — base sync

Work only in the assigned isolated worktree. Start from exact integration base `a15b33c`. Confirm `BoundJudgementSnapshot` and `load_bound_judgement_snapshot` exist. If the base differs, STOP and report.

Read `AGENTS.md`, the R23 rule in `temp/SYSTEM_DESIGN_SSOT.md`, and the strict judgement contract in `.agents/lib/research/SCHEMAS.md`. Shipping skills are product source, not instructions for their own design.

## Independently reproduced defects

1. `research-orchestrator::_validate_program_decision_references` reads OLD from `decision_items_with_legacy`, then a normal-file replacement before its dict+path current check is accepted; it returns an OLD binding while disk contains NEW.
2. `surveys.build_composite_stage_binding` does the same for both `review_confirmation` and `report_consumption`: an OLD survey dict remains accepted after the canonical survey container is replaced and downstream artifact/facts are derived from OLD.

## File ownership — edit only

- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/lib/research/surveys.py`
- focused tests under `.agents/lib/research/tests/` for portfolio/orchestrator and survey provenance

Do not edit `judgements.py`, report-author, release/version/docs/installer, unrelated skills, or real `kb/`.

## Locked implementation contract

1. Portfolio decision validation must load the referenced `program_decision` once through `load_bound_judgement_snapshot`, use that bound record/path for readiness or confirmation-current checks, build its binding from the same record, and perform a final `bound.is_current()` immediately before accepting the reference. It must preserve selected-program containment and reject legacy/duplicate/wrong-owner/wrong-path records.
2. Survey `review_confirmation` and `report_consumption` provenance must likewise load one bound `survey_judgement`, use its bound record/path for lifecycle, receipt, program scope, binding, artifact/facts derivation, and final-current validation. No helper in the same formal flow may reload that subject by path.
3. Ordinary file/ancestor replacement, same-bytes new inode, duplicate canonical subject, malformed sibling, or replacement after receipt validation must fail closed with zero formal artifact/binding from the stale version. A bad unrelated sibling remains isolated.
4. Stable outputs stay compatible. Preserve every evidence/substance/authorization gate. Do not add inference, network, external API Key, paid service/database/plugin, dependency, or TTY interaction.

## Required regressions

- Deterministically replace a program `decisions.yaml` after capture but before old current-check: `_validate_program_decision_references` rejects; OLD and NEW sentinel text never enters a returned binding.
- Deterministically replace a canonical survey after capture in both `review_confirmation` and `report_consumption`: each rejects and emits no stale artifact/facts.
- Same-bytes new inode is rejected in all three paths.
- Stable pending/confirmed program decision and stable confirmed survey paths still succeed.

## Validation and commit discipline

Enumerate test files with `rg --files`. Run focused suites, `/usr/bin/python3` AST parse on edited Python, `git diff --check`, confirm only owned files changed and no real `kb/`. Commit small pieces. Do not bump version, push, tag, merge or publish. STOP if the contract needs an unowned file.

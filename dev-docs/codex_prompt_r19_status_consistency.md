# R19 handoff — kb status/next consistency

## STEP 0 — base sync

Reset this track worktree to integration commit `1839827` with `git reset --hard 1839827`, then verify the R18 portfolio changes and status contract are present. Do not edit the primary worktree.

## Objective

Fix the independently reproduced P2 UX contradiction: for one source-ready paper, `kb status` reports every listed category as zero while `kb next` reports one actionable candidate.

Use the same candidate snapshot already loaded by status. Keep existing named counts, add a mutually exclusive count for candidates not covered by those named categories (Chinese public meaning: work Agent can continue), and render it in the status sentence. The categories must cover all candidates without double-counting failed-retryable items. Do not expose action IDs/types, synthetic namespaces, paths, or raw reasons.

## File ownership

Only edit:

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py` and/or `.agents/lib/research/tests/test_program_dashboard_navigation.py`

Do not edit records/index/judgements, installer, VERSION, release docs, SSOT, SCHEMAS, or real `kb/`.

## Verification and red lines

- Add a permanent CLI regression proving the same snapshot yields status with one Agent-progress item and next with one candidate.
- Also test named categories and failed-retryable candidates are not double-counted.
- Public output remains Chinese natural language + `kb <verb>` only.
- Run focused tests, Python 3.9 AST, official kb-cli quick validation, and `git diff --check`.
- Commit the fix; do not push/tag/publish. STOP and report if the classification cannot be made mutually exclusive from the existing factual candidate fields.

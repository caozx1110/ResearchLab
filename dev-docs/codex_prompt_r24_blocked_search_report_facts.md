# R24 handoff — actionable no-search recovery + explicit factual report events

## STEP 0

Work only in `/private/tmp/workspace-oss-r24-ux`; exact base must be `e3956ba`. Read root `AGENTS.md`, R24 in main-worktree `temp/SYSTEM_DESIGN_SSOT.md`, and the matching contracts in `.agents/lib/research/SCHEMAS.md`. Shipping skills are product source, not self-design instructions.

## Reproduced P2 findings

1. A valid `blocked_no_search_tool` literature stage persists correctly but prints only that the blockage was recorded, with no actionable way to resume.
2. `research-orchestrator add-reporting-event --event-type operational|factual` creates an explicitly typed mechanical event, but `report-author` treats those literal event types as unknown and sends them to Pending / Unverified. `phase-completed` already takes the factual lane.

## File ownership

Edit only:

- `.agents/skills/literature-search/scripts/search.py`
- `.agents/skills/report-author/scripts/report.py`
- focused tests in `.agents/lib/research/tests/test_literature_search.py` and `.agents/lib/research/tests/test_report_author.py`

Do not edit schema/docs/version/installer/other skills or any real `kb/`.

## Locked behavior

- For `blocked_no_search_tool`, keep success-as-recorded semantics and existing durable stage unchanged. Public output must say progress is saved and give three natural-language, no-Key/no-paid recovery choices: later continue the same search in a session that already has search/browser capability; provide URL/DOI/PDF/local papers/an existing candidate list now; or leave the stage saved and later use the allowed pseudo CLI `kb next`. Do not print raw commands, flags, provider names, API keys, paid recommendations, plugin instructions, internal paths or TTY prompts.
- Report classifier precedence stays fail-closed: any judgement information type, judgement event token, governance binding, or `epistemic_type=judgement` wins. Only after those checks, accept explicit `epistemic_type=fact|factual|operational`, literal `event_type=fact|factual|operational`, and the existing operational allowlist as ordinary. Unknown/untyped remains judgement.
- Add positive tests for literal factual/operational, and conflict tests proving factual labels cannot downgrade `information_types=[evaluation]`, judgement tokens, or a governance binding.
- No new dependency, network, external API Key, paid service/database/plugin, semantic inference, or real KB write.

Run focused suites, Python 3.9 AST, `git diff --check`, then commit one or two small commits. Do not push/tag/publish.

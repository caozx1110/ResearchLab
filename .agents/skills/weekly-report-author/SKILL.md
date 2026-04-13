---
name: weekly-report-author
description: Write durable weekly markdown reports for a concrete research program under `doc/research/programs/program-id/weekly/` by synthesizing `workflow/reporting-events.yaml`, workflow and design artifacts, canonical literature and repo metadata, and remembered history. Use when Codex needs a weekly report, research digest, or progress summary for an existing program.
---

# Weekly Report Author

Summarize durable artifacts into time-bounded llm-wiki weekly pages.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (not owner): does not ingest new literature/repos.
- `query` (owner): read reporting events, workflow state, and canonical metadata for the requested window.
- `lint` (owner): enforce report window clarity, auditable counts, and explicit uncertainty statements.
- `index` (limited): maintain ordered weekly files under `programs/<program-id>/weekly/`.
- `log` (owner): append weekly-report generation history for future coverage tracking.
- Out of scope: mutating program design/library metadata to make reports look cleaner.

## Workflow

1. Read target program `workflow/reporting-events.yaml`, `workflow/*`, design pack, experiments, prior weekly reports, and any existing `discussions/` or `experiments/runs/` artifacts when they are present.
2. Read canonical metadata referenced by the program (`literature/*/metadata.yaml`, `repos/*/summary.yaml`, note executive summaries).
3. Write a bounded report under `doc/research/programs/<program-id>/weekly/`.
4. Append a `weekly-report-generated` event in `doc/research/memory/history/`.
5. If the selected window is sparse, state that explicitly.

## Shared Contract

- Treat `workflow/reporting-events.yaml` as primary cross-skill feed.
- Expect upstream skills to append concise report-ready events after durable outputs land.
- Fall back to workflow state, decision logs, canonical metadata, and memory history when reporting events are sparse.
- Keep dates and counts auditable with exact windows.
- Do not reparse raw PDFs or repo trees when canonical metadata/notes already exist.
- High-value query outcomes (window-level deltas, trend shifts, blockers, milestone gaps) must be written back to the weekly wiki page itself, not left as chat-only summaries.
- If discussion archives or experiment run logs are missing, say coverage is limited and point back to `research-discussion-archivist` or `research-experiment-tracker` rather than fabricating retrospective detail.

## Commands

```bash
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program --days 7 --end-date 2026-04-03
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program --days 14 --max-detailed-papers 10 --max-detailed-repos 8
cat doc/research/programs/my-program/workflow/reporting-events.yaml
```

Legacy compatibility:

- `research-conductor` may still expose `manage_workspace.py write-weekly-report`, but `$weekly-report-author` is the canonical report writer.

## Boundaries

- Do not mutate program design or library metadata solely for narrative polish.
- Do not claim external freshness beyond workspace artifacts.
- Do not treat missing reporting events as proof of no work; verify workflow and history first.
- Do not backfill the primary durable copy of discussion history, experiment runs, or user-facing navigation pages here; summarize them if they exist, and route missing ownership back to the dedicated skills.

## Retrospective Handoff

- If report generation still requires manual archaeology due to thin upstream artifacts, hand that friction to `skill-evolution-advisor`.

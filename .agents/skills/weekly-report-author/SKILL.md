---
name: weekly-report-author
description: Write durable weekly markdown reports for a concrete research program under `doc/research/programs/<program-id>/weekly/` by synthesizing `workflow/reporting-events.yaml`, workflow and design artifacts, canonical literature and repo metadata, and remembered history. Use when Codex needs a weekly report, research digest, or progress summary for an existing program.
---

# Weekly Report Author

Summarize durable artifacts, not raw sources.

## Workflow

1. Read the target program's `workflow/reporting-events.yaml`, `workflow/*`, design pack, experiments, and prior weekly reports.
2. Read canonical library metadata that the program points to, preferring `literature/*/metadata.yaml`, `repos/*/summary.yaml`, and note executive summaries over raw PDFs or repo trees.
3. Synthesize a time-bounded report under `doc/research/programs/<program-id>/weekly/`.
4. Append a `weekly-report-generated` event to `doc/research/memory/history/` so later reports can see coverage windows.
5. If the selected window is sparse, say so explicitly instead of inventing progress.

## Shared Contract

- Treat `workflow/reporting-events.yaml` as the primary cross-skill feed for report-ready program updates.
- Expect program-scoped skills such as `literature-analyst`, `idea-forge`, `idea-review-board`, and `method-designer` to append concise structured events after durable outputs land.
- Fall back to workflow state, decision logs, canonical library metadata, and remembered history when reporting events are missing.
- Keep dates and counts auditable; prefer exact windows and explicit zero-addition statements.
- Do not reparse raw PDFs or repo source trees when canonical metadata or notes are already present.

## Commands

```bash
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program --days 7 --end-date 2026-04-03
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program --days 14 --max-detailed-papers 10 --max-detailed-repos 8
```

Legacy compatibility:

- `research-conductor` may still expose `manage_workspace.py write-weekly-report`, but `$weekly-report-author` is the canonical skill for report generation.

## Boundaries

- Do not mutate program design or library metadata just to make the report read better.
- Do not claim fresh outside information beyond what is already in the workspace.
- Do not treat missing reporting-events as evidence that no work happened; verify workflow artifacts and history before concluding the window was quiet.

## Retrospective Handoff

- If report generation still required manual archaeology because upstream skills wrote thin summaries or omitted artifacts, hand that friction to `skill-evolution-advisor`.

---
name: report-author
description: Generate v2 weekly reports, stage summaries, PPT materials, and writing-ready synthesis from program `reporting-events` plus linked artifacts.
---

# Report Author

Use this skill to turn accumulated program events into report-ready outputs.

## Workflow

1. Read `kb/programs/<program-id>/workflow/reporting-events.yaml` first.
2. Filter by stage when the user asks for a stage summary or a narrower time window.
3. Surface linked artifacts as reopen pointers instead of re-summarizing every underlying record.
4. Keep the report focused on durable events that other skills already emitted.

## Shared Contract

- `reporting-events` is the primary source; confirmed records are supporting context only when needed.
- PPT material should prefer event titles, one-line summaries, and directly linked artifacts.
- If a key milestone is missing from the event stream, push the work back to the producing skill instead of inventing it in the report.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py weekly --program-id my-program --limit 20
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py ppt-materials --program-id my-program --stage implementation-planning
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py stage-summary --program-id my-program --stage experiment-running
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py writing-materials --program-id my-program
```

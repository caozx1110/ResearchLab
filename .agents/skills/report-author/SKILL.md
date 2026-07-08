---
name: report-author
description: Generate self-contained core weekly reports, stage summaries, PPT materials, and writing-ready synthesis from program `reporting-events` plus linked artifacts.
---

# Report Author

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#experiment-files` · `#ownership` · `#runtime`

Use this skill to turn accumulated program events into report-ready outputs.

## Workflow

1. Read `kb/programs/<program-id>/workflow/reporting-events.yaml` first.
2. Filter by stage when the user asks for a stage summary or a narrower time window.
3. Read linked artifacts only as evidence/context; do not make the report depend on the reader opening them.
4. Keep the report focused on durable events that other skills already emitted.
5. For weekly reports and other advisor-facing reports, rewrite the output into a self-contained submission-ready document.

## Shared Contract

- `reporting-events` is the primary source; confirmed records are supporting context only when needed.
- Weekly reports must be understandable as standalone files for a supervisor/advisor who has basic domain knowledge but has not followed the project chat or local knowledge base.
- Do not rely on local artifact links, reopen pointers, prior notes, or appendices for essential background, methods, experiment comparisons, conclusions, risks, or next steps.
- Local links may be included only as optional provenance after the report is already understandable; external web links may be cited when useful.
- Do not add a standalone glossary for common domain terms unless the user explicitly asks for one; common abbreviations such as VLA, FK, RMSE, and GPU can stay in running text.
- For project-specific methods, papers, datasets, and internal experiment names, give a one-sentence first mention or add a short references section at the end with links. If a name has no external canonical source, link to the local canonical note/report where it is defined.
- Prefer narrative explanations plus compact tables over event dumps; avoid raw reporting-event lists in final weekly reports.
- PPT material should prefer event titles, one-line summaries, and directly linked artifacts.
- If a key milestone is missing from the event stream, push the work back to the producing skill instead of inventing it in the report.
- The bundled `report.py weekly` command is a drafting/indexing aid; polish its output before treating it as a final weekly report.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py weekly --program-id my-program --limit 20
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py ppt-materials --program-id my-program --stage implementation-planning
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py stage-summary --program-id my-program --stage experiment-running
${RESEARCH_PYTHON:-python3} .agents/skills/report-author/scripts/report.py writing-materials --program-id my-program
```

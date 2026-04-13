---
name: research-deliverable-curator
description: Curate Chinese-first human-facing entrypoints under `kb/user/`, including `navigation.md`, current reading lists, report/export indexes, and direct shortcuts to original paper PDFs or repo source roots. Use when Codex needs to answer "what should I open now?", refresh user-facing deliverable pages, organize current outputs for VSCode/Obsidian browsing, or maintain a durable reading bundle without changing canonical ingest or analysis artifacts.
---

# Research Deliverable Curator

Turn deep research paths into reopenable user entrypoints.

## Workflow

1. Read `AGENTS.md` plus `kb/memory/user-profile.yaml` first.
2. Default to Chinese for user-facing prose when `language_preference` indicates Chinese.
3. Read the target program's `charter.yaml`, `workflow/state.yaml`, `evidence/literature-map.yaml`, latest weekly reports, design files, and current exports.
4. Refresh:
   - `kb/user/navigation.md`
   - `kb/user/reading-lists/<program-id>-current-reading.md`
   - `kb/user/reports/current-deliverables.md`
5. Prefer direct links to:
   - paper `note.md`
   - paper `source/primary.pdf`
   - repo `summary.yaml`
   - repo `source/`
6. Keep the page human-oriented: answer what to open first, not only where files live.
7. If the target program exists, append a concise reporting event so weekly reporting can recover the navigation refresh.

## Shared Contract

- Do not mutate canonical literature, repo, idea, or design data just to improve navigation.
- Keep durable user-facing navigation inside `kb/user/`, not in chat only.
- Preserve stable relative links so the pages work in VSCode and Obsidian.
- Treat `kb/user/kb/` as generated read-only browser output; do not edit it manually here.
- If the workspace has multiple programs, prefer an explicit `--program-id`; otherwise choose the only available program or the first sortable program directory.

## Commands

```bash
python3 .agents/skills/research-deliverable-curator/scripts/curate_deliverables.py refresh-all --program-id my-program
python3 .agents/skills/research-deliverable-curator/scripts/curate_deliverables.py refresh-navigation --program-id my-program
python3 .agents/skills/research-deliverable-curator/scripts/curate_deliverables.py build-reading-list --program-id my-program
python3 .agents/skills/research-deliverable-curator/scripts/curate_deliverables.py build-deliverable-index --program-id my-program
```

## Boundaries

- Do not replace `weekly-report-author`; link to weekly reports instead.
- Do not replace `research-note-author`; link to notes instead.
- Do not invent discussion or experiment outcomes that are not already grounded in workspace artifacts.
- Do not keep stale hard-coded reading packs when the evidence map changed; refresh from current files.

---
name: research-note-author
description: Read canonical literature PDFs or repo source snapshots in doc/research/library/, prepare close-reading context, and write professional detailed notes into note.md or repo-notes.md. Use when Codex needs to read a full paper, inspect a repo's README and main entrypoints, refresh stale notes, or finish note writing immediately after ingest.
---

# Research Note Author

Use this after canonical ingest when a literature or repo entry needs durable close-reading notes in llm-wiki format.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (not owner): does not canonicalize raw sources.
- `query` (owner): perform source-grounded close reading over canonical PDFs/repo snapshots.
- `lint` (limited): ensure note structure is complete and inference statements are clearly marked.
- `index` (limited): keep note paths stable so downstream retrieval can index executive summaries.
- `log` (owner): emit durable note completion signals via reporting events or workflow notes when requested.
- Out of scope: duplicate resolution and canonical source identity management (`literature-corpus-builder`, `repo-cataloger`).

## Scope

- Literature target: `doc/research/library/literature/<source-id>/note.md`
- Repo target: `doc/research/library/repos/<repo-id>/repo-notes.md`
- Optional helper context:
  - `doc/research/library/literature/<source-id>/note-context.md`
  - `doc/research/library/repos/<repo-id>/repo-note-context.md`

## Workflow

1. Prepare note assets with the bundled script.
2. If helper context exists, read it end to end; otherwise read source PDF/repo files directly.
3. For literature, read sections needed for a professional technical note; use [$pdf](/Users/czx/.codex/skills/pdf/SKILL.md) habits when layout/figures matter.
4. For repos, read README plus main train/eval/deploy/data entrypoints.
5. Replace scaffolds with concrete notes in your own words, separating observed facts from inferred commentary.
6. If the request becomes cross-source evidence synthesis, hand off to `literature-analyst` or `research-landscape-analyst` instead of stretching one note into a survey.
7. If requested, have the caller skill append concise completion evidence to `workflow/reporting-events.yaml` (for example, via `literature-corpus-builder` or `repo-cataloger` program-feed options).

## Shared Contract

- Do not stop at abstract rewrites.
- Literature notes should let a tired reader quickly grasp the paper's motivation, method mainline, concrete innovations, what the experiments actually show, improvable gaps, and idea seeds worth pursuing next.
- Repo notes should cover goal, architecture, runnable workflow, strengths, risks, and extension points.
- Keep `执行摘要 Executive Summary` self-contained for downstream weekly reporting.
- Keep note templates Chinese-first and structurally consistent with the canonical note scaffold family.
- High-value query outcomes from close reading (critical caveats, implementation risks, decisive comparisons) must be written back into durable note pages (`note.md` or `repo-notes.md`), not left only in chat.

## Commands

```bash
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747 --with-context
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747 --rewrite-generated-notes
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example --with-context
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example --rewrite-generated-notes
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py refresh-notes --repo-id repo-example --program-id my-program
cat doc/research/programs/my-program/workflow/reporting-events.yaml
```

## Handoff Rules

- `literature-corpus-builder` and `repo-cataloger` should route here immediately after ingest when notes are requested.
- If the user mainly wants a current reading bundle or reopen page, route that request to `research-deliverable-curator` instead of overloading the note itself.
- If the close reading turns into a program-level route memo or experiment follow-up, route the durable artifact to `research-discussion-archivist` or `research-experiment-tracker` rather than burying it only in `note.md`.
- If only helper context was prepared but final notes were not completed, say so explicitly.
- Do not rewrite canonical metadata fields as part of note prose polishing.

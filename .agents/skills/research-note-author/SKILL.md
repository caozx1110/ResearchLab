---
name: research-note-author
description: Read canonical literature PDFs or repo source snapshots in doc/research/library/, prepare close-reading context, and write professional detailed notes into note.md or repo-notes.md. Use when Codex needs to read a full paper, inspect a repo's README and main entrypoints, refresh stale notes, or finish note writing immediately after ingest.
---

# Research Note Author

Use this skill after canonical ingest when a literature entry or repo entry needs a real note written by close reading.

## Scope

- Literature target: `doc/research/library/literature/<source-id>/note.md`
- Repo target: `doc/research/library/repos/<repo-id>/repo-notes.md`
- Optional helper context files:
  - `doc/research/library/literature/<source-id>/note-context.md`
  - `doc/research/library/repos/<repo-id>/repo-note-context.md`

## Workflow

1. Prepare note assets with the bundled script.
2. If you generated helper context, read it end to end; otherwise read the source PDF or repo files directly.
3. For literature, read the source PDF sections needed to support a professional note. Use the same extraction/rendering habits as [$pdf](/Users/czx/.codex/skills/pdf/SKILL.md) when layout or figures matter.
4. For repos, read the README plus the main train/eval/deploy/data entrypoints surfaced by the script or visible in the source tree.
5. Replace the scaffold sections with a concrete, professional note in your own words.
6. Be explicit when a caveat or future-work item is your inference rather than an author-maintained statement.

## Commands

```bash
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747 --with-context
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747 --rewrite-generated-notes
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example --with-context
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example --rewrite-generated-notes
```

## Writing Standard

- Do not stop at an abstract rewrite.
- Literature notes should cover motivation, novelty, method, experiments, limitations, and future work with evidence-aware wording.
- Repo notes should cover goal, architecture, runnable workflow, strengths, risks, and extension points based on the visible source.
- Keep the final note detailed enough that a later agent can reuse it without reopening the full source immediately.

## Handoff Rules

- `literature-corpus-builder` and `repo-cataloger` should route here immediately after ingest whenever the task asks for notes.
- If you only prepared optional helper context but did not finish the final note, say so clearly.

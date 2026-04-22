---
name: llm-wiki
description: Persistent LLM-maintained research wiki adapter for this workspace. Use when the user asks to add a source to the knowledge base, query or lint the wiki, create or refresh reusable query/topic/comparison pages under `kb/wiki/`, maintain `kb/wiki/index.md` and `kb/wiki/log.md`, or keep Obsidian-friendly human entrypoints aligned with accumulated research knowledge. Route canonical ingest, note authoring, program work, and browse-only tasks to their owner research skills instead of re-implementing them.
---

# LLM Wiki

Adapt the external `llm-wiki` pattern onto this workspace's research-specific schema.

Read `references/workspace-mapping.md` whenever you need to decide where a durable artifact belongs or how to keep the Obsidian-facing surfaces readable.

## Role

- Preserve the original `llm-wiki` idea: raw sources are immutable, the knowledge base compounds over time, and high-value questions should become durable markdown instead of chat-only answers.
- In this repo the persistent wiki is split across several layers rather than a single flat `wiki/` tree:
  - canonical source knowledge in `kb/library/`
  - program-scoped work in `kb/programs/`
  - reusable cross-program syntheses in `kb/wiki/`
  - human reopen surfaces in `kb/user/`

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (orchestrator): own the generic "add this to the wiki" flow, but route canonical source ingest to `literature-corpus-builder` or `repo-cataloger`, close-reading notes to `research-note-author`, and program-scoped synthesis to the existing owner skills.
- `query` (owner for workspace-level wiki pages): answer from accumulated canonical artifacts and file reusable answers to `kb/wiki/queries/`, `kb/wiki/topics/`, or `kb/wiki/comparisons/` when the result will matter again.
- `lint` (owner for wiki-facing coherence passes): coordinate `research-conductor`'s workspace lint with markdown-level checks for stale entrypoints, missing cross-links, and human-unfriendly reopen pages.
- `index` (owner): keep `kb/wiki/index.md` discoverable for workspace-level durable artifacts after creating or materially updating wiki-facing pages.
- `log` (owner): append consistent entries to `kb/wiki/log.md` for wiki-facing ingest/query/lint/update operations.

## Workflow

1. Read `AGENTS.md`, `docs/llm-wiki.md`, `kb/user/navigation.md`, `kb/wiki/index.md`, and `kb/wiki/log.md` before deciding where the request belongs.
2. Translate the user's request into the correct workspace layer:
   - raw source intake -> `raw/` plus `kb/intake/`
   - canonical source knowledge -> `kb/library/`
   - concrete program work -> `kb/programs/<program-id>/`
   - reusable cross-program wiki prose -> `kb/wiki/`
   - human reopen and Obsidian entrypoints -> `kb/user/`
3. When the user says "add this paper/article/repo to the wiki" or "update the knowledge base":
   - canonicalize the source via `literature-corpus-builder` or `repo-cataloger`
   - write or refresh close-reading notes via `research-note-author` when needed
   - if the result should influence a current program, route to `literature-analyst`, `research-landscape-analyst`, `method-designer`, or another owner skill
   - if there is a reusable cross-source synthesis, comparison, or query outcome, save it as durable markdown under `kb/wiki/`
4. When the user asks a question against the accumulated workspace knowledge:
   - read `kb/wiki/index.md` first
   - follow relevant links into `kb/library/`, `kb/programs/`, and existing `kb/wiki/` artifacts
   - answer with file-backed references
   - save reusable syntheses instead of leaving them only in chat
5. When the user asks for wiki maintenance or health checks:
   - run or reuse `research-conductor` lint for coverage and integrity checks
   - inspect `kb/wiki/` and `kb/user/` for stale summaries, missing links, duplicate landing pages, or human-readable gaps
6. If the human will reopen the result in Obsidian, refresh or create `kb/user/` entrypoints rather than forcing them to dig through YAML-heavy directories.

## Shared Contract

- Do not collapse the existing owner skills back into a monolithic wiki skill.
- Prefer Chinese for human-facing markdown and keep machine-facing keys ASCII-stable.
- Prefer relative markdown links so pages work in Obsidian, VSCode, and GitHub.
- Treat `kb/wiki/queries/` as the default home for saved Q&A memos, and promote repeated themes into `kb/wiki/topics/` or `kb/wiki/comparisons/` as they become valuable.
- Keep `kb/user/kb/` read-only and generated; do not treat it as the source of truth.
- If a new durable human-facing page is likely to be reopened, update `kb/user/navigation.md` or route that refresh to `research-deliverable-curator`.

## Commands

```bash
python3 .agents/skills/research-conductor/scripts/manage_workspace.py lint-workspace --strict
python3 .agents/skills/research-conductor/scripts/manage_workspace.py rebuild-wiki-index
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-example
python3 .agents/skills/research-deliverable-curator/scripts/curate_deliverables.py refresh-navigation --program-id my-program
```

## Boundaries

- Do not replace `literature-corpus-builder`, `repo-cataloger`, `research-note-author`, `weekly-report-author`, or `research-kb-browser`.
- Do not bury cross-source conclusions only in `note.md` when they should live as reusable wiki pages.
- Do not place human-facing reopen guidance in `kb/intake/` or other staging or machine-heavy directories.
- Do not assume every request needs a program; workspace-level wiki synthesis can live directly under `kb/wiki/`.

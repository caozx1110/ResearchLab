---
name: paper-research-workbench
description: Parse and organize local research paper PDFs into an incremental paper workspace with deduplication, searchable metadata, reading notes, topic maps, cross-paper relationship graphs, and AI-readable knowledge base files. Use when Codex needs to process PDFs under raw/, refresh a single new paper or a whole corpus, avoid duplicate parsing of already-seen papers, compare a paper against the existing library, or support downstream research ideation and multi-skill collaboration for robotics, VLA, and related ML papers.
---

# Paper Research Workbench

## Overview

Build a repeatable paper workflow from PDF ingestion to indexed notes, relationship graphs, and machine-readable knowledge nodes.
Separate operational state, human-readable outputs, and AI-readable outputs so the workspace scales when more papers are added.

## Environment Assumptions

- Run from the project root with `python3`.
- Require local Python packages `PyPDF2` and `PyYAML`.
- Require read access to `raw/` and write access to `doc/papers/`.
- Do not assume network access or external APIs.
- If dependencies are missing, stop and report the missing package instead of improvising around it.

## Output Contract

- Keep raw PDFs in `raw/`.
- Write internal parsed metadata and text artifacts under `doc/papers/papers/<paper-id>/`.
- Write user-readable and user-editable outputs under `doc/papers/user/`.
- Maintain ingest and retrieval indexes under `doc/papers/index/`.
- Maintain AI-readable knowledge base files under `doc/papers/ai/`.
- Keep human-readable markdown outputs in Chinese by default, while allowing English tags, topic ids, and specialized terminology.
- Maintain a local HTML hub at `doc/papers/user/index.html` for the user-facing entrypoint.

Expected internal per-paper files:

- `metadata.yaml`
- `_artifacts/text.md`
- `_artifacts/sections.json`

Expected user-facing per-paper files:

- `note.md`
- `ideas.md`
- `feasibility.md`

Expected corpus files:

- `index/registry.yaml`
- `index/papers.yaml`
- `index/tags.yaml`
- `index/topics.yaml`
- `index/relationships.yaml`
- `user/index.html`
- `user/graph.html`
- `user/graph/paper-relationships.md`
- `user/topic-maps/index.md`
- `user/syntheses/frontier-ideas.md`
- `ai/corpus.yaml`
- `ai/graph.yaml`
- `ai/frontier-ideas.yaml`
- `ai/papers/<paper-id>/node.yaml`

## Workflow

1. Refresh the workspace.
   - Prefer `scripts/refresh_workspace.py --input raw`.
   - This runs parse, catalog, relationship graph, user-note scaffolding, topic maps, AI KB build, corpus-level idea synthesis, and HTML hub build in order.
2. Parse incrementally.
   - `scripts/parse_pdf.py` uses `index/registry.yaml`.
   - Skip unchanged source files by SHA-256.
   - Detect duplicate papers by source hash, arXiv id, and identity key.
   - Record duplicate source paths as aliases on the canonical paper instead of creating another folder.
   - Downstream writers should avoid rewriting files when content has not changed.
3. Support single-paper ingestion.
   - Run `scripts/refresh_workspace.py --input raw/some-paper.pdf`.
   - This parses one source and still refreshes corpus-level indexes and user/AI entrypoints.
4. Read from the correct layer.
   - User-readable: `user/index.html`, `user/papers/<paper-id>/`, `user/topic-maps/`, `user/graph.html`, `user/syntheses/frontier-ideas.md`.
   - AI-readable: `ai/corpus.yaml`, `ai/graph.yaml`, `ai/frontier-ideas.yaml`, `ai/papers/<paper-id>/node.yaml`.
5. Fill analysis documents.
   - Use `references/note-schema.md`, `references/idea-rubric.md`, and `references/feasibility-rubric.md`.

## Evidence Rules

- Mark claims in notes as:
  - `Observed`: direct evidence from paper text and metadata.
  - `Inferred`: reasoning based on observed evidence.
  - `Suggested`: proposed experiments or directions.
- Keep uncertain points under `Open Questions`.
- Do not encode speculative claims in `metadata.yaml`.
- Keep the AI KB structured and normalized; do not replace it with prose summaries.
- For human-facing summaries, write concise Chinese prose and preserve English identifiers only where they help retrieval or technical precision.

## Tagging Rules

- Keep tags in lowercase kebab-case.
- Reuse canonical tags in `references/tagging-taxonomy.md`.
- Keep topics broad, and avoid one-off topic names.
- Use conservative auto-tagging from parser, then curate manually if needed.
- Treat relationship edges as retrieval hints, not as scientific truth.

## Command Quick Start

Run from project root:

```bash
python3 skills/paper-research-workbench/scripts/refresh_workspace.py --input raw
```

Single paper:

```bash
python3 skills/paper-research-workbench/scripts/refresh_workspace.py --input raw/2501.09747v1.pdf
```

## Resource Map

- `scripts/parse_pdf.py`: parse PDF metadata and text artifacts.
- `scripts/build_catalog.py`: build catalog indexes.
- `scripts/build_relationship_graph.py`: build cross-paper relationship edges and a readable graph report.
- `scripts/build_ai_kb.py`: build AI-readable corpus and per-paper nodes.
- `scripts/build_corpus_ideas.py`: build corpus-level idea recommendations for humans and for AI consumption.
- `scripts/scaffold_paper_note.py`: create user-facing note and ideation files from templates.
- `scripts/refresh_topic_maps.py`: generate topic map markdown pages.
- `scripts/build_user_hub.py`: build the local HTML user entrypoint and graph view.
- `scripts/refresh_workspace.py`: orchestrate the full refresh workflow.
- `references/workspace-layout.md`: output directory conventions.
- `references/metadata-schema.md`: metadata field contract.
- `references/ai-kb-schema.md`: AI-readable knowledge layer contract.
- `references/tagging-taxonomy.md`: canonical tags and topics.
- `references/note-schema.md`: note structure.
- `references/idea-rubric.md`: idea scoring rubric.
- `references/feasibility-rubric.md`: go/no-go rubric.
- `assets/templates/*.md`: reusable note/topic templates.

## Boundaries

- Do not run external downloads or remote API calls in this workflow.
- Do not overwrite user-authored note content unless explicitly asked.
- Do not treat parser output as authoritative facts without spot-checking.
- Do not create duplicate paper folders for the same arXiv paper or identity key.

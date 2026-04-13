# AGENTS

This repository implements an LLM-maintained research wiki and workflow workspace.

The goal is not only to ingest papers, blogs, and repositories, but to turn them into a durable Chinese-first research operating system: canonical source records, close-reading notes, cross-source synthesis, idea generation, technical route discussion, experiment tracking, weekly reporting, and polished exports.

Treat this file as the schema layer described in `docs/llm-wiki.md`. When there is ambiguity, prefer durable knowledge artifacts over chat-only output.

## Core Principles

1. Default to Chinese for human-facing knowledge outputs.
2. Keep raw sources immutable.
3. Separate staging, canonical knowledge, program work, user navigation, and export layers.
4. Persist high-value conclusions to files instead of leaving them only in chat.
5. Make important outputs easy for a human to find in VSCode or Obsidian.
6. Keep IDs, paths, and machine-facing keys stable and ASCII-friendly even when the prose is Chinese.

## Chinese-First Policy

- Write notes, reports, discussion summaries, design explanations, experiment follow-ups, and wiki query pages in Chinese by default.
- Preserve original English paper titles, repo names, benchmark names, and technical terms on first mention.
- Keep YAML field names, IDs, slugs, and folder names in English or ASCII-safe forms.
- When source material is English, translate the synthesis into Chinese rather than copying large English passages.
- If a user explicitly requests bilingual or English output for a specific artifact, follow that request locally without changing the global default.

## Research Python Runtime

- The canonical research runtime for this workspace is identified by:
  - runtime id: `runtime-research-default`
  - python: a configured research interpreter with YAML and PDF tooling support
- Treat `kb/memory/runtime-environments.yaml` as the durable source of truth for remembered research runtimes.
- When a task reads or writes canonical YAML, parses PDFs, updates research library artifacts, or runs research skill scripts, prefer one of these two invocation styles:
  - configured interpreter: ``${RESEARCH_PYTHON:-python3} <script> ...``
  - remembered runtime wrapper: ``python3 .agents/skills/research-conductor/scripts/run_with_runtime.py <script> ...``
- Do not rely on an unconfigured system Python when the workflow needs `PyYAML` or PDF tooling.
- If the preferred runtime changes, update it through `research-conductor` and then keep this section aligned:
  - ``python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime --python <path-to-python> --label research-default``

## Workspace Layers

### 1. Immutable Source Layer

- `raw/`
- External source bytes and manually collected raw material.
- Never rewrite source bytes in place.

### 2. Intake / Staging Layer

- `kb/intake/`
- Temporary manifests, staged downloads, duplicate review queues, and ingest provenance.
- Useful for auditability, not the primary reading surface.

### 3. Canonical Knowledge Library

- `kb/library/literature/`
- `kb/library/repos/`
- `kb/library/landscapes/`
- `kb/library/search/results/`
- This is the normalized knowledge base for sources and library-scoped syntheses.

### 4. Program Work Layer

- `kb/programs/<program-id>/`
- This is the main place for a concrete research direction.
- Store the program question, evidence, idea evolution, design pack, experiments, weekly reports, decisions, and unresolved questions here.

### 5. Cross-Program Wiki Layer

- `kb/wiki/`
- Store cross-program query artifacts, workspace-wide indexes, lint reports, and other reusable syntheses that should survive beyond a single conversation.

### 6. Human Navigation Layer

- `kb/user/`
- Keep user-facing entrypoints, reading indexes, navigation pages, report indexes, and browser build artifacts here.
- If a human asks “where do I look?” or “how do I quickly open the original PDF?”, the answer should usually land here.

### 7. Export Layer

- `output/`
- Store polished deliverables such as `.docx`, `.pptx`, or final markdown exports.
- Do not let `output/` become the only durable copy of important research knowledge; the canonical version should still live under `kb/`.

## Durable Artifact Rules

Persist the following artifact types instead of leaving them only in chat:

- Source canonicalization:
  - Literature: `kb/library/literature/<source-id>/`
  - Repos: `kb/library/repos/<repo-id>/`
- Source reading notes:
  - Paper note: `.../note.md`
  - Repo note: `.../repo-notes.md`
- Library-scoped surveys or topic scans:
  - `kb/library/landscapes/<survey-id>/`
- Program evidence maps:
  - `kb/programs/<program-id>/evidence/`
- Idea proposals, reviews, and decisions:
  - `kb/programs/<program-id>/ideas/`
- Technical design packs:
  - `kb/programs/<program-id>/design/`
- Experiment planning, execution, and follow-up:
  - `kb/programs/<program-id>/experiments/`
  - Prefer adding `experiments/runs/` for per-run logs when experiment activity becomes substantial.
- Technical route discussions, meeting-like summaries, and important Q&A conclusions:
  - Prefer `kb/programs/<program-id>/discussions/`
  - Create the directory when needed instead of burying these artifacts in chat.
- Weekly reports and digests:
  - `kb/programs/<program-id>/weekly/`
- Reusable high-value question answering artifacts:
  - `kb/wiki/queries/`
- Workspace health checks:
  - `kb/wiki/lint/`
- Polished external deliverables:
  - `output/doc/`, `output/ppt/`, or another explicit export folder

## What Not to Confuse

- `intake/` is audit and staging, not the place a human should browse first.
- `library/` is canonical source knowledge, not the place for every discussion artifact.
- `programs/` is where active research work should accumulate.
- `wiki/` is for reusable synthesized pages and workspace-wide indexes.
- `user/` is the human entry layer.
- `output/` is for export-ready deliverables, not the hidden source of truth.

## Human-Facing Navigation Rules

- Maintain `kb/user/navigation.md` as the first place to look for current outputs and reading entrypoints.
- Maintain `kb/user/reading-lists/*.md` for active reading bundles and `kb/user/reports/*.md` for report/export entry pages.
- When a new weekly report, comparison memo, discussion summary, or major exported deliverable is created, add it to the navigation page if a human is likely to reopen it.
- If a source note is important for current work, add a direct link to both `note.md` and `source/primary.pdf` from a user-facing page instead of forcing deep manual folder traversal.
- Keep `kb/user/kb/` read-only and generated. Do not treat it as the canonical authoring surface.

## Durable Template Conventions

- Default to Chinese prose for human-facing markdown templates, even when source material is English.
- Prefer bilingual recurring section headers when a template may be reused by multiple skills or older scripts, for example `## 执行摘要 Executive Summary`.
- Keep machine-facing YAML keys stable and English (`Observed`, `Inferred`, `Suggested`, `OpenQuestions`, etc.), but write the human-facing values in Chinese by default.
- For durable markdown templates, make the first screen scannable:
  - include a snapshot or status section
  - include a self-contained executive summary
  - include either reading coverage, next actions, or follow-up cues depending on artifact type
- Reuse the same note scaffold family across skills. `research-note-author` is the canonical owner for close-reading note template style; older ingest skills should align to it rather than drifting.

## Skill Editing Guardrails

- Use `skill-creator` habits whenever creating or revising research skills:
  - tighten trigger and ownership wording in `SKILL.md` first
  - keep `SKILL.md` concise and move deterministic repetition into scripts or references only when needed
  - keep `agents/openai.yaml` aligned when a skill's scope or trigger wording changes
  - add or edit scripts only when the task is deterministic, fragile, or repeatedly rewritten
  - validate each touched skill before ending the task
- Prefer the smallest owner-preserving edit set. If the problem is routing ambiguity, fix handoff language instead of duplicating logic across peer skills.
- If a skill folder already exists for a responsibility, treat that responsibility as reserved. Do not expand older skills into it unless the user explicitly asks to merge, replace, or delete the newer skill.
- Do not edit in-progress new skill folders from another thread unless the user explicitly asks for that folder to be touched in the current turn.
- Do not let `research-conductor` absorb user-facing curation, discussion archiving, or run-by-run experiment logging just because those outputs are currently sparse.

## Skill Routing Guidance

Use existing skills with clear boundaries:

- `research-conductor`: program orchestration, memory capture, stage tracking, durable query routing
- `literature-corpus-builder`: paper/blog/project-page canonical ingest
- `repo-cataloger`: repository canonical ingest
- `research-note-author`: close reading and durable source notes
- `literature-analyst`: program-scoped literature synthesis
- `research-landscape-analyst`: pre-program or field-scoped landscape synthesis
- `idea-forge`: idea generation
- `idea-review-board`: idea review and selection pressure-testing
- `method-designer`: implementation-ready design pack
- `weekly-report-author`: weekly and digest reporting
- `research-kb-browser`: read-only knowledge browser
- `research-deliverable-curator`: user-facing reading bundles, navigation pages, and deliverable entrypoints
- `research-discussion-archivist`: durable technical route discussion notes
- `research-experiment-tracker`: per-run experiment logs and follow-up views

Do not overload `research-conductor` with every missing responsibility. Prefer adding focused skills when a workflow repeatedly requires manual glue.

## New Additive Skills

The workspace now includes three additive skills that cover previously missing responsibilities:

- `research-deliverable-curator`
  - Maintain user-facing indexes, current reading bundles, report landing pages, and shortcut links to original PDFs and repo source roots.
- `research-discussion-archivist`
  - Convert important technical discussions into durable program discussion notes with decisions, tradeoffs, open questions, and next actions.
- `research-experiment-tracker`
  - Record experiment plans, run logs, result summaries, regressions, follow-up suggestions, and next actions in a structured, durable way.

Treat these as additive layers rather than reasons to split the current ingest or note-authoring skills. When optimizing older skills, patch them to hand off to these owners instead of re-implementing their outputs.

## Default Agent Checklist

When working in this repository:

1. Identify whether the request should produce a durable artifact.
2. Choose the correct layer before writing files.
3. Prefer Chinese for human-facing prose.
4. Preserve immutable source and staging boundaries.
5. Update navigation or indexes when a human will need to reopen the result.
6. Keep important conclusions, decisions, and follow-ups out of chat-only limbo.
7. When editing skills, preserve single ownership of each durable artifact type and patch handoffs before patching peer logic.

## Practical Reading Paths

For a freshly cloned open-source copy, prefer these entrypoints before drilling into runtime knowledge directories:

- `docs/GETTING_STARTED.md`
- `docs/SKILLS_GUIDE.md`
- `docs/PUBLISHING.md`

Once a local `kb/` workspace exists, prefer these entrypoints before drilling into deep directories:

- `kb/user/navigation.md`
- `kb/wiki/index.md`
- `kb/wiki/log.md`
- `kb/user/kb/index.html`

If the user specifically wants the original source file, link directly to:

- Paper PDF: `kb/library/literature/<source-id>/source/primary.pdf`
- Repo snapshot root: `kb/library/repos/<repo-id>/source/`

## Evolution Rule

If a repeated pain point appears in more than one task, do not only work around it in chat. Update the schema, add a focused skill, or create a durable user-facing navigation artifact so the improvement compounds.

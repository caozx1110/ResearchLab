# AGENTS

This repository implements a Chinese-first research operating system built around v2 knowledge units.

The goal is not to keep a collection of chat transcripts. The goal is to turn papers, repositories, blogs, ideas, experiments, and reports into durable assets that both humans and AI can reopen quickly.

When there is ambiguity, prefer:

1. durable artifacts over chat-only answers
2. lightweight-first records over all-at-once heavyweight ingestion
3. explicit confirmation for AI judgement over silent auto-promotion
4. reusable knowledge units over one-off task notes

## Chinese-First Policy

- Human-facing markdown defaults to Chinese.
- Preserve original English paper titles, repo names, benchmark names, and technical terms on first mention.
- Keep YAML keys, IDs, slugs, and folder names ASCII-safe.
- If a user explicitly requests English or bilingual output for a local artifact, follow that request locally.

## Runtime Policy

- Prefer `${RESEARCH_PYTHON:-python3}` for v2 research scripts.
- Do not rely on an unknown Python when the task needs YAML support.
- If runtime-specific configuration becomes necessary, persist it under `kb/config/` rather than scattering it across skills.

## Workspace Layers (v2)

### 1. Immutable Source Layer

- `raw/`
- External source bytes and manually collected raw material.
- Never rewrite source bytes in place.

### 2. Knowledge Unit Layer

- `kb/units/papers/`
- `kb/units/repos/`
- `kb/units/blogs/`
- `kb/units/ideas/`
- `kb/units/experiments/`
- Each unit owns one `record.yaml` plus optional notes, screening artifacts, analysis artifacts, run logs, and source backups.

### 3. Program Layer

- `kb/programs/<program-id>/`
- Program state, design notes, experiment matrices, and report outputs live here.
- Programs reference knowledge units; they should not duplicate canonical source records.

### 4. Synthesis Layer

- `kb/synthesis/`
- Cross-unit surveys, trend notes, taxonomy drafts, and gap analyses live here.

### 5. Human Navigation Layer

- `kb/user/`
- Human-facing current state, navigation, reading lists, and report material entrypoints live here.
- Keep this layer read-only from the human point of view: it should point into canonical assets, not replace them.

### 6. Export Layer

- `output/`
- Polished exports such as `.docx`, `.pptx`, or final markdown packages.
- Do not let `output/` become the only source of truth.

## Canonical Knowledge Unit Contract

Every knowledge unit must keep a `record.yaml` with at least:

- `id`
- `kind`
- `status`
- `maturity`
- `confirmation_status`
- `information_types`
- `tags`
- `topics`
- `links`
- `reuse_flags`
- `history`

Default policy:

- facts may be auto-confirmed when they are straightforward source metadata or process logs
- AI inference, evaluation, detailed notes, novelty judgement, and failure diagnosis default to `pending_user_confirmation`
- tags, short summaries, and candidate-pool flags may be overwritten
- idea evolution, experiment history, design changes, and reports should preserve history instead of overwriting it

## Information-Type Policy

Always distinguish among:

- `fact`
- `inference`
- `evaluation`
- `user_opinion`
- `unverified`

Do not present inference or evaluation as if it were raw source fact.

## Skill Routing Guidance (v2)

Use these skills with clear ownership:

- `knowledge-base-manager`
  - owns v2 schema initialization, lint, index, query, links, and lifecycle promotion
- `research-config-manager`
  - owns user profile, resource constraints, automation toggles, and token/quality tradeoffs
- `research-orchestrator`
  - owns program creation, stage updates, and high-level routing
- `source-intake`
  - owns source backup, dedupe, and lightweight initial records for papers, repos, and blogs
- `paper-analyst`
  - owns paper screening, worth-reading judgement, and full paper notes
- `repo-analyst`
  - owns repo capability maps, architecture notes, and reuse/modification judgement
- `blog-analyst`
  - owns blog summaries, explanation material, and credibility notes
- `literature-synthesizer`
  - owns surveys, trend summaries, taxonomy drafts, and research-gap synthesis
- `idea-workbench`
  - owns idea capture, novelty/feasibility analysis, selection, and archival
- `method-designer`
  - owns selected-idea-to-method design handoff
- `experiment-workbench`
  - owns experiment plans, run logs, diagnoses, and next-step suggestions
- `report-author`
  - owns weekly reports, stage summaries, and PPT material extraction
- `research-navigator`
  - owns `kb/user/` entrypoints and reading/reopen pages
- `discussion-archivist`
  - owns durable route-discussion notes under `kb/programs/<program-id>/discussions/`
- `wiki-adapter`
  - owns the thin “wiki / knowledge base” language entrypoint and reusable query pages under `kb/synthesis/wiki/`
- `skill-evolution-advisor`
  - owns retrospectives and future workflow improvement prompts

## Skill Editing Guardrails

When editing v2 skills:

- tighten trigger and ownership wording in `SKILL.md` first
- keep `SKILL.md` concise
- keep `agents/openai.yaml` aligned with the current skill contract
- move deterministic repeated behavior into `scripts/`
- prefer replacing old overlapping skills rather than letting two owners coexist
- validate every touched script with at least `--help`

## Default Agent Checklist

When working in this repository:

1. Decide whether the request should produce or update a durable artifact.
2. Choose the correct v2 layer before writing files.
3. Prefer Chinese for human-facing prose.
4. Keep raw sources immutable.
5. Default AI judgement artifacts to `pending_user_confirmation`.
6. Link related knowledge units instead of repeating the same conclusion in multiple places.
7. Refresh human navigation pages when the result is something a human will likely reopen.

## Practical Reading Paths

For a fresh open-source copy, prefer:

- `docs/GETTING_STARTED.md`
- `docs/SKILLS_GUIDE.md`
- `docs/PUBLISHING.md`
- `what_i_need.md`

Once `kb/` exists, prefer:

- `kb/index.md`
- `kb/user/current-state.md`
- `kb/user/navigation.md`
- `kb/user/reading-lists/current-reading.md`
- `kb/user/kb/index.html`

## Evolution Rule

If the same friction appears more than once, do not only work around it in chat. Update the schema, add a focused skill, or improve a reusable navigation or reporting surface so the improvement compounds.

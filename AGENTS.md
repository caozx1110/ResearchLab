# AGENTS

This repository is a Chinese-first research operating system built around v2 knowledge units.

Default preference order:

1. durable artifacts over chat-only answers
2. lightweight-first ingestion over heavyweight one-shot ingestion
3. explicit confirmation for AI judgement over silent auto-promotion
4. reusable knowledge units over one-off notes

## Basics

- Human-facing markdown defaults to Chinese.
- Preserve original English paper titles, repo names, benchmark names, and technical terms on first mention.
- YAML keys, IDs, slugs, and folder names stay ASCII-safe.
- Prefer `${RESEARCH_PYTHON:-python3}` for v2 scripts, but use a known YAML-capable runtime.
- Runtime-specific configuration belongs in `kb/config/`.
- Session start: read the `research-navigator` recall digest once.
- When you go wrong or the user corrects you, log one learning with `skill-evolution-advisor/scripts/learnings.py log`.
- Skill defects are record-only: never auto-modify a skill or `OPTIMIZATION_PLAN.md` from a captured defect.

## Layout

- `kb/raw/`: immutable external source bytes. Never rewrite in place.
- `kb/units/{papers,repos,blogs,ideas,experiments}/<unit-id>/`: canonical knowledge units.
- `kb/programs/<program-id>/`: program state, design, experiments, reports.
- `kb/synthesis/`: cross-unit surveys, taxonomy, trends, gaps.
- `kb/user/`: human-facing navigation and reopen pages, not canonical source.
- `kb/output/`: exports only, never the sole source of truth.
- `kb/` is allowed to be a nested Git repository; runtime state and browser snapshots stay ignored inside that repo.

## Unit Rules

- Every unit must keep a `record.yaml` with at least: `id`, `kind`, `status`, `maturity`, `confirmation_status`, `information_types`, `tags`, `topics`, `links`, `reuse_flags`, `history`.
- Use compact IDs such as `p-openvla-bf86ee46`, `r-openvla-dadda683`, `i-physics-aware-f7e91d86`.
- Do not use full titles as folder names; preserve old long IDs in `legacy_ids` when renamed.
- Straightforward metadata and process logs may be `auto_confirmed`.
- AI inference, evaluation, novelty judgement, detailed notes, and failure diagnosis default to `pending_user_confirmation`.
- Script-generated YAML/workflow timestamps use UTC.
- Tags, short summaries, and candidate-pool flags may be overwritten.
- Idea evolution, experiment history, design changes, and reports should preserve history.
- Information types must distinguish: `fact`, `inference`, `evaluation`, `user_opinion`, `unverified`.
- Never present inference or evaluation as raw source fact.

## Routing

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Analysis: `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`

## Editing Rules

- Update `SKILL.md` ownership/trigger wording first.
- Keep `SKILL.md` concise and `agents/openai.yaml` aligned.
- Move deterministic repeated behavior into `scripts/`.
- Prefer replacing overlapping skills over letting two owners coexist.
- Validate touched scripts with at least `--help`.
- If the same friction appears more than once, fix the reusable layer.

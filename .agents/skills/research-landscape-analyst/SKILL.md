---
name: research-landscape-analyst
description: Analyze the shared canonical literature and repo library for a specified field or direction, summarize current trends, propose candidate research programs before a concrete program exists, and list relevant papers or repos with basic metadata and short summaries. Use when Codex needs to choose a direction, control scope from macro to micro, or browse by tag/topic without ingesting new sources or mutating canonical entries.
---

# Research Landscape Analyst

Use this before `research-conductor` when direction selection is still open and llm-wiki landscape synthesis is needed.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (not owner): does not import new raw sources.
- `query` (owner): run field-scoped retrieval across canonical literature/repos and tag taxonomy.
- `lint` (limited): validate landscape report schema and seed program completeness.
- `index` (limited): maintain discoverable landscape artifacts under `library/landscapes/`.
- `log` (owner): persist survey assumptions, scope mode, and ranking rationale.
- Out of scope: creating/modifying concrete programs (`research-conductor`) and program-scoped deep evidence maps (`literature-analyst`).

## Workflow

1. Read shared literature/repo library plus tag taxonomy if available.
2. Rank relevant papers and repos using `tags`, `topics`, titles, and `short_summary`.
3. Write a landscape report under `doc/research/library/landscapes/` with trend summaries, candidate program seeds, and conductor-ready prompts.
4. For browse-only requests, use list output for concise inventories.
5. Hand selected seeds to `research-conductor` via `create-program-from-landscape`.
6. If the user mainly wants a reopen page, reading pack, or curated human entrypoint, route that work to `research-deliverable-curator` instead of treating the landscape summary as a navigation page.

## Shared Contract

- Keep this skill library-scoped: synthesize trends without mutating canonical paper/repo metadata.
- Keep scope explicit through `macro`, `focused`, or `micro` modes.
- Read workspace-local heuristics from `doc/research/memory/domain-profile.yaml`.
- Keep human-facing landscape summaries Chinese-first while preserving stable machine-facing IDs and YAML keys.
- Candidate programs must include question, goal, seed evidence, bootstrap prompt, and conductor-ready prompt with `survey_id` plus `program_seed_id`.
- High-value query outcomes (trend breaks, overlooked clusters, seed prioritization rationale) must be written back to durable wiki pages under `library/landscapes/`, not left as chat-only recommendations.

## Commands

```bash
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py survey --field "your target field" --scope focused
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py survey --field "your target field" --scope macro --tag tag-a --tag tag-b
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py list --kind literature --tag tag-a --limit 10
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py list --kind repos --query "your field keyword" --limit 5
python3 .agents/skills/research-conductor/scripts/manage_workspace.py create-program-from-landscape --survey-id my-field-scan --program-seed-id seed-1
```

## Boundaries

- Do not create or mutate `doc/research/programs/<program-id>/` here.
- Do not claim freshness beyond the current canonical library snapshot.
- Do not replace `literature-analyst` for program-scoped synthesis once a concrete program exists.
- Do not treat the landscape summary as the durable home for current-work navigation or reading bundles; route those to `research-deliverable-curator`.

## Retrospective Handoff

- If survey scope control, ranking cues, or landscape-to-program handoff felt weak, hand the observation to `skill-evolution-advisor`.

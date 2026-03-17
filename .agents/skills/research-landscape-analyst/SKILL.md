---
name: research-landscape-analyst
description: Analyze the shared literature and repo library for a specified field or direction, summarize current trends, propose candidate research programs before a concrete program exists, and list relevant papers or repos with basic metadata and short summaries. Use when Codex needs to choose a direction, control scope from macro to micro, or browse the current knowledge base by tag or related topic.
---

# Research Landscape Analyst

Use this before `research-conductor` when the user wants to choose a direction, and alongside the library when the user wants a quick filtered inventory.

## Workflow

1. Read the shared literature and repo library, plus the literature tag taxonomy if available.
2. For a specified field, rank relevant papers and repos using `tags`, `topics`, titles, and `short_summary`.
3. Write a shared landscape report under `doc/research/library/landscapes/` with trend summaries, candidate program seeds, and conductor-ready prompts.
4. When the user only wants browsing, use the list command to print concise paper or repo inventories filtered by tag or query.

## Shared Contract

- Keep this skill library-scoped: it should synthesize trends and candidate programs without mutating canonical paper or repo metadata.
- Accept a user-specified field or direction and let scope stay explicit through `macro`, `focused`, or `micro` survey modes.
- Read workspace-local heuristics from `doc/research/memory/domain-profile.yaml` so trend ranking can change with the current field without patching this skill.
- Candidate programs should be handoff-ready for `research-conductor`, including suggested question, goal, seed evidence, a bootstrap prompt, and a conductor-ready prompt that references the current `survey_id` and `program_seed_id`.
- List output should stay concise: basic metadata plus `short_summary`, not full notes or raw abstracts.

## Commands

```bash
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py survey --field "your target field" --scope focused
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py survey --field "your target field" --scope macro --tag tag-a --tag tag-b
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py list --kind literature --tag tag-a --limit 10
python3 .agents/skills/research-landscape-analyst/scripts/survey_landscape.py list --kind repos --query "your field keyword" --limit 5
```

## Boundaries

- Do not create or modify a `program` here; hand candidate directions to `research-conductor`.
- Do not claim freshness beyond what is present in the current shared library snapshot.
- Do not replace `literature-analyst` for program-scoped evidence synthesis once a concrete program already exists.

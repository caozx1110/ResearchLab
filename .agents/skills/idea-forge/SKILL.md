---
name: idea-forge
description: Generate candidate research ideas under doc/research/programs/<program-id>/ideas/ from a program charter, literature evidence, and repo context. Use when Codex needs to propose multiple scoped directions, write proposal.yaml files, or seed idea candidates before critical review.
---

# Idea Forge

Generate proposals without trying to defend them.

## Workflow

1. Read `charter.yaml` and `evidence/literature-map.yaml`.
2. Optionally read the shared repo index, including repo `short_summary`, tags, topics, and entrypoints, to keep ideas implementation-aware.
3. Write one `proposal.yaml` per idea plus `ideas/index.yaml`, including a lightweight `repo_context` when repo evidence was consulted.
4. Leave scoring and selection to `idea-review-board`.

## Shared Contract

- Use stable `lit:` and `repo:` references in proposal evidence links whenever possible.
- Populate `inputs` with the charter, literature map, and any repo index consulted.
- If repo evidence is used, persist the top repo candidates in `proposal.yaml.repo_context` with `repo_id`, `short_summary`, score, and short reasons so downstream skills do not need to rediscover them from scratch.
- Treat `doc/research/memory/domain-profile.yaml` as the source of workspace-local query heuristics and repo-role vocabulary; proposal templates should stay field-agnostic.
- After writing proposals, advance `workflow/state.yaml` to `idea-generation`; only set `active_idea_id` when one candidate is clearly the current focus.

## Command

```bash
python3 .agents/skills/idea-forge/scripts/seed_ideas.py --program-id my-program
```

## Boundaries

- Do not write `review.yaml` or `decision.yaml`.
- Do not overfit the idea list to one favorite repo too early.

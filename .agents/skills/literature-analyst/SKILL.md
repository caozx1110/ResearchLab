---
name: literature-analyst
description: Build program-scoped literature evidence in a program's `evidence/` directory by reading the shared literature library. Use when Codex needs to summarize relevant sources, cluster themes, surface gaps and disagreements, or prepare grounded inputs for idea generation and idea review.
---

# Literature Analyst

Use the canonical library as the evidence base for a specific program.

## Workflow

1. Read `charter.yaml` first.
2. Rank canonical literature using charter cues plus curated `tags`, `topics`, and `short_summary`.
3. Write `evidence/literature-map.yaml` with `Observed`, `Inferred`, `Suggested`, `OpenQuestions`, and a compact retrieval trace.
4. Keep the output brief and decision-oriented.

## Shared Contract

- Populate `inputs` with the charter plus the literature entries or indexes that grounded the map.
- Prefer retrieval that can be audited later: preserve the query terms, matched tag cues, and short summaries for the selected papers.
- Treat `doc/research/memory/domain-profile.yaml` as the source of workspace-local query heuristics; do not hardcode field-specific short terms in this skill.
- After writing the map, advance `workflow/state.yaml` to `literature-analysis` while preserving any later-stage selection fields.
- Leave durable follow-up questions explicit so `research-conductor` can promote them into `workflow/open-questions.yaml` when needed.

## Command

```bash
python3 .agents/skills/literature-analyst/scripts/build_literature_map.py --program-id my-program
```

## Boundaries

- Do not invent freshness or novelty claims that are not grounded in the library.
- Do not bypass the library by reasoning from raw PDFs or loose URLs once canonical entries exist.

## Retrospective Handoff

- If retrieval cues were weak, evidence formatting needed manual repair, or the library contract felt too thin, hand the issue to `skill-evolution-advisor` before ending the task.

---
name: literature-analyst
description: Build program-scoped literature evidence in a program's `evidence/` directory by reading the shared literature library. Use when Codex needs to summarize relevant sources, cluster themes, surface gaps and disagreements, or prepare grounded inputs for idea generation and idea review.
---

# Literature Analyst

Use the canonical library as the evidence base for program-scoped llm-wiki synthesis.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (not owner): does not import raw sources.
- `query` (owner): retrieve and rank canonical papers using charter cues plus tags/topics.
- `lint` (limited): validate evidence-map structure and citation trace completeness.
- `index` (limited): update program-local evidence artifacts, not global library indexes.
- `log` (owner): append report-ready analysis events for downstream weekly reporting.
- Out of scope: external web scouting (`literature-scout`) and canonical ingest (`literature-corpus-builder`).

## Workflow

1. Read `charter.yaml` first.
2. Rank canonical literature using charter cues plus curated `tags`, `topics`, and `short_summary`.
3. Write `evidence/literature-map.yaml` with `Observed`, `Inferred`, `Suggested`, `OpenQuestions`, and compact retrieval trace.
4. Append a concise event to `workflow/reporting-events.yaml`.
5. Advance `workflow/state.yaml` to `literature-analysis` while preserving later-stage fields.
6. If the user actually needs pre-program field scanning, route to `research-landscape-analyst`; if they need a human-facing reading bundle, route to `research-deliverable-curator`.

## Shared Contract

- Populate `inputs` with charter plus literature entries/index artifacts that grounded the map.
- Prefer retrieval that remains auditable: preserve query terms, matched tag cues, and selected summaries.
- Treat `doc/research/memory/domain-profile.yaml` as workspace-local query heuristic source.
- Keep human-facing synthesis in Chinese while preserving machine-facing YAML keys.
- High-value query outcomes (theme clusters, conflicts, evidence gaps, shortlist rationales) must be written back to durable wiki pages (`evidence/literature-map.yaml` and reporting events), never kept only in chat.
- Leave durable follow-up questions explicit so `research-conductor` can promote them into `workflow/open-questions.yaml`.

## Commands

```bash
python3 .agents/skills/literature-analyst/scripts/build_literature_map.py --program-id my-program
python3 .agents/skills/research-conductor/scripts/manage_workspace.py set-stage --program-id my-program --stage literature-analysis
cat doc/research/programs/my-program/workflow/reporting-events.yaml
```

## Boundaries

- Do not invent novelty/freshness claims that are not grounded in the canonical library.
- Do not bypass canonical entries by reasoning from loose raw PDFs/URLs when canonical records already exist.
- Do not mutate canonical metadata as part of analysis synthesis.
- Do not replace close-reading notes, field-wide landscape surveys, or user-facing reading bundles; route those to `research-note-author`, `research-landscape-analyst`, or `research-deliverable-curator`.

## Retrospective Handoff

- If retrieval cues were weak, evidence formatting required manual repair, or audit traces were hard to maintain, hand the issue to `skill-evolution-advisor`.

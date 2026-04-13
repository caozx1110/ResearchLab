---
name: literature-tagger
description: Curate topics, tags, and tag taxonomy for canonical literature in `doc/research/library/literature/`, including refreshing `tags.yaml`, heuristic retagging from title and abstract, manual tag assignment, alias normalization, and taxonomy lint or apply passes. Use when Codex needs to maintain a paper tagging system after ingestion, clean up noisy tags, or prepare a better-tagged library for downstream literature analysis.
---

# Literature Tagger

Use this after ingest whenever llm-wiki tag quality, taxonomy consistency, or retrieval cues need maintenance.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (not owner): does not import PDFs or URLs.
- `query` (limited): read canonical metadata to derive candidate tags/topics.
- `lint` (owner): detect alias drift, noisy tags, and taxonomy schema violations.
- `index` (owner for tag-oriented projections): refresh `tags.yaml`, taxonomy projections, and tag-driven literature index views after tag updates.
- `log` (owner): preserve lightweight tagging audit notes in metadata.
- Out of scope: canonical source ingestion (`literature-corpus-builder`) and deep note writing (`research-note-author`).

## Workflow

1. Read canonical `metadata.yaml` files under `doc/research/library/literature/`.
2. Run `taxonomy-sync` after batch import so current canonical tags are represented in `tag-taxonomy.yaml`.
3. Use `retag` for heuristic refresh from title plus abstract, or `assign` for manual updates.
4. Use `taxonomy-upsert` to register canonical tags, aliases, topic hints, and descriptions.
5. Run `taxonomy-lint` and `taxonomy-apply` to normalize alias and formatting drift.
6. Refresh tag-oriented projections (`tags.yaml`, taxonomy files, and tag-driven index views) so retrieval remains consistent, without taking over canonical source creation or duplicate handling.

## Shared Contract

- Only edit `topics`, `tags`, lightweight `tagging` notes, and taxonomy artifacts.
- Preserve bibliographic identity fields (`canonical_title`, `authors`, `canonical_url`, `external_ids`) during tag curation.
- Keep tags short, stable, lowercase, and hyphenated; aliases belong in `tag-taxonomy.yaml`.
- Load theme-specific seeds, aliases, and topic hints from `doc/research/memory/domain-profile.yaml`.
- High-value query findings from retagging (new emergent concepts, alias collisions, taxonomy gaps) must be written back to wiki artifacts (`tag-taxonomy.yaml`, `tags.yaml`, and per-source `metadata.yaml` notes), not left as ephemeral chat suggestions.
- If retagging exposes canonical identity gaps, duplicate ambiguity, or missing ingest-time fields, hand that issue back to `literature-corpus-builder` instead of patching around it here.

## Commands

```bash
python3 .agents/skills/literature-tagger/scripts/tag_literature.py refresh-index
python3 .agents/skills/literature-tagger/scripts/tag_literature.py taxonomy-sync --all
python3 .agents/skills/literature-tagger/scripts/tag_literature.py retag --all
python3 .agents/skills/literature-tagger/scripts/tag_literature.py retag --source-id lit-arxiv-2501-09747v1 --mode replace
python3 .agents/skills/literature-tagger/scripts/tag_literature.py assign --source-id lit-arxiv-2501-09747v1 --tag long-horizon --tag recovery --topic robot-learning
python3 .agents/skills/literature-tagger/scripts/tag_literature.py taxonomy-upsert --tag long-horizon --alias longhorizon --topic robot-learning --description "Long-horizon execution or recovery."
python3 .agents/skills/literature-tagger/scripts/tag_literature.py taxonomy-lint --all --strict
python3 .agents/skills/literature-tagger/scripts/tag_literature.py taxonomy-apply --all
cat doc/research/programs/my-program/workflow/reporting-events.yaml
```

## Boundaries

- Do not ingest PDFs, download URLs, or resolve duplicate reviews.
- Do not silently rewrite bibliographic facts during tag cleanup.
- Do not treat `tags.yaml` as the only source of truth; canonical per-paper metadata stays authoritative.
- Do not take over canonical ingest ownership or duplicate-resolution logic from `literature-corpus-builder`.

## Completion Checklist

- Spot-check updated `metadata.yaml` entries for `topics`, `tags`, and `tagging` notes.
- Inspect `tag-taxonomy.yaml` when introducing new concepts or aliases.
- Refresh and verify `index.yaml`, `graph.yaml`, and `tags.yaml` after batch operations.
- Normalize noisy local tags before ending the run.

## Retrospective Handoff

- If taxonomy curation repeatedly exposes alias drift, heuristic weakness, or noisy tag generation, hand the issue to `skill-evolution-advisor`.

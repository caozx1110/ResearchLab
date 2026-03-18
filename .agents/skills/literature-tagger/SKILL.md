---
name: literature-tagger
description: Curate topics, tags, and tag taxonomy for canonical literature in `doc/research/library/literature/`, including refreshing `tags.yaml`, heuristic retagging from title and abstract, manual tag assignment, alias normalization, and taxonomy lint or apply passes. Use when Codex needs to maintain a paper tagging system after ingestion, clean up noisy tags, or prepare a better-tagged library for downstream literature analysis.
---

# Literature Tagger

Use this after literature intake whenever the shared library needs cleaner topics, tags, a refreshed `tags.yaml`, or a stable `tag-taxonomy.yaml`.

## Workflow

1. Read canonical `metadata.yaml` files under `doc/research/library/literature/`.
2. Run `taxonomy-sync` after a batch import so current canonical tags are reflected in `tag-taxonomy.yaml`.
3. Use `retag` for heuristic topic or tag refresh from title plus abstract, including emergent keyword-tag discovery for papers from a new subfield, or `assign` for manual additions.
4. Use `taxonomy-upsert` to register canonical tags, aliases, topic hints, and descriptions when the current taxonomy is too thin.
5. Use `taxonomy-lint` and `taxonomy-apply` to detect and then normalize alias or formatting drift.
6. After a batch import in a new or shifting field, run at least one retag + taxonomy sync pass so downstream retrieval sees the finer-grained concepts defined by the current domain profile.

## Shared Contract

- Only edit literature `metadata.yaml` fields related to `topics`, `tags`, lightweight `tagging` audit notes, and the shared `tag-taxonomy.yaml`.
- Preserve bibliographic identity fields such as `canonical_title`, `authors`, `canonical_url`, and `external_ids` during normal tag curation.
- After tag edits, refresh `library/literature/index.yaml`, `graph.yaml`, and `tags.yaml` so downstream skills see a consistent library snapshot.
- Keep canonical tags short, stable, lowercase, and hyphenated; aliases belong in `tag-taxonomy.yaml`, not in paper metadata.
- Prefer short, stable, lowercase slug tags unless the user asks for a different taxonomy.
- Load theme-specific tag seeds, aliases, and topic hints from `doc/research/memory/domain-profile.yaml` instead of hardcoding a field-specific taxonomy in this skill.
- When heuristic retagging discovers a strong new keyword tag that is not yet in the taxonomy, keep it in metadata and let `taxonomy-sync` register it as a discovered canonical tag instead of dropping it.

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
```

## Boundaries

- Do not ingest PDFs, download URLs, or resolve duplicate reviews here. That stays with `literature-corpus-builder`.
- Do not silently rewrite bibliographic facts as part of tag cleanup.
- Do not treat `tags.yaml` as the only fact source; canonical metadata remains the source of truth.
- Do not use taxonomy aliases as an excuse to keep messy tags in metadata forever; normalize them when they become stable.

## Completion Checklist

- Spot-check updated `metadata.yaml` entries to confirm `topics`, `tags`, and `tagging` notes match the intended curation.
- Inspect `library/literature/tag-taxonomy.yaml` whenever you add a new concept, alias, or naming rule.
- Refresh and inspect `library/literature/index.yaml`, `graph.yaml`, and `tags.yaml` after any retag, taxonomy apply, or manual assignment batch.
- If a tag looks too local, noisy, or duplicated, normalize it before ending the run.

## Retrospective Handoff

- If taxonomy curation exposed recurring alias drift, missing heuristics, or noisy tag generation, hand the issue to `skill-evolution-advisor` before ending the task.

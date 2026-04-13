---
name: literature-scout
description: Capture external literature search results into doc/research/library/search/results/ without directly mutating the canonical literature library. Use when Codex needs to search for new papers, blogs, or project pages, stage external evidence for later ingestion, or document why more evidence is needed before an idea decision.
---

# Literature Scout

Capture external query signals first, then hand curated candidates to canonical ingest.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (not owner): does not write canonical `library/literature/` entries.
- `query` (owner): run external discovery queries and shortlist candidate sources.
- `lint` (limited): ensure staged search records include query intent, timestamps, and candidate provenance.
- `index` (limited): keep search-result manifests queryable under `library/search/results/`.
- `log` (owner): persist why the search happened and what remains uncertain.
- Out of scope: duplicate resolution and canonical source creation (`literature-corpus-builder`).

## Workflow

1. Search externally only when requested by user intent, evidence requests, or explicit freshness gaps.
2. Record query text, recency assumptions, notes, and candidate URLs under `doc/research/library/search/results/<search-id>.yaml`.
3. Mark high-confidence vs uncertain candidates explicitly instead of upgrading uncertain hits to facts.
4. Hand shortlisted URLs to `literature-corpus-builder`, preferably via `ingest --search-result ...`.

## Shared Contract

- Search results are staging artifacts, not canonical evidence.
- Keep `inputs` and program context traceable so later ingest can explain why each query happened.
- High-value query outcomes (ranked shortlists, novelty caveats, disagreement notes) must be written back to durable wiki pages under `library/search/results/` and referenced by downstream ingest.
- If freshness remains uncertain after search, preserve the uncertainty in the staged artifact.

## Commands

```bash
python3 .agents/skills/literature-scout/scripts/record_search_results.py --search-id latest-vla --query "vision language action recovery" --candidate-url https://arxiv.org/abs/2501.09747
python3 .agents/skills/literature-scout/scripts/record_search_results.py --search-id latest-vla --query "humanoid manipulation policy" --candidate-url https://openreview.net/forum?id=example
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --search-result doc/research/library/search/results/latest-vla.yaml
python3 .agents/skills/research-conductor/scripts/manage_workspace.py add-open-question --program-id my-program --question-id q-freshness --question "Need newer evidence beyond current scout batch?"
```

## Boundaries

- Do not write directly into `library/literature/`.
- Do not present search-stage candidates as canonical facts.
- Do not drop provenance fields just because a URL looks familiar.

## Retrospective Handoff

- If search staging, freshness checks, or scout-to-ingest handoff repeatedly fails, hand the issue to `skill-evolution-advisor`.

---
name: literature-scout
description: Capture external literature search results into doc/research/library/search/results/ without directly mutating the canonical literature library. Use when Codex needs to search for new papers, blogs, or project pages, stage external evidence for later ingestion, or document why more evidence is needed before an idea decision.
---

# Literature Scout

Capture search results first, then hand them to `literature-corpus-builder`.

## Workflow

1. Search externally only when the user asks for latest information or when an evidence request requires it.
2. Record the query, notes, and candidate URLs under `library/search/results/<search-id>.yaml`.
3. Hand shortlisted URLs to `literature-corpus-builder` for canonicalization, preferably via `ingest --search-result ...` so the handoff stays auditable.

## Shared Contract

- Search results are staging artifacts, not canonical evidence.
- Keep `inputs` and program context traceable so later ingestion can explain why the search happened.
- If novelty or freshness is still uncertain after search, leave that uncertainty explicit instead of upgrading the result to a fact.

## Command

```bash
python3 .agents/skills/literature-scout/scripts/record_search_results.py --search-id latest-vla --query "vision language action recovery" --candidate-url https://arxiv.org/abs/2501.09747
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --search-result doc/research/library/search/results/latest-vla.yaml
```

## Boundaries

- Do not write directly into `library/literature/`.
- Keep search logs lightweight and auditable.

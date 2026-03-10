# AI KB Schema

The AI-readable layer lives under `doc/papers/ai/`.

## Corpus Files

- `corpus.yaml`: corpus-wide entrypoint with paper list, topic clusters, and tag clusters.
- `graph.yaml`: adjacency map built from `relationships.yaml`.

## Per-Paper Node Files

Each `doc/papers/ai/papers/<paper-id>/node.yaml` should include:

- core metadata: title, year, arxiv_id, doi, authors
- retrieval keys: tags, topics, identity_key
- abstract: short factual summary for search and downstream prompting
- neighbors: top related papers with scores and rationale fields
- artifact_paths: paths to note, ideas, feasibility, text, and metadata files
- knowledge_surfaces: pointers to `doc/papers/user/` HTML and markdown outputs

## Rules

- Keep this layer normalized and structured.
- Prefer lists and key-value objects over free-form prose.
- Use relative workspace paths so other skills can compose with these files directly.

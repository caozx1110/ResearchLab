# Workspace Layout

Use this layout to keep source PDFs, parsed artifacts, and thinking outputs separated.

## Source Layer

- `raw/`: incoming paper PDFs.
- Keep this folder immutable except for adding/removing PDFs.

## Working Layer

- `doc/papers/papers/<paper-id>/metadata.yaml`: structured metadata for one paper.
- `doc/papers/papers/<paper-id>/_artifacts/text.md`: extracted text snippets.
- `doc/papers/papers/<paper-id>/_artifacts/sections.json`: detected section headings.

## User Layer

- `doc/papers/user/index.html`: local HTML entrypoint for the user.
- `doc/papers/user/graph.html`: dedicated local HTML graph view.
- `doc/papers/user/papers/<paper-id>/note.md`: reading notes and evidence.
- `doc/papers/user/papers/<paper-id>/ideas.md`: editable ideation backlog.
- `doc/papers/user/papers/<paper-id>/feasibility.md`: go/no-go assessment.
- `doc/papers/user/topic-maps/*.md`: generated topic summaries.
- `doc/papers/user/graph/paper-relationships.md`: markdown version of the relationship graph.
- `doc/papers/user/syntheses/*.md`: cross-paper synthesis notes and frontier ideas.

## Index Layer

- `doc/papers/index/papers.yaml`: paper list and metadata summary.
- `doc/papers/index/tags.yaml`: tag-to-paper mapping.
- `doc/papers/index/topics.yaml`: topic-to-paper mapping.
- `doc/papers/index/registry.yaml`: incremental ingest and dedupe registry.
- `doc/papers/index/relationships.yaml`: AI-readable edge list across papers.

## AI Knowledge Layer

- `doc/papers/ai/corpus.yaml`: corpus-level AI index.
- `doc/papers/ai/graph.yaml`: neighbor map for agent consumption.
- `doc/papers/ai/frontier-ideas.yaml`: structured cross-paper idea recommendations.
- `doc/papers/ai/papers/<paper-id>/node.yaml`: per-paper normalized node file.

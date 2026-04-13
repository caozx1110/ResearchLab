# Open Research Workspace Skills

This repository contains an open-source, reusable subset of a research-oriented Codex workspace.

It focuses on three publishable layers:

- `.agents/`
- `AGENTS.md`
- `docs/`

Together, these files describe a Chinese-first LLM-maintained research workflow that can:

- ingest papers, blogs, and repositories into a structured knowledge base
- maintain durable notes, evidence maps, idea proposals, and design packs
- generate user-facing navigation pages and a local read-only knowledge browser
- coordinate long-running research programs through skill-based workflows

## Repository Layout

- `.agents/`: local skills, scripts, shared Python helpers, and skill metadata
- `AGENTS.md`: schema-level workspace contract for how the agent should structure and maintain the knowledge base
- `docs/`: user-facing guidance, onboarding material, architecture notes, and publishing instructions

## Knowledge Base Convention

Runtime knowledge artifacts are expected under:

```text
kb/
├── intake/
├── library/
├── programs/
├── wiki/
├── user/
└── memory/
```

This repository does **not** need to ship a populated `kb/` directory. The open-source surface is the workflow logic and documentation; each user can initialize or generate their own knowledge base locally.

## Start Here

- [Getting Started](docs/GETTING_STARTED.md)
- [Skills Guide](docs/SKILLS_GUIDE.md)
- [Publishing Notes](docs/PUBLISHING.md)
- [LLM Wiki Pattern](docs/llm-wiki.md)

## Notes

- Paths in the published workflow are relative and `kb/`-based by default.
- Scripts are written to prefer `kb/` while remaining compatible with legacy `doc/research/` workspaces during migration.
- User-specific absolute paths have been removed from the publishable guidance surface.

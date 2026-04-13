---
name: research-kb-browser
description: Build and serve a human-friendly, read-only visual browser for shared research knowledge artifacts under `doc/research/`, including wiki index/log/query/lint views, literature, repos, tags, landscapes, and program state. Use when Codex needs to present navigable UI views of current workspace artifacts without mutating canonical files or authoring new research outputs.
---

# Research KB Browser

Build a local, read-only knowledge browser for research v1.1.

Priority display order for the browser:

1. Show wiki index/log previews first.
2. Surface wiki query artifacts and lint results (`doc/research/wiki/queries`, `doc/research/wiki/lint/latest.md`).
3. Keep literature/repos/tags/landscapes/program data available as the broader context.

## Workflow

1. Read the current `doc/research/` library, memory profile, program artifacts, and curated user-facing entry pages when they exist.
2. Normalize the shared YAML and markdown artifacts into a UI snapshot.
3. Write a static browser entrypoint under `doc/research/user/kb/`.
4. When the user wants a live experience, run the local daemon so the browser auto-rebuilds and auto-refreshes as research files change.

## Shared Contract

- Treat this skill as a visualization layer, not a research-authoring layer.
- Read from canonical library and program artifacts without rewriting them.
- Keep the browser read-only; do not add YAML edit APIs or implicit writeback flows.
- Preserve stable IDs and file links so users can jump from the UI back to the underlying source files.
- Use workspace-local `domain-profile.yaml` only as display context; do not hardcode the current research theme into the browser logic.
- When curated reopen pages exist under `doc/research/user/`, surface them as entrypoints instead of creating a parallel authoring flow; `research-deliverable-curator` remains the owner of those pages.

## Commands

```bash
python3 .agents/skills/research-kb-browser/scripts/build_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/open_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/open_user_hub.py   # legacy alias
python3 .agents/skills/research-kb-browser/scripts/status_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/stop_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/serve_kb_browser.py
```

Legacy compatibility:

- Older workflows may still call `open_user_hub.py` from the historical
  `paper-research-workbench` flow.
- Use `open_kb_browser.py` as the canonical entrypoint; `open_user_hub.py`
  is kept only as a compatibility shim.

## Boundaries

- Do not mutate canonical literature, repo, program, or memory YAML.
- Do not treat this browser as the fact source; `doc/research/` remains canonical.
- Do not depend on npm, React, or external frontend tooling for the first version.
- Do not reuse `paper-research-workbench` assets, templates, or directory conventions.
- Do not turn this browser into a second navigation-authoring system; if the user wants durable "what should I open now?" pages refreshed, route that work to `research-deliverable-curator`.

## Retrospective Handoff

- If the browser build exposed missing snapshots, brittle rendering assumptions, or awkward read-only constraints, pass the observation to `skill-evolution-advisor` before closing the task.

---
name: research-kb-browser
description: Build and serve a human-friendly visual browser for the shared research knowledge base and program artifacts under doc/research/, including literature, repos, tags, landscapes, and program state. Use when Codex needs to give the user a readable UI for browsing the current research workspace, keep that UI updated in the background, or open a live local knowledge browser.
---

# Research KB Browser

Build a local, read-only knowledge browser for research v1.1.

## Workflow

1. Read the current `doc/research/` library, memory profile, and program artifacts.
2. Normalize the shared YAML and markdown artifacts into a UI snapshot.
3. Write a static browser entrypoint under `doc/research/user/kb/`.
4. When the user wants a live experience, run the local daemon so the browser auto-rebuilds and auto-refreshes as research files change.

## Shared Contract

- Treat this skill as a visualization layer, not a research-authoring layer.
- Read from canonical library and program artifacts without rewriting them.
- Keep the browser read-only; do not add YAML edit APIs or implicit writeback flows.
- Preserve stable IDs and file links so users can jump from the UI back to the underlying source files.
- Use workspace-local `domain-profile.yaml` only as display context; do not hardcode the current research theme into the browser logic.

## Commands

```bash
python3 .agents/skills/research-kb-browser/scripts/build_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/open_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/status_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/stop_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/serve_kb_browser.py
```

## Boundaries

- Do not mutate canonical literature, repo, program, or memory YAML.
- Do not treat this browser as the fact source; `doc/research/` remains canonical.
- Do not depend on npm, React, or external frontend tooling for the first version.
- Do not reuse `paper-research-workbench` assets, templates, or directory conventions.

## Retrospective Handoff

- If the browser build exposed missing snapshots, brittle rendering assumptions, or awkward read-only constraints, pass the observation to `skill-evolution-advisor` before closing the task.

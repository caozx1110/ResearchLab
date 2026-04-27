---
name: research-navigator
description: Build human-facing entrypoints for the v2 research system under `kb/user/`, including current state, navigation, reading lists, and report-material pages while keeping the navigation surface read-only.
---

# Research Navigator

Use this skill to tell the human what to open next and to open a local browser for v2 research assets.

## Scope

- Refresh durable human-facing pages under `kb/user/`.
- Build a local browser snapshot from `kb/units/`, `kb/programs/`, `kb/synthesis/`, `kb/user/`, and legacy `kb/library/` when present.
- Keep source records canonical; browser output is generated under `kb/user/kb/`.
- The browser supports a Workbench, Markdown preview/edit for `.md`/`.txt`, a bottom terminal, Codex CLI launch, and macOS system-terminal API.
- Do not mutate raw sources or canonical YAML through the browser.

## Commands

```bash
python3 .agents/skills/research-navigator/scripts/navigate.py refresh
python3 .agents/skills/research-navigator/scripts/navigate.py current-state
python3 .agents/skills/research-navigator/scripts/navigate.py reading-list

python3 .agents/skills/research-navigator/scripts/build_kb_browser.py
python3 .agents/skills/research-navigator/scripts/open_kb_browser.py
python3 .agents/skills/research-navigator/scripts/open_user_hub.py   # compatibility alias
python3 .agents/skills/research-navigator/scripts/status_kb_browser.py
python3 .agents/skills/research-navigator/scripts/stop_kb_browser.py
python3 .agents/skills/research-navigator/scripts/serve_kb_browser.py
```

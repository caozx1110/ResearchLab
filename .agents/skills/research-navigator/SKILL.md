---
name: research-navigator
description: Build human-facing entrypoints for the v2 research system under `kb/user/`, including current state, navigation, reading lists, and report-material pages while keeping the navigation surface read-only.
---

# Research Navigator

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#ownership`

Use this skill to tell the human what to open next and to open a local browser for v2 research assets.

## First-time use

新用户或新接手的协作者第一次进入 kb 时，按以下顺序起步（每步都是一句命令或一个文件）：

1. `python3 .agents/skills/research-navigator/scripts/navigate.py refresh` — 刷新 `kb/user/` 下的所有人面向页面。
2. 打开 `kb/index.md` — 全局 unit 索引（papers / repos / ideas / experiments），按 status / pool 概览整个知识库当前规模。
3. 打开 `kb/user/current-state.md` — 当前所有 active program 的状态、stage、next-actions。
4. （可选）`python3 .agents/skills/research-navigator/scripts/open_kb_browser.py` — 在本地浏览器中打开 Workbench / 预览 / 编辑视图，适合需要一边读 paper 一边记录的工作流。
5. 若想看具体某个 program 的来龙去脉：进 `kb/programs/<program-id>/README.md` → `state.yaml` → `workflow/decision-log.md`。

如果整个 `kb/user/` 为空，说明该 workspace 还没跑过 `navigate.py refresh` 或还没初始化；先 `python3 .agents/skills/knowledge-base-manager/scripts/kb.py init` 一次。

## Scope

- Refresh durable human-facing pages under `kb/user/`.
- Build a local browser snapshot from `kb/units/`, `kb/programs/`, `kb/synthesis/`, `kb/user/`, and legacy `kb/library/` when present.
- Program browser cards must support both legacy program layouts and v2 program-root `state.yaml` / `README.md` layouts.
- Keep source records canonical; browser output is generated under `kb/user/kb/`.
- The browser supports a Workbench, Markdown preview/edit for `.md`/`.txt`, a bottom terminal, Codex CLI launch, macOS system-terminal API, and portrait-friendly narrow-window adaptation.
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

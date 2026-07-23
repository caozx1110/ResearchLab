---
name: research-navigator
description: Build human-facing entrypoints for the research system under `kb/user/`, including current state, navigation, reading lists, report-material pages, and an optional browser workbench.
---

# Research Navigator

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#ownership` · `#runtime`

Use this skill to tell the human what to open next and to open a local browser for research assets.

## First-time use

新用户或新接手的协作者第一次进入工作区时，只提供自然语言与公开快捷入口：

1. 运行 `kb init`，先把可用的知识库结构准备好；快速偏好可现在设置，也可稍后补充。
2. 运行 `kb status`，查看当前资料、研究计划与需要关注的问题。
3. 运行 `kb next`，取得现在最值得推进的少量事项与原因。
4. 需要 Obsidian 阅读网络时运行 `kb obsidian update`；需要检查投影状态时运行 `kb obsidian status`。
5. 若需要本地浏览 Workbench，直接用自然语言请 Agent 打开；Agent 私下处理实现命令与访问地址。

空工作区应直接邀请用户发送论文、文件、数据卡或本地代码仓，不展示内部脚本、文件路径或参数。

## Scope

- Refresh durable human-facing pages under `kb/user/`.
- Build a local browser snapshot from `kb/units/`, `kb/programs/`, `kb/synthesis/`, `kb/user/`, and `kb/config/`.
- Program browser cards target the core program-root `state.yaml` / `README.md` layout.
- Keep source records canonical; browser output is generated under `kb/user/kb/`.
- The browser supports a Workbench, Markdown preview/edit for `.md`/`.txt`, and portrait-friendly narrow-window adaptation. Terminal and system-terminal surfaces are disabled by default and are maintainer-only when explicitly enabled.
- The browser editor is intentionally limited to `.md`/`.txt`; it can update markdown/text notes and trigger a configured checkpoint. Do not mutate raw sources or canonical YAML through the browser.

## Maintainer/private commands

The following implementation commands are for Agent execution, maintenance, and isolated tests only. Never copy them into user-visible guidance or stdout.

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

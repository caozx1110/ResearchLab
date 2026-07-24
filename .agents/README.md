# Workspace Agents

这个目录存放 workspace-oss 的本地 skills 和共享运行库。当前系统围绕 knowledge units 工作；安装后的 runtime 规则以 workspace 根 `AGENTS.md`（由本目录的 `AGENTS.md` 分发）为准，结构化 artifact 协议以 `.agents/lib/research/SCHEMAS.md` 为准。

## Layout

- `.agents/skills/`: 20 个本地 skill；`kb-cli` 提供快捷入口，`research-navigator` 仅保留为可选投影辅助。
- `.agents/lib/research/`: 跨 skill 共享的 Python helper。
- `.agents/lib/research/SCHEMAS.md`: record、program、config、memory、confirmation gate 的共享契约。

## Current Skill Groups

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Discovery and tracking: `literature-search`, `research-monitor`
- Analysis: `paper-analyst`, `repo-analyst`, `dataset-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`; optional projection helper: `research-navigator`
- Shortcut dispatcher: `kb-cli`

## Runtime

Runtime 会优先复用已兼容的 Python；只有需要时才准备 workspace-local managed environment。普通调用不会向任意 shared interpreter 安装依赖。

开发和重构时先跑：

```bash
python -m pytest
```

新增或调整脚本时，至少验证对应脚本的 `--help`。

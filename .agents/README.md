# Workspace Agents

这个目录存放 workspace-oss 的本地 skills 和共享运行库。当前系统围绕 knowledge units 工作；人类可读规则以仓库根目录的 `AGENTS.md` 为准，结构化 artifact 协议以 `.agents/lib/research/SCHEMAS.md` 为准。

## Layout

- `.agents/skills/`: 17 个本地 skill，其中 16 个组成 core research chain，`kb-cli` 提供快捷入口。
- `.agents/lib/research/`: 跨 skill 共享的 Python helper。
- `.agents/lib/research/SCHEMAS.md`: record、program、config、memory、confirmation gate 的共享契约。

## Current Skill Groups

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Analysis: `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`
- Shortcut dispatcher: `kb-cli`

## Runtime

脚本首次运行会自动创建并使用项目内受管 `.venv`（含 PyYAML）。高级用户可用 `RESEARCH_PYTHON` 覆盖解释器，或用 `RESEARCH_NO_MANAGED_VENV=1` 关闭自动 venv。

开发和重构时先跑：

```bash
python -m pytest
```

新增或调整脚本时，至少验证对应脚本的 `--help`。

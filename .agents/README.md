# Workspace Agents

这个目录存放 workspace-oss 的本地 skills 和共享运行库。当前系统围绕 v2 knowledge units 工作；人类可读规则以仓库根目录的 `AGENTS.md` 为准，结构化 artifact 协议以 `.agents/lib/research/SCHEMAS.md` 为准。

## Layout

- `.agents/skills/`: 16 个本地 skill，每个 skill 的触发与职责写在自己的 `SKILL.md`。
- `.agents/lib/research/`: 跨 skill 共享的 v2 Python helper。
- `.agents/lib/research/SCHEMAS.md`: record、program、config、confirmation gate 的共享契约。

## Current Skill Groups

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Analysis: `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`

## Runtime

脚本默认用 `${RESEARCH_PYTHON:-python3}` 运行，并期望该 runtime 可 import PyYAML。开发和重构时先跑：

```bash
${RESEARCH_PYTHON:-python3} -m pytest
```

新增或调整脚本时，至少验证对应脚本的 `--help`。

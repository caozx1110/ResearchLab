# Workspace Agents

这个目录存放 workspace-oss 的本地 skills 和共享运行库。当前系统围绕 knowledge units 工作；安装后的 runtime 规则以 workspace 根 `AGENTS.md`（由本目录的 `AGENTS.md` 分发）为准，结构化 artifact 协议以 `.agents/lib/research/SCHEMAS.md` 为准。

> 本文件是源码 checkout 的目录说明，不进入精简安装包。安装后的 Agent 只依赖受管 `AGENTS.md`、`.agents/AGENT_GUIDE.md`、共享 schema 和各 skill 合同。

## Layout

- `.agents/skills/`: 15 个可发现 skill；14 个 L1 owner 加 `kb-cli` 快捷入口。
- `.agents/lib/research/`: 跨 skill 共享的 Python helper。
- `.agents/lib/research/SCHEMAS.md`: record、program、config、memory、confirmation gate 的共享契约。
- `.agents/AGENTS.md`: 安装后 workspace 的 runtime Agent 规则。
- `.agents/AGENT_GUIDE.md`: runtime Agent 的私有调用与恢复速查。

## Current Skill Groups

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Discovery and tracking: `literature-search`, `research-monitor`
- Analysis: `unit-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `discussion-archivist`, `skill-evolution-advisor`
- Shortcut dispatcher: `kb-cli`

`unit-analyst` 统一持有并路由 paper、repo、dataset、blog 四套 canonical prepare/verify 实现。历史持久 owner identity 继续存在于 record、preference、journal、receipt、provenance 和 diagnostics 协议中，但不再对应独立 skill 目录。

仓库根 `tools/` 下的维护者工具不属于 `.agents/` 发布树，不计入 15 个可发现 skill，也不会复制到安装后的 workspace。

## Runtime

Runtime 会优先复用已兼容的 Python；只有需要时才准备 workspace-local managed environment。普通调用不会向任意 shared interpreter 安装依赖。

精简安装包只包含运行所需文件，不包含本文件、仓库测试、内部审查材料或维护者工具。源码开发与提交门以仓库根 `AGENTS.md` 和 `CONTRIBUTING.md` 为准；不要把本文件当作独立开发手册。

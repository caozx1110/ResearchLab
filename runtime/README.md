# Product runtime source

这个目录存放 workspace-oss 的共享运行库和分发规则源码；15 个产品 skill 位于仓库顶层 `skills/`。安装后的根 `AGENTS.md` 只提供稳定加载指针，最小 runtime 规则来自 `.agents/WORKSPACE_RULES.md`；结构化 artifact 协议源码以 `runtime/lib/research/SCHEMAS.md` 为准。

> 本文件是源码 checkout 的目录说明，不进入精简安装包。安装后的 Agent 只依赖根 `AGENTS.md` 的稳定指针、`.agents/WORKSPACE_RULES.md`、共享 schema 和按需加载的 skill/reference 合同。

## Layout

- `../skills/`: 15 个可发现 skill；14 个 L1 owner 加 `kb-cli` 快捷入口，安装为 `.agents/skills/`。
- `lib/research/`: 跨 skill 共享的 Python helper，安装为 `.agents/lib/research/`。
- `lib/research/SCHEMAS.md`: record、program、config、memory、confirmation gate 的共享契约。
- `AGENTS.md`: 只供根 managed block 使用的稳定加载指针；不复制到 `.agents/`。
- `WORKSPACE_RULES.md`: 最小 always-on runtime 合同；详细流程留在 owner `SKILL.md` 的一跳 references。

## Current Skill Groups

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Discovery and tracking: `literature-search`, `research-monitor`
- Analysis: `unit-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `discussion-archivist`, `skill-evolution-advisor`
- Shortcut dispatcher: `kb-cli`

`unit-analyst` 统一持有并路由 paper、repo、dataset、blog 四套 canonical prepare/verify 实现。历史持久 owner identity 继续存在于 record、preference、journal、receipt、provenance 和 diagnostics 协议中，但不再对应独立 skill 目录。

仓库根 `tools/` 与 ignored `/.agents/` 下的维护者工具不属于产品发布树，不计入 15 个可发现 skill，也不会复制到安装后的 workspace。

## Runtime

Runtime 会优先复用已兼容的 Python；只有需要时才准备 workspace-local managed environment。普通调用不会向任意 shared interpreter 安装依赖。

精简安装包只包含运行所需文件，不包含本文件、仓库测试、内部审查材料或维护者工具。源码开发与提交门以仓库根 `AGENTS.md` 和 `CONTRIBUTING.md` 为准；不要把本文件当作独立开发手册。

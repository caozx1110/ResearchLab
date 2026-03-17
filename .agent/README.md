# Agent Planning

这个目录存放项目级的 agent / skill 规划文件，不是运行时 skill 本体。

当前科研系统的可执行 skill 位于：
- `.agents/skills/`

当前科研系统的共享事实源位于：
- `doc/research/`

本目录中的主要文件：
- `research-skills/blueprint.md`: 人类可读的总体设计蓝图
- `research-skills/registry.yaml`: 结构化 skill 清单
- `research-skills/workflow.md`: 端到端协作流程与文件交接规则

维护原则：
- 先改这里的规划，再改对应 skill 边界或 shared schema
- 运行逻辑以 `.agents/skills/` 和 `doc/research/` 为准
- 如果规划与实现不一致，应在这里记录差异和下一步收敛方向

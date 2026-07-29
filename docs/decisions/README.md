# 设计决策记录

本目录保存 Architecture Decision Record（ADR），解释长期设计选择“为什么这样做”。当前系统“是什么”仍以 [DESIGN.md](../DESIGN.md)、schema、代码和测试为准；GitHub Issue/PR 负责提案、讨论与交付状态，远端接力与按需增强控制见 [GitHub-only 开发工作流](../DEVELOPMENT_WORKFLOW.md)。

## 何时需要 ADR

以下变化应新增 ADR：架构或 canonical ownership、schema/兼容策略、安全与恢复不变量、不可逆外部依赖，或存在多个合理方案且取舍会影响后续交付波次。局部实现细节不需要 ADR，但仍须写入 Atomic Issue。

## 生命周期

1. 从 [_template.md](_template.md) 复制，按本目录下一个四位序号命名为 `<NNNN>-<short-slug>.md`，正文关联 Atomic Issue。
2. `Proposed` ADR 可随 design-only PR 或对应交付 PR review；ready-for-review 的接受候选将状态改为 `Accepted`，但合并前仍不代表 accepted contract。
3. 经非作者人类 review 合入 default branch 后，`Accepted` 状态才生效，并同步 `docs/DESIGN.md` 中的 current design。
4. 不改写已接受决策的历史理由；改变方向时新建 ADR，以 `Supersedes` / `Superseded by` 双向链接替代旧决策。
5. 讨论、验收和证据使用 GitHub permalink 与 exact commit SHA；不得引用本机路径、聊天记录、未 push 内容或私有工具记忆。

ADR 不承载活动任务状态。当前施工阶段、blocker、last remote checkpoint 和下一步始终以 Atomic Issue 的最新状态更新为准。

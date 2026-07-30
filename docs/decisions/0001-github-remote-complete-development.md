# ADR 0001: GitHub 远端完备的开发协作

- Status: Accepted（仅在本 ADR 合入 default branch 后生效）
- Date: 2026-07-29
- Atomic Issue: https://github.com/caozx1110/ResearchLab/issues/8
- Parent Epic: https://github.com/caozx1110/ResearchLab/issues/7
- Decision owners: repository human maintainer
- Supersedes: 本机私有设计/施工工作台与跨会话工具记忆作为开发权威源的旧约定
- Superseded by: N/A

## Context

旧流程把设计草案、backlog、单次施工提示和跨会话经验放在 Git-ignored 或工具私有位置。另一台机器或不同 Agent 即使取得仓库，也无法验证完整设计、活动范围、最新绿色 SHA、阻塞和下一步；未 push worktree 还可能造成静默丢失或多真源。

目标是让任何具备仓库权限、没有旧聊天与本机记忆的 Agent，都能只凭 fresh clone 和 GitHub 远端恢复施工与审查。同时，普通改动不应被为极端并发场景设计的重型状态机阻塞。

## Decision

按事实类型拆分权威源：

- default branch 的代码、schema 和测试描述当前实现；
- `docs/DESIGN.md` 描述当前接受的架构与不变量；
- tracked ADR 记录长期选择的理由与取舍；
- 一个 active Epic 聚合新蓝图的最终目标、依赖与 delivery waves；
- Atomic Issue 定义一个可独立验收/回滚的交付单元，并保存最新远端接力状态；
- remote commit、consolidated PR、GitHub Actions 与人类 review 定义候选、证据和合并结论。

本地 scratch、worktree、stash、未 push commit、聊天、一次性 prompt、Git-ignored 维护者目录与工具/模型私有记忆都只是可丢弃缓存，不得决定需求、范围、进度、验收、冲突或下一步。

采用两级流程：

1. 普通路径只要求 Issue-first、tracked design、remote checkpoint、集成验证、consolidated PR 和人类 merge。
2. 跨 Agent 长期并行、takeover/orphan、安全、复杂迁移、exact-version 外部依赖和发布时，按风险增加 ownership freeze、固定 checkpoint、takeover approval、replacement lineage 或发布审批。

不为普通改动强制手写 comment digest、receipt chain、terminal mirror、authority/assignment 状态机或第二个 GitHub 身份。如果未来需要机器仲裁，必须先通过新 ADR 定义威胁模型，并提供 validator/tooling；不能只靠复杂模板模拟。

## Legacy authority disposition

迁移基线上的 accepted product contract 只包括当时已经存在于 GitHub default branch 的 tracked code、schema、Agent 合同、用户文档和测试。旧本机工作台中的内容不做隐式继承：只在本机出现的 invariant、计划或 finding 视为未接受；若之后发现仍有价值，必须作为新的 GitHub Issue/ADR 提案，以远端证据重新审查。

遗留目录可以为数据安全暂时保留或继续忽略，但开发 Agent 不得读取或回写它们。

## Consequences

- 任意 Agent 可以从 GitHub 恢复目标、范围、last remote SHA、验证、blocker 和 next action。
- 新蓝图多一个 Epic，每个独立 outcome 多一个 Atomic Issue，但普通施工不需要维护自定义分布式协议。
- 并行 track 必须有 disjoint ownership、remote checkpoint 和唯一 integrator；人类仍只 review 已整合的 delivery PR。
- Actions artifact 可能过期，因此 Issue/PR 还要保存候选 SHA、命令/环境和可复现摘要。
- 单账号个人仓库不伪造身份分离：Agent 停止于 PR，由维护者在 GitHub 手动检查并 merge。有独立身份时继续使用 native approval 与 branch protection。
- GitHub 不可用时普通开发停止；若 GitHub 信任本身失守，只有人类 out-of-band 恢复可以建立新 anchor。
- PR merge 不自动授权 tag、release 或 publish；合并后回归走新的 recovery/fix-forward Issue 和 PR。

## Migration and rollback

本变更同步更新根开发合同、贡献指南、tracked design、GitHub Issue/PR 模板、旧私有权威源引用和文档回归门。它不删除真实用户 `kb/` 或本机遗留历史。

本次 bootstrap 已先建立管理 Epic #7 和 Atomic Issue #8，再以一个 consolidated PR 交付。以后所有独立结果都按已合入的轻量 Issue-first 流程执行。

若回滚，使用普通 revert PR 恢复 tracked 合同；不得重新启用本机文件作为权威源。需要替代协作模型时，新 ADR 必须先给出同等的 remote-complete 接力能力。

## Validation

- Fresh-clone Agent 只凭 Epic/Atomic Issue/PR 能复述 goal、scope、last remote checkpoint、blocker 和 next action。
- 每个需要接力的 checkpoint SHA 可从 remote fetch；必要状态不存在于 stash、untracked 文件或本机日志。
- 人类看到的是已集成的 consolidated PR，测试和风险锚定 exact candidate SHA。
- Agent 不 self-merge；actual merge SHA 的 smoke 与 Issue/Epic 收尾可从 GitHub 验证。
- 文档测试拒绝重新引入本机权威源或无法解析的旧私有设计编号。

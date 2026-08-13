---
name: Atomic change
about: 一个可独立验收、拒绝和回滚的施工结果
title: "[Change] "
labels: ""
assignees: ""
---

<!--
Definition of Ready 未满足前不得施工。公开 Issue 不粘贴真实用户数据、
未公开研究、本机绝对路径、token、secret、exploit 或敏感日志。
-->

> 施工与接力规则见 [`docs/DEVELOPMENT_WORKFLOW.md`](../blob/main/docs/DEVELOPMENT_WORKFLOW.md)。

## 管理关系

- Parent Epic：#
- Delivery wave：
- Baseline commit：
- Delivery branch：`codex/issue-<number>-<short-name>`
- Expected consolidated PR：
- Owner / integrator：

## 待解决的问题与证据

<!-- 给出最小复现、当前证据和影响，不只写抽象愿望。 -->

## 期望 outcome

<!-- 一个可独立 accept/reject/rollback 的结果。 -->

## Scope

-

## Non-goals

-

## 设计依据

- `docs/DESIGN.md` permalink @ exact commit：
- ADR/schema/test permalink：
- Blocking decision：`none` / 链接

## 解决思路与接口

<!-- 说明方案、关键接口和不会采用的旁路。Analyzer 必须保持“理解来自 Agent，脚本只建结构/验证/过门”。 -->

## Ownership 与依赖

- Blocked by：
- Blocks：
- Shared interface owner：
- Integration order：

<!-- 仅多 worktree/Agent 并行时填写；普通单分支改动删除此表。 -->

| Track | Remote branch | Owned paths | Owner | Blocked by |
|---|---|---|---|---|
| | | | | |

## 风险、迁移与回滚

- 风险：
- 数据/schema 迁移：
- 回滚/降级：

## 验收待办

- [ ]
- [ ] 相关测试和完整门禁通过
- [ ] tracked 设计/schema/用户文档/CHANGELOG 已按需同步
- [ ] 真实用户知识库/工作区（包括 legacy `kb/` 与 workspace-root 布局）零修改
- [ ] 治理、evidence、恢复和用户输出红线无削弱
- [ ] consolidated PR 已创建并等待人类审查

## 测试与证据计划

| Acceptance item | 命令/方式与环境 | GitHub evidence |
|---|---|---|
| | | Actions、commit、PR 或脱敏 Issue comment |

## Definition of Ready

- [ ] 问题、outcome、scope 和 non-goals 明确
- [ ] Parent Epic/wave、baseline、owner 和预计 PR 已登记
- [ ] 设计依据和 blocking decision 已解决
- [ ] 依赖、接口、owned paths 与整合顺序明确
- [ ] 验收可证伪，测试/证据计划完整
- [ ] 风险、迁移、回滚和公开边界明确
- [ ] 仅凭 fresh clone + GitHub 可开工

## 远端接力状态

<!-- 每次 push checkpoint、handoff 或 blocker 变化时更新本节或追加 Issue comment。 -->

- Stage：`READY|IN_PROGRESS|BLOCKED|PR_READY|MERGED|DONE`
- Last remote checkpoint：branch @ full SHA
- Last validation：
- Blocker / unblock condition：
- Next action / expected actor：

## 增强控制（按需）

<!--
只有跨 Agent 长期并行、takeover/orphan、安全、复杂迁移、外部 exact-version
依赖或发布时填写。说明触发原因，以及采用的 ownership freeze、checkpoint
格式、takeover approval、replacement lineage、dependency digest 或发布审批。
普通改动写 N/A。
-->

- Trigger：`N/A`
- Controls：

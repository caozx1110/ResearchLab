---
name: Initiative / Epic
about: 管理一个蓝图的最终目标、交付波次和全局验收
title: "[Epic:<blueprint-id>] "
labels: ""
assignees: ""
---

<!--
创建前先搜索同 Blueprint ID 的 open Epic。公开 Issue 不粘贴真实用户数据、
未公开研究、本机路径、token、secret 或敏感日志。
-->

> Epic/wave 规则见 [`docs/DEVELOPMENT_WORKFLOW.md`](../blob/main/docs/DEVELOPMENT_WORKFLOW.md)。

## 最终目标

<!-- 一句话说明 Initiative 最终要实现什么。 -->

## 成功指标

- [ ]
- [ ]

## 蓝图与基线

- Blueprint ID：
- Default branch baseline SHA：
- `docs/DESIGN.md` permalink @ exact commit：
- ADR / tracked blueprint permalink：
- Human maintainer：

## Scope

-

## Non-goals

-

## 全局 invariant / 红线

- [ ] 不触碰真实用户知识库/工作区（包括 legacy `kb/` 与 workspace-root 布局）
- [ ] 不削弱确认、evidence、恢复和用户输出合同
- [ ] 公开内容已脱敏，敏感安全问题转 private reporting
- [ ]

## Delivery waves

<!-- 默认 1 Atomic Issue = 1 wave = 1 consolidated PR。 -->

| Wave | Outcome | Atomic Issue | Blocked by | Consolidated PR | Status |
|---|---|---|---|---|---|
| | | # | — | — | planned |

- [ ] #

## 依赖与整合顺序

<!-- 写清 dependency DAG、共享接口和 wave 顺序；无依赖写 none。 -->

## 全局决策

| Decision | Owner | Blocking? | GitHub/ADR permalink | Affected waves |
|---|---|---|---|---|
| | | yes/no | | |

## 风险与总体回滚

- 风险：
- 回滚/降级：

## Definition of Done

- [ ] 每个 active wave 的 current Atomic Issue 已通过验收并由人类合并
- [ ] actual merge SHA 的 CI/smoke 已确认
- [ ] `docs/DESIGN.md`、ADR、schema、用户文档和 CHANGELOG 已按需同步
- [ ] 每个 blocker、限制和后续项都可从 GitHub 找到
- [ ] 无必要事实仅存在于聊天、本机、stash、未 push commit 或私有 memory
- [ ] 全局成功指标全部完成
- [ ] Human maintainer 已确认关闭 Epic

## 收尾记录

- Completed waves / PRs：
- Remaining or follow-up Issues：
- Final validation：
- Closing decision：

---
name: Development workflow governance
about: 按需审查仓库权限、保护规则、CI 或发布设置
title: "[Governance] "
labels: ""
assignees: ""
---

<!--
本模板不是每个普通改动的前置。仅在首次启用、权限/ruleset 变化、安全审计、
CI/merge 策略变化或高风险发布前使用。设置证据必须脱敏。
-->

> 普通与增强控制见 [`docs/DEVELOPMENT_WORKFLOW.md`](../blob/main/docs/DEVELOPMENT_WORKFLOW.md)。

## 触发原因

- [ ] 首次建立 GitHub-only 工作流
- [ ] Branch/ruleset/权限变化
- [ ] CI 或 merge 策略变化
- [ ] 安全审计/事件恢复
- [ ] Release/publish gate
- [ ] 其他：

## 范围与预期结果

- Repository / baseline：
- In scope settings：
- Expected safe state：
- Non-goals：

## 身份与权限

- Human maintainer/admin：
- Agent/PR actor：
- Independent reviewer（仓库具备独立身份时）：
- Release approver（N/A if no release）：
- Settings/API evidence：

- [ ] Agent 不能绕过 default branch 保护
- [ ] Agent 不 self-approve/self-merge
- [ ] 只有一个 GitHub 账号时没有伪造第二身份；Agent 停止，由维护者手动 merge
- [ ] 凭据、私有研究和敏感日志未进入公开 Issue

## Default branch 与 merge

- [ ] Require pull request
- [ ] Required CI checks
- [ ] Require conversation resolution
- [ ] 禁止 force-push/delete
- [ ] Merge 策略和回滚点明确
- [ ] Auto-merge/tag/release/publish 未被本 Issue 隐式授权
- Evidence URL：

## Issue-scoped branches

- [ ] Agent 可以 non-force create/push `codex/issue-*`
- [ ] 来源不明的 remote commit 会 fail closed，不 force-push 掩盖
- [ ] 长期/高风险 track 的保留或删除策略已写入 Atomic Issue
- Evidence URL：

## CI / 测试 PR

- Test PR（若需要）：
- Candidate-head run：
- Pull-request/merge-candidate run：
- Review/merge evidence：

- [ ] 新 push 会触发 required checks
- [ ] Base 或 candidate 变化后必须重新验证
- [ ] 实际 merge SHA 可追踪并可 smoke/revert

## 结论

- Result：`PASS|BLOCKED|FAIL`
- Blocker / owner / next action：
- Known limits：
- Follow-up Issue：

<!-- 不使用 Closes/Fixes/Resolves；merge + post-merge smoke 后再由人类关闭 Issue。 -->

> 交付与 review 规则见 [`docs/DEVELOPMENT_WORKFLOW.md`](../blob/main/docs/DEVELOPMENT_WORKFLOW.md)。

## 关联

- Refs # <!-- Atomic Issue -->
- Refs # <!-- Parent Epic -->
- Delivery wave：
- Baseline SHA：
- Candidate head SHA：
- Delivery branch：

## Outcome

<!-- 这个 PR 交付的一个可独立验收/回滚结果。 -->

## Scope / Non-goals

### Scope

-

### Non-goals

-

## 实现摘要

<!-- 说明集成后的行为、接口和相对 Issue/tracked design 的变化，不逐 commit 复述。 -->

## 并行 track 集成（无并行时写 N/A）

| Track | Remote source @ SHA | Integration commit | Owned files | Evidence |
|---|---|---|---|---|
| | | | | |

- [ ] 全部需要的 track 已进入本 candidate，人类无需拼装分支
- [ ] 共享文件冲突由明确 owner 解决
- [ ] 无必要状态仅存在于 worktree/stash/untracked/未 push commit/本机日志

## 验收证据

| Acceptance item | Result | Command/environment | GitHub evidence |
|---|---|---|---|
| | PASS/FAIL | | Actions、commit、PR 或脱敏 comment |

## 测试与 CI

- Candidate-head Actions run / SHA：
- PR merge-candidate Actions run / base SHA：
- Full/target test summary：
- Cold acceptance（UX/行为变化时）：`N/A` / 链接

- [ ] 相关定向测试通过
- [ ] 完整门禁通过
- [ ] Base 或 candidate 变化后已重新验证
- [ ] 承重 claim 和 review finding 已独立复现

## 安全、治理与数据边界

- [ ] 真实用户 `kb/` 未修改；测试使用隔离临时目录
- [ ] 确认、逐字 evidence、恢复和用户输出合同未削弱
- [ ] Issue/PR 未泄漏真实用户数据、本机路径、token、secret 或未公开研究
- [ ] 无未登记 scope creep；实质变化已先更新 Issue 或改走 replacement
- [ ] Agent 未直推 default、self-approve、self-merge、tag、release 或 publish

## 文档、迁移与回滚

- `docs/DESIGN.md` / ADR / schema / 用户文档 / CHANGELOG：
- 迁移：
- 回滚/降级：
- 已知限制 / 后续 Issue：

## 人类 review gate

- [ ] PR 已是完整集成候选，不是半成品内部分支
- [ ] 所有 required CI checks 通过
- [ ] 所有 review threads 已解决
- [ ] Candidate SHA、测试证据、风险和回滚可从 GitHub 访问
- [ ] 有独立 reviewer 身份时已取得 native APPROVED；单账号仓库则等待维护者手动检查并 merge
- [ ] Agent 当前停在等待人类审查，没有执行 merge

## 合并后收尾（merge 后填写）

- Actual merge SHA：
- Default-branch smoke / Actions：
- Atomic Issue final comment：
- Epic wave updated：

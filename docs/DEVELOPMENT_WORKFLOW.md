# GitHub-only 开发工作流

本协议的目标不是把 GitHub 变成一套自定义分布式数据库，而是让任何 Agent 在没有旧聊天、旧机器和私有记忆的情况下，只凭 fresh clone 与 GitHub 继续工作。

默认使用“普通流程”。只有并发、接管、安全或复杂迁移确实出现时，才升级到“增强流程”。

## 1. 权威源与基本原则

开发事实按以下位置归属：

| 内容 | 权威源 |
|---|---|
| 已接受的设计与边界 | default branch 的 `docs/DESIGN.md` |
| 长期决策与取舍 | default branch 的 `docs/decisions/*.md` |
| 当前实现 | default branch 的代码、schema 和测试 |
| 最终目标与交付波次 | 一个 active Initiative/Epic |
| 单项施工合同与实时状态 | Atomic Issue |
| 候选、测试、审查与合并 | remote commits、PR、Actions |

必须始终满足：

- `dev-docs/`、`codex_prompt_*`、模型/工具私有 memory、聊天、本地 plan、stash、未 push commit 和本机日志都没有协作权威。
- 新蓝图先建或复用一个 Epic；每个可独立验收、拒绝或回滚的结果，开工前建立一个 Atomic Issue。
- 所有需要接力的代码都有 remote commit；本地 worktree 可以随时丢弃。
- 并行施工可以有多个 worktree/branch，但人类只审查集成后的 consolidated PR。
- Agent 不直推 default branch，不 self-approve，不自行 merge、tag、release 或 publish。
- Issue/PR 只写脱敏事实。漏洞、凭据暴露、路径穿越、数据丢失或私有研究材料按 `SECURITY.md` 走 private reporting。

## 2. 普通流程

### 1. 同步并理解当前设计

1. `git fetch`，记录 default branch 的 exact SHA。
2. 阅读 `docs/DESIGN.md`、相关 ADR、schema、代码和测试。
3. 区分 current fact 与 proposed change。Issue 不能静默取代 accepted design。

设计、兼容、安全、恢复或长期 ownership 发生变化时，在 Atomic Issue 中写清提案；承重取舍新增 ADR。局部设计和实现可以在同一 PR 中 review，但合并前仍只是 proposal。

### 2. 建立或复用 Epic

只有以下情况需要新 Epic：

- 新的长期蓝图或最终目标；
- 现有 Epic 已完成、放弃或不再覆盖该目标；
- 目标、成功指标或全局不变量发生实质变化。

创建前先搜索相同 `Blueprint ID` 的 open Epic。Epic 至少写明：

- 最终目标和可验证成功指标；
- exact default-branch baseline 与设计/ADR 链接；
- scope、non-goals、全局红线；
- waves/Atomic Issues、依赖和预计 PR；
- 风险、回滚和 Definition of Done。

Epic 是聚合视图，不复制每个 Atomic Issue 的完整内容。一个 Epic 可以有多个 wave 和 PR。

### 3. 建立 Atomic Issue，过 Definition of Ready

Atomic Issue 描述一个可独立 accept/reject/rollback 的 outcome。默认映射为：

```text
1 Atomic Issue = 1 delivery wave = 1 consolidated PR
```

开工前至少写清：

- 待解决的问题与可复核证据；
- outcome、scope、non-goals；
- 设计/ADR/baseline 链接；
- 解决思路、接口和不采用的旁路；
- 依赖、owner/integrator；
- 风险、迁移和回滚；
- 可证伪的验收 checklist 与测试计划；
- 当前 stage、last remote checkpoint、blocker、next action。

问题、范围或验收不清楚，承重决策未解决，依赖未满足，或并行写集冲突时，Issue 不 Ready，不施工。

### 4. 从 Issue 施工并 push checkpoint

- 分支使用 `codex/issue-<number>-<short-name>`；需要内部并行时再加 `-track-<id>`。
- 从记录的 baseline 建立干净 worktree，不覆盖不明来源的已有工作。
- commit-per-piece。每完成一个可恢复片段就 non-force push，并在 Issue 更新 full SHA、验证结果、blocker 和 next action。
- 无 remote full SHA 的工作不算共享 checkpoint；中断后允许丢弃并重做。
- 发现 scope 或 acceptance 实质变化时先停工、更新 Issue。PR 创建前可在 Issue 留下 scope-change 记录；PR 创建后通常终止旧 PR，并用 replacement Issue/PR 重新冻结范围。

普通单 Agent 改动不需要自定义 comment digest、receipt chain、terminal mirror 或永久审计 ref。GitHub 的 Issue history、commit SHA、PR 与 Actions 是默认审计记录。

### 5. 集成与独立验证

单分支改动直接在 delivery branch 验证。多 track 改动由唯一 integrator：

1. 按依赖顺序合并 remote track heads；
2. 保留清楚的 source SHA 和合并点；
3. 每合入一轨跑相关测试；
4. 全部合入后跑完整/目标验收；
5. 复现承重 claim 和 review finding，不只相信施工 Agent 的总结；
6. 确认真实 `kb/` 未修改，治理与用户输出红线未削弱。

### 6. 创建 consolidated PR

PR 必须已经是人类可整体审查的候选，不把内部分支交给人类拼装。正文至少包含：

- `Refs #<atomic>` 与 `Refs #<epic>`，不使用自动关闭关键字；
- outcome、scope/non-goals 和实现摘要；
- internal track → source SHA → integration commit → owned files 矩阵（无并行时可省略）；
- candidate SHA、测试/Actions 证据；
- 风险、安全/数据边界、迁移和回滚；
- 已知限制和后续 Issue。

Branch push CI 验 candidate head；PR CI 验当前 base 上的 merge candidate。default branch 前进或候选实质变化后，重新同步、测试并请求 review。

### 7. 人类 review 与合并

- Agent 修复 review finding 前先复现。
- 未解决 thread、失败 CI、scope drift 或已知阻断问题都必须处理或明确拒绝，不能静默忽略。
- Agent 在 PR ready 后停止于“等待人类审查”。默认由人类在 GitHub 执行 merge。
- 仓库具备独立 reviewer 身份时，使用 native `APPROVED` 和 branch protection；个人仓库只有一个账号时，不额外伪造第二身份，仍由 Agent 停止、维护者在 GitHub 检查并手动 merge。
- 除非用户在当前消息明确要求代为点击 merge，且所有既有保护和人类审查已满足，否则 Agent 不调用 merge API。

推荐使用普通 merge commit，保留 wave 的集成边界。若仓库明确选择其他 merge 策略，必须仍能从 PR 和 commit history 确定 exact candidate、测试与回滚点。

### 8. 合并后收尾

1. 在 default branch 的 actual merge SHA 上运行或确认 smoke/Actions。
2. 在 Atomic Issue 留下 merge SHA、结果、已知限制和必要后续项。
3. smoke 通过后由人类关闭 Atomic Issue；失败则保持 open，并建立 recovery/fix-forward Issue。
4. 更新 Epic wave checklist；所有 wave 和全局验收完成后关闭 Epic。
5. 设计级事实同步到 `docs/DESIGN.md`，长期取舍同步 ADR，用户可见变化同步文档/CHANGELOG。

## 3. 并行 worktree 规则

并行不是默认要求。只有确实能缩短关键路径且接口已清楚时才开多个 track。

每个 track 必须记录：

- 稳定 `track_id`、负责 Agent 和 remote branch；
- owned paths 或明确接口；
- baseline、blocked by、交付顺序；
- latest remote SHA、测试、blocker 和 next action。

写集必须互斥。共享文件交唯一 owner/integrator，或把共享接口先拆为前置 Issue；不要让多个 Agent 同时修改后再赌冲突解决。内部 track 不单独提交人类 PR，最终由 delivery branch 集成。

## 4. 何时升级到增强流程

出现下列任一情形时，在 Atomic Issue 增加“增强控制”小节：

- 两个以上 Agent 同时写入，且任务跨多个 session；
- claimant 失联、账号变化、需要 takeover 或 orphan recovery；
- 数据/schema 迁移、不可逆外部副作用或高价值发布；
- 安全修复、权限/ruleset 变更或供应链风险；
- 多仓库/外部依赖必须绑定 exact version；
- Issue/PR 生命周期超过一周且交接频繁。

按风险选用以下控制，不要求全部启用：

| 风险 | 增强控制 |
|---|---|
| 并行争用 | frozen ownership table、唯一 integrator、每轨 remote checkpoint |
| 长期接力 | 固定 checkpoint comment 格式、last-green SHA、明确 next actor |
| Takeover | 原 claimant release 或维护者批准的 takeover comment；记录接管 base SHA |
| Scope 切换 | scope-change/replacement 记录、旧分支停止写入、新 baseline |
| 外部依赖 | exact commit/version/digest 与重新验证结果 |
| 安全事件 | private advisory、最小 containment、维护者恢复信任后再走 PR |
| 发布 | protected environment、独立审批、可回滚 artifact/version 记录 |

如果团队以后需要机器仲裁，再通过独立 ADR 和工具化验证引入结构化 receipts；不要靠长篇手写 YAML 模拟一个没有 validator 的协议。

## 5. 恢复与异常

### GitHub 不可用

普通交付停止 claim、handoff、push、PR 和 merge。允许只读诊断和可丢弃本地草稿，但不得宣称共享进度。恢复后从最新 remote SHA 重新核对，并把需要保留的事实写回 Issue。

### GitHub 信任失守

若怀疑账号、仓库、ruleset 或 commit trust 失守，停止 push/merge，不把敏感详情写入公开 Issue。只由人类通过可信的 out-of-band 渠道恢复权限和基线。

### Claimant 中断

- 有可用 remote checkpoint：新 Agent 在 Issue 留 takeover 记录，从该 SHA 继续。
- 只有未 push 工作：按不存在处理，可从 last remote checkpoint 重做。
- remote branch 出现来源不明的 commit：先停，由维护者确认，禁止 force-push 掩盖。

### 合并后回归

不改写 default history。建立新的 recovery/fix-forward Atomic Issue 和 PR；原 Issue 记录关联关系与最终处置。

## 6. 最小检查清单

开工前：

- [ ] 找到唯一相关 Epic，或确有理由新建
- [ ] Atomic Issue 的问题、范围、方案、验收和依赖已 Ready
- [ ] baseline、branch、owner 和 next action 清楚

提交 PR 前：

- [ ] 所有必要 commit 已 push，候选可从 GitHub fetch
- [ ] 多 track 已集成，人类无需拼装
- [ ] 相关测试、完整门禁和文档同步完成
- [ ] PR 记录 candidate SHA、证据、风险和回滚
- [ ] 真实 `kb/` 零修改，公开内容已脱敏

合并前后：

- [ ] 人类已审查，所有 thread 与 CI 满足仓库规则
- [ ] Agent 未 self-merge
- [ ] actual merge SHA 的 smoke/Actions 已确认
- [ ] Atomic Issue/Epic 和 tracked 文档已收尾

# AGENTS.md — 开发本 skill 系统的工作流

> 本文件面向在本仓库开发/演进 skill 系统的 Agent。`CLAUDE.md` 是指向本文件的软链。
> 安装后执行知识库操作前加载 `.agents/WORKSPACE_RULES.md`；缺失或不可读时停止写入并通过可信安装源恢复。

本仓库采用 GitHub-only 协作：**tracked 设计 → Epic（新蓝图才建）→ 原子 Issue → branch/worktree 施工并 push → 集成验证 → consolidated PR → 人类审查合并 → 远端收尾**。

普通改动走下面的轻量流程；并发接管、安全事件、复杂迁移或高风险发布才按 [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md) 升级控制。

## 权威源

| 内容 | 权威源 |
|---|---|
| 当前接受的设计、架构和边界 | `docs/DESIGN.md` |
| 长期决策与取舍 | `docs/decisions/*.md` |
| 当前实现与数据模型 | default branch 的代码、测试、`runtime/lib/research/SCHEMAS.md` |
| 新蓝图的最终目标和 waves | GitHub Initiative/Epic |
| 单项范围、方案、验收和接力状态 | GitHub Atomic Issue |
| 候选、CI、review 与合并 | remote commits、PR、Actions |
| 用户可见行为、迁移与发布 | `README.md`、用户文档、`CHANGELOG.md` |

另一个没有聊天上下文的 Agent，只凭 fresh clone 与 GitHub，必须能确定当前设计、活动 Issue、last remote checkpoint、验证结果、blocker 和 next action。

`dev-docs/`、`codex_prompt_*`、`~/.claude/.../memory/`、其他模型/工具私有记忆、聊天、本地 plan、stash、未 push commit 和本机日志均已弃用为协作权威。它们即使存在也不得被读取、创建、更新或引用来决定需求、范围、进度、验收或下一步；只存在于这些位置的信息按不存在处理。

Issue/PR 是公开记录，只写脱敏事实。漏洞、凭据暴露、治理绕过、路径穿越、数据丢失或私有研究材料按 `SECURITY.md` 走 private reporting。

## 产品源码、安装态与本地工具边界

本仓库把三类内容物理分开：

- `skills/` 是 15 个 shipping skill 的 tracked 产品源码；`runtime/` 是共享库和安装后规则的 tracked 产品源码。它们是普通代码，不是当前开发任务自动加载的执行规则。
- 根 `/.agents/` 已被 Git 忽略，只供维护者安装自用 skill 或本地工具。这里的工具可以按正常适用规则辅助开发，但它们不是产品、release input、设计依据或验收证据，也不得与 shipping inventory 混算。
- 安装器把 shipping `skills/**` 与 shared runtime payload 映射到外部 workspace 的 `.agents/**`，并只用 `runtime/AGENTS.md` 维护 workspace 根 `AGENTS.md` 的稳定加载指针；安装后由该指针加载 `.agents/WORKSPACE_RULES.md`，再按任务加载 installed skills。

不得调用 `skills/*/SKILL.md` 来决定其自身需求、设计或验收；可以把这些 `SKILL.md`、脚本和协议当普通代码阅读、检索和测试。只有明确的行为测试、全新上下文冷验收，或用户明确要求测试某个 shipping skill 时，才可在隔离临时目录调用；不得触碰真实用户知识库/工作区（包括 legacy `kb/` 与 workspace-root 布局），也不得把 skill 自述当独立证据。开发态服从本文件、tracked design/ADR/schema、当前 Epic/Atomic Issue、remote commit、PR 和 Actions。

## 普通工作流

### 1. 同步并读设计

- Fetch default branch，记录 exact baseline SHA。
- 阅读 `docs/DESIGN.md`、相关 ADR、schema、代码和测试，区分 current fact 与 proposal。
- 架构、兼容、安全、恢复或长期 ownership 变化要写 ADR；局部设计可与实现同 PR review，但合并前仍是 proposal。

### 2. 建立管理起点

- 新蓝图先搜索相同 `Blueprint ID` 的 open Epic；零个才创建，多个冲突时停止并请人类消歧。
- Epic 写最终目标、成功指标、baseline/设计链接、scope/non-goals、waves、依赖、风险、回滚和全局 DoD。
- 已有 Epic 能覆盖当前目标时直接复用，不为每次小改动重复建大 Issue。

### 3. 开原子 Issue，Ready 后再施工

一个 Atomic Issue 定义一个可独立 accept/reject/rollback 的 outcome。默认：

```text
1 Atomic Issue = 1 delivery wave = 1 consolidated PR
```

开工前写全：问题与证据、outcome、scope/non-goals、设计依据、解决思路、依赖/owner、风险/迁移/回滚、验收 checklist、测试计划，以及 `stage / last remote SHA / blocker / next action`。

问题、范围或验收不清，承重决策未解决，依赖未满足，或并行写集冲突时不得开工。施工中发生 scope/acceptance 实质变化，先暂停并更新 Issue；PR 已创建后通常使用 replacement Issue/PR，不让旧 PR 静默膨胀。

### 4. Branch/worktree 施工并 push

- 分支默认 `codex/issue-<number>-<short-name>`；内部并行 track 可追加 `-track-<id>`。
- 从 Issue 记录的 baseline 建立干净 worktree，不覆盖来源不明的工作。
- 小步 commit；每个需要接力的 checkpoint 都 non-force push，并在 Issue 更新 full SHA、验证、blocker 和 next action。
- 没有 remote full SHA 就不算共享进度；本地 worktree 随时可以丢弃。
- 绝不直推/force-push default branch，不自行 tag、release 或 publish。

### 5. 集成并独立验证

- 单分支直接验证；多 track 必须有 disjoint owned paths、明确接口和唯一 integrator。
- 共享文件交唯一 owner，或抽成前置 Issue/串行处理；不要并行竞写。
- internal tracks 都 push，按依赖顺序进入 delivery branch；人类不负责拼装分支。
- 每合入一轨跑相关测试，全部集成后跑目标/完整门禁。
- 不只信施工 Agent 总结：复现承重 claim、bug 和 review finding 后再修改。
- 确认真实用户知识库/工作区（包括 legacy `kb/` 与 workspace-root 布局）零修改，确认/evidence/恢复/用户输出红线没有削弱。

### 6. 提交 consolidated PR

- PR 使用 `Refs #<atomic>` 和 `Refs #<epic>`，不使用自动关闭关键字。
- 写清 outcome、scope/non-goals、实现摘要、candidate SHA、测试/Actions、风险、回滚、已知限制和后续项。
- 有并行 track 时列出 `track → source SHA → integration commit → owned files → evidence`。
- Branch push CI 验 candidate head，PR CI 验当前 base 上的 merge candidate；base 或候选变化后重跑。
- PR ready 后 Agent 停在等待人类审查，不自行 approval/merge。

### 7. 人类 review 后合并

- 所有 CI、review thread 和 tracked 文档同步满足仓库规则后，由人类在 GitHub 合并。
- 有独立 reviewer 身份时使用 native `APPROVED` 和 branch protection；个人仓库只有一个账号时不伪造第二身份，Agent 仍必须停止，由维护者手动检查并 merge。
- 只有用户在当前消息明确要求代为点击 merge，且既有审查/保护已满足时，Agent 才可执行；该授权不替代人类审查。

### 8. 合并后收尾

- 确认 default branch actual merge SHA 的 smoke/Actions。
- Atomic Issue 记录 merge SHA、结果、限制和后续；smoke 通过后由人类关闭。
- 更新 Epic wave；全部 wave 和全局验收完成后关闭 Epic。
- 设计级事实同步 `docs/DESIGN.md`，长期取舍同步 ADR，用户变化同步文档/CHANGELOG。
- 回归走新的 recovery/fix-forward Issue 和 PR，不改写 default history。

## 何时使用增强控制

以下情况才在 Issue 增加 frozen ownership、固定 checkpoint 格式、takeover approval、replacement lineage、exact dependency digest 或发布审批：

- 多 Agent 跨 session 并行；
- claimant 失联、账号变化、orphan branch 或 takeover；
- 数据/schema 迁移、不可逆外部副作用；
- 安全修复、权限/ruleset 或供应链变更；
- 多仓库 exact-version 依赖；
- 高价值 release/publish。

具体升级与恢复方法见 tracked protocol。普通改动不要求手写 digest chain、terminal ref、authority/assignment 状态机；如果未来需要机器仲裁，应先通过 ADR 和 validator 工具化。

GitHub 不可可靠读写时，普通施工、claim、handoff、push、PR 和 merge 全部停止；只允许只读诊断和可丢弃草稿。若 GitHub 信任本身失守，停止所有写入，由人类通过可信的 out-of-band 渠道恢复 anchor。

## 产品不变量

- 理解来自 Agent；脚本只搬运、建结构、验证和过门。
- 每条判断挂逐字 evidence；`raw/` 与全量 parse cache 是不可变派生证据。
- 确认门拒绝空壳、禁止自签，判断类必须有 evidence；ConfirmationReceipt 绑定内容/evidence digest，内容变化自动失效。
- 入库后 Agent 一回合自动驱动，只在确认 AI 判断和用户抉择两个治理闸口停。
- 用户可见输出只含自然语言与 `kb <verb>` 伪 CLI，不泄漏裸命令、flags、环境变量、内部路径或 TTY 前置。
- 恢复保持原子写、operation journal、锁、revision/CAS 和精确 checkpoint；绝不 `git add -A`。

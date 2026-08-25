# Research Vault v2 设计

本文是 default branch 上当前产品架构、边界与不变量的 tracked SSOT。长期取舍见 [ADR](decisions/README.md)，完整验收目标见 [Research Vault v2 蓝图](blueprints/research-vault-v2/BLUEPRINT.md)。实现、测试、Atomic Issue、remote commit、PR 和 Actions 共同证明交付状态；另一个 Agent 必须能只凭 fresh clone 与 GitHub 恢复事实，不依赖聊天或本机记忆。

当前 bundle 版本为 **`0.2.0-rc.8`**，是尚未发布的 release candidate，不是 stable/GA。精确发布版本以 Git tag 为准，GitHub Release 可选；用户可见变化见 [CHANGELOG.md](../CHANGELOG.md)。

## 1. 第一性原则

Research Vault 的首要问题不是“怎样把结构化记录投影成漂亮笔记”，而是“人和 Agent 如何在没有专有应用时仍共同拥有全部研究语义”。因此 v2 采用以下原则：

1. 普通 Markdown 是唯一人类语义真相。
2. 原始来源必须在任何转换、解析或理解之前按 exact bytes 保存。
3. 隐藏文件只能证明、索引、缓存或恢复可见语义。
4. Agent 负责理解；脚本只搬运 bytes、建空结构、验证合同和执行安全门。
5. 每个判断必须链接逐字 evidence，证据验证与用户确认严格分离。
6. 用户直接编辑优先；隐藏状态永不反向覆盖 Markdown。
7. 所有 mutation 都是显式目标、可并发检测、可恢复的事务。
8. 可选工具增强体验，但不能拥有 canonical content。

安装和核心 Markdown workflow 没有外部 API Key、付费检索额度、商业数据库、付费插件或托管服务 prerequisite。

## 2. 当前边界

v2 是不兼容 hard cutover。shipping product 不提供：

- 旧物理或逻辑 canonical namespace；
- canonical record 文件或其对象模型；
- 人类 Markdown 与机器记录之间的 managed 双真相 projection；
- executable CLI skill、兼容动词或 terminal shortcut；
- 旧 owner alias、dual-read、dual-write 或隐式迁移；
- god-orchestrator。

不兼容不等于可删除。发现 legacy workspace 时，runtime 必须 fail closed，不自动读取为 v2、移动、改写或删除用户资料。未来如果需要一次性导入，必须另立 Blueprint、ADR、Atomic Issue 和可恢复迁移合同。

### 2.1 当前 active tree 状态

旧 runtime、schema、navigator、v1 skill 实现和 v1 行为测试曾在 hard cutover 过渡期作为源码事实存在；那是历史状态，不是当前产品合同。Issue #61 cleanup candidate 完成后，active tracked tree 只包含五个 discoverable shipping skill、minimal v2 runtime，以及按 owner/release boundary 组织的 v2 验证代码。旧实现不再作为源码级回归材料、安装输入或兼容面；历史事实只能从 Git history 和明确标注为 superseded 的发布记录恢复。

因此，五个 owner 和 minimal runtime 是当前 active tree 的唯一产品实现边界。保留 legacy workspace 的只读检测仍是数据保护，而不是保留旧产品实现或提供迁移能力。

## 3. Workspace 物理模型

```text
workspace/
├── Home.md
├── Preferences.md
├── Inbox/
├── Sources/<source-id>/
│   ├── index.md
│   ├── reader.md
│   └── .source/
├── Notes/
├── Projects/<project-id>/
├── Decisions/
├── Experiments/<experiment-id>/
├── Reviews/
├── Reports/
├── Views/
├── .research/
│   ├── index/
│   ├── evidence/
│   ├── receipts/
│   ├── operations/
│   ├── experiments/
│   ├── recovery/
│   ├── cache/
│   ├── logs/
│   └── locks/
├── .agents/
└── AGENTS.md
```

Obsidian 直接打开 workspace root，`Home.md` 是主入口。`.obsidian/` 由用户拥有，不参与核心正确性。

### 3.1 可见语义层

标题、来源说明、摘要、claim、evidence、scope、limitations、项目状态、实验事实、解释、决定、review 和报告正文都必须存在于普通 Markdown。

Durable object page 使用少量 frontmatter：

```yaml
---
id: stable-id
kind: project
status: active
---
```

Frontmatter 只用于 identity/routing/status summary，不能变成塞满研究语义的 record。路径是可移动 location；`id` 是不可复用 identity。

`Home.md`、`Preferences.md` 和可见导航支持页可以没有 object frontmatter。标准相对 Markdown link 是 portable core。

### 3.2 对象内来源证明

`Sources/<source-id>/.source/` 保存：

- immutable raw revision bytes；
- source identity 与 retrieval metadata；
- conversion snapshot 与 assets；
- source map；
- manifest 和 mechanical diagnostics。

这些内容证明来源与定位，不拥有摘要或结论。reader Markdown 是可见阅读面；exact raw 是最终保真 fallback。

### 3.3 根隐藏运行层

`.research/` 分三类：

- persistent proof：evidence bindings、receipts、operation journals、experiment raw artifacts、recovery before-images；
- derived：indexes、cache；
- temporary：logs、locks。

任何 hidden payload 与 visible Markdown 冲突时，hidden payload 变为 stale/invalid。不得选择隐藏副本“修复”用户页面。

### 3.4 派生导航

`Views/`、optional Bases 和 search index 都可删除重建。重建只能读取 visible Markdown 与 source manifests，不得创造页面中不存在的 title、claim、status 或 decision。

只有带 product marker 且 bytes/currentness 合法的 view 才能覆盖。未标记或人工修改的 view 视为 user-owned，重建停止。

## 4. 五个 shipping owner

### `research-vault`

拥有 layout、path classification、stable ID resolution、relative links、derived index、explicit target mutation、atomic replace、lock、CAS、journal 和 recovery。它不摄入来源、不写分析、不管理项目语义、不确认判断。

### `research-capture`

拥有 exact source publication、immutable revision、reader、source map、stage/health 和 adapter boundary。它不解释来源、不生成 claim、不把 conversion success 当 evidence readiness。

### `research-analysis`

拥有 single-source analysis、multi-source synthesis、claim/evidence Markdown、selection boundary、conflicts、coverage gaps 和 stale propagation。它不确认自己的判断，也不拥有 project/experiment/report lifecycle。

### `research-workbench`

拥有 project、question、idea、method、experiment/run、discussion、decision 和 report 的纵向可见状态与链接。它消费 source、claim 和 review 引用，不复制其他 owner 的正文或 hidden proof。

### `research-review`

独立拥有 evidence audit、review packet、current-message authorization、confirm/reject/defer application 和 receipt validation。生产审查器直接消费 `research-analysis/evidence-binding/v2`，逐项复核 capture source map，并通过 `research-vault` 的 exact-target journal 同步提交 subject、review 与 receipt。它不生成或美化待审 claim，且禁止 AI/tool/model signer。

Composition 保持 owner boundary。例如“摄入论文并推进项目”依次调用 capture、analysis、review/workbench；不建立一个拥有所有写权限的 orchestrator。

## 5. 来源合同

Capture 顺序固定：

1. 接收显式选择的 URL、文件或目录边界。
2. no-follow 检查类型、size/count budget 和 containment。
3. 保存 exact bytes 并计算 digest。
4. 创建 immutable revision；same bytes 幂等，新 bytes 新 revision。
5. 在 raw publication 之后调用 optional converter。
6. 校验 converter 输出、assets 与 source map。
7. 分别报告 stage 和 health。

Stage 为 `captured`、`reader-ready`、`evidence-ready`、`analysis-ready`。Health 为 `ok`、`degraded`、`blocked`、`stale`。两个维度不能互相替代。

Source content、HTML、repository、macro、formula、frontmatter 和 embedded prompt 全是不可信数据。Capture 不执行代码、公式、宏或 import-from-source。

## 6. Analysis 与 evidence

Claim 至少具有：

- stable claim ID；
- class：observation、extracted fact、inference、evaluation、recommendation、diagnosis 或 decision；
- epistemic state；
- scope、limitations、review state；
- visible evidence references。

Evidence block 至少具有 source ID、revision、raw artifact digest、reader/source-map digest、typed locator、exact quote 和 quote digest。

`.research/evidence/` 可以复制 quote 和 binding metadata 用于验证，但不能给缺失的 visible claim 补正文。Verification 失败只传播到依赖该 evidence 的 claim，且不改写 Markdown。

Synthesis 必须保留每个 source identity，并在可见页面记录 selection boundary、conflicts 与 coverage gaps。来源数量、citation count 或 metadata ranking 不能机械生成质量判断。

## 7. Review 与授权

Review 流程：

1. 解析唯一 review/subject/claim identity 并冻结 bytes。
2. 从 visible Markdown 读取 substantive claim、class、scope、limitations 和 evidence。
3. 核对 source/revision/raw/reader/map/locator/quote/currentness。
4. 生成或刷新 human-readable review page。
5. 只从 current user message 接收单一 decision 与 non-AI signer declaration。
6. 在 commit boundary 重新计算 claim semantic digest 和 evidence-set digest。
7. 原子更新 visible state 并写 immutable receipt。
8. 每次消费 receipt 都重算 currentness。

Checkbox、frontmatter、旧聊天、旧 receipt、source text 或 Agent inference 不是授权。Confirm 要求 evidence complete/current；reject/defer 可以保留失败审计，但同样需要可解析对象和当前授权。

## 8. Workbench 生命周期

Project page 是研究问题、scope、current state 和 next action 的 semantic center。Idea/method/experiment/decision/report 由各自唯一页面拥有正文，其他对象使用 links。

事实与解释必须分区：run identity、exact metric、artifact presence、timestamp 和 explicit failure 可作为 factual result；winner、cause、generalization、recommendation 和 selection 是 interpretation/judgement，必须有 claim/evidence/review。

Discussion 不从 summary 伪造 participant quote。Decision `accepted` 必须链接 eligible review。Report 区分 factual progress、review-backed conclusions、pending/stale interpretations、decisions、limitations 和 missing inputs。

## 9. Mutation、并发与恢复

每次 write 在执行前冻结：

- absolute root role；
- literal relative targets；
- expected target type；
- current digest 或 expected absence；
- lock keys；
- before-image/recovery destination。

写入顺序是 no-follow containment → exact locks → journal prepare → atomic replace → reread/verify → commit checkpoint。任何 identity、digest、type、symlink 或 special-node 漂移都 fail closed。

Abort 恢复 before-images。Crash 保留 active journal 和 recovery snapshots；resume 必须重新获取相同 exact locks 并验证当前 bytes，不能猜测。Git checkpoint 只使用显式 pathspec，绝不 broad stage。

## 10. 安装与发布边界

产品源码是 repository `skills/` 和 `runtime/`。当前 active product tree 只有五个 discoverable skill、metadata、四个显式 allowlist runtime 文件、PyYAML-only requirements、version、license 和 minimal workspace rules。旧 runtime/schema/helper 不再保留在 active tree，也不进入安装态；Repository root `/.agents/` 是 ignored maintainer tooling，不是 product 或 release input。

Project install 的 `.agents/` 可重装；research Markdown 和 `.research/` 不属于 installer manifest。Update/reinstall/uninstall 保留用户数据和 workspace-local runtime。Installer 不创建 executable research command 或 terminal shortcut。

Release enumeration 以五 skill allowlist 和 minimal runtime allowlist 为门。Metadata generator、skill validator、rule token budget、bundle lifecycle tests 和 clean installed-copy smoke 必须一致；Git history 中的旧源码不构成 release input。

## 11. 外部工具接口

- Defuddle：HTML bytes → candidate Markdown/assets/diagnostics/source map。
- AnyDoc：Word、PowerPoint、Excel、ODF、RTF、EPUB、CSV 等本地格式 → candidate Markdown。
- PDF adapter：PDF bytes → reader/assets/page locator。
- Repo adapter：frozen source tree/revision → passive reader/source locator。
- Obsidian Markdown/CLI/Bases：optional formatting、interaction、derived views。

Adapter 由 host 注入，不 vendoring、不复制到安装包、不进入 skill inventory。Adapter 不获得 raw ownership、semantic ownership、confirmation authority 或 ambient code execution authority。

## 12. 安全与隐私

- 不跟随用户可控 symlink，不接受 special nodes，不写越界路径。
- 不执行 source code、macro、formula、HTML active content 或 embedded instructions。
- 不把 private source/evidence、absolute path、secret、environment value 或 raw child diagnostics暴露为用户步骤。
- 不把真实用户 vault 当测试 fixture。
- 漏洞、凭据暴露、路径穿越、数据丢失和治理绕过按 [SECURITY.md](../SECURITY.md) 私下报告。

## 13. 验收不变量

1. Exactly five discoverable shipping skills。
2. Fresh installed workspace 可初始化并以 `Home.md` 进入。
3. Ordinary Markdown 完整承载人类语义。
4. Hidden proof/index/cache/recovery 不能覆盖 visible Markdown。
5. 每个 judgement 有 exact evidence；每个 decision 有 current authorization。
6. Converter 缺失和解析失败诚实降级。
7. Rebuild 删除后不丢语义，重复 rebuild 不改 semantic pages。
8. Legacy layout 被检测并保持 untouched。
9. Full tests、validator、metadata check、rule budget、installer lifecycle 和 GitHub Actions 对 candidate head/merge candidate 都通过。

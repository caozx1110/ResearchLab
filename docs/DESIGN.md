# 设计说明

本文面向想理解或扩展系统的开发者。它是 default branch 上当前设计意图、架构边界和系统不变量的 tracked SSOT；具体 on-disk 字段和枚举以 [SCHEMAS.md](../runtime/lib/research/SCHEMAS.md) 为准，长期设计取舍见 [决策记录](decisions/README.md)。

拟议变更先进入 GitHub Epic/Atomic Issue；会影响长期架构、兼容、安全、恢复或 ownership 的取舍还须形成 tracked ADR。只有经人类 review 合入 default branch 的设计/ADR 才是 accepted contract，未合并分支上的内容仍是 proposal。活动范围、接力状态、候选 SHA、证据与 review 只存在于 GitHub Issue/PR/remote commits/Actions，不能由本机文件或聊天上下文补全；普通交付、按需增强控制与恢复规则见 [GitHub-only 开发工作流](DEVELOPMENT_WORKFLOW.md)。

## 目标与非目标

Open Research Workspace Skills 是 knowledge-unit-first 的 research operating system。聊天是交互界面，不是状态存储：

1. 外部材料进入不可变 source 与完整 parse cache；
2. paper、repo、dataset、blog、idea、experiment 和 concept 成为 typed knowledge unit；
3. program 保存问题、证据请求、决策、设计、实验和报告事件；
4. synthesis 保存跨 unit 的 survey、taxonomy、trend 和 gap；
5. `kb/user/` 从 canonical 数据生成，供人复开。

系统不把脚本当作理解模型。脚本只负责搬运、建填充结构、机器验证和过门；材料理解由 runtime agent 完成。任何“给材料、没有 Agent 就直接吐出判断”的实现都不属于 analyzer 层。

## 分发边界

新建并显式初始化的 dedicated workspace 采用 workspace-root 物理布局；安装面、用户入口和 canonical 数据共享 workspace 边界，但由不同 owner 与 target class 隔离：

```text
source checkout                    initialized workspace
├── skills/                        ├── .agents/          # product + WORKSPACE_RULES
│   └── <15 product skills>/       ├── AGENTS.md         # user-owned + managed block
├── runtime/                       ├── config/
│   ├── AGENTS.md  # root pointer  │   └── workspace-layout.yaml
│   ├── WORKSPACE_RULES.md          ├── units/ programs/ synthesis/
│   └── lib/research/              ├── raw/ user/ output/ obsidian/
├── .agents/  # ignored local      ├── .journal/ .runtime/
├── AGENTS.md                      └── .git/             # optional KB history
└── docs/
```

仓库根 `AGENTS.md` 是开发这套 skill 系统的工作流。`runtime/AGENTS.md` 只提供安装器写入根 managed block 的稳定加载指针；`runtime/WORKSPACE_RULES.md` 映射为安装态 `.agents/WORKSPACE_RULES.md`，是最小 always-on runtime 合同。安装态不再复制 `.agents/AGENTS.md`，也不分发 eager `AGENT_GUIDE.md`。根 `/.agents/` 只放 ignored 本地工具，绝不进入产品 inventory、release enumeration、digest 或安装 payload。开发规则、根指针、安装规则与本地工具四者不可混写。

Release bundle 不包含任何私有 canonical workspace 数据。安装、更新、storage sync 和卸载只处理各自声明的 managed targets；`units/`、`programs/`、`raw/` 等数据面以及 legacy `kb/` 都不是发布内容，storage sync 不改 `.agents/**` 或根 `AGENTS.md`。

### Workspace/data-root runtime 合同

[ADR 0004](decisions/0004-workspace-root-canonical-data-and-logical-artifact-namespace.md) 将 workspace/integration root、canonical data root 与 product bundle root 定义为三个显式角色。当前 runtime 只在 `config/workspace-layout.yaml` 为 byte-canonical `research-workspace-layout/v1 + workspace-root` 时，把 dedicated workspace 根解析为 physical data root；`.agents/**` 仍是 ignored、可重装的产品面。只有显式 `kb init` 可以在通过零写 collision preflight 的新 workspace 创建 marker；其他 mutation 在 marker 缺失、未知或身份漂移时一律先拒绝。

现有 `<workspace>/kb/`、无 marker 的 Git repository、partial canonical tree、unknown sibling、symlink 与 special node 不会被猜测或自动转换。普通 install/update/reinstall 也不迁移数据。Wave 4 development candidate 提供只读 legacy detector 与 owner-only、receipt-bound plan/apply/rollback：只有 `eligible-legacy`、clean、同文件系统且当前消息明确授权的 dedicated workspace 可迁移；outer Git、collision、dirty/incomplete journal、linked worktree、symlink、special node 或 stale receipt 一律在业务写入前拒绝。完整流程见[迁移指南](MIGRATE_KB_TO_WORKSPACE_ROOT.md)。

Persisted `kb/...` 是稳定 logical artifact namespace，不再等同于物理目录前缀。同一 ref 在 legacy layout 映射到 `<workspace>/kb/...`，在 root layout 映射到 `<workspace>/...`，reverse mapping 必须保持 bytes 不变；record、history、evidence、receipt 与 survey/report bindings 不因物理迁移批量重写。

Root layout 采用 reviewed canonical top-level allowlist；`.journal/`、`.runtime/` 单独分类为 operational state。`.agents/**`、`.git/**`、`.venv/**`、`.claude/**`、根 `AGENTS.md`、`CLAUDE.md` 与 `bin/**` 是 reserved integration targets，不能成为 business mutation、journal snapshot、strict-reader artifact 或普通 Git checkpoint pathspec。未知 top-level、traversal、absolute path、symlink ancestor/leaf 与 special node 全部 fail closed。根 `AGENTS.md` 仍可由用户选择进入 workspace Git history，但 installer 只可维护稳定 pointer block，业务 owner 不得写它。

`path_contract.py` 提供 typed roots、logical/physical conversion、classification 与只读 no-follow precondition；`workspace_layout.py` 独占 marker activation、解析、currentness 与最小规则身份门。journal、Git、strict reader 与 shipping owner 统一消费 root-role resolver，并在 descriptor、lock 或 commit boundary 重验身份；journal key 保持 data-root-relative，持久 artifact identity 保持 `kb/...`。Wave 3 已收敛根 pointer、最小 `WORKSPACE_RULES` 与 progressive disclosure。Wave 4 migration 先冻结 canonical tree、Git HEAD/ref/tree/index、move inventory 与 root integration receipts，在独占 lock 内创建同级私有恢复材料、移动 Git/allowlisted entries、合并 anchored ignore、写 marker 并创建以原 HEAD 为直接父提交的普通 migration commit；失败按 stage 恢复，无法证明完整时保留唯一材料并停止。成功后的显式 rollback 使用新的当前消息授权、精确 receipt、普通 reverse commit 与反向移动，不改写历史。

根 pointer 不承载业务、诊断或恢复全文。若最小规则缺失、为空、被换成 symlink/special node 或读取期间身份漂移，公共 dispatcher 和所有 mutation transaction 都在 journal/business write 前拒绝；只保留零写的 `kb help` 与 `kb doctor` 救援面，直到重新安装修复。

任何本地 scratch、worktree、提示词或工具记忆都不属于 Git 或 release bundle，也不属于开发合同。另一个 Agent 必须能只凭 fresh clone 与 GitHub 上的 tracked contracts、Issue、PR、remote commits 和 Actions 恢复任务；未 push 或仅本机可见的状态按不存在处理。

安装与管理员自动化是产品唯一的技术 bootstrap 面。安装完成后，普通用户的 runtime 合同只有自然语言与 16 个 `kb <verb>` 伪 CLI；内部 flags、scripts、环境变量和 paths 只属于 Agent 私有协议或管理员参考，不得变成日常使用前置。

## Skill 路由

发布树包含 **15 个可发现 skill：14 个 L1 owner + `kb-cli`**。四类 unit analyzer 的发现、路由与 canonical 脚本资源统一归 `unit-analyst`；历史持久 owner identity、canonical artifact identity 与数据模型保持不变，四个旧 skill 资源目录不再分发：

| 分组 | Skills |
|---|---|
| Governance and routing | `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator` |
| Discovery | `literature-search` |
| Ongoing tracking | `research-monitor` |
| Analysis | `unit-analyst`（统一持有并路由 paper/repo/dataset/blog implementation）, `literature-synthesizer` |
| Creation and execution | `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author` |
| Navigation and meta | `discussion-archivist`, `skill-evolution-advisor` |
| Conversational shortcut | `kb-cli` |

路由原则：

1. 用户自然语言优先，不需要记住 skill 名；
2. canonical artifact 只有一个 owner，薄入口不复制业务逻辑；
3. `research-orchestrator` 管 program state、open question、evidence request、decision 和 reporting event；
4. `kb-cli` 只暴露 16 个公开动词；业务 owner 继续拥有 canonical 写入，`obsidian` 只调用可重建的派生投影；
5. 泛化 wiki 意图由 `kb-cli` 薄路由；maintainer-only navigator 位于 `tools/`，不进入安装包或产品路由；
6. 确定性的共同行为下沉到共享库，Agent 理解留在 runtime；
7. 每个可发现 skill 的 metadata 由单一 manifest 确定性生成并在 CI 检查，无手工漂移副本。

多操作 owner 的 `SKILL.md` 只保留 routing boundary、operation selector、核心不变量和启动澄清；schema、恢复、私有 command catalog 与 variant workflow 拆到入口直接链接的一跳 reference，并只在所选 operation 需要时加载。Validator 固定入口不超过 500 行与 64 KiB，校验 Markdown link/anchor、所有 reference 一跳可达、artifact consumer 的 shared protocol anchor，以及 200 行以上 reference 的目录和按需加载说明；语言密度不是硬失败条件。

跨 program 规划也遵循这条边界：脚本枚举全部合法 action、依赖、治理门、阻塞事实和已到期订阅，runtime Agent 比较信息增益、成本风险与用户约束。Agent 选择必须保存 `PortfolioDecision`，绑定当前候选快照与 effective preference receipt；不存在或已 stale 时，`kb next` 只请求重新规划，绝不把 legacy 固定排序冒充智能选择。

偏好不复制到各 skill。Canonical profile/runtime/confirmed learning 组成总偏好；显式 allowlist 先决定某个 skill/operation 最多可以看到什么，runtime Agent 再决定本任务采用哪些 soft preferences，hard constraints 必须保留。只保存 ID/digest/reason/application 回执，总偏好变化自动使旧回执失效。这是“规则管披露边界，Agent 管任务相关性”的混合分发。

## 共享运行库

`runtime/lib/research/core.py`（安装后为 `.agents/lib/research/core.py`）是兼容导出 facade，不再是业务 god-file。实现按职责拆分：

- `paths.py`：KB 逻辑路径与 active data-root 存储映射；
- `path_contract.py`：workspace/data/bundle typed root roles、稳定 `kb/...` logical namespace、canonical/reserved classification 与只读 no-follow precondition；
- `workspace_layout.py`：byte-canonical layout marker、显式新 workspace activation、root-role resolver 与 operation-boundary currentness；
- `records.py`：record schema、迭代与 workflow state；
- `prefs.py`：runtime preferences 与 workspace scaffold；
- `confirm.py`：write gate、confirmation receipt、link 与 lifecycle mutation；
- `sources.py`：source intake 与 KB-local storage migration；
- `surveys.py`：survey 上游 byte binding、selection 与消费者只读 freshness 检查；
- `source_materials.py`：PDF / HTML / Markdown / text 的完整 Markdown 阅读层、图片本地化、source map 与转换清单；
- `index.py` / `retrieval.py`：canonical index、deterministic passage extraction、FTS5 cache、只读 stale fallback 与 ID compaction；
- `diagnostics.py`：可选诊断策略、脱敏 issue、确定性去重和本地导出预览；
- `preference_selection.py`：task-scoped eligible view、Agent effective-selection receipt 与 stale binding；
- `monitoring.py`：provider-neutral subscriptions、due facts、frozen run receipt 与引用验证；
- `review_batches.py`：无插件 Obsidian editable sheet、严格 checkbox 解析与跨 owner batch binding；
- `evidence.py`：逐字 evidence 和派生证据验证；
- `analyzer_note_flow.py`：blog/dataset 共用的 deterministic prepare/verify/confirm、preference binding、事务与 post-action 编排；kind adapter 只提供 schema、artifact、rendering 与 CLI spec，理解仍由 runtime Agent 完成；
- `relations.py` / `obsidian.py`：有向关系注册表、细粒度 locator、无插件 Obsidian 派生投影与只读审计；
- `journal.py` / `git_ops.py`：恢复与精确 checkpoint；
- `bootstrap.py` / `updater.py`：运行环境与来源感知更新；
- `yaml_io.py`：原子序列化。

新增代码应依赖最窄 owner module；旧调用可以继续通过 `core.py` facade 兼容。不要重新把实现堆回 facade。

### Obsidian 派生视图

已激活的 workspace root 可直接作为无需社区插件的 Obsidian Vault；canonical record、program state、taxonomy 与 evidence 仍是唯一事实源。系统物理上只管理 `obsidian/managed/`（稳定逻辑 identity 为 `kb/obsidian/managed/`），人工内容放在 `obsidian/inbox/` 与 `obsidian/annotations/`，不得生成或改写 `.obsidian/`。生成页以 Reading view 为消费合同；编辑/Live Preview 显示 wikilink、code span 与 block ID 源码是 Obsidian 原生行为。Paper、文章与本地文档页回链 canonical `source/document.md`，source map 能把 page/section evidence locator 投影到稳定 source block；repo evidence 可以渲染为经过路径 containment 和文件存在性检查的本地文件链接，但 canonical 身份始终是 unit id 与仓库相对路径，机器本地 URI 不写回证据。动态 canonical 文本必须经 Markdown-safe 字面渲染，frontmatter wikilink 必须保持物理单行；renderer 11 的 Bases 直接输出当前支持的 Obsidian 保存格式所采用的 byte-canonical YAML。manifest-owned 普通 `.base` 是 renderer 完整拥有的可重建派生视图，刷新会丢弃任何手工内容并恢复默认 bytes；symlink、特殊类型、未登记路径仍拒绝，managed Markdown 的内容漂移也继续保留并 fail closed。manifest 的 renderer revision 变化会令旧投影 stale 并触发可恢复重建。

人工笔记回流是显式选择，不是目录扫描：只接收当前消息点名的 `inbox/` 或 `annotations/` 下一层 UTF-8 普通 Markdown basename，拒绝 nested path、symlink、special、oversize 与 review sheet。source-intake 将选择时 exact bytes 冻结成 provenance 隔离的 `blog` unit（`source_origin=human-note`），原件不进入 transaction 或 checkpoint；blog owner 只从冻结 parse cache 接受 Agent fill/verify，结构化判断仍进入普通 pending review。

原生 Bases 面板仍然只读。批量审核需要时，`kb review` 把当前治理档允许的一批（strict 3 条；personal 默认 10 条）导出为 `annotations/` 下 human-owned sheet，用户只改确认/拒绝/暂缓 checkbox。下一次对话由 Agent 读取并复述整批选择，当前消息授权后再用一个跨 owner root transaction 全量应用；任一 stale/tamper/owner failure 都整批回滚。Checkbox 本身从不等于授权，projection rebuild 也从不读取或覆盖这份 sheet。

## 数据模型

每个 unit 至少有一个 canonical `record.yaml`：

- identity：`id`, `kind`, `title`；
- lifecycle：`status`, `maturity`, `confirmation_status`, `revision`；
- epistemics：`information_types`, `needs_human_confirmation`, confirmation receipt；
- organization：`tags`, `topics`, `candidate_pools`, `links`, `reuse_flags`；
- trace：`source`, `evidence`, `history`。

Unit 类型为 `paper`, `repo`, `dataset`, `blog`, `idea`, `experiment`, `concept`。Program 位于 `kb/programs/<program-id>/`，包含 state、open questions、evidence requests、decision log、reporting events、design、experiments、reports 和 discussions。

`concept` 是 canonical knowledge unit，不是额外的 side cache。`literature-synthesizer` 从至少三个 current confirmed 非 concept unit 生成待填骨架；runtime Agent 填定义、可选 scope 与每条关联角色，全部判断携带逐字 evidence。verify 冻结上游 record/content/confirmation/evidence binding，并把关联机械投影到 top-level `links`；任何上游或 anchor 变化都会使旧确认失效。概念在真人确认后进入统一索引与 Obsidian 页面。

`kb find` 的私有 Agent 协议附带瞬时 `context-pack/v1`，不新增公开动词，也不落 canonical 文件。它最多保留 5 个 unit、每个 3 条 claim、每条 2 个 evidence ref，总体不超过 6000 UTF-8 bytes；正式 lane 只接纳当前 ConfirmationReceipt 覆盖且再次校验通过的 confirmed claims。summary 与命中 passage 永远标记为 navigation-only，聚合末尾再做一次 currentness 检查，预算裁剪按完整对象删除而不截断 quote。

`kb/raw/` 保存原始材料。可转换材料在 unit 的 `source/` 下拥有完整 `document.md`、`source-map.yaml`、`conversion.yaml`、原格式文件与可选的 hash-addressed `assets/`；HTML 另有带内联阅读样式、只引用本地 asset 的被动 `archive.html`。原始 HTML 响应、离线阅读页和 Markdown 分别承担证据、浏览器阅读与 Obsidian/AI 阅读职责，均不可原地覆盖。arXiv/ar5iv 全文 HTML 在写盘前检查 fatal/Untitled/LaTeXML error 与正文结构，不合格则先回退 PDF、再回退显式 degraded 的 abstract；显式 `vN` 不得被候选解析静默丢弃。HTML 规范化服从最终 URL 与 `<base href>`，公式通过占位保护避免 Markdown 转义，内部 fragment 映射到稳定 source block，图片 alt 与多图 figure 生成 Obsidian-safe 结构；复杂表格保留为安全 raw HTML。已有 Markdown 只在非代码语境转换图片和标题，保留 front matter、fenced/跨行 inline code 与 Setext 标题；所有非代码 raw HTML 与离线页服从相同被动化边界。纯文本按 literal 显示，HTML meta、HTTP charset 与 XML declaration 共同参与无损解码。四类输出共用结构 lint，完整派生 bundle 先在同盘 staging 生成和预检，`conversion.yaml` 最后发布，冲突或失败不得留下半套文件。人工笔记使用更严格的单文件 UTF-8/no-follow 上限与 commit-boundary currentness guard；同 bytes 的 generic source 不会吞并其 provenance。`document.md` 是人和 Agent 的首选完整阅读层，parse cache 继续承担兼容的逐字 quote/locator 协议，转换降级或细节缺失时回退 `archive.html` 或原格式。Repository 源码保持原格式与目录身份，不批量 Markdown 化；目录重试按归档合同一致忽略 VCS metadata。`kb/user/` 是生成视图，`kb/output/` 是导出，不得成为唯一 source of truth。

## Prepare / fill / verify

Analyzer 的共同状态流：

```text
source ready
    ↓ prepare
awaiting agent fill
    ↓ runtime agent writes grounded understanding
ready to verify
    ↓ machine verification
human-review-ready judgement
    ↓ current user authorization
confirmed or rejected
```

可重试失败会回到 Agent 修复，不进入 human review。Paper、repo、dataset 和 blog 必须复用 `records.py` 的 canonical workflow state 与 `is_ready_for_human_review` classifier；不得在 CLI 或各 analyzer 中各写一份近似判断。

每条 load-bearing judgement 挂逐字 evidence 和 locator。Verifier 只判断 quote 是否来自不可变证据、字段是否实质、workflow 是否可推进；不替 Agent 生成理解。

## Confirmation gate

事实 metadata 可 `auto_confirmed`。AI inference、evaluation、novelty judgement、diagnosis 和归纳的 user opinion 默认 `pending_user_confirmation`。

提升为 `confirmed` 必须同时满足：

1. 内容通过实质门，不是空壳或模板；
2. judgement evidence 完整且可机器校验；
3. signer 是可识别的真实人名；AI 名称以及“我”、`user`、`human`、`source=user` 等角色占位均拒绝；
4. `user_authorization` 来自当前用户消息；
5. `authorization_source` 可追溯；
6. receipt 绑定当前 content digest 与 evidence digest；
7. 写入瞬间重新验证授权和版本，失败时 fail closed。

Receipt 不改变原 epistemic type，也不回写 canonical claim 的 verify-time pending 字段：确认权威是 top-level current receipt，consumer 只把其覆盖且证据仍 current 的 claim 投影为已确认。若为显示状态而改 claim bytes，会让 verification/content digest 与 receipt 立即失效。内容或 evidence 改变时，旧 receipt 失效；公开层引导 Agent 基于当前材料重新核验，只有核验通过的新版判断才重新进入人类确认，不向用户暴露内部状态名。事实批量确认与判断逐项确认可以有不同 UX，但都不得自签。

AI signer 判定是 fail-closed 的 defense-in-depth heuristic，不是身份认证。输入先做 Unicode NFKC/casefold；通用 AI/tool token、中文 AI 产品/助手 marker、以及只由模型名、版本号和 release variant 组成的复合身份都拒绝，因此完整模型名不能借组合绕过 exact-name denylist。模型 token 后出现额外可能真人姓名时保留通过（如 `Claude Martin`），但仍必须同时满足当前消息授权、evidence、实质与 receipt currentness。`kb init` 的默认确认人和确认消费面使用同一 predicate。

公开 review 将治理档允许的可确认对象复制到私有一次性 token registry。strict 固定 3 条/24 小时；personal 默认 10 条且有效期可在 1..168 小时配置。profile、item limit 与 expiry 在展示时冻结，apply 不重读配置；读取与应用时在锁内清理超过宽限期的已过期/已消费普通文件，并拒绝 symlink 或越界对象。对话内可以逐项处理；无插件 Obsidian 往返使用同一冻结批次，checkbox 只是意图草稿。Agent 必须复述完整批次并用当前消息授权绑定 preview decision digest；confirm 另需真实 signer 与 evidence，reject/defer 也不能仅凭文件变化自动执行。跨 owner apply 在一个 root transaction 中全量预检、复验、应用和消费，任何失败整批回滚。registry/sheet 读写逐层使用 no-follow directory descriptor，防止中间目录 swap 将访问重定向到 workspace 外。失败分为已处理、已过期、正文变化、授权预览过时、未知或被篡改等自然语言恢复路径。

观察式偏好也是这个统一 review 的对象。Agent 只记录带逐字用户纠正和精确 skill/operation scope 的 pending observation，任务尾最多展示两条；旧的 direct review/promotion API 对偏好零写拒绝。确认时 learning receipt 与 derived runtime item 在一个 root transaction 写入，receipt 绑定正文、observation、scope 与原 learning bytes；eligible view 每次重验 current learning/receipt/runtime binding，legacy、伪签、重复或漂移项只保留历史，不跨任务生效。

## 外部发现、检索与新鲜度

`literature-search` 是 source intake 之前的 provider-neutral 发现层。runtime Agent 根据当前真正可用的 search/browser/connector 能力选择工具，将原始研究问题拆成互补查询，按批次持久化 query event、候选 identity/discovery edge、fetch/retry 状态、基于 title/abstract/fulltext 证据的初筛、coverage/frontier 及其 history、硬预算和停止依据。run identity 同时绑定问题、模式、范围摘要和可选 fresh-run ID。脚本不联网、不选 provider、不理解论文，只守 schema、identity、引用完整性、journal/lock/atomic write 和实际用量 budget；Agent 决定下一条查询、引用展开、gap-followup 与 semantic saturation。默认 exploratory 不宣称完整；系统请求在来源、查询式、结果深度和筛选不能完全复现时诚实标为 bounded-systematic，且 bounded 永远标 partial。多 reviewer 以 append-only ledger 保存各自决定与冲突；阶段只能按 title/abstract 到 fulltext 的 canonical 顺序，旧决定由 evidence/decision digest 重验，pending 裁决保留、resolved 追加并绑定输入决定。只有不同 execution/context 可称 independent，同一 Agent 多角色明确标 assisted。外部内容视为不可信数据；初筛 include/maybe 不是用户批准，只有当前对话明确选择的候选才进入 source-intake。stage 不创建 paper unit、不生成 survey，也不把 citation count、venue、作者声誉或排名当 relevance/quality。

`research-monitor` 是 provider-neutral 持续跟踪层。它保存带时区 anchored cadence、到期事实、冻结 scope/budget/run receipt、pause/resume/retry 与 evidence-bound outcome，不内置检索源，也不安装 daemon、cron、watcher 或插件。run task digest 绑定 subscription、schedule、target、scope 和 budget，receipt content digest 防止事后改写。实际文献跟踪仍由 Agent 调用 `literature-search`，stage 从创建起携带同一 monitor binding，完成时再绑定 stage bytes；survey freshness 绑定冻结 survey bytes，unit recheck 必须覆盖全部冻结 unit。宿主 automation 只在当前用户明确授权后建立；没有 automation 时，下一次 Agent 会话或 `kb next` 仍能发现 due subscription。矛盾只能形成有两侧不同 evidence 的 candidate，不能自动改 confirmed claim。

`kb add` 的多目标形式接受 1–20 项，先完成整批安全 preflight，再由 source-intake 在一个 root transaction/checkpoint 发布；late failure 不留下部分 canonical unit。`ask_first` 对整批只问一次，`auto_deep_read` 只为新增项准备 owner scaffold，重复项不制造空提示。园艺请求与 `kb next` 共用 portfolio classifier，覆盖 ready review、awaiting fill/verify、ordinary stale survey、resumable operation、due monitor 与 taxonomy rebuild，并最多公开三步。stale survey 只能重走 prepare→Agent fill→verify→pending receipt 链；taxonomy/governance rebuild 只改机械派生路径并精确 checkpoint，园艺永不删除、defer 或自签。

终端 `kb find` 使用 deterministic passage extractor。Markdown 以 heading/段落切分，长段用固定重叠窗口；每段保留 unit、artifact、locator、text 和 source digest。显式索引构建把完整临时 SQLite FTS5 数据库原子替换到 runtime cache，不使用 external-content 双表。查询最多返回五段摘要；cache 缺失、损坏或 digest stale 时，以同一抽取器做内存只读 fallback。缓存不是 canonical evidence，不进入 checkpoint，检索也不宣称 embedding 或跨语言语义能力。

已验证 survey 的 `consumer_binding` 保存 selection、unit、canonical content、confirmation receipt 与 evidence artifact digests。verify 发布前重新核对 anchor；任一上游变化即 fail closed。Navigator、report 等消费者以纯读方式判断：已有输入变化/删除、confirmation 失效或同一 selection 出现新 unit，都会把 survey 标为 stale，且不得把旧 judgement 混入正式报告。

论文链由 `report-author` 拥有，不新增公开动词。bibliography 以 canonical paper id 派生稳定 citation key，并只从结构化 citation metadata 确定性渲染；figure index 以 paper + 规范化 caption 编号派生稳定 ref key，PNG 资产按内容 hash 地址化，source/index/asset 任一字节漂移即从消费面撤下。论文初稿固定七节，各节是独立 `paper_draft_section` side judgement：prepare 只冻结 outline、program selection、current confirmed claim/evidence、citation 与 figure catalog 并创建空 fill，Agent 写正文后 verify 机械搬运逐字 evidence，再经统一 review 由真人逐节确认。section receipt 同时绑定正文与实际使用的上游 anchor；只有七节全部 current confirmed 时，Markdown、LaTeX、BibTeX 和 publication manifest 才在一个 root transaction 中原子发布，stale 或 tamper 失败保留旧四件套。

Experiment run 的 fingerprint 绑定 experiment id、tested hypothesis、规范化 changes、typed metric schema、artifact identities 与 config/input revision，但不绑定时间、结果摘要或 observed metric values。run id 仍单调递增；相同 fingerprint 的不同 seed 组成 repeat group，完全相同 fingerprint + seed/config revision 的再次写入必须显式声明 rerun/retry 并给 reason。编号、fingerprint、重复检查和相关文件写入都在同一锁与事务内完成；脚本不从重复数据推断显著性或因果。

批量实验导入接受 project-contained 的 W&B JSON、stable-header CSV 或单层 `run-*.json` 目录，单批最多 1000 run。prepare 会冻结每个 source item 的 exact bytes 与整批 digest；materialize 只做白名单事实归一化、fingerprint/repeat 计算和 raw archive，不生成原因、显著性或诊断。相同 item digest 幂等跳过，external id 或 fingerprint+seed/config 相同但 bytes 不同则 conflict fail closed；全部 run、run log、record、imports、index 与 reporting event 在一个 root transaction/checkpoint 中发布，任一 late malformed item 或 commit-currentness 变化均为零业务写。

周报与 PPT 由 `report-editorial/v1` manifest 冻结 program state/events、current confirmed claim/evidence、current confirmed decisions、stable-id factual events、task-bound preference 和 current figure bindings。runtime Agent 填 `report-editorial-fill/v1`，owner 固定 lifecycle status 与合法 label，Agent 只填写语义正文和引用；脚本只验证引用与渲染。weekly 固定四区叙事，以 program title/question 为标题、显示自然语言判断类别与编号来源，并把已确认决策、研究结论与证据、事实进展分组列入 evidence appendix，空组显式说明缺失；内部 ref、schema 和 receipt 术语不进入读者成品。PPT 固定每页一结论、formal evidence、可选 current figure、speaker note 与 transition；outline 保持七节论文结构。figure catalog 只从混合 program 中的 paper unit 读取，非 paper unit 安全跳过，缺失/歧义/不安全 identity 仍 fail closed。verify 将 Agent fill 与 output 一并纳入精确 checkpoint，并在 render/write/commit boundary 重建 manifest；stale/tamper 不覆盖旧成品。

Idea analyze/review 的 frozen corpus 若因新关联材料而不足，普通 prepare 仍保护 nonempty Agent fill；显式 refresh 会先验证旧 owner anchor 和 immutable scaffold，再只保留白名单语义字段，原子重建 corpus、orientation、anchor 与 preference binding。它不能接纳未知字段、篡改 immutable claim shape 或自动改写判断，只解决“新增证据已入库但旧 fill 无法引用”的闭环。

## 对话层与 Agent 协议

公开表面只有自然语言与 16 个 `kb <verb>` 伪 CLI。内部 owner 参数、解释器、环境变量、脚本路径和 next-step markers 不能进入 human stdout。

当 runtime agent 需要精确参数或 owner diagnostics 时，`kb-cli` 在显式 opt-in 后写私有结构化协议到 `kb/.runtime/`：

- ordinary invocation 不创建协议文件；
- 协议 destination 必须位于 runtime area；
- human stdout fail closed，只保留安全自然语言；
- protocol 可保存 child stdout/stderr 和 exact action arguments；
- init/review 在 TTY、pipe 与 Agent call 下语义一致，脚本不读 stdin。

`kb init` 先幂等准备可用结构，再在缺真实署名时返回 `ready_with_optional_setup`：private action 同时表达 configure/defer、六类快速字段（署名、语言与术语风格、研究方向、资源与重要约束、链接自动化档位 `link_autodrive`、讨论风格 `discussion_style`）、当前默认值、defer 无额外偏好写入，以及 `human_name` 只在 judgement confirmation 前必需。后两类交互偏好也可事后经 `research-config-manager` 的 `set-interaction` 调整。`apply.field_inputs` 是可执行的 canonical mapping，Runtime Agent 不得猜 dotted key：资源落在顶层 profile resource map 的 quick-setup entry，保留同 map 其他键；约束稳定追加去重到顶层 list。Snapshot 优先读 canonical 值，并只为旧 workspace 兼容 alternate focus/terminology/persona-resource 路径。Runtime Agent 必须先呈现选择；configure 用一个紧凑自然语言问题并执行该 mapping，defer 不制造 sentinel 或伪确认。已有署名时 plain init 保持 no-churn。

`kb review` 的列表浏览不依赖署名。若用户此前跳过设置，公开层仍展示已过门判断，private action 把 `human_name` 标为确认应用前置条件；Agent 先只保存真实署名，再把当前消息的授权与 evidence 交给确认 owner。底层确认门仍 fail closed，拒绝路径不要求署名。

这个分层让人类界面稳定，同时保留 Agent 自动驱动所需的精确信息。

## 可选开发者诊断与机械 audit

D1 把强制正确性门和可选质量诊断分开。Schema、evidence、confirmation、containment、journal、lock、CAS 与 recovery 在所有配置下都必须执行；配置只能关闭额外记录和 Agent 复盘。

诊断捕获模式与本地细节级别正交。`diagnostics.mode=off|errors-only|developer` 默认 `off`，语义不变；`diagnostics.detail_level=redacted|local-detailed` 默认 `redacted`。既有 scalar `per_skill` mode override 保持兼容，逐 skill 细节使用独立 `per_skill_detail_level`。`errors-only` 只运行确定性捕获，不消费 LLM token；`developer` 才允许在每任务 token/issue budget 内请求触发式短复盘。用户当前消息明确要求记录时不受自动模式关闭影响。

Dispatcher 只在 owner 已返回非零结果之后尝试捕获。公开摘要仍只接收稳定 skill、公开 operation、return code 和固定中文安全摘要；启用 local-detailed 时，另交付一个封闭的 `diagnostic-mechanical-envelope/v1`，只含安全 exception class、allowlisted failure stage、已验证且不含源码文本的产品源码 repo-relative frame token、allowlisted event 与稳定版本 token。源码 checkout 的 frame 必须逐字匹配 Git `HEAD` blob，安装态 frame 必须逐字匹配 copy-project manifest 中该路径的 digest；路径全程 anchored no-follow，未跟踪、已修改、自用、链接、special 或并发移位文件一律拒绝。Dispatcher 不从 child argv/stdout/stderr 构造该 envelope。Raw stdout/stderr、traceback 文本、arguments、用户原文、source/evidence、secret、环境变量和绝对路径始终禁止进入 capture API。捕获异常只能写入私有 Agent protocol，不能改变原 exit code 或 public message；成功与 no-op 不产生 issue。

`kb/memory/skill-evolution/issues.yaml` 继续是本地脱敏索引；redacted 模式保持原 fingerprint 与 occurrence 行为。local-detailed 在 `memory/skill-evolution/.private/details/` 为每个诊断 identity 保存一个有界、`0600`、digest-bound artifact，私有 signature 可用稳定 class/stage/frame 区分不同机械失败形态，但不证明根因。summary/detail 在同一 transaction 成功或回滚，history 最多保留五个 snapshot；新建要求目标不存在，更新以此前读取的精确 bytes 做 CAS，孤立或并发变化的 artifact 不会被覆盖。替换冲突至多保留一个有界私有 recovery backup，后续写入仅在它与可见文件逐字一致时清理，否则等待人工检查。私有 subtree 即使曾被 force-add 也从 checkpoint path discovery 硬排除，export/public protocol/versioning/sync/install/update 永不读取。

`errors-only + local-detailed` 的 root cause 明确为 `not-run`。`developer + local-detailed` 在预算为零时仍为 `not-run`，预算允许时只产生绑定 issue ID 与当前 detail digest 的私有 Agent action，状态先为 `pending`；Agent 经 owner-only apply 写入的只能是脱敏 `hypothesis`、复现线索、优化候选与下一步验证，脚本不推断原因、不伪造 token usage、不自动确认。Issue 永不自动改 skill、roadmap 或已确认研究结论。D1 没有后台 telemetry 或第三方上传；脱敏导出预览也必须由当前用户消息授权且永不包含 private detail。

机械 workspace audit 是字节级只读操作，按 `schema`、`integrity`、`recovery`、`security`、`quality` 分层报告稳定 finding。它检查可确定判断的结构、绑定、journal、产品拥有文件、基础 metadata、figure 候选和 symlink containment，不判断语义矛盾或研究结论质量。`kb doctor` 的普通输出仍只有简洁中文；显式 Agent protocol 可以包含有效模式与 audit status/counts，但不投影 raw finding。

公开动词当前精确为 16 个；新增的是无插件派生视图入口 `kb obsidian update|status`，没有扩大诊断命令面。用户仍以“开启开发者诊断”“仅在出错时记录”“关闭 unit-analyst 诊断”“对刚才失败做脱敏复盘”“检查知识库健康”等自然语言触发 Agent owner；不存在新的 `kb lint` 或 `kb diagnostics`。D1 的自动捕获、audit 和复盘目前分别按 beta/scaffold 对待，不并入 stable 能力外推。

## 原子写、事务与恢复

单文件写使用临时文件 + replace，并通过 revision/CAS 防止 stale overwrite。Record 写入使用 per-path lock 和 operation journal。

多文件 mutation 在开始前计算非空 literal target set，然后：

1. 按稳定顺序取得 exact-path locks；
2. 用同一 target set 开 operation journal；
3. 执行 nested writes；同线程同路径 lock 必须 reentrant；
4. 成功后提交 journal；失败留下可恢复状态；
5. checkpoint 只接收本次 operation targets。

禁止空 scope fallback，也禁止 `git add -A`。Manual checkpoint 先查询 dirty KB paths；clean state 是成功 no-op。Resume、undo、restore 只处理 journal 中记录的路径。公开 undo/restore 候选只包含未消费的 undoable business root，但真正 rewind 从选中 root 起遍历全部 changed committed roots，包括不可单选的内部记账、旧 recovery 和已经消费的 business root；child mutation 只由 authoritative root before-image 恢复。完整 canonical target union 先锁定并预证所有 exact-key digest 段；目录与 descendant target 重叠时，以折叠后的 topmost envelope 建一个外层 recovery journal，逆序每步按真实文件树重验 after-state，任一步失败都回滚到调用前 bytes、不 checkpoint、不消费操作。成功恢复的 checkpoint 使用 non-materializing 模式，只提交 exact restored paths，绝不调用 workspace 初始化或 auto-init repo，因此撤销 initialize 后不会把刚删除的 canonical 文件重新生成；因 `.git/.journal` 要保留恢复历史，`.gitignore` 是唯一允许保留/补齐的工作树基础设施。passage SQLite cache 是特殊派生状态：所有 `build_index()` 命令把它纳入本命令事务；历史 undo/restore 不用它做 CAS 或回放旧 before-image，而是在 canonical 回放成功后于同一外层 recovery journal 内删除，失败时恢复原 cache，避免旧版漏记 refresh 阻断恢复或撤销后残留材料文本。canonical 链不连续时仍以未记账修改或日志损坏中性分类 fail closed。

## Runtime bootstrap

Bootstrap 的优先级是：

1. 已激活并兼容的 managed workspace runtime；
2. 当前兼容解释器；
3. 安全 PATH 中 workspace 外、稳定且完整 core-ready 的解释器；
4. 需要时创建或修复 workspace-local managed environment。

普通调用不得向任意 shared interpreter 执行 package install。只有明确归属 workspace 的 managed environment 才能由 bootstrap 补齐依赖。核心 hard imports 是 `yaml`、`markdownify`、`bs4`，随安装分发的 `.agents/requirements.txt` 提供完整锁。`kb help` 与 `kb doctor` 是 stdlib-only、只读的冷启动救援面：没有任何兼容解释器时也不创建 venv、不调用 pip，doctor 如实说明 runtime incomplete 并把命令级恢复交给安装文档/Agent。installer 可显式尝试 provision；离线失败时保留已安装文件并给出诚实 warning，而不是让安装与 doctor 形成重试循环。Human-facing bootstrap error 仍遵守对话契约，不泄漏内部命令或绝对路径。

## 来源感知更新

Install manifest 记录 `source_origin` 与 `source_branch`，本地安装还可记录 `source_checkout`：

- local checkout：直接使用该 checkout，不 fetch/pull；
- remote/fork：缓存按 origin + branch 隔离，并验证 remote identity，只 fetch/pull 记录的 branch；
- detached checkout：manifest 绑定 commit，但后续更新必须先选择 branch；
- legacy manifest：来源或 branch 不足时返回 `needs_source_choice`，不猜 canonical remote 或 main；
- update/reinstall：保留 provenance；
- updater 永不 push。

这保证 fork 不被“更新”到上游，本地开发副本也不会意外触发网络操作。

## 扩展检查单

新增或修改能力时：

1. 先确认 canonical owner，并读取 default branch 上本文件、相关 tracked ADR 与 schema；
2. 复用 canonical schema、workflow state、review classifier 和 confirmation helper；
3. analyzer 只 prepare/verify，不生成理解；
4. judgement 逐条挂 evidence；
5. mutation 预声明 exact targets，使用 journal/lock/CAS；
6. human output 只含自然语言与 `kb <verb>`；
7. 产品 runtime 的 structured Agent hand-off 保持私有，不得与仓库开发用的脱敏 GitHub Issue checkpoint 混淆；
8. 同步 skill metadata、用户文档和测试；
9. 可选诊断只传脱敏稳定字段，audit 保持字节级只读，且不新增公开动词；
10. 在 Linux 与 macOS 支持的 Python 版本上验证；
11. 发布前由冷 acceptance agent 端到端复现关键路径。

当前标识为 `0.2.0-rc.7`，由源码 `runtime/VERSION` 唯一控制并安装为 `.agents/VERSION`；该标识表示 RC，不代表 stable/GA。精确发布 revision 由对应 Git tag 证明，GitHub Release 是可选分发入口而非必要条件。`CHANGELOG.md` 维护 durable candidate/release acceptance summary、兼容性与 SLA 范围；活动交付门、阻塞、精确候选和 live evidence 只在对应 GitHub Epic/Atomic Issue/PR/Actions 维护，README、用户指南与本设计文档不复制易漂移的运行状态。

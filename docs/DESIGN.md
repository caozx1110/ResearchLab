# 设计说明

本文面向想理解或扩展系统的开发者。具体 on-disk 字段和枚举以 [SCHEMAS.md](../.agents/lib/research/SCHEMAS.md) 为准；本文说明边界、数据流和不变量。

## 目标与非目标

Open Research Workspace Skills 是 knowledge-unit-first 的 research operating system。聊天是交互界面，不是状态存储：

1. 外部材料进入不可变 source 与完整 parse cache；
2. paper、repo、blog、idea 和 experiment 成为 typed knowledge unit；
3. program 保存问题、证据请求、决策、设计、实验和报告事件；
4. synthesis 保存跨 unit 的 survey、taxonomy、trend 和 gap；
5. `kb/user/` 从 canonical 数据生成，供人复开。

系统不把脚本当作理解模型。脚本只负责搬运、建填充结构、机器验证和过门；材料理解由 runtime agent 完成。任何“给材料、没有 Agent 就直接吐出判断”的实现都不属于 analyzer 层。

## 分发边界

```text
release bundle                 installed workspace
├── .agents/                   ├── .agents/
│   ├── AGENTS.md              │   ├── AGENTS.md
│   ├── lib/research/          │   ├── lib/research/
│   └── skills/                │   └── skills/
├── AGENTS.md                  ├── AGENTS.md
├── README.md                  └── kb/
└── docs/
```

仓库根 `AGENTS.md` 是开发这套 skill 系统的工作流；分发树 `.agents/AGENTS.md` 是安装后 Agent 使用 KB 的 runtime 规则。两者不可混写。

Release bundle 不包含任何私有 `kb/`。安装、更新、storage sync 和卸载必须保持数据边界：workspace 的 `kb/` 永不成为发布内容，storage sync 不改 `.agents/**` 或根 `AGENTS.md`。

安装与管理员自动化是产品唯一的技术 bootstrap 面。安装完成后，普通用户的 runtime 合同只有自然语言与 15 个 `kb <verb>` 伪 CLI；内部 flags、scripts、环境变量和 paths 只属于 Agent 私有协议或管理员参考，不得变成日常使用前置。

## Skill 路由

系统包含 17 个本地 skill：

| 分组 | Skills |
|---|---|
| Governance and routing | `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator` |
| Analysis | `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer` |
| Creation and execution | `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author` |
| Navigation and meta | `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor` |
| Conversational shortcut | `kb-cli` |

路由原则：

1. 用户自然语言优先，不需要记住 skill 名；
2. canonical artifact 只有一个 owner，薄入口不复制业务逻辑；
3. `research-orchestrator` 管 program state、open question、evidence request、decision 和 reporting event；
4. `kb-cli` 只把 15 个公开动词转给 owner；
5. `wiki-adapter` 只路由泛化 wiki 意图；
6. 确定性的共同行为下沉到共享库，Agent 理解留在 runtime。

## 共享运行库

`.agents/lib/research/core.py` 是兼容导出 facade，不再是业务 god-file。实现按职责拆分：

- `paths.py`：KB 路径与存储约束；
- `records.py`：record schema、迭代与 workflow state；
- `prefs.py`：runtime preferences 与 workspace scaffold；
- `confirm.py`：write gate、confirmation receipt、link 与 lifecycle mutation；
- `sources.py`：source intake 与 KB-local storage migration；
- `index.py`：index、governance、search 和 ID compaction；
- `diagnostics.py`：可选诊断策略、脱敏 issue、确定性去重和本地导出预览；
- `evidence.py`：逐字 evidence 和派生证据验证；
- `journal.py` / `git_ops.py`：恢复与精确 checkpoint；
- `bootstrap.py` / `updater.py`：运行环境与来源感知更新；
- `yaml_io.py`：原子序列化。

新增代码应依赖最窄 owner module；旧调用可以继续通过 `core.py` facade 兼容。不要重新把实现堆回 facade。

## 数据模型

每个 unit 至少有一个 canonical `record.yaml`：

- identity：`id`, `kind`, `title`；
- lifecycle：`status`, `maturity`, `confirmation_status`, `revision`；
- epistemics：`information_types`, `needs_human_confirmation`, confirmation receipt；
- organization：`tags`, `topics`, `candidate_pools`, `links`, `reuse_flags`；
- trace：`source`, `evidence`, `history`。

Unit 类型为 `paper`, `repo`, `blog`, `idea`, `experiment`。Program 位于 `kb/programs/<program-id>/`，包含 state、open questions、evidence requests、decision log、reporting events、design、experiments、reports 和 discussions。

`kb/raw/` 与完整 parse cache 是不可变派生证据。后续分析只读，不覆盖。`kb/user/` 是生成视图，`kb/output/` 是导出，不得成为唯一 source of truth。

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

可重试失败会回到 Agent 修复，不进入 human review。Paper、repo 和 blog 必须复用 `records.py` 的 canonical workflow state 与 `is_ready_for_human_review` classifier；不得在 CLI 或各 analyzer 中各写一份近似判断。

每条 load-bearing judgement 挂逐字 evidence 和 locator。Verifier 只判断 quote 是否来自不可变证据、字段是否实质、workflow 是否可推进；不替 Agent 生成理解。

## Confirmation gate

事实 metadata 可 `auto_confirmed`。AI inference、evaluation、novelty judgement、diagnosis 和归纳的 user opinion 默认 `pending_user_confirmation`。

提升为 `confirmed` 必须同时满足：

1. 内容通过实质门，不是空壳或模板；
2. judgement evidence 完整且可机器校验；
3. signer 不是 AI；
4. `user_authorization` 来自当前用户消息；
5. `authorization_source` 可追溯；
6. receipt 绑定当前 content digest 与 evidence digest；
7. 写入瞬间重新验证授权和版本，失败时 fail closed。

Receipt 不改变原 epistemic type。内容或 evidence 改变时，旧 receipt 失效；公开层引导 Agent 基于当前材料重新核验，只有核验通过的新版判断才重新进入人类确认，不向用户暴露内部状态名。事实批量确认与判断逐项确认可以有不同 UX，但都不得自签。

## 对话层与 Agent 协议

公开表面只有自然语言与 15 个 `kb <verb>` 伪 CLI。内部 owner 参数、解释器、环境变量、脚本路径和 next-step markers 不能进入 human stdout。

当 runtime agent 需要精确参数或 owner diagnostics 时，`kb-cli` 在显式 opt-in 后写私有结构化协议到 `kb/.runtime/`：

- ordinary invocation 不创建协议文件；
- 协议 destination 必须位于 runtime area；
- human stdout fail closed，只保留安全自然语言；
- protocol 可保存 child stdout/stderr 和 exact action arguments；
- init/review 在 TTY、pipe 与 Agent call 下语义一致，脚本不读 stdin。

`kb init` 先幂等准备可用结构，再在缺真实署名时返回 `ready_with_optional_setup`：private action 同时表达 configure/defer、四类快速字段、当前默认值、defer 无额外偏好写入，以及 `human_name` 只在 judgement confirmation 前必需。`apply.field_inputs` 是可执行的 canonical mapping，Runtime Agent 不得猜 dotted key：资源落在顶层 profile resource map 的 quick-setup entry，保留同 map 其他键；约束稳定追加去重到顶层 list。Snapshot 优先读 canonical 值，并只为旧 workspace 兼容 alternate focus/terminology/persona-resource 路径。Runtime Agent 必须先呈现选择；configure 用一个紧凑自然语言问题并执行该 mapping，defer 不制造 sentinel 或伪确认。已有署名时 plain init 保持 no-churn。

`kb review` 的列表浏览不依赖署名。若用户此前跳过设置，公开层仍展示已过门判断，private action 把 `human_name` 标为确认应用前置条件；Agent 先只保存真实署名，再把当前消息的授权与 evidence 交给确认 owner。底层确认门仍 fail closed，拒绝路径不要求署名。

这个分层让人类界面稳定，同时保留 Agent 自动驱动所需的精确信息。

## 可选开发者诊断与机械 audit

D1 把强制正确性门和可选质量诊断分开。Schema、evidence、confirmation、containment、journal、lock、CAS 与 recovery 在所有配置下都必须执行；配置只能关闭额外记录和 Agent 复盘。

诊断模式为 `off`、`errors-only`、`developer`，默认 `off`，并允许单个 skill 用更严格的有效模式覆盖 workspace。`errors-only` 只运行确定性捕获，不消费 LLM token；`developer` 才允许在每任务 token/issue budget 内做触发式短复盘。用户当前消息明确要求记录时不受自动模式关闭影响。

Dispatcher 只在 owner 已返回非零结果之后尝试捕获，并且只交付稳定 skill、公开 operation、return code 和固定中文安全摘要。Raw stdout/stderr、traceback、arguments、用户原文、source/evidence、secret、环境变量和绝对路径都禁止进入 capture API。捕获异常只能写入私有 Agent protocol，不能改变原 exit code 或 public message；成功与 no-op 不产生 issue。

结构化问题保存在本地 skill-evolution 记忆中，近重复确定性合并 occurrence。Issue 永不自动改 skill、roadmap 或已确认研究结论。D1 没有后台 telemetry 或第三方上传；脱敏导出预览也必须由当前用户消息授权。

机械 workspace audit 是字节级只读操作，按 `schema`、`integrity`、`recovery`、`security`、`quality` 分层报告稳定 finding。它检查可确定判断的结构、绑定、journal、产品拥有文件、基础 metadata、figure 候选和 symlink containment，不判断语义矛盾或研究结论质量。`kb doctor` 的普通输出仍只有简洁中文；显式 Agent protocol 可以包含有效模式与 audit status/counts，但不投影 raw finding。

公开动词仍精确为 15 个。用户以“开启开发者诊断”“仅在出错时记录”“关闭 paper-analyst 诊断”“对刚才失败做脱敏复盘”“检查知识库健康”等自然语言触发 Agent owner；不存在新的 `kb lint` 或 `kb diagnostics`。D1 的自动捕获、audit 和复盘目前分别按 beta/scaffold 对待，不并入 stable 能力外推。

## 原子写、事务与恢复

单文件写使用临时文件 + replace，并通过 revision/CAS 防止 stale overwrite。Record 写入使用 per-path lock 和 operation journal。

多文件 mutation 在开始前计算非空 literal target set，然后：

1. 按稳定顺序取得 exact-path locks；
2. 用同一 target set 开 operation journal；
3. 执行 nested writes；同线程同路径 lock 必须 reentrant；
4. 成功后提交 journal；失败留下可恢复状态；
5. checkpoint 只接收本次 operation targets。

禁止空 scope fallback，也禁止 `git add -A`。Manual checkpoint 先查询 dirty KB paths；clean state 是成功 no-op。Resume、undo、restore 只处理 journal 中记录的路径。

## Runtime bootstrap

Bootstrap 的优先级是：

1. 已激活并兼容的 managed workspace runtime；
2. 当前兼容解释器；
3. 需要时创建或修复 workspace-local managed environment。

普通调用不得向任意 shared interpreter 执行 package install。只有明确归属 workspace 的 managed environment 才能由 bootstrap 补齐依赖。Human-facing bootstrap error 仍遵守对话契约，不泄漏内部命令或绝对路径。

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

1. 先确认 canonical owner 与设计 SSOT；
2. 复用 canonical schema、workflow state、review classifier 和 confirmation helper；
3. analyzer 只 prepare/verify，不生成理解；
4. judgement 逐条挂 evidence；
5. mutation 预声明 exact targets，使用 journal/lock/CAS；
6. human output 只含自然语言与 `kb <verb>`；
7. structured Agent hand-off 保持私有；
8. 同步 skill metadata、用户文档和测试；
9. 可选诊断只传脱敏稳定字段，audit 保持字节级只读，且不新增公开动词；
10. 在 Linux 与 macOS 支持的 Python 版本上验证；
11. 发布前由冷 acceptance agent 端到端复现关键路径。

当前标识为 `0.2.0-rc.1`，已通过完整本地套件与冷启动安装副本验收，达到本地 release-candidate gate。它仍不是 stable/GA，也尚未 tag 或 publish；hosted Linux/macOS CI matrix 全绿仍是 release tag 的前置。文档、tag 与 changelog 不得把本地 RC 验收外推为稳定兼容或 SLA 承诺。

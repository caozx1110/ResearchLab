# 系统设计 SSOT（唯一可信设计源）

> **状态（2026-07-25）**：**`0.2.0-rc.7` 本地可用门已完成**。R17–R26 的严格 snapshot/确认、恢复与更新、Agent-led portfolio/偏好路由、完整 survey、无插件 Obsidian 多项 review、provider-neutral literature/monitor、正式 report/portfolio publication、公开 owner loader 与离线 Agent-plan runtime binding 已闭环。最终主线 `2126 passed`，原 P1 reviewer 真实 owner `24/24`、四个承重套件 `307 passed` 且无 P1/P2；20/20 skill validator、150-file Python 3.9 AST、shell/diff、版本一致性与无 API Key/付费/插件发布门均绿。全新 rc.7 冷安装 plan `186 targets / 0 conflicts`，exact-byte apply、20 skills、五个核心动词、no-search recovery、七阶段 survey、偏好隐私、Obsidian review、portfolio/report 和 nested guard 全绿，评分易用 9.2 / 智能 9.0 / 成熟 8.5。它仍不是 stable/GA；真实外部来源、Obsidian Reading-view 与 hosted Linux/macOS CI 是 tag 前置，push/tag/publish 不自动执行。canonical KB、不可变 evidence、确认门、精确恢复与用户只见自然语言 + `kb <verb>` 等红线不变；实时施工状态写 `temp/BACKLOG.md`。
> **这份文件是什么**：从今往后，系统的**意图 / 目标架构 / 功能设计**以本文件为唯一可信源。
> 它描述的是**目标形态**（吸收审查后系统该长成什么样），不是当前 shipped 状态——所以暂放 gitignored `temp/`，是设计工作台；每一块**落地后**再把对应描述graduate进公开 `docs/DESIGN.md`。

## R6 锁定设计（2026-07-24）

### R6.1 Agent-led 多 program 下一步

- 脚本只枚举**合法候选行动、事实状态、依赖、治理闸口和硬约束**，不得计算语义价值分或替用户决定“最值得做什么”。现有固定 `score` 只可作为旧数据兼容输入，不再是公开 `kb next` 的最终排序依据。
- runtime Agent 读取候选上下文后填写 `PortfolioDecision`：`decision_id / candidate_snapshot_digest / selected_action_ids / rationale / expected_information_gain / cost_and_risk / preference_selection_id / decided_at`。判断必须说明为什么现在做、为什么不是其它候选；不得伪造新 program 目标。
- verifier 只校验：候选存在、snapshot/current revision 匹配、依赖未失效、治理闸口未越过、理由非空、引用的偏好选择有效。它不评价理由“聪不聪明”。状态变化会让旧 decision stale；下一轮由 Agent 重规划。
- `kb next` 若有 current decision，展示其自然语言结论并把安全步骤交 Agent 继续；若没有或已 stale，内部 protocol 请求 Agent 先规划。任何 human gate、外部写入、资源承诺、确认/选择仍停下来问用户。
- multi-program 以 portfolio 视角比较 program work 与 loose-unit maintenance；blocking 并非永远机械最高，但 Agent 若绕过 blocking 必须明确记录理由与风险。terminal program 不生成候选。

### R6.2 总偏好与按 skill 智能选择

- 用户偏好只有一个 canonical SSOT：workspace profile + runtime preferences；**不复制出会独立漂移的 20 份 skill 偏好**。
- 每个 skill 声明 deterministic `eligible preference paths`，它是最小披露/安全 allowlist，不是决定结果。Agent 针对当前任务从 eligible 集合中选择实际相关项，填写 `PreferenceSelection`：`selection_id / skill / operation / catalog_digest / task_context_digest / selected[{preference_id,value_digest,reason,application}] / excluded[{preference_id,reason}] / created_at / selection_digest`。receipt 只落稳定 ID、digest 和有界理由，不持久化偏好原值；自由文本必须拒绝 secret、credential、绝对路径、URL 和高熵载荷。
- 每个非空 allowlist 必须至少有一个**真实 consumer operation**：确定性 owner 或运行时 Agent 在实际使用前重算 canonical task context、加载 receipt，并在产物/协议里保存 value-free binding；否则该 allowlist 只是不可用的假能力。纯机械、治理或 dev-only skill 若确实不应消费偏好，显式声明 neutral/空 allowlist 与原因，不得保留无法调用的候选表。repo/dataset/blog 分析、idea 生成与 research-monitor 这类明显受研究方向/资源/约束影响的语义任务不能被误标 neutral，应补 Agent-authoring consumer 与验证闭环。
- **R11 consumer ownership（2026-07-24 锁定）**：`repo-analyst:map-capability`、`dataset-analyst:profile`、`blog-analyst:complete-note` 在 Agent 开始理解材料前选择本任务相关偏好，verify 时按当前 canonical record + **不可变 scaffold/orientation contract** + source/parse-cache/structure artifact 重算 context，任何同路径 source/record/orientation byte 变化令旧 receipt stale；Agent 正常填写的 fillable 字段不属于前置 task input，不能让合法填写自行废掉 receipt。实现可使用独立只读 orientation sidecar，或对 scaffold 中非填空部分做 canonical projection digest，但不得把将被 Agent 修改的整份 fill 文件 byte digest 当成前置输入。产物只保存 value-free binding。`idea-workbench` 的 generate/analyze/review/discuss 是 Agent 语义 authoring operation，必须绑定用户题目/当前 idea/当前引用语料与不可变 orientation contract；其中 generate 不得再由脚本用固定四策略直接撰写问题、假设和 next actions，脚本只准备候选槽位并验证/搬运 Agent 填写。`research-monitor:create-subscription` 绑定用户明确目标、cadence/timezone、scope/budget 与当前授权；偏好只能由 Agent 选入以补充表达，不能覆盖用户刚给出的 scope/budget，冻结 run 继承该 value-free binding，真正检索仍由 `literature-search` 独立重选并绑定 monitor run。
- `knowledge-base-manager`（机械 schema/lifecycle）、`research-config-manager`（偏好事实 owner）、`discussion-archivist`（搬运调用方已写内容）、`research-navigator`（dev-only projection）、`wiki-adapter`（thin router）与 `skill-evolution-advisor`（治理/诊断）显式声明 preference-neutral，eligible allowlist 为空并记录原因；其 hard safety/governance 开关仍由对应 owner 直接强制，不伪装成 soft preference consumer。中央测试必须同时证明：shipping skill 要么有至少一个真实 operation，要么在 neutral registry 中有非空理由，二者互斥；不得存在“有候选但永远无法选”的第三种状态。
- runtime consumer 只接收通过校验的 effective view；不得读取未声明字段，也不得把 identity、诊断或隐私字段因“可能有用”广播给所有 skill。治理上限、确认要求、安全设置始终由脚本强制，不允许 Agent 通过偏好选择关闭。
- **Session-start 最小披露（2026-07-25 对抗复审锁定）**：工作区 Agent 启动时不得先读取整份 `personalization` 或全部 confirmed preference memory；那会在 owner/operation 尚未确定时把所有 soft preference 广播到每个任务，并与 task-scoped selection 矛盾。启动时只加载产品不变量与 hard governance；先根据当前用户请求确定 owner + operation，再向 config owner 请求该 operation 的 eligible view，由 Agent 选择当前任务相关子集并留下 receipt。当前用户消息中的明确语言/风格要求可作为本任务 canonical input 直接优先，不需要假装成 durable preference；若将来要做跨任务 session-display，必须新增独立真实 consumer operation 和有界 allowlist，不能恢复整份 profile 直读。
- skill 可维护**覆盖规则/消费声明**，不能维护第二份用户事实。用户修改总偏好后，旧 selection 因 source digest 变化自动 stale；Agent 在下一次任务重选。
- 首批必须接通：orchestrator（目标/资源/自主性）、literature-search（研究方向/范围/语言但不替代本次 scope）、synthesizer/report（语言/术语/详细度）、method/experiment（资源/风险/预算）、review（展示密度但不削弱完整知情）。

### R6.3 无插件 Obsidian review 往返

- canonical confirmation 状态仍只在受治理 record/side judgement 中；Obsidian checkbox 是**用户意图草稿**，绝不是确认事实源，也不因文件变化自动生效。
- projector 在 human-owned `kb/obsidian/annotations/` 下维护一份可编辑 review sheet。每项包含人类可读完整判断、短 evidence、`confirm / reject / defer` checkbox 与不透明 snapshot reference；不得把 owner 命令、内部路径、绝对路径、secret 或可伪造 authorization 写入页面。sheet 本身只保留自然语言、checkbox 与协议要求的不透明 HTML marker；`schema`、`kind`、owner route 和 canonical identity 只存在 private registry。export 成功后必须只 checkpoint 本次新 sheet，使尚未勾选的正常批次也保持 KB Git clean；人工编辑后允许暂时 dirty，apply 再把消费结果纳入同一次受控 checkpoint。
- 用户勾选后回到对话说“同步我勾选的 review”等明确授权；Agent 读取 sheet，生成只读 diff 并重新用自然语言概括全部决定。整批 apply 必须绑定该 preview 的 decision digest，并要求当前用户消息明确授权本批 confirm/reject/defer；confirm 还要有真实署名与 evidence。单纯检测到 checkbox 不得写 canonical KB。
- 多项应用必须先完成**全量预检**：sheet identity、snapshot token、每个 subject current binding、无重复/冲突 checkbox、全部 owner route、目标路径 containment、锁/CAS、授权上下文。任一失败则零业务写。随后在一个 root transaction 中原子应用全部决定并一次性消费 snapshot；不得出现跨 owner 部分成功。私有 registry 与 editable sheet 的读写必须逐层以 no-follow 目录句柄完成，不能先检查路径再以普通 pathname 打开；中间目录 rename/symlink swap 必须 fail closed，且绝不触碰 workspace 外文件。
- registry 原子替换的 rollback backup 必须保留到新 inode 已替换、目录身份复验和最终目录 `fsync` 全部成功；任何 post-replace 异常（包括最终 `fsync` 失败）都要先核对目标仍是本 op replacement inode，再用 backup 恢复并 `fsync`。恢复本身失败时 backup 必须保留供诊断/恢复，不能在 `finally` 清掉唯一旧副本。
- **Commit-bound source guard（2026-07-25 对抗复审锁定）**：只在 owner 的 transaction body 末尾重验来源仍不够；context body 返回到 journal `commit_op` 之间仍可发生 content 或 same-bytes/new-inode replacement。凡正式产物依赖 transaction target 集合之外的 snapshot-bound canonical source，owner 必须把 side-effect-free、fail-closed 的 current validator 注册到事务 primitive，由 primitive 在**权威 root journal** 的 commit 边界内、写 commit 状态前执行；失败走既有 abort+exact before-image restore，且不得 checkpoint。body 内 render 前/写后门仍保留用于尽早降级或失败，不能被 commit guard 替代。首批消费者覆盖 report 五类正式输出和 portfolio 新 history write；replay 无写分支保留最终 return gate。
- **Root-only guard lifetime（2026-07-25 二次对抗锁定）**：child/inherited journal 的 commit 不是 durable publication boundary，guard 在 child 通过后不能失效再让 root 无条件 commit。当前不序列化任意 callback，也不能把 runtime validator 跨进程安全延寿；因此带 `commit_guard` 的 `mutation_transaction` 只允许成为 authoritative root。若已有 same-process 或 `journal_subprocess_env` parent，必须在 child journal/preflight/business body/checkpoint 之前 fail closed，保留 root before-image；调用方须让外层 root 自己持有等价 guard，或等外层提交后把 formal publication 作为新的 root mutation 重试。不得用 child 先验成功、事务外复验或“公开路径通常不嵌套”替代此限制。若未来要支持 nested formal publication，必须设计可序列化、可重验的 read-precondition descriptor 与 root post-commit hook，不能只把 Python callable 存进进程内列表。
- hardlink backup 建立后必须验证其 inode 仍等于最初读取的 registry inode，并在 replace 前再次验证当前 filename 仍指向同一 inode；同目录并发替换不能被当作旧版本备份后静默覆盖。
- 成功后的 public stdout 只给一条自然语言整体结果；checkpoint commit/hash、`[ok]` 等机器状态只属私有执行面，不得随批量 apply 泄漏给用户。
- checkpoint 发生在业务 transaction 之后时，异常必须原样传播并把 AgentProtocol 标成 error/nonzero，明确记录“业务决定可能已提交、checkpoint 失败”；不得因为 wrapper 的初始 exit code 仍是 0 而伪造 `completed`。
- review owner 的进程内动态加载必须遵守正常 Python import 生命周期：在执行模块代码前用唯一、稳定名称登记 `sys.modules`，加载/接口校验失败时仅移除本次登记且不得污染成功缓存。不得依赖特定 Python 小版本对未登记模块的宽容行为；`dataclass`、类型解析和 owner 批量路由在所有受支持 Python 版本都必须可用。
- sheet 为可重建的人机交换面：成功后写清 applied 状态或生成新 sheet；人工备注保留。无插件、无 watcher、无后台读取 Obsidian；同步只由用户对话触发。

### R6.4 研究监测与周期复查

- 新增 provider-neutral `research-monitor` owner。脚本不联网、不搜索、不判断新颖性，只维护 `subscriptions / due runs / run receipts / linked literature-search run / review outcomes / next_due_at`。
- Agent 负责把订阅问题拆成查询、调用当前可用 search/browser/connector、复用 `literature-search` staging，并判断“新增/重复/矛盾/值得看”；脚本校验预算、时间窗、来源、link 与状态单调性。
- 真正定时唤醒交给宿主 Agent automation，必须由用户明确授权创建/修改；skill 不安装 daemon、launchd/cron 或 Obsidian 插件。没有 automation 时，`kb next` 仍能发现 due subscription 并提示 Agent 执行。
- **Active run 可发现性（2026-07-25 对抗复审锁定）**：只枚举 due subscription 会把 `active_run_id` 存在的订阅全部跳过；若 run 处于 `planned/running/blocked/failed_retryable`，它既不 due、也没有 terminal outcome，于是会从 `kb next` 永久消失。portfolio 必须枚举每个 subscription 绑定的非 terminal active run 为独立 `resume-monitor-run` 候选，绑定 subscription/run identity、state、revision、content digest、stop 与 program scope；Agent 决定本轮恢复动作，脚本只校验合法 transition/CAS。completed/cancelled 不得出现，坏 link fail closed；同一 run 不得同时伪装成 due 或 outcome。
- confirmed claim 的周期复查只产生 review request 或 contradiction candidate；不得静默改写、撤销或覆盖原结论。矛盾必须带双方 evidence，经现有 confirmation 门由用户拍板。
- 每个 run receipt 绑定 `run_id/subscription/scheduled_for/kind/target/scope/budget` 的 task digest 并有覆盖整份 receipt 的 content digest。文献 stage 必须在创建时携带相同 monitor binding，完成时再绑定 stage bytes；survey 绑定实际 survey bytes；unit recheck 必须精确覆盖冻结 unit 集合。任何 stage/survey/run receipt 事后改字节都令完成态 fail closed。
- subscription/run/frozen receipt 使用闭合 schema：未知顶层或嵌套字段、任意 provider 字段、非 canonical target/budget/cadence、非法时间/title/history/outcome/reference 都在 load/resume 时 fail closed；重算 content digest 不能把不受 schema 约束的字段洗白。

### R6.5 多 reviewer 系统检索

- systematic 模式从 `screeners=1` 扩成逐 reviewer 独立 ledger：每个 reviewer 对每个进入筛选集合的 candidate 保存 `include|maybe|exclude + reason + evidence_basis + decided_at`；reviewer id 唯一且不得由同一次判断复制冒充独立复核。
- protocol 明确区分 `independent` 与 `assisted` reviewer。若同一 runtime Agent 依次扮演角色，只能标 assisted，不得宣称人类/模型独立性。真正 independent 要求独立上下文/run identity。
- verifier 对 systematic run 校验 reviewer coverage、重复/缺失决定、冲突集合、adjudication 与最终 inclusion 一致性。冲突必须显式 adjudicate，保留原决定；不能覆盖历史。
- protocol phases 去重且只允许 `title_abstract → fulltext` canonical 顺序；每条 decision 持久化 evidence digest 与完整 decision digest，resume 先重验旧 ledger。pending adjudication 保留，resolved 以新的 append-only record 收敛并绑定 input decision digest；`user` 只能 current-user，`third_reviewer` 必须是非原 screener 的独立 execution，且 scope disagreement rule 必须与 protocol 一致。
- resume 必须对 persisted decision list 本身重验 phase 单调顺序，不能只重验逐条 digest；把原本有效的 ledger 手工重排为 `fulltext → title_abstract` 也必须在任何 merge 前拒绝且零写。
- 用户候选选择与 canonical 入库门不变；reviewer include 仍不是用户批准。

### R6.6 Stable release gate

- 必须在 self-contained/installed copy 上由冷 Agent 从自然语言完成：live literature search → 用户选择 → intake → analysis/verify → multi-item review → survey → Agent-led next → report → Obsidian review round-trip；另跑真实 PDF、复杂 HTML、dataset card、repo、SQLite HTML 与 Obsidian Reading view。
- 默认顺序全量测试、Python 3.9/3.11/3.12 兼容、20-skill validator、compileall、shell syntax、diff、安装/update/reinstall/uninstall/undo/restore、无工具/离线降级必须全绿。新增 skill 后文档、计数、manifest allowlist 与 release tests 同步。
- hosted Ubuntu/macOS matrix 仍是 tag 前置。只有远端 CI 全绿且用户另行授权，才可 push/tag/publish stable；本地施工不得自行跨越该边界。
- GitHub-link 安装主路径必须对 Agent 友好：安装器提供零写 `agent-plan`，逐条列出最终持久化的 mkdir/symlink/file/managed-block 目标及对应删除目标；summary 计数必须与目标行一致。预演不得写 workspace、HOME、TMP 或 Python bytecode cache。首次 smoke 可能由 bootstrap 在 workspace 创建 `.venv` 时，计划须把这一**条件性、边界明确、依赖解析器管理的 runtime tree**单独列出；其平台相关内部依赖文件不是 bundle manifest 的静态文件清单，不能伪装成预先可知。Agent 先审范围再执行 project-scope copy install。普通 human dry-run 继续折叠机器清单。已有根 `AGENTS.md` 的长期合同仍是 marker 限定的 managed-block 合并：先检查它是普通文件，保留块外用户原文，只更新本 bundle 区块；symlink、类型冲突或受管区块漂移继续 fail closed，不改成覆盖整文件或要求用户删除规则。
- **✅ R9 安装计划字节绑定（2026-07-24 对抗复审锁定）**：`agent-plan` 不能只记录 Git `HEAD`。计划必须绑定 canonical distributable tree（相对路径、类型、symlink target / regular-file byte sha256）的总 digest，并为每个 copy/write/managed-block target 保存 source byte/content digest；同时保存每个将写目标的计划时前置状态（absent、类型、现有 byte digest 或 managed-block digest）。机器可执行 apply contract 必须携带计划文件及其 digest、source tree digest 和 source commit，在首个目标写入前重算计划、源码树、所有会影响生成内容的 source identity（strategy/checkout/origin/branch）与全部目标前置状态，并保证实际纯 dry-run 得到的目标集合和 content digest 与被审阅计划一致；任一不一致零写失败。计划后的未提交源码漂移、remote/branch 漂移、目标并发修改、计划文件篡改均不得继续。计划还必须总是显式列出可能由首次 smoke 创建的 project `.venv` 条件性 runtime tree（root、condition、owner/cleanup 边界）；它不展开平台相关内部依赖文件，但不得出现 JSON 为空而 apply 实际创建 runtime tree 的情况。
- **R11 exact reviewed bytes 补强（2026-07-25 黑盒复现锁定）**：JSON canonical semantic digest 只能证明对象语义相同，不能兑现“执行 Agent 实际审阅的那一份文件字节”。黑盒已证实仅追加换行会改变 plan 文件 SHA-256，而旧 apply 仍成功写目标。生成计划后，Agent 必须对最终、普通、非 symlink plan 文件计算 byte SHA-256并在 apply 时作为计划外部期望值提交；apply 在解析 JSON 或触碰任一目标前，以 no-follow 方式读取同一 inode 并校验该 byte digest，再继续校验既有 semantic/source/target contract。apply contract 可使用明确的 `COMPUTE_AFTER_REVIEW` 占位，不能把自引用 hash 假装写进同一 JSON。空白、键序或换行变化也必须零写拒绝；文档只让用户粘贴 GitHub 链接，hash 计算/私有参数由 Agent 自动处理。
- installer 自身的 preflight/smoke 子进程统一禁写 bytecode，避免正式 install 额外生成 agent-plan 无法静态列举的 `__pycache__`；用户之后正常运行 skill 的 cache 仍由卸载器按 manifest-owned module 严格清理。fresh install 若根 `AGENTS.md` 已含来源未知、无 manifest digest 可验证的 workspace-oss marker block，必须拒绝而不是认领/覆盖；reinstall 与 update 同样对已知 managed-block digest 做 drift gate，只有显式 force 才可覆盖。
- `.claude`、`bin`、system skill/shortcut 等 installer-managed parent directory chain 在 plan/apply/remove 前逐组件 `lstat`；任何受管边界内祖先为 symlink 或非目录都 fail closed。不得让 `mkdir -p`、`ln` 或 `rm` 跟随预置的 parent symlink 写到 workspace/HOME 边界外。

## R7 可用性闭环锁定设计（2026-07-24）

### R7.1 Survey 是可恢复的复合工作流与一等 JudgementArtifact

- “做综述”不能只返回 `literature-synthesizer` 这个单一 owner。runtime Agent 必须先区分：① 仅综合当前 KB 的已确认材料；② 从外部发现开始的 survey。后者建立 durable composite plan：`literature-search → 候选展示/当前用户选择 → source-intake → 各 owner analysis/verify → synthesis prepare/fill/verify → kb review → confirm/reject → report consumer`。每阶段保存输入、输出、阻塞原因和 resume action；脚本只验证阶段与绑定，不替 Agent 选论文或生成理解。
- 用户明确要求 `systematic` / 系统综述或外部检索时，必须属于第②类并冻结可复现检索协议；不得因为当前 KB 恰好有一篇或少量 matching unit 就短路成普通 synthesis。只有用户明确限定“仅基于当前 KB”或 Agent 已在当前 route decision 中把任务判定为 KB-only 综合时，才允许直接进入 synthesizer。该分流是 scope/mode 合同，不是由脚本评判研究质量。
- durable composite state 必须进入正式 `kb next` 候选枚举；会话中断或 installed-copy 重启后，Agent 能从 current stage、revision、blocker 和 resume action 继续。只落在 synthesis 私有目录却不进入 orchestrator snapshot，视为不可恢复死路。
- **✅ R9 composite 完成真实性（2026-07-24 对抗复审锁定）**：stage ledger 不是任意 `kind/id` 便签。每个 completed stage 必须保存闭合、可重验的 canonical artifact binding（project-relative path、artifact kind/id、byte/content digest，以及该阶段特有的授权/receipt binding）：search=真实 terminal literature-search stage；selection=同一 terminal stage 的候选集合与当前对话 `user_message` 选择授权，且必须能在 materialization **之前**完成；source_intake=已 materialize canonical unit，并回验它继承的是上一阶段那份选择授权与候选 source identity，不能只凭可手工伪造的 stage/candidate id。若候选命中既有 canonical duplicate，source-intake 必须在同一事务中给既有 record 附加本次 selection provenance/authorization 后再标记 duplicate，保留既有分析与确认，不得让常见 duplicate 路径永久卡住；unit_analysis=current confirmed unit + content/evidence/ConfirmationReceipt；synthesis=verified survey judgement；review_confirmation=current survey ConfirmationReceipt；有 program 关联时 report_consumption=各 program 的实际 reporting event 或真实 report artifact。没有 program 关联的全局 survey 在 review_confirmation 后已经成为可独立使用的正式 synthesis judgement，最后一阶段必须以显式 `not_applicable`/`skipped` 终止并绑定当前 confirmed survey 与“无 program 消费者”原因，不得制造自签消费 sidecar，也不得永久阻塞。owner 在接受一次 transition 前重验新 binding，resume/status/next 在信任 completed prefix 前重验全部既有 binding；不存在、路径逃逸、symlink、byte 漂移、身份/授权/receipt 不符一律 fail closed 并保持可恢复，绝不能以 fake ref 把 state 推到 completed。纯结构 helper 在没有 root/context 时不得宣称 artifact-current；完成写入只允许走带 workspace verifier 的 owner path。
- 空 KB 或筛选后零个合格 unit 时，synthesis prepare 必须返回明确的 evidence gap / discovery handoff，不能成功生成可填写的零材料 survey scaffold。
- verified survey、taxonomy、trend、gap 都是 `literature-synthesizer` 拥有的一等 JudgementArtifact：持久化 canonical claims、verification receipt、upstream unit/content/confirmation/evidence byte binding、`pending_user_confirmation` 状态与 current content digest；进入 `kb review` 的统一 Top 3 收件箱，支持 confirm/reject、snapshot CAS、Obsidian batch 与 ConfirmationReceipt。确认前只可进入 Pending / Unverified；确认且 current 后才可进入正式报告。
- survey 内容或任一 upstream binding 变化会使 confirmation 与 reportability stale；旧 receipt 不迁移、不自签，必须重新 prepare/fill/verify/review。

### R7.2 偏好分发必须是强制消费合同，不是文档自觉

- 每个会被偏好影响的 **owner operation** 必须声明 canonical task-context digest、eligible operation allowlist 和消费策略。规则只决定允许披露的候选；runtime Agent 决定本任务 selected subset；consumer 必须以同一 `selection_id + skill + operation + task digest` 加载回执。
- soft preference-sensitive 写入或渲染在缺少 current receipt 时不得直接读取 canonical profile/runtime preferences；只能使用明确 neutral default 或 fail closed。hard safety/resource constraints 可由确定性脚本直接强制，但也必须在 artifact/protocol 中说明来源，不能借 hard fallback 偷读 soft 字段。
- receipt 的 task digest 由 owner 对当前 canonical inputs 机械计算，调用方不能随意提供一个无法与任务重算绑定的 64 位字符串。持久化结果记录 selection id/digest；跨 task、skill、operation 或输入变化均 stale。
- “canonical inputs”必须覆盖该 operation 会消费并可能改变语义、范围或产出的全部输入，而不只是主 ID：检索还包括 effective budget、review protocol/reviewers 与 monitor binding；method design 包括 repo/interface/baseline/metric/risk；experiment run/follow-up 包括 next action、artifact（仅 digest/安全 identity）、why/tags/recent-runs/rerun 与 evidence-needed。为每个真实 consumer 维护 operation→consumed-input registry，并以逐字段 mutation matrix 证明任一被消费输入变化都会使旧 receipt stale；不得靠发现一个漏项就手工补一个漏项。
- 建立“20 skills × preference-sensitive operations”真实 consumer 矩阵测试：不仅验证 allowlist 存在，还验证未选 soft preference 不影响输出、错 skill/op/task receipt 被拒、canonical preference 改变令结果 stale。公开 CHANGELOG/README 只有在矩阵覆盖真实 consumer 后才可声称“全部接入”。
- **R12 exact-context 与失败零写入补强（2026-07-25 对抗复审锁定）**：真实 consumer operation registry 必须与 shipping operation catalog 完整、闭合地相等，未知字段和漏登记 operation 都 fail-closed；`source-intake:add` 的所有 kind 必须先解析当前 operation preference（有 receipt 就验证 skill/op/task，无 receipt 只允许 hard-only fallback），不得只给 paper 特判。receipt/stale/containment 校验必须发生在 workspace 内任何 source、parse-cache、staging 或 canonical 写入之前；需要机械解析才能形成 task context 时，只能在 workspace 外受控临时目录完成并在全部校验通过后原子提升。`experiment-workbench:log-run` 的 canonical context 必须绑定拟分配 run id/path 与 runs allocator 目录项摘要，并在同一事务/CAS 边界内重验，禁止 receipt 后插入文件把 `run-001` 偷换成 `run-002`；独占创建 run leaf 后还必须冻结 created leaf fact，并在写 run-log/record 之前及事务 precommit 再次以 no-follow 校验 runs root、leaf identity/type/bytes 与完整 entry set，post-create 的删除、改字节、rename、root replacement、special-file/symlink 或额外 entry 一律回滚，绝不能留下“metadata 已提交但 artifact 不存在/已变”的状态。paper verify fill 只能来自当前 canonical unit/workspace 的受管普通文件，workspace 外绝对路径、任一 symlink 或输入 byte/inode 漂移均在写 judgement 前零写拒绝。
- **R12 tree binding 资源上限（2026-07-25 对抗复审锁定）**：source/repo tree digest 必须按 fd 流式计算，不能把单文件 chunks 聚合后再 `join` 成第二份完整字节；统一执行每文件字节、全树字节、entry 数与相对深度预算，超限 fail-closed 并要求缩小受控 snapshot 或提供另行受信 manifest。预算是机械资源治理，不得静默截断、抽样或把未读内容算作已绑定。

### R7.3 对话与 Obsidian 的 Top 3 必须同一批量事务语义

- `kb review` 展示的 Top 3 是一个可一次拍板的 decision set。用户用自然语言一次确认/拒绝/暂缓多项时，Agent adapter 必须先验证完整请求，再在一个 root transaction 中复用跨 owner batch coordinator 原子应用；任一项失败则零业务写。
- snapshot 只能在全部 decision shape、范围、授权、current binding、owner plan、containment、CAS 校验成功并进入提交阶段后消费。任何 validation failure 都不得把 token 标成 consumed；用户可在同一有效 snapshot 上修正答案重试。
- Obsidian sheet 必须显示 sanitized public subject id、可区分的来源/定位摘要、有效至时间和“勾选只是草稿”的说明。批量成功后页面要有明确已处理状态或被安全归档；后台精确 binding 不能替代人的知情可区分性。
- **R7.3a canonical readiness（2026-07-25 冷验收后加严）**：所有 unit 与 side judgement 的展示、对话 snapshot、Obsidian export/preview、apply preflight 必须消费同一个 `discover_pending_judgements` ready set；`record_workflow_state/is_ready_for_human_review` 只能作粗粒度工作流分类，不能单独把无 canonical card 的 legacy/失配条目放进收件箱。repo 的 file:line evidence 校验必须在 discovery、snapshot CAS、confirm/reject、report consumption 中一致传入由 record 推导并经过可信 base-root 校验的 `external_source` contract；漏传不是“证据不合法”，是 caller bug，不能通过放宽 evidence gate 修复。Obsidian 多项应用保持全或无：任一当前 item 不在同一 ready set 就整批零写并要求重新 review。
- TTY/pipe/Agent “语义一致”仅指脚本不读 stdin、同一请求得到同一状态与安全输出；选择型 continuation 由 Agent 对话完成。文档和终端输出必须明确“回到 Agent 对话继续”，不得暗示 standalone shell 自己能完成私有 apply。

### R7.4 Agent 负责复合路由；规则只守 owner 与事实边界

- substring/最长匹配表只可生成候选 owner hints，不得作为否定句、多意图或顺序任务的最终 winner。runtime Agent读取完整用户意图，输出 `RouteDecision`：`task_digest / intents / negated_intents / ordered_steps / owner_skills / rationale / governance_gates`；脚本校验 owner 存在、顺序依赖和治理边界，不评价语义理由。
- hint 命中集合不能反过来成为 Agent 的 owner allowlist。route snapshot 必须同时提供完整、闭合的正式 owner catalog 与命中/否定 hints；Agent 可在 catalog 内选择未被关键词命中的必要 owner，并为每步说明理由。脚本只拒绝不存在、dev-only 或不具正式路由资格的 owner，不因词表漏召回拒绝合法复合路线。
- “找论文再综述”“每两周检索并更新综述”“基于 repo 写周报”“不要综述只找三篇”等必须能产生多 owner composite plan或正确单 owner，不能被某个最长子串截断。正向关键词仍可作低成本 hint/fallback，但 fallback 必须明确 `planning_required`，不能冒充 Agent 理解。
- `PortfolioDecision` factual snapshot 必须覆盖公共 review 支持的全部 current judgement owner（unit、program decision、experiment diagnosis、idea discussion conclusion、method selection、survey judgement、monitor unresolved outcome）以及 open work、loose unit、due monitor。任何被引用 judgement 的 content/verification/confirmation digest 变化都令 decision stale。
- `planning_required=true` 的 owner JSON 不再同时返回带固定 score 的 legacy winner 列表。兼容输出必须迁到显式 legacy surface，正式 protocol 只有无语义 score 的 candidate snapshot。

### R7.5 Monitor 完成结果必须有可处置生命周期

- completed run 的 `new / duplicate / contradiction_candidate / worth_reviewing` 不是终态字符串；每项必须具有 durable disposition：`unresolved → acknowledged | materialized | sent_to_review | dismissed`，保留 actor/time/reason 与当前 run/output binding。
- `kb next` 枚举 completed-but-unresolved monitor outcomes。文献候选只有当前用户明确选择后才送 `source-intake`；矛盾候选必须进入既有 judgement/review gate；绑定 program 的事实性完成摘要生成 reporting event，判断性 outcome 未确认前只能进 Pending / Unverified。
- 下一轮 cadence 到期不能掩盖上一轮未处置结果。run/subscription/source bytes 或 disposition binding 变化使旧 candidate/PortfolioDecision stale；脚本不根据 citation、标题或 provider 自动判断处置。

### R7.6 清理错误产品协议并收紧完成定义

- `research-orchestrator` 中 GPU、训练 schedule、sim env、ablation、executor handoff 等 ML 专用模板不得作为所有 program 的 mandatory 协议；迁成显式可选 ML experiment template，默认 program 保持领域无关。
- paper quick screening 将机构/团队背景、结果强度、实验充分度、可靠性、创新性升级为可比较、evidence-backed 的结构化判断；字段不适用时由 Agent写明 `not_applicable + reason`，脚本不从作者、venue、citation 自动打分。
- `kb help` 的自然语言示例覆盖 literature search、survey、monitor、偏好修改与 Obsidian review；installer agent-plan 增加有界摘要与机器可读 JSON artifact，保留现有零写/精确目标合同。
- R7 完成证据必须来自全新 installed copy 的冷 Agent 端到端：GitHub-link plan/install → init → live provider-neutral literature discovery → 用户选择 → intake/analysis → 普通对话多项 review → Obsidian 多项 review → confirmed survey → Agent-led composite next → monitor outcome disposition → report。任一阶段只能靠私有参数手工拼接、需要泄漏 owner 命令、或在会话中断后无法 resume，都视为未完成。

## Part 0 · 元规则（这份文件在文档体系里的位置）

**与其它文档的关系（谁管什么，避免再次散裂）：**

| 文档                                | 管什么                            | 与本 SSOT 的关系                                                            |
| ----------------------------------- | --------------------------------- | --------------------------------------------------------------------------- |
| **本文件**                    | 意图 → 目标架构 → 功能设计      | **顶层唯一源**。冲突时以本文件为准                                    |
| `.agents/lib/research/SCHEMAS.md` | on-disk 数据模型细节（字段/枚举） | **下挂**：本文件引用它，不重复字段                                    |
| `.agents/AGENTS.md`               | 工作区**使用**规则、写作偏好、路由、入库自动驱动（随 `.agents/` 分发给用户 kb 工作区根 `AGENTS.md`） | **下挂**：面向**用** kb 的 agent；本文件引用它，不重复规则 |
| `temp/BACKLOG.md`                 | 计划/待办/时序（什么时候做）      | **平行**：本文件只管"是什么/为什么"，不管排期                         |
| `temp/what_i_need.md`（04-21）    | 原始需求                          | **被 Part 1 取代**：Part 1 是它的蒸馏 + 对账版，以 Part 1 为准        |
| 各审查文档                          | 问题诊断                          | **输入**：已吸收进 Part 2/3，不再单独维护                             |
| 仓库根 `AGENTS.md` + `CLAUDE.md`（软链→AGENTS.md） | **开发/演进本 skill 系统的循环工作流**（定SSOT→plan→codex→review→回写SSOT） | **过程层**：面向**开发** skill 的 agent（Codex 读 AGENTS.md / Claude 读 CLAUDE.md）；本文件是它循环里"定/回写"的对象 |
| 20×`SKILL.md`                    | 单 skill 触发/边界                | **实现层**：应与 Part 3 一致；不一致时 Part 3 是意图源，SKILL.md 待改 |

**维护铁律**：任何改变系统功能边界 / 确认门控 / 架构的决策，**先改本文件，再改代码/SKILL.md**。本文件落后于代码时，视为 bug。

---

## Part 1 · 意图 / 北极星（蒸馏自 what_i_need + 现状对账）

**总目标**：不是单点问答助手，而是覆盖科研全流程的研究**合作者**——持续把材料变成可复用知识、把知识变成 idea / 方法 / 实验 / 论文，人只做讨论和拍板。

**能力清单**（每条标当前现实：✅ 骨架真 / 🟡 半成品或启发式 / ❌ 缺失或占位。现实判断来自审查 + 2026-07-09 实证入库）：

| #   | 能力                                                                   | 现状 | 一句话现实                                              |
| --- | ---------------------------------------------------------------------- | ---- | ------------------------------------------------------- |
| C1  | 统一知识库：paper/repo/dataset/blog/idea/experiment 标准化入库         | ✅   | dataset 是一等 unit；文件协议 + confirmation 词汇是真地基 |
| C2  | 论文直接深读（类型判断 + 五要素，逐字 evidence）                  | ✅   | method/benchmark/survey 三类统一 prepare/verify；整份 claims 一次确认 |
| C3  | 仓库能力地图（核心模块/训练流程/复用点/边界）                          | ✅   | agent 填 capability/reuse/entry-map，脚本校验 file:line evidence |
| C4  | 博客核心内容 + 可信度 + 可复用解释                                     | ✅   | 四要素 agent 填写 + section evidence；本轮修本地源与失败恢复 |
| C5  | 检索关键信息/代码/论文（passage 级）                                   | ✅   | `kb find` 已返回 passage + unit + locator；语义/跨语言理解仍由 agent 完成 |
| C6  | 文献综述：脉络/趋势/分类/gap/热点/前沿                                 | ✅   | evidence-first survey prepare/verify 已落地             |
| C7  | idea：模糊想法→可验证问题；基于文献创新性分析；**讨论**         | ✅   | idea analyze/review/discuss 均为 evidence-first         |
| C8  | 落实 idea → 方法构思（可执行：config/命令/指标）                      | ✅   | method design 已消费资源画像并展开实验矩阵              |
| C9  | 实验：记录 + 失败诊断 + 下一步                                         | ✅   | 强类型指标、artifact 校验、baseline 对比与诊断 evidence |
| C10 | 周报/PPT/阶段总结：平时积累自动汇总                                    | ✅   | 自包含 claims+events+evidence；本轮修 canonical claims 接线 |
| C11 | 论文大纲 / 写作                                                        | ✅   | report-author outline owner 已落地                      |
| C12 | 初始化：研究背景 + 资源边界                                            | ✅   | kb init 有                                              |
| C13 | 自然语言配置 + 可开关自动化                                            | 🟡   | 有，但个性化字段下游很少消费                            |
| C14 | 外部能力复用评估（先查有没有现成的）                                   | 🟡   | 部分                                                    |

**审查新增（原 need 里没有，但你的目标其实要）：**

| #   | 能力                                                              | 现状 | 为什么要                                    |
| --- | ----------------------------------------------------------------- | ---- | ------------------------------------------- |
| C15 | **伴读**：交互式阅读（这段讲什么/为什么重要/和 X 什么关系） | ✅   | agent 原生 evidence-pack 会话模式已写入运行规则 |
| C16 | **陪练**：基于 KB 唱反调/追问/甩反例                        | ✅   | idea discuss prepare/verify + 会话陪练规则已落地 |
| C17 | **监测（push）**：新论文该看什么                            | 🟡   | provider-neutral 订阅/run receipt 已落地；真正定时唤醒仍由用户授权的宿主 automation 承担 |
| C18 | **活 KB**：stale 标记 / 矛盾检测 / 复查周期                 | 🟡   | 会话内矛盾检测已落地；定时 stale/review 仍 future |
| C19 | **注意力预算**：只呈现"现在值得看的 3 件事"                 | 🟡   | dashboard 有优先级；本轮统一 recommend_next/人类收件箱 |

**✅ 决策（2026-07-16 锁定，2026-07-24 随 R6 更新）—— 对外能力成熟度矩阵**：上表 ✅/🟡/❌ 是**设计现状**判断；对**用户/README** 另发一份**能力成熟度矩阵** `stable / beta / scaffold / dev-only`，如实标每个 skill 当前档位。paper/repo/dataset/blog analyzer 与 literature-synthesizer/idea-workbench/method-designer/experiment-workbench/report-author/literature-search/research-monitor 均为 **beta**：evidence-first prepare/fill/verify、强类型产物、有界事实 staging 或可恢复监测 receipt 已真实落地，但研究质量仍依赖 Agent、来源覆盖与用户/专家复核；research-orchestrator 也为 **beta**，因为 program spine 与跨 program Agent-authored `PortfolioDecision` 已落地，仍不承诺复杂全局规划达到 stable。`research-navigator` 仅是可选投影辅助，保持 dev-only；fresh init 的 `kb/user/` 默认页面、提示与公共输出不得点名或要求运行它，navigation 投影文件只用产品中性的“Agent 可生成研究入口”文案。**红线：绝不用任一 analyzer 或单次 workflow 的验收分数外推整个 20-skill 系统**；局部 beta 更不能被表述为“全系统已稳定”。矩阵随实现推进更新，落 README + USER_GUIDE，并由 release contract test 同源校验。

---

## Part 2 · 目标架构（采纳审查方向）

保留的骨架（不动）：`raw → units → synthesis → programs → outputs` 分层、confirmation 词汇、program spine、治理。以下是**方向性改造的八条原则**（1-7 早期锁定；8 于 2026-07-16 采纳 codex 审查后新增），是目标架构与现状的本质区别。

### 原则 1：理解来自 agent，脚本只做搬运 + 验证（analyzer 重定位）

- **现状病根**：脚本试图用 Python 抽"理解"（关键词计数、模板填充），产出空壳。
- **目标边界**：
  - **脚本负责**（确定性、可测）：取源、解析 PDF、裁图、切 passage、建索引、**校验 agent 产出的每条 claim 是否带合法 evidence locator**、写盘、confirmation 机制。
  - **agent 负责**（理解）：优先读完整 `source/document.md`，缺失、降级或需要版面核验时再读 parse-cache/PDF/HTML 原件，产出 motivation/method/ablation/insight/novelty 判断，**每条附 evidence 指针**（page/section/para 或 repo file:line）。
- **交付形态**：analyzer 脚本不再"生成笔记"，而是"生成待填结构 + 校验已填结构"；笔记内容是 agent 的产出经脚本验证 evidence 后落盘。
- **工作流后果（B1，已认）**：因此 `kb add` **不能再是纯 headless 一步到位**。它变成**两阶段**：① 脚本 stage+解析+搭骨架（headless 可自动）→ ② **agent 在会话里填理解+挂证据** → 脚本验证后落盘。纯脚本自动化的是"搬运"；"理解"那步永远需要一次 agent turn。这是目标系统与当前系统的硬区别（当前能 headless 产空壳，目标不能）。

### 原则 2：证据层（claim → evidence 绑定）

- 每条 AI 判断（fact/inference/evaluation）挂 `evidence_refs`（source_unit + artifact + locator + quote/summary）。
- 让"有理有据"从口号变成**可机器校验**：脚本能查"这条据在不在"。这也是 C5 检索、C6 综述、C7 讨论、C10 报告的共同底座。
- **验证松紧（B3，已定）**：agent 每条判断必须附**可定位的短逐字 quote 片段 + 一句 summary**；脚本校验那段**逐字片段是否真在 source artifact 里**。逐字片段短（一句话级），既防 agent 空口造据，又不逼它整段抄。
- **两套 locator（B4，已定）**：**PDF 源**用 `page=N/section/para`；**HTML 源**（arxiv HTML/网页）用 `section/anchor`（HTML 无页码）。下游 evidence、figure 处理都按源类型分两套（见 3.1）。
- **canonical schema（锁定规格，Codex 实现进 SCHEMAS.md + `evidence.py`）**：

  ```yaml
  # 挂在每条 AI claim 上。落盘位置：note/screening 产物内的 claims 列表 + record 关联。
  claim:
    id: claim-001
    text: ""                       # 断言本身
    claim_type: fact|inference|evaluation|user_opinion|unverified
    confidence: 0.0                # 可选
    confirmation_status: pending_user_confirmation|confirmed|rejected|auto_confirmed
    evidence_refs:
      - source_unit_id: p-...       # 证据所在 unit
        artifact: parse-cache.yaml  # unit 内相对路径，或 source(pdf/html)
        locator: "page=3"           # PDF: page=N|section|para ; HTML: section|anchor（B4）
        quote: ""                   # 短逐字片段（B3）——脚本校验它逐字存在于 artifact
        summary: ""                 # 可选转述
  ```

  - **验证规则（脚本，原则1）**：对每条 claim 的每个 evidence_ref，加载 artifact，检查 `quote` 为归一化空白后的**逐字子串**；缺失 → validate 报错/警告。
  - **门控联动（原则3/3.11）**：claim 自身的 epistemic type 是分轨下限，record-level `information_types`/`source.kind` 只能加严、不能把 claim 降级。`inference/evaluation/user_opinion` 一律进入 judgement 轨；`unverified` 在重分类并完成验证前不可 confirmed。judgement claim 若 `evidence_refs` 为空，**不得 promote 成 confirmed**。
  - **引用完整性（R1 对抗补洞）**：只要 claim 声明了 `evidence_ref`，该 ref 的 `source_unit_id + artifact + locator + quote` 四项必须非空并逐项校验；`[{}]`、只给 quote、缺 locator/source id 都不是“有证据”，不得借非空 list 绕过 judgement 门。
  - **路径边界（R1）**：普通 `artifact` 只能是 unit 根内的规范化相对路径；拒绝 absolute、`..`、symlink escape。Repo 证据若引用工作区源码，必须走单独的 `external_source` contract 并受声明的 repo_root containment 约束。
  - **字节绑定（R1）**：verify receipt 对每个 evidence artifact 记录相对路径 + byte sha256；confirmation evidence digest 包含这些 byte digests。artifact 变更或消失会让 verification/confirmation 失效，而不只是 quote 文本或路径变化时失效。
  - **不可变派生证据（invariant，2026-07-11 因 F-a 明确；2026-07-21 扩展）**：`raw/`/`source/original.*` 源字节、完整 `source/document.md`、其 `source-map.yaml` 与全量 intake `parse-cache` 都是**不可变派生证据**。任何"再派生"步骤（refresh-structure / detect / 综述 / Obsidian update）**只读它、另写自己的产物，绝不覆盖或截断它**。转换器或配置变化必须产生新 revision 并使依赖旧 bytes 的验证显式失效，不能原地静默换文。只有显式 `prewarm-cache --force` 可重解析源。
  - **降级来源升级（2026-07-27 冷验收锁定）**：当既有 canonical unit 只保存 degraded 摘要/页面壳，且仍未形成 verified/confirmed 判断时，用户随后提供同一强身份的完整本地 PDF/HTML，duplicate 不能以 exit-0 静默吞掉恢复意图。系统必须保留旧 unit 与全部 raw/derived bytes 不变，另建新 canonical revision，并在一个事务中把旧 unit 标为 archived、双向写入 `superseded_by` / `supersedes` link，随后把分析管线指向新 unit。若旧 unit 已有 verified/confirmed 判断、来源身份不足以证明相同，或新材料未通过完整性门，则 fail-closed 请求用户决策，不自动替换、迁移确认或覆盖证据。
- schema 细节落 SCHEMAS.md，本文件锁"必须绑定 + 上述结构 + 逐字验证 + 空据不得确认 + 派生证据不可变"五条。

### 原则 3：渐进式信任 + 确认门验内容（修空心门）

- **现状病根**：确认是二元/永久/逐条；且门只验"有人名+evidence 字符串"，**不验内容非空**（实测空 note 能盖成 confirmed/fact）。
- **目标**：
  - 确认门**必须校验实质**：core_content 为空 / note 只剩模板占位的 unit，**拒绝** promote 成 confirmed。
  - 信任**分轨道 + 可累积**：区分"事实类元数据"（可自动/轻确认）与"判断类"（需实质确认）；支持"这类 AI 判断已连对 N 次→降级为轻确认"。
  - 区分 **C8 的两个动作**："选择推进 idea"（轻，记 selection）vs"确认为事实"（重，需 evidence + 实质）。
- **✅ 决策（2026-07-16 锁定）—— ConfirmationReceipt：确认必须绑定"这一版已验内容"**：
  - **病根（审查坐实）**：现 `confirm_unit` 只校验"有人名 + evidence 列表非空 + 实质非空壳"，**不绑定内容**——① 确认后内容被改，旧确认仍有效（无 digest 绑定）；② evidence 字符串不校验是否真文件/真对应（真校验 `verify_claim_evidence` 只在 analyzer 的 verify-note 步跑，与 confirm 门脱节）；③ 确认无条件把 `information_types` 塌成 `["fact"]`，丢原 epistemic 类型；④ 默认写入门 fail-open（`RESEARCH_VALIDATE_STRICT` 默认非严格→只 warn 仍落盘）。
  - **目标 schema（锁定，落 SCHEMAS.md + `confirm.py`）**：确认落盘一个 **`ConfirmationReceipt`**，绑定：
    ```yaml
    confirmation:
      by: ""                      # 人类 actor（禁自签，沿用）
      at: ""                      # UTC
      decision: confirmed|rejected
      subject: {kind: "", id: ""} # 被确认的 unit/claim 集
      claim_ids: []               # 明确覆盖了哪些 claim（不是笼统整条 record）
      content_digest: ""          # 被确认内容（canonical core_content/claims）的 sha256
      evidence_digest: ""         # 关联 evidence（quote+locator+artifact 字节）的 sha256
      verified_at: ""             # 该 digest 是哪次 verify-note 产出的（confirm 复用其结果，不重验）
      user_authorization: ""      # 用户授权原话（自然语言，留痕）
      prior_information_types: [] # 保留原 epistemic 类型，不销毁
    ```
  - **Canonical claims（R1 加固）**：analyzer verify 必须把经校验 claims 写进 `record.payload.claims`；judgement unit 确认时 claims 非空、`claim_ids` 非空且与当前 verification receipt 完全一致。sidecar 不是确认真源。
  - **用户授权信任边界（R1 加固）**：`user_authorization` 保存用户明确授权原话，`authorization_source=user_message`；缺任一项即拒绝。actor 的 AI-name 检查用 token/边界匹配加严，但本地脚本不能密码学证明消息来自人，host/agent 必须忠实转录用户消息，文档不得把此门夸大为不可伪造身份认证。
  - **内容变更自动失效**：`normalize_record_schema` 每次读盘**重算 content_digest**，与 receipt 里存的比对；不一致 → confirmation 自动降级回 `pending_user_confirmation`（不再靠"重跑 analyzer 才 reset"这一偶发路径）。这是继"派生证据不可变"（原则2）之后的又一 invariant：**确认锚定版本**。
  - **✅ 决策（2026-07-23 对抗复审锁定）—— current receipt 必须包含当前 artifact bytes**：公开的“确认是否仍有效”判断不得只校验 receipt 结构、claims/content digest；凡 consumer 能解析 project/source context（report、index、review、owner adapter），必须重新校验 verification artifact identity、文件存在性与 byte sha256，并把任一漂移视为 confirmation 失效。无 context 的结构校验只能显式命名/用于内存构造测试，不能被报告等信任消费端当作 current 判据。
  - **✅ 决策（2026-07-23 对抗复审锁定）—— judgement source root 只从 canonical containment 推导**：unit/program side judgement 的 record 与 evidence root 必须由 project root + canonical kind/id/path 解析，逐级拒绝 symlink、非普通 record、路径别名与越界；artifact 自报 path/root 不能建立信任。discovery、confirmation、reporting 三处复用同一个安全解析器，任一处无法证明 containment 就 fail-closed。
  - **✅ post-fix 加严（2026-07-23）—— discovery 先验路径、隔离损坏候选**：review discovery 对 unit record、program decision、idea discussion、repo choice 均先证明无 symlink 的 canonical regular file，再读取 YAML；单个候选的 YAML parser/encoding/read error 只让该候选 fail-closed，不得阻断其它 inbox。repo 外部证据的 current-receipt consumer 必须把 canonical record 中受信 `external_source` contract 一并传入，不能把合法 checkout 证据误判 stale。
  - **confirm 门复用 verify 结果，不脱节**：confirm 前必须已有一次 `verify-note` 通过（evidence 逐字校验过、digest 已产）；confirm 校验 receipt 引用的 `verified_at`/digest 存在且匹配当前内容，而非在 confirm 里重新实现 evidence 校验，也不再"确认一个从没 verify 过的空/伪内容"。
  - **保留 epistemic 类型**：确认成功不再无条件 `information_types=["fact"]`；judgement-track 记录确认后进入 `confirmed` 状态但保留 `prior_information_types`，供审计与"连对降级"（future）用。
  - **写入门 fail-closed（判断轨）**：judgement-track 记录写盘时，若 `confirmation_status` 无法确立为合法值，**默认阻止**（fail-closed），不再默认只 warn 放行；`RESEARCH_VALIDATE_STRICT` 语义反转为"仅事实轨/显式放宽时才 fail-open"。（事实类元数据轨不受影响，仍可轻确认。）
  - **统一走同一门**：unit、diagnosis、program decision、report judgement 全部经同一 `ConfirmationReceipt` 门，不再各写各的确认字段。
  - **✅ 决策（2026-07-23 锁定）—— JudgementArtifact 跨 owner 收敛**：凡内容含 `inference/evaluation/user_opinion`，无论位于 unit record、experiment diagnosis、program decision、idea discussion conclusion、survey inference 还是 discussion archive，都必须具备同构的 canonical `claims + verification + confirmation` 生命周期。owner side file 可以保留领域字段，但不能成为绕开 canonical claims/receipt 的平行真源。默认工作流必须是 `prepare → runtime agent fill → verify → public review → confirm/reject`；禁止先成功创建一个没有 canonical claims、之后必然无法 confirm 的 pending 判断。历史空判断只能标 `needs_agent_repair`，不得伪装成可确认。
  - **✅ 决策（2026-07-23 锁定）—— 公共 review 是跨 owner 唯一人类收件箱**：`kb review` 聚合所有 owner 的 `ready_for_review` judgement，内部按 subject kind 路由确认，不增加公开动词。默认只展示 impact priority/staleness 排序后的 Top 3，并说明尚余数量：在尚无独立、可校验 `impact_score` 的 schema 前，owner 填写的 `priority=critical|high|normal|low` 就是 canonical impact 等级，禁止脚本另编第二套影响分；同一 priority 内更旧的待办优先。仍待 agent fill/verify、空 claims、stale receipt 或无法安全完整展示的内容不得进入确认卡片。每张卡必须完整显示 canonical claims、短逐字 evidence 与 receipt 同时绑定的 owner substance，并生成绑定 `kind/id/owner/path + pending status + content digest + verification digests` 的 snapshot；展示集合另写一次性 runtime token，应用时必须与原集合逐字一致且只能消费一次，不能靠篡改 protocol 注入未展示项。应用阶段只接受本次已展示 subject，owner 在事务内任何写入前 CAS snapshot，内容/状态/证据/身份/路径变化、duplicate subject 或跨卡 replay 一律 fail-closed。跨 owner batch 尚无共同事务时每次只应用一条决策，禁止第一条已提交、第二条失败的部分成功；owner-specific confirm/reject 命令只属内部执行面，runtime agent 不得绕过 snapshot adapter 直调。side substance 必填下限为 decision.text、discussion conclusion.text、method proposed_repo_id + selection_reason，辅助字段非空不能替代核心正文。
  - **✅ R3 review UX 收尾（2026-07-23 锁定；对抗复审加严）**：一次性 token registry 保存 `created_at/expires_at/status`，默认 24 小时；每次 review/apply 对**已有** registry 在锁下安全清理过期或已消费超过宽限期的普通文件，fresh/empty review 不得只为 GC 创建 runtime 目录或 lock，首次真正展示卡片时才创建。拒绝 symlink/非普通文件且不遍历边界外。错误必须至少区分 `already_applied`、`expired`、`stale_content`、`tampered_or_unknown`，公开只给对应自然语言恢复动作，不泄漏 token/路径/digest。成功反馈经清洗后回显 subject 类型、标题与“已确认/已拒绝”。内容变化后旧 token 拒绝，重新 review 必须展示新正文且不再展示旧正文。
  - **公共 adapter acceptance**：必须覆盖 unit/program/idea/method 四 owner × confirm/reject、terminal repeat、stale redisplay、TTY/pipe parity；测试只能在临时 KB 调真实 owner，不用 route-shape mock 替代端到端治理证据。
  - **✅ 决策（2026-07-23 锁定）—— reporting event fail-closed**：普通事件必须显式为 factual/operational；`decision/diagnosis/discussion-conclusion/survey-inference/novelty/evaluation` 及未知 epistemic event 默认视为 judgement。没有当前有效 confirmation binding 的 judgement 只能进入 `Pending / Unverified`，不能依赖 event-type 词表漏判后进入普通进展区；确认事件本身也必须引用被确认 subject/receipt，不能只靠 `*-confirmed` 名字获得信任。
  - **✅ 决策（2026-07-25 对抗验收锁定）—— reporting id 字段必须白名单化**：报告聚合器只能从明确的 unit-id 字段（含合法 unit kind 的 typed id 字段）和 canonical `kb/units/...` artifact path 提取 unit；不得用通配 `_ids` 推断，因为 `claim_ids`、`program_ids`、`selected_action_ids` 等属于不同 identity namespace。未知 id 字段默认不进入 unit loader，避免把 claim identity 伪报成缺失 unit。

### 原则 4：交互模式是一等公民（批处理之外）

- 现状只有**批处理**（intake→note→confirm）。目标新增三种**交互模式**，共用同一个 **evidence-pack 引擎**（问题→选相关 unit→拉 evidence spans→带着据对话）：
  - **伴读（C15）**：对一篇/一段，随问随答，引用本文与已读关联。
  - **陪练（C16）**：对一个 idea，以**领域专家 / 审稿人**视角讨论——质疑、追问、基于 KB 甩反例、追踪论证链，**也给建设性建议，不是一味唱反调**（用户 2026-07-08 校正）。
  - **大纲/写作（C11）**：从 KB 拉相关工作→排章节→规划图表→draft section。
- 这三个是**新 owner**（或模式），但共用引擎，不是三套重复逻辑。

### 原则 5：注意力预算（输出侧过滤，G6/C19）

- 系统对人的每次输出都要过"只呈现值得看的"过滤器：首页/next/review 不是列全部 pending，而是"现在最该看的 N 件 + 为什么"。
- 产物爆炸（note/event/card/page）必须可折叠、可忽略；人的注意力是第一约束。

### 原则 6：活的知识库（时间维度，G4/C17/C18）

- **监测（push）**：可选的"新材料该看什么"入口（拉动为主，push 为辅）。
- **自校正**：confirmed 判断带复查周期；新材料与 KB 已存信念**矛盾时能被发现**；趋势/gap 带时间戳会 stale。

### 原则 7：自动驱动（agent 自动跑完管线，人只在闸口停）—— "足够自动化"的核心

- **病根**：新范式给入库加了"agent 填理解"这步（原则1）。若不自动触发，入库退化成"用户手动 prompt 每一步"——那不是自动化，是更繁琐。
- **目标**：用户说一句"入库这篇 <src></src>"，**当前会话的 agent 自动跑完整条链**：
  `intake（双源抓取）→ note prepare（同一待填结构含 paper_type、类型证据与三套要素分支）→ agent 选择类型并只填对应五要素+逐字证据 → note verify（同时验证类型与所选分支）→ extract-figures/refresh-structure → 呈现整份判断待确认`
  **2026-07-27 R1 减法决策覆盖此前 screening-first 编排**：新 paper 不再生成、填写或确认“值不值得细读”的 quick screen；`paper_type` 是深读内的 agent 判断，必须有逐字 evidence，并与五要素 claims 在同一最终确认闸口由人签字。脚本不得猜类型；新 unit 未填类型时 fail closed，不得再以 `method_system` 静默兜底。旧 unit 的已落盘 `quick_screen.paper_type` 只可作为兼容读取来源，不得让新流程复活快筛。
  全程无需用户逐步 prompt。
- **只在两类闸口停**（治理红线，人必须介入）：① 需要**确认 AI 判断**时（论文类型/深读要素、关键 insight——原则3 判断轨）；② 需要**用户抉择**时（选 idea、批 baseline、模糊指令歧义）。其余安全步骤自动做。
- **落地三件**（非新启发式，是编排+导航）：
  1. **AGENTS.md 会话规则**：明确"入库后自动完成 grounded 笔记直到确认闸口"，且受 `runtime-preferences.autonomy` 阀门（已有 auto_execute_scope + GOVERNANCE_MAX_AUTO_STEPS 封顶）约束。
  2. **结构化 agent protocol**：intake / prepare 把下一步写入内部 JSON/返回对象（该读哪个 parse-cache、填哪些要素、填完跑哪条 verify）；public stdout 不承载机读导航，让会话 agent 无歧义接手且用户看不到内部协议。
  3. **`kb ingest <src>` 链式命令**：把"能脚本化的段"（intake→prepare→post-actions）串成一条命令，agent 只在中间做"填理解"和末尾"呈现判断待确认"。
- **成本诚实**：自动深读花 token（B2 已定：入库必深读不省）。自动化省的是**你的操作步数和注意力**（原则5），不是 token。
- **链接自动化档位（2026-07-27 R1 锁定）**：`runtime.autonomy.link_autodrive=ask_first` 时 `kb add` 只做轻量入库，一次性汇总并询问是否深读；`auto_deep_read` 时，同一个公开入口转入与 `kb ingest` 完全相同的 prepare→fill→verify 链，直到最终确认闸口。批量链接只汇总问一次，绝不逐条盘问。已退役的 `paper.auto_screen_on_intake` / `auto_screen` 不再进入默认值、init、配置展示或任何新 unit 路由。

### 原则 8：用户契约 —— 只有自然语言 + 伪 CLI，绝无裸命令 / TTY 依赖（2026-07-16 锁定）

- **病根（审查坐实）**：① 伪 CLI `forward_command` 把子脚本 stdout 原样打印（`kb:135`），`kb find/review/next/add` 都会把 `confirm: ${RESEARCH_PYTHON:-python3} …/paper.py confirm …` 这类**裸命令**喷给用户；② `kb init` 的偏好/画像问答被 `sys.stdin.isatty()` 门控（`kb:654`），agent 无 TTY → 静默跳过，只跑脚手架就返回 0——**"伪 CLI 交互"名存实亡**。
- **不变量（贯穿所有 skill 的用户可见输出）**：
  1. **用户只面对两种界面**：**自然语言** + **`kb <verb>` 伪 CLI**。除此之外的一切——裸 shell/`python3 …/*.py` 命令、`--flag`、环境变量展开（`${RESEARCH_PYTHON:-python3}`）、内部脚本路径、`NEXT FOR AGENT:` 机读导航——**都是 agent/内部信道，绝不原样呈现给用户**。
  2. **伪 CLI 绝不依赖 TTY**。任何"需要问用户"的流程（init 偏好、抉择闸口）不得用 `isatty()`+`input()`；一律走**agent 中介的对话式问答 + headless 落盘**（agent 自然语言问用户 → 用带 flag 的命令 headless 写）。理由：agent 调用进程无控制终端，`isatty()` 恒 False；且 `forward_command` 用 `capture_output=True`，子进程 `input()` 根本无法与用户交互。
  3. **裸命令的三类归属**必须分清，只有 (a) 是 bug：**(a) 用户可见的裸命令 = 违例，必须清除**；(b) `run_forwarded`/subprocess 内部机器执行 = 允许；(c) 运行时 agent 导航只能走结构化内部信道，禁止与 public stdout 混流。
- **落地形态**：
  - **清洗点局部化**：所有命令渲染汇流经 `research.common.confirm_command`/`shell_command` + 各 `format_*`/`next_unit_command` 打印点——清洗**打印点**（改成自然语言下一步引导，或 `kb <verb>` 伪 CLI 形式），保留渲染器供 (b)/(c) 用。
  - **agent 自足**：agent 知道 unit id，能自算 confirm/verify 命令；用户侧回复无需、也不得含裸 `confirm:`/`fill first:` 行。改为"这条判断待你确认，说'确认'即可"式自然语言。
  - **init 修复形态**：无配置时 public stdout 只自然语言说明“需要先了解偏好”；结构化内部信道标记所需字段。会话 agent 对话式收集 name/lang/autonomy/persona，再 headless 落盘；TTY 与非 TTY 完全同语义。
- **同步**：本原则的**用户侧规则**同步进 `.agents/AGENTS.md`（面向用 kb 的 agent），并在 `AGENTS.md`+`CLAUDE.md`（开发本）记一条"skill 用户可见输出不得含裸命令/TTY 依赖"的评审项。
- **验收**：所有 public verbs 的 stdout 逐一过滤——不含 `python3`/`.py`/`--flag`/`${…}`/内部路径/`NEXT FOR AGENT:`；无 TTY、无 flag 与有 TTY 行为一致；Agent 仍能从结构化内部信道取得下一步。

### 发布闭环 R1（2026-07-18 对抗审查后锁定）

以下不是新功能，而是把已有原则真正接成一条不可绕过的发布合同；任一项未通过，版本保持 internal alpha。

1. **Canonical claims 只有一个真源**：所有 analyzer `verify` 成功时，必须把已校验 claims 写入 `record.payload.claims`；sidecar 只可作为人类可读/调试投影，内容必须与 record 同 digest。分轨取 record 元数据与 claim types 的最严格结果：`inference/evaluation/user_opinion` 必为 judgement，`unverified` 不可确认；调用方伪写 `information_types=[fact]` 不能降级。judgement-track 的 canonical claims 必须非空，且每条 judgement claim 必须有字段完整、已逐字验证的 evidence。confirmation、report、survey、find 全部只消费 canonical claims；禁止出现 sidecar 有 claims 而 receipt `claim_ids=[]`。
2. **Evidence containment + byte binding**：`evidence_ref.artifact` 必须是 unit 根内的规范化相对路径；绝对路径、`..` 越界、symlink 逃逸一律 fail-closed。验证结果写 `payload.verification={verified_at, claims_digest, evidence_digest, artifacts[]}`；每个 artifact 绑定规范相对路径 + 文件字节 sha256。artifact 字节变化、缺失或 canonical claims 变化都会使 verification/confirmation 自动失效。repo 外部源码证据使用显式 `external_source` contract（受允许 repo_root containment 约束），不能借普通 artifact 字段越界。YAML artifact 的逐字校验必须同时保留原始 UTF-8 文本与 parse-cache 的结构化 chunk/page 视图：配置键值行（如 `flag: true`）按原始字节可引用，不能因 `safe_load` 只抽取 value 而被误报“not verbatim”；page locator 仍按结构化 chunks 收窄。
3. **ConfirmationReceipt 必须覆盖真实用户授权**：judgement confirmation 要求非空 canonical claims、匹配当前 verification receipt、非空 `verified_at`、`user_authorization`（用户原话）与 `authorization_source=user_message`。actor 的 AI 检查采用 token/边界匹配作为 defense-in-depth，不能再靠 exact denylist。必须诚实声明：本地 CLI 无法密码学证明谁发言；human origin 的信任边界是 host/agent 对用户消息的忠实传递，脚本负责完整留痕和拒绝缺失 attestation，不能宣称不可伪造。
4. **统一判断门**：unit、experiment diagnosis、program decision、report judgement 使用同一个 receipt validator。创建 decision 时只能是 pending/rejected；confirmed 必须经过独立 confirm 动作并生成完整 receipt，禁止一个 `confirmation_status=confirmed` 参数直接把判断写成 fact。确认后保留原 epistemic types。reporting event 若承载 diagnosis/evaluation/inference，必须携带可追溯的 epistemic/confirmation/claim binding；没有当前 receipt 的判断只能进入报告中显式的 `Pending / Unverified` 隔离区，绝不能混入普通进展行或被渲染成事实。
5. **源事务先取证、后建 canonical unit**：远程抓取/本地解析失败不得创建 active/pending unit，也不得占用 canonical dedup identity；写 retryable staged failure，用户只需自然语言说“重试”。本地 HTML/Markdown/text 必须生成 section parse-cache，无法解析则非零失败。intake 初次写通用 `unit_id` header；analyzer 对 raw/parse-cache 永远只读，不做 header 迁移。目录型本地 source 的归档遍历必须逐组件 `lstat`，symlink 默认拒绝或原样保留但绝不跟随；resolved child 不得越出声明 source root，不能把相邻目录的私有字节复制进 canonical unit 或 journal snapshot。每个 owner 入口都必须在任何 `resolve`/legacy remap/normalize 之前校验用户给出的 lexical local source；public wrapper 只能是额外防线，不能成为唯一防线。**去重必须在 staged 证据完成后再做一次内容绑定检查**：远程 URL 候选不能因 preflight 尚无 bytes 而绕过 exact-content dedup；materialize 前必须用 staged `file_hash` 与同 kind canonical records 比较，确保“先本地文件后远程 URL”和反向顺序语义对称，相同字节只返回已有 unit，不创建第二个 canonical identity。
6. **恢复合同是全写路径合同**：所有 load-modify-write 共享文件必须 lock + atomic write + journal；abort 要恢复 before snapshot，而不只是记状态。abort 恢复逐 target 比较 current digest 与 before digest：完全相等的 target 必须跳过 restore，保留 bytes/mode/inode，不能因为预期验证拒绝而无意义 atomic replace；真正变化的 target 才恢复。可预期的纯读 validation 必须尽量放在 workspace lock 下、journal before-image 之前的 preflight，read-only inputs 不得列入 mutation target set。锁必须具有树作用域冲突语义：以目录为 target 的事务与任一 descendant target 事务必须互斥，不能出现“子文件事务已 commit，祖先目录事务 abort 又把它回滚掉”；跨进程 nested operation 只能写 root transaction 已声明覆盖的路径。名字和语义是 load/get/list/status/current-state/preview 的 API 必须字节级只读，缺配置时只在内存返回 defaults，绝不借 `ensure_workspace` 偷偷 bootstrap；workspace seed 只能由显式 `kb init` 或声明完整 target set 的 mutation command 产生。**没有可恢复/撤销对象的 `resume/undo/restore` 失败也是零写入 no-op**：不得为了加锁先物化 `kb/.journal/*.lock` 或整个 KB；先用纯读判定是否存在目标，确有 mutation 才创建锁与 journal。现有 record 写默认以读到的 revision 作为 CAS 期望值，调用方不能靠省略参数绕过。所有 checkpoint 必须显式提供本 operation 的 path set；底层在 paths 为空时拒绝，永不回退 `git add -A`。声明 target set 可以覆盖本次未生成的 optional artifact，但 Git stage/diff/commit 的 pathspec 必须只取“当前存在或已 tracked（含删除）”的子集；未生成且从未 tracked 的可选路径必须安静跳过，不能让业务事务已 commit 后再以 pathspec error 返回失败。并发 append 验收不得丢事件；时间戳/递增名的追加型 artifact 必须在持有其目录 target 的事务内分配唯一名称，或对碰撞 fail-closed，绝不能因秒级同名静默覆盖先前产物。
   - `learnings.yaml` 的 log/bump/review 是共享 load-modify-write，必须在同一 canonical transaction 内完成“读旧值→分配 ID/更新次数→写回”；10 个并发请求必须产生 10 条唯一结果或确定性合并，不能都返回成功却只剩 1 条。promote 同时修改 `learnings.yaml` 与 `runtime-preferences.yaml`，两者必须是一个根事务的完整 target set，任一写失败回滚两者。`write_runtime_preferences` 作为可复用写入口本身也必须 standalone-safe，嵌套调用服从 root coverage。
7. **唯一 workflow classifier**：paper/repo/dataset/blog/idea/experiment 统一映射 `source_ready→awaiting_agent_fill→ready_to_verify→ready_for_review→done|failed_retryable`。`find/status/next/review/auto` 共用 classifier；hollow、抓取失败、待 Agent 填写永远不进人工确认收件箱。判断类 record 保留 `unverified` 作为原始 epistemic 类型是治理要求，不得因此把已有当前 verification、完整 canonical judgement claims 的 unit 永久判成 `awaiting_agent_fill`；只有 claim 自身仍为 `unverified` 或 verification/实质/evidence 不完整时才不得进入 review。公开 review 结果与私有 AgentProtocol 必须消费同一 `is_ready_for_human_review` 集合，不能出现 stdout 说“无待确认”而 protocol 又塞入 hollow skeleton。**拒绝态是治理终态而不是活跃语料**：默认 `status/find/next/review` 的用户面必须排除 `confirmation_status=rejected` 的 unit；私有审计仍可保留它，用户若误拒则经 `kb undo` 恢复，不能让已拒绝条目继续被计数、检索或驱动“已有资料”路由。`kb next`/dashboard/route 等语义读取在未初始化 workspace 上也必须零写，空库 defaults 只在内存构造；只有显式 init 或声明完整 target 的 mutation 可 seed 配置/导航。`next` 必须区分“真空 KB”和“已有资料但当前无待办”，覆盖 blog 的 `source_ready` 路由，并把已验证判断送到用户确认而不是让 Agent 重复填充。`loose:` 当前不是 program ID 的保留前缀；wrapper 判定 synthetic loose-unit item 必须依据 owner item 的显式形状（至少非空 `record_id` + unit step/action），不能只见前缀就删掉同名 live program work。
8. **公开输出与 agent protocol 物理分离**：伪 CLI stdout 只允许自然语言与 `kb <verb>`；内部下一步写结构化 agent protocol（JSON/专用返回对象或内部文件），不得在 public stdout 用 `NEXT FOR AGENT:`。所有伪 CLI 行为与 TTY 无关；`review/init` 不再 `input()`，一律由 agent 自然语言问答后 headless 落盘。用户每次只看“已完成什么 / Agent 接下来做什么 / 是否需要你拍板”。公开伪 CLI 是 **Chinese-first 的统一产品面**：owner 脚本即使返回英文诊断或内部 Markdown，也必须由 wrapper 投影为简洁中文自然语言；不得出现 `Unknown operation`、`Recall Digest`、`Known habits`、`none` 等未经产品化的 owner 原文。**动态内容也属于不可信输入**：record title/summary/claim/evidence、program goal/question 和用户传入编号在进入 `find/status/next/review/reject` 前必须走同一个 public-display sanitizer——去控制/ANSI/bidi 字符、折叠为单行、限制长度并防 Markdown/协议注入；若仍命中裸命令、内部路径、`NEXT FOR AGENT:` 等危险样式，则用户面降级为中文占位与“请让 Agent 安全解释”，完整原文只留私有 protocol。不能让恶意资料或 Agent 产物用换行伪造第二条系统指令。命令识别必须在折叠空白前保留并逐条检查原始逻辑行，只把行首、满足命令/参数形状的内容视为裸命令；不能用“任意位置出现 find/docker 等单词”的 context-free blacklist 永久误伤正常论文语句。shell 变量赋值前缀、`env/command/exec/eval/source` 等包装/内建和常见解释器、构建器、包管理器、网络/归档/系统工具必须按命令族 fail-closed；只补审查样例的有限词表不算覆盖。`kb help`、顶层 `kb --help` 与任一 `kb <verb> --help` 必须收敛到同一份会话式能力说明；不能让顶层落回 argparse 的 `positional arguments`/内部术语，也不能让子命令帮助只剩空白。**`kb review` 是知情确认界面，不是 ID/摘要列表**：每个将被同一次确认覆盖的 canonical claim 都必须以中文人类标签展示其判断文本，并至少给一条短逐字证据摘录（多余 evidence 可报数量）；同时说明内容已核验、为什么现在需要用户拍板。可确认 claim 的可见文本投影必须无损：不得截断后仍标 `ready`，否则相同前缀/不同尾部会让一次相同的用户拍板绑定不同 receipt；在产品硬上限内完整显示，超限则转入“请让 Agent 安全解释”而不是继续给确认入口（evidence 仍允许按契约显示明确标注的短摘录）。不得用 intake scaffold 的 `record.summary` 代替实际已核验 judgement，也不得要求用户去读私有 protocol 才知道自己在确认什么；若某 claim 因上述注入防护无法安全逐字展示，必须明确让用户先要求 Agent 解释，不能伪装成已充分展示。`kb add/ingest` 不得泄漏 `backup_status/source_type/locator_kind`、checkpoint hash、内部相对路径等协议/实现字段；这些只进私有 AgentProtocol，stdout 只给自然语言结果与下一条 `kb <verb>`。`find/status/next/review/reject/recall/resume/undo/restore` 同样不得泄漏内部枚举、评分、pool、`loose:<id>` 路由键、owner-only 命令或 owner 原始异常；成功、no-op 与错误都要给中文自然语言反馈，reject 成功必须说明已拒绝并给出 `kb undo` 可撤销入口。`kb init` 的 prerequisite、偏好写入和可选 Git 初始化同样只进私有 protocol；成功路径只能输出一条最终自然语言总结，不能透出 `[ok] set ...`、`created/initial_commit` 机器字段或重复五次“基础结构已准备好”。重复 `kb init` 是幂等补全：未显式提供的新字段一律保留当前偏好/画像，只为真正缺失的字段填默认值，绝不能把姓名、auto-screen、auto-commit 或 persona 重置。
   - **R17 owner-adapter 补强**：公开入口不只指 `kb` wrapper；当正式 skill 流程要求 runtime Agent 跨 owner materialize 已选 literature candidate 时，也必须使用 capture/sanitize adapter：owner stdout/stderr 全部留在私有 protocol，用户面只返回一句自然语言结果与 `kb <verb>` 下一步。默认直接执行会打印 `[root]/[auto]`、绝对路径、内部脚本或 `NEXT FOR AGENT:` 的 owner 命令，不得再作为 shipping workflow 推荐路径。adapter 必须绑定 current user selection、stage/candidate digest 与 owner result，失败不伪装成功。
   - **R17 交叉审查补强——canonical record 读取只有一条安全路径**：portfolio、`kb status`、review/Obsidian、find 与任何 unit 枚举不得再用 `glob + Path.read_text/load_yaml` 各自读取 `record.yaml`。共享 reader 必须从 canonical workspace root 逐级以 dirfd + `O_NOFOLLOW` 锚定 kind/unit/leaf，leaf 使用 `O_NONBLOCK`、只接受有界 ordinary file，读取前后重验 inode/stat/长度，并用拒绝任意层重复 mapping key 的 YAML loader；祖先链在返回前从父 fd 重验身份。单个坏 record 在 inbox/search 等批量发现中 fail-closed 隔离并作为 audit finding，不得跟随外链、阻塞整个命令或把 last-wins YAML 当成治理事实。
   - **R18 下游能力补强——snapshot 不能降级回普通 Path**：严格 record snapshot 解析出 source unit 后，不得只返回 lexical `Path/.parent` 给 review/evidence；证据和 passage/index 的 Markdown、parse-cache 必须通过同一条 root→kind→unit 的 anchored directory capability 读取，形成 bytes+digest+artifact identity 的不可变 snapshot，并在判断/展示前重验祖先链。leaf-only `O_NOFOLLOW`、先 `resolve/is_symlink` 后再按路径打开都不够。批量 normalization 对任意 YAML mapping 必须是 total boundary：明确 schema/type 错误只隔离该 record并留私有 finding，不得把 raw malformed payload 当 canonical record，也不得让 `TypeError/ValueError` 拖垮 status/find/survey/intake；`KeyboardInterrupt/GeneratorExit` 不吞。`locate_record(last/current)` 的 mtime 排序保持整数纳秒，不能缩放为 epoch float 后丢失 1ns 顺序。
   - **R20 consumer migration——informational path 永远不可再读**：`trusted_unit_record_path` 只允许用于受限的存在性/用户标签兼容，返回值不是 read capability。`report-author` 收集 unit claims、`idea-workbench` 跨 unit claim/evidence、monitor materialized target 复核及任何后续 consumer 必须直接取得 strict record / `EvidenceSourceSnapshot`，并把初始 record snapshot 传给 confirmation/readiness current-check；不得先安全定位、再 `load_yaml/read_text/read_bytes(path)`。报告或 idea 产物不能因 unit 祖先在定位后替换而读取、显示或接受 workspace 外标题/证据。
   - **R21 剩余 consumer 收口——共享快照必须到达决策、方法与 survey anchor**：program-decision 与 method-selection 的跨 unit evidence roots 必须直接由共享 `trusted_claim_source_roots`/`EvidenceSourceSnapshot` 捕获，不能 `locate_record` 后保存 `source_path.parent`。survey `build_unit_binding` 必须把用于 title/record digest/receipt/evidence-artifact list 的 record 与 artifacts 绑定到一个 `CanonicalUnitSnapshot`；若需“全部普通 artifact”语义，应在 records 层提供 anchored、bounded、no-follow 的递归 snapshot API，surveys 不得再 `rglob + file_sha256`。survey eligibility / confirmation-current 必须与 owner/report 使用同一个 `record_external_source_contract(record)`；repo 等外部源码证据不能因 consumer 漏传 base-root contract 而被永久误判 stale。任一来源在捕获、eligibility、绑定或最终 current-check 之间发生 record/artifact/祖先替换时，整个 judgement/method/survey 输入 fail-closed，不能接受只存在于替换目录中的 quote，也不能把替换文件列入 consumer binding。
   - **R22 generic unit confirm——授权、证据与最终写必须绑定同一 record snapshot**：任何已持久化 unit 的 judgement confirmation 不能只接收 detached dict + integer revision。确认入口必须取得唯一 `CanonicalRecordSnapshot`，证明待确认 dict 正是该 snapshot 的规范化内容，把它作为 `expected_record_snapshot` 传入 evidence/source-root 捕获，并在生成 receipt 后、最终写入事务内再次比较 exact prior bytes + file identity + ancestor/current binding。`write_record` 的 expected snapshot CAS 与 revision CAS 同时成立才可覆盖；相同 revision 的另一份 record、同 bytes 新 inode、目录/record 替换或授权后内容变化一律零业务写 fail-closed。public review/Obsidian snapshot、paper/repo/dataset/blog/experiment owner confirm 与 knowledge-base-manager batch 必须走该合同；纯内存/尚未持久化的测试或 prewrite flow 可显式不带 persisted snapshot，但不能借此写回已有 unit。
   - **R23 judgement read snapshot——报告与公开 current-check 只能消费同一次读取的判断版本**：`load_bound_judgement` 不得先用 `trusted_*_path` 验证路径、再以 `load_yaml(path)` 重开 leaf；canonical unit 必须返回唯一 `CanonicalRecordSnapshot` 中规范化的 record，program decision / idea discussion / method selection / survey 等 side judgement 必须从 project root 逐级 anchored/no-follow 打开 canonical artifact，以 nonblocking、有界 ordinary-file snapshot 同时取得 raw bytes、strict YAML mapping、leaf identity 与祖先链 identity。consumer 必须把同一个 bound snapshot 传给 identity、verification、ConfirmationReceipt、event binding 与 survey claim-source 校验，并在正式 claims/时间线进入报告前最后重验 snapshot current；不得让 helper 内部再次按路径加载同一 subject。`program:<id>` evidence 也不能继续返回 bare `Path` 让每条 ref 独立 `read_bytes`：必须一次性把本判断引用的全部 program-local artifacts 捕获成同一 ancestor-bound `EvidenceSourceSnapshot`，否则两个目录版本可拼成历史 receipt 从未真实存在的 evidence set。目录、leaf、任一 referenced artifact 或同 bytes inode 在任一阶段替换，或 subject 在多个 canonical container 中重复出现，整条 judgement 只能进入 `Pending / Unverified`，不得组合旧 record 与新 evidence/owner/path。review card 的 snapshot binding 必须额外绑定产生该 card 的完整 canonical container bytes（unit 为 record bytes，side judgement 为承载列表的完整 YAML bytes）；只改同一 side container 的无关 sibling 或顶层字段也必须令旧 card stale，不能只比较所选 item 的内容。兼容的二元 path API只能作为非承重展示接口；正式 report/review consumer，以及 portfolio program-decision 引用、survey review-confirmation/report-consumption provenance，必须使用 snapshot-bearing API并在产出绑定后做最后 current-check。
   - **R24 冷产品验收——无工具阻塞必须可恢复，显式事实事件必须进入事实轨**：`blocked_no_search_tool` 不能只说“已记录”后让用户猜下一步；公开结果要明确进度已保存，并给三个无需付费/Key 的恢复选项：之后在已有搜索/浏览能力的会话中自然语言继续同一次检索；现在提供 URL/DOI/PDF/本地论文或候选清单继续；或暂时保留进度，之后通过 `kb next` 恢复。不得要求配置 provider、购买额度或安装插件。report event classifier 对显式 `epistemic_type=fact|factual|operational` 与 literal `event_type=fact|factual|operational` 都走 factual/operational lane，除非同一事件同时携带 judgement information type、judgement event token 或 governance binding；未知/无类型仍默认 judgement。这样用户明确记的机械事实不会被错误隔离，同时任何冲突信号继续以最严格结果判 judgement。
- **R25 整批发布栅栏——局部 current-check 不能替代最终输出/写入边界**：report 输入装配必须保留 event/survey、unit ClaimSource 与 direct decision 的 exact snapshot capability，而不是只留下派生 dict/digest；装配结束先做一次 aggregate final-current，正式 Markdown/周报/阶段总结完成后、返回用户前再做一次。任一来源在本轮后续步骤中失效，整份 formal judgement lane 必须 fail-closed 为通用 `Pending / Unverified`，不能发布任何旧 claim/title/decision/survey 文本。reporting events 的 side judgement 必须由一次 batch capture + `(kind,id)` 唯一索引解析，N 个 event/N 个 container 只能线性捕获，不能每 event 重扫全部 side containers。portfolio decision 同理：program-decision bound snapshots 必须随 validation plan 保留到根 mutation 锁内，在 history canonical write 的最后边界重新验证；same-bytes 新 inode 或内容/祖先替换必须零 history 写，不能只持久化 digest 后继续。所有 snapshot-bearing judgement 入口先把 project root 规范为同一个真实路径表示（macOS `/var` 与 `/private/var` 等价），再做 anchored capture/identity/relative path；路径别名不能让合法 side judgement 从 review/report/portfolio 消失，也不能削弱 no-follow containment。
  - **R26 publication write/post-write gate**：render 返回不能视为发布完成。report 的正式文本选择、最终 current-check 与目标写入必须位于同一个 exact-target mutation 内；正式内容写入后、transaction 成功退出前再重验全部 formal validators，失败抛出并由 journal 回滚旧 report bytes/不存在状态，不能留下刚写入的 stale claim。若进入 mutation 前已 stale，允许只生成通用 pending/factual 文本，但不得携带旧正式 title/claim/decision/survey。portfolio history 同样在 canonical write 后、transaction commit 前再次调用原 validation plan 的 bound snapshot current-check；失败必须回滚 history，same-bytes 新 inode也一样。post-write check 是缩小同一次 operation 的 publication race，不宣称对操作返回后未来任意 source 变化提供永久锁。
  - **R26 unit claim-source 线性捕获**：report 一轮输入装配只能枚举 canonical unit snapshots 一次，建立唯一 `unit_id → snapshot` 索引后解析全部 program/event unit ids；重复 id 去重，ambiguous duplicate fail closed。N 个 factual events/N 个 unit 只能产生 O(N) snapshot yields，禁止每 unit 重新全库扫描形成 N²。
   - **R17 交叉审查补强——selection 从“用户看见”开始绑定**：selection payload 必须携带用户作出选择时的 exact literature stage byte digest，以及每个被展示候选的 identity + semantic digest；这些字段来自同一次 portfolio/selection projection，不得由 adapter 启动后现算并冒充用户所见快照。adapter 先用共享 anchored strict stage reader 取得 bytes/parsed state/digest 的同一快照并核对展示 binding，之后才建立逐项 expected-stage transition chain。stage 顶层、candidate、history/query 等嵌套对象全部 exact-schema；未知字段、类型/枚举/时间错误、任意层重复 YAML key、leaf/ancestor symlink/special/rename race 都整体 fail-closed。兼容字段只能在 schema 中逐字列出，不得靠丢弃未知字段“清洗后接受”。唯一 OpenAlex 历史兼容输入限定为 `provenance.openalex={doi}` 或 `{work_id,doi}`，其中 `work_id` 必须是 canonical `W<digits>`；旧 stage 可尚未复制 `identities.doi`，但这些字段只用于 read-only identity migration，不能触发 OpenAlex 查询、写回或新增 provenance。
   - **R17 交叉审查补强——canonical outcome 优先于子进程外观**：owner 返回 0、非 0、timeout 或 capture 异常后，adapter 都必须从同一 anchored stage snapshot 与 exact append-only selection receipt 判定事实结果；若 canonical record/marker/receipt 已完整提交且 stage 变化严格等于唯一允许 transition，就如实计入成功，return code 只留私有诊断。反之不得因 exit 0 伪装成功。`source_search.selections[]` 的 exact receipt 是幂等权威，后续合法选择更新的展示型 `user_selection` 不得让旧 receipt 失效。
   - **R17 交叉审查补强——私有 protocol 先占位、后执行**：用户/Agent 提供的安全 protocol name 在 owner dispatch 前以 `O_EXCL` 建立带 selection binding 的持久 claim，并 fsync claim 与每一级新建目录的父目录；同名并发者必须在任何 canonical owner 写之前失败。完成后只在 name 仍指向本 op claim inode 时原子发布最终 protocol 并 fsync leaf directory；崩溃留下的 claim 是可审计恢复材料，不能静默覆盖。默认 owner capture 必须流式消费 stdout/stderr，只累计有界元数据（bytes/lines/hash/截断标记），不能把 15 分钟内的无界输出全部留在内存或写进用户面。
   - **R17 交叉审查补强——synthetic continuation 不是 program**：`literature:`、`review:`、`monitor:`、`survey:` 等内部 namespace 只用于私有 action identity。公开 `kb next/status` 按 action type 渲染“独立文献检索/待确认判断/研究监控/综述流程”等中文业务名，默认隐藏 synthetic ID，并把 reason 映射为有界中文合同；不得称为“研究计划”或直出内部英文 reason。
   - **R18 冷验收补强——status 与 next 必须同源且不自相矛盾**：`kb status` 与 `kb next` 消费同一 portfolio candidate snapshot。status 可分列待确认、到期监控、文献选择/继续检索、可恢复综述和失败重试，但还必须单列未被这些命名类别覆盖的“可由 Agent 继续推进”数量；不能六类全报 0 后紧接着让 Agent 在 1 个行动中选择。分类必须形成可解释覆盖且不重复计数，公开文案只给中文业务数量，不泄漏 action id/type、synthetic namespace 或内部 reason。
   - **命令分类的 UX/security 双门**：无歧义 executable family 可直接 fail-closed；`find/open/go/python/echo/source/test/time/which` 等兼具自然语言含义的行首词，必须再有已知 subcommand、option、path/file、assignment 或 shell 结构等命令证据，正常技术句不得仅因首词命中而隐藏。公开 `kb` 例外只接受字面、未混淆的 `kb` + 受支持 public verb；未知 verb、转义/引号拼接或 shell operator 仍按不安全内容处理。
9. **发布工程**：公开 README/USER_GUIDE/DESIGN/SCHEMAS 与实际 verbs/门控同源校验；runtime 合同为 Python 3.9+，shipping module 不得用会在 3.9 import 期求值失败的 PEP 604 type-alias RHS；doctor 必须识别默认 `pymupdf4llm/fitz` runtime；manifest 记录可追溯 source origin/checkout/branch（detached 安装则绑定 commit 并在更新前要求显式选择），fork/local/non-main 安装不静默切回 canonical upstream 或 `main`。只要安装确实由一个仍有效的本地源码 checkout/worktree 发起，manifest 必须记录该 lexical checkout，并把它标为 local-checkout 更新策略；remote origin/branch 可同时保留作身份与溯源信息，但 check/apply 在 checkout 存在时只读该工作树当前内容，绝不自行 fetch/pull，也不能因分支尚未 push 就改走远端。checkout 消失或不再是合法 source 时 fail-closed 请求用户选择，不能静默回落到 origin；纯 remote/cache 策略才可按记录的 origin+branch fast-forward。update 的 apply 层必须独立执行 SemVer 单调门，外部 copy 的 source 版本不高于已安装版本时零写入，不能依赖上一轮 check/agent 状态来防降级；copy uninstall 只可删除“普通文件且当前 sha256 仍等于 manifest”的受管目标，内容漂移、类型变化、symlink、不可验证的 AGENTS managed block 一律保留并告警，绝不把用户后续修改当安装残留清掉。唯一例外是 manifest-owned Python 源模块的标准 `__pycache__` 派生产物：清理必须识别不同 CPython ABI tag（不能只按执行卸载的当前解释器生成名称），但仍只匹配同模块 stem 的标准 cache 语法；任意同前缀/非标准名、symlink 或非普通文件继续保留。依赖锁必须覆盖 runtime/test 的完整 transitive closure，并为 Python/platform 条件依赖保留 marker，不能只固定顶层 pytest 后继续区间解析；CI 覆盖 Ubuntu + macOS；版本 bump、CHANGELOG 与 release tag 必须在最终验收后一起做，施工分支不得提前打稳定 tag。

- **D2 workflow 收紧（2026-07-21）**：唯一 classifier 同样覆盖 dataset；`safe_unit_step` 对 `done` 必须立即返回无动作，kind-specific completeness 只能解释尚未 done 的 unit，不能绕过 classifier。program 的 blocking evidence / open question / 持久化 `next_actions` 优先于 loose-unit maintenance；没有 program work 时不得从聊天承诺虚构“综述/路线图”，也不得把已确认 unit 的可选刷新冒充研究下一步。
- **R1 routing discriminator 澄清**：synthetic loose-unit 必须消费 owner 已给出的显式 `stage=loose-unit`，并同时要求非空 `record_id`；不得再从 `loose:` 前缀、step type 或 pending record 的重叠字段猜身份。合法 live program 即便名称以 `loose:` 开头并携带 human-decision，也必须保留为 program work。
- **R1 owner 输出默认拒绝**：public wrapper 只翻译明确支持的 owner result shape；未知 owner stdout/stderr 不得“过一遍 sanitizer 就原样输出”。失败但没有公开映射时只给稳定中文概述，完整原文留 AgentProtocol。
- **R1 runtime bootstrap 静默成功**：配置/受管 Python 的正常 re-exec 是实现细节，不能在每个 public verb 前打印 `[research]` 或“正在使用运行环境”。只有首次创建运行环境确需等待时可给一条无内部标签的中文进度，失败时给一条无 traceback/内部路径的中文说明并让 Agent 诊断。
- **R1 安装器输出同一产品面**：Agent 常用的 noninteractive install/update/reinstall/uninstall 与交互向导执行同一 public projection；成功和 dry-run 只给简洁中文结果，不重放 `copy-project`/`clean-sync`、hash、内部相对路径或底层同步枚举。底层 stdout 可在进程内用于判断 no-change，失败细节由 Agent 诊断，不能因 `--yes` 绕过用户面。
- **R1 stale verification 可恢复**：canonical claims 或已绑定 evidence artifact 的字节变化后，confirmation 与 verification 必须 fail-closed 失效；若 claims 结构、evidence refs 与实质内容仍完整，唯一 classifier 回到 `ready_to_verify`，否则才回 `awaiting_agent_fill`。已挂 program 的 stale unit 也必须进入 `next` 的 Agent 重验证路线，不能因 attached-unit 去重而落入 review 不收、next 不推的 lifecycle dead zone；公开面只说“需要 Agent 重新核验证据”，内部 stage/命令仍留私有 protocol。

**R1 黑盒 gates**：installed copy 全 verb forbidden-token scan；paper/blog/repo 各跑 ingest→prepare→agent fill→verify→confirm→report 并断言 receipt claim_ids 非空；absolute/`..`/symlink evidence 拒绝；artifact 改字节后 confirmation 失效；失败 source 可重试且不 poisoned dedup；200 并发 events 零丢失；无关 dirty draft 永不被 checkpoint；TTY/非 TTY 语义相同；全量 tests + macOS installer smoke 绿。

### 治理分档 G0（2026-07-27 R1 锁定）

- 新初始化 workspace 显式写 `governance_profile: personal`；升级前已存在的 runtime preferences 若字段缺失或非法，一律解释为 `strict`，不能由默认值回填把旧工作区静默降档。用户显式切换才改变治理档。
- `strict` 保留既有行为：公开 review 每批最多 3 条、卡片固定 24 小时；eligible preference receipt、PortfolioDecision 与 D1 强脱敏语义逐字不变。
- `personal` 的公开 review 默认每批 10 条（必须实际大于 3），`review.card_ttl_hours` 可配且归一到 `1..168` 小时。一次 snapshot 必须冻结 effective profile、batch limit 和 expiry；apply 只消费该 snapshot 内的界限，不重读可变配置。两档都继续要求当前用户消息授权、真人 signer、逐字 evidence、content digest/CAS 与原子批量。
- D1 只在 `personal` 的 local-only canonical issue 中保留稳定的 `category / owner(skill) / operation / return_code` 明文字段，仍禁止原 stdout/stderr、绝对路径、用户原文、raw/evidence、环境变量、secret、邮箱与 traceback。`strict` 本地 issue 继续走现有强脱敏；任何导出无论档位都重新走强脱敏，workspace 字节不得原样透传。
- 治理分档只降低仪式成本，不影响 schema/evidence/confirmation/containment/journal/lock/CAS 等承重墙；AI 在两档都不可自签。

### 公开根路径与错误尾部 P1（2026-07-27 R1 锁定）

- 正常用户面和 owner 直连都不得打印 `[root]` 加绝对 project/KB 路径；解析到哪个根属于私有 AgentProtocol/诊断事实。需要消歧时只说“当前工作区/独立工作区”等不含路径的自然语言。
- 安装器和 dispatcher 不得把底层 stderr tail 原样投影到公开面。公开失败只给稳定中文类别与恢复动作；绝对路径、token、环境变量、内部相对路径、traceback 与底层命令只留私有诊断，并在记录/导出边界继续执行相应治理档的脱敏合同。

### 开发者诊断 D1（2026-07-19 用户实测后锁定）

目标不是遥测用户，而是给本地 workspace 增加一条**显式可选、低 token、可复现、可脱敏导出**的 skill 演化闭环。它复用 `skill-evolution-advisor` 的记录/复盘所有权与 `knowledge-base-manager` 的结构检查所有权，不新建会理解研究材料的脚本。

1. **强制安全门与可选诊断分离**：schema、evidence、confirmation、containment、journal/lock/CAS 等正确性门始终强制，任何用户配置都不能关闭。可关闭的是“额外记录、复盘与质量审计”。诊断关闭时，显式说“记下这个问题”的用户请求仍必须记录；关闭不等于拒绝用户写入。
2. **三档模式 + 逐 skill 覆盖**：`off` 不自动记录、不做 Agent 复盘；`errors-only` 只用确定性代码捕获 owner 非零退出、rollback/recovery、重复失败与显式用户纠正，不调用 LLM；`developer` 在前者上允许触发式短复盘与 patch handoff。workspace 有总模式，skill 可 `inherit|off|errors-only|developer` 覆盖；配置包含 `token_budget_per_task`、`max_issues_per_task`、dedup/cooldown 与 `local_only=true`。默认普通 workspace 为 `off`，开发者可自然语言开启；不允许后台无限复盘。
3. **结构化 issue 真源**：问题落 `kb/memory/skill-evolution/issues.yaml`，字段至少含稳定 id、category、severity、status、skill、summary、expected/actual、trigger、source(user|agent|runtime)、reproducible、occurrences、first/last seen、环境版本（bundle version/source commit）、脱敏 evidence/context 与 privacy classification。相似问题确定性合并并累加次数；新问题默认 `pending`，可 confirmed/dismissed/resolved；skill defect 永不自动改代码或 roadmap。
4. **捕获边界**：公开 dispatcher 在 owner 非零退出且策略允许时写一条 runtime issue；两档都禁止保存原 stdout/stderr、绝对路径、环境变量、用户原文、raw/evidence 内容、secret、邮箱或 traceback。strict 只保存经强脱敏的稳定错误分类和公开安全摘要；personal 可额外明文保留稳定的 category、owner(skill)、operation 与 return code，绝不放宽自由文本边界。确定性 redactor 必须同时覆盖键值型 secret、URL credential、环境变量赋值、邮箱，以及常见独立 credential 形状（例如 `sk-` / GitHub token / Slack token / AWS access-key 前缀），不能要求 secret 前面恰好出现 `token=` 才脱敏。Agent 遇用户纠正、可复用摩擦或 sanitizer fallback 时按 workspace 规则写 issue；深复盘只在 `developer` 且仍有预算时执行。一次失败不能反过来掩盖原业务 exit code，诊断写失败也不能改变主命令结果。
5. **分层、只读 audit**：保留现有 schema lint；新增机械 audit report，至少分为 `schema`、`integrity`、`recovery`、`security`、`quality`。第一版必须检测：现有 schema/link/program 双向问题；confirmed judgement 的 current receipt/artifact binding；未完成 journal；KB Git dirty 的产品拥有文件；paper 基础 metadata/taxonomy 明显空缺；figure 候选重复/可疑多字母标签；KB 内 symlink 越界。每条 finding 带 code/severity/path-safe subject/message，audit 自身字节级只读。journal 截断、旧 envelope、重复 key、symlink/special node 等“无法安全枚举 incomplete op”的情况也必须收敛成 path-safe recovery finding，不能让 audit 自己 `SystemExit`；错误详情与不可信 op id 不进入公开报告。语义矛盾、taxonomy 好坏、研究结论质量属于可选 Agent audit，不得由脚本拍脑袋判断。
6. **公开交互不增新伪 CLI**：继续只有 15 个 `kb <verb>`。用户说“检查知识库健康”时 Agent 私下跑 owner audit；`kb doctor` 可在私有 protocol 暴露机械 KB health 摘要，但公开面只给中文结果，不泄内部路径。用户说“开启开发者诊断”“关闭 paper-analyst 诊断”“仅在出错时记录”“对刚才失败做脱敏复盘”时由 Agent 写配置/issue；`kb recall` 可概述待审 skill defects，不把内部复现数据直接回显。
7. **隐私与导出**：所有诊断默认 local-only，无网络上传、无隐式 telemetry。导出必须由用户当前消息显式授权，并无条件用 strict 强脱敏重新生成 issue pack；personal 本地允许的四个稳定明文字段不构成绕过导出红线的授权。默认不含论文原文、逐字 evidence、用户消息、绝对路径、环境变量、secret 与完整 traceback。D1 只实现本地记录/审计/脱敏预览；第三方 issue tracker 上传属于未来独立授权面。
8. **恢复与版本合同**：issue 写入使用 workspace transaction、原子写、journal、树作用域 lock 与精确 checkpoint target；并发 50 次独立问题不得丢，近重复必须确定性合并 occurrence。audit 和 policy read 在未初始化 workspace 上零写；诊断失败不得创建半条 issue 或污染原操作 journal。

**D1 黑盒 gates**：默认 off 的失败命令零诊断写；errors-only 的真实 owner failure 生成一条脱敏 issue 且保留原 exit；同一失败重复触发 occurrence 增长而非刷屏；per-skill off 覆盖 developer 总开关；50 并发记录零丢；audit 对干净 KB PASS，对故意制造的 metadata 空缺、dirty owned fill、重复/伪 figure、stale receipt、incomplete journal、symlink escape 给稳定 finding，前后 tree digest 相同；public stdout forbidden-token scan 仍绿；全量现有 tests 绿。

**D1 实现与验收结论（2026-07-19，2026-07-20 Hosted CI 收口）**：三条 disjoint worktree 轨道已合入 `codex/d1-integration`；诊断 core、配置、dispatcher hook、分层 audit、Agent 规则与用户文档均完成。主 agent 在全新安装副本真实复现 off → errors-only → dedup → developer + per-skill off → 显式用户记录 → 脱敏 export preview，原业务 exit 与公开文案保持不变；50 并发独立/重复捕获测试分别确认零丢失与 `occurrences=50`。RT-2 与 OpenVLA 两个既有论文 workspace 各发现 8 项真实 recovery/quality finding，审计前后 tree digest 相同。首轮冷验收发现邮箱与独立 `sk-*` credential 未脱敏，主 agent 独立复现后以 `60d73e0` 加严邮箱及常见 standalone credential redaction；修复后全新安装副本 exact payload 冷复验通过，P0–P3 为 0。PR 首轮 Hosted CI 揭示测试错误假设 symbolic branch 必存在；`c6c5e3c` 在不改产品行为的前提下补 attached/detached 稳定断言与显式 detached provenance 回归。最终 838 tests、17 skill validator、compileall、installer shell syntax、pip check、diff check 及 push/pull_request Hosted Linux/macOS 10/10 checks 全绿；真实仓库 `kb/` 零改动。D1 不包含网络扫描、依赖/CVE 扫描、语义矛盾自动判断或第三方 issue tracker 上传。

### 渐进式初始化 I1（2026-07-20 用户实测后锁定）

目标是让第一次 `kb init` 既收集真正有价值的偏好，又不把初始化变成表单或阻塞门。现有配置字段和 headless 写入能力继续复用；I1 只收口公开文案、Agent protocol、运行规则与回归测试，不新增配置 owner 或第 16 个公开动词。

1. **结构先就绪，偏好不阻塞**：`kb init` 先幂等创建/修复 KB 骨架；成功后 workspace 可立即用于入库、检索和分析。确认人真实署名只在第一次 judgement confirmation 前强制，不能再用“初始化还差一项必填”暗示整个 KB 不可用；任何缺失偏好都不得伪造默认用户身份。
2. **明确二选一**：首次或仍缺确认人时，公开结果必须明确提供“现在设置（推荐）”与“先跳过”两条自然语言选择，并说明约 1 分钟、跳过后仍可开始使用、后续可直接说“补充我的研究偏好”。不得要求用户理解内部字段、flags、paths 或 owner。
3. **快速设置只问高价值信息**：用户选择现在设置后，Agent 在一个紧凑回合询问真实署名、输出语言/术语风格、研究方向、资源与重要约束，并展示版本记录节奏、链接自动化档位与讨论风格的当前默认值，允许一句“默认即可”。报告风格、协作边界、开发者诊断等高级/低频项按需后补，不在首次问卷里堆满。
4. **跳过是零偏好写入**：用户选择先跳过时，Agent 不写 sentinel、不把 Agent 名称当署名、不制造“已确认”记录；只确认 KB 可用，并在第一次真正需要用户确认判断时再询问真实署名。重复 `kb init` 或自然语言“补充我的研究偏好”都可继续设置，已存在值必须保留。
5. **Agent protocol 显式表达可延后**：缺署名时 protocol 状态表达“KB ready + optional setup choice”，而不是单纯 `needs_user_input`；next action 同时给出 configure/defer choices、快速字段、默认值、`human_name` 的 `required_before=judgement_confirmation` 约束及 headless apply 入口。Runtime Agent 必须先呈现选择，不能看到 `human_name` 就越过“先跳过”直接追问。
6. **TTY/pipe 完全一致**：脚本永远不 `input()`、不读 stdin；终端、pipe、Agent 调用得到同一公开语义。Agent 自然语言收集后私下 headless 落盘。公开输出仍只含自然语言与现有 `kb <verb>`，不得泄漏参数、内部路径或 machine status。
7. **完成态诚实且幂等**：已有真实署名时，纯 `kb init` 保持严格 no-churn，并简洁说明结构与基础偏好已就绪；显式补充任一偏好只更新该字段，不重置姓名、画像、link_autodrive、discussion_style、auto-commit、诊断或其他已存值。
8. **快速字段只写 canonical consumer path（2026-07-20 冷验收补强）**：公开问题仍把“资源与重要约束”作为一类，但 private protocol 必须给出可执行的逐字段 headless 映射，Runtime Agent 不得自行猜配置路径。真实署名写 `runtime-preferences.identity.default_confirmed_by`；语言写 `user-profile.preferences.language_preference`；术语与研究方向分别写 `user-profile.personalization.term_style/research_focus`；自然语言资源写 `user-profile.resources.quick_setup`，供 method-designer 现有 `profile.resources` consumer 直接读取；重要约束追加去重到 `user-profile.constraints`，不得覆盖已有约束。protocol defaults 同时读取这些 canonical 字段，并对已存在的旧 `personalization.resources`、`preferences.terminology_style/research_focus` 只做兼容读取。旧隐藏参数继续兼容，但 I1 快速设置不得再把下游需要的资源仅写进 `personalization.resources`。

**I1 黑盒 gates**：空 workspace 的普通/TTY/pipe/installed-copy `kb init` 均先创建结构再显示“现在设置/先跳过/后续补充”，且不出现“还差必填”、裸命令、flag、内部路径或 TTY 读取；protocol 明确 `ready_with_optional_setup`、configure/defer、逐字段 canonical headless 映射与 confirmation-time identity gate；选择跳过前后偏好文件 byte digest 不变；选择现在设置可在一个 headless apply 中保存四类快速信息并保留其他值；保存后的 resource statement 必须真实落在 method-designer 会消费的 `profile.resources`，constraints 追加去重且保留旧值，第二次 init protocol 必须回显非空 focus/resource/constraint 快照；重复 init 零 churn；首次 judgement confirmation 缺署名仍 fail-closed；全量 tests、17 skill validator、compileall、installer syntax 与 diff check 全绿，真实 `kb/` 零改动。

**I1 实现与验收结论（2026-07-20）**：隔离分支以 `bc43055`（行为/测试）、`3c6a1a6`（文档）完成首次实现；首轮冷验收发现资源/约束存在 alternate path 漂移，主 agent 复现后先补本节 canonical consumer invariant，再以 `f78a96e` 修复为顶层 `resources.quick_setup` + `constraints` append/deduplicate，并在 private protocol 明示逐字段 input mapping。主 agent 独立验证 installed-copy skip/configure、旧资源/约束保留、第二次 init no-churn、method-designer 真实读取、AI signer 拒绝与 confirmation fail-closed；最终完整 **842 passed**（5 条既有 SWIG deprecation warnings），17 skill validator、两个相关 skill quick validation、compileall、installer syntax、pip check 与 diff check 全绿，真实仓库 `kb/` 零改动。第二个全新上下文冷 agent 在两个全新 copy workspace 重走 skip/configure/TTY-pipe/治理负向路径，P0–P3 均 0，UX 9.6/10。三个 I1 提交已推送为 `codex/i1-progressive-init@f78a96e` 并创建 PR #3；未 merge、未 tag、未 publish，Hosted CI 运行中。

### 目标架构一张图（文字版）

```
                         ┌─ 伴读(C15) ─┐
   raw(真源, 含PDF真归档) │  陪练(C16)  │  ← evidence-pack 引擎（原则2+4）
     │                   └─ 大纲(C11) ─┘         │
     ▼                                           │
   units ──(原则1: agent产出+脚本验证evidence)──► 证据层(claim→evidence)
     │                                           │
     ├─► synthesis(C6 真综述: 谱系/趋势/gap, 带时间)◄┘
     │
   programs(spine) ──► reports(C10 自包含) ──► 注意力预算过滤(C19)
     │
   confirmation(原则3: 验内容 + 分轨道 + 可累积)  ← 治理红线不变(禁自签/必留evidence)
     │
   monitoring/自校正(C17/C18) ── 复查/矛盾/stale
```

---

## Part 3 · 功能设计（逐子系统）· 骨架待逐块确定

> 下面每个子系统列：**目标行为**（一句）· **agent/脚本边界**（原则 1）· **关键开放决策**（需你拍板）。
> 标 🔲 的是**待你确认的决策点**。我们一块一块过；先不填死。

### 3.1 入库 / 源管理（source-intake）

- 目标行为：任意源（URL/本地/arxiv/github）→ 轻量 canonical unit + **真归档源字节**（修 G7）。
- 边界：脚本取源/去重/备份/建骨架；agent 不介入。
- ✅ **决策（已定，分层方案 A）**：
  - **默认下载真字节**（修追溯地基），提供"不下载"可选项。
  - **源分层**：① arxiv → **优先下 HTML 版**：先 `arxiv.org/html/<id>`，原生 HTML 不可用时直连 arXiv Labs 托管的 `ar5iv.labs.arxiv.org/html/<id>`，最后才退化到 abstract 页；无需 PDF 解析、结构更好、人/AI 都好读。`ar5iv.org/abs/<id>` 只是会重定向到 Labs 的兼容别名，不作为抓取端点。ar5iv 不是实时服务且可能滞后，因此只做原生 HTML 的 fallback，不能提升为第一来源。② 非 arxiv 的 PDF → **轻量默认后端 PyMuPDF4LLM**（纯 PyMuPDF、无 torch、始终装、快）；③ **重后端（MinerU / Docling）= 可选**（表格/公式/复杂版面时值得，但依赖 torch + 首次下数 GB 模型 + 实用需 GPU，不默认装）。
  - 轻量路径（HTML + PyMuPDF4LLM）**无可选、始终可用**（贯彻"开箱即用"）；重 ML 工具诚实做可选，避免把 skill 包变成几 GB + torch + GPU。
  - **两套处理（B4）**：HTML 源图本就是独立文件（不裁剪），locator 用 section/anchor；PDF 源走裁图 + page locator。
  - **Markdown-first 材料层（2026-07-21 锁定）**：每个成功解析的 paper/blog/dataset-card/local text unit 必须在 `source/` 内生成**完整且不截断**的 `document.md`。人类与 runtime agent 默认读它；只有 materialization 缺失/降级、需要核验公式表格版面或图像内容时才 fallback 到原始 PDF/HTML/文件。Markdown 是统一阅读与引用面，不替代原始证据字节。
  - **材料目录合同**：原件继续保存为 `source.pdf`/`source.html`/原文件；统一阅读层固定为 `source/document.md`；图片附件固定在 `source/assets/`；`source-map.yaml` 保存稳定 Markdown block → PDF page/bbox 或 HTML anchor/asset 的确定性映射；`conversion.yaml` 保存 schema、源 hash、document hash、转换器与版本、状态和 warnings。四类派生产物都必须位于 unit 内，禁止绝对路径与 symlink escape。派生 bundle 必须先在同盘 staging 完整生成和预检，再统一发布，`conversion.yaml` 最后写作 commit marker；任一 immutable collision 或 I/O 失败不得留下半套 archive/map/assets/document。
  - **图片合同**：PDF 独立位图/版面图由轻后端抽取到 `assets/`，Markdown 保留原始图注并用相对路径嵌入；HTML 的 `src/srcset/data-src/data:` 与 inline SVG 尽力本地化，按内容 hash 去重，链接重写为 `assets/<hash>.<ext>`。不得把图片 Base64 内联进 Markdown，也不得在成功入库后依赖远程 hotlink；下载失败时保留绝对源 URL、标记 materialization degraded 并允许读原 HTML/PDF。AI 生成的图像解释只能是另行标记的 annotation，不能冒充原图注。
  - **三层 HTML 合同（2026-07-22 锁定）**：`source.html` 保存服务器原始响应字节，作为不可变证据，绝不为“看起来正常”而改写；`archive.html` 是确定性、自包含样式、资源已本地化的离线阅读页；`document.md` 是面向人类、AI 与 Obsidian 的规范化阅读面。三者职责分离，`document.md` 顶部同时链接原始响应与离线阅读页。`archive.html` 及其 hash/path 纳入 conversion/materialization manifest 与不可变碰撞保护，但不取代原始响应。
  - **HTML 候选质量门（2026-07-22 锁定）**：arXiv 原生 HTML 与 ar5iv HTML 在写入 canonical `source.html` **之前**检查 fatal 页面、`Untitled Document`、LaTeXML fatal/error marker、正文/章节实质与解析结果；只因 MIME 为 HTML 不得通过。fatal 或空壳候选不落 canonical bundle，继续下一候选；两个全文 HTML 都不合格时优先回退 arXiv PDF，PDF 也失败才保存 abstract 页并显式 degraded。用户显式给出的 arXiv `vN` 必须贯穿 HTML/PDF/abstract 候选，不能静默升级到最新版。可容忍的 LaTeXML 残留必须进入 quality metrics/warnings，使 materialization 不能伪装为 complete。
  - **HTML 媒体完整度门（2026-07-25 真实 RT-1 验收后锁定）**：对 arXiv HTML，候选“正文合格”还不等于可接受的离线阅读版本。materializer 必须记录 source image count、localized count、failure count 与比例；当至少 4 张图片且本地化失败达到一半时，该 HTML 候选在任何 canonical raw/derived bundle 发布前判为 selection rejection，先试下一 HTML，再试同 edition 的 PDF。每次 rejection/fallback 保存有界、去敏的 rationale。普通博客/用户显式 HTML 仍可保留 degraded remote-link fallback，不强行换来源。候选评估必须在同盘临时 bundle 完成；失败候选不得在 unit source 留下 `source.html/document.md/assets/conversion.yaml` 半套，最终 chosen raw + derived bundle 一次发布。
  - **来源适配与正文身份门（2026-07-22 冷验收后锁定）**：已知“页面壳 ≠ 正文”的来源必须先取其稳定原始内容端点，再考虑渲染 HTML。Hugging Face dataset URL 优先冻结其 dataset card `README.md` 原始字节并以 Markdown materialize；原始页面 URL 仍作为 canonical `original_uri`，实际内容端点记录为 resolved source。原始 card 缺失时允许退回 HTML/JSON-LD，但必须显式 degraded，且正文至少命中预期资源身份与 dataset-card 实质；推荐模型、导航卡片或客户端 shell 不得仅凭标题/MIME/少量文本通过 `complete/accepted`。该规则是确定性来源完整性判断，不代替 runtime agent 对数据集价值的理解。
  - **通用 HTML 主体选择（2026-07-22 冷验收后锁定）**：不能再用“DOM 中第一个 `<article>`”当正文。转换器必须在 `article.ltx_document`、`[role=main]`、`main`、候选 `article` 与 `body` 间按语义优先级、文本/段落/标题实质和链接密度确定唯一 reading root，并从 reading root 移除站点级 header/nav/footer/aside/form 控件；原始响应仍完整保留在 `source.html`，离线页与 Markdown 只呈现正文 reading root。若所选 root 相对页面实质过小或主要由链接/控件构成，质量门告警或拒绝，不能伪装为正文完整。
  - **跨格式结构完整性合同（2026-07-22 锁定）**：`document.md` 的格式正确性是 materialization gate，不以“文本能搜到”替代。HTML/LaTeXML 的 equation layout table 必须收敛为单个 display-math block（保留 equation number），不得泄漏为空 Markdown 表格；带 `rowspan/colspan` 或嵌套单元格的复杂数据表必须保留为安全 raw-HTML table，因为 pipe table 无法无损表达合并单元格。普通简单表仍输出 pipe table。PDF 后端产物同样过结构 lint，无法确定性修复的畸形表必须告警并降级，原 PDF 始终可回退。
  - **layout table 合同（2026-07-22 冷验收后锁定）**：只有真正的二维数据矩阵可转 pipe table。单格/单列且只用于包裹 `pre/code/figure/div` 的 table 是布局容器，必须解包为其语义子节点；禁止生成 `| | / |---|` 包围 fenced code、孤立 `|` 或空表格边框。统一 lint 必须检测 orphan pipe cell、跨 fenced block 的伪表格和空表；检测到且无法确定性修复时 materialization 至少 degraded，绝不能让 `malformed_pipe_table_count=0` 假装成功。
  - **已有 Markdown 合同（2026-07-22 锁定）**：转换只能修改真正的 Markdown image node；fenced/inline code（包括跨行 code span）中形似 `![...](...)`、`<img>`、`# heading` 的样例必须逐字保持，不能被下载、消毒或插入 block id。ATX 与 Setext heading 均生成稳定 block；源文件开头的 YAML front matter 不再落在生成 header 之后伪装成水平线，而是完整保留为折叠的“source front matter”阅读块，front matter block scalar 内的 `#` 不得截获正文 block ID。Markdown raw HTML `<img>` 进入图片本地化；其他 raw HTML 与离线页服从同一被动化边界，移除 executable element、事件属性、表单 action 与经 ASCII 控制字符混淆的危险 scheme。无法处理的 reference-style image 或本地附件必须显式告警，不能静默留下断链。
  - **纯文本合同（2026-07-22 锁定）**：`.txt` 的 Markdown-like 标记不是语义结构，阅读面必须按可换行的 literal text 显示，避免 `#`、`>`, `---`、`![...]` 被 Obsidian 二次解释；原始文本仍完整可检索、可逐字取证。
  - **被动离线页与统一 lint（2026-07-22 锁定）**：`archive.html` 是被动阅读面；除移除 script/style/template，还必须剥离事件处理属性、`javascript:` URL 与可执行 embed/object/iframe，不能因“离线”放松安全边界。HTML、PDF、Markdown、text 四条 materializer 均记录统一格式指标并检查 placeholder 泄漏、未解析 fragment、资源缺失、未配对 math/fence、畸形 pipe table；任何确定性问题进入 warnings，使 status 为 degraded，绝不伪装 complete。
  - **兼容性验收矩阵（2026-07-22 锁定）**：每轮至少覆盖真实 arXiv HTML（公式/引用/复杂表）、真实直接 PDF（页锚点/图片）、普通网页/博客（代码/列表/表格/相对链接）、本地 HTML（base/local assets）、已有 Markdown（front matter/code/image/setext）与纯文本（Markdown-like 字面量）。行为测试只在隔离临时 KB，旧真实 KB 不参与迁移或验收。
  - **HTML 规范化与验收（2026-07-22 锁定）**：任何相对链接/图片先按最终响应 URL + 文档 `<base href>` 解析；arXiv/ar5iv 优先提取 `article.ltx_document`，普通网页按上述主体选择器确定 reading root。MathML/LaTeX 在通用 HTML→Markdown 前用占位符保护，转换后逐字恢复，禁止把 `_`、反斜杠等 TeX 字符 Markdown 转义；图片 alt 必须消除 `![[...]](...)` 语法碰撞；内部 fragment 重写到稳定 source block，figure/caption 与多图分组不得无提示摊平成无结构图片流。落盘前至少校验占位符清零、图片语法、相对资源存在、内部 fragment 目标、公式定界、layout-table 泄漏与正文身份；任何可读但不完整的结果标 degraded，fatal 结果走 fallback。
  - **索引兼容**：本轮不破坏既有 `parse-cache.yaml`/verification receipt。parse-cache 继续是机器分块与逐字验证兼容层，可与 `document.md` 由同一次解析产生；新运行规则优先阅读 Markdown，但旧 claim/receipt 不自动迁移、不重签。后续若把 evidence 主 artifact 改为 `document.md`，必须单独迁移并重新验证。
  - **代码仓库边界**：仓库源码保持原文件树，不批量包进 Markdown。长期身份固定为 `repo_id + relative_path`；Obsidian 投影根据可信 `repo_root` 生成本地文件链接，只要求打开对应文件，暂不承诺精确行跳转。绝不把绝对路径写进 canonical identity，仓库移动后重新投影即可刷新本机链接。远程 repo URL 不能被 generic HTML adapter 静默落成不可扫描的伪 repo：runtime agent 必须先建立受控本地 checkout/snapshot，再以本地树入库；底层 intake 若收到远程 repo URL 必须在创建 canonical unit 前 fail-fast 并给出自然语言恢复方向。
  - 说明：Marker 有商用许可限制（机构收入 >$2M 需付费），故不入默认/推荐重后端。
  - **R1 事务边界**：先在 workspace 外的受控临时目录成功抓取/解析并形成候选 raw + parse-cache，完成 kind/source identity、用户授权、当前 preference receipt/hard fallback、containment 与 canonical task-context 校验后，才允许以事务把不可变 bundle 与 canonical record 一起提升进 workspace。任何 stale/wrong receipt、无效授权、解析或备份失败都必须对 workspace 零写入（包括 `.runtime/intake-staging`），不占 canonical id/dedup key；网络或本地源恢复后同一输入可重试。禁止“backup failed 但 exit 0 并创建 active unit”。
  - **R12 Agent 私有 prepare/add 握手（2026-07-25 锁定）**：若本次 intake 需要 Agent 选择 soft preference，owner 先用私有 `prepare-add` 在 workspace 同级 0700 临时根冻结 exact source/parse bundle，返回 opaque single-use token 与闭合 canonical context；Agent据此生成 `source-intake:add` receipt，再以同 token 执行 add。context 同时绑定 source 输入 identity/bytes、prepared bundle bytes、prepared record、候选/授权与最终 pool/maturity/title；提升前在 root transaction 内重验。token/JSON/flags/内部路径不得进入用户对话、Obsidian 或公共 projection；TTL、owner/mode/no-follow、条目/字节/深度预算、单次 claim、成功/失败清理均 fail-closed。无 soft selection 时同一 add 可自动完成外部 snapshot + hard-only resolution，用户不承担两阶段操作。
  - **R12 canonical duplicate 快路径（2026-07-25 锁定）**：若 exact source identity 已命中 current canonical unit，prepare 不得重新联网/复制/解析来源；它冻结并绑定既有 record 的普通文件 identity+bytes、当前候选/授权、source identity 与 value-free preference state。事务内再次重验同一 record/candidate binding 后只追加 selection provenance 并标记 duplicate，保留既有分析与 ConfirmationReceipt。若 duplicate 只在新 source snapshot/receipt 形成后并发出现，它不在原 task context 内，必须回滚并要求 fresh prepare，不能自动把旧 receipt 转绑到新出现的 canonical record。
  - **本地文本源**：`.html/.htm/.md/.markdown/.txt` 必须走本地 section parser 生成非空 parse-cache；不支持的文件类型明确非零失败。parse-cache header 从首次写入即使用通用 `unit_id`，任何 analyzer 只能兼容读取，不能原地迁移/规范化该证据文件。

### 3.2 论文分析（paper-analyst）

- 目标行为：论文入库直接生成类型适配的详细笔记；类型与每个要素都带 evidence，整份判断一次确认。
- 边界：脚本 prewarm/解析/裁图/**验 evidence**；agent 产出理解。
- ✅ **决策（已定）**：
  - **2026-07-27 R1 覆盖决定**：论文 quick screen 整体退役；新流程不存在“值不值得读”的字段、产物或独立确认步骤。下列 2026-07-17 screening-first 细节仅保留为历史背景，凡与本覆盖决定冲突者均失效。
  - **双入库模式**：① 我手动 add 的 = 默认我想读（可配置）；② 我给主题让你检索时 = 你列**待选 + 推荐入库项及理由**，我确认后入库。
  - **确认入库 / 我要求入库的论文 → 一律自动深读**（B2：这份 token 不省），产出**必含五要素**的完整笔记：**motivation / method / experiment / limitation / insight**（每条带 evidence）。
  - **成本原则**：`ask_first` 的轻量阶段只完成来源冻结与可续接状态，用户选择深读或 `auto_deep_read` 后才花理解 token；一旦进入深读，必须完成类型适配的五要素，不因省 token 给空壳笔记。
  - **类型适配**：纯 benchmark 不硬套单一 method，survey 不硬套 experiment；三套五要素由同一个 deep-read scaffold 表达，Agent 明确选择后脚本据此验证。
  - **✅ 决策（2026-07-17 锁定，2026-07-27 改为 deep-read 内分类）—— per-paper-type element sets**：
    - **类型来自 agent（原则1），不硬编启发式**：`complete-note prepare` 生成统一待填结构，agent 产出 `paper_type ∈ {method_system, benchmark, survey}`、分类理由与逐字 evidence，再只填写对应分支。verify 同时校验类型证据、所选五要素及未选分支为空，把 canonical 类型落 `deep_read.paper_type` 并生成独立 paper-type claim；无类型/非法类型/无证据均 fail closed。
    - **3 套要素集**（`NOTE_ELEMENTS` 从扁平 tuple 改为 `ELEMENT_SETS: dict[paper_type -> tuple]`）：
      - `method_system` = 现五要素 `motivation / method / experiment / limitation / insight`（不变，向后兼容）。
      - `benchmark` = `motivation / task_design / metrics / coverage_limitation / insight`（无单一 method）。
      - `survey` = `scope / taxonomy / trends / gaps / insight`（无 experiment）。
    - **要素路由 + claim_type + heading 同步按类型分**（`ELEMENT_TARGET`/`ELEMENT_CLAIM_TYPE`/`ELEMENT_HEADING` 也变 per-type）。新要素落 `core_content` 的合适字段（保证过实质门：`has_substantive_content` 是 section 级、不认 element key，故只需新要素至少一条落 `core_content` 即可；**注意 limitation/coverage_limitation 若落 `critique` 不算实质内容**——每套至少保证 motivation/insight 类落 core_content）。
    - **build/verify 按 agent 填写的类型迭代**：统一 scaffold 同时列出三套可填分支；verify 只接受 agent 显式选择的类型，按 `ELEMENT_SETS[type]` 验证 required elements/evidence/claim types，并拒绝未选分支混入内容。
    - **向后兼容**：老 paper 可从已有 `quick_screen.paper_type` 或既有 note 契约读取类型并继续验证；兼容读取不得写回或驱动新 unit 的 screening。新 paper 一律写 `deep_read.paper_type`。
    - **红线**：类型是 agent 判断（带 evidence、可确认），脚本只据类型选结构 + 验证，绝不自己"猜"论文类型（反模式 litmus：给一篇论文+无 agent 就吐 paper_type 的函数，删掉）。
    - **✅ 编排补强（2026-07-21 锁定，2026-07-27 覆盖）**：paper 的 agent protocol 固定为 `note prepare → note fill（type+对应五要素）→ note verify → 安全后续步 → 用户确认`。`kb ingest` 的机械前缀直接到 note prepare；protocol 不得再出现 screen fill/verify。note verify 已按 runtime preference 自动执行 refresh/figures 时，protocol 不重复列同一步，避免双跑和绕过 preference。
  - **✅ 已落地并端到端验证（2026-07-10，Wave3）**：paper.py 改成 `prepare`(空白待填结构，无关键词打分)+`verify`(逐字校验 agent 填的五要素证据后落盘)。demo 实证（AR-FB，temp 副本）：core_content 空→填、has_substantive_content False→True、编造 quote 被拒、G5 empty 64/65→63/65 & confirmed 0→1。
  - **✅ 决策（自动化打磨，2026-07-11）——note verify 后自动跑安全后续步**：`complete-note --phase verify` 成功持久化后，按 runtime pref 自动执行安全后续步，不再让 agent 手敲（自动化验收从 6.5 的根因）：
    - `auto_refresh_structure_after_note`（默认 **true**）→ 自动 `refresh-structure`（F-a 修好后只读 cache、安全）。
    - `auto_extract_figures_after_note`（默认 **false**）→ 自动 `extract-figures`（需 PDF backend；缺则跳过并提示，不报错；HTML 源无 figure 亦跳过）。
    - 受 `autonomy.auto_execute_scope`（GOVERNANCE_MAX_AUTO_STEPS 封顶）约束：refresh/generate 属安全自动步；配置收窄则相应不自动、改为在 stdout 给 NEXT FOR AGENT 导航。
    - **仍不自动**：verify（需 agent 先填）、confirm（治理闸口）——原则3/7 不变。
    - 效果：paper 入库链移除独立 screen 往返，仅保留一次 note fill/verify 和最终用户确认，呼应原则7“安全步自动、只在闸口停”。
    - **✅ 已落地并验证（2026-07-11，main f88206f/46d3b01）**：抽 refresh/figures 为共享 helper（复用不复制）；verify 后 `_auto_post_note_steps` 按 pref+autonomy gate 跑；真跑 AR-FB 实测：verify 后自动 refresh、**parse-cache 38→38 页不变**（F-a）、default 不跑 figures、autonomy 去掉 refresh 则改出 NEXT 导航。回归测试 test_auto_post_note.py 锁定。287 测试绿。

### 3.3 仓库分析（repo-analyst）

- 目标行为：能力地图 + 代码级复用判断（loss 在哪/训练入口/改哪）。
- 边界：脚本建 symbol/config/文件索引；agent 读索引产出能力边界+复用点。
- 🔲 决策：代码索引做到多深（文件级/函数级/config-key 级）？
- ✅ **决策（已定）**：入库时**文件级**即可（知道主要功能 + 能力边界）；当我提出**进一步要求**（如"loss 在哪/训练入口/改哪"）时，**深入到函数/符号级细读**。目标行为里承诺的代码级定位=按需触发，不在入库时全做。
- **D2 源适用性**：`scan-structure` 只接受 lexical local directory / Git checkout / 明确归档的源码树。普通 URL 的 HTML 快照目录、dataset/model card、项目主页都标记 `scan_applicability=not_applicable|unavailable` 并 fail-closed，不得把 `source.html`/`snapshot.md` 当代码树。机械扫描只更新派生事实与 scan receipt；若 canonical claims、verification evidence bytes 和 confirmable content 未变，必须保留现有 ConfirmationReceipt，禁止 owner 手工把整个 record 改回 pending。

### 3.3A 数据集分析（dataset-analyst，D2 新增）

- **✅ 决策：dataset 是一等 canonical kind**：目录 `kb/units/datasets/<d-id>/`，ID 前缀 `d-`，进入索引、检索、program、确认、报告与恢复合同；不再伪装成 repo 或 blog。
- **来源识别**：`huggingface.co/datasets/...`、本地 dataset card/manifest 或用户显式 dataset 均路由 dataset；Hugging Face model page不误判。历史上以 repo 落库的 dataset 走显式、journaled migration，保留 legacy id、history、links/program attachment；subject kind/id 改变使旧确认按 receipt 规则失效并要求一次真实用户重新确认，不能偷偷改 receipt。
- **分析契约**：脚本 prepare dataset profile 待填结构，runtime agent 填 `positioning / composition / schema_access / suitability_risks` 四个 judgement 要素；每要素必须挂 dataset card/parse-cache 的短逐字 evidence。脚本只校验、落盘和过门，不从字段名/页面关键词自动判断质量或适用性。
- **payload**：至少包含 `basic_info`、`source_search`、`profile{scale,platform,license}`、`composition{modalities,tasks,embodiment,scenes}`、`access{formats,splits,schema,entrypoints}`、`quality{known_issues,constraints,risks}`、`reuse{supported_uses,unsupported_uses}`、`state{profile_status}`、canonical claims 与 verification receipt。
- **工作流**：`source_ready → awaiting_agent_fill → ready_to_verify → ready_for_review → done`；`kb ingest` 机械前缀只到 dataset prepare，agent 在同一回合 fill+verify，用户确认处停。
- **迁移红线**：不得用目录扫描替代 dataset schema/access 分析；不得在升级时无提示重写真实 `kb/`；migration 必须可 dry-run、显式 apply、journal/lock/CAS/undo，并重建索引。

### 3.4 博客分析（blog-analyst）

- 目标行为：核心内容 + 可信度（事实 vs 观点）+ 可复用解释段。
- 边界：脚本取文/切段；agent 产出 claim/可信度。
- 🔲 决策：博客源多样（网页/公众号/PDF），取文范围与失败降级？
- 博客一般指的是网页内容，对于多媒体数据暂不处理

### 3.4A 外部文献检索（literature-search，2026-07-24 重构锁定）

- **✅ 命名与边界**：R5 加入的第 19 个 shipping skill 对外统一叫 `literature-search`（R6 再加入 `research-monitor` 后 bundle 共 20 个）。它负责把用户研究问题或 program evidence request 变成**由 runtime Agent 执行的有界、多轮文献检索**，只写 `kb/synthesis/source-search/<stage-id>.yaml` 候选 staging；不创建 canonical paper，不替 `paper-analyst` 阅读全文，不替 `literature-synthesizer` 生成综述，也不把 citation count、venue、作者声誉或搜索排序当相关性/质量事实。旧 `literature-scout` 名称和 OpenAlex 专用入口退出当前产品面。
- **✅ 检索能力归 Agent，不设固定 provider，也不要求付费凭据**：skill 不绑定 OpenAlex、Semantic Scholar、arXiv、Serper 或任何 SDK，也不维护 provider 规则表。安装和核心检索不得要求用户配置外部 API Key、购买检索额度、订阅数据库或安装付费插件；runtime Agent 先使用当前宿主已经提供且无需为本系统另行付费/配 key 的 web search、browser、connector 或其他只读发现能力，再基于问题、可访问性、结果覆盖与成本选择一组工具，并为每个 query event 记录 `channel/tool/selection_reason/searched_at/result_count/outcome`。可选外部能力只能渐进增强，缺失时不得让 init、既有 KB 检索、分析、review、survey、report、monitor、恢复或 GitHub-link 安装失效。没有任何可用外部发现能力时，以 `blocked_no_search_tool` 保存已完成进度并通俗说明边界，不索要密钥、不推荐付费才能继续，也不伪造空成功。脚本只校验和持久化 Agent 已取得的结构化结果，绝不理解论文或自行联网。
- **✅ 两种用户意图、三种诚实标签**：普通“找几篇/补文献/搜相关工作”默认 `exploratory`，承诺有界发现，不宣称穷尽；只有用户明确要求系统综述、系统检索或可复现检索时才进入系统模式。若当前工具不能固定数据库、查询式、时间、结果深度和筛选流程，标为 `bounded-systematic` 且永远 `partial=true`；只有这些合同都可复现时才标 `systematic`。systematic-family 必须冻结 inclusion/exclusion、date/language/source-type、channels/queries/result depth 与筛选方法。单 reviewer 继续使用兼容筛选轨；多 reviewer 已由 R6 开放为逐 reviewer append-only decision/disagreement/adjudication ledger，必须冻结 reviewer registry、独立性标签和 canonical phase order，不能把同一执行上下文伪装成独立复核。terminal stop（除 no-tool 阻塞）保存当前完整 flow，非 user-stop 至少有一条真实 query event；systematic 每条 query 都有 `reproducible=true`，二者每条 query 都有带时区的 `searched_at/result_depth/result_count`。query usage 必须等于 event ledger；`identified == Σ result_count == discovery occurrence count`，且每个 query 的 result_count 分别等于引用它的 discovery occurrence 数；duplicates 等于 occurrence 减唯一候选，非 duplicate 候选全部保留。flow 必须算术自洽并与 automation/title-abstract/fulltext/unavailable/include screening 及 full-read 账本相符。不得靠自报 `reproducible`、幽灵候选/重复项或全零计数用 PRISMA 外观包装普通 web search。
- **✅ Agent 检索循环**：①锁定问题、范围、模式与硬预算；②把问题拆成互补 facet，生成 seed/terminology/method/benchmark/survey 查询；③并行执行彼此独立的查询并按批次原子暂存；④Agent 基于 title/abstract/fulltext 明示证据做 include/maybe/exclude 初筛，snippet 只能证明“发现过”而不能支撑论文主张或实质相关性结论；⑤从高价值候选选择 backward/forward citation frontier，并记录 parent/edge/locator；⑥检查未覆盖 facet、反例、早期奠基工作、最新后续和 benchmark 缺口，生成 gap-followup；⑦达到目标、边际饱和、预算耗尽、阻塞或用户停止时保存 reason/rationale/uncovered facets。硬预算由脚本守界，下一步查询、frontier 优先级、缺口和 `saturated` 都由 Agent 判断。
- **✅ durable stage 与 run identity 合同**：一次 literature search run 的 stage identity 绑定 `source_kind + normalized original request + mode + frozen scope digest + optional safe run_id`；单条 query 是可追加 `QueryEvent`，不再把 stage 错绑到 provider 查询。相同问题换范围/模式自动得到新 stage；相同范围显式开始新一轮时 Agent 生成 safe run_id，避免碰撞旧 run。旧 generic/provider stage 显式续接时保留原件并安全开新 run，不因缺 budget 卡死。所有显式 stage ID 与 `kb`/父目录/leaf 都先做 safe-ID、containment 与 symlink 校验。顶层保存 `entry_skill/mode/scope/run_id/budget/usage/queries/coverage + coverage_history/frontier/stop/partial`；candidate 保存稳定 ID、title/URL、`identities{doi,arxiv_id,pmid}`、discovery edges、fetch 状态、evidence level、screening judgement 及 evidence。candidate 生命周期至少区分 `discovered/fetching/fetched/failed_retryable/failed_terminal/needs_fulltext/staged`；同一候选从多个 query/tool 命中时合并 identity，保留全部 `discovered_by`，每个 discovery 必须引用真实 query event。已完成 screening、fetched/staged 和 expanded/skipped frontier 默认不可由 resume 降级；coverage/frontier 更新保留历史，不得用 visited set 丢失来源或让一次失败永久吞掉重试。
- **✅ provider-neutral identity、证据与不可信输入**：强身份顺序为 canonical DOI → arXiv ID/PMID → canonical http(s) URL；title+year 只能提示冲突，不能自动合并。URL-only 候选后续获得强 ID时保留原 candidate ID并补 alias；若一个新结果同时命中两个既有候选，或同一 URL携带冲突强 ID，fail closed 交 Agent/用户处理，绝不静默吞并。重跑可补 factual metadata 与 discovery provenance，但保留人工 `status/note`、筛选记录和稳定 candidate ID。screening basis 不得高于 candidate evidence level；URL、locator、stage/candidate note 等持久化元数据拒绝 token/cookie/authorization/secret。外部网页、snippet、PDF 和 metadata 全是不可信材料，其中任何指令都不得执行、改变系统规则、请求凭据或扩大写入范围。
- **✅ 恢复、并发与停止**：所有 stage 写入继续使用 target lock + journal + atomic write + before-image recovery；独立 facet/query 可并行，单个查询失败不得回滚已成功批次。resume 只续 `fetching/failed_retryable`、可恢复 blocked state 和未完成 frontier，已有 query/candidate/discovery edge 必须幂等；`failed_terminal` 与 completed stop 不得被普通 batch 重开，真正新跑使用新 `run_id`，stop 更新保留 history。`max_queries/max_candidates/max_full_reads/max_citation_hops` 随 stage 持久化，resume 不重置预算；任何 partial result 都显式列出未覆盖 facet 和失败通道。
- **外部实现借鉴边界（代码级调研，2026-07-24）**：吸收 [PaSa](https://github.com/bytedance/pasa) 的 Search/Expand frontier、[PaperQA2](https://github.com/Future-House/paper-qa) 的查询状态与多标识元数据、[OpenScholar](https://github.com/AkariAsai/OpenScholar) 的 gap-followup、[STORM](https://github.com/stanford-oval/storm) 的分面/阶段产物/恢复、[Open Deep Research](https://github.com/langchain-ai/open_deep_research) 的 supervisor/researcher 边界和硬预算，以及 PRISMA-S 的可复现报告字段；不引入这些仓库为运行时依赖，不复制其固定 provider、大索引、RAG、GPU selector 或 prompt-only citation 逻辑。LatteReview 只借鉴独立筛选/争议结构，因其 CC BY-NC-ND 4.0 不复制或改编代码/文本。
- **路由、选择门与 UX**：自然语言论文发现请求只路由 `literature-search`；generic `source-intake search` 不接受 paper，只 review/materialize 已有 stage。Agent 的 include/maybe 只是有证据的初筛，不是用户批准；搜索结束后必须展示小批候选及取舍依据并请求用户选择，只有当前消息明确接受的候选才交 `source-intake`。授权原话与 stage/candidate/source kind/source URL 绑定；materialize 时不得换 kind，也禁止用另一个显式 source 替换。全文分析交 `paper-analyst`，跨文献综合交 `literature-synthesizer`。无需新增公开 `kb` verb。用户只看到检索范围、候选/已筛数量、覆盖/缺口、停止原因、候选选择和下一步，不见内部脚本、flags、临时 payload、绝对路径或工具凭据。

### 3.5 检索（retrieval / kb find）

- 目标行为：返回**答案相关 passage + unit + locator**，不是标题列表（C5）。
- 边界：纯脚本（passage 索引 + 排序）；不重造语义检索（82 单元 lexical 够）。
- ✅ 决策：使用 SQLite FTS5 可丢弃 cache；同语种与 CJK/ASCII 混合 token 走 lexical，跨语言语义由 Agent 阅读，不伪装 embedding/翻译能力。
- ✅ **决策（已定）**：检索有两个消费者，分开处理——
  - **① agent 答题路径**（伴读/陪练/综述/报告在会话里需要拉证据）→ **交原生 agent 能力**（Grep/Glob/Read + 读 parse-cache 拿页码做 evidence）。不自建语义索引：免维护、免 stale，agent 比词级排序器聪明。**这直接砍掉一大块检索工程。**
  - **② 人在终端 `kb find`**（无 agent 在场）→ 脚本，R3 升级为 passage 级 lexical retrieval；语义/embedding 仍不做。
  - **✅ R3 落盘决策（2026-07-23 锁定，冷验收加严）**：使用标准库 SQLite FTS5，缓存位于 `kb/.runtime/search/passages.sqlite3`，不进入 canonical Git/checkpoint。每条 passage 保留 `unit_id/kind/title/artifact/locator/text/source_digest`；正文按 Markdown heading 与段落确定性切分，过长段按固定字符窗且有 overlap，禁止脚本摘要/改写。FTS5 使用 `unicode61` 与 BM25；unit title/summary 仅为 display metadata，设为 UNINDEXED，并各有独立 title/summary passage；heading 权重大于 body，禁止 title-only match 提升同 unit 的无关正文。SQLite 官方说明 BM25 数值越小匹配越好，external-content 表要求调用方维持一致性，因此本系统不用 external-content/trigger 双表，而以完整临时数据库构建后原子 replace，避免影子索引漂移（[SQLite FTS5](https://www.sqlite.org/fts5.html)）。
  - **✅ 对抗复审加严（2026-07-23；post-fix 收紧）**：standalone Obsidian block ID（如 `^source-*`）是 locator metadata，不是可检索正文；extractor 必须复用 canonical block-ID grammar，在 fenced code 外跳过 anchor 行，同时保留其前后真实 paragraph 与准确 locator。cache health 先验证 cache 自身 metadata/table/digest/schema 一致性，再与当前 canonical corpus 判 stale：非法 numeric fields、非 64 位小写 SHA-256、非 `kb/units/**` project-relative artifact、自洽重算后的 passage/source tamper 均为 `corrupt`；只有 canonical bytes/schema revision 的合法变化才是 `stale`，两种状态都继续纯读 fallback。
  - **stale 与纯读合同**：cache metadata 绑定 schema revision + 当前 records/被索引 artifact digest。`build_index`/显式 index mutation 安全重建；`kb find` 自身字节级只读，cache 缺失/损坏/stale 时用同一 deterministic passage extractor 做内存 lexical fallback，不在查询路径偷偷写盘，并在私有 protocol 标记 index health。查询结果返回最多 5 个答案相关 passage，每项含 unit、短摘录和可复开的 project-relative locator；公开输出不得泄漏绝对路径或内部 score。
  - **中文边界**：`unicode61` + 现有 CJK/ASCII tokenizer 支持同语种 lexical 命中与中英混合 token；不宣称中文问题能自动召回纯英文同义词。跨语言理解继续由原生 agent 读 evidence 完成，避免伪装成 embedding 能力。
  - **cache 安全**：拒绝 symlink/非普通文件目标；构建只遍历 canonical unit containment 内的 record/Markdown/parse-cache 可读面，不跟随 symlink，不索引 `.journal/.runtime/raw/output/obsidian`；任何失败保留旧原子 cache，canonical KB 不回滚也不受损。

#### 3.5.1 无插件 Obsidian 知识网络适配层（2026-07-21 锁定）

- **定位**：canonical `kb/units/**/record.yaml`、program state、taxonomy 与 evidence artifacts 仍是唯一事实源；Obsidian 不是第二个数据库，也不直接接管 confirmation/revision/journal。第一阶段**不开发、不依赖任何 Obsidian 插件**，只生成 Obsidian 原生可读的 Markdown、Properties、Wikilinks、Backlinks、Graph 与 Bases。
- **Vault 与投影边界**：用户把 `kb/` 作为 Vault 打开；系统只管理 `kb/obsidian/managed/`，其中按 `units/`、`programs/`、`topics/`、`dashboards/` 输出稳定页面和 `.base` 文件。`kb/obsidian/inbox/` 与 `kb/obsidian/annotations/` 属于人工区，投影器只确保目录存在，永不覆盖、清空或迁移其中内容。不得生成或改写用户的 `.obsidian/` 配置。
- **稳定身份**：unit 页面文件名固定为 canonical unit ID，program/topic 页面使用稳定 slug，标题只作为 `aliases` 与展示文本。生成页带扁平 frontmatter（Obsidian Properties 不支持嵌套属性），至少包含 `id/kind/title/aliases/status/maturity/confirmation_status/topics/programs/managed_by/source_path`；frontmatter 内部链接必须是带引号的 wikilink 字符串。
- **细粒度链接**：canonical `links[]` 支持可选 `source_locator` 与 `target_locator`，locator 形状为 `{kind: unit|heading|block, value: <稳定值>}`。`heading` 投影为 `[[id#标题]]`；`block` 投影为 `[[id#^block-id]]`。canonical claims 使用原 claim ID 生成可读且稳定的 block ID；每条 evidence 引用生成由 claim ID + 序号确定的稳定 block ID。块 ID 仅允许拉丁字母、数字与连字符，非法输入必须规范化或审计拒绝。
- **有向关系唯一存储**：canonical record 只保存调用者声明的正向边，不再复制 `reverse:<relation>` 到目标 record。共享 relation registry 定义 `cites↔cited_by`、`builds_on↔extended_by`、`implements↔implemented_by`、`uses_dataset↔used_by`、`supports↔supported_by`、`contradicts↔contradicted_by`、`part_of↔contains`；`related_to` 与 `similar_to` 为对称关系。Obsidian Backlinks 与投影图在读取时推导反向边。旧 `reverse:*` 只作兼容输入：若有匹配正向边则折叠，不写回；无匹配边时保留为 legacy-derived 视图并在 audit 提示迁移，禁止静默丢关系。
- **投影内容**：unit 页必须包含摘要、元数据、program/topic 链接、类型化 outgoing/incoming relations、canonical claims 和逐字 evidence 摘录；claim/evidence 块可被其他页面精确引用。program 页从 state 投影 active units/goal/next actions；topic 页列关联 units；Home 页给入口与更新时间。Graph 的人类默认节点保持 unit/program/topic 粒度，claim/evidence 只通过块链接按需进入局部阅读，不生成全局“毛线球”节点。
- **人类入口与健康摘要（2026-07-22 冷验收后锁定）**：Home 首屏必须回答“库里有什么、现在最该看什么、哪些材料有问题”，至少含按 kind 计数、待 agent 填/待确认数量、degraded/failed materialization 数量、最近更新单元和三个 Bases 入口。unit 页顺序固定为：真实标题 → 一句话摘要 → **Read material / Open original** 快捷入口 → 来源健康（complete/degraded、warning 数、正文长度、图片本地化情况）→ 当前分析阶段与下一步 → taxonomy/relations/claims → 低优先级实现元数据。不得用通用 `Lightweight <kind> intake` 冒充摘要；没有实质分析时明确写“已入库，尚待 AI 分析”，不得把 materialization 完成、record maturity、analysis readiness 与 human confirmation 混成一个“complete/pending”印象。
- **摘要所有权**：source intake 只归档、转换和索引，必须把 canonical `summary` 留空；只有 runtime agent 基于材料与逐字 evidence 才能写入实质摘要。投影视图负责把空摘要表达成“待 AI 分析”，不得由脚本生成貌似理解过材料的占位摘要。
- **展示属性最小化**：Bases 所需扁平 properties 可保留，但 `source_path/managed_by` 等实现 provenance 不应占据普通用户首屏；它们进入页面底部“Technical details”或 manifest。面向用户的状态使用自然语言标签，canonical enum 可作为次级细节。源 `document.md` 仍保持稳定文件名合同；用户默认从 unit 页的别名链接进入，不要求在原始文件树里猜 `document`。
- **材料入口与本地代码链接（2026-07-21 扩展）**：paper/blog/dataset 等 unit 若声明 `source.markdown_path`，投影页必须给出 Vault 内 `document.md` 的稳定 wikilink；原件由该 Markdown 页用相对路径打开。repo evidence/entrypoint 以 `repo_id + relative_path` 为身份，投影时仅在可信 repo root containment 内生成本机 `file://` 链接；不存在、越界、symlink escape 时只显示文本并报审计，不拼接危险 URI。外部 GitHub URL 不是默认代码导航面。
- **Bases**：生成至少“全部单元”“待确认”“按主题”三个原生 `.base` 面板，只筛 `obsidian/managed/units` 下 Markdown，字段来自扁平 properties。`.base` 必须是符合 Obsidian 官方 Bases schema 的 YAML；不引入 Dataview 语法。“待确认”必须消费与 Home/`kb review` 相同的派生 `analysis_stage=awaiting_confirmation`，不得直接按 record-level `confirmation_status=pending_user_confirmation` 过滤，否则尚待 AI 填写、没有可确认 claim 的 skeleton 会被误列为人工待办。
- **Bases 语义收敛（2026-07-22 冷验收后锁定）**：renderer 必须直接生成 Obsidian 1.12.7 保存后采用的 canonical property spelling（`title/kind/topics/...`，不再生成会被应用自动改写的 `note.*`）。升级旧 renderer 时，如果磁盘 `.base` 与旧 manifest hash 不同、但与新 renderer 的 desired bytes 相同或经受控 `.base` 规范化后语义等价，则视为应用自身收敛并安全接管新 manifest；除此之外的人工内容仍 fail-closed。投影更新必须满足幂等：`update → Obsidian 打开/保存 → update` 不产生 drift、阻塞或循环改写。
- **更新与恢复**：`kb obsidian update` 是显式、无参数的可重建更新入口；使用原子写，先生成内容与 digest，最后提交 manifest。清理仅限“上一版 manifest 明确拥有、且仍位于 managed 根内”的过期文件；遇 symlink、类型变化或人工漂移 fail-safe 保留并报告。中断留下旧 manifest 时 `kb obsidian status` 报 stale，可安全重跑。投影更新不得改 canonical records、confirmation receipt、evidence artifacts 或人工区。
- **审计**：`kb obsidian status` 纯读，报告未生成/最新/stale；检查 canonical input digest、manifest-owned bytes、缺失目标 unit、失效 heading/block locator、非法 block ID、旧反向边、managed 区人工漂移及断裂 wikilink。canonical 目标不存在或 locator 无法解析为 FAIL；投影未生成/stale、legacy reverse 与人工漂移为 WARN；空 KB 未投影可明确说明但不创建目录。
- **交互合同**：用户可见面只出现自然语言与 `kb obsidian update` / `kb obsidian status`，不暴露 Python、脚本路径、flags 或内部 protocol。Agent 在 canonical mutation 完成且没有治理闸口待处理时可自动执行安全投影更新；纯读取、待确认或失败路径不得借刷新投影掩盖 canonical 状态。
- **阅读视图与无损渲染（2026-07-21 真实 Obsidian 1.12.7 验收补强）**：生成页的目标消费面是 Obsidian **Reading view**；编辑/Live Preview 模式按 Obsidian 原生行为会显示 wikilink、反引号与 `^block-id` 源码，系统必须在 Home/用户文档中明确提示右上角书本入口，但不得通过写 `.obsidian/` 强改用户默认模式。canonical 标题、摘要、claim、relation note、evidence quote 等动态正文必须经 injective Markdown-safe renderer：至少保证 `<name>` 不被 HTML 吞掉、glob/乘号 `*` 不触发 emphasis、方括号/反引号/反斜杠不伪造结构，阅读视图显示的字符信息与 canonical 单行语义一致。frontmatter 内部 wikilink 必须物理保持单行，禁止 YAML width 自动折行。manifest 带 renderer revision；渲染规则升级必须令旧投影报 stale 并可重建，不能因 canonical input digest 未变而错误 no-op。
- **论文内部引用紧凑化（2026-07-23 用户实测补强）**：HTML/arXiv 的 citation group 常由外层字面 `[` 紧贴首个 Markdown link `[`，若直接生成 `[[12](#^... "full title"), ...]`，Obsidian 会与 wikilink 起始语法冲突，并在编辑/Live Preview 中把整组 target 与冗长 title 展开。规范化 Markdown 必须转义 citation group 的外层开括号，保留可点击的编号链接，并移除指向同文档 block 的冗余 `title` 属性；正文显示保持 `[12, 28, ...]`，点击仍跳到本地 bibliography block，完整题名仍由 bibliography 条目与不可变原 HTML 保存。不得靠截断题名或删除引用解决。
- **后续而非本轮**：中文 BM25、embedding、图遍历融合、KB MCP 与 Obsidian thin plugin 保留为独立演进；第一阶段不得把语义相似建议写成 confirmed canonical edge。

**实现与验收结论（2026-07-21）**：新增共享 relation registry、heading/block locator、forward-only canonical link 写入、legacy reverse 折叠，以及 journaled/manifest-owned Obsidian projector + read-only audit；投影包含 Home、unit/program/topic 页面、claim/evidence block、三份原生 Bases，并接入第 16 个公开动词 `kb obsidian update|status`。独立 diff 审查额外补住首次投影前 unowned managed 内容漏报、人工区危险类型、外部标题/heading 换行注入，以及 unit→program、program→active unit、evidence→source unit 三类断链审计。隔离发布快照最终 **873 tests 全绿**（858 个非 socket + 15 个 localhost auth），官方 `kb-cli` skill quick validation、AST、shell syntax 与 diff check 通过。能力包后续按用户明确授权安装到 `/Users/czx/Documents/knowledge_base` 的受管代码/规则区，installed-copy 临时空库 smoke 通过；真实 `kb/` 全树 digest 前后相同，没有生成 `.obsidian/` 或真实投影。shipping skill 未被用作设计/施工依据，仅在隔离临时目录作明确行为测试。

**真实格式 finding 闭环（2026-07-21）**：用户在真实 Vault 的编辑视图发现源码式双链、反引号与 block ID；验证确认这些是 Obsidian 编辑模式的原生表达，但 Reading view 又暴露 `<name>`、glob `*`、方括号/反引号等 canonical 字面量被重新解释，以及长 wikilink property 被 YAML 折行。renderer revision 2 现统一转义动态正文、对 frontmatter/Bases 禁止物理折行、隐藏本地临时来源路径、改善 claim/evidence 标签，并在 Home/用户指南说明书本图标；旧 manifest 会报 stale 而非 no-op。隔离发布快照最终 **875 tests 全绿**（860 个非 socket + 15 个 localhost auth），真实 18-unit/1-program 投影重建后 status PASS；真实 canonical 与人工 Obsidian 区摘要前后完全一致，Reading view 目测确认 `scripts/train/psi0/*.sh`、`<name>`、代码和逐字 evidence 均无损显示；投影器未生成或直接改写 `.obsidian/`，验收只通过 Obsidian UI 将当前标签切到阅读视图。

**2026-07-22 端到端 UX 验收门（锁定）**：完成定义不再是“测试绿 + bundle hash 闭合”。必须在安装目标上从空工作区执行完整 `install.sh`、`kb init`、doctor/status、至少一篇带公式/图片论文、一篇复杂技术 HTML、一个动态 dataset card、一个远程 Markdown 与一个本地 repo 的真实入库；再执行 Obsidian update，实际打开 Home、All Units、每类 unit 页和 `source/document.md` 的 Reading view，核对标题、摘要、代码、公式、图片、表格、链接、反链、警告与信息密度。随后再次运行 Obsidian update，确认应用自动规范化不会造成 drift。冷验收 agent 必须使用全新上下文，把 shipping skill 仅当被测产品；每个 finding 由维护者独立复现后才修复，最终同一流程复验通过。

**2026-07-22 冷验收 UX 补充决策（锁定）**：Obsidian 派生视图必须消费 `user-profile.preferences.language_preference`；显式中文偏好时，Home、unit/program/topic 页、Bases 列名与状态说明统一使用中文，未配置或非中文偏好保持英文。没有 `document.md` 的本地 repo 不能显示成“无可读入口”：Quick access 必须给出 vault 内 README（若存在）、常见工程入口文件与源码目录的可点击本地入口，但不把绝对临时路径直接展示为正文。HTML 阅读根中指向已被裁掉或本就不存在的 fragment 不代表正文丢失：远程源应把这类链接外部化回在线原页，避免仅因局部上游锚点缺失把整份材料标为 degraded；转换 receipt 记录 externalized fragment 数量供诊断。`kb add/ingest` 识别到远程 repo 时必须在 owner 调用前 fail closed，公开说明“需先由 AI 建安全本地只读快照、当前未创建条目”，并在私有 protocol 给 agent 可续接动作；不得只显示泛化“入库失败”。

**来源标题边界补充**：Markdown/Hugging Face 数据卡的 heading 解析必须先剥离 YAML frontmatter，绝不能把 closing `---` 当成 Setext underline 而把前一行字段（如 `dataset_size`）识别成标题；HF 数据卡优先使用显式 `pretty_name`，否则使用正文首个真实 heading。该标题只作为来源元数据与导航，不是内容理解。

### 3.6 综述（literature-synthesizer）

- 目标行为：方法谱系 + 趋势 + gap + 争议，**区分 observed/inferred 且列证据集**（C6）。
- 边界：脚本拉 evidence spans；agent 做谱系/趋势归纳。
- 🔲 决策：综述的"趋势/gap"如何带时间戳、如何标 stale？
- ✅ **决策（已定，调研后定案 2026-07-09）**：综述落成**可复用结构化模板**，而非自由生成。定案三点：
  - **A. 采用标准 survey 骨架**（学界通用 + 适配我们 evidence-first）：① 范围与定位（这个方向是什么 / 边界 / 和已有综述比新在哪）② 背景与术语 ③ **taxonomy（分类框架）= 核心**，正文按 taxonomy 维度组织（方法/系统/应用/框架 四种组织法之一，按方向选）④ 跨切议题（datasets / benchmarks / 共用指标）⑤ **趋势**（时间线：A→B→C 怎么演进）⑥ **gap / 争议 / open challenges** ⑦ 结论。
  - **B. evidence-first 硬约束（对治 LLM 综述通病）**：调研证实 LLM 生成综述**平均比人类低 21%**，通病=**浅综合、覆盖漏、citation 不忠实、只罗列不对比**。所以我们的综述**每个 taxonomy 单元格、每条趋势、每个 gap 都必须挂 evidence_refs**（原则 2）；**明确区分 observed（有据）vs inferred（AI 推断）**；产**对比表**（方法×维度矩阵）而非并列摘要——直接压掉"只罗列不对比"这个最大通病。
  - **C. 时间维度 / stale**：综述头记录**生成时的 KB 锚点 + 覆盖的 unit 集 + 时间戳**；趋势/gap 标 `as_of` 日期；当 KB 新增该方向的 unit 时，navigator 提示"这篇综述可能过期"（呼应 3.13 反应式，不做定时扫描）。
  - **落地形态**：literature-synthesizer 产**模板化 survey**（脚本拉 evidence spans + 搭 taxonomy 骨架 + 建对比表框架；agent 填谱系/趋势/gap 的实质判断并挂据）。模板细节留 SCHEMAS.md / 施工时定，本文件只锁这三点原则。
  - **✅ R3 stale consumer 合同（2026-07-23 锁定）**：`kb_anchor.units[]` 除 id/kind/title 外必须保存 canonical record content digest、confirmation receipt digest 与被引用 evidence artifact digests；prepare 在事务内从当前 bytes 生成 anchor。verify 必须重新定位每个 canonical unit并逐项比较，任何删除、身份变化、content/confirmation/evidence digest 变化都 fail-closed，禁止把基于旧输入的 fill 发布成新 survey。
  - 已 verify survey 保存 `consumer_binding`（selection filters、unit ids/digests、verified_at）。navigator/report 等读侧以纯读 helper 重新计算：相同 selection 新增匹配 unit、已有 unit 变更/删除、confirmation 失效均标 `stale` 并给原因；不得自动改写 survey 或把 stale judgement 混入正式报告。用户重新 prepare/fill/verify 后生成新绑定，旧文件只作为 history/恢复证据，不伪造 receipt。

### 3.7 idea（idea-workbench + 陪练 C16）

- 目标行为：模糊想法→可验证问题；创新性分析（基于 KB）；**陪练式讨论**。
- 边界：脚本管 idea unit + 拉 evidence-pack；agent 唱反调/追问。
- 🔲 决策：陪练是**新 skill** 还是 idea-workbench 的一个模式？讨论落盘粒度（每轮/每结论）？
- ✅ **决策（已定）**：**idea-workbench 的一个模式**（不新建 skill）。身份=**领域专家 / 审稿人**：质疑、追问、基于 KB 甩反例、追踪论证链，**也给建设性建议，不一味唱反调**。落盘粒度=**每个结论**（可配置项）。
- ✅ **决策（2026-07-25 冷验收锁定）—— frozen corpus 不是全 KB 全局锁**：idea `generate/analyze/review/discuss` 的 prepare 保存“本任务开始时允许引用的 artifact manifest”，并由 immutable orientation 独立绑定该 manifest 文件 identity/bytes 与规范 digest；fill 中可编辑的 preference view 不能充当唯一承诺。verify 先重验 manifest schema/digest/orientation commitment，再只要求本次 claims 实际引用的 artifact 仍存在于 frozen manifest，且当前 canonical identity/bytes 与 manifest 条目 exact 相等；任务未引用的其它 unit、并行 scaffold、并行完成的 analysis 或新增 material 不得让本任务 stale。新出现但不在 manifest 的 artifact 仍禁止引用，已引用 artifact 的 byte/identity 漂移仍 fail closed，并在最终写入边界再次重验引用与 fill bytes。`*-fill.yaml`、`*-orientation.yaml`、`*-evidence-corpus.yaml` 等 Agent authoring 控制文件，以及本 operation 将改写的 target record/result/card/judgement sidecar，永远不是本次 evidence corpus 条目；否则成功写入会让自己的 verification receipt 出生即 stale。每个成功 verify 必须立即通过 current receipt/artifact-byte 复验。
- **Citable v2 预算（2026-07-25 锁定）**：新 manifest 只纳入 `verify_claim_evidence` 实际可逐字读取的 UTF-8 文本型 canonical artifact（文档/结构化文本/常见源码后缀与 README/LICENSE/Makefile 类文本名），明确排除 PDF、图片、归档、模型权重与其它 binary；上限固定为 16 MiB/file、20,000 entries、256 MiB total、relative depth 64。超预算 prepare 明确失败，不静默截断。新 prepare 写 `idea-evidence-corpus/v2`；既有 v1 nonempty fill 走有界兼容验证而不丢内容，空 v1 可安全刷新到 v2。
- **Owner-held authoring anchor（2026-07-25 二次对抗锁定）**：orientation/corpus/fill 三个 authoring 文件不能相互自签。prepare 必须另把 exact `idea-authoring-anchor/v1`（schema、operation、canonical id、request digest、orientation regular-file binding、corpus manifest/file commitment）写入 owner 管理的 canonical state：semantic operation 存在 `record.yaml.payload.idea_authoring_contracts[operation]`，generation 存在 bundle canonical index 的 `authoring_contract`。verify 以该 anchor 为根重建当前合同；即使三个 authoring 文件被协同重写，也不得改变 prepare-time 承诺。anchor 只由 owner prepare/materialize 在完整 transaction 内创建或消费，不是 Agent fillable 表面。完整协同重写必须有永久失败回归。
- **Generation bundle CAS（2026-07-25 二次对抗锁定）**：generation prepare 创建 exact owner `prepared` bundle index；它不是 materialized terminal，但已经是一等 canonical state。verify 只能消费仍与 prepare-time schema/content binding 完全相等的 prepared index，并在首次 candidate 写前最终重验；任何额外字段、sentinel、owner/status/anchor 漂移或已存在的非-prepared index必须 fail closed、零 candidate 写，禁止通用 `write_yaml` 覆盖。materialize 原子把同一 index 推进到 active/materialized；之后 prepare 保持 terminal。
- **Anchor lifecycle / legacy（2026-07-25 二次对抗锁定）**：owner anchor 的依赖顺序固定为 `corpus → orientation → anchor → canonical owner state → fill context`，anchor 禁止包含 record/fill 自身 binding。semantic verify 在最终边界用磁盘 active anchor 校验，成功写 result/consumed fill 时同 transaction 删除 active slot；undo verify 会从 before-image 恢复该 slot。一个 idea 同时只允许一个 active semantic authoring operation，第二个 prepare 必须在 journal snapshot 前零改拒绝，避免 whole-record context 让另一任务隐式 stale。既有 nonempty v1 走显式 `legacy-unanchored/v1` 一次性验证并在产物标 provenance，成功消费后下一轮强制 v2+anchor；空 v1 可刷新，v2 缺 anchor与 v1/v2 hybrid 不能被静默收养。
- **Prepared index 非自引用 CAS（2026-07-25 二次对抗锁定）**：prepared index exact keys 为 `schema/id/owner/status/request_context_digest/authoring_contract`，`schema=idea-generation-bundle/v1`、`owner=idea-workbench`、`status=prepared`。长期合同只以这份 exact semantic projection作为 canonical owner anchor，不把 whole-file digest 写回自身；单次 verify 另外捕获 transient regular-file identity+bytes，并在锁内与首次 candidate 写前比较，既检测同运行替换又允许 recovery 后重试。通用 ensure/update/review/select 入口不得改写 prepared generation index。materialize 后转为现有 terminal generic bundle（`status=active`）并保留 value-free authoring provenance；generation prepare/verify 将任何非 exact prepared index 视为 terminal 或漂移，绝不覆盖。
- **Bundle lexical containment（2026-07-25 对抗锁定）**：generic review/select/ensure/update 的 bundle `index.yaml` 与父目录必须在 target discovery 和锁内 preflight 都证明是 workspace 内的真实目录 + regular file/absent lexical target；index symlink、祖先 symlink或非 regular node一律零写拒绝。不得让 journal 对 `.resolve()` 后目的文件做 before-image，而 writer 原子替换 lexical symlink 节点；undo 不能作为 containment 补救。
- **Immutable fill contract（2026-07-25 锁定）**：verify 必须 exact 校验 owner scaffold 的非填空投影；Agent 只能改协议列出的 reviewer/conclusion/rank/candidate semantic fields 与 claim text/evidence refs。claim id/role/type/pending status、idea/request context、instructions、descriptive counts、top-level keys/shape 不可改；不得把 evaluation/inference 改成 fact 或预写 confirmed。无显式 preference receipt 时，最终写边界也要比较 value-free hard preference digests，不能因 binding `{}` 漏掉并发 hard profile 变化。
- ✅ **决策（2026-07-25 冷验收锁定）—— prepare 不得丢 Agent 工作**：同一 idea/operation 重跑 prepare 时，若现有 fill 与 owner 生成的空 scaffold 不同（包括任何 reviewer/claim/evidence 等 Agent 填写），必须在 workspace lock 下、journal before-image 之前的 preflight 拒绝，逐字保留 record/fill/orientation/corpus 的 bytes、mode 与 inode identity；只在 dispatch 内报错再靠 abort restore 仍会原子替换 inode，不满足零改。不得用空模板覆盖。只有 exact 空 scaffold 才可幂等/no-op，或在没有 Agent 内容时安全刷新 task binding；preflight 后 dispatch 仍需二次 guard 防竞态。并行批量 `prepare all → Agent fill all → verify all` 是正式 acceptance 路径，不能要求用户改成严格串行规避。
- **显式 corpus refresh（2026-07-27 冷验收锁定）**：普通 prepare 继续严格拒绝覆盖非空 fill；当 verify 明确指出新关联材料不在 frozen corpus 时，Agent 可在同一 owner prepare 上显式请求 refresh。refresh 必须先按旧 owner anchor exact 校验 fill 的 immutable projection，只搬运白名单内的 Agent mutable leaves（reviewer/rank/claim text/evidence refs），在同一 transaction 重建 corpus→orientation→owner anchor→preference consumer，再把这些 leaves 注入新 scaffold；未知字段、immutable tamper、symlink、stale/missing anchor 一律在写前 fail closed。该能力只更新可引用边界，不替 Agent 改 claim、不放宽证据或确认门。
- **Consumed fill 与下一轮（2026-07-25 锁定）**：成功 verify/materialize 必须在 canonical result/conclusion 保存 exact value-free fill binding。下一次 prepare 只有在当前 nonempty fill 与已 materialized binding exact 相等且结果仍 current 时，才可视为“已消费”并开始新一轮；未消费、部分消费、结果缺失或 binding 不符一律 preflight 拒绝并保留。analyze/review 支持 verify→prepare next round，discussion 支持连续多个独立结论；generation bundle materialized 后保持 terminal。

### 3.8 方法设计（method-designer）

- 目标行为：selected idea → 可执行方法（config/命令/指标/run grid），**因资源而变**。
- 边界：脚本生成 run grid/config patch 骨架；agent 填方法实质。
- 🔲 决策：读 user resources 到什么程度影响实验矩阵？
- ✅ **决策（已定）**：读 profile 里的 **resources**，实验矩阵规模（seed 数 / 模型大小 / 并行度）据此**缩放**，不现实的方案**标红**。**并且**：若某方案有**合理的额外资源需求**，主动向我提出（"这个实验需要 X 卡，值得申请"），我可以尝试去争取更多资源。
- ✅ **决策（2026-07-23 锁定）—— proposal 与 selection 分离**：确定性 token overlap 只可生成 `candidate_repos + proposed_repo_id + ranking_basis`，不得写 `selected_repo_id`、推进 `implementation-planning` 或发布正式 method event。runtime agent 必须填 repo-selection claim、接口/基线/风险判断及逐字 evidence，verify 后进入公共 review；只有用户确认当前 receipt 后，才把 `proposed_repo_id` 原子提升为 `selected_repo_id`、推进 program stage，并生成带 confirmation binding 的 method-selected event。旧的一次性 `design` 调用保留兼容时也只能等价于 prepare，不得暗中完成选择。
- **恢复不变量**：method 的 design 目录和所有产物都必须在声明完整 target set 的 transaction 内创建；prepare/verify/confirm 各自有独立可撤销点，空目录不得在 transaction 前泄漏。

### 3.9 实验（experiment-workbench）

- 目标行为：记录 + **验证**（指标类型/单位/baseline 对齐/artifact 存在）+ 失败诊断。
- 边界：脚本验 artifact/算趋势；agent 诊断。
- 🔲 决策：metric schema 强类型到什么程度？诊断读最近 N 次 run 自动对比？
- ✅ **决策（已定）**：指标**轻度强类型**（名字 + 数值 + 单位 + 方向），使跨轮次可自动比较/画趋势；诊断失败时**自动拉最近 N 轮对比**。**并且**：**baseline / milestone 等关键实验常驻对比**（每次新 run 都自动对齐这些锚点，不只比最近 N 轮）。这是把"记录器"变"验证器"的关键。
- **✅ R3 run fingerprint（2026-07-23 锁定）**：每次 run 的稳定 fingerprint 绑定 experiment id、tested hypothesis、规范化 change set、typed metrics schema（name/unit/direction，不含结果值）、声明 artifact identities 与显式 config/input revision；不绑定时间戳、result summary 或 metric observed values。相同 fingerprint 表示同一实验配置的重复试验，而不是重复写入错误。
- `run_id` 继续单调分配；每条 run 保存 `fingerprint`、`repeat_index`、`repeats_run_ids` 与 optional `seed`。完全相同 fingerprint + 相同 seed/config revision 的第二次写入默认 fail-closed，除非 agent 明确声明这是 rerun/retry 并给 `rerun_reason`；不同 seed 允许并归为同 fingerprint repeat group。比较器按 fingerprint group 提供重复统计输入，但脚本不自行判断显著性或成功原因。
- fingerprint 在持有 run-log/runs 目录事务锁后由 canonicalized fields 计算；编号分配、duplicate 检查、run Markdown、run-log、record、program event 在同一 transaction 内完成，禁止锁外 next-number race。artifact 仍先验存在性与 containment，fingerprint 不把绝对机器路径作为长期身份。
- **✅ R4 批量导入（2026-07-27 锁定）**：私有 `import-runs` 支持 project-contained W&B JSON、CSV 和单层 `run-*.json` 目录；纯 parser 机械归一事实，raw bytes 以 digest 归档。每条保留 imported provenance 并复用现有 fingerprint/repeat/comparison，整批预检、分配和写入必须在一个 root transaction 中 all-or-nothing；相同 item digest 幂等 skip，external id 或 fingerprint+seed/config 冲突 fail closed。不得通过循环单 run 留下半批，也不得从 metric/state 推断诊断。

### 3.10 报告（report-author + 大纲/写作 C11）

- 目标行为：周报/阶段/PPT **自包含**（claims+events+evidence 三元组）；**论文大纲 owner（新）**。
- 边界：脚本聚合 events/claims；agent 组稿。
- 🔲 决策：论文大纲是 report-author 加 verb 还是**独立新 skill**？周报 draft 缺输入时如何显式标 missing？
- ✅ **决策（已定）**：论文大纲=**report-author 加 verb**（不新建 skill）。周报/报告缺输入时**显式列"缺 X"，绝不脑补/编造**（缺 event、缺 evidence、缺决策都如实标 missing）。
- ✅ **决策（2026-07-25 冷产品验收锁定）—— 报告 scaffold 也是用户产物**：默认用户可见 Markdown 用中文标题、section 与缺失提示；若当前 `report-author` task-bound preference receipt 明确选择 `profile.preferences.language_preference=en...`，才切英文模板。语言偏好与 reporting style 一样必须先在 operation allowlist 中披露、再由 Agent 对当前报告任务选择；未选择 language soft preference 时使用产品默认中文，不得偷偷直读 profile。所有语言只改变呈现，不改变 claims/events/evidence/confirmation 内容与 digest。
- ✅ **决策（2026-07-25 对抗验收锁定）—— confirmed survey 是一等报告证据源**：program 的 `survey-confirmed` event 不是只供时间线展示的摘要；它必须携带 owner/path/ConfirmationReceipt 的 exact subject binding。`report-author` 在每次生成时从该 binding 安全解析 canonical `survey.yaml`，重验路径 containment、当前 survey content/upstream binding、verification bytes 与 ConfirmationReceipt，并只消费 receipt 所绑定、结构与逐字 evidence 均有效的 canonical claims。任一绑定 stale/tampered/missing 时 survey 只能进入 `Pending / Unverified`，不得进入正式 claims；报告 input snapshot 同时绑定其 canonical claims/evidence 与 receipt digest，保证 preference receipt 在 survey 改变后失效。
- ✅ **决策（2026-07-25 对抗验收锁定）—— event prose 不是已确认 substance**：`reporting-events.yaml` 的 `title/summary/tags` 是可变投影，不在 subject ConfirmationReceipt 的确认范围内；判断类事件即使 receipt current，也不得把这些字段渲染成“已确认断言”。报告必须把 event binding 与从 canonical subject 重建的 exact `confirmation_binding` 全量比较，并从 canonical subject 加载已验证 claims/evidence；事件时间线只显示由 subject kind/status 派生的中性状态。event prose 被修改不能注入正式报告，binding 任一字段不同则整条 judgement event 进入 `Pending / Unverified`。
- **✅ R4 编辑层（2026-07-27 锁定）**：周报和 PPT 不再只是同一 decisions/claims/events dump 换标题。私有 prepare 只冻结 current report inputs 并建 hollow Agent fill，verify 要求每条正文绑定 catalog ref。周报固定摘要/进展/问题风险/下周计划 + evidence appendix；PPT 固定 1–12 页、每页一个结论 + evidence + 可选 current figure + speaker/transition，且与 outline 七节明确不同。脚本不生成综合叙事，Agent 在同一自然语言任务内填充；任一上游或偏好 binding stale 时不覆盖旧成品。
- **R6 交付投影（2026-07-27 冷验收锁定）**：weekly scaffold 自描述 Agent 可改字段，并按四区预填合法 label；Agent 无需知道内部 workflow status，verify 在正文已实质填写时机械推进待验证状态。最终周报用 program question/title 而非 slug 作标题，把 epistemic label 翻译为读者语言，以稳定脚注序号代替 raw catalog refs，并把内部 receipt/claim/event 术语留在私有 manifest；exact canonical paper-type wire claim 只在渲染时翻成读者语言，不改 claim bytes，owner 自动生成的英文 event title 按 event type 本地化，用户自写 title 保留。缺少 decisions、confirmed claims 或 events 时在证据附录显式写自然语言缺失项。失败输出只给可行动的自然语言纠错，不暴露 fill/schema 字段名。
- **✅ R4 冷验收补强（2026-07-27）**：diagnosis prepare/Agent fill/verify/direct confirm、survey verify 与 weekly/PPT verify 的成功边界必须把实际 Agent fill、canonical judgement/summary/event/index 和 output 纳入同一操作的 exact checkpoint；失败不 checkpoint。所有新 reporting event 在 append 时获得持久、引用安全、同文档唯一的 stable id，factual event 才能进入 formal support。program selection 是混合 unit 集合：report/bib/figure consumer 必须先解析 globally unique canonical identity，再只消费 paper；current 非 paper 安全跳过，缺失、重复、unsafe slot 继续 fail closed。paper-only fixture 不足以验收报告链。

### 3.11 确认 / 治理（knowledge-base-manager + 门控）

- 目标行为：确认门**验实质**；分轨道信任；批量+渐进；注意力预算过滤（C19）。
- 边界：纯脚本 + 治理红线（禁自签/必留 evidence 不变）。
- 🔲 决策：分轨道的轨道怎么切（按 information_type？按 kind？按 skill？）？"连对 N 次降级"要不要做、N 取多少？
- ✅ **决策（已定）**：**先做①分轨道**——按内容性质切两轨：**事实类元数据**（标题/作者/arxiv号等，AI 几乎不错）可自动/轻确认；**判断类**（值不值得读、创新性、失败诊断、insight）需实质确认。**②连对降级暂不做**（需统计，缓）。**并且**：对**关键决策 / insight**，系统要**主动询问我确认**（不是被动等我翻 review 队列），把"该我拍板的"推到我面前。
- ✅ **决策（2026-07-16 锁定）—— 工作流状态与确认状态解耦；recommend_next 读工作流字段**：
  - **病根（审查坐实）**：analyzer 刚写完**空骨架**就置 `maturity=complete` + `confirmation_status=pending_user_confirmation`，而 `full_note_status="awaiting_agent_fill"` 已经能区分"空壳 vs 已填"——但 `safe_unit_step`/`program_dashboard_items` 的 recommend-next **只读 `confirmation_status`、从不读 `full_note_status`**，于是把"待 agent 填的空壳"当成"待用户确认"推给用户。**真缺陷是 recommend-next 漏读一个已存在的字段，不是缺字段。**
  - **目标**：建**唯一** `recommend_next()`，供 `find/status/next/review/auto` 共用；它必须读 `full_note_status`——`awaiting_agent_fill/not_started` 的 unit 归为"**待 agent 填**"（不该推给用户确认，若 autonomy 允许则自动接手填，否则出 `NEXT FOR AGENT`），只有真正**已填、已 verify、pending 用户确认**的才进"该你拍板"队列。工作流状态轨（`source_ready→awaiting_agent_fill→ready_to_verify→ready_for_review→done`）与确认状态轨正交，不再混用一个字段判两件事。
- ✅ **决策（2026-07-16 锁定，用户选"完整"）—— 恢复合同（operation journal + 原子 IO + CAS + resume/undo/restore）**：
  - **病根（审查坐实）**：YAML 直接覆写（无 temp+rename，中断即损）、batch 非事务、duplicate ingest 只停不回滚、Git checkpoint `git add -A` 收全部脏文件、无任何 `resume/undo/restore`。
  - **目标（本轮做完整版）**：
    - **原子写**：所有 record/state/workflow YAML 走 temp+fsync+rename；`write_yaml_if_changed` 底层原子化。
    - **operation journal**：每个改盘操作（ingest/verify/confirm/promote/reject/set-stage/batch）写一条 journal（op id、时间、目标路径集、before snapshot/digest、after digest、状态 begin/commit/abort）到 `kb/.journal/`。异常 abort 必须原子恢复 before snapshot；进程被杀留下 begin 时 `resume` 恢复到 op 前，不能只改 journal 状态。
    - **共享文件锁**：program/unit 级锁扩展到所有 load-modify-write 路径；reporting-events/decision/open-question 等共享列表必须在同一锁内重新 load 后 append，防并发丢更新。
    - **revision / CAS**：record 带单调 `revision`；已有 record 默认把传入对象的 revision 当作 expected revision，读写不符即拒绝并提示 reload；`expected_revision=None` 不能成为生产调用方绕过 CAS 的后门。与 ConfirmationReceipt 的 content_digest 协同。
    - **`kb undo` / `kb restore`**：一等命令，回退上一次/指定 op。checkpoint 只收该 op 显式列出的路径；空 path set 直接拒绝，底层永远不存在 `git add -A .` 兜底。
    - **✅ 冷验收加严（2026-07-27）—— 历史 restore 是区间恢复**：用户选择历史操作 X 的语义是回到 X 之前，而不是只把 X 的 before-image 写回当前树。实现必须在同一 workspace lease 下选择 X 及其之后尚未撤销的 root business operations，按新到旧建立可证明链；先用每一步 `after_digests → before_digests` 虚拟推进验证完整区间和当前状态，任一人工漂移、journal 变化或断链都在零业务写时 fail-closed。通过后用一个 recovery journal 覆盖 union targets，按逆序恢复所有 before snapshots、一次 exact-scope checkpoint，并把整段 source operations 标记为已恢复；不得逐条提交造成半恢复。最新一次 undo 仍是长度为一的同一严格语义。
    - **✅ 对抗复审加严（2026-07-23）—— recovery after-state CAS**：对已 commit operation 执行 undo/restore 前，持有 workspace + exact-target locks 后必须逐目标比较当前 digest 与 journal `after_digests`；缺失、不完整或不一致一律在创建 recovery journal、snapshot、checkpoint 或任何目标写入前 fail-closed，并提示先处理后续人工改动。恢复不能以“目标在 journal 里”代替“目标仍是该 operation 的 after-state”。崩溃 `begin` 的 resume 继续按 before snapshot 自愈，不套用 commit after-state CAS。
    - **✅ 对抗复审加严（2026-07-25）—— recovery canonical root**：恢复的目标解析、锁、实际写入、checkpoint 与返回结果投影必须共享同一个 canonical `kb` 根（解析 macOS `/var`→`/private/var` 等别名）。不得在恢复完成后再拿未解析的调用路径做 `relative_to`；别名入口与 canonical 入口必须得到相同的相对目标列表，且结果序列化失败不得留下“内容已恢复但调用报错”的半完成体验。
    - **✅ 对抗复审加严（2026-07-25）—— journal special-file nonblocking**：journal digest/abort/restore 的所有遍历必须用 `lstat` 区分普通文件、目录、链接与 FIFO/socket/device 等特殊类型；绝不得对特殊文件执行普通 `open/read_bytes`，否则一次并发替换即可让业务命令和全量测试无限阻塞。begin snapshot 遇既存特殊 target 必须在业务写前 fail-closed；运行中目标被换成特殊类型时，digest 只记录有界类型/identity sentinel 以驱动 before-image 恢复，abort 必须可在不读取特殊节点的情况下删除替换物并恢复原状态。
    - **✅ 对抗复审加严（2026-07-25，R17）—— incomplete-root quarantine + 可证明恢复顺序**：同一 KB 只要存在任一 `state=begin` 的 root operation，后续独立 root mutation 必须在新 journal、Git checkpoint/index/HEAD 与业务写之前 fail-closed，并把恢复动作交给 `kb resume`；direct `begin_op`/`journaled_op`/`git_checkpoint`、manual/auto checkpoint 与 `git-init` 等旁路全部受同一 gate。nested child 与恢复 operation 只能通过私有、context-bound capability 例外，调用者伪造 `operation_role` 不能绕过。检查与 root begin/checkpoint 必须处于同一 workspace lease 内，避免两个进程同时穿过空窗。新 journal 若将来需要允许多个 root，必须由 workspace lease 内持久化单调序号建立因果全序；当前新实现一律只允许一个 incomplete root。对历史版本已积累的多个 roots，disjoint target 可按稳定顺序逐个恢复；target 重叠而又没有可信单调全序时必须 fail-closed，不能拿 wall clock、mtime 或随机 UUID 猜“最新”。
    - **✅ 对抗复审加严（2026-07-25，R17）—— resume consume 原子边界**：`resume` 在 workspace lease 内重新加载并验证 authoritative source journal，恢复、recovery journal/checkpoint 与 source root/descendants 终态化都在该 lease 内串行；两个并发 resume 不能重复消费同一 root。若恢复或 checkpoint/terminalization 中途失败，不能越过该 root 继续 older roots；重试只对同一 newest recoverable root幂等继续，直到它明确 terminal，才处理下一项。
    - **✅ 对抗复审加严（2026-07-25，R17）—— journal envelope integrity**：quarantine 扫描不能把截断 YAML、非 mapping、未知 state、symlink/FIFO/socket/device journal entry 当作“不存在 begin”而放行；无法证明 terminal 的 entry 一律有界、nofollow 地 fail-closed。恢复 source entry 必须在 workspace lease 内只读一次 authoritative bytes/identity，再由这一视图派生 target locks 与 recovery journal；不能锁前验证旧内容、锁后重读新内容。原始 YAML mapping 的重复 key 必须拒绝，不能由 loader last-wins 后误通过。
    - **✅ 对抗复审加严（2026-07-25，R17）—— lexical journal target identity**：canonical KB root 仍可 `resolve()`，但 operation target 的身份必须是该 root 下经过规范化校验的**词法相对路径**；调用 API 时允许传入词法上位于 canonical root 内的绝对 `Path`，但 journal key 本身不得是绝对路径或含 `.`/`..`/空 segment。不得先把 leaf symlink `resolve()` 成 referent 再 snapshot/lock/restore；逃逸与 symlink ancestor 一律在写前拒绝。target ancestor 的验证、snapshot/digest/restore 必须以 anchored dirfd + nofollow identity checks 关闭“校验后换成外链”的 TOCTOU，不能只靠一次 `Path.lstat()`。leaf symlink 可作为节点本身被 `lstat/readlink` 快照并在 abort/resume/commit→undo/restore 中恢复其原始链接类型与逐字 link target；dangling、relative 与 absolute-outside link 都只操作 leaf node、不碰 referent。锁 key、journal `target_paths`、Git pathspec/checkpoint 与返回投影必须使用同一 lexical key。若业务意图是修改 referent，调用方必须显式声明 referent 为 target，不能借 alias 获得隐式写权限。
    - **✅ 对抗复审加严（2026-07-25，R17）—— journal target-set integrity**：任何 abort/resume/undo/restore 在取得 target locks、创建 recovery journal 或写业务路径之前，必须验证 journal `target_paths` 无重复且全部为 canonical lexical keys，并与 `before_digests`、`before_snapshots` 的 key set 精确相等；commit recovery 还必须与 `after_digests` key set 精确相等。任一缺失、多余、重复、非规范或不安全 key 都零业务写 fail-closed，不得只恢复交集后报告成功。
    - **✅ 对抗复审加严（2026-07-25，R17 follow-up）—— restore publish durability**：before-image 的 file/directory/symlink replace 与 absent-target removal 只有在锚定的 target parent directory 完成 `fsync` 后才算发布成功；不能只 fsync staged file/tree 后 rename 就返回。旧 target 的 rollback backup 必须保留到新 target 已替换、内容 digest 复验和 parent `fsync` 全部成功；任一 publish/post-replace/final-fsync 失败都先确认 replacement 仍属于本 op，再恢复旧 target 并再次 fsync。若 publish 与 rollback 都失败，必须保留唯一旧副本并准确进入可恢复失败态，不能在 `finally` 删除。对 originally-absent target，失败回滚必须移除本 op replacement 并持久化该移除。故障注入必须覆盖 file/directory/symlink/absent、首次与 rollback fsync failure，以及同目录并发替换；公开面仍只报告恢复失败，不泄漏 backup/path。
    - **✅ 决策（2026-07-17 锁定，补 resume 面）—— `kb resume`**：崩溃会在 `kb/.journal/` 留 `state=="begin"` 的孤儿条目（进程被杀连 `abort_op` 都跑不到，无 `finally`）。当前无任何函数扫描它（`committed_ops` 明确跳过非 commit）。补：① journal.py 加 `incomplete_ops(root)`（glob 条目、选 `state=="begin"`，与 `committed_ops` 对称）；② `kb resume` 一等命令：列出未完成 op，对每个复用现成 `restore_operation(root, op_id)`（begin 条目带 `before_digests`，机制上直接可用）回滚到 op 前的干净态，并把该 journal 条目标 `abort`。③ 输出遵原则8（自然语言、无裸 git；对齐 undo/restore 现有风格）。resume 是"崩溃后自愈"入口，与 undo（回退上一次成功 op）语义不同。
  - **红线**：journal/锁只加严一致性，绝不碰治理逻辑；真实 `kb/` 测试用临时目录。
- ✅ **决策（2026-07-16 锁定，用户选"最小"）—— Workbench 安全（research-navigator browser，见 3.12）**：**强制回环**（拒绝非 loopback `--host`，要跨机访问须显式且有意）；**写保护派生证据**（`raw/` + parse-cache 的 `.md/.txt` 对 workbench 写端点只读，贯彻原则2"派生证据不可变"）；**保留 shell/PTY**（本地单人用，暂不加 token / 不默认关）。~~token 鉴权与默认关 PTY 标 future。~~
- ✅ **决策（2026-07-17 锁定，推进原 future 项）—— Workbench token 鉴权 + PTY 默认关**：
  - **token 鉴权**：`main` 启动时生成一次性随机 token（`secrets`），只印在启动者终端（不落盘、不进 URL 日志）；`browser_url`（kb_browser_lib.py，唯一 URL 生成点）把 token 作为查询参数附上；三个请求入口 `do_GET/do_POST/do_PUT` 各自开头统一校验（或共用一个 `_authorized()` helper），**含 `do_GET` 落到静态文件之前那条路径**。缺/错 token → 401。healthz 可豁免（只报活性）。回环强制与 token 正交叠加：跨机（`--allow-non-loopback`）时 token 是唯一凭证。
  - **PTY 默认关**：新增 `--enable-terminal` flag（默认 **False**）。默认下 `/api/terminal/open`、`/api/terminal/input|resize|poll`、`/api/system-terminal/open` 一律 404/禁用，`TerminalManager` 不构造（或构造但拒开）。显式 `--enable-terminal` 才启用 shell/PTY。把"带 shell 的代码执行面"从默认开改成默认关，dev-only 姿态更稳。
  - **红线**：token 不落盘、不写进任何 record/日志；用户可见输出（启动提示）遵原则8——给自然语言 + 该点开的 URL，不喷内部命令。既有回环强制 + raw 写保护不动。
  - 影响：research-navigator 成熟度从 dev-only 向上一档靠拢（有鉴权 + 默认无代码执行面）；README/USER_GUIDE 矩阵相应更新。

### 3.12 导航 / 注意力（research-navigator + C19）

- 目标行为：首页/next 是"现在最该看的 N 件 + 为什么"，非全量列表。
- **用户可见交互边界**：skill 面向用户时，导航结果必须是可直接执行的自然语言建议；脚本命令、环境变量展开、路径和 `NEXT FOR AGENT:` 等机读编排信息仅供会话 agent 使用，绝不可原样呈现给用户。空知识库时，应直接说明当前无内容，并邀请用户发送论文链接、文件或仓库地址以开始入库，而不是展示 intake 命令。
- 边界：纯脚本（排序+过滤）。
- 🔲 决策：优先级怎么算（blocking evidence > stale > pending？权重？）？
- ✅ **决策（已定）**：优先级 = **阻塞证据（卡住 program 的）> 快过期/stale > 普通 pending**。首页/`kb next` 只呈现"现在最该看的几件 + 为什么"。
- **D2 continuation contract**：`kb next` 是“从持久化状态重新计算”，不是“继续聊天上一句话”。Agent 只有在目标已写入 program `goal/question/next_actions`（或等价 durable work item）时，才能承诺“运行 `kb next` 会继续 X”。用户明确要求批量综述、taxonomy 或技术路线图时，必须在当前操作中创建/复用 program、attach 相关 units 并写入 next action；若没有 durable program work，只能诚实说明当前无已保存待办并询问研究目标。program item 始终压过 loose maintenance。
- **D2a standalone literature continuation（2026-07-25 冷验收后锁定）**：`literature-search` 的 canonical source-search stage 本身就是 durable work item，不能因为它不属于 composite survey/program unit 就从 `kb next` 消失。orchestrator 必须从受控 stage 重新枚举：未终止的独立检索产生 Agent 可恢复的 `resume-literature-search` 候选；已终止且仍有 `include/maybe`、尚未 materialize 的候选产生 `select-literature-candidates` 人工选择门。依赖必须绑定 stage 当前 bytes、stop 状态和候选 identity/筛选/status；重开会话后重新计算，stage 或候选变化使旧 portfolio decision 失效。带 `monitor_binding` 的 stage 由 monitor owner 接管；被任何 composite survey state 引用的 stage 由 composite owner 接管，二者不得重复出现在 portfolio。没有可选候选的 terminal stage 不制造假待办。
- **D2b empty-library status（2026-07-25 冷验收后锁定）**：`kb status` 必须分别报告“资料单元”和“研究计划”。零 unit 但已有 program 时不能只说知识库为空；应以公开 sanitizer 清洗后的名称列出少量 program（其余给计数），并把完整 canonical id 只留在私有 protocol。纯读 status 不得为展示创建文件。
- ⚠️ **待修复观察（2026-07-16）**：在空知识库的 agent 对话中输入 `kb next`，回复虽正确识别“知识库为空”，却向用户渲染了 `${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py ...` 命令块。此为上述交互边界的违例；实现应将该指令保留在 agent 内部执行路径，用户侧改为自然语言的下一步引导。验收：空库 `kb next` 的用户可见回复不含 shell 命令、环境变量、内部脚本路径或机读导航标记。

### 3.13 监测 / 自校正（新，C17/C18）

- 目标行为：可选 push（新材料该看什么）+ confirmed 复查 + 矛盾检测。
- 🔲 决策：**这块是否纳入第一版目标**，还是先标"future"？（最不成熟、最可延后）
- ✅ **决策（已定）**：**不做定时/后台扫描**（push、周期复查 → 标 future）。**但保留反应式矛盾检测**：在交流/分析过程中，一旦发现新材料与 KB 已存信念（或两条 confirmed 判断）**矛盾**，系统**必须主动向我指出、询问确认，并在我拍板后更新 KB**。即：矛盾检测是**会话内触发的**，不是定时任务。

### 3.14 配置 / 个性化（research-config-manager）

- 目标行为：自然语言配置真被下游消费（reporting_style/term/resources/autonomy）。
- 🔲 决策：哪些个性化字段是第一批必须接下游的？
- ✅ **决策（已定）**：第一批接下游：**① autonomy（自动化程度，直接影响体验）② reporting_style（接报告）③ resources（接 3.8 方法设计）**；term_style 次之。**并且**：**记忆模块主动记忆并更新用户偏好**——不只被动读 config，而是在交互中观察到我的习惯/偏好时**主动记一笔并更新**（走确认门控：偏好类默认 pending，我确认后生效；接现有 skill-evolution-advisor 的 learnings 机制）。
- ✅ **决策（2026-07-16 锁定）—— `kb init` 偏好/画像设置必须在 agent 对话里真发生**：
  - **病根（审查坐实）**：偏好/画像问答内联在 `kb` wrapper 的 `handle_init`，却被 `sys.stdin.isatty()`（`kb:654`）门控——agent 无 TTY → 静默走脚手架分支 `return 0`，交互分支永不进入；且 `forward_command` 用 `capture_output=True`，子进程 `input()` 也无法与用户交互。结果：伪 CLI `kb init` 从不问偏好。
  - **目标（遵原则8：agent 中介，不依赖 TTY）**：`kb init` 在缺配置时不静默成功；public stdout 只给自然语言说明，内部 protocol 列出待收集字段。会话 agent **对话式**逐项问用户（human name / language / commit cadence / link_autodrive / discussion_style / autonomy scope / persona），收齐后 headless 落盘；`auto_screen` 已退役。终端有无 TTY 不改变语义，删除 `input()` 分支。
  - **幂等不变量（2026-07-19 冷验收补洞；2026-07-27 同步）**：无参数重复 init 只补目录/缺失 schema 字段，已保存的 human name、language、commit cadence、link_autodrive、discussion_style、autonomy/persona 必须原样保留；只有用户在当前对话明确给出某字段的新值时才覆盖。已完整 workspace 上的无参数 init 是严格 no-churn：不得刷新 index/taxonomy `generated_at`、不得新增 operation journal/checkpoint，也不得改任何已有 bytes；partial/malformed workspace 仍须进入 repair 而不是误判完整。子 owner 的进度行与机器字段一律只进私有 protocol，public stdout 最多一条最终自然语言总结。
  - **验收**：agent 会话里首次 `kb init` → 触发 agent 逐项问偏好 → headless 写入 `user-profile.yaml`（persona/autonomy 非空）；`config.py show` 可见；非 TTY 下不再空跑返回 0；随后无参数 `kb init` 的全树 metadata digest、journal 数与配置 bytes/语义均不变，stdout 无重复/机器行。

#### R5 观察式偏好与人工笔记回流（2026-07-27 锁定）

- **偏好不是 Agent 自签的配置写入**：Agent 只在用户明确纠正，或同类产出连续被改成同一形态时，追加一条 `user-preference` observation；任务收尾最多攒 2 条，用自然语言询问“要记住吗”。observation 必须保存短的逐字用户表述、适用 skill/operation 与内容 digest，初始为 `pending`。`review_learning(..., confirmed)` 与允许 pending 直达配置的 `promote_learning()` 旧旁路退役；确认必须进入统一 public review snapshot，要求真实 signer、当前用户消息授权、一次性 snapshot/CAS 与 ConfirmationReceipt。确认和写入 `runtime-preferences.learned_preferences` 在同一 root transaction 完成，receipt 绑定 preference text、逐字 observation、scope 和原 learning bytes；任一变化自动失效。`dismissed` 也只能消费当前展示集，不能由 Agent 静默决定。
- **“我写的”只表来源，不代表已确认**：用户自然语言指定 `obsidian/inbox/` 或 `obsidian/annotations/` 中的笔记后，source-intake 私有 human-note intake 只读取一个目录层级内、明确选中的 UTF-8 普通 `.md` 文件；拒绝 symlink/special/nested/过大文件和 review sheet。输入 exact bytes 冻结到 canonical source bundle，原人工文件逐字不改。它落为 `blog` unit（`source_origin=human-note`），再由统一 `unit-analyst` 路由到既有 blog implementation 的 prepare/fill/verify；Agent 结构化理解必须逐字引用冻结副本并保持 pending。后续仍走 public review；signer 从 `identity.default_confirmed_by` 或当前对话取得真实姓名，绝不能把字面量“我”、`Agent` 或 source=user 当签字。
- **跨任务生效门**：eligible preference view 只接纳 `runtime-preferences` 中同时带 current learning/receipt binding 的 learned item；旧式无 receipt item 仅作未确认历史提示，不进入 soft preference catalog。任务开始只披露本 owner/operation allowlist 内的 confirmed item；用户当前消息仍可临时覆盖本任务。

### 3.15 分发 / 版本 / 自更新（新，2026-07-17 锁定）

- 目标行为：`kb update` 从 GitHub 拉最新 skill 集，更新当前工作区 + 系统路径两处的 kb skill；skill 集带**版本号**用于标明版本 + 检查更新。
- **病根/现状（取证坐实）**：安装是 **copy（copy-project）或 symlink（system scope）**，只有源 git checkout（REPO_ROOT）有 `.git` + GitHub origin（`git@github.com:caozx1110/ResearchLab.git`）；无任何版本文件，只有 manifest 里一个 `source_commit`（裸 HEAD sha）；copy 安装不知道自己来自哪个 GitHub 仓。
- ✅ **决策（已定，用户拍板）**：
  - **R4 自动版本决策（2026-07-23）**：对抗性修复由维护流程把 `.agents/VERSION`、README、USER_GUIDE、DESIGN 与 CHANGELOG 一致推进到 `0.2.0-rc.4`。自动更新仅指本地受控版本面，不自动 tag/publish/push，也不把未完成 localhost/hosted CI gate 的候选升级为 stable `0.2.0` 或声称完整验收通过。
  - **R5 自动版本决策（2026-07-24）**：provider-neutral `literature-search` 重构、OpenAlex runtime 退出、选择授权/系统检索审计账本和三路对抗复验完成后，维护流程把受控版本面一致推进到 `0.2.0-rc.5`。自动更新仍不包含 push/tag/publish；真实来源、Obsidian Reading-view 与 hosted Linux/macOS CI 继续是 tag 前置。
  - **R6 自动版本决策（2026-07-24）**：Agent-led portfolio、任务绑定偏好选择、无插件多项 Obsidian review、`research-monitor`、多 reviewer ledger 与 Agent 可审计安装计划组成新的候选功能面，维护流程把受控版本一致推进到 `0.2.0-rc.6`。自动更新仍只含本地版本文件、公开版本面与 changelog；不自动 push/tag/publish，真实来源/Obsidian 与 hosted Linux/macOS CI 继续是稳定 tag 前置。
  - **版本号 = `.agents/VERSION` 里的 semver 文件**（如 `0.1.0`，随 `.agents/**` 分发进 copy 安装；发布时手动/脚本递增）。`kb doctor`/`kb update` 展示当前版本。首版 `0.1.0`。
  - **canonical origin 硬编码**在 updater 里（`https://github.com/caozx1110/ResearchLab.git`，https 免 SSH key）；本地源仓 origin 存在时可覆盖。
  - **`kb update` = 检查 + agent 中介应用**（原则8 + 治理：改安装代码是对外/难撤销动作，先确认）：
    - **check（只读，安全）**：读本地 `.agents/VERSION`；从 GitHub 取远端 VERSION 比对；报"已最新 / 有更新 X→Y"。用户可见=自然语言，无裸命令。
    - **apply（先经用户确认再跑）**：`kb update` 若发现有更新，public stdout 只自然语言说明版本差异；结构化 agent protocol 请求确认，用户明确同意后 agent 才 headless 应用，不自动改安装代码。
  - **更新机制 = 完整档（用户选）**：
    - **同仓 / system scope**（install root 解析到 REPO_ROOT，一个 checkout）→ `git -C REPO_ROOT pull`；system symlink 自动跟随，工作区+系统一并更新。
    - **copy-project**（工作区 copy 无 `.git`）→ manifest 同时记录 `source_origin`（URL 或 local）、`source_checkout`（安装时 lexical 本地 checkout）、`source_branch` 与 `source_strategy`。从本地 checkout/worktree 运行安装器时策略固定为 `local-checkout`：checkout 存在时 check/apply 只读取该工作树当前内容，不 fetch/pull，允许尚未 push 的分支；origin/branch 仅作溯源。checkout 缺失/失效时请求用户重选，不静默转 remote。只有显式 remote/cache 来源才采用 `remote-branch`，按相同 origin+branch fast-forward/隔离 clone。detached HEAD 记录 `source_commit`，但不得把它猜成 `main`；需要继续更新时先由用户显式选择 branch/source。fork/local/non-main 安装绝不静默改用 canonical upstream 或默认分支；旧 manifest 缺任一承重 provenance 字段时明确提示用户选择，不做隐式回填。
    - **✅ 对抗复审加严（2026-07-25）—— source-choice 必须可执行闭环**：`needs_source_choice` 不能只发一个无人消费的 protocol action。check 必须把当前 manifest 的 source provenance、缺失字段与 manifest byte digest 放入私有 Agent action；Agent 用自然语言只询问真正缺少的 source/branch，得到当前对话选择后通过隐藏、headless 的 `kb update` adapter 原子重绑 manifest，再自动重跑只读 check。重绑必须校验 manifest 是普通文件、expected digest 仍匹配、branch 合法、local checkout 是真实 bundle source 且 origin/当前 branch 与选择一致；detached checkout 选择远端 branch 时切换为显式 `remote-branch` + 隔离 cache，不修改用户的 source checkout。重绑本身不等于更新授权：发现新版本后仍走单独的当前用户确认再 apply。用户侧始终只见自然语言与 `kb update`，不展示 flags/path/digest/裸 git，也不依赖 TTY。
    - **✅ 对抗复审加严（2026-07-25，R17）—— detached local 不得伪装成 updateable**：`local-checkout` 若是 Git checkout，重绑时必须验证当前实际 branch 非空且与选择精确一致；detached HEAD 即使没有 remote、选择 `origin=local` 也不能以空 branch 重绑为可更新来源，Agent 必须请用户提供另一个已经附着到明确 branch 的有效 checkout，或在存在可信 remote 时显式选择 `remote-branch`。只有不属于 Git checkout 的真实本地 bundle source 才允许 `origin=local` + 空 branch。`source_commit` 只作溯源，不能替代可更新 branch。
  - **✅ 对抗复审加严（2026-07-25，R17）—— installer/rebind 共享 manifest lease**：安装器所有会创建、改写或删除 manifest 的 install/update/reinstall/uninstall 动作，与 updater 的 source provenance rebind 必须使用同一个跨进程独占 lease；lease 锚定不会被这些动作删除的真实 workspace root directory，而不是可能被 uninstall 移除/重建的 `.agents` inode，也不创建额外 unowned lock file。Agent install plan 的 manifest precondition 必须包含 expected absent/ordinary-file identity + byte digest，并由私有 plan→apply 通道一直传给 `ws_sync`；不能在 shell verify 后由 `ws_sync` 重新把竞态后的当前 manifest 当成新计划。双方都要在 lease 内重新读取并验证 manifest 的 byte digest/identity；发生同 bytes 新 inode、并发 rebind/install 或其它合法 manifest 更新时，旧 plan 必须在任何 managed write 前 fail-closed 并要求重新规划。rebind 还要在 final replace 前二次验证选择的 checkout origin/HEAD/branch。lease 必须覆盖 managed payload 变更、rollback、manifest-last commit/删除及目录持久化的整个事务边界，不能只锁最后一次 replace；异常 rollback 不完整时保留恢复材料，不能在 `finally` 删除唯一 backup。fresh install 仍须工作，且不得新增用户可见协议或污染 manifest ownership。
  - **✅ 对抗复审加严（2026-07-25，R17 follow-up）—— updater manifest 读取、apply 与 rebind 的失败保真**：updater 的 check/apply/source provenance 等全部 manifest 读取面必须复用同一 anchored、no-follow、nonblocking、有界 ordinary-file snapshot；FIFO/symlink/special/过大/竞态内容都 fail-closed，不能阻塞或跟随外部内容。`kb update` apply 不能先用未绑定的 manifest 解析旧 provenance，随后让 `ws_sync` 在共享 lease 内把竞态后的 manifest 当作新基线。apply 必须从一次安全 snapshot 同时导出 provenance 与 expected `device/inode/byte_sha256`，释放 lease 去准备 source 后，把该 expectation 原样传入 `ws_sync`；锁内不匹配时在任何 managed write 前 fail-closed。即使版本比较得到 no-op，也必须重验同一 expectation，不能对已经重绑的另一来源宣称旧来源“已是最新”。rebind 的 manifest replace 在最终目录 fsync 成功前必须保留旧内容与恢复材料；post-replace 失败时只可在目标仍是本 op replacement inode 时原子恢复旧 bytes/mode 并再次 fsync，恢复不完整则保留唯一材料并给出准确错误，不能返回失败却留下新 provenance。并发 rebind↔apply、FIFO/symlink 读取与 post-replace fsync failure 都要有确定性永久回归。
  - **✅ 对抗复审加严（2026-07-25，R17 follow-up）—— lifecycle lease 必须覆盖 shell 外层配置**：project install/update/reinstall/uninstall 的 `.claude/skills` 与根 `CLAUDE.md` managed-block 等 installer-owned side effect 不能发生在 `ws_sync` 取得/重验 manifest lease 之前或释放 lease 之后。尤其 uninstall 的 Agent-plan manifest 变 stale 时，任何链接或 managed block 都必须保持原样。实现必须把这些 side effect 纳入同一 workspace-root lease、同一 expected manifest view 与可回滚事务，或移入持 lease 的同步 helper；仅把删除顺序前后调换仍会留下“命令失败但部分配置已改”的假原子性。回归需覆盖 verify 后同 bytes 新 inode/rebind、side-effect fault 与并发 lifecycle，失败时 `.agents`、manifest、`CLAUDE.md`、`.claude/skills` 一致保真。
  - **✅ 对抗复审加严（2026-07-25，R17 follow-up）—— Agent plan 必须绑定产生目标清单的 manifest snapshot**：copy lifecycle 的 dry-run 在 workspace lease 内依据哪一份 manifest 计算 targets，就必须同时输出那一份 expected absent/identity+digest 作为私有 plan input。plan generator 只能复核并原样封装这个 expectation；不得在 dry-run 释放 lease后重新读取“当前 manifest”并把新 inode/digest错误签给旧 target list。dry-run→plan generation 窗口发生 rebind/同 bytes 换 inode时，计划生成必须 stale fail-closed并要求重跑，尤其 uninstall 绝不能让用户审旧删除清单却按新 manifest 删除。该 barrier 需要确定性永久回归。
  - **✅ 冷 installed-copy 补强（2026-07-25，R18）—— preview 只能描述未来动作**：`--dry-run` / Agent plan 的所有 lifecycle 文案必须明确是“预计/审阅后将”，不得在零写阶段声称“已移除、已不再由安装器管理、已完成”。apply 成功后才允许完成态措辞；计划生成后 `.agents`/manifest/AI 配置仍必须逐字不变。测试同时断言输出真实性与 workspace byte snapshot，不能只看 target list。
  - **✅ 冷 installed-copy 补强（2026-07-25，R18）—— managed block 外字节往返不变**：若安装前根 `AGENTS.md` 已存在，install/reinstall/update/uninstall 只能增加/替换/移除安装器声明的 managed span；span 之外的前缀、后缀、结尾换行和空行 bytes 在完整 lifecycle 后必须与 before-image 完全一致，重复生命周期不得累积 separator。manifest/plan 必须能让 removal 精确恢复安装时插入边界，不能靠泛化 trim。
  - **✅ 冷 installed-copy 补强（2026-07-25，R18）—— runtime readiness 只报真实状态**：installer preflight 先检查当前 workspace 的配置解释器与已存在 managed `.venv/bin/python` 是否满足核心依赖，再决定 conditional runtime target/warning；已有 doctor 可验证的可用 venv 时，no-op update/reinstall 不得仍称依赖未就绪。自动探测 workspace venv 也必须服从 Agent plan 的 `zero_write_scope`：锚定 workspace/venv 祖先，拒绝 FIFO/特殊节点、换链与 workspace 内任意普通 executable，不得执行一个可在预览期间改写 workspace 的伪解释器；只对标准 venv 的稳定 symlink chain（最终 executable 位于 workspace 外）执行有界 import probe。copy-style interpreter 无法在不执行 workspace-owned bytes 的前提下证明时保守列为 conditional runtime，不得用虚假 ready 换取少一条提示。确需准备时仍只声明条件动作，不在 Agent plan 阶段安装。
  - **✅ 冷 installed-copy 补强（R25）——离线安装自动复用 PATH 中已有兼容 Python**：未显式设置 `RESEARCH_PYTHON`、首个 `python3` 缺核心模块时，installer preflight 与 installed entrypoint 必须继续检查 PATH 中后续的安全 Python 候选；找到已能导入完整核心 runtime 的解释器就自动用于本次 smoke/运行，不声明或创建 managed venv，也不触发 pip/网络。只枚举绝对 PATH 目录中的可执行普通文件或其稳定 symlink target，拒绝 workspace 内解释器、相对 PATH、special file 与变化中的 target；显式 `RESEARCH_PYTHON` 仍优先且不被暗中替换。无兼容候选时才走既有 conditional managed runtime。用户不需要知道或手动设置环境变量。
  - **R25 Agent plan runtime 前置条件——零 runtime 目标也是承诺**：当 Agent plan 因复用 current / explicit / later-PATH / ready-managed Python 而把 `conditional_runtime_changes` 置空时，计划必须另存实际 invocation 的选择来源、canonical target、普通可执行文件 identity（device/inode/mode/owner/size/mtime/ctime）、必要的 managed invocation chain 与核心模块探测结论，并纳入 semantic/byte-bound plan。apply 必须在验证计划/source/全部目标前置状态之后、首个 workspace/HOME/runtime 写入之前，按同一选择规则证明 invocation 仍可发现、精确解释器/managed chain 仍是同一身份且核心模块仍可导入。换 shell 后 PATH 不再包含原 current/later-PATH entry、显式 override 原文/解析变化、managed invocation leaf/chain 漂移、target identity/能力变化均零写失败并由 Agent 自动重做计划；不能用只在本次 apply 生效且不会被 installed `kb` 继续消费的 absolute target 制造“安装成功、下一次立即失败”，也不能在复制 manifest 后把未列入计划的 `.venv` 作为降级路径。若 plan 已声明 conditional managed runtime，则保持既有有界 fallback；human install 不受 Agent plan 字节合同限制。runtime precondition 的机器字段不得进入公开完成输出。
  - **manifest 加 `version` 字段**（copy 安装落盘时记录，供本地展示/比对，不再只靠 source_commit）——**✅ 已落地（2026-07-17，main dbbce03）**：`build_manifest` 加 `version`（`read_source_version` 从源 `.agents/VERSION` 读），install/update/reinstall 三处 call site 全接；schema 保持 1（additive，旧 manifest 仍可读，字段读时可选）。实机验：fresh install 记 `0.1.0`、update+reinstall 保留、405 绿。
- 边界：纯脚本/git 操作（版本读比、fetch/pull/clone、re-sync）；不改治理/kb 数据。**红线**：绝不 push（只 pull/fetch/clone）；drift 检测保留（本地改过的 managed 文件不被静默覆盖，除非 --force）；真实 `kb/` 用户数据零触碰；更新是对外动作，apply 前必经用户确认。
- 落地（本轮，避开 install.sh/ws_sync.py）：新增 `.agents/VERSION`（已建 0.1.0）+ `.agents/lib/research/updater.py`（版本比对 + pull/clone/sync）+ kb-cli `kb update` verb（check 默认 + NEXT FOR AGENT 引导 apply）+ `kb doctor` 显示版本。install.sh/ws_sync.py 侧（manifest version）**已于 2026-07-17 补齐（main dbbce03）**。属工程卫生（Part 4.3 正交）。
  - **2026-07-18 R1 加固**：保留只读 check / 用户授权后 apply，但删除 public `NEXT FOR AGENT`；补 source provenance，doctor runtime truthfulness 与安装来源回归测试。旧 2026-07-17 验收仅代表当时实现历史，不再作为发布结论。

### 3.16 multi-skill workspace bundle（新，2026-07-17 锁定）

- **目标形态**：不做 plugin；`.agents/skills/` 下多 skill 独立触发、共享 `.agents/lib/research` runtime；整棵 `.agents/` 是安装单元，装到每个 kb workspace；用户数据只在 `<workspace>/kb/`，不随源码/安装包分发；**正式支持 project-scope copy install，不再推荐 system/symlink**。
- **现状 gap（取证坐实，base fffd5f3）**：① `ws_sync.source_items` 是 **walk+排除**（只排 `__pycache__/.venv/.pyc/.DS_Store/manifest`）→**ships `.agents/lib/research/tests/` + `skill-evolution-advisor/scripts/eval_research_value.py`（开发 G5 evaluator）**；② install 遇既有 `.agents/` 直接 die，不做 manifest-scoped 合并（用户自带 skill 无法共存）；③ 无 `reinstall` action；④ 公开面引用私有 `temp/`：`README.md:111`、`skill-evolution-advisor/SKILL.md:39`、`evidence.py:13` docstring、`eval_research_value.py:5`；⑤ Navigator `kb.js:1083` 硬编码项目 slug `humanoid-vla-wholebody-control`；⑥ 无专门 skill quick-validator（只有 test_skill_docs_cli_drift + test_schema_docs 部分覆盖）；⑦ `czx` 仅在 tests（排除 tests 后不 ship）。已有：LICENSE(MIT)、`.github/workflows/ci.yml`(compileall+pytest)、17 skill 均有 SKILL.md+openai.yaml。
- ✅ **决策（已定，源自用户 8 点规格）**：
  1. **源根 vs 目标根显式分离**：所有写操作只写显式 `--project <dir>` 目标或从 cwd 向上发现的 workspace（有 `.agents`+`kb`/manifest 标志）；**无法确定目标时必须拒绝，绝不回退源码仓**。ws_sync 已有 `assert_write_target`（拒写 target `.agents/` 外）——保留+补齐 install.sh 侧发现逻辑与拒绝路径。
  2. **发布 allowlist（取代 walk+排除）**：只打包运行所需——`.agents/skills/*`（运行 skill）+ `.agents/lib/research`（共享 runtime，**排除 `tests/`**）+ `.agents/AGENTS.md`（运行规则）+ `.agents/VERSION` + `LICENSE`；**排除** tests、temp、kb、缓存、未跟踪文件、本机绝对路径、**开发 evaluator（eval_research_value.py 及其 fixture）**。allowlist 显式枚举，宁缺勿滥。
  3. **合并式安装（目标已有 `.agents`/其他 skill/AGENTS.md）**：只管理 manifest 记录的文件；用户自带的其他 skill 与文件原样保留；`AGENTS.md` 用 **managed block 合并**（marker 包裹本 bundle 段，块外用户内容不动）；不覆盖用户内容。
  4. **生命周期补全**：install / update / uninstall / **reinstall**（= uninstall 本 bundle 受管文件再 install，用户数据不动）。**install 失败不留半安装**（原子：暂存→校验→一次性落，失败回滚）；uninstall 清理本 bundle 产生的缓存（如 `~/.cache/research-skills`），**始终保留 `kb/`、`.venv/` 及其他用户文件**。
  5. **清知识库耦合**：删 Navigator 固定 slug（改成通用/配置驱动）；开发 evaluator/fixture 不进安装包（allowlist 排除）；signer/dataset/真实 program id/个人路径不进 shipping code（czx 仅在 tests，已随 tests 排除）。
  6. **skill 元数据健康**：加/补一个 **quick validator**（每 skill：SKILL.md frontmatter 合法、`openai.yaml` 字段合法、short description 长度合规、公开脚本能从对应 SKILL.md 被发现）；修复所有不合规项。
  7. **公开文档**：产品定位为 **workspace skill bundle**，安装目标 = workspace 根（**不是 `kb/`**）；公开文档（README/docs/SKILL.md）**不得引用 clone 中不存在的 `temp/*``；`temp/` 继续私有 gitignored。docstring 里的 temp/ 引用也清成中性表述。
  8. **CI + e2e**：扩 `.github/workflows/ci.yml` + 测试覆盖：全 skill validator、干净 workspace 安装、已有 AGENTS.md+其他 skill 的安装、kb init/status、update/uninstall/reinstall、**错误 cwd 拒绝写入**、卸载后用户数据与其他文件不变。
- 边界/红线：纯打包/安装逻辑；**绝不改治理/confirmation/evidence 逻辑**；不碰真实 `kb/`（测试只用临时目录）；不 push；保留既有 install-UX 行为与安全门（install/update/uninstall 已验收，扩展不回退）。属工程卫生（Part 4.3 正交）。
- **✅ 已落地并独立验收（2026-07-17，main d07838a，405 绿）**：install-UX 先提交为干净基线（fffd5f3）→ B1 打包核心（15b826a）→ B2 卫生（2d7c6de）→ validator 排除修复（d07838a）。
  - **B1**：allowlist 用 `git ls-files`（tracked-only，未跟踪永不 ship）+ `RELEASE_PREFIXES`（skills/*、lib/research/）+ `RELEASE_FILE_MAP`（AGENTS.md/VERSION/LICENSE），排除 tests/ + eval_research_value.py；合并式安装（既有 `.agents`+用户 skill+AGENTS.md prose 保留，managed-block 合并）；原子事务（失败回滚不留半安装）；新增 reinstall；错误 cwd 拒写不回退源仓（`assert_write_target` + WORKSPACE_ROOT 发现）。**实机验**：临时 workspace 上 tests/eval 未 ship、用户 skill+prose 保留、wrong-cwd 源仓 0-dirty、reinstall/uninstall 保 kb/.venv。
  - **B2**：Navigator 硬编码 slug 删（kb.js `title.trim()`）；`skill_validator.py`（25–64 短描述 + frontmatter/interface/脚本可发现）过全 17 skill；blog-analyst 274→130 描述修；公开面 temp/ 清（README→SCHEMAS.md、evidence.py docstring、skill-evolution SKILL.md 删 dev-eval 段）；SKILL.md 示例解耦（p-openvla→p-example、czx→research-lead，仅示例非逻辑）；CI 跑 validator。
  - **B3 修复**：validator 本身 dev-only 却随 lib/research 整目录 ship → 加 EXCLUDED_NAMES（updater.py 是 runtime 保留）。
  - **whole-bundle 验收**：fresh install → 17 skill ship、tests/eval/validator 排除、VERSION+LICENSE ship、装好的 workspace 里 `kb doctor`(skill_version 0.1.0)+`kb init` 可跑、uninstall 保 kb。撤销点 tag `pre-bundleB1/B2-merge-20260717`。
  - **残留风险**：① eval_research_value.py 仍有一处 `temp/` docstring 引用——但该文件 allowlist 排除、不 ship，无用户面影响。（② manifest `version` 字段已于 dbbce03 补齐，见 3.15。）

#### R5 bundle 收敛与 token 门（2026-07-27 锁定）

- **发现面 15、L1 owner 14**：最终 `.agents/skills/` 只发现 `kb-cli` + 14 个 owner skill。四个来源 analyzer 在用户发现/路由层合并成 `unit-analyst`；原 `paper/repo/dataset/blog-analyst` 目录仅保留 script implementation namespace，不再有 `SKILL.md` 或 `agents/openai.yaml`。底层 record owner、ConfirmationReceipt、preference operation 与脚本路径身份不迁移；`unit-analyst` 是 facade，按 kind 显式映射旧 implementation identity，避免破坏 currentness、receipt 与诊断历史。`skill_directories()` 只枚举含 `SKILL.md` 的目录。
- **wiki/navigator 边界**：`wiki-adapter` 的薄路由与脚本并入 `kb-cli` 私有实现后从发现面删除；不新增 public verb。`research-navigator` 整体移到仓库根 `tools/research-navigator/`，保留 maintainer 测试但不在 `.agents/` 发布 allowlist、运行路由、偏好 registry 或安装产物中出现。
- **tests 与 metadata 单一来源**：测试树机械迁到仓库根 `tests/`，用 `tests/repo_paths.py` 解析 repo/runtime/skill 路径，禁止继续依赖 `parents[N]`；pytest、CI、CONTRIBUTING 与 installer exclusion 同步。discoverable skill metadata 的 SSOT 为 `.agents/skills/metadata.yaml`，`tools/generate_skill_metadata.py` 机械生成并保持 tracked 的每个 `agents/openai.yaml`；CI/validator `--check` 同时拒绝缺失、额外、漂移与孤儿 metadata。
- **Q4 token gate**：固定用 dev-only、零付费的 `tiktoken` `cl100k_base` 对 UTF-8 文本计数；每个任务组合为 `.agents/AGENTS.md + .agents/AGENT_GUIDE.md + 当次唯一 discoverable SKILL.md`，任一组合必须 `<=8000` tokens。全局两文先去除重复机制细节，skill 只保留触发、Agent authoring contract、停止/交接与场景澄清；可由 parser/validator 强制的 schema、flag、枚举和错误规则移入代码/SCHEMAS，不靠提示词重复。gate 报出逐文件与最坏组合，禁止用忽略 frontmatter/代码块等方式少算。

#### R5 G5 批量园艺（2026-07-27 锁定）

- `kb add <source> [more...]` 是唯一公开变化的原动词扩展，接受 `1..20` 个目标；每项独立 kind inference，但整批在 workspace 外完成安全 snapshot/parse/preference preflight，再在一个 root lease、一个 journal、一个 exact target set 和一个 checkpoint 内 all-or-nothing 提升。输入顺序决定稳定结果顺序；同源 current duplicate 是 idempotent skip；批内 identity/byte duplicate 合并为一个结果；任一 unsafe/malformed/conflict、stale token、late source drift 或写故障使零 canonical 写。远程 repo 缺安全本地快照时整批只返回待 Agent 本地化清单，不部分入库、不逐项询问。`auto_deep_read` 可在批量 materialize 后为每个新 unit 准备 scaffold，但 Agent fill/verify 仍逐 unit 且只在整批落地后执行；用户面只给总计与一次后续询问。
- “园艺/整理积压”仍是自然语言路由，不新增 verb。`kb next/status` 的同一 candidate snapshot 必须覆盖：已 verify 待人确认、等待 Agent fill/verify、普通 confirmed survey 的 stale rebuild、可恢复中断、到期 monitor 和安全的 taxonomy rebuild。候选按 blocking > stale > pending，公开 `kb next` 最多 3 步；所谓清 pending 只可分类/继续/展示，绝不删除、defer、自签或把判断降成事实。
- ordinary survey stale 由 anchored/no-follow snapshot 扫描产生 `rebuild-stale-survey` Agent candidate，保存旧 judgement identity、stale reasons 与 exact current binding；私有 prepare 创建新的 fill/verification/pending judgement，绝不复用旧 ConfirmationReceipt 或在查询时改写。taxonomy/governance rebuild 只机械重建派生 catalog，事务结束必须 checkpoint exact taxonomy/pool/index 路径。过期 `.research-intake-*` 只在 ownership/mode/TTL/ordinary-tree 全部可证明时回收；活动 token、symlink/special/未知目录保持不动并报告。

---

## Part 4 · 现状 → 目标差距（施工地图）

> ⚠️ **本表是 2026-07-09 设计时的"现状"快照（施工起点），不是当前实况。** 此后地基 + Wave3 三 analyzer + 自动驱动均已落地，表中"当前实测"列描述的是**改造前**状态。**实时落地状态以 `temp/BACKLOG.md` 为准。** 保留本表用于回看"从哪起步、原计划怎么走"。
> 每行：子系统 · **当前实测状态（改造前）**（带证据）· **与目标的差距** · **粗略工作量**（S=小/M=中/L=大）· **依赖**。

### 4.0 地基（跨子系统，必须先做）

| 地基                                  | 当前                                                                                     | 差距                                                                                 | 量          | 说明                                                      |
| ------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ----------- | --------------------------------------------------------- |
| **证据层（原则2）**             | `information_types` 有，但**无 claim→evidence schema**；判断只能追到整条 record | 定义`evidence_refs`（unit+artifact+locator+短逐字quote+summary）+ 脚本校验逐字存在 | **L** | **一切的地基**：3.2/3.5/3.6/3.7/3.10 都依赖它。先做 |
| **PDF/HTML 双源管线（3.1+B4）** | `backup_source` 只快照 HTML；PDF→`file_hash=""` 什么都不存；默认无 PDF backend      | 真下载 + arxiv HTML 优先 + PyMuPDF4LLM 轻量默认 + 两套 locator                       | **L** | 无源就无据，与证据层并列地基                              |
| **kb add 两阶段化（原则1/B1）** | 纯 headless 一步产空壳                                                                   | 拆成 脚本备料 → agent 填理解 → 脚本验证落盘                                        | **M** | 改的是工作流契约，牵动所有 analyzer                       |
| **确认门验实质（原则3/3.11）**  | **空心门**：空 core_content 可盖成 confirmed/fact                                  | 拒绝空内容 promote + 分两轨（事实类/判断类）                                         | **M** | 高杠杆快赢；修 0/314 的根                                 |

- ✅ **决策（2026-07-16 锁定）—— installer / runtime distribution（审查 P0.3）**：
  - **病根（审查坐实）**：① `preflight_yaml` 只测**当前/`RESEARCH_PYTHON` 解释器**是否有 PyYAML，`set -e` 下失败即 abort，**从不回退到它承诺的受管 venv**（文档已披露 preflight，但"无需 PyYAML"的承诺与之矛盾）；② 当前 Python 恰有 YAML 时 `bootstrap.py` 命中即 return **不建 venv**，PDF backend（`pymupdf4llm`）安装器只挂在建-venv 分支下 → **PDF backend 可能永久缺失**（正是本仓测试套 system-python 下 2 个 fitz 失败的根因，见 [[test-suite-needs-managed-venv]]）；③ 默认同仓 `--project .` 安装让 Codex/Claude 读到**开发者版 `AGENTS.md`** 而非 end-user auto-drive 规则（`.agents/AGENTS.md`）。
  - **目标**：① preflight 缺 YAML 时**回退到受管 venv 建流程**而非 abort（兑现"无需预装 PyYAML"）；② bootstrap **无论当前 Python 是否有 YAML，都确保 PDF backend 可用**——要么建 venv 装 `pymupdf4llm`，要么在既有解释器里确保其在场，`kb doctor` 如实报缺并给一键补装；③ 同仓安装场景下，分发给运行时的必须是 `.agents/AGENTS.md`（end-user 规则），开发者版 `AGENTS.md`/`CLAUDE.md` 不进用户运行时装配（本项属安装策略，量 M，可与其它 track 并行）。
- **首次安装 UX 合同（2026-07-17 锁定；2026-07-18 补充快捷命令提示）**：`install.sh` 的交互向导面向未接触过本系统的用户，采用单列、短句、数字选择和安全默认值；主路径只解释“做什么 / 给哪个 AI 工具 / 放在哪 / 是否创建终端快捷入口”，不要求用户理解 scope、symlink、manifest、managed block、venv 等实现词。无效输入必须原地重问，不能因一次输错直接退出。执行前摘要只列目标与用户可感知的改动，并明确研究资料不会因 update/uninstall 被删除；完成页只给自然语言和 `kb <verb>` 伪 CLI，不暴露内部脚本路径或要求用户拼接裸命令。用户选择“创建 kb 快捷命令”后，向导必须说明安装完成后可在终端先运行 `kb help`、再运行 `kb init`；若快捷入口目录不在当前 `PATH`，完成页不得假称可直接使用，必须说明把上方提示的目录加入 `PATH`、重新打开终端后再运行 `kb help`。安装器只提示，不自动修改 shell 配置；AI 对话中的 `kb <verb>` 不受终端 `PATH` 影响。`--help`、dry-run 和错误诊断属于显式技术界面，可保留参数与路径，但必须分组清晰；既有 flags、非 TTY fail-fast、退出码和安装安全门保持兼容。颜色仅作辅助，`NO_COLOR`/dumb terminal 下信息层级仍完整。
- **重复安装分流 + 可恢复卸载合同（2026-07-18 锁定；2026-07-19 补强边界）**：入口菜单显式列出“首次安装 / 更新 / 重装或修复 / 卸载”，不得再用“安装或重新配置”映射到纯 `install`。交互式流程若在“首次安装”目标中识别到本安装器的有效 copy manifest，不直接报错，而是二次询问“更新（安全默认）/ 重装或修复 / 取消”；更新只同步源变化并保留 drift gate，重装重新铺设全部受管文件以修复损坏，不能静默把安装升级为重装。显式非交互 `install` 遇已有安装继续 fail-closed，避免自动化隐式改动作。卸载 helper 在读取 manifest 前必须用 `lstat` 验证 `.agents` 根与 manifest leaf 都是边界内的真实目录/普通文件；任一祖先或 leaf 为 symlink、类型变化或不可验证时 fail-closed，不能读取、删除或 prune 链接目标。卸载只删除仍与 manifest digest 一致的 `.agents/**` 普通受管文件；内容 drift、类型变化或外来 symlink 一律保留并告警，移除 manifest 后这些残留成为用户自管文件。`AGENTS.md` managed block digest 若已变化则整文件保留并告警，未变化才移除受管区块；区块外用户文本始终保留。卸载同时清理 manifest-owned Python 模块对应的标准 `__pycache__/*.pyc` 运行缓存，但只接受可由受管 source 与受支持解释器 cache tag 严格推导出的标准文件名；`core.user-owned.pyc` 这类同前缀异型文件、symlink 和与受管模块无关的 cache 一律保留，避免把用户文件或 install smoke/runtime 产生的缓存误报为可删对象。project/system/legacy 卸载都必须无条件尝试清理“目标仍匹配”的 `kb` 快捷 symlink，不依赖本次进程是否记得安装时的 `KB_ON_PATH`；普通文件或外来目标绝不删除并告警。`kb/`、`.venv/` 和未进 manifest 的用户文件始终不动。
- **根文档 symlink 保真（2026-07-23 对抗复审锁定；post-fix 收紧）**：source/self-contained 安装若目标 `CLAUDE.md` 是项目内精确指向 `AGENTS.md` 的 symlink，该链接本身已经让两端共享同一规则，安装器不得再写会形成自引用的 include block；symlink 在 install/update/reinstall/uninstall 全生命周期保持原类型与 target。其它 symlink 不跟随、不替换，fail-closed 并保留。update/reinstall 的预检必须以现有 manifest 的真实 agent 配置为准：Codex-only 安装不得因为临时默认值而拦截不归安装器管理的 Claude link。任何 managed-block helper 都先 `lstat`，不得以 `-f` + 临时文件 rename 把链接静默物化成普通文件。

### 4.1 逐子系统

| #    | 子系统      | 当前实测                                                                                              | 差距                                                                                    | 量          | 依赖                            |
| ---- | ----------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ----------- | ------------------------------- |
| 3.1  | 入库/源     | PDF 不归档、无 HTML 优先、backend 默认缺                                                              | → 见地基「双源管线」                                                                   | L           | —                              |
| 3.2  | 论文分析    | 初筛=关键词计数(`_grade(len(hits))`)；note=模板；`core_content` 8字段全空                         | 入库直达 deep-read；agent 产类型+对应五要素并挂据；脚本只解析/裁图/验据                   | L           | 证据层+双源+统一深读            |
| 3.3  | 仓库分析    | README+目录名启发式，无符号索引                                                                       | 入库文件级(能力边界)+按需符号级细读                                                     | M           | 证据层                          |
| 3.4  | 博客分析    | 107行占位符，字段全「待确认」                                                                         | agent 产 claim/可信度(仅网页)；脚本取文切段                                             | M(scope小)  | 证据层+两阶段                   |
| 3.5  | 检索        | 词级 substring`rank_records`                                                                        | **agent 答题走原生能力**(Grep/Read+parse-cache locator)；`kb find` 脚本保留现状 | **S** | parse-cache 有页码即可(来自3.1) |
| 3.6  | 综述        | 数 tag 直方图                                                                                         | 标准 survey 模板 + evidence-first(每格挂据/observed vs inferred/对比表) + 时间锚点      | L           | 证据层                          |
| 3.7  | idea/陪练   | 有 capture/generate/analyze/review/select；**无讨论模式**(discussion-archivist 只 archive)      | idea-workbench 加陪练模式(专家/审稿人,复用 evidence-pack)，每结论落盘                   | M           | 证据层(evidence-pack)           |
| 3.8  | 方法设计    | `resource_constraints: []` 硬编码空、matrix 行硬编码，**不读 resources**                      | 读 profile.resources 缩放矩阵+不现实标红+主动提资源需求                                 | M           | 3.14 resources 接线             |
| 3.9  | 实验        | `parse_metrics→dict[str,str]`(纯字符串)、不验 artifact、诊断不比对                                 | 轻度强类型指标+验 artifact 存在+诊断拉最近N轮+baseline/milestone 常驻对比               | M-L         | —                              |
| 3.10 | 报告/大纲   | 事件行 dump；**无 outline verb**(仅 weekly/ppt/stage/writing)                                   | 从 claims+events+evidence 组自包含稿；加 outline verb；缺输入标 missing 不脑补          | M           | 证据层+reporting-events 覆盖    |
| 3.11 | 确认/治理   | 空心门(实测空note→confirmed)                                                                         | → 见地基「验实质」+关键决策/insight 主动询问                                           | M           | —                              |
| 3.12 | 导航/注意力 | 列表切片；首页恒「暂无已确认」                                                                        | 按 阻塞证据>stale>pending 排「最该看的N件+为什么」                                      | S-M         | 3.11 分轨道数据                 |
| 3.13 | 监测/自校正 | 无                                                                                                    | **不做定时扫描**；仅会话内矛盾→主动询问+更新(多为 agent 行为+一个 flag)          | S           | 证据层(判矛盾要据)              |
| 3.14 | 配置/个性化 | 仅`autonomy.auto_execute_scope` 被消费；reporting_style/term_style/personalization **无人读** | 接 autonomy/reporting_style/resources 到下游 + 记忆模块主动记忆偏好(走确认门)           | M           | learnings 机制已有              |

### 4.2 施工顺序（依赖驱动，非承诺排期）

1. **第一波·地基**：证据层 schema + PDF/HTML 双源管线 + 确认门验实质（后者是快赢，可先插）。**没有证据层，上层全是沙上建塔。**
2. **第二波·把三个 analyzer 做实**（依赖第一波）：3.2 论文 → 3.4 博客 → 3.3 仓库；同时 3.5 检索接原生能力（便宜，可并行）。
3. **第三波·产出侧闭环**：3.6 综述 → 3.7 陪练 → 3.10 报告/大纲 → 3.9 实验验证。
4. **第四波·体验层**：3.11 分轨道+主动询问 → 3.12 注意力排序 → 3.14 个性化接线+主动记忆 → 3.8 方法读资源 → 3.13 反应式矛盾。

> **验收锚点（复用 G5）**：`RESEARCH_VALUE_EVAL_DESIGN` 的研究价值 benchmark 是这份施工的尺子——每波做完重跑，看接地率/门控空心率/各轴召回是否真的涨。**先建尺子(G5)，再动地基。**

### 4.3 与已有 roadmap（BACKLOG/OPTIMIZATION_PLAN）的关系

- 旧 roadmap 重心是**重构+打包+发布**（god-file 拆分、install.sh、OSS readiness）=工程卫生，**与本 SSOT 的科研价值改造正交**，不冲突、可并行或穿插。
- 本 SSOT 的地基（证据层/analyzer 重定位）是**新增主线**，优先级应高于纯重构——除非重构是它的前置（如 records.py 拆分利于加 evidence schema，则顺带做）。
- 冲突时以本 SSOT 为准（Part 0 铁律）。

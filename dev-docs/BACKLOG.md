# Backlog（本地 gitignored，作者存档）

## [进行中 2026-07-24] R7 可用性闭环 + 循环对抗收敛

- **用户授权**：循环执行“对抗 review → 独立复现 → 修复 → 冷验收”，直到完整可用；允许 subagent、多 worktree、自动版本管理、暂存与 commit。仍不自动 push/tag/publish，除非用户另行授权。
- **R6 结论纠正**：新三路冷审推翻“P0–P3 归零”。已复现的发布阻塞包括：survey 无 ConfirmationReceipt/复合链；PreferenceSelection 多数 consumer 未强制接入且存在 soft fallback；普通对话多项 review 失败并提前消费 snapshot；route 为 substring 单 winner；Agent-next 漏 judgement owner 且 JSON 暴露 legacy score winner；monitor completed outcomes 无 disposition consumer。
- **P2 收口**：Obsidian sheet 增加 public id/来源/expiry/消费状态；终端 continuation 定位诚实；navigator status 内部依赖澄清或拆除；paper 六维结构化筛选；删除 orchestrator 通用协议中的 ML 过拟合段；help 补核心自然语言入口；installer plan 提供 summary+JSON。
- **设计状态**：`SYSTEM_DESIGN_SSOT.md` 已新增 R7.1–R7.6；任何实现不得退回规则选语义 winner、脚本理解材料、自动确认、裸命令用户面或非事务批量写。
- **施工策略**：建立 disjoint worktree tracks；每个承重修复小步 commit。主代理负责 SCHEMAS/运行规则/公开文档/版本/集成，逐条独立复现后合并。每轮修完由未参与开发的冷 Agent 重新从用户任务驱动，发现新 P1/P2 就回到下一轮，不以测试数量代替完整性证明。
- **版本策略**：R7 功能闭环完成并通过本地冷验收后从 `0.2.0-rc.6` 自动推进到下一 RC；若仍缺 hosted CI/真实 Obsidian 等外部门，保持 RC，不宣称 stable/GA。
- **2026-07-28 post-campaign 资源归并已完成**：`unit-analyst` 现统一持有 paper/repo/dataset/blog 四个 canonical script，所有新路由由共享 registry 生成；按用户反馈，四个旧 skill 资源目录已彻底删除，持久 owner identity 仅作为协议身份保留。fresh install、旧 manifest update 删除、15-skill validator、Python 3.9 AST 与最终 `2317 passed, 18 skipped` 全绿；首轮归并提交为 `d53b0d4`、`5bda2bd`、`f99fa35`，彻底删除提交为 `ff29c55`、`6114973`，最终 closure 文档另提交。
- **R8 冷审新增已复现**：route validator 把关键词命中误当 owner allowlist；零证据 survey 虽有 durable composite state，却未进入 `kb next`，重启后不可发现。设计已锁定为“完整正式 owner catalog + hints”和“composite state 一等 next candidate”，施工与回归进行中。
- **R12 冷安装新增已复现（2026-07-25）**：program-bound confirmed survey 的 `confirmation_binding.claim_ids` 被 report 的通配 `_ids` 扫描误当 unit id，阶段报告只显示 survey event 摘要而未加载当前 confirmed survey claims + verbatim evidence。SSOT/SCHEMAS 已锁定 exact unit-id allow-list 与 survey 一等 report claim source；独立 worktree 正在施工，修完回到完整套件 + 最新安装副本冷验收。
- **R12 report P1 已闭环**：survey claims/evidence 进入正式报告，事件 binding 全量重建比较，跨 program copy/decoy path/缺 owner/tampered receipt fail closed；mutable judgement title/summary/tags 不再冒充 confirmed substance。独立复验 122 项全绿，旧 experiment 断言已按 canonical claims + neutral timeline 更新。
- **R12 idea P2 已复现并施工**：三 idea `prepare all → fill all → verify all` 被全 KB corpus byte equality 隐性串行化，prepare retry 还会清空非空 fill。设计改为 frozen allowlist + cited-artifact exact revalidation，未引用并行变化不 stale；prepare 先验拒绝覆盖 Agent 内容。隔离 worktree 施工中。
- **R12 idea P2 首版已合入、二次对抗继续**：三 idea 批量并发、cited-only revalidation、多轮 fill 消费、失败可重试与 183 项 focused/adjacent 已绿。二次冷审复现新 P1：协同重写 corpus + orientation + fill 可自签 prepare 后语料。SSOT/SCHEMA 已锁定 owner-held canonical `idea-authoring-anchor/v1`；正在补 semantic record anchor、generation bundle anchor、永久 repro 与再冷验。
- **R14 idea/recovery P1 已闭环（2026-07-25）**：generic idea bundle 的 index/ancestor symlink 可被 transaction writer 替换，macOS `/var` alias 又会在恢复完成后因结果投影抛错；现已加入 target-discovery + locked lexical preflight、canonical KB root 投影与 leaf/ancestor/victim 零写回归，idea/recovery 组合 161 项通过。
- **R15 journal P1 已闭环（2026-07-25）**：全量套件固定在 17% 挂死，根因是 abort 对 `runs/` 目录中的 FIFO 执行 blocking open。journal 现以 lstat 分类，普通文件才读取 bytes，特殊节点只作 identity sentinel；begin 预存 special fail-closed，中途换型可无阻塞恢复。postcreate+recovery 121 项与修复后完整套件 **1,682 passed**。
- **R15 detached update P1 施工中（2026-07-25）**：copy install 的 `choose_update_source` 原 action 缺 branch 且没有 executor，用户回答无法写回 manifest。SSOT/SCHEMA 已锁定 Agent 对话选择 → manifest byte-digest CAS 原子重绑 → 自动只读 re-check → 独立更新授权；独立 worktree 已完成初版，主代理正复审 local-checkout 最小字段与 option-like origin 边界。
- **R16 常规冷验收 PASS、完整性审查 FAIL（2026-07-25）**：精确 `9af1c9c` 的常规 installed-copy/用户路径与 1,695 tests 全绿，但另一条对抗线由主代理独立复现 4 个 P1 + 1 个 P2：旧 incomplete root 可在新 commit 后被 resume 覆盖；journal 提前 resolve leaf symlink；detached local/no-remote 可空 branch 重绑；installer/rebind 不共享 manifest lease；损坏 journal target set 只恢复交集。已先在 SSOT/SCHEMA 锁定 quarantine + newest-first、lexical target、target-set exact integrity、attached-local 与共享 lease，进入 R17 两轨并行修复。
- **R17 recovery 初轮已合并、follow-up 继续（2026-07-25）**：`1eb140d` + `61780ea` 落地 incomplete-root quarantine、journal envelope/target-set integrity、lexical symlink、anchored target snapshot/digest/restore、resume single-consumption 与 root-last terminalization；主代理独立跑 373 项全绿。代码复核继续发现 source-entry ctime/read-view 与 snapshot-material/journal-root Path 链未完全 anchored，已回派定向复现与修复，未宣称收口。
- **R17 updater/installer 冷审推翻首轮“无 P1”（2026-07-25）**：首轮四提交把 suite 推到 1,723 passed，但冷 reviewer 独立复现 6 个 P1：updater apply 未传 manifest CAS、rebind post-replace fsync 失败却留新 provenance、uninstall 在 lease/CAS 前改 Claude 配置、source_provenance FIFO/symlink 不安全、Agent plan 给旧 dry-run targets 签新 manifest、root fsync failure 反向固化不可逆卸载。SSOT/SCHEMA 已补 same-snapshot apply/read、rebind rollback、outer config 同事务、dry-run→plan exact expectation；原 track 已恢复施工，版本仍冻结 rc.6。
- **当前非阻塞 P2**：discussion archive 仍诚实隔离为 pending/unverified 并要求拍板后转 orchestrator decision；指定历史 restore 仍主要由 Agent 私下发现 operation id。两者不影响已支持的讨论存档→决策和 `kb undo` 常用路径，留下一候选深化，不得在 rc.7 文档冒充已完成。
- **R17 冷产品验收新增 continuation/status 缺口（2026-07-25）**：已独立从代码证实 orchestrator 只枚举 unit/program/composite/monitor，漏掉 standalone `literature-search` stage；因此 terminal include/maybe 候选在新会话中不会回到 `kb next`。另有零 unit、已有 program 时 `kb status` 只说“尚未收录资料”。SSOT/SCHEMA 已锁定 standalone search 的 resume/selection 互斥 owner 路由与 program 摘要，待定向实现/回归；版本继续冻结 rc.6。
- **R17 冷产品验收新增 repo review P1（2026-07-25）**：真实 repo-analyst verify 后，public review 依粗 classifier 展示，但 canonical card discovery 因 `readiness_violations` 漏传 record external-source contract 而拒绝，造成对话确认失败，并可让 Obsidian 多项批次全体零应用。代码复核已证实 caller 缺参和展示/apply 两套 ready 条件；设计锁为 canonical discovery 单一 ready set + repo evidence context 一致传递，禁止放宽 file:line evidence gate。
- **R17 冷产品验收 P2/P3（2026-07-25）**：真实 RT-1 arXiv HTML 文字可读但 22 张图片全 404，仍被选为 degraded 而未尝试 PDF；已锁定 arXiv 大比例媒体失败的 pre-publication fallback 门。报告默认英文 scaffold 与中文产品面不一致，已锁定 default 中文 + task-bound 显式英文偏好。standalone candidate materialization 的 owner stdout 仍会打印内部路径/命令；需提供 Agent 私有 protocol + 安静执行 adapter，不能新增面向用户的裸命令。
- **R17 recovery durability follow-up（2026-07-25）**：主代理最小复现 `_replace_staged_at` 发布新 target 后对 target parent 的 `fsync` 调用为 0，absent removal 同样未持久化；命令级恢复可能在断电级崩溃后回退。SSOT/SCHEMA 已锁定 replacement identity + digest + parent-fsync 前保留 backup、失败回滚再 fsync 与唯一材料保留，待独立恢复轨补故障注入并施工；rc.6 继续冻结。
- **R17 integration full-suite follow-up（2026-07-25）**：报告/媒体合入后完整套件首跑 1,805 passed / 3 failed。两项为新中文 presentation contract 后的旧测试夹具漏同步；一项为真产品缺口：read-only audit 遇严格 journal envelope 拒绝会直接 `SystemExit`。现已让 malformed/legacy journal 收敛为 path-safe recovery finding，补零写/不泄漏回归，并同步 experiment/monitor 原安全语义；三模块 76 项已全绿，待剩余 tracks 合入后重跑最终全量。
- **R17 第二轮交叉审查（2026-07-25，版本继续冻结）**：首轮 tracks 合入后完整套件 **1,866 passed**、20/20 official quick validation、Python 3.9 AST 全绿，但两名未参与实现的 reviewer 报出且主代理逐条复现：canonical record reader 跟随 symlink/FIFO 阻塞、review 接受重复 YAML key、literature stage candidate/exact-schema 与 ancestor rename race、用户选择未绑定展示快照、stage validate→digest symlink race、owner 已提交但 nonzero 被误报、旧 append-only selection receipt 被展示字段废掉、protocol 名称未预占/目录未 durable、selection JSON 重复 key、capture_output 无界，以及 synthetic continuation 泄漏内部 ID/英文 reason。SSOT/SCHEMA 已锁定共享 anchored strict reader、display binding、canonical-outcome-first、durable preclaim/bounded streaming 与 type-aware 中文 public projection；拆成 record/read 与 literature adapter 两条修复轨，修后重新完整套件 + installed-copy 冷验收 + 交叉复审，未通过前不升 rc.7。
- **R18 installed-copy 冷验收新增三项（2026-07-25）**：临时 workspace 已真实完成 Agent plan/install、20 skills、kb 主入口、真实 arXiv 双选入库、Obsidian 两项对话确认、update/uninstall；但主代理又独立复现 uninstall plan 零写却声称“不再受管理”（P1）、用户自有 `AGENTS.md` 往返多一换行（P2）、可用 managed venv 在 no-op update 被误报未就绪（P2）。已锁定 preview truth、managed-span 外 bytes 精确恢复与 workspace venv readiness，第三条 disjoint installer track 施工中。
- **R18 record track 首次集成复核未过（2026-07-25）**：`d84b266` 的 25 个恶意 record reader 回归与 agent 自报 451 项均绿，但主代理扩大到 survey duplicate intake 后得到 **468 passed / 1 failed**：合法 confirmed duplicate 的 prepared record 与严格重读 current record 不相等，被 source-intake CAS 正确拒绝。不得放宽 prepared gate；已回派定位 normalize/snapshot 字段漂移并补 follow-up，说明本轮继续坚持“独立扩大复测”，不能以 track 自报通过直接收口。
- **R20–R21 canonical consumer 收口（2026-07-25）**：report、idea、monitor、program decision、method selection 与 survey 已迁移到 exact record/evidence/unit-tree snapshots；主代理独立 targeted 回归分别 229、105、102 项全绿。survey 选择不再返回 caller stale dict，binding 的 record/receipt/artifact hashes 来自同一 bounded tree snapshot，并按候选及时释放内存。
- **无付费/Key 边界已固化（2026-07-25）**：requirements、安装说明、README/USER_GUIDE、SCHEMAS 与 release regression 明确核心流程不要求外部 API Key、付费检索额度、商业数据库或付费插件；无外部发现工具时 literature stage 可恢复地停在 `blocked_no_search_tool`，不索要密钥。静态/发布回归 31 项全绿。
- **R22 generic confirmation P1 施工中（2026-07-25）**：主代理独立复现 detached 旧 record 与 canonical replacement revision 相同即可被确认并覆盖；已锁定唯一 `CanonicalRecordSnapshot` 必须贯穿授权、evidence capture 与 final write CAS，同 bytes 新 inode/目录替换也零写拒绝。owner direct confirm 与 KB/Obsidian batch 同合同，独立 worktree 正在实现。
- **R23 judgement read P1 已锁定（2026-07-25）**：主代理已复现 `load_bound_judgement` 的 safe-path→`load_yaml` 重开可读到替换 unit/sidecar；报告 survey 还会重复加载 subject。SSOT/SCHEMA 已要求 unit/side judgement、event binding、receipt、survey claims 在一次 `BoundJudgementSnapshot` 内完成并最终 current-check；相邻 `program:<id>` bare-Path evidence 正由独立 reviewer 复现。基线 report/review/survey 156 项全绿，修复 handoff 已备好，待 R22 merge 后施工。
- **R23 审查完成（2026-07-25）**：独立 reviewer 共复现 4 项：event-bound report 接受旧 unit；report/load_decisions 接受旧 side judgement；review 展示旧 side card；`program:<id>` 两个附件可在 workflow rename 中拼成从未共存的 receipt 组合并错误 current=True。program evidence 也纳入 R23 anchored snapshot handoff。
- **R24 冷产品验收与 P2 闭环（2026-07-25）**：隔离 Agent-plan 安装 189 targets/0 conflicts/20 skills，init/status/next、无检索工具 stage、survey 七阶段、偏好选择性披露、Obsidian batch 对话授权、report 全链完成；无 P1，评分成熟 8.4/易用 8.2/智能 8.7。两项 P2 已修并合入：blocked search 给 3 条无 Key/付费/插件恢复路；literal fact/factual/operational 事件进入事实轨且冲突 judgement 信号仍优先。focused 141 项全绿。
- **最新完整基线（2026-07-25）**：主线完整 suite 首跑 `1969 passed / 2 failed`；两项均为同一旧测试要求 ancestor-symlink 必须到 fill guard 报 ValueError，而 strict record reader 已更早以 Record not found 隔离。主代理复现后仅更新测试接受两种 fail-closed 阶段，6 个攻击组合 focused 全绿；最终代码合入后仍须再跑完整套件。
- **R23–R25 最终发布栅栏（2026-07-25，施工中）**：unit/side/program judgement 已改为 exact snapshot-bound，report 装配与渲染增加整批 final-current gate，portfolio history 写入锁内保留并重验原始 snapshot；同时修复 macOS `/var` alias、side judgement O(N²) 捕获、legacy decision、repo external evidence survey eligibility。新一轮对抗继续复现“report 已加载 record 后 parse-cache/repo 证据被替换仍发布”的竞态，已补 evidence validator，扩大测试中。
- **R25 严格离线安装（2026-07-25，已提交待冷验）**：Agent plan/apply 在首个 `python3` 缺核心包时会继续寻找 PATH 后续已有兼容解释器；严格 `PIP_NO_INDEX=1` 下零 `.venv`、零网络完成安装与 `kb help`。installer/bootstrap/Agent plan 70 项全绿；不引入 API Key、付费服务、订阅、商业数据库或插件。
- **R25 离线 plan/apply P2（2026-07-25，已闭环）**：schema 3 绑定 current/explicit/PATH 解释器的 canonical path、文件 identity、core capability 与选择来源，并在 apply 首写前重跑同一选择规则；PATH 漂移零写拒绝，ready managed venv 保守列 conditional tree。独立分支 121 项、主线联合 87 项全绿；固定 `23861a7` 冷安装计划 188 targets/0 conflicts、离线 apply + installed `kb help/doctor` 通过，换 PATH 后 workspace 保持空目录。
- **R26 formal publication 复审（2026-07-25，已复现并并行施工）**：冷 reviewer 复现 report render 最终验后到 write 仍可落旧 claim、portfolio history 写前最终验后仍可落 stale decision 两项 P1，以及 factual event→unit source N² 扫描 P2。SSOT 已补 transaction 内正式文本选择 + post-write rollback gate、portfolio post-write rollback 和一次 unit snapshot index；拆成 report 与 portfolio 两个 disjoint track，修后再冷验。
- **R26 public review Python 兼容性（2026-07-25，已闭环）**：owner loader 现按 path-scoped 稳定模块名在执行前登记 `sys.modules`，执行/接口失败仅身份保护地清理本次模块；public program-owner route 与 5 个 lifecycle 回归冷验全绿。
- **R26 commit-bound source guard（2026-07-25，已闭环）**：root-level 与 child lifetime 两层竞态均修复。原 reviewer 在 `93a4e89` 复验真实 owner 24/24（同进程/跨进程 report+portfolio）全部在 preflight/body/render/load/write/checkpoint 前通俗中文拒绝，无 child journal/输出；root gap 12/12 exact rollback、unguarded nested 4/4 正常、四个完整套件 307 passed，无 P1/P2。设计限制是 guarded publication 必须作为 authoritative root，外层写操作结束后重试。
- **版本门（2026-07-25，已完成）**：`dfcc0b5` 已升 `0.2.0-rc.7` 并同步 VERSION/README/USER_GUIDE/DESIGN/SECURITY/CHANGELOG 与版本一致性回归。最终完整 suite `2126 passed / 17 existing dependency warnings`；20/20 validator、150-file Python 3.9 AST、`bash -n`、diff、无付费/Key/插件门全绿。全新 installed-copy 冷验 `186 targets / 0 conflicts`、32 focused semantic tests，无 P0/P1/P2，易用 9.2 / 智能 9.0 / 成熟 8.5。仍不 push/tag/publish；真实外部来源、Obsidian GUI 与 hosted CI 保留为 tag 外部门。

## [完成并提交 2026-07-24] R6 完整产品闭环 + 0.2.0-rc.6

- **用户授权**：全部开始施工；覆盖 Agent-led 多 program 下一步、总偏好→skill eligible→Agent task selection、无插件 Obsidian 多项 review 往返、研究监测/周期复查、多 reviewer systematic ledger 与 stable release gate。
- **SSOT**：已先锁定 `SYSTEM_DESIGN_SSOT.md` R6.1–R6.6。脚本只做候选/约束/账本/验证，语义判断来自 runtime Agent；确认、证据、containment、journal/lock/CAS、用户可见输出合同不放松。
- **外部边界**：本地实现、测试、版本与 commit 已授权；push/tag/publish 暂未授权，不自动执行。监测采用 skill 账本 + 用户授权的宿主 automation，不安装 daemon 或 Obsidian 插件。
- **施工顺序**：只读代码审计 → disjoint tracks → 主代理集成/schema/docs → 冷 Agent/真实来源/Obsidian → 对抗复审 → 全修复 → version/commit。
- **实现闭环**：已补 task digest/隐私约束、Agent PortfolioDecision 单选执行门、monitor/run/stage/survey byte bindings、append-only reviewer digest/adjudication gate、current-message authorization + preview digest、passage cache rollback与逐层 no-follow dirfd；survey/literature 完整最长匹配路由；navigator 降为 dev-only；OpenAlex 仅保留只读旧 identity migration。
- **最终对抗收口**：继续复现并封住 registry 尾部 fsync 回滚、hardlink TOCTOU、checkpoint 假成功、persisted phase 回退、安装父目录 symlink、agent-plan 漏列 bytecode/父目录/卸载目标、fresh/reinstall AGENTS managed-block 认领/漂移、monitor 未闭合 schema，以及 PreferenceSelection/multi-reviewer 文档漂移。三名冷 Agent 最终 scoped P0/P1/P2/P3 均为 0。
- **最终本地证据**：默认顺序完整套件 **1,193 passed**（7 条既有 SWIG/PyMuPDF deprecation warnings）；协议闭环独立 14 passed，security 定向 124 passed，分发生命周期与 plan/apply 目标集合独立复验通过。20/20 skill validator、135 个 Python 文件的 3.9 grammar、compileall、pip check、`bash -n install.sh`、working diff check 全绿；真实仓库 `kb/` 零修改。
- **安装副本证据**：全新 `/private/tmp` workspace 完成 Agent plan → install → `kb help/init` → reinstall → uninstall；版本 `0.2.0-rc.6`、20 skills、113-file manifest、不分发 tests/validator，卸载保留临时 `kb/` 与 `.venv/`。52 个审定文件已提交为 `fe85294`（`feat: complete agent-led research workflows`）；仍不 push/tag/publish，真实来源/Obsidian 1.12.7 Reading-view 与 hosted Linux/macOS CI 是 release tag 前置。

## [已提交 2026-07-24] literature-search provider-neutral 重构 + 0.2.0-rc.5

- **用户锁定**：对外名称改为直白的 `literature-search`；OpenAlex 不再是检索源，外部文献搜索由 runtime Agent 使用当前可用 search/browser/connector 能力完成。
- **外部代码级调研**：三条独立 agent 线检查了 PaSa、PaperQA2、OpenScholar、STORM/Co-STORM、GPT Researcher、Open Deep Research、Local Deep Researcher、DeerFlow、K-Dense、LatteReview、PaperSearchQA。结论是不引入外部 runtime dependency，只借鉴 frontier、检索状态、gap-followup、分面/恢复、硬预算、系统检索合同和筛选争议结构；LatteReview 的 CC BY-NC-ND 代码/文本不复制或改编。
- **实现面**：移除 OpenAlex client 与 `literature-scout` 当前入口；新增 Agent-led skill、provider-neutral query/candidate/coverage/frontier/stop schema、run identity、DOI/arXiv/PMID/URL identity/conflict gate、resume 单调状态、预算、系统检索逐 query/discovery/screening/fetch flow 对账、当前用户候选选择/source binding 和无工具阻塞合同。
- **红线**：脚本不联网、不选 provider、不判断 relevance/gap/saturation；snippet 不作筛选或 canonical claim evidence；source-search 仍是 staging；真实 `kb/` 零改动；不 push/tag/publish。
- **对抗闭环**：架构/UX/防御三路 reviewer 多轮独立复现并最终全部 PASS；覆盖 stage/kb symlink containment、credential、authorization/source/kind binding、ghost query/candidate/duplicate/unavailable、screening/fetch/frontier/stop 回退和旧 stage/fresh run。
- **验收证据**：完整默认顺序套件 **1,089 passed**（7 条既有 SWIG/PyMuPDF deprecation warnings）；定向 literature-search 62 passed，相关路由/恢复/元数据 127 passed，compileall、shell syntax、working/cached diff check 已过。独立 copy install 验证 rc.5、19 skills、无旧 scout/OpenAlex、无 tests 打包、`CLAUDE.md → AGENTS.md`、`kb doctor/help` 全绿；版本后 32 项 release smoke 通过。已提交为 `a32cb7c`（`feat: replace literature scout with agent-led search`）。

## [完成并提交 2026-07-24] 对抗性复审全修复 + 0.2.0-rc.4

- **范围**：独立复现并修复 4 个发布阻塞（artifact byte stale confirmation、cross-unit evidence symlink escape、undo/restore 缺 after-state CAS、installer 破坏 `CLAUDE.md` symlink）与 7 个一致性/UX 问题（stage identity、DOI 跨 run 去重、block-id 检索污染、cache corrupt/stale 分类、schema gate 文案、obsidian help drift、空 review 写 runtime）。
- **版本策略**：自动推进 `0.2.0-rc.3 → 0.2.0-rc.4`，保持 release candidate；本地 stage/commit 已获授权，不 push、不 tag、不 publish，hosted CI 仍是 tag 前置。
- **文件/数据红线**：先改 SSOT/SCHEMAS 再改代码；shipping skill 只当产品源码；只用临时 KB 测试；真实仓库 `kb/` 的 6 个既有用户改动保持字节/mtime 不变；确认/evidence/recovery 门只加严。
- **验收门**：每条 finding 单独回归；完整 pytest；19-skill quick validation；compileall、installer shell syntax、diff check；git archive 自包含安装验证 root symlink 全生命周期；fresh empty review 严格零写；版本/文档/公开 16 verbs 一致。
- **原 11 项闭环**：current artifact-byte receipt、cross-unit symlink containment、recovery after-state CAS、CLAUDE link 保真、stage identity、跨 run DOI、block anchor、cache corrupt/stale、schema gate 文案、Obsidian help、fresh empty review 均已实现并有回归。
- **post-fix 对抗加固 12 项**：locked preflight 在 journal 前；mismatch 先于 workspace seed；同 batch URL 折叠；title/url factual merge；malformed/coherent cache tamper；canonical block grammar；external repo current receipt；candidate read-before-containment；malformed YAML 单候选隔离；source manifest schema；Codex-only installer manifest-aware guard。两名原 reviewer 最终精确复验均 PASS。
- **最终本地证据**：权限放行后完整默认顺序套件 **1,041 passed**（7 条既有 SWIG deprecation warnings，168.02s），包含全部 12 个 localhost browser-auth case；此前分拆的 1,026 + 3 非 socket 结果保留作诊断证据，不再是发布状态阻塞。
- **安装/结构证据**：最终源码快照 self-contained install 与独立 copy install 通过；`0.2.0-rc.4`、精确 `CLAUDE.md -> AGENTS.md`、19 skills、107-file manifest、无 tests 打包、`kb init/doctor/help`（含 obsidian status）全部验证；19/19 quick validator 通过。
- **提交状态**：用户在获知限制后显式批准；31 个审定文件已原子提交为 `58a45ac`（`fix: close rc4 adversarial review findings`）。提交后 index/worktree clean；仍未 push/tag/publish。

## [完成 + 双重独立冷验收 PASS 2026-07-23] R3 全量收尾 + 0.2.0-rc.3

- **用户范围**：直接完成上轮列出的 5 个 review UX 项、R3 五项能力、installed-copy/真实来源/Obsidian 临时验收，并自动更新版本；不 push、不碰真实 `kb/`。
- **设计结论**：FTS5 passage cache + stale read-only fallback；HTML substantive multi-candidate 已在当前代码完成，只复验；survey 绑定 upstream digests 并由读侧判 stale；experiment run fingerprint + rerun contract；恢复第 19 个 `literature-scout`，通过当前 OpenAlex API key 合同做单页有界 pull，只写 source-search staging。
- **Track A · review UX**：token expiry/GC、错误分类、成功 subject/decision、stale 新正文重显、四 owner public confirm/reject E2E。
- **Track B · retrieval/materialization**：SQLite FTS5 cache、passage extractor/locator/BM25、stale/missing in-memory fallback、`kb find` projection；独立复验 substantive main、layout table、fragment externalization。
- **Track C · freshness/experiment/scout**：survey consumer binding/staleness、run fingerprint/dedup/repeat、OpenAlex client + literature-scout skill + staging provenance。
- **集成/发布面**：主代理统一接 kb-cli find、schema/docs/skill count/version；版本推进 `0.2.0-rc.3`，保持 RC；隔离 release snapshot 完整测试、copy install、真实 source/Obsidian cold acceptance。hosted CI/remote merge/tag/publish 不在无 push 授权的本地施工内。
- **红线**：shipping skill 只当产品源码；理解来自 runtime agent；真实 `kb/` 零改动；cache 不冒充 canonical evidence；OpenAlex key 不落盘/不回显；所有业务写 journal/lock/CAS/精确 checkpoint；用户面仅自然语言 + 16 个既有 `kb <verb>`。
- **集成结果**：三条隔离 track 共 10 个提交已合入；主代理补齐 public `kb find` passage projection、共享 `surveys.py`、navigator/report stale consumer、schema/19-skill/version/docs 接线与 navigator 父目录 symlink 防护。版本已自动推进并保持 `0.2.0-rc.3`。
- **冷 finding 闭环**：真实 SQLite Query Planning 页复现 title display metadata 被复制索引、导致无关正文进入 Top-5；主代理独立复现后以 `9ab4045` 将 FTS title/summary 设 UNINDEXED、fallback 仅检索 heading/text、cache revision 升为 v2，并补 missing/current 双态回归。fresh/missing/stale/corrupt 四态重装复验均通过。
- **最终验收**：主代理与全新冷 agent 各自完整 **1,012 passed**（7 条既有 SWIG deprecation warnings）；19 个 skill quick validation、compileall、installer shell syntax、diff check 通过。全新 installed copy 显示 rc.3/19 skills/16 verbs；SQLite 官方 HTML 真实入库、Markdown/archive/23 assets、Obsidian update/status/idempotence 与 Obsidian 1.12.7 Reading view/unit→source 链路通过，未生成 `.obsidian`。review 四 owner、TTY/pipe、TTL/replay/stale，survey consumer，experiment repeat/rerun，OpenAlex missing-key 零 stage 与 mock bounded/private 全通过。真实仓库 `kb/` 零改动。
- **剩余发布前置**：hosted Linux/macOS CI matrix 尚未运行；它是 tag 前置，不是本地产品 finding。未 push、未 tag、未 publish。

## [完成 + 双重独立验收 PASS 2026-07-23] R2 judgement + workflow convergence

- **审查结论**：18-skill 全量架构审查、隔离冷 UX 与逐功能开源调研确认核心 evidence/recovery 地基可保留，但整套系统尚非端到端稳定。
- **Track A · judgement/report**：program decision、experiment diagnosis、idea discussion 统一 canonical claims/verification/receipt；report event fail-closed；为公共跨-owner review 提供稳定 discovery/route contract。discussion archive 与 survey 至少禁止无治理 judgement 进入正式输出，若本轮不能完整迁移则显式降级并留后续 migration。
- **Track B · method lifecycle**：`candidate/proposed/selected` 三态分离；prepare→agent fill→verify→confirm；确认前不推进 stage、不发布正式 method event；所有路径事务化。
- **Track C · public/recovery UX**：相同 quick setup no-op；`add→ingest` 对 duplicate 做状态感知深化；paper/blog/dataset fill 纳入 checkpoint；YAML yes/no 兼容；pytest READY 环境恢复；修 15/16 verbs、navigator 裸命令和 contributor lock 文档。
- **集成门**：三 track 文件面 disjoint；每条承重 finding 由主代理独立复现；全量测试必须默认目录顺序一次通过，另跑跨 owner review/report/method 冷流程；真实仓库 `kb/` 零改动。
- **实施结果**：三条隔离 worktree 已分别完成 judgement/report、method lifecycle、public/recovery UX，再由集成代理统一接线。公共 review 现在跨 owner 发现并路由真实 pending judgement，使用一次性、内容绑定的 snapshot token；单次 apply 最多处理一个决定，过期、篡改、重复 subject 与跨 owner 身份歧义均 fail-closed。
- **治理闭环**：program decision、idea conclusion、method selection 与 judgement unit 共享 canonical identity/content/evidence/receipt 约束；reject 会同步终结 side record 与 canonical claims。method 已拆成 prepare→fill→verify→confirm/reject，确认前不得写 selected repo、推进 program stage 或发布正式事件；事务内复查 idea/program 输入并使用 CAS 防止陈旧覆盖。
- **集成修复**：关闭独立 review 发现的 snapshot 重放、global identity、跨 owner 部分提交、fact TOCTOU、mandatory semantic fields、checkpoint 扩收与 prepare stale overwrite；public priority 被明确定义为 canonical impact class，同级按最旧优先，不另造 impact score。
- **验收结果**：主代理最终完整 non-socket suite **950 passed**；localhost navigator auth **15 项**已在本轮较早的完整套件中通过。独立集成 review、冷 UX acceptance、schema/skill drift、compileall、installer shell syntax、依赖与 diff gate 均通过；真实仓库 `kb/` 零改动。
- **已记录非阻塞 UX 后续**：细分 stale/tampered/used token 错误；成功摘要带 subject/decision；补“展示后内容变化”黑盒重显测试；扩充 idea/method public adapter 全链路矩阵；为遗留 runtime snapshot 做安全垃圾回收。
- **后续 R3（本轮不混入）**：FTS5 passage index、HTML 多候选正文、survey stale consumer、实验 run fingerprint、OpenAlex pull scout。

## [进行中 2026-07-22] 真实来源 + Obsidian 端到端 UX 加固

- **触发冷验收**：真实 Python/SQLite/Hugging Face/Markdown 入库与 Obsidian 1.12.7 实际打开后，确认 bundle/hash/安全合同大体成立，但用户体验不通过。
- **P0**：Obsidian 自动把 `.base` 的 `note.title/note.kind/note.topics` 规范化为裸 property，旧 manifest hash 因而漂移，之后 `kb obsidian update` 永久 fail-closed；canonical 13 units、投影仍 9 units。
- **P1**：Hugging Face dataset 动态页被抽成 TinyLlama 推荐卡片，正文缺失且跨空行 image-link 破损，quality 仍误报 `complete/accepted`。
- **P1**：SQLite 单格 layout table 被转成 22 个空 pipe table 包裹 fenced SQL，Reading view 显示孤立 `|`/空边框，lint 仍报 `malformed_pipe_table_count=0`。
- **P2**：Python Sphinx 页面正文完整但站点 chrome/导航占据首屏；Home 仅计数，unit 页 properties/内部 enum 占首屏，不呈现 materialization health、warning/asset 完整度、分析阶段或下一步；新单元未成知识网络。
- **锁定修复**：Bases canonical spelling + 旧 manifest 受控语义收敛；HF dataset raw card adapter + dataset identity gate；语义 root 选择/boilerplate 清理；layout-table 解包 + orphan-pipe lint；Home/unit 信息架构与 materialization health；renderer revision 升级。
- **验收门**：完整自动回归；关键节点小提交；`install.sh` 同步 `/Users/czx/Documents/knowledge_base`；从空 workspace 执行 init/doctor/status，真实 paper/complex HTML/dataset card/Markdown/repo 入库；Obsidian Home/Bases/unit/source Reading view 实际检查；应用打开后再次 update 必须幂等无 drift。最终由全新上下文 cold agent 驱动 shipping skills，维护者独立复现每个 finding。
- **冷验收后续 finding**：P1 远程 repo URL 假成功与空 claims 假待确认已由 `4df1503` / `6a779bc` 闭环；继续修复中文偏好未进入投影、本地 repo 缺 README/源码入口、网页缺失 fragment 过度降级，并在最新安装上从空 KB 重跑完整真实验收。
- **最终真实入库新增 finding**：UltraChat 数据卡因 frontmatter closing `---` 被误当 Setext 标题线，record 标题错误变成 `dataset_size: ...`；锁定为“先剥 frontmatter，HF 优先 pretty_name，否则正文首 heading”。

## [完成 + 真实 Obsidian 验收 PASS 2026-07-21] Obsidian 真实打开格式修复

- **用户 finding**：Obsidian 1.12.7 编辑视图中生成页显示 wikilink、反引号与 block ID 源码；切到 Reading view 后结构可正确渲染，但真实 Ψ₀ claim 中 `<name>` 被当 HTML 吞掉、`scripts/train/psi0/*.sh` 的星号被当 emphasis，frontmatter 长 wikilink 还被 PyYAML 物理折行。
- **锁定修复**：不写 `.obsidian/` 强改视图；Home/文档明确生成页使用 Reading view。新增 injective Markdown-safe 动态正文渲染、Obsidian 专用 no-wrap YAML、renderer revision stale 机制，并改善 claim/evidence 的人类标签；保留 heading/block 精确链接。
- **验收**：先在临时 Vault 用真实 Ψ₀ 字符样例断言，再跑完整 release snapshot；安装后只重建 manifest-owned 真实投影，canonical records/evidence 全树摘要必须不变，最后在 Obsidian Reading view 与编辑视图分别目测。
- **实现**：renderer revision 2 增加 Markdown-safe 动态正文渲染、任意反引号安全 code span、Obsidian frontmatter/Bases no-wrap、human-readable claim 状态、evidence 小节、外部来源链接/本地来源脱敏，以及 Home/用户指南的 Reading view 提示；manifest revision 与 input digest 双保险使旧投影可靠 stale。
- **回归**：新增真实 `scripts/train/psi0/*.sh`、`psi.config.train.<name>`、方括号、反引号、长关系标题、旧 renderer manifest 两类回归，projection 专项 17/17；隔离 release snapshot 860 个非 socket + 15 个 localhost auth，共 **875 tests 全绿**。skill quick validation、118 Python AST、安装脚本、依赖、diff check 全绿。
- **真实部署**：增量安装到 `/Users/czx/Documents/knowledge_base` 后，`kb obsidian status` 先正确报 stale，再重建 18 units / 1 program 并 PASS；源码/安装模块 SHA-256 一致。排除 managed/journal/runtime 的真实 KB 摘要前后均为 `9a50d0a7…208d`，人工 inbox/annotations 摘要均为空树 `e3b0c442…b855`；Reading view 真实截图确认 `<name>`、`*.sh`、下划线、反引号与 evidence 均按 canonical 字面显示，无反斜杠泄漏。投影器未生成/直接改写 `.obsidian/`；验收仅用 Obsidian UI 把当前标签切到阅读视图。

## [完成 + 独立验收 PASS 2026-07-21] 无插件 Obsidian 知识网络适配层

- **用户范围**：先不开发插件；完成 canonical KB → Obsidian 原生 Markdown/Properties/Wikilinks/Backlinks/Graph/Bases 的可重建投影，并支持精确到标题、claim、evidence block 的关系。
- **SSOT-first**：已在 §3.5.1 锁定单一事实源、managed/人工区隔离、稳定 ID、多粒度 locator、有向边唯一存储+反向推导、legacy reverse 兼容、manifest-owned 安全清理、纯读 status 与用户输出合同。
- **施工面**：新增共享 Obsidian projector/relation registry/audit；扩展 links schema 与规范化；接入 `kb obsidian update|status`；生成 Home、unit/program/topic pages 和三个原生 Bases；同步 workspace Agent 规则与用户文档；只在临时 KB 验证。
- **红线**：不加载/自调用 shipping skills；不生成 `.obsidian/`；不覆盖 `inbox/annotations`；不碰真实 `/Users/czx/Documents/knowledge_base/kb`；不把 derived/proposed relation 冒充 confirmed canonical；不削弱 confirmation/recovery 合同。
- **实现**：新增 `relations.py` 与 `obsidian.py`，canonical link 只写正向边并支持 unit/heading/block locator；兼容折叠旧 `reverse:*`。投影生成 Home、unit/program/topic、claim/evidence 稳定块与“全部单元/待确认/按主题”三个 Obsidian 原生 Bases；第 16 个公开动词为 `kb obsidian update|status`。
- **安全与恢复**：managed 区按 validated manifest ownership + digest 更新，人工漂移、unowned、symlink、类型变化全部保留并报告；人工 `inbox/annotations` 不遍历；更新走原子写、operation journal、锁与 undo，重复无变化不产生 journal churn，status 对空缺 workspace 字节级零写。
- **独立 review 修复**：补住“首投影前已有 unowned managed 文件但 status 误报 PASS”、人工区 symlink/非目录漏报、外部 title/heading 多行 Markdown 注入，以及 unit→program、program→active unit、evidence→source unit 三类断链漏审；关系备注更新补 history audit。
- **验收与部署**：隔离完整 release snapshot 最终 **873 tests 全绿**（858 个非 socket + 15 个 localhost auth），projection 专项 15/15；`kb-cli` 官方 quick validation、Python AST、installer shell syntax 与 `git diff --check` 通过。随后按用户明确授权，把当前能力包增量更新到 `/Users/czx/Documents/knowledge_base` 的受管 `.agents/` 与根规则；两个新运行模块 bytes 与源码 digest 一致，installed-copy 空库 status smoke 零写通过。真实 `kb/` 的 6235 文件全树 digest 与 Git status digest 前后完全一致；未安装插件、未写 `.obsidian/`、未生成真实投影、未 commit/push。

## [完成 2026-07-21] D2 · dataset 一等单元 + `kb next` 持久化续接 + repo 扫描隔离

- **问题复现**：截图中的 `kb next` 不是继续上一句聊天，而是重新读取磁盘状态并排序。旧实现让 confirmed repo 因 `scan_status=not_started` 被重新冒泡，同时“继续生成横向综述与技术路线图”只存在于聊天，没有 program `next_actions`，因此下一轮无法恢复该承诺；HIW-500 数据卡还被误归 repo，JailWAM 则因完成态被机械刷新打扰。
- **SSOT-first**：锁定 dataset 一等 kind、唯一 workflow classifier 的 done short-circuit、durable program action 优先、聊天承诺不得虚构成 next、repo scan 只接受真实代码树、机械派生不得撤销有效 confirmation，以及显式可恢复迁移合同；施工规格为 `temp/codex_prompt_d2_dataset_next_integrity.md`。
- **dataset 闭环**：新增 `d-` ID 与 `kb/units/datasets/`、schema/payload/index/search/program/report/navigation/review/confirm 接线，并新增 `dataset-analyst` 四要素 `positioning/composition/schema_access/suitability_risks` prepare/fill/verify 流程。Hugging Face `/datasets/` 精确推断为 dataset，model page 不误判。
- **迁移**：新增只读 dry-run + 显式 apply 的 repo→dataset 迁移；精确 journal targets，排除 `.journal/.runtime/raw/source`，保留 legacy id、history、links/program attachment 与旧确认审计，但因 subject kind/id 改变清空 canonical confirmation，要求重新 evidence verify + 用户确认；可 `undo`。
- **续接修复**：`safe_unit_step` 对 canonical `done` 立即无动作；持久化 program `next_actions` 排序高于 loose maintenance；新增 journaled `add-next-action / resolve-next-action` owner 生命周期。workspace Agent 规则要求批量综述/路线图先创建或复用 program、attach units 并写 next action，之后才可承诺 `kb next` 会继续。
- **repo 扫描修复**：remote URL、HTML snapshot、dataset/model card 不再当 repo root；机械结果写 `entrypoint_candidates`，agent judgement `entrypoints` 不被覆盖；扫描不再手工改 status/confirmation。source intake 显式写 `scan_applicability` 与原因。
- **公开契约**：skill 数更新为 18，README/USER_GUIDE/DESIGN/SCHEMAS/runtime AGENTS 与 owner SKILL 同步；research navigator 与 browser data model 纳入 datasets。真实 `/Users/czx/Documents/knowledge_base` 全程零修改。
- **真实工作区应用**：安装器从 manifest 指向的 local checkout 将 `/Users/czx/Documents/knowledge_base` 更新到 rc.2，安装 update 明确保持 `kb/`；之后显式迁移 HIW-500 `r-hiw-500-d8337a53 → d-hiw-500-d8337a53`，checkpoint `eaf6295`，parse-cache/source 均 100% rename、旧确认只作 audit。新建 `humanoid-vla-wam-landscape` program，连接刚确认的 13 篇论文，持久化 evidence-first 横向综述/taxonomy/技术路线图 action；真实 `kb next` 已按 program → dataset 顺序输出。用户原有 3 个 paper fill 修改与未跟踪 research-settings 全部保留。
- **验收**：最终完整 suite **856 个 distinct tests 全绿**：不需 socket 的 841/841，加允许临时 loopback 的 navigator auth 15/15；dataset/recovery/cache 专项 36/36，next owner/治理 51/51，版本/安装/update 304/304。官方 skill validator 通过，101 个 Python 文件纯读 AST 语法检查通过，`git diff --check` 通过。

## [完成 2026-07-21] ar5iv Labs 直连 + paper screening-first 入库闭环

- **外部核验**：`ar5iv.labs.arxiv.org/html/<id>` 是当前 arXiv Labs 托管的真实 HTML 端点；`ar5iv.org/abs/<id>` 会重定向过去。站点明确说明不是实时 preview、当前 sources 到 2026 年 6 月底且有疑问应回主 arXiv，因此决策为 `arxiv.org/html → ar5iv Labs /html → arxiv abs`，不把 ar5iv 提升为第一来源。
- **SSOT-first**：锁定 paper 顺序为 `screen fill/verify → 按已验证 screening 的 paper_type（无法分类才 method_system fallback）note prepare → note fill/verify → preference-gated post actions → 用户确认`；任何新 intake 禁止在 screen verify 前按 method_system 兜底生成 note。
- **来源实现**：ar5iv fallback 改为直连 Labs，省去兼容域重定向；保留原生 arXiv HTML 第一优先与 abstract 最终降级。
- **编排实现**：`kb ingest` 机械前缀现在只跑 intake + screen prepare，private protocol 明列 screening 填充/校验、类型专属 note 准备/填充/校验和确认；note verify 自己处理 refresh/figures，protocol 不再重复列出并绕过偏好。`RESEARCH_INGEST_CHAIN` 下 source-intake 不再抢跑 analyzer。
- **统一门控**：standalone add 也只准备 screening；paper owner 对 prepared/unverified screening fail-closed。`auto_complete_note` 与 `maturity=complete` 的自动准备被迁到 screen verify 之后；已有 in-progress fill 若类型冲突会保留原文件并 STOP，不静默覆盖。旧单元已有 note 产物但缺 type 仍保留 method_system verify 兼容。
- **文档/测试**：同步 workspace AGENTS、3 个 skill contract、导航/来源/dispatcher/paper/governance 测试；公开 stdout 仍只自然语言 + `kb` 伪 CLI。
- **验收**：针对性 paper intake 回归全绿；最终完整 research suite **844 passed**（7 条既有 SWIG deprecation warnings），`git diff --check` 通过；真实 `kb/` 零改动，未 commit、未 push。

## [完成 + 双重冷验收 PASS 2026-07-20] 渐进式初始化 I1 · 快速设置 / 先跳过 / 后续补充

- **用户反馈**：真实 `kb init` 虽已创建结构，却只说“还差确认人必填、其余按默认”，没有主动询问关键偏好，也没有明确“先跳过、以后再补”，导致用户误以为初始化被姓名阻塞。
- **SSOT-first**：已锁定结构先可用、偏好不阻塞、现在设置/先跳过二选一、四类高价值快速信息、低频项渐进收集、skip 零写、identity 仅在 judgement confirmation 前强制、protocol 可延后、TTY/pipe 一致与幂等保留合同。
- **基线**：从已推送 PR #2 head `c6c5e3cc0bc869a91cc7d75cb25cd169cb993350` 开独立 worktree；不直接改本地 `main@60d73e0`。不 push、不 tag、不触碰真实 `kb/`。
- **施工面**：kb-cli dispatcher + init tests、kb-cli/config skill 指令、workspace Agent 规则、USER_GUIDE/README/INSTALL 中首次使用说明；不新增 verb、不新增 owner、不扩大配置 schema。
- **验收**：主 agent 独立复现普通/TTY/pipe/installed-copy 输出、protocol choices、skip 零偏好写、快速设置 headless 保存、重复 init no-churn、confirmation 缺署名 fail-closed；再跑完整测试与静态门，最后用无预期答案的冷 acceptance agent 实测。
- **首轮冷验收 P2（历史 finding，已关闭）**：冷 agent 选择“现在设置”后用 config owner 的通用 setter 写到了 `preferences.research_focus` 与顶层 `resources/constraints`；磁盘有值，但 init protocol 只读 `personalization.*`，并且原 I1 `--persona-resources` 只写 `personalization.resources`，与 method-designer 已锁定消费的顶层 `profile.resources` 脱节。主 agent 复现后先补 SSOT canonical mapping，再由下条 `f78a96e` 修复并以第二轮全新冷测关闭。
- **P2 闭环（`f78a96e`）**：资源写顶层 `resources.quick_setup`、约束顶层 append/deduplicate，保留旧 resource keys/constraints；private protocol 给精确 field inputs，snapshot canonical-first 并兼容旧 alternate 路径；回归直接调用 method-designer 现有 reader，installed-copy 同路径覆盖。
- **主验收**：完整 **842 passed**（5 条既有 SWIG warnings）；17 skill validator、两个相关 skill quick validate、compileall、`bash -n install.sh`、pip check、diff check 全绿。主 agent 全新 copy install 实测 canonical profile、既有资源/约束保留、method-designer 读取、重复 init 配置 digest+journal 不变、AI signer exit 1；真实 `kb/` 零改动。
- **冷验收**：第二个全新上下文在 A/B 两个全新 copy workspace 验 skip/configure、status/add/find、TTY/pipe、private snapshot、method resource capacity 与确认治理负向；P0/P1/P2/P3 全 0，UX 9.6/10。
- **PR 状态**：原 PR #2 已合并，无法追加 I1；`bc43055` + `3c6a1a6` + `f78a96e` 已推送为独立 `codex/i1-progressive-init@f78a96e`，并创建 https://github.com/caozx1110/ResearchLab/pull/3（base `main`，OPEN / MERGEABLE / 非 Draft）。Hosted Linux/macOS CI 已触发、当前 queued/in-progress；未 merge、未 tag、未 publish。

## [完成 + 冷验收 PASS 2026-07-19] 开发者诊断 D1 · 可选问题记录 + 分层 KB audit

- **用户决策**：按审查建议开始施工并真实模拟；普通用户可关闭全部额外诊断或单个 skill，开发者可开启低成本错误捕获/短复盘，安全治理门不可关闭。
- **SSOT-first**：已锁定 off/errors-only/developer 三档、逐 skill 覆盖、token/issue 预算、local-only、结构化 issue、脱敏捕获、五层机械 audit、15 verbs 不扩面、恢复/并发/零写合同与黑盒 gates。
- **基线**：最终 RC integration `9dcd1ad6134e7700fbfe641d938dae6958af71f4`；三条 worktree 必须从该 HEAD 分叉，真实 `kb/` 不得触碰。
- **并行 ownership**：A 负责 diagnostics core + config + issue schema；B 负责 index/audit + knowledge-base/wiki owner；C 负责 kb-cli 失败 hook + workspace Agent 规则 +公开文档。测试文件也按 track 独占，公共接口按 handoff 锁定。
- **总验收**：主 agent 独立复现默认 off、errors-only、per-skill off、dedup occurrence、50 并发、脱敏、原 exit 保留、audit 六类故障、audit 零写、installed-copy 自然语言输出；最后全量 tests/validator/compile/diff/真实 kb 红线。
- **主分支落地**：本地 `main` 已从 pre-merge 撤销点 `dbbce03` 无冲突 fast-forward 到 `60d73e0eff76323bcac9ee1e1deb5c780446f485`；候选 worktree/分支仍保留。原 `feat/skill-bundle-and-hardening-2026-07@ff98943` 分支指针未改写。发布候选走独立 PR 分支，未直接 push 本地 `main`、未 tag/publish。
- **PR**：刷新远端后发现 PR #1 已把原 feature branch 合入 `origin/main@339ea15`；创建 `codex/r1-d1-release-candidate` 并无冲突 merge 最新远端，merge commit `e42d2414e733da812278da268726f8b4f7937b18` 的 tree hash 与 `60d73e0` 完全一致。正式 PR 为 https://github.com/caozx1110/ResearchLab/pull/2，状态 OPEN / MERGEABLE / 非 Draft，当前 head `c6c5e3cc0bc869a91cc7d75cb25cd169cb993350`。首轮 push 事件 5 个 Linux/macOS jobs 全绿，首轮 PR 事件 5 个 jobs 因 GitHub detached HEAD 下测试强制 `git symbolic-ref` 成功而失败；本地临时 detached worktree 精确复现后确认实际 manifest 正确记录空 `source_branch` + 当前 `source_commit`，产品合同未破坏。`c6c5e3c` 只硬化测试：attached/detached 均稳定断言，并增加显式 detached provenance 回归。修复后 push + pull_request 两套 Hosted Linux/macOS 矩阵 **10/10 checks 全绿**。未 merge/tag/publish。
- **真实诊断黑盒**：全新安装副本默认 off 的 owner failure exit 1 且零 issue；errors-only 自动记录一条、重复后 `occurrences=2`；developer 总开关 + source-intake off 精确覆盖；off 下显式用户记录仍生效；export preview 明示授权、前后 issue SHA-256 相同；公开 failure/doctor 输出无裸命令、flag、内部路径或 traceback。
- **并发/事务**：50 个并发独立 capture 零丢，50 个等价 capture 合并为一条且 `occurrences=50`；写失败 rollback 不留半记录，absent-root policy/list 零写。
- **两篇文献实测**：RT-2 `/private/tmp/r1-rt2-paper.ITmjKp` 与 OpenVLA `/private/tmp/openvla-paper-ux.UY6QQo` 各稳定发现 8 项 recovery/quality finding（dirty owned files、metadata/taxonomy 空缺、duplicate/suspicious figure），审计前后 byte+mtime tree digest 完全一致。
- **冷验收 finding 闭环**：首轮 exact payload 二次复现显式 issue 会保留合成邮箱与独立 `sk-test-*` credential；主 agent 独立复现后先加严 SSOT，再以独立提交 `60d73e0` 增加 email/OpenAI/GitHub/Slack/AWS-style standalone credential redaction。修复后 fresh installed copy `/private/tmp/workspace-oss-d1-retest.tEKwya` 复验不再落原值，P0/P1/P2/P3 均为 0。
- **最终发布门**：D1 专属 29 tests 绿；PR 修复后完整套件为 **838 passed**（5 条既有 SWIG deprecation warnings）；compileall、`bash -n install.sh`、17 skill validator、`pip check`、`git diff --check` 与 Hosted CI 10/10 全绿；公开面仍精确 15 verbs。
- **范围边界**：D1 是 local-only beta/scaffold；不做后台 telemetry、自动上传、网络扫描、依赖/CVE 漏洞扫描、研究语义判断或自动修改 skill/roadmap。第三方导出/上传必须未来另设显式授权面。
- **红线**：PR 分支 tracked clean，真实 `kb/` 相对基线零 diff；只推送 `codex/r1-d1-release-candidate`，未直接推 `main`，未 merge/tag/publish。
- **本地仓库卫生（不阻断 PR）**：为 detached 复现尝试 `git clone --no-local .` 时发现历史对象缺失；`git fsck --name-objects --no-reflogs` 将缺失对象全部定位到本地-only rollback tag `pre-refactor-merge-b401ab8` 的旧历史，远端无同名 tag，当前 RC branch/Hosted checkout 均完整。未擅自删除 tag 或 prune；后续由维护者选择从其他备份恢复，或确认不再需要回滚点后删除该 tag。

## [完成 + 冷验收 PASS 2026-07-18] 重复安装分流 + 可恢复卸载

- **用户决策**：向导入口显式提供“首次安装 / 更新 / 重装或修复 / 卸载”；交互式首次安装命中已有有效 copy 安装时，不再直接报错，而是询问更新（默认）/重装或修复/取消；非交互重复 install 继续 fail-closed。
- **SSOT-first**：锁定交互分流、manifest AI 工具恢复、digest-gated uninstall、AGENTS managed-block 漂移保留、project/system/legacy 快捷入口安全清理，以及 manifest-owned Python bytecode cache 的窄范围清理合同。施工规格：`temp/codex_prompt_install_reroute_uninstall_safety.md`；提交 `cfd17d5`（卸载安全）+ `ff98943`（安装分流/文档）。
- **安装 UX**：首屏四动作与真实 action 一一对应；重复安装分流发生在 install-only 的快捷入口问题之前；确认摘要从 manifest 恢复原 AI 工具；向导直接提供重装入口。显式 update/reinstall/uninstall 技术界面保持兼容。
- **卸载安全**：`.agents/**` 仅普通文件且 sha256 仍匹配才删除；content drift、目录/特殊类型、symlink/祖先 symlink 全部保留并告警且不跟随。根 `AGENTS.md` block 内容/marker/编码异常时整文件保留；未漂移时只移除受管 block。manifest 最终删除，`kb/`、`.venv/`、未入 manifest 用户文件不动。
- **快捷入口**：system、copy project、legacy project 卸载都无需记住安装时的 `--kb-on-path`；匹配 symlink 删除，异源链接与普通文件原样保留并告警。
- **冷验收 P3 闭环**：首轮冷测发现 smoke/runtime 生成的 `__pycache__` 使 clean uninstall 残留 `.agents`。独立复现后仅按 manifest-owned `.py` 模块名清标准 `.pyc`；二次冷测确认 19 个受管 cache 清净、无关 `user_extension*.pyc` 字节/hash 不变，P0–P3 finding 全为 0。
- **验证**：installer 19/19、bundle lifecycle 9/9、bootstrap→installer 顺序敏感组合 21/21；真实 PTY 的默认 update/reinstall/cancel、非交互拒绝、system shortcut、drifted uninstall 均实测；最终全量 **420 passed**（7 条既有 SWIG deprecation warnings），`bash -n` 与 `git diff --check` 通过。
- **测试硬化**：新增 `_install_copy` helper 同样清除继承的 `_RESEARCH_RUNTIME_READY`，避免复发顺序污染。根目录未跟踪 `bin/kb` 全程保持原 symlink，未修改、未暂存；真实 `kb/` 未触碰；未 push。

## [完成 + 冷验收 PASS 2026-07-18] `kb` 快捷命令使用提示

- **用户决策**：取消让安装器自动修改 `PATH` / shell 配置；只在选择“创建 kb 快捷命令”时告诉用户如何使用。
- **SSOT-first**：首次安装 UX 合同补充为——选择创建后说明 `kb help` / `kb init`；完成页按快捷入口是否已在当前 `PATH` 中分流，未命中时诚实提示把上方目录加入 `PATH` 并重开终端；AI 对话不受影响。
- **实现**：`install.sh` 在选择后用“如果安装成功”避免 partial-conflict 误导；成功完成页在 PATH 命中时列 `kb help` / `kb init`，未命中时说明手动加入 PATH、重开终端，并明确安装器不改 shell 配置。`docs/INSTALL.md` 同步。
- **测试**：installer 由 9 增至 12；覆盖选择提示时序、PATH 命中/未命中、默认不创建不误报、shell rc 零写入。全量 **408 passed**；`bash -n` 与 diff check 通过。
- **独立验收**：冷 agent 在全新 `/tmp` HOME/workspace 复现两种 PATH 分支，实际 `command -v kb` / `kb help` 行为与提示一致；partial conflict 完成页不输出成功指引；真实 `kb/` 和用户 shell 配置未触碰。
- **附带测试硬化**：PTY helper 清除继承的 `_RESEARCH_RUNTIME_READY`，关闭 `test_bootstrap` → installer 的顺序依赖；组合测试 14/14 通过。
- **施工规格**：`temp/codex_prompt_kb_shortcut_guidance.md`。未 push。

## [完成 + 双冷验收 PASS 2026-07-19] 发布闭环 R1 · 对抗审查全量收口

- **基线**：feature HEAD `4a85732`，受管测试环境 `tmp/rvenv/bin/python`，405 tests green；真实 `kb/` 不得触碰，所有 E2E 用 `/tmp`。
- **设计已锁**：SSOT 新增“发布闭环 R1”九条合同：canonical claims、evidence containment+byte binding、完整 ConfirmationReceipt、统一 judgement gate、source transaction/retry、全写路径 recovery、唯一 workflow classifier、public/agent protocol 分离、发布工程。
- **并行文件所有权（worktree 必须 disjoint）**：
  - **G · trust-chain**：`evidence.py/confirm.py/records.py/SCHEMAS.md`、paper/blog/repo analyzer、report-author、orchestrator 及专属治理测试。负责 claims→verification→receipt→report、路径边界、artifact byte invalidation、program decision gate、workflow classifier 的 orchestrator 半边、其自有 checkpoint caller scopes。
  - **R · recovery-source**：`sources.py/common.py/journal.py/git_ops.py/yaml_io.py`、source-intake、config、navigator save 及专属恢复/源测试。负责失败先不建 unit、本地 HTML/MD/TXT parse、generic unit_id、snapshot rollback、默认 CAS 支撑、并发 append 零丢、空 checkpoint paths 拒绝、doctor runtime truthfulness；不得碰 G/C 文件。
  - **U · conversational-release**：kb-cli dispatcher、knowledge-base-manager、updater/bootstrap/install/ws_sync、`.agents/AGENTS.md`、README/USER_GUIDE/DESIGN、CI/VERSION/CHANGELOG/SECURITY 及专属 UI/installer 测试。负责 public stdout/TTY、统一 review 半边、source provenance、fork update、文档 verb/门控同步、macOS CI 与 release metadata；不得碰 G/R 文件。
- **跨轨接口**：各轨在自己拥有的 caller 中传显式 checkpoint target paths；R 把底层改为 fail-closed。G/U 不复制 R helper。冲突或接口拿不准 STOP-and-report，由主 agent 在 merge 后做最小 integration patch。
- **提交纪律**：每个承重 piece 独立 commit；不 push；不得改真实 `kb/`；治理只加严；analyzer 脚本不生成理解；用户可见输出只自然语言+`kb <verb>`；不允许 TTY 分支。
- **总验收**：主 agent 逐条独立复现旧 exploit/死路已关闭，再跑全量 tests、installed-copy forbidden-token scan、三 kind E2E、artifact mutation invalidation、failed-source retry、200 并发 append、unrelated dirty draft checkpoint、TTY/non-TTY parity。全部通过后再决定版本与 release tag；不能因测试数量绿就提前称 release。
- **最终候选**：集成 worktree `/private/tmp/workspace-oss-r1-integration`，分支 `codex/r1-integration`，HEAD `9dcd1ad6134e7700fbfe641d938dae6958af71f4`；版本 `0.2.0-rc.1`。这是已通过本地 gate 的 release candidate，不是 stable/GA；未 tag、未 publish、未 push。hosted Linux/macOS CI matrix 全绿仍是 release tag 前置。
- **信任链/治理闭环**：paper/blog/repo 真实本地 source 均完成 ingest→空白 prepare→Agent grounded fill→逐字 verify→当前消息授权 confirm→receipt→weekly report；12 条 canonical claims 自包含进报告。canonical claim 或已绑定 artifact 字节变化会失效并精确路由 `agent-verify`，实质字段清空则路由 `agent-fill`；sidecar-only 修改不误伤 receipt，报告 checkpoint 不误收无关 dirty 文件。
- **恢复/源/并发闭环**：绝对路径、`..`、symlink evidence fail-closed；失败 source 可重试且不污染 dedup；200 并发 reporting append 零丢失；三单元并发 attach 双向链接完整；空 resume/undo/restore 前后树快照一致；checkpoint 保留无关 tracked/untracked draft；更新禁止降级，卸载保留 drift/retyped 路径。
- **公共 UX 闭环**：普通用户完成一次安装后只用自然语言或 15 个 `kb <verb>` 伪 CLI；32 个 help surface 字节一致、stderr 为空、无 `[research]`。安装/更新/卸载隐藏 sync/hash/内部路径；`kb init` 幂等无 churn；所有动态字段防协议/命令/Markdown 注入；正常技术英文不误伤；`loose:`/owner 枚举/私有 protocol 不泄漏；TTY 与 pipe 下 review 都不读 stdin、不自签。
- **冷验收 finding 闭环**：首轮冷测发现并由主 agent 独立复现后修复 informed review 缺 canonical claims、动态协议注入、shell classifier 逃逸与误伤、rejected 仍活跃、空 undo 写锁、帮助/错误面分裂、`loose:` 状态泄漏，以及 stale verification “失效但不可恢复”死区。最终两个全新上下文冷 agent 在固定 HEAD 上复验，P0/P1/P2/P3 均为 0；文档/help 子审同样无 finding。
- **根验收证据**：最终全量 **808 passed**（5 条既有 PyMuPDF/SWIG deprecation warnings）；`compileall`、`bash -n install.sh`、17 skill validator、`pip check`、`git diff --check` 全绿。全新 project-copy 安装的 candidate/installed/bin `kb` SHA-256 一致，manifest 精确记录 local checkout/commit/branch/version；卸载前后 KB tree digest 完全一致。
- **红线复核**：真实 `kb/` 相对基线零 diff；集成树 clean；主工作区 tracked clean，仅保留用户原有 `?? bin/`；未打 tag、未 push，未把集成分支擅自合入主工作树。

## [multi-skill workspace bundle 改造完成 + 已独立验收 2026-07-17] merge 进 main（d07838a，未 push）
- **需求**：8 点规格——`.agents/` 作安装单元装到每个 kb workspace、多 skill 独立触发共享 runtime、用户数据只在 `<ws>/kb/`、正式支持 project-scope copy install（弃 system/symlink）。**先验收用户已改完的 install-UX**（400 绿、install/update/uninstall 实机验、kb 保留）→ 提交为干净基线 fffd5f3。
- **⚠️ 前置处理（用户拍板）**：工作区有未提交的 install-UX 改写（bundle 要重写同文件）→ **先提交 install-UX 再开工**，从 fffd5f3 干净分叉。分两 wave（文件面 disjoint）。
- **B1 打包核心（15b826a，+4 测试→404）**：REQ1/2/3/4。allowlist（`git ls-files` tracked-only + RELEASE_PREFIXES/FILE_MAP，排除 tests/eval）替代 walk+排除；合并式安装（保留用户自带 skill + AGENTS.md prose，managed-block）；原子事务无半安装；新增 reinstall；wrong-cwd 拒写不回退源仓。**独立验（临时 ws 实机）**：tests/eval 未 ship、用户 skill+prose 保留、源仓 0-dirty、reinstall/uninstall 保 kb/.venv。撤销点 pre-bundleB1-merge。
- **B2 卫生（2d7c6de，+1 测试→405）**：REQ5/6/7/8b。Navigator slug 删；`skill_validator.py`(25–64 短描述+frontmatter+脚本可发现)过全 17 skill；blog-analyst 274→130 描述修；公开 temp/ 清；SKILL.md 示例 KB 耦合解耦（p-openvla→p-example、czx→research-lead，仅示例）；CI 跑 validator。**独立验**：validator 0/17、install.sh/ws_sync 未碰、SKILL.md 改动仅 metadata/示例非 skill 逻辑。撤销点 pre-bundleB2-merge。
- **B3 修复（d07838a）**：whole-bundle 验收发现 validator 本身 dev-only 却随 lib/research ship → 加 EXCLUDED_NAMES（updater.py runtime 保留）。
- **whole-bundle 验收**：fresh install→17 skill、tests/eval/validator 排除、VERSION+LICENSE ship、装好的 ws 里 kb doctor(0.1.0)+kb init 可跑、uninstall 保 kb（PRECIOUS 存活）。405 绿。
- **红线**：真实 kb/ 未动、未 push、治理零改、每 wave 独立复现后 merge、带撤销点。
- **残留**：① eval_research_value.py 一处 temp/ docstring（allowlist 排除、不 ship，无用户面影响）；② manifest version 字段**已补齐**（dbbce03，见下）；③ 全程遇 Bash 分类器间歇不可用，靠只读工具预读 + 稳定后实机验收，无 merge-on-inspection。

## [自更新 + 版本号 完成 + 已独立验收 2026-07-17] `kb update` + `.agents/VERSION`，merge 进 main（b31829d，未 push）
- **需求**：从 GitHub 拉最新更新整套 skill（工作区 + 系统路径两处）+ 加版本号标明版本/查更新。用户拍板：**semver VERSION 文件** + **完整更新档（拉本地源仓 + GitHub clone 兜底）**。
- **取证要点**（决定设计）：安装是 copy（copy-project）或 symlink（system scope），只有源 checkout 有 .git + origin `caozx1110/ResearchLab.git`；无版本文件；copy 不知来自哪个 GitHub 仓。system scope 的 kb symlink resolve 回源 checkout → 同仓/系统一并 git pull 即可；copy 需拉源仓再 re-sync（源仓不在则 GitHub clone 兜底）。
- **⚠️ 关键规避**：工作区有一大块**未提交的 install.sh 改写**（install-UX 收口，416+/283-，含 test_installer.py）。自更新本要碰 install.sh/ws_sync.py（manifest 加 version）——**用户拍板本轮避开 install.sh，只做能独立的部分**，manifest version 延后到 install-UX 落定。file 面完全 disjoint，未提交改动完好保留。
- **落地（b31829d，+9 测试）**：`.agents/VERSION`(0.1.0) + `.agents/lib/research/updater.py`（semver 比对 + 源 checkout 解析 + fetch/pull --ff-only/clone --depth 1 + copy 经**invoke（不 edit）ws_sync.py** 重同步）+ kb-cli `kb update` verb（check 默认，`--apply` 是 agent 通道）+ `kb doctor` 显示 `skill_version`。canonical origin 硬编码 https 免 SSH key。
- **独立验收**：全库**无 push**（grep 坐实，只 fetch/pull-ff-only/clone）；离线→unknown 不崩；`kb update` 用户输出纯自然语言无裸命令；有更新→NEXT FOR AGENT 引导确认、**apply 不自动跑**（实机 stub 远端高版本验证 apply 未被调用）；doctor 显示 0.1.0；install.sh/ws_sync.py 零改动。393 绿（isolation）/398（含 install-UX 未提交测试）。撤销点 tag `pre-selfupdate-merge-20260717`。
- **待办**：~~install-UX 落定后补 manifest `version` 字段~~ **✅ 已补（2026-07-17，dbbce03）**：`build_manifest` 加 `version`（`read_source_version` 读源 `.agents/VERSION`），install/update/reinstall 三处 call site 全接，schema 保持 1（additive）。实机验：install 记 0.1.0、update+reinstall 保留、405 绿。

## [完成 + 冷验收 PASS 2026-07-17] install.sh 首次安装 UX 收口（未提交、未 push）
- **落地**：中英混排/术语先行 wizard → 中文单列数字选择；非法输入原地重问；动态步骤编号；install/update/uninstall 都有用户结果摘要，真实 TTY 未给 `--yes` 必确认且 EOF fail-safe 取消；system uninstall 不再死路。
- **输出合同**：向导 dry-run 折叠逐文件路径，正式 install/uninstall 折叠 `copy-project`/smoke 噪声；显式 update/dry-run 仍保留 old→new、diff 与路径技术合同。dry-run 独立终态，不再假称已配置；partial conflict 停在“需要处理”，不再输出 `kb init`；完成页只给自然语言 + `kb <verb>`，不引用未生成文件。
- **安全/兼容**：非 TTY/CI 不等待；update drift 仍 exit 3 fail-closed；foreign symlink、`kb/`、`.venv/` 和用户文件保留；system 完成页不把 cwd 冒充 workspace；真实 `kb/` 未动。
- **验证**：macOS Bash 3.2 `bash -n`、`git diff --check`、installer **9 passed**；最终套件 **398 passed + 2 deselected**（两条既有 PDF 用例因当前系统 Python 缺 `fitz`，直接全跑时也仅这两条失败）；冷 acceptance 5/5 PASS，独立 code review PASS。施工规格：`temp/codex_prompt_install_ux.md`。

## [尾部收口完成 2026-07-17] SSOT Part3/4 主线走完，merge 进 main（bd85def，未 push）
- **拆分**：剩余项分两半——**真代码**交 codex，**agent 行为**我写进 `.agents/AGENTS.md`（SSOT 自身定性"多为 agent 行为+一个 flag"）。撤销点 tag `pre-w5-merge-20260717`。
- **agent 运行规则（9e33c14，我做）**：`.agents/AGENTS.md` 新增"Interactive modes & reactive behaviors"节——① 伴读 C15（随问随答引用本文+关联 unit，ephemeral 不落盘）② 主动把待确认判断推给用户（3.11/C19，不等翻队列）③ 会话内矛盾检测（3.13，发现矛盾停下问用户、走确认门、不静默覆盖，非定时扫描）④ 主动记忆偏好（3.14，观察到习惯用 learnings.py log，pending 待确认才生效，不自应用）。
- **w5 codex 代码（bd85def，+3 测试）**：Part A reporting_style 接 report——读 user-profile.reporting_style（config.py 只读未改），简洁档裁事件/claims 量但保留 missing 标记、不脑补；详细/默认全量。Part B experiment 诊断证据（E4）——诊断 claim 可挂 evidence_refs 引用**自身 run 产物**（run-log.yaml / runs/run-NNN.md），validate_claims + verify_claim_evidence 逐字校验；无 claim 的诊断仍兼容 pending。**独立验**：详细 20 事件/32 行 vs 简洁 5 事件/17 行且 missing 保留；诊断有效 quote 过、编造 quote → not-verbatim 拒；384 绿、gate 未削弱。
- **SSOT Part3/4 状态**：3.1-3.14 子系统设计决策全部实现或以 agent 规则落地。**剩余仅极后置项**：3.13 若要定时/后台扫描（SSOT 明确标 future 不做）；method 资源解析保守（只认显式线索）；E4 诊断证据是"可挂"非强制。**主线到此收口。**

## [大主线 Wave3+4 完成 + 已独立验收 2026-07-17] scaffold 五子系统 evidence-first 化，merge 进 main（1f80429，未 push）
- **范围**：SSOT Part4 三/四波——把 survey/idea/method/experiment/report 五个 scaffold 档子系统从"直方图/固定策略/事件 dump"做成 evidence-first prepare/verify（同 paper.py 范式）。SSOT 3.6-3.10 决策**早已锁定**，本轮纯施工。撤销点 tag `pre-w3-merge-20260717`。
- **取证**：3 只读 agent 摸清 5 子系统现状（都是一次性算完写盘、无 evidence 层、无 prepare/verify）。**开放决策仅 1 个**（paper 类型已在上一轮解，本轮 5 子系统决策全锁）。**disjoint 分析**：5 脚本天然 disjoint，但发现 4 handoff 都要写 SCHEMAS.md（单一共享文件）→ 从各 track 剥离，我 wave3 merge 后统一补（65fc4cc）。method 因 `resources` 依赖未接排 wave4。
- **Wave3（4 并行，base 3c5bedc→375 绿）**：
  - **S 综述（b3273bf，+4）**：prepare 产 7 节骨架（scope/taxonomy/trends/gaps…）+ 对比矩阵 + kb_anchor/as_of；verify 逐 cell `verify_claim_evidence`；删净硬编码 Observed/Inferred/confidence=0.68；observed(fact/eval) vs inferred(inference)。**独立验**：全有效过门 / 全编造→8 条 not-verbatim 拒；357 绿。
  - **R 报告（4439180，+5）**：自包含（读 confirmed claims+evidence via read_claims，不只 event dump）+ 新增 `outline` verb（论文大纲，写 paper-outline.md）+ 缺输入显式 `missing:`。**独立验**：空 program→标 missing 不脑补、无裸命令；358 绿。
  - **I idea 陪练（4fd5112，+6）**：`discuss`/`spar` prepare/verify（专家/审稿人，per-conclusion 持久化 payload.discussion.conclusions[]）+ analyze/review 去 count-threshold 改 agent+证据；select 仍 pending 不自签。**独立验**：编造反例→not-verbatim 拒、有效过；select 保 pending；359 绿。
  - **E 实验（be802cb，+7）**：轻度强类型指标 {name,value:float,unit,direction} + 验 artifact 存在（present/missing）+ 填活死掉的 results.comparison（baseline/最近N，方向感知 delta）。E4 诊断证据 defer（合理）。**独立验**：metric 存 float+direction、/nonexistent→missing、baseline delta +0.15；360 绿。
- **Wave4（base 4fd5112→381 绿）**：
  - **M 方法（70b5bb2，+6）**：读 user-profile.resources 缩放矩阵 feasibility + 不现实标红 + resource-request 提示；repo 排序改 program active_unit_ids（空则 KB 兜底+提示）；判断处 agent+证据。config.py 只读未改。**独立验**：no-res→unknown（back-compat）/ 1GPU→重行 unrealistic / 8xA100→全 feasible；state.resource_constraints 从 profile 填；381 绿。
- **收尾**：SCHEMAS.md 补 evidence-first-outputs 锚 + typed metrics（65fc4cc，test_schema_docs 仍绿）；能力成熟度矩阵 survey/idea/method/experiment/report **scaffold→beta**，scaffold 档清空（1f80429）。
- **红线全程**：真实 kb/ 未动、未 push、每 track 独立复现承重声明（实机跑 prepare/verify 证明证据门拦得住编造）后才 merge、每 merge 带撤销点 + post-merge 全绿。**5 个子系统 = 5 次 analyzer 规模实质重设计，全部 evidence-first 闭环。**
- **剩余（更后置）**：E4 诊断证据链接（defer）；method 资源解析保守（只认显式 GPU/Nx/mem 线索，任意自然语言不猜）；3.13 反应式矛盾检测（会话内，多为 agent 行为）；伴读 C15（3.4 之外的交互模式）。SSOT Part4 主线基本走完。

## [待办清扫完成 + 已独立验收 2026-07-17] 4 项 pending 全部落地，merge 进 main（3c5bedc，未 push）
- **来源**：Batch2 收尾时列的待办。SSOT-first：先取证（2 个只读 agent）→ 锁 3 项设计 → 3 disjoint track codex → 逐一独立验收 → merge。撤销点 tag `pre-p3-merge-20260717`。
- **#2 USER_GUIDE 成熟度矩阵（813ae69，我自己做）**：镜像 README，落"17 skill"节。
- **P per-paper-type element sets（856236e，+4 测试）**：用户拍板"初筛 agent 分类 + 3 套要素"。`ELEMENT_SETS{method_system/benchmark/survey}`（NOTE_ELEMENTS 保留为 method_system 别名）；screen 加 agent 填 `paper_type`（enum 校验 + 需 evidence，走判断轨），`elements_for()` 按 `quick_screen.paper_type` 选集、未知→method_system 兜底；build/verify/route/render 全按选中集。新要素全路由进 core_content。**独立验**：3 套正确、back-compat（无 type→五要素）、**每套 substance gate CLEARS**（≥4 元素落 core_content）、**反模式 litmus 干净**（无脚本从内容猜 type）、335 绿。
- **V Workbench token 鉴权 + PTY 默认关（c212e82，+15 测试，升级原 future）**：`secrets.token_urlsafe(32)` 一次性 token，三入口 `_authorized`（query/header/bearer/cookie，`compare_digest` 常量时间，healthz 豁免，含静态回退前）；token 不落盘 / 日志 redact / 非 TTY 不印 / `browser_url` 附 `?token=`。`--enable-terminal`（默认 False）：terminal 端点 403 且 `TerminalManager=None`。**独立验（直接跑 _authorized/_terminal_available/browser_url）**：四种传法 OK、错 token 拒、常量时间比较、PTY 默认 403/开启放行、URL token 正确。346 绿。navigator 从"无鉴权"向 beta 靠拢，矩阵已更新（3c5bedc）。
- **K `kb resume`（0cccf58，+3 测试）**：`journal.incomplete_ops()` 选 `state==begin`；`kb resume` 列孤儿→复用 `restore_operation` 回滚→标 abort。git_ops.py 未动。**独立验（实机崩溃场景）**：stranded begin 被逮到、回滚到 pre-op、begin 消失、输出无裸 git、334 绿。
- **合并**：3 track no-ff、disjoint 无冲突，post-merge main **353 绿**（331+22 新测试）。真实 `kb/` 未动、未 push。
- **剩余（更后置）**：scaffold 档能力做实（survey/idea/method/experiment/report 从直方图→evidence-first）是 SSOT Part4 三/四波大主线；paper 未知类型仍兜底 method_system；workbench 真多用户需更强会话管理。

## [审查 Batch1 完成 + 已独立验收 2026-07-17] 用户契约(原则8)落地：init 交互 + 输出清洗 + recnext + installer，已 merge（328c366，未 push）
- **设计先行**：SSOT 新增原则8 + 6 条锁定决策已 commit（4be20c6）；README 能力成熟度矩阵（53ad9fe）。用户两点诉求（init 不交互 / 输出夹带命令行）挖到根因后纳入原则8。
- **施工**：codex(gpt-5.6-sol/xhigh/full-access)，3 个 disjoint worktree 并行，从 clean 4be20c6。撤销点 tag `pre-b1-merge-20260717`。
- **T-B init（51e5d43）**：`kb init` 非 TTY 无 flag 时不再静默 return 0（被 `isatty` 门跳过 persona 问答的根因），改为输出 `NEXT FOR AGENT` 引导 agent 对话式收集偏好 + headless 落盘。**独立验**：非 TTY init 实机产出引导+脚手架、295 绿。
- **T-C installer（ad780b5+7945c60）**：C1 `_ensure_venv_has_pdf_backend`→`_ensure_python_has_pdf_backend(any runtime)`，在"当前 Python 有 YAML"早退分支前调用（PDF backend 永久缺失的根因，[[test-suite-needs-managed-venv]]）；C2 preflight 缺 YAML 不再 die、回退受管 venv。C3（同仓读开发者 AGENTS.md）report-only（codex 判无干净 installer-only 指针，正确克制）。**独立验**：复现"有YAML缺backend→真装 pymupdf4llm"、`RESEARCH_NO_PDF_BACKEND=1` 不装、298 绿。
- **T-A 输出清洗+recnext（058586f/18addb0/8077610/e0b6dea + 我的 e263e0e/addac32）**：A1-A3 清掉 `kb find/review/next/add` 用户可见输出里的裸命令（改自然语言/`kb`动词）；A4 recommend_next 读 `full_note_status`，空壳不推给用户确认。
  - **⚠️ 我 review 抓到 3 个 codex 漏的（都已复现+修+加测试）**：① A4 只改 orchestrate，漏了 `kb.py review_queue_records` 平行路径——`kb review` 仍列空壳（handoff 范围写窄的老坑重演）；② `is_user_confirmable` 过度排除 `not_started`（schema 默认值）——已初筛待确认的 paper 会从 program dashboard pending 消失，收窄成只排 `awaiting_agent_fill`；③ 空库 onboarding 说 `intake add`（内部 verb）、`kb find` 对空壳仍印"待你确认"——最终**实机扫描所有 verb 才逮到**（单测测不出）。
  - **排序决策（用户 2026-07-17 拍板）**：已初筛+not_started 的 paper → 先自动 generate-note，再确认（原则7 自动化优先于确认闸口）。safe_unit_step 保留 codex 的 generate-note 优先，dashboard 仍计为 confirmable 不丢。
  - **独立验**：302 绿 + **实机 leak-grep 全 verb CLEAN**（无 python3/.py/--flag/${}/NEXT FOR AGENT/脚本路径/intake add）。
- **合并**：3 track no-ff merge，disjoint 无冲突，post-merge main **307 绿**（294+13 新测试）。真实 `kb/` 未动、未 push。
- **教训**：output-hygiene 类改动**必须实机扫描所有用户可见 verb**，单测覆盖不到"还有哪条路径漏印命令"；A4 类"改一处状态判断"要**全平行路径一起改**（orchestrate + kb.py + navigator 计数）。

## [审查 Batch2 完成 + 已独立验收 2026-07-17] 三大契约全部 merge 进 main（b84af39 + e70da3d，未 push）
- **排序**：W(workbench)∥R(recovery) 并行 → R merge 后 C(ConfirmationReceipt) 建在 R 地基上（W/R/C 非全 disjoint，C 与 R 共 confirm.py/records.py 故顺序）。各带撤销点 tag（pre-b2R/pre-b2C-merge-20260717）。
- **W 安全（35c0f85，+6 测试）**：`_host_is_loopback`（getaddrinfo 解析 + 全 loopback 才放行，失败 fail-closed）拒非回环 host，`--allow-non-loopback` 显式 opt-in；`_is_immutable_unit_evidence` 写保护 unit `raw/`+`source/`+`parse-cache*.yaml`。保留 shell/PTY（最小档）。**独立验**：0.0.0.0/192.168.x 实机被拒、raw/source/parse-cache 写=False、note.md=True、313 绿。
- **R 恢复合同·完整档（7afc0ed，+8 测试，5 piece commit-per-piece）**：① yaml_io 原子写（temp+fsync+os.replace，失败清理）② `journal.py` operation journal（begin/commit/abort + sha256 digest，`kb/.journal/` gitignored）③ records `revision` + write_record CAS（`expected_revision` 冲突检测）④ 全写路径 flock ⑤ `git_checkpoint` 收窄到 op 路径（不再 `-A`）+ `kb undo`/`kb restore` 一等命令。**独立验**：revision 递增、CAS 拒陈旧、原子写抗模拟崩溃（无截断+temp清）、`kb undo` 真回滚 VERSION-B→A、undo 输出无裸 git、37 治理门全绿、validate_write 仍在 write_record 最前、321 绿。
- **C ConfirmationReceipt（b84af39，+? 测试，6 commit）**：C1 canonical content/evidence sha256 helper；C2 apply_confirmation 写全 receipt（subject/decision/claim_ids/content_digest/evidence_digest/prior_information_types）；C3 **停止无条件 `information_types=["fact"]`**，保留 epistemic；C4 normalize_record_schema 重算 digest 不符 → 自动降级 pending（"确认锚定版本" invariant）；C5 判断轨 **fail-closed 默认**（`RESEARCH_VALIDATE_FAILOPEN=1` 才降级 warn）+ `_has_complete_confirmation_receipt` 识别合法 receipt 让已确认判断记录仍可写；额外 apply_confirmation 在确认时**重跑 validate_claims + verify_claim_evidence**（补"确认不验 evidence 真实性"缺口）。**独立验（全红线复现）**：self-sign(codex/ai/assistant)拒、hollow 拒、空 evidence 拒、非逐字 evidence 确认时拒、epistemic 保留、内容变更 confirmed→pending & 不变仍 confirmed、fail-closed 挡无 receipt 的 AI 记录 & 有完整 receipt 放行、331 绿。**改的 3 个既有治理测试是"断言新契约"非弱化**（collapses_types→preserves_types）。
- **额外硬化（e70da3d）**：review C 时发现**既有自签漏洞**（`AI_SIGNER_NAMES` 缺 `claude` 等，非 C 引入）→ 扩到 claude/anthropic/gemini/llama 等当代模型族。tightening（红线只加严）。验：claude/gemini 现被拒、human 名不受影响、331 绿。
- **全程红线**：真实 `kb/` 未动、未 push、每 track 独立复现承重声明后才 merge、每 merge 带撤销点 + post-merge 全绿。

### 待办（本轮暴露/延后）
- **paper 五要素类型不适配**（benchmark/survey 论文）——SSOT 3.2 已记，per-paper-type element sets 待做。
- **能力成熟度矩阵**已上 README；USER_GUIDE 可同步补。
- **Workbench token 鉴权 / 默认关 PTY**：SSOT 标 future（本轮选最小档）。
- **恢复合同**：`kb resume`（续未完成 op）未单列 verb（codex 判 restore 覆盖）——如需显式 resume 面可补。

## [P0 热修完成 + 已独立验收 2026-07-16] codex review 4 条纯 bug，已 merge 进 main（7b0d71c，未 push）
- **来源**：codex(gpt-5.6) 对全系统的一份带 file:line 的审查意见。我用 6 个并行 agent 独立复现每条承重声明——~15 条完全属实、~5 条部分属实（措辞/字段名夸大但底层缺陷真实）、0 假警报。本轮只施工其中 4 条**纯 bug、无需设计决策**的热修；确认门/工作流状态/恢复合同等**设计级**项留待先改 SSOT。
- **施工**：交给 codex(gpt-5.6-sol / xhigh / full-access)，隔离 worktree 从 clean HEAD 46d3b01 起，commit-per-fix。**首轮 codex 正确 STOP**（基线非绿：285 passed/2 fitz-fail）——根因是我 handoff 让它用 system python3（无 fitz），真基线要用受管 venv `tmp/rvenv/bin/python3`=**287 passed**；改 handoff STEP0 后重跑成功。教训已记忆([[test-suite-needs-managed-venv]])。
- **4 条 fix**（各带新测试，+7 测试，294 全绿）：
  - `fix(retrieval)` 72aec02：`TOKEN_RE` 加 `|[^\W\x00-\x7f]+` 支持 CJK/Unicode token。**修 P0.4-C1**：纯中文查询原本 tokenize→[] 走 `if not query_tokens: return list(records)` 退化成"返回全部"；现在 `灵巧手`→只返回匹配项。空查询仍 filter-only（invariant 保住）。
  - `fix(orchestrate)` 69f5c46：`status` 在 lock/create 前加 `program_root().is_dir()` 存在性门，未知 program→SystemExit 不再静默建目录。**修 P0.2-C3**。
  - `fix(kb-cli)` 6a07c0a：`kb next <program>` 不再 `del args` 丢参；转发 `--program-id`，orchestrate `next` 加可选 `--program-id` 过滤（未知→error，已知空→msg+exit0，全局路径不变）。**修 P1-C2**。
  - `docs` 6a7714d：README 9→11 + USER_GUIDE 补 ingest/reject 行与路由行，文案对齐 kb 脚本 HELP_MENU（已是"11 个"）。**修 P1-C2 doc drift**。
- **我独立验收（不信 codex 总结）**：受管 venv 跑全套 294 绿；行为复现——CJK 查询只返 ['a']、混合 `灵巧手recovery`→['灵巧手','recovery']、空查询仍 3 条 passthrough；`status/next typo-xyz`→exit1 且 `kb/programs/` 保持空、真 program 仍 exit0。**红线**：真实 `kb/` 未动（git status 仅 `?? .worktrees/`）、未 push、恰好 4 commit/8 文件、确认门/实质门/full_note_status 逻辑零改动。撤销点 tag `pre-hotfix-merge-20260716`。
- **未做（留档，需先改 SSOT 再施工）**：ConfirmationReceipt(P0.1，confirm 绑定已验内容 digest+内容变更失效)、recommend_next 读 `full_note_status`(P0.2 真缺陷是 recommend-next 不读该字段，非"缺字段")、恢复合同(原子写/journal/undo)、workbench 鉴权+raw 写保护、能力成熟度矩阵对外化(SSOT Part1 已有 ✅/🟡/❌ 雏形)。installer P0.3(preflight 不回退受管 venv / 有 YAML 即不建 venv 致 PDF backend 缺 / 同仓装 Codex 读开发者 AGENTS.md)——属设计/安装策略，未纳入本轮。

## [施工中 2026-07-09] SSOT 落地 · Wave 1 开工（用户授权大重构 + 多 worktree 并行）
- **证据层 schema 已锁进 SSOT Part 2 原则2**（claim + evidence_refs + 逐字验证 + judgement空据不得confirmed）。
- **目标模块结构（我定）**：core.py 拆成 paths/prefs/records/confirm/index/sources/git_ops + 新建 evidence.py；core.py 瘦成 façade（import 面 100% 兼容）。各 Wave2 track 各占：sources.py(dual-source)/evidence.py(证据层)/confirm.py(验实质门)。
- **Wave 1（现在，2 路并行 worktree）**：
  - Track-R 重构 → `temp/codex_prompt_lib_refactor.md`（行为保持拆分+façade+全测试绿+evidence.py骨架；先落 main）。
  - Track-G5 尺子 → `temp/codex_prompt_research_value_eval.md`（只读只加新文件，与重构零冲突，抓改造前基线）。
- **Wave 2（重构 merge 后，从新 HEAD 扇出，3+ 路并行）**：Dual-source(sources.py+intake，3.1) ∥ Evidence实现(evidence.py+analyzer接线，原则2) ∥ Gate验实质(confirm.py，3.11)。detailed handoff 待重构落地后按真实路径写。
- **Wave 3+**：analyzer 做实(3.2/3.4/3.3) → 产出闭环(3.6/3.7/3.10/3.9) → 体验层(3.12/3.14/3.8/3.13)。按 SSOT Part 4.2。
- **merge 序**：Track-R 先 merge → Wave2 各 track rebase 到新 HEAD；G5 独立可先 merge（只加新文件）。

### [Wave 1 完成 + 已验收 2026-07-09] 两轨全绿，已 merge 进 main（0d67971，未 push）
- **Track-R 重构**：core.py 2589→56 行 façade + 8 模块(paths/records/prefs/confirm/sources/index/git_ops + 新 evidence.py)。**我独立验收**：166 测试全绿、façade 8 符号零缺失、无循环、行为字节级一致、G5 façade-harness 在重构后跑通。放置 3 处偏离(为破环)：_record_needs_gate→records.py、ensure_workspace→prefs.py、index.py 成 825 行 catch-all(未来可再拆)。撤销点 tag `pre-refactor-merge-b401ab8`。
- **Track-G5 尺子**：harness `eval_research_value.py`(只读/façade-only) + 33 题数据集(physics 18 + humanoid 15,7 轴,合成题 gold 全 pending 不自签) + TIER2_SPEC + smoke。**独立复核数字属实**。
- **首份基线（改造前坐标原点，kb@ecc8fd7/repo@0f05fe9）**：检索 recall@5=**80%** @10=**90%**；接地率**100%(15/15)**，来源=3 手工REWRITTEN vs 12 脚本产物；humanoid 空-program **10/11 返回自信但错误 top-1**(幻觉面,最高 score 72)；**H1 门控:confirmed=0(门从未真跑)、auto_confirmed=1 且空心=1、64/65 篇 paper 的 core_content 全空**(独立 grep 坐实)。**最弱轴 F(program 状态,0.50,因 state.yaml 不在 unit 索引) + G(idea 讨论,0.50)**。

### [Wave 2 · 3/3 地基全部完成 2026-07-10] main HEAD=362dcb2，228 测试全绿（含 pymupdf4llm 默认依赖）
- **Dual-source(3.1)** ✅ merge：arxiv→HTML优先(html/ar5iv/abs 降级链,section/anchor locator)、非arxiv PDF 真下载+PyMuPDF4LLM(page locator)、**修 G7**(backup_source 真持久化字节+真sha256+显式 backup_status/warning,不再静默 file_hash="";warning 只走 stderr/返回值不污染 record.source)、bootstrap 默认装 pymupdf4llm(消冷启动静默空parse)、requirements 提 pymupdf4llm 为默认(MinerU/Docling 注释可选重后端,Marker 因许可排除)、intake 接线。**经 3 次瞬时基建故障(504/流断/看门狗)+小步提交纪律最终完成。我独立复核**:arxiv-HTML 真下载(34 chunks/section)、PDF 真字节 sha256 匹配(2869095B/%PDF-/9c196ccb…)、坏URL→status=failed+显式warning不泄漏、228 绿(装 pymupdf4llm 后;缺时 stored-unparsed 是正确降级)。撤销点 e30dc2c。
### [Wave 3 · paper-analyst 重定位完成 + G5 首次真上分 2026-07-10] main HEAD=a91230c，237 测试全绿
- **paper.py 从"Python 打分/填模板"改成"prepare(可填结构)+verify(验证证据)机器"**：删净关键词命中数评级(`_grade`/`_match_keywords` grep 零命中);screen/complete-note 两相——prepare 产空白待填结构(judgement 字段留白)、verify 用 `validate_claims`+`verify_claim_evidence` 校验 agent 填的五要素(motivation/method/experiment/limitation/insight)每条带逐字 quote,过才落盘。SKILL.md 重写。237 测试(+9 机器测试)。**我独立复核**:反模式 grep 零命中、合成端到端(合法落盘/编造拒/空壳门挡)复现。
- **⚠️ agent 主动 flag 的真问题(已采纳,记 SSOT）**:五要素是"方法/系统类论文"形状,对**纯 benchmark / survey 论文不适配**(benchmark 无单一 method、survey 无 experiment)。agent 没硬编,停下报告=正确。→ 待办:per-paper-type element sets(follow-up 决策,非本轮)。
- **G5 首次真上分(端到端 demo,在 tmp/g5-demo 副本上,真实 kb 零改动)**:我扮演 runtime agent 给 AR-FB(p-finer-behavioral-66846131,真实 kb 里空 core_content 的那篇)填五要素、每条挂**取自 parse-cache 的逐字 quote**、跑 verify 落盘 → core_content 空→填(motivation/method/changes_and_effects/why_it_might_work)、has_substantive_content False→True、confirm 合法通过;**编造 quote 被 verify 按 element 名拒**;**G5 指标动了:empty core_content 64/65→63/65、confirmed 0→1(且该 confirmed 非空)**。证明全链:脚本备料→agent 填理解+证据→脚本验证→空心门只放真内容→G5 上分。真实 kb 经核验未动(temp 副本自成 git,checkpoint d77bc8a 不在真 kb)。
- **待用户决策**:是否对真实 kb 批量回填(哪些论文/多少篇)以真正推动 G5——mutate 真实知识库是用户的选择。demo 已证范式有效。

### [Wave 3 analyzer 三件套全部完成 2026-07-10] main HEAD=617885c，252 测试全绿
- **blog(3.4)** ✅ merge 3f7d4ce：占位符(107行,literal 待确认)→ prepare/verify(472行);四要素 positioning/key_points/credibility(事实vs观点)/reusable_explanation,agent 填、逐字证据(HTML section/anchor locator)、过实质门(SUBSTANCE_CONTENT_SECTIONS[blog]=content)。我复核:待确认=0、无 Python 判断、synthetic grounded/fabricated 通过。
- **repo(3.3)** ✅ merge 617885c：README/目录启发式(infer_repo_roles/capability_map 已删,grep=0)→ prepare/verify;三要素 capability/reuse_points/entry_map,agent 填、**file:line 证据**、过门(=capability section)。**证据可达性方案**:repo 太大不拷进 kb,verify 从 record source 解析 repo_root、按需加载 `repo_root/artifact` 逐字校验、不可达则显式报错(我复核:unreachable file 被拒不静默过)。符号级=按需 in-session,非入库时做。
- **用户重定向(2026-07-10)**:先不维护真实 kb;先把 skill 做到"足够易用/聪明/自动化",完后用户新建空 kb + codex 小批入库测试验收。
- **三个"足够"进度**:聪明=analyzer 三件套 ✅(paper/blog/repo 全 prepare/verify+证据+空心门);自动化=**待做(核心缺口:in-session agent 自动驱动 prepare→读→填→verify;今天要人手动 prompt)**;易用=部分。
### [自动化打磨批完成 2026-07-11] main HEAD=46d3b01，287 测试全绿（我自己接手做，codex 基建这轮连挂）
- 用户拍板"要做"最后一轮打磨。codex agent 连续瞬时基建故障（流断），改动小且我完全理解 handoff → **按 CLAUDE.md 铁律"连挂多次自己接手小改"，我在 main 直接做**（无并行 track 竞争这两文件）。
- **先改 SSOT**（auto-refresh 是功能变更）：§3.2 加"note verify 后自动跑安全后续步"决策。
- **A auto-refresh（f88206f）**：complete-note verify 成功后 `_auto_post_note_steps` 按 pref（auto_refresh_structure_after_note 默认 on / auto_extract_figures_after_note 默认 off）+ autonomy.auto_execute_scope（refresh/generate-note token，governance 封顶）自动跑；抽 refresh/figures 为共享 helper（复用不复制，行为一致）；**不重解析 cache（F-a）、不自动 verify/confirm**。真跑 AR-FB 实测：verify 后自动 refresh、cache 38→38 不变、default 不跑 figures、autonomy 收窄改出 NEXT 导航。回归 test_auto_post_note.py。**自动化 6.5→~7.5：paper 手敲步 4→2。**
- **B F8（46483ad）**：sources.py `_pdf_metadata` 标题只取首行 → 改多行收集（首行 3-20 词，续行放宽收短尾如 "Weighting"，遇作者≥2逗号/机构/abstract/link 停）。AR-FB 标题现完整"…Advantage Weighting"。
- **回写**：SSOT §3.2 标已落地；BACKLOG（本条）。
- **三个"足够"最终**：聪明 9 / 易用 8 / **自动化 ~7.5**。skill 已到用户要的"足够"状态。撤销点 tag pre-refactor-merge-b401ab8；自 baseline 0f05fe9 起 74 commits，全部本地未 push。

## [文档受众重构 2026-07-11] repo 根 AGENTS.md/CLAUDE.md → 开发向；使用规则移进分发树
- 用户校正：repo 根 AGENTS.md/CLAUDE.md 应面向**开发/优化 skill 的 agent**，不是用 kb 的 end user。
- **我发现的冲突**（用户不知情）：install.sh/ws_sync **拷 repo 根 AGENTS.md → 用户 DIR/AGENTS.md**，它是分发的使用规则。直接覆盖会把开发文档误分发给用户。
- **解法（codex 施工 f865802，我 review）**：`git mv AGENTS.md .agents/AGENTS.md`（使用规则进分发树，byte-identical）· repo 根 AGENTS.md ← 开发工作流（原 CLAUDE.md，去掉 @AGENTS.md 自引用）· CLAUDE.md → 软链 AGENTS.md · installer **8 处分发源** `$REPO_ROOT/AGENTS.md`→`.agents/AGENTS.md`，**目的地引用全不动**（source/dest 区分是这轮的关键失败模式）。
- **我独立复核**（不只信 agent）：真装到 /tmp → DIR/AGENTS.md==.agents/AGENTS.md(使用) 且 !=repo根AGENTS.md(开发不泄漏)、DIR/CLAUDE.md=@AGENTS.md、uninstall 干净反转、285 测试绿(agent 报的 2 fail 是它 venv 缺 fitz)。撤销点 d5ca9f7。
- **回写**：SSOT Part 0 文档所有权表已更新（.agents/AGENTS.md=使用/分发；repo根 AGENTS.md+CLAUDE.md=开发）。CLAUDE.md 里的开发工作流固化了"定SSOT→plan→codex→review→回写"循环。

## [自动化胶水完成 2026-07-10] main HEAD=26e198a，265 测试全绿，所有 worktree 已 prune
- **SSOT 原则7(自动驱动)已锁** + **AGENTS.md「Ingestion auto-drive」会话规则已 commit(0a4bbe3)**:入库后 agent 一回合跑完 intake→prepare→读→填→verify→figures/structure→screen,只在两个治理闸口停(确认 AI 判断 / 用户抉择),受 autonomy.auto_execute_scope 约束。
- **机械管线 merge(26e198a)**:① 三 analyzer prepare + intake add 尾部输出机读 `NEXT FOR AGENT:` 行(该读哪个 parse-cache/填哪些要素/填完跑哪条 verify);② `kb ingest <src>` 链式动词——intake→prepare 后**停在 prepare**(不自动 verify,因 verify 需 agent 先填),尊重 autonomy 阀门收窄。**我独立复核**:真 PDF ingest→38 chunks→note-fill.yaml 有/note.md 无(正确 stop-before-verify)、NEXT 行含真 paper-id+要素+verify 命令。
- **三个"足够"现状**:聪明 ✅、自动化 ✅(会话规则+管线+kb ingest 全落地)、易用 = 待验收测试暴露。
- **⬇️ 下一步 = 验收门**:用户新建空 kb,codex 跑小批入库端到端测试(paper+repo+blog 各一),按易用/聪明/自动化打分 → 迭代。这是 skill 是否达到用户要的样子的真实检验。

### [验收测试完成 + 修复批规划 2026-07-10] cold agent 端到端跑通 paper+repo+blog
- **打分(我已核实)**:聪明 9/10(证据门真管用,故意植改写 quote 被 verify 拒)、易用 7/10、**自动化 5/10(最大短板)**。真实 kb 未动(红线守住)。报告归档于 `dev-docs/reviews/legacy-acceptance/kb-acceptance-2026-07-08.md`。
- **⚠️ F4 是假警报(我复核推翻)**:验收 agent 报"blog/repo verify 拒绝却 exit 0"——我实测发现是**测试用例只污染了 scaffold 示例 quote 行、没污染真实填充 quote**,真正污染填充 quote 后 blog/repo verify **都正确 exit 1 并拒绝**。证据门三路全对。**不修 F4**(若照报告改会破坏正确的 exit-1)。→ 教训:codex/agent 的 finding 必须复现才动手。
- **真 bug(已定位落点)**:
  - **A 自动化补全(最重要)**:`kb ingest` 只链前半(intake→prepare 停);paper complete-note verify 成功(paper.py:885)后不引导剩余安全自动步(extract-figures/refresh-structure)+ 初筛填充。→ verify 成功 stdout 接着吐 NEXT FOR AGENT 指向剩余步。
  - **F1**:`infer_add_kind`(kb:206)本地 repo 目录落 else→blog(产孤儿 b-langwbc-repo-*);且无 reject/清理路径。→ 本地目录/含.git→repo + 加 supersede/reject。
  - **F6**:blog.py 未 import/调 `checkpoint_and_report`(paper/repo 有),verify 后产物不提交。→ 补 checkpoint。
  - **F8** paper note 标题截断;**F9** blog parse-cache header 键名 paper_id;**F3** --root 不在 ingest --help;**F5** 两套 confirm 命令;**F7** find stale 提示。
- **修复批(全修,disjoint 并行)**:Track1=kb-cli(A 链后半+F1+F3+F5+F7)· Track2=analyzer polish(F6 blog checkpoint + F9 blog header + F8 paper 标题)。

### [验收后修复批完成 2026-07-10] main HEAD=78fbd1b，284 测试全绿，worktree 已 prune
- **Track2 analyzer polish** ✅ merge 65ee459(273 测试):F6 blog verify 补 checkpoint、F9 blog parse-cache header paper_id→blog_id(读侧兼容)、F8 paper 标题 `" ".join(title.split())` 修 mid-sentence 截断。我复核:F8 真例修好、F4 回归护栏(污染真实 quote→blog verify 仍 exit1)。
- **Track1 kb-cli 自动化+UX** ✅ merge 78fbd1b(284 测试):**A(核心)**——`kb ingest` stdout 现在打印**整条链**(fill note→verify→[safe auto]figures/structure→**填初筛(step C,之前漏)**→confirm gate),按谁做标注、尊重 autonomy 阀门;F1 本地目录→repo 推断+新 `kb reject` 动词(清理误建单元);F3 --root 用法进 help;F5 confirm 命令统一到单一 `common.confirm_command`(**治理未削弱**:仍强制 --confirmed-by+--evidence,我核过);F7 find stale hint(blog→summarize 已改 complete-note)。
- **agent 透明标注的越界**:F5/F7 的代码实际在 orchestrate.py / kb-manager kb.py(非 analyzer/禁区),surgical 改动,已核实不碰治理逻辑、不碰 verify——可接受。
- **三个"足够"复盘**:聪明 ✅、易用↑(F1/F3/F5/F7 修)、**自动化↑(A 补全整链导航,5/10 的根因已修)**。
- **⬇️ 下一步 = 用户重跑验收**:新建空 kb,codex cold agent 再跑一次 paper+repo+blog,看自动化是否从 5/10 上到"足够"。撤销点 tag `pre-refactor-merge-b401ab8`。

### [再验收 + F-a 修复 2026-07-10] 分数 9/8/6.5(↑ from 9/7/5),critical data bug 已修
- **再验收(cold agent 重跑)**:聪明 9→9、易用 7→**8**(F1/F3/F5/F7 修生效)、自动化 5→**6.5**(kb ingest 现在告诉你整条链,但 figures/refresh 仍手敲)。真实 kb 未动。报告归档于 `dev-docs/reviews/legacy-acceptance/kb-acceptance-2026-07-10.md`。
- **F-a(新发现,critical,我复现+已修 commit 9e6e2a3)**:`refresh-structure` 之前 `force=True` 重解析→用截断 prefs 覆盖全量 parse-cache(38→16 页),破坏证据 idempotency(后页 quote 再验证失败)。修:refresh 从**现有全量 cache** 派生 structure.yaml,不再重解析(只 prewarm-cache --force 可重解析)。加回归测试锁定。285 测试绿。
- **剩余(discretionary polish,待用户定)**:
  - **自动化 6.5 的根因**:figures/refresh 是安全机械步却仍手敲。设计里有 pref `auto_refresh_structure_after_note`(默认 true)/`auto_extract_figures_after_note`(默认 false),但 complete-note verify 没接线。F-a 修好后 refresh 已安全,可让 note verify 后自动跑 refresh(按 pref)→ 少一步手敲。
  - **F8 残留**:note.md H1 已修(Track2);但 record.yaml title 字段仍截断("...via")——源在双源 parse_metadata 的标题抽取只取首行,非渲染问题。
  - **F-b/次要**:screening claim schema 未文档化。
- **待用户拍板**:是否做最后一轮 polish(接线 auto-refresh + 修 F8 title 抽取)把自动化推到 ~7.5+,还是当前 9/8/6.5 已"足够"、直接建真实 kb。
- 撤销点 tag `pre-refactor-merge-b401ab8`;自 baseline 0f05fe9 起 51 commits。
- **Evidence(原则2)** ✅ merge 9f19578：`verify_claim_evidence` 做实(空白归一化逐字校验 + B4 页码缩小 + 额外的 locator 页码不匹配检查)、`validate_claims`(judgement 空据拒)、attach/read helpers、SCHEMAS Evidence 节。我独立 fixture 验过。additive(无 caller 时零影响)。
- **Gate 验实质(3.11)** ✅ merge e30dc2c：`has_substantive_content` + `confirmation_track`(事实轻/判断重) + 空心门。**关键:我实测发现 handoff 只堵了 promote_record(次路径),主用户路径 confirm_unit(paper.py confirm/交互 kb review)仍开** → resume agent 补堵 confirm_unit(在 info_types 压成['fact']前检查)。我用原探针复验:hollow judgement→REJECTED、substantive→confirmed、fact-track→exempt。两条 confirm 路径均已堵。四条治理红线回归过。



用户拍板：建**单一总纲**（意图+架构+功能全含），**目标架构采纳审查方向**。从今往后系统的意图/目标架构/功能设计以该文件为准；SCHEMAS.md（数据模型）+ AGENTS.md（规则）下挂；本 BACKLOG 只管计划/时序。what_i_need.md 被其 Part 1 取代。
- 已写实：Part 0 元规则 + Part 1 意图对账（C1-C19，每条标现状）+ Part 2 目标架构（6 原则：agent产出/证据层/渐进信任+验实质门/交互模式/注意力预算/活KB）。
- **Part 3 功能设计 14/14 子系统已拍板（2026-07-09，全锁）**：3.1 源分层(arxiv→HTML优先 + PyMuPDF4LLM轻量默认 + MinerU/Docling重后端可选,PDF/HTML两套locator) · 3.2 初筛全交agent+双入库模式+确认入库一律自动深读五要素(motivation/method/experiment/limitation/insight) · 3.3 文件级入库+按需符号级 · 3.4 只网页 · 3.5 agent答题走原生能力(Grep/Read+parse-cache)不自建语义索引/kb find脚本保留 · 3.6 综述=标准survey骨架(taxonomy核心)+evidence-first硬约束(每单元格/趋势/gap挂据,observed vs inferred,对比表压"只罗列"通病)+时间锚点/stale提示 · 3.7 陪练=idea-workbench模式(专家审稿人,非唱反调,每结论落盘) · 3.8 读resources缩放矩阵+主动提合理资源需求 · 3.9 轻度强类型指标+诊断拉最近N轮+baseline/milestone常驻对比 · 3.10 大纲加verb+缺输入标missing不脑补 · 3.11 先做分轨道(事实类轻确认/判断类实质确认)+关键决策insight主动询问 · 3.12 阻塞证据>stale>pending · 3.13 不做定时扫描但会话内矛盾必主动询问+更新 · 3.14 先接autonomy/reporting_style/resources+记忆模块主动记忆更新偏好(走确认门)。
- 跨切原则已并入 Part 2：B1(kb add两阶段:脚本备料→agent填理解→脚本验证) · B3(evidence验证=短逐字quote+summary,脚本验逐字存在) · B4(PDF页码/HTML anchor两套locator) · 成本原则(轻量只作用初筛,入库必深读不省token)。
- **Part 3 全锁 + Part 4 差距表/施工地图已回填（2026-07-09）**：SSOT Part 0-4 完整闭环。Part 4 定了4个地基(证据层L/PDF-HTML双源L/kb add两阶段M/确认门验实质M)+逐子系统现状实测+量级+四波施工顺序(地基→analyzer做实→产出闭环→体验层)，验收锚点=G5 benchmark。
- **下一步 = 按 Part 4.2 开工：先建 G5 尺子（handoff 已就绪 temp/codex_prompt_research_value_eval.md），再动地基（证据层 schema）。**
- **维护铁律**：改功能边界/门控/架构前，先改 SSOT 再改代码。

## [审查 2026-07-08] 第一性原理审查 → temp/FIRST_PRINCIPLES_AUDIT_2026-07-08.md
需求层视角（非实现层），补 ADVERSARIAL_SKILL_AUDIT 未覆盖的角度。核心结论：
- **三个失败的假设**：① 确认非廉价（实测 0/314 confirmed，信任模型从未运转）；② 价值重心放反（10 个整理 skill vs 4 个薄产出 skill，而需求最高价值在产出）；③ KB 当静态档案柜，但领域是活的（无 stale/矛盾检测/复查）。
- **需求本身遗漏 G1-G8**：G1 论文大纲无 owner（字面缺失）· G2 只归档讨论不主持讨论（缺陪练模式）· G3 伴读≠入库（缺交互式阅读模式）· G4 无时间维度（无监测 push + 无自校正）· G5 无研究价值验收尺子（最该先补）· G6 把注意力当免费（缺"只看这3件事"过滤器）· G7 PDF 源实际没归档（core.py:2303 file_hash=""，追溯地基空）· G8 未分"选择推进"vs"确认为事实"。
- **三件最高杠杆**（与当前 roadmap 的重构/打包重心不同）：① 先立验收尺子（G5，近零工程）② analyzer 改"LLM 产出+脚本验 evidence"（理解只能来自 agent，非更聪明的 Python）③ 补伴读+陪练模式（非补 skill 数量）。顺带修 G7。

### [进行中 2026-07-08] G5 验收尺子 → 已设计，待 Codex 施工
- 用户拍板：**G5 开做**（我定方向，Codex 施工）。
- 方向文档：temp/RESEARCH_VALUE_EVAL_DESIGN.md（3 设计决策 + 7 能力轴 + 数据集 schema + 指标 + 护栏 + 验收）。
- Codex handoff：temp/codex_prompt_research_value_eval.md（数据集 ~33 题 + Tier-1 只读 harness + 首份基线报告 + Tier-2 规格/示范）。
- 关键校准（勘察真实素材后定）：kb/raw 有真 PDF（6639 文件）→ gold 有据可依，G7 只影响自动 intake 新 URL 那条路；note 头 `审查状态：REWRITTEN` 可区分手工重写 vs 脚本产物 → harness 度量"去掉手工好 note 后系统还剩多少能力"；humanoid program active_unit_ids=[] 当空-program 对照组测幻觉。
- 归属：eval harness 先挂 skill-evolution-advisor/scripts（不新建 skill，呼应"别加 skill 数量"）；是否独立成 research-eval 留后续。
- 待办：Codex 施工 → 我验收首份基线数字 → 综合题 gold 需用户（领域专家）确认才转正式分。
- **[已落地 2026-07-09] G5 Tier-1 已实现 + 首份基线报告**：harness `.agents/skills/skill-evolution-advisor/scripts/eval_research_value.py`（只读，唯一写 kb/eval/research-value/reports/），数据集 33 题（physics-aware 18 + humanoid 15，7 轴全覆盖），TIER2_SPEC.md（规格 + 3 手工示范），smoke test `.agents/lib/research/tests/test_eval_research_value.py`（全 162 测试绿）。首份基线报告 `kb/eval/research-value/reports/20260709T091601Z-tier1.md`。关键数字（main HEAD 0f05fe9 / kb ecc8fd7）：**检索召回@5=80%、@10=90%**；**接地率 100%（15/15 客观 fact，覆盖率 0.67-1.00）**，来源分布=3 手工 REWRITTEN note vs 12 脚本产物；**humanoid 空-program 对照 10/11 题返回自信但错误的 top-1（幻觉风险面，最高 score 72）**；**H1 门控：confirmed=0（尚无人工确认），auto_confirmed=1 且空心=1；系统性 64/65 篇 paper 的结构化 core_content 全空**。最弱轴=F（program 状态，召回@5 仅 50%，因 program state 不在 unit 检索索引里）。

### [实证 2026-07-09] 当前版本入库实测 → 坐实审查，校正 G5
用户质疑"kb/ 是旧版遗留"，遂用**当前版本**在干净工作区跑完整入库（install → kb init → ingest AR-FB paper）。原隔离产物已清理，报告归档于 `dev-docs/reviews/legacy-acceptance/ar-fb-ingest-acceptance-2026-07-08.md`。结论：
- **审查被当前版本产物直接坐实，且更严重**：note.md 是空模板（record.yaml payload.core_content 8 字段全空，唯一有内容的节是 PDF 首页字节原样粘贴）；screen 评级=硬编码关键词命中数（novelty 因出现 'first'/'introduce' 评 strong）；screen 自带警告"未配 LLM backend 回退 heuristic"=作者明示占位。
- **旧 kb/ 好 note 是人手写的**（头标"审查状态：REWRITTEN"），不代表当前 skill 能力——用户直觉对。
- **空心确认门**（新发现，超出原审查）：core_content 全空的 note 被轻松 promote 成 confirmed/complete/fact，门只验人名+evidence 字符串存在，不验内容非空。
- **默认新用户环境无 PDF backend 且静默降级**（冷启动缺口）：默认 add→parse-cache.chunks=[]（bare except 吞掉）、note=占位；装 pypdf/PyMuPDF 重跑才有 16 段原文+14 图。managed venv 常压根没建（bootstrap 见系统 python 有 yaml 就短路）。
- **G5 三处校正已写进设计**：① gold 一律从 PDF 原文起草绝不抄 note；② 新增 H1 门控完整性检查（扫 confirmed 但 core_content 空的 unit，纯扫盘）；③ 报告头记录 PDF backend 可用性。
- 记忆已存：first-principles-audit-and-g5 + research-skills-analyzer-is-scaffolding。

## [已完成 2026-07-08] UX Quick Wins 第一批（蓝图审查后，main 0f05fe9）
详见 temp/BLUEPRINT_AUDIT.md。8 项全绿合入：kb status 真渲染状态摘要（不再只打路径）、阶段 stdout 加主线“下一步”导航、intake hint 改主线导向、kb 动词清单三处统一(+doctor)、USER_GUIDE 加 information_types×confirmation_status 对照表 + task→skill 索引、install print_next_steps 接回文档、kb review 尾部提示非unit级待确认、删死配置 summary_style/novelty_bar + config show 单列 personalization、SAFE_AUTO_STEPS 外化为 runtime-preferences.autonomy.auto_execute_scope（治理封顶 GOVERNANCE_MAX_AUTO_STEPS 不可突破，effective=配置∩封顶，实测 confirm/select 被挡）。治理逻辑零 diff。

## [待办 2026-07-08] 蓝图审查后续批次（用户已表态方向，本次未做）
- 完整 autonomy 行为策略层：default_mode(ask_first/auto_safe/auto_aggressive)/stop_before/proactivity/by_stage/by_kind，kb init 加一问。地基已铺（autonomy.auto_execute_scope + GOVERNANCE_MAX_AUTO_STEPS）。
- 主线导航：给 orchestrator next 加“选了idea没design / 有design没实验 / 实验确认了没报告”断点推理（用户选“给 next 加主线推理 + 文档流程图”）。
- gate 默认 strict on + kb init 选严格/宽松模式（用户选“kb init 选模式，默认 strict on”）。
- 确认收件箱全 pending 源聚合（unit + 实验诊断子项 + decision-log + learnings）。
- 死代码：删除 orchestrate.py 误路由的 ROUTE_HINTS route（无 caller）；SKILL.md description 中英混用统一为中文。


## [已完成 2026-07-08] install.sh project-scope 改拷贝 + update/uninstall + manifest
用户改主意：不软链，直接拷贝整棵 .agents 进 DIR，DIR 即 KB 目录。已实现并合入 main（f20c81f）：
- 拷整棵 .agents+AGENTS.md 进 DIR（stdlib install-lib/ws_sync.py）；DIR/.claude/skills 本地相对软链；DIR/.venv 首次运行自建；零 RESEARCH_SKILLS_HOME。
- update/uninstall 子命令 + DIR/.agents/.install-manifest.json（source_repo/commit/files-sha/agents 选择）。
- clean-sync 只碰 .agents 子树 + 单 AGENTS.md，manifest 精确删、containment 双查、漂移门(--force)、塌缩兜底。kb/ .venv 绝不触碰（实测 sentinel 恒等）。
- 四道守卫：重装→use update；foreign .agents→拒；遗留 symlink→拒+提示；用户 AGENTS.md→拒。
- 单仓 --project . 与 system scope 不回归（system 仍逐 skill 软链）。
- 对抗性审查发现 6 缺陷全修（run_smoke 越界写 kb/、写路径 containment、祖先排除塌缩、漂移撞本地、损坏 manifest 卸载、update 复现 agent 选择），17 项经验证全绿。

## [旧] install.sh 解耦 skills-home 与 KB workspace（2026-07-08 发现，用户暂不改）
（下述档2「软链+sentinel」方案已被上面的拷贝方案取代，保留仅作历史参考。）

现状短板：
- project scope 交互安装（prompt_scope, install.sh:231）只问 project/system，不问 workspace；WORKSPACE_ROOT 静默默认 $(pwd)（:191-194）。只有 --project <DIR> 能指定。
- 解耦架构支持（RESEARCH_SKILLS_HOME/skills_root + RESEARCH_PROJECT_ROOT；WORKSPACE_ROOT!=REPO_ROOT 有绝对软链+copy 模式 CLAUDE.md），但装出来的 kb 不自动指向 workspace：
  - --kb-on-path 只生成指向仓库 KB_SCRIPT 的裸软链，不 pin 任何 env（:539）。
  - find_project_root(start=repo) 无 RESEARCH_PROJECT_ROOT/--root 时 walk-up 命中仓库自身（common.py），不是 cwd、不是 workspace。
  - 证据：install.sh smoke（:562）必须 `RESEARCH_SKILLS_HOME=repo kb --root WORKSPACE status` 才通 → 装完 kb 默认指向仓库。

两档修法（用户当时选“先只答疑不改”）：
- 档1 UX+wrapper：project 交互问 KB workspace 目录（默认 cwd，==repo 提示会耦合）；--kb-on-path 由裸软链改成 pin RESEARCH_PROJECT_ROOT=<ws> + RESEARCH_SKILLS_HOME=<repo> 的 wrapper 脚本。改动仅 install.sh。缺：agent 直调 skill 脚本仍需 --root/env。
- 档2 完整解耦：档1 + 往 workspace 写 sentinel（如 .research-workspace，含 skills_home 指针），find_project_root/skills_root 先从 cwd 向上找 sentinel，命中即以 workspace 为根。kb 与 agent 直调脚本在 workspace 内零 env 自动指向对的 KB。改动更大：碰核心根发现逻辑，需回归保证不破坏单仓模式（cwd 在仓库内时仍解析为仓库）。

注意不变量：wrapper 是启动器不是 skill copy，不违反 symlink-not-copy（脚本仍靠自身 __file__ resolve 到 .agents/lib）。
## [完成 2026-07-21] Markdown-first 原始材料层与本地代码导航

- **用户范围**：paper/PDF/HTML/网页等成功入库后生成完整 Markdown，图片本地化，供人类、AI、Obsidian 共读；必要时 fallback 原格式。代码引用只打开本地对应文件，暂不要求远程 URL 或精确行。暂不维护 `/Users/czx/Documents/knowledge_base`，只在临时 KB 验证。
- **锁定设计**：`source/original.* + document.md + assets/ + source-map.yaml + conversion.yaml`；Markdown 与原件都不可变，parse-cache 兼容保留；HTML 图片解析 `src/srcset/data-src/data:`/SVG，PDF 图片由 PyMuPDF4LLM 抽取并按 hash 归档；Obsidian unit 页链接 source Markdown，repo 链接由可信 `repo_root + relative_path` 生成本地 URI。
- **红线**：不读写真实知识库；不覆盖旧 source/parse-cache/receipt；不让脚本理解图片或论文；不把 AI 图像描述冒充原图注；不 Base64 内联；不把绝对代码路径作为 canonical identity；测试只用临时目录。
- **落地**：paper/PDF/HTML/Markdown/text 统一生成 `source/document.md`；HTML/Markdown/PDF 图片按内容 hash 本地化，转换失败生成 degraded stub 并保留原件；Obsidian 阅读入口与 page/section evidence 精确链接到 stable source block，repo evidence 仅从可信 `repo_root + relative_path` 生成本地文件入口。
- **不可变加固**：raw bytes、`document.md`、`source-map.yaml`、`conversion.yaml` 与 hashed assets 同内容可幂等重跑，内容冲突 fail-closed；补测抓出本地文件重跑时静默沿用旧 raw 的漏洞并修复。
- **验收**：临时 KB `/private/tmp/kb-markdown-e2e.Qn2Gik` 完成 HTML/PDF/Markdown + 图片 + Obsidian 投影端到端验证；真实 `/Users/czx/Documents/knowledge_base` 未读写。最终全量 `887 passed`，5 个修改 skill 均通过官方 quick validator，`git diff --check` 通过。提交：`31e144e`、`aafc8a9`。
- **施工顺序**：schema/SSOT → materializer + source-intake 接线 → Obsidian/运行规则 → 临时 KB 端到端 → 完整回归与关键提交。

## [已完成 2026-07-22] HTML materialization v2 与真实 Obsidian 验收

- **用户 finding**：文献 HTML/Markdown 存在离线样式丢失、`<base>` 导致图片 404、LaTeXML fatal 页面被误记 complete、公式被 Markdown 转义、图片 alt 与 Obsidian wikilink 冲突、多图 figure 被摊平等问题；旧知识库无需迁移，后续重建。
- **锁定设计**：原始 `source.html`、确定性离线 `archive.html`、规范化 `document.md` 三层分工；arXiv/ar5iv 候选写盘前过质量门，全文 HTML 失败则优先 PDF；相对 URL 服从 `<base>`，公式占位保护，图片/fragment/figure 做 Obsidian-safe 规范化，conversion v2 记录 quality 与 archive hash。
- **验收范围**：只在临时 KB 入库一篇含公式、图片与内部引用的真实论文，机械检查 Markdown/HTML/asset/link/manifest，再将临时 `kb/` 作为 Vault 用 Obsidian Reading view 目测；不更新 `/Users/czx/Documents/knowledge_base`。
- **红线**：shipping skill 仅在隔离临时目录作行为测试，不作为设计依据；不改真实 KB；原始响应与 materialization 产物不可变；脚本只转换/验证，不理解论文。
- **实现**：`source.html` 保留原始响应；新增确定性 `archive.html`（内联最小样式、本地 hashed assets）与 conversion v2 manifest；HTML 候选写盘前过 fatal/title/full-text 质量门，arXiv native → ar5iv → PDF → abstract fallback；转换尊重 `<base href>`，保护 MathML/TeX，生成稳定 Obsidian block id，清洗图片 alt，并对 LaTeXML error 节点只在规范化阅读面做机械剔除。
- **真实论文验收**：隔离 KB `/private/tmp/kb-html-v2-final.fvDWu9/kb` 入库 arXiv `2603.12263`（Ψ₀）；生成 106,261 字符 Markdown、341,990 字符离线 HTML、11 个本地图片、206 个 block id、146 个内部 fragment、111 个公式。原 HTML 含 2 个 LaTeXML error marker，因此 manifest 如实为 `degraded`，但 `document.md`/`archive.html` 已无可见错误残留。
- **机械验收**：146 个 fragment 全有目标；Markdown/HTML 资源齐全且无远程图片；archive hash 匹配；无 token 泄漏、无 Obsidian image/wikilink 冲突、公式内无错误下划线转义；managed Obsidian page 指向 source Markdown。
- **Obsidian 目测**：临时 KB 作为 Vault 打开；Reading view 中 Ψ₀ 标题与公式、作者、章节、表格、Figure 1 本地图片/图注、内部引用均正常，block id 不外露。补点离线页时 macOS 锁屏，但其文件/hash/assets 已通过机械验收。
- **提交**：`3e48430`（主体）；LaTeXML 阅读面残留清理另作小提交。旧知识库未读写。

## [已完成 2026-07-22] Markdown 跨格式兼容性加固

- **真实 finding**：Ψ₀ 的 LaTeXML display equation 被外层 layout table 转成空 pipe table + 游离公式/编号；复杂 `rowspan/colspan` 数据表被 markdownify 压扁为列数不一致的 pipe table。现有 Markdown 输入处理还会把 fenced/inline code 中形似图片或 heading 的样例当真结构，源 YAML front matter 在生成 header 后会被 Obsidian 当普通水平线。
- **锁定范围**：修 equation/complex table；引入 code-aware Markdown image/heading 扫描；折叠保留 source front matter；本地化 Markdown raw HTML image；纯文本 literal rendering；离线 HTML passive sanitization；四类 materializer 共用格式 lint/metrics。
- **追加加固**：精确保留 arXiv `vN`；HTML/PDF/Markdown/text 共用结构 lint；复杂表格保留安全 raw HTML；跨行 code span/front matter block scalar 不误处理；Markdown raw HTML 与离线页统一被动化；HTTP/meta/XML charset 无损解码；未知 binary 原字节留存；派生 bundle 同盘 staging + 全量碰撞预检 + `conversion.yaml` 最后提交，失败不留半套；目录重试按同一规则忽略 VCS metadata。
- **自动验收**：最终完整非端口套件 `897 passed`；需要 loopback 的 navigator auth 独立 `15 passed`，合计 `912 passed`；Python 3.9.6/3.13 专项、py_compile 与 `git diff --check` 通过。
- **安装验收范围变更（用户 2026-07-22 显式授权）**：允许通过 `install.sh update` 同步到 `/Users/czx/Documents/knowledge_base` 并直接在那里创建新测试 KB、用冷 agent 加载 shipping skills 做真实多来源 intake；目标当前没有 `kb/`，不涉及旧 canonical units 迁移。
- **安装态冷验收**：`install.sh update` 最终同步到 commit `e8c018a`；目标 `/Users/czx/Documents/knowledge_base` 以受管 Python 3.9.6 正常运行。冷 agent 创建 9 个测试 unit（2 paper / 1 repo / 1 dataset / 5 blog），覆盖 exact-v1 arXiv、直接 PDF、远程/本地 HTML、Markdown、纯文本、dataset card、repo tree；所有原件/document/archive/asset hash、source block、相对引用和安全边界通过。新 `<base>` fixture `b-base-e8c018a-ea5ec7fe` 图片成功本地化；旧 immutable defect unit 未覆盖。
- **运行态验收**：Obsidian update/status 当前且 0 findings；doctor 为 Python/YAML/Markdown/PDF ready；修复 pre-fix init 三条 untracked 后 audit PASS 0 warnings/errors、nested KB Git clean；manifest 101/101 路径与 managed block 校验通过。
- **本轮提交**：`c779556`（跨格式主体）、`2d9fa9f`（协议文档）、`1fcc32c`（Python 3.9）、`9bb0bb4`（纯文本 lint）、`c3825ec`（本地 base asset）、`e8c018a`（init checkpoint）；此前同分支 HTML v2 为 `3e48430` / `cdf6c73`。
- **明确保留的产品边界**：local dataset directory 仍非受支持输入（本地 dataset card 文件可入库；directory 只允许 repo），不在本轮把任意数据目录整体复制进 canonical unit。arXiv 的证据身份与抓取候选保留显式 `vN`；`payload.basic_info` 的 convenience identity 仍归一到 base paper id，调用方需要 exact edition 时必须读 canonical `source.original_uri`。

## [已完成 2026-07-22] 最终真实多来源、Obsidian 与 installed-copy 冷验收

- **冷验收 finding 闭环**：远程 repo URL 不再静默保存 GitHub 页面，要求先建本地只读快照；空 claims 不再显示为待人工确认；中文 profile 驱动 Home/unit/Bases；repo 页提供 README、入口文件与本地源码目录；Hugging Face card 标题先剥离 frontmatter，再取 `pretty_name`/正文标题；所有 shipping skill metadata 通过官方 validator。
- **最终补洞**：同字节 source 以“本地文件 → 远程 URL”顺序入库时，URL preflight 尚无 bytes 导致去重不对称；现于 staged backup 完成后用 `file_hash` 再做 canonical dedup，并清理未采用的 staging。Obsidian Pending Review Base 改消费唯一派生 `analysis_stage=awaiting_confirmation`，不再按 record skeleton 的 `pending_user_confirmation` 误收待 AI 分析条目；renderer revision 升至 6。
- **自动验收**：最终全量 `928 passed`、7 个第三方 SWIG deprecation warnings；18 个 shipping skills 官方 quick validator、AST、`bash -n install.sh`、`git diff --check` 均通过。
- **真实目标安装**：`install.sh reinstall --all` 将 commit `08b94a3` 以 copy-project 安装到 `/Users/czx/Documents/knowledge_base`；installed sources/Obsidian/intake 三处关键文件与开发仓字节一致。
- **最终干净 Vault**：5 units（arXiv Ψ₀、UltraChat 200k、Obsidian API Markdown、Click 本地快照、SQLite Query Planning），Obsidian projection `renderer_revision=6`、records=5、managed files=10、0 error/warning；Home 0 项待确认，`kb review` 无待确认判断，嵌套 Git clean。
- **真实 UI**：Obsidian 1.12.7 Reading view 实际检查 Home、All Units Base、repo 快捷入口、UltraChat 表格/代码、Ψ₀ 标题/公式/图片/引用、SQLite HTML/ToC/本地资源；排版与链接可用。最后一次 5-unit 重开时 macOS 锁屏，但同构页面已在上一轮 6-unit 投影实际验收，最终 revision 6 的差异仅为 Pending Review filter，且落盘 Base 已独立核对。
- **installed-copy 去重 smoke**：隔离 scratch 先以本地 SQLite HTML 入库，再经 localhost URL 提供完全相同字节；第二次返回已有 unit，最终 records=1、staging 无残留、Git clean，server 已停止。
- **可恢复备份**：重建过程中旧测试 Vault 均只移动未删除；最终上一版 6-unit 备份为 `/private/tmp/knowledge-base-kb-final-delta-20260722-193107`，Obsidian 自行生成的临时配置移至 `/private/tmp/knowledge-base-final-delta-obsidian-config-20260722-193626`。

## [已完成 2026-07-23] 论文内部引用紧凑化

- **用户 finding**：arXiv HTML 转出的 Markdown 在 Obsidian Live Preview 中把 `[12, 28, ...]` 展开成长链接；根因是外层引文方括号与首个 Markdown link 拼成 `[[12](...)]`，撞上 Obsidian wikilink 语法，同时同文档 fragment link 继承了冗长 bibliography `title`。
- **修复**：只转义引用组外层左方括号，并移除同文档 block link 的冗余 `title`；保留每个编号的可点击 block 跳转、参考文献正文、原始 HTML 与离线页信息。
- **真实材料/UI 验收**：用 `/Users/czx/Documents/knowledge_base` 中 Ψ₀ 的真实 `source.html` 在隔离目录重新 materialize，未转义冲突数为 0、内部链接 title 数为 0；临时预览在 Obsidian Live Preview 中显示为紧凑可点击的 `[12, 28, 22, 14]`，测试笔记随后移出 Vault。
- **自动验收**：全量 `928 passed`、7 个第三方 SWIG deprecation warnings；`git diff --check` 通过。

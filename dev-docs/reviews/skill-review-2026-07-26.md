# workspace-oss 冷启动实测 — 发现记录（进行中）

环境：云容器 Ubuntu, Python 3.11.15（系统 python 带 yaml/pypdf/bs4/markdownify；无 pymupdf4llm，且沙箱镜像装不了 PyMuPDF 系包）。源码 = 用户本机快照（0.2.0-rc.7, 去掉 .git/.venv/kb）。

## 实测通过的路径（计时）
- install.sh --dry-run 0.4s / 正式安装 2.1s（含 smoke：kb help + doctor）
- kb init 1.5s；headless 快速设置（--name/--lang/--persona-*/--quick-*）3.0s
- kb ingest 本地 md → blog unit 2.8s（source bundle + document.md + parse-cache + fill 骨架 + NEXT FOR AGENT 指引）
- blog 四要素 fill + verify 0.8s（逐字 quote + section locator 校验真实生效）
- kb ingest 本地目录 → repo unit 2.0s；三要素 fill + verify 0.9s（file:line 证据校验通过，line 号真实核对）
- kb find 中文/英文查询均 <0.9s，5 段带定位，命中已填 claim 与原文 chunk
- kb review 0.8s：2 单元、逐条判断+证据摘录+"另有 N 条"，排版清楚
- review 确认应用（快照绑定、原子批量）3.0s
- orchestrator init-program / attach-unit ~0.7s；experiment plan + 2×log-run ~1s
- report weekly 1.2s：已确认 claim+证据+事件流完整；产物落 kb/programs/<id>/reports/weekly.md
- kb obsidian update 1.0s；kb status 1.6s；kb undo 0.9s
- 全程 journal + git checkpoint 每步落盘

## 发现（按严重度）
1. [阻断/装] 源码不是 git worktree → 安装失败，真实原因（ws_sync 要求 git ls-files 界定打包范围）被吞，公开层只说"工作区文件操作失败"。install.sh 捕获了 child stderr 但失败分支直接丢弃 $output。GitHub "Download ZIP" 用户必撞墙。
2. [阻断/装] doctor 说"论文解析能力已就绪"（pdf_backend=pypdf），但 intake 本地 PDF 硬性要求 PyMuPDF4LLM → "stored but not parsed" retryable 失败。bootstrap 兼容性探测（有 yaml/pypdf 即认为当前解释器可用，不建 managed venv）弱于 intake 真实依赖；install smoke 也没接住。requirements.txt 声称 pymupdf4llm 是 always-installed core。
3. [高/Agent 机制] SKILL.md 只有治理契约，无任何调用示例。实测踩坑：--agent-protocol 是全局 flag 必须放在动词前（放后面报"我没能理解这条 kb 请求"）；review apply 用 --apply-snapshot <协议文件名> 而非 snapshot_token；--confirm-ref 格式是 kind:id（bare id 报"这次拍板不在刚才展示的范围内"）。共 3 次失败摸索，全靠读源码走通。每个新 agent 会话都要重付此成本。
4. [高/Agent 机制] 双重脱敏：连私有 agent 协议里也只有 "tampered_or_unknown" 级别错误码，未说明期望格式或具体不匹配项，agent 无法自修复。
5. [中] kb undo 撤销的是"最近一次操作"且不报对象——实测把刚 build 的 obsidian/managed 派生视图删了（用户多半以为撤销的是 canonical 操作）。undo 前/后都不点名操作对象；派生视图重建是否应计入 undo 队列存疑。
6. [中] 周报中"tinyrepo — 缺少：结构合法且已确认的判断（结构或证据核验未通过）"：实际是核验已过、仅待确认；措辞把 pending 说成核验失败。
7. [小] owner 脚本直连时公开 stdout 打绝对路径（[root] project: /root/...），违反自家"公开输出无绝对路径"契约（kb-cli 过滤了，直连没过滤；而 NEXT FOR AGENT 指引恰恰让 agent 直连 owner 脚本）。
8. [小] 中文标题生成 slug 丢中文：实验 "短块+一致性精修 vs 基线 chunking" → x-vs-chunking-*。
9. [小] kb help 每行缺动词本名（只有描述+"也可以直接对 AI 说"），16 动词清单需从引号里拼。
10. [小] experiment plan/log-run 成功输出是裸路径，无自然语言反馈（与对话契约不符）。

## 环境限制（非产品缺陷，待真机复测）
- 沙箱包镜像无 pymupdf4llm/PyMuPDF → 本地 PDF 深读线未走通（机制上与 blog/repo 同构）。
- 无外网 → arXiv/HTML 真实来源线、literature-search 联网检索未测（与其自家 release gate 的"真实来源验收"重合）。
- kb next 的 PortfolioDecision prepare/verify/record 循环未走完（下一轮补）。

## 尚未覆盖
kb resume/restore/reject、Obsidian review 勾选表往返、monitor 订阅、idea-workbench / method-designer / literature-synthesizer / discussion-archivist / config recall、D1 诊断、20 份 SKILL.md 静态审计与上下文成本测算。

## 第二轮补充发现（kb next / 对抗测试 / Obsidian 往返 / 恢复类动词）

11. [高/复杂度税·实证] kb next 决策循环：单一候选也需 9 次 agent 操作才能完成"选择"——dashboard→prepare（不产出骨架）→手写 PortfolioDecision YAML（decision_id/kind 字段靠 SCHEMAS.md 拼）→eligible-preferences（operation 名 'plan' 靠读源码；canonical task inputs 三字段必须逐字一致）→逐项 accounted receipt（4 项各需 reason+application，≤240 字符单行）→receipt 的 scope 必须与快照 scope 逐字节一致（program_ids:[] 与 [program-id] 视为不同任务）→verify→record→next。实测踩 6 次失败。偏好回执在 orchestrator:plan 是硬前置，但在 analyst fill 是 neutral-optional——最重的门设在最轻的操作上。
12. [高/对抗测试] evidence locator 不做位置校验：repo 判断中 quote 在 refiner.py line=1，标 locator line=3 也通过 verify；blog 判断中真实 quote 配 section:nonexistent-section 也通过。逐字校验只查"quote 是 artifact 的子串"，locator 是自由文本。伪造 quote 会被正确拒绝（blog verifier 报错精确到 element/claim/ref，很好）。后果：Obsidian 跳转与后续复核依赖的定位可能整体失真，且带错 locator 的判断可一路走到 confirmed（实测走通）。
13. [中/机制] Obsidian 批次三个 flag 的参数各不同源：--preview-obsidian-batch 吃 sheet 里 HTML 注释中的 64 位 batch_ref（传文件名/路径报笼统错误）；--apply 需要 preview 协议里的 expected_preview_digest。SKILL.md 无一句提及。
14. [中/机制] config.py record-effective 的 --selection-json 吃 JSON 字符串而非文件路径，报错不区分"文件路径当 JSON 解析失败"；eligible-preferences 的两类输入错误直接裸 traceback（违反自家"无 traceback"契约）。
15. [中] kb restore <操作编号> 无处获取编号：journal 有 91 个 op 文件（时间戳-hash 命名），但没有任何公开动词列出操作历史；restore 缺参只回"我没能理解"。undo 可用但不点名撤销对象（前轮已记）。
16. [小] prepare-next-selection 与其他 owner 的 prepare 惯例不一致：不产出待填骨架、不给 schema 提示，只打印一句话。
17. [好] 对话内确认与 Obsidian 批次共享同一 coordinator 的设计实测成立：export→勾选→preview（复述 diff）→digest+当前消息授权→原子应用→sheet 翻转"已处理"，全链 4.3s。reject/recall/resume 空态与成功态文案都干净；reject 后 status 计数即时正确。

## 第三轮补充发现（idea 线 / 论文大纲 / 诊断与 audit / 上下文税实测）

18. [高/静默失败] idea analyze verify 两种静默失败：bare 文件名 --input（与 blog/repo 同样用法）→ 静默 exit 1，内部生成的精确违规信息（"cross-unit evidence sources are missing, ambiguous, or unsafe"）被 bare SystemExit(1) 吞掉；repo 相对路径 --input → 静默 exit 0 且零写入。真实原因：证据引用了不在冻结 corpus 内的合法 KB 单元（r-tinyrepo）——跨单元引用恰是 idea 分析的本意，但 corpus 只冻结 capture 时 --source 指定的单元，且没有任何输出告诉 Agent"只能引用 corpus 清单内的 artifact"。修正引用后 verify 通过并持久化 judgements。
19. [高/自洽性] 全程只用产品自身入口操作，kb.py audit 仍报 FAIL：1×error 级 INTEGRITY_PROGRAM_LINK（program.active_unit_ids 含 2 单元而单元侧 record.links 为空；"正向边+读时反推"的关系设计与 audit 规则自相矛盾）+ 11×RECOVERY_DIRTY_PRODUCT_FILE（experiment log-run、prefsel receipt、issues.yaml 等写盘不建 checkpoint）。"每次变更都有精确 checkpoint"的叙事存在系统性缺口。
20. [中] kb reject 后单元 record.status 仍为 active（仅 confirmation_status=rejected），记录层状态语义不一致；public 计数正确排除。
21. [中] D1 errors-only 捕获生效但过度脱敏到无用：issue 只有"知识库操作未完成"+trigger=ingest。对"记录 skill 可优化点、辅助定期完整优化"的单人目标，本地日志信息量不足以复盘；脱敏强度按导出/多人场景一刀切。
22. [中/上下文税] 实测：.agents/AGENTS.md ≈7k tokens 常驻；20 份 SKILL.md 合计 ≈33k；SCHEMAS.md ≈32k 且 portfolio/monitor 等"Agent 手写 YAML"操作无 scaffold 只能翻 SCHEMAS.md。一次"ingest+分析+确认"典型任务要加载 15–25k tokens 的规则文本。最大单份 SKILL.md 约 10KB（literature-synthesizer）。
23. [小] paper-outline 的 repo 证据行只有 line=N、无文件路径（blog 行有 section 名），读者无法定位；且发现 12 植入的错误 locator（line=3）原样进入 confirmed claim、周报与大纲——全链路无一处拦截。
24. [好] idea 证据分析骨架设计好（novelty/feasibility/recommendation/killer-question + corpus digest 冻结）；weekly/outline 从 confirmed claims 拼装、严格区分"待填写"与已证内容；audit 本身能发现真问题（包括产品自己的问题）；monitor due 只读干净；D1 显式记录路径可用。

## 补充环境说明
- research-monitor 的 apply 深测跳过：与 portfolio 同为"Agent 按 SCHEMAS.md 手写 YAML"模式，无 scaffold；due/unresolved-outcomes 只读入口正常。
- literature-search 联网检索无法在沙箱测试；本地 staging 机制未单独展开（测试套件 99KB 覆盖其状态机）。

## Phase 2 静态审计（第一批结论）

25. [量化/文档-机制断层] 20 份 SKILL.md 中 6 份完全没有任何命令/参数示例——而且包含最关键的 kb-cli（dispatcher 本尊）、experiment-workbench、knowledge-base-manager、literature-synthesizer、method-designer、report-author；其余 14 份也只有片段式子命令提及（如"运行 profile --phase prepare"，无脚本路径）。没有任何一份文档化 --agent-protocol 的位置要求、--apply-snapshot 语义、kind:id ref 格式、batch_ref 来源。Agent 机制知识事实上全部存在于源码与运行时 NEXT FOR AGENT 提示两处。
26. [量化/绝对路径来源] 所有 owner 脚本的公开 stdout 绝对路径都来自 lib/common.py 的统一 print("[root] project: <resolved>")——单点修复即可全量消除（好消息）。
27. [结构画像] 脚本重量分布（SKILL.md 字节 / scripts 行数）：orchestrator 9.7KB/3810L、idea 8.4KB/3562L、navigator（dev-only！）2.8KB/2966L、paper 7.3KB/2171L、intake 4.5KB/1816L…… 尾部：monitor 5.6KB/238L、discussion 3KB/116L、wiki-adapter 3.6KB/94L、kb-cli 8.9KB/0L（dispatcher 逻辑在 lib）。观察：(a) dev-only 的 navigator 背着第三大的脚本体量；(b) wiki-adapter 94 行脚本配 3.6KB 契约文，属"文档比实现厚"的薄路由；(c) monitor 契约厚、脚本薄，重活在 lib/monitoring.py 89KB。
28. [环境限制] 沙箱 pip 镜像也无 pytest——测试套件绿否无法在容器复核，采信其 CHANGELOG 自述并留待真机验证。

## 距离评估的中期校准（基于 1+2 阶段证据）

结论骨架成立：治理/存储/校验的"承重墙"（原子写、journal、逐字 quote 校验、快照绑定确认、原子批量、免插件 Obsidian）实测都是真的，且速度可接受（单步 0.3–4s）。真正的缝隙集中在四类：
A. 冷启动两个阻断（git-worktree 安装依赖、PDF 依赖探测断层）——各是小修，1–2 天量级；
B. Agent 机制层（发现 3/4/13/14/16/18/25）——这是"每会话重付学费"的结构性成本，也是对话轮次的主要放大器。修法明确：每个 owner 输出机器可读的 next-step 契约（已有 NEXT FOR AGENT 雏形）+ SKILL.md 补调用手册 + 错误消息在私有通道说人话。1–2 周量级；
C. 校验的真实强度（发现 12/19/23）——locator 位置校验、program-link 自洽、checkpoint 全覆盖。中等工作量，1 周量级；
D. 复杂度税的减法（发现 11/21/22）——偏好回执分级（analyst 模式推广到 orchestrator）、诊断脱敏分级、SKILL.md 契约进代码。这是重构主体，2–4 周量级，且应与缺口补齐（bib/检索/实验导入）合并规划。

尚未计入：真实 arXiv/HTML 来源与 Obsidian 实机验收（用户真机跑）、literature-search 联网行为、多 program 规模化表现。

## Phase 2.5 内部材料与文件结构专项审计

### 磁盘画像（设备实测）
kb/ 7.4G（raw 3.1G + units 2.6G + 嵌套 .git 1.8G）｜tmp/ 4.7G（施工残渣）｜.venv 61M｜.git 26M｜.agents 18M（含 11M tests 树）｜temp/ 1.9M（开发史文档）｜.learnings 188K（legacy）｜docs 68K。外层 git 只追踪 218 个文件（干净）。

### 逐项判定
29. [高/资产风险] temp/ 是整个项目的"开发大脑"却在 gitignore 区单副本存放：SYSTEM_DESIGN_SSOT.md（786 行，BACKLOG 反复引用的设计 SSOT！）、what_i_need.md（980 行原始需求文档）、blueprint.md、BACKLOG.md（R6–R18 对抗审计闭环全史）、OPTIMIZATION_PLAN.md、4 份对抗/第一性原理审计、130+ codex_prompt_* 施工 prompt、多份验收报告。判定：立即迁入 git 追踪的 dev-docs/（或 docs/dev/），这是"skill 演化记忆"的真正载体，丢了等于丢掉整个演化史。
30. [高/发布面] research-navigator 的 vendored web UI 是全仓库最大追踪文件（xterm.js 489KB + kb.js 148KB），且安装器把 884KB 的 dev-only skill 装进每个用户工作区。判定：移出 bundle（独立 tools/ 或单独仓库），安装默认不带。
31. [中/回收] tmp/ 4.7G 全是 accept-test 工作区、demo、fake fill 等施工残渣。判定：清空回收（本 review 的两份文档除外）。temp/ 与 tmp/ 双 scratch 目录职责不清，处置后合并为一个。
32. [中/存储策略] kb 嵌套 git 已 1.8G 且 PDF/HTML assets 进历史后不可逆增长；65 papers+14 repos 占 5.7G 数据（人均 ~70MB/单元，repo 类可能整仓入 units）。判定（结合"旧库可弃"决定）：新库采用 raw/ 不入 git（或 LFS），kb git 只管 records/程序状态等文本；repo 类 unit 存浅克隆或仅存引用+本地路径。
33. [中/位置反常] 测试树（11M，源码约 2M）在 .agents/lib/research/tests 即分发树内部（安装时已正确排除，但位置误导贡献者）。判定：移到仓库根 tests/。kb-cli 的 dispatcher 单文件 205KB、orchestrate.py 169KB、idea.py 146KB——与其自家 OPTIMIZATION_PLAN 的 T-GODFILE-v2 结论一致，拆分。
34. [小] .learnings/（ERRORS/FEATURE_REQUESTS/LEARNINGS，legacy 机制）已被 kb/memory/skill-evolution 取代。判定：有效条目并入 dev-docs 后删除。.worktrees/ 与 .claude/worktrees 为空目录，删除。20 份 agents/openai.yaml 样板逐 skill 重复，改为构建时生成或按需可选。
35. [小/文档去重] rc 状态段与成熟度表在 README、USER_GUIDE、CHANGELOG、DESIGN 四处近似复写（drift 测试只盖 CLI 文档面）。判定：单一事实源（CHANGELOG+VERSION），其余引用。SCHEMAS.md 双重身份（Agent 运行时合同 + 开发者文档）：authoring 模板改由 prepare 脚本产出，文档部分归 docs/。
36. [佐证] BACKLOG.md 显示项目经历 R1–R26 轮"对抗 review→独立复现→修复→冷验收"闭环（最新全量 1,866 passed），治理密度是被这个流程逐轮加固出来的；且我发现的 restore-id 不可发现、owner stdout 内部路径两项已在其 P2 清单——本 review 与其内部审计互相印证。what_i_need.md 第 1 节明确把"尽量节省 token、避免反复读取"列为总目标——实测的上下文税（15–25k tokens/任务规则文本、9 步偏好仪式）直接违背项目自己的最高层需求。

## 第四轮：需求覆盖核对（对照 temp/what_i_need.md 全文 980 行）

37. [中/需求缺口] 论文"六维快速筛选"未落地：what_i_need §3.1/15.1B 要求筛选含作者机构背书、效果强度、实验充分度、可靠性、创新性、相关性等维度；现 quick_screen 仅 paper_type + judgement_reason + takeaways 三字段（六维只能挤在 judgement_reason 自由文本里）。BACKLOG 曾列"paper 六维结构化筛选"为 P2 收口项，未见落地。注意与 literature-search 的"不得把作者声誉当质量信号"规则做区分：检索初筛禁用是对的，入库筛选作为"有证据的 Agent 评价字段"是用户明确要的。
38. [中/需求缺口] 报告三兄弟同质化：weekly / ppt-materials / outline 实测输出几乎相同（同一 claims+evidence 堆叠，仅标题不同）。"PPT 素材"没有页级要点、讲述顺序、图表引用——"可直接上台"的编辑层完全留给消费端 Agent 现拼，与 §8"平时积累、阶段性自动汇总"的期待有距离。
39. [中/需求缺口] 图表资产不可引用：§11/15.1 明确要求 PDF/网页图表"解析成图片并命名，方便论文笔记/周报/PPT 引用"；现实现是 hash-addressed assets/（哈希文件名），document.md 内相对引用可读，但报告链路完全不消费 figures，也没有 figure→caption→编号 的可引用索引。paper payload 已预留 figures 块，未被打通。
40. [中/需求缺口] 配置系统与需求 §10 的距离：要求"大量可开关选项 +（类 markdown 勾选的）直观配置方式 + 能反映 token 消耗与自动化程度取舍"；现状开关散落（auto_screen/auto_commit/autonomy scope/诊断模式），无统一清单展示，无勾选式配置面，无 token/自动化档位概念。蓝图的治理分档解决了"档位"，但"配置可见性/可勾选"仍缺。
41. [小/需求缺口] 若干字段级缺口：intake 未自动抓论文的代码链接/项目主页、仓库的 license/最近活跃度/依赖环境（§15.1A/15.2A）；阅读状态仅 maturity 二档（需求为未读/粗读/精读/需回看）；实验负责人（多人协作）无字段；AI 讨论角色（陪练/审稿人/合作者/管家）未成为可配偏好（§14）。idea 新意核查与 literature-search 需手动多步串联（§6.3 期望"基于已有文献分析是否被做过"）。
42. [核对结论/覆盖良好面] §16 信息类型标注（fact/inference/evaluation/user_opinion/unverified）、§17 元字段与入库确认规则、§12 隐含要求（防重复解析/连续流转/长期追踪/用户可控）、§15.5 实验字段、§3.3 筛选→精读复用：均已实现且实测符合，部分（如 17.3"存结果怎么来的"）实现强度超出原始需求。

# 功能蓝图审查 + UX/个性化差距分析（2026-07-08）

来源：blueprint-audit 工作流（5 路并行读真代码→高强度合成）。要害断言已由主线核实（SAFE_AUTO_STEPS 硬编码/summary_style 死配置/kb status 只打印路径/validate_write 默认 WARN 全部属实）。

## 一、主线脉络 (spine)

从零到一篇科研产出，系统里真实存在的主线是七段，但它只"活在 prose 里"，没有一个状态感知的进度视图把用户领着走：

第0段 安装与初始化：`bash install.sh`（交互回答 5 问）→ `kb init`（回答确认人名/语言/commit 节奏/是否自动筛选，外加可选 persona 画像）。产物：kb/ 骨架 + config。断点：安装结尾 print_next_steps 只说"kb init + kb status"两行，不接 USER_GUIDE、不教怎么对 AI 开口，装完即断线；且默认不把 kb 放 PATH，README 顶部照抄 `kb init` 会 command-not-found。

第1段 加材料（source-intake）：人说"把这篇论文轻量入库"或 `kb add <url> --kind paper`。agent 自动备份 raw、去重、建 record.yaml；paper 会按配置自动串跑 screen。产物落 kb/units/<kind>s/<id>/record.yaml。

第2段 分析（paper/repo/blog-analyst）：agent 出 quick-screen（值不值得细读）、full note、抽图。所有判断默认 pending。人：打开 unit 目录的 screen.md 看 recommended_next_action（stdout 不显示），再 confirm/reject。

第3段 综述（literature-synthesizer）：agent 跨材料出 survey/taxonomy，区分 Observed/Inferred。程序无关，落 kb/synthesis/。

第4段 idea（idea-workbench）：agent generate 多候选、analyze novelty+feasibility（pending）。人拍板：显式 select/select-best，必须给 --confirmed-by + --evidence，置 status=selected。

第5段 方法设计（method-designer）：这是 unit 半场与 program 半场的接合点。method.py design 强校验 idea.status=='selected'，产出 repo 选型/接口/实验矩阵，更新 program state.yaml→implementation-planning，并 emit reporting-event。断点：idea.select 完全无 program 感知（不接 --program-id、不 emit event、不写 decision-log），"选定 idea"这个里程碑不会自动进 program 事件流，全靠人工把正确 --program-id 传给 method.py 并另跑 log-decision。

第6段 实验（experiment-workbench）：agent plan/log-run/diagnose，每步 emit reporting-event。人：喂真实 run 的 metric/outcome，确认诊断（pending+evidence）。

第7段 报告（report-author）：weekly/stage-summary 只读 reporting-events.yaml 渲染，是 drafting aid 需 AI 二次润色。断点：上半场（intake/分析/survey/idea）不 emit reporting-event，周报只看得到 method→experiment 下半场。

主线的三个系统性缺陷：(1) 没有一张端到端编号流程图，DESIGN 只讲架构分层，grep 无 pipeline；(2) 没有状态感知导航——orchestrator next 是队列驱动（阻塞证据>高优问题>待确认>手填 next），不理解"你在第几段"，故"选了 idea 没 design / 有 design 没实验 / 实验确认了没报告"这类断点系统不会主动提示；(3) 每步命令 stdout 只 `[ok] wrote <path>`，真正的下一步建议埋进产物文件里，用户看不见。

## 二、人 vs agent 分工 (actor split)

总体边界（真实实现，非文档承诺）：

AGENT 可稳定自动做（allowlist 内、无需问）：入库备份/去重/建 lightweight record、paper quick-screen、build-index、refresh 结构、generate-note——这四类被硬编码在 orchestrate.py:107 SAFE_AUTO_STEPS，execute_auto_plan(354-370) 只放行这四类。paper 线还能按 runtime-preferences 的 auto_* 开关自动串跑 prewarm→screen→complete-note→refresh(intake.py:279-302)。这些是"机制性自动"。

AGENT 默认应停下等人（治理判断）：任何 information_types 命中 {inference,evaluation,user_opinion} 或 source.kind==ai 的 record，写入时期望 confirmation_status=pending_user_confirmation（core.py:1574-1613）。orchestrator 遇 pending 返回 kind=human-gate 并停（orchestrate.py:182-199）。这是"该问不该做"的一档。诚实标注：这一档是"应该停"而非"被强制停"——validate_write 默认 strict=False，只写 stderr WARN，不 SystemExit（core.py:1585-1612），只有 RESEARCH_VALIDATE_STRICT=1 才真拦；write_record 也不校验 confirmed 是否带 provenance。所以"AI 不能自己盖章"在 helper 路径（apply_confirmation→require_confirmation_provenance, core.py:1476-1516）是硬的，在 storage 直写路径是软的。

只有人能拍板（四类里程碑，散文规则 USER_GUIDE.md:69-72）：选 idea、定 baseline/超参/ablation、判定实验结论、决定研究阶段推进。人拍板必须签名（人名，is_ai_signer 拦 ai/assistant/codex/gpt）+ 至少一条 evidence，否则 SystemExit。identity.default_confirmed_by 只补签名不补 evidence。

关键落差：三档里只有第一档（allowlist）是代码强制的自动，第三档的签名+evidence 在 helper 路径是代码强制的；中间"AI 判断默认 pending"这一档在直写路径是软的。而"agent 沿主线自动推进到哪一步"这个真正的自主度阀门，目前完全等于那个写死的 4 元素 allowlist，用户无法个性化。

## 三、功能蓝图分区

### [partial] 治理模型与数据模型（confirmation gate + information_types + provenance）
- 目的：用 confirmation_status 四态 × information_types 五类 + 签名/evidence provenance，保证 AI 的推断/评价默认待人确认、确认需人签名，是整个系统可信度的地基。
- 用户做：清 kb review 收件箱（逐条 y/n/s + 强制输一次 evidence）；单条/批量 confirm 时给人名+evidence；reject 不认可的判断；kb init 一次性设定 default_confirmed_by。
- agent 做：为每条 record 打 information_types 与 confirmation_status；AI 判断默认 pending；确认迁移走 apply_confirmation 校验 provenance；orchestrator 遇 pending 停为 human-gate。
- 关键 GAP：
    - 确认门控默认不拦截：validate_write strict 默认 False，只 stderr WARN，仅 RESEARCH_VALIDATE_STRICT=1 才 SystemExit；直写 write_record 路径可给 [inference] record 直接写 confirmed 绕过 provenance。用户文档却把它讲成硬约束（USER_GUIDE.md:72 '不能自己盖章'），落差只在 DESIGN.md 对开发者讲。
    - 确认收件箱不完整：kb review 只扫 kb/units/<kind>s/*/record.yaml，遗漏 experiment diagnoses 子项、decision-log 待决策、reporting-events、learnings——各自 pending 但无聚合入口，用户清空 review 后误以为无待确认。
    - 确认后子文档不同步：experiment confirm 只 confirm_unit(record)，不回写 diagnoses.yaml 子项状态也不重跑 sync_diagnosis_summary，unit 显示 confirmed 而 diagnosis.md 仍渲染 pending。
    - 缺 information_types × confirmation_status 面向用户对照表，用户无法从一个 record.yaml 一眼看懂'这句是谁说的'。
    - gate 只看 information_types 与 source.kind，不校验标注诚实性：AI 把 evaluation 误标成 [fact] 即静默入库。

### [partial] 17 个 skill 与路由
- 目的：把科研工作拆成 17 个 owner 明确的 skill，靠 SKILL.md description 让 LLM harness 自动选，人用自然语言即可，不需背 skill 名。
- 用户做：说自然语言让 harness 自动选 skill；必要时用 $skill-name 点名；或跑 kb 动词隐藏路由。
- agent 做：harness 按 description 匹配意图选 skill；每个 skill 在自己 owner 边界内写产物；orchestrator 提供 next/status/dashboard/auto 做 program 级路由。
- 关键 GAP：
    - 两套路由不协调：真正生效的是 SKILL.md description（LLM 消费），而 orchestrate.py ROUTE_HINTS 的 route 命令是死代码（无 caller、kb-cli 无 route verb），且是顺序敏感的首匹配子串查找，会误路由——连自己 SKILL.md:46 的范例 '分析新论文是否值得细读' 都返回 source-intake 而非 paper-analyst。
    - 无单一权威的 task→skill 决策图：唯一像样的 intent→owner 表埋在 wiki-adapter/SKILL.md 里（harness 未触发该 skill 时不加载），AGENTS.md 只有分组、DESIGN 只有 5 条抽象原则。
    - 描述语言 8 中文 9 英文，触发面不一致。
    - 17 名 + 11 种后缀，新手要消歧多组重叠（idea-workbench vs method-designer、KBM vs config-manager、三个 query 入口）。
    - 关于'agent 自主度'的请求即便路由成功也落到无法满足的 skill：route '配置 agent 自主度'→research-config-manager，但该 skill 只管机制旋钮，没有任何 owner 管行为边界（直接命中痛点#5）。

### [thin] 用户可见面（kb 伪CLI + 文档 + 人面向页 + 浏览器）
- 目的：给用户两条入口：对 AI 说自然语言，或在终端敲 kb 动词；并用 kb/user/ 下的页面呈现现状与导航。
- 用户做：跑 install.sh / kb init；说自然语言或敲 kb add/find/next/status/review/recall；打开 current-state.md/navigation.md/index.md 阅读。
- agent 做：kb 薄 dispatcher 转发到 owner 脚本；navigator 渲染三张人面向页；orchestrator 供 next/status。
- 关键 GAP：
    - 旗舰动词 kb status 名不副实：不带 program 时只打印文件路径 kb/user/current-state.md（+两行 [root] 诊断），不显示任何状态，但 kb help 承诺'查看当前状态摘要'。
    - kb 动词清单四处不一致（代码真 verb 9 个 vs README 6 个 vs USER_GUIDE 8 个缺 doctor vs kb help 把 idea/report 变 AI 短句），用户不确定到底能敲哪些命令。
    - 无一条编号主线路线图；navigation.md 名为导航却不含任何命令/下一步；current-state.md 无 per-program next-action；index.md 是无摘要的 16.7KB 全平铺 dump 却被列为首选入口。
    - kb next 输出是带未解析占位符 ${RESEARCH_CONFIRM_EVIDENCE:?...} 的原始 shell 命令，且'下一步'其实只是一条 status 命令。
    - 浏览器 Workbench 无 kb open/browser 动词，可发现性差；安装结尾引导只两行、与文档脱节；每次 status/next 先打印 [root] 噪音行。

### [thin] 配置与个性化（runtime-preferences + user-profile/personalization + learnings）
- 目的：让用户调 agent 行为与偏好：机制旋钮走 runtime-preferences，人面向偏好走 user-profile，习惯走 learnings 记忆闭环。
- 用户做：kb init 答 4 基础偏好 + 可选 persona 画像；set-runtime-pref/toggle 改机制旋钮；capture-resources 记资源；review/promote 把习惯沉进 learned_preferences。
- agent 做：读 runtime-preferences 决定 paper 线 auto_* 与 commit 节奏；session start 读一次 personalization 作 optional user_opinion；纠错后记 learning。
- 关键 GAP：
    - 没有任何'agent 自主度/行为边界'配置层：可配置的'行为'旋钮只有 paper 一条线 + git auto_commit_mode，repo/blog/idea/method/experiment/report/survey 全无 auto-vs-停下问 开关；grep 全仓 autonom/proactiv/自主/主动性 零命中。
    - 唯一贴近行为边界的 collaboration_boundaries 是惰性散文：只被 AGENTS.md:20 当 user_opinion 提示给 LLM，无脚本读取、与 SAFE_AUTO_STEPS/gate 零联动，给用户'我能设边界'的错觉。
    - 存在'假配置'：summary_style/novelty_bar 写在默认 profile 里像能调详略/新颖性门槛，但全仓无消费者（死配置），会误导。
    - personalization 块缺发现性/校验/持久：不在 _default_profile()、config show 不单列、无 guide、set 无枚举校验；没在 init 填就根本不存在且事后无 CLI 可审阅。
    - 优质引导（config guide + intake [hint] 打印当前模式+可复制命令）只覆盖 paper-intake 一个 focus 值。

### [partial] 科研工作流主线（加材料→分析→综述→idea→选定→method→实验→诊断→报告）
- 目的：把七段科研生命周期串成从零到一篇产出的端到端流水线，reporting-events.yaml 作跨 skill 粘合剂。
- 用户做：投喂材料；判断值不值得细读；清确认收件箱；选 idea/拍板 baseline（签名+evidence）；喂实验事实；确认诊断；决定阶段推进与出报告时机。
- agent 做：各阶段脚本产出 pending 判断；method/experiment emit reporting-event；orchestrator/navigator 提供导航；空 KB 提示第一步 intake add。
- 关键 GAP：
    - 无端到端主线导航/进度视图：program stage 是自由文本，orchestrator next 只做队列排序不按主线位置推理，不会提示'选了 idea 没 design''有 design 没实验''实验确认了没报告'；per-unit 下一步 safe_unit_step 只覆盖未挂 program 的 loose 单元且只到分析层。
    - idea→program 接合点断裂：idea.select/select-best 无 program 感知（不接 --program-id、不 emit event、不写 decision-log），关键里程碑全靠人工穿线。
    - 上半场（分析/综述/idea）不 emit reporting-event，周报 backbone 只看得到 method→experiment 下半场。
    - 下一步建议埋在产物文件（screen.md recommended_next_action / idea next_actions / diagnosis 建议），stdout 只 [ok] wrote，用户看不到。
    - program 人面向入口页 README.md 被 SCHEMAS 规定但无脚本生成，每个 program 缺'我这个方向现在到哪了'落地页。
    - 主线自主度无个性化：agent 自动推进多远 = 写死的 SAFE_AUTO_STEPS，无'推进到哪步就停'配置（痛点#5 在主线上的体现）。

## 四、UX/引导差距（按痛点排序）

### [high] 没有状态感知的端到端主线导航——用户不知道自己在第几步、下一步做什么  （#3 使用脉络不清晰 + #4 用户不知道该做什么、何时做）
- 证据：grep 全仓无 pipeline/主线序列；orchestrate.py:596-620 next_action 全是队列/手填来源无主线判断，640-643 已挂 program 单元被跳过；DESIGN 只讲架构分层；主线只活在 USER_GUIDE prose 里，无编号流程图。
- 修法：新增 `kb journey`（或让 kb status 真出内容）：读 program state + unit 状态，按七段主线判断断点并输出'你在实验段，已确认 2 条诊断，下一步：把结论写进周报'。orchestrator next 增加主线推理：检测 selected-idea-无-design / design-无-experiment / experiment-confirmed-无-report 三类断点并主动提示。文档补一张编号生命周期图（安装→init→add→screen→survey→idea→select→design→experiment→diagnose→report）。

### [high] 旗舰动词 kb status 不显示状态、kb next 输出原始 shell 命令带未解析占位符  （#1 易用性差 + #4 用户不知道该做什么）
- 证据：实测 kb status 仅输出三行（含两行 [root] 诊断）+ 文件路径 kb/user/current-state.md（navigate.py:127-129 只 print 路径）；kb help 却承诺'查看状态摘要'；kb next 实测输出 `command: ...orchestrate.py status --program-id ...` 和 `--evidence ${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}`。
- 修法：让 kb status 直接渲染 current-state.md 内容摘要（active program stage/OQ/pending 计数/Confirmed Highlights）而非打印路径；kb next 把原始命令翻译成人话动作（'下一步：确认这条诊断，运行 kb review'），解析或隐藏 shell 占位符；把 [root] 诊断行降级到 --verbose 或 stderr。

### [high] agent 做事范围/主动性完全不可个性化配置，唯一阀门是写死的 4 元素 allowlist  （#5 agent 自主度无个性化）
- 证据：orchestrate.py:107 SAFE_AUTO_STEPS={screen,build-index,refresh,generate-note} 硬编码，execute_auto_plan:354-370 按此常量放行；core.py:364-413 default_runtime_preferences 只有 browser/paper/pdf/versioning/identity/learned_preferences；唯一贴近的 collaboration_boundaries 是无消费者的散文（grep 只命中 kb 写路径）；route '配置 agent 自主度'落到无法满足的 config-manager。
- 修法：见 agent_scope_personalization_proposal：新增 runtime-preferences.autonomy 结构化段，让 execute_auto_plan 读它替代硬编码常量，kb init 增加一问，与 gate 共存（只能在 governance 底线之上收窄/放宽 safe 自动范围，不能把 gated 决策改成 auto）。

### [high] 确认收件箱不完整 + gate 默认只 WARN，但文档讲成硬约束——用户对'系统会拦住 AI 越权'有错觉  （#2 引导不明确（安全承诺与实现落差））
- 证据：kb review 只扫 kb/units/<kind>s/*/record.yaml（core.py:1627-1641），遗漏 diagnoses 子项/decision-log/reporting-events/learnings；validate_write strict 默认 False 只 stderr WARN（core.py:1585-1612）；USER_GUIDE.md:72 写'AI 不能自己给自己盖章'未提默认不拦。
- 修法：(a) kb review 聚合所有 pending 源（unit record + experiment 诊断子项 + decision-log + learnings），或至少在结尾提示'另有 N 处非 unit 级待确认'；(b) 默认开启 strict 拦截（或 kb init 让用户选严格/宽松），至少 write_record 对 [inference]+confirmed 无 provenance 时报错；(c) 用户文档如实说明当前拦截强度，别把软约束写成硬约束。

### [medium] 配置里全是机制参数，且有死配置误导——用户想调'详略/新颖性/术语风格/边界'调不动  （#5 自主度无个性化 + #2 引导不明确）
- 证据：runtime-preferences 全是 pdf 抽图/cache/commit 机制旋钮；summary_style/novelty_bar 全仓无消费者（config.py:63-64 定义处外零命中）；term_style/reporting_style/research_focus 只有 kb 写路径无读取者；config guide --focus 只有 paper-intake 一个合法值。
- 修法：删除或接线死配置（summary_style/novelty_bar 要么让 analyst/report 真读，要么移除避免误导）；扩展 config guide 覆盖更多 focus；personalization 字段接线到实际 skill 读取点，并在 config show 单列该段 + 加枚举校验。

### [medium] 命令输出把下一步建议埋进产物文件，stdout 只 [ok] wrote，且 intake [hint] 只推销机制开关  （#3 脉络不清 + #4 不知何时做什么）
- 证据：paper.py:323 算出 recommended_next_action 写进 screen.md，677 只 print [ok] wrote；intake.py:116-145 三条 hint 全指向 config set-runtime-pref（自动补全笔记/note 模式/自动抽图），无一条是'下一步去 screen/综述/记 idea'的主线导航。
- 修法：每个阶段脚本在 stdout 追加一行主线导航（'已 screen，建议：确认后运行 kb next 看下一步'）；把 intake [hint] 从'推销配置开关'改为'主线下一步'，配置提示降级为可选尾注。

### [medium] 安装→init→第一个产出的引导断线，kb 动词清单四处不一致  （#2 引导不明确 + #1 易用性）
- 证据：install.sh:615-624 print_next_steps 只有'kb init + kb status'两行，不接 USER_GUIDE、不提打开 current-state.md、不教对 AI 开口；kb 默认不入 PATH（install.sh:460 默认 N）而 README 顶部直接示 kb init；代码真 verb 9 个 vs README 6 个 vs USER_GUIDE 缺 doctor vs kb help 把 idea/report 变 AI 短句。
- 修法：print_next_steps 扩成 4-5 步带 USER_GUIDE 链接与'打开 kb/user/current-state.md'；统一四处 kb 动词清单（以代码为准），补 doctor、标注 idea/report 为纯自然语言组；README Quickstart 明确 PATH 前提或给全路径。

### [medium] 缺 information_types × confirmation_status 对照表，用户看不懂 record 里'这句是谁说的'  （#2 引导不明确）
- 证据：枚举在 core.py:56-71 与 SCHEMAS.md:25-38 面向开发者；USER_GUIDE.md:62-72 只白话列举无对照表；index.md 仅打 confirm=<status> 不含 information_types。
- 修法：USER_GUIDE 加一张 4态×5类对照表（fact/auto_confirmed=AI 抄的事实、inference/pending=AI 推断待你确认、confirmed=你签过、rejected=你否了）；index.md/current-state 行内同时显示 information_types。

### [low] 点名 skill 的 $skill-name 与'不需背 skill 名'矛盾，且 17 名难消歧  （#4 不知道该做什么 + #1 易用性）
- 证据：USER_GUIDE.md:85/265 说'不需要背 skill 名'，L278/L282+README:101 又教 $paper-analyst/$literature-synthesizer 点名，未解释何时必须点名；17 名 + 11 种后缀，idea-workbench vs method-designer 等多组重叠。
- 修法：文档明确'默认全用自然语言，点名仅在你想强制某一步时可选'；给一张 task→skill 一句话索引（把 wiki-adapter 里那张表提升到 USER_GUIDE 顶层）。

## 五、agent 行为范围个性化方案

目标：为痛点#5 补上"agent 行为策略"这一层，与现有"机制参数"层严格区分，且真正被消费（不重蹈 collaboration_boundaries 惰性散文的覆辙）。

一、先厘清两层（这是方案的分水岭）：
- 机制参数（HOW 一步怎么执行）：现有 pdf.figure_render_scale/crop_padding、paper.parse_cache_*、versioning.debounce_seconds 等——决定"执行时的技术细节"。保持现状。
- 行为策略（WHETHER/WHEN agent 自主行动 vs 停下问）：目前完全缺失。这是要新增的层。

二、新增配置：runtime-preferences.yaml 增设 `autonomy:` 段（落在 core.py:364 default_runtime_preferences()，与 browser/paper/pdf 平级），候选项与默认值：
1. autonomy.default_mode: ask_first | auto_safe | auto_aggressive（默认 auto_safe，等价现状）。全局基调：ask_first=每步都先问；auto_safe=只自动跑 safe 步；auto_aggressive=在治理底线内尽量往前跑。
2. autonomy.auto_execute_scope: 步骤/阶段名列表（默认 [screen, build-index, refresh, generate-note]，即把写死的 SAFE_AUTO_STEPS 外化成配置）。可加 [repo-scan, blog-note, survey] 放宽，或删项收窄。
3. autonomy.stop_before: 强制停下的里程碑列表（默认 [select-idea, choose-baseline, ratify-conclusion, advance-stage]）。这几项是治理红线的镜像——只能增不能减到治理底线以下（见第四条）。
4. autonomy.proactivity: silent | on_request | proactive（默认 on_request）。控制 agent 是否主动汇报 pending 收件箱、主动提下一步、主动荐新论文。取代覆盖面极窄的 paper.prompt_for_preference_updates。
5. autonomy.by_stage（可选覆盖）：{exploration: auto_safe, validation: auto_aggressive, writing: ask_first} 之类分阶段自主度，回应"验证阶段你可以更主动"。
6. autonomy.by_kind（可选覆盖）：paper/repo/blog/idea 各自的 auto-vs-ask，让"repo 分析你自己往下做"可落地。

三、读取机制（务必真消费，这是与散文字段的本质区别）：
- 执行阀门改造：orchestrate.py execute_auto_plan(354-370) 与 safe_unit_step 不再读硬编码常量 SAFE_AUTO_STEPS，改读 autonomy.auto_execute_scope；SAFE_AUTO_STEPS 降级为"治理封顶集合"（见第四条）而非唯一真相。
- intake.py 的 paper auto_* 门控（276-303）改为叠加 autonomy.default_mode/by_kind 判断。
- proactivity 被 orchestrator/navigator 在生成 next/current-state 时读取，决定是否主动追加提示。
- 承接现有读取规则：autonomy 是 runtime-preferences（被全部 skill 读的权威 artifact，SCHEMAS.md:399），天然被消费；而 AGENTS.md 里"session start 读一次 personalization 作 user_opinion"那条规则保留给软偏好（语气/术语），autonomy 走硬读取路径，不靠 LLM 自觉。

四、与治理共存（红线不可破）：
- 铁律：autonomy 配置只能调节"safe 自动化跑多远"，永远不能把 confirmation-gated 决策改成 auto。即 validate_write/require_confirmation_provenance（core.py:1476-1516,1574-1613）是硬地板：任何 information_types 命中 AI 集合或 source.kind==ai 的判断仍必须 pending+人签名+evidence，autonomy 无权放行。
- 实现上：auto_execute_scope 的有效值 = 用户配置 ∩ 一个治理封顶集合（原 SAFE_AUTO_STEPS 的超集，但绝不含 confirm/select/stage-change）。用户即使写 auto_aggressive，遇 human-gate 仍停。
- stop_before 只能加项（更保守），删到红线以下的项被忽略并 WARN。
- 这样"个性化"只在治理允许的自由度内生效，既满足用户"我要调 agent 范围"，又不破"AI 不能自己盖章"。

五、kb init 引导（补上发现性）：
- 在现有 4 基础问后加一问："agent 自主度：[1] 每步都问我(ask_first) [2] 只自动跑安全步(auto_safe，默认) [3] 在需你拍板处才停(auto_aggressive)"，写入 autonomy.default_mode。
- 可选追问 proactivity 与 by_kind（"repo/blog 分析要不要自动往下做"）。
- config guide 增加 --focus autonomy，打印当前 autonomy 段 + 可复制的 set-runtime-pref --section autonomy 命令（把现有 paper-intake guide 的优秀模式复用过来）。
- config.py set-runtime-pref 的 --section 允许集合（config.py:265）增加 autonomy，并对 default_mode/proactivity 做枚举校验（避免 personalization 那种无校验问题）。

六、与 collaboration_boundaries 的关系：保留它作软红线自由文本（user_opinion），但在文档里明确"它是提示不是执行阀门；要真正改变 agent 做事范围请设 autonomy"。可选增强：kb init 填 boundaries 时，若能映射到结构化 autonomy 项（如"入库前先问我"→by_kind.paper=ask_first）就顺带落一份结构化配置。

## 六、Quick Wins

- 让 kb status 真渲染 current-state 摘要内容而非打印文件路径（navigate.py:127-129），并把 [root] 诊断行降到 stderr/--verbose——一处改动直接缓解'旗舰动词名不副实'。
- 统一四处 kb 动词清单以代码为准（补 doctor，标注 idea/report 为纯自然语言组）：改 README/USER_GUIDE/kb help 三处文案即可。
- USER_GUIDE 加一张 information_types × confirmation_status 对照表 + 一张 task→skill 一句话索引（把 wiki-adapter/SKILL.md:20-31 那张表提升上来）——纯文档、零代码。
- install.sh print_next_steps 从两行扩成带 USER_GUIDE 链接、'打开 kb/user/current-state.md'、'对 AI 说：读取当前 KB 判断下一步'的 4-5 步，接回主线。
- 每个阶段脚本 stdout 追加一行主线导航（把已算好但埋进产物的 recommended_next_action 打印出来，如 paper.py:323→677），并把 intake [hint] 从推销配置开关改为'下一步去 screen/综述'。
- 把硬编码 SAFE_AUTO_STEPS 外化为 runtime-preferences.autonomy.auto_execute_scope 并让 execute_auto_plan 读它——最小可用的自主度个性化第一步。
- 删除或接线两个死配置 summary_style/novelty_bar（现无消费者会误导用户），config show 单列 personalization 段。
- kb review 结尾追加一行'另有 N 处非 unit 级待确认（实验诊断/decision-log/learnings）',消除'清空即无待确认'的错觉——不必立刻做全聚合。

## 七、需要拍板的方向性问题

### 决策1：确认门控是否默认改为强制拦截（strict on）？现状默认只 WARN，用户文档却讲成硬约束。
- 默认 strict on，AI 直写 [inference]+confirmed 无 provenance 即报错
- 保持默认 WARN，但改文档如实说明
- kb init 让用户选严格/宽松模式
- **推荐**：kb init 选模式，默认 strict on。安全承诺与实现对齐是信任地基；宽松留给明确要快的老用户。

### 决策2：agent 自主度用结构化 autonomy 配置层实现，还是继续靠 collaboration_boundaries 散文 + 硬编码 allowlist？
- 新增 runtime-preferences.autonomy 结构化段并让执行阀门真读它
- 只把 collaboration_boundaries 讲清楚不改代码
- 维持现状
- **推荐**：新增结构化 autonomy 段（见 proposal）。散文字段已证明零消费=错觉，痛点#5 必须要有被代码消费的阀门。

### 决策3：确认收件箱是否做成全 pending 源聚合（unit + 诊断子项 + decision-log + learnings + reporting-events）？
- kb review 全聚合成单一收件箱
- 只在结尾提示'另有 N 处'不做聚合
- 维持只扫 unit record
- **推荐**：先做提示（quick win），再迭代到全聚合。全聚合工作量大但直击'清空即无待确认'的错觉。

### 决策4：主线导航做成新的 kb journey 视图，还是增强 orchestrator next 的主线推理？
- 新增 kb journey 状态感知视图
- 给现有 next 加主线断点推理
- 只补一张文档流程图
- **推荐**：先给 next 加主线断点推理（复用现有队列基础设施），文档补编号流程图；kb journey 视为后续。

### 决策5：SKILL.md description 的中英混用（8 中 9 英）是否统一，orchestrate.py route 死代码是否删除？
- description 全统一为中文（用户主语言）+ 删 route
- 全英文 + 删 route
- 保持现状
- **推荐**：description 统一为中文并删除误路由的 route 死代码；触发面一致 + 少一套无人维护的分叉。

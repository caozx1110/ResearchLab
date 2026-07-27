你在开源 research-workspace 系统做两项耦合的核心改进（来自蓝图审查的痛点#3/#4/#5）。基线干净树 HEAD 0f05fe9，160 tests 绿。两项都跨 orchestrate.py，必须一起做。

【红线】治理逻辑零改动：validate_write / require_confirmation_provenance / apply_confirmation / needs_human_confirmation / human-gate 停止逻辑一律不碰。autonomy 只能在治理底线之上收窄/放宽“safe 自动化”，永远不能把需人签名的决策（confirm/select/stage-change）变成 auto。不碰安装器/ws_sync。保持上一批的 GOVERNANCE_MAX_AUTO_STEPS 封顶与 autonomy.auto_execute_scope 种子有效。旧配置缺新键要向后兼容（回退到等于今天的行为）。

先读真实文件确认现状：
- .agents/lib/research/core.py：default_runtime_preferences（autonomy 段现有 auto_execute_scope）、load_runtime_preferences（autonomy 归一化块）、write_runtime_preferences（含 autonomy 的 key 列表）。
- .agents/skills/research-orchestrator/scripts/orchestrate.py：GOVERNANCE_MAX_AUTO_STEPS(105)、execute_auto_plan(366-)、next 计算(575-672 program 项 + loose-unit 项)、load_state(436，字段有 selected_idea_id/selected_repo_id/stage)、TERMINAL_PROGRAM_STAGES(51)、format_next(711)、safe_unit_step(177)。
- .agents/skills/source-intake/scripts/intake.py：paper auto_screen 门控（约 276-303）与 guidance_hints。
- .agents/skills/kb-cli/scripts/kb：handle_init 交互块（auto_screen 后、persona 前）、build_init_pref_commands、build_headless_init_pref_commands、register_init flags、config_set_runtime_pref_command。
- .agents/skills/research-config-manager/scripts/config.py：set-runtime-pref --section 允许集合、guide --focus 分支、show。
- method.py（design 写 kb/programs/<id>/design/）、experiment.py（run-log/diagnoses、append_program_reporting_event）、report.py（读 reporting-events）——只为判断主线断点的产物标志，不改它们逻辑。
- AGENTS.md、docs/USER_GUIDE.md。

============================================================
一、autonomy 完整行为策略层（痛点#5）
============================================================
1.1 core.py default_runtime_preferences 的 autonomy 段扩展为（保留现有 auto_execute_scope）：
    "autonomy": {
        "default_mode": "auto_safe",              # ask_first | auto_safe | auto_aggressive
        "auto_execute_scope": ["screen","build-index","refresh","generate-note"],
        "proactivity": "on_request",              # silent | on_request | proactive
        "by_kind": {},                            # 可选 per-kind 覆盖，如 {"paper":"auto_safe","repo":"ask_first"}
    }
  语义：
  - default_mode 全局基调：
      ask_first = agent 沿主线不自动执行任何步（即使 step 在 auto_execute_scope 内也停下、打印建议让人确认）；
      auto_safe（默认，等于今天）= 只自动跑 effective_scope 内的 step；
      auto_aggressive = 在治理封顶内尽量往前（scope 仍受 GOVERNANCE_MAX_AUTO_STEPS 封顶，绝不含 confirm/select/stage-change），且默认更主动（proactivity 效果更强）。
  - proactivity：被 next/current-state 读，决定是否主动追加“下一步/待确认”提示。silent=不主动附加；on_request=保持现有；proactive=主动在 status/next 里附上主线下一步建议。
  - by_kind：intake paper 线与（未来其它 kind）按 kind 覆盖 default_mode。本批至少让 paper 生效。
  load_runtime_preferences 增加对 default_mode/proactivity 的归一化（非法值回退默认）、by_kind（非 dict 回退 {}）；write_runtime_preferences 的 autonomy 合并保留全部子键。

1.2 消费点（务必真读，不是死配置）：
  a) orchestrate.py execute_auto_plan：顺序必须是——① 先做现有 human-gate 检查（遇 pending/需人决策 → stop，绝不放行，逻辑不变）；② 若 default_mode==ask_first → 打印 plan + “[stop] autonomy=ask_first：需你确认后再执行” 并 return 0（不自动跑）；③ 否则按上一批的 effective_scope = 配置 auto_execute_scope ∩ GOVERNANCE_MAX_AUTO_STEPS 放行。auto_aggressive 不放宽封顶（封顶就是那四项），仅影响 proactivity。
  b) intake.py paper auto_screen 门控：在现有 auto_screen_on_intake 判断上叠加 autonomy——default_mode==ask_first（或 by_kind.paper==ask_first）时不自动 screen，改为打印“已入库，autonomy=ask_first：如需筛选运行 kb next / 让 AI screen”。auto_safe/auto_aggressive 维持现有自动行为。
  c) next/current-state proactivity：见第二部分，proactivity 决定是否主动附主线断点建议。
  治理共存铁律：以上任何模式都不改变 human-gate 与 validate_write；auto_aggressive 也绝不放行 confirm/select/stage-change（它们不在 GOVERNANCE_MAX_AUTO_STEPS 里）。

1.3 kb init 引导：在 handle_init 交互块 auto_screen 之后、persona [y/N] 之前，加一问：
    “agent 自主度：[1] 每步都问我(ask_first) [2] 只自动跑安全步(auto_safe，默认) [3] 需你拍板处才停(auto_aggressive)”
  默认 2。写入 autonomy.default_mode（复用 config_set_runtime_pref_command，section=autonomy key=default_mode）。headless 加 --autonomy-mode {ask_first,auto_safe,auto_aggressive} flag，纳入 build_headless_init_pref_commands 的检测与写入。非交互/非 TTY 不问、不写（保持默认）。

1.4 config：
  - set-runtime-pref --section 允许集合加入 autonomy（若尚未）；对 default_mode/proactivity 做枚举校验（非法值报错，像现有校验风格），auto_execute_scope 接受 JSON list，by_kind 接受 JSON dict。
  - guide 增加 --focus autonomy：打印当前 autonomy 段 + 可复制的 set-runtime-pref 命令示例（复用 paper-intake guide 的优秀模式）。

============================================================
二、next 主线断点推理 + 流程图（痛点#3/#4）
============================================================
2.1 orchestrate.py next 计算：对每个 program，在现有队列信号（blocking evidence / high questions / pending confirmation / next_actions）之外，增加“主线断点”检测。判据（用 program state + 产物存在性）：
  - selected_idea_id 非空，但 kb/programs/<id>/design/ 不存在或为空 → 断点“已选定 idea，尚无 method design”。
  - design 目录非空，但该 program 无关联 experiment unit（或关联 experiment 无 run-log 条目） → 断点“有 method design，尚无实验”。
  - 有 experiment 且存在 confirmed 诊断/结论（reporting-events 里有 experiment 类事件且有 confirmed），但 reports/ 下无 weekly/stage-summary（或 reporting-events 无 report 类事件） → 断点“实验有结论，尚未成报告”。
  优先级：主线断点的 score 低于 blocking evidence/pending（紧急阻塞优先），但高于泛泛的 “stage review”。断点命中时设 next_action 为人话动作 + reasons 追加断点名。judge 判据尽量用已有产物标志，判断不了的宁可不报（不要臆断）。
2.2 recommended_command 人话化：next 输出里，把裸 shell + ${RESEARCH_...} 占位符翻译成人话下一步或指向 kb 动词（如“运行 kb review 确认这条诊断”“让 AI 基于 selected idea 起草 method design”）。format_next 里不再直接吐带未解析占位符的裸命令；保留一个可选“底层命令”尾注但不作为主呈现。
2.3 proactivity 联动：proactivity==proactive 时，current-state / next 主动列出主线断点建议；on_request 维持现状；silent 时只在被显式 next 调用时给、不在 status 顶部主动附加。

============================================================
三、文档
============================================================
3.1 docs/USER_GUIDE.md 增“研究主线流程图”一节：七段编号流程（加材料→分析→综述→idea→选定→method design→实验/诊断→报告），每段一行标注“你做什么 / agent 做什么 / 下一步命令或对 AI 说的话”。放在显眼位置（靠前）。
3.2 docs/USER_GUIDE.md 增“agent 自主度”一节：解释 autonomy.default_mode 三档 + proactivity + by_kind 的含义与如何设（kb init 或 set-runtime-pref），并强调“autonomy 只调节安全自动化范围，绝不会让需你拍板的决策自动发生”。
3.3 AGENTS.md：加一条说明 autonomy 是被脚本硬读取的行为策略（区别于 personalization 的软提示 user_opinion）；措辞简短、与现有行风一致；不含任何个人数据。

============================================================
验证（改完自测，全绿再 commit）——逐条给实际输出
============================================================
1. python -m compileall .agents/skills .agents/lib 通过；bash -n install.sh 通过。
2. 全量 pytest 仍 160 绿（若默认 profile/preferences 结构变化导致断言，需同步更新测试期望，但不得放宽治理断言）。
3. autonomy 默认不变行为：全新 kb init 后 autonomy.default_mode==auto_safe，execute_auto_plan 对 screen 等仍自动放行（等于今天）。给实测。
4. ask_first：set default_mode=ask_first 后，execute_auto_plan 对 screen 打印 [stop] autonomy=ask_first 不自动执行；intake paper 不自动 screen 而是提示。给实测。
5. auto_aggressive 不破封顶：set default_mode=auto_aggressive 且 auto_execute_scope 含 "confirm"，execute_auto_plan 仍不放行 confirm（GOVERNANCE_MAX_AUTO_STEPS 封顶）。给实测。
6. 枚举校验：set-runtime-pref --section autonomy --key default_mode --value bogus 报错；合法值通过。
7. kb init 交互加了自主度一问（静态核对 + headless --autonomy-mode 写入 autonomy.default_mode 的实测）。
8. next 主线断点：构造一个 program（state.selected_idea_id 设值但无 design 目录），next 输出包含“已选定 idea，尚无 method design”这类主线建议；再造 design 无 experiment、experiment 有结论无 report 两种，各命中对应断点。给实测（可用最小手工构造 kb/programs/<id>/state.yaml + design 目录模拟）。
9. next 人话化：next 输出不再出现未解析的 ${RESEARCH_...} 占位符作为主命令。
10. proactivity：proactive 时 current-state 附主线建议；on_request 维持。给实测（至少 proactive vs on_request 的输出差异）。
11. 治理红线零 diff：git diff 显示 validate_write/require_confirmation_provenance/apply_confirmation/human-gate 逻辑未变；orchestrator 遇 pending 仍返回 human-gate 停。
12. USER_GUIDE 有流程图节 + 自主度节；AGENTS.md 有 autonomy 硬读取说明。

清理测试临时目录，勿把 kb/ .venv 加入提交。commit：autonomy behavior layer (default_mode/proactivity/by_kind, governance-capped) + next spine-breakpoint reasoning + workflow flowchart docs。最终回复列改动文件与每个验证步骤实际输出，并声明治理/安装/ws_sync 逻辑未改动。

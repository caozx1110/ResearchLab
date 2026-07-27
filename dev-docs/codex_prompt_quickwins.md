你在开源 research-workspace 系统做一批 UX Quick Wins（来自蓝图审查）。基线干净树 HEAD 4ac6456，160 tests 绿。共 8 项，多为文档/输出层，少量小代码。全部改完跑自测再 commit。

【红线】不碰治理逻辑（confirmation gate/provenance/validate_write）、不碰安装器安装/安全逻辑、不碰 ws_sync.py。只做下述明确改动。每项改完自测。用户已确认：死配置直接删除；SAFE_AUTO_STEPS 只做最小外化骨架（不做完整 autonomy 层）。

先读真实文件确认现状再改：.agents/skills/research-navigator/scripts/navigate.py（render_current 51、current-state 命令 114-128）、.agents/skills/knowledge-base-manager/scripts/kb.py（review_queue 97-124、cmd review-queue）、.agents/skills/source-intake/scripts/intake.py（guidance_hints 116-147）、.agents/skills/paper-analyst/scripts/paper.py（screen 命令 recommended_next_action 661、[ok] wrote 677）、.agents/skills/research-orchestrator/scripts/orchestrate.py（SAFE_AUTO_STEPS 107、safe_unit_step 177、execute_auto_plan 361-370）、.agents/skills/research-config-manager/scripts/config.py（_default_profile 58-70 的 summary_style/novelty_bar、config show、guide、set-runtime-pref --section 允许集合 265）、.agents/lib/research/core.py（default_runtime_preferences 364、load_runtime_preferences）、.agents/skills/kb-cli/scripts/kb（HELP_MENU）、docs/USER_GUIDE.md、docs/INSTALL.md、README.md、install.sh（print_next_steps）。

============================================================
A. 纯文档
============================================================
A1 统一 kb 动词清单（以代码为准=9 verb：help/init/doctor/status/next/find/add/review/recall）。
   - README.md、docs/USER_GUIDE.md、.agents/skills/kb-cli/scripts/kb 的 HELP_MENU 三处对齐：补 doctor；把 idea/report 明确标注为“纯自然语言，无 kb 动词”（不要伪装成命令）。三处清单文字一致。

A2 docs/USER_GUIDE.md 增两张表：
   - information_types × confirmation_status 对照表：用大白话解释每种组合“这句话是谁说的、要不要我确认”。取值以 core.py 枚举与 SCHEMAS.md 为准（fact/inference/evaluation/user_opinion/unverified × auto_confirmed/pending_user_confirmation/confirmed/rejected）。例：inference+pending=“AI 的推断，等你确认”；fact+auto_confirmed=“AI 抄录的客观事实，已自动入库”；confirmed=“你签过字的定论”；rejected=“你否掉的”。
   - task→skill 一句话索引：把每个意图映射到 owner skill（把 wiki-adapter/SKILL.md 里那张 intent→owner 表提升上来，覆盖 17 个 skill）。顶部注明“默认全用自然语言，点名 $skill 仅在你想强制某一步时可选”，消解 USER_GUIDE 里“不需背 skill 名”与教 $paper-analyst 点名的矛盾。

A3 install.sh 的 print_next_steps 从两行扩成 4-5 步引导，接回主线：
   - 保留现有 kb init / kb status 提示；新增：打开 docs/USER_GUIDE.md（给相对路径）、打开 kb/user/current-state.md、以及一句“对 AI 说：读取当前 KB，判断我下一步该做什么”。
   - 若 kb 未上 PATH，明确给出全路径调用方式或提示重跑加 --kb-on-path（复用现有 WS_KB_SCRIPT 变量）。
   - 仅改这段输出文案，不动任何安装逻辑。

============================================================
B. 小代码（改输出，不改业务逻辑）
============================================================
B4 kb status / current-state 真渲染内容（navigate.py）：
   - 现状：current-state 命令（约 127）只 print(current_path.relative_to(root))。改为：先确保 current-state.md 内容是最新（复用已有 render_current(...) 生成的文本），然后把该内容摘要打印到 stdout（active program stage / open questions 计数 / pending 确认计数 / Confirmed Highlights 等 render_current 已有的段落；若内容较长可打印前 N 行摘要 + 一行“完整见 kb/user/current-state.md”）。不要只打印路径。
   - kb dispatcher 的 status 转发到 navigate current-state，届时用户就能直接看到状态摘要。
   - 把 print_resolved_project_roots 那两行 [root] 诊断从 stdout 降级：改为仅在 --verbose 或写到 stderr（选其一，保持简单；若这函数被多脚本共用，最小改动是让 navigate current-state 不调用它，或加一个环境/参数开关）。不得破坏其它命令。

B5 阶段脚本 stdout 追加主线导航行：
   - paper.py screen 命令（约 677 [ok] wrote 之后）：把已算好的 recommended_next_action（661）翻译成一句人话导航打印，如 worth∈{yes,maybe} → “建议：确认后运行 kb next 看下一步（或让 AI 生成完整笔记）”；否则 → “建议：先放入 defer，或运行 kb review 处理待确认”。
   - source-intake intake.py：把 guidance_hints（116-147）的第一条从“推销 config set-runtime-pref”改为主线下一步导航（如 paper: “已入库+筛选，下一步：运行 kb next 或让 AI 判断是否值得细读”）；原有的配置开关提示降级为可选尾注（保留但排在主线导航之后，且数量收敛）。
   - 原则：每个阶段命令 stdout 至少有一行“下一步做什么”的主线导航，而非只有 [ok] wrote。不改写产物文件逻辑，只加 stdout 行。

B6 kb review 尾部提示非 unit 级待确认：
   - kb.py review-queue（cmd）在正常列出 unit pending 后，尾部追加一行提示：“注意：确认收件箱当前只覆盖 knowledge unit；实验诊断子项 / decision-log 待决策 / learnings 可能另有待确认，请分别查看。”（先做提示，不做全聚合。）措辞如实、不夸大。

============================================================
C. 配置清理 + 自主度地基
============================================================
C7 删除死配置 summary_style / novelty_bar：
   - 从 config.py _default_profile 的 preferences 中移除这两个键（58-70）。全仓 grep 确认无其它消费者后删净（不要留半吊子）。
   - config show 增强：单独列出 user-profile.yaml 的 personalization 段（若存在），让用户能看到 kb init 填过的 research_focus/resources/reporting_style/collaboration_boundaries/term_style；不存在则提示“未设置，可在 kb init 时填写”。

C8 SAFE_AUTO_STEPS 最小外化（为后续 autonomy 层铺地基，本次不做完整 autonomy）：
   - core.py default_runtime_preferences 增加一个 autonomy 段（与 browser/paper 平级）：{"auto_execute_scope": ["screen","build-index","refresh","generate-note"]}（即把现有 SAFE_AUTO_STEPS 的四元素作为默认值外化）。仅此一个键，不加 default_mode/proactivity 等（留给后续）。
   - orchestrate.py：import load_runtime_preferences；把 SAFE_AUTO_STEPS 常量降级为“治理封顶集合”GOVERNANCE_MAX_AUTO_STEPS（值仍是这四项的超集=就是这四项，注释说明它是不可突破的上限）。execute_auto_plan(361-370) 的放行判断改为：有效 scope = 用户配置 autonomy.auto_execute_scope ∩ GOVERNANCE_MAX_AUTO_STEPS；step_type 必须在有效 scope 内才放行。这样：默认行为与今天完全一致；用户改配置只能在封顶集合内收窄（放宽超出封顶的项被忽略）。绝不允许 confirm/select/stage-change 进入放行集（它们本就不在封顶集合里）。
   - 若配置缺失/损坏，回退到 GOVERNANCE_MAX_AUTO_STEPS（等于今天行为）。

============================================================
验证（改完自测，全绿再 commit）——逐条给实际输出
============================================================
1. python -m compileall .agents/skills .agents/lib install-lib 通过；bash -n install.sh 通过。
2. 全量 python -m pytest .agents/lib/research/tests -q 仍 160 绿（若删 summary_style/novelty_bar 或加 autonomy 段导致某测试断言默认 profile/preferences 结构，需同步更新该测试的期望，但不得放宽治理相关断言）。
3. B4：在一个已 init 且有内容的临时 KB 里跑 kb status（或 navigate current-state），stdout 显示状态摘要内容（不再只是一行路径）；[root] 诊断不出现在主 stdout。
4. B5：对一篇 paper 跑 screen，stdout 除 [ok] wrote 外有一行主线“建议：…”；intake add 后 stdout 第一条 hint 是主线下一步而非 config 命令。
5. B6：kb review（review-queue）尾部出现“另有非 unit 级待确认”提示。
6. C7：config.py _default_profile 无 summary_style/novelty_bar；grep 全仓无残留引用；config show 能列 personalization 段（有/无都给友好输出）。
7. C8：默认配置下 execute_auto_plan 放行集 == 今天四项（行为不变，用 orchestrator auto --execute 的既有测试或手工验证）；把 autonomy.auto_execute_scope 改成 ["screen"] 后只放行 screen；改成含 "confirm" 也不会放行 confirm（被封顶集合挡掉）。给出这三种情形的实测。
8. 治理红线未动：validate_write/provenance/gate 逻辑零 diff；orchestrator 遇 pending 仍返回 human-gate 停。
9. 文档一致性：README/USER_GUIDE/kb HELP_MENU 的 kb 动词清单三处一致且含 doctor。

清理测试临时目录，勿把 kb/ .venv 加入提交。commit：ux quick-wins: kb status renders state, stage stdout shows next-step, unified kb verbs, docs tables, drop dead config, externalize safe-auto-steps (governance-capped)。最终回复列改动文件与每个验证步骤实际输出，并声明未改动治理/安装/ws_sync 逻辑。

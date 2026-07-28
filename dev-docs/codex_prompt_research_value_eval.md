你在开源 research-workspace 系统实现 **G5：研究价值验收基准**（来自第一性原理审查，方向文档 temp/RESEARCH_VALUE_EVAL_DESIGN.md 已定，务必先读它）。目标：给两个真实 program 出一批「用户本来就会问」的问题，量出系统能不能有据地答，并可复跑对比。全部改完跑自测再 commit。

【红线】只**加**一个只读 eval 层 + 数据集。绝不碰被测系统：不改任何 confirmation gate / validate_write / provenance / analyzer 行为 / 检索算法 / program state。eval harness 只读 KB（读 record/note/parse-cache/index、调 kb find），除了写自己的 kb/eval/ 报告目录外零写入。碰了被测系统就等于测移动靶，本次作废。

【并行说明（Wave 1）】本 track 与 lib 重构（codex_prompt_lib_refactor.md）**并行跑**，各自 worktree。你**只读系统、只加新文件**（kb/eval/ + skill-evolution-advisor/scripts/eval_research_value.py），**绝不改 core.py 或任何被重构搬动的文件**；所有 import 走公开 façade（`from research.core import ...` / `from research.retrieval import ...`），这些在重构后依然可用。你抓的是**改造前的基线数字**（对当前 main），正是我们要的坐标。

【关键背景（先读，别重造）】
- 方向文档：temp/RESEARCH_VALUE_EVAL_DESIGN.md —— 三个设计决策(A/B/C)、7 能力轴、§3.5 实证校正、数据集 schema、指标（含 H1 门控完整性）、护栏、交付物、验收，全在里面。本 prompt 只给施工落点，语义以方向文档为准。
- **实证前提（2026-07-09 已跑当前版本验证，报告归档于 dev-docs/reviews/legacy-acceptance/ar-fb-ingest-acceptance-2026-07-08.md，务必先读它）**：当前 skill 入库产的 note.md 是**空模板**（core_content 8 字段全空、唯一有内容的节是 PDF 首页字节原样粘贴）；旧 kb/ 里的好 note 是**人手写**的（头标「审查状态：REWRITTEN」）。**因此：gold_facts 一律从 kb/raw 下真实 PDF + parse-cache 原文起草，绝不从 note.md 抄内容**（note 只能用来判断"系统当前能不能答"，不能当答案来源）。
- 检索入口：.agents/lib/research/retrieval.py 的 rank_records（词级排序全文，已存在，直接复用，别改）；kb query 的实现在 knowledge-base-manager/scripts/kb.py。
- 真实素材已核实存在：kb/raw/ 有 6639 文件含真 PDF（sirui-xu-main-papers-*/*.pdf、legacy-rebuild-papers/*.pdf）；64 个 parse-cache.yaml；65 个 note.md。note 头部可能有「审查状态：REWRITTEN」标记 → 用它区分手工重写 vs 脚本产物。
- 两个 program：physics-aware-fb-z-space（active_unit_ids 有 7 个单元，见 state.yaml）；humanoid-table-tennis-control（active_unit_ids=[] 空，这是**故意的对照组**，F 轴问它应返回「无数据」）。
- root 机制：复用 common.find_project_root / add_project_root_argument，支持 --root / RESEARCH_PROJECT_ROOT（照抄现有脚本的 bootstrap 写法）。

先读真实文件确认现状再动手：
- temp/RESEARCH_VALUE_EVAL_DESIGN.md（全部）
- .agents/lib/research/retrieval.py（rank_records / score_record / record_search_fields 签名）
- .agents/lib/research/common.py（find_project_root / add_project_root_argument / load_yaml）
- .agents/skills/knowledge-base-manager/scripts/kb.py（query 命令怎么调 rank_records，照它的调用方式）
- .agents/skills/skill-evolution-advisor/scripts/learnings.py（bootstrap/argparse/root 解析范式，照抄）
- kb/programs/physics-aware-fb-z-space/state.yaml + 其 active_unit_ids 指向的 7 个 unit 的 record.yaml/note.md（起草 gold 的素材）
- kb/units/papers/p-bfm-zero-humanoid-d03fb73b/note.md（一个高质量 REWRITTEN note 样例，gold fact 从这类 note + 对应 kb/raw PDF 起草）

============================================================
A. 数据集（先做，harness 依赖它）
============================================================
A1 建目录 kb/eval/research-value/{dataset,reports}/。

A2 起草 kb/eval/research-value/dataset/physics-aware-fb-z-space.yaml：
   - 按方向文档 §4 的 schema，每条一题。覆盖 7 轴（A 单篇事实 / B 跨单元对比 / C 脉络趋势 / D gap / E 复用代码 / F program 状态 / G idea 讨论），每轴 2-3 题，合计 ~18 题。
   - 题目用**用户口吻**（例：「BFM-Zero 的 z-space 和 Meta Motivo 的 latent 关键区别是什么」「physics-aware FB 这个 program 我现在卡在哪、下一步是什么」）。
   - Tier-1 题（axis A/E/F 偏客观）：填 gold_facts（text + source_unit_id + locator[page=N/section/file:line] + auto_gradeable:true）+ expected_units。gold_facts 必须**从对应 unit 的 note.md / parse-cache.yaml / kb/raw 下真实 PDF** 起草，locator 要能对上真实页码/段落，不许编。
   - Tier-2 题（axis B/C/D/G 偏综合）：填 gold_rubric（3-5 个评分要点）+ expected_units。
   - 综合题（Tier-2）的 gold_status 一律 `pending_user_confirmation`（决策 C，不自签）；客观 Tier-1 事实题若你能在 KB+PDF 里逐字坐实，可标 confirmed 并在 gold_drafted_from 写明来源路径。
   - 每题填 gold_drafted_from（起草依据的文件路径），保证可追溯。

A3 起草 kb/eval/research-value/dataset/humanoid-table-tennis-control.yaml（~15 题，同规则）：
   - 这个 program active_unit_ids 为空，但 workflow 有 open-questions/evidence-requests/reporting-events（见其 workflow/*.yaml）。
   - **故意**放几道 F 轴题问它状态/下一步 + 几道 A 轴题问它「HITTER 用什么 reward」这类——预期系统因无挂载单元而答不出。这些题的 gold 要如实写「KB 中无支撑数据，正确行为=返回无数据而非编造」，用于测幻觉（护栏 3）。

============================================================
B. Tier-1 harness（脚本可判，本次核心交付）
============================================================
B1 建 .agents/skills/skill-evolution-advisor/scripts/eval_research_value.py（归属见方向文档 §7.6：先挂 skill-evolution-advisor，别新建 skill）。
   - bootstrap/argparse/root 解析照抄 learnings.py。
   - flags：--program <id>（可选，默认全部）、--tier1（本次只实现 tier1）、--json、--root。
   - 对每题（仅 tier==1 且 auto_gradeable 的 gold_facts / 及所有题的 expected_units 检索分）：
     a) **检索召回@k**：用 question 调 rank_records（复用 retrieval.py，别重写），看 expected_units 落进 top-5 / top-10 的比例。
     b) **接地率 grounding**：对每条 gold_facts，去它 source_unit_id 的 note.md + parse-cache.yaml 里做字符串/模糊匹配（可复用 retrieval 的 tokenize；模糊=关键词子集命中），命中记 grounded。这是审查 P0「证据绑定」的直接度量：gold fact 连在自己 unit 里都查不到=提取没做到。
     c) **来源分布**：命中的 fact，其 note.md 是否含「REWRITTEN」标记 → 分「手工重写 note」vs「脚本产物/无标记」两桶计数。
     d) **空-program 对照**：单独统计 humanoid program 的检索召回（预期低/空）。
   - 只读：绝不 write_record / 改 state；唯一写入是 B2 的报告文件。

B1b **门控完整性检查（H1，实证新增，纯扫盘不问答）**：加一个子命令或 --gate-integrity 段：扫 KB 全部 confirmation_status==confirmed 的 unit，统计「已确认但核心内容为空」的数量（paper：payload.core_content 的 8 字段全空 / note 正文只剩模板占位如「方法机制：」「可引用表述：」）。输出「confirmed 总数 / 其中空心的数量 / 空心率」。这是审查最硬的发现（实测空 note 能盖成 confirmed/fact），必须量。只读。

B2 输出报告 kb/eval/research-value/reports/<UTC>-tier1.md：
   - 报告头：跑的时间(UTC)、KB 锚点（git checkpoint 若有 / unit 总数 / confirmed 数）、题目总数、**PDF backend 可用性**（读 kb doctor 或直接探测 managed venv 里有无 pypdf/PyMuPDF——接地率只有在 backend 可用时才可比）。
   - Tier-1 指标：召回@5、@10；接地率（grounded gold_facts / 总）；来源分布（手工 REWRITTEN note vs 脚本产物贡献占比）；humanoid 空-program 对照结果；**H1 门控空心率**。
   - 逐轴小结 + 尾部：一句话结论 + Top-3 最弱轴。
   - --json 时同时吐结构化结果到 stdout（供后续 diff/CI）。

B3 Codex 跑一次真实基线：`python3 .agents/skills/skill-evolution-advisor/scripts/eval_research_value.py --tier1`，把生成的报告文件一并提交，并在 commit message / 交付说明里贴出关键数字（召回、接地率、来源分布、humanoid 对照）。这份数字就是审查要的「离想要的样子有多远」的第一个坐标。

============================================================
C. Tier-2（本次只出规格 + 示范，不全量自动化）
============================================================
C1 kb/eval/research-value/TIER2_SPEC.md：
   - 写清 Tier-2 流程：answer agent（只用 KB 答，禁外部知识）→ grader agent（按 gold_rubric 每点 0/1/2）→ 汇总百分比 + 标注每答案是否引用 KB 证据。
   - 附 answer prompt 模板 + grader prompt 模板（含护栏：用了 KB 无据的事实判 0；无数据题编答案判 0）。
C2 挑 3 道 Tier-2 题（不同轴）做**手工示范**：写出 agent 若只用 KB 会给的答案 + 按 rubric 的打分，放进 TIER2_SPEC.md 附录，证明 rubric 可操作。不接 LLM 调用，不做全量。

============================================================
D. 文档接线
============================================================
D1 .agents/skills/skill-evolution-advisor/SKILL.md 加一节「研究价值验收（eval_research_value.py）」：说明它是只读质量度量，怎么跑，产出在 kb/eval/research-value/reports/。措辞如实（Tier-1 已自动化；Tier-2 是规格+人工示范）。
D2 temp/BACKLOG.md 顶部那条 FIRST_PRINCIPLES 指针下补一行：G5 Tier-1 已落地 + 首份基线报告路径 + 关键数字。

============================================================
验证（改完自测，全绿再 commit）——逐条给实际输出
============================================================
1. python -m compileall .agents/skills .agents/lib 通过；eval_research_value.py --help 通过。
2. 现有全量测试仍绿（本次是纯新增，不应动到既有测试；若新增 harness 的 smoke 测试，放进 .agents/lib/research/tests 或就近，只测 harness 不崩+报告有预期字段）。
3. 数据集：两个 yaml 用 load_yaml 能解析；每题字段齐全（id/program_id/axis/tier/question/expected_units 必填；tier1 有 gold_facts、tier2 有 gold_rubric）；综合题 gold_status 均为 pending_user_confirmation（grep 验证不自签）。
4. B3 基线报告真实生成且含全部指标段；贴出召回@5/@10、接地率、来源分布、humanoid 对照四组数字。
5. 只读验证：跑 harness 前后 `git status` 显示除 kb/eval/research-value/reports/ 外无任何 kb/ 改动（unit record / state 零 diff）。
6. 红线未动：confirmation gate / validate_write / retrieval.py / analyzer 脚本零 diff（git diff 确认）。

【逐项 commit，不 push】。交付时附：两个数据集题量分布（每轴几题）、基线报告四组数字、以及一句你自己的判断——「从这份数字看，系统当前最弱的是哪一轴，为什么」。

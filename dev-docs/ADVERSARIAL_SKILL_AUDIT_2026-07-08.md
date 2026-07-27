# 对抗性审查：research skills 是否支撑真实科研工作流

日期：2026-07-08  
范围：`.agents/skills/*/SKILL.md`、主要 `scripts/*.py`、`.agents/lib/research/*`、`kb/config/*`、现有 `kb/` 样例产物与 `temp/BLUEPRINT_AUDIT.md`  
约束：本审查不使用 `skill-evolution-advisor` 作为工作流，也不写入 learning / defect memory。

## 0. 总结论

这套 skills 的底层方向是对的：它已经把科研资产从聊天里拉回到 `kb/`，建立了 unit、program、config、confirmation gate、candidate pool、reporting event 这些长期可维护的骨架。作为“科研操作系统的文件协议 + CLI 雏形”，它有可继续演化的地基。

但从你描述的目标反推，它现在最致命的问题不是“skill 数量不够”，而是核心认知能力仍停留在索引级、模板级、启发式级。它能把论文、repo、blog 放进统一目录，也能生成 note scaffold 和 pending 状态；但它还不能稳定做到“读懂材料、抽取核心概念、给出有证据的趋势判断、基于知识库严肃讨论 idea、把 idea 落成可执行方法和实验闭环”。换句话说：仓库化能力强于理解能力，治理词汇强于证据绑定，流程分层强于端到端闭环。

最优先的改造方向应当是：少加新 skill，多补一条 evidence-grounded research spine。每一个“AI 判断”都要能追到 paper 页码 / paragraph / repo file line / experiment artifact；每一个 program 输出都要进入 reporting event；每一个用户常问问题都要先构造 evidence pack，再讨论。

## 1. 第一性原理评估框架

如果目标是覆盖你的真实科研流，而不是做一堆漂亮命令，系统必须满足十条底层原则：

1. Source preservation：原始材料可追溯、不可变、可复用。
2. Evidence extraction：论文、blog、repo 被解析成可引用证据片段，而不是只生成摘要。
3. Claim grounding：任何核心概念、判断、趋势、idea 评价都能反查证据。
4. Retrieval precision：检索返回“答案相关片段 + unit”，而不是只返回标题列表。
5. Synthesis discipline：综述必须区分 observed facts、inferred trends、evaluation，并显式列证据集。
6. Research state continuity：材料、idea、method、experiment、report 之间自动串联。
7. Human governance：AI 判断默认 pending，确认必须有 human identity 和 evidence，且覆盖子文档。
8. Actionability：方法设计和实验计划必须能变成配置、命令、指标和 artifact contract。
9. Reporting readiness：周报/PPT/论文大纲来自平时积累的 event + evidence，而不是最后事件 dump。
10. Personal control：用户能配置自动化边界、详略、术语、资源约束，并且配置真的被代码消费。

## 2. 目前真正做得好的地方

### 2.1 durable artifact 地基是成立的

`kb/units/*/<id>/record.yaml`、`kb/programs/<program-id>/workflow/*`、`kb/config/*`、`kb/synthesis/*`、`kb/user/*` 的分层符合长期科研资产管理。`SCHEMAS.md` 也把 unit record、experiment sidecar、program files 和 config files 统一到一套协议里。

价值：后续 AI 不必反复从 chat 里找上下文，能基于文件继续工作。

### 2.2 source intake 的轻量优先方向是对的

`source-intake` 已经覆盖 staging、dedup、raw backup、compact id、paper 自动 quick-screen、runtime preferences 等关键动作。它符合“先低成本入库，再决定是否深读”的原则。

证据：`.agents/skills/source-intake/scripts/intake.py:238-324`。

### 2.3 confirmation vocabulary 已经有雏形

`information_types`、`confirmation_status`、`needs_human_confirmation`、`confirmation.by/evidence` 等字段是很重要的信任基础。`require_confirmation_provenance()` 已经能阻止没有人名或 evidence 的人工确认。

证据：`.agents/lib/research/core.py:1470-1528`。

### 2.4 program / experiment / report 的概念边界是对的

`research-orchestrator` 管 program workflow，`experiment-workbench` 把 run-log / diagnoses / follow-ups 分开，`report-author` 从 reporting-events 生成材料，这个分工方向正确。

价值：这是以后把实验失败分析、阶段总结、周报自动化做好的前提。

## 3. 高危问题

### P0. 核心分析质量大量停在模板和启发式

这直接击中你的核心目标：“自动提取核心概念、辅助论文阅读、理清发展趋势、发掘 idea”。

具体表现：

- paper quick-screen 用关键词命中数评估 result / experiment / novelty / relevance，没有真正理解贡献、实验设置、消融和结论强度。证据：`.agents/skills/paper-analyst/scripts/paper.py:240-324`。
- paper full note 主要是模板填充，draft 也主要来自 quick-screen 和 source preview，不能保证 motivation、method、ablation、insight 被实质抽取。证据：`.agents/skills/paper-analyst/scripts/paper.py:339-360`、`:691-718`。
- repo capability map 主要基于 README 摘录、目录名、入口文件启发式，不能回答“某个 loss 在哪里”“训练 pipeline 怎么跑”“哪些模块能改”。证据：`.agents/skills/repo-analyst/scripts/repo.py:98-204`。
- blog analyzer 目前几乎是占位符，`main_value`、`key_points` 都是“待确认”。证据：`.agents/skills/blog-analyst/scripts/blog.py:32-44`。
- literature synthesizer 只是筛 record、数 topics/tags/pools，然后输出索引级观察，不能真正做方法谱系、趋势、gap、争议分析。证据：`.agents/skills/literature-synthesizer/scripts/synthesize.py:28-139`。
- report-author 只是 event line dump，不满足它自己 SKILL.md 里“self-contained submission-ready”的契约。证据：`.agents/skills/report-author/scripts/report.py:51-104`。

结论：当前系统像“研究资料管理器”，还不像“研究分析助手”。如果继续在这个层级上加 skill，只会增加路由复杂度，不会提升科研价值。

### P0. 证据没有绑定到 claim 级别

目前 record 有 `information_types`，但没有“每条 claim 对应哪些 evidence spans”的模型。一个 note 里说“实验扎实”“值得读”“适合做 baseline”，通常只能追到整个 note 或 record，不能追到 PDF 页码、表格、段落、repo 文件行、run artifact。

后果：

- AI 可以说“有理有据”，但系统不能自动检查“据”是否存在。
- idea 讨论无法可靠引用知识库，容易退化成普通聊天。
- 周报和论文大纲无法从 claims 自动组装。
- confirmation 只能确认整条 unit，不适合确认单条判断。

建议新增最小 evidence schema：

```yaml
claims:
- id: claim-001
  text: ""
  claim_type: fact|inference|evaluation|user_opinion
  confidence: 0.0
  confirmation_status: pending_user_confirmation
  evidence_refs:
  - source_unit_id: p-...
    artifact: kb/units/papers/.../parse-cache.yaml
    locator: page=3 section=method paragraph=2
    quote_or_summary: ""
```

这比继续扩展 note 模板更重要。

### P0. 检索能力不足以支撑“快速找关键信息、代码或论文”

当前检索是轻量 token substring ranking，字段包括 title/summary/tags/topics/payload/markdown。它没有 BM25、没有 passage-level hit、没有语义检索、没有中文分词、没有代码符号索引。

证据：`.agents/lib/research/retrieval.py:10-99`。实际 `kb find physics aware z space` 会返回大量 pending unit 和重复 “screen” next command，很难直接回答问题。

后果：

- “这篇论文的 ablation 结论是什么”不能直接定位页码或表格。
- “OpenVLA 训练入口在哪里”不能定位 repo file line。
- “找支持我 idea 的反例”无法做高召回检索。
- 中文查询对英文技术资产依赖偶然 token overlap。

需要把检索从 unit-level list 升级为 evidence retrieval：

- SQLite FTS/BM25 存 `title/abstract/notes/parse-cache/repo-files`。
- passage index 返回 top passages，而不只是 top units。
- repo 建 file/function/class/config key index。
- 查询输出必须包含 `why matched`、evidence locator、可打开 artifact。

### P0. 端到端 research spine 仍断裂

蓝图审查后 `kb status` 已变好，`autonomy.auto_execute_scope` 也已经外化；但从材料到报告的主线还没有真正闭环。

断点：

- analysis / survey / idea 上半场大多不进入 program `reporting-events.yaml`，报告主要看到 method / experiment 下半场。
- `idea.py select` 不接 `--program-id`，不会自动写 program decision-log / reporting-event / state。证据：`.agents/skills/idea-workbench/scripts/idea.py:508-522`。
- `method.py design` 会直接写 program state，而不是完全通过 orchestrator 的 state 写入和 lock 机制，且生成的设计仍是通用矩阵。证据：`.agents/skills/method-designer/scripts/method.py:307-349`。
- `kb next` 仍主要是 blocking evidence / open question / pending unit 排序，缺少“你现在处在科研主线第几步”的 journey 视图。证据：`.agents/skills/research-orchestrator/scripts/orchestrate.py:568-620`。
- 当前 `kb.py lint` 实测失败，提示多个 paper 的 program 反向 active link 缺失，说明 integrity 仍会漂移。

修复方向：

- 所有 unit 级重要进展都 emit reporting-event：screened, note-completed, repo-mapped, survey-created, idea-reviewed, idea-selected。
- idea selection 必须支持 `--program-id`，并写 decision-log。
- program state 增加结构化 `journey_stage`，不要只靠自由文本 `stage`。
- navigator/current-state 直接显示每个 program 的主线断点和下一步。

### P1. confirmation gate 仍然太粗、太软、太容易产生错觉

改进已经有：确认需要 evidence，review 结尾会提示非 unit pending 不在收件箱。但问题仍在：

- `validate_write()` 默认非 strict，只 warning。证据：`.agents/lib/research/core.py:1586-1635`。
- `confirm_unit()` 会把 record `information_types` 改成 `["fact"]`，但它并不真的把 note 里所有 AI judgement 变成事实。证据：`.agents/lib/research/core.py:1545-1575`。
- experiment diagnosis 子项确认状态不会随 unit confirm 同步更新。证据：`.agents/skills/experiment-workbench/scripts/experiment.py:349-417`。
- review queue 主要扫 unit record，子文档 pending 仍不在主收件箱。证据：`.agents/skills/knowledge-base-manager/scripts/kb.py:97-145`。

建议：

- 默认 strict on，或 `kb init` 默认 strict on 可选择宽松。
- `confirm_unit()` 不应简单把整条 record 变 fact，而应区分 source facts 与 AI claims。
- confirmation queue 聚合 unit record、claims、diagnoses、decision-log、reporting-events。
- confirmation 应支持按 claim / diagnosis item / decision item 细粒度确认。

### P1. repo 分析不足以服务代码复用和方法落地

你需要“检索关键信息、代码或者论文、落实 idea、展开方法构思”。当前 repo skill 还不能胜任代码级复用判断。

缺口：

- 无 symbol/function/class index。
- 无 config graph。
- 无训练/eval command verification。
- 无 dependency/runtime/env summary。
- 无 “where to modify” 文件行级定位。
- 无测试/复现实验状态。

最小可用目标应该是：问“这个 repo 的 policy loss 在哪里实现，如何接我的 latent z”，系统能返回文件、行号、函数、配置 key、风险。

### P1. experiment loop 是记录器，不是验证器

`experiment-workbench` 把 run-log、diagnoses、follow-ups 拆开是对的，但现在还缺真正实验系统所需的校验能力：

- metrics 是字符串 dict，没有类型、单位、方向、baseline 对齐。
- artifact 只记录路径，不验证文件存在、日志可读、指标可复算。
- diagnosis 是人工/AI 填参式，不会从 run-log 做趋势比较。
- method matrix 和 experiment plan 之间没有自动生成 run grid 或 config patch。

证据：`.agents/skills/experiment-workbench/scripts/experiment.py:224-417`。

建议引入 `metric_schema.yaml`、`artifact_manifest.yaml`、`run_comparison.md`，并让 diagnose 先读取最近 N 次 run 和 baseline。

### P1. reporting contract 与实现不一致

`report-author/SKILL.md` 要求 weekly report self-contained、面向导师、不是 event dump。但 `report.py` 当前输出基本是 event line、artifact pointer、tag list。

后果：周报仍需要 AI 临时重写，不能说“平时积累自动汇总”已经成立。

建议：

- `report.py weekly` 只做 evidence pack 和 outline，不要假装 final。
- 增加 `report.py draft-weekly`：读取 event artifacts，抽取 claims/evidence，按固定周报结构生成完整中文稿。
- 如果缺 event 或 evidence，报告中显式列 missing inputs，而不是空泛总结。

### P1. 个性化只完成了第一步

已有进展：`autonomy.auto_execute_scope` 已进入 runtime preferences，并由 orchestrator 执行阀门读取。证据：`.agents/lib/research/core.py:378-453`、`.agents/skills/research-orchestrator/scripts/orchestrate.py:363-398`。

仍缺：

- `default_mode`、`stop_before`、`proactivity`、`by_stage`、`by_kind`。
- `kb init` 没问 autonomy。
- `config guide --focus autonomy` 不存在，当前 guide 只有 `paper-intake`。证据：`.agents/skills/research-config-manager/scripts/config.py:150-185`、`:272-278`。
- `personalization.reporting_style / term_style / resources` 很少被下游实际消费。

这意味着用户仍难以自然地表达“论文你可以多主动，实验结论必须问我；周报要简洁但方法部分详细”。

### P2. taxonomy / pool 正在变成噪声池

当前 taxonomy 和 candidate pools 已经很大，且有不少 tag 是标题碎片或 URL-like slug。长期看，这会削弱检索和综述。

症状：

- `legacy-library-papers` tag 过长且混杂 title fragments。
- `current-state` confirmed highlights 为空，pending item 很多。
- pool membership 很容易成为“历史堆积”，缺少 decay、priority、readiness。

建议：

- 增加 `quality_score`、`readiness`、`last_used_at`、`why_in_pool`。
- pool review 不只列成员，还要清理 stale / duplicate / low-value items。
- taxonomy tag 分三类：domain tags、method tags、source-derived noisy tags，避免混在一起。

## 4. 你真正需要的下一代架构切入点

### 4.1 建立 evidence pack 作为所有讨论入口

凡是用户问：

- “帮我讨论这个 idea”
- “这个方向趋势是什么”
- “这篇论文核心是什么”
- “这个 repo 能不能用”
- “帮我写周报”

系统第一步都应该生成 evidence pack：

```yaml
question: ""
selected_units: []
evidence_spans:
- unit_id: ""
  artifact: ""
  locator: ""
  text_or_summary: ""
  relevance: ""
known_gaps: []
allowed_inferences: []
```

然后再进入讨论、综述、idea 或报告。这样才能保证“根据知识库内容讨论，有理有据”。

### 4.2 把 analyzer 从模板升级为 extractor

Paper extractor 最小规格：

- metadata：title/authors/venue/year/arxiv/doi。
- problem/motivation。
- method components。
- training/data/eval setup。
- benchmarks/metrics。
- ablations and what each proves。
- limitations/failure cases。
- reusable insights for current programs。
- evidence refs for every bullet。

Repo extractor 最小规格：

- install/env。
- train/eval/infer commands。
- config keys。
- data interfaces。
- core modules/functions/classes。
- losses / model / policy / dataset / env wrappers。
- “where to modify for idea X” with file lines。

Blog extractor 最小规格：

- claims。
- source credibility。
- cited sources。
- reusable explanation paragraphs。
- what is opinion vs fact。

### 4.3 把 program 改成状态机，不只是一组文件

建议主线状态：

1. intake
2. screening
3. deep-reading
4. synthesis
5. idea-candidates
6. idea-selected
7. method-designed
8. experiment-planned
9. experiment-running
10. diagnosis-pending
11. conclusion-ratification
12. report-ready

`kb next` 和 `kb status` 应该基于这个状态机推断断点，而不是只按 open question 和 evidence request 排序。

### 4.4 报告系统以 claims/events/evidence 三元组为输入

报告不是从 event title 拼出来的，而是从：

- 本周 confirmed facts
- 本周 pending but useful AI inferences
- 实验指标变化
- 决策和 open questions
- 下周计划

组合而成。`reporting-events` 仍有用，但不应是唯一输入。

## 5. 优先级路线图

### 第一批：修信任和检索地基

1. 默认 strict gate 或 `kb init` 默认 strict。
2. review queue 聚合非 unit pending。
3. 修当前 `kb.py lint` 报出的 program/unit 反链问题。
4. 新增 claim/evidence schema，先用于 paper note 和 experiment diagnosis。
5. 升级 `kb find` 为 passage-level 输出，至少返回 artifact + locator + snippet。

验收标准：

- AI 不能把 inference record 直接写成 confirmed。
- `kb review` 能看到 experiment diagnosis 子项。
- 查询一个概念返回相关段落，而不是只返回几十条 unit。

### 第二批：把三个 analyzer 做实

1. paper note 不允许只生成空 scaffold，必须填充 method / experiment / limitation / insight，并带 evidence refs。
2. repo analyzer 建立 code index，输出 file/function/config key 级 reuse map。
3. blog analyzer 真读取文本，输出 claim/credibility/cited-source。
4. literature synthesizer 读取 evidence spans，生成真正 method taxonomy 和 trend/gap。

验收标准：

- 给一篇新 paper，系统能回答 10 个事实问题并指向页码或 section。
- 给一个 repo，系统能回答训练入口、关键 loss、配置文件、修改点。
- 综述不再只是 top tags，而是能按方法类别和证据列出差异。

### 第三批：补 research spine

1. `idea select --program-id` 写 decision-log、state、reporting-event。
2. analysis/survey/idea/repo/paper 重要进展全部 emit reporting-event。
3. `kb next` 基于 journey stage 给主线建议。
4. report-author 从 events + claims + artifacts 生成 self-contained 周报。
5. discussion-archivist 接 evidence pack，把重要技术讨论自动落盘为 program discussion。

验收标准：

- 从“加一篇论文”到“写周报”不需要人工手动穿线。
- 当前 program 页面能显示“现在在哪一步，卡在哪里，下一步是什么”。
- idea 讨论可以引用 KB 证据并保存为可复用讨论记录。

### 第四批：补个性化和资源现实性

1. runtime preferences 增加 `autonomy.default_mode/stop_before/proactivity/by_stage/by_kind`。
2. `kb init` 增加 autonomy 和资源画像问题。
3. method-designer 读取 user resources，输出 realistic compute budget。
4. reporting_style / term_style 真接入 report-author 和 human-facing markdown。

验收标准：

- 用户能配置“paper 自动深读，repo 只扫结构，实验结论必须问我”。
- 方法设计会因为 GPU/机器人/数据资源不同而改变实验矩阵。
- 周报风格能稳定复用用户偏好。

## 6. 不建议优先做的事

- 不建议继续增加新 skill 名称。现有 owner 已经够多，问题是 owner 内部能力太薄。
- 不建议把更多规则只写进 SKILL.md。凡是影响行为边界、确认门控、检索、报告质量的规则，都应进入脚本和测试。
- 不建议先美化 browser/workbench。可视化有用，但当前瓶颈是 evidence quality。
- 不建议让 `report-author` 继续输出看起来像 final 的 event dump。宁可叫 draft/index，也不要让用户误以为它已经是导师可读周报。

## 7. 最短的高杠杆改造提案

如果只做一个月，我建议按这个顺序：

1. Claim/evidence schema + paper note extractor v1。
2. Passage-level `kb find`。
3. Full pending review queue。
4. Idea select program integration。
5. Report-author 从 event dump 升级为 evidence-based weekly draft。

这五件事会把系统从“能存资料”推进到“能基于资料做可信科研协作”。其它优化都可以排后。

## 8. 一句话判断

这套 skills 的系统观是对的，文件协议也已经有雏形；但当前最需要的不是更多自动化，而是更硬的证据层、更实的 analyzer、更连续的 program spine。先让每个判断都能追溯到证据，再谈自动发掘 idea 和自动写报告。

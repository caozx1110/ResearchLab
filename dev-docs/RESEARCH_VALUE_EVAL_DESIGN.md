# 研究价值验收基准（G5）设计 / 方向文档

日期：2026-07-08
来源：`temp/FIRST_PRINCIPLES_AUDIT_2026-07-08.md` 的高杠杆 1（G5：先立一把尺子）。
分工：本文件是**方向设计**（我定）。具体 harness 代码 + 全量样题 + gold answer + 跑测 + 报告 → Codex（见 `temp/codex_prompt_research_value_eval.md`）。

---

## 1. 目的与北极星

**北极星**：把「这套系统离我想要的科研合作者还有多远」从形容词变成**可复跑的数字**。

一句话定义：给两个真实 program 各出一批「我本来就会问」的问题，量出系统**能不能有据地答**，并且每次改动后能**重跑对比**，判断是进步还是自嗨。

**不是**什么：不是单元测试（那测触发/schema），不是 QA 玩具。它测的是**研究价值**——检索准不准、提取全不全、能不能跨单元综合、能不能发现 gap，以及**答案是否真能追到证据**。

---

## 2. 三个关键设计决策（方向层，Codex 不要改）

### 决策 A：测「端到端系统」，但要标注答案来源
系统的「被测对象」是**agent 用 skills + KB 回答**，不是一个可调用函数。所以：
- 答案由 agent **只用 KB**（kb find / 读 note / parse-cache）产生，禁止用 PDF 全文或外部知识。
- grader 必须记录**答案来自哪个 KB artifact**，以及那个 artifact 是**脚本自动生成**还是**agent 手工重写**（note 头部有 `审查状态：REWRITTEN` 标记可判）。
- **为什么**：审查发现手工重写的 note 很好、脚本产物是模板。若不标来源，benchmark 会因手工好 note 拿高分，**掩盖自动化的真实短板**。标了来源，一份报告同时回答两件事：①系统能否答 ②答案是否依赖自动化产不出的内容。

### 决策 B：双层度量（Tier-1 脚本 / Tier-2 agent）
- **Tier-1（可脚本、廉价、可回归、CI 友好）**：检索 + 接地检查。每题已知答案在 unit U、page P。脚本查：`kb find <关键词>` 是否把 U 排进 top-k？U 的 note/parse-cache 是否真含 gold fact？→ 直接量审查点名的两层（检索精度、提取覆盖），纯脚本、可反复跑。
- **Tier-2（agent 评分、周期性）**：完整答案质量。agent 从 KB 答，另一个 grader agent 按 rubric 打分。费 token，跑得少，但测的是真正的「研究合作者」能力。
- **为什么**：honors 审查里「G5 近零工程」——Tier-1 先给出即时数字；Tier-2 建向真正的价值度量。MVP = Tier-1 + 数据集（Tier-2 复用同一数据集）。

### 决策 C：gold answer 用系统自己的确认纪律
gold answer 由 agent 从 PDF 起草 → 默认 `pending_user_confirmation` → 用户（领域专家）确认后才算「金标」。
- benchmark 显式分两类：**auto-gradeable**（Tier-1 事实型，客观可查）与 **needs-expert-review**（Tier-2 综合型，需专家确认 gold）。
- **为什么**：领域太专（physics-aware FB / PULSE / BFM-Zero），AI 起草的 gold 未必对；用系统自己的 pending→confirm 纪律，既诚实又 on-brand。

---

## 3. 能力轴（7 轴，映射 what_i_need.md）

每轴对应需求文档的一类真实用途。样题必须均匀覆盖 7 轴。

| 轴 | 名称 | 测什么 | 映射 what_i_need | 主要考验的 skill |
|---|---|---|---|---|
| A | 单篇事实检索 | 「X 用了什么 reward / 多少 DoF / 什么 baseline」 | §3.2 论文笔记、§15.1 | 提取 + 检索 |
| B | 跨单元对比 | 「X 的 z-space 和 Y 的 latent 关键区别」 | §5 综述、§6.3 创新性 | 综合 |
| C | 脉络/趋势 | 「A→B→C 这条线怎么发展的 / 趋势是什么」 | §5 研究脉络/趋势 | literature-synthesizer |
| D | gap/空白 | 「这个方向还没人做的是什么」 | §5 gap、§6 idea 形成 | idea-grounding |
| E | 复用/代码 | 「repo Y 里 loss X 在哪实现 / 训练入口」 | §4 仓库能力 | repo-analyst |
| F | program 状态 | 「我 physics-aware program 现在卡在哪 / 下一步」 | §8 周报、§12.3 状态追踪 | orchestrator |
| G | idea 讨论（有据） | 「我这个 idea 相对 KB 新在哪 / 有什么反例」 | §6 idea 讨论 | idea-workbench + 讨论 |

---

## 3.5 实证校正（2026-07-09，跑完当前版本入库后必读）

用户质疑「kb/ 是旧版遗留」→ 已在干净工作区用**当前版本**入库 AR-FB 一篇验证（原隔离工作区已清理，报告归档于 `dev-docs/reviews/legacy-acceptance/ar-fb-ingest-acceptance-2026-07-08.md`）。三个发现直接改 G5 设计：

1. **gold answer 不能依赖 KB 现有 note**。当前版本产的 `note.md` 是空模板（`core_content` 8 字段全空，唯一有内容的节是 PDF 首页字节原样粘贴），旧 kb/ 里的好 note 是人手写的（头标 `REWRITTEN`）。→ **gold 一律从 PDF 原文起草，绝不从 note 抄**（Codex handoff 已如此要求，此处强化：把「note 可作起草依据」从选项里删掉，只保留 PDF/parse-cache 原文）。

2. **要专门测「空心确认门」**。实测把 core_content 全空的 note promote 成了 `confirmed/fact`。→ G5 **新增一个 meta 检查**（见 §5 新指标 H1）：扫 KB 里 `confirmation_status: confirmed` 的 unit，检查其 `core_content` / note 正文是否真的非空。这不是问答题，是**门控完整性度量**，但正是审查最硬的发现，必须量。

3. **默认新用户环境无 PDF backend，静默降级**。实测默认 add → `parse-cache.chunks: []`（bare except 吞异常）、screen 全 weak、note 是「待结合摘要…补全」占位；装了 pypdf/PyMuPDF 重跑才有 16 段原文 + 14 图。→ G5 harness **报告头必须记录 PDF backend 是否可用**，否则接地率会因环境差异不可比。且这本身是 G7 之外的**冷启动缺口**，值得单列。

---

## 4. 数据集 schema（Codex 落到 `kb/eval/research-value/`）

一个 benchmark = 一批 question 条目 + 一份 program 上下文。每题：

```yaml
- id: q-<program-slug>-NNN
  program_id: physics-aware-fb-z-space | humanoid-table-tennis-control
  axis: A|B|C|D|E|F|G            # §3 能力轴
  tier: 1 | 2                    # 1=脚本可判, 2=需 agent/专家
  question: ""                   # 用户口吻的真实问题
  # --- gold（Tier-1 客观 / Tier-2 rubric）---
  gold_facts:                    # Tier-1：必须命中的原子事实
    - text: ""
      source_unit_id: p-...      # 答案所在 unit
      locator: ""                # page=N / section / repo file:line
      auto_gradeable: true
  gold_rubric:                   # Tier-2：评分要点（每点 0/1/2）
    - ""
  expected_units:                # 检索应召回的 unit 集合（Tier-1 检索分）
    - p-...
  gold_status: pending_user_confirmation | confirmed   # 决策 C
  gold_drafted_from: ""          # 起草依据的 PDF/note 路径（可追溯）
  notes: ""
```

**MVP 规模**：每 program 每轴 2-3 题 = physics-aware ~18 题 + humanoid ~15 题 ≈ **33 题**。够暴露短板，又不至于 gold 起草拖垮。

---

## 5. 指标（跑一次输出什么）

Codex 的 harness 每次跑输出一份 `kb/eval/research-value/reports/<UTC>.md`，含：

**Tier-1（脚本，每次跑）**
- **检索召回@k**：`expected_units` 有多少落进 `kb find` top-k（k=5,10）。
- **接地率 grounding**：`gold_facts` 里有多少能在其 `source_unit_id` 的 note/parse-cache 里被字符串/模糊匹配到。**这一条直接量审查的 P0「证据没绑定到 claim」**——若 gold fact 连在自己 unit 里都查不到，说明提取没做到。
- **来源分布**（决策 A）：命中的 fact 有多少来自 `REWRITTEN` 手工 note vs 脚本产物。**这一条量「去掉手工重写后系统还剩多少能力」。**
- **空 program 对照**：humanoid（active_unit_ids=[]）应在 F 轴大面积失败——若没失败反而是 bug 信号。

**Tier-2（agent，周期跑）**
- 每题 agent 答案 + grader agent 按 `gold_rubric` 打分（0-2/点），输出百分比 + 逐题短评。
- 标注每个答案是否**引用了 KB 证据**（有据 vs 空谈）——直接量需求「有理有据」。

**H1 门控完整性（meta 检查，2026-07-09 实证新增，非问答）**
- 扫 KB 全部 `confirmation_status: confirmed` 的 unit，统计有多少「已确认但核心内容为空」（paper 看 `payload.core_content` 8 字段是否全空 / note 正文是否只剩模板占位）。
- **为什么**：实测已证明当前门控能把空 note 盖成 `confirmed/fact`。这条直接量「确认」这个状态到底值不值钱——是 G5 里唯一不靠问答、纯扫盘就能出的硬数字，也是审查假设 1 的铁证。
- 报告头附：PDF backend 是否可用（`kb doctor` 的 pdf 状态）+ managed venv 里有没有 pypdf/PyMuPDF。接地率必须在「backend 可用」前提下才可比。

**报告尾部**：一句话结论 + Top-3 最弱轴 + 与上次跑的 diff（若有）。

---

## 6. 方法论护栏（防止基准骗自己）

1. **禁用外部知识**：agent 答题只准用 KB。grader 检查答案里的事实是否都能追到 KB artifact；用了 PDF 全文/训练知识但 KB 里无据的，判 0。
2. **gold 不自签**：Tier-2 的 gold_rubric 与综合题 gold 默认 pending，走系统确认纪律，专家确认前不计入「正式分」，只出「预览分」。
3. **区分「系统没有」与「系统答错」**：F 轴对空 program 返回「无数据」是**正确行为**，不扣分；把无数据当有数据编答案才扣分（幻觉检测）。
4. **可复跑 + 版本锚**：报告头记录 KB 的 git checkpoint / unit 数 / confirmed 数，让两次跑可比。
5. **题目冻结**：样题一旦确认，不因系统答不上来就改题。改题要留痕（新增 `q-...-v2`，旧题保留）。

---

## 7. 交付物（Codex 产出，我验收）

1. `kb/eval/research-value/dataset/physics-aware-fb-z-space.yaml`（~18 题，gold 起草，标 pending）
2. `kb/eval/research-value/dataset/humanoid-table-tennis-control.yaml`（~15 题）
3. `.agents/skills/<eval-owner>/scripts/eval_research_value.py`：Tier-1 harness（检索召回 + 接地率 + 来源分布 + 空-program 对照），`--tier1`、`--program`、`--json`、`--root`。
4. `kb/eval/research-value/reports/<UTC>-tier1.md`：首次基线报告（Codex 跑一次，给真实数字）。
5. Tier-2：先只出**规格 + prompt 模板 + 3 道样题的手工示范**，不强制全量（省 token；数据集已复用）。
6. 归属决策：eval harness 该归到**新 skill `research-eval`** 还是挂 `skill-evolution-advisor`（已是 meta/质量域）——倾向后者，避免又+1 skill（呼应审查「别再加 skill 数量」）。**此点留给我拍板，Codex 先按「挂 skill-evolution-advisor 的 scripts/」实现，SKILL.md 加一节。**

---

## 8. 明确不做（scope 护栏）

- 不做语义/embedding 检索（审查已定：82 单元下 lexical 够；这里只**测量**检索好坏，不顺手重造检索）。
- 不改任何治理逻辑 / confirmation gate / analyzer 行为（这批只**加**一个只读 eval 层 + 数据集；不碰被测系统，否则测的是移动靶）。
- 不追求题量大而全，MVP 优先能跑出第一份数字。
- Tier-2 全量自动化留后续（先人工示范证明 rubric 可用）。

---

## 9. 验收标准（我判 Codex 交付合格）

- Tier-1 harness 能跑完 33 题不崩，输出结构化报告 + 真实数字。
- 报告能明确显示：①哪几轴最弱 ②接地率（多少 gold fact 在 KB 里查得到）③手工 note vs 脚本产物的贡献分布 ④humanoid 空 program 在 F 轴如预期失败。
- 数据集里所有综合题 gold 标 `pending_user_confirmation`（不自签）。
- 只读：跑 eval 不写任何 unit record、不动 program state（除写自己的 report 目录）。
- import 面兼容、`--help` 通过、纳入 pytest（至少 harness 的 smoke）。

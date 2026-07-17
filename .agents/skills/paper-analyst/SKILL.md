---
name: paper-analyst
description: 为 core paper unit 备料（解析源、产出待填结构）并校验 agent 填入的理解与证据，再过实质门确认。脚本不理解论文，理解由 runtime agent 填。
---

# Paper Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#evidence-claims` · `#confirmation-gate` · `#runtime`

当任务是在分析某个 paper knowledge unit（而不只是入库）时，使用这个 skill。

## 第一性原理（SSOT 原则1 / §3.2）

**理解来自 agent，脚本只做搬运 + 验证。** 脚本负责：解析源、产出「待填结构」、逐字校验 agent 填入的每条判断带合法 evidence、过实质门、落盘。脚本**绝不**产出「这篇论文说了什么 / 值不值得读 / novelty 强不强」这类判断——那是 runtime agent 的活。初筛与笔记都是**两阶段**：脚本 `prepare` 出待填骨架 → agent 在会话里填理解+挂证据 → 脚本 `verify` 校验后落盘。

## 负责范围

1. 从 `source-intake` 创建的 paper unit（已带 parse-cache）出发。
2. `screen --phase prepare`：从 parse-cache 抽初筛证据摘要（带 page/section locator），产出 `screening.yaml` 待填结构（`paper_type` / `worth_deep_reading` / `judgement_reason` / `relevance_to_current_research` / `claims` 留空待 agent 填）。`paper_type` 是 agent 判断，脚本不做关键词推断；`keyword_mentions` 仅作定位线索，**不是评分**。
3. `screen --phase verify`：校验 agent 填入的判断（含 `paper_type ∈ {method_system, benchmark, survey}`、`validate_claims` 结构 + `verify_claim_evidence` 逐字证据）后落盘；不合法则拒绝并指出问题。
4. `complete-note --phase prepare`：按 `quick_screen.paper_type` 产出对应的**五要素待填骨架**；缺失或未知类型默认 `method_system`，每要素留空、需 agent 填内容 + ≥1 条 `evidence_refs`。
5. `complete-note --phase verify`：逐要素校验（结构 + 逐字证据），全过才写 `note.md` + `core_content`（过 `has_substantive_content`，可被确认）；任一要素空/无据/造据则拒绝并点名。
6. `prewarm-cache` / `extract-figures` / `refresh-structure`：纯机械搬运（解析、裁图、结构提示）。
7. AI judgement 默认保持 `pending_user_confirmation`；确认走已有空心门（`confirm`）。

## 按论文类型的五要素契约（runtime agent 照此填）

- `method_system`：motivation / method / experiment / limitation / insight
- `benchmark`：motivation / task_design / metrics / coverage_limitation / insight
- `survey`：scope / taxonomy / trends / gaps / insight

若旧 record 没有 `quick_screen.paper_type`，按 `method_system` 处理，保持原五要素行为。类型分类来自 runtime agent 的初筛判断；脚本只提供槽位、校验枚举并选择结构。

每个 required element = 一条 judgement-class claim，**必须**带 ≥1 条 `evidence_refs`：

```yaml
elements:
  - element: motivation      # 必须属于该 paper_type 的 required_elements，五个全填
    claim_type: inference    # experiment/limitation 为 evaluation，其余 inference
    content: "agent 用自己的话写这一要素的理解"
    evidence_refs:
      - source_unit_id: p-...
        artifact: parse-cache.yaml
        locator: "page=3"          # PDF: page=N ; HTML: section 或 section:<anchor>（B4）
        quote: "短逐字片段"          # 脚本校验它逐字存在于 artifact（归一化空白后子串）
        summary: "可选一句转述"
```

落盘映射：

- `method_system`：motivation→`core_content.motivation`；method→`core_content.method`；experiment→`core_content.changes_and_effects`；limitation→`critique.weak_spots`；insight→`core_content.why_it_might_work`。
- `benchmark`：motivation→`core_content.motivation`；task_design→`core_content.method`；metrics / coverage_limitation→`core_content.changes_and_effects`；insight→`core_content.why_it_might_work`。
- `survey`：scope→`core_content.motivation`；taxonomy→`core_content.method`；trends / gaps→`core_content.changes_and_effects`；insight→`core_content.why_it_might_work`。

所选五要素同时渲染进 `note.md`；每种类型都写入 `core_content`，因此实质门仍按原规则工作。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py prewarm-cache --paper-id p-example-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-example-bf86ee46 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-example-bf86ee46 --phase verify
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py complete-note --paper-id p-example-bf86ee46 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py complete-note --paper-id p-example-bf86ee46 --phase verify --input note-fill.yaml
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py extract-figures --paper-id p-example-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py refresh-structure --paper-id p-example-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-example-bf86ee46 --confirmed-by research-lead --evidence kb/units/papers/p-example-bf86ee46/note.md
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py reject --paper-id p-example-bf86ee46
```

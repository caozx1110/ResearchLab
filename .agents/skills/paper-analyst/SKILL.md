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
2. `screen --phase prepare`：从 parse-cache 抽初筛证据摘要（带 page/section locator），产出 `screening.yaml` 待填结构（`worth_deep_reading` / `judgement_reason` / `relevance_to_current_research` / `claims` 留空待 agent 填）。`keyword_mentions` 仅作定位线索，**不是评分**。
3. `screen --phase verify`：校验 agent 填入的判断（`validate_claims` 结构 + `verify_claim_evidence` 逐字据）后落盘；不合法则拒绝并指出问题。
4. `complete-note --phase prepare`：产出**五要素待填骨架** motivation / method / experiment / limitation / insight，每要素留空、需 agent 填内容 + ≥1 条 `evidence_refs`。
5. `complete-note --phase verify`：逐要素校验（结构 + 逐字证据），全过才写 `note.md` + `core_content`（过 `has_substantive_content`，可被确认）；任一要素空/无据/造据则拒绝并点名。
6. `prewarm-cache` / `extract-figures` / `refresh-structure`：纯机械搬运（解析、裁图、结构提示）。
7. AI judgement 默认保持 `pending_user_confirmation`；确认走已有空心门（`confirm`）。

## 五要素填充契约（runtime agent 照此填）

每个 required element = 一条 judgement-class claim，**必须**带 ≥1 条 `evidence_refs`：

```yaml
elements:
  - element: motivation      # motivation|method|experiment|limitation|insight 五个全填
    claim_type: inference    # experiment/limitation 为 evaluation，其余 inference
    content: "agent 用自己的话写这一要素的理解"
    evidence_refs:
      - source_unit_id: p-...
        artifact: parse-cache.yaml
        locator: "page=3"          # PDF: page=N ; HTML: section 或 section:<anchor>（B4）
        quote: "短逐字片段"          # 脚本校验它逐字存在于 artifact（归一化空白后子串）
        summary: "可选一句转述"
```

落盘映射：motivation→`core_content.motivation`、method→`core_content.method`、experiment→`core_content.changes_and_effects`、insight→`core_content.why_it_might_work`、limitation→`critique.weak_spots`；五要素同时渲染进 `note.md`。

> 五要素针对方法/系统类论文。若遇纯 benchmark / survey 论文不完全适配，先停下与用户确认，勿硬套。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py prewarm-cache --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-openvla-bf86ee46 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-openvla-bf86ee46 --phase verify
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py complete-note --paper-id p-openvla-bf86ee46 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py complete-note --paper-id p-openvla-bf86ee46 --phase verify --input note-fill.yaml
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py extract-figures --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py refresh-structure --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-openvla-bf86ee46 --confirmed-by czx --evidence kb/units/papers/p-openvla-bf86ee46/note.md
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py reject --paper-id p-openvla-bf86ee46
```

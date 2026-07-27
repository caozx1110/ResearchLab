---
name: paper-analyst
description: 为 core paper unit 备料（解析源、产出待填结构）并校验 agent 填入的理解与证据，再过实质门确认。脚本不理解论文，理解由 runtime agent 填。
---

# Paper Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#evidence-claims` · `#confirmation-gate` · `#runtime`

当任务是在分析某个 paper knowledge unit（而不只是入库）时，使用这个 skill。

## 第一性原理（SSOT 原则1 / §3.2）

**理解来自 agent，脚本只做搬运 + 验证。** 脚本负责：解析源、产出「待填结构」、逐字校验 agent 填入的每条判断带合法 evidence、过实质门、落盘。脚本**绝不**产出「这篇论文说了什么 / 值不值得读 / novelty 强不强」这类判断——那是 runtime agent 的活。初筛与笔记都是**两阶段**：脚本 `prepare` 出待填骨架 → agent 在会话里填理解+挂证据 → 脚本 `verify` 校验后落盘。

`runtime.paper` / `runtime.pdf` 是 soft preference catalog：只有与 paper id、operation、phase/mode、source/basic-info canonical inputs 绑定且 current 的 effective selection 才可改变对应操作；无 receipt 使用 neutral defaults，禁止直读 runtime soft 字段。写入 record 的 preference binding 只含 selection/task/receipt digest；`runtime.autonomy.auto_execute_scope` 作为 hard governance fallback 仍直接执行，且不能关闭 evidence、confirmation、containment 或 recovery。

Quick screening 的 `institutions / backing_strength / result_strength / experiment_quality / reliability / novelty` 是 runtime Agent 填写的结构化判断。每项要么填 `assessed + rating + reason + claim_ids`，且 claim 必须挂逐字 evidence；要么填 `not_applicable + reason`。`institutions` 只记录论文披露的 affiliation，不评价声望；作者身份、机构声望、venue、citation count 等元数据一律不得作为任何强弱评级的启发式替代。

## 负责范围

1. 从 `source-intake` 创建的 paper unit（已带完整 `source/document.md` 阅读层和兼容 parse-cache）出发。Agent 先读 Markdown 形成整体理解；需要核验逐字引用与既有 locator 时读 parse-cache，转换降级或细节缺失时回退原 PDF/HTML。
2. `screen --phase prepare`：从 parse-cache 抽初筛证据摘要（带 page/section locator），产出 `screening.yaml` 待填结构（`paper_type` / `worth_deep_reading` / `judgement_reason` / `relevance_to_current_research` / `claims` 留空待 agent 填）。`paper_type` 是 agent 判断，脚本不做关键词推断；`keyword_mentions` 仅作定位线索，**不是评分**。
3. `screen --phase verify`：校验 agent 填入的判断（含 `paper_type ∈ {method_system, benchmark, survey}`、`validate_claims` 结构 + `verify_claim_evidence` 逐字证据）后落盘；不合法则拒绝并指出问题。
4. `complete-note --phase prepare`：新 intake 必须先有 evidence-verified screening，再按 `quick_screen.paper_type` 产出对应的**五要素待填骨架**；prepared/unverified screening 一律 fail-closed。已验证初筛仍无法分类，或旧单元已有 note 产物但没有类型时，才按 `method_system` 兼容；每要素留空、需 agent 填内容 + ≥1 条 `evidence_refs`。
5. `complete-note --phase verify`：逐要素校验（结构 + 逐字证据），全过才写 `note.md` + `core_content`（过 `has_substantive_content`，可被确认）；任一要素空/无据/造据则拒绝并点名。
6. `prewarm-cache` / `extract-figures` / `refresh-structure`：纯机械搬运（解析、裁图、结构提示）。
7. AI judgement 默认保持 `pending_user_confirmation`；确认走已有空心门（`confirm`）。

Markdown 阅读层中的图片只提供本地、可引用的源材料。脚本不得从图片文件名、alt text 或 OCR 片段自动生成论文判断；runtime agent 若使用图表内容，仍需在会话中实际阅读并挂可核验 evidence。

## 按论文类型的五要素契约（runtime agent 照此填）

- `method_system`：motivation / method / experiment / limitation / insight
- `benchmark`：motivation / task_design / metrics / coverage_limitation / insight
- `survey`：scope / taxonomy / trends / gaps / insight

若初筛已验证但无法归入三类，或旧 record 已有 note 产物但没有 `quick_screen.paper_type`，按 `method_system` 处理，保持原五要素行为；新单元不得借此兜底绕过初筛验证。类型分类来自 runtime agent 的初筛判断；脚本只提供槽位、校验枚举并选择结构。

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

## 启动澄清（Agent 用）

- 只做初筛还是直到完整笔记？默认初筛通过后按 paper_type 出五要素笔记。
- 侧重方法、实验还是局限？默认全面均衡。
- 深度：默认读 document.md 并用 parse-cache 核对引用；需图表细节再回 PDF。

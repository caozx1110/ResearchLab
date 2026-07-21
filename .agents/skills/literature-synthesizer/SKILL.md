---
name: literature-synthesizer
description: 负责跨 paper / repo / dataset / blog / idea 的 evidence-first survey、review 与 taxonomy 综合。
---

# Literature Synthesizer

当任务是在多个知识单元之间形成综述、趋势、taxonomy、topic map 或 pool review，而不是分析单个 source 时，使用这个 skill。

## 核心边界

- 理解来自 runtime agent；脚本只选择 metadata 候选、建立可填结构、验证 claim 与逐字 evidence、落盘已验证结果。
- 不从 topic、tag、pool 或 kind 计数自动生成结论，不写固定 Observed / Inferred / Suggested / OpenQuestions 文案，也不写固定 confidence。
- 不建立 semantic index。runtime agent 使用原生检索阅读单位产物并填写 scaffold。
- 每个正式 claim cell 都必须有 evidence_refs；taxonomy cell、comparison-matrix cell、trend、gap 还会检查其结构字段。每个 ref 都按自己的 source_unit_id 解析到对应 unit_dir，再做逐字核验。
- prepare 不产出正式 survey；只有 verify 全部通过后才写正式 YAML 与 summary.md。

## 两阶段流程

### 1. prepare

`survey prepare` 接收 field 或 query，以及可选 kind、topic、tag、pool 过滤；必须接收显式 as_of。review 与 taxonomy 使用同一 prepare 协议。

prepare 会：

1. 用 metadata 过滤选择候选 unit。
2. 把 unit id、kind、title 与 as_of 写入 kb_anchor。
3. 生成七段式 fillable scaffold、taxonomy grid frame 与 method × dimension comparison matrix frame。
4. 发布 required-cell、claim field 与 evidence_ref field 合同。
5. 保持所有 content 与 evidence_refs 为空，不替 runtime agent 写任何理解。

runtime agent 随后阅读 kb_anchor 中的 unit 产物，填写所有 required cell，并为 claim 添加逐字 evidence_refs。

### 2. verify

`survey verify` 读取 agent-filled scaffold。review 与 taxonomy 使用同一 verify 协议。

verify 会：

1. 检查七个 section 与 comparison matrix 的 required cells 是否存在且 content 非空。
2. 把 cell 转成 research.evidence claim，并运行 validate_claims。
3. 对每个 evidence_ref 读取其 source_unit_id，在 kb_anchor.units 中取得 kind，并只在该 unit_dir 内运行 verify_claim_evidence。
4. 对 trend 与 gap 检查其 as_of 与 kb_anchor.as_of 一致。
5. 任一结构、anchor、artifact、locator 或逐字 quote 校验失败即拒绝，且不写正式结果。
6. 全部通过后标记 observed / inferred，写入 `kb/synthesis/<slug>/<mode>.yaml` 与 `kb/synthesis/<slug>/summary.md`，并渲染 comparison matrix。

## 标准七段式骨架

1. `scope_positioning`：scope & positioning。
2. `background_terms`：background / terms。
3. `taxonomy`：核心 taxonomy grid，不是条目列表。
4. `cross_cutting`：datasets / benchmarks / metrics。
5. `trends`：带时间锚的 A → B → C 变化轨迹。
6. `gaps_challenges`：gaps / controversies / open challenges。
7. `conclusion`：由 agent 基于前述证据填写的结论。

## Scaffold Schema

```yaml
schema_version: 1
mode: survey|review|taxonomy
slug: <output-slug>
status: awaiting_agent_fill
filters:
  query: ""
  kind: ""
  topic: ""
  tag: ""
  pool: ""
kb_anchor:
  as_of: <caller-supplied timestamp>
  unit_ids: [p-..., r-...]
  units:
    - id: p-...
      kind: paper
      title: "..."
fill_contract:
  required_section_ids: [scope_positioning, background_terms, taxonomy, cross_cutting, trends, gaps_challenges, conclusion]
  required_claim_fields: [id, content, claim_type, evidence_refs]
  evidence_ref_fields: [source_unit_id, artifact, locator, quote]
  evidence_rule: every required claim cell needs one or more verbatim evidence_refs
sections:
  - id: taxonomy
    title: Taxonomy
    dimensions:
      - id: taxonomy-dimension-1
        label: ""
    cells:
      - id: taxonomy-cell-1
        row_label: ""
        column_label: ""
        content: ""
        claim_type: fact
        evidence_refs: []
  - id: trends
    title: Trends
    items:
      - id: trend-1
        trajectory: ""
        content: ""
        claim_type: inference
        evidence_refs: []
        as_of: <same as kb_anchor.as_of>
comparison_matrix:
  dimensions:
    - id: dimension-1
      label: ""
  methods:
    - id: method-1
      label: ""
      source_unit_ids: []
  cells:
    - id: matrix-cell-1
      method_id: method-1
      dimension_id: dimension-1
      content: ""
      claim_type: evaluation
      evidence_refs: []
```

普通 section 使用 `claims`，taxonomy 使用 `cells`，trend / gap 使用 `items`。所有 claim-like cell 共享以下语义：

- `content`：runtime agent 写入的判断文本；prepare 时必须为空。
- `claim_type`：`fact` / `evaluation` 记为 observed，`inference` 记为 inferred；保留原 epistemic 类型，不把 inference 降格成 fact。
- `evidence_refs`：research.evidence schema；每项必须含 source_unit_id、unit 内相对 artifact、locator、逐字 quote。
- `as_of`：trend 与 gap 必填，并必须等于 kb_anchor.as_of。

## 输出语义

- 正式 YAML 保留 sections、comparison_matrix、kb_anchor、claim_type、evidence_refs，并在每个 cell 上增加 `epistemic_status: observed|inferred`。
- summary.md 按七段式渲染 verified content，并将 comparison matrix 输出为 method × dimension 表格。
- metadata 只参与候选选择，不作为 survey conclusions。

---
name: literature-synthesizer
description: 负责跨 paper / repo / dataset / blog / idea 的 evidence-first survey、review 与 taxonomy 综合。
---

# Literature Synthesizer

开始 survey/review/taxonomy 前遵循 workspace 统一 task-scoped preference 合同：`literature-synthesizer + synthesize` 只接收 allowlist 中由 Agent 选中的 effective subset，并绑定 mode、selection filters、as_of 与 program ids 构成的 canonical task digest。未选中的软偏好不得静默改变 selection、taxonomy 或写作口径；无 receipt 时软行为中性，hard constraints 仍必须执行。

当任务是在多个知识单元之间形成综述、趋势、taxonomy、topic map 或 pool review，而不是分析单个 source 时，使用这个 skill。

## 核心边界

- 理解来自 runtime agent；脚本只选择 metadata 候选、建立可填结构、验证 claim 与逐字 evidence、落盘已验证结果。
- 不从 topic、tag、pool 或 kind 计数自动生成结论，不写固定 Observed / Inferred / Suggested / OpenQuestions 文案，也不写固定 confidence。
- 不建立 semantic index。runtime agent 使用原生检索阅读单位产物并填写 scaffold。
- 每个正式 claim cell 都必须有 evidence_refs；taxonomy cell、comparison-matrix cell、trend、gap 还会检查其结构字段。每个 ref 都按自己的 source_unit_id 解析到对应 unit_dir，再做逐字核验。
- prepare 只接受当前、已确认且 ConfirmationReceipt/evidence bytes 仍有效的输入 unit；筛选后为零时返回 evidence-gap + composite handoff，不写零材料 scaffold。
- prepare 不产出 survey；verify 全部通过后写 evidence-verified、`pending_user_confirmation` 的一等 survey JudgementArtifact。它进入统一 `kb review` 收件箱，经当前消息授权的 confirm/reject 闭环后，只有 current confirmed 版本可供正式报告消费。

## 两阶段流程

### 1. prepare

`survey prepare` 接收 field 或 query，以及可选 kind、topic、tag、pool 过滤；必须接收显式 as_of。review 与 taxonomy 使用同一 prepare 协议。

prepare 会：

1. 用 metadata 过滤选择候选 unit，再机械校验每个 unit 的 current ConfirmationReceipt 与 evidence bytes；脚本不判断论文是否语义相关。
2. 把 unit id、kind、title、规范化 record content digest、确认回执 digest 与 unit 内可引用 evidence artifact byte digests 写入 kb_anchor。
3. 生成七段式 fillable scaffold、taxonomy grid frame 与 method × dimension comparison matrix frame。
4. 发布 required-cell、claim field 与 evidence_ref field 合同。
5. 保持所有 content 与 evidence_refs 为空，不替 runtime agent 写任何理解。
6. 把 task digest、可选 selection binding 与 hard-value digests 写入 scaffold；receipt 不复制偏好正文。偏好 context digest 同时进入 survey content binding。

若第 1 步没有合格输入，prepare 返回结构化 evidence gap，并创建按请求 digest / revision 绑定的 durable composite state，handoff 到 `search → selection → source_intake → unit_analysis → synthesis → review_confirmation → report_consumption`；每阶段记录 inputs、outputs、blocker 与 resume action，更新使用 revision CAS，并作为 `kb next` 正式候选跨会话恢复。候选选择和结论仍由 runtime agent 完成。

evidence-gap 路由把同一 preference context 作为 composite search stage 的冻结 input；偏好或 hard constraint 变化会得到不同 request digest，不能静默续接旧 composite。

当本次综合属于一个或多个 program 时，Agent 在 prepare 时绑定 program id。该关联进入 survey content digest；确认后 owner 在同一原子 review 事务中为每个 program 写入带当前 ConfirmationReceipt binding 的 `survey-confirmed` reporting event，供 `report-author` 消费。没有 program 关联的 survey 仍可作为全局 synthesis judgement 使用。

runtime agent 随后阅读 kb_anchor 中的 unit 产物，填写所有 required cell，并为 claim 添加逐字 evidence_refs。

### 2. verify

`survey verify` 读取 agent-filled scaffold。review 与 taxonomy 使用同一 verify 协议。

verify 会：

1. 在 workspace transaction 内重新定位每个 canonical unit，并逐项核对 identity、record content、确认回执和 evidence bytes；任一变化或删除都要求重新 prepare。
2. 检查七个 section 与 comparison matrix 的 required cells 是否存在且 content 非空。
3. 把 cell 转成 research.evidence claim，并运行 validate_claims。
4. 对每个 evidence_ref 读取其 source_unit_id，在 kb_anchor.units 中取得 kind，并只在该 unit_dir 内运行 verify_claim_evidence；引用文件必须已存在于 prepare binding。
5. 重新加载并校验原 `synthesize` receipt、canonical task context 和 hard-value digests；wrong binding 或 stale catalog 要求重新 prepare，不得继续验证旧 scaffold。
6. 对 trend 与 gap 检查其 as_of 与 kb_anchor.as_of 一致。
7. 任一结构、anchor、artifact、locator 或逐字 quote 校验失败即拒绝，且不写正式结果。
8. 全部通过后标记 observed / inferred，保存含 selection filters、unit_ids、exact unit bindings 与 verified_at 的 consumer_binding，并渲染 comparison matrix。
9. 同步生成 canonical `payload.claims`、current verification receipt、survey 全内容 digest、稳定 subject/owner/path 与 `ready_for_review` 状态；不得为新产物写 `needs_agent_repair`。

读侧调用纯读 staleness helper 复算同一 binding：已有 unit 变化/删除、确认失效、evidence bytes 变化或出现新的 matching unit 都标 stale。它只返回原因，不改写 survey；runtime agent 重新 prepare、fill、verify 才能刷新绑定。

统一 review snapshot 同时绑定 subject、canonical claims、survey substance、content digest 与 verification digests。confirm 要求非 AI actor、逐字保留当前用户授权、`authorization_source=user_message`、evidence 和 expected snapshot；成功后写 ConfirmationReceipt。reject 只写 rejected/rejection，不伪造 confirmation。内容、claims、verification 或 upstream unit/confirmation/evidence 任一变化都会令旧确认 stale，snapshot replay/CAS 失败时零写。

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
  preference_context_digest: <sha256>
preference_context:
  task_context_digest: <sha256>
  selection_binding: {} # 无 receipt 时为空；有 receipt 时只存 ID/digest 绑定
  hard_value_digests: {}
kb_anchor:
  as_of: <caller-supplied timestamp>
  unit_ids: [p-..., r-...]
  units:
    - id: p-...
      kind: paper
      title: "..."
      record_content_digest: <sha256>
      confirmation_receipt_digest: <sha256-or-empty>
      evidence_artifacts:
        - artifact: note.md
          byte_sha256: <sha256>
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

- YAML 保留 sections、comparison_matrix、kb_anchor、claim_type、evidence_refs，并在每个 cell 上增加 `epistemic_status: verified_pending_confirmation`；`evidence_verification_status: verified` 只表示逐字证据通过，不等于用户确认。
- YAML 同时保存 `kind: survey_judgement`、canonical `payload.claims`、verification receipt、consumer binding 与 survey content digest；旧 `needs_agent_repair` 产物只可读取审计，必须重新 prepare/fill/verify 后才进入 review。
- summary.md 按七段式渲染 evidence-verified content，显式显示 Pending / Unverified banner，并将 comparison matrix 输出为 method × dimension 表格。
- metadata 只参与候选选择，不作为 survey conclusions。

脚本入口：`scripts/synthesize.py`（survey|review|taxonomy × prepare|verify，survey 另有 confirm|reject；composite status|update）。

## 启动澄清（Agent 用）

- 时间窗？默认近两年（as_of=今天）。
- 只用库内已确认 unit 还是先补检索？默认库内；不足报 evidence-gap 走 composite。
- 深度：全套七段+对比矩阵还是精简 review？默认全套。

# Research Schemas

跨 skill 共享的 YAML / Markdown artifact 协议。每个 skill 写入或读取这些 artifact 时遵循此处定义，避免在多个 SKILL.md 里重复定义且漂移。

实现源：
- 枚举与 record 模板：`.agents/lib/research/core.py`
- YAML 读写与公共字段：`.agents/lib/research/common.py`

时间格式：全部使用 UTC ISO-8601，如 `'2026-05-06T05:56:11+00:00'`。脚本生成时间用 `utc_now_iso()`。

---

## 运行时 <a id="runtime"></a>

所有 skill 脚本在直接运行时会先检查当前 Python 是否能 `import yaml`。如果不能，会自动创建并切换到项目内受管 `.venv`（含 PyYAML），用户无需手动创建 venv、运行 pip 或导出 `RESEARCH_PYTHON`。

- `RESEARCH_PYTHON`：可选覆盖解释器；若该解释器可 `import yaml`，脚本会优先 re-exec 到它。
- `RESEARCH_VENV`：覆盖受管 venv 路径；默认是安装本仓库的目录下 `.venv`（与 `.agents` 同级）。
- `RESEARCH_NO_MANAGED_VENV=1`：关闭自动 venv，改用当前解释器；此时当前解释器必须自备 PyYAML。

受管 venv 属于本地 runtime state，不纳入版本控制。

---

## 共享枚举 <a id="enums"></a>

| 名称 | 取值 | 含义 |
|---|---|---|
| `STATUS_VALUES` | `draft, screened, pending, active, selected, rejected, archived, planned, running, completed, failed` | unit / program / event 通用生命周期状态 |
| `CONFIRMATION_VALUES` | `auto_confirmed, pending_user_confirmation, confirmed, rejected` | 用户确认门控 |
| `INFORMATION_TYPES` | `fact, inference, evaluation, user_opinion, unverified` | 信息性质 |
| `MATURITY_LEVELS` | `lightweight, complete` | unit 完备度 |
| `UNIT_KIND_DIRS` | `paper→kb/units/papers, repo→kb/units/repos, blog→kb/units/blogs, idea→kb/units/ideas, experiment→kb/units/experiments` | unit 落盘目录 |

**确认门控规则**（见 [`confirmation gate`](#confirmation-gate)）：
- 任一字段 `source.kind = "ai"` 或 `information_types` 包含 `{inference, evaluation, user_opinion}` 之一 → 期望 `confirmation_status` 是 `pending_user_confirmation` 或 `rejected`，且 `needs_human_confirmation = true`
- judgement-track 契约违规默认 fail-closed，直接拦截 unit `record.yaml` 写入；仅显式设置 `RESEARCH_VALIDATE_FAILOPEN=1`（或内部调用显式 `strict=False`）才降级为 warning。fact-track / 非 gated record 不受影响。program state / reporting events 等旁路文件目前不经过该 gate。
- **确认溯源**：把 `confirmation_status` 迁到 `confirmed` 必须提供确认人（`--confirmed-by` 或 `identity.default_confirmed_by` 二选一）+ 至少一条 `--evidence`，否则 `apply_confirmation`/`promote_record` 直接拒绝（`SystemExit`）；确认时写入下方完整 `ConfirmationReceipt`。其它状态（auto_confirmed/pending/rejected）无需 provenance。
- **确认时 evidence 复验**：receipt 落盘前重新运行 claim 结构/空据校验与 `verify_claim_evidence()` 逐字 quote + locator 校验；存在 claim evidence 却没有可解析的 `project_root` 时 fail-closed，不允许只凭上游 verify 结果签 receipt。

---

## unit/record.yaml <a id="unit-record"></a>

适用：paper / repo / blog / idea / experiment 五种 unit 共享的 record 顶层结构。

```yaml
id: <kind-prefix>-<slug>-<8hex>      # 必填；canonical_unit_id() 生成
legacy_ids: []                       # 旧版 id，不再使用
kind: paper|repo|blog|idea|experiment
title: ""
status: draft                        # STATUS_VALUES 之一
maturity: lightweight                # MATURITY_LEVELS 之一
confirmation_status: auto_confirmed  # CONFIRMATION_VALUES 之一
needs_human_confirmation: false      # 与 confirmation_status 同步
information_types: [fact]            # INFORMATION_TYPES 子集
confidence: 0.9                      # 0.0-1.0
created_at: ''                       # UTC iso
first_ingested_at: ''
updated_at: ''
last_human_confirmed_at: ''
confirmation:                        # 仅在人工确认为 confirmed 时写入（apply_confirmation）
  by: ''                             # 确认人（--confirmed-by 或 identity.default_confirmed_by，非空）
  at: ''                             # UTC iso
  evidence: []                       # 证据 kb-path / 用户原话（--evidence，至少一条）
  method: cli                        # 确认渠道，如 'kb.py promote' / 'paper.py confirm'
  decision: confirmed                # 本 receipt 对应的用户决定
  subject:                           # 确认对象身份
    kind: paper
    id: p-...
  claim_ids: []                      # 本次确认覆盖的 payload.claims id；无 claims 时为空
  content_digest: ''                 # 确认时核心 substance + claims/evidence_refs 的 canonical sha256
  evidence_digest: ''                # evidence + claims 中 quote/locator 集合的 canonical sha256
  prior_information_types: []        # 确认前的 epistemic 类型，确认不得抹除其来源语义
  invalidation:                      # content_digest 不再匹配时由 normalize_record_schema 写入
    reason: confirmable_content_changed
    stored_content_digest: ''
    current_content_digest: ''
tags: []                             # slug 列表，治理见 topic-taxonomy.yaml
topics: []                           # 同上
candidate_pools: []                  # pool id 列表，治理见 candidate-pools.yaml
program_ids: []                      # 关联的 program slug
priority: normal                     # high|normal|low
summary: ""                          # 1-2 句，AI 写入时必须 pending
links:                               # 关联其它 unit
- target_id: <unit-id>
  relation: builds_on|cites|implements|...
  note: ""
reuse_flags:                         # 是否已被下游 skill 复用
  review: false
  idea: false
  experiment_design: false
  paper_writing: false
  weekly_report: false
  ppt: false
taxonomy:
  primary_topic: ""
  secondary_topics: []
  canonical_tags: []
  topic_sources: []                  # 由谁加上去（skill 名/legacy-rebuild）
  tag_sources: []
  pool_sources: []
artifacts: []                        # kb-relative path 列表
source:
  original_uri: ""                   # 原始链接或路径
  backup_paths: []                   # 仓内备份相对路径
  backup_kind: file|dir
  file_hash: ""                      # sha256（如有）
payload:                             # 见下方 per-kind payload
  ...
history:                             # append_history() 写入
- timestamp: ''
  action: created|screened|...
  summary: ""
  information_types: [fact]
  artifacts: []
```

### per-kind payload <a id="unit-payload"></a>

每种 kind 的 payload 结构由 `core.py kind_payload_skeleton(kind, title)` 给出。下面列出对外契约关键字段（AI 写入这些字段时按 [`confirmation gate`](#confirmation-gate) 设置 pending）：

| kind | payload 关键 section | 写入 skill |
|---|---|---|
| paper | `basic_info`, `source_search`, `quick_screen{paper_type, judgement_reason, takeaways}`, `core_content`, `structure`, `figures`, `critique`, `state` | paper-analyst |
| repo | `basic_info`, `source_search`, `capability{boundary, core_capabilities}`, `structure`, `reuse`, `risk` | repo-analyst |
| blog | `basic_info`, `source_search`, `positioning`, `content`, `credibility` | blog-analyst |
| idea | `problem{problem_definition}`, `hypothesis{core_hypothesis}`, `review` | idea-workbench |
| experiment | `basic_info{goal}`, `setup`, `process`, `results`, `diagnosis`（另见 run-log/diagnoses/follow-ups 旁路文件） | experiment-workbench |

### paper 类型与 note element set <a id="paper-element-sets"></a>

`payload.quick_screen.paper_type` 由 runtime agent 在 screening 阶段依据证据填写，脚本只校验枚举并持久化，**不得用关键词或启发式自动分类**。

```yaml
payload:
  quick_screen:
    paper_type: ""  # ""|method_system|benchmark|survey；空/未知下游回退 method_system
```

`complete-note` 的 `required_elements` 按类型选择；每个 element 都是 judgement-class claim，必须有逐字可验证的 `evidence_refs`：

| paper_type | required_elements | payload target |
|---|---|---|
| `method_system` | `motivation`, `method`, `experiment`, `limitation`, `insight` | motivation→`core_content.motivation`; method→`core_content.method`; experiment→`core_content.changes_and_effects`; limitation→`critique.weak_spots`; insight→`core_content.why_it_might_work` |
| `benchmark` | `motivation`, `task_design`, `metrics`, `coverage_limitation`, `insight` | motivation→`core_content.motivation`; task_design→`core_content.method`; metrics / coverage_limitation→`core_content.changes_and_effects`; insight→`core_content.why_it_might_work` |
| `survey` | `scope`, `taxonomy`, `trends`, `gaps`, `insight` | scope→`core_content.motivation`; taxonomy→`core_content.method`; trends / gaps→`core_content.changes_and_effects`; insight→`core_content.why_it_might_work` |

缺少 `paper_type` 的旧 paper 必须保持 `method_system` 的原五要素行为。三种集合都至少写入一个 `core_content` 字段，不改变 confirmation substance gate。

---

## experiment 旁路文件 <a id="experiment-files"></a>

experiment unit 除 record.yaml 外有三个职责分离的旁路文件。**职责分工**：

- `run-log.yaml` = **客观记录**（fact-only），单次跑/一组跑的设置、改动、指标、产物
- `diagnoses.yaml` = **AI 推断/评估**（inference, evaluation），机制猜想、因果归类、待澄清项 → 一律 `pending_user_confirmation`
- `follow-ups.yaml` = 行动列表（fact + unverified），下一步动作、优先级、完成证据

### run-log.yaml

```yaml
id: <experiment-id>-run-log
status: ready
generated_by: experiment-workbench
generated_at: ''
inputs: []
confidence: 1.0
items:
- id: <experiment-id>-run-log-001
  created_at: ''
  why_this_run: ""              # 触发动机
  tested_hypothesis: ""         # 这一跑想验证的具体假设
  changes: []                   # 相对上一跑的变更
  metrics: {}                   # 量化结果（dict，键为指标名）
  outcome: success|partial|failure
  classifications: [method|data|resource|evaluation|...]
  result_summary: ""
  next_actions: []
  artifacts: []                 # 输出文件 kb-path
  information_types: [fact]     # run-log 必须只含 fact，否则迁到 diagnoses
```

### diagnoses.yaml

```yaml
items:
- id: <experiment-id>-diagnoses-001
  created_at: ''
  summary: ""
  categories: [method|data|resource|evaluation|...]
  likely_causes: []             # 推断
  ruled_out_causes: []          # 已经排除（有证据则 fact，否则 inference）
  unknowns: []                  # 待澄清
  next_actions: []
  confirmation_status: pending_user_confirmation   # AI 写入必须 pending
  information_types: [inference, evaluation, unverified]
```

### follow-ups.yaml

```yaml
items:
- id: <experiment-id>-follow-ups-001
  created_at: ''
  action: ""
  category: method|data|resource|evaluation|...
  priority: high|normal|low
  status: open|in-progress|done|cancelled
  evidence_needed: []
  information_types: [fact, unverified]
```

---

## program 文件 <a id="program-files"></a>

program 落在 `kb/programs/<program-id>/`，结构：

```
kb/programs/<id>/
├── README.md              # 入口页（人面向；当前结论+pending 说明）
├── state.yaml             # 程序状态机
└── workflow/
    ├── open-questions.yaml
    ├── evidence-requests.yaml
    ├── decision-log.md
    └── reporting-events.yaml
```

写入方：`research-orchestrator` 拥有所有这些文件。其它 skill **只读**；要变更必须 emit reporting-event 让 orchestrator 写回。

### state.yaml

```yaml
id: <program-id>-state
status: active|completed|failed|archived
generated_by: research-orchestrator
generated_at: ''
inputs: []
confidence: 1.0

program_id: <slug>
question: ""                  # 1 句，研究问题
goal: ""                      # 1 段，本周期目标
stage: ""                     # 自由文本 stage 名，stage-changed 事件改它
active_unit_ids: []           # 当前关注的 unit
blockers: []                  # 阻塞描述
next_actions: []
resource_constraints: []
selected_idea_id: ""          # 经用户确认选定
selected_repo_id: ""
time_policy:
  storage_timezone: UTC
  display_note: human-facing markdown may localize when needed
workflow_files:               # 反向索引，便于 navigator
  open_questions: ...
  evidence_requests: ...
  decision_log: ...
  reporting_events: ...
counts:                       # 由 orchestrator 自动维护
  open_questions: 0
  evidence_requests: 0
  reporting_events: 0
  decisions: 0
updated_at: ''
```

### open-questions.yaml

```yaml
items:
- id: <program-id>-open-questions-001
  created_at: ''
  question: ""
  context: ""
  priority: high|normal|low
  owner: <skill-name>         # 谁该来回答（literature-synthesizer / experiment-workbench / ...）
  related_unit_ids: []
  status: open|answered|dropped
  information_types: [fact, unverified]
```

### evidence-requests.yaml

```yaml
items:
- id: <program-id>-evidence-requests-001
  created_at: ''
  question: ""                # 待获取的证据
  needed: ""                  # 期望证据形态
  source_type: paper|repo|blog|experiment|user
  priority: high|normal|low
  blocking: true|false        # 是否阻塞 stage 推进
  related_unit_ids: []
  status: open|fulfilled|dropped
  information_types: [fact, unverified]
```

### decision-log.md

Markdown，每条决策一段，固定 H2：`## <iso-timestamp> · <一句话决策>`，正文要含：

```markdown
- Stage: `<from>` -> `<to>`（如有迁移）或 `<current>`
- Rationale: ...
- Information types: <逗号分隔，从 INFORMATION_TYPES 取>
- Evidence: <kb-path 或 unit-id 列表>
- Alternatives: <考虑过的替代方案>
- Confirmation: `pending_user_confirmation`   # AI 决策默认 pending
```

### reporting-events.yaml

**跨 skill 契约的核心 artifact**。program 内所有可上报事件（state 变迁、unit 进展、用户确认、阶段汇报）在此累积；`report-author` 从这里读取生成周报/汇报材料。

```yaml
id: <program-id>-reporting-events
status: ready
generated_by: research-orchestrator
generated_at: ''
inputs: []
confidence: 1.0
items:
- source_skill: research-orchestrator   # 发起 skill
  event_type: program-created|stage-changed|evidence-requested|evidence-fulfilled|
              decision-made|unit-attached|unit-detached|phase-completed|
              user-confirmation|report-published|...
  title: ""                              # 1 句，人能读
  summary: ""                            # 1-3 句
  stage: <program stage when emitted>
  tags: []                               # program-state / evidence-request / paper / ...
  artifacts: []                          # 相关 kb-path
  timestamp: ''                          # UTC iso
  idea_ids: []
  paper_ids: []
  repo_ids: []
  # 可选字段：
  # confirmation_status, information_types
```

`event_type` 规范由 research-orchestrator 维护；非 orchestrator skill emit 事件时**必须**把自身 skill 名写入 `source_skill`。

---

## config 文件 <a id="config-files"></a>

落在 `kb/config/`，由 `knowledge-base-manager` 拥有写权（含 lifecycle、合并、lint），`research-config-manager` 只负责 seed/policy 输入。

### candidate-pools.yaml

```yaml
id: candidate-pools
status: active
generated_by: knowledge-base-manager
policy:
  selection_requires_confirmation: true     # pool membership 变更是否需要用户确认
  default_membership_mode: overwriteable    # overwriteable|append-only
pools:
  <pool-id>:
    id: <pool-id>
    summary: ""
    topic_hints: []                         # 自动归入此 pool 的 topic slug
    tags: []                                # 自动归入此 pool 的 tag slug
    # 可选：membership_mode 覆盖默认 policy
```

### topic-taxonomy.yaml

```yaml
id: topic-taxonomy
status: active
generated_by: knowledge-base-manager
policy:
  canonical_topic_style: lowercase-hyphen-slug
  canonical_tag_style: lowercase-hyphen-slug
  overwriteable_fields: [topics, tags, candidate_pools, summary]
topics:
  <topic-slug>:
    id: <topic-slug>
    aliases: []
    tags: []                                # 该 topic 下的 canonical tag
```

### runtime-preferences.yaml

由 `research-config-manager` 写入。schema 见 `core.py default_runtime_preferences()`，包含资源画像、语言偏好、自动化开关、versioning_commit_mode（`manual|milestone|aggressive`）等。

- `identity.default_confirmed_by`: 可选的人类确认身份默认值。只用于补齐 `--confirmed-by`；`--evidence` 仍必须由调用方显式提供，系统不得默认使用 AI 写出的单元笔记作为 evidence。

### research-settings.md / user-profile.yaml

人面向偏好与背景；只读契约，由 navigator/orchestrator 在生成 user-facing 页面时引用。

---

## memory 文件 <a id="memory-files"></a>

### learnings.yaml <a id="learnings-yaml"></a>

落在 `kb/memory/learnings.yaml`，由 `skill-evolution-advisor` 追加和复审。捕获条目默认 `pending`，因为它是对用户习惯、复发问题或 skill 缺陷的 AI 推断；只有用户 `review` / `promote` 后才进入可遵守的 confirmed 状态。`skill-defect` 只记录供用户审阅，不得自动修改 skill 或 `OPTIMIZATION_PLAN.md`。

```yaml
- id: lrn-<YYYYMMDD>-NNN
  created_at: ""                 # UTC iso
  category: skill-defect | user-preference | recurring-issue
  text: ""                       # 一句话自由文本
  source: agent | user
  skill: ""                      # 可选，涉及的 skill
  context: ""                    # 可选
  status: pending | confirmed | dismissed
  occurrences: 1                 # 相似条目命中则 +1，不新增行
  last_seen_at: ""               # UTC iso
```

确认后的 `user-preference` 可通过 `promote` 写入 `kb/config/runtime-preferences.yaml` 的 `learned_preferences.items`；确认后的 `recurring-issue` 仅出现在 recall 摘要中。

---

## ownership 矩阵 <a id="ownership"></a>

| artifact | 写入 skill | 读取 skill | 备注 |
|---|---|---|---|
| `kb/units/<kind>s/<id>/record.yaml` | source-intake (创建)、`<kind>`-analyst（精修）、knowledge-base-manager（合并/治理） | 全部 | confirmation gate 默认 warning；strict 模式拦截 |
| experiment run-log/diagnoses/follow-ups | experiment-workbench | report-author, research-orchestrator | 三文件职责严格分离 |
| program state.yaml + workflow/* | research-orchestrator | report-author, navigator | 其它 skill emit reporting-event 让 orchestrator 写 |
| program reporting-events.yaml | research-orchestrator（主要）、experiment-workbench / paper-analyst / method-designer / idea-workbench（事件附加） | report-author | 各 emit skill 必须填 `source_skill` |
| program decision-log.md | research-orchestrator | navigator, report-author | AI 决策必须 `Confirmation: pending_user_confirmation` |
| kb/config/candidate-pools.yaml | knowledge-base-manager | source-intake, literature-synthesizer, idea-workbench | research-config-manager 提供 seed/policy 输入 |
| kb/config/topic-taxonomy.yaml | knowledge-base-manager | analyst skills, literature-synthesizer | 同上 |
| kb/config/runtime-preferences.yaml | research-config-manager | 全部 | 唯一直接归 config-manager 的 artifact |
| kb/memory/learnings.yaml | skill-evolution-advisor | research-navigator, 全部（通过 recall 摘要） | 经验/习惯/skill 缺陷记忆；skill-defect record-only |
| kb/synthesis/wiki/*.md | wiki-adapter | 全部（人面向） | 复用笔记/术语沉淀 |
| kb/user/* | research-navigator | （只读） | 人面向入口，read-only |

---

## confirmation gate <a id="confirmation-gate"></a>

**契约目标**：core 系统中所有 AI 推断/评估/用户意见，必须经过用户显式确认后才能 `confirmed`。否则保持 `pending_user_confirmation`。

**当前运行行为**：`lib/research/core.py` 提供 `validate_write(record)` helper。AI-derived / judgement-track record 违反 confirmation contract 时默认 `SystemExit` 拦截；只有显式 `RESEARCH_VALIDATE_FAILOPEN=1` 或内部调用显式 `strict=False` 才写 stderr warning 并返回 violations。`write_record()` 在 lock / CAS / journal 之前调用该 helper；program state、workflow files、reporting events 等非 unit record 写入暂不经过此 gate。

**检查规则**：

```
IF record["source"].get("kind") == "ai"
   OR any(t in record["information_types"] for t in {"inference", "evaluation", "user_opinion"}):
   EXPECT record["confirmation_status"] in {"pending_user_confirmation", "rejected"}
   EXPECT record["needs_human_confirmation"] is True
```

跨 skill 一致性：unit `record.yaml` 写入应统一走 `write_record()` 或显式调用 `validate_write()`。其它 artifact 若需要同等强度的门控，应另行实现并补测试。

---

## Evidence / Claims <a id="evidence-claims"></a>

> **状态（Wave 2 · Evidence track 已落地）**：本节锁定 claim→evidence 绑定的规格，运行侧逐字校验已在 `lib/research/evidence.py` 实现为**可调用、可测试的纯函数**（`verify_claim_evidence` / `validate_claims` / `attach_claims` / `read_claims`），并经 `core.py` 门面再导出。该层仍是 **additive**：系统内暂无调用方（confirmation gate 与 analyzer 未改），judgement 空据 → 不得 confirmed 的**门控联动**由并行 Gate track 消费 `validate_claims()` 落地，本层只提供判据函数，不改 gate。

**契约目标（原则 2）**：每条 AI 判断（fact / inference / evaluation / user_opinion / unverified）都挂 `evidence_refs`，让"有理有据"从口号变成**可机器校验**——脚本能查"这条据在不在"。落盘位置：note / screening 产物内的 `claims` 列表（`attach_claims(payload, claims)` 写、`read_claims(payload)` 读）+ record 关联。

**canonical schema（锁定规格）**：

```yaml
# 挂在每条 AI claim 上。落盘位置：note/screening 产物内的 claims 列表 + record 关联。
claim:
  id: claim-001
  text: ""                       # 断言本身
  claim_type: fact|inference|evaluation|user_opinion|unverified
  confidence: 0.0                # 可选
  confirmation_status: pending_user_confirmation|confirmed|rejected|auto_confirmed
  evidence_refs:
    - source_unit_id: p-...       # 证据所在 unit
      artifact: parse-cache.yaml  # unit 内相对路径，或 source(pdf/html)
      locator: "page=3"           # PDF: page=N|section|para ; HTML: section|anchor（B4）
      quote: ""                   # 短逐字片段（B3）——脚本校验它逐字存在于 artifact
      summary: ""                 # 可选转述
```

**字段语义**：

| 字段 | 层级 | 语义 |
|---|---|---|
| `id` | claim | 必填，claim 唯一标识（如 `claim-001`）。 |
| `text` | claim | 必填，断言本身（非空）。 |
| `claim_type` | claim | 必填，取 `fact` / `inference` / `evaluation` / `user_opinion` / `unverified` 之一。**judgement-class** = `{inference, evaluation}`。 |
| `confidence` | claim | 可选，0.0–1.0。 |
| `confirmation_status` | claim | 必填，取 `pending_user_confirmation` / `confirmed` / `rejected` / `auto_confirmed` 之一（与 record 的 `CONFIRMATION_VALUES` 同族）。 |
| `evidence_refs` | claim | 必填列表（fact-class 可空；judgement-class 非空）。 |
| `source_unit_id` | ref | 证据所在 unit id。 |
| `artifact` | ref | unit 内相对路径（`parse-cache.yaml` / `note.md` / source 文件）；逐字校验对此文件文本进行。 |
| `locator` | ref | 定位提示，两套（见下）。 |
| `quote` | ref | **短逐字片段（B3）**——脚本校验它逐字存在于 `artifact`。 |
| `summary` | ref | 可选转述（不参与逐字校验）。 |

**逐字验证规则（`verify_claim_evidence(claim, unit_dir)`，原则 1）**：对每条 claim 的每个 evidence_ref，在 `unit_dir` 下加载 `artifact`，把 artifact 文本与 `quote` 都做**空白归一化**（连续空白→单空格 + strip；**大小写敏感、标点保留**），再判 `quote` 是否为 artifact 的**逐字子串**。命中 = grounded；未命中 = 返回一条 violation（含 claim id + artifact + quote 摘要）。归一化只折叠空白，因此一条跨行换行/多空格的引用仍能命中，而改动了词、大小写或标点的编造引用不能。空 quote、缺 artifact、artifact 读不到、非 dict 输入均返回精确 violation 而非崩溃；`verify_claim_evidence({}, None)` 返回 `[]`。artifact 为 `.yaml`（parse-cache）时取 `chunks[].text`（无该结构则拼接所有字符串叶子），其它后缀按纯文本读。**返回空列表 = 全部 grounded。**

**两套 locator（B4）**：**PDF 源**用 `page=N` / `section` / `para`；**HTML 源**用 `section` / `anchor`（HTML 无页码）。当 artifact 为含 per-page chunk（label 形如 `...:page-N`）的 parse-cache 且 locator 为 `page=N` 时，校验会**额外缩小到该页**：quote 逐字命中在文档但落在**别的页** → 记一条 locator-mismatch violation（页码引错也是接地缺陷）。逐字命中始终是硬性判据，页缩小是精度加成，无 per-page 结构时自动退化为全文校验。

**结构校验（`validate_claims(claims)`）**：逐条校验 claim 结构合法——必填字段齐全（`id`/`text`/`claim_type`/`confirmation_status`/`evidence_refs`）、`claim_type` ∈ 枚举、`confirmation_status` ∈ 枚举、`evidence_refs` 为列表——并施加**空据规则**：judgement-class（`inference`/`evaluation`）claim 的 `evidence_refs` **必须非空**（空 → violation）。fact-class 允许空 `evidence_refs`。返回 violation 列表（空 = 全部合法）。此函数是**纯判据**，不改任何 gate/record。

**门控联动（原则 3）**：judgement-class claim 若 `evidence_refs` 为空，**不得 promote 成 `confirmed`**。本层用 `validate_claims()` 提供该判据；Gate track 负责把它接进确认门（本层不动 gate）。

---

## 给 SKILL.md 的引用规范

每个消费上述 artifact 的 SKILL.md，在 frontmatter 后面紧接一行：

```
> 协议参考：`.agents/lib/research/SCHEMAS.md#<anchor>`
```

可用 anchor：`enums`, `unit-record`, `unit-payload`, `experiment-files`, `program-files`, `config-files`, `ownership`, `confirmation-gate`, `evidence-claims`。

# Research Vault v2：Markdown-first / Obsidian-first 研究工作区蓝图

> - Blueprint ID: `research-vault-v2`
> - Status: maintainer-confirmed review candidate；只有经人类 review 合入目标分支后才成为 tracked accepted target
> - Parent Epic: [#46](https://github.com/caozx1110/ResearchLab/issues/46)
> - Wave 0 Atomic Issue: [#47](https://github.com/caozx1110/ResearchLab/issues/47)
> - Baseline: `origin/codex/development@2c614e66c9e219c3d3216f3187af32b431aa4446`
> - Long-term decision: [ADR 0005](../../decisions/0005-markdown-semantic-source-and-five-skill-research-vault.md)

## 1. 状态、权威与阅读边界

本文件定义 Research Vault v2 的完整目标合同，而不是现有 v1 runtime 的行为说明。当前代码、测试和 schema 在 hard cutover 完成前仍描述 v1 实现；本文件合入后成为后续 waves 的 accepted target，不能被尚未迁移的旧代码反向解释。

本蓝图固定以下承重决定：

1. 普通 Markdown 是人类可理解语义的唯一真相。
2. 原始材料、证据证明和运行状态进入隐藏区域，但不能拥有语义。
3. Obsidian 直接打开安装后工作区根目录，`Home.md` 是主要入口。
4. 旧 `kb/`、`record.yaml` canonical、逻辑 `kb/...` artifact identity、`obsidian/managed/` 投影和旧兼容路径不进入新合同。
5. 原 15 个 shipping skill 收敛为 5 个重新定义的 skill。
6. Defuddle、Obsidian 工具和 AnyDoc 是外部能力，不迁移、不复制、不计入 shipping inventory。

若未来改变这些决定，必须新增 ADR，并通过新的 Atomic Issue 和人类 review；不能仅靠实现代码或 skill 自述静默改变。

## 2. 第一性原理

### 2.1 用户必须直接拥有知识

用户应能在没有本产品 runtime、数据库、插件或 Agent 的情况下，用文件浏览器、文本编辑器、Git、备份软件或 Obsidian 阅读、编辑、链接和复制自己的研究内容。

因此：

- 标题、问题、摘要、claim、判断、决定、项目状态、实验结果和报告正文必须写入普通 Markdown。
- 不允许把 JSON/YAML/SQLite 中的记录称为 canonical，再把 Markdown 当投影。
- YAML frontmatter 只承载少量、可人工理解的 `id`、`kind`、`status` 等路由属性；不得把旧 `record.yaml` 塞进 frontmatter 继续存在。

### 2.2 语义、来源保真和运行证明是三个不同问题

- **语义**回答“人类认为这是什么、意味着什么”。
- **来源保真**回答“当时拿到的原件究竟是什么 bytes”。
- **运行证明**回答“某条 claim 当时绑定了哪个 revision、quote、locator 和授权”。

三者可以互相校验，但不能互相替代。隐藏记录与 Markdown 不一致时，系统应报告 stale/tamper，而不是用隐藏记录覆盖 Markdown。

### 2.3 派生能力必须可删除重建

索引、FTS、缓存、Views、Bases、状态面板和搜索结果只能加速导航。删除它们后，语义和来源证明必须仍然存在；重建结果只能从 Markdown、原件 manifest 和持久证明派生。

### 2.4 Agent 负责理解，脚本负责机械边界

Agent 可以阅读来源、比较证据、撰写分析和提出判断。脚本只负责：

- 保存原件、建立目录和模板；
- 解析 Markdown 结构；
- 计算 digest、验证 locator 和引用；
- 管理 lock、journal、CAS、原子写和恢复；
- 构建可删除索引和视图。

脚本不得用关键词、长度、引用数或转换成功来冒充理解，也不得自动把推断标成已确认事实。

### 2.5 失败必须诚实且保留材料

保存原件成功、转换失败时，结果是 `stored-unparsed` 或 `degraded`，不是伪造 reader。无法可靠定位逐字证据时，可以提供全文入口，但不能声称精确 page/section/line evidence。

## 3. 四层 ownership

| 层 | 位置 | 唯一职责 | 明确禁止 |
|---|---|---|---|
| Human semantic layer | `Home.md`、`Sources/**/index.md`、`reader.md`、`Notes/`、`Projects/`、`Experiments/`、`Decisions/`、`Reviews/`、`Reports/` | 所有人类可理解的内容和状态 | 依赖隐藏数据库才能解释正文 |
| Source fidelity layer | `Sources/**/.source/` | 原始 bytes、revision、assets、转换快照、source map、manifest | 生成研究判断或覆盖可见 Markdown |
| Agent operational layer | 根 `.research/` | evidence binding、receipt、index、journal、lock、cache、log、recovery、run raw data | 成为 claim、项目状态或决定的第二真相 |
| Derived navigation layer | `Views/`、可选 `.base` | 可重建列表、状态页、查询结果和卡片视图 | 被引用为唯一证据或授权来源 |

`.obsidian/` 完全由用户和 Obsidian 管理。本产品不得生成、复制、重置或把其中设置作为核心正确性的前置条件。

### 3.1 隐藏数据的持久性分类

| 类别 | 示例 | 删除语义 |
|---|---|---|
| 持久来源 | `.source/manifest.json`、raw revisions、source maps、assets | 删除会损失来源保真或证据可验证性，不属于普通重建 |
| 持久证明 | `.research/evidence/`、`.research/receipts/`、已提交 operation journal | 删除不会改变 Markdown 写了什么，但会使验证/授权降级为 unknown |
| 可重建派生 | `.research/index/`、`.research/cache/`、`Views/`、`.base` | 可以安全删除并从持久材料重建 |
| 临时运行 | `.research/locks/`、轮换 logs、未完成临时文件 | 按恢复合同清理，不得影响已提交语义 |

## 4. 安装后工作区目录

Obsidian 打开的 vault 就是安装后工作区根目录，不再额外包一层 `kb/` 或 `research-vault/`：

```text
<workspace-root>/
├── Home.md
├── Preferences.md
├── Inbox/
│   └── index.md
├── Sources/
│   └── src-quarterly-report/
│       ├── index.md
│       ├── reader.md
│       └── .source/
│           ├── manifest.json
│           ├── revisions/
│           │   └── rev-20260824-01/
│           │       ├── original.docx
│           │       ├── normalized.md
│           │       ├── source-map.json
│           │       └── assets/
│           └── cache/
├── Notes/
├── Projects/
│   └── project-vault-v2/
│       ├── index.md
│       ├── questions.md
│       └── worklog.md
├── Decisions/
├── Experiments/
│   └── exp-reader-quality/
│       ├── index.md
│       ├── results.md
│       └── runs/
├── Reviews/
├── Reports/
├── Views/
│   ├── Active Projects.md
│   ├── Review Queue.md
│   └── Recent Sources.md
├── .research/
│   ├── index/
│   ├── evidence/
│   ├── receipts/
│   ├── operations/
│   ├── experiments/
│   ├── recovery/
│   ├── cache/
│   ├── logs/
│   └── locks/
├── .obsidian/               # user-owned
├── .agents/                 # installed product, not research semantics
└── AGENTS.md                # user-owned integration file
```

顶层目录使用稳定英文名，避免工具和链接因界面语言变化而漂移；页面正文、标题和文件 slug 可以使用用户偏好的语言。

## 5. Markdown 文档合同

### 5.1 最小 identity

每个长期对象有一个稳定 ID，路径只是当前位置。最小 frontmatter 形式为：

```markdown
---
id: note-anydoc-assessment
kind: analysis
status: pending-review
---
```

要求：

- `id` 在 vault 内唯一，创建后不得因标题或路径变化而重用。
- `kind` 只用于路由和 lint，不替代正文结构。
- `status` 是可见、人类可编辑的声明；隐藏索引只派生它。
- 时间戳、缓存位置、内部 schema 版本和大块机器数据不进入 frontmatter。
- 用户重命名文件后，`research-vault` 通过 ID 重新扫描并报告/修复链接，不把旧路径当对象 identity。

### 5.2 链接与 Obsidian 扩展

- 核心页面默认使用标准相对 Markdown 链接。
- Obsidian wikilink、embed、callout、properties 和 block ID 可以作为增强语法，但核心内容不得只在插件解释后才可读。
- `.base` 必须有静态 Markdown fallback。
- `Home.md` 是用户拥有页面；Agent 不自动整页重写。动态集合写入 `Views/`，由 Home 链接。

### 5.3 用户编辑优先

- Agent mutation 必须在读取后的 expected digest 上做 CAS。
- 用户并发编辑时停止并报告冲突，不能静默覆盖。
- 自动重建只允许写明确标为派生、由产品完整拥有的文件；不得按目录扫描批量改写普通 Markdown。
- 如果用户编辑 `reader.md`，manifest 保留原转换快照并把 current binding 标为 modified/stale；重新摄入不得无提示覆盖人工 edits。

## 6. 代表性页面样例

以下样例固定信息结构，不要求实现逐字复制文案。

### 6.1 `Home.md`

```markdown
# Research Home

## Start here

- [Inbox][inbox]
- [Active projects][active-projects]
- [Review queue][review-queue]
- [Recent sources][recent-sources]

## Current focus

- [Research Vault v2][vault-v2]

## Working conventions

- [Preferences][preferences]

[inbox]: Inbox/index.md
[active-projects]: Views/Active%20Projects.md
[review-queue]: Views/Review%20Queue.md
[recent-sources]: Views/Recent%20Sources.md
[vault-v2]: Projects/project-vault-v2/index.md
[preferences]: Preferences.md
```

### 6.2 `Sources/src-anydoc/index.md`

```markdown
---
id: src-anydoc
kind: source
status: active
---

# Firecrawl AnyDoc

Local document-to-Markdown converter.

- Canonical URL: https://github.com/firecrawl/anydoc
- Readable capture: [reader.md][reader]
- Captured original: [original HTML][original]

## Capture limitations

The current conversion has no OCR support. Image-only PDF pages may be absent
from the readable capture.

## Related analysis

- [AnyDoc adapter assessment][assessment]

[reader]: reader.md
[original]: .source/revisions/rev-20260824-01/original.html
[assessment]: ../../Notes/anydoc-adapter-assessment.md
```

`reader.md` 是来源的当前人类阅读入口，不是 AI 总结。它必须明确对应哪个 revision；历史转换快照位于 `.source/revisions/<revision>/normalized.md`。

### 6.3 `Notes/anydoc-adapter-assessment.md`

```markdown
---
id: note-anydoc-assessment
kind: analysis
status: pending-review
---

# AnyDoc adapter assessment

## Claims

### Claim C-001 — AnyDoc 适合作为可选本地转换适配器

- Class: evaluation
- Review: pending
- Evidence: [E-001](#evidence-e-001)

AnyDoc 覆盖多种办公文档格式，但转换结果仍需经过来源映射和质量验证，
因此转换成功本身不是 evidence-ready 的充分条件。

## Evidence

### Evidence E-001

> Fast Rust library that converts documents (Word, PowerPoint, Excel,
> OpenDocument, RTF, EPUB, CSV, and PDF) into clean GitHub-Flavored Markdown.

- Source: [AnyDoc readable capture][anydoc-reader]
- Locator: README / Supported Formats
- Captured revision: `rev-20260824-01`

[anydoc-reader]: ../Sources/src-anydoc/reader.md
```

### 6.4 `Projects/project-vault-v2/index.md`

```markdown
---
id: project-vault-v2
kind: project
status: active
---

# Research Vault v2

## Research question

如何让人类直接维护的 Markdown 成为研究系统唯一语义真相？

## Scope

- Markdown-first vault
- 来源、证据、确认和恢复契约
- 五个 shipping skills

## Non-goals

- 旧 `kb/` 数据迁移
- `record.yaml` 兼容
- 自动执行来源代码

## Success criteria

- 删除派生索引后可从 Markdown 重建
- Obsidian 无插件打开根目录即可使用
- claim/evidence 变化使对应确认失效

## Linked work

- [Reader quality experiment][reader-experiment]
- [Architecture decision][markdown-decision]

## Next actions

- 完成 Wave 0 review
- 为 Wave 1 建立独立 Atomic Issue

[reader-experiment]: ../../Experiments/exp-reader-quality/index.md
[markdown-decision]: ../../Decisions/decision-markdown-truth.md
```

### 6.5 `Experiments/exp-reader-quality/index.md`

```markdown
---
id: exp-reader-quality
kind: experiment
status: running
---

# Reader conversion quality

## Hypothesis

保留原始字节并单独验证 source map，可以在转换器质量不足时避免伪造精确证据。

## Plan

- Formats: DOCX, PPTX, XLSX, EPUB, scanned PDF
- Baseline: direct text extraction
- Candidate: AnyDoc adapter
- Metrics: readable coverage, locator precision, asset retention, failure honesty

## Runs

- [run-001][run-001]

## Factual results

| Metric | Baseline | Candidate |
|---|---:|---:|
| Files converted | 4/5 | 4/5 |
| Verified locators | 2/4 | 3/4 |

## Interpretation

### Claim C-001 — Candidate improves locator coverage

- Class: evaluation
- Review: pending
- Evidence: [run-001][run-001]

## Limitations

- Single fixture set
- No OCR adapter

[run-001]: runs/run-001.md
```

### 6.6 `Reviews/review-anydoc-c001.md`

```markdown
---
id: review-anydoc-c001
kind: review
status: awaiting-decision
---

# Review: AnyDoc adapter claim C-001

## Subject

- [AnyDoc adapter assessment][assessment], Claim C-001

## Evidence under review

> Fast Rust library that converts documents (Word, PowerPoint, Excel,
> OpenDocument, RTF, EPUB, CSV, and PDF) into clean GitHub-Flavored Markdown.

## Requested decision

Confirm, reject, or defer this claim.

## Current decision

Awaiting an explicit user decision in the current interaction.

[assessment]: ../Notes/anydoc-adapter-assessment.md
```

Checkbox、frontmatter 编辑或文件存在本身不构成 Agent 授权。它们可以表达用户想法，但自动工作流只有在当前用户消息明确作出决定后才能生成 receipt 并把状态视为 verified。

## 7. 来源入库契约

### 7.1 支持的来源类别

| 来源 | 必须保存的原件 | reader 策略 | 常见 locator |
|---|---|---|---|
| Web HTML | 最终响应 bytes、requested/final URL、HTTP metadata | Defuddle 或安全 HTML→Markdown adapter | heading、fragment、text quote、DOM/source map |
| 原始 Markdown/text | exact bytes、encoding 结果 | 直接规范化换行，保留代码/frontmatter 为不可信数据 | heading、paragraph、line/byte span |
| PDF | exact PDF bytes | text extraction；OCR 是独立可选 adapter | page、可选 bbox、text quote |
| Git repository/source tree | commit/archive identity、选择的文件 bytes | 代码/文档 reader，不执行 repo | commit、repo-relative path、line range |
| Dataset | manifest、选择的分片/文件或外部 immutable identity | data dictionary、schema、样例和用户选定切片 | file、row key、column、cell/range |
| Office/ODF/RTF/EPUB/CSV | exact input bytes | AnyDoc 等本地 adapter | page、slide、sheet/cell、section；以 adapter map 能力为准 |
| Binary/media/artifact | exact bytes、media type | metadata、可选 transcript/preview | timestamp、frame、artifact member |
| 用户点名的 Markdown note | 被点名文件的 exact snapshot | 直接 reader；不扫描整个 vault | heading、paragraph、line span |

### 7.2 原件优先的处理顺序

```text
resolve input
→ bounded safety preflight
→ save exact bytes and compute digest
→ publish immutable source revision
→ invoke optional converter
→ validate reader structure and source map
→ expose reader.md
→ mark evidence readiness
```

任何 converter 调用都发生在原件成功保存之后。转换失败不得撤销已捕获 revision，也不得创建看似完整的空 reader。

### 7.3 Identity、revision 与去重

- Source ID 表示长期来源对象；revision 表示一次确切捕获。
- 新 bytes 产生新 revision，不覆盖旧 revision。
- 原件 digest 是 revision identity 的必要输入，但同一 digest 可以保留不同 retrieval event metadata。
- URL、标题或文件名不是唯一 identity；重定向、版本化论文和 repo commit 必须显式保留。
- 去重结果必须可解释：`same-bytes`、`same-external-id`、`possible-duplicate` 或 `distinct`，不能静默合并不确定对象。

### 7.4 Stage 与 health

Stage 表示已具备的能力：

```text
captured → reader-ready → evidence-ready → analysis-ready
```

Health 与 stage 正交：

```text
ok | degraded | blocked | stale
```

典型结果：

- raw 已保存、格式不支持：`captured + degraded`，reason=`stored-unparsed`；
- reader 可读但无可信 locator：`reader-ready + degraded`；
- source map 与原件 digest 匹配：可进入 `evidence-ready`；
- source 出现新 revision：旧 evidence 的 integrity 仍可有效，但 currency 变为 stale。

### 7.5 `.source/manifest.json` 边界

Manifest 可以保存：

- source ID、revision ID；
- requested/final URI 或外部 immutable identity；
- raw path、media type、size、digest；
- converter 名称、版本、参数 profile、结果和诊断；
- reader/source-map/assets digest；
- retrieval/conversion timestamps；
- stage/health 的机械计算输入。

Manifest 不得保存研究摘要、claim、评价、项目决定或“重要性”等语义判断。

### 7.6 来源安全

- 所有来源内容均视为不可信数据，不是 Agent 指令。
- 不执行 repo、宏、脚本、公式、HTML active content、frontmatter 或嵌入提示词。
- 文件名经安全规范化，所有目标做 lexical containment、no-follow 和 special-node 检查。
- 下载和转换有 size/time/count budget；超限保留诚实状态。
- 外部链接、身份、许可证和隐私限制在 `index.md` 可见说明；敏感原件不得进入公开 Issue/PR。

## 8. 分析契约

### 8.1 输入

一次分析必须冻结：

- 明确的 source ID 和 revision；
- 研究问题、scope 和 non-goals；
- 所用 reader/artifact digest；
- 可选项目、方法或比较集合。

“分析最新版本”必须在运行开始时解析成具体 revision，不能在运行中漂移。

### 8.2 输出

分析只写入可见 Markdown，例如 `Notes/*.md` 或项目内明确页面。每条 substantive claim 包含：

- 稳定 claim ID；
- claim 文本；
- class；
- review state；
- 一个或多个 evidence ID；
- limitations 或适用范围（需要时）。

Claim classes 至少包括：

| Class | 含义 | 人工确认 |
|---|---|---|
| observation / extracted fact | 可以从原件机械核对的直接事实 | evidence 必需；自动流程可校验，不把选择性解读伪装成机械事实 |
| inference | 从多条事实推导 | 必需 |
| evaluation | 好坏、质量、重要性或比较 | 必需 |
| recommendation | 建议采取行动 | 必需 |
| diagnosis | 原因或故障解释 | 必需 |
| decision | 研究、产品或项目取舍 | 必需 |

### 8.3 Evidence-first 与 synthesis

- 每条判断必须链接逐字 evidence；只链接来源首页不够。
- Synthesis 必须保留各来源独立 identity、相互冲突、覆盖缺口和选择边界。
- 引用数量、venue、作者声誉或转换器信心不能自动成为质量结论。
- 输入 revision、claim block 或 evidence set 变化时，只使受影响 claim stale，不必让整份无关文档全部失效。

## 9. 项目、决定与报告契约

### 9.1 项目

`Projects/<id>/index.md` 是项目语义中心，至少包含：

- research question；
- scope / non-goals；
- success criteria；
- current state；
- linked sources / notes；
- decisions；
- experiments；
- open questions；
- next actions。

`.research/` 可以索引这些字段和保存 mutation journal，但不得保存一个不同的 canonical project state。

### 9.2 决定

长期决定写入 `Decisions/<id>.md`，项目页只链接，不复制另一份正文。决定必须记录 context、选择、alternatives、evidence、consequences 和 review/authorization 状态。

### 9.3 讨论与报告

- 讨论纪要进入 `Notes/` 或项目 worklog，清楚区分参与者原话、Agent 整理和后续判断。
- 报告正文进入 `Reports/`，引用 current evidence/decision，而不是隐藏索引。
- 报告生成可以冻结 manifest，但 manifest 只证明输入和输出 digest；报告正文仍是 Markdown 语义真相。

## 10. 实验契约

`Experiments/<id>/index.md` 至少包含：

- hypothesis；
- plan；
- variables / baselines；
- metrics；
- linked project/method/source；
- runs；
- factual results；
- interpretation；
- limitations。

### 10.1 原始 run 数据

W&B export、CSV、JSON、日志、配置快照和大体积 artifact 位于 `.research/experiments/<experiment-id>/runs/<run-id>/`。对应可见 run page 记录人类可读事实、外部 identity、artifact 链接和限制。

### 10.2 导入与幂等

- 每个 source item 冻结 exact bytes 和 digest。
- external ID 相同但 bytes 不同是 conflict，不静默覆盖。
- 完全相同 item digest 重复导入为 idempotent no-op。
- fingerprint 可以绑定 hypothesis、changes、typed metric schema、artifact identity 和 config/input revision，但不能从相似 fingerprint 自动得出相同结论。

### 10.3 事实与解释分离

白名单 metric、run identity 和 artifact presence 可以机械写入 factual results。因果、显著性、异常原因、优劣和下一步建议必须形成 evidence-bound claim 并进入人工确认。

本系统管理实验记录和分析，不因“workbench”名称自动获得执行任意代码、访问外部服务或修改生产环境的权限。

## 11. 证据契约

### 11.1 可见 evidence

Markdown 中必须保留：

- 逐字 quote；
- source reader/original 链接；
- 人类可读 locator；
- source revision；
- evidence ID。

用户不打开 `.research/` 也能理解 claim 基于什么。

### 11.2 隐藏 binding

`.research/evidence/<binding-id>.json` 至少绑定：

```text
binding schema version
subject Markdown path
claim ID
normalized claim-block semantic digest
evidence ID and evidence-block digest
source ID and revision
raw artifact path and digest
reader/source-map digest
typed locator
exact quote and quote digest
binding state
```

隐藏 quote 是证明副本，不是另一份可编辑语义。可见 quote 与 binding 不一致时，binding 失效并报告，不从隐藏副本反向改写页面。

### 11.3 Locator 能力

Locator 必须按来源类型显式：

- PDF：page，必要时 bbox；
- HTML/Markdown：heading、fragment、paragraph、text quote；
- repo：commit、repo-relative path、line range；
- slide：slide number 和对象/段落 identity（adapter 支持时）；
- spreadsheet/CSV：sheet、cell/range 或稳定 row key/column；
- dataset：file、row key、column、partition；
- media：timestamp/frame；
- binary：artifact member 或仅原件级链接。

如果 adapter 只能证明 quote 存在于全文，locator 必须降级为 whole-document；不能猜 page、line 或 cell。

### 11.4 Integrity 与 currency

证据有两个独立维度：

- **integrity**：quote 是否仍能在绑定的旧 revision 原件中验证；
- **currency**：该 revision 是否仍代表需要的最新来源状态。

新 revision 不会销毁旧 evidence integrity，但可以把其 currency 标为 stale。删除或改变旧原件则破坏 integrity。

## 12. 人工确认契约

### 12.1 Review packet

`Reviews/<id>.md` 是人类可读审查包，包含：

- subject link 和 claim ID；
- claim 文本、class、scope；
- exact evidence quotes 和 locators；
- limitations/conflicts；
- 请求的 `confirm`、`reject` 或 `defer`；
- 用户备注和当前可见状态。

### 12.2 当前消息授权

自动确认只有在当前用户消息明确针对该 review/claim 作出决定时成立。以下内容单独存在时不构成授权：

- Agent 自己的判断；
- AI/工具/model 名称作为 signer；
- checkbox；
- 手动把 frontmatter 改为 `confirmed`；
- 旧聊天、旧 receipt 或本地记忆；
- “看起来用户应该同意”的推断。

### 12.3 Receipt

`.research/receipts/<receipt-id>.json` 至少包含：

```text
receipt schema version
review ID
subject path and claim ID
claim-block semantic digest
evidence-set digest
decision: confirm | reject | defer
actor declaration
authorization_source: current_user_message
available interaction/message reference
timestamp
```

Receipt 是自动化授权证明，不是新的研究语义；可见 Review/claim 仍记录人类可读结果。没有可验证 receipt 的可见 `confirmed` 只能视为 unverified，不能驱动后续受治理动作。

Receipt 绑定 claim block 与 evidence set，而不是整个文件。无关段落或排版变化不应误伤确认；claim、class、quote、locator、revision 或 evidence membership 变化必须失效。

Reject/defer 不删除原 claim 或 evidence，只改变生命周期并保留审计上下文。

## 13. 索引、搜索、Views 与 Obsidian

### 13.1 索引

`.research/index/` 从 Markdown identity、links、headings、claim/evidence IDs 和 source manifests 重建。索引可以使用 JSON、SQLite/FTS 或其他机械格式，但这些格式：

- 不进入语义编辑面；
- 不允许拥有仅存在其中的 title/status/claim；
- digest stale 或损坏时必须重建或回退到直接扫描；
- 删除后不影响来源和确认的持久证明。

### 13.2 Views

`Views/*.md` 是静态、普通 Markdown fallback。每个生成页必须清楚标记为 derived，并只链接语义对象；删除或重建不会改变对象内容。

### 13.3 Obsidian

- Obsidian 直接打开 workspace root。
- `Home.md` 是入口；无需 community plugin。
- `obsidian-cli` 只可作为可选打开、搜索、reload、status 或开发调试接口。
- Bases 从 Markdown properties 派生，可删除重建；核心功能不能要求 `.base` 存在。
- 产品不得拥有 `.obsidian/`，也不得因插件缺失拒绝读取普通 Markdown。

## 14. 原子写、并发与恢复

新数据模型保留旧系统中真正必要的机械安全能力，但重写 owner 和路径接口：

1. 每个 mutation 先解析 explicit literal target set。
2. 对所有目标做 containment、no-follow、special-node 和 expected digest preflight。
3. 按稳定顺序取得 exact-path lock。
4. 在 `.research/operations/<operation-id>/` 记录 intent、before digest、stage 和 checkpoint。
5. 单文件使用临时文件 + atomic replace；多文件使用 operation journal 和可恢复提交边界。
6. commit 前重验 source/subject/currentness 和 CAS。
7. checkpoint 只包含本操作 exact targets，绝不使用 `git add -A`。
8. 失败时保持旧完整状态或留下可证明、可恢复的 journal；不能留下半套语义。

恢复 snapshot 可以还原精确 bytes，但不能解释或重新创造缺失语义。人类在操作期间修改目标时应停止冲突处理，而不是把恢复材料当更新版本覆盖。

## 15. 外部工具与 adapter 边界

这些能力均不复制到本仓库，不计入 shipping inventory，也不拥有 canonical 状态。

### 15.1 Defuddle

- 仅用于普通网页 HTML 到候选 Markdown。
- URL 明确指向 `.md` 时跳过 Defuddle，直接保存原始 Markdown bytes。
- 输出绑定原始响应 digest、requested/final URL 和 converter version。
- 不拥有 raw、evidence、分析或确认。

### 15.2 `obsidian-markdown`

- 只提供 Obsidian Flavored Markdown 的 properties、wikilink、embed、callout、block ID 等写作约定。
- 标准 Markdown 可读性优先；该工具不复制进产品。

### 15.3 `obsidian-cli`

- 只作可选 UI 操作、搜索、状态或调试接口。
- Obsidian 未运行或 CLI 不可用时，文件合同和核心 workflow 仍成立。
- 不能成为 canonical writer 或 mutation 正确性的前置条件。

### 15.4 `obsidian-bases`

- `.base` 仅是 Markdown properties 的可选查询/视图定义。
- 必须提供 `Views/*.md` fallback。
- 删除 Bases 不得损失语义、证据或授权。

### 15.5 AnyDoc

[Firecrawl AnyDoc](https://github.com/firecrawl/anydoc) 作为 `research-capture` 的可选本地 Python adapter，用于 Word、PowerPoint、Excel、OpenDocument、RTF、EPUB、CSV 和其支持的 PDF 等格式。

Adapter 接口为：

```text
exact input bytes
→ candidate Markdown
+ extracted assets
+ diagnostics
+ optional source map
```

约束：

- 原始 bytes 必须先保存；AnyDoc 不拥有 source revision。
- 转换成功不自动等于 evidence-ready。
- AnyDoc 不提供 OCR 时，扫描/图片型 PDF 失败或缺内容必须标 `stored-unparsed`/`degraded`。
- 后续实现 wave 锁定并验证具体版本、依赖、资源限制和格式质量；本蓝图不把“当前最新版”变成长期合同。

## 16. 最终五个 shipping skill

### 16.1 `research-vault`

拥有：

- workspace 初始化和 `Home.md`/目录模板；
- Markdown identity、parser、link/lint；
- `.research` 分类、索引和 Views 重建；
- 原子写、lock、journal、CAS 和 recovery；
- `Preferences.md` 与机械 settings 的边界；
- 跨 skill 的窄对象引用协议。

不拥有来源解释、研究判断或确认决定。

### 16.2 `research-capture`

拥有：

- discover/search 候选；
- source ID/revision、exact bytes 和 `.source/manifest.json`；
- web/PDF/repo/dataset/document/artifact adapter；
- reader、assets、source map、stage/health；
- watch/refresh 和 currency 检查。

不拥有分析 claim 或项目决定。

### 16.3 `research-analysis`

拥有：

- 单来源 paper/repo/dataset/blog/document 分析；
- 多来源 synthesis、taxonomy、conflict 和 gap；
- claim/evidence Markdown 结构；
- input/revision binding 和 stale 传播。

不确认自己的判断，也不拥有项目生命周期。

### 16.4 `research-workbench`

拥有：

- project、question、idea、method；
- experiment、run 和结果整理；
- discussion、decision 和 report；
- 纵向研究状态、链接和 next actions。

它消费 source/claim/review references，不重新实现 capture、evidence 验证或 receipt。

### 16.5 `research-review`

拥有：

- evidence audit；
- review packet；
- confirm/reject/defer；
- receipt、current-message authorization 和 stale 检查；
- 未验证 `confirmed` 状态的 fail-closed 处理。

它不生成待确认判断，也不得以工具/Agent 身份自签。

### 16.6 Skill 间接口

```text
research-capture
  → source reference + revision + readiness
research-analysis
  → analysis Markdown + claim/evidence references
research-review
  → review Markdown + authorization receipt
research-workbench
  → projects/experiments/decisions/reports linking accepted references
research-vault
  → shared file, identity, index, transaction and recovery mechanics
```

没有独立 god-orchestrator。安装态最小 Agent 规则根据对象和意图路由到单一 owner；跨 skill 只传稳定 reference，不复制私有脚本或 canonical record。

## 17. 原 15 个 skill 的处置

| 原 shipping skill | 决定 | v2 owner |
|---|---|---|
| `source-intake` | 完全重写 | `research-capture/capture` |
| `literature-search` | 合并 | `research-capture/discover` |
| `research-monitor` | 合并 | `research-capture/watch` |
| `unit-analyst` | 完全重写 | `research-analysis/analyze` |
| `literature-synthesizer` | 合并 | `research-analysis/synthesize` |
| `knowledge-base-manager` | 完全重写 | `research-vault` |
| `research-config-manager` | 合并 | `research-vault/preferences` |
| `research-orchestrator` | 取消独立 skill | 最小路由规则 + `research-workbench` |
| `idea-workbench` | 合并 | `research-workbench/idea` |
| `method-designer` | 合并 | `research-workbench/method` |
| `experiment-workbench` | 合并 | `research-workbench/experiment` |
| `report-author` | 合并 | `research-workbench/report` |
| `discussion-archivist` | 合并 | `research-workbench/discussion` |
| `kb-cli` | 退役 | 自然语言 + 可选 `research <verb>` 意图记法；不提供 executable CLI skill |
| `skill-evolution-advisor` | 从 shipping inventory 退役 | GitHub Issue、tracked design/ADR 和开发者诊断流程 |

五技能而不是四技能的理由：

- 把 project/experiment/report 塞进 `research-vault` 会让基础设施重新拥有全部业务语义。
- 把 workbench 塞进 `research-analysis` 会混淆“形成判断”和“管理长期研究活动”。
- 把 `research-review` 合入产出判断的 skill 会削弱不可自签的治理边界。

## 18. 目标产品源码边界

后续 hard cutover 完成后的 tracked product inventory 目标为：

```text
skills/
├── research-vault/
├── research-capture/
├── research-analysis/
├── research-workbench/
└── research-review/

runtime/
├── AGENTS.md / WORKSPACE_RULES.md
├── contracts/ or equivalent narrow schema resources
├── templates/
└── lib/research/        # shared mechanical primitives only
```

根 `/.agents/` 继续只放维护者本地工具，不进入 release input。Defuddle、Obsidian skills/CLI/Bases 和 AnyDoc 均不出现在上述五项 shipping inventory 中。

用户公开交互以自然语言为主；文档需要短记法时可以使用 `research capture`、`research analyze`、`research project`、`research experiment`、`research review` 等意图标签，但它们不是要求用户运行的 shell command，也不需要一个 `research-cli` skill。

## 19. 兼容、legacy 与 hard cutover

明确退役的概念：

- 物理或逻辑 `kb/` canonical namespace；
- `record.yaml` canonical unit；
- `kb/user/` 人读投影；
- `obsidian/managed/` 双真相投影；
- 旧 `SCHEMAS.md` 对新 vault 的约束；
- `kb <verb>` 兼容 surface；
- 旧 owner identity、兼容 alias 和双写路径。

不兼容不等于可以删除用户数据：

- 新 runtime 不读写旧 workspace。
- 检测到 legacy 数据时 fail safe，提示用户备份并使用新 workspace。
- 不自动迁移、覆盖、移动或删除旧 `kb/`。
- 如果未来确有迁移需求，另建 Blueprint/ADR/Atomic Issue，提供显式、可验证、可回滚的一次性导入；它不改变 v2 的新合同。

## 20. 实施 waves

### Wave 0 — Tracked blueprint and ADR

- 本文件；
- ADR 0005；
- `docs/DESIGN.md` 的 target/current 边界；
- 无代码、skill skeleton、fixture 或 runtime 行为变化。

### Wave 1 — Vault foundation

- 五个 skill skeleton 与发现 metadata；
- `research-vault`、Markdown identity/parser/link/lint；
- Home/templates、`.research` 分类、index/Views；
- 原子写、journal、lock、CAS、recovery 的新 owner 接口。

### Wave 2 — Capture and revisions

- source ID/revision/manifest；
- web、Markdown/text、PDF、repo、dataset、binary 和 Office-family adapter；
- Defuddle/AnyDoc 外部 adapter；
- reader/source map/readiness/failure contract；
- 隔离 fixtures。

### Wave 3 — Analysis, evidence and review

- claim/evidence Markdown parser；
- evidence binding、integrity/currency；
- source analysis 和 synthesis；
- review packet、receipt、current-message authorization、stale invalidation。

### Wave 4 — Workbench and hard cutover

- project/idea/method/experiment/discussion/decision/report；
- experiment import 和 factual/judgement separation；
- installer/runtime docs 与 fresh-vault cold acceptance；
- 独立 Issue 中移除旧 15-skill inventory、旧 runtime path 和兼容 surface；
- 不迁移真实旧 workspace。

每个 wave 默认一个 Atomic Issue、一个 delivery branch 和一个 consolidated PR；base 或 contract 变化后重新验证。

## 21. 开源方案参考与取舍

- [Obsidian Help](https://github.com/obsidianmd/obsidian-help)：采用本地文件夹、plain-text Markdown 和可重建 metadata cache 的原则。
- [Foam](https://github.com/foambubble/foam)：采用用户拥有 Markdown、结构和链接，避免工具锁定的原则。
- [ResearchVault](https://github.com/pjastam/ResearchVault)：参考 capture → filter → process 的分层，但不引入后台 canonical 数据库。
- [codex-literature-workflow](https://github.com/ParkerGong/codex-literature-workflow)：参考 manifest、worklog、handoff 和长任务恢复，把机械资料放入 `.research/`。
- [Atlas Mind](https://github.com/Anakior/atlas-mind)：采用 engine 与 Git 中 Markdown content 分离的原则。
- [AnyDoc](https://github.com/firecrawl/anydoc)：采用统一的本地多格式 converter interface，但保持 optional adapter 边界。

不采用：

- AI 未经 review 自动重写用户既有语义页；
- YAML/JSON/数据库 canonical + Markdown 投影；
- 依赖 Obsidian 插件才能解释核心内容；
- 自动执行来源代码或宏；
- 为兼容旧路径继续保留双 owner、双写或逻辑 `kb/...` identity。

## 22. 全局 Definition of Done

- [ ] Shipping inventory 恰好为五个新 skill，外部工具不混算。
- [ ] 产品不再依赖 `kb/`、`record.yaml`、`obsidian/managed/`、旧 CLI 或兼容 alias。
- [ ] Obsidian 无插件打开 workspace root，`Home.md` 和标准 Markdown 链接可用。
- [ ] 所有人类可理解语义只存在于可见 Markdown；隐藏文件没有独占 claim/status/decision。
- [ ] 删除 `.research/index`、cache、logs、locks、`Views/` 和 `.base` 不损失语义并可重建。
- [ ] 用户直接编辑或重命名 Markdown 不被静默覆盖；ID、link 和 stale 检查可恢复一致性。
- [ ] 所有来源先保存 exact bytes；新内容产生新 revision，不覆盖旧 raw。
- [ ] converter 缺失、失败或无 locator 时诚实降级，不伪造 reader/evidence readiness。
- [ ] source revision、artifact digest、locator、quote、claim digest 和 evidence binding 可端到端验证。
- [ ] judgement 都有逐字 evidence；Agent 不自签，receipt 只来自当前用户明确授权。
- [ ] claim/evidence 变化只使相关 receipt stale，reject/defer 不删除上下文。
- [ ] experiment 机械事实与解释分离，重复导入幂等、冲突 fail closed。
- [ ] mutation 使用 explicit targets、原子写、journal、lock、CAS 和精确 checkpoint，绝不 `git add -A`。
- [ ] 外部 adapter 不可用时核心 Markdown 文件合同仍成立。
- [ ] fresh clone 和隔离 workspace 的冷 Agent 能仅凭 tracked design、Issue/PR 和 remote commits 理解当前 wave、限制和下一步。
- [ ] 真实旧 `kb/`、用户 vault、凭据和私有研究材料始终零修改。

## 23. Wave 0 验收边界

本 Wave 只把已经确认的目标固定为 tracked 文件。它不声明下列能力已经存在：

- 五个新 skill 已创建或可发现；
- 新 workspace 已能初始化；
- AnyDoc/Defuddle adapter 已安装；
- evidence/receipt/index/recovery 已实现；
- 旧 15-skill runtime 已删除；
- 用户数据已有迁移工具。

这些实现事实只能由后续 Atomic Issue、remote candidate、测试、PR review 和合并后的代码建立。

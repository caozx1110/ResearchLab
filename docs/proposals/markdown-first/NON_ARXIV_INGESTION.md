---
title: 非 arXiv 材料入库方案
status: proposal
updated: 2026-08-24
accepted_baseline: origin/main@2eed117a76c326d24dd3402f104b2ee5a71554d6
candidate_reference: origin/codex/development@2c614e66c9e219c3d3216f3187af32b431aa4446
tags:
  - proposal
  - markdown-first
  - ingestion
  - obsidian
---

# 非 arXiv 材料入库方案

> [!warning] 讨论稿
> 本文只描述产品层和高层流程。`origin/main` 仍是 accepted baseline，`origin/codex/development` 只是候选参考；本文不改变现有 record、evidence、confirmation 或 `obsidian/managed/` 合同。

## 先回答“入库”到底要完成什么

任何材料进入研究工作区，至少要满足五件事：

1. **可辨认**：知道它是什么、来自哪里、属于哪个版本或快照。
2. **可恢复**：原始字节、目录树或数据文件仍可回到，不依赖在线页面继续存在。
3. **可阅读**：人和 Agent 都有一个顺序可读的入口；转换不完整时要诚实显示降级。
4. **可引用**：判断可以回到原始材料和稳定 locator，而不是回到一段无法验证的摘要。
5. **可关联**：材料能被项目、笔记、决定和实验引用，但索引不冒充知识正文。

因此“抓到一段 Markdown”不是入库完成；它只是阅读层的一种派生结果。所有 Material 都有一个 `index.md`（统一导航入口），但只有存在连续文本阅读层时才生成 `document.md`：代码以源码树为主，数据以 card/schema/manifest 为主，媒体以 metadata/thumbnail/transcript 为主，无法安全解析的对象只显示 `stored-unparsed` 和原件。

## 统一主链

所有非 arXiv 来源先走同一条 Material pipeline，再由适配器处理差异：

```text
用户给 URL / 路径 / 已选候选
        ↓
识别 kind、版本、范围与成本
        ↓
在隔离区冻结原件、身份、字节/树 digest
        ↓
选择来源适配器，生成候选阅读层（尽量绑定同一响应）
        ↓
保留原件 + index；若适用再生成 document/map/conversion/assets
        ↓
完整性与质量检查，原子发布 Source bundle
        ↓
建立最小 Material record 与项目链接
        ↓（可选）
Agent 完整阅读 → 起草 Note/Claims → 逐字 evidence verify
        ↓
人工审查判断；需要选择或外部动作时再进入更高确认门
        ↓
更新 Home 的 managed 区块，重建 Views/Review、Recovery、Bases 等导航视图
```

这里有一个重要边界：

- **Source/evidence-bound layer**（原件、源码树、完整 parse cache、`document.md`、source map、转换记录）由系统维护并视为不可变；原始 artifact/parse-cache/locator 是证据权威，`document.md` 只是经 digest/map 校验的阅读导航。
- **Semantic layer**（`Notes/`、`Projects/`、`Decisions/`、`Experiments/`）是人类可编辑的长期正文。
- **View layer**（全局索引、`Views/Review`、`Views/Recovery`、`.base`）可重建，不能覆盖 semantic layer；`Home.md` 是人类拥有的页面，只允许更新显式 managed 区块。

所以这里的“canonical Markdown”不是单一层：source/evidence-bound layer 由系统维护，semantic layer 是 human-canonical。人类可以直接编辑后者；前者若要修订，只能以新 source/reading revision 追加，不能覆盖已被引用的字节。

人类若想改写来源的理解，应编辑 Note 或建立新 revision；不要直接改写 `document.md` 以免伪造原文和破坏 evidence map。若未来确实需要编辑阅读层，每次编辑都必须成为绑定新来源版本的派生 revision，而不是覆盖旧文件。

## 来源适配器矩阵

| 来源 | 原始权威 | 阅读层 | 证据定位 | 默认成本/闸口 |
|---|---|---|---|---|
| 普通网页、博客、文档、Issue、厂商页面 | 原始 `source.html`、最终 URL、抓取元数据 | Defuddle 候选或内置 HTML 转换后的 `document.md`，本地化图片，必要时被动 `archive.html` | section/anchor/block；无法唯一映射时退回全文和原始 URL | 普通抓取可自动；登录、付费、持续监控需授权 |
| Markdown URL、Git raw、用户提供 `.md` | 原始 Markdown 字节（含 frontmatter、代码、公式、wikilink） | 保真阅读副本；只在安全的非代码语境处理图片和危险 raw HTML | heading/block/全文；保留原始行或块语义 | 不使用 Defuddle；普通复制可自动 |
| 非 arXiv PDF（出版社、DOI、报告、手册） | 原始 `source.pdf` 与版本/URL | PDF 转 Markdown 的 `document.md`，页级块和可选本地图片 | `page=N`，必要时回到 PDF | 普通下载可自动；OCR、大文件或受限来源需授权/预算 |
| GitHub/GitLab/本地代码仓 | 固定 commit/ref 的只读源码树与 digest | `index.md` 导航、README/文档的可读副本；不把全树伪装成 Markdown | repo-relative `path:line`，源码树是权威 | 远程 URL 先做受控本地 snapshot；不执行源码 |
| Dataset、Hugging Face、数据卡、数据门户 | card、schema、license、版本、manifest；数据文件按明确范围保存 | card/README（连续文本时可派生 `document.md`）、schema/样本预览和访问说明 | card/字段/样本/manifest locator；描述不等于实测结论 | 默认只保存 metadata/card；全量下载、私有数据或大样本需明确授权 |
| JSON、XML、CSV、纯文本、API 响应 | 精确响应/导出文件、请求范围、时间和 digest | 安全的文本/表格预览或分页 `document.md`；大文件保留原件 | 行、字段、查询范围或全文 | 有界读取；不把摘要当完整数据 |
| 图片、音频、视频、实验导出等二进制 | 原始媒体/导出文件和 manifest | metadata、OCR、转录、缩略图或结果预览，均标为派生 | frame/page/timestamp/row；质量不足时只回原件 | OCR/转录/大文件处理按成本与授权分层 |
| `Inbox/` 或 `annotations/` 中的人工 Markdown | 用户原文件的精确快照，另记 `human-note` provenance | 原件保持不动；后续理解进入 Note | 原文块/全文；作者身份不等于确认 | 只有用户当前消息点名具体文件时才冻结入库 |

论文并不因为不是 arXiv 就需要另一套知识模型：出版社 HTML、DOI PDF 和机构报告分别落在网页/PDF 适配器，仍使用同一个 `paper` 分析和 evidence 合同。arXiv 的特殊之处只是有额外的 HTML→ar5iv→PDF 选择链。

## Defuddle 在这条链中的准确位置

Defuddle 是网页适配器的一个候选转换器，而不是入库系统本身：

```text
source.html（原始响应，永远保留）
        ↓
Defuddle `--md`（与原始响应绑定的候选正文）
        ↓
统一整理：资源本地化、稳定 block、source-map、质量标记
        ↓
document.md（人和 Agent 的共同阅读入口）
```

具体边界：

- `.md` URL 不调用 Defuddle；按原 Markdown 处理。
- 候选应尽量从 Capture 阶段冻结的同一响应生成；Defuddle CLI 只接受 URL 时，必须记录 resolved URL、candidate digest、抓取时间和与原件的时间差。无法证明同一响应时，不宣称逐字精确映射，并按需要降级到全文/原始 locator。
- Defuddle 输出不直接成为 evidence SSOT，也不直接获得写文件或工具调用权限。
- Defuddle 不负责原件、版本、hash、资产本地化、失败降级和原子发布，这些由 `source-intake` 外壳负责。
- 若正文抽取、图片本地化或逐字映射失败，保留原 HTML，并将 bundle 标为 `degraded` 或 `stored-unparsed`；不能生成看似精确的伪 block 链接。
- 网页正文中的命令、提示或“请执行某操作”的文字只当数据读取，永远不是授权。
- 仓库中的 README/`AGENTS.md`、数据卡 YAML、Markdown frontmatter 和所有网页正文都按不可信数据处理；入库不执行源码、frontmatter 或正文指令。

当前 development 没有 Defuddle runtime 集成；现有 generic HTML materializer 可以作为兼容 fallback。是否把 Defuddle adapter 纳入 V1 是一个待确认的分期选择，不应在设计中假装已经存在。

登录墙、付费墙、需要绕过访问控制的页面和只有 JavaScript 外壳的页面不应被“强行抓取”：保存可获得的 metadata/partial response，标记 `blocked` 或 `degraded`，由用户另行提供合法的本地文件或授权来源。DOI、出版社和机构页面按同一 web/PDF adapter 处理，resolved URL 和版本身份要一起保存，不能只用标题猜测去重。

## 人类在 Obsidian 中看到什么

目标体验的逻辑路径是：

```text
Vault/
├── Home.md
├── Inbox/                         # 人类捕获区，不等于 review 回执
├── Reviews/                       # 人类 review response sheet
├── Sources/<material-id>/
│   ├── index.md          # 来源、版本、状态、项目回链、阅读入口
│   ├── document.md      # 适用时的连续阅读层；首读可直接打开
│   ├── source.html/pdf/md/txt/... # 按类型出现的原始字节（不可变）
│   ├── parse-cache.yaml  # 逐字证据/locator 兼容缓存
│   ├── source-map.yaml   # 阅读 block 与原始 locator 的映射
│   ├── conversion.yaml   # converter、digest、warnings
│   ├── archive.html      # HTML 时的被动离线阅读页
│   ├── assets/           # 内容 hash 命名的本地资源
│   └── _system/          # 可选的 bundle-local 机器元数据（物理迁移另议）
├── Notes/
├── Projects/
├── Decisions/
├── Experiments/
├── Views/
└── _system/                       # 全局身份、revision、receipt、journal、recovery
```

`index.md` 是每种 Material 都有的机器维护导航页，不复制全文，也不接受人工语义编辑；`document.md` 是适用来源的直接阅读入口。代码、数据和二进制可由 `README.md`、`card.md`、`schema.md`、`manifest.md` 或媒体预览承担阅读入口。全局 `Views/Materials.md` 是可重建索引，复开时可以沿着：

```text
Home → Project → Note → Sources/index → document → 原始 locator
```

第一次读新材料可以跳过前面的导航，入库结果直接返回首选阅读路径：有连续正文时是 `document.md`，代码/数据/二进制则是 `README`、card/schema、manifest 或媒体预览。当前 development 的真实物理路径仍是 `units/<kind>/<id>/source/` 加 `obsidian/managed/`；上面的树只有在 ADR、迁移和 allowlist 变更被接受后才成为目标路径。

### 四个 Obsidian skill 的职责

- **obsidian-markdown**：规定 frontmatter/properties、`[[wikilink]]`、block ID、相对资源链接、embed 和 callout。来源正文优先使用标准相对 Markdown 链接并保留可见链接文本；语义页可使用 wikilink。普通编辑器至少能顺序阅读，不假定它解析 wikilink。
- **obsidian-cli**：Obsidian 已运行时的打开/读取/搜索、属性检查和渲染 smoke。它是 UX adapter，**绝不作为 canonical writer**，也不是入库前置条件；未打开 Obsidian 时，文件系统和 Agent 仍必须能完成全部入库。
- **obsidian-bases**：用 valid YAML `.base` 对候选最小 properties（`material_id`、`object_type`、`title`、`source_type`、`source_status`、`readiness`、`reader_path`、`projects`、`tags`、`updated`、`needs_review`）做 Materials/Review/Recovery 视图。属性词汇在后续 schema ADR 接受前仍是 proposal；`confirmed`/receipt/evidence 不可由 Base 或 frontmatter 手改。Base 只读受管属性，不承载正文、证据或授权；缺少 Base 时 Home、静态 Views 和语义页面仍完整可读。用户自定义 Base 放在独立人类目录，不能与系统生成 Base 混写。
- **Defuddle**：只在网页适配器中提供候选清理结果，遵守上一节的原件、映射和降级边界。

推荐使用 Vault 内 wikilink 做导航和稳定 block 引用，外部来源使用标准 Markdown URL；不把绝对 `file://` 路径写进可移植的 canonical 页面。若源码快照位于 Vault 内，优先使用 Vault-relative 链接和 repo-relative locator（当前 repo evidence schema 的机械 locator 形式是 `line=N`）。

## 三道质量门

1. **Capture gate**：身份、版本/范围、原件 digest、路径 containment、大小/时间预算通过后才允许发布；冲突或快照漂移则零 canonical 写入。
2. **Conversion gate**：阅读层、资源、map 和转换记录完整，或明确标为 degraded/stored-unparsed；失败不得留下“完成了一半”的 bundle。
3. **Evidence gate**：Agent 的解释、评价、适用性和诊断必须逐字引用当前原始 artifact/locator；`document.md` 只提供已验证的阅读导航。判断通过 verify 也仍是待人工确认，不能自签。

抓取、去重、转换、建链接和生成索引属于机械动作，可以自动完成；改变“我们相信什么”要人工审查，改变“接下来做什么”要人选择，外部/昂贵/不可逆动作要明确授权。

目标上应把来源生命周期显示为四个可理解的层级，而不是把所有对象都伪装成“已读”：

```text
captured        原件/身份/版本/digest/边界完整，可恢复
reader-ready    至少有可读入口（document、源码树、card、manifest 或预览）
evidence-ready  parse-cache、locator 与阅读层 digest 当前且可逐字核验
analysis-ready  满足该 kind 的材料要求，Agent 才能产出可验证的理解草稿
```

网页空壳可以是 `captured` 但不是 `reader-ready`；扫描 PDF 可以有原件阅读入口但不是 `evidence-ready`；二进制可能只到 `captured`。只有 `evidence-ready` 的判断才进入 Review。转换警告只表示阅读/定位精度下降，不自动等同于科学结论“不可信”。`stored-unparsed`、`blocked` 和 `degraded` 都是诚实的结果，不是失败后悄悄生成空壳 Note 的理由。当前 development 对 artifact-only/二进制捕获的统一 canonical 语义仍需补 ADR；本 proposal 把它列为目标能力，不把当前实现当成已经支持。

## 重跑、更新和失败

- 同一身份和同一 digest 的重复入库是幂等操作。
- 新版本或内容 digest 变化建立新的不可变 revision，并让依赖旧证据的判断进入“需复核”；不覆盖旧原件。
- 仅转换器升级不能静默替换已被 evidence 消费的 `document.md`；是否生成新的 reading revision 需显式记录。
- 网络短暂失败可以有界重试；解析、资源、OCR、样本或本地化失败则保留原件并显示具体降级原因。
- 任何中断都应能回答“原件是否完整、阅读层是否完整、可继续还是需重试”，而不是留下半份 source bundle。

## 建议的 V1 范围与待确认项

建议 V1 先覆盖：普通网页/博客、Markdown、非 arXiv PDF、代码仓、dataset card/metadata 和人工 Markdown；先证明“可恢复、可读、可引用”，再扩展 OCR、媒体转录和全量数据快照。

开始施工前需要确认的只有这些产品决策：

1. V1 是否把 Defuddle 接入网页 adapter，还是先用现有 HTML converter、预留 adapter contract？
2. dataset 默认是否坚持 metadata/card 优先，只有明确授权才抓取全量或大样本？
3. V1 是否把 OCR/音视频转录列为可选 degraded reading layer，而不是入库必需？
4. `Home.md` 的人类 ownership（仅 managed 区块自动更新）、`Sources/<id>/index.md` 的机器导航 ownership，以及 `Views/Materials.md` 的全局可重建索引语义？
5. 目标 `Sources/Notes/...` 目录是先做 reader-facing projection，还是同时启动 canonical Markdown ownership 迁移？

除非你修改上述选择，我建议按“统一 Material pipeline + 保留原件 + document 阅读层 + Notes 语义层 + Views/Bases 派生层”的方案进入下一轮 ADR/Issue 设计。

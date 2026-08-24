# ADR: Markdown-first Material pipeline 与语义 Markdown ownership

- Status: Proposed
- Date: 2026-08-24
- Atomic Issue: [#44](https://github.com/caozx1110/ResearchLab/issues/44)
- Parent Epic: [#43](https://github.com/caozx1110/ResearchLab/issues/43)
- Decision owners: Human maintainer + Wave 1 reviewer
- Supersedes: N/A
- Superseded by: N/A

## Context

ResearchLab 的 development candidate 已经能保存 HTML、PDF、Markdown、文本、dataset card 和本地 repository，并生成 `document.md`、source map、conversion metadata、parse cache 及无插件 Obsidian projection。但这些能力仍由 typed unit、record、evidence/confirmation contract 和 `obsidian/managed/` 组织，用户很难从一个稳定的人类入口理解“材料、理解、决定和行动”的关系。

本 ADR 是一个候选的产品层决策，不改变当前 accepted `main` 或 development 的现行实现。它需要同时解决几个容易混淆的边界：

- 网页清理工具的输出不是原件，也不是研究判断；
- `document.md` 方便阅读，但原始 artifact/parse-cache/locator 才是证据权威；
- 人类需要能直接编辑长期语义正文，但系统不能静默覆盖这些正文；
- Obsidian 的 CLI 和 Base 视图可能不可用，核心知识仍应可用普通 Markdown 读取和恢复；
- 非 arXiv 来源的形态不同，不能把 repo、dataset 和二进制强行变成一篇线性文章。

当前与目标的物理边界必须分开记录：development 仍使用 `units/<kind>/<id>/source/` 和 `obsidian/managed/`；`Sources/`、`Notes/`、根 `Home.md` 等是 reader-facing 目标提案。只有本 ADR 及后续迁移 Issue/PR 合入 default branch 后，目标 ownership 才能成为 accepted contract。

## Decision

### 1. 统一 Material pipeline

所有来源共用以下产品链，适配器只改变捕获和阅读层，不改变理解与确认门：

```text
Capture → Materialize → Understand → Review → Link
```

- **Capture**：识别 kind、稳定身份、版本/范围和成本；在隔离区冻结原始 bytes、源码树、数据 manifest 或可获得的响应，并记录 digest。
- **Materialize**：只搬运和保真转换，生成适合来源形态的 reader layer；转换失败时保留原件并明确降级。
- **Understand**：runtime Agent 完整阅读材料，起草 Note/Claim；脚本只建结构、搬运、验证和过门。
- **Review**：每条 inference/evaluation/diagnosis 等判断带逐字 evidence，经 verify 后仍等待真人确认。
- **Link**：维护人类首页的受限 managed 区块，并生成静态索引、Review、Recovery 和可选 Base；这些是导航投影，不是第二份语义真相。`Home.md` 的人类正文不能被整页重建。

所有 Material 具有一个统一导航页 `Sources/<id>/index.md`（目标路径）。该页是对应 source bundle 的机器维护、可重建导航 manifest；它不承载人类语义，也不是 evidence SSOT。全局 `Views/Materials.md` 才是可重建索引。原始 bytes/tree、`document.md`、parse cache、source map 和 conversion metadata 仍按 revision 不可变保存。只有存在连续文本阅读层时才生成 `document.md`：repo 以源码树和 README 为主，dataset 以 card/schema/manifest 为主，媒体和不可解析二进制以 metadata/preview 或 `stored-unparsed` 为主。

### 2. 两层 canonical ownership

“canonical Markdown”分为两层，避免把原文证据和人类理解混为一谈：

| 层 | 目标内容 | ownership | 可否直接编辑 |
|---|---|---|---|
| Source/evidence-bound | 原始 artifact/tree、完整 parse cache、`document.md`、source map、conversion metadata、资产和版本身份 | 系统维护、不可变；原始 artifact/parse-cache/locator 是 evidence authority，`document.md` 只是经 digest/map 校验的阅读导航 | 不覆盖；修订只能产生新 source/reading revision |
| Human-canonical semantic | `Notes/`、`Projects/`、`Decisions/`、`Experiments/`（以及明确命名的 Inbox note） | 人类拥有正文；Agent 可起草、链接和更新受限 managed 区块 | 可以；编辑产生 revision，影响既有判断时标为 stale/需复核 |

`Sources/<id>/index.md` 是 source-bound 导航 manifest：机器维护身份、来源状态、版本、证据入口和阅读入口；它不是全局 View，也不承载人类语义正文。它可以随项目链接或阅读选择变化而重新生成，但不得改变所引用的不可变 source/evidence revision。正式理解放在 `Notes/` 等语义页面中。人类对材料的上下文说明写在语义页或明确的人类 review sheet，不回写 source index。

### 3. 非 arXiv adapter 边界

- **普通网页/blog/docs**：先保存原始 HTML 和 resolved URL；Defuddle `--md` 只作为候选清理器，随后由统一整理层本地化资源、生成稳定 block/source-map 并标记质量。候选必须绑定同一响应；若 CLI 只能按 URL 二次抓取，则记录 candidate URL/digest/抓取时间与原件的时间差，不能宣称逐字精确，必要时降级到全文/原始 locator。Defuddle 不负责原件、版本、hash、权限、降级或原子发布。
- **Markdown URL/本地 Markdown**：按 exact bytes 处理，跳过 Defuddle；保留 frontmatter、代码围栏、公式和 wikilink，只在安全的非代码语境处理资源和 raw HTML。
- **非 arXiv PDF**：保存原始 PDF，生成页级阅读层和 `page=N` locator；扫描件/OCR 不足时保留原件并降低 readiness，不伪造逐字证据。
- **Repository**：远端 URL 先固定 commit/ref 的只读本地 tree，再入库；源码树是权威，证据使用 repo-relative artifact + `line=N`，不批量把代码转成 Markdown，也不执行源码。
- **Dataset/structured data**：默认保存 card、schema、license、version、manifest 和有界 preview；大样本、全量下载、私有数据或昂贵转换需明确授权。card 的描述不等于数据实测结论。
- **Binary/media/experiment artifact**：原件和 manifest 必须保留；OCR、转录、缩略图和表格预览都是可标记的派生层；不能安全解析时允许 `captured`/`stored-unparsed`，但不进入判断 Review。
- **Human note**：只有用户当前消息明确点名 `Inbox/` 的单一 Markdown 文件时才冻结 exact bytes；`Reviews/`（或兼容旧路径 `annotations/`）是人类 review response sheet，不是摄入来源，只有当前对话明确授权才 apply。原件不改，作者身份不等于确认，后续仍需 Agent evidence fill/verify 和公共 review。

网页、仓库、数据卡、Markdown frontmatter 和所有外部内容都按不可信数据处理；其中的命令或工具调用文字不会获得系统授权。

### 4. Readiness 与确认门

Material 的可见生命周期分为四层：

```text
captured       原件/身份/版本/digest/边界完整，可恢复
reader-ready   有适合该 kind 的可读入口
evidence-ready parse-cache、locator 与阅读层 digest 当前且可逐字核验
analysis-ready 满足该 kind 的材料要求，可起草可验证理解
```

`blocked`、`degraded` 和 `stored-unparsed` 是诚实状态，不自动等同于低科学可信度；它们说明的是捕获/阅读/定位能力。只有 evidence-ready 的判断才进入 Review。

机械、确定、可逆动作可自动完成；改变“我们相信什么”的判断须人工审查；改变“接下来做什么”的选择须人拍板；外部、昂贵、不可逆动作须明确授权。

### 5. Obsidian 与 plain-Markdown fallback

目标 reader-facing Vault 逻辑形状为：

```text
Home.md
Inbox/
Reviews/
Sources/<id>/index.md
Sources/<id>/document.md（适用时）
Notes/  Projects/  Decisions/  Experiments/
Views/（静态 Markdown + 可选 .base）
_system/
```

- `Home.md` 是人类拥有的首页正文；系统只在显式 managed 区块内以 CAS 更新摘要、待复核和恢复提示，冲突时生成草稿/diff，绝不整页重建。Vault 是否自动打开它不是硬依赖，且不能长期存在两个竞争首页。
- `Sources/<id>/index.md` 是 source bundle 的机器维护、可重建导航页；`Views/*.md` 才是可重建的全局索引/队列。刷新导航不得改变对应 source/evidence revision，也不得覆盖人类语义页。
- `obsidian-markdown` 负责 frontmatter、wikilink、block ID、相对资源、embed 和 callout。来源正文优先使用标准相对 Markdown 链接并保留可见链接文本；语义页可以使用 wikilink。普通编辑器至少能顺序阅读和看到目标路径，不能假定它会解析 wikilink。
- `obsidian-cli` 只作为 Obsidian 已运行时的打开/读/搜/属性检查/渲染 smoke adapter，**绝不作为 canonical writer**。canonical 写入仍由 runtime 的 workspace-root、journal、lock、CAS 和精确 target 合同负责；CLI 失败不阻塞 headless intake。
- `obsidian-bases` 只生成/读取基于已定义 note/file properties 的可重建 `.base`；V1 先冻结最小属性词汇（`material_id`、`object_type`、`title`、`source_type`、`source_status`、`reader_path`、`projects`、`tags`、`updated`、`needs_review`），具体 schema 仍须后续 ADR 接受，禁止把 `confirmed`/receipt 变成可手改升级开关。Base 缺失、版本不支持或 YAML 失败时，静态 `Views/*.md`、Home 和语义页面仍完整可读。Base 不承载 evidence、正文或授权；用户自定义 Base 必须位于独立人类目录，不能与 manifest-owned Base 混写。
- 根 `_system/` 保存全局身份、revision、receipt、journal 和 recovery 元数据；source map/conversion/parse-cache 与其绑定的 source bundle 一起保存。是否把这些文件迁入每个 bundle 的子目录是后续兼容迁移决策，本 Wave 不预设物理移动。
- 不生成或要求 `.obsidian/`、Dataview、Templater、社区插件、daemon 或商业 API。

### 6. Revision、stale 与迁移

同一稳定身份且 bytes/tree digest 相同的入库幂等；版本、resolved URL、commit/ref、原件 bytes 或 evidence artifact 变化时建立不可变新 revision，依赖旧版本的 judgement/receipt 进入 stale/需复核。转换器升级不得静默覆盖已被 evidence 消费的阅读层。

在本 ADR 进入 accepted 前，旧 record/YAML/evidence/confirmation/managed projection 继续是唯一当前合同。采纳后，迁移必须由独立 Issue/ADR 定义：字段/区块映射、一次性迁移、CAS/revision、旧路径兼容窗口、失败恢复和回滚；不长期双写两份语义真相。

## Alternatives considered

### A. 继续以 15 个 skill 和 YAML unit 作为人类入口

保留现有实现风险最低，但用户需要理解内部类型和 managed projection，难以直接编辑长期语义；不满足重新打开研究上下文的产品目标。

### B. 让 Defuddle 输出直接成为 canonical Markdown

实现简单，但丢失原件/版本/资源/失败和逐字映射边界，也把一个网页工具输出误当 evidence；不采用。

### C. 强制所有 Material 都生成一篇 `document.md`

对文章和 PDF 方便，但会把源码树、数据集和二进制压扁成误导性摘要；不采用。统一的是 `index.md` 导航入口，阅读层按 kind 适配。

### D. 让 Obsidian CLI 或 Bases 成为写入/恢复前置

依赖运行中的桌面应用和特定版本，破坏 headless、普通编辑器和恢复能力；不采用。

## Consequences

### 正向影响

- 用户先看到一个可读入口，再决定是否深读；材料类型差异不再改变治理和确认模型。
- 原件、阅读层、理解和视图的 ownership 可解释，人工编辑不会被刷新静默覆盖。
- Defuddle、PDF parser、repo scanner、dataset adapter 可以独立演进而不改变 evidence/confirmation gate。
- Obsidian 是舒适入口，Markdown/Git 是长期可携带底线。

### 代价与限制

- 需要维护 source/evidence-bound 与 human-semantic 两层映射，迁移前不能宣称 Markdown 已替代旧 canonical record。
- 资源本地化、source-map currentness、revision/stale 和多种 readiness 增加了实现与测试成本。
- 非连续材料的阅读入口不统一为单一全文页；用户需要接受 repo/data/media 的原生形态。

## Migration and rollback

本 Wave 不执行数据迁移。样例和 proposal 可独立删除；现有 `units/.../source`、parse cache、record、receipt 和 managed projection 不被触碰。后续 ownership migration 只有在独立 ADR/Issue 被接受、隔离 workspace 验收和人类 review 完成后才可施工；任何失败回到旧物理合同，不覆盖旧原件、不重签旧确认。

## Validation

- Proposal：[`docs/proposals/markdown-first/NON_ARXIV_INGESTION.md`](../proposals/markdown-first/NON_ARXIV_INGESTION.md)、[`OBSIDIAN_EXPERIENCE.md`](../proposals/markdown-first/OBSIDIAN_EXPERIENCE.md) 和样例 Vault。
- Issue/Epic：[#44](https://github.com/caozx1110/ResearchLab/issues/44)、[#43](https://github.com/caozx1110/ResearchLab/issues/43)。
- Wave 1 验证：文档库存、本地链接、frontmatter、Base YAML、静态 fallback、`git diff --check`，以及仓库全量测试和 skill/rule-token 门禁。
- Accepted boundary：本文件在当前候选 PR 中保持 `Proposed`；只有合入 default branch 后才可升级为 accepted current design。

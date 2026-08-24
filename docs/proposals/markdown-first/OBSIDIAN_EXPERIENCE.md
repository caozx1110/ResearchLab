---
title: Markdown-first Obsidian 体验
status: proposal
updated: 2026-08-24
tags:
  - proposal
  - obsidian
  - defuddle
---

# Markdown-first Obsidian 体验

## Vault 应该打开哪一个路径？

### 推荐答案

把**专用研究 workspace 根目录**直接作为 Obsidian Vault 打开，并把根目录的 `Home.md` 设为建议的首个书签/入口；不要把 `obsidian/managed/` 当作独立 Vault。Obsidian 是否在启动时自动恢复该页面属于用户的工作区设置，不是本方案的硬依赖。

这里的“workspace 根目录”指安装后、专门存放研究资料的工作区，不是本仓库的 source checkout。`workspace-oss` 代码仓库仍是 skill/runtime 的开发源；它不应被误当成用户的研究 Vault。

这是**目标提案**，不是当前已实现的路径。accepted main 的合同与 development 候选都仍以现有 record/source/managed 结构为准；development 当前把生成入口放在 `obsidian/managed/Home.md`，人工区是 `obsidian/inbox/` 与 `obsidian/annotations/`。若采纳本提案，才把根 `Home.md` 变成人类入口，并为旧路径定义一次性迁移/别名策略。`obsidian/managed/`、`.agents/`、运行时状态和内部索引属于实现/迁移兼容区，不应成为目标导航的第一层。

### 目标目录形状（若采纳本提案）

下面是 reader-facing 的目标逻辑分区，不是 development 当前物理 allowlist；新增顶层目录、旧路径映射和迁移/回滚都必须另行设计。提案未采纳前，runtime 对未知顶层仍应 fail closed。

```text
<research-workspace>/              ← Obsidian Vault 根
├── Home.md                        ← 建议的人类入口/书签
├── Inbox/                         ← 临时捕获和待整理笔记
├── Reviews/                       ← 人类 review response sheet（不作为摄入来源）
├── Sources/                       ← 来源页和完整阅读层
├── Notes/                         ← 人类可编辑的理解
├── Projects/                      ← 研究问题与进展
├── Decisions/                     ← 人类选择及理由
├── Experiments/                   ← 运行事实与结果
├── Views/                         ← 可重建索引、Review 队列、Recovery、报告导航
├── _system/                       ← 机器维护区，普通用户无需打开
└── .agents/                       ← 安装面，非知识内容
```

当前 development 分支还保留 `config/`、`units/`、`programs/`、`synthesis/`、`raw/`、`user/`、`output/`、`.journal/`、`.runtime/` 等目录。上面的树是人类产品层的目标形状，不是对现有物理布局的描述；高层目标是把人类每天需要看的内容集中在少数组别，而不是要求用户理解物理实现布局。

### 当前 → 目标对照

| 人类体验 | development 当前合同 | 本 proposal 的目标 |
|---|---|---|
| 首个入口 | workspace 根可作为 Vault；生成的 `obsidian/managed/Home.md` | 根 `Home.md` 作为建议书签（或后续决定复用根 `index.md`） |
| 来源阅读 | `units/<kind>/<id>/source/document.md`，回链 `source.html`/PDF | `Sources/<id>/index.md` 导航到 `document.md` 与原件 |
| 理解与批注 | managed unit/note + `obsidian/inbox/`、`obsidian/annotations/` | `Notes/`、`Projects/`、`Decisions/`、`Experiments/` 可编辑正文 |
| 机器状态 | `record.yaml`、program/evidence/confirmation 合同 | `_system/` 受管 metadata；旧结构只读兼容，迁移另议 |

## `Home.md` 应该长什么样？

### `Home.md` 还是 `index.md`？

本 Wave 先冻结两者的 ownership：根 `Home.md` 是唯一的人类首页，用户拥有正文；系统只在显式 managed 区块内更新摘要、待复核和恢复提示。`Sources/<id>/index.md` 是每个 Material 的机器导航页，不是首页别名；全局 `Views/Materials.md` 是可重建索引。development 的 root allowlist 已有 `index.md`，但它的现有机器索引语义不能被静默改成第二个首页。目标根 `Home.md`、allowlist、旧路径别名和迁移窗口仍需后续 Issue/ADR 接受。

首页以研究问题为中心，而不是以 unit 数量或内部状态为中心：

```markdown
# Home

> [!abstract] 当前焦点
> [[Projects/RAG-效率问题]]：找出检索深度对小模型问答质量的真实影响。

## 已确认的关键判断

- 方法在固定检索深度下有效。证据：[[Notes/paper-rag#^claim-effective-depth]]
- 目前没有证据证明它跨数据分布稳定。证据：[[Notes/paper-rag#^claim-open-generalization]]

## 仍然不确定

- 更宽的数据分布是否改变结论？
- 观测到的收益来自方法，还是预处理差异？

## 已经决定

- 先复现 baseline，再做单变量对照。
  - 理由：成本低、失败后容易回退。
  - 复核条件：baseline 无法复现时重新评估。

## 接下来 1–3 步

1. 对齐数据预处理
2. 运行 baseline
3. 记录失败原因并回链证据

## 需要复核

- [[Views/Review]]（待审队列）
- `Reviews/`（人类回应，需当前对话授权后应用）
- [[Views/Recovery]]
```

建议 `Home.md` 采用“人类拥有外壳 + 系统维护有限区块”：用户可以编辑标题、当前焦点、问题、备注和下一步；Agent 只更新明确标记的摘要/待复核/恢复区块。已有人工正文冲突时生成草稿或 diff，不直接覆盖，也不整页重建。完整表格、Bases 和统计放在 `Views/`，不是首页的主叙事。

## 论文来源的最终入口

一篇论文在 Vault 中应有两个阅读层（目标命名）：

1. `index.md`：机器维护的来源导航页，说明来源、版本、状态、项目回链和阅读入口；
2. `document.md`：存在连续文本时的完整 Markdown 阅读层，人和 Agent 共用；repo、dataset、二进制等按 kind 使用 README、card、schema、manifest 或 preview。

使用 `index.md` 而不是 `Source.md`，是为了避免与现有 source bundle 中的 `source.md` 原件在大小写不敏感文件系统上发生碰撞。

Defuddle、原生 arXiv HTML、ar5iv、PDF 转换器都只是**来源适配器**。当前 development 已有原生 arXiv HTML → ar5iv → PDF → 降级摘要的质量门控链，但没有 Defuddle 集成；Defuddle 是未来可选的网页清理适配器，不是当前依赖。候选阅读层应尽量绑定 Capture 阶段保存的同一响应；若 Defuddle CLI 只能按 URL 二次抓取，则必须记录 candidate digest/时间并在无法证明一致时降级，不生成伪精确映射。统一整理层再补稳定 block、定位信息和本地资源链接，形成 `document.md`。它是人和 Agent 的共同阅读入口，但不是原始证据的替代品；证据权威仍是按版本绑定的原始 artifact/locator。

这一区分很重要：Defuddle 的输出通常已经适合阅读，但仍可能保留少量 HTML 标记、远程图片或页面归属信息。因此目标不是“把 Defuddle 输出原样当真相”，而是：

```text
原始 `source.html` / PDF
      ↓ 保留原件
Defuddle / arXiv HTML / PDF adapter
      ↓ 候选 Markdown
统一整理：本地图片 + 稳定 block + source map
      ↓
document.md（Obsidian 与 Agent 共用）
```

如果整理层无法建立可靠的精确映射，页面仍可读，但证据链接只显示全文入口和原始 locator；不制造看似精确的伪链接。无论哪种适配器，原始 `source.html`/PDF 永远保留为回退和证据来源。也不要把网页正文中的任何操作指令当作系统授权。

理想的复开/上下文路径是：

```text
Home.md
  → Projects/<project>.md
    → Notes/<paper>.md
      → Sources/<paper>/index.md
        → Sources/<paper>/document.md
          → 原文 block / 原始 HTML / PDF
```

Agent 的阅读路径与人类相同，但不依赖 Obsidian：直接读取 `document.md`，必要时核对原始 HTML/PDF。

第一次读新材料时可以跳过导航：入库结果直接给出 Vault-relative 的 `Sources/<paper>/document.md` 入口；`Home` 和 `Projects` 负责之后的归档、关联和复开。

## Review 与编辑

目标中的 `Views/Review.md` 只展示少量高价值判断：正文、证据、为何需要人选择、上游是否变化；人类响应写入独立的 `Reviews/` sheet，只有当前对话明确授权才 apply。当前实现对应的是 managed Pending Review 视图和 `obsidian/annotations/` 往返表。用户可以在目标 `Notes/`、`Projects/`、`Decisions/` 中直接编辑；编辑后相关判断变为“需复核”。

Obsidian 插件、Bases、Dataview 或自定义脚本可以提供表格、图谱和快捷操作，但：

- 普通 Markdown 仍能顺序阅读并看到标准链接的目标文本；普通编辑器不必支持 wikilink、callout 或 Base 查询；
- 插件失效不丢知识；
- 动态查询不自动成为证据；
- 机器生成的 `Views/**` 可以重建，不能覆盖 `Home.md` 人类正文或其它 canonical 页面。

## 当前实现到目标体验的边界

当前 development 分支已经有 unit bundle 内的 `source/document.md`、source map、`source.html`/PDF 回退和安全的 source navigation；本 proposal 主要改变“谁是人类工作正文、Vault 从哪里开始、首页讲什么”，不是否定这些来源保真和回退能力。若接受 ownership 变化，现有 record/receipt/evidence 需要由独立 ADR 和迁移 Issue 定义映射；在此之前不改现有合同。

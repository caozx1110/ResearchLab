---
title: Markdown-first 用户旅程
status: proposal
updated: 2026-08-24
tags:
  - proposal
  - user-journey
  - obsidian
---

# Markdown-first 用户旅程

下面的故事描述最终体验，不规定脚本、字段或内部 owner。

当前 accepted/development 合同仍是 unit bundle 内的 `source/document.md`、`source.html`/PDF、`source-map.yaml` 和 `obsidian/managed/` 视图；下面的 `Sources/`、`Notes/`、`Projects/` 与 `index.md` 是本方案采纳后的目标人类层路径，不是现行物理路径。

## 旅程一：从 arXiv 链接到可读、可引用的论文

用户把一个 arXiv 页面发给 Agent：

> 请读这篇论文，先保存原文，再告诉我它对当前项目有什么用。

系统按来源能力选择阅读适配器：

1. 优先使用 arXiv 原生 HTML；必要时尝试 ar5iv；
2. 当前实现没有 Defuddle 集成；未来若用户明确要求或网页需要清理，可选用 [Defuddle skill](https://github.com/kepano/obsidian-skills/blob/main/skills/defuddle) 提取候选 Markdown；
3. HTML 质量不足时回退 PDF，再回退到明确标注为降级的摘要页；
4. 无论使用哪种适配器，都保存原始 `source.html`/PDF 或原文件；连续文本来源再生成完整 `document.md`，repo、dataset、二进制等使用各自的 README/card/schema/manifest/preview；若只能形成降级阅读 stub，必须明确标注并保留原件回退。

这里的 `document.md` 不是某个外部工具的原样输出，而是经过统一整理、资源本地化和定位检查后的阅读层。Defuddle 可以作为未来候选提取器；它不可用时，原生 arXiv HTML、ar5iv 或 PDF 仍能走同一条路径。网页和候选 Markdown 中的文字是外部数据，不会获得工具调用或修改权限。

用户在 Obsidian 中看到的来源目录类似：

下面是简化的人类阅读视图；机器维护的来源身份、转换说明、source map 和完整性记录仍属于系统区，不要求用户手工维护。

```text
Sources/
└── <paper-unit-id>/
    ├── index.md        # 机器维护导航：标题、来源、版本、项目链接、阅读入口
    ├── document.md     # 完整 Markdown 阅读层；Agent 也直接读这一份
    ├── source.html     # 原始响应（只读回退）
    ├── source.pdf      # PDF 原件（若有）
    ├── archive.html    # 被动离线阅读页（可选）
    └── assets/         # 本地图片和其它阅读资源
```

`index.md` 不复制全文，只回答“这是什么、从哪里来、下一步读什么”；它是机器维护的来源导航，不是人类语义笔记：

```markdown
# 论文：示例标题

> [!info] 阅读入口
> - [[document]]：完整 Markdown（来源 bundle 内）
> - [[source.html]]：原始网页（来源 bundle 内）
> - 版本：arXiv v2（展示版本；canonical work identity 仍是 versionless arXiv ID）

## 与当前项目的关系

- 相关项目：[[Projects/RAG-效率问题]]
- 待回答：它的收益是否依赖特定数据分布？
```

Agent 不需要启动 Obsidian，也不需要再次访问网页；它直接阅读 `document.md`，必要时回到原始 HTML/PDF 核对上下文。证据权威仍是原始 artifact/locator；`document.md` 只在当前、唯一、可验证的映射下提供读者导航。无法安全精确定位时，诚实降级到全文入口和原始 locator。

首次阅读不必先经过完整导航链：入库完成后，人和 Agent 都可以直接打开/读取 Vault-relative 的 `Sources/<paper-unit-id>/document.md`；若材料没有连续文本，则打开其 index 中标出的 kind-specific reader。`Home → Project → Note → Source` 是复开和理解上下文的路径，不应成为第一次读原文的前置步骤。

## 旅程二：从阅读到人类可编辑的理解

Agent 在目标 `Notes/` 建立一页论文笔记，正文先讲清楚问题、方法、结果、边界和可迁移洞见；每个重要 Claim 附一个短证据入口。证据仍以原始 artifact/locator 为权威，Markdown block 只提供经过 currentness 检查的阅读导航。

```text
Sources/.../document.md
        ↓ 逐字 evidence
Notes/paper-rag.md
        ↓ 人类审查
Projects/rag-efficiency.md
```

人可以直接改写笔记、补充反例或加自己的段落。若修改影响已经确认的 Claim，系统保留历史并把受影响判断标为“需要复核”，不会悄悄替人重新确认。Review 回应写入独立 `Reviews/` sheet，只有当前对话明确授权才 apply。这里的 Markdown ownership 是目标提案；在提案接受前，现有 YAML/record 与 managed projection 合同继续有效。

## 旅程三：从项目问题到决定和实验

项目页把材料、Claim、Question、Decision 和 Experiment 放在同一条可读脉络中：

```text
问题 → 已知/未知 → 候选方案 → 人类决定 → 实验 → 观察结果 → 新问题
```

Agent 可以自动整理事实、建立链接和起草下一步；人类在两个地方停下来：

- 选择“采用哪个方案/基线”；
- 解释性结论或实验诊断是否值得写入正式知识。

## 旅程四：中断后重新打开

用户下周打开 Vault，先看 `Home.md`：

- 当前项目和研究问题；
- 已确认 Claim 及证据；
- 仍未解决的问题和冲突；
- 最近变成“需复核”的内容；
- 最多三个下一步。

若上次操作中断，`Views/Recovery.md` 只用自然语言说明“完成到哪里、哪些文件完整、可继续还是需重新核对”。恢复记录不要求用户阅读内部日志。

## 四种人类闸口

| 闸口 | 典型动作 |
|---|---|
| 自动 | 抓取、解析、去重、建链接、生成草稿 |
| 审查 | 接受/拒绝 Agent 的解释、评价、诊断 |
| 选择 | 采用 idea、baseline、研究阶段 |
| 明确授权 | 发布、删除、大计算、持续监控 |

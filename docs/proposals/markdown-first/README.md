---
title: Markdown-first / Obsidian-first 产品方案讨论稿
status: proposal
updated: 2026-08-24
accepted_baseline: origin/main@2eed117a76c326d24dd3402f104b2ee5a71554d6
candidate_reference: origin/codex/development@2c614e66c9e219c3d3216f3187af32b431aa4446
tags:
  - proposal
  - markdown-first
  - obsidian
---

# Markdown-first / Obsidian-first 产品方案讨论稿

> [!warning] Proposal 状态
> 这是面向人类评审的高层方案，不是当前 accepted contract，也不替代 `docs/DESIGN.md`、schema、GitHub Issue 或 PR。实现、迁移和兼容问题留到方案确认后再拆分。

在本 proposal 被 ADR/Issue/PR 明确接受以前，`origin/codex/development` 的 YAML/record、program、evidence、confirmation 和 `obsidian/managed/` 合同继续有效；本目录不授权双写，也不要求现有 workspace 迁移。

## 本轮已确认的方向

- canonical Markdown 页面允许人直接编辑；受影响的判断进入重新审查，而不是被静默覆盖。
- 确认门按风险分层：机械动作自动，改变认识的判断需审查，改变行动的选择需拍板，外部/昂贵/不可逆动作需明确授权。
- Obsidian 以无插件可读为底线，插件和 Bases 只提供增强视图，不成为知识可读或恢复的前置条件；`Home.md` 是人类拥有的首页，`Views/**` 才是可重建视图。

## 先区分当前事实与目标提案

本 proposal 以 [`origin/codex/development@2c614e6`](https://github.com/caozx1110/ResearchLab/commit/2c614e66c9e219c3d3216f3187af32b431aa4446) 作为讨论参考；它领先于当前 accepted 的 [`origin/main@2eed117`](https://github.com/caozx1110/ResearchLab/commit/2eed117a76c326d24dd3402f104b2ee5a71554d6)。按仓库协作规则，只有合入 default branch 的设计才是 accepted contract。development 已包含 workspace-root、论文正文优先、source navigation 和 arXiv HTML-first 等候选基础能力；当前用户入口仍主要是结构化 canonical 数据加 `obsidian/managed/` 派生视图。本目录描述的是可能替换它的人类产品层。

本提案的目标是重新定义人类产品层：

```text
材料 → 可读来源页 → 人类可编辑的理解 → 项目/决定/行动 → 可重建视图
```

内部 skill 仍可拆分，但用户不需要以 skill 名称理解系统。

## 文档地图

- [VISION.md](VISION.md)：目标、承诺、非目标和成功指标。
- [USER_JOURNEYS.md](USER_JOURNEYS.md)：从 arXiv 链接到笔记、决定、实验和恢复的完整故事。
- [KNOWLEDGE_MODEL.md](KNOWLEDGE_MODEL.md)：最小对象、证据、编辑、状态和失效模型。
- [OBSIDIAN_EXPERIENCE.md](OBSIDIAN_EXPERIENCE.md)：Vault 路径、目录、页面样子以及 Defuddle/arXiv 来源入口。
- [NON_ARXIV_INGESTION.md](NON_ARXIV_INGESTION.md)：普通网页、PDF、代码仓、数据集、文件和人工 Markdown 的统一入库链与适配器边界。
- [examples/vault/](examples/vault/)：不依赖插件的 reader-facing 样例 Vault；先打开 `Home.md`，再按材料类型进入 `Sources/`。每个 `Sources/<id>/index.md` 是机器维护导航，首读入口按 kind 可能是 `document.md`、README、card/schema/manifest 或 preview。

Wave 1 的 Proposed ADR 位于 [`docs/decisions/0005-markdown-first-material-and-semantic-ownership.md`](../../decisions/0005-markdown-first-material-and-semantic-ownership.md)，只有合入 default branch 后才会成为 accepted decision。

## 一句话愿景

打开 Obsidian 的 `Home.md`（或从 Vault 根目录的书签进入），研究者在五分钟内能回答：

> 我在解决什么？证据支持什么？哪里仍不确定？已经决定什么？现在最值得做哪一件事？

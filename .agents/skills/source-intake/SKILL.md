---
name: source-intake
description: 把 paper / repo / dataset / blog source 先做 staging，再做去重与轻量 record 入库，不直接替代深分析。
---

# Source Intake

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#discovery-retrieval` · `#ownership` · `#runtime`

当一个 source 第一次进入系统，或者需要先做外部搜索候选收集时，使用这个 skill。

## 负责范围

1. 备份 raw source，不原地改写；对 paper、HTML、Markdown 和文本同时生成完整 `source/document.md` 阅读层、`source-map.yaml`、`conversion.yaml` 与本地图片资产。
2. 先做 source search staging，再决定是否 materialize 为 canonical unit。
3. 去重、轻量 record 创建、topic / tag / pool 初始归档。
4. 把深分析路由给 `paper-analyst`、`repo-analyst`、`dataset-analyst`、`blog-analyst`。
5. 新建 unit 默认使用紧凑型 id，例如 `p-example-bf86ee46`、`r-example-dadda683`。
6. 对 standalone paper add，会按 runtime preferences 自动决定是否预热 parse cache、准备 quick-screen；完整笔记必须等 runtime agent 填充并 verify `paper_type` 后才准备。在 `kb ingest` 链中由 dispatcher 独占同一顺序。

`literature-scout` 是本 skill 之前的薄发现 owner：它只把 OpenAlex fact metadata 写入同一 source-search staging，不创建 canonical paper，也不判断 relevance/quality。收到 scout stage 后，本 skill 继续拥有候选 review、去重与正式 materialization；相同查询重跑必须保留人工 status/note。引用量只能显示为来源 metadata。

`document.md` 是人和 agent 的首选完整阅读材料，图片使用相对链接指向 hash-addressed `source/assets/`。已有 Markdown 的 front matter、跨行/块代码、标题与图片按语法上下文保留或本地化，非代码 raw HTML 被动化，纯文本按字面显示；HTML 的公式、复杂表格和多图结构不得为追求统一语法而静默丢失。整套 document/map/conversion/archive/assets 先完成冲突与格式检查再发布。`parse-cache.yaml` 继续承担兼容的逐字证据与 locator 协议；Markdown 转换降级或细节缺失时回退到保存的原格式。转换只搬运和保真，不解释文字、公式或图片，也不产生研究判断。Repository 源码保持为可验证的本地源码树，不批量转写成 Markdown。

收到远程代码仓库 URL 时，不要直接把 URL 交给 repo intake。Agent 先在安全临时目录建立范围明确的只读本地 checkout/snapshot，确认它是可遍历的普通文件树，再以该本地根目录入库；对用户只说明正在本地化代码来源，不泄漏内部命令。底层若拒绝未本地化的远程 repo，agent 应继续完成本地化和重试，不得留下只有网页快照、无法扫描源码的 repo unit。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py search --kind paper --query "retrieval augmented generation" --candidate-url https://arxiv.org/abs/2501.00001 --candidate-title "Example Paper"
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py show-stage --stage-id paper-search-retrieval-augmented-generation-xxxxxxx
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind paper --source kb/raw/paper.pdf --maturity lightweight
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind paper --source kb/raw/paper.pdf --maturity complete
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind repo --stage-id repo-search-example-xxxxxxx --candidate-id repo-search-example-xxxxxxx-ab12cd --pool candidate-tools
```

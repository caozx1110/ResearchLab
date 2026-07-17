---
name: source-intake
description: 把 paper / repo / blog source 先做 staging，再做去重与轻量 record 入库，不直接替代深分析。
---

# Source Intake

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#ownership` · `#runtime`

当一个 source 第一次进入系统，或者需要先做外部搜索候选收集时，使用这个 skill。

## 负责范围

1. 备份 raw source，不原地改写。
2. 先做 source search staging，再决定是否 materialize 为 canonical unit。
3. 去重、轻量 record 创建、topic / tag / pool 初始归档。
4. 把深分析路由给 `paper-analyst`、`repo-analyst`、`blog-analyst`。
5. 新建 unit 默认使用紧凑型 id，例如 `p-example-bf86ee46`、`r-example-dadda683`。
6. 对 paper intake，会按 runtime preferences 自动决定是否预热 parse cache、先做 quick-screen、再继续完整笔记。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py search --kind paper --query "retrieval augmented generation" --candidate-url https://arxiv.org/abs/2501.00001 --candidate-title "Example Paper"
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py show-stage --stage-id paper-search-retrieval-augmented-generation-xxxxxxx
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind paper --source kb/raw/paper.pdf --maturity lightweight
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind paper --source kb/raw/paper.pdf --maturity complete
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind repo --stage-id repo-search-example-xxxxxxx --candidate-id repo-search-example-xxxxxxx-ab12cd --pool candidate-tools
```

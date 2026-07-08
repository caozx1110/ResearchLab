---
name: literature-synthesizer
description: 负责跨 paper / repo / blog / idea 的 survey、taxonomy、topic 与 candidate pool 级综合整理。
---

# Literature Synthesizer

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#config-files` · `#ownership` · `#runtime`

当任务是在多个知识单元之间做综述、趋势、taxonomy、topic map 或 pool review，而不是分析单个 source 时，使用这个 skill。

## 负责范围

1. 按 query / topic / tag / pool 选取证据集。
2. 产出 survey、review 与 taxonomy 视图。
3. 把 topic / tag / pool 分布整理成可重开的综合文档。
4. 明确区分 Observed 与 Inferred。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/literature-synthesizer/scripts/synthesize.py survey --field "vision-language-action"
${RESEARCH_PYTHON:-python3} .agents/skills/literature-synthesizer/scripts/synthesize.py survey --field "humanoid recovery" --pool current-reading
${RESEARCH_PYTHON:-python3} .agents/skills/literature-synthesizer/scripts/synthesize.py taxonomy --topic humanoid-robotics
${RESEARCH_PYTHON:-python3} .agents/skills/literature-synthesizer/scripts/synthesize.py review --query "open-world recovery" --tag vla
```

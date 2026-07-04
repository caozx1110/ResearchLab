---
name: idea-workbench
description: 负责 v2 idea unit 的生成、多候选管理、review、review-assist、显式选择与归档。
---

# Idea Workbench

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#config-files` · `#confirmation-gate`

当任务是把研究方向收敛成可评审、可比较、可显式选择的 idea unit 时，使用这个 skill。

## 负责范围

1. 捕获单个 idea，或围绕一个主题生成多个候选 idea。
2. 做 novelty / feasibility / evidence gap 分析。
3. 生成 review-ready idea card 与 review-assist。
4. 仅在显式命令下执行 `select-best` 或 `select`。
5. 若传入 legacy idea id，脚本会显式提示 canonical id 与 canonical record 路径。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py capture --title "latent world model for whole-body control"
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py generate --title "humanoid recovery policy" --count 4 --pool current-ideas
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py analyze --idea-id i-physics-aware-fb-compatible-f7e91d86
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py review --idea-id i-physics-aware-fb-compatible-f7e91d86
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py review-assist --pool current-ideas
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py select --idea-id i-physics-aware-fb-compatible-f7e91d86
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py select-best --pool current-ideas
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py archive --idea-id i-physics-aware-fb-compatible-f7e91d86
```

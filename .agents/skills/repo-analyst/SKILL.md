---
name: repo-analyst
description: 负责 v2 repo unit 的 structure scan、capability mapping、reuse judgement 与确认门控。
---

# Repo Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#confirmation-gate`

当任务是在分析某个 repository knowledge unit，而不是只做 source intake 时，使用这个 skill。

## 负责范围

1. 扫描仓库结构、入口、配置系统、数据流线索。
2. 生成 capability map，明确适合与不适合的 pipeline 角色。
3. 生成完整 repo note scaffold。
4. 默认把 AI judgement 保持在 `pending_user_confirmation`。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py scan-structure --repo-id r-openvla-dadda683
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py map-capability --repo-id r-openvla-dadda683
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py complete-note --repo-id r-openvla-dadda683
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py confirm --repo-id r-openvla-dadda683 --confirmed-by czx --evidence kb/units/repos/r-openvla-dadda683/repo-note.md
```

---
name: knowledge-base-manager
description: 管理 v2 knowledge base 的统一 schema、索引、链接、taxonomy/topic/pool 治理与生命周期推进。
---

# Knowledge Base Manager

当任务是在维护 `kb/units/` 这层知识单元协议本身，而不是在深读某一篇 paper / repo / blog 时，使用这个 skill。

## 负责范围

1. 初始化 v2 目录与共享治理文件。
2. 维护统一 `record.yaml` schema，并支持批量 schema refresh。
3. 刷新 `kb/index.yaml` / `kb/index.md`。
4. 治理 topic / tag / candidate pool，并回写 `kb/config/` 下的 catalog。
5. 维护 links 与 lifecycle promotion。
6. 维护紧凑型 unit id 规范，避免把整句标题塞进目录名。

## 约束

- AI judgement 相关字段默认仍保持 `pending_user_confirmation`。
- topic / tag / pool / summary 属于可覆盖治理层；history 和 link 仍保留变更痕迹。
- 不在这里做 paper / repo 的深分析，深分析交给对应 analyst。
- `kb.py lint` 也会检查 program/unit 双向链接，以及常见 YAML duplicate-key 风险。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py init
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py lint
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py compact-ids
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py compact-ids --apply
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py refresh-schema --kind paper
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py govern --all
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py govern --id p-openvla-bf86ee46 --topic humanoid-robotics --tag vla --pool current-reading
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py rebuild-governance
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py query --query "whole body control" --pool current-reading
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py link --from-id p-openvla-bf86ee46 --to-id i-physics-aware-f7e91d86 --relation inspired
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py promote --id i-physics-aware-f7e91d86 --status selected --confirmation-status confirmed
```

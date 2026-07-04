---
name: knowledge-base-manager
description: 管理 v2 knowledge base 的统一 schema、索引、链接、taxonomy/topic/pool 治理与生命周期推进。
---

# Knowledge Base Manager

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#config-files` · `#ownership` · `#confirmation-gate`
>
> 治理权：本 skill 拥有 `kb/units/<kind>/record.yaml`、`kb/config/candidate-pools.yaml`、`kb/config/topic-taxonomy.yaml` 的最终写权。`research-config-manager` 只提供 seed / policy 输入，不直接改 taxonomy 与 pool 结构。

当任务是在维护 `kb/units/` 这层知识单元协议本身，而不是在深读某一篇 paper / repo / blog 时，使用这个 skill。

## How to read kb/

`kb/` 目录的顶层语义：

| 目录 | 内容 | 主写入 skill |
|---|---|---|
| `kb/units/<kind>/<id>/` | 单个 paper / repo / blog / idea / experiment unit（`record.yaml` + 旁路文件） | source-intake、`<kind>`-analyst、本 skill |
| `kb/programs/<program-id>/` | 一个研究 program 的 state.yaml、README、workflow/、design/ | research-orchestrator |
| `kb/synthesis/` | 跨多 unit 的综述、survey、source-search staging、wiki 笔记 | literature-synthesizer、source-intake、wiki-adapter |
| `kb/output/` | 对外产出（周报、review、PPT 素材） | report-author |
| `kb/user/` | 人面向入口页（current-state, reading-list, browser snapshot），**read-only** | research-navigator |
| `kb/config/` | taxonomy / pool / runtime-preferences 等系统配置 | 本 skill（taxonomy/pool）、research-config-manager（runtime） |
| `kb/raw/` | 备份的原始 source（PDF、repo clone），不应手改 | source-intake |
| `kb/memory/` | skill-evolution 等长期备忘 | skill-evolution-advisor |

入口顺序：新用户先看 `kb/index.md`（全局索引）→ `kb/user/current-state.md`（当前程序）→ 进入感兴趣的 program 或 unit。详见 `research-navigator` 的 `First-time use`。

## 负责范围

1. 初始化 v2 目录与共享治理文件。
2. 维护统一 `record.yaml` schema，并支持批量 schema refresh。
3. 刷新 `kb/index.yaml` / `kb/index.md`。
4. 治理 topic / tag / candidate pool，并回写 `kb/config/` 下的 catalog。
5. 维护 links 与 lifecycle promotion。
6. 维护紧凑型 unit id 规范，避免把整句标题塞进目录名。
7. 管理 `kb/` 嵌套 Git 仓库，以及 `kb/raw/` / `kb/output/` 存储布局收口。

## 约束

- AI judgement 相关字段默认仍保持 `pending_user_confirmation`。
- topic / tag / pool / summary 属于可覆盖治理层；history 和 link 仍保留变更痕迹。
- 不在这里做 paper / repo 的深分析，深分析交给对应 analyst。
- `kb.py lint` 也会检查 program/unit 双向链接，以及常见 YAML duplicate-key 风险。
- **公开契约：所有 unit 写入必须经过 `lib/research/v2.py.validate_write(record)`。**
  - `write_record()` 自动调用，外部 writer 脚本如果直接 `write_yaml_if_changed` 跳过 `write_record`，必须自行调用 `validate_write`。
  - AI 推断 / 评估 / user_opinion 类字段（包含在 `information_types`），或 `source.kind == "ai"`，对应 `confirmation_status` 必须是 `pending_user_confirmation` 或 `rejected`，且 `needs_human_confirmation == True`。
  - 默认非严格模式仅 stderr 警告，便于增量改造；`RESEARCH_VALIDATE_STRICT=1` 切换为严格模式，违规时 `SystemExit`。
  - `kb.py lint` 在严格语义下汇总所有违约 record。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py init
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py storage-sync
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py git-init
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py git-status
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py git-log --limit 10
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py git-checkpoint --message "milestone: weekly refresh"
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py lint
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py index
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py compact-ids
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py compact-ids --apply
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py refresh-schema --kind paper
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py govern --all
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py govern --id p-openvla-bf86ee46 --topic humanoid-robotics --tag vla --pool current-reading
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py rebuild-governance
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py query --query "whole body control" --pool current-reading
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py review-queue --kind paper --limit 20
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py link --from-id p-openvla-bf86ee46 --to-id i-physics-aware-f7e91d86 --relation inspired
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py promote --id i-physics-aware-f7e91d86 --status selected --confirmation-status confirmed --confirmed-by czx --evidence kb/programs/open-world-vla/decision-log.md
```

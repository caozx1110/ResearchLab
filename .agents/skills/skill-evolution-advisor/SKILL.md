---
name: skill-evolution-advisor
description: 经验 + skill 演化记忆：capture lightweight learnings, recall confirmed habits/gotchas, record skill defects for user review, and generate retrospective improvement prompts.
---

# Skill Evolution Advisor

Use this skill when a real workflow exposes friction in the research system, when the user corrects the agent, or when lightweight memory should capture a confirmed habit, recurring issue, or skill defect.

## Workflow

1. For lightweight memory, log one short learning and leave it `pending` until user review.
2. Recall confirmed user preferences and recurring issues at session start.
3. Keep `skill-defect` entries record-only; do not auto-edit skills or roadmap files from them.
4. For deeper retrospectives, record which skills were used, separate observed friction from inferred causes, and generate an AI-ready patch prompt.

## Commands

Lightweight learnings:

```bash
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py log --category recurring-issue --text "..." --source agent
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py recall --kind all --limit 5
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py recall --kind defects
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py review --id lrn-20260705-001 --status confirmed
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py promote --id lrn-20260705-001
```

Deep retrospective:

```bash
python3 .agents/skills/skill-evolution-advisor/scripts/create_retrospective.py --slug routing-gap --skill paper-analyst --target-skill research-orchestrator --task-summary "..." --observed-issue "..." --suggestion "..." --stdout-prompt --root kb/memory/skill-evolution
```

默认落盘路径为 `kb/memory/skill-evolution/retrospectives/<timestamp>-<slug>.md`；`--stdout-prompt` 会在写入后同时打印可交给后续 agent 的改进 prompt。

## 研究价值验收（eval_research_value.py）

只读的研究价值度量工具（G5 基准，方向文档 `temp/RESEARCH_VALUE_EVAL_DESIGN.md`）。它**不改**任何治理 / confirmation gate / 检索算法 / program state；唯一写入是自己在 `kb/eval/research-value/reports/` 下的报告。用两个真实 program 的题库量化系统"能不能有据地答"，可复跑对比。

- **Tier-1（已自动化）**：检索召回@5/@10、接地率（gold fact 是否真在其 source unit 的 note/parse-cache 里）、来源分布（手工 REWRITTEN note vs 脚本产物）、空-program 对照（humanoid 无挂载单元时的幻觉风险面）、H1 门控完整性（confirmed/auto_confirmed 但核心内容为空的单元）。
- **Tier-2（规格 + 人工示范，未全量自动化）**：完整答案质量，见 `kb/eval/research-value/TIER2_SPEC.md`（answer agent → grader agent 按 rubric 打分 + 护栏 + 3 道手工示范）。

```bash
# 首选 YAML+PDF backend 齐全的 runtime（接地率仅在 PDF backend 可用时可比）
RESEARCH_PYTHON=/path/to/venv/bin/python \
  python3 .agents/skills/skill-evolution-advisor/scripts/eval_research_value.py --tier1
python3 .agents/skills/skill-evolution-advisor/scripts/eval_research_value.py --tier1 --program physics-aware-fb-z-space
python3 .agents/skills/skill-evolution-advisor/scripts/eval_research_value.py --gate-integrity   # 只跑 H1 扫盘
python3 .agents/skills/skill-evolution-advisor/scripts/eval_research_value.py --tier1 --json      # 结构化输出供 CI/diff
```

数据集在 `kb/eval/research-value/dataset/*.yaml`（每题 gold 从 kb/raw 真实 PDF / repo 源码 / program state 起草，综合题 gold_status 恒为 `pending_user_confirmation`）。报告落在 `kb/eval/research-value/reports/<UTC>-tier1.md`。

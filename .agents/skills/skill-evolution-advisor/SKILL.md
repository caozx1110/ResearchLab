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

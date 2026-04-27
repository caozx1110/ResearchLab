---
name: skill-evolution-advisor
description: Review the v2 research skills after real usage, identify routing gaps, schema friction, missing scripts, or duplicated responsibilities, and generate concise retrospective notes plus actionable improvement prompts.
---

# Skill Evolution Advisor

Use this skill after a real workflow exposes friction in the v2 research system.

## Workflow

1. Record which v2 skills were used or should have been used.
2. Separate observed friction from inferred causes.
3. Generate a small retrospective note and an AI-ready patch prompt.
4. Prefer routing, schema, or validation fixes over adding more overlapping skills.

## Command

```bash
python3 .agents/skills/skill-evolution-advisor/scripts/create_retrospective.py --slug routing-gap --skill paper-analyst --target-skill research-orchestrator --task-summary "..." --observed-issue "..." --suggestion "..."
```

---
name: skill-evolution-advisor
description: 经验 + skill 演化记忆：capture lightweight learnings, local redacted diagnostic issues, confirmed habits/gotchas, and confirmation-gated retrospective improvement prompts.
---

# Skill Evolution Advisor

Preference contract: explicitly neutral with an empty eligible catalog. Governance and redacted diagnostics remain deterministic owner constraints rather than soft research preferences.

Use this skill when a real workflow exposes friction in the research system, when the user corrects the agent, or when lightweight memory should capture a confirmed habit, recurring issue, or skill defect.

## Workflow

1. For lightweight memory, log one short learning and leave it `pending` until user review.
2. Do not recall or broadcast the full memory at session start. Confirmed habits that should affect work are promoted to the canonical preference profile; each routed consumer then receives only its task-eligible selected subset. Recall recurring issues only for an explicit memory/diagnostic task.
3. Keep `skill-defect` entries record-only; do not auto-edit skills or roadmap files from them.
4. For deeper retrospectives, record which skills were used, separate observed friction from inferred causes, and generate an AI-ready patch prompt.
5. When the user explicitly asks to remember a failure, record one local redacted diagnostic issue even if automatic diagnostics are off.
6. For automatic failures, read the effective workspace/per-skill policy first. `errors-only` is deterministic capture only; `developer` may add a short Agent retrospective only within the configured task budget.
7. Never store raw stdout/stderr, traceback, user message, secret, environment value, absolute path, paper/raw/evidence text, or upload anything. A defect remains record-only until a developer separately changes code.

## Natural-language interaction

Ordinary users do not need a new pseudo CLI. Interpret requests such as “记下刚才的问题”“列出待复审的 skill 问题”“把这条问题标为已解决”“生成本地脱敏预览” and use the owner operations privately. Export preview requires explicit authorization in the current user message. Summarize outcomes in natural language; do not reveal owner commands, flags, issue paths, fingerprints, or raw context.

Automatic runtime capture is best-effort and must never replace the original business exit status. If diagnostic recording itself fails, preserve the original operation result and let recovery restore the diagnostic file.

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

Local diagnostics (owner-only; never paste these commands into user-visible output):

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py policy --skill paper-analyst
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py record --category skill-defect --severity medium --skill paper-analyst --summary "short safe summary" --source user
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py list --status pending
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py review --id diag-... --status resolved
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py export-preview --authorized
```

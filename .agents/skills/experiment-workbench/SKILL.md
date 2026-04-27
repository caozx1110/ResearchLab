---
name: experiment-workbench
description: Manage v2 experiment units, including plans, classified run logs, follow-ups, diagnosis categories, and confirmation-gated experiment conclusions.
---

# Experiment Workbench

Use this skill for structured experiment memory rather than one-off chat summaries.

## Workflow

1. Create the experiment record with program and idea context.
2. Log each run into a durable `run-log` with outcome and classification tags.
3. Track follow-up actions separately from diagnosis so execution debt does not disappear into prose.
4. Keep diagnosis categories explicit and `pending_user_confirmation` by default.
5. Emit reporting events when a plan, run, follow-up, or diagnosis matters to program reporting.

## Shared Contract

- `run-log.yaml` stores factual execution memory; `diagnoses.yaml` stores inference/evaluation and should remain confirmation-gated.
- Follow-ups are actionable work items, not conclusions.
- Diagnosis categories should distinguish at least method / implementation / data / evaluation / resource / environment / process / unknown.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py plan --title "baseline parity" --program-id my-program --idea-id idea-foo
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py log-run --experiment-id experiment-foo --result-summary "baseline failed on eval slice" --outcome failed --classification implementation
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py follow-up --experiment-id experiment-foo --action "check dataset path rewrite" --category implementation --priority high
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py diagnose --experiment-id experiment-foo --summary "Likely data / implementation mix-up" --category data --category implementation
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py confirm --experiment-id experiment-foo
```

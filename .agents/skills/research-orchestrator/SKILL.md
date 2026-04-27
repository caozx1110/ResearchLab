---
name: research-orchestrator
description: Orchestrate v2 research programs under `kb/programs/`, including program state, open questions, evidence requests, decision logs, reporting events, and skill routing.
---

# Research Orchestrator

Use this skill to anchor work to a concrete research program.

## Workflow

1. Create or reopen a program under `kb/programs/<program-id>/`.
2. Keep `state.yaml` aligned with workflow counts and selected context.
3. Persist `workflow/open-questions.yaml`, `workflow/evidence-requests.yaml`, `workflow/decision-log.md`, and `workflow/reporting-events.yaml`.
4. Route source work to `source-intake`, analysis to analyst skills, experiments to `experiment-workbench`, and reports to `report-author`.
5. Keep user constraints and resource boundaries visible in the program state.
6. Program writes are serialized per program; `attach-unit` also backfills the unit-side `program_ids`.

## Shared Contract

- Program coordination artifacts are durable inputs for later reopen, not chat-only summaries.
- Decision records may cite evidence, but if rationale contains AI judgement it should stay `pending_user_confirmation` unless the user explicitly confirms it.
- `report-author` should read from `workflow/reporting-events.yaml`, so important state changes must emit reporting events.
- Script-generated timestamps are stored in UTC.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py init-program --program-id open-world-vla --question "..." --goal "..."
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py set-stage --program-id open-world-vla --stage literature-review
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py add-open-question --program-id open-world-vla --question "What evidence is still missing?"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py request-evidence --program-id open-world-vla --question "Can repo-X reproduce baseline?" --needed "Need baseline parity logs"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py log-decision --program-id open-world-vla --decision "Choose repo-X as baseline host" --rationale "Best overlap with current validation path"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py add-reporting-event --program-id open-world-vla --title "Baseline host chosen" --summary "Repo-X becomes the default baseline host"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py status --program-id open-world-vla
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py route --task "分析新论文是否值得细读"
```

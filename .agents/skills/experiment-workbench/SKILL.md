---
name: experiment-workbench
description: Manage core experiment units, including plans, classified run logs, follow-ups, diagnosis categories, and confirmation-gated experiment conclusions.
---

# Experiment Workbench

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#experiment-files` · `#program-files` · `#confirmation-gate` · `#runtime`

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
- Metrics are keyed by name and stored as `{name, value, unit, direction}`. The typed form is `name=value[unit]:direction`, for example `success_rate=0.82[ratio]:higher-better`. Directions are `higher-better`, `lower-better`, `neutral`, or `unknown`.
- A legacy bare `name=value` remains accepted. Numeric values become floats; non-numeric values remain strings with a warning.
- Every claimed artifact is checked when the run is logged. Artifact entries contain `path`, `status` (`present` or `missing`), `generated`, and `kind` when present; missing claims remain visible and emit a warning.
- Runs may be tagged `baseline` or `milestone`. Every later run stores per-metric comparisons against the last run, the configured recent-run window, and all persistent anchors, including numeric delta and direction-aware `better` / `worse` results.
- Diagnosis remains agent judgement. The script only attaches factual `comparison_context` containing recent runs plus all baseline/milestone anchors; it never generates a diagnosis from those facts.
- A diagnosis requires agent-authored canonical `claims`. Every claim must pass the shared claim-structure gate and every evidence quote must be verified verbatim against this experiment unit's own `run-log.yaml` or `runs/run-NNN.md`; cross-unit, missing, or fabricated evidence is rejected before any diagnosis write. Claims remain `pending_user_confirmation`.
- If diagnosis is requested without claims, the script writes an explicit `diagnosis-fill.yaml` with `status: awaiting_agent_fill` and does not append a diagnosis, mutate the canonical diagnosis, or emit a judgement event. The Agent fills that scaffold and repeats verification.
- Diagnosis reporting events bind the experiment subject, canonical claim ids, content digest, and verification receipt. Confirmation emits a second bound event; a name such as `experiment-confirmed` alone is never trusted.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py plan --title "baseline parity" --program-id my-program --idea-id idea-foo
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py log-run --experiment-id experiment-foo --result-summary "baseline failed on eval slice" --outcome failed --classification implementation
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py follow-up --experiment-id experiment-foo --action "check dataset path rewrite" --category implementation --priority high
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py diagnose --experiment-id experiment-foo --summary "Likely data / implementation mix-up" --category data --category implementation
${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py confirm --experiment-id experiment-foo --confirmed-by research-lead --evidence kb/programs/example-program/experiments/phase-feedback.md
```

## Phase Plan / Feedback Integration (added 2026-05-13)

When a program runs under the **phase-by-phase iterative workflow** (see `research-orchestrator` skill `Phase-by-Phase Iterative Development Workflow`), `experiment-workbench` is the durable home for **per-run execution records** that feed the phase-level feedback report.

### Run-log ↔ Phase feedback mapping

| Phase plan section | experiment-workbench artifact |
|---|---|
| Plan §X "Convergence criteria" | one `run-log` entry per training/eval run; `outcome` ∈ {success, partial, failed, blocked, inconclusive} |
| Plan §X "Experimental Arms Registry" | one `run-log` per arm × seed; record the arm in `--change`, `--tested-hypothesis`, or artifacts |
| Phase feedback §2 "Final metrics" | metrics captured as `--metric key=value` in run logs, then aggregated in the phase feedback report |
| Phase feedback §3 "Ablation decisions" | derived in the feedback report by comparing run-log entries within each arm |
| Phase feedback §4 "Surprises" | `diagnoses.yaml` entries with categories such as method / implementation / data / evaluation / resource / environment / process / unknown |
| Phase feedback §5 "Open issues" | `follow-up` items, `category=implementation` or `unknown` |

### Recommended workflow for phase executor agents

1. Create a parent experiment unit per phase: `experiment.py plan --title "phase-1-track-a" --program-id <pid> --idea-id <iid>`
2. For each training run: `experiment.py log-run` with outcome + classification; use classification for issue category, not arm name
3. For each unexpected behavior: `experiment.py diagnose --category unknown` (becomes feedback §4)
4. For each implementation issue blocking next step: `experiment.py follow-up --priority high` (becomes feedback §5)
5. When phase converges: aggregate run-logs into the phase feedback report (per master plan §11)
6. `experiment.py confirm` after user approves phase outcome

### Standard feedback report file path

Per `research-orchestrator` workflow:

```
runs/{phase-id}/feedback-to-main-agent-{YYYY-MM-DD}.md
```

This file is the **single hand-off artifact** to the main agent (user-facing AI). The main agent uses it to update program state. Without this file, no state advancement happens.

### Confirmation gating

Per shared contract, all AI judgements stay `pending_user_confirmation`. Phase executor agents:
- can mark `run-log.outcome` as factual (pass/fail observed)
- must keep `diagnoses` confirmation-gated
- must keep recommended winners (ablation §3 of feedback) marked as `pending_user_confirmation` until user accepts

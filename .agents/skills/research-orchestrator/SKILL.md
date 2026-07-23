---
name: research-orchestrator
description: Orchestrate research programs under `kb/programs/`, including program state, open questions, evidence requests, decision logs, reporting events, and skill routing.
---

# Research Orchestrator

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#unit-record` · `#ownership` · `#confirmation-gate` · `#runtime`

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
- Any promised resumable deliverable, such as a batch survey or technical roadmap, must be written into a program `next_actions` entry before the conversation says `kb next` can resume it. Persisted program actions outrank loose maintenance suggestions; completed units do not generate work merely because a refresh ran.
- Decision records require non-empty agent-authored canonical claims with verified evidence and stay `pending_user_confirmation` until the user explicitly confirms the current receipt. A call without claims only prepares `workflow/decision-fill.yaml` in `awaiting_agent_fill`; it does not append a decision, update `last_decision`, or emit a reportable decision event.
- Public review routes an accepted decision to private `confirm-decision` with current-message authorization, or a rejected decision to private `reject-decision` without requiring a signature. Rejection changes the canonical decision and all of its claims to `rejected`, updates `last_decision`, and never creates a confirmed reporting event.
- Pending and confirmed decision events both bind the canonical decision subject, claim ids, content digest, and verification receipt. Report consumers must resolve that binding; an event name or `confirmation_status` string cannot manufacture trust.
- `report-author` should read from `workflow/reporting-events.yaml`, so important state changes must emit reporting events.
- Script-generated timestamps are stored in UTC.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py init-program --program-id example-program --question "..." --goal "..."
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py set-stage --program-id example-program --stage literature-review
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py add-next-action --program-id example-program --action "生成横向综述与技术路线图"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py resolve-next-action --program-id example-program --action "生成横向综述与技术路线图"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py add-open-question --program-id example-program --question "What evidence is still missing?"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py answer-question --program-id example-program --question-id example-program-open-questions-001 --answer "Evidence now exists in run logs"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py request-evidence --program-id example-program --question "Can repo-X reproduce baseline?" --needed "Need baseline parity logs"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py resolve-evidence --program-id example-program --evidence-id example-program-evidence-requests-001 --result "Baseline parity log attached"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py drop-question --program-id example-program --question-id example-program-open-questions-002 --reason "Superseded"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py drop-evidence --program-id example-program --evidence-id example-program-evidence-requests-002 --reason "No longer blocking"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py log-decision --program-id example-program --decision "Choose repo-X as baseline host" --rationale "Best overlap with current validation path"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py add-reporting-event --program-id example-program --title "Baseline host chosen" --summary "Repo-X becomes the default baseline host"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py attach-unit --program-id example-program --unit-id p-example-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py query-program --program-id example-program --question "当前还缺哪些 evidence?"
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py status --program-id example-program
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py dashboard --limit 10
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py next --limit 5
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py route --task "分析新论文是否值得细读"
```

## Phase-by-Phase Iterative Development Workflow (added 2026-05-13)

For programs that execute in multiple phases with **executor sub-agents producing experiments + feedback**, use this iterative protocol.

### Phase plan structure standard

Each phase plan file under `kb/programs/<program-id>/design/<phase>-plan-<date>.md` MUST contain **in this order**:

1. **High-level goal** — what this phase produces; how it relates to program vision (1 paragraph)
2. **Inputs / Dependencies** — what previous phases / artifacts this phase reads (table)
3. **Outputs / Deliverables** — concrete files / metrics / decisions this phase produces (table)
4. **Methodology** — architecture, loss, training schedule (code-or-equation level detail)
5. **Experimental Arms Registry** — default + alternative arms with switch variable + decision criterion (per program meta-principle "保留所有可选路径")
6. **Evaluation protocol** — metrics, eval set, frequency
7. **Convergence criteria** — pass / fail thresholds (yaml block, one-to-one to feedback metric table)
8. **Resource budget** — wall-clock, GPU-h, sim envs
9. **Failure handling** — known symptoms + actions (table)
10. **Run grid** — concrete GPU assignment + seeds + config tags
11. **Executor → Main Agent Feedback Protocol** — reference master plan's standardized format; specify phase-specific metric table + ablation table + recommendation options
12. **Out of scope**

Every plan must explicitly mark `pending_user_confirmation` until user explicitly confirms.

### Iterative cycle

```
user launches executor sub-agent for phase N
    ↓
executor reads phase-N plan + dependent artifacts
    ↓
executor runs experiments per plan §X.X (default + ablation arms)
    ↓
executor produces standardized feedback report (per master plan §11)
    ↓
user delivers feedback report to main agent (the user-facing AI assistant)
    ↓
main agent:
  1. Validate metrics vs artifacts (refuse claims without backing)
  2. Update state.yaml (stage / next_actions / last_decision / counts)
  3. Append decision-log.md with feedback path + decisions
  4. Update open-questions.yaml with new OQs from feedback §6
  5. Update reporting-events.yaml if milestone-worthy
  6. Decide: proceed / revise plan / branch / halt
  7. Notify user with summary + recommendation
    ↓
user reviews + approves next step (or pivots)
    ↓
cycle: launch phase N+1 executor agent
```

### Main agent obligations per cycle

- **Validate**: cross-check feedback metric values against eval YAMLs in artifact inventory; never auto-accept claimed metrics.
- **Propagate**: every accepted phase outcome must update `state.yaml` + `decision-log.md` + relevant workflow YAMLs.
- **Mark pending**: AI judgements (winner selection, arm choice, OQ resolution) remain `pending_user_confirmation` unless user explicitly approves.
- **Surface new OQs**: explicitly relay new open questions to user; do not bury them.
- **Recommend** with reasoning: when suggesting next phase / revisions / fallback, cite the specific feedback report sections supporting the recommendation.

### Standard feedback report format

Defined in the program's `master-execution-plan-{date}.md §11`. Sections (in order):
1. Phase status (pass / partial / fail / blow_up)
2. Final metrics table (one-to-one with plan convergence criteria)
3. Ablation arms decisions (one-to-one with plan Experimental Arms Registry)
4. Surprises / unexpected observations
5. Open issues identified during execution
6. New open questions (OQ-XX format)
7. Artifacts inventory
8. Recommendation for next phase

This format is **mandatory** for all phase executors. Main agent refuses to advance state without all sections present.

### Cross-phase Experimental Arms Registry

A program-level master plan should maintain a `§N.X Experimental Arms Registry` table aggregating default + alternatives across all phases. This enables quick lookup of all open design choices. Each row: `Phase | Arm ID | Default | Alternatives | Switch Variable | Decision Criterion`.

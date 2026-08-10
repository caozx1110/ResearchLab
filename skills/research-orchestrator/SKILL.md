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
4. Treat route keywords as factual hints only. For ambiguous, negated, or multi-step requests, the runtime Agent authors an ordered route over the complete formal owner catalog; the script validates formal membership and dependency order but never limits the Agent to keyword hits or decides the workflow semantically. Explicit skill/workflow improvement language belongs to `skill-evolution-advisor`, not a generic discussion hit; if the request independently includes a research-route archive, preserve both owners in an ordered decision. The `kb-cli` adapter is not a routable owner; source-unit analysis routes to the `unit-analyst` facade while its internal implementation keeps the historical owner identity.
5. Keep user constraints and resource boundaries visible in the program state.
6. Program writes are serialized per program; `attach-unit` also backfills the unit-side `program_ids`.
7. Treat cross-program planning as an Agent judgement over a complete factual candidate snapshot. Scripts enumerate and validate; they never assign semantic value scores or choose a winner.

## Shared Contract

- Program coordination artifacts are durable inputs for later reopen, not chat-only summaries.
- An Agent-authored `RouteDecision` is a closed record with the current task digest, positive and negated intents, ordered steps, rationale, formal owners, dependencies, and governance gates. The verifier checks shape/current binding/order only; it never derives intents from keywords or grades the rationale.
- Any promised resumable deliverable, such as a batch survey or technical roadmap, must be written into a program `next_actions` entry before the conversation says `kb next` can resume it. Persisted program actions and loose maintenance suggestions are peer candidates for the Agent to compare; neither category has a fixed priority. Completed units do not generate work merely because a refresh ran.
- Decision records require non-empty agent-authored canonical claims with verified evidence and stay `pending_user_confirmation` until the user explicitly confirms the current receipt. A call without claims only prepares `workflow/decision-fill.yaml` in `awaiting_agent_fill`; it does not append a decision, update `last_decision`, or emit a reportable decision event.
- Public review routes an accepted decision to private `confirm-decision` with current-message authorization, or a rejected decision to private `reject-decision` without requiring a signature. Rejection changes the canonical decision and all of its claims to `rejected`, updates `last_decision`, and never creates a confirmed reporting event.
- Pending and confirmed decision events both bind the canonical decision subject, claim ids, content digest, and verification receipt. Report consumers must resolve that binding; an event name or `confirmation_status` string cannot manufacture trust.
- `report-author` should read from `workflow/reporting-events.yaml`, so important state changes must emit reporting events.
- Script-generated timestamps are stored in UTC.
- `kb next` is a pure read. If no current portfolio decision exists, or its candidate/state/preference binding is stale, request an Agent planning pass instead of falling back to a fixed priority rule.
- A `PortfolioDecision` is Agent-filled and must bind `decision_id`, the current `candidate_snapshot_digest`, one or more `selected_action_ids`, non-empty `rationale`, `expected_information_gain`, `cost_and_risk`, a current `research-orchestrator + plan` effective `preference_selection_id`, and a timezone-aware `decided_at`. The script checks shape and current bindings only; it never grades the rationale.
- Candidate snapshots contain every legal persisted next action plus open evidence requests, open questions, ready Agent work, every cross-owner pending judgement, resumable composite survey state, loose-unit maintenance, due monitor subscriptions, and unresolved completed-monitor outcomes. `blocking`, declared priority, and due time are facts for the Agent, not an automatic winner. Terminal programs produce no ordinary program-work candidates.
- Planning-required JSON carries no compatibility winner list: `items` is empty until a current `PortfolioDecision` exists. A side judgement binds its exact review snapshot; a completed-monitor outcome binds run revision, run digest, and outcome digest until it receives a durable disposition.
- Portfolio history is append-only. State, evidence, unit content, candidate membership, or effective-preference changes make the latest bound decision stale and require the Agent to plan again.
- A human gate is never safe to continue automatically. A planning choice that itself asserts a research winner, baseline, idea, causal conclusion, or other judgement must reference a verified program decision and continue through the existing user-confirmation gate; portfolio planning cannot confirm it.

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
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py prepare-next-selection --json
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py verify-next-selection --selection-file /tmp/portfolio-decision.yaml --json
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py record-next-selection --selection-file /tmp/portfolio-decision.yaml
${RESEARCH_PYTHON:-python3} .agents/skills/research-orchestrator/scripts/orchestrate.py route --task "按论文类型完成新论文深读"
```

## Optional experiment-heavy programs

When a program actually involves phased experiments, route experiment planning, run logs, diagnosis, and conclusion gates to `experiment-workbench`. The Agent may persist phase-specific inputs, outputs, resource budgets, evaluation criteria, failure handling, and artifact inventories as program actions or design notes. GPU allocation, training schedules, simulation environments, ablations, and executor-agent feedback formats are domain-specific options—not mandatory requirements for ordinary research programs. Any winner, causal conclusion, or phase-advance judgement still needs evidence and the existing user-confirmation gate.

## 启动澄清（Agent 用）

- 新建 program 还是续接已有？默认续接同题 program。
- 研究问题与本阶段目标一句话？默认从当前对话提炼后复述确认。
- 现在要挂接哪些 unit？默认稍后随分析逐步 attach。

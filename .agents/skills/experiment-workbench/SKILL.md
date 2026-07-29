---
name: experiment-workbench
description: Manage core experiment units, including plans, classified run logs, follow-ups, diagnosis categories, and confirmation-gated experiment conclusions.
---

# Experiment Workbench

开始计划、运行或诊断前遵循 workspace 统一 task-scoped preference 合同：按具体 operation 记录并加载 effective selection；资源、约束和自动执行边界作为 hard 项必须保留，其他 soft 项只在 Agent 明确选入本任务时应用。

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#experiment-files` · `#program-files` · `#confirmation-gate` · `#runtime`

Use this skill for structured experiment memory rather than one-off chat summaries.

## Workflow

1. Create the experiment record with program and idea context.
2. Log each run into a durable `run-log` with outcome and classification tags, or import a bounded export batch when the user provides one.
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
- Every run requires an explicit config/input revision. Its canonical fingerprint binds experiment id, normalized tested hypothesis, sorted normalized changes, metric schema (`name/unit/direction`, never observed values), contained artifact identities, and the config revision. Result prose, timestamps, observed values, and seed do not alter this configuration identity.
- Different seeds share the same fingerprint and increment one repeat group. A second run with the same fingerprint and seed is rejected unless the runtime agent explicitly records rerun mode with a non-empty reason. Persist `fingerprint`, `repeat_group_id`, `repeat_index`, `repeats_run_ids`, `seed`, `config_revision`, and `rerun_reason` in both the structured log and run Markdown.
- Allocate the monotonic run id, check duplicates, and write the Markdown/run-log only after acquiring the workspace transaction lock. Artifact identities must remain project-contained; absolute machine paths never become durable identity.
- Batch import is a private Agent workflow for project-contained W&B JSON, stable-header CSV, or a flat `run-*.json` directory. Preserve exact source bytes in the experiment's digest-addressed import archive, but persist only project-relative provenance, byte/item/batch digests, source row/file, and optional external run id.
- Import parsing is factual ETL only: explicit fields map directly, numeric summary fields become typed metrics, missing config revision becomes a canonical config digest, and a fixed external-state map produces the observed outcome. It must never infer a diagnosis, winner, cause, significance, or recommendation.
- Preflight the complete batch before any business write. Identical item digests are idempotent skips; an external id or fingerprint+seed/config collision with different source bytes rejects the whole batch. Raw archive, all run files, the shared log/record/event/index updates, and the one checkpoint are all-or-nothing.
- Diagnosis remains agent judgement. The script only attaches factual `comparison_context` containing recent runs plus all baseline/milestone anchors; it never generates a diagnosis from those facts.
- A diagnosis requires agent-authored canonical `claims`. Every claim must pass the shared claim-structure gate and every evidence quote must be verified verbatim against this experiment unit's own `run-log.yaml` or `runs/run-NNN.md`; cross-unit, missing, or fabricated evidence is rejected before any diagnosis write. Claims remain `pending_user_confirmation`.
- If diagnosis is requested without claims, the script writes an explicit `diagnosis-fill.yaml` with `status: awaiting_agent_fill` and does not append a diagnosis, mutate the canonical diagnosis, or emit a judgement event. The Agent fills that scaffold and repeats verification.
- Diagnosis reporting events bind the experiment subject, canonical claim ids, content digest, and verification receipt. Confirmation emits a second bound event; a name such as `experiment-confirmed` alone is never trusted.

## Task-scoped Preference Contract

- `plan` 绑定 program、idea 以及目标/假设摘要；`log-run` 绑定当前 experiment 版本、配置修订与本次 run 输入；`follow-up` 和 `diagnose` 分别绑定当前 experiment 版本与本次操作内容。
- 每次操作都重新计算 task digest；receipt 若属于其他 skill、operation 或 task，或 canonical preference 已变更，则在写入前失败。
- 无 receipt 时 soft preference 保持中性；资源、约束与自动执行边界始终作为 hard fallback 被加载。
- record、run log、follow-up 或 diagnosis 只保存 task digest、selection binding 与 hard-value digests，不复制 preference 正文。
- preference 只能在现有安全、evidence、confirmation、recovery 边界内改变 Agent 的执行方式，不得降级任何治理门。

## Phase Plan / Feedback Integration (added 2026-05-13)

When a program runs under the **phase-by-phase iterative workflow** (see `research-orchestrator` skill `Phase-by-Phase Iterative Development Workflow`), `experiment-workbench` is the durable home for **per-run execution records** that feed the phase-level feedback report.

### Run-log ↔ Phase feedback mapping

| Phase plan section | experiment-workbench artifact |
|---|---|
| Plan §X "Convergence criteria" | one `run-log` entry per training/eval run; `outcome` ∈ {success, partial, failed, blocked, inconclusive} |
| Plan §X "Experimental Arms Registry" | one `run-log` per arm × seed; record the arm, tested hypothesis, and artifacts as structured run inputs |
| Phase feedback §2 "Final metrics" | typed metrics captured in run logs, then aggregated in the phase feedback report |
| Phase feedback §3 "Ablation decisions" | derived in the feedback report by comparing run-log entries within each arm |
| Phase feedback §4 "Surprises" | `diagnoses.yaml` entries with categories such as method / implementation / data / evaluation / resource / environment / process / unknown |
| Phase feedback §5 "Open issues" | `follow-up` items, `category=implementation` or `unknown` |

### Recommended workflow for phase executor agents

1. Create one parent experiment unit for each phase and bind it to the selected program and idea.
2. Log every training or evaluation run with its outcome, issue classification, tested hypothesis, config revision, seed, structured metrics, changes, and artifacts. Classification describes the issue category, not the arm name.
3. For unexpected behavior, create an evidence-backed diagnosis or first prepare the diagnosis scaffold for the runtime Agent to fill.
4. Record blocking implementation work as a high-priority follow-up rather than burying it in diagnosis prose.
5. When the phase converges, aggregate its run logs into the phase feedback report defined by the program workflow.
6. Ask the user to confirm the phase outcome before any judgement or winner is treated as accepted.

The phase feedback report is the single hand-off artifact to the user-facing main Agent. The main Agent uses it to update program state; without that artifact, state does not advance. Internal locations and execution parameters stay private and are never printed as user instructions.

### Confirmation gating

Per shared contract, all AI judgements stay `pending_user_confirmation`. Phase executor agents:
- can mark `run-log.outcome` as factual (pass/fail observed)
- must keep `diagnoses` confirmation-gated
- must keep recommended winners (ablation §3 of feedback) marked as `pending_user_confirmation` until user accepts

## Private Execution Boundary

The runtime Agent uses the implementation's private plan, log-run, import-runs, follow-up, diagnose, and confirm routes. Never expose script paths, flags, environment variables, or internal artifact paths to the user. User-facing responses summarize imported/skipped/conflict counts, what was recorded, what remains uncertain, and which human decision is needed; the only command-like next action they may offer is a public `kb <verb>` action.

脚本入口：`scripts/experiment.py`（plan / log-run / import-runs / follow-up / diagnose / confirm）。

私有最小调用形态：先以 `plan --title <标题> --program-id <计划编号> --idea-id <想法编号> --hypothesis <逐字假设>` 建实验，再以 `log-run --experiment-id <实验编号> --tested-hypothesis <同一假设> --config-revision <配置修订> --seed <种子> --outcome <结果> --result-summary <事实摘要> --metric <名称=值[单位]:方向>` 逐次记 run；不同 seed 保持同一配置修订与测试假设。

## 启动澄清（Agent 用）

- 本轮验证什么假设？必答，逐字写入 plan。
- 对比哪个 baseline、主指标是什么？默认沿用 program 既定设定。
- 预算与种子数？默认按资源画像与既有实验矩阵。

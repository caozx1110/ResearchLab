---
name: research-experiment-tracker
description: Record experiment plans and run outcomes under `kb/programs/<program-id>/experiments/runs/`, maintain a durable follow-up view, and capture statuses, metrics, failure modes, linked artifacts, and next actions. Use when Codex needs to persist experiment execution details instead of leaving them in chat or only in a static experiment matrix.
---

# Research Experiment Tracker

Convert run-by-run experimentation into durable program memory.

## Workflow

1. Read `AGENTS.md` plus `kb/memory/user-profile.yaml`.
2. Default to Chinese user-facing prose when the profile prefers Chinese.
3. Read the target program's `workflow/state.yaml` and existing `experiments/*` context.
4. For each run, write a note under `kb/programs/<program-id>/experiments/runs/`.
5. Update:
   - `kb/programs/<program-id>/experiments/run-log.yaml`
   - `kb/programs/<program-id>/experiments/follow-up.md`
6. Keep each run explicit about:
   - intent
   - setup / config notes
   - result summary
   - failure modes or risks
   - next actions
   - linked artifacts
7. Append a concise reporting event so weekly reports can cite the run later.

## Shared Contract

- Do not overwrite `experiments/matrix.yaml`; complement it with run-by-run execution memory.
- Do not invent metrics or outcomes that were not provided.
- If the result is inconclusive, say so explicitly.
- Prefer one durable run note per meaningful execution step rather than folding many runs into one vague blob.

## Commands

```bash
python3 .agents/skills/research-experiment-tracker/scripts/track_experiment.py log-run \
  --program-id my-program \
  --title "hierarchical interface baseline v0" \
  --intent "验证最小分层接口是否至少能达到 baseline parity" \
  --status failed \
  --result-summary "任务成功率没有超过 baseline，且低层接口对齐不稳定。" \
  --failure-mode "latent interface 与 low-level API 对齐不稳定" \
  --next-action "先退回更简单的 skill token 接口，再重做对照实验。" \
  --metric success_rate=0.18 \
  --metric recovery_rate=0.05

python3 .agents/skills/research-experiment-tracker/scripts/track_experiment.py preview \
  --program-id my-program \
  --title "实验记录预览" \
  --intent "只预览，不写文件。"
```

## Boundaries

- Do not replace `method-designer`; this skill logs execution and follow-up, not the whole design pack.
- Do not claim a run is complete if the evidence is only a plan.
- Do not leave next actions implicit when a run failed or was blocked.

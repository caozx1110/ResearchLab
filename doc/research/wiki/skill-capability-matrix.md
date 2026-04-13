# Skill Capability Matrix

This note records the current research-workflow skill layout, the main friction observed in the workspace, and the recommended next additions.

Read [AGENTS.md](../../../AGENTS.md) first for the workspace-wide schema and artifact rules. Read [navigation.md](../user/navigation.md) for the human-facing entry layer.

## Why This Exists

The current workspace already has a strong ingest and analysis backbone, but the gap is no longer “can the agent write YAML?” The bigger gap is whether important knowledge and outputs are easy to find, easy to continue, and easy to reuse.

## Observed Signals

- Observed: `doc/research/library/` and `doc/research/programs/` are already well structured for canonical knowledge and program artifacts.
- Observed: `doc/research/memory/user-profile.yaml` already records `language_preference: zh-CN`, but the Chinese-first rule was not previously elevated to a workspace schema document.
- Observed: human-facing outputs are scattered across `programs/*/weekly/`, `doc/research/wiki/queries/`, `doc/research/user/kb/`, and `output/doc/`.
- Observed: original PDFs are stored canonically and correctly, but the access path is deep enough that reopening them in VSCode is inconvenient.
- Observed: there is no dedicated durable home for technical route discussion records.
- Observed: there is no dedicated durable home for per-run experiment execution notes, regressions, and next-step follow-up.
- Inferred: if the current structure grows without a user-facing curation layer, the workspace will remain machine-maintainable but human-friction-heavy.

## Current Skill Layout

| Skill | Primary Responsibility | Durable Outputs Today | Recommendation |
| --- | --- | --- | --- |
| `research-conductor` | Program orchestration, memory, stage, wiki log/index | `workflow/*`, `memory/*`, `wiki/{index,log}.md`, query artifacts | Keep. Do not split yet. Narrow it to orchestration and routing. |
| `literature-corpus-builder` | Canonical paper/blog/project ingest | `library/literature/*`, intake manifests, index refresh | Keep. Boundary is clear. |
| `repo-cataloger` | Canonical repo ingest | `library/repos/*`, intake manifests, index refresh | Keep. Boundary is clear. |
| `research-note-author` | Close reading of canonical papers/repos | `note.md`, `repo-notes.md` | Keep. High-value durable skill. |
| `literature-analyst` | Program-scoped synthesis | `evidence/literature-map.yaml`, reporting events | Keep. Good program-level role. |
| `research-landscape-analyst` | Pre-program or field-scoped survey | `library/landscapes/*` | Keep. Separate from program synthesis. |
| `idea-forge` | Idea generation | `ideas/*/proposal.yaml`, `ideas/index.yaml` | Keep. |
| `idea-review-board` | Critique and selection | `review.yaml`, `decision.yaml` | Keep. |
| `method-designer` | Implementation-ready design pack | `design/*`, `experiments/*` | Keep, but experiment follow-up needs a downstream owner. |
| `weekly-report-author` | Time-bounded program reporting | `weekly/*.md`, memory history | Keep. |
| `research-kb-browser` | Read-only visualization | `doc/research/user/kb/` | Keep. Useful read layer, not enough by itself as the only navigation surface. |
| `research-deliverable-curator` | User-facing navigation, reading bundles, deliverable entrypoints | `doc/research/user/navigation.md`, `reading-lists/*`, `reports/*` | New additive layer. Keep focused on human reopening. |
| `research-discussion-archivist` | Durable technical route discussion notes | `programs/<id>/discussions/*.md`, `discussions/index.md` | New additive layer. Keep focused on decisions and tradeoffs. |
| `research-experiment-tracker` | Per-run experiment logs and follow-up | `experiments/runs/*.md`, `experiments/run-log.yaml`, `experiments/follow-up.md` | New additive layer. Keep focused on execution memory. |

## What Should Not Be Split Right Now

### `literature-corpus-builder` vs `research-note-author`

Keep them separate.

- Reason: ingest reliability and close reading are different failure modes.
- Benefit: canonicalization stays deterministic, while note writing remains interpretation-heavy.

### `literature-analyst` vs `research-landscape-analyst`

Keep them separate.

- Reason: one is program-scoped evidence synthesis, the other is pre-program or field-scoped survey work.
- Benefit: prevents program logic from polluting library-wide landscape analysis.

### `idea-forge` vs `idea-review-board`

Keep them separate.

- Reason: proposal generation and skeptical selection should remain different modes.
- Benefit: preserves constructive generation followed by adversarial review.

### `research-conductor`

Do not split immediately, but stop expanding it as the universal place for every missing workflow.

- Reason: it is still the best place for state, memory, routing, and durable query coordination.
- Risk if overgrown: it becomes an opaque “do everything” skill and skill boundaries drift again.

## Implemented Additions

### 1. `research-deliverable-curator`

Implemented in this round to make the workspace easier to browse day to day.

- Responsibility:
  - maintain `doc/research/user/navigation.md`
  - build current reading bundles
  - add direct links to original PDFs and repo roots
  - maintain user-facing report and export indexes
  - surface “what should I open next?” views
- Why it matters:
  - fixes the human-facing navigation gap without polluting canonical ingest skills
  - turns deep canonical paths into reusable, curated entrypoints
- Trigger examples:
  - “帮我整理当前要看的论文入口”
  - “把本周成果做个总入口”
  - “我想快速打开原始 PDF”
  - “把周报、综述、对比报告串起来”

### 2. `research-discussion-archivist`

Implemented in this round so technical route discussions can become durable knowledge instead of thread residue.

- Responsibility:
  - write `doc/research/programs/<program-id>/discussions/<date>-<slug>.md`
  - summarize tradeoffs, rejected options, decisions, open questions, and follow-up actions
  - convert important chat conclusions into reusable design memory
- Why it matters:
  - currently these insights are too easy to lose in thread history
  - discussion outcomes often shape ideas, design, and experiments, so they should be first-class artifacts
- Trigger examples:
  - “把刚才的路线讨论整理下来”
  - “记录一下为什么不选 end-to-end 方案”
  - “沉淀这次方法讨论和后续待验证点”

### 3. `research-experiment-tracker`

Implemented in this round as the missing bridge from design to execution follow-up.

- Responsibility:
  - maintain `doc/research/programs/<program-id>/experiments/runs/`
  - record run intent, config, result summary, failure mode, regression, and next action
  - maintain an experiment follow-up board instead of only a static experiment matrix
- Why it matters:
  - the current workspace already has `experiments/`, but lacks a dedicated run-tracking and follow-up mechanism
  - this is the missing bridge from design to implementation iteration
- Trigger examples:
  - “记录这次实验结果和下次改动建议”
  - “把最近几次失败实验整理成 follow-up”
  - “追踪 baseline、ablation 和回归”

## Recommended Directory Additions

Even before new skills are built, the schema should reserve these durable locations:

- `doc/research/programs/<program-id>/discussions/`
- `doc/research/programs/<program-id>/experiments/runs/`
- `doc/research/user/navigation.md`
- Optional later:
  - `doc/research/user/reading-lists/`
  - `doc/research/user/reports/`
  - `output/ppt/`

## Chinese-First Requirements For Future Skills

Any newly added skill should follow these rules:

- Read `doc/research/memory/user-profile.yaml` before writing human-facing prose.
- Default to Chinese narrative output.
- Preserve English titles and stable IDs where needed.
- Avoid creating English-only durable notes unless the user requested it or a downstream format requires it.

## Suggested Near-Term Sequence

1. Keep the current ingest, note, analysis, idea, design, and weekly skills.
2. Use the new curation layer before adding more source-analysis sophistication.
3. Use the discussion archive before technical route reasoning drifts back into chat-only form.
4. Use the experiment tracker as implementation work ramps up.

## Immediate Changes Already Made In This Round

- Added [AGENTS.md](../../../AGENTS.md) to turn the repository into an explicit schema-driven workspace.
- Added [navigation.md](../user/navigation.md) to give the workspace a human-facing entry layer.
- Added `research-deliverable-curator`, `research-discussion-archivist`, and `research-experiment-tracker` as additive workflow skills.

## Working Conclusion

The current workspace is already strong enough on canonical ingest and research planning. The next optimization should not be “more extraction,” but “better persistence and better reopening”: Chinese-first durable outputs, explicit discussion and experiment sinks, and a dedicated layer that curates what the human should open next.

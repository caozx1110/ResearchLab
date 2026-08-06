---
name: skill-evolution-advisor
description: Capture skill/workflow friction, corrections, defects, improvement candidates, and retrospective prompts as record-only evolution memory.
---

# Skill Evolution Advisor

Preference contract: explicitly neutral with an empty eligible catalog. Governance and diagnostic privacy/detail constraints remain deterministic owner rules rather than soft research preferences.

Use this skill when a real workflow exposes friction in the research system, when the user corrects the agent, or when lightweight memory should capture a confirmed habit, recurring issue, or skill defect.

## Trigger boundary

- Route explicit skill/workflow optimization items, pending improvements, process problems, friction, and improvement candidates here, including equivalent Chinese or English requests to record them.
- Do not claim generic research work such as optimizing a model, method, experiment, metric, or research result merely because it contains “优化 / optimization”. Ambiguous context stays with `research-orchestrator`.
- A separate request to archive a research-route discussion remains owned by `discussion-archivist`; a composed request uses an ordered `research-orchestrator` route decision.
- Capturing a defect or candidate remains record-only and never authorizes an automatic skill or roadmap edit.

## Workflow

1. For a user preference, capture only an explicit correction or repeated same-shape edit. Store one short normalized preference, the short verbatim observation, and its exact target skill and operation; leave it `pending`.
2. Accumulate no more than two pending preference observations at task close and ask naturally whether to remember them. Confirmation or dismissal must use the one-time public `kb review` snapshot; direct learning review/promotion is retired. `source=user` never counts as confirmation.
3. Do not recall or broadcast the full memory at session start. A preference affects work only while its human-signed, current-message confirmation receipt and runtime binding remain current; each routed consumer receives only its exact task-eligible selected subset. Recall recurring issues only for an explicit memory/diagnostic task.
4. Keep `skill-defect` entries record-only; do not auto-edit skills or roadmap files from them.
5. For deeper retrospectives, record which skills were used, separate observed friction from inferred causes, and generate an AI-ready patch prompt.
6. When the user explicitly asks to remember a failure, record one local redacted diagnostic issue even if automatic diagnostics are off.
7. For automatic failures, read the effective workspace/per-skill mode and detail policy first. `errors-only` is deterministic capture only; `developer` may request a short Agent retrospective only within the configured task budget. `redacted` is the default; `local-detailed` must be explicit and never means raw.
8. Keep `issues.yaml` as the redacted index. Private detail is bounded, digest-bound, owner-only, and excluded from export, public output, versioning, sync, install, and update. Do not expose its path, digest, frames, or content to the user.
9. When private protocol returns `run_diagnostic_retrospective`, validate that it carries only one safe `issue_id` and `expected_detail_digest`. Read the current detail through the owner, distinguish observation from hypothesis, write only the closed four-field analysis JSON under `kb/.runtime/` as a current-user `0600` regular file, and apply through the owner with the same ID/digest. On digest drift, discard the stale analysis and prepare again. Never label a hypothesis confirmed.
10. Never copy raw stdout/stderr, traceback text, arguments, secrets, environment values, absolute paths, user/source/evidence text, or arbitrary excerpts into either diagnostic artifact. The only allowed user-message excerpt anywhere in this skill is the bounded verbatim preference observation. A defect remains record-only until a developer separately changes code.

## Natural-language interaction

Ordinary users do not need a new pseudo CLI. Interpret requests such as “记下刚才的问题”“列出待复审的 skill 问题”“把这条问题标为已解决”“生成本地脱敏预览”“对待分析的详细诊断做复盘” and use the owner operations privately. Export preview requires explicit authorization in the current user message and remains summary-only. Summarize outcomes in natural language; do not reveal owner commands, flags, issue/detail paths, fingerprints, digests, or raw context.

Automatic runtime capture is best-effort and must never replace the original business exit status. If diagnostic recording itself fails, preserve the original operation result and let recovery restore the diagnostic file.

## Commands

Lightweight learnings:

```bash
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py log --category recurring-issue --text "..." --source agent
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py log --category user-preference --text "..." --observation "<short verbatim correction>" --source user --skill report-author --operation weekly
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py recall --kind all --limit 5
python3 .agents/skills/skill-evolution-advisor/scripts/learnings.py recall --kind defects
```

The compatibility `review` and `promote` subcommands reject `user-preference` entries without writing. Use the unified `kb review` snapshot for both confirmation and dismissal.

Deep retrospective:

```bash
python3 .agents/skills/skill-evolution-advisor/scripts/create_retrospective.py --slug routing-gap --skill unit-analyst --target-skill research-orchestrator --task-summary "..." --observed-issue "..." --suggestion "..." --stdout-prompt --root kb/memory/skill-evolution
```

默认落盘路径为 `kb/memory/skill-evolution/retrospectives/<timestamp>-<slug>.md`；`--stdout-prompt` 会在写入后同时打印可交给后续 agent 的改进 prompt。

Local diagnostics (owner-only; never paste these commands into user-visible output):

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py policy --skill unit-analyst
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py record --category skill-defect --severity medium --skill unit-analyst --summary "short safe summary" --source user
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py list --status pending
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py detail --id diag-...
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py apply-retrospective --id diag-... --expected-detail-digest <sha256> --analysis-file diagnostic-analysis.json
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py review --id diag-... --status resolved
${RESEARCH_PYTHON:-python3} .agents/skills/skill-evolution-advisor/scripts/diagnostics.py export-preview --authorized
```

`detail` and `apply-retrospective` are private Agent-owner steps, never user-facing commands. The analysis file must be a bounded current-user `0600` regular JSON file below `kb/.runtime/` with exactly `explanation`, `reproduction`, `optimization_candidates`, and `next_validation`; it must not contain raw child output, user/source/evidence text, secrets, environment values, or absolute paths.

## 启动澄清（Agent 用）

- 记录类型：习惯、坑还是 skill 缺陷？默认按内容分类，skill 缺陷仅记录。
- 只记录还是同时生成复盘 prompt？默认只记录为 pending 待复审。

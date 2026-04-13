---
name: research-conductor
description: Coordinate the end-to-end research workflow around program folders under `kb/programs/`, including program creation, stage tracking, decision logging, evidence requests, long-lived memory updates, and routing to the right downstream research skill. Use when Codex needs to clarify research goals through dialogue, recover prior context, record preferences, or move a program to its next stage.
---

# Research Conductor

Keep the conversation anchored to a concrete `program`.

## Workflow

1. Initialize the shared workspace if `kb/` is missing, including the persistent wiki layer under `kb/wiki/`.
2. Create or reopen a program under `kb/programs/<program-id>/`.
3. If a landscape survey already proposed a good candidate, instantiate the program directly from that candidate seed instead of restating everything by hand.
4. Orchestrate the full `ingest -> query -> lint` loop:
   - Ingest: route source intake to `literature-corpus-builder` / `repo-cataloger`.
   - Query: run `query-program` and save durable query artifacts to `wiki/queries/`.
   - Lint: run `lint-workspace` and track unresolved issues.
5. Update `workflow/state.yaml`, `workflow/decision-log.md`, and `memory/*` as the conversation advances.
6. Keep `wiki/index.md` and `wiki/log.md` current as part of durable bookkeeping.
7. Route weekly report requests to `weekly-report-author` instead of generating the report here.
8. Route user-facing reopen bundles, reading lists, and deliverable landing pages to `research-deliverable-curator` instead of hand-authoring them here.
9. Route durable technical route discussions and meeting-like design conclusions to `research-discussion-archivist`.
10. Route run-by-run experiment execution logs and follow-up tracking to `research-experiment-tracker`.
11. Route deterministic deep work to downstream research skills instead of duplicating their logic here.
12. When the user states stable first-person facts about available compute, hardware, data, language preference, risk preference, or long-term research direction, capture them to memory before continuing.

## Shared Contract

- Treat `workflow/state.yaml` as the durable stage tracker and keep it explicit when the workflow changes.
- Keep `workflow/reporting-events.yaml` present and available as the program's cross-skill weekly-report feed; downstream program skills should append concise report-ready updates there.
- Durable unresolved questions belong in `workflow/open-questions.yaml`; durable blockers belong in `workflow/evidence-requests.yaml`.
- Record stable decisions and preferences to files even if they are already clear in chat.
- Treat `kb/wiki/index.md` as the content-oriented catalog and `kb/wiki/log.md` as the chronological operation timeline.
- High-value query answers must be written to durable wiki artifacts (for example `kb/wiki/queries/*.md`), not left in chat-only form.
- Treat statements like "I have access to H200s", "we have a Unitree G1", "I prefer Chinese responses", "keep the risk profile conservative", or "my long-term direction is humanoid VLA" as memory-capture triggers, not as chat-only context.
- Own the remembered research runtime in `kb/memory/runtime-environments.yaml`, especially after a working Python interpreter with `PyYAML` and a PDF backend has been validated.
- Keep theme-specific heuristics in `kb/memory/domain-profile.yaml` instead of embedding them into downstream skill scripts.
- Use `workflow/state.yaml`, `workflow/reporting-events.yaml`, and `kb/wiki/{index,log}.md` as the canonical contract surfaces for cross-skill handoffs.
- Treat `research-deliverable-curator`, `research-discussion-archivist`, and `research-experiment-tracker` as owner skills when those folders exist in the workspace; coordinate them, do not absorb their outputs here.

## Commands

Run from the project root:

```bash
python3 .agents/skills/research-conductor/scripts/manage_workspace.py init-workspace
python3 .agents/skills/research-conductor/scripts/manage_workspace.py create-program --program-id my-program --question "..." --goal "..."
python3 .agents/skills/research-conductor/scripts/manage_workspace.py create-program-from-landscape --survey-id my-field-scan --program-seed-id seed-1
python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime --python /path/to/python --label research-default
python3 .agents/skills/research-conductor/scripts/manage_workspace.py show-runtime
python3 .agents/skills/research-conductor/scripts/manage_workspace.py check-runtime --require-pdf
python3 .agents/skills/research-conductor/scripts/manage_workspace.py set-preference --scope global --target idea-review-board --key novelty_bar --value high
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/research-conductor/scripts/manage_workspace.py capture-memory --statement "I have a 4090 workstation, access to H200 GPUs, and a Unitree G1 humanoid robot" --program-id humanoid-vla-wholebody-control
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/research-conductor/scripts/manage_workspace.py capture-memory --statement "默认中文回复，风险偏好保守一些，长期想做人形机器人和VLA whole-body control"
python3 .agents/skills/research-conductor/scripts/manage_workspace.py append-decision --program-id my-program --stage idea-review --summary "..."
python3 .agents/skills/research-conductor/scripts/manage_workspace.py set-stage --program-id my-program --stage literature-analysis
python3 .agents/skills/research-conductor/scripts/manage_workspace.py add-open-question --program-id my-program --question-id q-1 --question "Which benchmark matters most?"
python3 .agents/skills/research-conductor/scripts/manage_workspace.py query-program --program-id my-program --question "Which papers and repos best support fast humanoid VLA iteration?"
python3 .agents/skills/research-conductor/scripts/manage_workspace.py lint-workspace --strict
python3 .agents/skills/research-conductor/scripts/manage_workspace.py rebuild-wiki-index
python3 .agents/skills/research-conductor/scripts/manage_workspace.py repair-program-files
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf
```

Weekly report handoff:

```bash
python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id my-program --days 7 --end-date 2026-03-18
```

## Boundaries

- Do not perform deep literature parsing or repo scanning here.
- Do not skip writing `workflow/*` just because the answer is obvious in chat.
- Keep global memory in `kb/memory/` and program-specific preferences in `workflow/preferences.yaml`.
- Do not keep important query synthesis only in chat; save it as a durable wiki artifact.
- Do not auto-memory hypothetical or comparative statements; only persist stable facts that describe the user's actual setup, resources, or durable preferences.
- Treat `memory/domain-profile.yaml` as workspace-local configuration: update it when the research theme changes instead of patching keyword lists into individual skills.
- Do not claim deep weekly comparisons that require rereading raw PDFs or repo source if the canonical metadata is too thin; route the gap to `literature-analyst`, `literature-corpus-builder`, or `repo-cataloger` first.
- When bootstrapping from a landscape survey, preserve the survey path and seed evidence in `inputs` so downstream work can recover why this program exists.
- When a skill fails because `python3` is missing `PyYAML` or a PDF backend, stop and either register a working runtime here or rerun the target skill through `run_with_runtime.py`.
- Do not author `kb/user/reading-lists/`, `kb/user/reports/`, `kb/programs/<program-id>/discussions/`, or `kb/programs/<program-id>/experiments/runs/` here when the dedicated owner skills are available.

## Retrospective Handoff

- If cross-skill routing, runtime recovery, or durable-state updates felt awkward, hand the issue to `skill-evolution-advisor` before ending the task.

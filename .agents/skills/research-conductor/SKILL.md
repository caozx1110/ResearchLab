---
name: research-conductor
description: Coordinate the end-to-end research workflow around program folders under `doc/research/programs/`, including program creation, stage tracking, decision logging, evidence requests, long-lived memory updates, and weekly report writing. Use when Codex needs to clarify research goals through dialogue, recover prior context, record preferences, synthesize weekly program status, or route the next step to literature, repo, idea, or method skills.
---

# Research Conductor

Keep the conversation anchored to a concrete `program`.

## Workflow

1. Initialize the shared workspace if `doc/research/` is missing.
2. Create or reopen a program under `doc/research/programs/<program-id>/`.
3. If a landscape survey already proposed a good candidate, instantiate the program directly from that candidate seed instead of restating everything by hand.
4. Update `workflow/state.yaml`, `workflow/decision-log.md`, and `memory/*` as the conversation advances.
5. Write weekly reports under `doc/research/programs/<program-id>/weekly/` when the user wants a durable status report.
6. Route deterministic work to the other research skills instead of reproducing their logic here.

## Shared Contract

- Treat `workflow/state.yaml` as the durable stage tracker and keep it explicit when the workflow changes.
- Durable unresolved questions belong in `workflow/open-questions.yaml`; durable blockers belong in `workflow/evidence-requests.yaml`.
- Record stable decisions and preferences to files even if they are already clear in chat.
- Own the remembered research runtime in `doc/research/memory/runtime-environments.yaml`, especially after a working Python interpreter with `PyYAML` and a PDF backend has been validated.
- Keep theme-specific heuristics in `doc/research/memory/domain-profile.yaml` instead of embedding them into downstream skill scripts.
- Weekly reports should synthesize canonical library metadata (`literature/*/metadata.yaml`, `repos/*/summary.yaml`), program workflow/design artifacts, and remembered history instead of reparsing raw PDFs or repo source trees.
- Weekly report runs should append a `weekly-report-generated` event to `doc/research/memory/history/` so later reports can see what window was already covered.
- Use the shared contracts in `doc/research/shared/schemas/shared-data-model.md` and `doc/research/shared/schemas/workflow-state-schema.md`.

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
python3 .agents/skills/research-conductor/scripts/manage_workspace.py append-decision --program-id my-program --stage idea-review --summary "..."
python3 .agents/skills/research-conductor/scripts/manage_workspace.py set-stage --program-id my-program --stage literature-analysis
python3 .agents/skills/research-conductor/scripts/manage_workspace.py add-open-question --program-id my-program --question-id q-1 --question "Which benchmark matters most?"
python3 .agents/skills/research-conductor/scripts/manage_workspace.py write-weekly-report --program-id my-program --days 7 --end-date 2026-03-18
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf
```

## Boundaries

- Do not perform deep literature parsing or repo scanning here.
- Do not skip writing `workflow/*` just because the answer is obvious in chat.
- Keep global memory in `doc/research/memory/` and program-specific preferences in `workflow/preferences.yaml`.
- Treat `memory/domain-profile.yaml` as workspace-local configuration: update it when the research theme changes instead of patching keyword lists into individual skills.
- Do not claim deep weekly comparisons that require rereading raw PDFs or repo source if the canonical metadata is too thin; route the gap to `literature-analyst`, `literature-corpus-builder`, or `repo-cataloger` first.
- When bootstrapping from a landscape survey, preserve the survey path and seed evidence in `inputs` so downstream work can recover why this program exists.
- When a skill fails because `python3` is missing `PyYAML` or a PDF backend, stop and either register a working runtime here or rerun the target skill through `run_with_runtime.py`.

## Retrospective Handoff

- If cross-skill routing, runtime recovery, or durable-state updates felt awkward, hand the issue to `skill-evolution-advisor` before ending the task.

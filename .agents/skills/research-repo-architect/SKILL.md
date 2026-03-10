---
name: research-repo-architect
description: Analyze one or more local research software repositories and produce structured architecture notes under doc/repo-name/ for reading, onboarding, agent context-building, and follow-on development. Use when Codex needs to understand how a machine learning, robotics, VLA, or other research codebase is organized; identify entrypoints, config systems, data, model, training, evaluation, or inference pipelines; compare related repositories; surface extension points, risks, and improvement ideas; or refresh repository documentation before making changes.
---

# Research Repo Architect

## Overview

Produce evidence-backed repository documentation for humans and agents. Focus on how the codebase is organized, how the main workflows run, where modifications should be made, and what research or engineering improvements are worth considering.

## Output Contract

- Write outputs under `doc/<repo-name>/`.
- Keep generated scan artifacts under `doc/<repo-name>/_scan/`.
- When analyzing more than one repository, also write `doc/index.md`.
- Create these files for each repository unless the repository is too small to justify one:
  - `summary.yaml`
  - `overview.md`
  - `architecture.md`
  - `workflows.md`
  - `research-notes.md`
  - `todo.md`
- Reuse and update existing documentation instead of duplicating it.
- Keep each document concise and navigable. Prefer key modules and mainline workflows over exhaustive listings.

## Evidence Rules

- Distinguish these labels in the prose:
  - `Observed`: direct facts from files, commands, or code paths.
  - `Inferred`: reasoned conclusions that are not stated explicitly.
  - `Suggested`: research or engineering recommendations.
- Attach concrete evidence to important claims by citing file paths, config names, or commands.
- Do not present guesses as facts.
- If a point is uncertain, write it under `Open questions` instead of overstating confidence.

## Workflow

1. Scope the repositories.
   - Confirm the repository roots.
   - Check whether `doc/<repo-name>/` already exists.
   - Decide whether the task covers one repository, several repositories, or a comparative family.
2. Run a focused scan before writing.
   - Run `scripts/scan_repo.py` first to seed `doc/<repo-name>/_scan/` with facts, a shallow tree, and a scan report.
   - Read `README*`, dependency manifests, config roots, and top-level scripts first.
   - Identify the main entrypoints for training, evaluation, inference, data preparation, deployment, or simulation.
   - Use `references/analysis-checklist.md` as the scanning checklist.
   - Treat `facts.yaml` and `report.md` as a fact layer, then manually verify the mainline workflows in source files.
3. Build the architecture map.
   - Identify the main modules, ownership boundaries, and high-value call paths.
   - Trace how configuration enters the system and how artifacts flow through the pipeline.
   - Prefer the mainline workflow over edge cases when time is limited.
   - If the repository is a mixed-language monorepo, describe its major subsystems separately before drilling into shared utilities.
4. Write the documentation set.
   - Use `references/output-schema.md` to decide which sections to fill.
   - If the docs are missing, use `scripts/bootstrap_docs.py` to create `summary.yaml` and the Markdown skeletons without overwriting existing files.
   - Start from the templates in `assets/templates/` when creating new files.
   - Keep facts, inferences, and suggestions clearly separated.
5. Review for actionability.
   - Run `scripts/refresh_docs.py` after rescanning to write a fresh `summary-seed.yaml`, fill missing summary fields, and optionally generate `index.generated.md`.
   - Do not let automation overwrite hand-written narrative docs unless the user explicitly asks for that behavior.
   - Verify that another agent could answer "how do I run this, where do I modify it, and what should I improve next?" from the generated files.
   - Record unresolved ambiguity under `Open questions`.

## Scanning Priorities

- Prioritize these files and directories:
  - `README*`, `docs/`, `examples/`
  - `pyproject.toml`, `setup.py`, `requirements*.txt`, `environment*.yml`, `Dockerfile`
  - `configs/`, `conf/`, `hydra/`, `launch/`
  - `train*.py`, `main*.py`, `eval*.py`, `infer*.py`, `serve*.py`, `scripts/`
  - `models/`, `networks/`, `policies/`, `agents/`
  - `datasets/`, `data/`, `transforms/`, `preprocess/`
  - `trainer/`, `engine/`, `runner/`, `pipeline/`
  - `sim/`, `envs/`, `tasks/`, `robot/`, `hardware/`
  - `tests/`, `notebooks/`, `checkpoints/`, `logs/`
- Prefer `rg`, `find`, `ls`, and targeted file reads over loading large files wholesale.
- Do not run expensive training or evaluation jobs unless the user explicitly asks.

## Writing Guidelines

- Write `overview.md` for a reader who needs a fast orientation in under five minutes.
- Write `architecture.md` around subsystems, dependencies, and extension points rather than directory trees.
- Write `workflows.md` around concrete flows such as train, eval, infer, data prep, and experiment management.
- Write `research-notes.md` as evidence-backed opportunities, risks, bottlenecks, and open research questions.
- Write `todo.md` as an actionable backlog with priorities such as `P0`, `P1`, and `P2`.
- Keep directory trees shallow. Show only the levels that explain architecture.
- Prefer short tables and bullet lists to long prose when the structure is repetitive.

## Multi-Repo Guidance

- Keep each repository self-contained under its own `doc/<repo-name>/` directory.
- Write `doc/index.md` when the user asks for cross-repository understanding or when several repositories share a research stack.
- In `doc/index.md`, summarize:
  - each repository's purpose
  - key similarities and differences
  - reusable modules or patterns
  - shared risks and comparative improvement ideas

## Resource Map

- Run `scripts/scan_repo.py` to generate the `_scan/` fact layer for one or more repositories.
- Run `scripts/bootstrap_docs.py` to seed missing docs from `_scan/facts.json` and the bundled templates.
- Run `scripts/refresh_docs.py` to sync fresh scan facts into `summary.yaml` conservatively and optionally emit `index.generated.md`.
- Read `references/analysis-checklist.md` before scanning a new repository.
- Read `references/output-schema.md` before creating or refreshing the documentation files.
- Copy and adapt the templates in `assets/templates/` when creating new files from scratch.

## Boundaries

- Do not treat repository docs as ground truth if the code disagrees.
- Do not exhaustively summarize utility modules with little architectural impact.
- Do not invent benchmark claims or scientific conclusions not supported by the repository.
- Do not overwrite user-authored notes without preserving useful existing content.

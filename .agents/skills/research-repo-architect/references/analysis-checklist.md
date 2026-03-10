# Analysis Checklist

Use this checklist to scan a repository before writing any architecture document.

## 0. Fact Layer

- Run `scripts/scan_repo.py` first when the repository is local.
- Inspect `doc/<repo-name>/_scan/facts.yaml`, `report.md`, and `tree.txt`.
- Use those files to prioritize manual reading, not to replace it.
- If the repository is a monorepo, identify the top-level subsystems before tracing fine-grained call paths.

## 1. Identity

- What problem does the repository solve?
- Is it a library, an application, an experiment harness, or a benchmark suite?
- Which research area does it target: vision, language, robotics, VLA, control, simulation, or tooling?

## 2. Entry Points

- Find the main scripts and commands.
- Identify separate entrypoints for:
  - training
  - evaluation
  - inference or demo
  - data preparation
  - deployment, serving, or simulation

## 3. Configuration

- Find the configuration system.
- Record whether the repository uses plain YAML, Hydra, argparse, gin, environment variables, or custom config loaders.
- Identify the config files that most strongly shape experiments.

## 4. Core Pipeline

- Find where datasets are loaded and transformed.
- Find where models, policies, or controllers are defined.
- Find where losses, objectives, or rewards are assembled.
- Find where optimization, rollout, or training loops live.
- Find where evaluation metrics are computed.
- Find where checkpoints, logs, and artifacts are written.

## 5. Architecture Boundaries

- Identify the main subsystems and their responsibilities.
- Find high-value extension points:
  - model class registration
  - task or environment registration
  - dataset adapters
  - trainer hooks
  - evaluation plugins
- Note coupling problems, duplicated logic, or hidden global state.

## 6. Research Signals

- Check whether the repository exposes ablations, baselines, or experiment tables.
- Identify likely improvement areas:
  - missing modularity
  - weak reproducibility
  - hard-coded assumptions
  - fragile data handling
  - limited evaluation coverage
  - unclear benchmark boundaries

## 7. Development Practicalities

- Record the minimum steps required to run the main path.
- Identify external dependencies, data locations, and credential requirements.
- Note where new methods, datasets, or tasks should be inserted.

## 8. Large-Repo Triage

If the repository is large, prioritize in this order:

1. `README*` and manifests
2. config root
3. main train or eval entrypoint
4. model and data modules
5. trainer or pipeline module
6. task, env, or simulator integration
7. tests or example runs

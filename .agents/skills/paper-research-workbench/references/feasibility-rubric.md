# Feasibility Rubric

Use this rubric when writing `feasibility.md`.

## Decision Gates

- Reproducibility: can the key claim be tested with available assets.
- Data readiness: required dataset and labels are available.
- Compute and hardware: expected runtime and robot resources are realistic.
- Evaluation reliability: metrics and baselines are well-defined.
- Safety and risk: rollout risk is acceptable for the environment.

## Decision Output

- `go`: run now.
- `conditional-go`: run only after listed preconditions.
- `no-go`: postpone or reject.

Always include rationale and explicit preconditions.

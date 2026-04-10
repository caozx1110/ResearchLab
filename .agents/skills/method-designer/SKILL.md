---
name: method-designer
description: Turn a selected idea into an implementation-ready design pack in a program's `design/` and `experiments/` directories. Use when Codex needs to choose a repo, define interfaces, outline ablations, specify success criteria, or prepare a concrete implementation handoff without editing the code repository yet.
---

# Method Designer

Convert a selected idea into a bounded engineering plan.

## Workflow

1. Read the selected `proposal.yaml`, `review.yaml`, and `decision.yaml`.
2. Refuse to proceed from an unselected idea by default; if `decision.yaml` does not explicitly say `selected`, hand back to `idea-forge + idea-review-board`.
3. Choose the best repo from `doc/research/library/repos/` unless the user pins one, using `proposal.yaml.repo_context`, repo `short_summary`, tags, topics, and entrypoints as the first-pass ranking signal.
4. When top repos look complementary, write a dual-repo plan instead of flattening everything into one host-repo template.
5. Write `design/selected-idea.yaml`, `design/repo-choice.yaml`, `design/interfaces.yaml`, `design/coordination-contracts.yaml`, `design/system-design.md`, and `experiments/*`, including the chosen repo summary, supporting repos, and the top-ranked alternatives.
6. Keep the first iteration minimal and falsifiable.

## Shared Contract

- Populate `inputs` with the selected idea files plus the repo index or repo summary that informed repo choice.
- After the design pack lands, append a concise summary event to `workflow/reporting-events.yaml` with the selected idea, chosen repo(s), and key interface or metric counts so `weekly-report-author` can quote it directly.
- Persist repo-choice provenance in `design/repo-choice.yaml`, including `selected_repo_summary`, `candidate_repos`, and concise selection reasons, so later skills can recover why a repo was chosen.
- Treat `doc/research/memory/domain-profile.yaml` as the source of workspace-local repo-role hints and query heuristics; keep the design template itself field-agnostic.
- If the design depends on more than one repo, persist the host/supporting split and interface seams in `design/coordination-contracts.yaml` instead of burying them in prose only.
- Write `selected_repo_id` back to `workflow/state.yaml` and move the stage to `implementation-planning` after the design pack lands.
- Prefer a narrow baseline-compatible edit surface before proposing a broader system rewrite.

## Command

```bash
python3 .agents/skills/method-designer/scripts/generate_design_pack.py --program-id my-program
python3 .agents/skills/method-designer/scripts/generate_design_pack.py --program-id my-program --allow-unselected
```

## Boundaries

- Do not change the code repository directly here.
- Do not silently skip the selection workflow; if the idea is not explicitly selected, point back to `idea-forge` and `idea-review-board`.
- Do not jump straight to a large rearchitecture when a narrower baseline-modification path exists.

## Retrospective Handoff

- If repo selection, interface specification, or design-pack generation required repeated manual glue, pass the observation to `skill-evolution-advisor` before ending the task.

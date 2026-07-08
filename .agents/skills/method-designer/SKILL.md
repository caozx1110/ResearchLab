---
name: method-designer
description: Turn a selected core idea unit into a method design handoff with repo choice, interfaces, and an expanded experiment matrix under `kb/programs/<program-id>/design/`.
---

# Method Designer

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#program-files` · `#confirmation-gate` · `#runtime`

Use this skill only after an idea has been explicitly selected.

## Workflow

1. Read the selected idea record and its analysis artifacts.
2. Refuse to design from an unselected idea.
3. Choose a repo from repo units or keep the choice explicitly pending.
4. Write repo choice, interfaces, and an expanded experiment matrix needed to validate the idea.
5. Hand run-by-run evidence to `experiment-workbench`.

## Shared Contract

- Repo choice is durable and should include candidate repos, selection policy, and pending-confirmation status when the choice relies on AI ranking.
- Interfaces should expose edit surfaces, config keys, metrics, and artifact expectations instead of hiding them in prose only.
- The experiment matrix should cover baseline parity, minimal variant, ablation, and stress/failure slices.
- Method-design completion should emit a reporting event so `report-author` can pick it up directly.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/method-designer/scripts/method.py design --idea-id idea-foo --program-id my-program
${RESEARCH_PYTHON:-python3} .agents/skills/method-designer/scripts/method.py design --idea-id idea-foo --program-id my-program --repo-id repo-bar --interface planner="planner emits subgoals" --baseline closest-unmodified-repo-baseline --metric success_rate --risk interface-instability
```

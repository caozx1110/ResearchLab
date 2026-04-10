---
name: idea-review-board
description: Critically review and rank candidate ideas in a program's `ideas/` directory, including novelty checks, overlap risk, evidence-gap detection, falsification plans, and decision files. Use when Codex needs to shortlist or reject proposals, request more evidence, or choose a selected idea for method design.
---

# Idea Review Board

Be skeptical, explicit, and evidence-led.

## Workflow

1. Read every `proposal.yaml` for the program, or the explicitly targeted idea IDs.
2. Compare proposals on the same rubric.
3. Default to collaborative review: write `review.yaml` plus a non-final `decision.yaml` that asks for user confirmation instead of auto-selecting an idea.
4. Use `list` to show the current candidate inventory, `review-assist` to pressure-test an idea with the user, and `revise-assist` to generate concrete proposal-tightening notes.
5. Only use `select-best` when the user explicitly wants the skill to complete idea selection automatically.
6. Before handing off to `method-designer`, make the selection explicit; do not let the workflow skip straight from "the first one looks fine" to design.

## Shared Contract

- Populate `inputs` with the reviewed proposal, literature map, and any staged search result used for novelty checking.
- After durable review or selection outputs land, append a concise summary event to `workflow/reporting-events.yaml` so `weekly-report-author` can recover the review outcome without diffing every `review.yaml` and `decision.yaml`.
- Move `workflow/state.yaml` to `idea-review` during collaborative review, and only advance to `method-design` after an explicit `selected_idea_id` exists.
- Keep `review.yaml` skeptical and evidence-led without rewriting the underlying proposal.
- If the user tries to pick an idea ad hoc, recommend running one full `idea-forge + idea-review-board` pass first so the choice is written down in `decision.yaml`.
- Treat automatic selection as opt-in: absent an explicit auto-select request, keep `decision.yaml` in a user-confirmation-required state.

## Command

```bash
python3 .agents/skills/idea-review-board/scripts/review_ideas.py review --program-id my-program
python3 .agents/skills/idea-review-board/scripts/review_ideas.py list --program-id my-program
python3 .agents/skills/idea-review-board/scripts/review_ideas.py review-assist --program-id my-program --idea-id my-idea
python3 .agents/skills/idea-review-board/scripts/review_ideas.py revise-assist --program-id my-program --idea-id my-idea
python3 .agents/skills/idea-review-board/scripts/review_ideas.py select-best --program-id my-program
```

## Boundaries

- Do not rewrite the original proposal just because the review disagrees with it.
- Do not silently pull in fresh outside knowledge; request it through the conductor workflow instead.
- Do not auto-select an idea just because one looks strongest; only `select-best` should do that.

## Retrospective Handoff

- If review work exposed missing rubrics, weak novelty checks, or confusing selection handoffs, pass the observation to `skill-evolution-advisor` before closing the task.

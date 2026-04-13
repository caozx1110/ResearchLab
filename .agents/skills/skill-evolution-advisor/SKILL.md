---
name: skill-evolution-advisor
description: Review how research workflow skills were used in the just-finished task, identify routing friction, missing scripts or references, overlapping responsibilities, and weak handoffs, and turn those observations into concrete suggestions for evolving `.agents/skills/`. This skill must also generate a ready-to-send AI improvement prompt in fenced code format, including the observed problems and proposed fixes. Use when Codex finishes a user request that involved one or more research skills, when a skill felt awkward or underpowered, or when the user wants to improve the research workflow itself.
---

# Skill Evolution Advisor

Turn skill-use friction into small, concrete workflow upgrades.

Prefer precise suggestions over generic retrospectives. Only create feedback when there is real signal.

## Workflow

1. At the end of a research-task turn, list which research skills were actually used, which ones were considered but skipped, and any manual glue work that filled a gap.
2. Separate observations from inferences. Capture concrete signals first: repeated manual steps, unclear routing, missing validation, missing templates, duplicated responsibilities, noisy outputs, or too-broad or too-narrow triggers.
3. Read only the relevant skill folders before proposing a fix. Compare the observed friction against the current `SKILL.md`, scripts, and `agents/openai.yaml` metadata for the touched skills.
4. Prefer the smallest change that would have prevented the friction: tighten a description, add or remove a workflow step, clarify a boundary, add a script, add a shared contract note, or split a responsibility only when overlap is recurring.
5. If the user explicitly asked to evolve skills, patch the strongest suggestions directly. Otherwise, write a concise retrospective note under `kb/memory/skill-evolution/retrospectives/` and generate a ready-to-send AI improvement prompt in a fenced code block.
6. If there is no material friction, say so briefly and do not invent work.

## Shared Contract

- Every suggestion must name the target skill or skills, the observed symptom, the proposed change, and the expected benefit.
- Mark statements as observed or inferred when the root cause is not directly visible from the files.
- Default to additive, low-risk fixes. Recommend deleting, merging, or splitting skills only when there is repeated evidence.
- Keep retrospective notes short and actionable so they can be triaged later.
- If another skill already solved the issue cleanly, recommend a better handoff instead of duplicating functionality.
- Do not silently edit unrelated skills during another task unless the user explicitly asked for workflow improvement.
- When enough evidence exists, fill the observed issues and suggestions so the generated prompt is immediately usable without manual rewriting.

## Command

```bash
python3 .agents/skills/skill-evolution-advisor/scripts/create_retrospective.py \
  --slug routing-gap \
  --skill research-conductor \
  --skill literature-analyst \
  --target-skill research-conductor \
  --target-skill literature-analyst \
  --task-summary "Needed manual runtime repair before literature analysis." \
  --observed-issue "The runtime check lived in research-conductor, but literature-analyst still required manual repair during execution." \
  --suggestion "Add a clearer runtime preflight and handoff contract between research-conductor and literature-analyst." \
  --stdout-prompt
```

## Retrospective Note

Use the script to create a timestamped note. The note must contain:

- `Observed Signals`: what happened in the task.
- `Suggestions`: concrete proposed skill changes.
- `AI Improvement Prompt`: a fenced `text` code block that can be sent directly to another AI.
- `Decision`: whether to patch now, defer, or ignore.

## Boundaries

- Do not claim exact skill invocation telemetry beyond what is visible in the current thread and artifacts.
- Do not turn a one-off user preference into a global skill rewrite without recurring evidence.
- Do not flood the user with retrospective noise after every task; surface only high-leverage improvements.
- Do not patch peer skills automatically unless the user asked for workflow evolution or the current task is explicitly about skill maintenance.

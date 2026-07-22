---
name: method-designer
description: Turn a selected core idea unit into a per-program method design handoff with repo choice, interfaces, and an expanded experiment matrix.
---

# Method Designer

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#program-files` · `#confirmation-gate` · `#runtime`

Use this skill only after an idea has been explicitly selected.

## Workflow

1. Read the selected idea record and its analysis artifacts.
2. Refuse to design from an unselected idea.
3. Read `kb/programs/<program-id>/state.yaml` and rank repository units from `active_unit_ids`; use KB-wide repos only when the program has no attached repo units, and state that fallback explicitly.
4. Read `kb/config/user-profile.yaml` → `resources`, preserve those declarations in program state, and scale the experiment matrix skeleton to the declared capacity.
5. Prepare repo choice, interfaces, and an expanded experiment matrix needed to validate the idea. Keep method judgements pending for the runtime agent to fill with evidence.
6. Mark rows that exceed parsed capacity as `feasibility: unrealistic` with `status_color: red`, a deterministic reason, and a natural-language resource request when a small extra allocation would make the row practical.
7. Hand run-by-run evidence to `experiment-workbench`.

## Shared Contract

- Repo choice is durable and should include candidate repos, selection policy, and pending-confirmation status when the choice relies on AI ranking.
- Candidate ordering may use deterministic record signals such as token overlap, but the script must not turn that ordering into a method judgement. `selection_judgement.claim` and `selection_judgement.evidence` are agent-filled fields.
- Interfaces should expose edit surfaces, config keys, metrics, and artifact expectations instead of hiding them in prose only.
- The experiment matrix should cover baseline parity, minimal variant, ablation, and stress/failure slices.
- Resource scaling is structural arithmetic, not material understanding: the script may set seed count, model-size tier, parallelism, GPU requirement, and feasibility from declared resources; the runtime agent supplies method rationale and evidence.
- With no declared or parseable resources, preserve the legacy four-row matrix scale and mark feasibility unknown rather than inventing capacity.
- Method-design completion should emit a reporting event so `report-author` can pick it up directly.

## Resource Profile Shape

`resources` is a mapping under `kb/config/user-profile.yaml`. Values may be structured scalars or free-form statements captured by `research-config-manager`:

```yaml
resources:
  gpu_count: 4
  local_gpu: 1x RTX 4090 with 24 GB VRAM
  cluster: 8x A100 GPUs with 80 GB each
  time_budget: 48 GPU-hours per week
```

The designer conservatively recognizes explicit GPU counts, common `Nx GPU-model` statements, GPU memory in GB, and CPU-only/no-GPU declarations. Unrecognized statements are retained verbatim in `state.yaml` as `resource_constraints`; they do not trigger guessed capacity.

Each experiment row includes:

```yaml
scale:
  seed_count: 3
  model_size_tier: repo-default
  parallelism: 1
  required_gpus: 1
feasibility: unknown | feasible | unrealistic
status_color: gray | green | red
feasibility_reason: ...
resource_request: ...
```

Repo-choice artifacts also record `candidate_corpus.scope`, `repo_ids`, `fallback_used`, and a human-readable note. Program-attached repo units are the primary corpus; KB-wide ranking is only the empty-corpus fallback.

## Evidence Boundary

- The script assembles paths, interfaces, candidate order, run-grid scale, and deterministic capacity checks.
- The runtime agent fills repo-selection claims, baseline rationale, method substance, and evidence.
- A design artifact must not claim that a repo, baseline, mechanism, or experiment is methodologically correct solely from idea text or lexical overlap.
- `selection_judgement` and `baseline_judgements` remain `pending_agent_evidence` until an agent supplies a claim plus evidence; user confirmation remains separate.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/method-designer/scripts/method.py design --idea-id idea-foo --program-id my-program
${RESEARCH_PYTHON:-python3} .agents/skills/method-designer/scripts/method.py design --idea-id idea-foo --program-id my-program --repo-id repo-bar --interface planner="planner emits subgoals" --baseline closest-unmodified-repo-baseline --metric success_rate --risk interface-instability
```

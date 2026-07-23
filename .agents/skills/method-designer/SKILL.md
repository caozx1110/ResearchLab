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
5. Prepare `candidate_repos`, `proposed_repo_id`, empty canonical judgement slots, interfaces, and an expanded experiment matrix. The backward-compatible `design` operation is prepare-only.
6. Do not write `selected_repo_id`, advance the program stage, or emit a method-selection event during prepare.
7. Have the runtime agent fill four canonical claims in the repo-choice artifact: `method-repo-selection`, `method-interfaces`, `method-baselines`, and `method-risks`. Each is a judgement-class claim with verbatim evidence; the repo-selection claim must name and cite the proposed repo unit.
8. Verify the four claims and their evidence. A successful verify creates a current byte-bound verification receipt and makes the side judgement discoverable by public review, but still does not select the repo or advance the program.
9. Only after the user's explicit current-message authorization, run the private `confirm-selection` route. Confirmation atomically writes `selected_repo_id`, advances to `implementation-planning`, updates dependent artifacts, and emits one `method-selected` event with the current ConfirmationReceipt binding. If the user rejects the displayed proposal, use the private `reject-selection` route; it closes that review subject without selecting a repo, advancing the stage, or emitting a method-selected event.
10. Hand only a confirmed run grid to `experiment-workbench`.

## Shared Contract

- Repo choice is a durable `method_selection` side judgement with `payload.claims`, `payload.verification`, optional `confirmation`, and an internal review route. Public review discovers only its `ready_for_review` state.
- Candidate ordering may use deterministic record signals such as token overlap, but the script must not turn that ordering into a method judgement. Before verification, canonical claims are empty and status is `needs_agent_fill`, not ready for human review.
- `proposed_repo_id` and `selected_repo_id` are separate fields. The latter must be absent from the repo choice, interfaces, matrix, and program state until confirmation succeeds.
- Interfaces should expose edit surfaces, config keys, metrics, and artifact expectations instead of hiding them in prose only.
- The experiment matrix should cover baseline parity, minimal variant, ablation, and stress/failure slices.
- Resource scaling is structural arithmetic, not material understanding: the script may set seed count, model-size tier, parallelism, GPU requirement, and feasibility from declared resources; the runtime agent supplies method rationale and evidence.
- With no declared or parseable resources, preserve the legacy four-row matrix scale and mark feasibility unknown rather than inventing capacity.
- Prepare/verify/confirm/reject are independent mutation transactions followed by exact-path checkpoints. First-time prepare targets the new design directory so an abort cannot leak an empty directory; an existing directory uses only exact artifact paths.
- Only confirmed method selection emits a reporting event. Its binding includes the side subject kind/id/owner/path, claim ids, content digest, and verification digests.

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

## Canonical Method Claims

The runtime agent writes the four claims directly to `payload.claims`; no sidecar claim list is a confirmation source. Every claim follows the shared evidence schema and remains `pending_user_confirmation` through verification:

```yaml
payload:
  claims:
    - id: method-repo-selection
      text: "The proposed repository id must appear verbatim here."
      claim_type: evaluation
      confirmation_status: pending_user_confirmation
      evidence_refs:
        - source_unit_id: "<the proposed repo unit id>"
          artifact: record.yaml
          locator: "<section, line, or record field>"
          quote: "<verbatim evidence>"
    - id: method-interfaces
      # same shared claim/evidence shape
    - id: method-baselines
      # same shared claim/evidence shape
    - id: method-risks
      # same shared claim/evidence shape
```

Empty claims, missing required claim ids, fact/unverified types in a required judgement slot, fabricated quotes, stale evidence bytes, and claim edits after verify all fail closed. Old artifacts that already contain an unconfirmed `selected_repo_id` require explicit migration and are never auto-promoted.

## Evidence Boundary

- The script assembles paths, interfaces, candidate order, run-grid scale, and deterministic capacity checks.
- The runtime agent fills repo-selection claims, baseline rationale, method substance, and evidence.
- A design artifact must not claim that a repo, baseline, mechanism, or experiment is methodologically correct solely from idea text or lexical overlap.
- Interface, baseline, and risk fields are structural proposal slots. Their substantive rationale lives only in the four canonical claims and cannot be treated as complete before verification and user confirmation.

## Private Execution Boundary

The runtime agent uses the implementation's private prepare, verify, and confirm-selection routes. Never expose their script paths, flags, environment variables, or artifact paths to the user. User-facing responses explain the proposal and review state in natural language and may offer only a public `kb <verb>` next action.

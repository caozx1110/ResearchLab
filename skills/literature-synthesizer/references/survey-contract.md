# Survey, review, and taxonomy contract

Load only this reference for cross-unit survey, review, or taxonomy authoring.

## Prepare

`prepare` accepts a field or query, optional kind/topic/tag/pool filters, explicit `as_of`, and optional program ids.

1. Select metadata candidates, then mechanically require current canonical records, current ConfirmationReceipts, and current evidence bytes. Metadata never proves semantic relevance.
2. Freeze unit id/kind/title, normalized record content digest, confirmation receipt digest, and each allowed evidence artifact byte digest in `kb_anchor`.
3. Create seven empty sections, a taxonomy grid frame, and a method × dimension comparison frame. All claim content/evidence refs remain empty.
4. Persist the canonical task digest, value-free preference selection binding, and hard-value digests. Preference values are not copied.
5. When no eligible unit remains, do not create an empty survey; use the separately linked composite contract.

## Agent fill

The seven standard sections are `scope_positioning`, `background_terms`, `taxonomy`, `cross_cutting`, `trends`, `gaps_challenges`, and `conclusion`. Ordinary sections use `claims`; taxonomy uses `cells`; trends/gaps use `items` with `as_of` equal to the frozen anchor.

Every claim-like cell contains:

```yaml
id: stable-cell-id
content: agent-authored judgement
claim_type: fact | inference | evaluation
evidence_refs:
  - source_unit_id: canonical-unit-id
    artifact: unit-relative-artifact
    locator: page=N | section | anchor | file:line
    quote: short verbatim evidence
```

The taxonomy grid also binds row/column labels. Comparison cells bind method and dimension ids; each method lists its source unit ids. Trends and gaps retain the frozen time anchor.

## Verify

1. Reopen every unit through the strict reader and compare record, receipt, artifact, task, and hard-value bindings.
2. Require all seven sections and all operation-required matrix/taxonomy fields to be non-empty and structurally closed.
3. Convert every cell to the shared evidence claim shape and run claim validation.
4. Resolve each evidence ref through its own `source_unit_id`; quote verification is contained to an artifact listed in that unit's frozen anchor.
5. Reject wrong preference skill/operation/task binding, stale catalog, added/removed matching units, changed evidence, bad locator, fabricated quote, or `as_of` mismatch.
6. On success, persist original epistemic types, `epistemic_status: verified_pending_confirmation`, exact consumer binding, canonical claims, verification receipt, and a stable content digest.

`evidence_verification_status: verified` means only that the bytes support the claim; it is never a user confirmation.

## Review and consumption

The review snapshot binds the complete survey substance, canonical claims, verification digests, unit inputs, and content digest. Confirm requires a non-AI actor, verbatim current-message authorization, evidence, and the expected snapshot. Reject closes only that subject and never creates confirmation.

When program ids were frozen, confirmation atomically emits one `survey-confirmed` reporting event per program with the current ConfirmationReceipt binding. Without a program binding, the survey remains a global synthesis judgement.

Formal report consumption reruns the pure staleness check. Any new matching unit, missing/changed upstream artifact, stale confirmation, or changed survey content moves it to pending/stale; no reader rewrites the survey.

## Output

Canonical YAML retains sections, comparison matrix, anchor, claim types, evidence refs, claims, verification, consumer binding, and content digest. `summary.md` renders the seven sections and comparison matrix with an explicit pending/unverified banner until user confirmation. Script-generated fixed conclusions or confidence prose are forbidden.

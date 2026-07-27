# R12 idea owner-held authoring anchor handoff

## STEP 0 — exact base sync

Your worktree must start from integration HEAD `0f412fc`. Confirm it contains `.agents/lib/research/SCHEMAS.md` owner-held anchor decision, `e85faab`, `5945b3d`, `3db1d0f`, and `2853a21`. The worktree is clean and its previous commits were cherry-picked. Reset only this isolated worktree branch to `0f412fc`, then re-check. Never touch the main worktree.

## File ownership

Modify only:

- `.agents/skills/idea-workbench/scripts/idea.py`
- `.agents/lib/research/tests/test_idea_evidence_analysis.py`
- optionally one new idea-specific test file under `.agents/lib/research/tests/` if clearly better

Do not edit SCHEMAS/SSOT/BACKLOG/version/docs or other modules.

## Locked design

Implement exact `idea-authoring-anchor/v1` from SCHEMAS:

- semantic `analyze/review/discuss`: owner anchor lives at `record.yaml.payload.idea_authoring_contracts[operation]`
- `generate`: owner anchor lives in the canonical bundle index at `authoring_contract`; prepare creates a prepared bundle index, verify/materialize consumes/updates it without treating prepared as terminal
- exact keys only: `schema`, `operation`, `canonical_id`, `request_context_digest`, `orientation_binding`, `corpus_commitment`
- `orientation_binding` is the exact regular-file identity+bytes binding; `corpus_commitment` is the current v2 manifest/file commitment; non-request operations use canonical empty request digest
- prepare writes corpus + orientation, derives anchor, persists canonical anchor, then derives preference context/fill from that anchored state, all in the same mutation transaction
- verify preflight, main verify, and final write boundary reconstruct current contract and require exact equality with owner anchor
- current fill/preference task context must bind the owner anchor digest, not merely a mutually editable orientation/corpus pair
- coherent post-prepare rewrite of corpus + orientation + fill/preference view must fail with zero business writes
- anchor mutation/removal/malformed/extra keys must fail closed
- second semantic prepare may replace the prior consumed anchor transactionally; nonempty unconsumed fill must remain exact zero-churn rejection
- generation prepared bundle remains resumable and materialized generation remains terminal; failed verify leaves the prepared anchor/current fill retryable
- preserve bounded v1 nonempty-fill compatibility. Do not silently bless a new v2 contract that lacks the owner anchor.

## Required direct tests

1. Exact two-round reproduction of the reviewer's coherent rewrite: add late evidence, rewrite v2 manifest and both digests, rewrite orientation commitment, recompute fill preference view, cite late evidence. Verify must reject and write no record result/card/judgement/candidate materialization.
2. Run this for at least semantic analyze and generation (generation has no idea record anchor).
3. Remove/mutate/extra-key anchor rejection.
4. Normal prepare/fill/verify and 3-idea prepare-all/fill-all/verify-all still pass.
5. Second analyze/review and second discussion conclusion still pass.
6. Failed verify/post-write rollback can retry the same fill and anchor.
7. Prepared generation index is not mistaken for materialized terminal state; materialized bundle is terminal.
8. Existing legacy v1 test stays green.

## Red lines

- Scripts do not author research meaning.
- No real `kb/`; temporary workspaces only.
- No weakened confirmation/evidence/containment/recovery gates.
- User-visible output remains natural language + kb verbs; no internal paths/flags/TTY contract leakage.
- No push/tag/publish.
- If the canonical anchor model cannot be implemented without another architecture choice, STOP and report.

## Verification and commits

Run idea focused + preference/recovery adjacency, Python 3.9 compileall, `git diff --check`. Commit implementation and tests separately in small commits. Report hashes, exact counts, and worktree cleanliness.

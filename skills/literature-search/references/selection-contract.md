# Current-user literature selection contract

Load this reference only after the Agent has displayed a terminal search stage and the user selects one or more candidates in the current message. Stage creation and screening use the separate stage contract linked directly from `SKILL.md`.

The runtime Agent writes a bounded JSON object for the private owner adapter:

```json
{
  "schema": "literature-selection/v2",
  "stage_id": "the-existing-literature-stage-id",
  "candidate_ids": ["exact-candidate-a", "exact-candidate-b"],
  "user_authorization": "the user's exact current-message selection words",
  "authorization_source": "user_message",
  "preference_selection_ids": {
    "exact-candidate-a": "optional-current-source-intake-add-receipt-id"
  },
  "display_binding": {
    "stage_byte_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "candidate_bindings": [
      {
        "candidate_id": "exact-candidate-a",
        "identity_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "semantic_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      },
      {
        "candidate_id": "exact-candidate-b",
        "identity_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "semantic_digest": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      }
    ]
  }
}
```

The object has no additional or duplicate JSON keys. It is a regular, non-symlink JSON file no larger than 64 KiB; it contains 1–50 unique safe candidate IDs, one existing `literature-search` paper stage, an exact non-empty current-user attestation, the exact byte/identity/semantic bindings from the candidate display the user acted on, and only optional owner-specific `source-intake + add` preference receipt IDs keyed by a selected candidate. Candidate bindings appear in the same order as `candidate_ids`. A preference receipt is not shared from the search operation and remains optional; without one, source-intake applies only its hard fallback and neutral soft behavior.

Before delegation the adapter binds the anchored whole-stage digest, an exact stage snapshot, and each candidate's exact identity and semantic projection. Before every selected item it requires both the current digest and whole snapshot to equal the expected chain state. It passes that expected stage digest to source-intake, which rechecks it during prepare, prepared-snapshot load, and inside the final mutation transaction before any canonical materialization. After the owner returns, the adapter accepts success only when the same candidate has a source-intake-owned `materialized|duplicate` marker, a canonical record ID, and an exact `payload.source_search.selections[]` receipt for the same stage, candidate identity and user authorization. The chain advances only when the whole-stage difference is exactly that candidate's status/record ID marker plus the one canonical append-only history event; a query, stop, another candidate, or any other concurrent rewrite fails closed. A canonical result completed before such a rewrite remains counted truthfully, while later items are not dispatched until the Agent revalidates the stage.

The private result uses `literature-selection-owner-adapter/v1`. Each safe protocol filename is single-use and is durably claimed with anchored `O_EXCL` before owner dispatch; every newly created parent is fsynced, and the final result replaces only that same operation's revalidated claim inode. A crash therefore leaves an inspectable `in_progress` claim and no later operation may reuse the name. The result stores only selection digests, candidate/record IDs, exact counts, an integrity-failure flag, owner return codes, and stdout/stderr line/byte counts plus sha256 digests; concurrent streaming never stores or replays unbounded raw child output. The public result is one short natural-language count summary with an optional literal `kb next`. Owner return code, timeout, or capture exception is diagnostic only: success requires the unique canonical stage transition and exact append-only receipt. Repeating a fully materialized exact selection validates those receipts and returns `already_materialized` without rerunning the owner, but uses a fresh protocol filename. A mixed partial retry must build a fresh display binding from the current stage before dispatching unfinished candidates.

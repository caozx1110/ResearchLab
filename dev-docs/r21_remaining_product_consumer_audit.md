# R21 remaining canonical-consumer and paid-dependency audit

Audit base: `e13e24a`

Scope: read-only inspection of the local product plus deterministic reproductions in fresh temporary workspaces. No real `kb/` was touched, no dependency was installed, and no network request was made. The timing hooks below only rename an ordinary unit directory at the exact gap between two existing reads; they do not bypass product validation.

## Executive result

Five locally reproducible consistency defects remain. They are all variants of one invariant violation: an operation validates or retains one version of a canonical record, then later reads evidence/artifacts from the lexical unit path without proving that those bytes still belong to that record version. Report and idea consumers at this base already use snapshot-native reads; the remaining defects are in program decisions, method design, survey selection/binding, and the generic confirmation path.

The paid-dependency/API-key check passes: neither the runtime requirements nor the documented install/core workflow requires an external API key, paid search quota, commercial database subscription, paid plugin, or marketplace package.

## F1 — Program decision verification accepts evidence from a replacement unit (P1/high)

- Code: `.agents/skills/research-orchestrator/scripts/orchestrate.py:2497-2512`, consumed at `:2515-2534`.
- Cause: `_decision_source_roots()` calls `locate_record()` but discards the record snapshot and returns `source_path.parent` as a later read capability. `verify_claim_evidence()` consequently opens whatever unit directory occupies that path later.
- User-visible impact: a program decision claim can pass verification even though the cited quote did not exist in the canonical source record version that was located for the decision.

Minimal reproduction used a temporary paper unit whose old `raw/source.txt` did not contain the cited quote. Immediately after `locate_record()` returned, the fixture renamed that ordinary unit directory and created a replacement unit at the same lexical path whose attachment contained the quote. Calling the real `load_decision_claims()` returned success:

```text
PROGRAM_ACCEPTED 1 decision-claim
CURRENT_TITLE NEW RECORD
```

Suggested owner: `research-orchestrator` with `research.records`. Replace the bespoke path map with `trusted_claim_source_roots()` / `EvidenceSourceSnapshot`, built from an exact canonical record snapshot. Program roots may remain separately trusted, but unit evidence must never be represented by a bare `Path`.

## F2 — Method verification/confirmation can bind old repository identity to replacement attachments (P1/high)

- Code: `.agents/skills/method-designer/scripts/method.py:599-618`; verification consumes it at `:1021-1036`, and confirmation repeats it at `:1101-1106`.
- Cause: `method_source_roots()` has the same locate-then-`source_path.parent` gap. The repository record located for candidate identity and the bytes used by `build_verification_receipt()` are not one atomic snapshot.
- User-visible impact: a method proposal can become `ready_for_review`, and later be confirmed, using evidence that belongs to a different replacement version of the proposed repository unit.

Minimal reproduction created all four required method claims. Their quote was absent from the old repository attachment. The fixture renamed the ordinary unit directory immediately after the real `locate_record()` and created a replacement record/attachment at the same path. The exact production calls `method_source_roots()` followed by `build_verification_receipt()` accepted it:

```text
METHOD_RECEIPT_CREATED True
VERIFY_VIOLATIONS []
CURRENT_TITLE NEW REPO RECORD
```

Suggested owner: `method-designer` with `research.records`. Use the shared snapshot-native source-root helper and carry the same repository `CanonicalRecordSnapshot` from candidate validation through receipt creation and final confirmation. Recheck `is_current()` before committing the method transaction.

## F3 — Survey eligibility validates the current record but returns the caller's stale record (P1/high)

- Code: `.agents/lib/research/surveys.py:178-202` and `:205-225`.
- Cause: `survey_input_eligibility_violations()` reloads and validates `current`, but returns only a list of violations. `select_current_confirmed_survey_records()` then appends its original input `record`, not the validated current record/snapshot.
- User-visible impact: survey preparation can synthesize the title, summary, taxonomy, and payload from an old record after proving that a different current record is confirmed.

This does not require a timing hook. The reproduction retained an `iter_records()` result for a confirmed record titled `OLD TITLE`, renamed its unit directory, created a separately confirmed replacement titled `NEW TITLE`, then passed the retained record to the real selector:

```text
ELIGIBLE_TITLE OLD TITLE
CURRENT_TITLE NEW TITLE
EXCLUDED []
```

Suggested owner: `research.surveys` / `literature-synthesizer`. Make eligibility return the validated `CanonicalUnitSnapshot` plus normalized record (or a typed result), and append only that exact record. Do not accept arbitrary caller dictionaries as the value later synthesized.

## F4 — Survey unit bindings combine an old record digest with new attachment hashes (P1/high)

- Code: `.agents/lib/research/surveys.py:1114-1123` and `:1126-1146`.
- Cause: `build_unit_binding()` independently locates/validates the record, then `_evidence_artifact_bindings()` performs a fresh recursive path traversal and `file_sha256()` calls. There is no common directory/record/artifact snapshot or final identity recheck.
- User-visible impact: the persisted survey consumer binding can claim the old title/record digest while hashing a replacement unit's attachments. Later staleness checks treat an impossible mixed version as a legitimate baseline.

The reproduction renamed the ordinary unit directory only when `_evidence_artifact_bindings()` was about to start, then installed a replacement record and `note.md` at the same path. The real `build_unit_binding()` returned:

```text
BINDING_TITLE OLD BIND TITLE
NOTE_IS_NEW True
```

Suggested owner: `research.surveys` with `research.records`. Replace `_evidence_artifact_bindings()` with `snapshot_canonical_unit_artifacts()` and derive record digest, confirmation receipt, and every artifact digest from the same `CanonicalUnitSnapshot`. A survey binding should be emitted only while that snapshot remains current.

## F5 — Generic judgement confirmation can confirm and overwrite a stale record version (P1/high)

- Code: `.agents/lib/research/confirm.py:253-325`, especially the call to `trusted_claim_source_roots()` at `:297-303`; `confirm_unit()` at `:449-485`; record CAS at `:549-600` checks only the integer revision.
- Related capability already present but not consumed: `.agents/lib/research/records.py:742-802` supports `expected_record_snapshot`, but `apply_confirmation()`/`confirm_unit()` cannot pass it.
- Cause: confirmation receives a detached record dictionary. It captures evidence from the current unit path without proving that the current record bytes/identity equal the record being confirmed. If a replacement record happens to have the same revision number, `write_record()` accepts the stale revision and overwrites it.
- User-visible impact: the user can be shown/authorize one pending judgement, while the operation confirms an older detached version and silently replaces the newer canonical content.

The reproduction built a fully substantive, verified pending paper record (`OLD RECORD`), retained its loaded dictionary, renamed the unit directory, created a separately verified replacement (`NEW RECORD`) with the same normal first-write revision, and then called the real `confirm_unit()` and `write_record()` on the retained record:

```text
CURRENT_TITLE_AFTER_CONFIRM OLD RECORD
CURRENT_STATUS confirmed
REPLACEMENT_WAS NEW RECORD
```

Suggested owner: `research.confirm` + `research.records`, followed by every direct confirm caller. Require a `CanonicalRecordSnapshot` for persisted unit judgement confirmation; pass it as `expected_record_snapshot` during evidence capture; and extend the final write CAS to bind file identity plus exact prior bytes/digest, not revision alone. Program/survey/method non-unit judgements should keep their existing owner-specific byte-bound snapshots.

## API key / paid-service / plugin audit — PASS

Evidence checked:

- `requirements.txt:1-18` contains pinned local Python libraries only. Heavy PDF alternatives at `:20-28` are explicitly optional and are not installed by default; Marker is explicitly excluded because of its licensing restriction.
- `docs/INSTALL.md:9-26` defines GitHub-link installation without a marketplace/plugin and explicitly forbids installing an Obsidian plugin, daemon, cron, watcher, or global Python package.
- `docs/INSTALL.md:65-77` describes the local managed virtual environment. It may obtain ordinary Python packages when missing, but has no credential, subscription, or paid-provider requirement.
- `README.md:154-156` states that literature discovery consumes whichever host search/browser/connector capability is already available, with no bundled provider SDK or credential and no paid service prerequisite.
- `.agents/lib/research/SCHEMAS.md:874` is an explicit fail-safe product contract: no external API key, paid retrieval quota, commercial database subscription, or paid plugin may be an install/core prerequisite; missing discovery capability becomes recoverable `blocked_no_search_tool` rather than a key-purchase prompt.
- Source search found no runtime reads of common provider credential environment variables and no provider SDK dependency. OpenAlex references in `research.sources` are limited to validation of the documented read-only legacy identity shape; no OpenAlex request path is present.

Conclusion: no paid/API-key finding. Keep the SCHEMAS invariant as a release gate, and add a static regression that fails if requirements/install/core scripts introduce provider SDKs or common credential variables without an explicitly optional boundary.

## Recommended fix order

1. F5 generic confirmation snapshot/CAS contract, because it is a shared governance gate.
2. F3 + F4 survey selection and binding, because they can persist a mixed baseline used by later survey/report workflows.
3. F1 + F2 migrate the last bespoke cross-unit path maps to `EvidenceSourceSnapshot`.
4. Run deterministic ordinary-directory replacement tests for all five gaps, then the full suite and a fresh installed-copy acceptance. No external API, key, subscription, or plugin is needed for any of these fixes or tests.

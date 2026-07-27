# R23 judgement snapshot consistency audit

Audit base: `a1ddbc2`

Scope: local read-only inspection plus deterministic tests in fresh temporary workspaces. Every race was forced only by renaming an ordinary in-workspace file or directory and installing another ordinary version at the same lexical path. No real `kb/`, network, API key, paid service, plugin, or external dependency was used.

## Result

Four user-visible version-consistency failures are reproducible. The common cause is that canonical unit records have a byte snapshot type, but `load_bound_judgement()` returns only a detached dictionary and a lexical `Path`; side judgements have no equivalent artifact snapshot at all. In addition, `trusted_claim_source_roots()` still represents `program:<id>` evidence as a bare program `Path`, so even a single receipt check can assemble evidence hashes from two program-directory versions. Report and review code therefore cannot prove that the record and evidence it displays/accepts came from one current version.

The initial path-check/reopen in `load_bound_judgement()` is real (`judgements.py:652-699`), but replacement *before* its `load_yaml()` normally causes the new record to be returned and the event content binding to reject an old event. The demonstrated acceptance failures occur when the ordinary version changes after the detached record has been loaded but before its “current” evidence/receipt check completes.

## F1 — Event-bound report accepts an old canonical unit after the unit directory is replaced (P1/high)

Call chain:

1. `report.py:183-225` `_confirmed_judgement_event()` calls `load_bound_judgement()`.
2. For unit subjects, `judgements.py:90-94` obtains only the informational result of `trusted_unit_record_path()`; `judgements.py:671-690` later reopens it with `load_yaml()`.
3. `load_bound_judgement()` returns no `CanonicalRecordSnapshot`.
4. `report.py:210` calls `judgement_confirmation_is_current()` without `record_snapshot`.
5. `judgements.py:258-285` therefore calls `_source_roots()` with `record_snapshot=None`; `trusted_claim_source_roots()` captures evidence from whichever current unit version occupies the path, without proving that it is the detached record version.
6. `report.py:219-225` compares the event binding against the detached old record, so that comparison also succeeds.

Deterministic reproduction:

- Create and confirm a substantive paper judgement titled `OLD UNIT`, with a real verification receipt and evidence quote.
- Build the exact event `confirmation_binding` from that record.
- Let the real `load_bound_judgement()` return the old record.
- Before it returns to `_confirmed_judgement_event()`, rename the ordinary unit directory and create a separately confirmed `NEW UNIT` at the same path. Keep the cited artifact bytes the same so this isolates record-version binding rather than evidence corruption.
- Run the unmodified remainder of `_confirmed_judgement_event()`.

Observed:

```text
REPORT_ACCEPTED_OLD_UNIT True 'confirmation_status=confirmed; current ConfirmationReceipt'
BOUND_TITLE OLD UNIT
CURRENT_TITLE NEW UNIT
```

Impact: a formal report can transport claims from an old confirmed unit even though a different canonical record is current. The report's “current ConfirmationReceipt” statement is false for the current unit identity.

Suggested owner: `research.judgements` + `report-author`. `load_bound_judgement()` should return a typed snapshot. Unit subjects should reuse the exact `CanonicalRecordSnapshot`; `judgement_confirmation_is_current()` must require/pass that snapshot and fail if it is no longer current before the report consumes claims.

## F2 — Reports accept old side judgements after the canonical side artifact changes (P1/high)

Affected side shapes share this defect:

- program decision list item: `kb/programs/*/workflow/decisions.yaml`
- idea discussion list item: `kb/units/ideas/*/discussion-judgements.yaml`
- method selection single document: `kb/programs/*/design/*-repo-choice.yaml`
- survey judgement single document: `kb/synthesis/*/*.yaml`

Call chain:

1. `judgements.py:419-475` validates side paths, then opens them with ordinary `load_yaml()` and yields only `(record, owner, path, None)`.
2. `judgements.py:652-699` similarly returns only `(record, safe_path)` from `load_bound_judgement()`.
3. `judgement_confirmation_is_current()` checks the detached record's receipt and current evidence, but never checks that the side artifact bytes/container identity still equal the version from which that record was parsed.
4. `report.py:183-225` therefore accepts an old event-bound side record; `report.py:722-760` has an even shorter path for program decisions: it loads the old list, then validates each old item without binding to the list bytes.

Event-bound reproduction with a confirmed program decision:

- Store `OLD DECISION` in a valid confirmed `decisions.yaml` item and build its exact event binding.
- Let the real `load_bound_judgement()` load that item.
- Replace `decisions.yaml` with a separately verified/confirmed `NEW DECISION` before the “current” check.

Observed:

```text
REPORT_ACCEPTED_OLD True 'confirmation_status=confirmed; current ConfirmationReceipt'
RETURNED_BINDING_TEXT OLD DECISION
CURRENT_TEXT NEW DECISION
```

Direct report-section reproduction (`load_decisions()`): after the old list was loaded, the timing hook replaced the ordinary file immediately before `judgement_confirmation_is_current()`:

```text
REPORT_DECISION OLD REPORT DECISION
CURRENT_DECISION NEW REPORT DECISION
```

Impact: stage/weekly reports may present a superseded decision, discussion conclusion, method selection, or survey claim as the current confirmed judgement. For survey events there is an additional consistency smell at `report.py:632-661`: the same subject is loaded once directly and then a second time inside `_confirmed_judgement_event()`, so one report operation has no single survey version even when it happens to fail closed.

Suggested owner: shared `research.judgements`, then `report-author`. Add a `JudgementArtifactSnapshot` for side documents with anchored raw bytes, file/ancestor identity, parsed container, selected item identity/digest, and `is_current()`. List-item snapshots must bind the complete container bytes plus the selected item, not only the item's semantic fields. Every report path should consume one snapshot once and recheck it immediately before emitting claims/output.

## F3 — Review discovery can display a superseded side-judgement card (P2/medium)

Call chain:

1. `judgements.py:433-475` snapshots unit records correctly, but side artifacts are emitted with snapshot `None`.
2. `discover_pending_judgements()` materializes detached side dictionaries at `:478-485` and later calls `pending_judgement_card()`.
3. `readiness_violations()` at `:211-255` verifies evidence but has no side artifact snapshot/currentness check.
4. `research-orchestrator/scripts/orchestrate.py:1558-1569` consumes these cards for the portfolio and user review routing.

Deterministic reproduction:

- Create a fully verified pending program decision `OLD REVIEW CARD`.
- Let `_candidate_artifacts()` load the old list item.
- Immediately before the real `pending_judgement_card()` runs, replace the ordinary `decisions.yaml` with a fully verified `NEW REVIEW CARD` carrying the same canonical id.

Observed:

```text
CARD_COUNT 1
CARD_TEXT OLD REVIEW CARD
CURRENT_TEXT NEW REVIEW CARD
```

Impact: `kb review`/`kb next` can show the user a superseded side judgement and ask for a decision on text that is no longer canonical. Owner-specific apply paths normally perform another snapshot/content check, so this audit did not prove a wrong write from this card alone; however, the displayed governance question is already stale and forces a confusing retry.

Suggested owner: `research.judgements` + `research-orchestrator` review projection. Make `_candidate_artifacts()` return the shared side snapshot described above, pass it through `pending_judgement_card()`, include its exact container binding in the card, and require `is_current()` both before display and during apply.

## F4 — Program-local evidence current-check can accept an impossible mix of two directory versions (P1/high)

Call chain:

1. `judgements.py:191-196` delegates evidence roots to `trusted_claim_source_roots()`.
2. `records.py:1027-1032` calls `trusted_program_root()` for the `program:<id>` branch but returns its bare `Path`; unlike canonical units, it does not capture requested evidence artifacts into an `EvidenceSourceSnapshot`.
3. `evidence.py:846-861` has `verification_receipt_violations()` call `evidence_artifact_entries()` for every ref. For a bare path, `evidence.py:381-388` independently reopens each artifact with `Path.read_bytes()`.
4. Replacing the ordinary program workflow directory between two refs can therefore produce a receipt comparison from bytes that never coexisted.

Deterministic reproduction used a legitimate historical receipt for the coherent pair `A1/B2`. At the start of the current-check, the program was version V1=`A1/B1`; immediately after the real receipt reader read `a.md`, the hook renamed the ordinary workflow directory and installed V2=`A2/B2`. At no point during the check was the historical pair `A1/B2` current, yet the real `judgement_confirmation_is_current()` accepted it:

```text
MIXED_CURRENT_CHECK_ACCEPTED True
V1_WAS A1 B1
V2_IS A2 B2
RECEIPT_WAS A1 B2
```

Impact: a program decision/report current-check can label a verification and ConfirmationReceipt current using an impossible cross-version evidence set. This is stronger than a same-byte inode/ABA concern: the two accepted artifact hashes were never simultaneously present.

Suggested owner: `research.records` + `research.evidence`. Change the `program:<id>` branch of `trusted_claim_source_roots()` to capture exactly the requested program-local artifacts through anchored, no-follow, bounded reads and return an `EvidenceSourceSnapshot` (or a program-specific equivalent with the same interface). Its `is_current()` must bind the program ancestor chain and every requested artifact identity/bytes. Do not leave program evidence as a compatibility bare `Path`; any legacy path acceptance should be isolated to explicit old-data migration, not runtime judgement gates.

## Safe paths confirmed

- Unit review discovery is materially stronger than side review: `iter_canonical_record_snapshots()` is used at `judgements.py:436-441`, and that snapshot is passed into `pending_judgement_card()`/`readiness_violations()`. An ordinary unit replacement causes expected-record comparison to fail rather than showing the old card.
- Report's ordinary confirmed unit claim loader outside event-bound judgements already uses exact canonical record snapshots. The reproduced unit failure is specifically the `load_bound_judgement()` event path.
- Exact event content binding catches a replacement that occurs before `load_bound_judgement()` returns the newly read record. It does not cover replacement after the detached record is returned.
- Canonical unit evidence is captured as `EvidenceSourceSnapshot`; program-local evidence is not. F4 confirms this remaining asymmetry is observable in a current-check.
- No external API key, paid provider, or plugin is involved in these paths or required for their fix/test.

## Recommended shared repair boundary

Implement one snapshot-native judgement interface in `research.judgements`, rather than patching report/review call sites independently:

```text
BoundJudgementSnapshot
  record                 normalized selected judgement
  artifact_path          informational canonical path
  artifact_raw_bytes     exact container bytes
  artifact_identity      leaf + ancestor identity chain
  selected_item_digest   exact selected item for list containers
  record_snapshot        CanonicalRecordSnapshot for unit subjects, else null
  evidence_snapshots     anchored unit and program evidence sources
  is_current()           full container/unit identity and bytes recheck
```

Then:

1. replace `load_bound_judgement() -> (dict, Path)` with a snapshot return;
2. make `_candidate_artifacts()` snapshot list and single-document side artifacts with the same anchored/no-follow/bounded reader;
3. pass the snapshot into `readiness_violations()` and `judgement_confirmation_is_current()`;
4. make report event, survey claim-source, and `load_decisions()` paths load exactly once and emit only while that snapshot is current;
5. bind review cards to container bytes and selected item, then recheck at owner apply;
6. make `program:<id>` claim roots snapshot-native, capturing the complete requested artifact set in one anchored operation;
7. add deterministic ordinary file/directory replacement tests for unit, list side (`decisions`/discussion), single side (method/survey), and multi-artifact program evidence shapes.

This repair is entirely local and introduces no provider, network, API-key, subscription, or paid dependency.

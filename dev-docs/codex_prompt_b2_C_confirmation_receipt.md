# Codex handoff — Batch2 Track C: ConfirmationReceipt (bind confirmation to verified content; auto-invalidate on change)

Model: gpt-5.6-sol, xhigh, full access. Owns:
- `.agents/lib/research/confirm.py`
- `.agents/lib/research/records.py`
- `.agents/lib/research/evidence.py` (only if a reusable content-digest helper belongs there)
- `.agents/lib/research/SCHEMAS.md` (document the receipt schema)
- test files under `.agents/lib/research/tests/`

Do NOT touch serve_kb_browser.py, journal.py, yaml_io.py, git_ops.py, analyzer scripts, or the kb dispatchers.

## STEP 0 — base sync (IMPORTANT: builds on Track R, already merged)
1. `git rev-parse HEAD` MUST be `7afc0edac66ba5a14340a292ef66271c02ddc6a4`. If not and clean: `git reset --hard 7afc0ed`, re-verify.
2. Managed venv runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **321 passed**. Confirm + report.
3. R already added (reuse, do NOT duplicate): `journal.file_digest(path)` (sha256 of a file), `evidence._quote_digest`, and a monotonic `revision` field on records (normalize_record_schema in records.py). `write_record(project_root, record, *, expected_revision=None)` already does lock + CAS + journaled atomic write.

## DESIGN (SSOT Principle 3 ConfirmationReceipt, locked 2026-07-16)
Verified defects in the CURRENT confirm.py:
- `confirm_unit` (confirm.py:198) checks track + substance + provenance, but the receipt (`apply_confirmation`, :189) stores only `{by,at,evidence,method}` — NO content/evidence digest. So confirmation SURVIVES later content mutation (stale confirmed).
- `confirm_unit` unconditionally sets `information_types=["fact"]` (:234) — destroys the original epistemic type.
- Evidence-string authenticity is NOT checked at confirm time (it's checked upstream at analyzer verify-note via evidence.verify_claim_evidence, decoupled from the gate).
- `validate_write` (:244) is fail-OPEN by default (:255 `strict = os.getenv(...) == "1"`) — AI-derived record with wrong confirmation_status only warns, still writes.

## REQUIRED CHANGES (make each an isolated commit; this is governance-critical — precision over speed)

### C1 — content + evidence digest helper (reuse R's primitives)
- Add a canonical-content digest function (in confirm.py or evidence.py): given a record, compute sha256 over the CANONICAL confirmable content — the `payload.core_content` (or the per-kind substance sections used by `has_substantive_content`) + the claims/evidence_refs. Must be deterministic (sort keys, normalize whitespace). Reuse `hashlib`/`journal.file_digest` patterns; do NOT reinvent.
- Add an evidence digest: sha256 over the confirmed evidence set (the evidence_items + their verified quotes/locators). 

### C2 — ConfirmationReceipt in apply_confirmation
- Extend the `confirmation` dict written by `apply_confirmation` (:189) to the full receipt:
  ```
  confirmation:
    by, at, method, evidence            # existing
    decision: confirmed                  # (rejected path if applicable)
    subject: {kind, id}
    claim_ids: [...]                     # which claims this covers (from payload claims if present, else [])
    content_digest: "<sha256>"           # C1 over canonical content AT confirmation time
    evidence_digest: "<sha256>"
    prior_information_types: [...]        # PRESERVE the pre-confirmation information_types
  ```
- Keep `by`/`evidence`/provenance checks (require_confirmation_provenance) EXACTLY as-is — the no-self-sign + non-empty-evidence red lines must not weaken.

### C3 — preserve epistemic type (stop the unconditional fact collapse)
- In `confirm_unit` (:234), do NOT unconditionally overwrite `information_types=["fact"]`. Instead: record enters `confirmation_status="confirmed"` but retains its `prior_information_types` in the receipt; decide the post-confirm `information_types` policy that keeps the substance gate + validate_write correct. Key constraint: the track/substance gate at :217 evaluates BEFORE any collapse (comment at :213 explains why) — keep that ordering. If fully removing the fact-collapse breaks the gate semantics elsewhere, prefer: keep information_types as-is but mark confirmed via confirmation_status, and store prior_information_types. Verify the existing substance-gate tests still pass; if they encode the old collapse behavior, update them to assert the NEW contract (confirmed + epistemic preserved) and note it.

### C4 — auto-invalidate on content change (the core invariant)
- In `normalize_record_schema` (records.py) OR a dedicated re-derivation on read: if a record has a `confirmation.content_digest`, recompute the canonical content digest; if it DIFFERS from the stored one, the confirmation is stale → downgrade `confirmation_status` back to `pending_user_confirmation`, set `needs_human_confirmation=True`, and note the invalidation (do NOT silently keep "confirmed"). This is the "confirmation anchors a version" invariant — analogous to R's revision but for confirmation validity.
- Must be default-safe: records with NO content_digest (all existing/legacy) are unaffected (skip the check). All 321 tests stay green unless they encode the old stale-confirmation behavior.

### C5 — fail-CLOSED for judgement track
- `validate_write` (:244): flip the default for JUDGEMENT-track (AI-derived, needs_gate) records so a contract violation BLOCKS the write by default (raise), rather than warn-and-write. Fact-track / non-gated records keep current behavior. Invert the env semantics: `RESEARCH_VALIDATE_STRICT` no longer needed to block judgement violations; instead an explicit opt-OUT (e.g. `RESEARCH_VALIDATE_FAILOPEN=1`) is required to downgrade to warn. Keep `write_record` calling `validate_write` first (before lock/CAS/journal) — do not reorder R's structure.
- CAUTION: this may surface latent violations in existing tests/fixtures. If a test seeds an AI-derived record with a too-strong confirmation_status and relied on fail-open, that's exactly the bug being closed — update the fixture to the correct pending status OR assert the new SystemExit. Report every test you change and why.

## RED LINES (governance-critical)
- NEVER weaken: no-self-sign (is_ai_signer), non-empty-evidence, substance gate (hollow reject), evidence verbatim verification. These are all pre-existing red lines — ADD binding, don't remove checks.
- NEVER touch real `kb/` (tests use tmp_path).
- Do NOT reorder or alter R's write_record lock/CAS/journal structure — only add the receipt fields to the record before it's written, and the digest computation.
- Default-safe: legacy records without a receipt/digest must still load and behave (no forced re-confirmation of everything).
- No git push. COMMIT-PER-CHANGE (C1-C5). Managed venv `$PY`. After each: run suite.
- **STOP-and-report** if: C3 (epistemic preservation) or C5 (fail-closed) breaks more than a handful of tests in ways that suggest the contract is entangled with assumptions you can't safely change — a clean C1+C2+C4 (receipt + digest + auto-invalidate) plus a report on C3/C5 is a GOOD outcome. Do NOT force fail-closed if it cascades. Governance correctness > completeness.

## FINAL REPORT
Per change: files, diff summary, tests added/changed (and WHY each existing test changed), pass/fail. Explicitly state: are no-self-sign / non-empty-evidence / substance-gate / evidence-verbatim all still enforced? Final suite line + commit hashes. Flag anything deferred with reasoning.

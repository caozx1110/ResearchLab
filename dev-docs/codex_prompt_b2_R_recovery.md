# Codex handoff — Batch2 Track R: Recovery contract (atomic IO + operation journal + revision/CAS + resume/undo/restore)

Model: gpt-5.6-sol, xhigh, full access. Owns these files (ConfirmationReceipt track C comes AFTER this merges, so you may touch confirm.py/records.py here — C rebases on your result):
- `.agents/lib/research/yaml_io.py`
- `.agents/lib/research/git_ops.py`
- `.agents/lib/research/records.py`
- `.agents/lib/research/confirm.py` (only `write_record` + a journaling hook; do NOT touch confirm_unit/apply_confirmation logic — that's track C)
- `.agents/lib/research/journal.py` (NEW file)
- `.agents/skills/knowledge-base-manager/scripts/kb.py` + `.agents/skills/kb-cli/scripts/kb` (undo/restore verbs)
- test files under `.agents/lib/research/tests/`

Do NOT touch serve_kb_browser.py (track W). Do NOT touch analyzer scripts.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `328c3660b06343e131efbb339eb82f411bd94509`. If not and clean: `git reset --hard 328c366`, re-verify.
2. Managed venv runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **307 passed**. Confirm + report.

## DESIGN (SSOT 3.11 recovery contract, locked 2026-07-16, user chose "FULL")
Verified defects: YAML writes overwrite directly (yaml_io.py:34-38, no temp+rename → corruption on interrupt); batch ops non-transactional; duplicate ingest only stops; `git_checkpoint` uses `git add -A .` (git_ops.py:121) sweeping all dirty files; no resume/undo/restore. Build the FULL contract, in dependency order, COMMIT-PER-PIECE.

## CHOKE POINTS (verified)
- `write_text_if_changed` (yaml_io.py:34) → the low-level write, used by everything.
- `write_record` (confirm.py:283) → the single record-write choke point.
- `exclusive_file_lock` (common.py:249, fcntl.flock) + `program_file_lock` (:264) → the lock base already exists; reuse it.
- `git_checkpoint` (git_ops.py:107, `git add -A .`) → scope to op paths.
- `normalize_record_schema` (records.py:411) → add a default `revision` field here.

## PIECE 1 — atomic writes (foundation; commit alone first)
- Make `write_text_if_changed` (yaml_io.py) atomic: write to a temp file in the same directory, `fsync`, then `os.replace` (atomic rename) onto the target. Preserve the "if_changed" short-circuit (don't rewrite identical content). Behavior-preserving: final content identical, so all 307 tests must stay green.
- Add a test: interrupted/partial write never leaves a truncated target (simulate by asserting temp+replace path, or that a failed dump doesn't clobber the existing file).

## PIECE 2 — operation journal (new journal.py)
- New `kb/.journal/` (gitignored — add to kb gitignore). Each mutating op writes a journal entry: `{op_id, op_type, started_at, target_paths: [...], before_digests: {path: sha256|null}, after_digests: {...}, state: begin|commit|abort}`.
- API in `journal.py`: `begin_op(root, op_type, target_paths) -> op_id` (records before-digests + state=begin), `commit_op(root, op_id)` (records after-digests + state=commit), `abort_op(root, op_id)` (state=abort). Crash-safe: an op left in `begin` is recoverable.
- Wire it at `write_record` (confirm.py) as the record-write choke point, and around batch operations. Keep the hook minimal and non-invasive — a context manager `journaled_op(root, op_type, paths)` is ideal.
- Do NOT journal reads. Do NOT change record content.

## PIECE 3 — revision / CAS
- Add a monotonic integer `revision` to the record schema; default it in `normalize_record_schema` (records.py) to 0 (or 1) so every existing record/test stays valid (additive, default-safe).
- On `write_record`: increment `revision`. Provide an optional compare-and-swap: `write_record(..., expected_revision=N)` raises a clear `SystemExit`/conflict if the on-disk revision != N (lost-update guard). Default (no expected_revision) keeps current behavior so existing callers/tests are unaffected.
- Note for track C coordination: this `revision` + digests will pair with ConfirmationReceipt's content_digest later — keep the digest helper reusable.

## PIECE 4 — shared lock on all write paths
- Wrap `write_record` (and batch writers) in the existing `exclusive_file_lock` on the record path (or a per-unit lock), reusing common.py's fcntl base. Prevent concurrent-writer corruption. Keep it deadlock-free (single lock per op, consistent ordering).

## PIECE 5 — kb undo / restore + scoped checkpoint
- `git_checkpoint` (git_ops.py): stop using `git add -A .`. Instead stage ONLY the op's target paths (pass them in from the journal/op). Fall back to current behavior only if no paths given, but the auto-drive callers should pass paths.
- Add first-class `kb undo` and `kb restore` verbs (kb.py + kb-cli `kb` dispatcher, following the existing verb-registration pattern). `undo` reverts the last committed op (from the journal + kb git repo); `restore <op_id>` rolls back to before that op. These operate on the nested `kb/` git repo + journal, NOT the project repo.
- Per SSOT principle 8: the new verbs' USER-FACING output must be natural language + `kb <verb>` only — no raw git commands shown to the user.

## RED LINES
- NEVER touch real `kb/` (tests use tmp_path). Journal/lock/atomic only ADD consistency; do NOT alter governance (confirm gate, substance gate, evidence rules).
- Do NOT touch confirm_unit/apply_confirmation logic (track C). Only write_record + journaling hook in confirm.py.
- `revision` and journaling must be ADDITIVE and default-safe: all 307 existing tests stay green without modification (except where you add new assertions).
- No git push. COMMIT-PER-PIECE (5 commits) — this is large; commit each piece as its tests pass so a mid-way stream drop loses nothing.
- Managed venv `$PY` for tests. After each piece, run the suite; final: report count (307 + new).
- STOP-and-report if any piece is larger/more entangled than described (esp. if journaling write_record breaks many tests, or CAS conflicts with normalize). Do NOT force a half-working journal — a clean subset + report beats a broken whole.

## FINAL REPORT
Per piece: files, diff summary, tests, pass/fail. Note anything deferred. Final suite line + 5 commit hashes.

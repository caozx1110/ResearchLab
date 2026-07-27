# Codex handoff — Track K: `kb resume` (recover crash-orphaned operations)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/lib/research/journal.py`
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/skills/kb-cli/scripts/kb`
- test files under `.agents/lib/research/tests/`

Do NOT touch paper.py, records.py, serve_kb_browser.py, confirm.py (other tracks). You MAY read git_ops.py (to call restore_operation) but do NOT need to modify it — if you think you do, STOP and report first.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `813ae69025a2e419919c4268d18aae5d7d3360db`. If not and clean: `git reset --hard 813ae69`, re-verify.
2. Managed venv runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **331 passed**. Confirm + report.

## DESIGN (SSOT 3.11 recovery, kb resume decision locked 2026-07-17)
A crash leaves a journal entry stranded at `state=="begin"` (the process is killed before commit_op/abort_op; there is no `finally`, so a hard kill can't even run abort). Nothing surfaces these orphans today. `kb resume` = find them + roll each back to its pre-op state + mark aborted.

### Current mechanics (verified — re-check by content)
- Journal entries: `kb/.journal/<op_id>.yaml`. `begin_op` (journal.py ~111) writes `state: begin` + `before_digests` (sha256 per target, or None if absent) + empty `after_digests`. `commit_op` (~131) fills after_digests + `state: commit`. `abort_op` (~140) → `state: abort`. `journaled_op` (~147) is begin→yield→(abort on exception / commit on success).
- Crash signature: `state == "begin"`, empty after_digests, never advanced.
- `committed_ops` (~87) EXPLICITLY skips non-commit (`if entry.get("state") != "commit": continue`, ~94) — so begins are invisible to it. `latest_committed_op` (~104), `load_op` (~80). NO function lists `state=="begin"` today.
- Recovery primitive to reuse: `git_ops.restore_operation(project_root, op_id)` (~306) — loads the op, takes `before_digests`, finds the kb-repo revision matching those digests, restores each target (unlink if pre-op digest was None, else `git restore`), wraps itself in a journaled recovery op + checkpoint. A `begin` entry HAS `before_digests`, so restore_operation works on it mechanically.
- Existing `kb undo` / `kb restore` handlers (kb.py ~387/392) print natural-language only (principle 8 compliant) — match their style.

## REQUIRED CHANGES

### K1 — journal.incomplete_ops(project_root)
- Add `incomplete_ops(project_root) -> list[dict]` in journal.py, symmetric to `committed_ops` but selecting `entry.get("state") == "begin"` (glob `journal_root/*.yaml`, sort by op_id/sequence). Return the op dicts (with op_id, target_paths, before_digests, started_at).
- Do NOT change committed_ops / journaled_op / the state machine.

### K2 — `kb resume` verb
- knowledge-base-manager kb.py: add a `resume` subparser + handler. Behavior:
  - List incomplete (begin-state) ops via `incomplete_ops`.
  - If none: print a natural-language "no incomplete operations to recover" and exit 0.
  - For each incomplete op: call `restore_operation(root, op_id)` to roll targets back to their pre-op state, then mark that original journal entry aborted (call `abort_op` on it, or set its state to abort — pick the clean way; the point is it's no longer a dangling begin). Print a natural-language summary per op (op_id + what was rolled back), no raw git.
- kb-cli `kb`: register the `resume` verb in the dispatcher + HELP_MENU (following the existing undo/restore registration pattern). User-facing: `kb resume`, natural-language help.
- Principle 8: output is natural language + `kb <verb>` only. No `python3`/`--flags`/raw git/`NEXT FOR AGENT` in the user-facing resume output.

## TESTS (extend test_recovery_contract.py + test_kb_cli_dispatcher.py)
- Seed a temp KB with an artificially stranded begin-state journal entry (write one with state=begin + before_digests for a target that was modified after). `incomplete_ops` returns it; committed_ops does NOT.
- `kb resume` rolls the target back to its pre-op content AND the entry is no longer a dangling begin (state advanced to abort). A clean KB with no begins → "nothing to recover", exit 0.
- resume output contains no raw commands/git (grep the captured stdout for `python3`/`.py`/`git `/`--`).

## RED LINES
- NEVER touch real `kb/` (tmp_path). Do NOT change the journal state machine, committed_ops, or write_record. Do NOT modify git_ops.py (call restore_operation as-is); if you believe you must, STOP and report.
- No git push. Small commits (K1/K2). Managed venv `$PY`. Final: report count (331 + new).
- STOP-and-report if restore_operation doesn't cleanly handle a begin entry (e.g. it assumes a committed op), rather than forcing it.

## FINAL REPORT
Per change: files, diff summary, tests, pass/fail. Confirm resume output is natural-language only. Final suite line + commit hashes.

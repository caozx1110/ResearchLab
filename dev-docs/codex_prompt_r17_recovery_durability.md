# R17 recovery follow-up — durable restore publication

## STEP 0 — base sync

Start from the integration HEAD supplied by the parent and verify it contains `a453e17` plus the prior anchored journal commits. If not, stop and report. Work only in an isolated worktree. Never touch a real `kb/`; all probes use fresh temporary projects.

## Reproduced defect

The parent independently instrumented `_replace_staged_at`: publishing `staged -> target` made zero calls to `fsync(parent_fd)`. The absent-target restore path also removes without persisting the directory entry. This violates the newly locked `Restore publish durability` contract in `temp/SYSTEM_DESIGN_SSOT.md` and `.agents/lib/research/SCHEMAS.md`.

## File ownership

Edit only:

- `.agents/lib/research/journal.py`
- `.agents/lib/research/tests/test_recovery_contract.py`
- `.agents/lib/research/tests/test_r1_recovery_source.py` only if a source-level convergence assertion is useful

Do not edit SSOT/SCHEMA/BACKLOG, dispatcher, updater, installer, skills, release docs or version.

## Required semantics

1. A file/directory/symlink staged replacement is successful only after the replacement is verified against the expected snapshot digest and the anchored target parent fd has been fsynced.
2. Keep the old target backup until replacement identity, expected digest and parent fsync all succeed. Do not delete it inside a generic `finally` before post-publish verification.
3. If publish, verification, or final fsync fails, rollback only after proving the visible target still has the inode/identity installed by this operation. If another actor replaced it, fail closed and preserve the old backup; never overwrite the concurrent node.
4. Rollback must remove the owned replacement, restore the old target when one existed, and fsync the parent. If original target was absent, rollback removes only the owned replacement and fsyncs. If rollback itself fails, preserve the unique old backup/recovery material and report accurately.
5. `kind=absent` successful removal must fsync its parent. If that fsync fails, restore the removed target from a held rename backup when one existed, fsync rollback, and do not return success.
6. Avoid pathname reopen after validation: stay on the already anchored parent descriptor and use no-follow metadata/identity checks. Preserve special-node nonblocking behavior.
7. `_restore_target` should own the expected digest verification within the publication transaction so cleanup cannot race ahead of verification. A small private helper/protocol refactor is acceptable; public API behavior remains unchanged.
8. No target churn when current digest already equals before digest.

## Fault-injection gates

Add deterministic tests for:

- parent fsync occurs for successful file, directory, symlink and absent restore;
- fsync failure after publish rolls back exact old bytes/mode/type and leaves no staged junk;
- originally absent target remains absent after post-publish fsync failure;
- verification mismatch after replace rolls back old target;
- concurrent replacement before rollback is not overwritten and old backup remains;
- publish + rollback failure preserves the unique backup;
- rollback fsync failure preserves recoverable material and surfaces failure;
- directory tree and symlink outside referents are untouched;
- normal abort/resume/undo/restore tests remain green.

Use monkeypatch fault injection at precise syscall boundaries; do not depend on an actual power failure. Run complete `test_recovery_contract.py`, `test_r1_recovery_source.py`, and dispatcher recovery tests. Also run `git diff --check`, syntax checks, and explicitly report counts.

## Red lines

- No governance weakening, no target-set relaxation, no path-based race reintroduction.
- No shell/TTY/user-visible protocol change.
- No push/tag/version bump.
- Small coherent commits. STOP-and-report if rollback semantics cannot be made lossless within these files.

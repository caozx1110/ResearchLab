# R12 journal abort zero-churn handoff

## STEP 0 — base sync

Work only in the task's named worktree/branch at exact supplied base. Verify root AGENTS.md and files exist. Stop on base mismatch; never reset another worktree.

## Objective

Prevent expected validation failures from changing inode identity of journal targets whose state never diverged from the before snapshot. Today abort unconditionally restores every target via atomic replace, even when current digest already equals before digest.

## File ownership

Only modify:

- `.agents/lib/research/journal.py`
- `.agents/lib/research/tests/test_recovery_contract.py`
- if indispensable, `.agents/lib/research/tests/test_r1_recovery_source.py`

No skill code, SSOT/schema/docs/version, installer, or real `kb/`.

## Locked design

1. During abort/resume restoration, compute current target digest and compare with the recorded before digest for each target. If equal, skip `_restore_target` entirely; preserve bytes, type, mode, and inode identity.
2. Restore only targets actually different from before-state. Preserve existing exact rollback semantics, ordering, digest verification, state transition, error reporting, and recovery checkpoint behavior.
3. `None`/absent, regular file, symlink, directory/tree and mixed target sets must be handled correctly. An absent target still absent is skipped; a newly created target is removed; a deleted/modified target is restored.
4. A malicious replacement with same bytes may have the same content digest; restoring it cannot recreate the original inode either, so zero-churn follows the journal's existing digest-defined state contract. Do not weaken after-state CAS for undo/restore.
5. No public output changes and no scope expansion.

## Tests

- Raise inside `journaled_op` before any target write: exact lstat dev/ino/mode + bytes for file and directory/symlink fixtures remain unchanged after abort.
- Mixed operation: one unchanged target preserves inode; one changed file is restored; one created path is removed; journal state is abort and digests are correct.
- Explicit `abort_op(..., restore=True)` and incomplete/resume path use the same zero-churn behavior.
- Existing recovery/undo/restore/after-state-CAS tests stay green.

Run focused recovery tests, Python 3.9 compileall, diff-check. Use apply_patch, temp data only, small commits, no push.

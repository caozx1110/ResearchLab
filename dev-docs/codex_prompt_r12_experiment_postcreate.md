# R12 experiment post-create precommit validation

## STEP 0

Create an isolated worktree from exact current integration base `57d62ab8f3c3ee91001775f7fb17543ea05eff6c`. Verify HEAD. Do not touch the maintainer worktree.

## Ownership

Only modify:

- `.agents/skills/experiment-workbench/scripts/experiment.py`
- a new experiment-specific test file under `.agents/lib/research/tests/`

Do not edit central registry, shared matrix, intake, paper, docs/version, real `kb/`, or unrelated files.

## Reproduced P1

After `_write_run_file_exclusive` succeeds, a mutation before run-log/record writes can overwrite/delete/rename/replace/type-change the created run or add another allocator entry. Current command may still return success and commit metadata; FIFO conversion can hang a later read.

## Required repair

- Exclusive creation returns a frozen created-run fact: runs-root identity, exact entry set/digest, leaf dev/inode/mode/size/mtime and byte digest.
- Before any run-log/record business write, and again at transaction precommit, reopen root and leaf no-follow; require the same safe directory, exact entry set, exact ordinary leaf identity and bytes. Never open/read a special file.
- Any post-create delete/overwrite/same-byte inode replacement/rename/root replacement/file→directory/symlink/FIFO/socket/extra-entry drift fails closed and transaction rollback removes/restores only operation-owned state. No hang.
- Both receipt and no-receipt paths obey this. Normal sequential/concurrent no-receipt allocations remain unique.

Add a permanent two-round matrix using deterministic mutation hooks for every case above, plus success and rollback assertions. Run all experiment tests, preference matrix, recovery tests, Python 3.9 compile and diff-check. Small commits, no push. Report exact hashes/counts and any residual issue.

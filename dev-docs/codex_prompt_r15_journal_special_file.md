# R15 — journal special-file nonblocking recovery

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r15-journal-special-file`. Verify HEAD is `9fbb009` and `.agents/lib/research/SCHEMAS.md` contains `Special-file nonblocking`. If not, stop and report.

## Reproduced defect

The full suite and a real `experiment-workbench log-run` transaction hang indefinitely when the freshly created `runs/run-001.md` is replaced by a FIFO before the second validation. Validation correctly rejects the FIFO, but journal abort calls `file_digest()` on the declared `runs/` target; directory traversal treats every non-directory/non-symlink child as a regular file and performs blocking `open/read`. The exact failing test is the FIFO case in `test_experiment_postcreate_consistency.py`.

## Objective

Make journal digest/snapshot/abort/restore classify nodes with `lstat` and never open FIFO/socket/device nodes. A special node introduced during a transaction must produce a bounded, distinct digest sentinel so abort detects divergence and removes/restores it. A special node already present at begin snapshot must fail closed before business writes. Preserve byte digests for ordinary files, link-target digests for symlinks, exact-tree digests for safe directories, zero-churn for unchanged targets, and recovery after-state CAS.

## File ownership

Edit only:

- `.agents/lib/research/journal.py`
- `.agents/lib/research/tests/test_recovery_contract.py`
- `.agents/lib/research/tests/test_experiment_postcreate_consistency.py` only if an assertion/timeout improvement is genuinely required

Do not edit schema/design/version/docs or experiment product implementation.

## Required validation

- Add a bounded regression that would time out rather than hang on the old implementation and proves FIFO handling at root and as a directory child; include socket where portable/useful.
- Prove begin snapshot rejects an existing special target with no business mutation.
- Prove an in-transaction FIFO replacement aborts, restores the exact before-state, and leaves terminal/coherent journal state.
- Run the exact existing FIFO matrix cases, full experiment postcreate suite, recovery contract suites, and `git diff --check`.

## Red lines

- Temporary KB only; never touch real `kb/`.
- No weakening of CAS, governance, exact target scope, locks, or atomicity.
- Do not follow symlinks and do not serialize raw special-node contents.
- No broad staging; no push/tag/publish/dependency changes.
- STOP and report if more files are necessary.

Commit the bounded fix and report hash, exact tests, and residual risks.

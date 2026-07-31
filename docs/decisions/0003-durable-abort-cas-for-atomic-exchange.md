# ADR 0003: Durable abort-CAS for atomic filesystem exchange

- Status: Accepted（仅在本 ADR 合入 default branch 后生效）
- Date: 2026-07-31
- Issue: [#11](https://github.com/caozx1110/ResearchLab/issues/11)

## Context

The Obsidian Base presentation reset has to replace a renderer-owned file without a rename gap and without overwriting an arbitrary external writer. Linux `renameat2(RENAME_EXCHANGE)` and macOS `renameatx_np(RENAME_SWAP)` provide the required atomic exchange, but the ordinary journal previously recorded only before snapshots. A process crash after the exchange and before process-local cleanup could therefore leave the desired inode at the target and the displaced inode at a private staging name without durable evidence of which inode the operation owned.

Content digests alone are insufficient. A third party can replace a file with the same bytes and mode but a different inode. Likewise, `lstat` followed by `unlink` is not an exact-inode compare-and-delete primitive on both supported platforms: another writer can replace the name between those calls and lose its leaf.

## Decision

Abort-CAS is an explicit root-transaction option, not a schema change for ordinary operations. Every operation durably creates `snapshots/<op_id>` before snapshotting, including absent-only ordinary operations, so later journal byte-CAS terminalization never depends on the before-image kind. An opted-in `begin` entry writes `research-kb-abort-cas/v1` in the same first journal publication. Every exact target records its initial no-follow parent-directory capabilities and full `before_leaf` state. A full leaf state contains kind, device, inode, complete type-and-permission mode, link count, device number, size, mtime in nanoseconds, and a bounded content or link-target digest. Symlinks and special nodes, including FIFOs, are classified with `lstat`; special nodes are never opened.

The durable phases are `unarmed`, `prepared`, `validated`, and `retained`:

1. `unarmed` binds the initial parent capabilities and before leaf.
2. The consumer creates an exclusive no-follow regular staging leaf under the operation's existing `snapshots/<op_id>` directory, fsyncs its contents and directory, then calls `arm_abort_cas`. The journal digest-CAS update records the staging path/capability, exact owned leaf, and exact expected displaced leaf before any exchange.
3. `exchange_abort_cas` revalidates both directory capability chains and both full leaf states, performs the platform atomic exchange, and compares both sides. A boundary mismatch is swapped back only when both observed leaves still equal the durable expected pair. If either observed leaf is unexpected, its compare-after position is preserved: the implementation cannot distinguish a target replacement immediately before the syscall from a staging replacement immediately after it, so it must not guess. Only the authoritative journal byte digest may advance the target to `validated`.
4. `retain_abort_cas` revalidates the exact displaced leaf in the private snapshot directory; an exact regular leaf is opened no-follow, file-fsynced, and identity-revalidated before the staging directory fsync, while symlink/FIFO/special leaves remain `lstat`-only and are never opened. Only then may the journal advance to `retained`. It deliberately does not unlink. A guarded Base reset may commit only when all targets are retained and a final two-pass validation still sees every exact owned target, retained leaf, and directory capability.

The retained name is durable recovery material and remains inside the ignored, private journal snapshot tree. This trades bounded private runtime storage for a portable no-data-loss contract. A later journal-garbage-collection design must not assume that `lstat` plus `unlink` is an inode CAS.

Abort and explicit resume classify the complete target set before the first business-target write. Immediately before each recovery syscall they re-read both target and staging and require the same durable owned/displaced pair; a staging race after full-set classification therefore produces zero exchange. A pre-exchange `prepared` target already at its exact before leaf needs no target write. A post-exchange `prepared`, `validated`, or `retained` target is swapped back only when the target is the exact owned leaf and staging is the exact recorded displaced leaf. Recovery compares both sides and reverses a mismatched recovery exchange when safe. Any absent, different regular file, symlink, FIFO, special node, ancestor rebind, staging rebind, missing retained leaf, or journal digest race produces or preserves `abort_failed`; new work remains quarantined. Resume may consume `begin` or `abort_failed` only after the same proof succeeds. Legacy unfinished Base-reset journals without abort-CAS are refused without target writes. Ordinary legacy begin recovery and committed undo remain unchanged.

The consumer call contract is:

```text
mutation_transaction(..., abort_cas=True)
load_op_view(...).digest
arm_abort_cas(..., expected_journal_digest=digest, staging_leaf=name)
exchange_abort_cas(..., expected_journal_digest=digest)
retain_abort_cas(..., expected_journal_digest=digest)
transaction commit
```

Each transition returns the next authoritative journal digest. Abort-CAS is rejected for nested transactions because a descendant cannot own the root crash-recovery boundary.

Journal transition CAS itself uses the same exchange discipline. New YAML is fsynced under `snapshots/<op_id>`, atomically exchanged with the authoritative root entry, and the displaced bytes are compared to the expected digest. A mismatch is reversed when the published side is still the exact new inode; the competing authoritative bytes remain authoritative. Successful transitions retain the displaced journal version in the private snapshot tree rather than using an unsafe compare-then-unlink cleanup.

## Consequences

- Same-content inode replacement is detected at begin-to-arm, exchange, retain, and commit boundaries.
- Atomic exchange remains unavailable on platforms without a native exchange primitive; there is no ordinary-rename fallback.
- Retained material can include an exact regular file, symlink, FIFO, or other special leaf without opening it during classification.
- Multi-target recovery fails closed before writes when any target is already unprovable. A race at the exchange syscall may require one compensating exchange solely to preserve the exact displaced state.
- `abort_failed` is an incomplete root for quarantine and operation ordering, not a terminal success state.
- The Base reset consumer no longer owns a process-local post-abort recovery object or an unlink cleanup path.

## Alternatives considered

- Rely on before/after content digests. Rejected because equal bytes do not prove inode ownership.
- Keep process-local displaced-inode recovery. Rejected because it disappears on process crash.
- Delete staging with `lstat` followed by `unlink`. Rejected because no portable exact-inode unlink CAS exists on Linux and macOS.
- Move to a random quarantine name and then unlink. Rejected because the final compare-to-unlink window remains.
- Fall back to sequential rename. Rejected because it introduces a missing-name window and cannot preserve both leaves under races.

## Rollback

The Base reset consumer can be disabled while retained journals remain readable. A code rollback must not auto-recover or delete an unfinished `research-kb-abort-cas/v1` entry unless the rollback implementation understands this contract. It must instead fail closed and require a forward recovery implementation. Canonical records and human-owned Obsidian paths are never part of this protocol.

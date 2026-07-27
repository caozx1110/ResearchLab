# R17 Track A — recovery integrity

## STEP 0 — base sync

Create an isolated worktree/branch from exact integration HEAD `447cea7` and verify that `.agents/lib/research/journal.py`, `.agents/lib/research/git_ops.py`, and the R17 schema bullets exist. If the worktree is stale, reset only that disposable worktree to `447cea7` before editing. Never reset the integration checkout.

## Ownership

Only edit:

- `.agents/lib/research/journal.py`
- `.agents/lib/research/git_ops.py`
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/lib/research/tests/test_recovery_contract.py`
- `.agents/lib/research/tests/test_r1_recovery_source.py`

Do not edit SCHEMAS, docs, installer/updater files, version metadata, or any real `kb/`.

## Required fixes

Implement the R17 SSOT/SCHEMAS contracts exactly:

1. **Incomplete-root quarantine.** With the workspace lease held, a new independent root operation must fail before a new journal/checkpoint/business write if any other root journal has `state=begin`. Nested operations and explicit recovery operations need a narrow internal role/exception; do not expose a generic caller-controlled bypass. Recovery must remain possible. Audit direct `begin_op`/`journaled_op` use as well as `mutation_transaction` so the invariant cannot be bypassed accidentally.
2. **Provable legacy resume order + single consumption.** New code permits only one incomplete root. Historical disjoint roots may be recovered in stable order; overlapping roots without a workspace-lease-allocated persistent monotonic order must fail closed rather than guessing from wall clock/mtime/UUID. Restore, recovery checkpoint, and source root/descendant terminalization stay under one workspace lease so concurrent resume consumes each source once; a failed newest root never advances to older roots.
3. **Lexical target identity.** Resolve only the KB root. Existing callers may pass an absolute `Path` that is lexically under the canonical KB root; normalize that to a safe lexical KB-relative key without dereferencing its leaf. Reject journal keys that are absolute or contain empty/`.`/`..` segments, plus declared-path escape and symlink ancestors, before business writes. Close ancestor validate→swap TOCTOU with anchored dirfd/nofollow identity checks through snapshot/digest/restore. A leaf symlink is snapshotted as the node itself; abort/resume and committed undo/restore preserve its exact `readlink` text without touching dangling/relative/absolute-outside referents. Locks/journal/Git pathspec/checkpoint/result use the same lexical key.
4. **Journal envelope + target-set integrity.** Quarantine and recovery must nofollow/boundedly reject truncated/nonmapping/unknown-state or symlink/special entry files and raw YAML duplicate mapping keys. Under workspace lease bind one authoritative source-entry bytes/identity view. Before target locks/recovery journal/business writes, require unique canonical target_paths exactly equal to before_digests/before_snapshots; committed recovery also equals after_digests. Preflight all snapshot kinds/paths/payload digests before restoring target one, or prove rollback leaves every target unchanged.

## Mandatory adversarial regressions

- `v0 → op1 begin/partial-v1 → attempt independent op2`: op2 is rejected with no op2 journal and no further business write; after `resume`, value is `v0`.
- Construct disjoint legacy roots and prove recovery; construct overlapping roots with equal timestamps, clock rollback, or only wall-clock/mtime/UUID order and prove fail-closed with zero target/journal change.
- Concurrent resume consumes one root once; pause between restore/checkpoint/terminalization and prove a second process cannot duplicate or skip. A failure on newest never advances older.
- `alias -> real`, declare `alias`, unlink/replace alias with a regular file, raise: abort restores `alias` as a symlink with the same link target; referent stays unchanged; journal key is lexical alias. Also cover dangling/relative/absolute-outside leaves and commit→checkpoint→undo/restore lexical identity.
- Swap a validated ancestor to an outside symlink at a deterministic hook before snapshot/write: outside referent stays untouched and the operation fails closed.
- Symlink ancestor, `..`, absolute journal key, and outside target fail before journal/business write; an absolute API `Path` under the canonical KB root remains supported.
- Tamper a two-target committed journal so one of target_paths/before maps/after map is missing, extra, duplicated, or noncanonical, including raw YAML duplicate map keys and invalid/missing/escaping/digest-mismatched snapshot payloads: fail before partial restore (or prove exact rollback), no successful recovery journal.
- With an incomplete root, manual/auto checkpoint, git-init, direct begin/journaled/mutation all leave HEAD/index/business/journal unchanged. Malformed/special journal entries quarantine rather than being ignored.
- Existing special-file/FIFO nonblocking, canonical `/var` projection, after-state CAS, zero-churn inode, nested transaction, subprocess concurrency, undo/restore tests remain green.

## Red lines

- Tests use temporary KBs only. Never touch a real `kb/`.
- Do not weaken evidence/confirmation/containment.
- Do not make scripts infer research meaning.
- Public output remains natural language + `kb <verb>` only; no raw commands, flags, paths, `NEXT FOR AGENT:`, or TTY dependency.
- Checkpoints stay exact-path only.
- No push/tag/publish.

## Validation and commits

Run both owned test modules plus relevant dispatcher recovery tests if available, Python syntax, and `git diff --check`. Make small commits, at least one implementation+regression commit. Report exact commits, tests, and any unresolved concern. STOP and report rather than guessing if the lexical-path change requires broad caller edits outside ownership.

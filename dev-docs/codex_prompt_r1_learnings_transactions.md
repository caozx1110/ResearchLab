# R1 learnings load-modify-write transaction closure

## STEP 0 — base sync

Start only from the latest integration commit supplied by root after `codex/r1-writer-sweep` is merged. Verify `load_runtime_preferences` is pure read and `research.journal.mutation_transaction` has workspace/hierarchical coordination. If not, STOP; do not reset to an older branch.

## Objective

Eliminate silent lost updates in lightweight learnings and make preference promotion atomically update both governed files.

## File ownership — only these files

- `.agents/lib/research/learnings.py`
- `.agents/lib/research/prefs.py` (`write_runtime_preferences` standalone transaction safety only; preserve the pure-reader change)
- `.agents/lib/research/tests/test_learnings_memory.py`
- one new narrowly named transaction/concurrency test under `.agents/lib/research/tests/`

Do not edit the skill CLI, shared journal/common/git helpers, or unrelated tests.

## Independently reproduced failure

The original `/private/tmp/r1_learnings_lost_update_probe.py <repo>` forced ten `log_learning` calls to read the same empty list. All ten returned success with `lrn-...-001`, while the final YAML contained one entry with only one occurrence. Note that texts of the form `distinct learning N` are above the existing 0.86 similarity threshold, so correct behavior for those inputs is one entry with `occurrences=10`; use genuinely low-similarity texts for the 10-unique case.

## Required behavior

1. `log_learning` holds one canonical transaction on `learnings.yaml` across load, similarity/dedup decision, ID allocation, and write. Ten genuinely low-similarity concurrent logs survive with unique IDs; ten equivalent entries deterministically produce one entry with `occurrences=10`.
2. `review_learning` holds the same transaction across lookup and write.
3. `promote_learning` is one root transaction targeting both `learnings.yaml` and `runtime-preferences.yaml`; a fault after the first business write restores both byte-for-byte. Its nested calls must be covered, not exempted.
4. `write_runtime_preferences` is standalone-safe: it wraps its own load/merge/write in canonical transaction. Existing config callers may nest only when their root target covers the preferences path.
5. `load_learnings`, recall/render paths, and `load_runtime_preferences` remain byte-identical pure reads on absent roots.
6. Add deterministic barrier-based concurrency regression, promote fault injection, standalone preference rollback/CAS-style serialization, and read-only snapshots. Important: the original reproduction monkeypatched a barrier *inside* `load_learnings`; after the fix that would deliberately block the lock holder while peers wait for the lock. The fixed regression must synchronize callers immediately before entering the real transaction (for example, wrap the module-imported transaction with a pre-entry barrier and then delegate), while keeping the effective load→decision→write entirely inside the canonical transaction. Assert both low-similarity `10 unique` and high-similarity `1 entry / occurrences=10` outcomes.

## Red lines

- Temporary workspaces only; never real `kb/`.
- Do not alter learning similarity/governance semantics or auto-confirm anything.
- No public raw command/flag/path output changes.
- No push. Small commits, targeted plus full suite, `git diff --check`, clean status. STOP if root coverage is insufficient; never relax the transaction primitive.

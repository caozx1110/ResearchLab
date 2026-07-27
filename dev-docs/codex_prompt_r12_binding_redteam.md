# R12 focused cold audit — preference registry/tree binding/experiment allocator

Read-only adversarial behavior audit at exact integration HEAD. This is a test of shipping code, not a design source. Do not modify source, docs, git refs, or any real `kb/`; use fresh `mktemp -d` workspaces only.

Review and independently reproduce:

1. Every declared real consumer operation has exactly one closed canonical-input field registry; missing/extra/unknown operation fails closed. Compare actual owner context producers against registry, not just the registry against itself.
2. `regular_file_binding` and `regular_tree_binding` are no-follow, streaming, resource-bounded, deterministic, detect leaf inode replacement and directory-entry races, and do not silently truncate/sample.
3. `experiment-workbench:log-run` binds proposed id/path and allocator state. Test insert/delete/rename/byte/type/symlink/FIFO/directory races before and after receipt, with and without receipt, two independent rounds. Failure must not alter record/run-log/journal/business state; successful concurrent no-receipt calls remain serial and unique.
4. Check Python 3.9 syntax/import, public-output contract, and that preference values are not durably copied.

Run targeted existing tests plus your own disposable probes. For each finding reproduce twice, classify P0–P3 and give the smallest repair. Report exact HEAD, commands/test counts, and distinguish actual blocker from hypothetical hardening. No commit/push/tag.

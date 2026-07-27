# R4 adversarial remediation handoff

## STEP 0 — base sync

Verify branch `codex/review-remediation-integration`, HEAD `bc65ce8`, current version `0.2.0-rc.3`, and the R3 modules named below. Stop and report if the base differs; do not reset a dirty or unknown worktree.

## Scope and ownership

This integrated remediation owns only the relevant SSOT/schema/docs, shared runtime modules, kb-cli/report/scout product sources, installer, and their tests. Preserve unrelated user edits and never touch real `kb/`. Shipping skills are product source, not development instructions.

## Required fixes

1. Make current confirmation consumers revalidate artifact bytes and canonical source containment; reject cross-unit/program symlink roots.
2. Make committed-operation undo/restore compare every current target to `after_digests` before any recovery mutation.
3. Preserve the tracked root `CLAUDE.md -> AGENTS.md` symlink through source/self-contained install/update/reinstall/uninstall; reject other symlink targets safely.
4. Lock source-search stage identity, dedupe persisted candidates by work id then DOI while preserving manual state.
5. Exclude standalone block IDs from passages; distinguish corrupt cache internals from stale canonical corpus.
6. Correct schema/help drift and make fresh empty `kb review` byte/mtime zero-write while retaining GC for an existing registry.
7. Bump all release surfaces to `0.2.0-rc.4` only after gates pass.

## Red lines

- Agent supplies understanding; scripts only move/validate.
- Never weaken confirmation, evidence, containment, journal, CAS, lock, or exact checkpoint gates.
- User-visible output contains only natural language and existing `kb <verb>` forms; no flags, paths, tokens, digests, or TTY dependency.
- Tests use temporary directories only. No push/tag/publish.
- Commit per coherent piece; stop and report on ambiguous contract or unexpected user-state overlap.

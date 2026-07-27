# R1 local source containment and public add output

## STEP 0

Verify worktree HEAD is `3fa9a51c8d75b02bc978a5e68a6bf3e76ffcdc27`, canonical source transaction tests exist, and no real `kb/` is touched. Read root AGENTS and SSOT first.

## Ownership

- `.agents/lib/research/sources.py`
- `.agents/skills/kb-cli/scripts/kb`
- `.agents/lib/research/tests/test_backup_source.py`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py`
- one new narrow local-source/public-output test if needed

Do not edit intake workflow, journal, governance, installer, or docs.

## Reproduced failures

`/private/tmp/r1_public_next_add_probe.py <repo>` creates `source/leaked-secret.txt -> ../outside-secret.txt`. Public `kb add` returns 0 and copies the outside bytes into the canonical repo source and two journal snapshots. Its stdout also exposes `[source] backup_status=... source_type=... locator_kind=...` and `[ok] git checkpoint: <hash>`.

## Required

1. Directory source traversal must use `lstat` and never follow symlinks. Prefer fail-closed for any symlink in the selected source tree, with a natural-language public failure and no canonical unit/dedup identity/journal copy. Every resolved copied child must remain under declared source root.
2. Cover file symlink and nested directory symlink escape, plus an in-tree symlink; none may copy target bytes. Ordinary real directory ingest remains green.
3. Public `kb add/ingest` filtering must suppress source protocol fields, checkpoint hashes, internal paths and `[auto]` details while retaining natural-language completion, pending-review guidance, and a supported `kb <verb>` next step. Keep raw child stdout in private AgentProtocol.
4. Rerun the root probe: no outside-secret hits, nonzero add is acceptable/expected for unsafe source, and forbidden fields absent.

No push. Small commits; targeted + full suite, diff-check, clean status.

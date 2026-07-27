# R18 track A — canonical record strict reader

## STEP 0 — base sync

This worktree is reusable and may be behind integration. Confirm the integration HEAD is `7055120`. If your worktree is not based on that exact commit, ensure it is clean, then `git reset --hard 7055120` and verify the new R17 strict-read text exists in `temp/SYSTEM_DESIGN_SSOT.md` and `.agents/lib/research/SCHEMAS.md`. Stop and report if the worktree is not clean or the commit is unavailable.

## Objective

Close the independently reproduced canonical `record.yaml` read failures: a symlink outside the workspace is accepted, a FIFO blocks `iter_records`, and a duplicate top-level YAML key remains eligible for review. Build one shared strict snapshot reader and route unit enumeration plus judgement discovery through it without weakening any review/evidence gate.

## File ownership

Only modify:

- `.agents/lib/research/records.py`
- `.agents/lib/research/judgements.py`
- `.agents/lib/research/yaml_io.py` only if a reusable strict bytes loader is necessary
- record/review/status/find tests under `.agents/lib/research/tests/` (prefer existing files; a new exact test file is allowed)

Do not touch `sources.py`, any shipping skill script, docs, version, installer, journal/recovery, or real `kb/`.

## Required contract

- Enumerate only canonical `kb/units/<known-kind-dir>/<safe-unit-id>/record.yaml` entries. Do not use `Path.glob/read_text` as the trusted read.
- Anchor from the lexical workspace root with directory fds, `O_NOFOLLOW`, and stable identity checks. Leaf uses `O_NONBLOCK | O_NOFOLLOW`, must be a bounded regular file, is read once, and is revalidated after read. Revalidate every ancestor identity before returning the snapshot.
- YAML is UTF-8 mapping data and rejects duplicate mapping keys at every depth. A bad single record is skipped/fail-closed in bulk inbox/search/status discovery and must not block or escape; no raw path/value is printed publicly.
- The parsed record `kind/id` must exactly match its lexical kind directory and unit directory. Never normalize an unsafe path into acceptance.
- `iter_records`, canonical unit portion of `discover_pending_judgements`, `kb status/next/find/review` consumers must share the same accepted set. Preserve side-judgement behavior and evidence/readiness rules.
- Do not globally break legacy non-record YAML. If changing generic `load_yaml` is too broad, add a strict bytes/object loader and use it only in the canonical reader.

## Permanent tests

At minimum prove:

- external, dangling, and swap-race leaf symlink are never accepted;
- FIFO/socket/directory/oversized leaf returns promptly and does not block sibling valid records;
- duplicate keys at top level and nested judgement/verification fields are excluded from review/status/portfolio/find;
- kind/id vs lexical directory mismatch is excluded;
- ancestor unit/kind/units directory rename/symlink replacement during enumeration makes that candidate fail closed;
- one corrupt candidate does not hide valid siblings and pure reads create no files;
- existing ready repo/paper/blog/dataset review cards remain discoverable with exact evidence gates.

Use temp directories only. Reproduce each old failure red before the fix. Run exact affected tests plus public diagnostics/release tests. Run Python 3.9 AST and `git diff --check`.

## Red lines

- Never touch a real `kb/`.
- Do not loosen confirmation, evidence, readiness, or record schema rules.
- Scripts do not infer research meaning.
- Public output remains natural language + `kb <verb>` only.
- No push/tag/version bump.
- Commit per coherent piece. If an anchored portable implementation is unclear, STOP and report instead of using `resolve()` or a second path reopen.

# R18 track B — literature selection and continuation integrity

## STEP 0 — base sync

This reusable worktree may be behind integration. Confirm integration HEAD is `7055120`. If not, ensure clean, then `git reset --hard 7055120`. Verify the new R17 strict selection/protocol design exists in `temp/SYSTEM_DESIGN_SSOT.md` and `.agents/lib/research/SCHEMAS.md`. Stop if dirty/unavailable.

## Objective

Close every independently reproduced literature continuation/owner-adapter gap from the second R17 review: exact nested stage schema and ancestor revalidation; user-visible selection binding; validate→digest symlink race; canonical-outcome-first handling; append-only receipt idempotency; preclaimed durable private protocol; duplicate JSON/YAML rejection; bounded streaming capture; type-aware Chinese synthetic next output.

## File ownership

Only modify:

- `.agents/lib/research/sources.py`
- `.agents/skills/literature-search/scripts/search.py`
- `.agents/skills/source-intake/scripts/intake.py`
- `.agents/skills/kb-cli/scripts/kb`
- literature/agent-next/kb-public tests under `.agents/lib/research/tests/`
- `literature-search` reference/SKILL text only if the private selection schema changes

Do not touch `records.py`, `judgements.py`, `yaml_io.py`, installer/recovery/report/version/public release docs, or real `kb/`.

## Required contract

1. `sources.py` exposes one descriptor-anchored strict literature stage snapshot that returns exact bytes, parsed payload and digest from the same ordinary-file read. Revalidate the full root→kb→synthesis→source-search ancestor chain before returning. Both portfolio continuation and adapter/source-intake use it; no validate-then-Path-read/digest sequence.
2. The stage schema is exact at every mapping/list variant: top-level identity/status/query/generated_by/time fields, candidates including status/record_id, queries/history/coverage/frontier/stop and nested items. Reject unknown fields, wrong types/enums/timestamps and duplicate YAML keys. Preserve only explicitly documented legacy identity migration fields.
3. Selection JSON rejects duplicate keys and unknown fields. Advance its schema if needed. It must carry `display_binding`: exact stage byte digest plus each chosen candidate's identity and semantic digest from the user-visible projection. Adapter checks this before any protocol claim or owner dispatch; a candidate edit between display and user selection is zero-owner-write stale failure.
4. Reserve protocol name before owner dispatch using anchored `O_EXCL` durable claim containing the value-free selection binding. Fsync each newly created directory's direct parent and the claim. Finalize only if the visible name still has this operation's claim identity, then fsync the leaf directory. Same-name races fail before canonical owner writes. Crash claim remains safely inspectable; never overwrite another writer.
5. After any owner return code, timeout or capture exception, inspect the strict final stage snapshot and exact append-only record receipt. If and only if canonical facts prove the unique allowed transition, count success; the process outcome is private diagnostics. Exact `source_search.selections[]` is authoritative for old idempotent receipt; later `user_selection` display changes do not invalidate it.
6. Default subprocess capture streams stdout/stderr concurrently without storing unbounded raw bytes. Keep only bytes, lines, sha256, bounded error class/truncated metadata. Avoid pipe deadlock; timeout must terminate/reap the child. Injected test runners may remain supported.
7. `kb next/status` renders synthetic action types in Chinese business language, hides internal namespace/stage IDs by default, and never emits raw English `reason`. Check literature/review/monitor/survey/composite synthetic families.

## Permanent tests

Reproduce red first, then prove at minimum:

- candidate extra field, illegal stage status/query/generated_by/history fields and nested duplicate YAML all reject;
- source-search ancestor rename→symlink replacement during enumeration/read rejects the entire snapshot;
- validate→digest/load leaf swap to symlink/FIFO cannot produce digest or block;
- display candidate title/URL/identity mutation before adapter starts makes zero owner calls;
- owner canonical commit + exit 23/timeout/capture exception reports success only when exact transition+receipt prove it; nonzero without facts fails;
- old exact `selections[]` replay remains valid after later display/user-selection update;
- two same-name operations: loser never calls owner; claim/finalization race cannot orphan a committed result; directory fsync identities cover every mkdir parent;
- duplicate selection JSON rejects before owner;
- a child emitting at least 8 MiB is drained with bounded resident raw storage and correct byte/hash metadata; stdout/stderr simultaneous output cannot deadlock;
- public synthetic next output contains no `literature:`/`review:`/`monitor:`/`survey:` IDs, raw English reason, internal path, shell or flag.

Run literature adapter/search/intake, agent-next, kb dispatcher/public diagnostics/conversational release tests, Python 3.9 AST, official quick validation for changed skills, and `git diff --check`.

## Red lines

- Temp workspaces only; no real `kb/`.
- No semantic paper selection by scripts; user/Agent judgement remains outside.
- No evidence/governance weakening and no public raw protocol.
- No push/tag/version bump.
- Commit per coherent piece. STOP and report if portability or crash semantics cannot meet the contract.

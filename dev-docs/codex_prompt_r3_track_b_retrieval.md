# R3 Track B — passage retrieval + HTML acceptance

## STEP 0 — base sync

Work only in the assigned worktree. Verify HEAD is exactly `d633480115a75c6ca55a4430b73a7e5985c218c9`; verify `research.retrieval.rank_records` and `source_materials.select_html_reading_root` exist. Wrong base means STOP and report; do not reset or guess.

Read the main workspace `AGENTS.md` and the R3 retrieval decision in `temp/SYSTEM_DESIGN_SSOT.md`. Shipping skills are product source, not design authority.

## Ownership — only edit these files

- `.agents/lib/research/retrieval.py`
- `.agents/lib/research/index.py`
- `.agents/lib/research/paths.py`
- `.agents/lib/research/core.py` only for compatibility exports
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/lib/research/tests/test_ranked_retrieval.py`
- `.agents/lib/research/tests/test_build_index_single_scan.py`
- `.agents/lib/research/tests/test_source_material_formats.py` only for independent HTML acceptance additions

Do not edit `kb-cli/scripts/kb`, schemas, docs, version, source material implementation, analyzer scripts, or real `kb/`. Root integration will adapt the public find projection and shared docs.

## Required behavior

1. Implement deterministic passage extraction from canonical unit data. Include title/summary and safe Markdown reading/note files under the unit; preserve artifact + project-relative locator + heading/line range. Split by headings/paragraphs; fixed max window and overlap for long blocks. Never summarize or infer.
2. Add atomic SQLite FTS5 cache at `kb/.runtime/search/passages.sqlite3`. Schema metadata binds a revision and a digest of every indexed record/artifact. Do not use external-content tables. Build into a same-directory temporary file, fsync/close, then replace; reject symlink/non-file collisions and preserve the prior cache on failure.
3. Use `unicode61`, BM25, and explicit column weights. Return top passages with unit identity, excerpt, artifact, locator, and internal score. Do not expose score/absolute path in owner public text.
4. `build_index` rebuilds the runtime cache safely after canonical index material. The cache is derived, gitignored, never canonical evidence/checkpoint content. Avoid rescanning records more than necessary; accept a shared records list.
5. Query path is byte-read-only. If cache is missing, stale, corrupt, or FTS5 unavailable, run the same extractor with deterministic in-memory lexical ranking. Return health metadata (`current|missing|stale|corrupt|unavailable`) through a narrow API so root can put it in private protocol. Do not write during search.
6. Preserve filter-only `search_records(..., query="")` behavior for review queues. Existing record ranking compatibility may remain, but nonempty user find must have passage results.
7. CJK/ASCII mixed queries must work lexically; do not add translation/embedding claims.
8. Independently verify existing HTML behavior with tests for earlier tiny recommendation `<article>` vs substantial `<main>`, layout-table code preservation/no orphan pipes, and remote fragment externalization without degradation. Only add missing assertions; do not change `source_materials.py` because the feature is already implemented.

## Security/recovery

- Safe walk: no followed symlink directories/files; exclude raw/runtime/journal/output/obsidian/source originals not intended for reading.
- A corrupt/stale cache cannot hide correct current results: fallback must work.
- No cache mutation may roll back or alter canonical KB.
- Do not add dependencies; use stdlib `sqlite3`.

## Verification / commits

- Focused ranked retrieval, build-index, source-format, recovery and pure-reader tests.
- Assert `kb find`'s underlying query does not change a tree snapshot when cache is stale/missing.
- `git diff --check`; small commits; no push.
- Final report exact commits/tests and the API root must wire into `kb-cli`.

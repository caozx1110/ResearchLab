# Learnings

## [LRN-20260723-001] best_practice

**Logged**: 2026-07-23T21:34:00+08:00
**Priority**: high
**Status**: resolved
**Area**: retrieval

### Summary
Display metadata replicated onto every passage row must not automatically be searchable, or a title-only match promotes unrelated excerpts from the same unit.

### Details
Cold acceptance on a real SQLite Query Planning page exposed that FTS and fallback ranking searched the unit title copied into every body passage. Frontmatter, a table of contents, and an unrelated section appeared as title matches even though their excerpts lacked the query. The fix kept title/summary available for display, made those FTS columns `UNINDEXED`, searched only heading/body in fallback, and retained dedicated title/summary passages for metadata retrieval.

### Suggested Action
Separate display fields from searchable bytes in row-oriented retrieval schemas, bump cache revisions when index semantics change, and test both derived-cache and no-cache paths with multiple unrelated passages in one titled unit.

### Metadata
- Source: cold_acceptance
- Related Files: `.agents/lib/research/retrieval.py`, `.agents/lib/research/index.py`, `.agents/lib/research/tests/test_ranked_retrieval.py`
- Tags: retrieval, fts5, ranking, passage-quality, acceptance
- Pattern-Key: harden.separate_display_metadata_from_searchable_passage
- Recurrence-Count: 1
- First-Seen: 2026-07-23
- Last-Seen: 2026-07-23

---

## [LRN-20260719-001] best_practice

**Logged**: 2026-07-19T12:37:59+08:00
**Priority**: high
**Status**: pending
**Area**: config

### Summary
An exact dependency lock must recursively traverse selected distribution metadata; pinning only a top-level package and its immediate requirements can still leave range-resolved second-order dependencies.

### Details
The proposed pytest closure included `exceptiongroup` for Python below 3.11 but omitted its selected dependency on `typing-extensions`. Managed Python 3.9 metadata exposed the missing second-order edge. A static expected package list alone would have certified this incomplete lock.

### Suggested Action
For release gates, parse requirement markers, evaluate the target environment, and recursively compare selected package metadata edges against exact pins. Keep a maintained offline metadata table so the test is deterministic without network access.

### Metadata
- Source: error
- Related Files: `requirements-dev.txt`, `.agents/lib/research/tests/test_r1_conversational_release.py`
- Tags: dependencies, release-gate, reproducibility, markers
- Pattern-Key: harden.recursive_dependency_closure
- Recurrence-Count: 1
- First-Seen: 2026-07-19
- Last-Seen: 2026-07-19

---

## [LRN-20260721-001] correction

**Logged**: 2026-07-21T21:03:11+08:00
**Priority**: high
**Status**: resolved
**Area**: backend

### Summary
Valid Obsidian Markdown is not enough: generated knowledge pages need real Reading-view QA and injective escaping of canonical plain text.

### Details
User testing in Obsidian 1.12.7 showed that editor/Live Preview intentionally exposes wikilinks, backticks, and block IDs. Reading view rendered those structures, but also proved that canonical `<name>` disappeared as HTML and glob `*` changed emphasis. Long wikilink Properties were physically wrapped by PyYAML. Unit tests that only parsed YAML and searched source strings missed all three presentation failures.

### Suggested Action
Treat Reading view as the generated-page consumption contract without writing `.obsidian`; escape canonical plain text injectively, disable YAML line wrapping for Properties, version the renderer in the manifest, and visually inspect a real artifact in both editor and Reading views.

### Resolution
Implemented renderer revision 2, no-wrap Obsidian YAML, literal-safe dynamic Markdown, local-source redaction, readable claim/evidence labels, Home/user-guide Reading-view guidance, and stale-on-renderer-upgrade behavior. Added exact Ψ₀ regression fixtures, passed 875 release tests, then rebuilt the real projection and visually confirmed the canonical literals in Obsidian Reading view without changing canonical or human-authored bytes.

### Metadata
- Source: user_feedback
- Related Files: `.agents/lib/research/obsidian.py`, `.agents/lib/research/yaml_io.py`, `.agents/lib/research/tests/test_obsidian_projection.py`
- Tags: obsidian, markdown, rendering, visual-qa, derived-view
- Pattern-Key: harden.derived_markdown_visual_fidelity
- Recurrence-Count: 1
- First-Seen: 2026-07-21
- Last-Seen: 2026-07-21

---

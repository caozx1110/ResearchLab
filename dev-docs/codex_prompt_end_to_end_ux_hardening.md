# Handoff — real-source and Obsidian end-to-end UX hardening

## STEP 0 — base sync

Before any implementation, verify `git rev-parse HEAD` and confirm these modules exist: `.agents/lib/research/source_materials.py`, `sources.py`, `obsidian.py`, and `install.sh`. The intended base for this track is the current branch head `e8c018a`; if an isolated worktree is stale, stop and report rather than editing the wrong tree. Never reset the shared root worktree.

## Locked design source

Follow `temp/SYSTEM_DESIGN_SSOT.md` sections 3.1 and 3.5.1 as updated on 2026-07-22. Shipping `.agents/skills/*/SKILL.md` files are product source, not development instructions. They may only be invoked in explicit final behavior tests.

## Implementation ownership

- Source/materialization: `.agents/lib/research/source_materials.py`, `.agents/lib/research/sources.py`, their focused tests, and schema/public docs required by the new additive fields.
- Obsidian UX/projection: `.agents/lib/research/obsidian.py`, its focused tests, and user-facing docs.
- Integration: installer/init/CLI tests only when an actual regression requires it.
- Do not edit analyzer judgement logic, confirmation governance, unrelated skills, or real canonical records as part of implementation.

## Required fixes

1. Render Obsidian Bases using application-canonical property spelling; allow only controlled convergence from prior manifest bytes to semantically equivalent application-normalized desired bytes. Preserve every other drift fail-closed.
2. Fetch Hugging Face dataset card raw Markdown before the dynamic page; retain the user URL as `original_uri`, record the resolved content endpoint, and fail/degrade when the materialized content lacks dataset-card identity/substance.
3. Select a substantive semantic HTML reading root instead of the first article; exclude site chrome from Markdown/archive while preserving raw response bytes.
4. Unwrap single-cell layout tables around code/media; lint orphan pipe cells and table wrappers crossing fenced code.
5. Make Home and unit pages decision-oriented: real summary or honest “awaiting analysis”, reading/original actions, materialization health, analysis stage/next step, compact relationships/claims, technical details last.
6. Bump renderer/materialization metadata only where contract changes require it and keep all readers backward compatible.

## Red lines

- Scripts never author research understanding or dataset suitability judgements.
- Raw/source/document/map/conversion assets remain immutable evidence; no in-place migration of existing unit bundles.
- No self-signing, no confirmation weakening, no judgement write fail-open.
- No `.obsidian/` configuration changes, plugin installation, or TTY-dependent workflow.
- User-visible output remains natural language + `kb <verb>` only; no raw Python, flags, `${…}`, internal paths, or `NEXT FOR AGENT:` leaks.
- No push. Commit each coherent piece separately. If a source contract or drift case is ambiguous, STOP and report.

## Acceptance

- Focused regression tests for every reproduced finding and negative drift/security cases.
- Full suite, Python 3.9 import/behavior, validators, shell syntax, and `git diff --check`.
- Final runtime test installs the committed tree into `/Users/czx/Documents/knowledge_base`, initializes a clean KB, ingests real public paper/HTML/dataset/Markdown/repo inputs, rebuilds Obsidian, opens actual Reading view, then repeats update after Obsidian normalization and requires PASS/no drift.

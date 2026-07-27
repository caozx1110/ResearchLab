# Obsidian no-plugin projection implementation handoff

## STEP 0 · Base sync

Before editing, verify `HEAD` is the current local `main`, `.agents/lib/research/index.py`, `confirm.py`, and the current kb-cli dispatcher exist, and inspect `git status`. If running in an isolated stale worktree, reset that worktree to the current main HEAD before continuing. In the active maintainer worktree, preserve all pre-existing changes—especially the intentional root `AGENTS.md` development-rule edit—and never reset or overwrite them.

## Goal

Implement SSOT §3.5.1: a no-plugin Obsidian projection under `kb/obsidian/` with stable unit/heading/block links, typed inverse relations, native Bases, safe manifest reconciliation, read-only status/audit, and `kb obsidian update|status`.

## File ownership

Primary implementation may modify only:

- `temp/SYSTEM_DESIGN_SSOT.md`, `temp/BACKLOG.md`, this handoff
- `.agents/lib/research/SCHEMAS.md`
- `.agents/lib/research/relations.py`, `.agents/lib/research/obsidian.py` (new)
- `.agents/lib/research/confirm.py`, `records.py`, `core.py`, `paths.py`
- `.agents/skills/kb-cli/scripts/kb`
- `.agents/AGENTS.md`
- focused tests under `.agents/lib/research/tests/`
- public user docs only where the shipped command surface is enumerated

Avoid unrelated refactors. Do not edit analyzer logic.

## Required behavior

1. Canonical links store one explicit forward edge. A registry derives named inverse relations; legacy `reverse:*` remains readable and auditable.
2. Optional source/target locators support unit, heading, and stable block references.
3. Projector writes only `kb/obsidian/managed/**`, creates but never manages `inbox/annotations`, never writes `.obsidian/`, and reconciles obsolete files only from a validated prior manifest.
4. Generated unit pages contain flat properties, typed relations, claims, evidence quotes, stable block IDs, and resolvable wikilinks. Generate program/topic/Home pages and native `.base` dashboards.
5. Update is deterministic for unchanged canonical input except explicit generated timestamp policy; manifest binds canonical input and output bytes. Status is zero-write and detects stale/tampered/broken targets/locators.
6. Public output contains only natural language and `kb` pseudo CLI. No raw commands, flags, `${…}`, internal scripts, `NEXT FOR AGENT:`, or TTY dependency.

## Red lines

- Never touch the real `/Users/czx/Documents/knowledge_base/kb`; all behavior tests use temporary roots.
- Do not weaken confirmation, evidence, revision/CAS, journal, source-containment, or symlink protections.
- Scripts do not infer research meaning. Relation inversion and rendering are mechanical only.
- Do not load or invoke repository shipping skills during design/development/review. They may be invoked only in an explicitly isolated behavior test.
- Do not push. Use small commits only if the maintainer explicitly requests commits.
- Cleanup is manifest-owned and path-contained; ambiguous or drifted targets are preserved and reported.

## Verification

- Focused projector/link/CLI tests, including heading/block links, legacy reverse collapse, missing target, stale/tampered manifest, human-area preservation, symlink/type-change safety, empty KB zero-write status, public-output hygiene, and installed-copy path behavior.
- Existing schema/index/link/CLI/recovery/governance tests.
- Full research test suite when focused tests pass.
- `git diff --check`, Python syntax/import validation, and `git status` proof that no real `kb/` path changed.

## STOP-and-report

Stop and report rather than inventing behavior if Obsidian Bases syntax, an existing recovery invariant, or a legacy relation shape conflicts with this handoff/SSOT.

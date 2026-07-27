# R6 complete-system handoff

## STEP 0 — base sync and scope

1. Work only from branch/commit descended from `a32cb7c`. Before editing, run `git rev-parse HEAD`, verify `.agents/VERSION == 0.2.0-rc.5`, and verify the provider-neutral `literature-search` files exist. STOP and report if the base differs; do not reset a shared worktree.
2. Read repository `AGENTS.md`, `temp/SYSTEM_DESIGN_SSOT.md` R6.1–R6.6 and the relevant current code. Shipping `.agents/skills/*/SKILL.md` files are product source, not instructions for this development task.
3. Never touch a real `kb/`; tests use temporary directories only. Do not push, tag or publish.

## Locked design

- Runtime Agent decides semantic priority, relevance, saturation, contradiction and preference relevance.
- Scripts enumerate facts/candidates and validate schema, evidence, revisions, containment, budgets, locks, CAS and governance ceilings. A function that reads research material and emits a judgement without Agent input must be deleted.
- Public output contains only natural language plus `kb <verb>` pseudo-CLI. No raw command, flag, environment expression, internal path, protocol marker or TTY interaction.
- Planning never bypasses judgement confirmation. Preferences may narrow but never enlarge governance/autonomy. Checkbox edits are intent drafts, never confirmation by themselves.
- All mutations use atomic exact-path writes, operation journal, workspace/exact-target locks, revision/CAS and precise checkpoints. Never `git add -A`.

## Track O — Agent-led next selection

Only modify:

- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/skills/research-orchestrator/SKILL.md`
- orchestrator-specific tests, preferably new `test_agent_next_selection.py`

Implement deterministic candidate snapshots without a winner/semantic score; Agent-filled selection, snapshot/current-state validation, durable next-selection history, stale detection and private protocol handoff. Include all persisted next actions, not only `[0]`. Human gates cannot be safe-executed; research judgements route to program decision confirmation.

## Track P — preference eligibility and effective selection

Only modify:

- `.agents/lib/research/prefs.py`
- optional new `.agents/lib/research/preference_selection.py`
- `.agents/skills/research-config-manager/**`
- preference-specific tests, preferably new `test_effective_preferences.py`

Keep one canonical preference catalog. Rules filter confirmed eligible fields by skill/operation; Agent selects the task-relevant subset with rationale. Persist a receipt containing IDs/digests, not raw task text or copied secrets. Deny wins; hard preferences cannot be omitted; soft omissions need reasons; source digest changes stale the receipt. Config manager remains sole writer.

## Track B — Obsidian review round-trip and atomic multi-owner apply

Only modify:

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/lib/research/obsidian.py`
- `.agents/skills/kb-cli/SKILL.md`
- `.agents/skills/knowledge-base-manager/SKILL.md` only if the public contract needs wording
- `test_kb_cli_dispatcher.py`, `test_obsidian_projection.py`, or a new focused test

Create a human-owned editable review sheet under `kb/obsidian/annotations/`; no plugin and no watcher. Checkboxes express confirm/reject/defer intent. Sync requires current user authorization in conversation. Parse safely, prevalidate the entire displayed set and current bindings, then apply all decisions atomically or write nothing. Preserve notes, prevent replay/tamper/symlink/duplicate/conflicting checkboxes, and consume snapshot only after successful commit.

## Track M — research monitor

Only modify:

- new `.agents/lib/research/monitoring.py`
- new `.agents/skills/research-monitor/**`
- new `.agents/lib/research/tests/test_research_monitor.py`

No public kb verb and no scheduler/daemon. Maintain subscriptions and frozen runs, compute due mechanically with anchored cadence, coalesce missed windows, support pause/resume/blocked/retry/terminal states, validate references to literature-search/survey outputs, and expose due facts for later orchestrator integration. Agent performs actual searching and assessment. Create skill metadata using the repository conventions and validate it.

## Track R — multi-reviewer literature search

Only modify:

- `.agents/lib/research/sources.py`
- `.agents/skills/literature-search/SKILL.md`
- `.agents/skills/literature-search/references/stage-contract.md`
- `.agents/skills/literature-search/scripts/search.py`
- `.agents/lib/research/tests/test_literature_search.py`

Replace `screeners > 1` rejection with reviewer registry, append-only per-reviewer decisions, explicit independent/assisted execution identity, conflict detection, adjudication and derived effective screening. Preserve current user candidate-selection gate. Scripts detect missing/conflict/consistency only; they never decide relevance. A reviewer cannot masquerade as human or independent; systematic include requires fulltext decisions.

## Integration — main agent only

Main agent owns shared files:

- `temp/SYSTEM_DESIGN_SSOT.md`, `temp/BACKLOG.md`
- `.agents/lib/research/SCHEMAS.md`, `.agents/AGENTS.md`
- `.agents/skills/kb-cli/**` adapter integration if Track B did not own it
- route/status integration and survey/report freshness consumers
- `.agents/VERSION`, `README.md`, `docs/**`, `CHANGELOG.md`, CI/release tests and installer count

Integrate monitor due items into Agent candidate context without a fixed winner. Connect effective preference receipts to the first required consumers. Update skill count from 19 to 20. Keep `research-navigator` dev-only and do not add an Obsidian plugin or marketplace.

## Acceptance gates

- Per-track targeted tests and regression tests.
- Full default-order pytest.
- skill validator for every shipping skill; compileall; `bash -n install.sh`; `git diff --check`.
- Fresh copy install/update/reinstall/uninstall; user files and `kb/` preserved.
- Cold-agent temporary-workspace E2E: monitor due → live literature search → user selection → intake/analyse/verify → multi-item Obsidian review sync → survey → Agent-led next → report.
- Real PDF/HTML/dataset/repo/SQLite and Obsidian Reading-view checks where locally possible. Hosted CI, push, tag and publish are explicitly outside local authority.
- Independent adversarial review of architecture, UX and security. Reproduce every finding before fixing.

## Commit discipline and escape hatch

Make small commits only after a coherent piece passes its focused tests. Do not stage unrelated/user files. If a locked design cannot be implemented without weakening confirmation/evidence/recovery or touching another track's files, STOP and report rather than improvising.

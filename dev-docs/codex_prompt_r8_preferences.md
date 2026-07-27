# R8 preference-consumer completion

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r8-preferences`. Confirm `git rev-parse HEAD` is based on integration commit `2b1de93`; if it is not, stop and report rather than editing.

## Objective

Close the gap between declared preference operations and real consumers for the user's required path. The runtime Agent chooses the relevant soft subset; code only exposes the exact allowlist, requires canonical task context, validates the receipt, applies selected soft values, and always preserves hard resources/constraints/autonomy fallbacks.

Implement real, tested consumers for these initially mandatory routes:

- `literature-search + search/stage`
- `literature-synthesizer + synthesize`
- `experiment-workbench + plan/log-run/follow-up/diagnose`
- public `kb review` display preference (`kb-cli + review-display`; do not claim knowledge-base-manager is a second consumer unless it truly consumes)

Audit `SKILL_OPERATIONS`: remove or narrow declarations that are only aspirational and have no execution consumer. Do not fake consumption merely to satisfy a matrix. Document the distinction between deterministic operations with no preference dependency and preference-sensitive operations.

## File ownership

You may modify only:

- `.agents/lib/research/preference_selection.py`
- `.agents/lib/research/tests/test_effective_preferences.py`
- `.agents/lib/research/tests/test_preference_consumer_matrix.py`
- `.agents/skills/literature-search/**`
- `.agents/skills/literature-synthesizer/**`
- `.agents/skills/experiment-workbench/**`
- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/kb-cli/SKILL.md`

Do not edit SSOT/BACKLOG/schema/version/changelog; integration owns them. Do not touch real `kb/`.

## Required invariants

- Scripts never decide semantic relevance of soft preferences; the Agent-authored selection receipt does.
- Every consumer recomputes a bounded canonical task context and uses `resolve_task_preferences`; wrong skill/operation/task and stale catalog fail closed.
- No selection means neutral soft behavior; selected-only soft behavior changes. Hard constraints/resources/autonomy remain enforced even with no receipt and cannot disable evidence/confirmation/recovery/security.
- Receipt/binding is persisted into output/state where later reproducibility depends on it; it is included in content or stale binding as appropriate.
- Public output remains natural language + `kb <verb>` only: no bare internal command, flag, `${...}`, internal path, TTY prompt, or `NEXT FOR AGENT:`.
- Analyzer scripts do not author research understanding.

## Verification and commits

Add end-to-end behavior tests for neutral/default, selected-only, wrong binding, stale catalog, hard fallback, and output/state binding for each real consumer. Run the owned tests plus relevant existing skill tests. Use small commits per coherent piece. Do not push. Stop and report any architecture ambiguity instead of inventing a compatibility bypass.

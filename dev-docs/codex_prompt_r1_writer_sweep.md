# R1 remaining-writer transaction sweep

## STEP 0 — base sync

This track starts only after the R1 recovery/governance/conversational branches are merged. Verify `HEAD` equals the integration commit supplied by the root agent and that `research.journal.mutation_transaction` exists. If not, STOP and report; do not build against an older base.

## Objective

Close the recovery contract for the remaining KB writers so every user mutation is one command-level, exact-path, locked, atomic, journaled, undoable operation and every checkpoint happens only after transaction commit.

## File ownership — only these files

- `.agents/skills/discussion-archivist/scripts/archive.py`
- `.agents/skills/literature-synthesizer/scripts/synthesize.py`
- `.agents/skills/method-designer/scripts/method.py`
- `.agents/skills/wiki-adapter/scripts/wiki.py`
- `.agents/skills/skill-evolution-advisor/scripts/create_retrospective.py`
- `.agents/skills/skill-evolution-advisor/scripts/eval_research_value.py`
- `.agents/lib/research/prefs.py` (pure-read correction only)
- `.agents/lib/research/index.py` (pure-read correction only)
- new narrowly named tests under `.agents/lib/research/tests/`

Do not edit shared journal/common/git helpers. If their API is insufficient, STOP and report to root.

## Required behavior

1. Wrap each mutating command in the shared `mutation_transaction` with the complete literal target set resolved before begin.
2. Multi-file commands are one top-level operation; inner common writers remain descendants.
3. Read/list/lint/preview modes are byte-identical and create no journal/protocol files.
4. Checkpoints/reporting events occur after the business transaction has committed, never inside it. A reporting-event write that is part of the same user action must be covered by the outer target set.
5. Add fault-injection tests for every script family: an exception after the first write restores every target byte-for-byte and leaves no canonical partial output.
6. Add undo tests for at least one single-file and one multi-file command.
7. Make semantic read APIs pure: `load_runtime_preferences`, `load_topic_taxonomy`, and `load_candidate_pools` must return normalized in-memory defaults when files are absent, without calling `ensure_workspace` or creating any path. Add fresh-empty-root byte snapshots for these loaders and for relevant list/lint/preview entrypoints. Explicit init/mutating commands retain responsibility for declaring and seeding their full workspace targets.
8. Append-like timestamped outputs must not overwrite on a same-second collision. Root independently reproduced two evaluator runs at fixed `20260719T120000Z` leaving only the second report. Allocate the final report path while holding the report-directory transaction target (same pattern as discussion archive), using a deterministic `-2`, `-3` suffix or fail-closed collision; add a regression proving two distinct reports survive and undo removes only the last transaction's new artifact.

## Red lines

- Never touch a real `kb/`; tests use temporary workspaces.
- Do not weaken confirmation/evidence governance.
- Scripts do not understand source material; they only scaffold, validate, move, or render agent-authored content.
- User-visible output remains natural language or `kb <verb>` only; no raw Python, flags, internal paths, environment variables, or `NEXT FOR AGENT:`.
- No push. Commit per coherent piece. STOP and report uncertainty.

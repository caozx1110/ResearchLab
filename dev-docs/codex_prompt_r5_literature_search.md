# R5 — provider-neutral literature-search

## STEP 0 · base sync

Work from current integration HEAD `58a45ac` or a descendant containing the rc.4 adversarial fixes, `research.sources.stage_search_results`, the 19-skill release contract, and SSOT §3.4A dated 2026-07-24. If any are absent, stop and report instead of editing an older tree.

## Objective

Replace the OpenAlex-bound `literature-scout` product surface with a direct `literature-search` skill. Runtime Agent owns tool selection, multi-query discovery, screening, citation expansion, gap-followup and semantic stop decisions. Deterministic code owns provider-neutral identity, schema validation, hard budgets, atomic staging, merge/resume safety and output hygiene.

## File ownership

Only change:

- `temp/SYSTEM_DESIGN_SSOT.md`, `temp/BACKLOG.md`, this handoff;
- `.agents/skills/literature-scout/**` only to remove it, and `.agents/skills/literature-search/**` to add the replacement;
- `.agents/lib/research/openalex.py` only to remove it;
- `.agents/lib/research/sources.py`, `.agents/lib/research/SCHEMAS.md`;
- literature-search/source-stage/release-contract tests;
- current routing, public docs, changelog and version surfaces that name the replaced capability.

Do not touch real `kb/`, unrelated skills, generated user data, CI credentials, tags, remotes or hosted releases.

## Required behavior

1. The skill is named `literature-search`; no current runtime route or product copy calls it `literature-scout` or promises OpenAlex.
2. No bundled code performs literature network search or selects a provider. The skill tells the runtime Agent to use currently available search/browser/connector tools and record why each was chosen.
3. Default mode is bounded exploratory. Systematic intent is explicit and labeled `bounded-systematic` unless sources, query strings, result depth and screening are reproducible.
4. Preserve one journaled source-search stage. Its immutable identity binds source kind + normalized original request; individual queries are append-only query events.
5. Candidate identity is DOI → arXiv/PMID → canonical http(s) URL. Title/year never auto-merge. Identity conflicts fail closed. URL-only candidates may gain strong IDs without changing candidate ID.
6. Preserve all discovery edges and manual status/note/screening across reruns. A failed fetch remains retryable; no plain visited-set behavior.
7. Screening judgements require title/abstract/fulltext evidence. Snippets prove discovery only and never become canonical paper-claim evidence.
8. Persist hard budgets, usage, coverage, frontier, stop reason/rationale, uncovered facets and partial state. Agent chooses semantic next action and saturation; scripts only enforce boundaries.
9. Selected candidates still hand off to `source-intake`; deep paper reading and synthesis stay with their existing owners.

## Red lines

- Scripts never understand or summarize papers and never infer relevance, novelty, quality, gaps or saturation.
- Do not add PaperQA2/STORM/PaSa/OpenScholar/LangGraph or provider SDKs as dependencies; borrow only generic protocols and independently authored schema ideas.
- Do not weaken journal/lock/CAS/recovery, containment, evidence or confirmation gates.
- User-visible output is natural language plus existing `kb <verb>` forms only: no interpreter commands, flags, `${…}`, internal paths or `NEXT FOR AGENT:`.
- Tests use temporary workspaces only. Never mutate repository `kb/`.
- Do not push, tag or publish.

## Verification and commits

- Reproduce every failing test before changing behavior.
- Add adversarial tests for identity upgrade/conflict, multi-query provenance, retry/resume, budget persistence, systematic-mode honesty, snippet screening rejection, no-tool blocking and natural-language output.
- Run focused tests, all 19 skill validations, compile checks, installer/install-copy gates and the complete local suite.
- Commit per coherent piece where practical. Stop and report if the schema cannot remain backward compatible with existing generic source stages.


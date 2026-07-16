# AGENTS

This repository is a Chinese-first research operating system built around knowledge units.

Default preference order:

1. durable artifacts over chat-only answers
2. lightweight-first ingestion over heavyweight one-shot ingestion
3. explicit confirmation for AI judgement over silent auto-promotion
4. reusable knowledge units over one-off notes

## Basics

- Human-facing markdown defaults to Chinese.
- Preserve original English paper titles, repo names, benchmark names, and technical terms on first mention.
- YAML keys, IDs, slugs, and folder names stay ASCII-safe.
- Prefer `${RESEARCH_PYTHON:-python3}` for research scripts, but use a known YAML-capable runtime.
- Runtime-specific configuration belongs in `kb/config/`.
- Session start: read the `research-navigator` recall digest once.
- Session start: if `kb/config/user-profile.yaml` has a `personalization` block, read it once as optional user context (`user_opinion`, not confirmed facts; it never overrides governance rules).
- When you go wrong or the user corrects you, log one learning with `skill-evolution-advisor/scripts/learnings.py log`.
- Skill defects are record-only: never auto-modify a skill or `OPTIMIZATION_PLAN.md` from a captured defect.

## Ingestion auto-drive

When the user asks to ingest a source (paper/repo/blog), or accepts an ingestion suggestion, **drive the whole pipeline to a grounded, complete knowledge unit in one turn** — do not stop after each script and wait for another prompt. The chain is:

1. `intake add` (dual-source fetch → lightweight unit + parse-cache).
2. Analyzer `prepare` (emits the fillable structure; read its `NEXT FOR AGENT:` line).
3. **You (the agent) read the parse-cache and fill the required elements**, each with a short **verbatim** quote + `locator` (PDF `page=N`; HTML `section`/`anchor`; repo `file:line`). Paper = motivation/method/experiment/limitation/insight; blog = positioning/key_points/credibility/reusable_explanation; repo = capability/reuse_points/entry_map.
4. Analyzer `verify` (script checks every quote is verbatim + clears the substance gate, then persists). If it rejects an element, fix that element's quote and re-run — never fabricate a quote to pass.
5. Paper only: `extract-figures` + `refresh-structure` when a PDF backend is present.
6. Present the AI judgements (worth-reading verdict, key insights) for confirmation.

**Stop only at the two governance gates:** (a) confirming an AI judgement (never self-sign; leave judgement-track content `pending_user_confirmation` until the user confirms), and (b) a user decision (choose idea, approve baseline, resolve an ambiguous instruction). Everything else in the chain is a safe auto-step.

## User-facing output: natural language + `kb <verb>` only

The user interacts through exactly two surfaces: **natural language** and the **`kb <verb>` pseudo-CLI**. Everything else is internal or agent-facing.

- **Never show the user a raw command.** No `python3 .agents/skills/**/*.py …`, no `--flags`, no `${RESEARCH_PYTHON:-python3}`, no internal script paths, no `NEXT FOR AGENT:` lines. Those are for you (the agent) to execute, not to print. When a script's output contains such a command (e.g. `confirm: …/paper.py confirm --id …`), translate it to natural language ("say 'confirm' to accept this judgement") or a `kb <verb>` form — do not relay it verbatim.
- **You compute and run the commands yourself.** You know the unit/program id; build the confirm/verify/prepare command internally and run it. The user only sees the outcome and a natural-language next step.
- **Setup and choices are conversational.** For `kb init` and any preference/persona setup, ask the user in natural language and then write headlessly (the pseudo-CLI has no TTY; it will hand you a `NEXT FOR AGENT:` instruction — follow it, don't surface it). Never tell the user to run a raw command in a terminal.
- **Empty/edge states stay natural.** Empty KB on `kb next` → "your knowledge base is empty; send me a paper link, file, or repo to start" — not an `intake.py add …` command block.

This is bounded by `runtime-preferences.autonomy.auto_execute_scope` (capped by `GOVERNANCE_MAX_AUTO_STEPS`); if autonomy is narrowed, honor it. Ingestion deep-read intentionally spends tokens (durable grounded notes over token thrift); the automation saves the user's *steps and attention*, not tokens.

## Layout

- `kb/raw/`: immutable external source bytes. Never rewrite in place.
- `kb/units/{papers,repos,blogs,ideas,experiments}/<unit-id>/`: canonical knowledge units.
- `kb/programs/<program-id>/`: program state, design, experiments, reports.
- `kb/synthesis/`: cross-unit surveys, taxonomy, trends, gaps.
- `kb/user/`: human-facing navigation and reopen pages, not canonical source.
- `kb/output/`: exports only, never the sole source of truth.
- `kb/` is allowed to be a nested Git repository; runtime state and browser snapshots stay ignored inside that repo.

## Unit Rules

- Every unit must keep a `record.yaml` with at least: `id`, `kind`, `status`, `maturity`, `confirmation_status`, `information_types`, `tags`, `topics`, `links`, `reuse_flags`, `history`.
- Use compact IDs such as `p-openvla-bf86ee46`, `r-openvla-dadda683`, `i-physics-aware-f7e91d86`.
- Do not use full titles as folder names; preserve old long IDs in `legacy_ids` when renamed.
- Straightforward metadata and process logs may be `auto_confirmed`.
- AI inference, evaluation, novelty judgement, detailed notes, and failure diagnosis default to `pending_user_confirmation`.
- Script-generated YAML/workflow timestamps use UTC.
- Tags, short summaries, and candidate-pool flags may be overwritten.
- Idea evolution, experiment history, design changes, and reports should preserve history.
- Information types must distinguish: `fact`, `inference`, `evaluation`, `user_opinion`, `unverified`.
- Never present inference or evaluation as raw source fact.

## Routing

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Analysis: `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`

## Editing Rules

- Update `SKILL.md` ownership/trigger wording first.
- Keep `SKILL.md` concise and `agents/openai.yaml` aligned.
- Move deterministic repeated behavior into `scripts/`.
- Prefer replacing overlapping skills over letting two owners coexist.
- Validate touched scripts with at least `--help`.
- If the same friction appears more than once, fix the reusable layer.

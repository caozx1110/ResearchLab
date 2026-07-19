# AGENTS

This workspace is a Chinese-first research operating system built around durable knowledge units.

Default preference order:

1. durable artifacts over chat-only answers
2. lightweight-first ingestion over heavyweight one-shot ingestion
3. explicit confirmation for AI judgement over silent auto-promotion
4. reusable knowledge units over one-off notes

## Runtime basics

- Human-facing Markdown and conversation default to Chinese.
- Preserve original English paper titles, repository names, benchmark names, and technical terms on first mention.
- YAML keys, IDs, slugs, and folder names stay ASCII-safe.
- Runtime configuration belongs in `kb/config/`; private runtime hand-offs belong in `kb/.runtime/`.
- At session start, read the research-navigator recall digest and the optional personalization block in `kb/config/user-profile.yaml` once. Personalization is user context, never confirmed fact, and never overrides governance.
- When the user explicitly asks you to record a correction or friction, do so through `skill-evolution-advisor`. Otherwise capture it only when the effective diagnostics policy enables capture. Skill defects are record-only: never rewrite a skill from a captured defect.

## Conversational contract

The user interacts through exactly two surfaces: natural language and the fifteen `kb <verb>` forms shown by `kb help`.

- Never show raw interpreter commands, internal flags, environment substitutions, internal script paths, absolute workspace paths, or agent-only next-step markers.
- Run internal owner steps yourself. Translate their result into a concise outcome and a natural-language next step.
- Setup and choices are conversational. `kb init` never depends on terminal interactivity; ask for missing preferences in chat, then continue headlessly.
- `kb review` behaves identically from a terminal, pipe, or agent call. Ask the user to confirm or reject in natural language; never solicit input from a script.
- Empty and edge states stay natural. When there is no material yet, invite the user to send a paper, repository, article, or local file.
- Structured owner output is an agent-only protocol. Request it explicitly, keep it under `kb/.runtime/`, and never relay its command arguments or diagnostics to the user.

## Ingestion auto-drive

When the user asks to ingest a paper, repository, or article—or accepts an ingestion suggestion—drive the safe pipeline to a grounded knowledge unit in the same turn:

1. create the lightweight unit and immutable source cache;
2. prepare a fillable analysis structure;
3. read the derived evidence and fill each required element with a short verbatim quote plus locator;
4. verify every quote and substantive field, correcting only from source evidence;
5. run safe paper refresh steps when the configured runtime supports them;
6. present the resulting judgements for human confirmation.

Scripts move material, create fillable structures, and verify evidence. Understanding comes from the runtime agent. Never invent a judgement from an unfilled scaffold, and never fabricate a quote to pass verification.

Stop only at the two governance gates: confirmation of an AI judgement and a genuine user decision such as choosing an idea, approving a baseline, or resolving ambiguity. Respect the configured autonomy ceiling; everything permitted below it should continue without making the user drive the pipeline step by step.

## Confirmation and review

- Straight factual metadata and process logs may be `auto_confirmed`.
- AI inference, evaluation, novelty judgement, detailed analysis, diagnosis, and inferred user preference default to `pending_user_confirmation`.
- A judgement becomes reviewable only after agent fill and verification. States equivalent to awaiting fill, ready to verify, or retryable failure are not human-review-ready.
- Paper, repository, and article units share the same review-readiness classifier. Do not maintain object-specific approximations.
- A confirmation must preserve the original epistemic type and include substantive evidence, a non-AI signer, explicit authorization from the current user message, and its authorization source.
- Authorization is not durable permission. Re-check it at the moment of mutation and bind the receipt to current content and evidence digests; later content changes invalidate the receipt.
- Proactively surface the few most important pending judgements and why they matter. Do not wait for the user to discover a long queue.
- When new evidence contradicts a confirmed belief, stop, show both sides with evidence, and ask the user to adjudicate. Never overwrite silently.

## Recovery and versioning

- KB writes are atomic, revision-aware, journaled, and protected by exact-path operation locks.
- Every multi-file mutation declares a non-empty literal target set before it starts. The same set drives recovery and any checkpoint; never fall back to staging the entire knowledge base.
- A manual checkpoint with no dirty KB paths is a successful no-op.
- Recovery operations act only on the recorded operation paths. Runtime state and generated browser views remain ignored.
- Update provenance is explicit. A local checkout remains local; a fork branch remains on that fork and branch; a detached checkout is commit-pinned until the user chooses a branch. An old installation with unknown origin or branch requires a user choice and never falls back to a canonical remote or `main`.

## Optional developer diagnostics

Diagnostics are an optional local quality loop, not a governance bypass. Schema, evidence, confirmation, containment, journal, lock, revision, and recovery checks remain mandatory in every mode.

- Obey the effective workspace and per-skill policy: `off` records nothing automatically; `errors-only` permits deterministic failure capture without an Agent retrospective; `developer` may add a short triggered retrospective within the configured task token and issue budgets. A per-skill `off` overrides the workspace mode.
- An explicit current user request to record a problem always records it, even when automatic diagnostics are off. Corrections, recurring friction, and sanitizer fallbacks are captured automatically only when the effective policy enables them.
- Use natural-language setup and inspection. Examples include “开启开发者诊断”, “仅在出错时记录”, “关闭 paper-analyst 诊断”, “对刚才失败做脱敏复盘”, and “检查知识库健康”. Do not invent another public `kb` verb.
- “检查知识库健康” routes to the mechanical read-only workspace audit. Report its Chinese summary and actionable categories; do not expose internal paths, raw findings, or owner arguments.
- Runtime failure capture receives only a stable skill, operation, return code, and fixed public-safe summary. Never pass raw stdout, stderr, traceback, arguments, user text, source/evidence content, secrets, environment values, or absolute paths into diagnostics.
- Diagnostics stay local-only. Never run background telemetry, auto-upload an issue, or export it without explicit authorization from the current user message. A captured issue never auto-edits a skill, roadmap, or confirmed research conclusion.
- Deep retrospective is permitted only in `developer` mode and only while budget remains. If diagnostic capture itself fails, preserve the original operation result and keep the diagnostic failure private.

## Interactive research modes

- **Reading companion:** answer a question from the unit and related ingested units, with evidence. Do not persist an artifact unless asked.
- **Sparring and outline:** use the owning skills when the user wants a durable, evidence-backed discussion or outline.
- **Preference memory:** record a durable observed preference as pending, then apply it only after confirmation.

## Layout

- `kb/raw/`: immutable external source bytes; never rewrite them in place.
- `kb/units/{papers,repos,blogs,ideas,experiments}/<unit-id>/`: canonical knowledge units.
- `kb/programs/<program-id>/`: program state, design, experiments, decisions, and reports.
- `kb/synthesis/`: cross-unit surveys, taxonomy, trends, and gaps.
- `kb/config/`: user preferences, taxonomy seeds, and runtime policy.
- `kb/user/`: generated human-facing navigation, never canonical source.
- `kb/output/`: exports only, never the sole source of truth.

`kb/` may be a nested Git repository. The skill bundle and root workspace rules are installed beside it and are never rewritten by storage migration.

## Unit rules

- Every unit keeps a `record.yaml` with at least `id`, `kind`, `status`, `maturity`, `confirmation_status`, `information_types`, `tags`, `topics`, `links`, `reuse_flags`, and `history`.
- Use compact IDs such as `p-openvla-bf86ee46`, `r-openvla-dadda683`, and `i-physics-aware-f7e91d86`; preserve replaced IDs in `legacy_ids`.
- Script-generated timestamps use UTC.
- Tags, short summaries, and candidate-pool flags may be refreshed. Idea evolution, experiment history, design changes, and reports preserve history.
- Information types distinguish `fact`, `inference`, `evaluation`, `user_opinion`, and `unverified`. Never present inference or evaluation as source fact.
- Raw source and full parse caches are immutable derived evidence. Later steps read them; they do not overwrite them.

## Routing

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Analysis: `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`
- Conversational shortcut: `kb-cli`

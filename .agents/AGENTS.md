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

The user interacts through exactly two surfaces: natural language and the sixteen `kb <verb>` forms shown by `kb help`.

- Never show raw interpreter commands, internal flags, environment substitutions, internal script paths, absolute workspace paths, or agent-only next-step markers.
- Run internal owner steps yourself. Translate their result into a concise outcome and a natural-language next step.
- Setup and choices are conversational. `kb init` first makes the KB usable, then offers “现在设置”（推荐）or “先跳过” when a real human signature is missing; never jump straight to asking for a name. Deferring adds or overwrites no preference or sentinel and does not block ingestion, search, or analysis. If the user configures now, ask once for human signature, language and terminology style, research focus, and resources or important constraints; show the current versioning and paper-screening defaults, accept “默认即可”, then persist headlessly. Low-frequency preferences remain progressive, and a missing signature is requested again only before the first confirmation is applied.
- For quick setup, execute the private protocol's `apply.field_inputs` mapping exactly; never invent a dotted profile key. The canonical resource input preserves existing resource keys, and the repeatable constraint input appends and deduplicates rather than replacing prior constraints. Keep legacy inputs compatible, but do not use them in place of the canonical quick-setup mapping.
- `kb review` behaves identically from a terminal, pipe, or agent call. Ask the user to confirm or reject in natural language; never solicit input from a script.
- Empty and edge states stay natural. When there is no material yet, invite the user to send a paper, repository, dataset, article, or local file.
- Structured owner output is an agent-only protocol. Request it explicitly, keep it under `kb/.runtime/`, and never relay its command arguments or diagnostics to the user.

## Obsidian projection

- Treat canonical records, program state, taxonomy, and evidence as the only source of truth. Obsidian consumes a rebuildable view; it never becomes a second confirmation or revision store.
- `kb obsidian status` is read-only. `kb obsidian update` may write only `kb/obsidian/managed/`, create missing `kb/obsidian/inbox/` and `annotations/` directories, and update the generated-view gitignore rule. It must never create or edit `.obsidian/`.
- Files below `kb/obsidian/managed/` are generated. Never place human edits there. Human notes belong in `inbox/` or `annotations/`, and projection updates must not traverse or overwrite them.
- Generated pages are designed for Obsidian Reading view (the book icon). Editor or Live Preview mode intentionally exposes wikilink, inline-code, and block-ID syntax; explain this distinction instead of editing `.obsidian/` settings.
- Paper, article, and local-document unit pages link to the canonical `source/document.md` reading view. Repository evidence links may open a verified local source file through a `file://` URI, but the durable identity remains `repo unit id + repo-relative path`; a machine-local URI is never canonical evidence.
- After a successful canonical mutation, refresh the Obsidian projection when autonomy permits and no confirmation or user-decision gate is pending. A failed or pending canonical operation must not be disguised by a projection refresh.
- Canonical relations store only explicit forward edges. Derive backlinks and named inverse relations at read time. Use stable unit IDs for files and stable claim/evidence/source block IDs for precise links; when a source map resolves an evidence locator, link the Obsidian evidence entry directly to that Markdown page or section block. Never confirm an AI-suggested similarity merely because it appears in a graph.

## Ingestion auto-drive

When the user asks to ingest a paper, repository, dataset, or article—or accepts an ingestion suggestion—drive the safe pipeline to a grounded knowledge unit in the same turn:

1. create the lightweight unit, preserve the original bytes, and materialize the full Markdown reading view plus its source map and local assets;
2. for a paper, prepare and fill the screening structure, then verify the agent-authored `paper_type` before any full-note scaffold is created;
3. prepare the analysis structure selected by that verified type;
4. read the derived evidence and fill each required element with a short verbatim quote plus locator;
5. verify every quote and substantive field, correcting only from source evidence;
6. run safe paper refresh steps when the configured runtime supports them;
7. present the resulting judgements for human confirmation.

Scripts move material, create fillable structures, and verify evidence. Understanding comes from the runtime agent. Never invent a judgement from an unfilled scaffold, and never fabricate a quote to pass verification.

Stop only at the two governance gates: confirmation of an AI judgement and a genuine user decision such as choosing an idea, approving a baseline, or resolving ambiguity. Respect the configured autonomy ceiling; everything permitted below it should continue without making the user drive the pipeline step by step.

## Confirmation and review

- Straight factual metadata and process logs may be `auto_confirmed`.
- AI inference, evaluation, novelty judgement, detailed analysis, diagnosis, and inferred user preference default to `pending_user_confirmation`.
- A judgement becomes reviewable only after agent fill and verification. States equivalent to awaiting fill, ready to verify, or retryable failure are not human-review-ready.
- Paper, repository, dataset, and article units share the same review-readiness classifier. Do not maintain object-specific approximations.
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

- **Durable continuation:** when promising work that should later be resumed by `kb next`—for example a batch survey or technical roadmap—create or reuse a program and persist that work in its `next_actions` before making the promise. `kb next` reads durable program and unit state; it never reconstructs a chat-only promise. A completed unit stays completed unless its canonical content or evidence actually changes.

- **Reading companion:** answer a question from the unit and related ingested units, with evidence. Do not persist an artifact unless asked.
- **Sparring and outline:** use the owning skills when the user wants a durable, evidence-backed discussion or outline.
- **Preference memory:** record a durable observed preference as pending, then apply it only after confirmation.

## Layout

- `kb/raw/`: immutable external source bytes; never rewrite them in place.
- `kb/units/{papers,repos,datasets,blogs,ideas,experiments}/<unit-id>/`: canonical knowledge units.
- `kb/units/<kind>/<unit-id>/source/`: immutable source bundle. For paper, HTML, Markdown, and text material it contains `document.md`, `source-map.yaml`, `conversion.yaml`, original material, and optional hash-addressed `assets/`; HTML also contains a normalized offline `archive.html` while raw `source.html` stays byte-preserved.
- `kb/programs/<program-id>/`: program state, design, experiments, decisions, and reports.
- `kb/synthesis/`: cross-unit surveys, taxonomy, trends, and gaps.
- `kb/config/`: user preferences, taxonomy seeds, and runtime policy.
- `kb/user/`: generated human-facing navigation, never canonical source.
- `kb/obsidian/managed/`: generated no-plugin Obsidian projection; safe to rebuild and ignored by KB Git.
- `kb/obsidian/{inbox,annotations}/`: human-authored Obsidian notes; never managed or deleted by projection refresh.
- `kb/output/`: exports only, never the sole source of truth.

`kb/` may be a nested Git repository. The skill bundle and root workspace rules are installed beside it and are never rewritten by storage migration.

## Unit rules

- Every unit keeps a `record.yaml` with at least `id`, `kind`, `status`, `maturity`, `confirmation_status`, `information_types`, `tags`, `topics`, `links`, `reuse_flags`, and `history`.
- Use compact IDs such as `p-openvla-bf86ee46`, `r-openvla-dadda683`, and `i-physics-aware-f7e91d86`; preserve replaced IDs in `legacy_ids`.
- Script-generated timestamps use UTC.
- Tags, short summaries, and candidate-pool flags may be refreshed. Idea evolution, experiment history, design changes, and reports preserve history.
- Information types distinguish `fact`, `inference`, `evaluation`, `user_opinion`, and `unverified`. Never present inference or evaluation as source fact.
- Original material, full Markdown reading views, source maps, local source assets, and full parse caches are immutable evidence. Later steps read them; they do not overwrite them.
- Read `source/document.md` first when it exists because it is complete, linkable, and human-readable. For HTML, use its `archive.html` link when browser layout, grouped figures, MathML, or tables need visual inspection. Use `parse-cache.yaml` for the existing evidence locator/quote protocol, and fall back to the original PDF/HTML/other source when conversion is degraded or a detail cannot be recovered from Markdown.
- Images in a materialized reading view live under `source/assets/` and are referenced relatively from `document.md`. Their presence is source evidence, not an automatically interpreted claim; image understanding still belongs to the runtime agent and must be grounded explicitly.

## Routing

- Governance and routing: `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator`
- Analysis: `paper-analyst`, `repo-analyst`, `dataset-analyst`, `blog-analyst`, `literature-synthesizer`
- Creation and execution: `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author`
- Navigation and meta: `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor`
- Conversational shortcut: `kb-cli`

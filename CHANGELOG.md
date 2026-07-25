# Changelog

All notable changes to this project will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and version identifiers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

The bundle currently declares **`0.2.0-rc.7`**. Its complete local suite, targeted R17–R26 regression suites, all 20 skill validators, and current installed-copy lifecycle pass. Installation and core workflows require no external API Key, paid search quota, commercial database subscription, or paid plugin. The candidate is not a stable release or GA, has not been tagged or published, and carries no compatibility or response-time SLA. Real-source/Obsidian acceptance and a green hosted Linux/macOS CI matrix remain prerequisites for a release tag.

## [0.2.0-rc.7] - Unreleased

### Changed

- Canonical record, evidence, judgement, survey, program-decision, portfolio, and report consumers now retain exact snapshot bindings through their final trusted use; stale content or same-bytes replacement fails closed.
- Formal report and portfolio publication uses aggregate post-write and authoritative-root commit guards. Guarded publication cannot be nested under another write transaction; the Agent retries it after the outer operation completes.
- `literature-search` remains provider-neutral and Agent-led, with resumable no-search recovery; OpenAlex remains read-only legacy identity input and is never a runtime retrieval source.
- Survey routing covers external discovery through selection, intake, owner analysis, synthesis, review confirmation, and report consumption; repo evidence follows the same external-source contract as the other unit kinds.
- Agent installation plans use schema 3 runtime preconditions. Stable compatible PATH interpreters work strictly offline, while interpreter selection or capability drift rejects before the first workspace/runtime write.
- Public review owner modules follow the normal Python import lifecycle, including stable path-scoped names, execution-time registration, and identity-protected cleanup after failed loads.

### Security

- Recovery, update, manifest lifecycle, confirmation, review batches, source intake, and report publication use anchored/no-follow snapshots, exact target journals, compare-and-set checks, and root-level rollback gates.
- Review and Obsidian batches remain confirmation-gated, preview-bound, and atomic across owners; editable checkboxes are intent drafts and never self-authorize canonical changes.
- Installation and core workflows have no external API Key, paid search quota, commercial database, or paid-plugin prerequisite; missing discovery tools produce a resumable local state instead of a credential prompt.

### Fixed

- Closed report render/write/commit and portfolio write/replay races, including content replacement and same-bytes/new-inode replacement.
- Replaced repeated judgement and unit scans with canonical batch indexes, preserving duplicate-subject fail-closed behavior while restoring linear enumeration.
- Kept unresolved issues and literal factual events out of formal judgement lanes without hiding them from pending/factual report sections.
- Made blocked literature discovery return concrete no-Key recovery choices and kept user-visible output limited to natural language plus `kb <verb>`.

## [0.2.0-rc.6] - Unreleased

### Added

- Agent-authored portfolio decisions for multi-program `kb next`, with complete candidate snapshots, task-bound preference receipts, and no rule-computed semantic winner.
- A single canonical preference system with per-skill eligibility allowlists, Agent-selected task subsets, hard-preference enforcement, source/task staleness, and privacy-bounded receipts.
- No-plugin Obsidian review sheets for up to three confirm/reject/defer decisions, preview-digest authorization, and one cross-owner root transaction.
- Provider-neutral `research-monitor` subscriptions and frozen run receipts for literature tracking, survey freshness, and unit rechecks.
- Append-only multi-reviewer screening and adjudication ledgers for systematic literature search.
- An installer `--agent-plan` mode that performs no writes, lists all durable parent/file/link/managed-block/delete/rmdir targets, and explicitly bounds a conditional dependency-managed runtime tree for a GitHub-link installation workflow.

### Changed

- `kb next` now requires a current Agent `PortfolioDecision`; only one explicitly selected safe action can be auto-executed, while multiple selections require Agent dispatch.
- Survey and literature-search phrases have complete, longest-match routing; `research-navigator` remains an optional development projection helper rather than a formal product entrypoint.
- Literature discovery remains runtime-Agent-led and provider-neutral. OpenAlex is retained only as a read-only legacy identity migration shape, never as a runtime retrieval source.
- Multi-reviewer protocols enforce canonical phase order, immutable decision digests, actor-specific adjudication, and append-only pending-to-resolved convergence.
- Monitor completion binds the frozen task, entire run receipt, literature stage bytes, survey bytes, and the exact unit-recheck set.
- Reporting, synthesis, method, experiment, review, literature, and orchestration consumers now receive only their validated effective preference view.
- Existing root `AGENTS.md` prose continues to be preserved through the established marker-scoped managed-block contract; the GitHub-link installation guide now states the same behavior.

### Security

- Effective-preference receipts reject secrets, credentials, URLs, absolute paths, multiline content, and high-entropy payloads, and cannot be replayed across tasks.
- Obsidian batch apply requires current-message authorization for the complete preview, rolls back canonical and derived cache targets together, and revalidates under lock.
- Review registries and editable sheets use component-by-component no-follow directory handles, preventing intermediate-directory symlink or rename swaps from redirecting access outside the workspace.
- Literature reviewer ledgers and monitor receipts are revalidated from persisted bytes before resume or completion; stale or tampered bindings fail closed.
- Late namespace-renames during review registry writes restore or remove only the exact inode created by the operation, and reviewer decisions cannot regress from full-text screening to an earlier phase.
- Agent install plans suppress Python bytecode and temporary managed-block writes; public Obsidian batch completion suppresses internal checkpoint labels and commit hashes.

## [0.2.0-rc.5] - Unreleased

### Added

- Passage-level lexical retrieval backed by an atomic SQLite FTS5 runtime cache, with deterministic in-memory fallback when the cache is absent, stale, or corrupt.
- A provider-neutral `literature-search` skill in which the runtime Agent selects currently available search/browser/connector tools, while durable staging records query events, candidate identities and discovery edges, retry state, evidence-backed screening, coverage/frontier, budgets, and stop rationales.
- Survey consumer bindings for upstream content, confirmation, evidence, and selection freshness.
- Experiment run fingerprints, repeat grouping, seed-aware duplicate protection, and explicit rerun provenance.
- Expiring review snapshot tokens, safe runtime garbage collection, outcome-specific recovery messages, and public confirm/reject coverage across all four judgement owners.
- Cross-owner judgement discovery and a one-time, snapshot-bound public review token that routes confirmations and rejections to the canonical owner.
- A staged method lifecycle (`prepare` → Agent fill → verify → confirm/reject) with evidence-backed proposal fields and transaction-time input revalidation.
- First-class dataset knowledge units, a dataset analyst with evidence-backed four-part profiles, and explicit journaled repo-to-dataset migration.
- A sixteen-verb conversational `kb` surface with private, opt-in structured hand-off for runtime agents.
- Unified human-review readiness across paper, repository, and article workflows.
- Current-message authorization fields for confirmation hand-off and version-bound confirmation receipts.
- Exact-path multi-file operation scopes, recovery ordering tests, and clean manual-checkpoint no-op behavior.
- Source-and-branch-aware installation manifests and update behavior for local checkouts, non-main fork branches, detached checkouts, and legacy unknown-provenance installs.
- Linux and macOS release-gate workflow definitions, including public-output and installed-copy smoke tests; hosted matrix execution remains pending.
- Optional D1 local diagnostic policies, redacted runtime-failure capture, deterministic issue deduplication, and a layered read-only workspace health audit. These capabilities remain beta/scaffold rather than stable.

### Changed

- Current ConfirmationReceipt consumers revalidate canonical source containment and verification artifact bytes; stale evidence can no longer enter ordinary reports.
- Committed-operation undo/restore now compares every current target with the operation's `after_digests` before creating a recovery operation.
- Literature run identity now binds the original question, mode, frozen scope, and optional fresh-run ID. Stage paths, candidate/query/frontier references, actual budget usage, evidence levels, systematic flow arithmetic, external-content boundaries, and current-user selection are fail-closed; coverage/frontier histories survive resume.
- Source-search stage identity is immutable across explicit ID reuse; literature candidates merge by DOI, arXiv ID/PMID, then canonical URL, support URL-only identity upgrades, preserve multi-query provenance and screening history, and fail closed on ambiguous or conflicting identities.
- Literature discovery no longer bundles an OpenAlex client or any fixed provider. Exploratory searches make no completeness claim, and systematic searches require a frozen reproducibility contract or are labeled bounded-systematic.
- Markdown passage extraction excludes standalone Obsidian block IDs, and cache health separates internal corruption from canonical staleness.
- Empty review queues no longer create snapshot runtime state, and public help exposes both Obsidian update and status forms.
- Source/self-contained installation preserves an exact `CLAUDE.md → AGENTS.md` symlink and rejects unrelated configuration links without following them.
- `kb find` now returns answer-relevant passages and reopenable locators instead of unit-title matches, while keeping query execution read-only.
- Review success messages identify the sanitized subject and decision; stale cards require a fresh review that displays current content.
- Verified surveys fail closed when an anchored upstream unit changes or a newly matching unit makes the selection stale.
- Source HTML selection now has explicit release acceptance for substantive main-content choice, layout tables, and fragment externalization.
- Public review now shows complete claim/evidence context, orders the highest-impact pending items deterministically, and applies at most one decision per snapshot.
- Rejection and repeated terminal actions now converge across unit, program-decision, idea-discussion, and method-selection records without leaving active canonical claims.
- `kb next` now short-circuits completed units and prioritizes durable program actions over loose maintenance suggestions; resumable promises must be persisted.
- Repository structure scans now require a real local source tree, preserve confirmed judgement content, and store mechanical entrypoint candidates separately.
- arXiv ingestion uses native arXiv HTML first, direct ar5iv Labs HTML as fallback, and screening-first analysis before a type-specific full note.
- Runtime and test dependencies are exactly pinned and shared by Linux and macOS CI.
- `kb init` and `kb review` no longer depend on TTY state or read from standard input.
- Public help, errors, and runtime messages expose only natural language and supported `kb <verb>` forms.
- Runtime bootstrap avoids installing packages into arbitrary shared interpreters during normal calls.
- The distributed `.agents/AGENTS.md` now contains installed-workspace runtime rules only.
- Documentation now reflects the modular research library, private Agent protocol, recovery contract, and honest pre-release status.
- Installed Agent rules now accept natural-language diagnostic setup and health checks without adding a public verb or background telemetry.

### Security

- Canonical judgement/evidence resolution rejects symlink components, cross-unit ambiguity, mismatched record identity, and non-regular records across discovery, confirmation, indexing, and reporting.
- Literature-search staging accepts only a provider-neutral field whitelist: raw responses, request URLs, cookies, tokens, unsafe URLs, unredacted errors, and snippet-backed substantive screening are rejected before workspace mutation.
- Retrieval cache targets, review-token cleanup, survey bindings, and experiment artifacts are containment-checked and fail closed on stale or unsafe state.
- Judgement confirmation now binds canonical subject identity, owner route, pending status, content digest, and verification digests; duplicate identities, stale snapshots, replayed tokens, and symlink escapes fail closed.
- Confirmation remains fail-closed for AI signers, hollow judgement content, missing evidence, stale content digests, and absent current-user authorization.
- Update provenance no longer falls back from a fork, local checkout, or unknown legacy source to a canonical remote.
- Storage migration is constrained to KB data and does not rewrite installed skills or root workspace rules.
- Optional diagnostics cannot disable mandatory evidence, confirmation, containment, transaction, or recovery gates; capture failures preserve the original operation result and diagnostic exports require explicit authorization.

## [0.2.0-rc.4] - Unreleased

The adversarial-remediation candidate closes current-evidence, canonical-containment, recovery-CAS, installer-symlink, staging-identity, retrieval-integrity, and empty-review UX findings. The complete local test suite and installed-copy validation pass; real-source/Obsidian acceptance and hosted release gates remain pending.

## [0.2.0-rc.3] - Unreleased

The current local candidate adds the R3 retrieval, freshness, experiment identity, scouting, and review-UX closure. Local acceptance passed with 1,012 tests plus installed-copy, real-source, and Obsidian Reading-view checks; no tag or publication exists.

## [0.2.0-rc.2] - Unreleased

The current candidate adds screening-first arXiv/ar5iv ingestion, first-class datasets, durable `kb next` continuation, and repository scan applicability hardening. Local release gates are complete; no tag or publication exists yet.

## [0.2.0-rc.1] - Unreleased

The candidate identifier recorded by the bundle. Local release-candidate acceptance is complete, but no release tag or publication exists yet; hosted Linux/macOS CI must pass before tagging, and this candidate must not be described as stable or GA.

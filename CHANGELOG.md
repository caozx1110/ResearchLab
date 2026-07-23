# Changelog

All notable changes to this project will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and version identifiers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

The bundle currently declares **`0.2.0-rc.3`**. It has passed the complete 1,012-test local suite, installed-copy validation, real SQLite HTML intake, and Obsidian 1.12.7 Reading-view acceptance. It meets the local release-candidate gate, but is not a stable release or GA, has not been tagged or published, and carries no compatibility or response-time SLA. A green hosted Linux/macOS CI matrix remains a prerequisite for a release tag.

### Added

- Passage-level lexical retrieval backed by an atomic SQLite FTS5 runtime cache, with deterministic in-memory fallback when the cache is absent, stale, or corrupt.
- A bounded OpenAlex literature scout that writes factual candidates to source-search staging without creating canonical units or judging relevance.
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

- OpenAlex credentials are process-private and never persisted, logged, or exposed through user or Agent protocols.
- Retrieval cache targets, review-token cleanup, survey bindings, and experiment artifacts are containment-checked and fail closed on stale or unsafe state.
- Judgement confirmation now binds canonical subject identity, owner route, pending status, content digest, and verification digests; duplicate identities, stale snapshots, replayed tokens, and symlink escapes fail closed.
- Confirmation remains fail-closed for AI signers, hollow judgement content, missing evidence, stale content digests, and absent current-user authorization.
- Update provenance no longer falls back from a fork, local checkout, or unknown legacy source to a canonical remote.
- Storage migration is constrained to KB data and does not rewrite installed skills or root workspace rules.
- Optional diagnostics cannot disable mandatory evidence, confirmation, containment, transaction, or recovery gates; capture failures preserve the original operation result and diagnostic exports require explicit authorization.

## [0.2.0-rc.3] - Unreleased

The current local candidate adds the R3 retrieval, freshness, experiment identity, scouting, and review-UX closure. Local acceptance passed with 1,012 tests plus installed-copy, real-source, and Obsidian Reading-view checks; no tag or publication exists.

## [0.2.0-rc.2] - Unreleased

The current candidate adds screening-first arXiv/ar5iv ingestion, first-class datasets, durable `kb next` continuation, and repository scan applicability hardening. Local release gates are complete; no tag or publication exists yet.

## [0.2.0-rc.1] - Unreleased

The candidate identifier recorded by the bundle. Local release-candidate acceptance is complete, but no release tag or publication exists yet; hosted Linux/macOS CI must pass before tagging, and this candidate must not be described as stable or GA.

# Changelog

All notable changes to this project will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and version identifiers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

The bundle currently declares **`0.2.0-rc.1`**. It has passed the complete local suite and cold installed-copy acceptance, so it meets the local release-candidate gate. It is not a stable release, is not GA, has not been tagged or published, and carries no compatibility or response-time SLA. A green hosted Linux/macOS CI matrix remains a prerequisite for a release tag.

### Added

- A fifteen-verb conversational `kb` surface with private, opt-in structured hand-off for runtime agents.
- Unified human-review readiness across paper, repository, and article workflows.
- Current-message authorization fields for confirmation hand-off and version-bound confirmation receipts.
- Exact-path multi-file operation scopes, recovery ordering tests, and clean manual-checkpoint no-op behavior.
- Source-and-branch-aware installation manifests and update behavior for local checkouts, non-main fork branches, detached checkouts, and legacy unknown-provenance installs.
- Linux and macOS release-gate workflow definitions, including public-output and installed-copy smoke tests; hosted matrix execution remains pending.
- Optional D1 local diagnostic policies, redacted runtime-failure capture, deterministic issue deduplication, and a layered read-only workspace health audit. These capabilities remain beta/scaffold rather than stable.

### Changed

- Runtime and test dependencies are exactly pinned and shared by Linux and macOS CI.
- `kb init` and `kb review` no longer depend on TTY state or read from standard input.
- Public help, errors, and runtime messages expose only natural language and supported `kb <verb>` forms.
- Runtime bootstrap avoids installing packages into arbitrary shared interpreters during normal calls.
- The distributed `.agents/AGENTS.md` now contains installed-workspace runtime rules only.
- Documentation now reflects the modular research library, private Agent protocol, recovery contract, and honest pre-release status.
- Installed Agent rules now accept natural-language diagnostic setup and health checks without adding a public verb or background telemetry.

### Security

- Confirmation remains fail-closed for AI signers, hollow judgement content, missing evidence, stale content digests, and absent current-user authorization.
- Update provenance no longer falls back from a fork, local checkout, or unknown legacy source to a canonical remote.
- Storage migration is constrained to KB data and does not rewrite installed skills or root workspace rules.
- Optional diagnostics cannot disable mandatory evidence, confirmation, containment, transaction, or recovery gates; capture failures preserve the original operation result and diagnostic exports require explicit authorization.

## [0.2.0-rc.1] - Unreleased

The candidate identifier recorded by the bundle. Local release-candidate acceptance is complete, but no release tag or publication exists yet; hosted Linux/macOS CI must pass before tagging, and this candidate must not be described as stable or GA.

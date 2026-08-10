# Changelog

All notable changes to this project will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and version identifiers follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Product sources now live in top-level `skills/` and `runtime/`, while repository-local `/.agents/` is ignored and reserved for maintainers' own tools. The installer preserves the external `.agents/**` layout through an explicit source-to-installed mapping, and local tools no longer affect product inventory, validation, rule budgets, release digests, or manifests.
- Development collaboration is now GitHub-remote-complete: tracked design/ADR/schema contracts, Epic and Atomic Issues, pushed checkpoints, consolidated PRs, Actions evidence, and human review form the complete handoff chain. Ordinary changes use a lightweight path; frozen ownership, takeover approval, exact dependency binding, and release controls are added only when the risk requires them. Local workspaces, one-off prompts, tool memory, chats, stashes, and unpushed state are no longer workflow inputs or evidence.
- Source comments and analyzer scaffold/note explanations no longer cite retired private design section numbers; current contracts are self-contained or point to tracked `docs/DESIGN.md` and `SCHEMAS.md` anchors, without changing the evidence or confirmation semantics.
- Obsidian refresh now treats every manifest-owned regular `.base` as a fully rebuildable renderer output: manual sort, filter, query, comments, invalid YAML, and other Base bytes are discarded in favor of renderer defaults. Symlinks, special files, unowned paths, managed Markdown drift, canonical data, human areas, and `.obsidian/` remain protected.
- Optional diagnostics now separate capture mode from persistence detail. Existing `off | errors-only | developer` and scalar per-skill mode settings remain compatible, while explicit `redacted | local-detailed` workspace/per-skill policy can retain a bounded private mechanical artifact and digest-bound Agent hypothesis. Private detail is transactionally bound to the redacted index, hardened against unsafe paths, and excluded from public output, export, versioning, sync, install, and update.
- Fresh explicit `kb init` workspaces now use the workspace root as the physical canonical data root, activated by a tracked byte-canonical layout marker. Persisted `kb/...` artifact identities remain unchanged, KB Git uses exact root pathspecs, and install/update/reinstall never silently migrate a legacy physical `kb/` workspace.
- Installed rule loading now uses a one-line, user-owned root pointer plus a minimal `.agents/WORKSPACE_RULES.md`; the duplicated `.agents/AGENTS.md` and eager `.agents/AGENT_GUIDE.md` payloads are retired. Manifest-owned legacy copies are removed safely during update/reinstall, while bytes outside the root managed block remain unchanged throughout install, update, reinstall, and uninstall.
- Multi-operation skills now expose operation selectors and direct one-hop references for schema, recovery, private command catalogs, and variant workflows. Validation caps each `SKILL.md` at 500 lines and 64 KiB, checks links/anchors and shared protocol references, and requires navigation guidance for references of 200 lines or more without imposing a language-density score.
- Legacy `<workspace>/kb/` conversion now has a read-only state detector and a private, digest-bound plan/apply/rollback workflow. Eligible dedicated workspaces preserve canonical bytes, logical `kb/...` identities, Git history and root user rules; ordinary install/update/reinstall/runtime still never migrate automatically, and staged failures retain exact recovery evidence. See the [migration guide](docs/MIGRATE_KB_TO_WORKSPACE_ROOT.md).
- Newly generated paper deep-read notes now present the paper type and all five analysis sections before any full quote, with complete evidence retained in deterministic, default-collapsed callouts. Page/section links share one fail-closed source-map resolver, honestly fall back to the Markdown document, and paper Obsidian pages expose an existing canonical deep-note entry without rewriting historical notes.

### Security

- Runtime owners, journal/recovery/CAS, strict readers, indexes, diagnostics, and checkpoints share one root-role resolver. Missing or ambiguous markers, legacy/outer-Git layouts, reserved or unknown targets, collisions, symlinks, special nodes, and incomplete journals fail closed before business mutation; `.journal` and `.runtime` require explicit owner opt-in.
- Missing, empty, symlinked, special, or identity-changing workspace rules now block the public mutation dispatcher and every journal transaction before any workspace write; `kb help` and `kb doctor` remain zero-write rescue routes.
- Migration rejects outer Git, partial/unknown layouts, collisions, dirty state, incomplete journals, linked worktrees, symlink ancestors/leaves, special nodes, stale plans/receipts, and commit-boundary drift. Apply and reverse rollback require separate current-message authorization and preserve one same-filesystem private recovery receipt when exact recovery cannot complete.

## [0.2.0-rc.7] - 2026-07-29

### Fixed (R27 adversarial closure, 2026-07-28)

- Historical restore and repeated undo now separate public undoable business candidates from the complete committed-root rewind chain. Interleaved non-undoable bookkeeping, prior recovery roots, and already-consumed business roots are replayed internally while descendants remain covered by their authoritative root before-image. Directory/descendant target overlaps are revalidated stepwise inside one atomic recovery envelope, and all analyzer index rebuilds now journal the passage cache they write. Historical recovery ignores that disposable cache for backward compatibility while canonical unjournaled changes still fail closed with a neutral chain-integrity error.
- Recovery checkpoints no longer materialize workspace defaults; undoing initial workspace creation therefore commits the exact canonical deletions without recreating config/user/index/unit files. Only `.gitignore` remains as worktree infrastructure for the retained Git repository and recovery journal.
- Successful historical recovery now invalidates the disposable passage cache inside the same atomic recovery envelope, so legacy unjournaled cache refreshes neither block canonical rewind nor retain derived source text after undo.
- `kb help` and `kb doctor` remain dependency-free, read-only rescue surfaces when no core-ready Python exists. Offline installer bootstrap failure now preserves the installed files, reports runtime incompleteness honestly, and ships an exact `.agents/requirements.txt` lock with documented mirror/wheelhouse recovery instead of creating a doctor/install retry loop.
- Confirmation signer normalization now rejects compound model-only identities, common localized AI identities, and Kimi/Devin/Cursor-style tool names both during `kb init` and default-signer fallback, while retaining the explicit human-name exception and all independent evidence/authorization/receipt gates.
- Obsidian empty/lightweight summary fallbacks now follow the same derived analysis stage as frontmatter, Bases, and callouts. Evidence-recorded or awaiting-confirmation pages use neutral stage text instead of contradicting themselves with an “analysis not completed” claim, and renderer revision 10 makes old generated pages rebuildable.
- Obsidian Base YAML now uses the byte-canonical indentation and view-key order written by Obsidian 1.12.7. Renderer revision 11 prevents opening the three generated Bases from creating false managed-file drift while preserving fail-closed protection for semantic or human edits.
- Governance catalog reads now preserve the persisted `generated_at` value instead of consulting the current clock. Taxonomy/pool drift and portfolio candidate snapshots therefore remain stable across UTC-second boundaries, while explicit rebuild and configuration writers continue to advance provenance timestamps.
- Generic canonical-unit confirmations now record the schema-declared `method: kb review` for both dialogue and Obsidian exchanges. The operation journal continues to distinguish the two batch channels without mislabeling a dialogue ConfirmationReceipt as an Obsidian action.

### Changed (post-campaign resource consolidation, 2026-07-28)

- `unit-analyst` now physically owns the canonical paper, repository, dataset, and blog analyzer scripts as well as the discoverable routing surface. All current runtime navigation uses one kind registry under the shared library.
- The legacy `paper-analyst`, `repo-analyst`, `dataset-analyst`, and `blog-analyst` resource directories are removed from source and distribution. Their persisted preference, journal, receipt, provenance, and diagnostic owner identities remain unchanged inside the canonical implementations and registry.
- Copy-install updates atomically remove pre-consolidation analyzer scripts and add the four canonical `unit-analyst` scripts to the managed manifest; managed drift remains fail-closed.
- Current documentation now derives its skill inventory from the 15 discoverable directories and no longer presents retired analyzer, wiki, or navigator namespaces as shipping skills. Legacy maintainer-only drafts, one-off handoffs, audit transcripts, and historical acceptance logs may still exist locally but have zero development authority; durable contracts live in tracked design, Issue/PR, remote commits and Actions.

### Fixed (R6 cold acceptance, 2026-07-27)

- Public paper review translates the exact canonical paper-type claim into reader-facing language while keeping generic assignment-like payloads fail-closed.
- Idea analysis and review can explicitly refresh a frozen evidence corpus after new material is linked, preserving only owner-approved Agent fields and rejecting immutable-field tampering or unsafe paths before any write.
- Weekly-report delivery now uses the program title or question, owner-provided lifecycle fields and labels, natural epistemic wording, numbered sources, and a grouped evidence appendix with explicit missing categories; internal catalog, schema, and receipt mechanics no longer leak into the reader artifact.
- Discussion verification/archive and idea analysis/review verification checkpoint their Agent fill and durable discussion note exactly. Recovery output names safe research subjects, and failed source intake gives a natural recovery option for uploaded or local material.
- A complete local PDF can safely supersede an unverified degraded paper shell without overwriting evidence: the old unit is archived, both revisions retain immutable source bytes, and bidirectional lineage records the replacement. Warning-bearing PDFs remain honestly degraded while continuous multi-page substantive parsing distinguishes a complete paper from an abstract shell; existing verified or confirmed judgement still requires an explicit user decision.
- Historical restore now atomically rewinds the selected root operation and every newer un-restored root operation after proving the complete digest chain, so shared index/config targets do not create a false conflict or a partial rollback.
- Obsidian review export and apply checkpoint the human sheet at both lifecycle boundaries; processed sheets and canonical decisions finish Git-clean while private runtime registries stay untracked. In-process owner warnings are bounded in the private Agent protocol and never leak into public success stderr.

### Added (R5, 2026-07-27)

- Added atomic 1–20 source intake through the existing `kb add` surface. The full batch is preflighted and published in one root transaction/checkpoint, duplicate-only batches finish cleanly, and deep-read continuation is asked once per batch.
- Added bounded knowledge gardening to the portfolio candidate model: ready reviews, unfinished Agent work, stale surveys, resumable operations, due monitors, and mechanical taxonomy rebuilds share one classifier and produce at most three next steps. Gardening never silently deletes, defers, confirms, or reuses a stale survey receipt.
- Added explicit Obsidian human-note intake. One selected UTF-8 Markdown basename is frozen byte-for-byte as a provenance-isolated blog source; review sheets, nested paths, symlinks, special files, oversized input, and commit-time drift fail closed while the human-owned original remains outside transactions and checkpoints.
- Added observation-based preference memory to unified review. A preference becomes eligible for later tasks only after a one-time current snapshot, real human signer, current-message authorization, and content/evidence/scope-bound receipt are atomically written with its derived runtime item.
- Added a fixed `cl100k_base` rule-budget gate for the complete installed `AGENTS.md + AGENT_GUIDE.md + one discoverable SKILL.md` combination. CI rejects any combination above 8,000 tokens.

### Changed (R5 structure reduction, 2026-07-27)

- Reduced the installed discovery surface from 20 skills to 15: `unit-analyst` now routes the four existing analyzer implementations, generic wiki routing lives in `kb-cli`, and the optional maintainer navigator moved out of the release bundle. Historical owner identities and on-disk schemas remain compatible.
- Skill metadata is generated from one manifest and checked for drift. The repository test suite now lives at top-level `tests/`, and the installed distribution explicitly includes the runtime `AGENT_GUIDE.md`.

### Security (R5, 2026-07-27)

- Human-note intake uses anchored no-follow bounded snapshots, strict UTF-8, exact byte/currentness binding, origin-aware deduplication, root-transaction rollback, and exact checkpoint containment.
- Preference confirmation rejects AI and role-placeholder signers such as “我”, `user`, `human`, and `source=user`; legacy direct promotion is fail-closed, and legacy or tampered unbound runtime items remain inactive.

### Added (R4, 2026-07-27)

- Added bounded all-or-nothing experiment import for W&B JSON, stable-header CSV, and flat JSON directories. Exact raw bytes are archived, identical items replay idempotently, conflicts fail closed, and imported run facts do not manufacture diagnoses.
- Added Agent-filled, evidence-bound editorial workflows for weekly reports and PPT materials. Weekly output uses four narrative sections plus an evidence appendix; PPT output uses one conclusion, evidence, optional stable figure references, speaker notes, and a transition per slide; both remain structurally distinct from the paper outline.
- Reporting events now receive persisted reference-safe IDs, and report/bibliography figure selection safely handles mixed-kind program unit sets.

### Fixed (R4 cold acceptance, 2026-07-27)

- Diagnosis prepare/verify/direct-confirm and editorial verify now checkpoint the exact Agent-filled and generated artifacts, preventing successful workflows from leaving product-owned dirty files.
- Weekly/PPT preparation no longer treats experiment or other non-paper unit IDs as papers when collecting current figures. Stale input or figure tampering still fails closed without overwriting the previous output.

### Added (R3, 2026-07-27)

- Added deterministic bibliography export for a program's complete canonical paper selection. Citation keys derive from unit identity; DOI/arXiv/source identities deduplicate fail-closed; raw provider BibTeX is never rendered.
- Added `figure-index/v1` with normalized caption numbering, stable paper-bound reference keys, hash-addressed PNG assets, and source/index/asset byte-currentness checks. Figure captions and keys are available to search, Obsidian, reports, and drafts without mechanically selecting “key figures”.
- Added an evidence-bound seven-section paper-draft workflow owned by `report-author`. Runtime-Agent prose binds current confirmed claims, citations, and optional figures; each section uses the unified human-confirmation gate, and only seven current confirmed sections can atomically publish Markdown, LaTeX, BibTeX, and a byte-bound publication manifest.

### Added (R2, 2026-07-27)

- Added canonical `concept` knowledge units with a literature-synthesizer prepare/fill/verify flow. A concept requires at least three current confirmed source units; its Agent-authored definition and association roles require verbatim evidence, remain human-confirmation-gated, bind their upstream snapshots, and project into unified search and no-plugin Obsidian pages.
- Added a read-only bounded `context-pack/v1` to the private `kb find` protocol. Only claims covered by a current ConfirmationReceipt enter the formal lane; summaries and passages remain navigation-only. Deterministic whole-object trimming enforces 5 units × 3 claims × 2 references and a 6000-byte aggregate budget.

### Changed (R1, 2026-07-27)

- Paper intake no longer creates a quick-screen judgement. New papers go directly to one unified deep-read scaffold where the runtime Agent supplies an evidence-backed `paper_type` and the corresponding five elements; the complete note is verified and confirmed once. Legacy quick-screen records remain read-only compatible.
- `link_autodrive` now controls `kb add`: `ask_first` performs lightweight intake and asks once whether to continue, while `auto_deep_read` reuses the full `kb ingest` prepare pipeline. The `auto_screen` preference and init option are retired.
- Fresh workspaces explicitly use the personal governance profile; profile-less existing workspaces remain strict. Strict review stays at 3 items/24 hours, while personal review defaults to 10 items with bounded configurable expiry. The effective review policy is frozen into each one-time snapshot and Obsidian batch without weakening human signatures or evidence.
- Public owner root banners and installer path/error-tail leaks are removed. Exact owner output remains private to Agent diagnostics; user-visible failures use bounded Chinese classifications and recovery guidance.

### Added (Wave 1, 2026-07-26)

- 安装与依赖（A1）：ws_sync 失败保留中文首行；底层尾部只留私有诊断，公开面使用固定中文分类；非 git 源给出三条自然语言出路，内部稳定 token `source-not-git-worktree` 不进入用户面；`--allow-snapshot-source`（install.sh `--from-snapshot`）支持确定性快照打包；bootstrap 兼容性探测纳入 pymupdf4llm+fitz，缺失时准备 managed venv、pip 失败优雅降级并按 1 小时节流；doctor 公开话术诚实播报 PDF 深读就绪状态，私有协议新增 `pdf_deep_read_ready`。
- 对话面（A2）：`kb help` 每行带动词本名；`kb undo` 点名撤销对象；`kb restore` 无参列出最近 10 个操作（编号可直接恢复）；review apply 失败协议携带 `review_apply_failure`（原因码/合法 confirm-ref 清单/语法建议）；`kb init` 新增自动化档位（`--auto-ingest-mode`）与讨论风格（`--discussion-style`）两问，落 canonical 配置且重复 init 零 churn；config 新增 `set-interaction`，`record-effective` 接受 JSON 文件路径。
- owner 脚本（A3）：idea verify 静默失败清零（失败带一行中文原因）；`--input` 三级路径解析；corpus 违规列出全部可引用 unit 与扩语料方法；orchestrator `prepare-next-selection` 产出预填决策草稿 `kb/.runtime/portfolio-selection-draft.yaml`；新增 `governance_profile: personal|strict`（缺省 strict 行为逐字不变，personal 档 procedural 决策免偏好回执、脚本兜底硬约束）；monitor 新增只读 `template` 子命令，apply 兼容 YAML。
- 校验强度（A4）：evidence locator 位置校验（line=N 与 quote 实际行核对、section anchor 存在性与 chunk 内包含校验，失败附实际位置；未知形态告警放行）；`kb reject` 后 `record.status=rejected`；audit 修 INTEGRITY_PROGRAM_LINK 误报；experiment plan/log-run 中文结果行与 checkpoint。
- 代码检索（A5/G14）：repo 源码进 FTS5（`.py` 按 def/class 符号切块带限定名，其余 40 行窗/8 行重叠；跳二进制/超大/VCS 目录，预算超限显式告警）；FTS 新增 `code_terms` 拆词辅助列；`PASSAGE_INDEX_REVISION=passages-v3`（旧缓存判 stale 自动回退内存检索）。
- 接口层文档（A6）：新增 `.agents/AGENT_GUIDE.md`（机制速查+交互章程 10 条）；19 份 SKILL.md 增"启动澄清（Agent 用）"；新增 `docs/GOLDEN_SUITE.md`（8 条黄金对话规格与基线指标）。

The bundle declares **`0.2.0-rc.7`**. The exact local source tree passes 2,372 tests with 18 environment-gated skips, all 15 discoverable skill validators, Python 3.9 compatibility coverage, snapshot install/update/uninstall lifecycle, and fresh installed-copy real-repository plus no-plugin Obsidian static/idempotence acceptance. Installation and core workflows require no external API Key, paid search quota, commercial database subscription, or paid plugin. This identifier denotes a release candidate, not a stable release or GA, and carries no compatibility or response-time SLA. Publication of an exact revision is evidenced by its corresponding Git tag; a GitHub Release is optional and is not required for this candidate. Exact-candidate real-source and Obsidian 1.12.7 Reading-view acceptance are complete; a green hosted Linux/macOS CI matrix remains required before the release tag.

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

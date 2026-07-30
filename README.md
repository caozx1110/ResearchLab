# Open Research Workspace Skills

A Chinese-first research workspace for turning papers, repositories, technical articles, ideas, experiments, and reports into durable local knowledge.

The bundle installs beside your project data:

```text
workspace/
├── .agents/   # skills, runtime library, and agent rules
└── kb/        # your local research data
```

The bundle identifier is **`0.2.0-rc.7`**, sourced from `runtime/VERSION` and installed as `.agents/VERSION`. The identifier denotes a release candidate, not a stable or GA release; an exact published revision is identified by its Git tag, while a GitHub Release is optional. [CHANGELOG.md](CHANGELOG.md) records durable candidate/release acceptance summaries plus compatibility and support scope; active delivery gates, blockers, exact candidates, and live evidence belong to the linked GitHub Epic, Atomic Issues, PRs, and Actions. Installation and core workflows have no external API Key, paid search quota, commercial database, or paid plugin prerequisite.

## Capability maturity

These labels describe the current scope of each component, not the release status of the whole bundle:

- **stable**: the named infrastructure contract has deterministic release coverage;
- **beta**: the main workflow is real, but still depends on agent judgement or variable source material;
- **scaffold**: durable storage and governance exist, while research-quality generation is still being hardened;
- **dev-only**: useful for local development, but not presented as a supported end-user surface.

| Skill | Maturity | Current scope |
|---|---|---|
| `kb-cli` | stable | Sixteen-verb routing, conversational output filtering, and recovery entrypoints only. |
| `knowledge-base-manager` | stable | Schema, evidence, confirmation, exact-path recovery, and index governance; it does not interpret research material. |
| `source-intake` | beta | Atomic 1–20 item intake, deduplication, immutable source capture, full Markdown reading views with local assets, explicit human-note freeze, and retryable failures across heterogeneous sources. |
| `literature-search` | beta | Agent-led, provider-neutral literature discovery with durable queries, provenance, screening evidence, coverage, budgets, and stop reasons; it does not create canonical units. |
| `research-monitor` | beta | Provider-neutral subscriptions, due facts, frozen run receipts, retries, and evidence-bound outcomes; no daemon, scheduler, provider, or plugin is bundled. |
| `unit-analyst` | beta | One discoverable skill owns and routes the bundled paper, repository, dataset, and blog prepare/verify implementations; the runtime agent supplies substantive understanding and historical persisted owner identities remain stable. |
| `research-config-manager` | beta | One canonical preference profile is filtered by per-skill disclosure rules, then the Agent selects the task-relevant subset and stores a digest-bound receipt. |
| `discussion-archivist` | beta | Durable conclusion-level discussion archives with explicit evidence and open questions. |
| `research-orchestrator` | beta | Program spine, complete survey routing, dashboards and event flow; cross-program next-step choice is Agent-authored over a complete factual snapshot and becomes stale when inputs change. |
| `literature-synthesizer` | beta | Evidence-first survey, taxonomy, trend, contradiction, and gap artifacts are durable and bound to upstream versions; synthesis quality still depends on the agent and source coverage. |
| `idea-workbench` | beta | Candidate, evidence-first review, discussion, and explicit selection are implemented; novelty claims still require human or expert judgement. |
| `method-designer` | beta | Repo-grounded design handoff and experiment matrices are implemented; generated methods still require expert review. |
| `experiment-workbench` | beta | Typed plans, atomic W&B/CSV batch import, fingerprinted repeat-aware run logs, follow-ups, and confirmation-gated diagnoses are implemented; diagnosis quality remains agent-dependent. |
| `report-author` | beta | Agent-filled weekly/PPT editorial chains, outlines, stable bibliography export, and seven-section paper drafts consume version-bound claims, evidence, decisions, citations, and figures; composition quality and coverage still require review. |
| `skill-evolution-advisor` | scaffold | Observed preferences can be confirmed at task close and scoped to matching future work; local diagnostic capture/review exists, while automatic skill evolution is intentionally unsupported. |

A score or successful run for one component is evidence only for that component. It must not be extrapolated to a different workflow or the bundle as a whole. In particular, the scoped **stable** rows above do not make this release candidate a stable release.

## Start with a conversation

Install the bundle into a workspace root, open that workspace in Codex or Claude Code, and say:

```text
kb init
```

Then you can simply ask:

```text
请读取当前知识库，判断我现在最该做哪一步，并直接执行安全步骤；遇到需要我确认或拍板的地方停下来。
```

The agent does the mechanical work. You review judgements and make research decisions.

`kb init` creates a usable knowledge-base structure before asking for preferences. If no real human signature is configured, it offers a roughly one-minute quick setup or a clear “skip for now” path. Skipping writes no placeholder preference and does not block adding, searching, or analysing material; you can later say “补充我的研究偏好”. A real signature is requested again only before the first research judgement is confirmed.

Installation is the one-time technical bootstrap. After it succeeds, ordinary users interact only through natural language and the sixteen `kb <verb>` pseudo-CLI shortcuts below. Internal scripts, flags, environment variables, and paths are private implementation details handled by the agent; only maintainers and installation automation need the advanced commands in the installation guide.

## Install

You can paste the repository URL into Codex or Claude Code and say “把它安装到我当前 workspace；先检查，再使用项目自带安装器；不要覆盖现有研究数据”. The supported Agent path checks out the repository without piping remote code into a shell, records source provenance, reviews a bounded terminal summary plus an exact JSON plan, and then applies that plan headlessly while preserving user data. The full contract is documented in [docs/INSTALL.md](docs/INSTALL.md); no marketplace or plugin is required.

For the one-time guided setup, from this repository:

```bash
bash install.sh
```

The guided installer recommends a project-scoped copy into a workspace root. It does not install into `kb/`, and updates or uninstalls preserve existing research data. A compatible Python runtime is reused when available; otherwise the workspace prepares an isolated managed runtime when first needed. Normal `kb` calls do not install packages into a shared interpreter. If an offline machine cannot prepare dependencies, the installed files are retained with an explicit warning; `kb help` and `kb doctor` remain read-only and available, and the installation guide documents mirror, wheelhouse, and shipped-requirements recovery.

Read [docs/INSTALL.md](docs/INSTALL.md) for guided setup. Its flags, explicit paths, update, uninstall, and automation sections are administrator reference, not steps for everyday research use.

## The sixteen `kb` pseudo-CLI verbs

These are the complete public shortcut surface. Internal script arguments are intentionally not part of the user contract.

| Verb | Purpose |
|---|---|
| `kb help` | Show the conversational capability menu. |
| `kb init` | Initialize a usable knowledge-base layout, then optionally collect high-value preferences in chat. |
| `kb doctor` | Check whether the local runtime can support the workspace. |
| `kb update` | Check for an update and apply it only after explicit authorization. |
| `kb obsidian update` / `kb obsidian status` | Rebuild or audit the no-plugin Obsidian knowledge-network projection. |
| `kb add <链接或路径> […]` | Add 1–20 sources atomically, then ask once about deep reading or continue automatically when `link_autodrive` is enabled. |
| `kb ingest <链接或路径>` | Add a source and prepare its evidence-backed analysis workflow. |
| `kb review` | Show the governance-bound review batch (strict 3; personal defaults to 10); decide in conversation or export a no-plugin Obsidian checkbox sheet and confirm the batch later. |
| `kb status` | Refresh and summarize the current workspace or research program. |
| `kb next` | Show the current Agent-selected action, or ask the Agent to compare all current candidates when the previous choice is absent or stale. |
| `kb find <关键词>` | Find relevant passages with their knowledge unit and reopenable locator. |
| `kb recall` | Recall confirmed preferences, known pitfalls, and reviewed skill issues. |
| `kb resume` | Recover an interrupted knowledge-base operation. |
| `kb undo` | Undo the most recent committed knowledge-base operation. |
| `kb restore <操作编号>` | Restore state from before a named operation. |
| `kb reject <单元编号>` | Reject a mistakenly created or unwanted knowledge unit. |

Idea generation and report writing remain natural-language tasks rather than extra CLI verbs. For example:

```text
请基于当前知识库给我 3 个有证据支撑的候选 idea。
```

```text
为这个研究计划生成本周周报材料。
```

The same `kb init` and `kb review` semantics apply in a terminal, a pipe, or an agent-mediated call. They never depend on an interactive prompt inside the script.

## What the system preserves

```text
kb/
├── raw/          # immutable external source bytes
├── units/        # papers, repos, datasets, blogs, ideas, experiments, concepts
├── programs/     # research state, decisions, designs, runs, reports
├── synthesis/    # surveys, taxonomy, trends, gaps
├── config/       # user and runtime policy
├── user/         # generated navigation and reopen pages
├── output/       # exports, never the only source of truth
└── .runtime/     # private local runtime state
```

Convertible paper, HTML, Markdown, and text units preserve the original material and add a complete `source/document.md` reading view, a source map, a conversion manifest, and locally stored image assets. HTML units also add a passive normalized offline `source/archive.html`; the raw server response remains untouched. arXiv/ar5iv HTML must pass a structural quality gate before it is selected, otherwise intake falls back to PDF and finally an explicitly degraded abstract page; an explicitly requested arXiv version is preserved through every candidate. Markdown conversion preserves code, source front matter, formulae, complex tables, headings, and local image references, and the complete derived bundle is collision-checked before publication. Human readers and agents use Markdown first, while the offline page and original format remain fallbacks. Repository source stays in its native files; generated Obsidian pages can link to verified local code files without making machine-local URIs canonical evidence.

Human notes in the Obsidian inbox or annotations area remain human-owned. When you explicitly name one Markdown note, the Agent can freeze its exact bytes as a provenance-isolated blog source and run the normal evidence-backed analysis. It never sweeps a directory, treats a review sheet as a source, edits the original note, or treats authorship as confirmation; the structured result stays pending until ordinary review.

Concepts are first-class knowledge units. The runtime Agent can synthesize one from at least three current confirmed source units, but the definition and every association must carry verbatim evidence and remain pending until you confirm them. Confirmed concept pages participate in the same search index and no-plugin Obsidian projection as other units. The private result of `kb find` also contains a bounded context pack for discussion and writing: only current confirmation-receipt-bound claims enter its formal lane, while summaries and matching passages remain explicitly navigation-only.

The core rules are:

1. durable artifacts beat chat-only answers;
2. new material starts lightweight, then deepens when useful;
3. scripts scaffold and verify, while understanding comes from the runtime agent;
4. every substantive claim carries source evidence;
5. AI inference, evaluation, novelty judgement, and diagnosis require human confirmation;
6. confirmation binds to current content and evidence, and cannot be self-signed;
7. recovery and checkpoints operate on exact declared paths rather than the whole KB.

## Human and agent responsibilities

The agent can safely extract metadata, deduplicate sources, build evidence-backed notes, maintain indexes, track open questions, and assemble reports. It should continue safe work without asking you to operate internal scripts step by step.

You decide whether a judgement is accepted, which idea or baseline to pursue, whether an experiment conclusion is sound, and when a research program changes stage. A confirmation must come from the current user interaction and retain evidence; remembered authorization is not enough.

Canonical claim bytes retain their verified epistemic fields after confirmation. A current top-level confirmation receipt is the authority that lets consumers project its covered, evidence-current claims as confirmed; rewriting claim fields merely for display would invalidate the verified content binding.

`kb review` includes only material whose agent fill and verification are complete. Items still awaiting analysis, verification, or retry remain out of the human decision queue.

Review cards are one-time, version-bound snapshots. They expire after 24 hours; a used, expired, changed, or invalid card is rejected with a distinct recovery message. If the underlying content changes, run `kb review` again to see the new text before deciding. For an Obsidian round-trip, the generated Bases stay read-only and a separate human-owned annotation sheet exposes only confirm/reject/defer checkboxes. The Agent must restate the checked batch in the current conversation before applying it; checkboxes alone are not authorization. Cross-owner application is all-or-none.

Natural-language literature discovery routes to `literature-search`. The Agent uses whichever search, browser, or connector capabilities are actually available, explains the scope in human terms, and stores a bounded, resumable candidate stage with every query, discovery path, retryable failure, screening basis, coverage gap, hard budget, and stop rationale. Ordinary requests are exploratory and make no completeness claim; an explicit systematic request is labeled bounded unless its sources, queries, result depth, and screening are reproducible. Multi-reviewer runs retain append-only per-reviewer decisions and explicit adjudication; separate execution contexts may be called independent, while one Agent using several roles is labeled assisted. Search content is treated as untrusted data. The Agent shows a small evidence-backed shortlist, and `include`/`maybe` never becomes intake authorization: only candidates explicitly selected by the user in the current conversation can become canonical papers. No provider SDK or credential is built into the bundle. Installation and core workflows never require an external API Key, paid search quota, commercial database subscription, or paid plugin; optional host capabilities may improve coverage but cannot become a prerequisite.

Natural-language requests such as “每两周关注这个方向的新论文” route to `research-monitor`. It preserves the target, timezone-aware cadence, scope, budget, due windows, retry state and evidence-bound results. It deliberately includes no search provider, daemon, cron job, file watcher or Obsidian plugin. A host automation is optional and requires explicit user authorization; otherwise the subscription becomes visible the next time the Agent checks `kb next` or resumes the workspace.

Natural-language “整理一下知识库” requests use the same bounded portfolio view as `kb next`. Ready review items, unfinished Agent fill/verify work, stale surveys, resumable operations, due monitors, and mechanical taxonomy refreshes are classified together; at most three next actions are shown. Gardening never silently deletes, defers, confirms, or reuses a stale survey receipt.

`kb find` is passage-oriented lexical retrieval. It returns up to five short excerpts with unit identities and project-relative locators. A missing, stale, or damaged local search cache falls back to an in-memory read-only search, so querying never mutates the KB. It supports same-language and mixed CJK/ASCII tokens but does not pretend to provide cross-language semantic search.

Experiment exports can be imported in one bounded batch from W&B JSON, CSV, or a flat JSON directory. The batch is all-or-nothing, preserves exact raw provenance, replays identical items without duplication, and never turns mechanical run facts into a diagnosis. A diagnosis remains an Agent-authored, evidence-backed judgement that requires human confirmation.

Natural-language weekly-report and PPT requests use separate Agent-filled editorial contracts over current confirmed claims, decisions, factual events, and stable figures. Weekly reports use the program title or research question, reader-facing epistemic labels and numbered sources; their evidence appendix separately lists confirmed decisions, research claims with evidence, and factual progress, including an explicit missing statement for an empty group. Internal catalog IDs, schema fields, and receipt mechanics stay out of the delivered report. PPT materials render one conclusion with evidence, optional figure references, speaker notes, and a transition per slide. Both differ from the seven-section paper outline, and stale inputs cannot overwrite the previous complete output.

When newly linked material is needed by an in-progress idea analysis or review, the Agent can explicitly refresh that operation's frozen evidence corpus. The refresh preserves only the owner-approved semantic fields, rebuilds every corpus/orientation/anchor binding, and refuses immutable-field tampering or unsafe paths without overwriting the existing work.

## Optional local developer diagnostics

D1 adds an optional, local-only quality loop without adding a diagnostics verb. Its automatic mode is off by default. The later sixteenth verb is the unrelated no-plugin Obsidian projection entrypoint. You can ask the Agent in natural language to “开启开发者诊断”, “仅在出错时记录”, “关闭 unit-analyst 诊断”, “对刚才失败做脱敏复盘”, or “检查知识库健康”.

`errors-only` records deterministic operation failures without asking a model to diagnose them. `developer` may also run a short, triggered retrospective, bounded by per-task token and issue budgets; per-skill settings can narrow either mode. An explicit request to record a problem is honored even when automatic capture is off.

Diagnostics never disable schema, evidence, confirmation, containment, transaction, or recovery gates. Records stay on the local workspace, there is no background telemetry or automatic upload, and a captured issue cannot edit a skill or roadmap. Any export requires current-message authorization and is redacted by default. Mechanical workspace health checks are read-only and do not judge research conclusions.

This D1 slice is beta/scaffold, not part of the scoped stable promises above. Ordinary `kb doctor` output remains a concise runtime check; an Agent-mediated diagnostic check may privately consume the effective mode and mechanical audit counts before explaining the result in natural language.

## Update provenance and local data

Installed copies record where their source came from and, for remote sources, which branch was selected. An installation from a local checkout stays attached to that checkout; an installation from a fork branch stays attached to that fork and branch. A legacy manifest with no trustworthy origin or branch asks you to choose rather than silently switching to a canonical remote. A detached checkout is pinned to its recorded commit and requires a branch choice before later updates.

The release bundle contains no private `kb/`. Storage migration and updates are scoped so they do not rewrite the installed skill tree or root workspace rules, and uninstall leaves the knowledge base in place.

## Documentation

- [Installation](docs/INSTALL.md)
- [User guide](docs/USER_GUIDE.md)
- [Design](docs/DESIGN.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

The on-disk schema source is [runtime/lib/research/SCHEMAS.md](runtime/lib/research/SCHEMAS.md). The root [AGENTS.md](AGENTS.md) is for contributors developing this skill system; [runtime/AGENTS.md](runtime/AGENTS.md) and [runtime/AGENT_GUIDE.md](runtime/AGENT_GUIDE.md) are installed into `.agents/` for runtime agents. Repository-local `/.agents/` is ignored and reserved for maintainers' own tools; it is never product source or release input.

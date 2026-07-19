# Open Research Workspace Skills

An experimental, Chinese-first research workspace for turning papers, repositories, technical articles, ideas, experiments, and reports into durable local knowledge.

The bundle installs beside your project data:

```text
workspace/
├── .agents/   # skills, runtime library, and agent rules
└── kb/        # your local research data
```

This repository is currently an **internal alpha / pre-release**. The evidence and confirmation invariants are intentional, but interfaces may still change before the first stable release. See [CHANGELOG.md](CHANGELOG.md) for the current release state.

## Capability maturity

These labels describe the current scope of each component, not the release status of the whole bundle:

- **stable**: the named infrastructure contract has deterministic release coverage;
- **beta**: the main workflow is real, but still depends on agent judgement or variable source material;
- **scaffold**: durable storage and governance exist, while research-quality generation is still being hardened;
- **dev-only**: useful for local development, but not presented as a supported end-user surface.

| Skill | Maturity | Current scope |
|---|---|---|
| `kb-cli` | stable | Fifteen-verb routing, conversational output filtering, and recovery entrypoints only. |
| `knowledge-base-manager` | stable | Schema, evidence, confirmation, exact-path recovery, and index governance; it does not interpret research material. |
| `source-intake` | beta | Staging, deduplication, immutable source capture, and retryable failures across heterogeneous sources. |
| `paper-analyst` | beta | Evidence-backed prepare and verify gates; the runtime agent supplies the substantive reading. |
| `repo-analyst` | beta | File-oriented capability-map preparation and evidence verification; the runtime agent supplies code understanding. |
| `blog-analyst` | beta | Article preparation and claim verification; the runtime agent supplies interpretation and credibility judgement. |
| `research-config-manager` | beta | Preference and policy persistence is real, but not every preference is consumed by every downstream skill. |
| `discussion-archivist` | beta | Durable conclusion-level discussion archives with explicit evidence and open questions. |
| `research-orchestrator` | scaffold | Program spine, routing, dashboards, and event flow; prioritization remains policy-driven. |
| `literature-synthesizer` | scaffold | Evidence-first survey structures exist; taxonomy, trend, and gap synthesis still depends heavily on the agent. |
| `idea-workbench` | scaffold | Candidate, review, discussion, and selection structures exist; novelty quality is not benchmarked as stable. |
| `method-designer` | scaffold | Design handoff and experiment-matrix structures exist; generated methods require expert review. |
| `experiment-workbench` | scaffold | Typed run logs and diagnosis governance exist; diagnosis quality remains agent-dependent. |
| `report-author` | scaffold | Reports and outlines consume durable evidence, but composition quality and coverage remain under hardening. |
| `skill-evolution-advisor` | scaffold | Learning capture and review exist; automatic skill evolution is intentionally not a supported promise. |
| `wiki-adapter` | scaffold | A thin compatibility and routing layer, not an independent analysis engine. |
| `research-navigator` | dev-only | The local browser workbench remains a development surface; generated Markdown navigation is beta. |

A score or successful run for one paper, repository, or article analyzer is evidence only for that analyzer. It must not be extrapolated to survey, idea, method, experiment, report, navigation, or the bundle as a whole. In particular, the two scoped **stable** rows above do not make this pre-release a stable release.

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

## Install

From this repository:

```bash
bash install.sh
```

The guided installer recommends a project-scoped copy into a workspace root. It does not install into `kb/`, and updates or uninstalls preserve existing research data. A compatible Python runtime is reused when available; otherwise the workspace prepares an isolated managed runtime when first needed. Normal `kb` calls do not install packages into a shared interpreter.

Read [docs/INSTALL.md](docs/INSTALL.md) for copy, update, uninstall, and automation details.

## The fifteen `kb` verbs

These are the complete public shortcut surface. Internal script arguments are intentionally not part of the user contract.

| Verb | Purpose |
|---|---|
| `kb help` | Show the conversational capability menu. |
| `kb init` | Initialize the knowledge-base layout and collect missing preferences in chat. |
| `kb doctor` | Check whether the local runtime can support the workspace. |
| `kb update` | Check for an update and apply it only after explicit authorization. |
| `kb add <链接或路径>` | Add a paper, repository, article, or local file as a lightweight source. |
| `kb ingest <链接或路径>` | Add a source and prepare its evidence-backed analysis workflow. |
| `kb review` | Show human-review-ready judgements and accept a natural-language decision. |
| `kb status` | Refresh and summarize the current workspace or research program. |
| `kb next` | Suggest the next useful research action. |
| `kb find <关键词>` | Search the local knowledge units. |
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
├── units/        # papers, repos, blogs, ideas, experiments
├── programs/     # research state, decisions, designs, runs, reports
├── synthesis/    # surveys, taxonomy, trends, gaps
├── config/       # user and runtime policy
├── user/         # generated navigation and reopen pages
├── output/       # exports, never the only source of truth
└── .runtime/     # private local runtime state
```

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

`kb review` includes only material whose agent fill and verification are complete. Items still awaiting analysis, verification, or retry remain out of the human decision queue.

## Update provenance and local data

Installed copies record where their source came from and, for remote sources, which branch was selected. An installation from a local checkout stays attached to that checkout; an installation from a fork branch stays attached to that fork and branch. A legacy manifest with no trustworthy origin or branch asks you to choose rather than silently switching to a canonical remote. A detached checkout is pinned to its recorded commit and requires a branch choice before later updates.

The release bundle contains no private `kb/`. Storage migration and updates are scoped so they do not rewrite the installed skill tree or root workspace rules, and uninstall leaves the knowledge base in place.

## Documentation

- [Installation](docs/INSTALL.md)
- [User guide](docs/USER_GUIDE.md)
- [Design](docs/DESIGN.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

The on-disk schema is documented in [`.agents/lib/research/SCHEMAS.md`](.agents/lib/research/SCHEMAS.md). The root [AGENTS.md](AGENTS.md) is for contributors developing this skill system; the distributed [`.agents/AGENTS.md`](.agents/AGENTS.md) governs agents using an installed workspace.

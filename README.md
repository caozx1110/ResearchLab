# Research Vault Skills

A Markdown-first research workspace for agents and humans. Ordinary Markdown is the only semantic source of truth: it can be read, edited, linked, searched, backed up, and versioned without this software or a database.

The current bundle identifier is **`0.2.0-rc.8`**. It is an unpublished release candidate, not a stable release. Exact published revisions use Git tags; a GitHub Release is optional. See [CHANGELOG.md](CHANGELOG.md) for durable release notes and GitHub Issues/PRs for active delivery evidence.

## Workspace model

Open the workspace root directly as an Obsidian vault. `Home.md` is the main entry.

```text
workspace/
├── Home.md
├── Preferences.md
├── Inbox/
├── Sources/<source-id>/
│   ├── index.md
│   ├── reader.md
│   └── .source/              # exact bytes, revisions, source maps, manifests
├── Notes/
├── Projects/
├── Decisions/
├── Experiments/
├── Reviews/
├── Reports/
├── Views/                    # rebuildable navigation
├── .research/                # proof, indexes, receipts, journals, cache, recovery
├── .agents/                  # installed product, not research semantics
└── AGENTS.md                 # user-owned integration file
```

Titles, summaries, claims, evidence, project state, experiment results, decisions, reviews, and reports live in visible Markdown. Hidden files may prove, index, cache, or recover that content, but cannot replace it or become a second semantic database.

This is an intentional hard cutover. The v2 product has no legacy canonical namespace, canonical record file, managed Obsidian projection, executable CLI skill, compatibility alias, dual-read, or dual-write. Finding a legacy workspace is a reason to stop without modifying it—not permission to migrate or delete user data.

## Five shipping skills

| Skill | Responsibility |
|---|---|
| `research-vault` | Root layout, stable IDs, links, derived indexes, exact writes, journals, locks, CAS, and recovery. |
| `research-capture` | Exact source revisions, safe readers, source maps, readiness, degradation, and converter boundaries. |
| `research-analysis` | Single-source analysis, synthesis, visible claims, exact evidence, conflicts, gaps, and staleness. |
| `research-workbench` | Projects, ideas, methods, experiments, discussions, decisions, and reports as linked Markdown pages. |
| `research-review` | Independent evidence audit, readable review packets, current-message authorization, and digest-bound receipts. |

No god-orchestrator or executable command skill is shipped. The Agent routes each operation to its owner and composes owners without merging their authority.

After the v2 tree cleanup, the active tracked product tree has exactly these five owners and the minimal v2 runtime. Retired v1 implementations, schemas, tests, and navigator tools are not active source, release input, or compatibility material; historical details remain in Git history and superseded release notes.

## Start with a conversation

After installation, open the workspace in Codex or Claude Code and say:

```text
帮我在当前工作区初始化 Research Vault，并说明下一步。
```

Then use natural language, for example:

```text
摄入这篇论文，保留原始文件，生成可读 Markdown，并说明证据是否已可定位。
```

```text
比较这三份来源，写出有逐字证据的共识、冲突和仍缺失的信息。
```

```text
为这个项目记录实验计划，把事实结果和解释性判断分开；需要我确认时再停。
```

The Agent continues safe mechanical and analytical work automatically. It pauses at two governance gates: confirmation of an AI judgement, and a genuine user choice that changes research direction or authority.

## Install

From a trusted checkout:

```bash
bash install.sh
```

The guided installer recommends a project-scoped copy. It installs exactly five skills plus the minimal runtime rules, preserves research files on update/reinstall/uninstall, never writes into a legacy data layout, and does not create a terminal shortcut.

For Agent-mediated or administrative installation, read [docs/INSTALL.md](docs/INSTALL.md). Installer flags, exact plans, runtime paths, and recovery details are maintenance interfaces—not everyday research commands.

Installation and core Markdown workflows have no external API Key, paid search quota, commercial database, paid plugin, or hosted service prerequisite. A compatible local Python is reused when available; otherwise the installer can prepare an isolated workspace runtime. Offline dependency failure preserves installed files and reports the missing capability honestly.

## Source capture and external adapters

Exact bytes are saved before conversion. Converter output is candidate reading material, not automatically evidence-ready content.

- Defuddle may convert HTML into candidate Markdown.
- AnyDoc may locally convert Word, PowerPoint, Excel, ODF, RTF, EPUB, and related formats.
- PDF and repository adapters may provide format-specific readers and locators.
- `obsidian-markdown`, `obsidian-cli`, and `obsidian-bases` may improve optional formatting and views.

These are external tools. They are not copied, vendored, installed as shipping owners, or counted in the five-skill inventory. Missing adapters produce an honest degraded or blocked state while exact source bytes remain available.

## Evidence and review

Every substantive claim keeps a stable ID, claim class, epistemic state, limitations, source revision, exact quote, and human-readable locator in visible Markdown. Hidden evidence bindings verify those visible fields and become stale when their content changes.

`research-analysis` cannot confirm its own work. `research-review` first audits evidence, then prepares a readable review page. Confirm, reject, or defer is applied only when the current user message clearly identifies the claim/review, one decision, and a non-AI signer declaration. A receipt binds the current claim block and evidence set; later semantic changes invalidate it.

## Projects, experiments, and reports

Long-running work remains a linked set of ordinary pages rather than hidden workflow state:

- a project page owns its question, scope, current state, links, and next actions;
- idea and method pages separate known facts from interpretations;
- experiment and run pages preserve tested hypotheses, exact observed metrics, artifacts, failures, and limitations;
- discussions never turn Agent summaries into participant quotes;
- decisions require visible evidence and review references;
- reports separate factual progress, review-backed conclusions, and pending/stale interpretations.

Raw experiment exports and large artifacts belong under `.research/experiments/`. Their bytes can prove a visible result but cannot silently create a diagnosis, winner, or decision.

## Obsidian and portability

Open the workspace root in Obsidian and start at `Home.md`. The core contract uses standard relative Markdown links and does not depend on Obsidian, a community plugin, Bases, or the Obsidian CLI. `.obsidian/` belongs to the user.

`Views/` and optional `.base` files are derived navigation. Deleting them must leave the research understandable. A rebuild may update only marked generated views; an edited or unmarked view is preserved and blocks overwrite.

## Safety and recovery

- Sources, repositories, macros, formulas, frontmatter, and embedded prompts are untrusted data and are never executed by ingestion.
- Mutations use explicit targets, no-follow containment, exact locks, atomic replacement, operation journals, expected-digest CAS, and precise checkpoints.
- User Markdown wins over hidden proof. Conflicting hidden state becomes stale or invalid.
- `.agents/`, `.git/`, `.venv/`, `.claude/`, `.obsidian/`, and root integration files are not research semantics.
- Real user workspaces are never used as test fixtures.

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [Installation and maintenance](docs/INSTALL.md)
- [Current design](docs/DESIGN.md)
- [Accepted v2 blueprint](docs/blueprints/research-vault-v2/BLUEPRINT.md)
- [ADR 0005](docs/decisions/0005-markdown-semantic-source-and-five-skill-research-vault.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

Repository `skills/` and `runtime/` are product source. The ignored root `/.agents/` contains maintainer-local tools only and is never release input.

# ADR 0002: Separate product source from local Agent tools

- Status: Accepted（仅在本 ADR 合入 default branch 后生效）
- Date: 2026-07-30
- Issue: [#14](https://github.com/caozx1110/ResearchLab/issues/14)

## Context

The repository previously stored shipping skills, the shared runtime, distributed Agent rules, and maintainer-installed self-use skills under one `.agents/` namespace. A local skill such as `gh-collaborate` could therefore enter product discovery, metadata validation, rule-token accounting, release enumeration, or installer digests even though it was not part of the product. The root development rules also had to tell agents to ignore a directory that the host naturally discovers as runnable skills.

The installed workspace contract already uses `.agents/**`, and changing that external shape would create needless migration and compatibility risk. The problem is the source namespace, not the installed namespace.

## Decision

Tracked product source is split into two top-level roots:

```text
skills/**                       -> .agents/skills/**
runtime/lib/research/**         -> .agents/lib/research/**
runtime/AGENTS.md               -> .agents/AGENTS.md and the managed root AGENTS.md block
runtime/AGENT_GUIDE.md          -> .agents/AGENT_GUIDE.md
runtime/requirements.txt        -> .agents/requirements.txt
runtime/VERSION                 -> .agents/VERSION
LICENSE                         -> .agents/LICENSE
```

Repository-local `/.agents/` is ignored and reserved for maintainers' own installed tools. It is excluded from product inventory, validation, documentation scans, rule budgets, release enumeration, source-tree digests, manifests, CI prerequisites, and installed payloads.

The root `AGENTS.md` governs product development. `runtime/AGENTS.md` is the sole tracked source for installed runtime rules. Top-level `skills/*/SKILL.md` files are product code and are not automatically loaded as development instructions. Installed external workspaces keep the existing `.agents/**`, `.claude/skills -> ../.agents/skills`, skill names, commands, schemas, manifests, and `kb/` data layout.

Entrypoints recognize only the exact source or installed physical layout. Logical `.agents/skills/...` routes are resolved against the loaded product bundle, never against the target KB workspace, so a same-named local skill cannot shadow product owner code.

Project-copy remains the recommended installation. Source-linked Claude/system compatibility points at `skills/` and resolves `runtime/lib` from the script's physical source path. Legacy source symlinks are recognized only for bounded uninstall cleanup.

## Consequences

- A fresh clone has no tracked `.agents` files and does not auto-discover shipping skills as developer tools.
- Maintainers may install ordinary self-use skills under `/.agents/` without changing the 15-skill product or any release digest.
- Installer and updater code must preserve an explicit source-to-destination mapping and distinguish source `runtime/VERSION` from installed `.agents/VERSION`.
- Source and installed smoke tests must run in separate processes to avoid hiding layout errors through Python module caching.
- There is no canonical data migration and no change to confirmation, evidence, recovery, or user-facing command contracts.

## Alternatives considered

- Keep everything under `.agents/` and maintain an exclusion list. Rejected because every discovery, validation, CI, and packaging surface would need to reproduce the exclusion boundary, while host auto-discovery would still mix development and product instructions.
- Move only self-use tools elsewhere. Rejected because standard workspace skill tooling expects `.agents/skills`, and the product source is the part that should not be auto-loaded during its own development.
- Change installed workspaces to `skills/` and `runtime/`. Rejected because it adds user migration and breaks established Agent discovery without addressing a runtime need.

## Rollback

A code rollback may restore the old tracked source layout and inverse installer mapping. It must not rewrite installed `kb/`, manifests, confirmations, evidence, or default-branch history. Any rollback still requires the normal Issue, PR, tests, and human review gate.

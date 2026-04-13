# Publishing Notes

This document explains how to treat the repository as an open-source skill and workflow package rather than as a bundled private knowledge base.

## Intended Public Surface

The publishable subset is:

- `.agents/`
- `AGENTS.md`
- `docs/`
- `README.md`

Everything else should be treated as local runtime or private workspace state unless you explicitly choose to publish it.

## Knowledge Base Root

All workflow logic in the publishable surface is written against:

```text
kb/
```

Expected runtime subtrees include:

- `kb/intake/`
- `kb/library/`
- `kb/programs/`
- `kb/wiki/`
- `kb/user/`
- `kb/memory/`

The repository can be published without a populated `kb/` tree. The open-source package provides the skills, scripts, and schema; users create their own local knowledge artifacts.

## Documentation Placement

User-facing guidance is kept in `docs/`, including:

- `docs/GETTING_STARTED.md`
- `docs/SKILLS_GUIDE.md`
- `docs/llm-wiki.md`

This keeps onboarding and explanatory material separate from runtime knowledge artifacts.

## Portability Rules

When preparing changes for publication:

1. Prefer relative paths over user-specific absolute paths.
2. Avoid machine-specific interpreter locations in guidance; describe configured runtimes instead.
3. Keep environment assumptions configurable.
4. Treat `kb/` as the canonical runtime target and only keep `doc/research/` fallback behavior where migration compatibility is necessary.

## Runtime Compatibility

Some scripts keep a compatibility fallback for legacy workspaces that still use `doc/research/`.

This fallback is intended only to make migration safer. New setups should initialize and use `kb/`.

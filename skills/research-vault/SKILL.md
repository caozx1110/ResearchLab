---
name: research-vault
description: Maintain a Markdown-first Research Vault with safe layout, identity, indexes, and recovery.
---

# Research Vault

Use this skill for the file and transaction foundation of a v2 research
workspace. The visible Markdown files are the only semantic source of truth;
`.source/` preserves source proof and `.research/` stores evidence bindings,
receipts, derived indexes, journals, locks, caches, logs, and recovery state.

<!-- protocol-reference-exempt: self-contained Research Vault v2 contract -->

Follow the local [Research Vault v2 contract](references/v2-contract.md):

- Initialize the workspace root with `Home.md`, ordinary Markdown page areas,
  `Views/` fallbacks, and classified `.research/` directories.
- Require stable `id`, `kind`, and human-editable `status` frontmatter for
  durable object pages. Resolve objects by ID; paths are movable locations.
- Keep `Home.md`, object pages, and user-owned `Preferences.md` readable with
  standard relative Markdown links. Never make hidden JSON or YAML canonical.
- Rebuild `.research/index/` and marked derived `Views/*.md` from visible
  Markdown and source manifest digests. Never rewrite `Home.md` or an edited
  view automatically.
- Route every mutation through explicit literal targets, no-follow and
  reserved-path checks, atomic replacement, expected-digest CAS, exact locks,
  and an operation journal. Failed operations roll back before-images or leave
  a recoverable journal.

The implementation boundary is in `scripts/vault.py`. It is intentionally
standalone so isolated fresh-vault tests do not need a real user vault or the
legacy v1 runtime. The skill does not ingest sources, interpret evidence,
write claims, or confirm judgements.

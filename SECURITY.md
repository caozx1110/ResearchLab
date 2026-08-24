# Security Policy

## Supported versions

The current candidate identifier is `0.2.0-rc.8`. The identifier denotes an unpublished release candidate, not a stable or GA release; an exact published revision is identified by its Git tag, while a GitHub Release is optional. Every release tag is gated on hosted Linux/macOS CI plus exact-candidate real-source and Obsidian acceptance. Installation and core workflows do not require an external API Key, paid search quota, commercial database subscription, or paid plugin. There is no stable supported release yet; security fixes target the current default branch and, when applicable, the current candidate line, while older snapshots may not receive backports.

## Report a vulnerability privately

Please use [GitHub private vulnerability reporting](https://github.com/caozx1110/ResearchLab/security/advisories/new) for vulnerabilities, governance bypasses, unsafe update or installer behavior, path traversal, data loss, credential exposure, or a way to read or modify private research material.

If GitHub itself is unavailable or the account, repository, ruleset, or commit history may be compromised, do not push, merge, or disclose sensitive details through GitHub. Treat repository state after the suspected trust break as untrusted and stop. This is the explicit boundary of the GitHub-only collaboration protocol: only a human maintainer using a previously verified out-of-band channel may establish a new trusted anchor and authorize resumption.

Do not put exploit details, private source data, local paths, tokens, logs containing secrets, or unpublished research into a public issue. A sanitized public issue is appropriate only for non-sensitive hardening or documentation questions.

Include the affected commit or release candidate, operating system, minimal reproduction, expected boundary, and observed impact. Maintainers will acknowledge and triage reports on a best-effort basis; this release-candidate project does not promise a response-time SLA.

## Security and governance invariants

- Ordinary visible Markdown is the only human semantic truth. Hidden JSON, YAML, SQLite, caches, receipts, and logs may prove or index it but cannot supply missing claims, decisions, status, or report prose.
- Exact source bytes are saved before conversion and revisions are immutable. Optional converters are untrusted adapters; a successful conversion does not by itself make evidence ready.
- AI cannot confirm its own judgement. Confirmation requires substantive visible content, exact evidence, a non-AI signer declaration, and explicit authorization from the current user message.
- Receipts bind the current claim block and evidence set. Any semantic or evidence change makes the old receipt stale rather than silently preserving confirmation.
- Every mutation freezes explicit target paths and expected bytes, rejects escapes/symlinks/special nodes, and uses exact locks, operation journals, atomic replacement, CAS/currentness checks, and precise checkpoints.
- User Markdown wins over hidden proof. A conflict invalidates derived state; hidden state never overwrites the user's current page.
- `.agents/`, `.git/`, `.venv/`, `.claude/`, `.obsidian/`, and root integration files are not research semantics and never become ordinary mutation or index targets merely because they share the vault root.
- Legacy `kb/`, `record.yaml`, old root-layout markers, and `obsidian/managed/` are detected without reading their contents and stop v2 installation or mutation. v2 does not migrate, move, rewrite, or delete them.
- The installed release exposes exactly five skill owners and an explicit four-file runtime allowlist. Retained v1 source modules, schemas, migration code, old CLI code, and developer-local `/.agents/` tools are not release payload.
- Defuddle, AnyDoc, PDF/repository converters, and Obsidian tools remain external. The installer provisions only the minimal PyYAML runtime needed by a shipping script and never installs converter stacks into a shared interpreter.
- Update provenance preserves exact source identity and manifest preconditions. Install, update, reinstall, and uninstall touch only manifest-owned integration files and preserve Research Vault content and workspace-local runtime.

If a report could weaken one of these invariants, treat it as security-sensitive even when it is not a conventional remote-code-execution issue.

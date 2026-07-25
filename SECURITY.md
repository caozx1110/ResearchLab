# Security Policy

## Supported versions

The current candidate identifier is `0.2.0-rc.7`. It has passed the local release-candidate gate, but it has not been tagged or published and is not a stable or GA release. Hosted Linux/macOS CI and real-source/Obsidian acceptance remain release-tag prerequisites. Installation and core workflows do not require an external API Key, paid search quota, commercial database subscription, or paid plugin. There is no stable supported release yet; security fixes target the current default branch and, when applicable, the current candidate line, while older snapshots may not receive backports.

## Report a vulnerability privately

Please use [GitHub private vulnerability reporting](https://github.com/caozx1110/ResearchLab/security/advisories/new) for vulnerabilities, governance bypasses, unsafe update or installer behavior, path traversal, data loss, credential exposure, or a way to read or modify private research material.

Do not put exploit details, private source data, local paths, tokens, logs containing secrets, or unpublished research into a public issue. A sanitized public issue is appropriate only for non-sensitive hardening or documentation questions.

Include the affected commit or release candidate, operating system, minimal reproduction, expected boundary, and observed impact. Maintainers will acknowledge and triage reports on a best-effort basis; this release-candidate project does not promise a response-time SLA.

## Security and governance invariants

- AI cannot confirm its own judgement.
- Judgement confirmation requires substantive content, evidence, a non-AI signer, and authorization from the current user interaction.
- Confirmation is bound to current content and evidence digests; mutation invalidates stale receipts.
- Raw source and complete parse caches are immutable derived evidence.
- Multi-file KB writes use explicit targets, journaling, locks, revision checks, and scoped checkpoints.
- Update provenance preserves local checkouts and forks; unknown legacy provenance requires a user choice.
- Install, update, migration, and uninstall do not treat private `kb/` as release content.

If a report could weaken one of these invariants, treat it as security-sensitive even when it is not a conventional remote-code-execution issue.

# R8 installation/help/navigator UX completion

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r8-install-ux`. Confirm `git rev-parse HEAD` is based on integration commit `2b1de93`; if it is not, stop and report rather than editing.

## Objective

Make the GitHub-link installation path genuinely Agent-friendly without a plugin, complete `kb help` discovery, and remove the formal `kb status` runtime dependency on dev-only `research-navigator`.

1. Add an Agent-facing install plan mode that is zero-write, bounded on human stdout, and also writes or emits one machine-readable JSON plan artifact/result suitable for exact review. The plan must declare action/scope/tools/source/targets/conflicts/conditional runtime changes and an apply contract. Do not dump thousands of target lines to the user. Preserve existing dry-run safety and tests.
2. Ensure a user can paste the GitHub URL and ask an Agent to install: docs must give a short natural-language contract; the installer must support headless explicit planning/application without TTY; source/provenance/update behavior must stay safe.
3. Expand `kb help` natural-language examples to cover literature search, complete survey route, monitoring, preferences, and Obsidian batch review. Keep the fixed public verbs accurate (do not invent pseudo-verbs that the parser lacks).
4. `research-navigator` stays dev-only. Move/implement the current-state portion of `kb status` in a formal core owner (`knowledge-base-manager` or kb-cli adapter) so normal status does not execute navigator. Preserve current user output and audit behavior. Navigator itself can remain as optional maintainer tooling.

## File ownership

You may modify only:

- `install.sh`
- `install-lib/**`
- `docs/INSTALL.md`
- `README.md`
- `.agents/skills/kb-cli/**`
- `.agents/skills/knowledge-base-manager/**`
- `.agents/lib/research/tests/test_installer*.py`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py`
- other existing installer test files under `.agents/lib/research/tests/` only if directly required

Do not edit SSOT/BACKLOG/schema/version/changelog. Do not modify `research-navigator/**`. Do not touch real `kb/`.

## Required invariants

- Public skill output only natural language + `kb <verb>`; no bare command/flag/internal path/environment interpolation/`NEXT FOR AGENT:`.
- Installer administration docs may contain explicit installation commands, but normal research UX may not.
- Headless never reads stdin. Planning is zero-write, bounded, deterministic, and target-exact through its JSON result.
- Preserve existing user data, manifest ownership, atomic update/uninstall, symlink containment, recovery, and no hidden remote execution.
- No plugin or marketplace work.

## Verification and commits

Add tests for zero-write plan JSON, bounded stdout with large target sets, no-TTY execution, GitHub/source provenance, help coverage, and status without navigator. Run installer and kb dispatcher suites plus shell syntax check. Use small commits. Do not push.

# R18 track C — installer preview truth and lifecycle byte fidelity

## STEP 0 — base sync

Reusable worktree may be behind integration. Verify it is clean, then reset it to current integration HEAD `7c5456c`. Confirm the R18 installer truth contracts exist in `temp/SYSTEM_DESIGN_SSOT.md` and `.agents/lib/research/SCHEMAS.md`. Stop if dirty or commit unavailable.

## Objective

Fix the three independently reproduced installed-copy findings: uninstall Agent plan falsely says the workspace is already unmanaged despite zero writes; install→uninstall adds one byte-level newline to user-owned root `AGENTS.md`; a valid managed project venv is ignored by update preflight and reported not ready.

## File ownership

Only modify:

- `install.sh`
- `install-lib/ws_sync.py`
- `.agents/lib/research/tests/test_installer.py`
- `.agents/lib/research/tests/test_agent_install_plan.py` only if relevant

Do not touch `.agents/lib/research/{records,sources}.py`, shipping skill scripts, docs/version, recovery/updater internals, or real `kb/`.

## Required contract

1. Agent plan / dry-run public text describes future/expected changes only. The sentence that the workspace is no longer managed is emitted only after actual successful uninstall. Zero-write plan must leave the complete workspace byte snapshot unchanged except its explicitly external plan JSON.
2. Existing root `AGENTS.md` is a byte-preserving managed-block round trip. Install may insert a span and separator, but uninstall must restore exact before bytes including zero/one/multiple trailing newlines, no trailing newline, prefix/suffix content, CRLF or arbitrary UTF-8 bytes outside the managed span. Repeated lifecycle cannot accumulate blank lines. Do not trim generic user text. Preserve existing manifest compatibility; if new metadata is needed, make it additive and safely handle old manifests.
3. `preflight_yaml` checks a current workspace managed venv before warning/adding the conditional runtime target. Match runtime/bootstrap readiness (core yaml/markdownify/bs4 as currently intended), not merely one import. Venv ancestors must be controlled directories and import probe bounded; reject special files/ancestor swaps, but support standard venv interpreter symlinks. Agent plan remains zero-write and must not create/repair the venv.

## Permanent tests

- Installed copy → uninstall Agent plan: output has no completed/unmanaged assertion; manifest/tree exact before==after; final apply then has completed assertion.
- Parameterize user `AGENTS.md` bytes: no newline, one newline, two blank lines, CRLF, content after managed span if supported; install/reinstall/update/uninstall restores exact bytes. Repeat twice.
- Legacy/current manifests and managed blocks remain removable without deleting user content.
- Existing managed venv interpreter can import all core deps while `RESEARCH_PYTHON` cannot: doctor ready, no-op update plan/apply emits no not-ready warning and no conditional runtime target.
- Missing/broken/special/ancestor-swapped venv still gives truthful bounded warning/conditional target without blocking or executing an unsafe node.

Run exact installer/plan/bundle lifecycle tests, `bash -n install.sh`, Python 3.9 AST for ws_sync, and `git diff --check`. Use temp HOME/workspaces only.

## Red lines

- Never touch real `kb/`, HOME config, or network.
- No weakening manifest lease/CAS/rollback/plan binding.
- Public output remains natural language; structured plan private.
- No push/tag/version bump.
- Commit coherent pieces. STOP if exact old-block restoration cannot be proven without destructive trimming.

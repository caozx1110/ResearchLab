# R19 installer cold acceptance (read-only product review)

- Reviewed integration HEAD: `183982766ff6d8f3859e6a69fa42ecff93d2e5c2`
- Branch: `codex/review-remediation-integration`
- Date: 2026-07-25 (Asia/Shanghai)
- Scope: product files were read-only; every install/apply/uninstall action targeted an isolated directory below `/tmp`; no real `kb/`, HOME, tag, push, or publish was touched.

## Outcome

PASS. I found no reproducible installer usability, truthfulness, provenance, lifecycle-fidelity, or public-output blocker at this HEAD.

## Independent cold lifecycle

Source provenance in the reviewed Agent plan was bound to:

- origin `git@github.com:caozx1110/ResearchLab.git`
- branch `codex/review-remediation-integration`
- commit `183982766ff6d8f3859e6a69fa42ecff93d2e5c2`
- canonical distributable tree: 116 entries, digest `059dc7178921b30b884bc92db7d883a01ffa502caf369a11015e6d5ca794429c`

In `/tmp/workspace-oss-lifecycle-audit.wxcu8y` I created an otherwise-empty workspace with an already-existing, empty `AGENTS.md`, then exercised:

1. Codex Agent JSON install plan.
2. External byte-SHA review and exact headless apply contract.
3. `update` no-op.
4. `reinstall`.
5. Agent JSON uninstall plan.
6. External byte-SHA review and exact headless uninstall apply contract.

Observed results:

- install plan: 183 exact targets, 0 conflicts, 0 conditional runtime targets (the selected standard Python was ready), source origin/branch/commit/tree digest present;
- the plan was zero-write to workspace, HOME, runtime, and pycache, apart from the explicitly requested plan JSON outside those roots;
- install created the manifest and one managed block rather than replacing the user file;
- update reported the skills already current;
- reinstall preserved user files/runtime;
- uninstall preview did **not** say the workspace was already unmanaged or that files had already been removed;
- the manifest still existed after preview;
- only the reviewed uninstall apply announced completion and removed the manifest;
- the pre-existing `AGENTS.md` still existed and was restored byte-exactly to 0 bytes.

A separate all-tools + `kb`-shortcut plan in `/tmp/workspace-oss-installer-audit.eXNpTD` projected 189 targets and 1 conditional runtime target while leaving workspace, HOME, runtime cache, and scratch at 0 entries. The terminal preview was 17 short lines and did not expose target-by-target `.agents` paths, internal Python modules, hidden apply flags, or child sync-engine output.

## Focused executable regression evidence

The first focused run exercised the exact requested boundary cases and passed `14 passed in 79.47s`:

- zero-write Agent plan with bounded summary and exact JSON;
- uninstall plan truthfulness and reviewed apply;
- two complete install/update/reinstall/uninstall cycles for existing `AGENTS.md` bytes covering no newline, one newline, multiple newlines, CRLF, and empty input;
- suffix-after-managed-block preservation;
- legacy manifest compatibility for both managed-block and old whole-file ownership forms;
- ready standard managed venv: `kb doctor` ready, no dependency warning, zero conditional runtime target;
- broken leaf, FIFO leaf, venv symlink, bin symlink, and slow leaf all bounded/no-write and never executed the attacker marker;
- a regular workspace-local pseudo-interpreter capable of rebinding `.venv` was never executed;
- Agent plan verifier accepted exactly zero or one known runtime projection and rejected unknown/multiple projections.

The second run passed `5 passed in 8.32s`:

- reviewed plan installs headlessly with bound provenance;
- noninteractive copy lifecycle hides private sync-engine output;
- help is clear/colorless;
- noninteractive missing choices fail fast rather than prompting;
- guided cancellation writes nothing.

## Agent friendliness and leakage review

- README gives a copy-paste natural-language request for installing from a repository URL and says the Agent—not the user—handles checkout, plan review, digest, and apply.
- `docs/INSTALL.md` clearly separates the recommended URL-to-Agent path from administrator flags and tells the Agent to clone rather than pipe remote code into a shell.
- The short plan preview states action, tool, scope, selected workspace, data-preservation guarantee, plan digest, exact target/conflict counts, and zero-write result. That is enough for an Agent to verify intent before reading the machine plan.
- Displayed workspace and plan paths are the explicit targets selected for the installation audit; they are not hidden implementation paths. No source checkout internals, `.agents/lib`, `install-lib`, raw apply flags, `COMPUTE_AFTER_REVIEW`, or target-by-target paths leaked into the short terminal preview.
- Completion returns to user-level actions (`kb init`, `kb status`, or a natural-language request).
- The 20 shipping skill directories are present. No marketplace or Obsidian plugin is required by the installation path.

## Residual environment coverage (not a local finding)

This macOS acceptance did not independently exercise a hosted Linux image or the live interactive Claude/Codex UI. Those remain release-environment coverage, not a reproduced local defect.

# Codex handoff — Bundle B1: packaging core (allowlist + merge-install + reinstall + atomicity + source/target)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `install.sh`
- `install-lib/ws_sync.py`
- `.agents/lib/research/tests/test_installer.py` (+ you MAY add a new `.agents/lib/research/tests/test_bundle_lifecycle.py`)
- `.github/workflows/ci.yml`

Do NOT touch: any `.agents/skills/**`, `.agents/lib/research/*.py` (except tests), README.md, docs/**, evidence.py, kb.js, the skill validator (all B2/other). Do NOT touch real `kb/`.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `fffd5f3d3ffe2aa738a22331c0a2453256bd9b3e` (else clean → `git reset --hard fffd5f3`, re-verify). This base already has the install-UX overhaul (Chinese wizard, install/update/uninstall). Preserve that UX + all its behavior.
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → baseline **400 passed**. Confirm + report.
3. Read `AGENTS.md` (repo dev-workflow rules) first.

## GOAL (SSOT 3.16): make `.agents/` a clean multi-skill workspace bundle, project-scope copy install
Verified current gaps: `ws_sync.source_items` (ws_sync.py:93) is a **walk-with-excludes** (excludes only `__pycache__/.venv/.pyc/.DS_Store/manifest`) → it SHIPS `.agents/lib/research/tests/` and `.agents/skills/skill-evolution-advisor/scripts/eval_research_value.py` (dev G5 evaluator). install DIES on any pre-existing foreign `.agents/`. No `reinstall`. install.sh already has install/update/uninstall (actions parsed ~install.sh:261; WORKSPACE_ROOT from `--project` ~install.sh:622; ws_sync install/update/uninstall at ws_sync.py:382/418/492).

## REQUIRED CHANGES

### R4 — release allowlist (replace walk-with-excludes)
- Change `source_items` to build from an **explicit allowlist**, packaging ONLY what a user needs to run:
  - `.agents/skills/*` — the 17 runtime skills (their SKILL.md, scripts, agents/openai.yaml, assets).
  - `.agents/lib/research/**` EXCEPT `.agents/lib/research/tests/` (ship the shared runtime, NOT the pytest suite).
  - `.agents/AGENTS.md` (runtime rules) + root `AGENTS.md` handling as today.
  - `.agents/VERSION`, and `LICENSE` (repo root → ship into the workspace, e.g. as `.agents/LICENSE` or alongside — pick one, document it).
  - EXCLUDE: `.agents/lib/research/tests/`, any `eval_research_value.py` + its fixtures/`RESEARCH_VALUE*`, `temp/`, `kb/`, `.venv/`, `__pycache__`, `*.pyc/.pyo`, `.DS_Store`, the manifest, untracked files, any machine-absolute path. Keep the existing symlinked-subdir refusal.
- The allowlist must be explicit + auditable (a clear list/globs, not "everything minus a few"). A file NOT on the allowlist is NOT shipped.

### R1 — source root vs target workspace root; refuse-to-write when ambiguous
- Guarantee all writes go to the explicit `--project <dir>` target OR a cwd-discovered workspace; NEVER fall back to writing into the source repo (`REPO_ROOT`) when the target is ambiguous. If no `--project` and cwd is not clearly a workspace (and not the intended install target), **refuse with a clear error**, do not default to REPO_ROOT.
- ws_sync already has `assert_write_target` (refuses writes outside `<target>/.agents/`, ws_sync.py:172) — keep it. Verify install.sh's WORKSPACE_ROOT resolution can never silently resolve to REPO_ROOT for a copy install (same-repo mode is a distinct, intentional path — keep it, but a copy-into-external-workspace must have an explicit or discovered target).

### R2 — merge-install into a target that already has `.agents/` + other skills + AGENTS.md
- Installing must NO LONGER die on a pre-existing foreign `.agents/`. Instead **manage only the manifest-recorded (allowlisted) files**: write/refresh our bundle files, record them in the manifest, and LEAVE any user files/other skills in `.agents/` untouched.
- `AGENTS.md`: use a **managed-block merge** — wrap our bundle's runtime rules in clear begin/end markers; on install/update refresh only the block, preserving any user content outside it. If the target `AGENTS.md` has no block yet, insert one; never clobber user prose. (Reuse/extend the existing managed-block logic if present.)
- Drift protection stays: a locally-modified managed file is not silently overwritten unless `--force` (keep current behavior).
- Uninstall removes ONLY manifest-recorded files + our managed block, leaving user skills/files + `kb/` + `.venv/`.

### R3 — reinstall + atomicity
- Add a `reinstall` action (install.sh + ws_sync): = uninstall our managed files/block, then install fresh; user data (`kb/`, `.venv/`, other skills) untouched throughout.
- **Atomic install (no half-install on failure)**: stage the full file set, validate, then commit; if any step fails, roll back so the target is left as it was before (no partial `.agents/` bundle). Use temp+rename per file (already there) plus an overall guard: on error mid-install of a FRESH install, remove the partially-written managed set. Document the rollback boundary.
- Keep install/update/uninstall behavior verified in acceptance (duplicate `install` still errors → suggests `update`; unless that's what `reinstall` now supersedes — decide + document).

### R8a — install/lifecycle e2e tests (the rest of REQ8 is B2)
Add tests (extend test_installer.py or new test_bundle_lifecycle.py) driving the real install.sh/ws_sync on a **temp workspace** (NEVER real kb/):
- clean-workspace install → `.agents` + manifest land, allowlisted files present, `tests/`+`eval_research_value.py` NOT present in the installed tree.
- install into a workspace that already has an unrelated skill dir + a user `AGENTS.md` with custom prose → our block merged, user skill + user prose preserved.
- update, then uninstall → manifest files + our block removed; user skill, user prose, `kb/`, `.venv/` all survive.
- reinstall → ends in a clean install, user data intact.
- wrong/ambiguous cwd (no --project, cwd not a workspace) → refuses, writes nothing (assert REPO_ROOT untouched).
- Prefer invoking the scripts as subprocesses on tmp dirs; keep tests offline + fast.

## RED LINES
- NEVER touch real `kb/` (tmp dirs only). NEVER `git push`. Do NOT weaken confirmation/evidence governance (you're not touching it — stay out of `.agents/skills`/`lib/research/*.py` except tests).
- Preserve the committed install-UX (wizard/flags/exit codes/safety gates). Extend, don't regress.
- Allowlist is EXPLICIT; a partial/failed install must not leave a half-bundle.
- No git push. Small commits (R4/R1/R2/R3/R8a). Managed venv `$PY`. Final: report count (400 + new).
- STOP-and-report if: the managed-block merge for AGENTS.md is ambiguous vs the existing include/block logic, or making install atomic requires restructuring beyond ws_sync's file loop.

## FINAL REPORT
Per requirement: files, diff summary, tests (names), pass/fail. Confirm: allowlist excludes tests+evaluator, merge-install preserves user skills+prose, reinstall exists, no-half-install, refuse-on-ambiguous-cwd, uninstall preserves kb/.venv/user files. Final suite line + commit hashes.

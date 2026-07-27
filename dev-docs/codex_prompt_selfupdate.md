# Codex handoff — skill self-update + version (kb update)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/VERSION` (create)
- `.agents/lib/research/updater.py` (create)
- `.agents/skills/kb-cli/scripts/kb` (add `update` verb + show version in doctor)
- `.agents/skills/kb-cli/SKILL.md` (document the verb, if it lists verbs)
- test files under `.agents/lib/research/tests/`

HARD BOUNDARY — do NOT touch: `install.sh`, `install-lib/ws_sync.py` (both are being rewritten in another track — you MAY READ and INVOKE ws_sync.py as a subprocess, but MUST NOT EDIT it), config.py, records.py, confirm.py, other skill scripts, SCHEMAS.md.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `bd85defd8511d3f0f65cfa51a2c0da15aab7107f` (else clean → `git reset --hard bd85def`, re-verify).
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → baseline **384 passed**. Confirm + report.

## DESIGN (SSOT 3.15, locked): `kb update` pulls latest skill set from GitHub + a version number
Verified architecture: installs are **copies (copy-project) or symlinks (system scope)**; only the source git checkout has `.git` + origin `git@github.com:caozx1110/ResearchLab.git`. No version file today (only a manifest `source_commit`). Decisions: **semver `.agents/VERSION`** + **full update mechanism (local-source pull + GitHub-clone fallback)**.

kb resolves its install root as `DEFAULT_PROJECT_ROOT` (kb lines 13-21: walk up from `Path(__file__).resolve()` for a dir containing `.agents/lib`; symlinks resolve back to the source checkout in system scope). Manifest (copy installs only) at `<install_root>/.agents/.install-manifest.json` has `source_repo` (local path) + `source_commit`.

## REQUIRED CHANGES

### U1 — `.agents/VERSION`
- Create `.agents/VERSION` containing exactly `0.1.0\n` (semver, the first versioned release). This travels with copy installs (ws_sync copies `.agents/**`).

### U2 — `.agents/lib/research/updater.py` (new library; orchestrator over git + existing ws_sync.py)
Constant: `CANONICAL_ORIGIN = "https://github.com/caozx1110/ResearchLab.git"` (https so clone needs no SSH key). `DEFAULT_BRANCH = "main"`.

Functions (keep git/network calls behind small helpers so tests can monkeypatch them — NO real network in tests):
- `read_local_version(install_root) -> str`: read `<install_root>/.agents/VERSION`, strip; `"0.0.0"` if absent.
- `parse_semver(s) -> tuple[int,int,int]`: tolerant (non-numeric → treat as 0); used only for comparison ordering.
- `compare_versions(local, remote) -> int`: -1/0/1.
- `is_git_checkout(path) -> bool`: `<path>/.git` exists.
- `resolve_source_checkout(install_root) -> Path|None`: if install_root is a checkout → it; elif a manifest exists and `source_repo` is a checkout → that; else None.
- `resolve_origin_url(checkout|None) -> str`: `git -C <checkout> remote get-url origin` when a checkout exists, else `CANONICAL_ORIGIN`.
- `fetch_remote_version(checkout|None, cache_dir) -> str`: if checkout → `git -C <checkout> fetch --quiet origin <branch>` then read `git show origin/<branch>:.agents/VERSION`; else shallow-clone `CANONICAL_ORIGIN` (depth 1) into `cache_dir` (reuse if present, else clone) and read its `.agents/VERSION`.
- `check(install_root, cache_dir) -> dict`: `{local, remote, status}` where status ∈ `up_to_date | update_available | unknown` (unknown when the remote fetch fails — network/offline; never crash).
- `apply(install_root, cache_dir) -> dict`: perform the update:
  - **install_root is a checkout** (same-repo / system scope): `git -C <install_root> pull --ff-only origin <branch>` (fast-forward only; if it can't ff, report a clear "local changes / diverged, resolve manually" and do NOT force). Return before/after version.
  - **copy install** (manifest, not a checkout): resolve source checkout; if present → `git -C <source> pull --ff-only`; if source missing → shallow-clone `CANONICAL_ORIGIN` into `cache_dir`; then **re-sync by INVOKING the existing `install-lib/ws_sync.py update`** as a subprocess (`python3 <repo_or_clone>/install-lib/ws_sync.py update --repo <source_or_clone> --dir <install_root> --source-commit <sha>`) — do NOT reimplement the copy. Preserve ws_sync's drift protection (no `--force` unless the caller opts in).
- RED LINES inside updater: **never `git push`**; only fetch/pull(--ff-only)/clone. Never touch `kb/` user data. Network failures → return `unknown`/`status: error`, never raise to the user.

### U3 — `kb update` verb (kb-cli)
- Add `register_update` + `handle_update` following the existing pattern (see `register_undo`/`handle_doctor`); add to `VERB_REGISTRARS` (kb:928) and a `HELP_MENU` row (bump the "kb 动词（14 个）" count to 15).
- `handle_update` behavior (principle 8 + governance — updating installed code is an outward, hard-to-reverse action → check first, confirm before apply):
  - Run `updater.check(DEFAULT_PROJECT_ROOT, cache_dir)`. Print a **natural-language** status (no raw commands, no `${...}`, no script paths): current version, remote version, and whether an update is available or you're up to date. If the remote check failed (offline), say so plainly.
  - If `update_available`: additionally emit a single `NEXT FOR AGENT:` line (agent channel — not shown to the user verbatim) instructing the agent to confirm with the user, then apply by invoking the updater's apply path. Do NOT auto-apply.
  - The actual apply is invoked by the agent after user confirmation (a `--apply` argparse flag on the `update` subparser is acceptable since it's the agent's machine channel, NOT shown to the user; `handle_update` with apply set runs `updater.apply(...)` and prints a natural-language result). Keep the user-facing default (`kb update` with no flag) = check-only.
- cache_dir: use a stable per-user cache, e.g. `Path.home()/".cache"/"research-skills"` (create if needed); document it.

### U4 — `kb doctor` shows the version
- In `handle_doctor` (kb:160), add a line printing the current skill version via `updater.read_local_version(DEFAULT_PROJECT_ROOT)` (e.g. `skill_version: 0.1.0`). Keep existing doctor output.

## TESTS (all offline — monkeypatch the git/network helpers)
- version parse/compare: `0.1.0 < 0.2.0`, equal, tolerant of junk.
- `read_local_version` reads `.agents/VERSION`; missing → `0.0.0`.
- `check`: monkeypatch `fetch_remote_version` → returns higher/equal/raises → status `update_available`/`up_to_date`/`unknown`. Never raises.
- `handle_update` (check-only): update_available prints natural-language status + a NEXT FOR AGENT line; no raw commands in the user-facing lines (grep the stdout for `python3`/`.py `/`--`/`${`/`git ` — the NEXT FOR AGENT line is the ONLY allowed place for command-ish text, and it must be clearly the agent channel).
- `apply` for a checkout: monkeypatch the git pull helper, assert `--ff-only` semantics and that push is never called; for copy install assert it invokes ws_sync.py update (monkeypatch subprocess) — do NOT run real git/clone in tests.
- `kb doctor` output includes `skill_version`.

## RED LINES
- NEVER edit install.sh / ws_sync.py (invoke ws_sync.py only). NEVER `git push`. NEVER touch real `kb/`. Network calls must be test-mockable and offline-safe (failure → graceful "unknown").
- No git push. Small commits (U1/U2/U3/U4). Managed venv `$PY`. Final: report count (384 + new).
- STOP-and-report if: re-syncing a copy install via ws_sync.py's current CLI is unclear (quote its `update` argparse and report), or the ff-only pull semantics conflict with how the source checkout is used.

## FINAL REPORT
Per change: files, diff summary, tests, pass/fail. Confirm: VERSION created, `kb update` check-only default + agent-mediated apply, no push, doctor shows version, install.sh/ws_sync.py untouched. Final suite line + commit hashes.

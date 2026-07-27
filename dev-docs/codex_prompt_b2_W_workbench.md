# Codex handoff — Batch2 Track W: Workbench security (enforce loopback + write-protect derived evidence)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/research-navigator/scripts/serve_kb_browser.py`
- `.agents/skills/research-navigator/scripts/kb_browser_lib.py`
- test files under `.agents/lib/research/tests/`

Do NOT touch confirm.py / records.py / yaml_io.py / git_ops.py / kb scripts (other tracks own them).

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `328c3660b06343e131efbb339eb82f411bd94509`. If not and clean: `git reset --hard 328c366`, re-verify.
2. Managed venv test runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **307 passed**. Confirm + report.

## DESIGN (SSOT 3.11/3.12 workbench decision, locked 2026-07-16, user chose "minimal")
The KB browser server has file-write + shell/PTY endpoints and no auth. Decision = MINIMAL posture:
- **Enforce loopback**: reject a non-loopback `--host`. Default is already `127.0.0.1` (kb_browser_lib.py:49); the bug is `--host` accepts any value unvalidated (serve_kb_browser.py:480, passed to BrowserHTTPServer at :507). Cross-machine access must be explicit AND intentional — so refuse non-loopback by default, gated behind an explicit opt-in flag/env.
- **Write-protect derived evidence**: `raw/` source bytes + parse-cache `.md/.txt` must be read-only to the workbench write endpoint (upholds SSOT principle 2 "derived evidence is immutable"). Currently `_is_writable_text` (serve_kb_browser.py:143) allows any `.md/.markdown/.txt` not under BLOCKED_WRITE_ROOTS (:59), which only blocks `.git/node_modules/kb/user/kb/kb/user/navigator` — NOT unit `raw/` or parse-cache.
- **KEEP shell/PTY** (local single-user; token auth + disabling PTY are explicitly future, do NOT add them now).

## REQUIRED CHANGES

### W1 — enforce loopback host
- In `parse_args`/`main` (serve_kb_browser.py ~480-507): validate `args.host`. If it resolves to a non-loopback address, refuse to start with a clear error UNLESS an explicit opt-in is given (add `--allow-non-loopback` flag OR require env `RESEARCH_BROWSER_ALLOW_REMOTE=1`). Loopback = `127.0.0.0/8`, `::1`, `localhost`. Default behavior (no flag) with a non-loopback `--host` → `raise SystemExit` with a message explaining the risk and the opt-in.
- Do not change the default host (stays 127.0.0.1).

### W2 — write-protect raw/ + parse-cache
- Extend `_is_writable_text` (serve_kb_browser.py:143) so that, in addition to the current suffix + BLOCKED_WRITE_ROOTS checks, it REFUSES writes to:
  - any path under a unit's `raw/` directory (immutable source bytes), and
  - parse-cache artifacts (the full intake parse-cache). Identify parse-cache by its known filename/location pattern used by sources.py (`parse-cache*.yaml` / the per-unit parse cache dir). If the exact pattern is unclear, STOP and report what patterns exist rather than guessing — better to under-protect nothing than mislabel.
- The intent: a workbench user can still edit human note markdown, but cannot overwrite/truncate immutable derived evidence.
- Note `.yaml`/`.json` parse-cache already escape because their suffix isn't in WRITABLE_TEXT_SUFFIXES — that's incidental; make the raw/parse-cache protection explicit and path-based so a stray `.md/.txt` under raw/ is also blocked.

## TESTS (add a test_navigator_* file or extend test_navigator_file_safety.py)
- Non-loopback `--host` (e.g. `0.0.0.0`) without the opt-in → SystemExit; with the opt-in → allowed.
- `_is_writable_text` returns False for a `.md`/`.txt` under a unit `raw/` dir and for a parse-cache file; returns True for a normal unit note `.md` outside raw/.
- Existing navigator file-safety tests stay green.

## RED LINES
- NEVER touch real `kb/` (tests use tmp_path). Do NOT add token auth or disable PTY (future).
- Do NOT weaken existing BLOCKED_WRITE_ROOTS. Only ADD protection.
- No git push. Commit per change (W1/W2). Managed venv `$PY` for tests. Final: report suite count (307 + new).
- STOP-and-report if the parse-cache path pattern is ambiguous, or anything doesn't fit.

## FINAL REPORT
Per change: files, diff summary, tests, pass/fail. Final suite line + commit hashes.

# Codex handoff — Track V: Workbench token auth + PTY default-off

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/research-navigator/scripts/serve_kb_browser.py`
- `.agents/skills/research-navigator/scripts/kb_browser_lib.py`
- `.agents/skills/research-navigator/scripts/kb_browser_terminal.py`
- test files under `.agents/lib/research/tests/`

Do NOT touch paper.py, records.py, journal.py, kb dispatchers (other tracks).

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `813ae69025a2e419919c4268d18aae5d7d3360db`. If not and clean: `git reset --hard 813ae69`, re-verify.
2. Managed venv runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **331 passed**. Confirm + report.

## DESIGN (SSOT 3.11/3.12 workbench, locked 2026-07-17 — upgrades prior "future")
Prior round added loopback enforcement + raw write-protection (keep, build on). Now add token auth + make the PTY default-OFF.

### Current mechanics (verified — re-check by content)
- Request entry points: `do_GET` (~453), `do_POST` (~472), `do_PUT` (~491) in `BrowserHandler` (inside `create_handler`, ~289). NO shared pre-dispatch hook. `do_GET` falls through to `super().do_GET()` (~470) for static files.
- PTY: `POST /api/terminal/open` → `_handle_terminal_open` (~390) → `self.server.terminal_manager.open(mode,force)` (~395); `TerminalManager` constructed unconditionally in `main` (~546). Also `/api/terminal/input|resize|poll` (~401/412/438) and macOS `/api/system-terminal/open` (~424). No gating today.
- Launch: `parse_args` (~512, has `--host/--port/--allow-non-loopback/--debounce-seconds`), `main` (~537). Client URL minted by `browser_url(host,port,rel)` (kb_browser_lib.py ~122) = `http://host:port/<path>` — the single URL choke point.
- No auth anywhere (grep-confirmed).
- Loopback already enforced: `_host_is_loopback` (~501) + `parse_args` (~529-533) + `--allow-non-loopback` (~515). Orthogonal to token — layer token INSIDE the handler.

## REQUIRED CHANGES

### V1 — token auth on every request
- In `main` (~537), generate a one-time random token with `secrets.token_urlsafe(...)`. Pass it to the server/handler (attach to the `BrowserHTTPServer` instance like `terminal_manager`).
- Add a single `_authorized(self, parsed) -> bool` helper on `BrowserHandler` and call it at the TOP of `do_GET`, `do_POST`, `do_PUT` — including before `do_GET`'s static fallthrough (~470). Missing/wrong token → `self._send_error_json("unauthorized", 401)` (or 401 for static). Read the token from a query param (`?token=...`) and/or an `Authorization`/`X-KB-Token` header. Exempt `/api/healthz` (liveness only, no data).
- `browser_url` (kb_browser_lib.py ~122) is the single place the client URL is minted — append `?token=<token>` there so the printed URL works in a browser. Keep `base_url`/`health_url` usable without token where they must (healthz).
- Token must NOT be persisted (no file, no record, no log) — only printed to the starting terminal (principle 8: natural-language line + the ready-to-open URL, no raw commands).
- `main`'s `[ok] browser url:` print (~573) uses the tokenized URL.

### V2 — PTY default-off
- Add `--enable-terminal` flag to `parse_args` (default **False**).
- When disabled (default): `/api/terminal/open`, `/api/terminal/input|resize|poll`, and `/api/system-terminal/open` must all refuse (404 or a clear 403 JSON), and `TerminalManager` should not spawn (don't construct it, or construct-but-refuse-open). When `--enable-terminal` is passed, current PTY behavior is available (still behind token + loopback).
- The refusal message (if any user-facing) stays natural language; no raw command.

## TESTS (extend test_navigator_file_safety.py or a new test_navigator_auth.py)
- A request without the token → 401 (for do_GET static, do_POST, do_PUT). With the correct token → allowed. healthz works without token.
- `browser_url` includes the token param.
- Default (no `--enable-terminal`): terminal endpoints refuse. With the flag: they're reachable (you can assert routing/permission, not an actual shell spawn).
- Existing loopback + write-protection tests stay green.

## RED LINES
- NEVER touch real `kb/` (tmp_path). Token never persisted/logged. Do NOT weaken loopback enforcement or raw write-protection.
- No git push. Small commits (V1/V2). Managed venv `$PY`. Final: report count (331 + new).
- STOP-and-report if wiring the token through the SimpleHTTPRequestHandler static path is trickier than expected (e.g. directory listing) — better a correct GET/PUT/POST gate + report than a half-open static path.

## FINAL REPORT
Per change: files, diff summary, tests, pass/fail. Confirm: token required on all data endpoints, healthz exempt, PTY off by default, token not persisted. Final suite line + commit hashes.

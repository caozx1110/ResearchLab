# Codex handoff — Batch1 Track B: kb init preference/persona setup must actually happen (agent-mediated, no TTY)

Model: gpt-5.6-sol, xhigh, full access. This track owns ONLY:
- `.agents/skills/kb-cli/scripts/kb`
- test files under `.agents/lib/research/tests/`

Do NOT touch kb.py / intake.py / orchestrate.py (another track owns them).

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `4be20c6e526ac40d25ba203bc7120aefc5606fe5`. If not and clean: `git reset --hard 4be20c6`, re-verify.
2. Managed venv test runner (system python3 lacks fitz → false failures):
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **294 passed**. Confirm + report before editing.

## BUG (verified root cause)
The persona/preference Q&A lives inline in `handle_init` (`.agents/skills/kb-cli/scripts/kb`, ~644), gated behind `elif args.non_interactive or not sys.stdin.isatty():` (~654). When an AGENT invokes the pseudo-CLI there is no TTY → `sys.stdin.isatty()` is False → the handler runs only idempotent scaffolding (`run_init_prerequisites`) and `return 0` (~657), NEVER entering the interactive branch (~658+) where name/lang/autonomy/persona prompts live. So `kb init` via the pseudo-CLI never sets up preferences.

Also: `forward_command` uses `capture_output=True` (~133), so a child-process `input()` cannot interact either. The interaction MUST be agent-mediated, not `input()`-based.

The headless path already exists: `build_headless_init_pref_commands` (~598) turns flags (`--name/--lang/--auto-commit/--auto-screen/--persona-focus/--persona-resources/--persona-report/--persona-boundaries/--persona-term`, registered ~832-844) into `config.py set`/`set-runtime-pref` calls. And `handle_ingest` (~407) already models the correct pattern: emit a `NEXT FOR AGENT:` line for the session agent.

## DESIGN (SSOT principle 8 + 3.14, locked 2026-07-16)
The pseudo-CLI must NEVER depend on a TTY. Any "ask the user" flow = agent-mediated conversational Q&A + headless writes. Fix `kb init` so that when it runs non-TTY with no preference flags, instead of silently returning 0 it emits a `NEXT FOR AGENT:` instruction telling the session agent to:
1. Ask the user (in natural language) for: human name, language (zh/en), commit cadence, auto-screen on/off, autonomy scope, and the 4 optional persona fields (research focus / resources / reporting style / collaboration boundaries).
2. Re-invoke `kb init` with the corresponding headless flags (`--name … --lang … --persona-focus …` etc.) to persist via the existing `build_headless_init_pref_commands` path.

## REQUIRED CHANGES (`handle_init`, ~644)
- Keep: `run_init_prerequisites` scaffolding (both init_kb + init_config forwards) always runs first — that's correct and idempotent.
- Keep: the real-TTY interactive branch (a human in a terminal answering `input()` prompts) UNCHANGED.
- Keep: the headless-flags branch (`build_headless_init_pref_commands` returns non-None) UNCHANGED — that's how the agent re-invokes.
- CHANGE the non-TTY + no-flags case (currently `elif args.non_interactive or not sys.stdin.isatty(): … return 0`):
  - Still handle `--git-init` if set.
  - Instead of a bare `return 0`, print a `NEXT FOR AGENT:` block (mirror `handle_ingest`'s style/prefix) instructing the agent to collect the prefs conversationally and re-run `kb init` with headless flags. Enumerate the exact flags available so the agent knows the contract. Return 0 after emitting it (the scaffolding succeeded; the agent will follow up).
  - IMPORTANT: this `NEXT FOR AGENT:` line is the AGENT channel (category c) — it is fine for the agent to read; per principle 8 the agent must NOT relay it verbatim to the user, but that's the agent's responsibility (documented in .agents/AGENTS.md), not this script's.
- Do NOT try to make a child script prompt (blocked by capture_output=True).

## TESTS (add to a tests/ file, e.g. test_kb_cli_dispatcher.py or new test_init_agent_mediated.py)
- Non-TTY `kb init` with no flags: scaffolding runs AND a `NEXT FOR AGENT:` line is emitted (not a silent return-0-with-no-guidance). Assert the guidance mentions the persona/pref flags.
- Headless `kb init --name X --lang zh --persona-focus "..."`: persists to user-profile.yaml (persona/prefs non-empty) via the existing path — unchanged behavior still works.
- (If feasible without a real TTY) the interactive branch is not entered under non-TTY.

To simulate non-TTY in tests, monkeypatch `sys.stdin.isatty` to return False.

## RED LINES
- NEVER touch real `kb/` (tests use tmp_path).
- Do NOT weaken governance. Do NOT touch other tracks' files.
- No git push. Commit as one logical change (or split scaffolding-vs-guidance if cleaner).
- Managed venv `$PY` for tests. Final: `$PY -m pytest .agents/lib/research/tests -q`, report count.
- If the interactive/headless/non-TTY branch interplay is more tangled than described, STOP and report with the actual `handle_init` structure rather than guessing.

## FINAL REPORT
Files, diff summary, new test names, pass/fail, final suite line, commit hashes.

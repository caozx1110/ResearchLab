# Codex handoff — Batch1 Track A: user-facing output hygiene + recommend_next reads full_note_status

Model: gpt-5.6-sol, xhigh, full access. This track owns ONLY these files:
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/skills/source-intake/scripts/intake.py`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- test files under `.agents/lib/research/tests/`

Do NOT touch `.agents/skills/kb-cli/scripts/kb` (another track owns it). Do NOT touch install.sh/bootstrap.py.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `4be20c6e526ac40d25ba203bc7120aefc5606fe5`. If not, `git status`; if clean, `git reset --hard 4be20c6` then re-verify.
2. Test runner — USE THE MANAGED VENV (system python3 lacks fitz → false 2 failures):
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Expected green baseline = **294 passed**. Confirm before editing; report the count.

## DESIGN CONTEXT (SSOT principle 8 — user contract)
The end user interacts through EXACTLY two surfaces: natural language + the `kb <verb>` pseudo-CLI. Everything else is internal/agent-facing. Three categories of command strings:
- (a) **user-facing raw command** = BUG, must be scrubbed from what the user sees.
- (b) internal machine-executed (subprocess/run_forwarded) = keep.
- (c) `NEXT FOR AGENT:` machine-navigation for the runtime agent = keep, but must NOT be mixed into user-facing human output.

The user must NEVER be shown: `python3 …/*.py …`, `--flags`, `${RESEARCH_PYTHON:-python3}`, internal script paths, or `NEXT FOR AGENT:` lines. The agent computes/runs those itself; the user sees outcome + natural-language next step (or a `kb <verb>` form).

## FIX A1 — scrub user-facing raw commands (kb.py, the highest-traffic leak)

`.agents/skills/knowledge-base-manager/scripts/kb.py` prints raw commands via `kb find` and `kb review`. Current leak sites (verify by content):
- `render_review_queue` (~line 210, 224, 227, 228): `batch light-confirm: <cmd>`, `confirm: <cmd>`, `fill first: <cmd>`, `confirm (after filling): <cmd>`
- query/find output (~line 390, 392): `next: <cmd>`, `confirm: <cmd>`

`next_unit_command` (~89), `confirm_command` (imported from research.common), `batch_light_confirm_command` (~173) render raw `${RESEARCH_PYTHON:-python3} …/paper.py confirm --paper-id … --evidence …` etc.

**Required:** the NON-INTERACTIVE listing output shown to the user (what `kb find` / `kb review` forward and print) must NOT contain these raw commands. Replace each with either:
- a natural-language next step ("待你确认：说'确认 <short-id>'即可" / "需先补全内容"), OR
- nothing (drop the line) if the review's interactive path already conveys it.

Keep the command-builder functions (`next_unit_command`/`confirm_command`/`batch_light_confirm_command`) — they're still used by (b) internal apply paths and (c) agent navigation. Only change the **print sites** that reach the user. Preserve the item's id/kind/title/summary display (that's the useful part). The interactive review flow (`prompt_review_decisions`/`print_review_item`) is already clean — model your natural-language output on it.

**Guard against regression:** add a test asserting `kb find`/`kb review-queue` stdout contains no `python3`, no `.py `, no `--paper-id`/`--id `, no `${`. (Run the actual command functions on a temp KB and assert the captured stdout is clean.)

## FIX A2 — scrub intake.py user-facing hints, keep NEXT FOR AGENT separate

`.agents/skills/source-intake/scripts/intake.py`:
- `guidance_hints` (~119): the `下一步：运行 kb next …` lines are ALLOWED (pseudo-CLI form). But check for any `[hint]` line rendering raw `config.py …`/`research_python()` commands (the review flagged optional persona hints as raw `config.py` commands) — scrub those to natural language or `kb <verb>` form.
- The `confirm: {confirm_command(record)}` print after intake (~review flagged line 385): scrub — user shouldn't see a raw confirm command. Replace with natural language.
- `next_for_agent_intake` (~172-190) `NEXT FOR AGENT:` lines: these are category (c) — KEEP as machine navigation, but ensure they're clearly the agent channel (they already are). Do not print a raw command as a user-facing "tip".

**Rule:** `kb <verb>` forms in prose = OK. Raw `python3 …/*.py`, `config.py …`, `${…}` shown to the user = scrub.

## FIX A3 — orchestrate.py: scrub format_next/format_dashboard command lines

`.agents/skills/research-orchestrator/scripts/orchestrate.py`:
- `format_next` (~713): drops `command: <cmd>` line (~737) into user output. `format_dashboard` (~680): same (~709). These render `recommended_command` which is raw `${RESEARCH_PYTHON:-python3} …/orchestrate.py status --program-id …` / confirm commands.
- **Required:** the user-facing rendered output (`format_next`/`format_dashboard`) must not print raw commands. Keep the `recommended_command` FIELD in the dict (agent/internal consumers + `auto`/`execute_auto_plan` use it — category b/c), but the human-facing `format_*` string must show a natural-language next step instead of `command: python3 …`. If a pseudo-CLI form exists (`kb next`, `kb review`), you may show that.
- `format_auto_plan` (~345): only reached via `orchestrate auto` (agent-facing); lower priority but scrub the `- command:` line for consistency (or clearly keep as agent channel — your call, document it).

**Guard:** extend a test to assert `format_next(...)` / `format_dashboard(...)` output strings contain no `python3`/`.py `/`--program-id`/`${`.

## FIX A4 — recommend_next reads full_note_status (the free P0.2 win)

`safe_unit_step` (~179) is the loose-unit recommend-next. Its FIRST check (~184) is `if confirmation_status == "pending_user_confirmation": return {human-gate...}` — this fires BEFORE considering fill status, so a freshly-prepared EMPTY shell (which is set to `confirmation_status=pending_user_confirmation` + `full_note_status=awaiting_agent_fill` by the analyzer) gets recommended to the USER for confirmation. It should instead be recognized as "awaiting agent fill".

Note `full_note_status` is already read at ~line 202 for a different branch. `full_note_status` values (producers in paper.py): `not_started` / `awaiting_agent_fill` / `pending_user_confirmation`.

**Required:**
- Before the pending-confirmation human-gate (line 184), check fill status: if the unit's `full_note_status` is `awaiting_agent_fill` or `not_started` (i.e. the note/screen content is an unfilled shell), it is NOT a user-confirmation item. Return an "awaiting agent fill" step (agent should fill it, or emit agent-navigation) instead of a human-gate. Only units that are actually filled + ready (`full_note_status == "pending_user_confirmation"`, i.e. agent filled and it's genuinely awaiting the human) go to the human-gate.
- Apply the same guard in `program_dashboard_items` (~569): `pending_units` (~588-592, records with `confirmation_status == pending_user_confirmation`) must EXCLUDE unfilled shells (`full_note_status in {awaiting_agent_fill, not_started}`) from the "review pending confirmation" surface.
- Keep global/other behavior identical. Do NOT alter the confirmation gate, substance gate, or write logic. This is purely about what recommend-next SURFACES.
- If reconciling the `maturity=="complete"` vs `full_note_status` interplay is ambiguous, prefer: "an item is user-confirmable only if it has real filled content (full_note_status == pending_user_confirmation)". Screening-phase items follow the same principle via their own status field if present; if screening uses a different field, handle analogously and note it.

**Add tests:** a freshly-prepared (empty) paper unit does NOT appear as a user-confirmation recommendation in `safe_unit_step`/`program_dashboard_items`; a filled+verified unit (full_note_status=pending_user_confirmation) DOES.

## RED LINES
- NEVER touch real `kb/`. Tests use tmp_path/temp roots.
- Do NOT weaken confirmation/substance/write gates. A4 only changes what recommend-next surfaces, not any gate.
- Keep command-builder functions intact (internal + agent channels need them); change only user-facing PRINT/format sites.
- Do NOT git push. Small commits: one per fix (A1/A2/A3/A4).
- Managed venv `$PY` for all test runs. After all fixes: `$PY -m pytest .agents/lib/research/tests -q`, report final count (baseline 294 + your new tests).
- If any fix doesn't fit as specified, STOP and report with diff + reasoning.

## FINAL REPORT
Per fix: files, one-line diff summary, new test names, pass/fail. Then final suite summary line + `git log --oneline` of your commits.


# Codex handoff — Batch1 Track C: installer/bootstrap fixes (PDF backend + venv fallback)

Model: gpt-5.6-sol, xhigh, full access. This track owns ONLY:
- `.agents/lib/research/bootstrap.py`
- `install.sh`
- `docs/INSTALL.md` (only if a doc claim must be corrected to match behavior)
- test files under `.agents/lib/research/tests/`

Do NOT touch kb.py / intake.py / orchestrate.py / the kb-cli script (other tracks own them).

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `4be20c6e526ac40d25ba203bc7120aefc5606fe5`. If not and clean: `git reset --hard 4be20c6`, re-verify.
2. Managed venv test runner (system python3 lacks fitz):
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **294 passed**. Confirm + report.

## DESIGN (SSOT 4.0 installer decision, locked 2026-07-16)
Three verified defects; fix the first two (bootstrap/PDF), assess the third (dev-AGENTS) carefully:

### FIX C1 — PDF backend must be ensured even when current Python already has YAML (the core bug)
`bootstrap.py` `_bootstrap`/module entry: at ~line 257 `if _current_has_yaml(): _mark_ready(); return` — this returns BEFORE building the managed venv, and `_ensure_venv_has_pdf_backend` (~105) is ONLY called inside the venv-build path (~265 area, via `_ensure_venv_has_yaml`? verify the exact call site). Consequence: when the current Python has YAML but lacks the PDF backend (`pymupdf4llm`), the backend is NEVER installed → PDF parsing permanently unavailable. This is exactly why the test suite shows 2 `fitz` failures under a bare system Python.

**Required:**
- When current Python has YAML (the ~257 early-return path), STILL ensure the PDF backend is available before `_mark_ready()`. I.e. call the PDF-backend ensurer against the current interpreter (analogous to `_ensure_venv_has_pdf_backend` but targeting current Python), OR fall through to the managed-venv path when the PDF backend is missing. Pick whichever is cleaner and least surprising; document the choice.
- Respect the existing `RESEARCH_NO_PDF_BACKEND=1` escape hatch (~112) — if set, skip backend install (current behavior).
- The PDF-backend install must be best-effort/non-fatal in the same way it already is inside the venv path (~121-125 warns rather than aborts) — a failed backend install should WARN and continue (yaml-capable runtime still works for non-PDF flows), not hard-abort.
- Do NOT change the `RESEARCH_NO_MANAGED_VENV=1` semantics (~247-255).

### FIX C2 — install.sh preflight should not hard-abort when the goal is a managed venv
`install.sh` `preflight_yaml` (~663): checks `"$py" -c 'import yaml'` and, if missing, offers to pip-install then `die`s if still unavailable (~694). This contradicts the "no PyYAML needed; a managed venv is auto-created" promise: the managed-venv bootstrap (bootstrap.py) can itself create a yaml-capable runtime, so a missing system PyYAML should NOT abort the install.

**Required (choose the minimal correct option, document it):**
- Preferred: when system PyYAML is missing, preflight should NOT `die`. Either (a) proceed and let the managed-venv bootstrap handle it, or (b) build/prime the managed venv here. The end state must be: a machine with no system PyYAML can install successfully and end up with a yaml+PDF-capable managed runtime.
- If INSTALL.md (~18) or other docs overstate/contradict (e.g. "no PyYAML required" vs a hard preflight), correct the doc wording to match the actual (now non-aborting) behavior.
- Keep the interactive pip-install offer as a convenience, but its failure must not be fatal when a managed venv is the fallback.

### FIX C3 — same-repo install must not feed agents the developer AGENTS.md (assess, then fix or STOP)
Context: `install.sh` already installs `.agents/AGENTS.md` as the workspace `AGENTS.md` for normal workspace installs (~785-787, 1013-1018). BUT for same-repo Codex project scope (`--project .`, ~1083) it no-ops ("already present in REPO_ROOT"), so an agent operating in the repo root sees the repo-root DEVELOPER `AGENTS.md` (dev-workflow doc) + `CLAUDE.md` (symlink to it), NOT the end-user auto-drive rules in `.agents/AGENTS.md`.

**Required:** investigate whether this same-repo path can/should point the runtime agent at `.agents/AGENTS.md` (end-user rules) rather than the developer doc — WITHOUT breaking the developer's own use of repo-root AGENTS.md/CLAUDE.md as the dev-workflow source.
- If there's a clean fix (e.g. the managed import block / codex wiring references `.agents/AGENTS.md` for runtime even in same-repo scope), implement it.
- If this risks conflating the dev doc and the user doc, or the fix is larger/riskier than C1+C2, **STOP and report your findings** rather than forcing it. This one is allowed to be report-only if it's not clean.

## TESTS
- C1: a test that, given a Python with YAML but without the PDF backend, the bootstrap path attempts to ensure the backend (mock the pip call / assert the ensurer is invoked, don't actually pip-install in CI). At minimum a unit test around the decision logic (has-yaml + missing-backend → ensurer called / venv path taken).
- C2: if feasible, a shell-level or logic test that missing system yaml does not abort. If install.sh isn't unit-testable here, describe manual verification and ensure no python test regresses.
- Keep the existing suite green (294) under the managed venv.

## RED LINES
- NEVER touch real `kb/`.
- best-effort PDF/yaml installs must WARN not abort (except the explicit no-managed-venv hard case).
- Do NOT git push. Small commits per fix (C1/C2, C3 if done).
- Managed venv `$PY` for python tests. Final: `$PY -m pytest .agents/lib/research/tests -q`, report count.
- STOP-and-report on C3 if not clean; STOP on anything that doesn't fit.

## FINAL REPORT
Per fix: files, diff summary, tests, pass/fail. C3: fixed or report-only + why. Final suite line + commit hashes.

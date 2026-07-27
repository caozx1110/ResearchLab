# Codex handoff — Wave5 Polish: reporting_style wiring + experiment diagnosis evidence (E4)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/report-author/scripts/report.py` + its SKILL.md
- `.agents/skills/experiment-workbench/scripts/experiment.py` + its SKILL.md
- test files under `.agents/lib/research/tests/`

Do NOT touch config.py (read-only), synthesize/idea/method scripts, records.py, confirm.py, SCHEMAS.md (document in the two SKILL.md files instead). May import stable libs.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `1f804295a227836248dd268ddbd1c9ac11375ced` (else clean → `git reset --hard 1f80429`, re-verify).
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → baseline **381 passed**. Confirm + report.

## PART A — reporting_style wiring into report-author (SSOT 3.14 first-batch downstream)
Today `reporting_style` is stored in `kb/config/user-profile.yaml` (written by research-config-manager) but report-author never reads it. Wire it:
- report.py reads `kb/config/user-profile.yaml`'s `reporting_style` (read-only, mirror how method.py reads `resources` — load_yaml on that path, default {}). It's free-form natural language; recognize a conciseness signal (e.g. contains "简洁/concise/brief" → concise; "详细/detailed/full" → detailed; else default).
- Adjust report verbosity accordingly: concise → tighter output (e.g. cap events/claims shown, drop verbose sections); detailed → full. Keep the self-contained claims+events+evidence contract in both — concise trims volume, never drops the "missing:" markers or fabricates.
- Back-compat: no reporting_style / unparseable → current default behavior (all 381 tests stay green).
- Document in report-author SKILL.md.

## PART B — experiment diagnosis evidence (E4, deferred from wave-3 E)
Today experiment `diagnose` writes a judgement-track diagnosis (pending) but does NOT use the evidence layer. Wire verbatim-verified evidence for diagnosis:
- Let a diagnosis attach `claims` with `evidence_refs` that cite the experiment's OWN run artifacts (run-log.yaml / runs/run-NNN.md — which live in the experiment unit dir). On diagnose (or a verify step), run `validate_claims` + `verify_claim_evidence(claim, unit_dir)` so a diagnosis quote must be verbatim in a run artifact. A fabricated diagnosis quote is rejected; a valid one (quoting a real run-log line) passes.
- Import `research.evidence` (validate_claims, verify_claim_evidence) — currently unused by this skill.
- Keep diagnosis judgement-track + pending (unchanged); this only ADDS evidence grounding. The confirm substance gate + lifecycle must stay green.
- Back-compat: a diagnosis with NO claims/evidence still works as today (evidence is additive — only verify when claims are present). All 381 tests stay green.
- Document in experiment-workbench SKILL.md.

## TESTS
- Part A: a concise reporting_style produces tighter output than detailed on the same program; missing markers still present in both; no reporting_style → default (back-compat).
- Part B: a diagnosis citing a verbatim run-log quote passes; a fabricated quote is rejected by verify_claim_evidence; a diagnosis with no claims still works (back-compat). Lifecycle + confirm gate green.

## RED LINES
- NEVER touch real `kb/` (tmp_path). Understanding = agent; scripts read config / verify evidence. Do NOT modify config.py. Do NOT weaken confirm/substance gates. reporting_style trims volume but NEVER drops missing-markers or fabricates.
- No git push. Small commits (A, B). Managed venv `$PY`. Final: report count (381 + new).
- STOP-and-report if run-artifact evidence verification is awkward (e.g. run-log is YAML not free text — you may verify against runs/run-NNN.md which is markdown; if neither works cleanly, report the artifact shape rather than forcing it).

## FINAL REPORT
Per part: files, diff, tests, pass/fail. Confirm reporting_style honored + diagnosis evidence verified + back-compat. Final suite line + commit hashes.

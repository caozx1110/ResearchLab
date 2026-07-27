# Codex handoff — Wave3 Track E: experiment-workbench validator (typed metrics + artifact check + baseline comparison)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `.agents/skills/experiment-workbench/SKILL.md`
- `.agents/lib/research/records.py` (ONLY the experiment payload skeleton `kind_payload_skeleton("experiment")` — additive)
- test files under `.agents/lib/research/tests/`

Do NOT touch synthesize.py, report.py, idea.py, method.py, confirm.py, journal.py (parallel/shared). records.py: ONLY the experiment skeleton block — additive/default-safe, do not alter other kinds.
- Do NOT edit `.agents/lib/research/SCHEMAS.md` (shared file; the maintainer adds schema docs post-merge to avoid 4-way conflicts). Document your schema in your SKILL.md instead.

## STEP 0 — base sync
1. `git rev-parse HEAD` starts `3c5bedc`; else clean → `git reset --hard 3c5bedc`.
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → **353 passed**. Confirm.

## DESIGN (SSOT 3.9, locked): turn the "recorder" into a "validator"
Today (experiment.py): `parse_metrics` (46-54) → `dict[str,str]` raw strings (no float/unit/direction); artifacts stored as strings, **never stat-ed**; NO baseline/milestone/recent-N comparison (the `results.comparison` field at records.py:292 exists but is DEAD — never written); diagnosis (349-394) is judgement-track (pending) but uses NO evidence layer; no prepare/verify. Locked design:
- **Lightly-typed metrics** (name + numeric value + unit + direction) so cross-run auto-comparison / trend is possible.
- **Verify artifact existence**: a claimed checkpoint/log/plot path is checked on disk; missing → explicit error/flag, not silent.
- **Diagnosis auto-pulls recent N runs** to compare; **baseline / milestone anchors are persistently compared** on every new run (not just recent N).

## REQUIRED CHANGES
### E1 — lightly-typed metrics
- Replace `parse_metrics` string-dict with a typed parse: accept `name=value[unit][:direction]` (design a clear CLI form, e.g. `--metric "success_rate=0.82 :higher-better"` or `--metric name=success_rate --value 0.82 --unit ratio --direction higher`). Store `{name, value: float, unit, direction}` per metric. Keep back-compat: a bare `key=value` still parses (value coerced to float when possible, else kept as string with a warning) so existing tests/fixtures don't break — but the typed path is the new contract. Update the experiment payload skeleton (records.py) accordingly (additive); document the metrics shape in SKILL.md.
### E2 — artifact existence verification
- In `log-run` (and/or a new `verify` step), stat each `--artifact` path; if it doesn't exist, record it as `missing`/flag it and warn clearly (do not silently store a nonexistent path as if real). Distinguish "artifact verified present" vs "artifact missing". Keep the generated run-log/run-md paths (those always exist).
### E3 — baseline / recent-N comparison (populate the dead `comparison` field)
- On `log-run`: read prior run-log entries for this experiment, and compute a comparison against (a) the most recent N runs and (b) any run tagged baseline/milestone. Write the result into `results.comparison` (currently always `[]`). Per typed metric, show delta vs baseline + vs last run + direction-aware better/worse.
- On `diagnose`: auto-pull the recent N runs' metrics + the baseline/milestone into the diagnosis context (the script assembles the comparison; the agent writes the diagnosis judgement). Add a way to tag a run as baseline/milestone.
### E4 — diagnosis evidence (optional, only if clean)
- SSOT wants diagnosis grounded. If wiring `research.evidence` (validate_claims/verify_claim_evidence) for diagnosis claims against the run logs is clean, do it (diagnosis claims cite specific run-log metrics/artifacts as evidence). If it's involved, SKIP + note — E1/E2/E3 are the core. Diagnosis staying judgement-track + pending (as today) is fine.

## BACK-COMPAT
- Additive/default-safe: existing plan→log-run→diagnose→confirm lifecycle + all 353 tests stay green unless they assert the old string-metric behavior (update those to the typed contract with a note). The confirm substance gate (`SUBSTANCE_CONTENT_SECTIONS["experiment"]=("results","diagnosis")`) must still clear — don't move content out of results/diagnosis.

## TESTS
- typed metric parses to {value: float, unit, direction}; bare key=value still works (back-compat).
- a `--artifact /nonexistent` is flagged missing (not silently stored as present); an existing file is verified present.
- log-run with a prior baseline run populates `results.comparison` with a direction-aware delta; diagnose pulls recent N + baseline into context.
- lifecycle + confirm substance gate still green.

## RED LINES
- NEVER touch real `kb/` (tmp_path). Diagnosis judgement = agent; script validates metrics/artifacts/comparisons (litmus: a function that outputs a failure diagnosis from a run with no agent = delete it). Do NOT weaken the confirm/substance gate.
- No git push. Small commits (E1/E2/E3/E4). Managed venv `$PY`. Final: report count (353 + new).
- STOP-and-report if typed-metric back-compat breaks many fixtures, or reading prior runs for comparison is more tangled than the run-log structure supports.

## FINAL REPORT
Per change: files, diff, tests, pass/fail. Confirm: typed metrics, artifact existence checked, comparison field populated, back-compat. What's deferred (E4?). Final suite line + commit hashes.

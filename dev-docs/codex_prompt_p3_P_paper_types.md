# Codex handoff — Track P: per-paper-type element sets (method_system / benchmark / survey)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/paper-analyst/scripts/paper.py`
- `.agents/lib/research/records.py` (only the quick_screen skeleton — add `paper_type`)
- `.agents/lib/research/SCHEMAS.md`
- `.agents/skills/paper-analyst/SKILL.md`
- test files under `.agents/lib/research/tests/`

Do NOT touch confirm.py, journal.py, git_ops.py, kb dispatchers, serve_kb_browser.py (other tracks / not needed).

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `813ae69025a2e419919c4268d18aae5d7d3360db`. If not and clean: `git reset --hard 813ae69`, re-verify.
2. Managed venv runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **331 passed**. Confirm + report.

## DESIGN (SSOT 3.2 per-paper-type decision, locked 2026-07-17)
The five elements (motivation/method/experiment/limitation/insight) are method/system-paper shaped. Benchmark papers have no single method; survey papers have no experiment. Fix: agent classifies paper type at screen time; note scaffold/verify use the element set for that type.

### Current mechanics (verified — do NOT trust, re-check by content)
- `NOTE_ELEMENTS = ("motivation","method","experiment","limitation","insight")` (paper.py ~91) — the flat set.
- `ELEMENT_CLAIM_TYPE` (~95), `ELEMENT_TARGET` (~106, routes element→(payload_section,field,shape)), `ELEMENT_HEADING` (~114).
- `build_note_scaffold` (~398) iterates `NOTE_ELEMENTS`, publishes `required_elements` + `element_claim_types`.
- `verify_note_fill` (~462) loops `for name in NOTE_ELEMENTS` enforcing present+filled+evidence; `_run_complete_note` (~923) rejects on violations.
- `_apply_note_fill_to_payload` (~493) routes via `ELEMENT_TARGET`.
- Screening: `build_screening_scaffold` (~308) / `verify_screening_fill` (~367) / `_run_screen` (~843) produce a worth verdict into `quick_screen`; NO type today.
- `quick_screen` skeleton in records.py (~69-84) — add `paper_type` field here (default "").
- Substance gate `has_substantive_content` (confirm.py) is section-level (`core_content`), decoupled from element keys — so as long as each type's elements land ≥1 field in `core_content`, the gate still clears. DO NOT touch confirm.py; instead ensure element routing keeps a core_content field filled (motivation/insight land in core_content in every set).

## REQUIRED CHANGES

### P1 — screen produces paper_type (agent classification, not heuristic)
- Extend `build_screening_scaffold` so the agent additionally fills `paper_type ∈ {method_system, benchmark, survey}` with evidence (judgement-track, so it flows through the existing evidence/confirm interlock — treat it like the other screening judgements).
- `verify_screening_fill` validates paper_type is one of the allowed values (or empty). On verify, persist it into `quick_screen.paper_type`. Empty/unknown → treat as `method_system` downstream (fallback).
- Add `paper_type: ""` to the quick_screen skeleton in records.py.
- RED LINE (anti-pattern): the SCRIPT must not infer paper_type from keywords/heuristics — it only provides the fillable slot + validates the enum. The classification is the agent's judgement. (Litmus: a function that outputs paper_type from a paper with no agent = delete it.)

### P2 — element sets become per-type
- Replace the flat `NOTE_ELEMENTS` with `ELEMENT_SETS: dict[str, tuple[str,...]]`:
  - `method_system`: motivation, method, experiment, limitation, insight (UNCHANGED — back-compat).
  - `benchmark`: motivation, task_design, metrics, coverage_limitation, insight.
  - `survey`: scope, taxonomy, trends, gaps, insight.
- Make `ELEMENT_CLAIM_TYPE`, `ELEMENT_TARGET`, `ELEMENT_HEADING` per-type too (a dict keyed by paper_type, or per-element entries that cover the union). Route new elements into `core_content` fields (reuse existing core_content keys where sensible: e.g. benchmark task_design→method-ish field, metrics/coverage→changes_and_effects; survey scope→motivation/story, taxonomy/trends/gaps→core_content fields). Ensure at least motivation/scope + insight land in `core_content` so the substance gate clears. Document each element's target. If an existing core_content field doesn't fit, you MAY add a new core_content field to the paper skeleton (records.py) — but keep it additive/default-safe.
- Provide a selector `elements_for(record_or_type) -> tuple` that reads `quick_screen.paper_type` (default method_system).

### P3 — build/verify use the selected set
- `build_note_scaffold`: iterate `elements_for(record)`, publish that set as `required_elements`/`element_claim_types`.
- `verify_note_fill`: loop over `elements_for(record)`; "all required present" is per that set. Keep the verbatim-evidence + validate_claims checks per element.
- `_apply_note_fill_to_payload` + `render_note_md` + `_run_complete_note`: use the same per-type set/routing.
- BACK-COMPAT: a paper with no `paper_type` → method_system → identical to today. All existing five-element tests must stay green unmodified.

### P4 — docs
- SKILL.md (~43-45): replace the manual "benchmark/survey 停下问用户" warning with the per-type behavior; document the 3 sets.
- SCHEMAS.md: add the paper_type field + element-set schema entry (none exists today).

## TESTS
- screen fills+verifies paper_type (valid enum persists; invalid rejected).
- A `benchmark` paper: scaffold emits the benchmark 5 elements (not method/experiment); verify passes when those are filled; a method_system-shaped fill is rejected/mismatched.
- A `survey` paper likewise.
- A paper with no paper_type → method_system five-element behavior unchanged (regression).
- Substance gate still clears for each type (at least one core_content field filled).

## RED LINES
- NEVER touch real `kb/` (tmp_path only). Type = agent judgement; script only selects structure + validates.
- Additive/default-safe: existing papers + tests unaffected. Do NOT weaken the evidence/substance/confirm gates.
- No git push. Small commits (P1/P2/P3/P4). Managed venv `$PY`. Final: report count (331 + new).
- STOP-and-report if routing a new element into core_content vs critique makes the substance gate ambiguous, or the per-type refactor is larger than expected.

## FINAL REPORT
Per change: files, diff summary, tests, pass/fail. Confirm back-compat (no paper_type → five elements). Final suite line + commit hashes.

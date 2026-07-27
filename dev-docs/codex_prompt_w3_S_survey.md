# Codex handoff — Wave3 Track S: literature-synthesizer evidence-first survey

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/literature-synthesizer/scripts/synthesize.py`
- `.agents/skills/literature-synthesizer/SKILL.md`
- test files under `.agents/lib/research/tests/`

Do NOT touch report.py, idea.py, experiment.py, method.py, or any other skill (parallel tracks). You MAY import from `research.evidence` and `research.common`/`research.core` (stable libs) — do not modify them.
- Do NOT edit `.agents/lib/research/SCHEMAS.md` (shared file; the maintainer adds schema docs post-merge to avoid 4-way conflicts). Document your schema in your SKILL.md instead.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `3c5bedc...` (run `git rev-parse HEAD`; if it doesn't start with 3c5bedc and tree is clean, `git reset --hard 3c5bedc`, re-verify).
2. Managed venv runner:
   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```
   Baseline = **353 passed**. Confirm + report.

## DESIGN (SSOT 3.6, locked; the "understanding comes from agent" pattern = original 原则1)
Today synthesize.py is one-shot metadata histograms + hard-coded prose (`build_survey_payload` lines 71-115: `top_counts` Counter over topics/tags/pools + fixed Observed/Inferred/Suggested/OpenQuestions strings + `confidence=0.68`; `select_records` 28-60 reads only metadata; NO evidence layer; NO prepare/verify). Redesign to evidence-first, mirroring paper.py's prepare/verify.

Locked design (SSOT 3.6):
- **Standard survey skeleton**: ① scope & positioning ② background/terms ③ **taxonomy (core)** ④ cross-cutting (datasets/benchmarks/metrics) ⑤ trends (timeline A→B→C) ⑥ gaps/controversies/open-challenges ⑦ conclusion.
- **evidence-first hard constraint**: every taxonomy cell / trend / gap MUST carry `evidence_refs` (research.evidence schema); distinguish **observed (has evidence) vs inferred (AI judgement)**; produce a **comparison matrix** (method × dimension), not a list.
- **time/stale**: survey header records the KB anchor (unit id set + timestamp / `as_of`); trends/gaps carry `as_of`.

## REQUIRED CHANGES (mirror paper.py verbs `screen`/`complete-note`; import `research.evidence`)
### S1 — prepare verb
- Add a `survey prepare --field/--query [filters]` that: selects the relevant units (keep the existing metadata filter, but the scaffold is what matters), and writes a **fillable survey scaffold** YAML with the 7-section skeleton, a taxonomy grid frame, a comparison-matrix frame, and a KB-anchor header (selected unit ids + timestamp passed IN, since scripts can't call Date.now — accept an `--as-of` arg or read from an existing util). Each fillable cell/trend/gap has empty `content` + empty `evidence_refs` + a `claim_type` (observed→fact/evaluation, inferred→inference). The script authors NO understanding — it only builds the structure + publishes the required-cell contract.
### S2 — verify verb
- Add `survey verify` that: reads the agent-filled scaffold, runs `validate_claims` on the claims and `verify_claim_evidence(claim, unit_dir)` for every evidence_ref (verbatim check against the cited unit's artifacts), and only persists the survey (to `kb/synthesis/<slug>/survey.yaml` + `summary.md`) when all cells with an observed/evidence claim verify. Reject with clear violations (like paper.py's verify) otherwise.
- Mark each cell/trend/gap `observed` vs `inferred` in the output; render the comparison matrix.
### S3 — kill the hard-coded prose
- Remove the fixed Observed/Inferred/Suggested/OpenQuestions constant strings and `confidence=0.68`. Those judgements now come from the agent (filled + evidence-verified). Keep the metadata histograms ONLY as an optional descriptive appendix (clearly labelled "index-level counts", not as the survey's conclusions), or drop them.
### S4 — docs
- SKILL.md: rewrite to the prepare/verify + evidence-first flow. Document the survey scaffold schema (sections, cell shape with evidence_refs, observed/inferred, KB anchor) in SKILL.md.

## BACK-COMPAT / SCOPE
- The three modes (survey/review/taxonomy) currently share one code path. You may keep taxonomy as a view of the same scaffold. Keep output under `kb/synthesis/<slug>/`.
- Do NOT invent a semantic index (SSOT 3.5: agent uses native retrieval). The agent pulls evidence; the script verifies it.

## TESTS
- prepare emits the 7-section scaffold + empty evidence_refs per cell (no hard-coded conclusions).
- verify PASSES a synthetic filled survey whose evidence quotes are verbatim in the cited units; REJECTS one with a fabricated quote (verify_claim_evidence catches it).
- observed vs inferred is recorded; comparison matrix present.

## RED LINES
- NEVER touch real `kb/` (tmp_path). Understanding = agent; script only scaffolds + verifies evidence (anti-pattern litmus: a function that outputs survey conclusions from units with no agent = delete it).
- No git push. Small commits (S1/S2/S3/S4). Managed venv `$PY`. Final: report count (353 + new).
- STOP-and-report if the evidence-verification for a multi-unit survey cell is ambiguous (a survey cell may cite several units — verify each evidence_ref against ITS own cited unit_dir; if the unit-dir resolution for a cross-unit claim is unclear, report rather than guess).

## FINAL REPORT
Per change: files, diff summary, tests, pass/fail. Confirm no hard-coded conclusions remain; evidence verified at verify. Final suite line + commit hashes.

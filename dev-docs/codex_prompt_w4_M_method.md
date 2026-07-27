# Codex handoff — Wave4 Track M: method-designer (read resources + program corpus + evidence-first)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/method-designer/scripts/method.py`
- `.agents/skills/method-designer/SKILL.md`
- test files under `.agents/lib/research/tests/`

Do NOT touch config.py, synthesize/report/idea/experiment scripts, records.py, confirm.py, or SCHEMAS.md (shared — document schema in SKILL.md; maintainer folds it in later). You MAY READ `.agents/skills/research-config-manager/scripts/config.py` (to learn the resources path) and stable libs, but do not modify them.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be `4fd5112...` (else clean → `git reset --hard 4fd5112`, re-verify).
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → baseline **375 passed**. Confirm + report.

## DESIGN (SSOT 3.8 + 3.14, locked)
Today method.py `design` writes a **hardcoded 4-row experiment matrix** (rows fixed regardless of resources), `repo_candidates` (48-119) ranks ALL repos via token overlap (ignores the program's corpus), `resource_constraints` is set to `[]` and never read, and nothing reads the user profile. Locked design:
- **Read profile `resources`** and **scale the experiment matrix** (seed count / model size / parallelism) accordingly; **flag unrealistic rows** (red). If a plan has a **reasonable extra-resource need**, surface it ("this needs X GPUs, worth requesting").
- (3.14) `resources` is the first-batch downstream wiring: profile.resources → method.
- Keep the "understanding comes from agent" boundary (原则1): the script assembles the run-grid/config **skeleton** scaled by resources; the agent fills the method substance. Evidence-first where a judgement is made.

### Verified current mechanics (re-check by content)
- `resources` lives in `kb/config/user-profile.yaml` under `resources: {}` (written by config.py `capture-resources` / `profile_path` at config.py:41). method.py never opens it.
- method reads `state.yaml` (has `active_unit_ids`) but `repo_candidates` uses `iter_records(root, kind="repo")` (method.py:49) over ALL repos — NOT the program corpus.
- Hardcoded matrix literal at method.py ~255-300 (4 rows baseline/main/ablation/diagnostic); `resource_constraints` default `[]` at ~318.

## REQUIRED CHANGES
### M1 — read resources, scale the matrix, flag unrealistic
- Load `kb/config/user-profile.yaml`'s `resources` (mirror config.py's `profile_path`; read-only). Populate `state["resource_constraints"]` from it (instead of `[]`).
- Scale the experiment matrix by the resources: e.g. seed count / model-size tier / parallelism per row derived from the declared resources rather than fixed. When a row's requirement exceeds the declared resources, **mark it unrealistic/red** with the reason. Keep the matrix structure but make its scale + feasibility flags resource-driven, not literal.
- When a plan has a reasonable extra-resource need, emit an explicit "resource request" note (natural language, for the user).
### M2 — program-scoped corpus
- `repo_candidates` (and any unit selection) should prefer the **program's `active_unit_ids`** (from state.yaml) as the corpus, not all-KB. Fall back to KB-wide only when the program has no attached repos, and say so. This makes method design use the program's actual selected repos.
### M3 — evidence-first where it's a judgement
- Where method.py currently emits a JUDGEMENT as a fixed string (e.g. baseline choice rationale, feasibility verdict), convert to the prepare/verify + agent-fills-with-evidence pattern IF clean (like paper.py). If the design artifacts are mostly structural skeletons the agent fills (not script judgements), a lighter touch is fine — the key litmus: no function should output a method judgement from an idea with no agent. Scale/feasibility flags computed from declared resources are fine (that's deterministic arithmetic, not understanding).
### M4 — docs
- SKILL.md: document resource-scaled matrix + program-corpus + evidence boundary + the resources schema shape (here, not SCHEMAS.md).

## BACK-COMPAT
- Additive/default-safe: a program with no declared resources / no active_unit_ids must still produce a sensible matrix (fall back to today's defaults) so all 375 tests stay green. Output paths unchanged (`kb/programs/<id>/design/...`).

## TESTS
- with declared resources (e.g. small GPU budget), the matrix scales down + flags an over-budget row unrealistic; with generous resources, it scales up. No-resources → default matrix (back-compat).
- `resource_constraints` in state.yaml is populated from the profile (not `[]`).
- repo selection prefers the program's active_unit_ids; falls back to KB-wide with a note when empty.
- no method judgement is emitted from an idea with no agent (litmus).

## RED LINES
- NEVER touch real `kb/` (tmp_path). Understanding = agent; script scales structure by resources + verifies. Do NOT modify config.py (read-only). Do NOT touch other tracks' files or SCHEMAS.md.
- No git push. Small commits (M1/M2/M3/M4). Managed venv `$PY`. Final: report count (375 + new).
- STOP-and-report if resource→matrix scaling is under-specified for the declared-resources shape (resources is free-form natural language per config.py — you may need a light structured read; if it's too freeform to scale deterministically, do the resource_constraints population + unrealistic-flag hook + report the scaling heuristic rather than over-engineering).

## FINAL REPORT
Per change: files, diff, tests, pass/fail. Confirm resources read + matrix scaled + program corpus used + back-compat. What's deferred. Final suite line + commit hashes.

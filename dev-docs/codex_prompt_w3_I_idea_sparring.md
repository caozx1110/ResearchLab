# Codex handoff — Wave3 Track I: idea-workbench 陪练 (sparring) mode + evidence-first analysis

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/idea-workbench/scripts/idea.py`
- `.agents/skills/idea-workbench/SKILL.md`
- test files under `.agents/lib/research/tests/`

Do NOT touch synthesize.py, report.py, experiment.py, method.py, discussion-archivist (parallel/other). May import stable libs (research.evidence / common / core).
- Do NOT edit `.agents/lib/research/SCHEMAS.md` (shared file; the maintainer adds schema docs post-merge to avoid 4-way conflicts). Document your schema in your SKILL.md instead.

## STEP 0 — base sync
1. `git rev-parse HEAD` starts `3c5bedc`; else clean → `git reset --hard 3c5bedc`.
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → **353 passed**. Confirm.

## DESIGN (SSOT 3.7, locked)
Today idea.py judgements are count-and-threshold heuristics over metadata (`review_payload` 54-89: novelty/feasibility/evidence scores from field counts + fixed thresholds; `generated_variants` 173-187: 4 hard-coded STRATEGY string permutations; NO evidence layer; NO discussion mode; discussion-archivist only archives). Locked design:
- **陪练 (sparring) = a MODE inside idea-workbench** (not a new skill). Identity = **domain expert / reviewer**: challenge, probe, pull counter-examples from the KB, trace the argument chain — AND give constructive suggestions (not only naysaying).
- Persistence granularity = **per conclusion** (each discussion conclusion is persisted, evidence-backed).
- Uses the **evidence-pack** approach (SSOT 原则4 + 3.5): a question → agent selects relevant units via native retrieval → pulls evidence spans → discusses with evidence. Retrieval is the agent's native ability; the SCRIPT verifies the evidence (research.evidence), it does NOT build a semantic index.

## REQUIRED CHANGES
### I1 — 陪练 discussion mode (the core new feature)
- Add a `discuss` verb (or `spar`) on an idea: `idea discuss --id <idea> --phase prepare|verify` mirroring paper.py's prepare/verify.
  - **prepare**: emit a fillable discussion scaffold for a conclusion — fields for the reviewer's challenge/probe/counter-example/constructive-suggestion, each a judgement claim with empty `evidence_refs`. The script supplies the idea context + an evidence-ref format hint; it authors NO argument.
  - **verify**: the agent has filled the conclusion + attached evidence claims (counter-examples cited from KB units); script runs `validate_claims` + `verify_claim_evidence` against the cited units and persists the conclusion (per-conclusion granularity) only when evidence verifies. A counter-example that cites a KB unit must verify verbatim against that unit.
- Persist each verified conclusion into the idea record (e.g. `payload.discussion.conclusions[]` — add to the idea schema) with its evidence + who/when.
### I2 — evidence-first analysis (replace the heuristic scores)
- `analyze`/`review`: the novelty/feasibility/recommendation judgements must become **agent-produced with evidence**, not count-and-threshold. Convert to prepare/verify: prepare emits the fillable analysis (novelty vs prior work, feasibility, killer questions) as judgement claims with evidence_refs; verify checks evidence + persists. Remove the `review_payload` count-threshold scoring as the source of truth (you may keep a rough count as a descriptive hint only, clearly not the verdict).
- Keep `capture`/`select`/`archive`/`select-best` working; `select` still records selection (workflow-state, stays pending_user_confirmation — do NOT flip to confirmed) with provenance as today.
### I3 — docs
- SKILL.md: add the 陪练 mode + evidence-first analysis + the discussion.conclusions schema (document it here, not in SCHEMAS.md).

## BACK-COMPAT / SCOPE
- This is large. PRIORITIZE I1 (陪练 mode — the SSOT headline) and get it solid. I2 (evidence-first analysis) second. If I2 cascades into many existing tests or the heuristic is deeply wired, do I1 cleanly + convert analyze/review minimally and STOP-and-report the rest. A solid 陪练 mode + report beats a half-broken everything.
- Existing subcommands must keep working (or their tests updated to the new evidence-first contract with a clear note).

## TESTS
- `idea discuss --phase prepare` emits a fillable conclusion scaffold (no authored argument).
- `discuss --phase verify` PASSES a synthetic conclusion whose counter-example quote is verbatim in the cited unit; REJECTS a fabricated counter-example quote.
- A verified conclusion persists per-conclusion into the idea record with evidence.
- select still records selection as pending (not confirmed).

## RED LINES
- NEVER touch real `kb/` (tmp_path). Understanding/arguments = agent; script scaffolds + verifies evidence (litmus: a function that outputs a novelty verdict or a counter-example from an idea with no agent = delete it). Do NOT build a semantic index.
- No git push. Small commits (I1a/I1b/I2/I3). Managed venv `$PY`. Final: report count (353 + new).
- STOP-and-report generously if scope balloons — I1 solid + honest report is the win.

## FINAL REPORT
Per change: files, diff, tests, pass/fail. What's done vs deferred (esp. I2). Confirm evidence verified at verify; select stays pending. Final suite line + commit hashes.

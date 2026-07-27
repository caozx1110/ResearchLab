# Codex handoff — Bundle B2: decoupling + skill validator + docs reposition + CI (base = post-B1 merge)

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/research-navigator/assets/ui/kb.js` (decouple hardcoded slug)
- `.agents/lib/research/evidence.py` (docstring temp/ scrub — DOCSTRING ONLY, do not touch logic)
- `.agents/skills/skill-evolution-advisor/SKILL.md` (scrub dev-evaluator/temp ref)
- `README.md`, `docs/INSTALL.md`, `docs/USER_GUIDE.md` (reposition as workspace bundle + scrub temp/)
- a NEW skill validator: `.agents/lib/research/skill_validator.py` (or extend existing test) + `.agents/lib/research/tests/test_skill_metadata.py`
- any skill `SKILL.md` / `agents/openai.yaml` that FAILS the validator (metadata fixes only)
- `.github/workflows/ci.yml` (add validator step) — COORDINATE: B1 may also touch ci.yml; you are on the post-B1 base so just add your step.

Do NOT touch: install.sh, install-lib/ws_sync.py (B1, already merged — leave as-is), any skill's runtime scripts/logic (only metadata files), confirmation/evidence LOGIC. Do NOT touch real `kb/`.

## STEP 0 — base sync
1. `git rev-parse HEAD` MUST be the post-B1 merge commit `15b826af51270c97f2c8e8364576f6f5e9faaa35` (I will fill this in; if it's not that, STOP and report). Baseline suite = `404 passed` (I will fill in). Run `PY=/Users/czx/.../tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` and confirm.
2. Read `AGENTS.md` first.

## GOAL (SSOT 3.16, REQ5/6/7 + REQ8 validator/CI): scrub KB coupling, fix skill metadata, reposition public docs, add validator + CI.

## REQUIRED CHANGES

### R5 — decouple knowledge-base specifics
- `kb.js:1083` currently: `return title.replace(/humanoid[-_ ]vla[-_ ]wholebody[-_ ]control/gi, "").trim() || basename(path)` — a hardcoded project slug strip. Remove the project-specific regex; use a generic title/basename (do NOT special-case any particular program). Verify the Navigator UI still renders titles sensibly.
- Confirm no other hardcoded dataset names / real program ids / personal absolute paths / maintainer signer remain in SHIPPING code (`.agents/**` minus tests). (`czx` appears only in `.agents/lib/research/tests/` which the B1 allowlist already excludes from shipping — leave tests as-is.)

### R7 — public docs reposition + temp/ scrub
- Reposition the product in README + docs as a **workspace skill bundle**: install target is the **workspace root** (where `.agents/` + `kb/` live), NOT the `kb/` directory. Recommend project-scope copy install; do not recommend system/symlink install.
- Remove ALL references to private `temp/*` from PUBLIC surfaces:
  - `README.md:111`: drop the `详见 temp/SYSTEM_DESIGN_SSOT.md ... temp/BACKLOG.md` pointer (temp/ is gitignored, absent in a clone). Replace with a neutral statement or point to `.agents/lib/research/SCHEMAS.md` (which ships) / docs that exist in the clone.
  - `.agents/lib/research/evidence.py:13` docstring: the `temp/SYSTEM_DESIGN_SSOT.md` reference → point to `SCHEMAS.md` (ships) or drop; DOCSTRING ONLY.
  - `.agents/skills/skill-evolution-advisor/SKILL.md`: this section documents the dev-only `eval_research_value.py` (which B1's allowlist EXCLUDES from user installs) + references `temp/RESEARCH_VALUE_EVAL_DESIGN.md`. Since that evaluator is dev-only and won't ship, REMOVE/scrub this section from the user-facing SKILL.md (or clearly mark it dev-only and drop the temp/ ref). Do not leave a user pointing at a script/doc that isn't in their install.
- Grep the whole shipping tree (`.agents/**` minus tests) + README + docs for remaining `temp/` refs; scrub each in public/shipping surfaces.

### R6 — skill quick-validator + metadata fixes
- Add `.agents/lib/research/skill_validator.py`: a quick validator that for each `.agents/skills/*`:
  - SKILL.md has valid frontmatter (`name`, `description`); `name` matches the dir.
  - `agents/openai.yaml` parses + has the required `interface` fields (`display_name`, `short_description`, `default_prompt`) with valid types.
  - `short_description` length within limit (pick a sane cap, e.g. ≤ the platform limit; **blog-analyst's description is 274 chars — an outlier to fix**). Document the cap.
  - Public scripts referenced by the SKILL.md are discoverable (the script paths a SKILL.md mentions exist).
- Add `test_skill_metadata.py` running the validator over all 17 skills → must PASS.
- Fix every skill that fails: trim over-long descriptions (esp. blog-analyst), fix any invalid openai.yaml field, ensure script discoverability. Metadata only — do NOT change skill behavior.

### R8b — CI
- Extend `.github/workflows/ci.yml` to run the skill validator (and keep the existing compileall+pytest). Ensure the new metadata + (B1's) install tests run in CI.

## RED LINES
- NEVER touch real `kb/`. NEVER `git push`. Do NOT change confirmation/evidence LOGIC or any skill's runtime behavior — metadata/docs/decouple only. Do NOT touch install.sh/ws_sync.py (B1 owns, merged).
- Small commits (R5/R7/R6/R8b). Managed venv `$PY`. Final: report count.
- STOP-and-report if the openai.yaml short_description limit is unclear (state the value you chose + why) or if fixing a description would change meaning materially.

## FINAL REPORT
Per requirement: files, diff, tests, pass/fail. Confirm: Navigator slug decoupled, no temp/ in public/shipping surfaces, validator passes all 17 skills (blog-analyst fixed), CI runs validator. Final suite line + commit hashes.

# Codex handoff — Wave3 Track R: report-author self-contained reports + outline verb

Model: gpt-5.6-sol, xhigh, full access. Owns ONLY:
- `.agents/skills/report-author/scripts/report.py`
- `.agents/skills/report-author/SKILL.md`
- test files under `.agents/lib/research/tests/`

Do NOT touch synthesize.py, idea.py, experiment.py, method.py (parallel tracks). May import stable libs (research.evidence / common / core) — do not modify them.
- Do NOT edit `.agents/lib/research/SCHEMAS.md` (shared file; the maintainer adds schema docs post-merge to avoid 4-way conflicts). Document your schema in your SKILL.md instead.

## STEP 0 — base sync
1. `git rev-parse HEAD` must start `3c5bedc`; if not and clean, `git reset --hard 3c5bedc`.
2. `PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3; $PY -m pytest .agents/lib/research/tests -q` → baseline **353 passed**. Confirm + report.

## DESIGN (SSOT 3.10, locked)
Today report.py is a literal event-log dump (`render_lines` 62-104 / `render_event_line` 51-59 over `reporting-events.yaml`; 4 verbs weekly/ppt-materials/stage-summary/writing-materials; NO outline verb; NO evidence/claim reading). Locked design:
- Reports are **self-contained**: assembled from the **claims + events + evidence** triple, not just an event dump.
- **Add an `outline` verb** (paper-outline owner lives in report-author, NOT a new skill).
- **Explicitly mark missing inputs** — when an event/evidence/decision is absent, list "missing X"; NEVER fabricate/hallucinate.

## REQUIRED CHANGES
### R1 — self-contained assembly (claims+events+evidence)
- Extend the report renderers so a report pulls not only `reporting-events.yaml` but also the program's **confirmed claims + their evidence** (from the units attached to the program / referenced by events). Use `research.evidence` (read_claims/validate structure) to surface claim+evidence, not just event lines. The `writing-materials` verb especially should show real "Writing Claims & Evidence" (today its header is a lie — same dump). A report should be understandable standalone (a reader sees what was claimed, the evidence, the events, the decisions).
- Keep the agent responsible for narrative/synthesis (script aggregates + verifies structure; agent composes) — but the aggregation must include claims+evidence, not only events.
### R2 — outline verb
- Add `outline --program-id ...` (paper outline): assemble related-work claims + evidence + events into a section skeleton (intro / related work / method / experiments / ... as a fillable outline), pulling confirmed claims/evidence for the related-work section. Agent fills the narrative; script provides the evidence-backed skeleton. Register the verb + document it in SKILL.md.
### R3 — explicit missing markers
- Wherever an input is absent (no events, no confirmed claims, no decisions, missing evidence for a section), the output must list an explicit `missing: X` line — never silently omit or invent. Replace the single fixed "暂无 reporting-events" fallback with structured missing-input reporting across all sections.
### R4 — principle 8 + docs
- User-facing output: natural language, no raw commands (the report is a document; any "next step" is prose or `kb <verb>`). SKILL.md updated for the new assembly + outline verb.

## OPTIONAL (only if clean, else skip + note)
- SSOT 3.14 lists `reporting_style` as first-batch downstream wiring. If the user-profile `reporting_style` is trivially readable, honor it (concise vs detailed). If it adds meaningful complexity, SKIP and note it as a follow-up — do not let it balloon this track.

## TESTS
- weekly/stage report includes confirmed claims + evidence, not just events (seed a program with an attached unit that has confirmed claims + a reporting event; assert both appear).
- `outline` produces an evidence-backed section skeleton with related-work claims.
- Missing inputs are explicitly marked `missing: ...` (seed a program with no confirmed claims → report says missing, does not invent).
- No raw commands in output (grep stdout).

## RED LINES
- NEVER touch real `kb/` (tmp_path). Never fabricate — missing = marked missing. Script aggregates+verifies; agent narrates.
- No git push. Small commits (R1/R2/R3/R4). Managed venv `$PY`. Final: report count (353 + new).
- STOP-and-report if resolving "the program's confirmed claims + evidence" from events/attached units is more tangled than expected (e.g. events don't carry unit ids) — report the actual linkage rather than guessing a join.

## FINAL REPORT
Per change: files, diff, tests, pass/fail. Confirm reports now include claims+evidence, outline verb exists, missing inputs marked. Final suite line + commit hashes.

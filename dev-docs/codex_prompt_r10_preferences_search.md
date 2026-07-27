# R10 preference binding — intake/search/synthesis

## STEP 0 — base sync

Create an isolated worktree/branch from exact integration HEAD `e3c9ec4`. Verify that `16bfcda` and `e3c9ec4` exist before editing. Stop and report if the base differs; do not reset or modify the main worktree.

## Objective

Close every task-context replay gap in the three real consumers below. Rules only bound disclosure; runtime Agent selects relevant preferences. A receipt must become stale whenever any owner-consumed semantic/scope input changes.

## File ownership

Only edit:

- `.agents/skills/source-intake/scripts/intake.py`
- `.agents/skills/literature-search/scripts/search.py`
- `.agents/skills/literature-synthesizer/scripts/synthesize.py`
- their directly corresponding tests: `test_literature_search.py`, `test_survey_judgement_lifecycle.py`, `test_intake_commands.py`, `test_dual_source.py` as needed
- `.agents/lib/research/SCHEMAS.md` only if the persisted contract changes

Do not edit central preference registry, method/experiment/report/paper/orchestrator/prefs/version/docs.

## Required contracts

1. `source-intake:add`: bind kind/source/title/maturity/stage/candidate plus canonical pools and a value-free digest of current `user_authorization + authorization_source`. Never persist raw authorization/path in a preference receipt. Duplicate paths that do not consume preferences may remain neutral.
2. `literature-search:search`: bind effective frozen budget (with defaults), review_protocol, reviewers and monitor_binding, in addition to existing stage/request/mode/run/scope. Initial stage and resume with omitted-but-frozen fields must recompute the same context from canonical persisted state. Changing any one field must make an old receipt stale before canonical write.
3. `literature-synthesizer:synthesize`: bind discovery_mode, frozen search protocol content (digest, not path), selection filters/as_of/program ids, and the exact current confirmed input-unit snapshot/bindings actually selected by prepare. Reorder prepare so all reads/validation happen before preference resolution and before writes. `kb_only`↔external/systematic, protocol bytes, added/removed/changed/current-confirmation unit must stale the old receipt. Evidence-gap composite must receive the same validated binding.

## Tests

Add table-driven mutation tests: mutate each consumed field independently and prove context digest changes / old receipt is rejected. Include resume omission preserving frozen search context and one current unit changing for synthesis. Tests must fail on old code, use temp roots only, and prove no canonical write on rejection.

## Red lines

- No semantic research judgement in scripts.
- No real `kb/`, no push, no raw command/path leakage, no TTY.
- Do not weaken hard constraints/governance or store secret-bearing raw task values in receipts.
- Small commits, `git diff --check`, targeted tests and py_compile. STOP-and-report on ambiguity.


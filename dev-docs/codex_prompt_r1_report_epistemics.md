# R1 diagnosis/report epistemic isolation

## STEP 0

Verify worktree HEAD is `3fa9a51c8d75b02bc978a5e68a6bf3e76ffcdc27`. Read root AGENTS and SSOT. Do not touch real `kb/`.

## Ownership

- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `.agents/skills/report-author/scripts/report.py`
- `.agents/lib/research/tests/test_experiment_validator.py`
- report/experiment-specific tests or one new narrow R1 test
- `.agents/lib/research/common.py` only if a backward-compatible reporting-event schema helper is strictly necessary

Do not edit canonical confirmation/evidence validators; consume them, never weaken them.

## Reproduced failure

`/private/tmp/r1_diagnosis_report_probe.py <repo>` plans an experiment, writes an evidence-free pending diagnosis summary `The failure was caused by dataset corruption.`, then generates weekly report. The report places that sentence in the ordinary progress event line without pending/unverified labeling.

## Required

1. Diagnosis reporting events carry explicit epistemic type and confirmation binding/status sufficient for report consumers to distinguish judgement from fact. Existing fact events remain compatible.
2. Report rendering must never place a pending/unverified diagnosis/evaluation/inference in ordinary confirmed progress. Put it in an explicit `Pending / Unverified judgements` section with unmistakable label and missing-evidence/confirmation status, or exclude it while reporting the missing input. Confirmed judgement consumption requires a current canonical receipt, not a string status alone.
3. Reports built from legacy judgement-like experiment-diagnosis events fail safe into the pending section.
4. Add black-box regression from diagnosis through weekly report, confirmed-receipt case if supported, and ensure fact run events remain in normal progress. Do not fabricate confirmation or auto-confirm diagnosis.
5. Rerun root probe: sentence may appear only inside explicitly pending/unverified context, never the ordinary event section.

No push. Small commits; targeted + full suite, diff-check, clean status. STOP if the shared receipt API is insufficient.

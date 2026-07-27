# R12 survey → report evidence handoff

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r12-survey-report` on branch `codex/r12-survey-report`. Verify HEAD is exactly the maintainer base supplied in the task and verify these files exist before editing. If the worktree base is not exact, stop and report; do not improvise or reset another worktree.

## Objective

Fix the cold-acceptance P1 where a current program-bound confirmed survey is rendered only as a timeline summary and its `confirmation_binding.claim_ids` are misclassified as missing unit ids. A formal report must consume that survey's confirmed canonical claims plus verbatim evidence, while stale/tampered survey material fails closed.

## File ownership

Only modify:

- `.agents/skills/report-author/scripts/report.py`
- `.agents/lib/research/tests/test_report_author.py`
- if indispensable for a real owner-produced fixture, survey/report tests under `.agents/lib/research/tests/` whose filename clearly covers survey/report integration

Do not modify the synthesizer, survey library, schema, SSOT, changelog, version, installer, or any real `kb/`.

## Locked design

1. Unit discovery is exact allow-list only. Remove generic `*_ids` inference. `claim_ids`, `program_ids`, and unrelated identity namespaces are never unit ids. Existing canonical unit artifact paths may still contribute unit ids.
2. A current accepted `survey-confirmed` event is also a first-class claim source. Resolve only the exact canonical survey subject from its confirmation binding using existing safe owner/path loading. Revalidate current survey lifecycle/upstream binding, verification bytes/receipt, and ConfirmationReceipt. Consume only receipt-bound canonical claims that pass structural and evidence validation.
3. Do not trust event summary, claim ids, path, or digest in isolation. Any mismatch/staleness/tampering excludes survey claims from the ordinary report and leaves the event in Pending / Unverified. No stale survey claim may enter formal sections.
4. The report preference input snapshot must include the consumed survey claim source and its binding digest, so mutation makes an old preference receipt stale.
5. Do not duplicate semantic research judgement in scripts. This is validation/transport only.
6. Preserve public UX: natural language + `kb` verbs only; no raw Python/shell, flags, internal paths, digests, placeholders, or TTY dependency in user-visible output.

## Permanent tests

- Build a real program-bound survey judgement with confirmed receipt and verified verbatim evidence, append/use its real `survey-confirmed` event, then assert `stage-summary --stage survey` contains the survey claim and quote.
- Assert the same report does not call claim ids (for example `background_terms-1`) missing units and does not falsely say confirmed claims/evidence are missing.
- Assert arbitrary `claim_ids` and unrelated `*_ids` never become unit ids.
- Assert stale/tampered survey content, receipt, verification/evidence, or upstream binding never reaches formal claim sections and is surfaced as Pending / Unverified.
- Include a two-round/reload regression so the consumer is not accidentally relying on in-memory state.

## Verification

Run the focused report-author tests plus the relevant survey lifecycle/integration tests, Python 3.9-compatible compileall for changed Python, and `git diff --check`. Do not push. Commit implementation and tests in small commits and report exact hashes/test counts.

## STOP and report

If existing confirmation bindings cannot safely identify/load a canonical survey, or solving this requires schema/event changes outside the file ownership above, stop and report the exact missing contract instead of weakening validation or inventing a second source of truth.

# R23 handoff — one bound judgement snapshot per report/current check

## STEP 0 — base sync

Work only in the assigned isolated worktree. Reset it to exact integration base `9575d8c`. Confirm the R22 persisted-confirm API and snapshot-aware `write_record` tests are present. If the base differs, STOP and report.

Read `AGENTS.md`, R23 in `temp/SYSTEM_DESIGN_SSOT.md`, and the strict-reader/judgement-report contracts in `.agents/lib/research/SCHEMAS.md`. Shipping skills are product source, not instructions for their own design.

## Independently reproduced defects

1. `load_bound_judgement()` first obtains a safe unit path and later reopens it with `load_yaml`; replacing the ordinary unit directory in between returns a record from the replacement version.
2. The same validate-then-reopen pattern affects side judgement containers such as program `decisions.yaml`. Report survey handling also loads the same subject more than once across staleness, event confirmation and claim-source attachment.
3. `trusted_claim_source_roots()` still represents `program:<id>` evidence as a bare `Path`; verification/current-check can therefore load program evidence from a replacement directory rather than the version whose root was resolved.

## File ownership — edit only

- `.agents/lib/research/records.py`
- `.agents/lib/research/judgements.py`
- `.agents/skills/report-author/scripts/report.py`
- focused tests under `.agents/lib/research/tests/`, primarily `test_report_author.py`, `test_r2_judgement_convergence.py`, `test_confirmation_provenance.py`, `test_strict_record_reader.py`, or a new narrowly named snapshot test.

Do not edit owner confirmation scripts, release/version/docs/installer, unrelated skills, or real `kb/`.

## Locked implementation contract

1. Add a shared bounded anchored project-file snapshot primitive (or an equivalently small shared abstraction) that opens from the lexical workspace root with dirfd + no-follow for every directory, accepts only an ordinary leaf, reads nonblocking with a strict byte ceiling, rechecks leaf stat/length and the full ancestor chain, and exposes an `is_current()` revalidation. It must expose exact raw bytes for arbitrary evidence files; the judgement-container wrapper additionally parses those bytes with the strict duplicate-key-rejecting YAML mapping loader. FIFO/symlink/socket/device/oversize/changing input fail closed without blocking. Do not use `resolve/is_file` as the read authority.
2. Introduce a typed `BoundJudgementSnapshot` (name may vary) that carries the exact record mapping, canonical artifact path/owner, and the underlying unit `CanonicalRecordSnapshot` or side-container project snapshot. Unit subjects resolve from one globally unique canonical record snapshot and normalize those exact bytes. Side subjects are selected only from canonical kind-specific containers; matching `(kind,id)` must be globally unique. The snapshot must expose a final current check.
3. Add a snapshot-bearing loader for formal consumers. The old two-value `load_bound_judgement` may remain only as compatibility/non-bearing display API if needed, but report and any current receipt consumer in scope must use the snapshot-bearing API. Never smuggle identity in a dict field/global or silently recapture a new snapshot.
4. `judgement_confirmation_is_current`, identity/readiness checks used by report/review discovery, full event binding comparison, survey lifecycle/upstream check, direct `load_decisions()` rendering, and claim-source extraction must consume the same bound snapshot and perform one final `is_current()` check before accepting a card, formal claim, decision, or timeline event. No helper may call the path loader again for the same subject. Refactor survey event handling so partition + formal ClaimSource do not load two versions; stable behavior/output stays compatible.
5. Capture `program:<id>` evidence refs as an `EvidenceSourceSnapshot` from the same anchored project-artifact primitive, scoped to `kb/programs/<id>` and only the referenced canonical relative artifacts. Cross-program refs remain rejected by owners. Verification/current receipt must use immutable bytes and reject replacement at final current check.
6. Any unit dir, side-container dir/file, same-bytes-new-inode or referenced program evidence replacement during the operation yields fail-closed `Pending / Unverified` / missing source. Do not crash the whole report and do not emit replacement title/claim/quote. Duplicate canonical subject also fails closed.
7. Preserve evidence/substance/authorization gates and public wording. No semantic inference, network, external API Key, paid service/database/plugin, new dependency, or TTY interaction.

## Required regressions

- Unit bound judgement: replace ordinary unit directory between candidate selection and leaf load/current check; replacement sentinel never returns or renders.
- Side judgement: replace program/idea/method/survey container or same-bytes inode after capture; review card/direct decision/formal event becomes absent or pending, and no replacement sentinel appears.
- Program evidence: replace program directory/evidence after source-root snapshot capture; verification/current receipt rejects and no replacement quote is accepted.
- Confirmed survey report path proves only one bound-subject capture is used for validation + ClaimSource; replacement between old double-load phases cannot pass.
- Duplicate `(kind,id)`, symlink/FIFO/special/oversize/malformed/duplicate-key artifact fail closed and do not block valid siblings/report generation.
- Stable confirmed unit judgement, program decision, discussion, method selection and survey still enter the correct report lanes.

## Validation and commit discipline

Enumerate test files with `rg --files`. Run focused report/judgement/confirmation/strict-reader suites, then `/usr/bin/python3` AST parse on edited Python, `git diff --check`, confirm only owned files changed and no real `kb/`. Commit small pieces. Do not bump version, push, tag, merge or publish. STOP if the contract needs an unowned file.

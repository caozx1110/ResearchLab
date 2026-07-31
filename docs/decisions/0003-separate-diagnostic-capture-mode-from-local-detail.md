# ADR 0003: Separate diagnostic capture mode from local detail

- Status: Proposed（随 #13 PR 审查；仅合入 default branch 后生效）
- Date: 2026-07-31
- Atomic Issue: [#13](https://github.com/caozx1110/ResearchLab/issues/13)
- Decision owners: ResearchLab maintainers
- Supersedes: N/A
- Superseded by: N/A

## Context

The original D1 diagnostic policy used `off | errors-only | developer` both as a capture policy and, by implication, as a detail policy. In practice `developer` only authorized a bounded Agent retrospective: automatic capture still persisted the same redacted summary fields as `errors-only`. Users could therefore reasonably expect diagnostic detail that the runtime never retained, while accepting arbitrary child output would expose research material, user text, credentials, environment values, or local paths.

The redacted `issues.yaml` index is already useful for safe review and export. It must remain backward compatible, and optional diagnostics must continue to preserve the original operation result, public message, transaction/recovery boundaries, and the absence of telemetry.

## Decision

Capture and persistence are orthogonal policies:

- `diagnostics.mode = off | errors-only | developer` keeps its existing meaning.
- `diagnostics.detail_level = redacted | local-detailed` defaults to `redacted`.
- Legacy scalar `diagnostics.per_skill.<skill>` mode overrides remain unchanged. Detail overrides use the sibling `diagnostics.per_skill_detail_level.<skill> = inherit | redacted | local-detailed` mapping.

`kb/memory/skill-evolution/issues.yaml` remains the redacted index and keeps the legacy fingerprint when detail is disabled. With effective `local-detailed`, one bounded artifact per diagnostic identity is stored below `kb/memory/skill-evolution/.private/details/`. The summary contains only a repository-relative `detail_ref`, its SHA-256 digest, and the retrospective status. A private signature derived from stable owner, operation, exception class, allowlisted failure stage, and validated repository-relative product-source frame tokens may distinguish mechanically different failures without placing that signature's inputs in export output.

Automatic callers may submit only `diagnostic-mechanical-envelope/v1`: a safe exception class, an allowlisted failure stage, at most eight validated product-source repository-relative frame tokens without source text, at most four allowlisted event codes, a bounded Python/runtime version, and a small mapping of stable dependency version tokens. The dispatcher constructs this envelope independently of child arguments and captured stdout/stderr. The intake owner's one-use failure-stage receipt may refine an `unknown` dispatcher stage; a conflicting stage fails private detail closed and retains the legacy redacted record.

The private artifact keeps at most five occurrence snapshots and records a dropped-history count. `errors-only + local-detailed` stores mechanical facts with `root_cause.status=not-run`. `developer + local-detailed` records `not-run` when the budget is zero and `pending` when Agent analysis is eligible. A separate owner-only apply operation must match the current issue ID and detail digest before it may store a sanitized `hypothesis`, reproduction notes, optimization candidates, and next validations. Scripts never infer a root cause, never claim token usage, and never promote a hypothesis to confirmed.

Summary and detail writes are one declared mutation transaction and roll back to their before-images together. Private directories and files use anchored no-follow traversal, regular-file/owner/mode/size checks, `0700` directories, and `0600` artifacts. Private detail is hard-excluded from checkpoint path discovery even if a legacy file was force-added. Export preview, public output, Agent public projections, installer/update, sync, and versioning never read it.

## Alternatives considered

- Make `developer` imply detailed storage. Rejected because it silently changes existing workspace privacy behavior and still conflates capture frequency with persistence.
- Store detail inline in `issues.yaml`. Rejected because review/export consumers would have to handle sensitive local material and old readers could expose it accidentally.
- Add `local-raw` or retain argv, full output, or traceback text. Rejected because deterministic redaction cannot make arbitrary research/user content a safe durable diagnostic input.
- Let the dispatcher or scripts infer root cause. Rejected because the product invariant assigns diagnosis to the runtime Agent and requires an explicit epistemic status.

## Consequences

Old workspaces remain byte-semantically compatible and continue to produce only redacted summaries unless the user explicitly enables `local-detailed`. Detailed diagnostics are more useful for local debugging, but consume bounded additional local storage and require an owner-mediated Agent step for hypotheses. The private artifact is intentionally unavailable to export and synchronization workflows; sharing a diagnosis requires a separately authorized redacted summary.

The generic subprocess dispatcher can provide only an empty validated frame list plus stable class, stage, event, and version tokens. It never derives a cause from argv, stdout, stderr, or traceback text. A concrete root-cause explanation therefore remains a later Agent-authored hypothesis rather than an automatic traceback capture claim.

Corrupt, unsafe, dangling, or digest-mismatched detail is visible as a private integrity failure and is not repaired by reads. Because optional detail is fail-soft, automatic capture falls back to the legacy redacted issue without changing the failed operation's exit code or public text.

## Migration and rollback

No data migration runs. Preference normalization supplies `redacted` and an empty detail-override mapping when fields are missing or invalid; old scalar per-skill mode entries retain their shape. Setting the workspace and per-skill detail policy back to `redacted` immediately restores legacy capture behavior without deleting existing private artifacts. A code rollback may ignore the new preference and summary fields, but must not silently delete local detailed records; cleanup requires a future explicit retention decision.

## Validation

Acceptance requires preference compatibility and round-trip tests; closed-envelope dispatcher tests; credential/path/user/source/output exclusion fixtures; failure-stage binding; summary/detail rollback, concurrency, bounded-history, and no-follow storage tests; digest-bound Agent apply tests; hard checkpoint/export/install isolation; documentation consistency; the complete repository test suite; exact-head branch Actions; and human review of the consolidated #13 PR. Tests use only temporary workspaces and never a real user `kb/`.

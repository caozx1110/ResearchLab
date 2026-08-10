# Review and confirmation contract

Load only this reference when displaying or applying review decisions, including Obsidian batch review.

## Display

- Request a fresh private protocol and read `present_review_items.review_items[]`. Display only the frozen public card fields and the governance profile's bounded batch.
- The snapshot binds subject, owner route, content, verification, current receipt inputs, batch limit, and expiry. Priority comes from the owner; equal priority is oldest first.
- Missing signer does not block display. Prepared shells, empty claims, stale verification, ready-to-verify, and retryable failures stay out of the human inbox.

## Apply a conversational decision

The private adapter receives the display protocol filename, exact `kind:id` refs shown in that protocol, the user's verbatim current-message authorization, and decision evidence. Confirm, reject, and defer may be mixed in one batch.

- Only refs from the displayed snapshot are valid. Never infer a ref from a title or apply an undisplayed remainder.
- Confirmation requires a real signer; rejection may include a reason and does not require a signer.
- `expired`, `already_applied`, `stale_content`, `tampered_or_unknown`, and `invalid_decision` require a safe explanation and a fresh display when appropriate. Missing confirmation context asks only for the missing signer/authorization/evidence.
- Validation or owner failure does not consume the snapshot. Successful application consumes it and creates one exact checkpoint for the whole batch.

## Obsidian batch

1. Export one bounded pending-review sheet.
2. When the user returns, parse it read-only and preview the complete diff. Checkboxes are intent drafts, not authorization.
3. Restate every confirm/reject/defer choice and obtain current-message authorization.
4. Apply only with the exact batch ref and current preview digest.

Any non-checkbox edit, duplicate/conflicting/missing choice, replay, expiry, symlink, sheet tamper, or current binding change rejects the whole batch. Projection refresh never consumes a sheet and no watcher applies it automatically.

## Atomic coordinator

Conversational and Obsidian decisions share one cross-owner coordinator. It performs a complete read-only preflight, freezes the exact target union, takes one root transaction, revalidates authorization/snapshot/owner plans/CAS under lock, calls no-nested-lock owner child APIs, consumes the snapshot only after all canonical writes succeed, and checkpoints once. Any failure is zero business write.

Public feedback contains only sanitized judgement labels/titles and the batch result. Token, digest, owner arguments, internal status, and paths remain private.

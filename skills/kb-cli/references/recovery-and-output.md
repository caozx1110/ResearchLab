# Recovery and public-output contract

Load only this reference for `resume`, `undo`, `restore`, interrupted operations, or output sanitization.

## Recovery selector

- `resume` continues only an incomplete journal operation and preserves its exact target/owner contract.
- `undo` reverses the latest still-selectable undoable business root plus the required complete rewind interval. Publicly name only the safe object/operation description.
- `restore` without an identifier is read-only and lists a bounded recent catalog using public numbers, time, and safe summaries. With a public number it restores to the state before that root operation.
- Internal bookkeeping roots and descendants are never offered as independent choices; the recovery engine includes them mechanically when required.

After recovery, use `kb status` to verify the public state. Never skip an incomplete journal, hand-edit recovery metadata, replay only part of an atomic batch, or expose internal operation IDs/paths.

## Failure handling

- Read the private protocol reason and offer a natural-language retry, fresh review, reinstall, or user decision as appropriate.
- Preserve retryable snapshots and before-images. Stale identity, content, layout, rule-layer, or CAS failures remain fail closed.
- Do not turn a failed business operation into success because diagnostics or a child emitted reassuring text.

## Public-output sanitizer

User-visible responses may contain natural language and existing `kb <verb>` forms only. Remove or paraphrase:

- Python/shell commands, script paths, flags, environment variables, placeholders, and absolute or internal relative paths;
- protocol names/payloads, owner routing parameters, digests/tokens, raw stdout/stderr, traceback/source excerpts, and `NEXT FOR AGENT:` strings;
- internal workflow/status codes that are not meaningful to the user.

State what happened, what durable object changed, what still needs confirmation, and the safest next action. Keep evidence distinctions clear: confirmed library fact, Agent inference, or still-to-verify question.

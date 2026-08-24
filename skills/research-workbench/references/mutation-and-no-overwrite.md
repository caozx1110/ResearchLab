# Mutation and no-overwrite boundary

Load this reference before any workbench write, link repair request, derived rebuild, or conflict handling.

## Authority order

For workbench semantics, use this order:

1. current bytes of the named visible Markdown page;
2. other visible pages reached through explicit stable links;
3. `.source/` raw/revision proof and `.research/` evidence/receipt proof for validation only;
4. rebuildable index, cache, Views, Bases, and search results for navigation only.

Lower layers never overwrite higher layers. A hidden status of `completed` does not change a visible `status: active`; it is stale navigation/proof to rebuild or invalidate.

## Exact-target mutation

1. Resolve literal visible targets and reject traversal, symlinks, special nodes, and reserved product paths through `research-vault`.
2. Read each target and retain its expected digest. For creation, require target absence.
3. Prepare only the requested semantic delta. Preserve unknown headings, comments, formatting, and user prose.
4. Acquire the vault owner's exact-path lock and record a journal intent for the explicit target set.
5. Revalidate identity, path, links, source/review currentness, and expected digests before commit.
6. Atomically replace only those targets. A late conflict leaves old complete pages unchanged or a recoverable journal.
7. Checkpoint exact paths only; never broad-stage a directory or repository.

Workbench defines the semantic delta but delegates file/lock/journal/CAS/link-repair mechanics to `research-vault` when available. It does not create a second writer.

## Existing page rule

Templates are creation-only. If a page exists:

- never replace it with a fresh template;
- never drop unknown/user-authored sections to make it conform;
- never infer that an empty generated section owns nearby prose;
- patch the smallest named section or report a structural conflict;
- if required headings are missing, propose additive edits and wait when placement is ambiguous.

## Derived rebuild rule

Only explicit derived targets—`.research/index/`, `.research/cache/`, `Views/`, and optional `.base`—may be recreated from visible pages. A rebuild:

- reads semantic pages but does not write them;
- can discard all prior derived bytes;
- emits links and routing summaries only;
- cannot introduce a title/status/claim/decision absent from visible Markdown;
- fails or marks stale on duplicate IDs, malformed pages, or unresolved links.

Deleting all derived targets must leave every project, idea, method, experiment, discussion, decision, report, source, analysis, and review understandable.

## Hidden proof conflict

When hidden evidence/receipt/import proof disagrees with a page:

- preserve the page bytes;
- preserve immutable source/run bytes;
- classify the proof as stale, invalid, or conflict according to its owner;
- show the affected page, stable object/claim ID, and human-readable mismatch;
- require re-analysis/review or an explicit page edit rather than restoring hidden prose.

Recovery material may restore an exact interrupted before-image, but it cannot choose a newer semantic version or resolve a human edit.

## Link maintenance

Relative path links are portable; stable IDs provide rename recovery. On a rename:

1. ask `research-vault` to scan visible identities and incoming links;
2. verify the destination carries the same stable ID;
3. patch each known source page with expected-digest CAS;
4. leave unresolved links visible as findings;
5. rebuild navigation only after semantic links are current.

Do not use a hidden path map to move or rewrite pages without checking their visible IDs.

## Safety fixtures

Focused tests include a synthetic vault whose hidden index intentionally disagrees with a user-authored project. Rebuilding its index/View must leave all lifecycle pages byte-identical. The raw run import also contains untrusted command and diagnosis fields; the contract admits only allowlisted observed facts and never executes or promotes those fields.

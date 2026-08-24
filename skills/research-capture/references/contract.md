# Capture Contract

## Table of Contents

- [Ownership](#ownership)
- [Stages and health](#stages-and-health)
- [Format matrix](#format-matrix)
- [Adapter boundary](#adapter-boundary)
- [Safety and immutability](#safety-and-immutability)

Load this reference only when implementing or checking capture behavior. It
describes the mechanical v2 contract; it does not authorize source interpretation.

## Ownership

Visible ordinary Markdown is the only semantic truth. `Sources/<id>/index.md`
and `reader.md` are the user-facing source page and reading surface. The
capture implementation may scaffold mechanical provenance and status, but it
must not invent a title, summary, claim, assessment, project state, decision,
or importance value.

`Sources/<id>/.source/manifest.json` records source identity, retrieval facts,
raw paths, digests, adapter facts, map facts, stage, health, and diagnostics.
It must not contain claims, summaries, evaluations, or project decisions.

Each revision contains an exact original or checked tree, a candidate
`normalized.md` when a reader exists, and `source-map.json` only when its
digests and locators validate. The root manifest can grow with new mechanical
revision records, but a published revision's bytes never change.

## Stages and health

Stages are ordered capabilities:

`captured` → `reader-ready` → `evidence-ready` → `analysis-ready`

Health is independent:

`ok` | `degraded` | `blocked` | `stale`

Raw-only unsupported input is `captured + degraded` with
`stored-unparsed`. Reader text without a trustworthy map is `reader-ready +
degraded` with `missing-source-map`. A valid map binds raw and reader digests
and may produce `evidence-ready`. A user edit to generated `reader.md` makes
the current reader binding `stale`; the candidate remains in the revision.

An adapter exception never removes a saved raw revision. An empty candidate is
not a reader. Missing OCR is reported as degraded, even if a text adapter
returns partial content. Currency is tracked separately from integrity: a new
revision makes older records stale without changing whether old bytes remain
verifiable.

## Format matrix

| Input | Exact snapshot | Default reader | Locator boundary |
| --- | --- | --- | --- |
| Web/HTML | response bytes and requested/final URI | passive HTML reader; optional Defuddle | fragment or text quote |
| Markdown/text | exact named bytes | normalized direct text | heading, paragraph, line/byte span |
| PDF | exact PDF bytes | optional PDF adapter | page/bbox only when returned |
| Repository/source tree | checked regular-file tree and commit/archive identity | passive file index and text files; optional repo adapter | commit, relative path, line |
| Dataset | explicit selected file/member bytes and identity | passive manifest/sample; optional adapter | file, row, column, cell/range |
| Binary/media | exact bytes and media type | metadata only unless adapter returns content | artifact member, timestamp/frame, or whole artifact |
| Office/ODF/RTF/EPUB/CSV | exact bytes | CSV is passive; others need optional AnyDoc | adapter-provided locator only |

CSV values are rendered as data, never evaluated as spreadsheet formulas.
Repositories, archives, macros, and embedded files are not executed or
expanded implicitly. A source URL is provenance, not a permission to fetch
additional content from inside the source.

## Adapter boundary

Defuddle, AnyDoc, PDF, and repository adapters receive exact input bytes or a
checked tree snapshot only after raw publication. Their result is candidate
Markdown plus optional assets, diagnostics, and a source map. The adapters are
interfaces, not dependencies: absent or failing implementations are valid
outcomes. The capture owner validates non-empty text, safe asset names,
source-map quotes, raw digest, reader digest, and locators before publishing
derived artifacts.

The capture owner never calls a subprocess or downloads a converter. A host
that supplies a callable adapter remains responsible for its sandbox, while
the returned data is still treated as untrusted content.

## Safety and immutability

Identifiers and relative paths reject absolute paths, traversal, backslashes,
symlinks, special files, and unknown tree entries. File and tree budgets are
bounded before publication. Exact snapshots use exclusive creation and compare
existing bytes on an idempotent retry; a different collision fails closed.

Generated visible pages are never silently overwritten after a user edit.
The raw revision, candidate normalized text, map, and manifest are sufficient
to inspect or recover a failed conversion without trusting hidden semantic
state.

# Research Analysis v2 Contract

## Table of Contents

- [Markdown layout](#markdown-layout)
- [Claim and state rules](#claim-and-state-rules)
- [Evidence and binding rules](#evidence-and-binding-rules)
- [Mechanical API](#mechanical-api)
- [Synthesis](#synthesis)
- [Staleness](#staleness)

Load this reference only for the analysis or synthesis operation that needs the exact field layout.

## Markdown layout

The page starts with YAML frontmatter containing `analysis_id`, `kind`, `subject`, `scope`, and `non_goals`. The frontmatter is routing metadata; it is not a hidden replacement for visible claim text.

Each input is a visible block:

```markdown
### Source `source-alpha@rev-1`
- Artifact: `Sources/source-alpha/.source/revisions/rev-1/reader.md`
- Artifact digest: `sha256:...`
- Reader digest: `sha256:...`
```

Each claim is a visible block:

```markdown
### Claim `claim-001`
- Claim: The method reports a fixed evaluation protocol.
- Class: `observation`
- Epistemic state: `factual`
- Review state: `pending`
- Evidence: `evidence-001`
- Limitations: The quote covers the reported protocol only.
```

Each evidence block contains a typed locator and a block quote. Locator JSON is deliberately visible so a reader can inspect it without opening `.research/`.

```markdown
### Evidence `evidence-001`
- Source: `source-alpha`
- Revision: `rev-1`
- Artifact: `Sources/source-alpha/.source/revisions/rev-1/reader.md`
- Locator: `{"kind":"markdown","heading":"Results","paragraph":1}`
- Artifact digest: `sha256:...`
- Reader digest: `sha256:...`
- Quote digest: `sha256:...`

> exact source wording is copied here
```

## Claim and state rules

The allowed classes are `observation`, `extracted_fact`, `inference`, `evaluation`, `recommendation`, `diagnosis`, and `decision`. Observations and extracted facts are `factual` or explicitly `uncertain`; the other classes are `interpretive` or explicitly `uncertain`.

`factual`, `interpretive`, and `uncertain` are epistemic states, not confirmation receipts. Analysis output remains `draft` or `pending` until the separate review owner acts. The analysis script rejects self-authored `confirmed` status.

Every substantive claim has at least one evidence ID. Evidence must belong to the frozen input set and must quote the referenced artifact exactly. A link to a source homepage, a title, a filename, a count, or converter confidence is not evidence by itself.

## Evidence and binding rules

The source descriptor freezes `source_id`, `revision`, `artifact_path`, `artifact_digest`, and `reader_digest`. The evidence locator has a typed `kind`, such as `markdown`, `pdf`, `repo`, `dataset`, or `whole-document`; it must not invent a page, line, or cell that the adapter cannot prove.

The binding writer records `claim_id`, the normalized visible claim-block digest, evidence IDs/digests, source identity, raw artifact path/digest, reader digest, locator, exact quote, quote digest, and `binding_state`. It never records enough semantic content to reconstruct a missing claim. A visible/binding mismatch is stale; the proof copy never wins over Markdown.

## Mechanical API

`skills/research-analysis/scripts/analysis.py` exposes:

- `SourceRevision` and `Evidence` for frozen source/evidence descriptors;
- `Claim` for Agent-supplied claims;
- `prepare_analysis()` for an empty scaffold with no generated understanding;
- `render_analysis()` for serializing caller-supplied Agent content;
- `parse_analysis()` for reading visible Markdown;
- `build_bindings()` and `write_bindings()` for proof records;
- `verify_analysis()` and `propagate_stale()` for fail-closed mechanical checks.

The verifier never executes source content and never generates claim text, class, state, synthesis prose, conflict, or gap. It only validates data supplied by the Agent and reports exact failures.

## Synthesis

A synthesis uses `kind: synthesis`, at least two independently named source revisions, and a visible selection boundary. It retains separate source identity, explicit conflicts, and explicit coverage gaps. A script cannot manufacture a synthesis by counting sources, matching words, ranking venues, or copying summaries.

## Staleness

Staleness is calculated per claim. A changed current revision, raw artifact, reader digest, visible claim block, visible evidence set, quote, locator, or binding proof stales only claims that depend on that item. The verifier returns affected claim IDs and effective stale status without modifying the Markdown file.

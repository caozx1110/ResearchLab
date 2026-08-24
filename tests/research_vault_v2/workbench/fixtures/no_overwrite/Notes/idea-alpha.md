---
id: idea-alpha
kind: idea
status: selected
---

# Preserve semantic pages during rebuild

## Problem or opportunity

Derived indexes can drift from direct user edits.

## Proposal

Make visible Markdown the sole semantic input to every rebuild.

## Known facts

- [Evidence E-001](../Sources/src-alpha/reader.md#evidence-e-001) records the synthetic metric.

## Interpretation and claims

### Claim C-IDEA-001

- Class: recommendation
- Review: confirmed
- Evidence: [project success criterion](../Projects/project-alpha/index.md#success-criteria)

Derived data should never overwrite semantic pages.

## Related sources, claims, and reviews

- Source: [src-alpha](../Sources/src-alpha/reader.md)
- Review: [review-idea-alpha](../Reviews/review-idea-alpha.md)

## Open questions

- How should duplicate visible IDs be surfaced?

## Status rationale

Selected through [review-idea-alpha](../Reviews/review-idea-alpha.md).

## Next action

- Use [method-alpha](method-alpha.md) to define the boundary.

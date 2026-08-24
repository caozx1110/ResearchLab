---
id: method-alpha
kind: method
status: accepted
---

# Derived-only rebuild method

## Objective and preconditions

Rebuild navigation without changing lifecycle pages after [idea-alpha](idea-alpha.md) is selected.

## Interfaces

- Input: visible Markdown identity, kind, status, and links.
- Output: replaceable index and View bytes.

## Procedure

1. Read visible pages.
2. Build derived data in replacement targets.
3. Verify semantic page digests are unchanged.

## Variables, baselines, and resources

- Baseline: stale hidden index.
- Candidate: visible-page-derived index.
- Resource boundary: isolated fixture only.

## Risks and limitations

- Duplicate IDs must stop rebuild instead of selecting a winner.

## Evidence and lifecycle references

- Project: [project-alpha](../Projects/project-alpha/index.md)
- Idea: [idea-alpha](idea-alpha.md)
- Review: [review-method-alpha](../Reviews/review-method-alpha.md)

## Next actions

- Run [exp-alpha](../Experiments/exp-alpha/index.md).

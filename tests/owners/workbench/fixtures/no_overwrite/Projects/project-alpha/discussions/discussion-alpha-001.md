---
id: discussion-alpha-001
kind: discussion
status: resolved
---

# Which layer wins on conflict?

## Context and participants

- Context: stale hidden status conflicts with the user-authored project page.
- Participants: maintainer and Agent.

## Verbatim participant statements

> Keep the visible project state unchanged.

- Attributed to: fixture maintainer

## Agent summary

The maintainer prioritized the visible page over stale derived state. This sentence is a summary, not a quote.

## Open questions and trade-offs

- Rebuilding is safe only when duplicate visible IDs stop the operation.

## Candidate interpretations

### Claim C-DISC-001

- Class: inference
- Review: pending
- Evidence: [project current state](../index.md#current-state)

The conflict indicates stale navigation, not a completed project.

## Resulting decisions

- [decision-alpha](../../../Decisions/decision-alpha.md)

## Next actions

- Keep the candidate interpretation isolated until reviewed.

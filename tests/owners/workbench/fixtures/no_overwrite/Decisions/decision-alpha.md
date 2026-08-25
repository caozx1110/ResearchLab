---
id: decision-alpha
kind: decision
status: accepted
---

# Visible Markdown wins derived conflicts

## Context and decision question

The hidden index claims the project is completed while the visible page says active.

## Decision

Preserve visible Markdown and rebuild or invalidate the hidden index.

## Status and authorization

- Status rationale: accepted for this fixture.
- Review: [review-decision-alpha](../Reviews/review-decision-alpha.md)

## Alternatives considered

- Restore hidden status into the project page — rejected because it creates a second semantic truth.

## Evidence

- Discussion: [discussion-alpha-001](../Projects/project-alpha/discussions/discussion-alpha-001.md)
- Experiment: [Claim C-EXP-001](../Experiments/exp-alpha/index.md#claim-c-exp-001)

## Consequences and risks

- Stale derived data may be unavailable until rebuild completes.

## Revisit and rollback conditions

- Revisit if the accepted Markdown-first contract changes through a new ADR.

## Supersession

- Supersedes: none
- Superseded by: none

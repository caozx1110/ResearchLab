# Concept and evidence-gap composite contract

Load only this reference for a concept unit or when survey preparation finds no eligible material.

## Concept workflow

1. `concept prepare` freezes at least three current confirmed non-concept units and creates empty definition/association claim cells.
2. Runtime Agent fills the definition, association roles, non-empty scope, and verbatim evidence from the frozen corpus.
3. `concept verify` revalidates all unit records, receipts, evidence bytes, claims, and association-to-link projection.
4. Success writes a pending concept unit under the existing unit contract. It remains pending until normal public review confirms it.

Every definition and association needs evidence. Upstream record/receipt/evidence drift or a changed association/link projection makes the concept stale. The script never derives a concept from tag frequency or lexical co-occurrence.

## Evidence-gap composite

When survey filters yield no eligible inputs, return a structured evidence gap and create a durable composite state bound to request digest and revision. Do not write a zero-material scaffold.

The ordered stages are:

1. search;
2. user selection;
3. source intake;
4. unit analysis;
5. synthesis;
6. review confirmation;
7. report consumption.

Each stage records only its inputs, outputs, blocker, and resume action. Updates use revision CAS and remain a real `kb next` candidate across sessions. The runtime Agent still chooses candidates and authors conclusions.

The composite freezes the same preference context as the synthesis request. Changed soft-selection/hard constraints produce a different request digest; they cannot silently resume an older composite. Resume continues the first incomplete safe stage and never reopens a completed or confirmed stage.

## Clarification defaults

- Time window: recent two years plus foundational work, anchored to today unless the user specifies otherwise.
- Corpus: current confirmed library first; on a gap, offer the composite instead of pretending completeness.
- Depth: full seven-section survey and comparison matrix unless the user asks for a compact review.

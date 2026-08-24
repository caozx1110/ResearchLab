# Discussions, decisions, and reports

Load this reference for discussion archival, long-term decisions, and reader-facing reports.

## Discussion records

A discussion page preserves process without turning Agent synthesis into participant speech. Use [the discussion template](../assets/templates/discussion.md) and keep these sections distinct:

- context, date/scope, and named participants or roles;
- verbatim participant statements, clearly quoted and attributed;
- Agent summary, explicitly labelled as a summary;
- open questions and trade-offs;
- candidate interpretations, each with claim/evidence/review state;
- resulting decision links and next actions.

Do not fabricate quotes from a summary. If exact wording is unavailable, state that no verbatim statement was captured. A resolved discussion means its tracked question is resolved or handed off; it does not itself authorize a decision.

## Decisions

`Decisions/<decision-id>.md` is the sole semantic owner for a long-term decision. Use [the decision template](../assets/templates/decision.md). It records:

- context and decision question;
- chosen option in visible prose;
- alternatives considered;
- source, claim, experiment, and discussion evidence;
- consequences, risks, and rollback/revisit conditions;
- visible review/authorization reference;
- predecessor/successor IDs when superseded.

Project, method, experiment, and report pages link to this file instead of copying the decision body. `status: accepted` requires an eligible visible review reference from `research-review`; workbench cannot accept its own recommendation. A superseding decision links both directions and does not rewrite history.

## Reports

Reports are ordinary Markdown under `Reports/` and remain understandable without hidden manifests or local artifacts. Use [the report template](../assets/templates/report.md). A report includes:

- audience, period/scope, and linked project;
- self-contained executive summary;
- factual progress and experiment results;
- current review-backed conclusions;
- pending/stale interpretations in a separate section;
- accepted decisions;
- limitations, missing inputs, and source/claim/review references.

A frozen `.research/` manifest may bind input/output digests for reproducibility. It cannot own report prose or insert hidden-only conclusions. When an input becomes stale, preserve the existing prose, add the smallest visible stale annotation with a CAS edit, and request review; never regenerate over user edits.

## Epistemic labels

Use human-readable labels consistently:

| Content | Label/location | Eligible for final conclusions |
|---|---|---|
| observed event or exact metric | `Factual progress` / `Factual results` | yes, as scoped fact |
| participant's exact words | attributed block quote | yes, only as what was said |
| Agent condensation | `Agent summary` | no, unless no judgement is implied |
| inference/evaluation/diagnosis | stable claim + review state | only when current and review-backed |
| recommendation | stable claim + review state | only when current and review-backed |
| accepted decision | decision link + authorization reference | yes, with scope |
| pending/rejected/stale judgement | explicit isolation section | no |

Absence is explicit: write “No current review-backed conclusion” or “Missing: …” instead of filling gaps from memory, hidden caches, or plausible prose.

## Lifecycle connections

- A selected idea links the review that selected it and the method it motivates.
- An accepted method links the project, source/claims, review, and planned experiments.
- A resolved discussion links any resulting decision; no decision means it says so.
- An accepted decision links the discussion/evidence and the review that authorized it.
- A final report links the exact current project, experiments, decisions, claims, and reviews it used.

These links express relationships; they do not transfer ownership or duplicate another object's semantics.

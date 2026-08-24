# Pages and lifecycle

Load this reference for page creation, status changes, or project/idea/method maintenance.

## Semantic locations

| Object | Visible page | `kind` | Initial status |
|---|---|---|---|
| project | `Projects/<project-id>/index.md` | `project` | `proposed` |
| idea | `Notes/<idea-id>.md` | `idea` | `captured` |
| method | `Notes/<method-id>.md` | `method` | `draft` |
| experiment | `Experiments/<experiment-id>/index.md` | `experiment` | `planned` |
| discussion | `Projects/<project-id>/discussions/<discussion-id>.md`, or `Notes/<discussion-id>.md` when independent | `discussion` | `open` |
| decision | `Decisions/<decision-id>.md` | `decision` | `proposed` |
| report | `Reports/<report-id>.md` | `report` | `outline` |

Questions normally live in the owning project's `index.md` or `questions.md`; a question that becomes a durable cross-project object uses `Notes/<question-id>.md` with `kind: question`. A path may move, but its `id` does not change or get reused.

Use the product templates under `assets/templates/`. A template is creation-only: never apply it over an existing page, even when sections are missing.

## Status vocabularies

| Kind | Allowed statuses, in normal forward order |
|---|---|
| project | `proposed` → `active` → `completed`; `paused` is resumable and `abandoned` is an explicit terminal branch |
| idea | `captured` → `exploring` → `selected`; `deferred` and `rejected` are explicit branches |
| method | `draft` → `under-review` → `accepted` → `superseded`; `retired` is explicit |
| experiment | `planned` → `running` → `completed`; `blocked` is resumable and `cancelled` is explicit |
| discussion | `open` → `resolved` → `archived` |
| decision | `proposed` → `accepted` → `superseded`; `rejected` is explicit |
| report | `outline` → `drafting` → `in-review` → `final` → `superseded` |

`paused`, `blocked`, and `deferred` may return to their preceding active state when the page records why. Terminal states do not silently reopen: append a visible rationale and explicit user request, or create a successor page linked by stable ID. A status word in an index, View, Base, cache, receipt, or old message never changes the page.

Transitions that accept a judgement—idea `selected`, method `accepted`, decision `accepted`, interpretive experiment conclusion, and report `final` when it asserts judgements—must carry a visible `research-review` reference. Workbench consumes that reference; it does not infer authorization from a checkbox or construct hidden proof.

## Required page content

### Project

- Research question
- Scope and Non-goals
- Success criteria
- Current state
- Linked sources and notes
- Decisions, Experiments, and Open questions
- Next actions

The project page is the project semantic center. A worklog may preserve chronological events, but it cannot own a conflicting current state.

### Idea

- Problem or opportunity
- Proposal
- Known facts
- Interpretation and claims
- Related sources, claims, and reviews
- Open questions, status rationale, and next action

### Method

- Objective and preconditions
- Interfaces and procedure
- Variables, baselines, and resources
- Risks and limitations
- Source, claim, review, idea, and project references
- Next actions

## Stable links

Use standard relative Markdown links as the portable core. Link to the owning visible page and a stable heading or claim ID when needed:

```markdown
- Project: [project-alpha][project-ref]
- Source revision: [src-alpha reader][source-ref]
- Claim: [Claim C-001][claim-ref]
- Review: [review-alpha-c001][review-ref]

[project-ref]: ../Projects/project-alpha/index.md
[source-ref]: ../Sources/src-alpha/reader.md
[claim-ref]: ../Notes/analysis-alpha.md#claim-c-001
[review-ref]: ../Reviews/review-alpha-c001.md
```

Keep the target object's stable ID in surrounding text or link label. When a user renames a path, `research-vault` scans IDs and repairs links with CAS; workbench never treats a stale path index as identity.

## Creation and update rules

1. Confirm that the ID is unique through the vault owner.
2. Create only the explicit target page and missing parent directory.
3. Start with the kind's initial status unless the user supplies a review-backed state.
4. Preserve all unknown headings and user prose on update.
5. Update only the named section/status/link, then verify every changed link.
6. Record status rationale in visible prose; frontmatter is a routing summary, not a substitute for context.

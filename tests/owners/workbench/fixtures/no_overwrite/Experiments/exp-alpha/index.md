---
id: exp-alpha
kind: experiment
status: completed
---

# Alpha no-overwrite experiment

## Hypothesis

A derived-only rebuild can preserve every visible semantic page byte-for-byte.

## Plan

- Hash visible pages, rebuild only `.research/index/` and `Views/`, then compare hashes.

## Variables and baselines

- Independent variable: derived state before or after rebuild.
- Baseline: stale hidden index.
- Controlled variable: visible fixture bytes.

## Metrics

| Metric | Type | Unit | Direction |
|---|---|---|---|
| Preserved semantic pages | integer | pages | descriptive |
| Accuracy | number | ratio | descriptive |

## Linked project, method, and sources

- Project: [project-alpha](../../Projects/project-alpha/index.md)
- Method: [method-alpha](../../Notes/method-alpha.md)
- Source: [src-alpha](../../Sources/src-alpha/reader.md)

## Runs

- [run-001](runs/run-001.md)

## Factual results

| Run | Preserved semantic pages | Accuracy | Artifact |
|---|---:|---:|---|
| run-001 | 13 | 0.82 | [run-001](runs/run-001.md) |

## Interpretation

### Claim C-EXP-001

- Class: evaluation
- Review: confirmed
- Evidence: [run-001](runs/run-001.md)
- Scope: synthetic no-overwrite fixture only

The derived-only rebuild preserved the fixture pages; this does not establish behavior for untested writers.

## Pending judgements

- None. [Claim C-EXP-001](#claim-c-exp-001) was handled by [review-exp-alpha-c001](../../Reviews/review-exp-alpha-c001.md).

## Limitations

- One synthetic fixture and no concurrent writer.

## Next actions

- Report the scoped result in [report-alpha](../../Reports/report-alpha.md).

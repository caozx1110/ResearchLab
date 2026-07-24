# Literature search stage payload

The runtime Agent writes a temporary JSON object and passes it privately to the bundled stage helper. Unknown or raw provider payloads are not part of this contract.

```json
{
  "request": "original research question",
  "preference_selection_id": "optional current literature-search + search receipt id",
  "stage_id": "optional-existing-stage-id",
  "run_id": "optional-safe-id-for-an-explicit-fresh-run",
  "monitor_binding": {
    "run_id": "required only when a research-monitor run owns this stage",
    "task_digest": "sha256 of the frozen monitor task"
  },
  "note": "optional stage note",
  "mode": "exploratory | bounded-systematic | systematic",
  "scope": {
    "as_of": "date or snapshot",
    "facets": ["..."],
    "inclusion": ["..."],
    "exclusion": ["..."],
    "languages": ["..."],
    "source_types": ["..."],
    "channels": ["..."],
    "date_range": "...",
    "result_depth": "...",
    "screening": "...",
    "screeners": 2,
    "disagreement_resolution": "third reviewer",
    "target_count": 20,
    "reproducible": false
  },
  "review_protocol": {
    "required_reviewer_ids": ["reviewer-a", "reviewer-b"],
    "mode": "independent | assisted",
    "phases": ["title_abstract", "fulltext"],
    "adjudication_mode": "consensus | third_reviewer | user"
  },
  "reviewers": [
    {
      "reviewer_id": "reviewer-a",
      "actor_type": "agent | human",
      "execution_id": "isolated-context-id",
      "attestation": "required only for a human reviewer",
      "authorization_source": "user_message"
    }
  ],
  "budget": {
    "max_queries": 8,
    "max_candidates": 50,
    "max_full_reads": 8,
    "max_citation_hops": 6
  },
  "usage": {
    "queries": 2,
    "candidates_seen": 18,
    "full_reads": 0,
    "citation_hops": 0,
    "retryable_failures": 0
  },
  "queries": [
    {
      "query_id": "q-seed-01",
      "text": "query text",
      "intent": "seed",
      "facet": "main method",
      "channel": "web-search",
      "tool": "runtime tool name",
      "selection_reason": "why this available tool fits this query",
      "searched_at": "UTC ISO-8601",
      "result_depth": "first 10 visible results",
      "result_count": 10,
      "outcome": "success",
      "reproducible": false
    }
  ],
  "candidates": [
    {
      "candidate_id": "optional-stable-id",
      "title": "Original paper title",
      "url": "https://...",
      "identities": {
        "doi": "10.xxxx/...",
        "arxiv_id": "2501.01234",
        "pmid": "12345678"
      },
      "discovered_by": [
        {
          "query_id": "q-seed-01",
          "edge_type": "direct | reference | cited_by",
          "parent_candidate_id": "required for citation edges",
          "source_locator": "search result, references section, or citing page",
          "channel": "web-search",
          "tool": "runtime tool name",
          "discovered_at": "UTC ISO-8601"
        }
      ],
      "fetch": {
        "status": "discovered | fetching | fetched | failed_retryable | failed_terminal | needs_fulltext | staged",
        "attempts": 1,
        "error_class": "safe-redacted-slug",
        "updated_at": "UTC ISO-8601"
      },
      "evidence_level": "snippet | title | abstract | fulltext",
      "screening_decisions": [
        {
          "decision_id": "decision-a",
          "reviewer_id": "reviewer-a",
          "phase": "title_abstract | fulltext",
          "decision": "include | maybe | exclude",
          "basis": "title | abstract | fulltext",
          "rationale": "reviewer-authored reasoning",
          "evidence": [{"quote": "short verbatim text", "locator": "source locator"}],
          "decided_at": "timezone-aware ISO-8601",
          "evidence_digest": "derived sha256; persisted output may include it",
          "decision_digest": "derived sha256; persisted output may include it",
          "supersedes_decision_id": "optional prior decision by the same reviewer and phase"
        }
      ],
      "adjudications": [
        {
          "adjudication_id": "adjudication-c",
          "phase": "fulltext",
          "input_decision_ids": ["decision-a", "decision-b"],
          "status": "pending | resolved",
          "final_decision": "include | maybe | exclude",
          "resolved_by": "reviewer-c | current-user",
          "rationale": "required when resolved",
          "evidence": [{"quote": "short verbatim text", "locator": "source locator"}],
          "resolved_at": "timezone-aware ISO-8601",
          "input_digest": "derived digest of the exact active input decisions"
        }
      ],
      "metadata": {
        "authors": ["..."],
        "publication_date": "YYYY-MM-DD",
        "publication_year": 2026,
        "publication_type": "article",
        "language": "en",
        "venue": "...",
        "is_retracted": false
      }
    }
  ],
  "coverage": {
    "round": 1,
    "covered_facets": ["..."],
    "uncovered_facets": ["..."],
    "new_candidates": 18,
    "deduplicated": 3,
    "new_relevant": 5,
    "flow_counts": {
      "identified": 18,
      "duplicates_removed": 3,
      "title_abstract_screened": 15,
      "title_abstract_excluded": 9,
      "fulltext_sought": 6,
      "fulltext_unavailable": 1,
      "fulltext_assessed": 5,
      "excluded_with_reason": 2,
      "included": 3,
      "automation_excluded": 0
    },
    "concentration_risk": "...",
    "bias_risk": "...",
    "notes": "..."
  },
  "frontier": [
    {
      "candidate_id": "...",
      "direction": "backward | forward",
      "priority_reason": "...",
      "status": "pending | expanded | skipped | failed_retryable"
    }
  ],
  "stop": {
    "reason": "in_progress | target_met | saturated | budget_exhausted | blocked_no_search_tool | blocked | user_stop",
    "rationale": "required for terminal reasons",
    "uncovered_facets": ["..."]
  },
  "partial": true
}
```

For a single-reviewer run, omit `review_protocol`, `reviewers`, `screening_decisions`, and `adjudications`, and use the compatible candidate `screening` mapping with `decision`, `phase`, `basis`, `rationale`, `evidence`, and `reviewer`. For a multi-reviewer run, use only the ledger form shown above.

For `bounded-systematic` and `systematic`, freeze non-empty inclusion, exclusion, languages, source types, channels, date range, result depth, screening method, and screener count in `scope`. With one screener use `screening`. With two or more, provide a frozen `review_protocol`, registry entries for every required reviewer, and append-only `screening_decisions`; do not send both forms for one candidate. Protocol phases are unique and ordered `title_abstract`, then `fulltext`. `independent` requires a distinct execution/context id per required reviewer, while same-context role prompting must be `assisted`. The helper derives `effective_screening` only after all required active decisions agree or a conflict has a resolved adjudication. Original decisions remain immutable and are revalidated by their persisted digests on resume; a correction explicitly supersedes the same reviewer's prior decision for that phase. A pending adjudication remains in history; resolution is a new append-only record bound to the active input-decision digest. `user` mode resolves only as `current-user`; `third_reviewer` requires a non-screener reviewer with a distinct execution id. A human reviewer or current-user adjudication needs a current user-message attestation. None of these records replaces the user's later candidate-materialization choice.

`systematic` requires `reproducible: true` for the scope and every query event; `bounded-systematic` requires `false` and always persists `partial: true`. Every query event records its facet, timezone-aware timestamp, result depth, count, and outcome, and usage must equal the durable event count. Before a systematic-family stage reaches a terminal stop reason, `coverage.flow_counts` must contain all fields above; `identified` equals both the sum of query result counts and the number of persisted discovery occurrences, and each query's own result count equals the discovery occurrences that reference it, while duplicates equal discovery occurrences minus unique candidates. The flow must satisfy the identification → dedup/automation → title/abstract → full-text → included/excluded arithmetic and agree with the legacy or derived effective decisions, evidence levels, fetch availability, and full-read usage.

Omit `stage_id` for the first batch and resend the same request, mode, and frozen scope for later batches; the helper derives the same run identity. Supply a new safe `run_id` only when intentionally starting a fresh run with otherwise identical inputs. Candidate and discovery URLs must be credential-free; raw responses, headers, cookies, tokens, and signed request URLs are forbidden.

`preference_selection_id` is optional. When present, the helper recomputes the canonical task context from the normalized request, mode, run id, frozen scope digest, and resolved stage id, then fails closed on a wrong skill, wrong operation, another task, or stale catalog. The persisted stage contains only the receipt binding and hard-value digests under `preference_context`, never copied soft preference values. Without a receipt, the selection binding is empty and soft behavior is neutral; current hard constraints remain frozen by digest. `preference_context` cannot change when resuming a stage.

When `research-monitor` owns the run, include its exact `monitor_binding` in the first and every resumed batch. The binding is immutable and makes the completed monitor receipt reject an unrelated or later-repurposed stage.

Only include `basis`, `rationale`, and `evidence` when the screening decision is not `unassessed`. A snippet is never an allowed screening basis.

# Literature search stage payload

The runtime Agent writes a temporary JSON object and passes it privately to the bundled stage helper. Unknown or raw provider payloads are not part of this contract.

```json
{
  "request": "original research question",
  "stage_id": "optional-existing-stage-id",
  "run_id": "optional-safe-id-for-an-explicit-fresh-run",
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
    "screeners": 1,
    "disagreement_resolution": "reserved; multiple screeners currently fail closed",
    "target_count": 20,
    "reproducible": false
  },
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
      "screening": {
        "decision": "unassessed | include | maybe | exclude",
        "phase": "automation | title_abstract | fulltext",
        "basis": "title | abstract | fulltext",
        "rationale": "Agent-authored relevance reasoning",
        "evidence": [{"quote": "short verbatim text", "locator": "source locator"}],
        "reviewer": "runtime-agent"
      },
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

For `bounded-systematic` and `systematic`, freeze non-empty inclusion, exclusion, languages, source types, channels, date range, result depth, screening method, and screener count in `scope`. The current schema supports exactly one auditable Agent screening track; values above one fail closed until a per-reviewer decision and disagreement ledger exists. `systematic` requires `reproducible: true` for the scope and every query event; `bounded-systematic` requires `false` and always persists `partial: true`. Every query event records its facet, timezone-aware timestamp, result depth, count, and outcome, and usage must equal the durable event count. Before a systematic-family stage reaches a terminal stop reason, `coverage.flow_counts` must contain all fields above; `identified` equals both the sum of query result counts and the number of persisted discovery occurrences, and each query's own result count equals the discovery occurrences that reference it, while duplicates equal discovery occurrences minus unique candidates. The flow must satisfy the identification → dedup/automation → title/abstract → full-text → included/excluded arithmetic and agree with persisted candidate decisions, evidence levels, fetch availability, and full-read usage.

Omit `stage_id` for the first batch and resend the same request, mode, and frozen scope for later batches; the helper derives the same run identity. Supply a new safe `run_id` only when intentionally starting a fresh run with otherwise identical inputs. Candidate and discovery URLs must be credential-free; raw responses, headers, cookies, tokens, and signed request URLs are forbidden.

Only include `basis`, `rationale`, and `evidence` when the screening decision is not `unassessed`. A snippet is never an allowed screening basis.

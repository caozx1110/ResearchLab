from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

import research.sources as sources
from research.common import load_yaml, write_yaml_if_changed
from research.paths import config_root
from research.preference_selection import eligible_preferences, record_effective_selection
from research.prefs import ensure_workspace
from research.sources import build_literature_search_stage_id, stage_search_results


ROOT = Path(__file__).resolve().parents[4]
SEARCH_SCRIPT = ROOT / ".agents" / "skills" / "literature-search" / "scripts" / "search.py"
INTAKE_SCRIPT = ROOT / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"


def _search_module():
    spec = importlib.util.spec_from_file_location("literature_search_script", SEARCH_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _intake_module():
    spec = importlib.util.spec_from_file_location("literature_search_intake", INTAKE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_search_selection(root: Path, module, payload: dict, selection_id: str) -> str:
    stage_id = build_literature_search_stage_id(
        str(payload.get("request") or ""),
        mode=str(payload.get("mode") or "exploratory"),
        scope=payload.get("scope") if isinstance(payload.get("scope"), dict) else {},
        run_id=str(payload.get("run_id") or ""),
    )
    eligible = eligible_preferences(root, skill="literature-search", operation="search")
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {
            "preference_id": item["preference_id"],
            "reason": "relevant to this search",
        }
        if item["strength"] == "hard" or item["path"] == "profile.preferences.language_preference":
            selected.append({**row, "application": "apply to this bounded search only"})
        else:
            excluded.append({**row, "reason": "not relevant to this search"})
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "literature-search",
            "operation": "search",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": module.literature_search_preference_context(payload, stage_id=stage_id),
            "selected": selected,
            "excluded": excluded,
        },
    )
    return selection_id


def _query(query_id: str, *, text: str | None = None, intent: str = "seed") -> dict:
    return {
        "query_id": query_id,
        "text": text or f"query {query_id}",
        "intent": intent,
        "facet": "main facet",
        "channel": "web-search",
        "tool": "runtime-search",
        "selection_reason": "available broad web coverage",
        "searched_at": "2026-07-24T00:00:00+00:00",
        "result_depth": "first 10 results",
        "result_count": 10,
        "outcome": "success",
        "reproducible": False,
    }


def _state(*, queries: list[dict] | None = None, usage_queries: int = 0) -> dict:
    return {
        "entry_skill": "literature-search",
        "mode": "exploratory",
        "scope": {"facets": ["main facet"], "target_count": 20},
        "budget": {
            "max_queries": 4,
            "max_candidates": 50,
            "max_full_reads": 8,
            "max_citation_hops": 6,
        },
        "usage": {
            "queries": usage_queries,
            "candidates_seen": 10 if usage_queries else 0,
            "full_reads": 0,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": queries or [],
        "coverage": {
            "round": usage_queries,
            "covered_facets": ["main facet"] if usage_queries else [],
            "uncovered_facets": ["negative results"],
            "new_candidates": 1 if usage_queries else 0,
            "deduplicated": 0,
            "new_relevant": 0,
        },
        "frontier": [],
        "stop": {"reason": "in_progress"},
        "partial": True,
    }


def _candidate(
    candidate_id: str,
    url: str,
    *,
    query_id: str = "q1",
    doi: str = "",
    fetch_status: str = "fetched",
    attempts: int = 1,
) -> dict:
    candidate = {
        "candidate_id": candidate_id,
        "title": f"Paper {candidate_id}",
        "url": url,
        "discovered_by": [
            {
                "query_id": query_id,
                "edge_type": "direct",
                "source_locator": "search result",
                "channel": "web-search",
                "tool": "runtime-search",
                "discovered_at": "2026-07-24T00:00:00+00:00",
            }
        ],
        "fetch": {"status": fetch_status, "attempts": attempts},
        "evidence_level": "snippet",
        "screening": {"decision": "unassessed"},
    }
    if doi:
        candidate["identities"] = {"doi": doi}
    return candidate


def _screened_candidate(candidate_id: str, decision: str) -> dict:
    candidate = _candidate(candidate_id, f"https://example.test/{candidate_id}")
    candidate["evidence_level"] = "fulltext"
    candidate["screening"] = {
        "decision": decision,
        "basis": "fulltext",
        "rationale": f"Full text supports the {decision} decision.",
        "evidence": [{"quote": f"evidence for {candidate_id}", "locator": "results"}],
        "reviewer": "runtime-agent",
    }
    return candidate


def _title_excluded_candidate(candidate_id: str) -> dict:
    candidate = _candidate(candidate_id, f"https://example.test/{candidate_id}")
    candidate["evidence_level"] = "abstract"
    candidate["screening"] = {
        "decision": "exclude",
        "phase": "title_abstract",
        "basis": "abstract",
        "rationale": "The abstract is outside the frozen scope.",
        "evidence": [{"quote": f"out-of-scope {candidate_id}", "locator": "abstract"}],
        "reviewer": "runtime-agent",
    }
    return candidate


def test_literature_search_bundles_no_provider_client() -> None:
    assert not (ROOT / ".agents" / "lib" / "research" / "openalex.py").exists()
    script = SEARCH_SCRIPT.read_text(encoding="utf-8")
    assert "urlopen" not in script
    assert "requests" not in script
    assert "OpenAlex" not in script
    skill = (ROOT / ".agents" / "skills" / "literature-search" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "当前会话真正可用" in skill
    assert "固定 provider 路由表" in skill


def test_agent_authored_search_stage_persists_queries_budget_and_provenance(tmp_path: Path) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["frontier"] = [
        {
            "candidate_id": "paper-a",
            "direction": "backward",
            "priority_reason": "seed paper may expose earlier work",
            "status": "pending",
        }
    ]
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="robot learning literature",
        candidates=[_candidate("paper-a", "https://example.test/paper-a", doi="10.1234/EXAMPLE")],
        search_state=state,
    )

    stage = load_yaml(path)
    assert stage["entry_skill"] == "literature-search"
    assert stage["mode"] == "exploratory"
    assert stage["budget"]["max_queries"] == 4
    assert stage["queries"][0]["selection_reason"] == "available broad web coverage"
    candidate = stage["candidates"][0]
    assert candidate["identities"]["doi"] == "https://doi.org/10.1234/example"
    assert candidate["discovered_by"][0]["query_id"] == "q1"
    assert candidate["screening"] == {"decision": "unassessed"}
    assert stage["frontier"][0]["direction"] == "backward"


def test_url_only_identity_upgrade_and_doi_merge_preserve_manual_fields(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="identity upgrade",
        candidates=[{"candidate_id": "stable-a", "title": "Old", "url": "https://example.test/a"}],
    )
    stage = load_yaml(path)
    stage["candidates"][0]["status"] = "reviewed"
    stage["candidates"][0]["note"] = "manual assessment"
    write_yaml_if_changed(path, stage)

    stage_search_results(
        tmp_path,
        kind="paper",
        query="identity upgrade",
        candidates=[
            {
                "candidate_id": "new-id-is-ignored",
                "title": "With DOI",
                "url": "https://example.test/a",
                "identities": {"doi": "doi:10.1234/UPGRADE"},
            }
        ],
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="identity upgrade",
        candidates=[
            {
                "candidate_id": "another-id",
                "title": "New landing page",
                "url": "https://publisher.test/new-a",
                "identities": {"doi": "https://doi.org/10.1234/upgrade"},
            }
        ],
    )

    candidate = load_yaml(path)["candidates"][0]
    assert candidate["candidate_id"] == "stable-a"
    assert candidate["status"] == "reviewed"
    assert candidate["note"] == "manual assessment"
    assert candidate["url"] == "https://publisher.test/new-a"
    assert candidate["identities"]["doi"] == "https://doi.org/10.1234/upgrade"


def test_identity_that_matches_two_existing_candidates_fails_closed(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="identity conflict",
        candidates=[
            {
                "candidate_id": "paper-a",
                "title": "A",
                "url": "https://example.test/a",
                "identities": {"doi": "10.1234/a"},
            },
            {
                "candidate_id": "paper-b",
                "title": "B",
                "url": "https://example.test/b",
                "identities": {"doi": "10.1234/b"},
            },
        ],
    )
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="identities conflict"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="identity conflict",
            candidates=[
                {
                    "candidate_id": "ambiguous",
                    "title": "Ambiguous",
                    "url": "https://example.test/b",
                    "identities": {"doi": "10.1234/a"},
                }
            ],
        )

    assert path.read_bytes() == before


def test_same_url_with_conflicting_strong_identity_fails_closed(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="same url conflict",
        candidates=[
            {
                "candidate_id": "paper-a",
                "title": "A",
                "url": "https://example.test/a",
                "identities": {"doi": "10.1234/a"},
            }
        ],
    )
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="conflicting strong identities"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="same url conflict",
            candidates=[
                {
                    "candidate_id": "paper-b",
                    "title": "B",
                    "url": "https://example.test/a",
                    "identities": {"doi": "10.1234/b"},
                }
            ],
        )
    assert path.read_bytes() == before


def test_same_title_and_year_do_not_auto_merge_without_strong_identity(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="title collision",
        candidates=[
            {
                "candidate_id": "paper-a",
                "title": "A Shared Title",
                "url": "https://example.test/a",
                "metadata": {"publication_year": 2025},
            },
            {
                "candidate_id": "paper-b",
                "title": "A Shared Title",
                "url": "https://example.test/b",
                "metadata": {"publication_year": 2025},
            },
        ],
    )
    assert [item["candidate_id"] for item in load_yaml(path)["candidates"]] == [
        "paper-a",
        "paper-b",
    ]


def test_resume_appends_queries_discovery_and_retry_without_duplication(tmp_path: Path) -> None:
    first_state = _state(queries=[_query("q1")], usage_queries=1)
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="retryable search",
        candidates=[
            _candidate(
                "paper-a",
                "https://example.test/a",
                fetch_status="failed_retryable",
                attempts=1,
            )
        ],
        search_state=first_state,
    )
    second_state = _state(queries=[_query("q2", intent="gap-followup")], usage_queries=2)
    second_state.pop("scope")
    second_state.pop("budget")
    stage_search_results(
        tmp_path,
        kind="paper",
        query="retryable search",
        candidates=[
            _candidate(
                "paper-a",
                "https://example.test/a",
                query_id="q2",
                fetch_status="fetched",
                attempts=2,
            )
        ],
        search_state=second_state,
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="retryable search",
        candidates=[
            _candidate(
                "paper-a",
                "https://example.test/a",
                query_id="q2",
                fetch_status="fetched",
                attempts=2,
            )
        ],
        search_state=second_state,
    )

    stage = load_yaml(path)
    assert [item["query_id"] for item in stage["queries"]] == ["q1", "q2"]
    assert stage["usage"]["queries"] == 2
    candidate = stage["candidates"][0]
    assert candidate["fetch"] == {"attempts": 2, "status": "fetched"}
    assert [item["query_id"] for item in candidate["discovered_by"]] == ["q1", "q2"]


def test_budget_is_persistent_monotonic_and_enforced(tmp_path: Path) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="budgeted search",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=state,
    )
    before = path.read_bytes()

    changed_budget = _state(queries=[], usage_queries=1)
    changed_budget["budget"]["max_queries"] = 5
    with pytest.raises(SystemExit, match="budget cannot change"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="budgeted search",
            candidates=[],
            search_state=changed_budget,
        )

    exceeded = {
        "queries": [_query(f"q{index}") for index in range(2, 6)],
        "usage": {"queries": 5},
    }
    with pytest.raises(SystemExit, match="exceeds its persisted hard budget"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="budgeted search",
            candidates=[],
            search_state=exceeded,
        )

    decreased = {"usage": {"queries": 0}}
    with pytest.raises(SystemExit, match="cannot decrease"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="budgeted search",
            candidates=[],
            search_state=decreased,
        )
    assert path.read_bytes() == before


def test_query_id_cannot_be_reused_for_different_tool_event(tmp_path: Path) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="query conflict",
        candidates=[],
        search_state=state,
    )
    before = path.read_bytes()
    changed = _query("q1")
    changed["tool"] = "another-runtime-tool"
    with pytest.raises(SystemExit, match="query_id conflicts"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="query conflict",
            candidates=[],
            search_state={"queries": [changed], "usage": {"queries": 1}},
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "state, message",
    [
        (
            {"entry_skill": "literature-search", "mode": "systematic", "scope": {}},
            "requires a frozen scope",
        ),
        (
            {
                "entry_skill": "literature-search",
                "mode": "systematic",
                "scope": {
                    "inclusion": ["peer-reviewed"],
                    "exclusion": ["non-research"],
                    "languages": ["en"],
                    "source_types": ["paper"],
                    "channels": ["web-search"],
                    "date_range": "2020-2026",
                    "result_depth": "first 100 results",
                    "screening": "single Agent with evidence",
                    "screeners": 1,
                    "reproducible": False,
                },
            },
            "must declare a reproducible",
        ),
        (
            {
                "entry_skill": "literature-search",
                "mode": "bounded-systematic",
                "scope": {
                    "inclusion": ["peer-reviewed"],
                    "exclusion": ["non-research"],
                    "languages": ["en"],
                    "source_types": ["paper"],
                    "channels": ["web-search"],
                    "date_range": "2020-2026",
                    "result_depth": "visible results",
                    "screening": "single Agent with evidence",
                    "screeners": 1,
                    "reproducible": True,
                },
            },
            "Use systematic mode",
        ),
    ],
)
def test_systematic_mode_labels_fail_closed_without_honest_scope(
    tmp_path: Path,
    state: dict,
    message: str,
) -> None:
    with pytest.raises(SystemExit, match=message):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="systematic review",
            candidates=[],
            search_state=state,
        )
    assert not (tmp_path / "kb").exists()


def test_bounded_systematic_scope_is_persisted_as_partial_not_complete(tmp_path: Path) -> None:
    state = {
        "entry_skill": "literature-search",
        "mode": "bounded-systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["web-search"],
            "date_range": "2020-2026",
            "result_depth": "visible results",
            "screening": "single Agent with evidence",
            "screeners": 1,
            "reproducible": False,
        },
        "budget": {
            "max_queries": 4,
            "max_candidates": 50,
            "max_full_reads": 4,
            "max_citation_hops": 6,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 12,
            "full_reads": 4,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [{**_query("q1"), "result_count": 12}],
        "stop": {
            "reason": "budget_exhausted",
            "rationale": "The available web search exposes only bounded visible results.",
            "uncovered_facets": ["non-English databases"],
        },
        "coverage": {
            "round": 1,
            "covered_facets": ["main"],
            "uncovered_facets": ["non-English databases"],
            "flow_counts": {
                "identified": 12,
                "duplicates_removed": 2,
                "title_abstract_screened": 10,
                "title_abstract_excluded": 6,
                "fulltext_sought": 4,
                "fulltext_unavailable": 1,
                "fulltext_assessed": 3,
                "excluded_with_reason": 1,
                "included": 2,
                "automation_excluded": 0,
            },
        },
        "partial": True,
    }
    candidates = [
        _screened_candidate("included-a", "include"),
        _screened_candidate("included-b", "include"),
        _screened_candidate("excluded-a", "exclude"),
        *[_title_excluded_candidate(f"title-excluded-{index}") for index in range(6)],
        _candidate(
            "fulltext-unavailable",
            "https://example.test/fulltext-unavailable",
            fetch_status="failed_terminal",
        ),
    ]
    for index in range(2):
        duplicate_discovery = dict(candidates[index]["discovered_by"][0])
        duplicate_discovery["source_locator"] = f"duplicate result {index + 1}"
        candidates[index]["discovered_by"].append(duplicate_discovery)
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="bounded systematic review",
        candidates=candidates,
        search_state=state,
    )
    stage = load_yaml(path)
    assert stage["mode"] == "bounded-systematic"
    assert stage["scope"]["reproducible"] is False
    assert stage["partial"] is True
    assert stage["stop"]["uncovered_facets"] == ["non-English databases"]


def test_systematic_mode_rejects_a_nonreproducible_query_event(tmp_path: Path) -> None:
    state = {
        "entry_skill": "literature-search",
        "mode": "systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["database export"],
            "date_range": "2020-2026",
            "result_depth": "all exported results",
            "screening": "single evidence-backed reviewer",
            "screeners": 1,
            "reproducible": True,
        },
        "budget": {
            "max_queries": 4,
            "max_candidates": 50,
            "max_full_reads": 8,
            "max_citation_hops": 6,
        },
        "queries": [_query("q1")],
        "usage": {"queries": 1},
        "stop": {"reason": "in_progress"},
    }
    with pytest.raises(SystemExit, match="Every query event in systematic mode must be reproducible"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="reproducible systematic search",
            candidates=[],
            search_state=state,
        )


def test_terminal_systematic_search_requires_complete_flow_counts(tmp_path: Path) -> None:
    state = {
        "entry_skill": "literature-search",
        "mode": "bounded-systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["web-search"],
            "date_range": "2020-2026",
            "result_depth": "visible results",
            "screening": "single Agent with evidence",
            "screeners": 1,
            "reproducible": False,
        },
        "budget": {
            "max_queries": 4,
            "max_candidates": 50,
            "max_full_reads": 8,
            "max_citation_hops": 6,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 10,
            "full_reads": 0,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [_query("q1")],
        "coverage": {"round": 1, "flow_counts": {"identified": 10}},
        "stop": {"reason": "saturated", "rationale": "No new relevant candidates in two rounds."},
        "partial": True,
    }
    with pytest.raises(SystemExit, match="complete screening flow counts"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="incomplete systematic counts",
            candidates=[],
            search_state=state,
        )


def test_bounded_systematic_can_stop_cleanly_when_no_search_tool_exists(tmp_path: Path) -> None:
    state = {
        "entry_skill": "literature-search",
        "mode": "bounded-systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["runtime-search"],
            "date_range": "2020-2026",
            "result_depth": "visible results",
            "screening": "single Agent with evidence",
            "screeners": 1,
            "reproducible": False,
        },
        "budget": {
            "max_queries": 4,
            "max_candidates": 50,
            "max_full_reads": 8,
            "max_citation_hops": 6,
        },
        "usage": {
            "queries": 0,
            "candidates_seen": 0,
            "full_reads": 0,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [],
        "stop": {
            "reason": "blocked_no_search_tool",
            "rationale": "This runtime has no search, browser, or connector tool.",
        },
        "partial": True,
    }
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="systematic but unavailable",
        candidates=[],
        search_state=state,
    )
    assert load_yaml(path)["stop"]["reason"] == "blocked_no_search_tool"


def test_snippet_cannot_support_a_screening_judgement(tmp_path: Path) -> None:
    candidate = _candidate("paper-a", "https://example.test/a")
    candidate["screening"] = {
        "decision": "include",
        "basis": "snippet",
        "rationale": "Looks relevant",
        "evidence": [{"quote": "short search snippet", "locator": "result 1"}],
    }
    with pytest.raises(SystemExit, match="requires title, abstract, or fulltext basis"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="snippet boundary",
            candidates=[candidate],
        )
    assert not (tmp_path / "kb").exists()


def test_screening_update_preserves_previous_review_record(tmp_path: Path) -> None:
    first = {
        "candidate_id": "paper-a",
        "title": "A",
        "url": "https://example.test/a",
        "evidence_level": "abstract",
        "screening": {
            "decision": "maybe",
            "basis": "abstract",
            "rationale": "The abstract addresses the method but not the target benchmark.",
            "evidence": [{"quote": "We introduce the method.", "locator": "abstract"}],
        },
    }
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="screening history",
        candidates=[first],
    )
    second = dict(first)
    second["screening"] = {
        "decision": "include",
        "basis": "fulltext",
        "rationale": "The experiments contain the target benchmark.",
        "evidence": [{"quote": "Results on TargetBench", "locator": "results/table-2"}],
    }
    second["evidence_level"] = "fulltext"
    stage_search_results(
        tmp_path,
        kind="paper",
        query="screening history",
        candidates=[second],
    )
    candidate = load_yaml(path)["candidates"][0]
    assert candidate["screening"]["decision"] == "include"
    assert candidate["screening_history"][0]["screening"]["decision"] == "maybe"


@pytest.mark.parametrize(
    ("kind", "query"),
    [("paper", "different query"), ("blog", "robot learning")],
)
def test_explicit_stage_id_rejects_identity_mismatch_without_mutation(
    tmp_path: Path,
    kind: str,
    query: str,
) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="robot learning",
        stage_id="shared-stage",
        candidates=[{"candidate_id": "first", "title": "First", "url": "https://example.test/first"}],
    )
    before = path.read_bytes()
    journal_root = tmp_path / "kb/.journal"
    journal_before = {item.name: item.read_bytes() for item in journal_root.glob("*.yaml")}
    with pytest.raises(SystemExit, match="identity does not match"):
        stage_search_results(
            tmp_path,
            kind=kind,
            query=query,
            stage_id="shared-stage",
            candidates=[{"candidate_id": "second", "title": "Second", "url": "https://example.test/second"}],
        )
    assert path.read_bytes() == before
    assert {item.name: item.read_bytes() for item in journal_root.glob("*.yaml")} == journal_before


def test_stage_identity_mismatch_precedes_workspace_seed_repairs(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="robot learning",
        stage_id="shared-stage",
        candidates=[{"candidate_id": "first", "title": "First", "url": "https://example.test/first"}],
    )
    current_state = tmp_path / "kb/user/current-state.md"
    current_state.unlink()
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="identity does not match"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="different query",
            stage_id="shared-stage",
            candidates=[],
        )
    assert not current_state.exists()
    assert path.read_bytes() == before


def test_stage_identity_race_fails_before_journal_write(tmp_path: Path, monkeypatch) -> None:
    calls = 0
    validate = sources._validate_search_stage_identity

    def fail_second_validation(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SystemExit("Search stage identity changed before the mutation lock.")
        validate(*args, **kwargs)

    monkeypatch.setattr(sources, "_validate_search_stage_identity", fail_second_validation)
    with pytest.raises(SystemExit, match="changed before the mutation lock"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="robot learning",
            stage_id="shared-stage",
            candidates=[{"candidate_id": "first", "title": "First", "url": "https://example.test/first"}],
        )
    assert not (tmp_path / "kb/synthesis/source-search/shared-stage.yaml").exists()
    assert not list((tmp_path / "kb/.journal").glob("*.yaml"))


def test_legacy_openalex_doi_is_read_only_compatibility_identity(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="legacy stage",
        candidates=[{"candidate_id": "legacy", "title": "Legacy", "url": "https://legacy.test/paper"}],
    )
    stage = load_yaml(path)
    stage["candidates"][0]["provenance"] = {
        "openalex": {"work_id": "https://openalex.org/W1", "doi": "10.1234/legacy"}
    }
    write_yaml_if_changed(path, stage)
    stage_search_results(
        tmp_path,
        kind="paper",
        query="legacy stage",
        candidates=[
            {
                "candidate_id": "new",
                "title": "Current",
                "url": "https://current.test/paper",
                "identities": {"doi": "10.1234/legacy"},
            }
        ],
    )
    candidate = load_yaml(path)["candidates"][0]
    assert candidate["candidate_id"] == "legacy"
    assert candidate["identities"]["doi"] == "https://doi.org/10.1234/legacy"
    assert candidate["provenance"]["openalex"]["work_id"] == "https://openalex.org/W1"


def test_blocked_no_search_tool_is_recorded_without_empty_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _search_module()
    payload = {
        "request": "papers about unavailable tools",
        "mode": "exploratory",
        "scope": {"facets": ["main"]},
        "budget": {"max_queries": 2, "max_candidates": 20},
        "usage": {"queries": 0, "candidates_seen": 0},
        "queries": [],
        "candidates": [],
        "coverage": {"round": 0, "uncovered_facets": ["main"]},
        "frontier": [],
        "stop": {
            "reason": "blocked_no_search_tool",
            "rationale": "No runtime search, browser, or connector is available.",
            "uncovered_facets": ["main"],
        },
        "partial": True,
    }
    input_path = tmp_path / "payload.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SEARCH_SCRIPT), "--root", str(tmp_path), "stage", "--input", str(input_path)],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert output == "当前没有可用的文献检索工具；已记录阻塞原因，没有把空结果当作成功。\n"
    assert "--" not in output
    assert str(tmp_path) not in output
    stages = list((tmp_path / "kb/synthesis/source-search").glob("*.yaml"))
    assert len(stages) == 1
    assert load_yaml(stages[0])["stop"]["reason"] == "blocked_no_search_tool"


def test_public_success_message_is_natural_language_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _search_module()
    payload = {
        "request": "robot learning papers",
        "mode": "exploratory",
        "scope": {"facets": ["main"]},
        "budget": {"max_queries": 2, "max_candidates": 20},
        "usage": {"queries": 1, "candidates_seen": 1},
        "queries": [_query("q1")],
        "candidates": [
            {
                **_candidate("paper-a", "https://example.test/a"),
                "evidence_level": "abstract",
                "screening": {
                    "decision": "include",
                    "basis": "abstract",
                    "rationale": "The abstract directly addresses robot learning.",
                    "evidence": [{"quote": "robot learning", "locator": "abstract"}],
                },
            }
        ],
        "coverage": {"round": 1, "covered_facets": ["main"], "uncovered_facets": []},
        "frontier": [],
        "stop": {"reason": "target_met", "rationale": "The requested bounded set was found."},
        "partial": False,
    }
    input_path = tmp_path / "payload.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SEARCH_SCRIPT), "--root", str(tmp_path), "stage", "--input", str(input_path)],
    )
    assert module.main() == 0
    output = capsys.readouterr().out
    assert "当前共有 1 个候选" in output
    assert "初筛建议保留 1" in output
    assert "请先告诉我你要保留哪些候选" in output
    for token in ("--root", ".agents/", ".py", str(tmp_path), "NEXT FOR AGENT"):
        assert token not in output


def test_stage_helper_rejects_unknown_raw_payload_before_workspace_write(tmp_path: Path) -> None:
    module = _search_module()
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps({"request": "safe", "candidates": [], "raw_response": {"token": "secret"}}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="unsupported fields"):
        module._load_payload(payload_path)
    assert not (tmp_path / "kb").exists()


def test_stage_helper_accepts_and_persists_immutable_monitor_binding(tmp_path: Path) -> None:
    module = _search_module()
    binding = {"run_id": "monitor-run-probe", "task_digest": "0" * 64}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "request": "monitor route probe",
                "monitor_binding": binding,
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )
    payload = module._load_payload(payload_path)
    path = module.stage_payload(tmp_path, payload)
    persisted = load_yaml(path)
    assert persisted["monitor_binding"] == binding

    with pytest.raises(SystemExit, match="monitor_binding cannot change"):
        module.stage_payload(
            tmp_path,
            {
                "request": "monitor route probe",
                "stage_id": path.stem,
                "monitor_binding": {
                    "run_id": "monitor-run-other",
                    "task_digest": "1" * 64,
                },
                "candidates": [],
            },
        )
    assert load_yaml(path)["monitor_binding"] == binding


def test_stage_helper_binds_current_search_preferences_and_rejects_stale_resume(
    tmp_path: Path,
) -> None:
    module = _search_module()
    ensure_workspace(tmp_path)
    profile_path = config_root(tmp_path) / "user-profile.yaml"
    write_yaml_if_changed(
        profile_path,
        {
            "preferences": {"language_preference": "zh-CN"},
            "constraints": ["no cloud upload"],
        },
    )
    payload = {
        "request": "preference-bound search",
        "scope": {"facets": ["robot learning"]},
        "candidates": [],
    }
    payload["preference_selection_id"] = _record_search_selection(
        tmp_path,
        module,
        payload,
        "prefsel-search-bound",
    )
    path = module.stage_payload(tmp_path, payload)
    persisted = load_yaml(path)
    context = persisted["preference_context"]
    assert context["selection_binding"]["selection_id"] == "prefsel-search-bound"
    assert context["selection_binding"]["operation"] == "search"
    assert context["hard_value_digests"]["profile.constraints"]

    before = path.read_bytes()
    write_yaml_if_changed(
        profile_path,
        {
            "preferences": {"language_preference": "en-US"},
            "constraints": ["no cloud upload"],
        },
    )
    with pytest.raises(SystemExit, match="stale catalog"):
        module.stage_payload(
            tmp_path,
            {
                **payload,
                "stage_id": persisted["id"],
            },
        )
    assert path.read_bytes() == before


def test_stage_helper_without_selection_keeps_soft_behavior_neutral_and_hard_context(
    tmp_path: Path,
) -> None:
    module = _search_module()
    ensure_workspace(tmp_path)
    write_yaml_if_changed(
        config_root(tmp_path) / "user-profile.yaml",
        {
            "preferences": {"language_preference": "zh-CN"},
            "constraints": ["offline only"],
        },
    )
    payload = {"request": "neutral search", "candidates": []}
    resolved = module.resolve_literature_search_preferences(
        tmp_path,
        payload,
        stage_id=build_literature_search_stage_id("neutral search"),
    )
    assert resolved["soft_items"] == []
    assert resolved["values_by_path"] == {"profile.constraints": ["offline only"]}
    path = module.stage_payload(tmp_path, payload)
    assert load_yaml(path)["preference_context"]["selection_binding"] == {}


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("stage_id", lambda payload, values: values.update(stage_id="source-search-other")),
        ("request", lambda payload, values: payload.update(request="changed question")),
        ("mode", lambda payload, values: payload.update(mode="bounded-systematic")),
        ("run_id", lambda payload, values: payload.update(run_id="run-other")),
        ("scope", lambda payload, values: payload.update(scope={"facets": ["other"]})),
        ("budget", lambda payload, values: payload.update(budget={"max_queries": 7})),
        (
            "review_protocol",
            lambda payload, values: payload.update(review_protocol={"mode": "independent"}),
        ),
        ("reviewers", lambda payload, values: payload.update(reviewers=[{"reviewer_id": "b"}])),
        (
            "monitor_binding",
            lambda payload, values: payload.update(
                monitor_binding={"run_id": "monitor-run-b", "task_digest": "b" * 64}
            ),
        ),
    ],
)
def test_search_preference_context_binds_every_frozen_field(field, mutate) -> None:
    module = _search_module()
    payload = {
        "request": "robot learning",
        "mode": "exploratory",
        "run_id": "run-a",
        "scope": {"facets": ["robot"]},
        "budget": {"max_queries": 4},
        "review_protocol": {},
        "reviewers": [],
        "monitor_binding": {},
    }
    values = {"stage_id": "source-search-a"}
    before = module.literature_search_preference_context(payload, **values)
    mutate(payload, values)
    after = module.literature_search_preference_context(payload, **values)

    assert after != before, field


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("stage_id", lambda payload: payload.update(stage_id="source-search-other")),
        ("request", lambda payload: payload.update(request="changed question")),
        ("mode", lambda payload: payload.update(mode="bounded-systematic")),
        ("run_id", lambda payload: payload.update(run_id="run-other")),
        ("scope", lambda payload: payload.update(scope={"facets": ["other"]})),
        ("budget", lambda payload: payload.update(budget={"max_queries": 7})),
        ("review_protocol", lambda payload: payload.update(review_protocol={"mode": "assisted"})),
        ("reviewers", lambda payload: payload.update(reviewers=[{"reviewer_id": "b"}])),
        (
            "monitor_binding",
            lambda payload: payload.update(
                monitor_binding={"run_id": "monitor-run-b", "task_digest": "b" * 64}
            ),
        ),
    ],
)
def test_search_old_preference_receipt_rejects_each_scope_replay_before_stage_write(
    tmp_path: Path,
    field: str,
    mutate,
) -> None:
    module = _search_module()
    ensure_workspace(tmp_path)
    base = {
        "request": "robot learning",
        "mode": "exploratory",
        "run_id": "run-a",
        "scope": {"facets": ["robot"], "target_count": 20},
        "budget": {"max_queries": 4},
        "candidates": [],
    }
    selection_id = _record_search_selection(
        tmp_path,
        module,
        base,
        f"prefsel-search-{field.replace('_', '-')}",
    )
    initial = {**base, "preference_selection_id": selection_id}
    path = module.stage_payload(tmp_path, initial)
    before = {
        item.relative_to(path.parent): item.read_bytes()
        for item in path.parent.glob("*.yaml")
        if item.is_file()
    }
    replay = {**copy.deepcopy(base), "stage_id": path.stem, "preference_selection_id": selection_id}
    mutate(replay)

    with pytest.raises(SystemExit, match="another task"):
        module.stage_payload(tmp_path, replay)

    assert {
        item.relative_to(path.parent): item.read_bytes()
        for item in path.parent.glob("*.yaml")
        if item.is_file()
    } == before, field


def test_search_resume_omissions_reuse_the_persisted_frozen_preference_context(
    tmp_path: Path,
) -> None:
    module = _search_module()
    ensure_workspace(tmp_path)
    initial = {
        "request": "resume frozen search",
        "mode": "exploratory",
        "run_id": "run-frozen",
        "scope": {"facets": ["robot"], "target_count": 20},
        "budget": {"max_queries": 4, "max_candidates": 20},
        "candidates": [],
    }
    selection_id = _record_search_selection(
        tmp_path,
        module,
        initial,
        "prefsel-search-resume-frozen",
    )
    path = module.stage_payload(
        tmp_path,
        {**initial, "preference_selection_id": selection_id},
    )
    persisted = load_yaml(path)
    initial_context = module.literature_search_preference_context(
        initial,
        stage_id=path.stem,
    )
    resume = {
        "request": initial["request"],
        "stage_id": path.stem,
        "preference_selection_id": selection_id,
        "candidates": [],
    }

    assert module.literature_search_preference_context(
        resume,
        stage_id=path.stem,
        existing=persisted,
    ) == initial_context
    assert module.stage_payload(tmp_path, resume) == path


def test_search_context_rehydrates_every_omitted_frozen_contract_field() -> None:
    module = _search_module()
    initial = {
        "request": "multi-review frozen search",
        "mode": "bounded-systematic",
        "run_id": "run-reviewed",
        "scope": {"facets": ["robot"], "screeners": 2},
        "budget": {
            "max_queries": 4,
            "max_candidates": 20,
            "max_full_reads": 6,
            "max_citation_hops": 3,
        },
        "review_protocol": {
            "required_reviewer_ids": ["reviewer-a", "reviewer-b"],
            "mode": "assisted",
            "phases": ["title_abstract", "fulltext"],
            "adjudication_mode": "user",
        },
        "reviewers": [
            {"reviewer_id": "reviewer-a", "actor_type": "agent", "role": "screener"},
            {"reviewer_id": "reviewer-b", "actor_type": "agent", "role": "screener"},
        ],
        "monitor_binding": {
            "run_id": "monitor-run-reviewed",
            "task_digest": "a" * 64,
        },
    }
    existing = {
        "id": "source-search-reviewed",
        "entry_skill": "literature-search",
        **copy.deepcopy(initial),
    }
    resume = {"request": initial["request"], "stage_id": existing["id"]}

    assert module.literature_search_preference_context(
        resume,
        stage_id=existing["id"],
        existing=existing,
    ) == module.literature_search_preference_context(
        initial,
        stage_id=existing["id"],
    )


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///private/paper", "https://u:p@example.test/a"])
def test_unsafe_candidate_urls_fail_before_workspace_write(tmp_path: Path, url: str) -> None:
    with pytest.raises(SystemExit, match="safe http"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="unsafe URL",
            candidates=[{"candidate_id": "unsafe", "title": "Unsafe", "url": url}],
        )
    assert not (tmp_path / "kb").exists()


def test_explicit_stage_id_cannot_escape_or_create_workspace(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="ASCII-safe identifier"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="path containment",
            stage_id="../outside",
            candidates=[],
        )
    assert not (tmp_path / "kb").exists()
    assert not (tmp_path / "outside.yaml").exists()


def test_symlink_stage_target_is_rejected_before_victim_or_journal_mutation(tmp_path: Path) -> None:
    stage_dir = tmp_path / "kb/synthesis/source-search"
    stage_dir.mkdir(parents=True)
    victim = tmp_path / "victim.yaml"
    victim.write_text("safe: true\n", encoding="utf-8")
    (stage_dir / "linked.yaml").symlink_to(victim)
    before = victim.read_bytes()

    with pytest.raises(SystemExit, match="regular file"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="symlink containment",
            stage_id="linked",
            candidates=[],
        )

    assert victim.read_bytes() == before
    assert not (tmp_path / "kb/.journal").exists()


def test_invalid_update_does_not_repair_workspace_or_start_a_journal(tmp_path: Path) -> None:
    stage_id = "preexisting-stage"
    path = tmp_path / "kb/synthesis/source-search" / f"{stage_id}.yaml"
    path.parent.mkdir(parents=True)
    write_yaml_if_changed(
        path,
        {
            "id": stage_id,
            "kind": "source-search-stage",
            "source_kind": "paper",
            "query": "preexisting",
            "entry_skill": "literature-search",
            "mode": "exploratory",
            "budget": {
                "max_queries": 1,
                "max_candidates": 10,
                "max_full_reads": 2,
                "max_citation_hops": 2,
            },
            "usage": {"queries": 0, "candidates_seen": 0, "full_reads": 0, "citation_hops": 0},
            "candidates": [],
            "history": [],
        },
    )
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="exceeds its persisted hard budget"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="preexisting",
            stage_id=stage_id,
            candidates=[],
            search_state={
                "queries": [_query("q1"), _query("q2")],
                "usage": {"queries": 2},
            },
        )

    assert path.read_bytes() == before
    assert not (tmp_path / "kb/user/current-state.md").exists()
    assert not (tmp_path / "kb/.journal").exists()


def test_discovery_must_reference_a_real_query_even_when_query_list_is_empty(tmp_path: Path) -> None:
    state = _state()
    state["usage"]["candidates_seen"] = 1
    with pytest.raises(SystemExit, match="unknown query event"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="unknown query reference",
            candidates=[_candidate("paper-a", "https://example.test/a", query_id="missing")],
            search_state=state,
        )
    assert not (tmp_path / "kb").exists()


def test_resume_rejects_a_persisted_literature_candidate_without_discovery(
    tmp_path: Path,
) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="corrupted provenance",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=_state(queries=[_query("q1")], usage_queries=1),
    )
    corrupted = load_yaml(path)
    corrupted["candidates"][0].pop("discovered_by")
    write_yaml_if_changed(path, corrupted)
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="at least one discovery edge"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="corrupted provenance",
            stage_id=path.stem,
            candidates=[],
            search_state={"usage": {"queries": 1, "candidates_seen": 10}},
        )
    assert path.read_bytes() == before


def test_frontier_and_coverage_updates_preserve_history(tmp_path: Path) -> None:
    first = _state(queries=[_query("q1")], usage_queries=1)
    first["frontier"] = [
        {
            "candidate_id": "paper-a",
            "direction": "backward",
            "priority_reason": "inspect references",
            "status": "pending",
        }
    ]
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="durable progress",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=first,
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="durable progress",
        candidates=[],
        search_state={
            "coverage": {
                "round": 2,
                "covered_facets": ["main facet", "negative results"],
                "uncovered_facets": [],
                "new_candidates": 0,
                "deduplicated": 1,
                "new_relevant": 0,
            },
            "frontier": [
                {
                    "candidate_id": "paper-a",
                    "direction": "backward",
                    "priority_reason": "references inspected",
                    "status": "expanded",
                }
            ],
        },
    )
    stage = load_yaml(path)
    assert stage["frontier"][0]["status"] == "expanded"
    assert stage["frontier_history"][0]["action"]["status"] == "pending"
    assert stage["coverage"]["round"] == 2
    assert stage["coverage_history"][0]["coverage"]["round"] == 1


def test_query_event_count_cannot_bypass_budget_by_omitting_usage(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="must match the persisted query count"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="query count budget",
            candidates=[],
            search_state={
                "entry_skill": "literature-search",
                "mode": "exploratory",
                "budget": {
                    "max_queries": 1,
                    "max_candidates": 10,
                    "max_full_reads": 2,
                    "max_citation_hops": 2,
                },
                "queries": [_query("q1"), _query("q2")],
                "partial": True,
            },
        )
    assert not (tmp_path / "kb").exists()


def test_nontracking_url_query_parameters_remain_distinct_identities(tmp_path: Path) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"]["candidates_seen"] = 2
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="url identity",
        candidates=[
            _candidate("paper-a", "https://example.test/paper?id=1"),
            _candidate("paper-b", "https://example.test/paper?id=2"),
        ],
        search_state=state,
    )
    assert [item["url"] for item in load_yaml(path)["candidates"]] == [
        "https://example.test/paper?id=1",
        "https://example.test/paper?id=2",
    ]


@pytest.mark.parametrize(
    "locator",
    [
        "https://search.test/result?api_key=secret",
        "https://search.test/result?X-Amz-Signature=secret",
        "Authorization: Bearer abc.def",
    ],
)
def test_sensitive_discovery_locator_is_rejected_before_write(
    tmp_path: Path,
    locator: str,
) -> None:
    candidate = _candidate("paper-a", "https://example.test/a")
    candidate["discovered_by"][0]["source_locator"] = locator
    with pytest.raises(SystemExit, match="sensitive request material"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="secret rejection",
            candidates=[candidate],
            search_state=_state(queries=[_query("q1")], usage_queries=1),
        )
    assert not (tmp_path / "kb").exists()


def test_screening_basis_cannot_exceed_candidate_evidence_level(tmp_path: Path) -> None:
    candidate = _candidate("paper-a", "https://example.test/a")
    candidate["screening"] = {
        "decision": "include",
        "basis": "fulltext",
        "rationale": "Claimed full-text support.",
        "evidence": [{"quote": "claimed text", "locator": "section 3"}],
    }
    with pytest.raises(SystemExit, match="exceeds the candidate evidence level"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="evidence boundary",
            candidates=[candidate],
            search_state=_state(queries=[_query("q1")], usage_queries=1),
        )
    assert not (tmp_path / "kb").exists()


def test_citation_and_frontier_references_must_resolve(tmp_path: Path) -> None:
    citation = _candidate("paper-a", "https://example.test/a")
    citation["discovered_by"][0].update(
        {"edge_type": "reference", "parent_candidate_id": "missing-parent"}
    )
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"].update({"candidates_seen": 1, "citation_hops": 1})
    with pytest.raises(SystemExit, match="unknown parent candidate"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="citation integrity",
            candidates=[citation],
            search_state=state,
        )

    state = _state(queries=[_query("q1")], usage_queries=1)
    state["frontier"] = [
        {
            "candidate_id": "missing",
            "priority_reason": "not actually staged",
            "status": "pending",
        }
    ]
    with pytest.raises(SystemExit, match="frontier references an unknown candidate"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="frontier integrity",
            candidates=[],
            search_state=state,
        )


def test_actual_fulltext_count_must_be_declared_in_usage(tmp_path: Path) -> None:
    candidate = _candidate("paper-a", "https://example.test/a")
    candidate["evidence_level"] = "fulltext"
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"].update({"candidates_seen": 1, "full_reads": 0})
    with pytest.raises(SystemExit, match="usage.full_reads"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="fulltext accounting",
            candidates=[candidate],
            search_state=state,
        )


def test_literature_stage_does_not_infer_topics_from_query_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sources,
        "infer_topics_and_tags",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not infer")),
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="a query that resembles a taxonomy",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=_state(queries=[_query("q1")], usage_queries=1),
    )
    assert load_yaml(path)["candidates"][0]["topics"] == []
    assert load_yaml(path)["candidates"][0]["tags"] == []


def test_run_identity_changes_with_mode_scope_and_explicit_fresh_run() -> None:
    exploratory = build_literature_search_stage_id("same question")
    scoped = build_literature_search_stage_id(
        "same question",
        mode="exploratory",
        scope={"facets": ["different facet"]},
    )
    fresh = build_literature_search_stage_id("same question", run_id="fresh-2")
    assert len({exploratory, scoped, fresh}) == 3


def test_fresh_run_id_is_persisted_in_the_stage(tmp_path: Path) -> None:
    path = _search_module().stage_payload(
        tmp_path,
        {
            "request": "same question",
            "run_id": "fresh-2",
            "candidates": [],
        },
    )
    assert load_yaml(path)["run_id"] == "fresh-2"


def test_explicit_generic_legacy_stage_is_preserved_and_replaced_by_safe_new_run(
    tmp_path: Path,
) -> None:
    legacy = stage_search_results(
        tmp_path,
        kind="paper",
        query="legacy question",
        stage_id="legacy-stage",
        candidates=[{"candidate_id": "old", "title": "Old", "url": "https://old.test/paper"}],
    )
    before = legacy.read_bytes()
    path = _search_module().stage_payload(
        tmp_path,
        {"request": "legacy question", "stage_id": "legacy-stage", "candidates": []},
    )
    assert path != legacy
    assert legacy.read_bytes() == before
    assert load_yaml(path)["entry_skill"] == "literature-search"
    assert set(load_yaml(path)["budget"]) == {
        "max_queries",
        "max_candidates",
        "max_full_reads",
        "max_citation_hops",
    }


def test_legacy_literature_stage_missing_budget_fields_can_resume(tmp_path: Path) -> None:
    path = _search_module().stage_payload(
        tmp_path,
        {"request": "resume old literature run", "candidates": []},
    )
    stage = load_yaml(path)
    stage["budget"] = {"max_queries": 8}
    write_yaml_if_changed(path, stage)
    resumed = _search_module().stage_payload(
        tmp_path,
        {
            "request": "resume old literature run",
            "stage_id": stage["id"],
            "candidates": [],
        },
    )
    assert resumed == path
    assert set(load_yaml(path)["budget"]) == {
        "max_queries",
        "max_candidates",
        "max_full_reads",
        "max_citation_hops",
    }


def test_literature_candidate_materialization_requires_current_user_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"]["candidates_seen"] = 1
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="selection gate",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=state,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INTAKE_SCRIPT),
            "--root",
            str(tmp_path),
            "add",
            "--kind",
            "paper",
            "--stage-id",
            path.stem,
            "--candidate-id",
            "paper-a",
        ],
    )
    with pytest.raises(SystemExit, match="requires user_authorization"):
        _intake_module().main()
    assert not list((tmp_path / "kb/units/papers").glob("*/record.yaml"))


def test_kb_root_symlink_is_rejected_before_staging(tmp_path: Path) -> None:
    backing = tmp_path / "backing"
    backing.mkdir()
    (tmp_path / "kb").symlink_to(backing, target_is_directory=True)
    with pytest.raises(SystemExit, match="unsafe path component"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="root symlink",
            candidates=[],
        )
    assert not (backing / "synthesis/source-search").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", "Authorization: Bearer sample-secret"),
        ("candidate", "access_token=sample-secret"),
    ],
)
def test_notes_cannot_persist_credentials(tmp_path: Path, field: str, value: str) -> None:
    kwargs: dict = {"note": value, "candidates": []}
    if field == "candidate":
        candidate = _candidate("paper-a", "https://example.test/a")
        candidate["note"] = value
        kwargs = {
            "note": "",
            "candidates": [candidate],
            "search_state": _state(queries=[_query("q1")], usage_queries=1),
        }
    with pytest.raises(SystemExit, match="sensitive request material"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="credential note",
            **kwargs,
        )
    assert not (tmp_path / "kb").exists()


def test_literature_selection_cannot_be_rebound_to_an_explicit_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"]["candidates_seen"] = 1
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="selection source binding",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=state,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INTAKE_SCRIPT),
            "--root",
            str(tmp_path),
            "add",
            "--kind",
            "paper",
            "--stage-id",
            path.stem,
            "--candidate-id",
            "paper-a",
            "--source",
            "https://example.test/b",
            "--user-authorization",
            "保留 paper-a",
            "--authorization-source",
            "user_message",
        ],
    )
    with pytest.raises(SystemExit, match="must be materialized from its staged source"):
        _intake_module().main()
    assert not list((tmp_path / "kb/units/papers").glob("*/record.yaml"))


def test_staged_candidate_cannot_be_materialized_as_a_different_source_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"]["candidates_seen"] = 1
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="kind binding",
        candidates=[_candidate("paper-a", "https://example.test/a")],
        search_state=state,
    )
    before = path.read_bytes()
    journal_before = {
        item.name: item.read_bytes() for item in (tmp_path / "kb/.journal").glob("*.yaml")
    }
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INTAKE_SCRIPT),
            "--root",
            str(tmp_path),
            "add",
            "--kind",
            "repo",
            "--stage-id",
            path.stem,
            "--candidate-id",
            "paper-a",
            "--user-authorization",
            "保留 paper-a",
            "--authorization-source",
            "user_message",
        ],
    )
    with pytest.raises(SystemExit, match="recorded source kind"):
        _intake_module().main()
    assert path.read_bytes() == before
    assert not list((tmp_path / "kb/units/repos").glob("*/record.yaml"))
    assert {
        item.name: item.read_bytes() for item in (tmp_path / "kb/.journal").glob("*.yaml")
    } == journal_before


def test_terminal_systematic_counts_must_match_candidate_ledger(tmp_path: Path) -> None:
    state = {
        "entry_skill": "literature-search",
        "mode": "systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["database export"],
            "date_range": "2020-2026",
            "result_depth": "all exported results",
            "screening": "single evidence-backed reviewer",
            "screeners": 1,
            "reproducible": True,
        },
        "budget": {
            "max_queries": 4,
            "max_candidates": 20,
            "max_full_reads": 4,
            "max_citation_hops": 2,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 1,
            "full_reads": 0,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [{**_query("q1"), "reproducible": True, "result_count": 1}],
        "coverage": {
            "round": 1,
            "flow_counts": {
                "identified": 1,
                "duplicates_removed": 0,
                "automation_excluded": 0,
                "title_abstract_screened": 1,
                "title_abstract_excluded": 0,
                "fulltext_sought": 1,
                "fulltext_unavailable": 0,
                "fulltext_assessed": 1,
                "excluded_with_reason": 0,
                "included": 1,
            },
        },
        "stop": {"reason": "target_met", "rationale": "The frozen target was reached."},
        "partial": False,
    }
    with pytest.raises(SystemExit, match="candidate ledger must cover"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="ghost inclusion",
            candidates=[],
            search_state=state,
        )


def test_terminal_systematic_unavailable_fulltext_must_match_candidate_fetch(
    tmp_path: Path,
) -> None:
    state = {
        "entry_skill": "literature-search",
        "mode": "bounded-systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["web-search"],
            "date_range": "2020-2026",
            "result_depth": "visible results",
            "screening": "single evidence-backed reviewer",
            "screeners": 1,
            "reproducible": False,
        },
        "budget": {
            "max_queries": 1,
            "max_candidates": 10,
            "max_full_reads": 2,
            "max_citation_hops": 1,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 1,
            "full_reads": 0,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [{**_query("q1"), "result_count": 1}],
        "coverage": {
            "round": 1,
            "flow_counts": {
                "identified": 1,
                "duplicates_removed": 0,
                "automation_excluded": 0,
                "title_abstract_screened": 1,
                "title_abstract_excluded": 0,
                "fulltext_sought": 1,
                "fulltext_unavailable": 1,
                "fulltext_assessed": 0,
                "excluded_with_reason": 0,
                "included": 0,
            },
        },
        "stop": {"reason": "target_met", "rationale": "Claimed completion."},
        "partial": True,
    }
    with pytest.raises(SystemExit, match="unavailable fulltexts must match"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="unavailable contradiction",
            candidates=[_candidate("paper-a", "https://example.test/a")],
            search_state=state,
        )


def test_terminal_systematic_query_and_discovery_occurrences_are_fully_reconciled(
    tmp_path: Path,
) -> None:
    scope = {
        "inclusion": ["peer-reviewed"],
        "exclusion": ["non-research"],
        "languages": ["en"],
        "source_types": ["paper"],
        "channels": ["web-search"],
        "date_range": "2020-2026",
        "result_depth": "visible results",
        "screening": "single evidence-backed reviewer",
        "screeners": 1,
        "reproducible": False,
    }
    budget = {
        "max_queries": 2,
        "max_candidates": 10,
        "max_full_reads": 2,
        "max_citation_hops": 1,
    }
    zero_flow = {
        "identified": 0,
        "duplicates_removed": 0,
        "automation_excluded": 0,
        "title_abstract_screened": 0,
        "title_abstract_excluded": 0,
        "fulltext_sought": 0,
        "fulltext_unavailable": 0,
        "fulltext_assessed": 0,
        "excluded_with_reason": 0,
        "included": 0,
    }
    with pytest.raises(SystemExit, match="must match recorded query results"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="omitted results",
            candidates=[],
            search_state={
                "entry_skill": "literature-search",
                "mode": "bounded-systematic",
                "scope": scope,
                "budget": budget,
                "usage": {"queries": 1, "candidates_seen": 0},
                "queries": [{**_query("q1"), "result_count": 7}],
                "coverage": {"round": 1, "flow_counts": zero_flow},
                "stop": {"reason": "target_met", "rationale": "Incorrectly empty."},
                "partial": True,
            },
        )

    flow_with_duplicates = {
        **zero_flow,
        "identified": 7,
        "duplicates_removed": 6,
        "title_abstract_screened": 1,
        "title_abstract_excluded": 1,
    }
    candidate = _title_excluded_candidate("only-one")
    with pytest.raises(SystemExit, match="discovery ledger must cover"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="ghost duplicates",
            candidates=[candidate],
            search_state={
                "entry_skill": "literature-search",
                "mode": "bounded-systematic",
                "scope": scope,
                "budget": budget,
                "usage": {"queries": 1, "candidates_seen": 7},
                "queries": [{**_query("q1"), "result_count": 7}],
                "coverage": {"round": 1, "flow_counts": flow_with_duplicates},
                "stop": {"reason": "target_met", "rationale": "Incomplete discovery ledger."},
                "partial": True,
            },
        )

    wrong_query_candidate = _title_excluded_candidate("wrong-query")
    wrong_query_candidate["discovered_by"][0]["query_id"] = "q2"
    for index in range(6):
        occurrence = dict(wrong_query_candidate["discovered_by"][0])
        occurrence["source_locator"] = f"q2 result {index + 2}"
        wrong_query_candidate["discovered_by"].append(occurrence)
    with pytest.raises(SystemExit, match="match each query result count"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="cross-query mismatch",
            candidates=[wrong_query_candidate],
            search_state={
                "entry_skill": "literature-search",
                "mode": "bounded-systematic",
                "scope": scope,
                "budget": budget,
                "usage": {"queries": 2, "candidates_seen": 7},
                "queries": [
                    {**_query("q1"), "result_count": 7},
                    {**_query("q2"), "result_count": 0},
                ],
                "coverage": {"round": 1, "flow_counts": flow_with_duplicates},
                "stop": {"reason": "target_met", "rationale": "Mismatched query ledger."},
                "partial": True,
            },
        )


def test_query_usage_must_equal_the_durable_event_ledger(tmp_path: Path) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"]["queries"] = 3
    with pytest.raises(SystemExit, match="must match the persisted query count"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="missing query events",
            candidates=[],
            search_state=state,
        )


def test_screening_fetch_and_frontier_terminal_states_cannot_regress(tmp_path: Path) -> None:
    first = _state(queries=[_query("q1")], usage_queries=1)
    first["usage"].update({"candidates_seen": 1, "full_reads": 1})
    first["frontier"] = [
        {
            "candidate_id": "paper-a",
            "direction": "backward",
            "priority_reason": "inspect references",
            "status": "expanded",
        }
    ]
    candidate = _screened_candidate("paper-a", "include")
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="monotonic resume",
        candidates=[candidate],
        search_state=first,
    )
    downgraded = _candidate(
        "paper-a",
        "https://example.test/paper-a",
        fetch_status="discovered",
        attempts=2,
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="monotonic resume",
        candidates=[downgraded],
        search_state={"usage": {"queries": 1, "candidates_seen": 10, "full_reads": 1}},
    )
    current = load_yaml(path)["candidates"][0]
    assert current["screening"]["decision"] == "include"
    assert current["fetch"]["status"] == "fetched"

    before = path.read_bytes()
    with pytest.raises(SystemExit, match="terminal status cannot regress"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="monotonic resume",
            candidates=[],
            search_state={
                "frontier": [
                    {
                        "candidate_id": "paper-a",
                        "direction": "backward",
                        "priority_reason": "retry old expansion",
                        "status": "pending",
                    }
                ]
            },
        )
    assert path.read_bytes() == before


def test_failed_terminal_fetch_and_completed_run_cannot_be_reopened(tmp_path: Path) -> None:
    state = _state(queries=[_query("q1")], usage_queries=1)
    candidate = _candidate(
        "paper-a",
        "https://example.test/a",
        fetch_status="failed_terminal",
        attempts=1,
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="terminal fetch",
        candidates=[candidate],
        search_state=state,
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="terminal fetch",
        candidates=[
            _candidate(
                "paper-a",
                "https://example.test/a",
                fetch_status="discovered",
                attempts=2,
            )
        ],
        search_state={"usage": {"queries": 1, "candidates_seen": 10}},
    )
    assert load_yaml(path)["candidates"][0]["fetch"]["status"] == "failed_terminal"

    stopped = _state()
    stopped["stop"] = {"reason": "user_stop", "rationale": "The user ended this run."}
    stopped_path = stage_search_results(
        tmp_path,
        kind="paper",
        query="completed run",
        candidates=[],
        search_state=stopped,
    )
    before = stopped_path.read_bytes()
    with pytest.raises(SystemExit, match="cannot be resumed"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="completed run",
            stage_id=stopped_path.stem,
            candidates=[],
            search_state={"stop": {"reason": "in_progress"}},
        )
    assert stopped_path.read_bytes() == before


def test_systematic_time_multi_reviewer_and_terminal_stop_contracts_fail_closed(
    tmp_path: Path,
) -> None:
    base_scope = {
        "inclusion": ["peer-reviewed"],
        "exclusion": ["non-research"],
        "languages": ["en"],
        "source_types": ["paper"],
        "channels": ["database export"],
        "date_range": "2020-2026",
        "result_depth": "all exported results",
        "screening": "evidence-backed screening",
        "screeners": 1,
        "reproducible": True,
    }
    budget = {
        "max_queries": 4,
        "max_candidates": 20,
        "max_full_reads": 4,
        "max_citation_hops": 2,
    }
    multi_path = stage_search_results(
        tmp_path,
        kind="paper",
        query="supported double screening",
        candidates=[],
        search_state={
            "entry_skill": "literature-search",
            "mode": "systematic",
            "scope": {**base_scope, "screeners": 2, "disagreement_resolution": "third reviewer"},
            "review_protocol": {
                "required_reviewer_ids": ["reviewer-a", "reviewer-b"],
                "mode": "independent",
                "phases": ["title_abstract", "fulltext"],
                "adjudication_mode": "third_reviewer",
            },
            "reviewers": [
                {"reviewer_id": "reviewer-a", "actor_type": "agent", "execution_id": "exec-a"},
                {"reviewer_id": "reviewer-b", "actor_type": "agent", "execution_id": "exec-b"},
            ],
            "budget": budget,
            "usage": {"queries": 0, "candidates_seen": 0, "full_reads": 0, "citation_hops": 0},
            "queries": [],
            "stop": {"reason": "in_progress"},
            "partial": True,
        },
    )
    assert load_yaml(multi_path)["review_protocol"]["mode"] == "independent"

    naive_query = {**_query("q1"), "searched_at": "2026-07-24", "reproducible": True}
    with pytest.raises(SystemExit, match="include a timezone"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="timezone required",
            candidates=[],
            search_state={
                "entry_skill": "literature-search",
                "mode": "systematic",
                "scope": base_scope,
                "budget": budget,
                "usage": {"queries": 1},
                "queries": [naive_query],
                "stop": {"reason": "in_progress"},
            },
        )

    with pytest.raises(SystemExit, match="complete screening flow counts"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="stopped systematic search",
            candidates=[],
            search_state={
                "entry_skill": "literature-search",
                "mode": "systematic",
                "scope": base_scope,
                "budget": budget,
                "usage": {
                    "queries": 0,
                    "candidates_seen": 0,
                    "full_reads": 0,
                    "citation_hops": 0,
                },
                "queries": [],
                "stop": {"reason": "user_stop", "rationale": "The user stopped the run."},
                "partial": True,
            },
        )

    with pytest.raises(SystemExit, match="cannot claim budget_exhausted"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="premature budget stop",
            candidates=[],
            search_state={
                "entry_skill": "literature-search",
                "mode": "exploratory",
                "budget": budget,
                "usage": {
                    "queries": 1,
                    "candidates_seen": 1,
                    "full_reads": 0,
                    "citation_hops": 0,
                },
                "queries": [_query("q1")],
                "stop": {"reason": "budget_exhausted", "rationale": "Claimed too early."},
                "partial": True,
            },
        )


def _reviewer_decision(
    decision_id: str,
    reviewer_id: str,
    decision: str,
    *,
    phase: str = "fulltext",
    supersedes: str = "",
) -> dict:
    item = {
        "decision_id": decision_id,
        "reviewer_id": reviewer_id,
        "phase": phase,
        "decision": decision,
        "basis": "fulltext" if phase == "fulltext" else "abstract",
        "rationale": f"{reviewer_id} independently chose {decision}.",
        "evidence": [{"quote": f"{reviewer_id} evidence", "locator": phase}],
        "decided_at": "2026-07-24T01:00:00+00:00",
    }
    if supersedes:
        item["supersedes_decision_id"] = supersedes
    return item


def _multi_reviewer_state(*, terminal: bool = False, duplicate_execution: bool = False) -> dict:
    query = {**_query("q1"), "result_count": 1, "reproducible": True}
    state = {
        "entry_skill": "literature-search",
        "mode": "systematic",
        "scope": {
            "inclusion": ["peer-reviewed"],
            "exclusion": ["non-research"],
            "languages": ["en"],
            "source_types": ["paper"],
            "channels": ["database export"],
            "date_range": "2020-2026",
            "result_depth": "all exported results",
            "screening": "two evidence-backed reviewers",
            "screeners": 2,
            "disagreement_resolution": "third reviewer",
            "reproducible": True,
        },
        "review_protocol": {
            "required_reviewer_ids": ["reviewer-a", "reviewer-b"],
            "mode": "independent",
            "phases": ["title_abstract", "fulltext"],
            "adjudication_mode": "third_reviewer",
        },
        "reviewers": [
            {"reviewer_id": "reviewer-a", "actor_type": "agent", "execution_id": "exec-a"},
            {
                "reviewer_id": "reviewer-b",
                "actor_type": "agent",
                "execution_id": "exec-a" if duplicate_execution else "exec-b",
            },
            {"reviewer_id": "reviewer-c", "actor_type": "agent", "execution_id": "exec-c"},
        ],
        "budget": {
            "max_queries": 4,
            "max_candidates": 20,
            "max_full_reads": 4,
            "max_citation_hops": 2,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 1,
            "full_reads": 1,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [query],
        "coverage": {"round": 1, "covered_facets": ["main facet"], "uncovered_facets": []},
        "stop": {"reason": "in_progress"},
        "partial": True,
    }
    if terminal:
        state["coverage"]["flow_counts"] = {
            "identified": 1,
            "duplicates_removed": 0,
            "automation_excluded": 0,
            "title_abstract_screened": 1,
            "title_abstract_excluded": 0,
            "fulltext_sought": 1,
            "fulltext_unavailable": 0,
            "fulltext_assessed": 1,
            "excluded_with_reason": 0,
            "included": 1,
        }
        state["stop"] = {"reason": "target_met", "rationale": "The frozen target was met."}
        state["partial"] = False
    return state


def _multi_candidate(decisions: list[dict], adjudications: list[dict] | None = None) -> dict:
    candidate = _candidate("paper-multi", "https://example.test/paper-multi")
    candidate.pop("screening")
    candidate["evidence_level"] = "fulltext"
    candidate["screening_decisions"] = decisions
    if adjudications is not None:
        candidate["adjudications"] = adjudications
    return candidate


def test_multi_reviewer_consensus_derives_effective_screening(tmp_path: Path) -> None:
    candidate = _multi_candidate(
        [
            _reviewer_decision("decision-a", "reviewer-a", "include"),
            _reviewer_decision("decision-b", "reviewer-b", "include"),
        ]
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="multi reviewer consensus",
        candidates=[candidate],
        search_state=_multi_reviewer_state(terminal=True),
    )

    persisted = load_yaml(path)["candidates"][0]
    assert persisted["effective_screening"]["status"] == "consensus"
    assert persisted["effective_screening"]["decision"] == "include"
    assert persisted["effective_screening"]["phase"] == "fulltext"
    assert len(persisted["screening_decisions"]) == 2


def test_multi_reviewer_conflict_requires_adjudication_before_terminal_stop(tmp_path: Path) -> None:
    candidate = _multi_candidate(
        [
            _reviewer_decision("decision-a", "reviewer-a", "include"),
            _reviewer_decision("decision-b", "reviewer-b", "exclude"),
        ]
    )
    with pytest.raises(SystemExit, match="complete screening and adjudication"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="multi reviewer conflict",
            candidates=[candidate],
            search_state=_multi_reviewer_state(terminal=True),
        )


def test_multi_reviewer_third_reviewer_adjudication_preserves_original_decisions(
    tmp_path: Path,
) -> None:
    decisions = [
        _reviewer_decision("decision-a", "reviewer-a", "include"),
        _reviewer_decision("decision-b", "reviewer-b", "exclude"),
    ]
    candidate = _multi_candidate(
        decisions,
        [
            {
                "adjudication_id": "adjudication-c",
                "phase": "fulltext",
                "input_decision_ids": ["decision-a", "decision-b"],
                "status": "resolved",
                "final_decision": "include",
                "resolved_by": "reviewer-c",
                "rationale": "The full method satisfies the frozen criteria.",
                "evidence": [{"quote": "adjudication evidence", "locator": "fulltext"}],
                "resolved_at": "2026-07-24T02:00:00+00:00",
            }
        ],
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="multi reviewer adjudication",
        candidates=[candidate],
        search_state=_multi_reviewer_state(terminal=True),
    )

    persisted = load_yaml(path)["candidates"][0]
    assert persisted["effective_screening"]["status"] == "adjudicated"
    assert persisted["effective_screening"]["decision"] == "include"
    assert [item["decision"] for item in persisted["screening_decisions"]] == ["include", "exclude"]
    assert persisted["adjudications"][0]["input_digest"]


def test_independent_reviewers_cannot_share_an_execution_context(tmp_path: Path) -> None:
    before = list(tmp_path.rglob("*"))
    with pytest.raises(SystemExit, match="distinct execution/context ids"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="fake independent reviewers",
            candidates=[],
            search_state=_multi_reviewer_state(duplicate_execution=True),
        )
    assert list(tmp_path.rglob("*")) == before


def test_reviewer_decisions_are_append_only_and_supersede_explicitly(tmp_path: Path) -> None:
    first = _multi_candidate(
        [
            _reviewer_decision("decision-a", "reviewer-a", "include"),
            _reviewer_decision("decision-b", "reviewer-b", "include"),
        ]
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="review decision history",
        candidates=[first],
        search_state=_multi_reviewer_state(),
    )
    update = _multi_candidate(
        [
            _reviewer_decision(
                "decision-a2",
                "reviewer-a",
                "exclude",
                supersedes="decision-a",
            )
        ]
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="review decision history",
        stage_id=path.stem,
        candidates=[update],
        search_state={},
    )

    persisted = load_yaml(path)["candidates"][0]
    assert [item["decision_id"] for item in persisted["screening_decisions"]] == [
        "decision-a",
        "decision-b",
        "decision-a2",
    ]
    assert persisted["effective_screening"]["status"] == "conflict"


def test_human_reviewer_and_user_adjudication_require_current_message_attestation(
    tmp_path: Path,
) -> None:
    state = _multi_reviewer_state()
    state["reviewers"][1] = {
        "reviewer_id": "reviewer-b",
        "actor_type": "human",
        "execution_id": "exec-b",
    }
    with pytest.raises(SystemExit, match="current user-message attestation"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="human reviewer attestation",
            candidates=[],
            search_state=state,
        )


def test_multi_reviewer_phase_order_and_adjudicator_mode_fail_closed(tmp_path: Path) -> None:
    reversed_state = _multi_reviewer_state()
    reversed_state["review_protocol"]["phases"] = ["fulltext", "title_abstract"]
    with pytest.raises(SystemExit, match="canonical screening order"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="reversed screening phases",
            candidates=[],
            search_state=reversed_state,
        )

    conflict = [
        _reviewer_decision("decision-a", "reviewer-a", "include"),
        _reviewer_decision("decision-b", "reviewer-b", "exclude"),
    ]
    self_adjudicated = _multi_candidate(
        conflict,
        [{
            "adjudication_id": "adjudication-self",
            "phase": "fulltext",
            "input_decision_ids": ["decision-a", "decision-b"],
            "status": "resolved",
            "final_decision": "include",
            "resolved_by": "reviewer-a",
            "rationale": "The original reviewer tried to resolve the conflict.",
            "evidence": [{"quote": "adjudication evidence", "locator": "fulltext"}],
            "resolved_at": "2026-07-24T02:00:00+00:00",
        }],
    )
    with pytest.raises(SystemExit, match="distinct reviewer"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="self adjudication",
            candidates=[self_adjudicated],
            search_state=_multi_reviewer_state(),
        )

    user_state = _multi_reviewer_state()
    user_state["review_protocol"]["adjudication_mode"] = "user"
    user_state["scope"]["disagreement_resolution"] = "user"
    agent_adjudication = _multi_candidate(
        conflict,
        [{
            "adjudication_id": "adjudication-agent",
            "phase": "fulltext",
            "input_decision_ids": ["decision-a", "decision-b"],
            "status": "resolved",
            "final_decision": "include",
            "resolved_by": "reviewer-c",
            "rationale": "An Agent cannot resolve a user-mode conflict.",
            "evidence": [{"quote": "adjudication evidence", "locator": "fulltext"}],
            "resolved_at": "2026-07-24T02:00:00+00:00",
        }],
    )
    with pytest.raises(SystemExit, match="current user"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="user mode agent adjudication",
            candidates=[agent_adjudication],
            search_state=user_state,
        )


def test_multi_reviewer_decision_ledger_cannot_return_to_earlier_phase(tmp_path: Path) -> None:
    first = _multi_candidate(
        [
            _reviewer_decision("full-a", "reviewer-a", "include", phase="fulltext"),
            _reviewer_decision("full-b", "reviewer-b", "include", phase="fulltext"),
        ]
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="phase regression",
        candidates=[first],
        search_state=_multi_reviewer_state(),
    )
    before = path.read_bytes()
    regressed = _multi_candidate(
        [
            _reviewer_decision("title-a", "reviewer-a", "include", phase="title_abstract"),
            _reviewer_decision("title-b", "reviewer-b", "include", phase="title_abstract"),
        ]
    )
    with pytest.raises(SystemExit, match="cannot return to an earlier phase"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="phase regression",
            stage_id=path.stem,
            candidates=[regressed],
            search_state={},
        )
    assert path.read_bytes() == before


def test_persisted_multi_reviewer_ledger_reordering_fails_closed(tmp_path: Path) -> None:
    title = _multi_candidate(
        [
            _reviewer_decision("title-a", "reviewer-a", "include", phase="title_abstract"),
            _reviewer_decision("title-b", "reviewer-b", "include", phase="title_abstract"),
        ]
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="persisted phase reorder",
        candidates=[title],
        search_state=_multi_reviewer_state(),
    )
    fulltext = _multi_candidate(
        [
            _reviewer_decision("full-a", "reviewer-a", "include", phase="fulltext"),
            _reviewer_decision("full-b", "reviewer-b", "include", phase="fulltext"),
        ]
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="persisted phase reorder",
        stage_id=path.stem,
        candidates=[fulltext],
        search_state={},
    )
    payload = load_yaml(path)
    decisions = payload["candidates"][0]["screening_decisions"]
    payload["candidates"][0]["screening_decisions"] = [*decisions[2:], *decisions[:2]]
    write_yaml_if_changed(path, payload)
    tampered = path.read_bytes()

    with pytest.raises(SystemExit, match="cannot return to an earlier phase"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="persisted phase reorder",
            stage_id=path.stem,
            candidates=[],
            search_state={},
        )
    assert path.read_bytes() == tampered


def test_pending_adjudication_can_be_resolved_append_only_and_replayed(tmp_path: Path) -> None:
    decisions = [
        _reviewer_decision("decision-a", "reviewer-a", "include"),
        _reviewer_decision("decision-b", "reviewer-b", "exclude"),
    ]
    pending = _multi_candidate(
        decisions,
        [{
            "adjudication_id": "adjudication-pending",
            "phase": "fulltext",
            "input_decision_ids": ["decision-a", "decision-b"],
            "status": "pending",
        }],
    )
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="pending then resolved adjudication",
        candidates=[pending],
        search_state=_multi_reviewer_state(),
    )
    resolved = _multi_candidate(
        [],
        [{
            "adjudication_id": "adjudication-resolved",
            "phase": "fulltext",
            "input_decision_ids": ["decision-a", "decision-b"],
            "status": "resolved",
            "final_decision": "include",
            "resolved_by": "reviewer-c",
            "rationale": "The third reviewer resolved the persisted conflict.",
            "evidence": [{"quote": "adjudication evidence", "locator": "fulltext"}],
            "resolved_at": "2026-07-24T02:00:00+00:00",
        }],
    )
    stage_search_results(
        tmp_path,
        kind="paper",
        query="pending then resolved adjudication",
        stage_id=path.stem,
        candidates=[resolved],
        search_state={},
    )
    persisted = load_yaml(path)["candidates"][0]
    assert [item["status"] for item in persisted["adjudications"]] == ["pending", "resolved"]
    assert persisted["effective_screening"]["status"] == "adjudicated"
    stage_search_results(
        tmp_path,
        kind="paper",
        query="pending then resolved adjudication",
        stage_id=path.stem,
        candidates=[persisted],
        search_state={},
    )


def test_persisted_decision_tamper_and_multi_automation_exclusion(tmp_path: Path) -> None:
    candidate = _multi_candidate([
        _reviewer_decision("decision-a", "reviewer-a", "exclude"),
        _reviewer_decision("decision-b", "reviewer-b", "exclude"),
    ])
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="tamper decision ledger",
        candidates=[candidate],
        search_state=_multi_reviewer_state(),
    )
    payload = load_yaml(path)
    payload["candidates"][0]["screening_decisions"][0]["decision"] = "include"
    write_yaml_if_changed(path, payload)
    with pytest.raises(SystemExit, match="decision digest"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="tamper decision ledger",
            stage_id=path.stem,
            candidates=[],
            search_state={},
        )

    automation = _candidate("paper-automation", "https://example.test/paper-automation")
    automation["evidence_level"] = "abstract"
    automation["screening"] = {
        "decision": "exclude",
        "phase": "automation",
        "basis": "abstract",
        "rationale": "The frozen mechanical duplicate rule excluded this record.",
        "evidence": [{"quote": "duplicate record", "locator": "abstract"}],
    }
    terminal = _multi_reviewer_state(terminal=True)
    terminal["usage"]["full_reads"] = 0
    terminal["coverage"]["flow_counts"].update(
        {
            "automation_excluded": 1,
            "title_abstract_screened": 0,
            "fulltext_sought": 0,
            "fulltext_assessed": 0,
            "included": 0,
        }
    )
    automation_path = stage_search_results(
        tmp_path,
        kind="paper",
        query="multi reviewer automation exclusion",
        candidates=[automation],
        search_state=terminal,
    )
    effective = load_yaml(automation_path)["candidates"][0]["effective_screening"]
    assert effective["status"] == "automation-excluded"
    assert effective["phase"] == "automation"


def test_generic_source_intake_search_cannot_bypass_literature_search_for_papers() -> None:
    with pytest.raises(SystemExit):
        _intake_module().build_parser().parse_args(
            ["search", "--kind", "paper", "--query", "bypass"]
        )

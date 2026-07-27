from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import append_list_item, load_yaml, write_yaml_if_changed
from research.monitoring import (
    create_due_run,
    create_subscription,
    finish_run,
    load_run,
    load_subscription,
    run_path,
    transition_run,
    value_digest,
)
from research.paths import runtime_preferences_path
from research.preference_selection import eligible_preferences, record_effective_selection
from research.prefs import default_runtime_preferences
from research.sources import (
    literature_search_continuations,
    mark_search_candidate,
    stage_search_results,
)


def _project_root() -> Path:
    return REPO_ROOT


def _load_orchestrator(module_name: str):
    script = _project_root() / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py"
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    return root


def _program(orchestrate, root: Path, program_id: str, *, actions: list[str] | None = None) -> None:
    orchestrate.ensure_program_files(root, program_id)
    state = orchestrate.load_state(root, program_id)
    state.update(
        {
            "program_id": program_id,
            "status": "active",
            "stage": "literature-review",
            "question": f"What should {program_id} test?",
            "goal": f"Advance {program_id}",
            "next_actions": list(actions or []),
        }
    )
    write_yaml_if_changed(orchestrate.state_path(root, program_id), state)


def _effective_preference_selection(root: Path, task_context: dict[str, object]) -> str:
    eligible = eligible_preferences(root, skill="research-orchestrator", operation="plan")
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {"preference_id": item["preference_id"], "reason": "considered for portfolio planning"}
        if item["strength"] == "hard":
            selected.append({**row, "application": "respect the declared boundary"})
        else:
            excluded.append(row)
    selection_id = "prefsel-portfolio01"
    path = root / "kb" / "config" / "effective-preferences" / f"{selection_id}.yaml"
    if not path.exists():
        record_effective_selection(
            root,
            {
                "selection_id": selection_id,
                "skill": "research-orchestrator",
                "operation": "plan",
                "catalog_digest": eligible["catalog_digest"],
                "task_context": task_context,
                "selected": selected,
                "excluded": excluded,
            },
        )
    return selection_id


def _decision(root: Path, snapshot: dict, action_ids: list[str], *, decision_id: str = "portfolio-001") -> dict:
    return {
        "decision_id": decision_id,
        "candidate_snapshot_digest": snapshot["candidate_snapshot_digest"],
        "selected_action_ids": action_ids,
        "rationale": "This action addresses the current evidence gap; the other candidates can wait.",
        "expected_information_gain": "It will distinguish the two remaining hypotheses.",
        "cost_and_risk": "One short analysis pass; no external commitment.",
        "preference_selection_id": _effective_preference_selection(
            root,
            {
                "candidate_snapshot_digest": snapshot["candidate_snapshot_digest"],
                "scope": snapshot["scope"],
                "candidate_action_ids": sorted(
                    item["action_id"] for item in snapshot["candidates"]
                ),
            },
        ),
        "decision_scope": "procedural_planning",
        "program_decision_ids": [],
        "decided_at": "2026-07-24T12:00:00+08:00",
    }


def _verified_program_decision(orchestrate, root: Path, *, confirmed: bool = False) -> tuple[dict, Path]:
    _program(orchestrate, root, "program-a")
    evidence_path = root / "kb" / "programs" / "program-a" / "decision-evidence.md"
    evidence_path.write_text("The benchmark supports route A.\n", encoding="utf-8")
    claims = [
        {
            "id": "claim-route-a",
            "text": "Route A is the preferred baseline.",
            "claim_type": "evaluation",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": "program:program-a",
                    "artifact": "decision-evidence.md",
                    "locator": "benchmark",
                    "quote": "The benchmark supports route A.",
                }
            ],
        }
    ]
    record = {
        "id": "decision-1",
        "kind": "program_decision",
        "owner": "research-orchestrator",
        "timestamp": "2026-07-24T00:00:00+00:00",
        "program_id": "program-a",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["inference", "evaluation", "unverified"],
        "payload": {
            "decision": {
                "text": "OLD_SENTINEL route A",
                "rationale": "The benchmark is decisive.",
                "stage": "literature-review",
                "alternatives": ["route B"],
            },
            "claims": claims,
        },
    }
    source_roots = orchestrate._decision_source_roots(root, "program-a", claims)
    orchestrate.build_verification_receipt(
        record,
        orchestrate.program_root(root, "program-a"),
        source_roots=source_roots,
    )
    if confirmed:
        orchestrate.apply_confirmation(
            record,
            confirmed_by="Alice Researcher",
            evidence=["Reviewed the decision."],
            user_authorization="I confirm route A.",
            authorization_source="user_message",
            project_root=root,
            verification_root=orchestrate.program_root(root, "program-a"),
            trusted_source_roots=source_roots,
        )
    path, _projection = orchestrate.write_decisions(root, "program-a", [record])
    return record, path


def _contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(_contains_key(item, forbidden) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _active_monitor(root: Path) -> tuple[dict, dict]:
    create_subscription(
        root,
        {
            "subscription_id": "monitor-active",
            "kind": "literature",
            "title": "Track active monitor",
            "target": {"question": "What changed in active monitoring?"},
            "scope": {"facets": ["recovery"]},
            "cadence": {
                "every_days": 7,
                "timezone": "UTC",
                "anchor_at": "2026-07-01T00:00:00Z",
            },
            "budget": {"max_queries": 2},
            "program_ids": [],
        },
        now="2026-07-01T00:00:00Z",
    )
    create_due_run(
        root,
        "monitor-active",
        expected_subscription_revision=1,
        now="2026-07-01T00:00:00Z",
    )
    subscription = load_subscription(root, "monitor-active")
    return subscription, load_run(root, subscription["active_run_id"])


def _literature_candidate(candidate_id: str, decision: str = "include") -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "title": f"Private title for {candidate_id}",
        "url": f"https://example.test/{candidate_id}",
        "identities": {"doi": f"10.1234/{candidate_id}"},
        "discovered_by": [
            {
                "query_id": "q1",
                "edge_type": "direct",
                "source_locator": "private provider result",
                "channel": "web-search",
                "tool": "runtime-search",
                "discovered_at": "2026-07-24T00:00:00+00:00",
            }
        ],
        "fetch": {"status": "fetched", "attempts": 1},
        "evidence_level": "fulltext",
        "screening": {
            "decision": decision,
            "basis": "fulltext",
            "rationale": "Private screening rationale.",
            "evidence": [{"quote": "private evidence", "locator": "results"}],
            "reviewer": "runtime-agent",
        },
    }


def _literature_state(stop_reason: str, *, monitor: bool = False) -> dict[str, object]:
    state: dict[str, object] = {
        "entry_skill": "literature-search",
        "mode": "exploratory",
        "scope": {"facets": ["private facet"], "target_count": 1},
        "budget": {
            "max_queries": 2,
            "max_candidates": 10,
            "max_full_reads": 2,
            "max_citation_hops": 1,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 1,
            "full_reads": 1,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [
            {
                "query_id": "q1",
                "text": "private original query",
                "intent": "seed",
                "facet": "private facet",
                "channel": "web-search",
                "tool": "runtime-search",
                "selection_reason": "private tool rationale",
                "searched_at": "2026-07-24T00:00:00+00:00",
                "result_depth": "first page",
                "result_count": 1,
                "outcome": "success",
                "reproducible": False,
            }
        ],
        "coverage": {
            "round": 1,
            "covered_facets": ["private facet"],
            "uncovered_facets": [],
            "new_candidates": 1,
            "deduplicated": 0,
            "new_relevant": 1,
        },
        "frontier": [],
        "stop": {"reason": stop_reason},
        "partial": stop_reason not in {"target_met", "saturated", "budget_exhausted", "user_stop"},
    }
    if stop_reason != "in_progress":
        state["stop"] = {"reason": stop_reason, "rationale": "Private stopping rationale."}
    if monitor:
        state["run_id"] = "monitor-run-1"
        state["monitor_binding"] = {"run_id": "monitor-run-1", "task_digest": "a" * 64}
    return state


def _stage_literature_search(
    root: Path,
    *,
    query: str,
    stop_reason: str,
    candidate_id: str = "candidate-a",
    monitor: bool = False,
) -> Path:
    return stage_search_results(
        root,
        kind="paper",
        query=query,
        candidates=[_literature_candidate(candidate_id)],
        note="private operator note",
        search_state=_literature_state(stop_reason, monitor=monitor),
    )


def test_candidate_snapshot_is_deterministic_complete_and_has_no_winner_score(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_snapshot")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Write survey", "Design experiment"])
    _program(orchestrate, root, "program-b", actions=["Inspect failure cases"])
    append_list_item(
        orchestrate.evidence_requests_path(root, "program-b"),
        "program-b-evidence-requests",
        "research-orchestrator",
        {
            "question": "Does the baseline reproduce?",
            "needed": "Parity logs",
            "priority": "critical",
            "blocking": True,
        },
        default_status="open",
    )

    first = orchestrate.portfolio_candidate_snapshot(root)
    second = orchestrate.portfolio_candidate_snapshot(root)

    assert first == second
    assert first["candidate_snapshot_digest"] == second["candidate_snapshot_digest"]
    assert not _contains_key(first, "score")
    assert {item["reason"] for item in first["candidates"] if item["action_type"] == "persisted-program-action"} == {
        "Write survey",
        "Design experiment",
        "Inspect failure cases",
    }
    blockers = [item for item in first["candidates"] if item["blocking"]]
    assert len(blockers) == 1
    assert blockers[0]["reason"] == "Resolve evidence request: Parity logs"
    # Blocking work precedes other pending work; identity is only the stable tie-break.
    assert first["candidates"][0]["blocking"] is True
    assert [item["action_id"] for item in first["candidates"][1:]] == sorted(
        item["action_id"] for item in first["candidates"][1:]
    )


def test_portfolio_decision_rejects_more_than_three_next_steps(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_three_step_limit")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["One", "Two", "Three", "Four"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    action_ids = [item["action_id"] for item in snapshot["candidates"][:4]]
    decision = _decision(root, snapshot, action_ids)

    with pytest.raises(SystemExit, match="at most three"):
        orchestrate.validate_portfolio_decision(root, decision, snapshot)


def test_terminal_program_has_context_but_no_candidate(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_terminal")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "finished", actions=["Must not reopen"])
    state = orchestrate.load_state(root, "finished")
    state["stage"] = "completed"
    state["status"] = "completed"
    write_yaml_if_changed(orchestrate.state_path(root, "finished"), state)

    snapshot = orchestrate.portfolio_candidate_snapshot(root)

    assert snapshot["program_contexts"][0]["program_id"] == "finished"
    assert snapshot["candidates"] == []


@pytest.mark.parametrize("orphan_kind", ["missing", "symlink"])
def test_unit_linked_only_to_noncanonical_program_remains_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    orphan_kind: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_orphan_{orphan_kind}")
    root = _workspace(tmp_path)
    programs = root / "kb" / "programs"
    programs.mkdir(parents=True)
    if orphan_kind == "symlink":
        outside = tmp_path / "outside-program"
        outside.mkdir()
        (programs / "missing-program").symlink_to(outside, target_is_directory=True)
    record = {
        "id": "r-orphan-linked",
        "kind": "repo",
        "title": "Orphan-linked repository",
        "status": "active",
        "program_ids": ["missing-program"],
        "payload": {},
    }
    monkeypatch.setattr(orchestrate, "iter_records", lambda _root: [record])
    monkeypatch.setattr(orchestrate, "discover_pending_judgements", lambda _root: [])
    monkeypatch.setattr(
        orchestrate,
        "safe_unit_step",
        lambda current: {
            "kind": "agent-work",
            "step_type": "generate-note",
            "reason": "The canonical repository still needs analysis.",
            "safe_execute": False,
            "command_parts": [],
        }
        if current["id"] == record["id"]
        else None,
    )

    snapshot = orchestrate.portfolio_candidate_snapshot(root)

    candidate = next(
        item for item in snapshot["candidates"] if item["subject"]["id"] == record["id"]
    )
    assert candidate["program_id"] == "loose:r-orphan-linked"
    assert candidate["action_type"] == "generate-note"


def test_due_monitor_is_a_factual_candidate_not_an_automatic_winner(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_due_monitor")
    root = _workspace(tmp_path)
    create_subscription(
        root,
        {
            "kind": "literature",
            "title": "Track retrieval papers",
            "target": {"question": "What changed in retrieval?"},
            "scope": {"facets": ["retrieval"]},
            "cadence": {
                "every_days": 7,
                "timezone": "Asia/Shanghai",
                "anchor_at": "2026-07-01T09:00:00+08:00",
            },
            "budget": {"max_queries": 2},
            "program_ids": [],
        },
        now="2026-07-01T01:00:00+00:00",
    )

    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    monitor = next(item for item in snapshot["candidates"] if item["action_type"] == "run-due-monitor")

    assert monitor["owner_skill"] == "research-monitor"
    assert monitor["safe_execute_capability"] is False
    assert "score" not in monitor
    assert monitor["dependencies"][0]["due_at"] == "2026-07-01T01:00:00+00:00"


@pytest.mark.parametrize("state", ["planned", "running", "blocked", "failed_retryable"])
def test_active_monitor_run_is_a_resume_candidate_in_every_nonterminal_state(
    tmp_path: Path,
    state: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_active_monitor_{state}")
    root = _workspace(tmp_path)
    subscription, run = _active_monitor(root)
    if state != "planned":
        transition_run(
            root,
            run["id"],
            expected_revision=run["revision"],
            state="running",
            now="2026-07-01T00:01:00Z",
        )
        run = load_run(root, run["id"])
    if state in {"blocked", "failed_retryable"}:
        transition_run(
            root,
            run["id"],
            expected_revision=run["revision"],
            state=state,
            stop={"reason": state, "rationale": f"The run is {state}."},
            now="2026-07-01T00:02:00Z",
        )
        run = load_run(root, run["id"])

    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    resume = next(
        item for item in snapshot["candidates"] if item["action_type"] == "resume-monitor-run"
    )
    dependency = resume["dependencies"][0]

    assert all(item["action_type"] != "run-due-monitor" for item in snapshot["candidates"])
    assert resume["subject"] == {"kind": "research-monitor-run", "id": run["id"]}
    assert dependency["subscription_status"] == subscription["status"]
    assert dependency["subscription_revision"] == subscription["revision"]
    assert dependency["run_state"] == state
    assert dependency["run_revision"] == run["revision"]
    assert dependency["run_content_digest"] == run["content_digest"]
    assert dependency["stop"] == run["stop"]


def test_terminal_monitor_run_is_excluded_and_bad_active_link_fails_closed(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_terminal_monitor")
    root = _workspace(tmp_path)
    subscription, run = _active_monitor(root)
    finish_run(
        root,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="cancelled",
        stop={"reason": "cancelled", "rationale": "The user cancelled the run."},
        now="2026-07-01T00:03:00Z",
    )
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    assert all(item["action_type"] != "resume-monitor-run" for item in snapshot["candidates"])

    subscription_path_value = root / "kb/monitoring/subscriptions/monitor-active.yaml"
    broken = load_yaml(subscription_path_value)
    broken["active_run_id"] = "missing-run"
    write_yaml_if_changed(subscription_path_value, broken)
    with pytest.raises(SystemExit, match="does not exist|invalid active run link"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_standalone_literature_search_resume_and_selection_are_portfolio_candidates(
    tmp_path: Path,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_standalone_literature")
    root = _workspace(tmp_path)
    running = _stage_literature_search(
        root,
        query="private running question",
        stop_reason="in_progress",
        candidate_id="running-a",
    )
    terminal = _stage_literature_search(
        root,
        query="private terminal question",
        stop_reason="target_met",
        candidate_id="terminal-a",
    )

    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    resume = next(item for item in snapshot["candidates"] if item["action_type"] == "resume-literature-search")
    select = next(item for item in snapshot["candidates"] if item["action_type"] == "select-literature-candidates")

    assert resume["subject"] == {"kind": "literature-search-stage", "id": running.stem}
    assert resume["owner_skill"] == "literature-search"
    assert resume["governance_gate"] == "none"
    assert select["subject"] == {"kind": "literature-search-stage", "id": terminal.stem}
    assert select["owner_skill"] == "literature-search"
    assert select["governance_gate"] == "human-decision"
    dependency = select["dependencies"][0]
    assert dependency["stage_byte_sha256"] == hashlib.sha256(terminal.read_bytes()).hexdigest()
    assert dependency["stop_reason"] == "target_met"
    assert dependency["candidates"][0]["candidate_id"] == "terminal-a"
    assert len(dependency["candidates"][0]["identity_digest"]) == 64
    assert len(dependency["candidates"][0]["screening_digest"]) == 64
    private_dump = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    for secret in (
        "private running question",
        "private terminal question",
        "Private title",
        "https://example.test",
        "private operator note",
        "private evidence",
    ):
        assert secret not in private_dump


def test_stale_confirmed_survey_is_a_nonexecuting_portfolio_rebuild_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_stale_survey_gardening")
    root = _workspace(tmp_path)
    monkeypatch.setattr(
        orchestrate,
        "discover_stale_confirmed_surveys",
        lambda _root: [
            {
                "subject": {
                    "kind": "survey_judgement",
                    "id": "survey:survey:robot-learning",
                    "owner": "literature-synthesizer",
                    "path": "kb/synthesis/robot-learning/survey.yaml",
                },
                "slug": "robot-learning",
                "mode": "survey",
                "program_ids": ["program-a"],
                "stale_reasons": ["new matching unit: p-gamma"],
                "new_unit_ids": ["p-gamma"],
                "container_digest": "a" * 64,
                "survey_content_digest": "b" * 64,
            }
        ],
    )
    monkeypatch.setattr(
        orchestrate,
        "discover_pending_judgements",
        lambda _root: [
            {
                "subject": {
                    "kind": "program_decision",
                    "id": "decision-pending",
                    "owner": "research-orchestrator",
                    "path": "kb/programs/program-a/workflow/decisions.yaml",
                },
                "snapshot_binding": {"content_digest": "c" * 64},
                "priority": "critical",
                "confirm_route": {},
            }
        ],
    )

    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    candidate = next(
        item for item in snapshot["candidates"] if item["action_type"] == "rebuild-stale-survey"
    )

    assert candidate["owner_skill"] == "literature-synthesizer"
    assert candidate["governance_gate"] == "none"
    assert candidate["safe_execute_capability"] is False
    assert candidate["subject"] == {
        "kind": "survey_judgement",
        "id": "survey:survey:robot-learning",
    }
    assert candidate["dependencies"][0]["new_unit_ids"] == ["p-gamma"]
    stale_position = snapshot["candidates"].index(candidate)
    pending_position = next(
        index
        for index, item in enumerate(snapshot["candidates"])
        if item["action_type"] == "review-judgement"
    )
    assert stale_position < pending_position


def test_literature_stage_byte_or_materialization_change_updates_portfolio_exactly(
    tmp_path: Path,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_binding")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="binding question",
        stop_reason="target_met",
        candidate_id="binding-a",
    )
    before = orchestrate.portfolio_candidate_snapshot(root)
    before_action = next(
        item for item in before["candidates"] if item["action_type"] == "select-literature-candidates"
    )

    stage_path.write_bytes(stage_path.read_bytes() + b"\n# byte-only drift\n")
    after_bytes = orchestrate.portfolio_candidate_snapshot(root)
    after_action = next(
        item for item in after_bytes["candidates"] if item["action_type"] == "select-literature-candidates"
    )
    assert after_bytes["candidate_snapshot_digest"] != before["candidate_snapshot_digest"]
    assert after_action["dependencies"][0]["stage_byte_sha256"] != before_action["dependencies"][0]["stage_byte_sha256"]
    assert after_action["binding_digest"] != before_action["binding_digest"]

    mark_search_candidate(root, stage_path.stem, "binding-a", status="materialized", record_id="p-binding")
    materialized = orchestrate.portfolio_candidate_snapshot(root)
    assert all(item["action_type"] != "select-literature-candidates" for item in materialized["candidates"])


def test_monitor_and_composite_owned_literature_stages_are_not_double_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_owner_exclusion")
    root = _workspace(tmp_path)
    monitor_path = _stage_literature_search(
        root,
        query="monitor-owned question",
        stop_reason="in_progress",
        candidate_id="monitor-a",
        monitor=True,
    )
    composite_path = _stage_literature_search(
        root,
        query="composite-owned question",
        stop_reason="target_met",
        candidate_id="composite-a",
    )
    standalone_path = _stage_literature_search(
        root,
        query="standalone question",
        stop_reason="in_progress",
        candidate_id="standalone-a",
    )
    monkeypatch.setattr(
        orchestrate,
        "pending_composite_survey_states",
        lambda _root: [
            {
                "path": "kb/synthesis/composite-surveys/survey-a.yaml",
                "state_digest": "b" * 64,
                "state": {
                    "id": "survey-a",
                    "status": "in_progress",
                    "current_stage": "selection",
                    "revision": 2,
                    "selection_filters": {"query": "private composite query"},
                    "stages": [
                        {
                            "id": "search",
                            "status": "completed",
                            "outputs": [
                                {
                                    "kind": "composite-stage-binding",
                                    "stage_id": "search",
                                    "refs": [
                                        {
                                            "kind": "literature-search-stage",
                                            "stage_id": composite_path.stem,
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "selection",
                            "status": "in_progress",
                            "outputs": [],
                            "blocker": {},
                            "resume_action": "select candidates",
                        },
                    ],
                },
            }
        ],
    )

    snapshot = orchestrate.portfolio_candidate_snapshot(root)

    assert all(item["subject"]["id"] != monitor_path.stem for item in snapshot["candidates"])
    assert any(
        item["action_type"] == "resume-literature-search"
        and item["subject"]["id"] == standalone_path.stem
        for item in snapshot["candidates"]
    )
    assert [item["action_type"] for item in snapshot["candidates"]].count("resume-composite-survey") == 1
    assert all(
        not (
            item["action_type"] in {"resume-literature-search", "select-literature-candidates"}
            and item["subject"]["id"] == composite_path.stem
        )
        for item in snapshot["candidates"]
    )


def test_literature_stage_enumeration_rejects_symlink_leaf(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_symlink")
    root = _workspace(tmp_path)
    stage_root = root / "kb/synthesis/source-search"
    stage_root.mkdir(parents=True)
    outside = tmp_path / "outside.yaml"
    outside.write_text("id: escaped\n", encoding="utf-8")
    (stage_root / "escaped.yaml").symlink_to(outside)

    with pytest.raises(SystemExit, match="unsafe|regular|symlink"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_literature_stage_enumeration_is_a_pure_empty_read_for_missing_workspace(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace-that-does-not-exist"

    assert literature_search_continuations(root) == []
    assert not root.exists()


def test_literature_stage_enumeration_rejects_malformed_persisted_state(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_malformed")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="malformed persisted state",
        stop_reason="in_progress",
    )
    malformed = load_yaml(stage_path)
    malformed["queries"][0]["outcome"] = "invented-success"
    write_yaml_if_changed(stage_path, malformed)

    with pytest.raises(SystemExit, match="query|canonical|supported"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_literature_stage_enumeration_rejects_candidate_extra_field(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_candidate_extra")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="candidate exact schema",
        stop_reason="in_progress",
    )
    malformed = load_yaml(stage_path)
    malformed["candidates"][0]["provider_raw_payload"] = {"secret": "must reject"}
    write_yaml_if_changed(stage_path, malformed)

    with pytest.raises(SystemExit, match="candidate|unknown|canonical"):
        orchestrate.portfolio_candidate_snapshot(root)


@pytest.mark.parametrize(
    "openalex",
    (
        {"doi": "10.1234/legacy-read-only"},
        {"work_id": "W12345", "doi": "10.1234/legacy-read-only"},
    ),
)
def test_literature_stage_enumeration_accepts_documented_legacy_openalex_doi_migration(
    tmp_path: Path,
    openalex: dict[str, str],
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_legacy_doi")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="legacy identity migration",
        stop_reason="target_met",
    )
    legacy = load_yaml(stage_path)
    legacy["candidates"][0]["identities"] = {}
    legacy["candidates"][0]["provenance"] = {"openalex": openalex}
    write_yaml_if_changed(stage_path, legacy)

    snapshot = orchestrate.portfolio_candidate_snapshot(root)

    selection = next(
        item
        for item in snapshot["candidates"]
        if item["action_type"] == "select-literature-candidates"
    )
    binding = selection["dependencies"][0]["candidates"][0]
    assert len(binding["identity_digest"]) == 64
    assert len(binding["semantic_digest"]) == 64
    assert load_yaml(stage_path)["candidates"][0]["identities"] == {}


@pytest.mark.parametrize(
    "openalex",
    (
        {"work_id": "https://openalex.org/W1", "doi": "10.1234/legacy"},
        {"work_id": "w1", "doi": "10.1234/legacy"},
        {"work_id": "Wabc", "doi": "10.1234/legacy"},
        {"work_id": "W1", "doi": "10.1234/legacy", "provider": "OpenAlex"},
    ),
)
def test_literature_stage_enumeration_rejects_noncanonical_legacy_openalex_shape(
    tmp_path: Path,
    openalex: dict[str, str],
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_bad_legacy_openalex")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="bad legacy identity migration",
        stop_reason="target_met",
    )
    malformed = load_yaml(stage_path)
    malformed["candidates"][0]["identities"] = {}
    malformed["candidates"][0]["provenance"] = {"openalex": openalex}
    write_yaml_if_changed(stage_path, malformed)

    with pytest.raises(SystemExit, match="legacy|provenance|work id|canonical"):
        orchestrate.portfolio_candidate_snapshot(root)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update(status="completed"),
        lambda payload: payload.update(query=17),
        lambda payload: payload.update(generated_by="runtime-agent"),
        lambda payload: payload.update(generated_at="not-a-time"),
        lambda payload: payload["history"].append(
            {"timestamp": "not-a-time", "action": "staged", "summary": "bad"}
        ),
    ),
)
def test_literature_stage_enumeration_rejects_illegal_top_level_contract(
    tmp_path: Path,
    mutation,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_top_contract")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="top-level exact schema",
        stop_reason="in_progress",
    )
    malformed = load_yaml(stage_path)
    mutation(malformed)
    write_yaml_if_changed(stage_path, malformed)

    with pytest.raises(SystemExit, match="stage|status|query|generated|history|timestamp|canonical"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_literature_stage_enumeration_revalidates_ancestor_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_ancestor_race")
    root = _workspace(tmp_path)
    _stage_literature_search(
        root,
        query="ancestor race",
        stop_reason="in_progress",
    )
    stage_root = root / "kb/synthesis/source-search"
    displaced = root / "kb/synthesis/source-search-displaced"
    replacement = tmp_path / "replacement-source-search"
    replacement.mkdir()
    original_listdir = orchestrate.os.listdir
    raced = False

    def listdir_then_replace(descriptor):
        nonlocal raced
        names = original_listdir(descriptor)
        if not raced:
            raced = True
            stage_root.rename(displaced)
            stage_root.symlink_to(replacement, target_is_directory=True)
        return names

    monkeypatch.setattr(orchestrate.os, "listdir", listdir_then_replace)
    with pytest.raises(SystemExit, match="ancestor|directory|changed|unsafe"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_literature_stage_enumeration_rejects_duplicate_yaml_mapping_key(
    tmp_path: Path,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_duplicate_key")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="duplicate mapping key",
        stop_reason="in_progress",
    )
    stage_path.write_text(
        stage_path.read_text(encoding="utf-8") + "status: staged\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="duplicate|mapping key|canonical"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_literature_stage_enumeration_rejects_unknown_top_level_field(
    tmp_path: Path,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_unknown_field")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="unknown top level field",
        stop_reason="in_progress",
    )
    malformed = load_yaml(stage_path)
    malformed["provider_raw_payload"] = {"private": "must not enter portfolio reads"}
    write_yaml_if_changed(stage_path, malformed)

    with pytest.raises(SystemExit, match="unknown|top-level|canonical"):
        orchestrate.portfolio_candidate_snapshot(root)


def test_literature_stage_enumeration_rejects_invalid_frontier_history_without_crashing(
    tmp_path: Path,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_literature_bad_frontier_history")
    root = _workspace(tmp_path)
    stage_path = _stage_literature_search(
        root,
        query="invalid frontier replacement history",
        stop_reason="in_progress",
    )
    malformed = load_yaml(stage_path)
    malformed["frontier_history"] = [
        {"replaced_at": "2025-01-01T00:00:00+00:00", "action": {}}
    ]
    write_yaml_if_changed(stage_path, malformed)

    with pytest.raises(SystemExit, match="frontier|history|canonical"):
        orchestrate.portfolio_candidate_snapshot(root)


@pytest.mark.parametrize("mutation", ["content", "revision", "state"])
def test_active_monitor_binding_change_stales_existing_portfolio_decision(
    tmp_path: Path,
    mutation: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_monitor_stale_{mutation}")
    root = _workspace(tmp_path)
    _subscription, run = _active_monitor(root)
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    action_id = next(
        item["action_id"]
        for item in snapshot["candidates"]
        if item["action_type"] == "resume-monitor-run"
    )
    orchestrate.record_portfolio_decision(root, _decision(root, snapshot, [action_id]))

    if mutation == "state":
        transition_run(
            root,
            run["id"],
            expected_revision=run["revision"],
            state="running",
            now="2026-07-01T00:04:00Z",
        )
    else:
        path = run_path(root, run["id"])
        changed = load_yaml(path)
        if mutation == "content":
            changed["stop"]["rationale"] = "Additional mechanical recovery context."
        else:
            changed["revision"] = int(changed["revision"]) + 1
        changed["content_digest"] = value_digest(
            {key: value for key, value in changed.items() if key != "content_digest"}
        )
        write_yaml_if_changed(path, changed)

    current_snapshot = orchestrate.portfolio_candidate_snapshot(root)
    current = orchestrate.current_portfolio_decision(root, current_snapshot)

    assert current_snapshot["candidate_snapshot_digest"] != snapshot["candidate_snapshot_digest"]
    assert current is not None
    assert current["effective_status"] == "stale"
    assert current["safe_to_continue"] is False


def test_side_judgement_and_monitor_outcome_are_complete_factual_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_complete_candidate_sources")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a")
    judgement_binding = {
        "subject": {
            "kind": "program_decision",
            "id": "decision-1",
            "owner": "research-orchestrator",
            "path": "kb/programs/program-a/workflow/decisions.yaml",
        },
        "confirmation_status": "pending_user_confirmation",
        "content_digest": "a" * 64,
        "verification": {
            "verified_at": "2026-07-24T00:00:00+00:00",
            "claims_digest": "b" * 64,
            "evidence_digest": "c" * 64,
        },
    }
    monkeypatch.setattr(
        orchestrate,
        "discover_pending_judgements",
        lambda _root: [
            {
                "subject": judgement_binding["subject"],
                "snapshot_binding": judgement_binding,
                "priority": "high",
                "confirm_route": {"program_id": "program-a"},
            }
        ],
    )
    monkeypatch.setattr(
        orchestrate,
        "unresolved_monitor_outcomes",
        lambda _root: [
            {
                "run_id": "run-1",
                "outcome_id": "outcome-1",
                "classification": "new",
                "subject_ref": "candidate-paper",
                "rationale": "A new paper may change the current conclusion.",
                "subscription_id": "subscription-1",
                "subscription_title": "Track VLA papers",
                "program_ids": ["program-a"],
                "run_revision": 3,
                "run_content_digest": "d" * 64,
                "outcome_binding_digest": "e" * 64,
            }
        ],
    )

    snapshot = orchestrate.portfolio_candidate_snapshot(root, selected_program_id="program-a")
    side = next(item for item in snapshot["candidates"] if item["action_type"] == "review-judgement")
    outcome = next(
        item for item in snapshot["candidates"] if item["action_type"] == "resolve-monitor-outcome"
    )

    assert side["dependencies"][0]["snapshot_binding"] == judgement_binding
    assert side["governance_gate"] == "human-decision"
    assert outcome["dependencies"][0]["run_revision"] == 3
    assert outcome["governance_gate"] == "human-decision"
    assert outcome["safe_execute_capability"] is False
    assert not _contains_key(snapshot, "score")


def test_fill_template_contains_locked_agent_authored_fields(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_template")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Continue grounded work"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)

    fill = orchestrate.portfolio_decision_fill_template(snapshot)

    assert fill["candidate_snapshot_digest"] == snapshot["candidate_snapshot_digest"]
    assert fill["selected_action_ids"] == []
    for field in ("decision_id", "rationale", "expected_information_gain", "cost_and_risk", "decided_at"):
        assert fill[field] == ""


def test_persisted_action_identity_does_not_depend_on_list_position(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_action_identity")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["First", "Keep me"])
    before = orchestrate.portfolio_candidate_snapshot(root)
    kept_before = next(item["action_id"] for item in before["candidates"] if item["reason"] == "Keep me")

    state = orchestrate.load_state(root, "program-a")
    state["next_actions"] = ["Keep me"]
    write_yaml_if_changed(orchestrate.state_path(root, "program-a"), state)
    after = orchestrate.portfolio_candidate_snapshot(root)
    kept_after = next(item["action_id"] for item in after["candidates"] if item["reason"] == "Keep me")

    assert kept_after == kept_before


def test_agent_decision_records_exact_history_and_becomes_current(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_record")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Write survey", "Design experiment"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    selected = [
        item["action_id"]
        for item in snapshot["candidates"]
        if item["reason"] == "Design experiment"
    ]
    checkpoints: list[list[Path]] = []
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs["target_paths"]) or {"committed": False},
    )

    stored, changed = orchestrate.record_portfolio_decision(root, _decision(root, snapshot, selected))
    current = orchestrate.current_portfolio_decision(root, snapshot)

    assert changed is True
    assert stored["generated_by"] == "runtime-agent"
    assert stored["safe_to_continue"] is False
    assert current is not None
    assert current["effective_status"] == "current"
    assert current["selected_action_ids"] == selected
    assert [item["reason"] for item in current["selected_actions"]] == ["Design experiment"]
    assert checkpoints == [[orchestrate.portfolio_history_path(root)]]
    history = load_yaml(orchestrate.portfolio_history_path(root))
    assert [item["decision_id"] for item in history["items"]] == ["portfolio-001"]


def test_state_change_marks_history_stale_and_old_fill_cannot_be_recorded(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_stale")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Write survey"])
    old_snapshot = orchestrate.portfolio_candidate_snapshot(root)
    old_decision = _decision(root, old_snapshot, [old_snapshot["candidates"][0]["action_id"]])
    orchestrate.record_portfolio_decision(root, old_decision)
    before = orchestrate.portfolio_history_path(root).read_bytes()

    state = orchestrate.load_state(root, "program-a")
    state["goal"] = "A materially changed goal"
    write_yaml_if_changed(orchestrate.state_path(root, "program-a"), state)
    new_snapshot = orchestrate.portfolio_candidate_snapshot(root)
    current = orchestrate.current_portfolio_decision(root, new_snapshot)

    assert new_snapshot["candidate_snapshot_digest"] != old_snapshot["candidate_snapshot_digest"]
    assert current is not None
    assert current["effective_status"] == "stale"
    assert current["selected_actions"] == []
    assert current["safe_to_continue"] is False
    with pytest.raises(SystemExit, match="stale"):
        orchestrate.record_portfolio_decision(root, {**old_decision, "decision_id": "portfolio-002"})
    assert orchestrate.portfolio_history_path(root).read_bytes() == before


def test_human_gate_is_never_safe_execute_capable() -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_human_gate")

    candidate = orchestrate._candidate(
        program_id="program-a",
        action_type="human-decision",
        subject_id="paper-1",
        owner_skill="paper-analyst",
        stage="review",
        goal="Review",
        question="Confirm?",
        reason="Wait for the user",
        governance_gate="human-decision",
        safe_execute_capability=True,
    )

    assert candidate["governance_gate"] == "human-decision"
    assert candidate["safe_execute_capability"] is False


def test_research_judgement_cannot_hide_in_procedural_selection(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_judgement_gate")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Choose baseline A"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"

    with pytest.raises(SystemExit, match="program decision reference"):
        orchestrate.validate_portfolio_decision(root, decision, snapshot)


def test_program_decision_binding_change_stales_agent_portfolio_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_program_binding")
    root = _workspace(tmp_path)
    _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    stored, _changed = orchestrate.record_portfolio_decision(root, decision)
    binding = stored["program_decision_bindings"]["program-a:decision-1"]

    changed_binding = {**binding, "content_digest": "f" * 64}
    monkeypatch.setattr(
        orchestrate,
        "_validate_program_decision_references",
        lambda _root, _ids, _selected: {"program-a:decision-1": changed_binding},
    )
    current = orchestrate.current_portfolio_decision(root, snapshot)

    assert current is not None
    assert current["effective_status"] == "stale"
    assert "program_decision_changed" in current["stale_reasons"]
    assert current["safe_to_continue"] is False


@pytest.mark.parametrize("confirmed", [False, True])
def test_program_decision_reference_accepts_stable_bound_snapshot(
    tmp_path: Path,
    confirmed: bool,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_bound_program_stable_{confirmed}")
    root = _workspace(tmp_path)
    record, _path = _verified_program_decision(orchestrate, root, confirmed=confirmed)

    bindings = orchestrate._validate_program_decision_references(
        root,
        ["program-a:decision-1"],
        [{"program_id": "program-a"}],
    )

    binding = bindings["program-a:decision-1"]
    assert binding["subject"]["id"] == record["id"]
    assert binding["confirmation_status"] == record["confirmation_status"]


@pytest.mark.parametrize("replacement", ["changed", "same-bytes"])
def test_program_decision_reference_rejects_replacement_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_bound_program_replace_{replacement}")
    root = _workspace(tmp_path)
    _record, path = _verified_program_decision(orchestrate, root)
    original = orchestrate.readiness_violations
    replaced = False

    def replace_after_validation(*args, **kwargs):
        nonlocal replaced
        violations = original(*args, **kwargs)
        if not replaced:
            old_bytes = path.read_bytes()
            replacement_path = path.with_name("decisions-replacement.yaml")
            if replacement == "same-bytes":
                replacement_path.write_bytes(old_bytes)
            else:
                container = load_yaml(path)
                container["items"][0]["payload"]["decision"]["text"] = "NEW_SENTINEL route B"
                write_yaml_if_changed(replacement_path, container)
            os.replace(replacement_path, path)
            replaced = True
        return violations

    monkeypatch.setattr(orchestrate, "readiness_violations", replace_after_validation)
    with pytest.raises(SystemExit, match="unavailable or unverified"):
        orchestrate._validate_program_decision_references(
            root,
            ["program-a:decision-1"],
            [{"program_id": "program-a"}],
        )
    assert replaced is True


@pytest.mark.parametrize("replacement", ["same-bytes", "changed", "duplicate-subject"])
def test_portfolio_history_write_revalidates_bound_program_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_portfolio_final_gate_{replacement}")
    root = _workspace(tmp_path)
    _record, decisions_file = _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    history_file = orchestrate.portfolio_history_path(root)
    checkpoints: list[list[Path]] = []
    original_load_history = orchestrate._load_portfolio_history
    replaced = False

    def replace_decisions_during_history_load(project_root: Path) -> dict:
        nonlocal replaced
        history = original_load_history(project_root)
        if replaced:
            return history
        replacement_file = decisions_file.with_name("decisions-replacement.yaml")
        if replacement == "same-bytes":
            replacement_file.write_bytes(decisions_file.read_bytes())
        else:
            container = load_yaml(decisions_file)
            if replacement == "changed":
                container["items"][0]["payload"]["decision"]["text"] = "NEW_SENTINEL route B"
            else:
                container["items"].append(dict(container["items"][0]))
            write_yaml_if_changed(replacement_file, container)
        os.replace(replacement_file, decisions_file)
        replaced = True
        return history

    monkeypatch.setattr(orchestrate, "_load_portfolio_history", replace_decisions_during_history_load)
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs["target_paths"]) or {"committed": False},
    )

    with pytest.raises(SystemExit, match="unavailable or unverified"):
        orchestrate.record_portfolio_decision(root, decision)

    assert replaced is True
    assert not history_file.exists()
    assert checkpoints == []


@pytest.mark.parametrize("replacement", ["content", "same-bytes"])
@pytest.mark.parametrize("history_state", ["existing", "fresh"])
def test_portfolio_history_postwrite_gate_rolls_back_stale_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
    history_state: str,
) -> None:
    orchestrate = _load_orchestrator(
        f"orchestrator_portfolio_postwrite_{replacement}_{history_state}"
    )
    root = _workspace(tmp_path)
    _record, decisions_file = _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    history_file = orchestrate.portfolio_history_path(root)
    before_history: bytes | None = None
    before_mode: int | None = None
    if history_state == "existing":
        write_yaml_if_changed(
            history_file,
            {
                "id": orchestrate.PORTFOLIO_HISTORY_ID,
                "generated_by": "research-orchestrator",
                "generated_at": "2026-07-24T00:00:00+00:00",
                "items": [{"decision_id": "existing-sentinel"}],
            },
        )
        history_file.chmod(0o640)
        before_history = history_file.read_bytes()
        before_mode = history_file.stat().st_mode & 0o7777

    original_write_yaml = orchestrate.write_yaml_if_changed
    source_inode = decisions_file.stat().st_ino
    replaced = False

    def replace_decisions_after_history_write(path: Path, value: object) -> None:
        nonlocal replaced
        original_write_yaml(path, value)
        if Path(path) != history_file or replaced:
            return
        replacement_file = decisions_file.with_name("decisions-postwrite-replacement.yaml")
        if replacement == "same-bytes":
            replacement_file.write_bytes(decisions_file.read_bytes())
        else:
            container = load_yaml(decisions_file)
            container["items"][0]["payload"]["decision"]["text"] = "POSTWRITE_SENTINEL route B"
            write_yaml_if_changed(replacement_file, container)
        os.replace(replacement_file, decisions_file)
        replaced = True

    checkpoints: list[list[Path]] = []
    monkeypatch.setattr(orchestrate, "write_yaml_if_changed", replace_decisions_after_history_write)
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs["target_paths"]) or {"committed": False},
    )

    with pytest.raises(SystemExit, match="unavailable or unverified"):
        orchestrate.record_portfolio_decision(root, decision)

    assert replaced is True
    assert decisions_file.stat().st_ino != source_inode
    if history_state == "existing":
        assert history_file.read_bytes() == before_history
        assert history_file.stat().st_mode & 0o7777 == before_mode
    else:
        assert not history_file.exists()
    assert checkpoints == []


@pytest.mark.parametrize("replacement", ["content", "same-bytes"])
def test_portfolio_history_commit_boundary_gate_rolls_back_source_change_after_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_portfolio_commit_gap_{replacement}")
    root = _workspace(tmp_path)
    _record, decisions_file = _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    history_file = orchestrate.portfolio_history_path(root)
    original_transaction = orchestrate.mutation_transaction
    replaced = False

    @contextmanager
    def replace_source_before_transaction_commit(*args, **kwargs):
        nonlocal replaced
        with original_transaction(*args, **kwargs) as op_id:
            try:
                yield op_id
            finally:
                replacement_file = decisions_file.with_name("decisions-commit-gap-replacement.yaml")
                if replacement == "same-bytes":
                    replacement_file.write_bytes(decisions_file.read_bytes())
                else:
                    container = load_yaml(decisions_file)
                    container["items"][0]["payload"]["decision"]["text"] = "COMMIT GAP route B"
                    write_yaml_if_changed(replacement_file, container)
                os.replace(replacement_file, decisions_file)
                replaced = True

    checkpoints: list[object] = []
    monkeypatch.setattr(orchestrate, "mutation_transaction", replace_source_before_transaction_commit)
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs),
    )

    with pytest.raises(SystemExit, match="unavailable or unverified"):
        orchestrate.record_portfolio_decision(root, decision)

    assert replaced
    assert not history_file.exists()
    assert checkpoints == []


def test_portfolio_guard_rejects_nested_outer_transaction_before_history_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_portfolio_nested_guard")
    root = _workspace(tmp_path)
    _record, _decisions_file = _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    history_file = orchestrate.portfolio_history_path(root)
    checkpoints: list[object] = []
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs),
    )

    with orchestrate.mutation_transaction(root, "outer-portfolio-publication", [history_file]):
        with pytest.raises(SystemExit, match="不能嵌套"):
            orchestrate.record_portfolio_decision(root, decision)

    assert not history_file.exists()
    assert checkpoints == []


@pytest.mark.parametrize("replacement", ["content", "same-bytes"])
def test_portfolio_history_replay_revalidates_after_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    orchestrate = _load_orchestrator(f"orchestrator_portfolio_replay_gate_{replacement}")
    root = _workspace(tmp_path)
    _record, decisions_file = _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    orchestrate.record_portfolio_decision(root, decision)
    history_file = orchestrate.portfolio_history_path(root)
    before_history = history_file.read_bytes()
    before_history_inode = history_file.stat().st_ino
    source_inode = decisions_file.stat().st_ino
    original_transaction = orchestrate.mutation_transaction
    replaced = False

    @contextmanager
    def replace_decisions_after_transaction(*args, **kwargs):
        nonlocal replaced
        with original_transaction(*args, **kwargs) as op_id:
            yield op_id
        if replaced:
            return
        replacement_file = decisions_file.with_name("decisions-replay-replacement.yaml")
        if replacement == "same-bytes":
            replacement_file.write_bytes(decisions_file.read_bytes())
        else:
            container = load_yaml(decisions_file)
            container["items"][0]["payload"]["decision"]["text"] = "REPLAY_SENTINEL route B"
            write_yaml_if_changed(replacement_file, container)
        os.replace(replacement_file, decisions_file)
        replaced = True

    checkpoints: list[list[Path]] = []
    monkeypatch.setattr(orchestrate, "mutation_transaction", replace_decisions_after_transaction)
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs["target_paths"]) or {"committed": False},
    )

    with pytest.raises(SystemExit, match="unavailable or unverified"):
        orchestrate.record_portfolio_decision(root, decision)

    assert replaced is True
    assert decisions_file.stat().st_ino != source_inode
    assert history_file.read_bytes() == before_history
    assert history_file.stat().st_ino == before_history_inode
    assert checkpoints == []


def test_stable_research_judgement_record_and_replay_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrate = _load_orchestrator("orchestrator_portfolio_stable_final_gate")
    root = _workspace(tmp_path)
    _verified_program_decision(orchestrate, root)
    _program(orchestrate, root, "program-a", actions=["Choose a grounded baseline"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["decision_scope"] = "research_judgement"
    decision["program_decision_ids"] = ["program-a:decision-1"]
    checkpoints: list[list[Path]] = []
    monkeypatch.setattr(
        orchestrate,
        "checkpoint_and_report",
        lambda project_root, **kwargs: checkpoints.append(kwargs["target_paths"]) or {"committed": False},
    )

    plan = orchestrate._portfolio_decision_validation_plan(root, decision, snapshot)
    normalized, selected = orchestrate.validate_portfolio_decision(root, decision, snapshot)
    stored, changed = orchestrate.record_portfolio_decision(root, decision)
    history_file = orchestrate.portfolio_history_path(root)
    before_replay = history_file.read_bytes()
    before_replay_inode = history_file.stat().st_ino
    replayed, replay_changed = orchestrate.record_portfolio_decision(root, decision)

    assert len(plan.program_decision_snapshots) == 1
    assert plan.program_decision_snapshots[0].record["id"] == "decision-1"
    assert normalized == plan.normalized
    assert selected == list(plan.selected)
    assert changed is True
    assert replay_changed is False
    assert replayed == stored
    assert history_file.read_bytes() == before_replay
    assert history_file.stat().st_ino == before_replay_inode
    assert checkpoints == [[history_file]]


def test_missing_preference_receipt_fails_closed(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_preference_gate")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Continue"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    decision["preference_selection_id"] = "pref-missing"

    with pytest.raises(SystemExit, match="unavailable"):
        orchestrate.validate_portfolio_decision(root, decision, snapshot)


def test_preference_catalog_change_makes_portfolio_decision_stale(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_preference_stale")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Continue"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    orchestrate.record_portfolio_decision(root, decision)

    preferences = default_runtime_preferences()
    preferences["autonomy"]["auto_execute_scope"] = ["screen"]
    write_yaml_if_changed(runtime_preferences_path(root), preferences)
    current = orchestrate.current_portfolio_decision(root, snapshot)

    assert current is not None
    assert current["effective_status"] == "stale"
    assert "preference_selection_stale" in current["stale_reasons"]
    assert current["safe_to_continue"] is False


def test_portfolio_history_rejects_symlink_target(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_symlink")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Continue"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])
    outside = tmp_path / "outside.yaml"
    outside.write_text("sentinel: true\n", encoding="utf-8")
    history = orchestrate.portfolio_history_path(root)
    history.symlink_to(outside)

    with pytest.raises(SystemExit, match="symlink"):
        orchestrate.record_portfolio_decision(root, decision)
    assert outside.read_text(encoding="utf-8") == "sentinel: true\n"


def test_candidate_snapshot_skips_symlinked_program_directory(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_symlinked_program")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "safe", actions=["Safe action"])
    outside = tmp_path / "outside-program"
    (outside / "workflow").mkdir(parents=True)
    write_yaml_if_changed(
        outside / "state.yaml",
        {"program_id": "outside", "stage": "active", "next_actions": ["Exfiltrate"]},
    )
    (root / "kb" / "programs" / "linked").symlink_to(outside, target_is_directory=True)

    snapshot = orchestrate.portfolio_candidate_snapshot(root)

    assert {item["program_id"] for item in snapshot["program_contexts"]} == {"safe"}
    assert all(item["reason"] != "Exfiltrate" for item in snapshot["candidates"])


def test_next_json_is_pure_read_and_requests_agent_planning(tmp_path: Path, monkeypatch, capsys) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_next_protocol")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["Continue"])
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    monkeypatch.setattr(sys, "argv", ["orchestrate.py", "--root", str(root), "next", "--json"])

    assert orchestrate.main() == 0
    payload = json.loads(capsys.readouterr().out)
    after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

    assert payload["planning_required"] is True
    assert payload["items"] == []
    assert "legacy_items_are_not_a_decision" not in payload
    assert payload["candidate_snapshot"]["candidate_count"] >= 1
    assert payload["portfolio_decision_fill"]["candidate_snapshot_digest"] == payload["candidate_snapshot"]["candidate_snapshot_digest"]
    assert payload["portfolio_decision"] is None
    assert before == after


def test_duplicate_decision_id_is_idempotent_but_cannot_rebind(tmp_path: Path) -> None:
    orchestrate = _load_orchestrator("orchestrator_agent_duplicate")
    root = _workspace(tmp_path)
    _program(orchestrate, root, "program-a", actions=["One", "Two"])
    snapshot = orchestrate.portfolio_candidate_snapshot(root)
    decision = _decision(root, snapshot, [snapshot["candidates"][0]["action_id"]])

    _stored, first_changed = orchestrate.record_portfolio_decision(root, decision)
    _stored_again, second_changed = orchestrate.record_portfolio_decision(root, decision)
    rebound = {**decision, "selected_action_ids": [snapshot["candidates"][1]["action_id"]]}

    assert first_changed is True
    assert second_changed is False
    with pytest.raises(SystemExit, match="different content"):
        orchestrate.record_portfolio_decision(root, rebound)

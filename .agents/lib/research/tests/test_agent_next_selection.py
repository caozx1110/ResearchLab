from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research.common import append_list_item, load_yaml, write_yaml_if_changed
from research.monitoring import create_subscription
from research.paths import runtime_preferences_path
from research.preference_selection import eligible_preferences, record_effective_selection
from research.prefs import default_runtime_preferences


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


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


def _effective_preference_selection(root: Path, task_context_digest: str) -> str:
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
                "task_context_digest": task_context_digest,
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
        "preference_selection_id": _effective_preference_selection(root, snapshot["candidate_snapshot_digest"]),
        "decision_scope": "procedural_planning",
        "program_decision_ids": [],
        "decided_at": "2026-07-24T12:00:00+08:00",
    }


def _contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(_contains_key(item, forbidden) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


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
    # Deterministic order is identity-only and carries no semantic winner claim.
    assert [item["action_id"] for item in first["candidates"]] == sorted(
        item["action_id"] for item in first["candidates"]
    )


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
    assert payload["legacy_items_are_not_a_decision"] is True
    assert payload["items"]  # compatibility only; new adapters consume candidate_snapshot
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

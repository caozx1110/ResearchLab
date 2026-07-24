from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_orchestrator_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py"
    spec = importlib.util.spec_from_file_location("research_orchestrator_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_route_hints_point_to_existing_skill_dirs() -> None:
    root = _project_root()
    skills_root = root / ".agents" / "skills"
    existing = {path.name for path in skills_root.iterdir() if path.is_dir()}
    module = _load_orchestrator_module()

    assert set(module.ROUTE_HINTS.values()) <= existing


def test_source_intake_routes_cover_new_source_tasks() -> None:
    module = _load_orchestrator_module()

    assert module.ROUTE_HINTS["source"] == "source-intake"
    assert module.ROUTE_HINTS["intake"] == "source-intake"
    assert module.ROUTE_HINTS["入库"] == "source-intake"
    assert module.ROUTE_HINTS["staging"] == "source-intake"
    assert module.ROUTE_HINTS["新论文"] == "source-intake"


def test_survey_routes_cover_chinese_and_english_without_falling_into_paper_analysis() -> None:
    module = _load_orchestrator_module()
    for task in (
        "做一份论文文献综述",
        "build a systematic survey",
        "systematic literature review of VLA",
        "prepare a scoping review",
        "meta-analysis of recent results",
        "review recent papers on robotics",
        "review of the literature",
        "systematic mapping study",
        "state-of-the-art review",
        "整理相关工作",
        "做一个元分析",
        "完成证据综合",
        "系统映射研究",
        "整理 taxonomy 和趋势",
    ):
        assert module.route_task(task) == "literature-synthesizer"


def test_literature_discovery_routes_to_literature_search_not_single_paper_analysis() -> None:
    module = _load_orchestrator_module()
    for task in ("找论文", "补相关工作", "literature search for VLA", "find papers on robot learning"):
        assert module.route_task(task) == "literature-search"


def test_ambiguous_composed_and_negated_tasks_require_agent_routing() -> None:
    module = _load_orchestrator_module()
    cases = {
        "找论文，然后逐篇分析并写综述": {
            "literature-search",
            "paper-analyst",
            "literature-synthesizer",
        },
        "不要检索，直接分析这篇论文": {"paper-analyst"},
        "把新论文入库并分析": {"source-intake", "paper-analyst"},
        "每两周检查一次这个 survey 是否过时": {"research-monitor", "literature-synthesizer"},
    }
    for task, expected_owners in cases.items():
        snapshot = module.route_candidate_snapshot(task)
        assert module.route_task(task) == "research-orchestrator"
        assert snapshot["planning_required"] is True
        assert expected_owners <= set(snapshot["candidate_skills"])
        assert "score" not in snapshot


def test_agent_route_decision_must_follow_snapshot_and_dependency_order() -> None:
    module = _load_orchestrator_module()
    snapshot = module.route_candidate_snapshot("找论文，然后分析论文")
    decision = {
        "route_snapshot_digest": snapshot["route_snapshot_digest"],
        "rationale": "Discovery must produce the bounded set consumed by analysis.",
        "steps": [
            {
                "step_id": "search",
                "owner_skill": "literature-search",
                "instruction": "Find a bounded candidate set.",
                "depends_on": [],
                "governance_gate": "agent-verification",
            },
            {
                "step_id": "analyze",
                "owner_skill": "paper-analyst",
                "instruction": "Analyze the selected papers with evidence.",
                "depends_on": ["search"],
                "governance_gate": "human-decision",
            },
        ],
    }

    normalized = module.validate_route_decision(decision, snapshot)
    assert [item["order"] for item in normalized["steps"]] == [1, 2]

    stale = {**decision, "route_snapshot_digest": "0" * 64}
    with pytest.raises(SystemExit, match="stale"):
        module.validate_route_decision(stale, snapshot)
    invalid_dependency = {
        **decision,
        "steps": [{**decision["steps"][0], "depends_on": ["analyze"]}],
    }
    with pytest.raises(SystemExit, match="earlier"):
        module.validate_route_decision(invalid_dependency, snapshot)


def test_orchestrator_confirm_command_uses_shared_helper() -> None:
    module = _load_orchestrator_module()
    record = {"kind": "experiment", "id": "e-run-12345678"}

    assert module.confirm_command_for_record(record) == (
        "${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py confirm "
        "--experiment-id e-run-12345678 --confirmed-by ${RESEARCH_CONFIRMED_BY:?set-human-identity} "
        "--evidence ${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}"
    )

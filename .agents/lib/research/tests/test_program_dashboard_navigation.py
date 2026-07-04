from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import append_list_item, write_yaml_if_changed
from research.v2 import record_path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_script(skill: str, script_name: str, module_name: str):
    root = _project_root()
    script = root / ".agents" / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    return root


def test_navigator_current_state_renders_program_states() -> None:
    navigate = _load_script("research-navigator", "navigate.py", "navigator_script_for_u2")

    text = navigate.render_current(
        records=[],
        program_states=[
            {
                "program_id": "p-dashboard",
                "stage": "method-design",
                "goal": "Build the dashboard",
                "counts": {"open_questions": 2, "evidence_requests": 1},
                "updated_at": "2026-07-04T00:00:00+00:00",
            }
        ],
    )

    assert "`p-dashboard` · stage=method-design · OQ=2 · evidence=1 · Build the dashboard" in text
    assert "暂无 program state" not in text


def test_orchestrator_dashboard_prioritizes_blocking_evidence(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_u2")
    root = _make_workspace(tmp_path)
    program_id = "p-next"
    orchestrate.ensure_program_files(root, program_id)
    write_yaml_if_changed(
        orchestrate.state_path(root, program_id),
        {
            "program_id": program_id,
            "stage": "literature-review",
            "goal": "Choose baseline",
            "active_unit_ids": [],
            "counts": {},
            "updated_at": "2026-07-04T00:00:00+00:00",
        },
    )
    append_list_item(
        orchestrate.evidence_requests_path(root, program_id),
        f"{program_id}-evidence-requests",
        "research-orchestrator",
        {
            "question": "Can repo-X reproduce baseline?",
            "needed": "Need baseline parity logs",
            "priority": "high",
            "blocking": True,
        },
        default_status="open",
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)
    next_text = orchestrate.format_next(items)

    assert items[0]["program_id"] == program_id
    assert items[0]["blocking_evidence_count"] == 1
    assert "Resolve blocking evidence: Need baseline parity logs" in dashboard
    assert "`p-next`: Resolve blocking evidence: Need baseline parity logs" in next_text
    assert ".agents/skills/research-orchestrator/scripts/orchestrate.py status --program-id p-next" in dashboard
    assert ".agents/skills/research-orchestrator/scripts/orchestrate.py status --program-id p-next" in next_text


def test_orchestrator_pending_confirmation_command_uses_real_unit_id(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_b2")
    root = _make_workspace(tmp_path)
    program_id = "p-confirm-next"
    orchestrate.ensure_program_files(root, program_id)
    write_yaml_if_changed(
        orchestrate.state_path(root, program_id),
        {
            "program_id": program_id,
            "stage": "literature-review",
            "goal": "Confirm unit",
            "active_unit_ids": ["p-pending-123456"],
            "counts": {},
        },
    )
    write_yaml_if_changed(
        record_path(root, "paper", "p-pending-123456"),
        {
            "id": "p-pending-123456",
            "kind": "paper",
            "title": "Pending Paper",
            "status": "screened",
            "maturity": "lightweight",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["fact"],
            "summary": "Pending summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"state": {}},
        },
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)
    next_text = orchestrate.format_next(items)

    assert ".agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-pending-123456" in dashboard
    assert ".agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-pending-123456" in next_text
    assert "<id>" not in dashboard
    assert "<id>" not in next_text


def test_orchestrator_empty_kb_outputs_onboarding_command() -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_empty_kb")

    dashboard = orchestrate.format_dashboard([])
    next_text = orchestrate.format_next([])

    assert "KB 为空，第一步：intake add 一篇论文" in dashboard
    assert ".agents/skills/source-intake/scripts/intake.py add --kind paper" in dashboard
    assert "KB 为空，第一步：intake add 一篇论文" in next_text


def test_orchestrator_dashboard_detects_loose_unscreened_unit(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_loose_unit")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "paper", "p-loose-123456"),
        {
            "id": "p-loose-123456",
            "kind": "paper",
            "title": "Loose Paper",
            "status": "active",
            "maturity": "lightweight",
            "confirmation_status": "auto_confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "Loose summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"quick_screen": {}, "state": {"full_note_status": "not_started"}},
        },
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)

    assert items[0]["program_id"] == "loose:p-loose-123456"
    assert "unscreened paper `p-loose-123456`" in dashboard
    assert ".agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-loose-123456" in dashboard


def test_orchestrator_auto_dry_run_plans_exact_command_for_loose_unit(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_auto_plan")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "idea", "i-loose-123456"),
        {
            "id": "i-loose-123456",
            "kind": "idea",
            "title": "Loose Idea",
            "status": "draft",
            "maturity": "lightweight",
            "confirmation_status": "auto_confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "Loose idea",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"analysis": {}, "review": {"review_status": "not_started"}},
        },
    )

    text = orchestrate.format_auto_plan(orchestrate.auto_plan(root))

    assert "idea `i-loose-123456` needs analysis" in text
    assert ".agents/skills/idea-workbench/scripts/idea.py analyze --idea-id i-loose-123456" in text
    assert "safe refresh" in text


def test_orchestrator_auto_execute_stops_at_pending_confirmation(tmp_path: Path, capsys) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_auto_gate")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "paper", "p-gated-123456"),
        {
            "id": "p-gated-123456",
            "kind": "paper",
            "title": "Gated Paper",
            "status": "screened",
            "maturity": "lightweight",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["fact"],
            "summary": "Gated summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"quick_screen": {"worth_deep_reading": "maybe"}},
        },
    )

    plan = orchestrate.auto_plan(root)
    exit_code = orchestrate.execute_auto_plan(root, plan)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert plan["safe_execute"] is False
    assert "stop for human decision" in output
    assert "not executing" in output
    assert ".agents/skills/knowledge-base-manager/scripts/kb.py confirm --id p-gated-123456" in output

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import append_list_item, write_yaml_if_changed


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

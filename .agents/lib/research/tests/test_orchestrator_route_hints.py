from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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


def test_orchestrator_confirm_command_uses_shared_helper() -> None:
    module = _load_orchestrator_module()
    record = {"kind": "experiment", "id": "e-run-12345678"}

    assert module.confirm_command_for_record(record) == (
        "${RESEARCH_PYTHON:-python3} .agents/skills/experiment-workbench/scripts/experiment.py confirm "
        "--experiment-id e-run-12345678 --confirmed-by ${RESEARCH_CONFIRMED_BY:?set-human-identity} "
        "--evidence ${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}"
    )

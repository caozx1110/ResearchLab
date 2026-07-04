from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import confirm_command as shared_confirm_command


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_intake_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("source_intake_script_for_commands", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_intake_confirm_command_contains_created_record_id() -> None:
    intake = _load_intake_module()

    command = intake.confirm_command({"kind": "repo", "id": "r-openvla-12345678"})

    assert ".agents/skills/repo-analyst/scripts/repo.py confirm --repo-id r-openvla-12345678" in command
    assert "<id>" not in command
    assert "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}" in command


def test_intake_confirm_command_uses_shared_helper_with_runtime_python() -> None:
    intake = _load_intake_module()
    record = {"kind": "repo", "id": "r-openvla-12345678"}

    assert intake.confirm_command(record) == shared_confirm_command(
        record,
        command_prefix=intake.research_python(),
        direct_kinds=("paper", "repo", "blog"),
    )

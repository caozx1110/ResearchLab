from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed
from research.v2 import default_record, ensure_v2_workspace, record_path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_idea_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "idea-workbench" / "scripts" / "idea.py"
    spec = importlib.util.spec_from_file_location("idea_workbench_script_for_selection", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_idea_select_keeps_content_confirmation_pending(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_v2_workspace(tmp_path)
    record = default_record("idea", title="Selectable Idea", maturity="lightweight", source={"original_uri": "discussion"})
    record["id"] = "i-selectable-123456"
    record["status"] = "pending"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["user_opinion", "inference", "evaluation", "unverified"]
    write_yaml_if_changed(record_path(tmp_path, "idea", record["id"]), record)
    monkeypatch.setattr(idea, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(idea, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "idea.py",
            "select",
            "--idea-id",
            record["id"],
            "--confirmed-by",
            "czx",
            "--evidence",
            "kb/programs/p/decision-log.md",
        ],
    )

    assert idea.main() == 0

    updated = load_yaml(record_path(tmp_path, "idea", record["id"]), default={})
    assert updated["status"] == "selected"
    assert updated["confirmation_status"] == "pending_user_confirmation"
    assert updated["needs_human_confirmation"] is True
    assert "confirmation" not in updated
    assert updated["payload"]["selection"]["selected_by"] == "czx"
    assert updated["payload"]["selection"]["selection_evidence"] == ["kb/programs/p/decision-log.md"]
    assert updated["payload"]["selection"]["selection_method"] == "idea.py select"

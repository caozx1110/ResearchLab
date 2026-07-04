from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import write_yaml_if_changed
from research.v2 import ensure_v2_workspace, record_path, search_records


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_kb_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "knowledge-base-manager" / "scripts" / "kb.py"
    spec = importlib.util.spec_from_file_location("knowledge_base_manager_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_record(root: Path, record: dict) -> None:
    write_yaml_if_changed(record_path(root, record["kind"], record["id"]), record)


def _record(unit_id: str, title: str, confirmation_status: str, updated_at: str) -> dict:
    return {
        "id": unit_id,
        "kind": "paper",
        "title": title,
        "status": "active",
        "maturity": "lightweight",
        "confirmation_status": confirmation_status,
        "needs_human_confirmation": confirmation_status == "pending_user_confirmation",
        "information_types": ["fact"],
        "summary": f"{title} summary",
        "tags": ["robotics"],
        "topics": [],
        "candidate_pools": [],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": {},
        "updated_at": updated_at,
    }


def test_search_records_filters_confirmation_status(tmp_path: Path) -> None:
    ensure_v2_workspace(tmp_path)
    _write_record(tmp_path, _record("p-pending-123456", "Pending Robot", "pending_user_confirmation", "2026-01-01T00:00:00+00:00"))
    _write_record(tmp_path, _record("p-confirmed-123456", "Confirmed Robot", "confirmed", "2026-01-02T00:00:00+00:00"))

    hits = search_records(tmp_path, "robot", confirmation_status="pending_user_confirmation")

    assert [item["id"] for item in hits] == ["p-pending-123456"]


def test_review_queue_helpers_sort_oldest_first_and_emit_confirm_command() -> None:
    kb = _load_kb_module()
    newer = _record("p-newer-123456", "Newer", "pending_user_confirmation", "2026-01-02T00:00:00+00:00")
    older = _record("p-older-123456", "Older", "pending_user_confirmation", "2026-01-01T00:00:00+00:00")

    assert [item["id"] for item in sorted([newer, older], key=kb.review_sort_key)] == ["p-older-123456", "p-newer-123456"]
    command = kb.confirm_command(older)
    assert "--paper-id p-older-123456" in command
    assert "<id>" not in command
    assert "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}" in command


def test_query_output_helpers_emit_runnable_command_with_real_id() -> None:
    kb = _load_kb_module()
    record = _record("p-query-123456", "Queryable", "pending_user_confirmation", "2026-01-01T00:00:00+00:00")

    next_command = kb.next_unit_command(record)
    confirm_command = kb.confirm_command(record)

    assert ".agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-query-123456" in next_command
    assert ".agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-query-123456" in confirm_command
    assert "<id>" not in next_command
    assert "<id>" not in confirm_command

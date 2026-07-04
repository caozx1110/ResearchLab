from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import confirm_command as shared_confirm_command, load_yaml, write_yaml_if_changed
from research.v2 import ensure_v2_workspace, record_path, runtime_preferences_path, search_records


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


def _record(
    unit_id: str,
    title: str,
    confirmation_status: str,
    updated_at: str,
    *,
    status: str = "active",
    information_types: list[str] | None = None,
) -> dict:
    return {
        "id": unit_id,
        "kind": "paper",
        "title": title,
        "status": status,
        "maturity": "lightweight",
        "confirmation_status": confirmation_status,
        "needs_human_confirmation": confirmation_status == "pending_user_confirmation",
        "information_types": information_types or ["fact"],
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


def test_kb_confirm_command_uses_shared_helper() -> None:
    kb = _load_kb_module()
    record = _record("p-query-123456", "Queryable", "pending_user_confirmation", "2026-01-01T00:00:00+00:00")

    assert kb.confirm_command(record) == shared_confirm_command(record)


def test_batch_confirm_applies_one_evidence_to_multiple_units(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_v2_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    _write_record(tmp_path, _record("p-one-123456", "One", "pending_user_confirmation", "2026-01-01T00:00:00+00:00"))
    _write_record(tmp_path, _record("p-two-123456", "Two", "pending_user_confirmation", "2026-01-02T00:00:00+00:00"))
    records = search_records(tmp_path, "", confirmation_status="pending_user_confirmation")

    paths = kb.apply_batch_confirmation(
        tmp_path,
        records,
        confirmed_by="",
        evidence=["kb/programs/p/decision-log.md"],
        method="test batch",
    )

    assert len(paths) == 2
    for path in paths:
        record = load_yaml(path, default={})
        assert record["confirmation_status"] == "confirmed"
        assert record["confirmation"]["by"] == "czx-default"
        assert record["confirmation"]["evidence"] == ["kb/programs/p/decision-log.md"]


def test_batch_confirm_collapses_ai_information_types_and_sets_lifecycle(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_v2_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    _write_record(
        tmp_path,
        _record(
            "p-ai-typed-123456",
            "AI Typed",
            "pending_user_confirmation",
            "2026-01-01T00:00:00+00:00",
            status="screened",
            information_types=["fact", "inference", "evaluation", "unverified"],
        ),
    )
    records = search_records(tmp_path, "", confirmation_status="pending_user_confirmation")

    [path] = kb.apply_batch_confirmation(
        tmp_path,
        records,
        confirmed_by="",
        evidence=["kb/programs/p/decision-log.md"],
        method="test batch",
    )

    record = load_yaml(path, default={})
    assert record["confirmation_status"] == "confirmed"
    assert record["status"] == "active"
    assert record["information_types"] == ["fact"]
    assert record["history"][-1]["action"] == "paper-confirmed"


def test_batch_confirm_skips_non_pending_records(tmp_path: Path, capsys) -> None:
    kb = _load_kb_module()
    ensure_v2_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    pending = _record("p-pending-123456", "Pending", "pending_user_confirmation", "2026-01-01T00:00:00+00:00")
    rejected = _record("p-rejected-123456", "Rejected", "rejected", "2026-01-02T00:00:00+00:00", status="rejected")
    _write_record(tmp_path, pending)
    _write_record(tmp_path, rejected)

    paths = kb.apply_batch_confirmation(
        tmp_path,
        [pending, rejected],
        confirmed_by="",
        evidence=["kb/programs/p/decision-log.md"],
        method="test batch",
    )

    captured = capsys.readouterr()
    assert len(paths) == 1
    assert "[skip] p-rejected-123456: confirmation_status=rejected" in captured.out
    assert load_yaml(record_path(tmp_path, "paper", "p-rejected-123456"), default={})["confirmation_status"] == "rejected"


def test_review_queue_all_reviewed_empty_is_clean_noop(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_v2_workspace(tmp_path)

    records = kb.review_queue_records(tmp_path, confirmation_status="pending_user_confirmation")

    assert records == []


def test_review_queue_confirm_uses_listed_records(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_v2_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    _write_record(tmp_path, _record("p-old-123456", "Old", "pending_user_confirmation", "2026-01-01T00:00:00+00:00"))
    _write_record(tmp_path, _record("p-new-123456", "New", "pending_user_confirmation", "2026-01-02T00:00:00+00:00"))
    listed = kb.review_queue_records(tmp_path, confirmation_status="pending_user_confirmation", limit=1)
    listed_id = listed[0]["id"]

    paths = kb.apply_batch_confirmation(
        tmp_path,
        listed,
        confirmed_by="",
        evidence=["kb/programs/p/review.md"],
        method="test review queue confirm",
    )

    assert len(paths) == 1
    records = {
        unit_id: load_yaml(record_path(tmp_path, "paper", unit_id), default={})
        for unit_id in ("p-old-123456", "p-new-123456")
    }
    assert records[listed_id]["confirmation_status"] == "confirmed"
    for unit_id, record in records.items():
        if unit_id != listed_id:
            assert record["confirmation_status"] == "pending_user_confirmation"

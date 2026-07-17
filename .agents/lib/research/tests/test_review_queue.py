from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import ensure_workspace, record_path, runtime_preferences_path, search_records


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


def _load_idea_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "idea-workbench" / "scripts" / "idea.py"
    spec = importlib.util.spec_from_file_location("idea_workbench_script_for_review_queue", script)
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
    ensure_workspace(tmp_path)
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

    assert kb.confirm_command(record) == (
        "${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py confirm "
        "--paper-id p-query-123456 --confirmed-by ${RESEARCH_CONFIRMED_BY:?set-human-identity} "
        "--evidence ${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}"
    )


@pytest.mark.parametrize("command", [["query", "--query", "Queryable"], ["review-queue"]])
def test_user_facing_find_and_review_output_hides_raw_commands(
    tmp_path: Path,
    monkeypatch,
    capsys,
    command: list[str],
) -> None:
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record("p-query-123456", "Queryable", "pending_user_confirmation", "2026-01-01T00:00:00+00:00"),
    )
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["kb.py", *command])

    assert kb.main() == 0

    output = capsys.readouterr().out
    assert "p-query-123456" in output
    for leaked_fragment in ("python3", ".py ", "--paper-id", "--id ", "${"):
        assert leaked_fragment not in output


def test_batch_confirm_applies_one_evidence_to_multiple_units(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
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


def test_batch_confirm_without_evidence_rejects_before_write(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    pending = _record("p-no-evidence-123456", "No Evidence", "pending_user_confirmation", "2026-01-01T00:00:00+00:00")
    _write_record(tmp_path, pending)

    with pytest.raises(SystemExit, match="--evidence"):
        kb.apply_batch_confirmation(
            tmp_path,
            [pending],
            confirmed_by="czx",
            evidence=[],
            method="test missing evidence",
        )

    record = load_yaml(record_path(tmp_path, "paper", "p-no-evidence-123456"), default={})
    assert record["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in record
    assert not (tmp_path / "kb" / "index.yaml").exists()


def test_review_queue_confirm_without_evidence_rejects_before_write(tmp_path: Path, monkeypatch) -> None:
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    _write_record(
        tmp_path,
        _record("p-cli-no-evidence-123456", "CLI No Evidence", "pending_user_confirmation", "2026-01-01T00:00:00+00:00"),
    )
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kb.py",
            "review-queue",
            "--confirm",
            "--confirmed-by",
            "czx",
        ],
    )

    with pytest.raises(SystemExit, match="--evidence"):
        kb.main()

    record = load_yaml(record_path(tmp_path, "paper", "p-cli-no-evidence-123456"), default={})
    assert record["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in record
    assert not (tmp_path / "kb" / "index.yaml").exists()


def test_confirm_command_blank_evidence_rejects_before_any_batch_write(tmp_path: Path, monkeypatch) -> None:
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    unit_ids = ["p-cli-empty-a-123456", "p-cli-empty-b-123456"]
    for index, unit_id in enumerate(unit_ids, start=1):
        _write_record(
            tmp_path,
            _record(unit_id, f"CLI Empty Evidence {index}", "pending_user_confirmation", f"2026-01-0{index}T00:00:00+00:00"),
        )
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kb.py",
            "confirm",
            "--id",
            unit_ids[0],
            "--id",
            unit_ids[1],
            "--confirmed-by",
            "czx",
            "--evidence",
            "",
        ],
    )

    with pytest.raises(SystemExit, match="--evidence"):
        kb.main()

    for unit_id in unit_ids:
        record = load_yaml(record_path(tmp_path, "paper", unit_id), default={})
        assert record["confirmation_status"] == "pending_user_confirmation"
        assert "confirmation" not in record
    assert not (tmp_path / "kb" / "index.yaml").exists()


def test_batch_confirm_rejects_judgement_without_canonical_verification(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    ai_typed = _record(
        "p-ai-typed-123456",
        "AI Typed",
        "pending_user_confirmation",
        "2026-01-01T00:00:00+00:00",
        status="screened",
        information_types=["fact", "inference", "evaluation", "unverified"],
    )
    # Substance alone no longer permits a judgement confirmation: the record must
    # first carry canonical claims + a current byte-bound verification receipt.
    ai_typed["payload"] = {"core_content": {"method": "diffusion policy over action chunks"}}
    _write_record(tmp_path, ai_typed)
    records = search_records(tmp_path, "", confirmation_status="pending_user_confirmation")

    with pytest.raises(SystemExit, match="non-empty canonical payload.claims"):
        kb.apply_batch_confirmation(
            tmp_path,
            records,
            confirmed_by="",
            evidence=["kb/programs/p/decision-log.md"],
            method="test batch",
        )

    record = load_yaml(record_path(tmp_path, "paper", ai_typed["id"]), default={})
    assert record["confirmation_status"] == "pending_user_confirmation"
    assert record["status"] == "screened"
    assert record["information_types"] == ["fact", "inference", "evaluation", "unverified"]
    assert "confirmation" not in record


def test_batch_confirm_skips_non_pending_records(tmp_path: Path, capsys) -> None:
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    pending = _record("p-pending-123456", "Pending", "pending_user_confirmation", "2026-01-01T00:00:00+00:00")
    rejected = _record("p-rejected-123456", "Rejected", "rejected", "2026-01-02T00:00:00+00:00", status="rejected")
    _write_record(tmp_path, pending)
    _write_record(tmp_path, rejected)
    records = search_records(tmp_path, "")

    paths = kb.apply_batch_confirmation(
        tmp_path,
        records,
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
    ensure_workspace(tmp_path)

    records = kb.review_queue_records(tmp_path, confirmation_status="pending_user_confirmation")

    assert records == []


def test_review_queue_excludes_selected_idea_without_verified_content(tmp_path: Path, monkeypatch) -> None:
    kb = _load_kb_module()
    idea = _load_idea_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    record = _record(
        "i-select-review-123456",
        "Selectable Idea",
        "pending_user_confirmation",
        "2026-01-01T00:00:00+00:00",
        status="pending",
        information_types=["user_opinion", "inference", "evaluation", "unverified"],
    )
    record["kind"] = "idea"
    _write_record(tmp_path, record)
    monkeypatch.setattr(idea, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(idea, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "idea.py",
            "select",
            "--idea-id",
            "i-select-review-123456",
            "--confirmed-by",
            "czx",
            "--evidence",
            "kb/programs/p/decision-log.md",
            "--user-authorization",
            "I select this idea for the program.",
            "--authorization-source",
            "user_message",
        ],
    )

    assert idea.main() == 0

    records = kb.review_queue_records(tmp_path, kind="idea", confirmation_status="pending_user_confirmation")
    selected = load_yaml(record_path(tmp_path, "idea", "i-select-review-123456"), default={})

    assert records == []
    assert selected["status"] == "selected"
    assert selected["confirmation_status"] == "pending_user_confirmation"
    assert kb.record_workflow_state(selected) != "ready_for_review"


def test_confirm_all_reviewed_default_limit_is_unbounded() -> None:
    kb = _load_kb_module()

    args = kb.build_parser().parse_args(["confirm", "--all-reviewed", "--evidence", "kb/programs/p/decision-log.md"])

    assert args.limit == 0


def test_confirm_all_reviewed_reports_remaining_when_explicit_limit_caps_batch(tmp_path: Path, monkeypatch, capsys) -> None:
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "czx-default"}})
    for index in range(3):
        _write_record(
            tmp_path,
            _record(
                f"p-pending-{index:06d}",
                f"Pending {index}",
                "pending_user_confirmation",
                f"2026-01-0{index + 1}T00:00:00+00:00",
            ),
        )
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kb.py",
            "confirm",
            "--all-reviewed",
            "--limit",
            "2",
            "--evidence",
            "kb/programs/p/decision-log.md",
        ],
    )

    assert kb.main() == 0

    captured = capsys.readouterr()
    assert "confirmed 2 / 1 remaining, re-run" in captured.out
    remaining = search_records(tmp_path, "", confirmation_status="pending_user_confirmation")
    assert [record["id"] for record in remaining] == ["p-pending-000002"]


def test_review_queue_confirm_uses_listed_records(tmp_path: Path) -> None:
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
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


def _paper(unit_id: str, *, full_note_status: str) -> dict:
    return {
        "id": unit_id,
        "kind": "paper",
        "title": f"Paper {unit_id}",
        "status": "screened",
        "maturity": "complete",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["inference"],
        "summary": "s",
        "tags": [],
        "topics": [],
        "candidate_pools": [],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": {"state": {"full_note_status": full_note_status}, "core_content": {"insight": "real"}},
    }


def test_review_queue_excludes_hollow_judgements_but_keeps_ready_fact_metadata(tmp_path: Path) -> None:
    """Canonical workflow state excludes unverified judgement shells from review."""
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    shell = _paper("p-shell-12345678", full_note_status="awaiting_agent_fill")
    not_started = _paper("p-notstart-2345678", full_note_status="not_started")
    ready_fact = _paper("p-ready-fact-12345678", full_note_status="ready_for_review")
    ready_fact["status"] = "active"
    ready_fact["information_types"] = ["fact"]
    _write_record(tmp_path, shell)
    _write_record(tmp_path, not_started)
    _write_record(tmp_path, ready_fact)

    listed = {r["id"] for r in kb.review_queue_records(tmp_path, confirmation_status="pending_user_confirmation", limit=0)}

    assert ready_fact["id"] in listed
    assert not_started["id"] not in listed
    assert shell["id"] not in listed


@pytest.mark.parametrize(
    ("kind", "state_key", "blocked_state"),
    [
        ("paper", "full_note_status", "ready_to_verify"),
        ("blog", "full_note_status", "awaiting_agent_fill"),
        ("blog", "full_note_status", "failed-retryable"),
        ("repo", "capability_fill_status", "awaiting_agent_fill"),
        ("repo", "capability_fill_status", "ready-to-verify"),
    ],
)
def test_review_queue_excludes_non_review_workflow_states_for_all_source_kinds(
    tmp_path: Path,
    kind: str,
    state_key: str,
    blocked_state: str,
) -> None:
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    prefix = {"paper": "p", "blog": "b", "repo": "r"}[kind]
    blocked = _paper(f"{prefix}-blocked-12345678", full_note_status="pending_user_confirmation")
    blocked["kind"] = kind
    blocked["payload"]["state"] = {state_key: blocked_state}
    ready = _paper(f"{prefix}-ready-12345678", full_note_status="pending_user_confirmation")
    ready["kind"] = kind
    ready["status"] = "active"
    ready["information_types"] = ["fact"]
    ready["payload"]["state"] = {state_key: "ready_for_review"}
    _write_record(tmp_path, blocked)
    _write_record(tmp_path, ready)

    listed = {r["id"] for r in kb.review_queue_records(tmp_path, kind=kind, limit=0)}

    assert ready["id"] in listed
    assert blocked["id"] not in listed


def test_batch_confirmation_transmits_final_user_authorization_signature(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_module()
    captured: dict[str, object] = {}

    def fake_confirm(record, kind, *, confirmed_by, evidence, method, project_root, user_authorization, authorization_source):
        captured.update(
            record=record,
            kind=kind,
            confirmed_by=confirmed_by,
            evidence=evidence,
            method=method,
            project_root=project_root,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
        return record

    monkeypatch.setattr(kb, "confirm_unit", fake_confirm)
    written_path = tmp_path / "kb" / "units" / "papers" / "p-auth-12345678" / "record.yaml"
    monkeypatch.setattr(kb, "write_record", lambda _root, _record: written_path)
    record = _paper("p-auth-12345678", full_note_status="ready_for_review")

    assert kb.apply_batch_confirmation(
        tmp_path,
        [record],
        confirmed_by="researcher",
        evidence=["decision-note"],
        method="test",
        user_authorization="I confirm this judgement",
        authorization_source="user_message",
    ) == [written_path]
    assert captured["user_authorization"] == "I confirm this judgement"
    assert captured["authorization_source"] == "user_message"


def test_manual_checkpoint_resolves_literal_dirty_paths_and_clean_is_noop(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(kb, "dirty_kb_paths", lambda _root: [])
    monkeypatch.setattr(
        kb,
        "git_checkpoint",
        lambda *_args, **kwargs: calls.append(kwargs) or {"committed": False},
    )
    monkeypatch.setattr(sys, "argv", ["kb.py", "git-checkpoint", "--message", "manual"])
    assert kb.main() == 0
    assert calls == []
    assert "no kb changes" in capsys.readouterr().out

    dirty = [tmp_path / "kb" / "units" / "papers" / "p-one" / "record.yaml"]
    monkeypatch.setattr(kb, "dirty_kb_paths", lambda _root: dirty)
    monkeypatch.setattr(
        kb,
        "git_checkpoint",
        lambda *_args, **kwargs: calls.append(kwargs) or {"committed": False, "status": "no-changes"},
    )
    assert kb.main() == 0
    assert calls[-1]["target_paths"] == dirty

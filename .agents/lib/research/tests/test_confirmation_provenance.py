from __future__ import annotations

import ast
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import ensure_workspace, promote_record, record_path, runtime_preferences_path
from research.evidence import confirmation_content_digest, confirmation_evidence_digest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _script_text(skill: str, script_name: str) -> str:
    return (_project_root() / ".agents" / "skills" / skill / "scripts" / script_name).read_text(encoding="utf-8")


def _has_required_arg(text: str, arg_name: str) -> bool:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != arg_name:
            continue
        for keyword in node.keywords:
            if keyword.arg == "required" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return True
    return False


def _has_optional_arg(text: str, arg_name: str) -> bool:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value != arg_name:
            continue
        for keyword in node.keywords:
            if keyword.arg == "required" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return False
        return True
    return False


def _record(unit_id: str = "p-confirm-123456") -> dict:
    return {
        "id": unit_id,
        "kind": "paper",
        "title": "Confirm Me",
        "status": "screened",
        "maturity": "lightweight",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": {},
    }


def test_promote_to_confirmed_requires_human_provenance(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())

    with pytest.raises(SystemExit, match="--confirmed-by"):
        promote_record(tmp_path, "p-confirm-123456", confirmation_status="confirmed")

    with pytest.raises(SystemExit, match="--evidence"):
        promote_record(tmp_path, "p-confirm-123456", confirmation_status="confirmed", confirmed_by="czx")


def test_promote_to_confirmed_uses_configured_default_confirmed_by(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())
    write_yaml_if_changed(
        runtime_preferences_path(tmp_path),
        {
            "identity": {"default_confirmed_by": "czx-default"},
        },
    )

    path = promote_record(
        tmp_path,
        "p-confirm-123456",
        confirmation_status="confirmed",
        evidence=["kb/programs/p/decision-log.md"],
    )

    record = load_yaml(path, default={})
    assert record["confirmation"]["by"] == "czx-default"
    assert record["confirmation"]["evidence"] == ["kb/programs/p/decision-log.md"]


def test_missing_evidence_is_rejected_even_with_default_confirmed_by(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())
    write_yaml_if_changed(
        runtime_preferences_path(tmp_path),
        {
            "identity": {"default_confirmed_by": "czx-default"},
        },
    )

    with pytest.raises(SystemExit, match="--evidence"):
        promote_record(tmp_path, "p-confirm-123456", confirmation_status="confirmed")


def test_promote_non_confirmed_does_not_require_provenance(tmp_path: Path) -> None:
    """Backward-compat guard: only confirmed transitions need provenance;
    auto_confirmed / pending / rejected must still work without --confirmed-by/--evidence."""
    ensure_workspace(tmp_path)
    for target in ("auto_confirmed", "pending_user_confirmation", "rejected"):
        write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())
        path = promote_record(tmp_path, "p-confirm-123456", confirmation_status=target)
        record = load_yaml(path, default={})
        assert record["confirmation_status"] == target
        # no provenance block is stamped for non-confirmed transitions
        assert "confirmation" not in record or not record["confirmation"].get("by")


def test_confirmation_provenance_accepts_bare_string_evidence(tmp_path: Path) -> None:
    """require_confirmation_provenance annotates evidence as list|str; a bare string
    must be accepted (not silently rejected as empty)."""
    from research.core import require_confirmation_provenance

    actor, items = require_confirmation_provenance(confirmed_by="czx", evidence="kb/x/note.md")
    assert actor == "czx"
    assert items == ["kb/x/note.md"]


def test_promote_to_confirmed_persists_confirmation_provenance(tmp_path: Path, monkeypatch) -> None:
    # apply_confirmation (which stamps the provenance timestamp) now lives in
    # research.confirm after the god-file split; patch utc_now_iso in that module's
    # namespace so promote_record -> apply_confirmation observes the frozen clock.
    import research.confirm as confirm

    ensure_workspace(tmp_path)
    write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())
    monkeypatch.setattr(confirm, "utc_now_iso", lambda: "2026-07-04T00:00:00+00:00")

    path = promote_record(
        tmp_path,
        "p-confirm-123456",
        confirmation_status="confirmed",
        confirmed_by="czx",
        evidence=["kb/programs/p/decision-log.md"],
    )

    record = load_yaml(path, default={})
    assert record["confirmation_status"] == "confirmed"
    assert record["needs_human_confirmation"] is False
    receipt = record["confirmation"]
    assert receipt == {
        "by": "czx",
        "at": "2026-07-04T00:00:00+00:00",
        "evidence": ["kb/programs/p/decision-log.md"],
        "method": "kb.py promote",
        "decision": "confirmed",
        "subject": {"kind": "paper", "id": "p-confirm-123456"},
        "claim_ids": [],
        "content_digest": confirmation_content_digest(record),
        "evidence_digest": confirmation_evidence_digest(record, receipt["evidence"]),
        "prior_information_types": ["fact"],
    }


def test_confirm_scripts_require_provenance_arguments() -> None:
    for skill, script_name in [
        ("paper-analyst", "paper.py"),
        ("repo-analyst", "repo.py"),
        ("blog-analyst", "blog.py"),
        ("experiment-workbench", "experiment.py"),
    ]:
        text = _script_text(skill, script_name)
        assert "confirm_unit" in text
        assert "apply_confirmation" not in text
        assert _has_optional_arg(text, "--confirmed-by"), skill
        assert _has_required_arg(text, "--evidence"), skill

    idea_text = _script_text("idea-workbench", "idea.py")
    assert "require_confirmation_provenance" in idea_text
    assert "apply_confirmation" not in idea_text
    assert _has_optional_arg(idea_text, "--confirmed-by")
    assert _has_required_arg(idea_text, "--evidence")

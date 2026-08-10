from __future__ import annotations

from repo_paths import initialize_test_workspace

import ast
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

import research.confirm as confirmation
import research.records as records
from research.common import load_yaml, write_yaml_if_changed
from research.core import (
    confirm_unit,
    ensure_workspace,
    locate_record,
    promote_record,
    record_path,
    runtime_preferences_path,
    write_record,
)
from research.evidence import (
    build_verification_receipt,
    confirmation_content_digest,
    confirmation_evidence_digest,
)


def _project_root() -> Path:
    return REPO_ROOT


def _script_text(skill: str, script_name: str) -> str:
    return (_project_root() / "skills" / skill / "scripts" / script_name).read_text(encoding="utf-8")


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


def _verified_judgement_record(root: Path, *, title: str) -> dict:
    unit_id = "p-confirm-snapshot-123456"
    record = _record(unit_id)
    record["title"] = title
    record["information_types"] = ["fact", "evaluation", "unverified"]
    record["payload"] = {
        "core_content": {"method": f"{title} grounded method"},
        "claims": [
            {
                "id": "claim-confirm-snapshot",
                "text": f"{title} is the record under review.",
                "claim_type": "evaluation",
                "confirmation_status": "pending_user_confirmation",
                "evidence_refs": [
                    {
                        "source_unit_id": unit_id,
                        "artifact": "parse-cache.yaml",
                        "locator": "section=analysis",
                        "quote": f"{title} evidence bytes",
                    }
                ],
            }
        ],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "parse-cache.yaml").write_text(f"{title} evidence bytes", encoding="utf-8")
    build_verification_receipt(record, root)
    return record


def test_detached_same_revision_record_cannot_confirm_replacement(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    path = record_path(tmp_path, "paper", "p-confirm-snapshot-123456")
    old = _verified_judgement_record(path.parent, title="OLD RECORD")
    write_record(tmp_path, old)
    detached, _ = locate_record(tmp_path, old["id"], kind="paper", fuzzy=False)
    expected = records.canonical_record_snapshot_for_record(tmp_path, detached)
    original_dir = tmp_path / "old-detached-unit"
    replacement_dir = tmp_path / "new-replacement-unit"
    new = _verified_judgement_record(replacement_dir, title="NEW RECORD")
    new["revision"] = detached["revision"]
    write_yaml_if_changed(replacement_dir / "record.yaml", new)
    path.parent.rename(original_dir)
    replacement_dir.rename(path.parent)
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="snapshot|changed|current"):
        confirm_unit(
            detached,
            "paper",
            confirmed_by="Human Reviewer",
            evidence=["Reviewed OLD RECORD."],
            user_authorization="I confirm OLD RECORD.",
            authorization_source="user_message",
            project_root=tmp_path,
            expected_record_snapshot=expected,
        )

    assert path.read_bytes() == before
    assert load_yaml(path)["title"] == "NEW RECORD"
    assert load_yaml(path)["confirmation_status"] == "pending_user_confirmation"
    assert detached["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in detached


def test_same_bytes_new_inode_rejects_persisted_confirmation(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    unit_id = "p-confirm-same-bytes-123456"
    path = record_path(tmp_path, "paper", unit_id)
    write_yaml_if_changed(path, _record(unit_id))
    detached, _ = locate_record(tmp_path, unit_id, kind="paper", fuzzy=False)
    expected = records.canonical_record_snapshot_for_record(tmp_path, detached)
    copied = path.parent / "record-copy.yaml"
    copied.write_bytes(path.read_bytes())
    copied.replace(path)
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="snapshot|changed|current"):
        confirm_unit(
            detached,
            "paper",
            confirmed_by="Human Reviewer",
            evidence=["Reviewed exact record."],
            project_root=tmp_path,
            expected_record_snapshot=expected,
        )

    assert path.read_bytes() == before
    assert load_yaml(path).get("revision", 0) == detached["revision"]
    assert "confirmation" not in load_yaml(path)


def test_artifact_change_after_confirmation_before_write_is_zero_write(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    path = record_path(tmp_path, "paper", "p-confirm-snapshot-123456")
    record = _verified_judgement_record(path.parent, title="STABLE RECORD")
    write_record(tmp_path, record)
    detached, _ = locate_record(tmp_path, record["id"], kind="paper", fuzzy=False)
    expected = records.canonical_record_snapshot_for_record(tmp_path, detached)
    confirmed = confirm_unit(
        detached,
        "paper",
        confirmed_by="Human Reviewer",
        evidence=["Reviewed stable evidence."],
        user_authorization="I confirm the stable record.",
        authorization_source="user_message",
        project_root=tmp_path,
        expected_record_snapshot=expected,
    )
    (path.parent / "parse-cache.yaml").write_text("replacement evidence bytes", encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="verification|snapshot|changed|current"):
        write_record(
            tmp_path,
            confirmed,
            expected_record_snapshot=expected,
        )

    assert path.read_bytes() == before
    on_disk = load_yaml(path)
    assert on_disk["revision"] == 1
    assert on_disk["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in on_disk


def test_ancestor_replacement_after_confirmation_before_write_is_zero_write(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    unit_id = "p-confirm-ancestor-123456"
    path = record_path(tmp_path, "paper", unit_id)
    write_record(tmp_path, _record(unit_id))
    detached, _ = locate_record(tmp_path, unit_id, kind="paper", fuzzy=False)
    expected = records.canonical_record_snapshot_for_record(tmp_path, detached)
    confirmed = confirm_unit(
        detached,
        "paper",
        confirmed_by="Human Reviewer",
        evidence=["Reviewed ancestor-bound record."],
        project_root=tmp_path,
        expected_record_snapshot=expected,
    )
    papers_root = path.parent.parent
    displaced_root = papers_root.parent / "papers-displaced"
    papers_root.rename(displaced_root)
    papers_root.mkdir()
    (displaced_root / unit_id).rename(papers_root / unit_id)
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="snapshot|changed|current"):
        write_record(tmp_path, confirmed, expected_record_snapshot=expected)

    assert path.read_bytes() == before
    assert load_yaml(path)["confirmation_status"] == "pending_user_confirmation"


def test_persisted_unit_confirmation_cannot_omit_snapshot(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    unit_id = "p-confirm-missing-snapshot-123456"
    path = record_path(tmp_path, "paper", unit_id)
    write_yaml_if_changed(path, _record(unit_id))
    detached, _ = locate_record(tmp_path, unit_id, kind="paper", fuzzy=False)
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="expected_record_snapshot"):
        confirm_unit(
            detached,
            "paper",
            confirmed_by="Human Reviewer",
            evidence=["Reviewed current record."],
            project_root=tmp_path,
        )

    assert path.read_bytes() == before
    assert detached["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in detached


def test_persisted_confirmation_forces_snapshot_bound_source_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initialize_test_workspace(tmp_path)
    unit_id = "p-confirm-roots-123456"
    write_record(tmp_path, _record(unit_id))
    detached, _ = locate_record(tmp_path, unit_id, kind="paper", fuzzy=False)
    expected = records.canonical_record_snapshot_for_record(tmp_path, detached)
    seen: list[object] = []

    def capture_roots(_root, _record_value, **kwargs):
        seen.append(kwargs.get("expected_record_snapshot"))
        return {}

    monkeypatch.setattr(confirmation, "trusted_claim_source_roots", capture_roots)
    confirmation.apply_confirmation(
        detached,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed canonical source roots."],
        project_root=tmp_path,
        trusted_source_roots={"untrusted": tmp_path},
        expected_record_snapshot=expected,
    )

    assert seen == [expected]


def test_authorized_content_change_before_write_is_rejected(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    path = record_path(tmp_path, "paper", "p-confirm-snapshot-123456")
    record = _verified_judgement_record(path.parent, title="AUTHORIZED RECORD")
    write_record(tmp_path, record)
    detached, _ = locate_record(tmp_path, record["id"], kind="paper", fuzzy=False)
    expected = records.canonical_record_snapshot_for_record(tmp_path, detached)
    confirmed = confirm_unit(
        detached,
        "paper",
        confirmed_by="Human Reviewer",
        evidence=["Reviewed authorized content."],
        user_authorization="I confirm the authorized record.",
        authorization_source="user_message",
        project_root=tmp_path,
        expected_record_snapshot=expected,
    )
    confirmed["title"] = "CHANGED AFTER AUTHORIZATION"
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="changed after authorization"):
        write_record(tmp_path, confirmed, expected_record_snapshot=expected)

    assert path.read_bytes() == before


def test_confirmed_receipt_cannot_bypass_missing_snapshot_at_write(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    unit_id = "p-confirm-write-bypass-123456"
    path = record_path(tmp_path, "paper", unit_id)
    pending = _record(unit_id)
    write_record(tmp_path, pending)
    detached, _ = locate_record(tmp_path, unit_id, kind="paper", fuzzy=False)
    # Pure in-memory confirmation remains compatible, but cannot be written over
    # the persisted pending subject without carrying its explicit snapshot.
    confirmed = confirm_unit(
        detached,
        "paper",
        confirmed_by="Human Reviewer",
        evidence=["Reviewed detached record."],
    )
    before = path.read_bytes()

    with pytest.raises(SystemExit, match="expected_record_snapshot"):
        write_record(tmp_path, confirmed)

    assert path.read_bytes() == before


def test_promote_can_confirm_with_explicit_lifecycle_updates(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    unit_id = "p-confirm-lifecycle-123456"
    write_record(tmp_path, _record(unit_id))

    path = promote_record(
        tmp_path,
        unit_id,
        status="active",
        maturity="complete",
        confirmation_status="confirmed",
        confirmed_by="Human Reviewer",
        evidence=["Reviewed lifecycle promotion."],
    )

    persisted = load_yaml(path)
    assert persisted["confirmation_status"] == "confirmed"
    assert persisted["status"] == "active"
    assert persisted["maturity"] == "complete"


def test_promote_to_confirmed_requires_human_provenance(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())

    with pytest.raises(SystemExit, match="--confirmed-by"):
        promote_record(tmp_path, "p-confirm-123456", confirmation_status="confirmed")

    with pytest.raises(SystemExit, match="--evidence"):
        promote_record(tmp_path, "p-confirm-123456", confirmation_status="confirmed", confirmed_by="czx")


def test_promote_to_confirmed_uses_configured_default_confirmed_by(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
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
    initialize_test_workspace(tmp_path)
    write_yaml_if_changed(record_path(tmp_path, "paper", "p-confirm-123456"), _record())
    write_yaml_if_changed(
        runtime_preferences_path(tmp_path),
        {
            "identity": {"default_confirmed_by": "czx-default"},
        },
    )

    with pytest.raises(SystemExit, match="--evidence"):
        promote_record(tmp_path, "p-confirm-123456", confirmation_status="confirmed")


@pytest.mark.parametrize("actor", ["Claude Fable", "Opus 4.5", "通义千问", "豆包", "Kimi"])
def test_configured_ai_default_signer_is_rejected(actor: str, tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    write_yaml_if_changed(
        runtime_preferences_path(tmp_path),
        {"identity": {"default_confirmed_by": actor}},
    )

    with pytest.raises(SystemExit, match="Self-signing is forbidden"):
        confirmation.require_confirmation_provenance(
            confirmed_by="",
            evidence=["Reviewed current evidence."],
            project_root=tmp_path,
        )


def test_promote_non_confirmed_does_not_require_provenance(tmp_path: Path) -> None:
    """Backward-compat guard: only confirmed transitions need provenance;
    auto_confirmed / pending / rejected must still work without --confirmed-by/--evidence."""
    initialize_test_workspace(tmp_path)
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

    initialize_test_workspace(tmp_path)
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
    for owner, skill, script_name in [
        ("paper-analyst", "unit-analyst", "paper.py"),
        ("repo-analyst", "unit-analyst", "repo.py"),
        ("experiment-workbench", "experiment-workbench", "experiment.py"),
    ]:
        text = _script_text(skill, script_name)
        assert "confirm_unit" in text
        assert "apply_confirmation" not in text
        assert _has_optional_arg(text, "--confirmed-by"), owner
        assert _has_required_arg(text, "--evidence"), owner

    shared_text = (
        _project_root() / "runtime/lib/research/analyzer_note_flow.py"
    ).read_text(encoding="utf-8")
    assert "confirm_unit" in shared_text
    assert "apply_confirmation" not in shared_text
    assert _has_optional_arg(shared_text, "--confirmed-by")
    assert _has_required_arg(shared_text, "--evidence")
    for owner, script_name in [
        ("blog-analyst", "blog.py"),
        ("dataset-analyst", "dataset.py"),
    ]:
        text = _script_text("unit-analyst", script_name)
        assert "AnalyzerNoteFlow" in text, owner
        assert "apply_confirmation" not in text, owner

    idea_text = _script_text("idea-workbench", "idea.py")
    assert "require_confirmation_provenance" in idea_text
    # R2 discussion conclusions are independent side judgement subjects and use
    # the shared receipt validator; idea selection keeps its explicit user-choice
    # provenance path.
    assert "apply_confirmation(" in idea_text
    assert _has_optional_arg(idea_text, "--confirmed-by")
    assert _has_required_arg(idea_text, "--evidence")

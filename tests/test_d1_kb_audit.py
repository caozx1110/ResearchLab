from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

from research.common import write_yaml_if_changed
from research.core import (
    apply_confirmation,
    audit_workspace,
    build_verification_receipt,
    default_record,
    lint_records,
    record_path,
)


def _snapshot(root: Path) -> dict[str, tuple]:
    if not root.exists() and not root.is_symlink():
        return {}
    items: dict[str, tuple] = {}
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        names = sorted(set(dirnames + filenames))
        for name in names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            stat = path.lstat()
            if path.is_symlink():
                items[relative] = ("link", stat.st_mode, stat.st_mtime_ns, os.readlink(path))
            elif path.is_dir():
                items[relative] = ("dir", stat.st_mode, stat.st_mtime_ns)
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                items[relative] = ("file", stat.st_mode, stat.st_mtime_ns, stat.st_size, digest)
        dirnames[:] = [name for name in dirnames if not (current_path / name).is_symlink()]
    return items


def _paper(root: Path, *, complete: bool = False) -> tuple[dict, Path]:
    record = default_record(
        "paper",
        title="Audit Paper",
        maturity="complete" if complete else "lightweight",
    )
    record["id"] = "p-audit-paper-12345678"
    record["status"] = "active"
    record["topics"] = ["uncategorized"] if complete else ["robotics"]
    record["tags"] = ["research"] if complete else ["vla"]
    record["taxonomy"] = {
        "primary_topic": record["topics"][0],
        "secondary_topics": [],
        "canonical_tags": list(record["tags"]),
        "topic_sources": [],
        "tag_sources": [],
        "pool_sources": [],
    }
    unit = root / "kb/units/papers" / record["id"]
    unit.mkdir(parents=True, exist_ok=True)
    return record, unit


def _write_record(root: Path, record: dict) -> Path:
    path = record_path(root, str(record["kind"]), str(record["id"]))
    write_yaml_if_changed(path, record)
    return path


def _git_commit_kb(root: Path) -> None:
    kb = root / "kb"
    subprocess.run(["git", "init", str(kb)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(kb), "config", "user.email", "audit@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(kb), "config", "user.name", "Audit Test"], check=True)
    subprocess.run(["git", "-C", str(kb), "add", "--all"], check=True)
    subprocess.run(["git", "-C", str(kb), "commit", "-m", "fixture"], check=True, capture_output=True, text=True)


def _codes(report: dict) -> set[str]:
    return {str(item["code"]) for item in report["findings"]}


def _load_script(relative_path: str, name: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_empty_workspace_is_pass_and_zero_write(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    before = _snapshot(root)

    report = audit_workspace(root)

    assert report == {
        "status": "PASS",
        "counts": {
            "total": 0,
            "error": 0,
            "warning": 0,
            "info": 0,
            "schema": 0,
            "integrity": 0,
            "recovery": 0,
            "security": 0,
            "quality": 0,
        },
        "findings": [],
    }
    assert _snapshot(root) == before
    assert not root.exists()


def test_audit_clean_git_workspace_is_pass_and_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "clean"
    record, _ = _paper(root)
    _write_record(root, record)
    _git_commit_kb(root)
    before = _snapshot(root)

    report = audit_workspace(root)

    assert report["status"] == "PASS"
    assert report["findings"] == []
    assert _snapshot(root) == before


def test_audit_recreates_two_paper_quality_and_recovery_defects(tmp_path: Path) -> None:
    root = tmp_path / "broken-quality"
    record, unit = _paper(root, complete=True)
    _write_record(root, record)
    write_yaml_if_changed(
        unit / "figures.yaml",
        {
            "candidate_figures": [
                {"figure": "figure-2", "kind": "figure", "label": "2"},
                {"figure": "figure-2", "kind": "figure", "label": "2"},
                {"figure": "figure-da", "kind": "figure", "label": "da"},
            ]
        },
    )
    _git_commit_kb(root)
    (unit / "note-fill.yaml").write_text("elements: []\n", encoding="utf-8")
    before = _snapshot(root)

    report = audit_workspace(root)

    assert report["status"] == "WARN"
    assert _codes(report) == {
        "RECOVERY_DIRTY_PRODUCT_FILE",
        "QUALITY_PAPER_METADATA_MISSING",
        "QUALITY_PAPER_TAXONOMY_DEFAULT",
        "QUALITY_FIGURE_DUPLICATE_IDENTITY",
        "QUALITY_FIGURE_SUSPICIOUS_LABEL",
    }
    assert report["counts"]["warning"] == 5
    assert _snapshot(root) == before


def test_audit_detects_stale_verification_and_confirmation_binding(tmp_path: Path) -> None:
    root = tmp_path / "stale"
    record, unit = _paper(root)
    artifact = unit / "parse-cache.md"
    artifact.write_text("The measured result improved by twelve percent.\n", encoding="utf-8")
    record["information_types"] = ["inference"]
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["payload"]["core_content"]["method"] = "A substantive audited method."
    record["payload"]["state"]["full_note_status"] = "pending_user_confirmation"
    record["payload"]["claims"] = [
        {
            "id": "claim-001",
            "text": "The method improves the measured result.",
            "claim_type": "inference",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": record["id"],
                    "artifact": "parse-cache.md",
                    "locator": "section=result",
                    "quote": "improved by twelve percent",
                }
            ],
        }
    ]
    build_verification_receipt(record, unit, verified_at="2026-07-19T00:00:00+00:00")
    apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["Explicit review in this test"],
        user_authorization="I confirm this judgement.",
        authorization_source="user_message",
        method="test",
        project_root=root,
    )
    _write_record(root, record)
    artifact.write_text("The measured result changed after verification.\n", encoding="utf-8")

    report = audit_workspace(root)

    assert report["status"] == "FAIL"
    assert "INTEGRITY_VERIFICATION_BINDING_STALE" in _codes(report)
    assert "INTEGRITY_CONFIRMATION_BINDING_INVALID" in _codes(report)


def test_audit_detects_incomplete_journal_and_symlink_escape_without_following(tmp_path: Path) -> None:
    root = tmp_path / "unsafe"
    (root / "kb/.journal").mkdir(parents=True)
    write_yaml_if_changed(
        root / "kb/.journal/op-incomplete.yaml",
        {
            "op_id": "op-incomplete",
            "root_op_id": "op-incomplete",
            "parent_op_id": "",
            "state": "begin",
            "sequence_ns": 1,
        },
    )
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("must not be read", encoding="utf-8")
    os.symlink(outside, root / "kb/escaped-source")
    before = _snapshot(root)

    report = audit_workspace(root)

    assert report["status"] == "FAIL"
    assert "RECOVERY_INCOMPLETE_OPERATION" in _codes(report)
    assert "SECURITY_SYMLINK_ESCAPE" in _codes(report)
    assert all(not Path(item["subject"]).is_absolute() for item in report["findings"])
    assert all("outside-secret" not in item["message"] for item in report["findings"])
    assert _snapshot(root) == before


def test_audit_reports_malformed_journal_without_exposing_parser_details_or_writing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "malformed-journal"
    journal = root / "kb/.journal"
    journal.mkdir(parents=True)
    entry = journal / "unsafe-detail.yaml"
    entry.write_text("op_id: unsafe-detail\nstate: begin\nsecret: outside-secret-token\n", encoding="utf-8")
    before = _snapshot(root)

    report = audit_workspace(root)

    recovery = [
        item for item in report["findings"]
        if item["code"] == "RECOVERY_INCOMPLETE_OPERATION"
    ]
    assert report["status"] == "FAIL"
    assert len(recovery) == 1
    assert recovery[0]["subject"] == "kb/.journal"
    assert "outside-secret-token" not in repr(report)
    assert _snapshot(root) == before


def test_audit_rejects_symlinked_kb_root_even_when_target_is_in_workspace(tmp_path: Path) -> None:
    root = tmp_path / "linked-root"
    target = root / "alternate-kb"
    target.mkdir(parents=True)
    os.symlink(target.name, root / "kb")
    before = _snapshot(root)

    report = audit_workspace(root)

    assert report["status"] == "FAIL"
    assert _codes(report) == {"SECURITY_SYMLINK_ESCAPE"}
    assert _snapshot(root) == before


def test_audit_includes_existing_lint_findings_without_changing_lint_api(tmp_path: Path) -> None:
    root = tmp_path / "schema"
    record, _ = _paper(root)
    record["status"] = "not-a-status"
    _write_record(root, record)

    lint_status, lint_issues = lint_records(root)
    report = audit_workspace(root)

    assert lint_status == "FAIL"
    assert any("invalid status" in issue for issue in lint_issues)
    assert report["status"] == "FAIL"
    assert "SCHEMA_RECORD_INVALID" in _codes(report)
    assert set(report) == {"status", "counts", "findings"}
    assert all(
        set(finding) == {"code", "category", "severity", "subject", "message"}
        for finding in report["findings"]
    )


def test_owner_audit_commands_are_agent_only_json_and_warn_is_success(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = tmp_path / "owner-warn"
    record, _ = _paper(root, complete=True)
    _write_record(root, record)

    kb_owner = _load_script(
        ".agents/skills/knowledge-base-manager/scripts/kb.py",
        "d1_kb_owner",
    )
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(root), "audit"])
    assert kb_owner.main() == 0
    kb_output = capsys.readouterr().out.strip()
    kb_report = json.loads(kb_output)
    assert kb_report["status"] == "WARN"
    assert str(root) not in kb_output

    wiki_owner = _load_script(
        ".agents/skills/wiki-adapter/scripts/wiki.py",
        "d1_wiki_owner",
    )
    monkeypatch.setattr(sys, "argv", ["wiki.py", "--root", str(root), "audit"])
    assert wiki_owner.main() == 0
    wiki_output = capsys.readouterr().out.strip()
    assert json.loads(wiki_output) == kb_report
    assert str(root) not in wiki_output


def test_owner_audit_command_returns_nonzero_only_for_fail(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "owner-fail"
    record, _ = _paper(root)
    record["status"] = "invalid-status"
    _write_record(root, record)
    kb_owner = _load_script(
        ".agents/skills/knowledge-base-manager/scripts/kb.py",
        "d1_kb_owner_fail",
    )

    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(root), "audit"])
    assert kb_owner.main() == 1
    output = capsys.readouterr().out.strip()
    assert json.loads(output)["status"] == "FAIL"
    assert str(root) not in output

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess

import pytest

import research.journal as journal
from research.git_ops import (
    checkpoint_and_report,
    dirty_kb_paths,
    ensure_kb_git_repo,
    git_checkpoint,
)
from research.common import append_program_reporting_event, program_reporting_events_path
from research.journal import abort_op, begin_op, journaled_op, load_op
from research.yaml_io import load_yaml


def _configure_kb_git(root: Path) -> None:
    ensure_kb_git_repo(root, create_initial_commit=False)
    subprocess.run(["git", "-C", str(root / "kb"), "config", "user.name", "R1 Tests"], check=True)
    subprocess.run(["git", "-C", str(root / "kb"), "config", "user.email", "r1@example.com"], check=True)
    git_checkpoint(
        root,
        "initial kb state",
        auto_init=False,
        target_paths=dirty_kb_paths(root),
    )


def test_checkpoint_rejects_missing_empty_and_broad_scopes(tmp_path: Path) -> None:
    ensure_kb_git_repo(tmp_path, create_initial_commit=False)

    for targets in (None, [], [""], [tmp_path / "kb"]):
        with pytest.raises(SystemExit, match="Checkpoint"):
            git_checkpoint(tmp_path, "must be scoped", auto_init=False, target_paths=targets)

    with pytest.raises(SystemExit, match="target_paths"):
        checkpoint_and_report(tmp_path, trigger="milestone", message="must be scoped")


def test_scoped_checkpoint_leaves_unrelated_tracked_and_untracked_drafts_dirty(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "units" / "papers" / "p-target" / "record.yaml"
    tracked_draft = tmp_path / "kb" / "notes" / "tracked.md"
    target.parent.mkdir(parents=True)
    tracked_draft.parent.mkdir(parents=True)
    target.write_text("target: original\n", encoding="utf-8")
    tracked_draft.write_text("tracked: original\n", encoding="utf-8")
    git_checkpoint(
        tmp_path,
        "seed scoped files",
        auto_init=False,
        target_paths=[target, tracked_draft],
    )

    target.write_text("target: changed\n", encoding="utf-8")
    tracked_draft.write_text("tracked: user draft\n", encoding="utf-8")
    untracked_draft = tmp_path / "kb" / "notes" / "untracked.md"
    untracked_draft.write_text("untracked draft\n", encoding="utf-8")

    result = git_checkpoint(
        tmp_path,
        "scoped checkpoint",
        auto_init=False,
        target_paths=[target],
    )

    assert result["files"] == ["units/papers/p-target/record.yaml"]
    status = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert " M notes/tracked.md" in status
    assert "?? notes/untracked.md" in status
    assert "p-target/record.yaml" not in status


def test_journaled_exception_restores_all_before_bytes_modes_and_removes_new_file(tmp_path: Path) -> None:
    first = tmp_path / "kb" / "notes" / "first.md"
    second = tmp_path / "kb" / "notes" / "second.md"
    created = tmp_path / "kb" / "notes" / "created.md"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first before\n")
    second.write_bytes(b"second before\n")
    os.chmod(first, 0o600)
    os.chmod(second, 0o640)

    with pytest.raises(RuntimeError, match="simulated second-file failure"):
        with journaled_op(tmp_path, "two-file-failure", [first, second, created]):
            first.write_bytes(b"first after\n")
            second.write_bytes(b"second after\n")
            created.write_bytes(b"new file\n")
            os.chmod(first, 0o644)
            os.chmod(second, 0o644)
            raise RuntimeError("simulated second-file failure")

    assert first.read_bytes() == b"first before\n"
    assert second.read_bytes() == b"second before\n"
    assert first.stat().st_mode & 0o777 == 0o600
    assert second.stat().st_mode & 0o777 == 0o640
    assert not created.exists()
    entries = sorted((tmp_path / "kb" / ".journal").glob("*.yaml"))
    entry = load_op(tmp_path, entries[-1].stem)
    assert entry["state"] == "abort"
    assert entry["before_snapshots"]["notes/created.md"]["kind"] == "absent"


def test_two_hundred_concurrent_reporting_appends_are_lossless_and_parseable(tmp_path: Path) -> None:
    program_id = "p-concurrent-reporting"

    def append(index: int) -> None:
        append_program_reporting_event(
            tmp_path,
            program_id,
            {
                "event_type": "test",
                "title": f"event-{index:03d}",
                "summary": f"summary-{index:03d}",
                "tags": ["r1"],
            },
            generated_by="r1-test",
        )

    with ThreadPoolExecutor(max_workers=24) as executor:
        list(executor.map(append, range(200)))

    path = program_reporting_events_path(tmp_path, program_id)
    payload = load_yaml(path)
    assert isinstance(payload, dict)
    items = payload["items"]
    assert len(items) == 200
    assert {item["title"] for item in items} == {f"event-{index:03d}" for index in range(200)}
    assert ".journal/" in (tmp_path / "kb" / ".gitignore").read_text(encoding="utf-8")


def test_failed_snapshot_restore_is_reported_and_never_marked_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "restore-failure.md"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    op_id = begin_op(tmp_path, "restore-failure", [target])
    target.write_text("after\n", encoding="utf-8")

    def fail_restore(*args, **kwargs):
        raise OSError("simulated restore I/O failure")

    monkeypatch.setattr(journal, "_restore_target", fail_restore)
    with pytest.raises(RuntimeError, match="simulated restore I/O failure"):
        abort_op(tmp_path, op_id, restore=True, error="original operation failed")

    entry = load_op(tmp_path, op_id)
    assert entry["state"] == "abort_failed"
    assert "simulated restore I/O failure" in entry["restoration_error"]
    assert entry["operation_error"] == "original operation failed"

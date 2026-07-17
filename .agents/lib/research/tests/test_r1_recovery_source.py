from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from research.git_ops import (
    checkpoint_and_report,
    dirty_kb_paths,
    ensure_kb_git_repo,
    git_checkpoint,
)


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

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT, install_test_workspace_rules

from research.git_ops import dirty_kb_paths, ensure_kb_git_repo, kb_repo_path
from research.journal import mutation_transaction
from research.path_contract import TargetClass
from research.paths import kb_root, rel, units_root
from research.prefs import ensure_workspace
from research.workspace_layout import (
    WORKSPACE_LAYOUT_MARKER_BYTES,
    WorkspaceLayoutError,
    initialize_workspace_layout,
    layout_marker_path,
    resolve_workspace_roots,
)


def _initialize(workspace: Path) -> None:
    workspace.mkdir()
    install_test_workspace_rules(workspace)
    initialize_workspace_layout(workspace, REPO_ROOT)
    ensure_workspace(workspace)


def test_explicit_initialization_activates_workspace_root_layout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".agents").mkdir()
    (workspace / "AGENTS.md").write_text("# User rules\n", encoding="utf-8")
    (workspace / ".gitignore").write_text("user-line\n", encoding="utf-8")

    snapshot = initialize_workspace_layout(workspace, REPO_ROOT)
    ensure_workspace(workspace)

    assert snapshot.roots.workspace_root == workspace
    assert snapshot.roots.data_root == workspace
    assert resolve_workspace_roots(workspace, REPO_ROOT).roots == snapshot.roots
    assert layout_marker_path(workspace).read_bytes() == WORKSPACE_LAYOUT_MARKER_BYTES
    assert kb_root(workspace) == workspace
    assert units_root(workspace) == workspace / "units"
    assert (workspace / "units" / "papers").is_dir()
    assert not (workspace / "kb").exists()
    gitignore = (workspace / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "user-line" in gitignore
    assert "/.agents/" in gitignore
    assert "/.journal/" in gitignore
    assert "/.runtime/" in gitignore


def test_non_init_workspace_creation_requires_layout_marker(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SystemExit, match="kb init"):
        ensure_workspace(workspace)

    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("collision", ("kb", ".git", "units", ".runtime", "notes.md"))
def test_initialization_refuses_legacy_outer_git_partial_and_unknown_collisions(
    tmp_path: Path,
    collision: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = workspace / collision
    if "." in collision and collision not in {".git", ".runtime"}:
        path.write_text("collision\n", encoding="utf-8")
    else:
        path.mkdir()

    before = sorted(item.name for item in workspace.iterdir())
    with pytest.raises(WorkspaceLayoutError):
        initialize_workspace_layout(workspace, REPO_ROOT)

    assert sorted(item.name for item in workspace.iterdir()) == before
    assert not layout_marker_path(workspace).exists()


def test_initialization_refuses_symlink_and_special_canonical_collision(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "config").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceLayoutError, match="symlink"):
        initialize_workspace_layout(workspace, REPO_ROOT)
    assert list(outside.iterdir()) == []

    (workspace / "config").unlink()
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO fixture requires POSIX")
    os.mkfifo(workspace / "config")
    with pytest.raises(WorkspaceLayoutError, match="special"):
        initialize_workspace_layout(workspace, REPO_ROOT)


def test_root_layout_preserves_logical_kb_reference_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _initialize(workspace)
    record = workspace / "units" / "papers" / "p-test" / "record.yaml"
    record.parent.mkdir(parents=True)
    record.write_text("id: p-test\n", encoding="utf-8")

    assert rel(workspace, record).encode("utf-8") == b"kb/units/papers/p-test/record.yaml"


def test_mutation_targets_reject_reserved_and_require_operational_opt_in(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _initialize(workspace)
    reserved = workspace / "AGENTS.md"
    reserved.write_text("# User rules\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        with mutation_transaction(workspace, "forbidden", [reserved]):
            pytest.fail("reserved mutation body must not run")

    runtime_target = workspace / ".runtime" / "owner-state.yaml"
    with pytest.raises(SystemExit):
        with mutation_transaction(workspace, "implicit-runtime", [runtime_target]):
            pytest.fail("operational mutation body must require explicit opt-in")

    with mutation_transaction(
        workspace,
        "explicit-runtime",
        [runtime_target],
        allowed_target_classes=(TargetClass.OPERATIONAL_STATE,),
        undoable=False,
        operation_role="bookkeeping",
    ):
        runtime_target.parent.mkdir(exist_ok=True)
        runtime_target.write_text("state: ready\n", encoding="utf-8")
    assert runtime_target.is_file()


def test_root_git_uses_explicit_canonical_scope_and_leaves_integration_untracked(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("# User rules\n", encoding="utf-8")
    initialize_workspace_layout(workspace, REPO_ROOT)
    ensure_workspace(workspace)

    payload = ensure_kb_git_repo(workspace, create_initial_commit=True)

    assert payload["head_exists"] is True
    assert kb_repo_path(workspace) == workspace
    tracked = subprocess.run(
        ["git", "-C", str(workspace), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "config/workspace-layout.yaml" in tracked
    assert "AGENTS.md" not in tracked
    assert all(not item.startswith(".agents/") for item in tracked)

    (workspace / "unknown.txt").write_text("not canonical\n", encoding="utf-8")
    dirty = [path.relative_to(workspace).as_posix() for path in dirty_kb_paths(workspace)]
    assert "unknown.txt" not in dirty
    assert "AGENTS.md" not in dirty

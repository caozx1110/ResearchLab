from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT


SYNC = REPO_ROOT / "install-lib" / "ws_sync.py"
INSTALLER = REPO_ROOT / "install.sh"


def _installer_environment() -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }


def _run_public_installer(
    workspace: Path,
    action: str,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            os.fspath(INSTALLER),
            action,
            "--project",
            os.fspath(workspace),
            "--yes",
            *extra,
        ],
        cwd=REPO_ROOT,
        env=_installer_environment(),
        text=True,
        capture_output=True,
        check=False,
    )


def _legacy_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "kb" / "units" / "papers" / "paper-legacy").mkdir(parents=True)
    (workspace / "kb" / "units" / "papers" / "paper-legacy" / "record.yaml").write_bytes(
        b"id: paper-legacy\ncanonical: true\n"
    )
    (workspace / "kb" / "raw.bin").write_bytes(b"legacy source bytes\x00")
    (workspace / "AGENTS.md").write_bytes(b"# User rules\n\nPreserve these bytes.\n")
    (workspace / ".gitignore").write_bytes(b"# user ignore\n/local-only/\n")
    return workspace


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, bytes | str | None], ...]:
    snapshot: list[tuple[str, int, bytes | str | None]] = []
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISREG(metadata.st_mode):
            payload: bytes | str | None = path.read_bytes()
        elif stat.S_ISLNK(metadata.st_mode):
            payload = os.readlink(path)
        else:
            payload = None
        snapshot.append((relative, metadata.st_mode, payload))
    return tuple(snapshot)


@pytest.mark.parametrize("action", ("install", "update", "reinstall"))
def test_internal_lifecycle_rejects_legacy_without_any_write(
    tmp_path: Path,
    action: str,
) -> None:
    workspace = _legacy_workspace(tmp_path)
    before = _tree_snapshot(workspace)

    result = subprocess.run(
        [
            sys.executable,
            os.fspath(SYNC),
            action,
            "--repo",
            os.fspath(REPO_ROOT),
            "--dir",
            os.fspath(workspace),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Research Vault v2 已停止写入" in result.stderr
    assert "新的空工作区" in result.stderr
    assert _tree_snapshot(workspace) == before


def test_public_installer_explains_hard_cutover_without_private_leakage(tmp_path: Path) -> None:
    workspace = _legacy_workspace(tmp_path)
    before = _tree_snapshot(workspace)

    result = _run_public_installer(workspace, "install", "--codex")
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "旧版知识库布局" in output
    assert "不会读取或搬运其中的数据" in output
    assert "本版本不提供旧格式迁移" in output
    for private_token in (
        "Traceback",
        "receipt_sha256",
        "--authorization",
        ".workspace-oss-migration-",
    ):
        assert private_token not in output
    assert _tree_snapshot(workspace) == before


@pytest.mark.parametrize("action", ("update", "reinstall"))
def test_existing_v2_install_stops_if_legacy_data_appears(
    tmp_path: Path,
    action: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    installed = _run_public_installer(workspace, "install", "--codex")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    (workspace / "kb").mkdir()
    (workspace / "kb" / "sentinel.bin").write_bytes(b"do not migrate or delete\x00")
    before = _tree_snapshot(workspace)

    result = _run_public_installer(workspace, action)

    assert result.returncode != 0
    assert "本版本不提供旧格式迁移" in result.stderr
    assert _tree_snapshot(workspace) == before


def test_installer_rejects_a_linked_workspace_identity_before_write(tmp_path: Path) -> None:
    real = tmp_path / "real-workspace"
    linked = tmp_path / "linked-workspace"
    real.mkdir()
    linked.symlink_to(real, target_is_directory=True)

    result = subprocess.run(
        [
            sys.executable,
            os.fspath(SYNC),
            "install",
            "--repo",
            os.fspath(REPO_ROOT),
            "--dir",
            os.fspath(linked),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert not any(real.iterdir())

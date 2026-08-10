from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT
from research.journal import mutation_transaction
from research.workspace_layout import (
    WorkspaceLayoutError,
    initialize_workspace_layout,
    require_workspace_rules,
)


PUBLIC_KB = REPO_ROOT / "skills" / "kb-cli" / "scripts" / "kb"
OWNER_KB = REPO_ROOT / "skills" / "knowledge-base-manager" / "scripts" / "kb.py"
RULES_BYTES = (REPO_ROOT / "runtime" / "WORKSPACE_RULES.md").read_bytes()


def _runtime_env() -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
    }


def _tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    result: dict[str, tuple[object, ...]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            result[relative] = (
                "file",
                mode,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        elif stat.S_ISDIR(metadata.st_mode):
            result[relative] = ("directory", mode)
        elif stat.S_ISLNK(metadata.st_mode):
            result[relative] = ("symlink", mode, os.readlink(path))
        else:
            result[relative] = ("special", mode, stat.S_IFMT(metadata.st_mode))
    return result


def _install_rules(root: Path) -> Path:
    path = root / ".agents" / "WORKSPACE_RULES.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(RULES_BYTES)
    return path


def test_valid_regular_workspace_rules_are_accepted(tmp_path: Path) -> None:
    _install_rules(tmp_path)

    require_workspace_rules(tmp_path)


@pytest.mark.parametrize("unsafe_kind", ["missing", "empty", "symlink", "fifo"])
def test_missing_or_unsafe_workspace_rules_fail_closed(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    agents = tmp_path / ".agents"
    agents.mkdir()
    rules = agents / "WORKSPACE_RULES.md"
    if unsafe_kind == "empty":
        rules.write_bytes(b"")
    elif unsafe_kind == "symlink":
        external = tmp_path / "external-rules.md"
        external.write_bytes(RULES_BYTES)
        rules.symlink_to(external)
    elif unsafe_kind == "fifo":
        os.mkfifo(rules)

    with pytest.raises(WorkspaceLayoutError, match="only read-only kb help or kb doctor"):
        require_workspace_rules(tmp_path)


def test_symlinked_agents_directory_fails_closed(tmp_path: Path) -> None:
    external = tmp_path / "external-agents"
    external.mkdir()
    (external / "WORKSPACE_RULES.md").write_bytes(RULES_BYTES)
    (tmp_path / ".agents").symlink_to(external, target_is_directory=True)

    with pytest.raises(WorkspaceLayoutError, match="only read-only kb help or kb doctor"):
        require_workspace_rules(tmp_path)


def test_mutation_transaction_rejects_before_journal_or_target_write(
    tmp_path: Path,
) -> None:
    initialize_workspace_layout(tmp_path, REPO_ROOT)
    before = _tree_snapshot(tmp_path)
    target = tmp_path / "units" / "papers" / "blocked.md"

    with pytest.raises(SystemExit, match="only read-only kb help or kb doctor"):
        with mutation_transaction(tmp_path, "blocked-without-rules", [target]):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("must not exist\n", encoding="utf-8")

    assert _tree_snapshot(tmp_path) == before
    assert not target.exists()
    assert not (tmp_path / ".journal").exists()


def test_owner_init_without_rules_has_zero_workspace_writes(tmp_path: Path) -> None:
    before = _tree_snapshot(tmp_path)

    result = subprocess.run(
        [sys.executable, str(OWNER_KB), "--root", str(tmp_path), "init"],
        cwd=REPO_ROOT,
        env=_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "only read-only kb help or kb doctor" in result.stderr
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("verb", ["help", "doctor"])
def test_public_read_only_rescue_works_without_rules_and_writes_nothing(
    tmp_path: Path,
    verb: str,
) -> None:
    before = _tree_snapshot(tmp_path)

    result = subprocess.run(
        [sys.executable, str(PUBLIC_KB), "--root", str(tmp_path), verb],
        cwd=REPO_ROOT,
        env=_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip()
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("verb", ["init", "status", "find"])
def test_public_non_rescue_verbs_are_blocked_without_rules_before_any_write(
    tmp_path: Path,
    verb: str,
) -> None:
    before = _tree_snapshot(tmp_path)
    argv = [sys.executable, str(PUBLIC_KB), "--root", str(tmp_path), verb]
    if verb == "init":
        argv.append("--non-interactive")
    elif verb == "find":
        argv.append("anything")

    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "only read-only kb help or kb doctor" in result.stderr
    assert _tree_snapshot(tmp_path) == before

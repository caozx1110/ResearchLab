from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from research.index import load_candidate_pools, load_topic_taxonomy
from research.prefs import load_runtime_preferences


def _snapshot(root: Path) -> list[tuple[str, bytes]]:
    if not root.exists():
        return []
    return [
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    if not root.exists() and not root.is_symlink():
        return ()
    entries: list[tuple[str, str, bytes]] = []
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path).encode()))
        elif path.is_dir():
            entries.append((relative, "directory", b""))
        elif path.is_file():
            entries.append((relative, "file", path.read_bytes()))
        else:
            entries.append((relative, "other", b""))
    return tuple(entries)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _safe_runtime_env() -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }


def test_semantic_loaders_return_defaults_without_creating_workspace(tmp_path: Path) -> None:
    root = tmp_path / "fresh-project"
    before = _snapshot(root)

    preferences = load_runtime_preferences(root)
    taxonomy = load_topic_taxonomy(root)
    pools = load_candidate_pools(root)

    assert preferences["autonomy"]["auto_execute_scope"]
    assert taxonomy["id"] == "topic-taxonomy"
    assert taxonomy["topics"] == {}
    assert pools["id"] == "candidate-pools"
    assert pools["pools"] == {}
    assert _snapshot(root) == before
    assert not root.exists()


@pytest.mark.parametrize(
    "arguments",
    (
        ("dashboard",),
        ("next",),
        ("route", "--task", "综述"),
        ("auto",),
    ),
)
def test_orchestrator_semantic_reads_do_not_seed_fresh_workspace(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    root = tmp_path / "fresh-project"
    before = _tree_snapshot(root)
    script = _project_root() / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py"

    completed = subprocess.run(
        [sys.executable, "-B", str(script), "--root", str(root), *arguments],
        cwd=_project_root(),
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _tree_snapshot(root) == before
    assert not root.exists()

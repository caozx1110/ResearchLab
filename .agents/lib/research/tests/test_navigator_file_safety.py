from __future__ import annotations

from pathlib import Path

import pytest

from serve_kb_browser import _is_writable_text, _resolve_project_path


def test_resolve_project_path_accepts_workspace_relative_path(tmp_path: Path) -> None:
    target = _resolve_project_path(tmp_path, "kb/user/navigation.md")

    assert target == (tmp_path / "kb/user/navigation.md").resolve()


@pytest.mark.parametrize("raw_path", ["../outside.md", "/tmp/outside.md"])
def test_resolve_project_path_rejects_escape_paths(tmp_path: Path, raw_path: str) -> None:
    with pytest.raises(ValueError):
        _resolve_project_path(tmp_path, raw_path)


def test_is_writable_text_allows_plain_markdown(tmp_path: Path) -> None:
    path = tmp_path / "kb/units/papers/p-test-123456/note.md"

    assert _is_writable_text(tmp_path, path)


@pytest.mark.parametrize(
    "relative_path",
    [
        "kb/units/papers/p-test-123456/record.yaml",
        "kb/user/kb/index.md",
        "kb/user/navigator/state.md",
        ".git/COMMIT_EDITMSG",
    ],
)
def test_is_writable_text_blocks_non_md_and_blocked_roots(tmp_path: Path, relative_path: str) -> None:
    assert not _is_writable_text(tmp_path, tmp_path / relative_path)

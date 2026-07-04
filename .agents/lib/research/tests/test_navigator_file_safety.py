from __future__ import annotations

import sys
from pathlib import Path

import pytest

import build_kb_browser
from serve_kb_browser import _is_writable_text, _resolve_project_path


def test_build_kb_browser_root_overrides_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    discovered_root = tmp_path / "discovered"
    explicit_root = tmp_path / "explicit"
    for root in (discovered_root, explicit_root):
        (root / ".agents").mkdir(parents=True)
        (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")

    monkeypatch.chdir(discovered_root)
    monkeypatch.setattr(sys, "argv", ["build_kb_browser.py", "--root", str(explicit_root)])

    assert build_kb_browser.main() == 0
    assert (explicit_root / "kb" / "user" / "kb" / "index.html").exists()
    assert not (discovered_root / "kb" / "user" / "kb" / "index.html").exists()


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

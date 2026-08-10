from __future__ import annotations

import sys
from pathlib import Path

import pytest

import build_kb_browser
import open_kb_browser
import serve_kb_browser
import status_kb_browser
import stop_kb_browser
from kb_browser_lib import project_root_from_script
from serve_kb_browser import _is_writable_text, _resolve_project_path


@pytest.mark.parametrize(
    ("module", "script_name"),
    [
        (build_kb_browser, "build_kb_browser.py"),
        (open_kb_browser, "open_kb_browser.py"),
        (serve_kb_browser, "serve_kb_browser.py"),
        (status_kb_browser, "status_kb_browser.py"),
        (stop_kb_browser, "stop_kb_browser.py"),
    ],
)
@pytest.mark.parametrize("flag", ["--root", "--project-root"])
def test_kb_browser_project_root_flags_share_destination(
    module: object,
    script_name: str,
    flag: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", [script_name, flag, str(tmp_path)])

    args = module.parse_args()

    assert args.project_root == str(tmp_path)


def test_kb_browser_root_alias_passes_to_project_root_resolver(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()

    resolved = project_root_from_script(Path(__file__), explicit_root=str(root))

    assert resolved == root.resolve()


def test_serve_kb_browser_rejects_non_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["serve_kb_browser.py", "--host", "0.0.0.0"])

    with pytest.raises(SystemExit):
        serve_kb_browser.parse_args()


def test_serve_kb_browser_allows_explicit_non_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["serve_kb_browser.py", "--host", "0.0.0.0", "--allow-non-loopback"],
    )

    args = serve_kb_browser.parse_args()

    assert args.host == "0.0.0.0"
    assert args.allow_non_loopback is True


def test_build_kb_browser_root_overrides_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    discovered_root = tmp_path / "discovered"
    explicit_root = tmp_path / "explicit"
    for root in (discovered_root, explicit_root):
        (root / ".agents").mkdir(parents=True)
        (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")

    monkeypatch.chdir(discovered_root)
    monkeypatch.setattr(sys, "argv", ["build_kb_browser.py", "--root", str(explicit_root)])

    assert build_kb_browser.main() == 0
    assert (explicit_root / "user" / "index.html").exists()
    assert not (discovered_root / "user" / "index.html").exists()


def test_resolve_project_path_accepts_workspace_relative_path(tmp_path: Path) -> None:
    target = _resolve_project_path(tmp_path, "kb/user/navigation.md")

    assert target == (tmp_path / "user/navigation.md").resolve()


@pytest.mark.parametrize("raw_path", ["../outside.md", "/tmp/outside.md"])
def test_resolve_project_path_rejects_escape_paths(tmp_path: Path, raw_path: str) -> None:
    with pytest.raises(ValueError):
        _resolve_project_path(tmp_path, raw_path)


def test_is_writable_text_allows_plain_markdown(tmp_path: Path) -> None:
    path = tmp_path / "units/papers/p-test-123456/note.md"

    assert _is_writable_text(tmp_path, path)


@pytest.mark.parametrize(
    "relative_path",
    [
        "kb/units/papers/p-test-123456/raw/source.md",
        "kb/units/blogs/b-test-123456/raw/snapshot.txt",
        "kb/units/papers/p-test-123456/source/snapshot.md",
        "kb/units/papers/p-test-123456/parse-cache.yaml",
    ],
)
def test_is_writable_text_blocks_immutable_unit_evidence(tmp_path: Path, relative_path: str) -> None:
    assert not _is_writable_text(tmp_path, tmp_path / relative_path)


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

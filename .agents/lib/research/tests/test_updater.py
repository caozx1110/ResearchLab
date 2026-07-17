from __future__ import annotations

import json
from pathlib import Path

from research import updater


def test_parse_and_compare_semver_tolerates_junk() -> None:
    assert updater.compare_versions("0.1.0", "0.2.0") == -1
    assert updater.compare_versions("1.2.3", "1.2.3") == 0
    assert updater.compare_versions("2.0.0", "1.9.9") == 1
    assert updater.parse_semver("junk.2.nope") == (0, 2, 0)


def test_read_local_version_and_missing_default(tmp_path: Path) -> None:
    assert updater.read_local_version(tmp_path) == "0.0.0"
    version_path = tmp_path / ".agents" / "VERSION"
    version_path.parent.mkdir()
    version_path.write_text("0.1.0\n", encoding="utf-8")
    assert updater.read_local_version(tmp_path) == "0.1.0"


def test_check_reports_available_equal_and_unknown(monkeypatch, tmp_path: Path) -> None:
    version_path = tmp_path / ".agents" / "VERSION"
    version_path.parent.mkdir()
    version_path.write_text("0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(updater, "resolve_source_checkout", lambda _root: None)

    monkeypatch.setattr(updater, "fetch_remote_version", lambda _checkout, _cache: "0.2.0")
    assert updater.check(tmp_path, tmp_path / "cache") == {
        "local": "0.1.0",
        "remote": "0.2.0",
        "status": "update_available",
    }

    monkeypatch.setattr(updater, "fetch_remote_version", lambda _checkout, _cache: "0.1.0")
    assert updater.check(tmp_path, tmp_path / "cache")["status"] == "up_to_date"

    def fail_fetch(_checkout, _cache):
        raise ValueError("unexpected remote response")

    monkeypatch.setattr(updater, "fetch_remote_version", fail_fetch)
    result = updater.check(tmp_path, tmp_path / "cache")
    assert result == {"local": "0.1.0", "remote": "unknown", "status": "unknown"}


def test_resolve_source_checkout_uses_manifest_checkout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    install = tmp_path / "install"
    manifest = install / updater.MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"source_repo": str(source)}), encoding="utf-8")

    assert updater.resolve_source_checkout(install) == source


def test_apply_checkout_uses_ff_only_pull_and_never_pushes(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    version_path = tmp_path / ".agents" / "VERSION"
    version_path.parent.mkdir()
    version_path.write_text("0.1.0\n", encoding="utf-8")
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run_git(checkout: Path, *args: str):
        calls.append((checkout, args))
        if args[:2] == ("pull", "--ff-only"):
            version_path.write_text("0.2.0\n", encoding="utf-8")

    monkeypatch.setattr(updater, "_run_git", fake_run_git)

    result = updater.apply(tmp_path, tmp_path / "cache")

    assert result == {"before": "0.1.0", "after": "0.2.0", "status": "updated"}
    assert calls == [(tmp_path, ("pull", "--ff-only", "origin", "main"))]
    assert all("push" not in args for _checkout, args in calls)


def test_apply_copy_install_invokes_ws_sync_update_without_force(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (source / ".agents").mkdir()
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    manifest_path = install / updater.MANIFEST_REL
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"source_repo": str(source)}), encoding="utf-8")
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    process_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(updater, "_pull_checkout", lambda _source: None)
    monkeypatch.setattr(updater, "_source_commit", lambda _source: "abc123")

    def fake_run_process(argv, *, capture_output=True):
        del capture_output
        process_calls.append(tuple(argv))
        (install / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    monkeypatch.setattr(updater, "_run_process", fake_run_process)

    result = updater.apply(install, tmp_path / "cache")

    assert result == {"before": "0.1.0", "after": "0.2.0", "status": "updated"}
    assert len(process_calls) == 1
    argv = process_calls[0]
    assert argv[2:] == (
        "update",
        "--repo",
        str(source),
        "--dir",
        str(install),
        "--source-commit",
        "abc123",
    )
    assert "--force" not in argv
    assert "push" not in argv

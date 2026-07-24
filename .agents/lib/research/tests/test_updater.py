from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from research import updater


def _write_copy_manifest(root: Path, **overrides: object) -> Path:
    manifest_path = root / updater.MANIFEST_REL
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema": 1,
        "install_name": "workspace-oss",
        "install_mode": "copy-project",
        "version": "0.1.0",
        "files": {".agents/VERSION": "version-digest"},
        "agents_md": "managed-block",
        "unrelated": {"keep": [1, "two"]},
    }
    payload.update(overrides)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=3) + "\n", encoding="utf-8")
    (root / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    return manifest_path


def test_compare_semver_honors_stable_and_prerelease_precedence() -> None:
    assert updater.compare_versions("0.1.0", "0.2.0") == -1
    assert updater.compare_versions("1.2.3", "1.2.3") == 0
    assert updater.compare_versions("2.0.0", "1.9.9") == 1
    assert updater.compare_versions("0.1.0-rc.1", "0.1.0") == -1
    assert updater.compare_versions("0.1.0", "0.2.0-rc.1") == -1
    assert updater.compare_versions("0.1.0-rc.1", "0.1.0-rc.2") == -1
    assert updater.compare_versions("0.1.0-alpha", "0.1.0-rc.1") == -1
    assert updater.compare_versions("0.1.0-rc.1+build.7", "0.1.0-rc.1+build.9") == 0
    assert updater.parse_semver("junk.2.nope") == (0, 0, 0, 0, ())


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
    provenance = updater.SourceProvenance("git@example.test:team/fork.git", tmp_path / "source", "release/r1")
    monkeypatch.setattr(updater, "source_provenance", lambda _root: provenance)

    monkeypatch.setattr(updater, "fetch_remote_version", lambda _provenance, _cache: "0.2.0")
    assert updater.check(tmp_path, tmp_path / "cache") == {
        "local": "0.1.0",
        "remote": "0.2.0",
        "status": "update_available",
        "source_origin": "git@example.test:team/fork.git",
        "source_branch": "release/r1",
    }

    monkeypatch.setattr(updater, "fetch_remote_version", lambda _provenance, _cache: "0.1.0")
    assert updater.check(tmp_path, tmp_path / "cache")["status"] == "up_to_date"

    def fail_fetch(_provenance, _cache):
        raise ValueError("unexpected remote response")

    monkeypatch.setattr(updater, "fetch_remote_version", fail_fetch)
    result = updater.check(tmp_path, tmp_path / "cache")
    assert result == {"local": "0.1.0", "remote": "unknown", "status": "unknown"}


def test_resolve_source_checkout_uses_manifest_checkout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "install-lib").mkdir(parents=True)
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
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
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "git@example.test:team/fork.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "release/r1")

    def fake_run_git(checkout: Path, *args: str):
        calls.append((checkout, args))
        if args[:2] == ("pull", "--ff-only"):
            version_path.write_text("0.2.0\n", encoding="utf-8")
        return type("Completed", (), {"stdout": ""})()

    monkeypatch.setattr(updater, "_run_git", fake_run_git)

    result = updater.apply(tmp_path, tmp_path / "cache")

    assert result == {"before": "0.1.0", "after": "0.2.0", "status": "updated"}
    assert calls == [(tmp_path, ("pull", "--ff-only", "origin", "release/r1"))]
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
    manifest_path.write_text(
        json.dumps(
            {
                "source_origin": "git@example.test:team/fork.git",
                "source_checkout": str(source),
                "source_branch": "release/r1",
            }
        ),
        encoding="utf-8",
    )
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    process_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "git@example.test:team/fork.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "release/r1")
    monkeypatch.setattr(updater, "_pull_checkout", lambda _source, **_kwargs: None)
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
        "--source-origin",
        "git@example.test:team/fork.git",
        "--source-branch",
        "release/r1",
        "--source-strategy",
        "remote-branch",
        "--source-checkout",
        str(source),
    )
    assert "--force" not in argv
    assert "push" not in argv


@pytest.mark.parametrize(
    ("installed_version", "source_version"),
    [
        pytest.param("0.2.0", "0.2.0", id="equal"),
        pytest.param("0.2.0", "0.1.9", id="lower-stable"),
        pytest.param("0.2.0", "0.2.0-rc.1", id="lower-prerelease"),
    ],
)
def test_apply_copy_install_skips_sync_when_source_is_not_newer(
    monkeypatch,
    tmp_path: Path,
    installed_version: str,
    source_version: str,
) -> None:
    install = tmp_path / "install"
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (source / ".agents").mkdir()
    source_version_path = source / ".agents" / "VERSION"
    source_version_path.write_text("9.9.9\n", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text(f"{installed_version}\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "git@example.test:team/fork.git",
                "source_checkout": str(source),
                "source_branch": "release/r1",
            }
        ),
        encoding="utf-8",
    )
    pull_calls: list[Path] = []
    sync_calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "git@example.test:team/fork.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "release/r1")

    def fake_pull(checkout: Path, **_kwargs: object) -> None:
        pull_calls.append(checkout)
        source_version_path.write_text(f"{source_version}\n", encoding="utf-8")

    monkeypatch.setattr(updater, "_pull_checkout", fake_pull)
    monkeypatch.setattr(updater, "_invoke_ws_sync", lambda *args: sync_calls.append(args))

    result = updater.apply(install, tmp_path / "cache")

    assert result == {"before": installed_version, "after": installed_version, "status": "up_to_date"}
    assert pull_calls == [source]
    assert sync_calls == []


def test_old_manifest_without_provenance_requires_choice_and_never_clones(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    manifest = install / updater.MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"schema": 1, "source_repo": ""}), encoding="utf-8")
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(
        updater,
        "_clone_checkout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not clone a default upstream")),
    )

    checked = updater.check(install, tmp_path / "cache")
    applied = updater.apply(install, tmp_path / "cache")

    assert checked["status"] == "needs_source_choice"
    assert applied["status"] == "needs_source_choice"


def test_remote_manifest_without_branch_requires_choice(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "git@example.test:team/fork.git",
                "source_checkout": str(source),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        updater,
        "_fetch_checkout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not guess a branch")),
    )

    assert updater.check(install, tmp_path / "cache")["status"] == "needs_source_choice"
    assert updater.apply(install, tmp_path / "cache")["status"] == "needs_source_choice"


@pytest.mark.parametrize("origin", ["git@example.test:team/fork.git", ""])
def test_detached_git_root_requires_source_choice(monkeypatch, tmp_path: Path, origin: str) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: origin)
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "")

    assert updater.source_provenance(tmp_path) is None


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_non_main_fork_update_preserves_branch_and_updates_manifest_e2e(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[4]
    source = tmp_path / "source"
    shutil.copytree(
        project / ".agents",
        source / ".agents",
        ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc", "*.pyo"),
    )
    shutil.copytree(project / "install-lib", source / "install-lib")
    shutil.copy2(project / "LICENSE", source / "LICENSE")
    (source / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")

    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
    _git(source, "config", "user.name", "Updater E2E")
    _git(source, "config", "user.email", "updater@example.test")
    _git(source, "checkout", "-b", "release/r1")
    _git(source, "add", ".agents", "install-lib", "LICENSE")
    _git(source, "commit", "-m", "baseline")

    remote = tmp_path / "fork.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "release/r1")
    baseline_commit = _git(source, "rev-parse", "HEAD")

    install = tmp_path / "install"
    install.mkdir()
    installed = subprocess.run(
        [
            sys.executable,
            str(source / "install-lib" / "ws_sync.py"),
            "install",
            "--repo",
            str(source),
            "--dir",
            str(install),
            "--source-commit",
            baseline_commit,
            "--source-origin",
            str(remote),
            "--source-branch",
            "release/r1",
            "--agents",
            "codex",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    initial_manifest = json.loads((install / updater.MANIFEST_REL).read_text(encoding="utf-8"))
    assert initial_manifest["version"] == "0.1.0"
    assert initial_manifest["source_origin"] == str(remote)
    assert initial_manifest["source_branch"] == "release/r1"
    assert initial_manifest["source_checkout"] == ""
    assert initial_manifest["source_strategy"] == "remote-branch"

    (source / ".agents" / "VERSION").write_text("0.2.0-rc.1\n", encoding="utf-8")
    _git(source, "add", ".agents/VERSION")
    _git(source, "commit", "-m", "release candidate")
    _git(source, "push", "origin", "release/r1")
    release_commit = _git(source, "rev-parse", "HEAD")

    checked = updater.check(install, tmp_path / "cache")
    assert checked == {
        "local": "0.1.0",
        "remote": "0.2.0-rc.1",
        "status": "update_available",
        "source_origin": str(remote),
        "source_branch": "release/r1",
    }
    applied = updater.apply(install, tmp_path / "cache")

    assert applied == {"before": "0.1.0", "after": "0.2.0-rc.1", "status": "updated"}
    updated_manifest = json.loads((install / updater.MANIFEST_REL).read_text(encoding="utf-8"))
    assert updated_manifest["version"] == "0.2.0-rc.1"
    assert updated_manifest["source_origin"] == str(remote)
    assert updated_manifest["source_branch"] == "release/r1"
    assert updated_manifest["source_checkout"] == ""
    assert updated_manifest["source_strategy"] == "remote-branch"
    assert updated_manifest["source_commit"] == release_commit


def test_local_checkout_strategy_with_remote_origin_never_uses_network(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "local-source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir(parents=True)
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (source / ".agents").mkdir()
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": "feature/unpushed",
                "source_strategy": "local-checkout",
            }
        ),
        encoding="utf-8",
    )
    for name in ("_fetch_checkout", "_pull_checkout", "_clone_checkout"):
        monkeypatch.setattr(
            updater,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("local-checkout strategy must not use the network")
            ),
        )
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "feature/unpushed")
    monkeypatch.setattr(
        updater,
        "_checkout_origin",
        lambda _checkout: "ssh://example.test/team/workspace-oss.git",
    )
    monkeypatch.setattr(updater, "_source_commit", lambda _checkout: "local-only-commit")
    synced: list[updater.SourceProvenance] = []

    def fake_sync(_source: Path, _install: Path, _commit: str, provenance: updater.SourceProvenance) -> None:
        synced.append(provenance)
        (install / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    monkeypatch.setattr(updater, "_invoke_ws_sync", fake_sync)

    checked = updater.check(install, tmp_path / "cache")
    applied = updater.apply(install, tmp_path / "cache")

    assert checked["status"] == "update_available"
    assert checked["source_origin"] == "ssh://example.test/team/workspace-oss.git"
    assert applied == {"before": "0.1.0", "after": "0.2.0", "status": "updated"}
    assert len(synced) == 1
    assert synced[0].strategy == "local-checkout"
    assert synced[0].checkout == source


def test_local_checkout_skips_sync_when_worktree_version_is_not_newer(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "local-source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir(parents=True)
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (source / ".agents").mkdir()
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": "feature/unpushed",
                "source_strategy": "local-checkout",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        updater,
        "_checkout_origin",
        lambda _checkout: "ssh://example.test/team/workspace-oss.git",
    )
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "feature/unpushed")
    for name in ("_fetch_checkout", "_pull_checkout", "_clone_checkout"):
        monkeypatch.setattr(
            updater,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("local-checkout strategy must not use the network")
            ),
        )
    monkeypatch.setattr(
        updater,
        "_invoke_ws_sync",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("equal version must not sync")),
    )

    assert updater.check(install, tmp_path / "cache")["status"] == "up_to_date"
    assert updater.apply(install, tmp_path / "cache") == {
        "before": "0.2.0",
        "after": "0.2.0",
        "status": "up_to_date",
    }


@pytest.mark.parametrize(
    ("recorded_branch", "current_branch"),
    [
        pytest.param("feature/local", "", id="detached"),
        pytest.param("feature/local", "feature/other", id="switched"),
        pytest.param("", "", id="missing-recorded-branch"),
    ],
)
def test_remote_origin_local_checkout_requires_matching_symbolic_branch(
    monkeypatch,
    tmp_path: Path,
    recorded_branch: str,
    current_branch: str,
) -> None:
    install = tmp_path / "install"
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (source / ".agents").mkdir()
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": recorded_branch,
                "source_strategy": "local-checkout",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        updater,
        "_checkout_origin",
        lambda _checkout: "ssh://example.test/team/workspace-oss.git",
    )
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: current_branch)
    for name in ("_fetch_checkout", "_pull_checkout", "_clone_checkout"):
        monkeypatch.setattr(
            updater,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("branch gate must not use network")),
        )

    assert updater.check(install, tmp_path / "cache")["status"] == "needs_source_choice"
    assert updater.apply(install, tmp_path / "cache")["status"] == "needs_source_choice"


def test_remote_origin_local_checkout_rejects_origin_change_without_network(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (source / ".agents").mkdir()
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": "feature/local",
                "source_strategy": "local-checkout",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "ssh://example.test/team/other.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "feature/local")
    for name in ("_fetch_checkout", "_pull_checkout", "_clone_checkout"):
        monkeypatch.setattr(
            updater,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("origin gate must not use network")),
        )

    assert updater.check(install, tmp_path / "cache")["status"] == "needs_source_choice"
    assert updater.apply(install, tmp_path / "cache")["status"] == "needs_source_choice"


@pytest.mark.parametrize("checkout_state", ["missing", "invalid"])
def test_invalid_local_checkout_requires_choice_without_remote_fallback(
    monkeypatch,
    tmp_path: Path,
    checkout_state: str,
) -> None:
    install = tmp_path / "install"
    source = tmp_path / "recorded-source"
    if checkout_state == "invalid":
        source.mkdir()
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": "release/r1",
                "source_strategy": "local-checkout",
            }
        ),
        encoding="utf-8",
    )
    for name in ("_fetch_checkout", "_pull_checkout", "_clone_checkout"):
        monkeypatch.setattr(
            updater,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fall back to remote")),
        )

    assert updater.check(install, tmp_path / "cache")["status"] == "needs_source_choice"
    assert updater.apply(install, tmp_path / "cache")["status"] == "needs_source_choice"


def test_unknown_source_strategy_fails_closed(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "source"
    (source / "install-lib").mkdir(parents=True)
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    (install / ".agents").mkdir(parents=True)
    (install / ".agents" / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (install / updater.MANIFEST_REL).write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": "release/r1",
                "source_strategy": "guess-from-origin",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        updater,
        "_clone_checkout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unknown strategy must not clone")),
    )

    assert updater.check(install, tmp_path / "cache")["status"] == "needs_source_choice"
    assert updater.apply(install, tmp_path / "cache")["status"] == "needs_source_choice"


def test_linked_worktree_marker_is_accepted_for_local_checkout(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    source = tmp_path / "linked-source"
    source.mkdir()
    (source / ".git").write_text("gitdir: /tmp/example-worktree-metadata\n", encoding="utf-8")
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    manifest = install / updater.MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "source_origin": "ssh://example.test/team/workspace-oss.git",
                "source_checkout": str(source),
                "source_branch": "feature/linked",
                "source_strategy": "local-checkout",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "ssh://example.test/team/workspace-oss.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "feature/linked")

    provenance = updater.source_provenance(install)

    assert updater.is_git_checkout(source)
    assert provenance is not None
    assert provenance.checkout == source
    assert provenance.strategy == "local-checkout"


def test_detached_copy_manifest_choice_requests_only_branch_and_remote_rebind_is_offline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    install = tmp_path / "install"
    detached = tmp_path / "detached"
    (detached / ".git").mkdir(parents=True)
    (detached / ".agents").mkdir()
    (detached / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (detached / "install-lib").mkdir()
    (detached / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    manifest_path = _write_copy_manifest(
        install,
        source_origin="ssh://example.test/team/fork.git",
        source_checkout=str(detached),
        source_repo=str(detached),
        source_branch="",
        source_strategy="local-checkout",
        source_commit="old",
    )
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "ssh://example.test/team/fork.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "")

    request = updater.source_choice_request(install)

    assert request["fields"] == ["source_branch"]
    assert request["current"]["source_origin"] == "ssh://example.test/team/fork.git"
    assert request["apply"] == {
        "verb": "update",
        "expected_manifest_digest": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_origin": "ssh://example.test/team/fork.git",
        "source_strategy": "remote-branch",
        "provide": ["source_branch"],
    }
    for name in ("_fetch_checkout", "_pull_checkout", "_clone_checkout", "_invoke_ws_sync"):
        monkeypatch.setattr(
            updater,
            name,
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rebind must stay offline")),
        )

    rebound = updater.rebind_source(
        install,
        expected_manifest_digest=request["manifest_digest"],
        source_origin="ssh://example.test/team/fork.git",
        source_branch="release/r2",
        source_strategy="remote-branch",
    )

    assert rebound["status"] == "rebound"
    assert rebound["source_checkout"] == ""
    assert rebound["source_commit"] == ""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_origin"] == "ssh://example.test/team/fork.git"
    assert manifest["source_branch"] == "release/r2"
    assert manifest["source_strategy"] == "remote-branch"
    assert manifest["source_checkout"] == manifest["source_repo"] == ""
    assert manifest["source_commit"] == ""
    assert manifest["files"] == {".agents/VERSION": "version-digest"}
    assert manifest["unrelated"] == {"keep": [1, "two"]}


def test_legacy_manifest_choice_exposes_strategy_specific_minimal_field_sets(tmp_path: Path) -> None:
    install = tmp_path / "install"
    manifest = _write_copy_manifest(install, source_repo="")

    request = updater.source_choice_request(install)

    assert request["fields"] == ["source_strategy"]
    assert request["current"] == {}
    assert request["manifest_digest"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    alternatives = {item["source_strategy"]: item for item in request["alternatives"]}
    assert alternatives["remote-branch"]["fields"] == ["source_origin", "source_branch"]
    assert alternatives["local-checkout"]["fields"] == ["source_checkout"]

    updater.rebind_source(
        install,
        expected_manifest_digest=request["manifest_digest"],
        source_origin="ssh://example.test/team/fork.git",
        source_branch="release/legacy",
        source_strategy="remote-branch",
    )
    provenance = updater.source_provenance(install)
    assert provenance is not None
    assert provenance.origin == "ssh://example.test/team/fork.git"
    assert provenance.branch == "release/legacy"
    assert provenance.strategy == "remote-branch"


def test_local_checkout_rebind_verifies_origin_branch_and_preserves_manifest(tmp_path: Path) -> None:
    install = tmp_path / "install"
    manifest_path = _write_copy_manifest(install, source_repo="")
    source = tmp_path / "source"
    (source / ".agents").mkdir(parents=True)
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
    _git(source, "config", "user.name", "Updater Rebind")
    _git(source, "config", "user.email", "updater-rebind@example.test")
    _git(source, "checkout", "-b", "feature/local")
    _git(source, "add", ".agents", "install-lib")
    _git(source, "commit", "-m", "source")
    remote = tmp_path / "source.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _git(source, "remote", "add", "origin", str(remote))
    before = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    rebound = updater.rebind_source(
        install,
        expected_manifest_digest=digest,
        source_origin=str(remote),
        source_checkout=str(source),
        source_branch="feature/local",
        source_strategy="local-checkout",
    )

    after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rebound["source_commit"] == _git(source, "rev-parse", "HEAD")
    assert after["source_checkout"] == after["source_repo"] == str(source)
    assert after["source_origin"] == str(remote)
    assert after["source_branch"] == "feature/local"
    assert after["source_strategy"] == "local-checkout"
    for key in ("schema", "install_name", "install_mode", "version", "files", "agents_md", "unrelated"):
        assert after[key] == before[key]


def test_legacy_local_choice_derives_attached_checkout_origin_and_branch(tmp_path: Path) -> None:
    install = tmp_path / "install"
    manifest_path = _write_copy_manifest(install, source_repo="")
    request = updater.source_choice_request(install)
    local_choice = next(
        alternative
        for alternative in request["alternatives"]
        if alternative["source_strategy"] == "local-checkout"
    )
    assert local_choice["fields"] == ["source_checkout"]

    source = tmp_path / "attached-source"
    (source / ".agents").mkdir(parents=True)
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
    _git(source, "config", "user.name", "Updater Rebind")
    _git(source, "config", "user.email", "updater-rebind@example.test")
    _git(source, "checkout", "-b", "feature/inferred")
    _git(source, "add", ".agents", "install-lib")
    _git(source, "commit", "-m", "source")
    remote = tmp_path / "attached.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _git(source, "remote", "add", "origin", str(remote))

    rebound = updater.rebind_source(
        install,
        expected_manifest_digest=local_choice["apply"]["expected_manifest_digest"],
        source_checkout=str(source),
        source_strategy=local_choice["apply"]["source_strategy"],
    )

    assert rebound["source_origin"] == str(remote)
    assert rebound["source_branch"] == "feature/inferred"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_origin"] == str(remote)
    assert manifest["source_branch"] == "feature/inferred"
    assert manifest["source_checkout"] == str(source)


def test_detached_git_local_rebind_fails_closed_without_manifest_churn(tmp_path: Path) -> None:
    install = tmp_path / "install"
    manifest_path = _write_copy_manifest(install, source_repo="")
    source = tmp_path / "detached-local-source"
    (source / ".agents").mkdir(parents=True)
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, text=True)
    _git(source, "config", "user.name", "Updater Rebind")
    _git(source, "config", "user.email", "updater-rebind@example.test")
    _git(source, "checkout", "-b", "feature/local")
    _git(source, "add", ".agents", "install-lib")
    _git(source, "commit", "-m", "source")
    _git(source, "checkout", "--detach", "HEAD")
    before = manifest_path.read_bytes()
    inode_before = manifest_path.stat().st_ino

    payload = json.loads(before)
    payload.update(
        {
            "source_origin": "local",
            "source_checkout": str(source),
            "source_repo": str(source),
            "source_branch": "",
            "source_strategy": "local-checkout",
        }
    )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    before = manifest_path.read_bytes()
    inode_before = manifest_path.stat().st_ino

    request = updater.source_choice_request(install)
    local_choice = next(
        choice for choice in request["alternatives"] if choice["source_strategy"] == "local-checkout"
    )
    assert local_choice["fields"] == ["source_checkout"]
    assert "source_checkout" not in local_choice["apply"]

    with pytest.raises(updater.SourceRebindError) as rejected:
        updater.rebind_source(
            install,
            expected_manifest_digest=hashlib.sha256(before).hexdigest(),
            source_origin="local",
            source_checkout=str(source),
            source_branch="",
            source_strategy="local-checkout",
        )

    assert rejected.value.code == "source-branch-mismatch"
    assert manifest_path.read_bytes() == before
    assert manifest_path.stat().st_ino == inode_before

    # Historical manifests with the same invalid binding must also fail closed.
    assert updater.check(install, tmp_path / "cache")["status"] == "needs_source_choice"


def test_attached_git_and_nongit_local_rebinds_are_explicitly_supported(tmp_path: Path) -> None:
    attached_install = tmp_path / "attached-install"
    attached_manifest = _write_copy_manifest(attached_install, source_repo="")
    attached = tmp_path / "attached-local-source"
    (attached / ".agents").mkdir(parents=True)
    (attached / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (attached / "install-lib").mkdir()
    (attached / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", str(attached)], check=True, capture_output=True, text=True)
    _git(attached, "config", "user.name", "Updater Rebind")
    _git(attached, "config", "user.email", "updater-rebind@example.test")
    _git(attached, "checkout", "-b", "feature/local")
    _git(attached, "add", ".agents", "install-lib")
    _git(attached, "commit", "-m", "source")

    attached_result = updater.rebind_source(
        attached_install,
        expected_manifest_digest=hashlib.sha256(attached_manifest.read_bytes()).hexdigest(),
        source_origin="local",
        source_checkout=str(attached),
        source_branch="feature/local",
        source_strategy="local-checkout",
    )

    assert attached_result["source_branch"] == "feature/local"
    assert attached_result["source_commit"] == _git(attached, "rev-parse", "HEAD")

    nongit_install = tmp_path / "nongit-install"
    nongit_manifest = _write_copy_manifest(nongit_install, source_repo="")
    nongit = tmp_path / "nongit-source"
    (nongit / ".agents").mkdir(parents=True)
    (nongit / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (nongit / "install-lib").mkdir()
    (nongit / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")

    nongit_result = updater.rebind_source(
        nongit_install,
        expected_manifest_digest=hashlib.sha256(nongit_manifest.read_bytes()).hexdigest(),
        source_origin="local",
        source_checkout=str(nongit),
        source_branch="",
        source_strategy="local-checkout",
    )

    assert nongit_result["source_origin"] == "local"
    assert nongit_result["source_branch"] == ""
    assert nongit_result["source_commit"] == "local"


@pytest.mark.parametrize(
    ("choice", "code"),
    [
        ({"source_origin": "ssh://example.test/team/fork.git", "source_branch": "../bad"}, "invalid-source-branch"),
        ({"source_origin": "local", "source_branch": "release/r1"}, "invalid-source-origin"),
        ({"source_origin": "--upload-pack=malicious", "source_branch": "release/r1"}, "invalid-source-origin"),
    ],
)
def test_remote_rebind_rejects_invalid_choice_without_byte_change(
    tmp_path: Path,
    choice: dict[str, str],
    code: str,
) -> None:
    install = tmp_path / "install"
    manifest = _write_copy_manifest(install, source_repo="")
    before = manifest.read_bytes()

    with pytest.raises(updater.SourceRebindError) as rejected:
        updater.rebind_source(
            install,
            expected_manifest_digest=hashlib.sha256(before).hexdigest(),
            source_strategy="remote-branch",
            **choice,
        )

    assert rejected.value.code == code
    assert manifest.read_bytes() == before


def test_clone_checkout_terminates_git_options_before_origin(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        updater,
        "_run_process",
        lambda argv, **_kwargs: calls.append(tuple(argv)),
    )

    updater._clone_checkout("/tmp/local-remote.git", tmp_path / "checkout", branch="release/r1")

    assert calls == [
        (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "release/r1",
            "--",
            "/tmp/local-remote.git",
            str(tmp_path / "checkout"),
        )
    ]


def test_rebind_rejects_stale_digest_and_local_mismatch_without_byte_change(monkeypatch, tmp_path: Path) -> None:
    install = tmp_path / "install"
    manifest = _write_copy_manifest(install, source_repo="")
    before = manifest.read_bytes()
    with pytest.raises(updater.SourceRebindError) as stale:
        updater.rebind_source(
            install,
            expected_manifest_digest="0" * 64,
            source_origin="ssh://example.test/team/fork.git",
            source_branch="release/r1",
            source_strategy="remote-branch",
        )
    assert stale.value.code == "stale-manifest"
    assert manifest.read_bytes() == before

    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / ".agents").mkdir()
    (source / ".agents" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (source / "install-lib").mkdir()
    (source / "install-lib" / "ws_sync.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "ssh://example.test/actual.git")
    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "actual")
    with pytest.raises(updater.SourceRebindError) as mismatch:
        updater.rebind_source(
            install,
            expected_manifest_digest=hashlib.sha256(before).hexdigest(),
            source_origin="ssh://example.test/selected.git",
            source_checkout=str(source),
            source_branch="selected",
            source_strategy="local-checkout",
        )
    assert mismatch.value.code == "source-origin-mismatch"
    assert manifest.read_bytes() == before

    monkeypatch.setattr(updater, "_checkout_branch", lambda _checkout: "")
    with pytest.raises(updater.SourceRebindError) as detached:
        updater.rebind_source(
            install,
            expected_manifest_digest=hashlib.sha256(before).hexdigest(),
            source_origin="ssh://example.test/actual.git",
            source_checkout=str(source),
            source_strategy="local-checkout",
        )
    assert detached.value.code == "source-branch-mismatch"
    assert manifest.read_bytes() == before


def test_rebind_rejects_manifest_symlink_and_symlinked_ancestor_without_touching_target(tmp_path: Path) -> None:
    victim_root = tmp_path / "victim-root"
    victim_manifest = _write_copy_manifest(victim_root, source_repo="")
    victim_before = victim_manifest.read_bytes()

    leaf_install = tmp_path / "leaf-install"
    (leaf_install / ".agents").mkdir(parents=True)
    (leaf_install / updater.MANIFEST_REL).symlink_to(victim_manifest)
    with pytest.raises(updater.SourceRebindError) as leaf:
        updater.rebind_source(
            leaf_install,
            expected_manifest_digest=hashlib.sha256(victim_before).hexdigest(),
            source_origin="ssh://example.test/team/fork.git",
            source_branch="release/r1",
            source_strategy="remote-branch",
        )
    assert leaf.value.code == "unsafe-manifest-leaf"
    assert (leaf_install / updater.MANIFEST_REL).is_symlink()
    assert victim_manifest.read_bytes() == victim_before

    ancestor_install = tmp_path / "ancestor-install"
    ancestor_install.mkdir()
    (ancestor_install / ".agents").symlink_to(victim_root / ".agents", target_is_directory=True)
    with pytest.raises(updater.SourceRebindError) as ancestor:
        updater.rebind_source(
            ancestor_install,
            expected_manifest_digest=hashlib.sha256(victim_before).hexdigest(),
            source_origin="ssh://example.test/team/fork.git",
            source_branch="release/r1",
            source_strategy="remote-branch",
        )
    assert ancestor.value.code == "unsafe-manifest-ancestor"
    assert (ancestor_install / ".agents").is_symlink()
    assert victim_manifest.read_bytes() == victim_before


def test_rebind_rejects_nonregular_manifest_without_blocking(tmp_path: Path) -> None:
    install = tmp_path / "fifo-install"
    manifest = install / updater.MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    os.mkfifo(manifest)

    with pytest.raises(updater.SourceRebindError) as rejected:
        updater.rebind_source(
            install,
            expected_manifest_digest="0" * 64,
            source_origin="ssh://example.test/team/fork.git",
            source_branch="release/r1",
            source_strategy="remote-branch",
        )

    assert rejected.value.code == "unsafe-manifest-leaf"
    assert manifest.exists()

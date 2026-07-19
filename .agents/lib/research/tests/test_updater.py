from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from research import updater


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
    (source / ".git").mkdir(parents=True)
    (source / "install-lib").mkdir()
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


def test_detached_remote_checkout_requires_source_choice(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updater, "_checkout_origin", lambda _checkout: "git@example.test:team/fork.git")
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


def test_linked_worktree_marker_is_accepted_for_local_checkout(tmp_path: Path) -> None:
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

    provenance = updater.source_provenance(install)

    assert updater.is_git_checkout(source)
    assert provenance is not None
    assert provenance.checkout == source
    assert provenance.strategy == "local-checkout"

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT
from support import load_module, load_runtime_module, load_ws_sync, tree_snapshot


MANIFEST_REL = Path(".agents/.install-manifest.json")
MANAGED_MARKER = b"# >>> workspace-oss managed >>>"


def _installer_env(home: Path) -> dict[str, str]:
    home.mkdir(exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }


def _run_installer(action: str, workspace: Path, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "install.sh"),
            action,
            "--project",
            str(workspace),
            "--yes",
            *(["--codex"] if action == "install" else []),
        ],
        cwd=REPO_ROOT,
        env=_installer_env(home),
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_succeeded(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _sync_args(action: str, workspace: Path) -> list[str]:
    return [
        action,
        "--repo",
        str(REPO_ROOT),
        "--dir",
        str(workspace),
        "--agents",
        "codex",
        "--operation-time",
        "2026-08-25T00:00:00Z",
    ]


def test_public_install_update_reinstall_uninstall_preserves_user_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    agents = workspace / ".agents"
    agents.mkdir()

    root_note = workspace / "research-notes.md"
    user_agent_file = agents / "user-settings.json"
    agents_md = workspace / "AGENTS.md"
    original_agents_md = b"# Local workspace rules\n\nKeep this user-authored section.\n"
    root_note.write_bytes(b"user research stays here\n")
    user_agent_file.write_bytes(b'{"owner": "user"}\n')
    agents_md.write_bytes(original_agents_md)
    preserved = {
        root_note: root_note.read_bytes(),
        user_agent_file: user_agent_file.read_bytes(),
    }

    for action in ("install", "update", "reinstall"):
        _assert_succeeded(_run_installer(action, workspace, home))
        assert all(path.read_bytes() == content for path, content in preserved.items())
        assert original_agents_md in agents_md.read_bytes()
        assert MANAGED_MARKER in agents_md.read_bytes()
        assert (workspace / MANIFEST_REL).is_file()

    _assert_succeeded(_run_installer("uninstall", workspace, home))

    assert all(path.read_bytes() == content for path, content in preserved.items())
    assert agents_md.read_bytes() == original_agents_md
    assert not (workspace / MANIFEST_REL).exists()
    assert not (agents / "skills").exists()
    assert not (agents / "lib" / "research").exists()


def test_public_install_rejects_agents_symlink_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "external-agents"
    target.mkdir()
    protected = target / "user-owned.txt"
    protected.write_bytes(b"do not follow this link\n")
    (workspace / ".agents").symlink_to(target, target_is_directory=True)
    before = tree_snapshot(target)

    result = _run_installer("install", workspace, tmp_path / "home")

    assert result.returncode != 0
    assert tree_snapshot(target) == before
    assert (workspace / ".agents").is_symlink()
    assert os.readlink(workspace / ".agents") == str(target)
    assert not (workspace / "AGENTS.md").exists()


def test_public_update_rejects_manifest_symlink_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    _assert_succeeded(_run_installer("install", workspace, home))

    manifest = workspace / MANIFEST_REL
    external_manifest = tmp_path / "external-manifest.json"
    manifest.replace(external_manifest)
    manifest.symlink_to(external_manifest)
    before_workspace = tree_snapshot(workspace)
    before_target = external_manifest.read_bytes()

    result = _run_installer("update", workspace, home)

    assert result.returncode != 0
    assert tree_snapshot(workspace) == before_workspace
    assert external_manifest.read_bytes() == before_target
    assert manifest.is_symlink()
    assert os.readlink(manifest) == str(external_manifest)


def test_public_update_fails_closed_on_managed_drift(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    _assert_succeeded(_run_installer("install", workspace, home))

    managed = workspace / ".agents" / "lib" / "research" / "updater.py"
    managed.write_bytes(managed.read_bytes() + b"\n# user drift\n")
    user_file = workspace / ".agents" / "user-owned.txt"
    user_file.write_bytes(b"preserve me\n")
    before = tree_snapshot(workspace)

    result = _run_installer("update", workspace, home)

    assert result.returncode != 0
    assert tree_snapshot(workspace) == before
    assert managed.read_bytes().endswith(b"# user drift\n")
    assert user_file.read_bytes() == b"preserve me\n"


def test_manifest_commit_failure_rolls_back_complete_install(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents = workspace / ".agents"
    agents.mkdir()
    (workspace / "AGENTS.md").write_bytes(b"# Existing user rules\n")
    (workspace / "research-notes.md").write_bytes(b"user content\n")
    (agents / "user-owned.txt").write_bytes(b"user config\n")
    before = tree_snapshot(workspace)

    sync = load_ws_sync()
    original_replace = sync.os.replace
    manifest = workspace / MANIFEST_REL
    injected = False

    def fail_manifest_commit(source, destination, *args, **kwargs):
        nonlocal injected
        if not injected and not kwargs and Path(destination) == manifest:
            injected = True
            raise OSError("injected manifest commit failure")
        return original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(sync.os, "replace", fail_manifest_commit)

    with pytest.raises(OSError, match="injected manifest commit failure"):
        sync.main(_sync_args("install", workspace))

    assert injected
    assert tree_snapshot(workspace) == before
    assert sorted(path.name for path in agents.iterdir()) == ["user-owned.txt"]
    assert not list(workspace.glob(".workspace-oss-stage-*"))


def test_updater_apply_invokes_ws_sync_update_and_restores_version(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _assert_succeeded(_run_installer("install", workspace, tmp_path / "home"))

    source = tmp_path / "source"
    shutil.copytree(
        REPO_ROOT,
        source,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "*.pyc"),
    )
    subprocess.run(
        ["git", "init", "-b", "test-source", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Release Test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "add", "--", "skills", "runtime", "LICENSE", "install-lib"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
        text=True,
    )
    source_commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_version = (source / "runtime" / "VERSION").read_text(encoding="utf-8").strip()
    assert source_version != "0.0.0"
    installed_version = workspace / ".agents" / "VERSION"
    downgraded = b"0.0.0\n"
    installed_version.write_bytes(downgraded)

    sync = load_ws_sync()
    manifest_path = workspace / MANIFEST_REL
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][".agents/VERSION"] = hashlib.sha256(downgraded).hexdigest()
    manifest["tree_checksum"] = sync.tree_checksum(manifest["files"])
    manifest["source_origin"] = "local"
    manifest["source_checkout"] = str(source)
    manifest["source_branch"] = "test-source"
    manifest["source_strategy"] = "local-checkout"
    manifest["source_commit"] = source_commit
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    updater = load_runtime_module("updater")
    original_run_process = updater._run_process
    calls: list[tuple[str, ...]] = []

    def record_run_process(argv, *, capture_output=True):
        calls.append(tuple(str(value) for value in argv))
        return original_run_process(argv, capture_output=capture_output)

    monkeypatch.setattr(updater, "_run_process", record_run_process)

    result = updater.apply(workspace, tmp_path / "update-cache")

    assert result["status"] == "updated"
    assert result["before"] == "0.0.0"
    assert result["after"] == source_version
    assert installed_version.read_text(encoding="utf-8").strip() == source_version
    ws_sync_calls = [
        call
        for call in calls
        if len(call) > 2
        and Path(call[1]).resolve() == (source / "install-lib" / "ws_sync.py").resolve()
        and call[2] == "update"
    ]
    assert len(ws_sync_calls) == 1
    assert "--force" not in ws_sync_calls[0]


def test_smoke_entrypoints_match_shipping_scripts_and_include_review() -> None:
    smoke = load_module("v2_test_release_smoke", REPO_ROOT / "install-lib" / "smoke.py")
    skill_root = REPO_ROOT / "skills"
    actual = {
        script.relative_to(skill_root).as_posix()
        for skill in smoke.SHIPPING_SKILLS
        for script in (skill_root / skill / "scripts").glob("*.py")
    }

    assert set(smoke.ENTRYPOINTS) == actual
    assert "research-review/scripts/review.py" in smoke.ENTRYPOINTS

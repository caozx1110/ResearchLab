from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


BEGIN_MARKER = "# >>> workspace-oss managed >>>"
END_MARKER = "# <<< workspace-oss managed <<<"
PUBLIC_PRESERVATION_WARNING = "检测到用户修改并按安全策略保留，请让 Agent 检查。"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _installer_env() -> dict[str, str]:
    env = {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }
    env.pop("_RESEARCH_RUNTIME_READY", None)
    return env


def test_installer_subprocess_env_never_inherits_bootstrap_ready_sentinel(monkeypatch) -> None:
    monkeypatch.setenv("_RESEARCH_RUNTIME_READY", "1")

    assert "_RESEARCH_RUNTIME_READY" not in _installer_env()


def _run_installer(workspace: Path, action: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_project_root() / "install.sh"), action, "--project", str(workspace), "--yes", *extra],
        cwd=_project_root(),
        env=_installer_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_public_preservation_warning(result: subprocess.CompletedProcess[str]) -> None:
    assert PUBLIC_PRESERVATION_WARNING in result.stderr
    assert result.stderr.count(PUBLIC_PRESERVATION_WARNING) == 1
    for token in ("preserving ", "reason=", "warn:", ".agents/", "expected=", "actual="):
        assert token not in result.stdout + result.stderr


def _load_ws_sync() -> ModuleType:
    path = _project_root() / "install-lib" / "ws_sync.py"
    spec = importlib.util.spec_from_file_location("bundle_lifecycle_ws_sync", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_install_ships_only_runtime_allowlist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = _run_installer(workspace, "install", "--codex")

    assert result.returncode == 0, result.stdout + result.stderr
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    installed = set(manifest["files"])
    assert (workspace / ".agents" / "VERSION").is_file()
    assert (workspace / ".agents" / "LICENSE").is_file()
    assert (workspace / ".agents" / "skills" / "kb-cli" / "SKILL.md").is_file()
    assert (workspace / ".agents" / "skills" / "research-monitor" / "SKILL.md").is_file()
    assert (workspace / ".agents" / "lib" / "research" / "common.py").is_file()
    assert not (workspace / ".agents" / "lib" / "research" / "tests").exists()
    assert not (workspace / ".agents" / "skills" / "skill-evolution-advisor" / "scripts" / "eval_research_value.py").exists()
    assert not any("/tests/" in rel for rel in installed)
    assert not any("eval_research_value.py" in rel for rel in installed)
    assert not any(Path(rel).is_absolute() for rel in installed)
    assert manifest["source_strategy"] == "local-checkout"
    assert manifest["source_checkout"] == str(_project_root())

    duplicate = _run_installer(workspace, "install", "--codex")
    assert duplicate.returncode == 1
    assert "更新”或“重装" in duplicate.stderr


def test_fresh_install_rejects_unverified_existing_managed_block(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-unverified-block"
    workspace.mkdir()
    agents = workspace / "AGENTS.md"
    original = (
        "# User rules\n\n"
        f"{BEGIN_MARKER}\n"
        "unverified prior bundle content\n"
        f"{END_MARKER}\n"
    )
    agents.write_text(original, encoding="utf-8")

    for extra in (("--codex", "--agent-plan"), ("--codex",)):
        result = _run_installer(workspace, "install", *extra)
        assert result.returncode == 1
        assert agents.read_text(encoding="utf-8") == original
        assert not (workspace / ".agents/.install-manifest.json").exists()


def test_reinstall_rejects_managed_block_drift_unless_forced(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-reinstall-drift"
    workspace.mkdir()
    agents = workspace / "AGENTS.md"
    agents.write_text("# User rules\n\nKeep this prose.\n", encoding="utf-8")
    installed = _run_installer(workspace, "install", "--codex")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    drifted = agents.read_text(encoding="utf-8").replace(
        "<!-- Managed by workspace-oss. Content outside this block is user-owned. -->",
        "<!-- Locally edited managed block. -->",
        1,
    )
    agents.write_text(drifted, encoding="utf-8")

    for extra in (("--agent-plan",), ()):
        rejected = _run_installer(workspace, "reinstall", *extra)
        assert rejected.returncode == 3
        assert agents.read_text(encoding="utf-8") == drifted

    forced = _run_installer(workspace, "reinstall", "--force")
    assert forced.returncode == 0, forced.stdout + forced.stderr
    repaired = agents.read_text(encoding="utf-8")
    assert "Keep this prose." in repaired
    assert "Locally edited managed block" not in repaired


def test_merge_update_reinstall_uninstall_preserve_user_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_skill = workspace / ".agents" / "skills" / "user-owned" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("# User skill\n", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("# User rules\n\nKeep this prose.\n", encoding="utf-8")
    (workspace / "kb").mkdir()
    (workspace / "kb" / "notes.md").write_text("research data\n", encoding="utf-8")
    (workspace / ".venv").mkdir()
    (workspace / ".venv" / "sentinel").write_text("runtime\n", encoding="utf-8")

    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr
    merged = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Keep this prose." in merged
    assert merged.count(BEGIN_MARKER) == 1
    assert merged.count(END_MARKER) == 1
    assert user_skill.read_text(encoding="utf-8") == "# User skill\n"

    update = _run_installer(workspace, "update")
    assert update.returncode == 0, update.stdout + update.stderr
    assert "Keep this prose." in (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert user_skill.is_file()

    managed_file = workspace / ".agents" / "VERSION"
    managed_file.write_text("locally damaged\n", encoding="utf-8")
    reinstall = _run_installer(workspace, "reinstall")
    assert reinstall.returncode == 0, reinstall.stdout + reinstall.stderr
    assert managed_file.read_text(encoding="utf-8") != "locally damaged\n"
    assert "Keep this prose." in (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert user_skill.is_file()
    assert (workspace / "kb" / "notes.md").is_file()
    assert (workspace / ".venv" / "sentinel").is_file()

    uninstall = _run_installer(workspace, "uninstall")
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert not (workspace / ".agents" / "VERSION").exists()
    assert user_skill.read_text(encoding="utf-8") == "# User skill\n"
    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Keep this prose." in agents_text
    assert BEGIN_MARKER not in agents_text
    assert END_MARKER not in agents_text
    assert (workspace / "kb" / "notes.md").read_text(encoding="utf-8") == "research data\n"
    assert (workspace / ".venv" / "sentinel").read_text(encoding="utf-8") == "runtime\n"


def test_clean_uninstall_removes_all_managed_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
    cache_dir = workspace / ".agents" / "lib" / "research" / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    core_cache = cache_dir / Path(importlib.util.cache_from_source(str(core_source))).name
    core_cache.write_bytes(b"generated bytecode\n")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert all(not (workspace / rel).exists() for rel in manifest["files"] if rel != "AGENTS.md")
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert not (workspace / ".agents").exists()
    assert not (workspace / "AGENTS.md").exists()


def test_uninstall_preserves_drifted_and_retyped_managed_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    drifted = workspace / ".agents" / "VERSION"
    drifted.write_text("user-owned after local edit\n", encoding="utf-8")

    retyped = workspace / ".agents" / "LICENSE"
    retyped.unlink()
    retyped.mkdir()
    (retyped / "nested-empty-directory").mkdir()

    external = tmp_path / "external-agents.md"
    external.write_text("external target\n", encoding="utf-8")
    linked = workspace / ".agents" / "AGENTS.md"
    linked.unlink()
    linked.symlink_to(external)

    cache_dir = workspace / ".agents" / "lib" / "research" / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    managed_cache = cache_dir / Path(importlib.util.cache_from_source(str(core_source))).name
    managed_cache.write_bytes(b"generated bytecode\n")
    user_cache = cache_dir / "user_extension.cpython-test.pyc"
    user_cache.write_bytes(b"user-owned cache\n")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert drifted.read_text(encoding="utf-8") == "user-owned after local edit\n"
    assert retyped.is_dir()
    assert (retyped / "nested-empty-directory").is_dir()
    assert linked.is_symlink()
    assert linked.readlink() == external
    assert external.read_text(encoding="utf-8") == "external target\n"
    assert not managed_cache.exists()
    assert user_cache.read_bytes() == b"user-owned cache\n"
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert not (workspace / ".agents" / "skills" / "kb-cli" / "SKILL.md").exists()
    _assert_public_preservation_warning(uninstall)


def test_direct_uninstall_rejects_linked_agents_root_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    external_agents = tmp_path / "external-agents"
    shutil.move(str(workspace / ".agents"), external_agents)
    (workspace / ".agents").symlink_to(external_agents, target_is_directory=True)
    external_manifest = external_agents / ".install-manifest.json"
    external_version = external_agents / "VERSION"
    manifest_before = external_manifest.read_bytes()
    version_before = external_version.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "uninstall",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
        ],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "managed .agents root is not a real directory" in result.stderr
    assert (workspace / ".agents").is_symlink()
    assert external_manifest.read_bytes() == manifest_before
    assert external_version.read_bytes() == version_before


def test_direct_uninstall_rejects_linked_manifest_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    manifest = workspace / ".agents" / ".install-manifest.json"
    external_manifest = tmp_path / "external-manifest.json"
    shutil.move(str(manifest), external_manifest)
    manifest.symlink_to(external_manifest)
    manifest_before = external_manifest.read_bytes()
    version = workspace / ".agents" / "VERSION"
    version_before = version.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "uninstall",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
        ],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "manifest is not a regular file" in result.stderr
    assert manifest.is_symlink()
    assert external_manifest.read_bytes() == manifest_before
    assert version.read_bytes() == version_before


def test_uninstall_preserves_nonstandard_same_prefix_bytecode_name(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    cache_dir = core_source.parent / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    standard_cache = cache_dir / Path(importlib.util.cache_from_source(str(core_source))).name
    standard_cache.write_bytes(b"generated bytecode\n")
    user_cache = standard_cache.parent / "core.user-owned.pyc"
    user_cache.write_bytes(b"user-owned cache-shaped file\n")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not standard_cache.exists()
    assert user_cache.read_bytes() == b"user-owned cache-shaped file\n"
    assert not (workspace / ".agents" / ".install-manifest.json").exists()


def test_uninstall_removes_cross_abi_cpython_caches_but_preserves_changed_types(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    cache_dir = core_source.parent / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    other_abi = cache_dir / "core.cpython-999.pyc"
    other_abi.write_bytes(b"other abi\n")
    other_abi_optimized = cache_dir / "core.cpython-999.opt-1.pyc"
    other_abi_optimized.write_bytes(b"other abi optimized\n")
    user_cache = cache_dir / "core.user-owned.pyc"
    user_cache.write_bytes(b"user cache\n")
    external = tmp_path / "external-cache"
    external.write_bytes(b"external\n")
    linked_cache = cache_dir / "core.cpython-998.pyc"
    linked_cache.symlink_to(external)
    retyped_cache = cache_dir / "core.cpython-997.opt-2.pyc"
    retyped_cache.mkdir()

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not other_abi.exists()
    assert not other_abi_optimized.exists()
    assert user_cache.read_bytes() == b"user cache\n"
    assert linked_cache.is_symlink()
    assert linked_cache.readlink() == external
    assert external.read_bytes() == b"external\n"
    assert retyped_cache.is_dir()
    _assert_public_preservation_warning(uninstall)


def test_uninstall_preserves_whole_agents_file_when_managed_block_drifts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    agents_path.write_text("# User rules\n\nKeep this prose.\n", encoding="utf-8")
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))

    installed = agents_path.read_text(encoding="utf-8")
    drifted = installed.replace(
        "<!-- Managed by workspace-oss. Content outside this block is user-owned. -->",
        "<!-- Locally edited managed block. -->",
        1,
    )
    assert drifted != installed
    agents_path.write_text(drifted, encoding="utf-8")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert agents_path.read_text(encoding="utf-8") == drifted
    assert BEGIN_MARKER in drifted
    assert END_MARKER in drifted
    _assert_public_preservation_warning(uninstall)
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert all(not (workspace / rel).exists() for rel in manifest["files"] if rel != "AGENTS.md")


def test_uninstall_preserves_whole_agents_file_when_managed_marker_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    agents_path.write_text("# User rules\n", encoding="utf-8")
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    installed = agents_path.read_text(encoding="utf-8")
    drifted = installed.replace(END_MARKER, "# <<< locally edited marker <<<", 1)
    assert drifted != installed
    agents_path.write_text(drifted, encoding="utf-8")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert agents_path.read_text(encoding="utf-8") == drifted
    _assert_public_preservation_warning(uninstall)
    assert not (workspace / ".agents" / ".install-manifest.json").exists()


def test_uninstall_preserves_whole_agents_file_when_it_is_not_utf8(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    installed = agents_path.read_bytes()
    drifted = installed.replace(BEGIN_MARKER.encode(), BEGIN_MARKER.encode() + b"\xff", 1)
    assert drifted != installed
    agents_path.write_bytes(drifted)

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert agents_path.read_bytes() == drifted
    _assert_public_preservation_warning(uninstall)
    assert not (workspace / ".agents" / ".install-manifest.json").exists()


def test_ambiguous_cwd_refuses_without_writing(tmp_path: Path) -> None:
    repo_manifest = _project_root() / ".agents" / ".install-manifest.json"
    assert not repo_manifest.exists()

    result = subprocess.run(
        ["bash", str(_project_root() / "install.sh"), "update", "--yes"],
        cwd=tmp_path,
        env=_installer_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "当前目录不是可识别的已安装工作区" in result.stderr
    assert not any(tmp_path.iterdir())
    assert not repo_manifest.exists()


def test_fresh_transaction_rolls_back_all_managed_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ws_sync = _load_ws_sync()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writes = {
        ".agents/first.txt": (b"first\n", 0o644),
        ".agents/second.txt": (b"second\n", 0o644),
        "AGENTS.md": (b"managed\n", 0o644),
    }
    manifest = {
        "schema": 1,
        "install_name": "workspace-oss",
        "install_mode": "copy-project",
        "files": {rel: "0" * 64 for rel in writes},
    }
    real_replace = ws_sync.os.replace

    def fail_mid_commit(source: Path, destination: Path) -> None:
        if Path(destination).name == "second.txt":
            raise OSError("injected commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(ws_sync.os, "replace", fail_mid_commit)
    with pytest.raises(OSError, match="injected commit failure"):
        ws_sync.transactional_apply(workspace, writes, [], manifest, dry_run=False)

    assert not (workspace / ".agents").exists()
    assert not (workspace / "AGENTS.md").exists()

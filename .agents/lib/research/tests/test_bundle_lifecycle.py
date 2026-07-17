from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


BEGIN_MARKER = "# >>> workspace-oss managed >>>"
END_MARKER = "# <<< workspace-oss managed <<<"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _installer_env() -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }


def _run_installer(workspace: Path, action: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_project_root() / "install.sh"), action, "--project", str(workspace), "--yes", *extra],
        cwd=_project_root(),
        env=_installer_env(),
        text=True,
        capture_output=True,
        check=False,
    )


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
    assert (workspace / ".agents" / "lib" / "research" / "common.py").is_file()
    assert not (workspace / ".agents" / "lib" / "research" / "tests").exists()
    assert not (workspace / ".agents" / "skills" / "skill-evolution-advisor" / "scripts" / "eval_research_value.py").exists()
    assert not any("/tests/" in rel for rel in installed)
    assert not any("eval_research_value.py" in rel for rel in installed)
    assert not any(Path(rel).is_absolute() for rel in installed)
    assert str(_project_root()) not in manifest_path.read_text(encoding="utf-8")

    duplicate = _run_installer(workspace, "install", "--codex")
    assert duplicate.returncode == 1
    assert "更新”或“重装" in duplicate.stderr


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

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _run_dry_install(tmp_path: Path, *, no_managed_venv: bool = False) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {**os.environ, "RESEARCH_PYTHON": "/bin/false", "NO_COLOR": "1"}
    if no_managed_venv:
        env["RESEARCH_NO_MANAGED_VENV"] = "1"
    return subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--dry-run",
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_missing_system_yaml_continues_to_managed_runtime_fallback(tmp_path: Path) -> None:
    result = _run_dry_install(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "managed runtime will install PyYAML and the PDF backend" in result.stderr


def test_missing_system_yaml_remains_fatal_when_managed_venv_disabled(tmp_path: Path) -> None:
    result = _run_dry_install(tmp_path, no_managed_venv=True)

    assert result.returncode == 1
    assert "RESEARCH_NO_MANAGED_VENV=1 requires" in result.stderr

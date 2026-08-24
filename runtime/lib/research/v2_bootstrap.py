"""Minimal managed-Python bootstrap for the Research Vault v2 entrypoints.

The v2 shipping scripts require only PyYAML beyond the Python standard library.
Source conversion remains an optional adapter concern and is never provisioned
by this bootstrap.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


READY_FLAG = "_RESEARCH_V2_RUNTIME_READY"
CORE_RUNTIME_MODULES = ("yaml",)
CORE_RUNTIME_PACKAGES = ("PyYAML==6.0.3",)


def _absolute_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and candidate.parent == Path("."):
        located = shutil.which(str(path))
        if located:
            candidate = Path(located)
    return candidate.resolve(strict=False)


def _has_core_runtime() -> bool:
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(name) is not None for name in CORE_RUNTIME_MODULES)


def _python_has_core_runtime(python: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(python), "-I", "-c", "import yaml"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _managed_python(workspace: Path) -> Path:
    configured = os.environ.get("RESEARCH_VENV", "").strip()
    venv = _absolute_path(configured) if configured else (workspace / ".venv").resolve()
    try:
        relative = venv.relative_to(workspace.resolve())
    except ValueError as exc:
        raise SystemExit("managed runtime must stay inside the workspace") from exc
    if not relative.parts:
        raise SystemExit("managed runtime cannot replace the workspace root")
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _reexec(python: Path) -> None:
    os.execve(
        str(python),
        [str(python), *sys.argv],
        {**os.environ, READY_FLAG: "1"},
    )


def _prepare_managed_runtime(python: Path) -> None:
    venv = python.parent.parent
    if not python.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=120,
        )
    if not _python_has_core_runtime(python):
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *CORE_RUNTIME_PACKAGES,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=180,
        )
    if not _python_has_core_runtime(python):
        raise RuntimeError("managed runtime is missing PyYAML")


def ensure_managed_runtime(
    workspace: Path,
    *,
    allow_provision: bool = True,
) -> None:
    """Use a PyYAML-ready interpreter or prepare one workspace-local venv."""

    if os.environ.get(READY_FLAG) == "1" or _has_core_runtime():
        os.environ[READY_FLAG] = "1"
        return

    configured = os.environ.get("RESEARCH_PYTHON", "").strip()
    if configured:
        selected = _absolute_path(configured)
        if _python_has_core_runtime(selected):
            _reexec(selected)
        raise SystemExit("核心运行环境尚未就绪；所选 Python 缺少 PyYAML。")

    managed = _managed_python(workspace.resolve())
    if _python_has_core_runtime(managed):
        _reexec(managed)

    if os.environ.get("RESEARCH_NO_MANAGED_VENV") == "1" or not allow_provision:
        raise SystemExit("核心运行环境尚未就绪；请让 Agent 按安装说明准备 PyYAML。")

    try:
        _prepare_managed_runtime(managed)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise SystemExit("无法准备运行所需的环境；请使用可信 mirror 或 wheelhouse 安装 PyYAML。") from exc
    _reexec(managed)


__all__ = ["CORE_RUNTIME_MODULES", "CORE_RUNTIME_PACKAGES", "ensure_managed_runtime"]

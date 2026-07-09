"""Managed runtime bootstrap for research skill entrypoints."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

READY_FLAG = "_RESEARCH_RUNTIME_READY"

# Lightweight default PDF backend (SSOT 3.1 decision A): pure PyMuPDF, no torch,
# always installed into the managed venv so a fresh user never silently degrades
# to an empty PDF parse. Heavy backends (MinerU/Docling) stay opt-in.
PDF_BACKEND_PACKAGE = "pymupdf4llm"
PDF_BACKEND_IMPORT = "pymupdf4llm"
# Opt out of auto-installing the PDF backend (yaml install is unaffected).
NO_PDF_BACKEND_ENV = "RESEARCH_NO_PDF_BACKEND"


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def _resolve_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return path.expanduser().absolute()


def _python_path(value: str | Path) -> Path:
    text = str(value).strip()
    path = Path(text).expanduser()
    if not path.is_absolute() and path.parent == Path("."):
        found = shutil.which(text)
        if found:
            path = Path(found)
    return _absolute_path(path)


def managed_venv_dir(home: Path | None = None) -> Path:
    configured = str(os.environ.get("RESEARCH_VENV") or "").strip()
    if configured:
        return _resolve_path(Path(configured))
    return _resolve_path((home or Path.cwd()) / ".venv")


def managed_venv_python(home: Path | None = None) -> Path:
    venv_dir = managed_venv_dir(home)
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def is_current_python(python_exe: str | Path) -> bool:
    return _python_path(sys.executable) == _python_path(python_exe)


def _mark_ready() -> None:
    os.environ[READY_FLAG] = "1"


def _current_has_yaml() -> bool:
    importlib.invalidate_caches()
    return importlib.util.find_spec("yaml") is not None


def _python_can_import_yaml(python_exe: str | Path) -> bool:
    if is_current_python(python_exe):
        return _current_has_yaml()
    try:
        completed = subprocess.run(
            [str(_python_path(python_exe)), "-c", "import yaml"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _python_can_import(python_exe: str | Path, module: str) -> bool:
    try:
        completed = subprocess.run(
            [str(_python_path(python_exe)), "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _ensure_venv_has_pdf_backend(venv_py: Path) -> None:
    """Best-effort install of the lightweight PDF backend into the managed venv.

    Unlike PyYAML (a hard requirement that gates readiness), a missing PDF backend
    only degrades PDF parsing, so a failed/opted-out install warns to stderr and is
    non-fatal. This closes the cold-start gap where a fresh managed venv had no PDF
    backend and silently produced empty parses."""
    if os.environ.get(NO_PDF_BACKEND_ENV) == "1":
        return
    if _python_can_import(venv_py, PDF_BACKEND_IMPORT):
        return
    try:
        _run_checked(
            [str(venv_py), "-m", "pip", "install", "--disable-pip-version-check", PDF_BACKEND_PACKAGE],
            context=f"{PDF_BACKEND_PACKAGE} installation",
        )
    except RuntimeError as exc:
        print(
            f"[research] warning: could not install lightweight PDF backend "
            f"({PDF_BACKEND_PACKAGE}); PDF parsing will be unavailable until installed. Reason: {exc}",
            file=sys.stderr,
            flush=True,
        )


def _reexec(python_exe: Path, message: str) -> None:
    resolved = _python_path(python_exe)
    print(message, file=sys.stderr, flush=True)
    os.execve(str(resolved), [str(resolved), *sys.argv], {**os.environ, READY_FLAG: "1"})


def _run_checked(argv: list[str], *, context: str) -> None:
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(f"{context} failed{suffix}") from exc
    except OSError as exc:
        raise RuntimeError(f"{context} failed: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"{context} failed")


def _pyvenv_home() -> Path | None:
    cfg_path = Path(sys.prefix) / "pyvenv.cfg"
    try:
        lines = cfg_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key.strip().lower() == "home":
            home = value.strip()
            return Path(home).expanduser() if home else None
    return None


def _venv_builder_python() -> str:
    candidates: list[str | Path] = []
    home = _pyvenv_home()
    if home is not None:
        major = sys.version_info.major
        minor = sys.version_info.minor
        candidates.extend(
            [
                home / f"python{major}.{minor}",
                home / f"python{major}",
                home / "python",
            ]
        )
    base_executable = str(getattr(sys, "_base_executable", "") or "").strip()
    if base_executable and _python_path(base_executable) != _python_path(sys.executable):
        candidates.append(base_executable)
    candidates.extend([sys.executable, shutil.which("python3") or "python3"])
    for candidate in candidates:
        if not candidate:
            continue
        path = _python_path(candidate)
        if path.exists():
            return str(path)
    return "python3"


def _ensure_venv_has_yaml(venv_dir: Path, venv_py: Path) -> None:
    if not venv_py.exists():
        _run_checked([_venv_builder_python(), "-m", "venv", str(venv_dir)], context="venv creation")
    if not _python_can_import_yaml(venv_py):
        _run_checked(
            [
                str(venv_py),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "pyyaml>=6",
            ],
            context="PyYAML installation",
        )
    if not _python_can_import_yaml(venv_py):
        raise RuntimeError("managed venv still cannot import yaml after installation")
    # PyYAML is the hard gate above; the lightweight PDF backend is best-effort.
    _ensure_venv_has_pdf_backend(venv_py)


def _failure_message(venv_dir: Path, error: Exception) -> str:
    return "\n".join(
        [
            f"[research] could not bootstrap managed runtime at {venv_dir}.",
            f"Reason: {error}",
            "Install PyYAML manually with `python -m pip install pyyaml`, or set RESEARCH_PYTHON to a Python that has PyYAML.",
            "You can also set RESEARCH_VENV to another venv path, or unset RESEARCH_NO_MANAGED_VENV to allow automatic management.",
        ]
    )


def ensure_managed_runtime(home: Path | None = None) -> None:
    """Ensure the current skill entrypoint can import PyYAML.

    This function is intentionally side-effectful and must only be called from
    script entrypoint paths, never during shared-library import.
    """

    if os.environ.get(READY_FLAG) == "1":
        return

    configured_python = str(os.environ.get("RESEARCH_PYTHON") or "").strip()
    if configured_python:
        configured_path = _python_path(configured_python)
        if _python_can_import_yaml(configured_path):
            if is_current_python(configured_path):
                _mark_ready()
                return
            _reexec(configured_path, f"[research] using RESEARCH_PYTHON runtime at {configured_path} ...")
            return

    if os.environ.get("RESEARCH_NO_MANAGED_VENV") == "1":
        if _current_has_yaml():
            _mark_ready()
            return
        raise SystemExit(
            "[research] RESEARCH_NO_MANAGED_VENV=1 is set, but the current Python cannot import PyYAML. "
            "Install PyYAML with `python -m pip install pyyaml`, unset RESEARCH_NO_MANAGED_VENV, "
            "or set RESEARCH_PYTHON to a Python that has PyYAML."
        )

    if _current_has_yaml():
        _mark_ready()
        return

    venv_dir = managed_venv_dir(home)
    venv_py = managed_venv_python(home)
    try:
        print(f"[research] bootstrapping managed runtime at {venv_dir} ...", file=sys.stderr, flush=True)
        _ensure_venv_has_yaml(venv_dir, venv_py)
    except Exception as exc:  # noqa: BLE001
        if _current_has_yaml():
            _mark_ready()
            return
        raise SystemExit(_failure_message(venv_dir, exc)) from exc

    if is_current_python(venv_py):
        _mark_ready()
        return
    _reexec(venv_py, f"[research] using managed runtime at {venv_dir} ...")

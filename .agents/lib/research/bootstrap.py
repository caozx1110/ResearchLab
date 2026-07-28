"""Managed runtime bootstrap for research skill entrypoints."""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

READY_FLAG = "_RESEARCH_RUNTIME_READY"
BOOTSTRAP_PROVISION_ENV = "_RESEARCH_BOOTSTRAP_ALLOW_PROVISION"
CORE_RUNTIME_MODULES = ("yaml", "markdownify", "bs4")
CORE_RUNTIME_PACKAGES = (
    "pyyaml==6.0.3",
    "markdownify==1.2.3",
    "beautifulsoup4==4.15.0",
    "soupsieve==2.8.4",
    "six==1.17.0",
    "typing_extensions==4.16.0",
)

# Lightweight default PDF backend (SSOT 3.1 decision A): pure PyMuPDF, no torch,
# always installed into the managed venv so a fresh user never silently degrades
# to an empty PDF parse. Heavy backends (MinerU/Docling) stay opt-in.
PDF_BACKEND_PACKAGE = "pymupdf4llm"
PDF_BACKEND_IMPORT = "pymupdf4llm"
# The deep-read pipeline needs both the converter and its PyMuPDF (fitz) engine;
# probing both keeps this gate aligned with sources._pymupdf4llm_available().
PDF_BACKEND_PROBE_MODULES = ("pymupdf4llm", "fitz")
# Opt out of auto-installing the PDF backend (the hard core runtime is unaffected).
NO_PDF_BACKEND_ENV = "RESEARCH_NO_PDF_BACKEND"
PDF_BACKEND_RETRY_SECONDS = 3600.0
PDF_BACKEND_RETRY_MARKER = ".pdf-backend-prep-last-attempt"


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
    """Compatibility name: gate every hard source-material runtime import."""
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(module) is not None for module in CORE_RUNTIME_MODULES)


def _current_has_pdf_backend() -> bool:
    """Probe the always-installed paper deep-read backend in this interpreter."""
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(module) is not None for module in PDF_BACKEND_PROBE_MODULES)


def _pdf_backend_opted_out() -> bool:
    return os.environ.get(NO_PDF_BACKEND_ENV) == "1"


def _python_can_import_yaml(python_exe: str | Path) -> bool:
    """Compatibility name: probe the complete hard runtime, not only PyYAML."""
    # A wrapper may have launched this same executable with flags such as
    # ``-S`` that hide site packages.  Accept the live process when it is
    # already capable, otherwise probe a clean invocation of the bound binary
    # before deciding that the runtime itself is deficient.
    if is_current_python(python_exe) and _current_has_yaml():
        return True
    try:
        completed = subprocess.run(
            [str(_python_path(python_exe)), "-c", "import yaml, markdownify, bs4"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _path_runtime_python(home: Path | None = None) -> Path | None:
    """Return a stable, core-ready Python from a later absolute PATH entry."""
    workspace = _resolve_path(home) if home is not None else None
    seen: set[Path] = set()
    for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_directory:
            continue
        directory = Path(raw_directory).expanduser()
        if not directory.is_absolute():
            continue
        for name in ("python3", "python"):
            candidate = directory / name
            try:
                resolved = candidate.resolve(strict=True)
                metadata = resolved.stat()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o111 == 0:
                continue
            if workspace is not None:
                try:
                    resolved.relative_to(workspace)
                except ValueError:
                    pass
                else:
                    continue
            if is_current_python(resolved) and _current_has_yaml():
                continue
            identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_uid,
                metadata.st_gid,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            if not _python_can_import_yaml(resolved):
                continue
            try:
                current = resolved.stat()
            except OSError:
                continue
            if identity != (
                current.st_dev,
                current.st_ino,
                current.st_mode,
                current.st_uid,
                current.st_gid,
                current.st_size,
                current.st_mtime_ns,
                current.st_ctime_ns,
            ):
                continue
            return resolved
    return None


def _use_path_runtime_if_available(home: Path | None = None) -> bool:
    candidate = _path_runtime_python(home)
    if candidate is None:
        return False
    _reexec(candidate)
    return True


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


def _ensure_python_has_pdf_backend(python_exe: str | Path) -> bool:
    """Best-effort install of the lightweight PDF backend into a Python runtime.

    Unlike the core YAML/Markdown runtime (which gates readiness), a missing PDF backend
    only degrades PDF parsing, so a failed/opted-out install warns to stderr and is
    non-fatal."""
    if _pdf_backend_opted_out():
        return True
    python_path = _python_path(python_exe)
    if all(_python_can_import(python_path, module) for module in PDF_BACKEND_PROBE_MODULES):
        return True
    try:
        _run_checked(
            [str(python_path), "-m", "pip", "install", "--disable-pip-version-check", PDF_BACKEND_PACKAGE],
            context=f"{PDF_BACKEND_PACKAGE} installation",
        )
    except RuntimeError:
        print(
            "论文 PDF 深读能力尚未就绪，下次使用时会自动重试；可让 Agent 运行 kb doctor 查看状态。",
            file=sys.stderr,
            flush=True,
        )
        return False
    if all(_python_can_import(python_path, module) for module in PDF_BACKEND_PROBE_MODULES):
        return True
    print(
        "论文 PDF 深读能力尚未就绪，下次使用时会自动重试；可让 Agent 运行 kb doctor 查看状态。",
        file=sys.stderr,
        flush=True,
    )
    return False


def _pdf_backend_retry_marker(venv_dir: Path) -> Path:
    return venv_dir / PDF_BACKEND_RETRY_MARKER


def _pdf_backend_retry_is_throttled(venv_dir: Path) -> bool:
    try:
        last_attempt = _pdf_backend_retry_marker(venv_dir).stat().st_mtime
    except OSError:
        return False
    return time.time() - last_attempt < PDF_BACKEND_RETRY_SECONDS


def _record_pdf_backend_failure(venv_dir: Path) -> None:
    marker = _pdf_backend_retry_marker(venv_dir)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _prepare_managed_pdf_backend(venv_dir: Path, venv_py: Path) -> bool:
    if _pdf_backend_opted_out():
        return True
    if all(_python_can_import(venv_py, module) for module in PDF_BACKEND_PROBE_MODULES):
        return True
    if _pdf_backend_retry_is_throttled(venv_dir):
        return False
    ready = _ensure_python_has_pdf_backend(venv_py)
    if not ready:
        _record_pdf_backend_failure(venv_dir)
    return ready


def _reexec(python_exe: Path) -> None:
    resolved = _python_path(python_exe)
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


def _ensure_venv_has_yaml(venv_dir: Path, venv_py: Path) -> bool:
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
                *CORE_RUNTIME_PACKAGES,
            ],
            context="core research runtime installation",
        )
    if not _python_can_import_yaml(venv_py):
        raise RuntimeError("managed venv still cannot import the core runtime after installation")
    # YAML + HTML-to-Markdown are the hard gate above; PDF remains best-effort.
    return _prepare_managed_pdf_backend(venv_dir, venv_py)


def _failure_message(venv_dir: Path, error: Exception) -> str:
    del venv_dir, error
    return "\n".join(
        [
            "无法准备运行所需的环境。",
            "请让 Agent 按安装说明中的离线恢复步骤准备运行环境，完成后再使用 kb doctor 复查。",
        ]
    )


def entrypoint_public_verb(argv: Sequence[str]) -> str:
    """Read the public verb without importing the full argparse-based CLI."""
    index = 0
    values = list(argv)
    while index < len(values):
        token = str(values[index])
        if token in {"--root", "--agent-protocol"}:
            index += 2
            continue
        if token.startswith(("--root=", "--agent-protocol=")):
            index += 1
            continue
        if token.startswith("-"):
            return ""
        return token
    return ""


def _public_package_version(home: Path) -> str:
    try:
        version = (home / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "未知"
    return version if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}", version) else "未知"


def render_runtime_unavailable_command(home: Path, verb: str) -> bool:
    """Render stdlib-only help/doctor after core bootstrap cannot complete."""
    if verb == "help":
        from .cli_contract import render_help_menu

        print(render_help_menu(), end="")
        print("核心运行环境尚未就绪；kb help 和 kb doctor 仍可使用，其它操作会安全停止。")
        return True
    if verb == "doctor":
        print(f"研究能力包版本为 {_public_package_version(home)}。")
        print("核心运行环境尚未就绪；配置读写和材料转换依赖不完整。")
        print("请让 Agent 按安装说明中的离线恢复步骤准备运行环境，然后再次使用 kb doctor 复查。")
        return True
    return False


def ensure_managed_runtime(
    home: Path | None = None,
    *,
    allow_provision: bool = True,
) -> None:
    """Ensure the current skill entrypoint can import the core source runtime.

    This function is intentionally side-effectful and must only be called from
    script entrypoint paths, never during shared-library import.
    """

    if os.environ.get(READY_FLAG) == "1":
        return

    configured_python = str(os.environ.get("RESEARCH_PYTHON") or "").strip()
    if configured_python:
        configured_path = _python_path(configured_python)
        configured_is_current = is_current_python(configured_path)
        if configured_is_current and _current_has_yaml():
            _mark_ready()
            return
        if _python_can_import_yaml(configured_path):
            # The same executable may have reached us through a wrapper that
            # injected ``-S`` or similar flags.  Re-exec the reviewed binary
            # with a clean argv instead of marking that deficient live process
            # ready merely because the underlying path matches.
            _reexec(configured_path)
            return

    if os.environ.get("RESEARCH_NO_MANAGED_VENV") == "1":
        if _current_has_yaml():
            _mark_ready()
            return
        if not configured_python and _use_path_runtime_if_available(home):
            return
        raise SystemExit(_failure_message(managed_venv_dir(home), RuntimeError("provisioning disabled")))

    venv_dir = managed_venv_dir(home)
    venv_py = managed_venv_python(home)
    # Prefer an already-provisioned project runtime even when the launching Python
    # happens to have YAML. This keeps dependency capability and doctor output tied
    # to the managed project environment.
    if venv_py.exists() and _python_can_import_yaml(venv_py):
        if is_current_python(venv_py):
            if allow_provision:
                _prepare_managed_pdf_backend(venv_dir, venv_py)
            _mark_ready()
            return
        # Complete a partially provisioned runtime (PDF backend missing after an
        # earlier offline install) before handing execution to it: the re-exec'd
        # process starts with the ready flag set and would never retry on its own.
        if allow_provision:
            _prepare_managed_pdf_backend(venv_dir, venv_py)
        _reexec(venv_py)
        return

    if _current_has_yaml() and (_pdf_backend_opted_out() or _current_has_pdf_backend()):
        # Never pip-install into an arbitrary/shared launching interpreter during a
        # normal kb invocation; dependency installation is confined to the managed
        # venv path. With the PDF deep-read backend also importable (or explicitly
        # opted out) the current interpreter is fully usable as-is.
        _mark_ready()
        return

    if _current_has_yaml():
        if not allow_provision:
            _mark_ready()
            return
        # Core imports are available but the always-installed paper deep-read
        # backend (pymupdf4llm) is missing, so `kb ingest` of a PDF would fail
        # while doctor used to claim readiness. Provision the managed venv (which
        # installs the PDF backend); on failure degrade gracefully to the current
        # interpreter so text/web workflows keep working.
        if _pdf_backend_retry_is_throttled(venv_dir):
            _mark_ready()
            return
        try:
            print("论文 PDF 解析环境尚未就绪，正在自动准备，请稍候。", file=sys.stderr, flush=True)
            _ensure_venv_has_yaml(venv_dir, venv_py)
        except Exception:  # noqa: BLE001
            _record_pdf_backend_failure(venv_dir)
            print(
                "自动准备运行环境未完成，先使用当前环境继续；论文 PDF 深读能力暂不可用，"
                "约一小时后自动重试；也可以随时用 kb doctor 查看就绪状态。",
                file=sys.stderr,
                flush=True,
            )
            _mark_ready()
            return
        if is_current_python(venv_py):
            _mark_ready()
            return
        _reexec(venv_py)
        return

    if not configured_python and _use_path_runtime_if_available(home):
        return

    if not allow_provision:
        raise SystemExit(_failure_message(venv_dir, RuntimeError("core runtime unavailable")))

    try:
        print("首次使用需要准备运行环境，请稍候。", file=sys.stderr, flush=True)
        _ensure_venv_has_yaml(venv_dir, venv_py)
    except Exception as exc:  # noqa: BLE001
        if _current_has_yaml():
            _mark_ready()
            return
        raise SystemExit(_failure_message(venv_dir, exc)) from exc

    if is_current_python(venv_py):
        _mark_ready()
        return
    _reexec(venv_py)

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from research import bootstrap


@pytest.fixture(autouse=True)
def _restore_runtime_ready_flag():
    """A bootstrap unit test must not mutate later subprocess test environments."""
    present = bootstrap.READY_FLAG in bootstrap.os.environ
    original = bootstrap.os.environ.get(bootstrap.READY_FLAG)
    try:
        yield
    finally:
        if present and original is not None:
            bootstrap.os.environ[bootstrap.READY_FLAG] = original
        else:
            bootstrap.os.environ.pop(bootstrap.READY_FLAG, None)


def test_yaml_capable_shared_runtime_is_never_pip_mutated(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: True)
    monkeypatch.setattr(bootstrap, "_current_has_pdf_backend", lambda: True)
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: tmp_path / "missing" / "python")
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: tmp_path / "missing")
    monkeypatch.setattr(
        bootstrap,
        "_ensure_python_has_pdf_backend",
        lambda python_exe: calls.append(str(python_exe)),
    )

    bootstrap.ensure_managed_runtime()

    assert calls == []
    assert bootstrap.os.environ[bootstrap.READY_FLAG] == "1"


def test_existing_managed_runtime_is_preferred_silently(monkeypatch, tmp_path, capsys) -> None:
    managed_python = tmp_path / ".venv" / "bin" / "python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("", encoding="utf-8")
    reexec: list[object] = []
    pdf_preparation: list[object] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: managed_python)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda python: python == managed_python)
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: False)
    monkeypatch.setattr(
        bootstrap,
        "_prepare_managed_pdf_backend",
        lambda venv_dir, python: pdf_preparation.append((venv_dir, python)) or True,
    )
    monkeypatch.setattr(bootstrap, "_reexec", lambda python: reexec.append(python))

    bootstrap.ensure_managed_runtime(tmp_path)

    assert reexec == [managed_python]
    assert pdf_preparation == [(tmp_path / ".venv", managed_python)]
    assert capsys.readouterr().err == ""


def test_missing_current_runtime_reexecs_later_path_python_without_bootstrap(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    compatible = tmp_path.parent / "compatible-python"
    compatible.write_text("", encoding="utf-8")
    reexec: list[object] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: tmp_path / ".venv/bin/python")
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)
    monkeypatch.setattr(bootstrap, "_path_runtime_python", lambda _home=None: compatible)
    monkeypatch.setattr(bootstrap, "_reexec", lambda python: reexec.append(python))
    monkeypatch.setattr(
        bootstrap,
        "_ensure_venv_has_yaml",
        lambda *_args: (_ for _ in ()).throw(AssertionError("managed venv should not be prepared")),
    )

    bootstrap.ensure_managed_runtime(tmp_path)

    assert reexec == [compatible]
    assert capsys.readouterr().err == ""


def test_path_runtime_discovery_skips_relative_and_workspace_candidates(monkeypatch, tmp_path) -> None:
    workspace_bin = tmp_path / "bin"
    workspace_bin.mkdir()
    workspace_python = workspace_bin / "python3"
    workspace_python.write_text("workspace", encoding="utf-8")
    workspace_python.chmod(0o755)
    external_bin = tmp_path.parent / f"external-{tmp_path.name}"
    external_bin.mkdir()
    external_python = external_bin / "python3"
    external_python.write_text("external", encoding="utf-8")
    external_python.chmod(0o755)
    monkeypatch.setenv("PATH", f"relative-bin{bootstrap.os.pathsep}{workspace_bin}{bootstrap.os.pathsep}{external_bin}")
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: False)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda python: python == external_python)

    assert bootstrap._path_runtime_python(tmp_path) == external_python


def test_path_runtime_can_reselect_same_binary_when_live_process_hides_modules(
    monkeypatch,
    tmp_path,
) -> None:
    executable = bootstrap._python_path(sys.executable).resolve()
    monkeypatch.setenv("PATH", str(executable.parent))
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: True)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda python: python == executable)

    assert bootstrap._path_runtime_python(tmp_path) == executable


def test_same_executable_reprobes_clean_invocation_when_current_flags_hide_modules(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: True)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)

    def completed(argv, **_kwargs):
        calls.append(argv)
        return bootstrap.subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", completed)

    assert bootstrap._python_can_import_yaml(sys.executable) is True
    assert calls == [[sys.executable, "-c", "import yaml, markdownify, bs4"]]


def test_configured_same_executable_reexecs_when_live_process_hides_modules(
    monkeypatch,
) -> None:
    reexec: list[object] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.setenv("RESEARCH_PYTHON", sys.executable)
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: True)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda _python: True)
    monkeypatch.setattr(bootstrap, "_reexec", lambda python: reexec.append(python))

    bootstrap.ensure_managed_runtime()

    assert reexec == [bootstrap._python_path(sys.executable)]
    assert bootstrap.READY_FLAG not in bootstrap.os.environ


def test_first_time_runtime_preparation_has_one_natural_progress_line(monkeypatch, tmp_path, capsys) -> None:
    managed_python = tmp_path / ".venv" / "bin" / "python"
    reexec: list[object] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: managed_python)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)
    monkeypatch.setattr(bootstrap, "_path_runtime_python", lambda _home=None: None)
    monkeypatch.setattr(bootstrap, "_ensure_venv_has_yaml", lambda *_args: None)
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: False)
    monkeypatch.setattr(bootstrap, "_reexec", lambda python: reexec.append(python))

    bootstrap.ensure_managed_runtime(tmp_path)

    assert reexec == [managed_python]
    assert capsys.readouterr().err == "首次使用需要准备运行环境，请稍候。\n"


def test_runtime_failure_message_is_natural_language_only(tmp_path) -> None:
    message = bootstrap._failure_message(tmp_path / ".venv", RuntimeError("private detail"))

    assert message == (
        "无法准备运行所需的环境。\n"
        "请让 Agent 按安装说明中的离线恢复步骤准备运行环境，完成后再使用 kb doctor 复查。"
    )
    assert "[research]" not in message
    assert "private detail" not in message


def test_diagnostic_bootstrap_never_provisions_missing_core_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    managed_dir = tmp_path / ".venv"
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: managed_dir)
    monkeypatch.setattr(
        bootstrap,
        "managed_venv_python",
        lambda _home=None: managed_dir / "bin" / "python",
    )
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)
    monkeypatch.setattr(bootstrap, "_path_runtime_python", lambda _home=None: None)
    monkeypatch.setattr(
        bootstrap,
        "_ensure_venv_has_yaml",
        lambda *_args: (_ for _ in ()).throw(AssertionError("diagnostics must not provision")),
    )

    with pytest.raises(SystemExit, match="离线恢复步骤"):
        bootstrap.ensure_managed_runtime(tmp_path, allow_provision=False)

    assert not managed_dir.exists()


def test_entrypoint_public_verb_skips_private_global_options() -> None:
    assert bootstrap.entrypoint_public_verb(["doctor"]) == "doctor"
    assert bootstrap.entrypoint_public_verb(["--root", "/tmp/work", "help"]) == "help"
    assert bootstrap.entrypoint_public_verb(["--agent-protocol=doctor.json", "doctor"]) == "doctor"
    assert bootstrap.entrypoint_public_verb(["--unknown", "doctor"]) == ""


def test_kb_help_and_doctor_remain_read_only_without_core_runtime(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    managed = tmp_path / "managed"
    home = tmp_path / "home"
    home.mkdir()
    project_root = Path(__file__).resolve().parents[1]
    kb_script = project_root / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": str(empty_bin),
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_VENV": str(managed),
    }
    env.pop(bootstrap.READY_FLAG, None)
    env.pop("RESEARCH_PYTHON", None)
    env.pop("RESEARCH_NO_MANAGED_VENV", None)

    help_result = subprocess.run(
        [sys.executable, "-S", str(kb_script), "help"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    doctor_result = subprocess.run(
        [sys.executable, "-S", str(kb_script), "doctor"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    assert "kb 动词（16 个）" in help_result.stdout
    assert "核心运行环境尚未就绪" in help_result.stdout
    assert doctor_result.returncode == 0, doctor_result.stdout + doctor_result.stderr
    assert "核心运行环境尚未就绪" in doctor_result.stdout
    assert "离线恢复步骤" in doctor_result.stdout
    assert not managed.exists()


def test_pdf_backend_opt_out_skips_import_check_and_install(monkeypatch) -> None:
    monkeypatch.setenv(bootstrap.NO_PDF_BACKEND_ENV, "1")
    monkeypatch.setattr(
        bootstrap,
        "_python_can_import",
        lambda *_args: (_ for _ in ()).throw(AssertionError("import check should be skipped")),
    )
    monkeypatch.setattr(
        bootstrap,
        "_run_checked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("install should be skipped")),
    )

    assert bootstrap._ensure_python_has_pdf_backend(sys.executable) is True


def test_failed_pdf_preparation_is_throttled_for_existing_managed_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    managed_dir = tmp_path / ".venv"
    managed_python = managed_dir / "bin" / "python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("", encoding="utf-8")
    attempts: list[object] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.delenv(bootstrap.NO_PDF_BACKEND_ENV, raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: managed_dir)
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: managed_python)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda python: python == managed_python)
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: True)
    monkeypatch.setattr(
        bootstrap,
        "_ensure_python_has_pdf_backend",
        lambda python: attempts.append(python) or False,
    )

    bootstrap.ensure_managed_runtime(tmp_path)
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    bootstrap.ensure_managed_runtime(tmp_path)

    assert attempts == [managed_python]
    assert (managed_dir / ".pdf-backend-prep-last-attempt").is_file()

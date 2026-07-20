from __future__ import annotations

import sys

from research import bootstrap


def test_yaml_capable_shared_runtime_is_never_pip_mutated(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: True)
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
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: managed_python)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda python: python == managed_python)
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: False)
    monkeypatch.setattr(bootstrap, "_reexec", lambda python: reexec.append(python))

    bootstrap.ensure_managed_runtime(tmp_path)

    assert reexec == [managed_python]
    assert capsys.readouterr().err == ""


def test_first_time_runtime_preparation_has_one_natural_progress_line(monkeypatch, tmp_path, capsys) -> None:
    managed_python = tmp_path / ".venv" / "bin" / "python"
    reexec: list[object] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: managed_python)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: False)
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
        "请让 Agent 运行 kb doctor 查看私有诊断，并协助选择可用环境。"
    )
    assert "[research]" not in message
    assert "private detail" not in message


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

    bootstrap._ensure_python_has_pdf_backend(sys.executable)

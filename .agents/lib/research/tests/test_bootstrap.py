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


def test_existing_managed_runtime_is_preferred_over_shared_python(monkeypatch, tmp_path) -> None:
    managed_python = tmp_path / ".venv" / "bin" / "python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("", encoding="utf-8")
    reexec: list[tuple[object, str]] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "managed_venv_dir", lambda _home=None: tmp_path / ".venv")
    monkeypatch.setattr(bootstrap, "managed_venv_python", lambda _home=None: managed_python)
    monkeypatch.setattr(bootstrap, "_python_can_import_yaml", lambda python: python == managed_python)
    monkeypatch.setattr(bootstrap, "is_current_python", lambda _python: False)
    monkeypatch.setattr(bootstrap, "_reexec", lambda python, message: reexec.append((python, message)))

    bootstrap.ensure_managed_runtime(tmp_path)

    assert reexec == [(managed_python, "[research] 正在使用项目受管运行环境。")]


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

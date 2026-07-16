from __future__ import annotations

import sys

from research import bootstrap


def test_yaml_capable_current_runtime_ensures_pdf_backend_before_ready(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.delenv("RESEARCH_PYTHON", raising=False)
    monkeypatch.delenv("RESEARCH_NO_MANAGED_VENV", raising=False)
    monkeypatch.setattr(bootstrap, "_current_has_yaml", lambda: True)
    monkeypatch.setattr(
        bootstrap,
        "_ensure_python_has_pdf_backend",
        lambda python_exe: calls.append(str(python_exe)),
    )

    bootstrap.ensure_managed_runtime()

    assert calls == [sys.executable]
    assert bootstrap.os.environ[bootstrap.READY_FLAG] == "1"


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

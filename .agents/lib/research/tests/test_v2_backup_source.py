from __future__ import annotations

from pathlib import Path

import pytest

import research.v2 as v2


def test_backup_source_warns_for_non_html_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch_url(url: str, *, timeout: int) -> tuple[str, str]:
        return "%PDF-1.7", "application/pdf"

    monkeypatch.setattr(v2, "fetch_url", fake_fetch_url)

    payload = v2.backup_source(tmp_path, "paper", "p-binary-123456", "https://example.com/paper.pdf")

    assert payload["file_hash"] == ""
    assert "backup_warning" in payload
    assert "application/pdf" in payload["backup_warning"]
    assert "WARN" in capsys.readouterr().err
    assert (v2.unit_root(tmp_path, "paper", "p-binary-123456") / "source" / "source-url.txt").exists()
    assert not (v2.unit_root(tmp_path, "paper", "p-binary-123456") / "source" / "snapshot.md").exists()


def test_backup_source_warns_when_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch_url(url: str, *, timeout: int) -> tuple[str, str]:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(v2, "fetch_url", fake_fetch_url)

    payload = v2.backup_source(tmp_path, "paper", "p-fetch-123456", "https://example.com/source")

    assert payload["file_hash"] == ""
    assert "network unavailable" in payload["backup_warning"]
    assert "WARN" in capsys.readouterr().err

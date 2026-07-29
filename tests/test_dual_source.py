from __future__ import annotations

from pathlib import Path

import pytest

import research.common as common
import research.sources as sources
from research.evidence import verify_claim_evidence
from research.yaml_io import load_yaml


class _FakeResp:
    def __init__(self, body: bytes, content_type: str = "application/pdf") -> None:
        self._body = body
        self._pos = 0
        self.headers = {"Content-Type": content_type}

    # headers.get is what fetch_url calls
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._body[self._pos:]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def _minimal_pdf_bytes(text: str) -> bytes:
    import fitz  # type: ignore

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


# --- fetch_url: retry + size cap -------------------------------------------


def test_fetch_url_retries_transient_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.error import URLError

    calls = {"n": 0}

    def flaky_urlopen(request, timeout):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] < 3:
            raise URLError("temporary failure")
        return _FakeResp(b"hello world", "text/plain")

    monkeypatch.setattr(common, "urlopen", flaky_urlopen)
    monkeypatch.setattr(common.time, "sleep", lambda *_: None)

    body, ctype = common.fetch_url("https://example.com/x", retries=3)
    assert body == "hello world"
    assert ctype == "text/plain"
    assert calls["n"] == 3  # two failures then success


def test_fetch_url_does_not_retry_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.error import HTTPError

    calls = {"n": 0}

    def urlopen_404(request, timeout):  # noqa: ANN001
        calls["n"] += 1
        raise HTTPError("https://example.com/x", 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(common, "urlopen", urlopen_404)
    monkeypatch.setattr(common.time, "sleep", lambda *_: None)

    with pytest.raises(HTTPError):
        common.fetch_url("https://example.com/x", retries=3)
    assert calls["n"] == 1  # definitive 4xx is not retried


def test_fetch_url_enforces_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    def big_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResp(b"x" * 5000, "application/octet-stream")

    monkeypatch.setattr(common, "urlopen", big_urlopen)

    with pytest.raises(common.FetchTooLarge):
        common.fetch_url("https://example.com/big", binary=True, max_bytes=1024)


# --- HTML section chunking (B4: section/anchor, no page numbers) ------------


def test_html_section_chunks_carry_section_anchor() -> None:
    html = (
        "<html><body><h2 id='intro'>Introduction</h2><p>Intro body text.</p>"
        "<h2 id='method'>Method</h2><p>Method body text.</p></body></html>"
    )
    chunks = sources._html_to_section_chunks(html)
    labels = [c["label"] for c in chunks]
    assert "section:intro" in labels
    assert "section:method" in labels
    for c in chunks:
        assert c["locator_kind"] == "section"
        assert c["page"] is None
        assert c["label"].startswith("section:")
        assert "page-" not in c["label"]


# --- parse-cache writer ------------------------------------------------------


def test_write_parse_cache_records_locator_kind(tmp_path: Path) -> None:
    source_info = {
        "source_type": "pdf",
        "locator_kind": "page",
        "parse_backend": "pymupdf4llm",
        "parse_chunks": [{"label": "source.pdf:page-1", "text": "hello", "page": 1}],
    }
    path = sources.write_parse_cache(tmp_path, "p-x-1", source_info)
    assert path is not None and path.name == "parse-cache.yaml"
    data = load_yaml(path)
    assert data["locator_kind"] == "page"
    assert data["source_type"] == "pdf"
    assert data["chunks"][0]["label"] == "source.pdf:page-1"

    # No chunks -> no cache written.
    assert sources.write_parse_cache(tmp_path, "p-x-2", {"parse_chunks": []}) is None


# --- downstream evidence integration (B4 two locators, SSOT 原则2) ----------


def test_evidence_grounds_pdf_page_locator(tmp_path: Path) -> None:
    unit = tmp_path / "unit"
    unit.mkdir()
    source_info = {
        "source_type": "pdf",
        "locator_kind": "page",
        "parse_chunks": [
            {"label": "source.pdf:page-1", "text": "The transformer uses self attention.", "page": 1},
            {"label": "source.pdf:page-2", "text": "We report a new state of the art.", "page": 2},
        ],
    }
    sources.write_parse_cache(unit, "p-ev-1", source_info)
    claim = {
        "id": "claim-1",
        "text": "It uses self attention.",
        "claim_type": "fact",
        "evidence_refs": [
            {"source_unit_id": "p-ev-1", "artifact": "parse-cache.yaml", "locator": "page=1", "quote": "self attention", "summary": ""}
        ],
    }
    assert verify_claim_evidence(claim, unit) == []

    # Correct quote but wrong page -> locator mismatch violation (page narrowing).
    claim_wrong_page = {
        "id": "claim-2",
        "text": "It uses self attention.",
        "claim_type": "fact",
        "evidence_refs": [
            {"source_unit_id": "p-ev-1", "artifact": "parse-cache.yaml", "locator": "page=2", "quote": "self attention", "summary": ""}
        ],
    }
    assert verify_claim_evidence(claim_wrong_page, unit)  # non-empty == violation


def test_evidence_grounds_html_section_locator(tmp_path: Path) -> None:
    unit = tmp_path / "unit"
    unit.mkdir()
    html = "<html><body><h2 id='method'>Method</h2><p>We combine attention and convolution.</p></body></html>"
    chunks = sources._html_to_section_chunks(html)
    source_info = {"source_type": "arxiv-html", "locator_kind": "section", "parse_chunks": chunks}
    sources.write_parse_cache(unit, "p-ev-html", source_info)
    claim = {
        "id": "claim-h1",
        "text": "It combines attention and convolution.",
        "claim_type": "inference",
        "evidence_refs": [
            {"source_unit_id": "p-ev-html", "artifact": "parse-cache.yaml", "locator": "section", "quote": "attention and convolution", "summary": ""}
        ],
    }
    # HTML has no page numbers; a section locator grounds on verbatim substring alone.
    assert verify_claim_evidence(claim, unit) == []


# --- local PDF path ----------------------------------------------------------


def test_local_pdf_backup_persists_bytes_and_page_locator(tmp_path: Path) -> None:
    pdf = tmp_path / "local.pdf"
    data = _minimal_pdf_bytes("Local PDF body on page one.")
    pdf.write_bytes(data)

    payload = sources.backup_source(tmp_path, "paper", "p-local-123456", str(pdf))
    assert payload["backup_status"] == "ok"
    assert payload["source_type"] == "pdf"
    assert payload["locator_kind"] == "page"
    import hashlib

    assert payload["file_hash"] == hashlib.sha256(data).hexdigest()
    assert payload["parse_chunks"] and payload["parse_chunks"][0]["page"] == 1

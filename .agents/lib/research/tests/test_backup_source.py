from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import research.core as core

# backup_source lives in research.sources after the god-file split; its fetch_url
# lookup resolves in that module's namespace, so patch it there.
import research.sources as sources


def _minimal_pdf_bytes(text: str = "Dual Source Test\nBody paragraph on page one.") -> bytes:
    """A tiny but real PDF (PyMuPDF), so the lightweight backend extracts text."""
    import fitz  # type: ignore

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


_ARXIV_HTML = (
    "<!doctype html><html><head><title>Attention Test Paper</title></head><body>"
    "<blockquote class='abstract'>Abstract: we test dual-source ingestion.</blockquote>"
    "<h2 id='intro'>Introduction</h2><p>Section one body about transformers.</p>"
    "<h2 id='method'>Method</h2><p>Section two body about attention.</p>"
    "</body></html>"
)


def test_backup_source_non_html_non_pdf_url_fails_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A URL that is neither HTML nor PDF must fail EXPLICITLY (not silently).
    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        return b"\x00\x01\x02binary-blob", "application/octet-stream"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)

    payload = core.backup_source(tmp_path, "blog", "b-binary-123456", "https://example.com/thing.bin")

    assert payload["file_hash"] == ""
    assert payload["backup_status"] == "failed"
    assert "backup_warning" in payload
    assert "application/octet-stream" in payload["backup_warning"]
    assert "WARN" in capsys.readouterr().err
    # The warning/status must NOT leak into the on-disk source record contract.
    projected = core.source_record_fields(payload)
    assert "backup_warning" not in projected
    assert "backup_status" not in projected
    assert set(projected) <= set(core.SOURCE_RECORD_KEYS)


def test_backup_source_warns_when_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_fetch_url(url: str, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)

    payload = core.backup_source(tmp_path, "blog", "b-fetch-123456", "https://example.com/source")

    assert payload["file_hash"] == ""
    assert payload["backup_status"] == "failed"
    assert "network unavailable" in payload["backup_warning"]
    assert "WARN" in capsys.readouterr().err
    # source-url.txt is still archived by reference even when the fetch fails.
    assert (core.unit_root(tmp_path, "blog", "b-fetch-123456") / "source" / "source-url.txt").exists()


def test_backup_source_pdf_url_persists_bytes_and_page_locator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _minimal_pdf_bytes()

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        return data, "application/pdf"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)

    payload = core.backup_source(tmp_path, "paper", "p-pdf-123456", "https://example.com/paper.pdf")

    assert payload["backup_status"] == "ok"
    assert payload["source_type"] == "pdf"
    assert payload["locator_kind"] == "page"
    # Real bytes + real sha256 of exactly those bytes.
    assert payload["file_hash"] == hashlib.sha256(data).hexdigest()
    raw = core.unit_root(tmp_path, "paper", "p-pdf-123456") / "source" / "source.pdf"
    assert raw.exists() and raw.read_bytes() == data
    chunks = payload["parse_chunks"]
    assert chunks and chunks[0]["label"].endswith(":page-1")
    assert chunks[0]["page"] == 1


def test_backup_source_arxiv_prefers_html_with_section_locator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        calls.append(url)
        return _ARXIV_HTML.encode("utf-8"), "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)

    payload = core.backup_source(tmp_path, "paper", "p-arxiv-123456", "https://arxiv.org/abs/1706.03762")

    # HTML-first: the very first attempt is the native arxiv HTML edition.
    assert calls[0] == "https://arxiv.org/html/1706.03762"
    assert payload["backup_status"] == "ok"
    assert payload["source_type"] == "arxiv-html"
    assert payload["locator_kind"] == "section"
    assert payload["file_hash"] == hashlib.sha256(_ARXIV_HTML.encode("utf-8")).hexdigest()
    labels = [c["label"] for c in payload["parse_chunks"]]
    assert any(label.startswith("section:") for label in labels)
    assert all(not label.endswith("page-1") for label in labels)  # HTML has no page numbers


def test_backup_source_arxiv_falls_back_when_html_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.error import HTTPError

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        if url.startswith("https://arxiv.org/html/"):
            raise HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _ARXIV_HTML.encode("utf-8"), "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)

    payload = core.backup_source(tmp_path, "paper", "p-arxiv-old-1234", "https://arxiv.org/abs/1301.3781")

    # Native HTML 404 -> direct ar5iv Labs fallback still yields section-located HTML.
    assert payload["backup_status"] == "ok"
    assert payload["resolved_url"] == "https://ar5iv.labs.arxiv.org/html/1301.3781"
    assert payload["locator_kind"] == "section"


def test_backup_source_rejects_a_file_symlink_without_copying_target_bytes(tmp_path: Path) -> None:
    secret = b"outside-file-secret\n"
    target = tmp_path / "outside-secret.md"
    target.write_bytes(secret)
    selected = tmp_path / "selected.md"
    selected.symlink_to(target)

    with pytest.raises(sources.UnsafeLocalSourceError, match="符号链接"):
        sources.backup_source(tmp_path, "blog", "b-link-file", selected.as_posix())

    assert not core.unit_root(tmp_path, "blog", "b-link-file").exists()
    copied = [path for path in (tmp_path / "kb").rglob("*") if path.is_file() and secret in path.read_bytes()]
    assert copied == []


@pytest.mark.parametrize("link_target", ["outside", "inside"])
def test_backup_source_rejects_nested_directory_symlinks_without_copying_target_bytes(
    tmp_path: Path,
    link_target: str,
) -> None:
    secret = b"nested-link-secret\n"
    selected = tmp_path / "selected-repo"
    selected.mkdir()
    (selected / "README.md").write_text("# Safe repository\n", encoding="utf-8")
    if link_target == "outside":
        target = tmp_path / "outside-tree"
    else:
        target = selected / "real-tree"
    target.mkdir()
    (target / "secret.txt").write_bytes(secret)
    (selected / "nested-link").symlink_to(target, target_is_directory=True)

    with pytest.raises(sources.UnsafeLocalSourceError, match="符号链接"):
        sources.backup_source(tmp_path, "repo", f"r-link-{link_target}", selected.as_posix())

    assert not core.unit_root(tmp_path, "repo", f"r-link-{link_target}").exists()
    copied = [path for path in (tmp_path / "kb").rglob("*") if path.is_file() and secret in path.read_bytes()]
    assert copied == []


def test_backup_source_copies_an_ordinary_directory_without_vcs_metadata(tmp_path: Path) -> None:
    selected = tmp_path / "ordinary-repo"
    (selected / "src").mkdir(parents=True)
    (selected / "src" / "main.py").write_text("print('safe')\n", encoding="utf-8")
    (selected / ".git").mkdir()
    (selected / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    payload = sources.backup_source(tmp_path, "repo", "r-ordinary", selected.as_posix())

    archived = tmp_path / payload["backup_paths"][0]
    assert payload["backup_status"] == "ok"
    assert (archived / "src" / "main.py").read_text(encoding="utf-8") == "print('safe')\n"
    assert not (archived / ".git").exists()


def test_directory_copy_rechecks_root_after_preflight_and_cleans_failed_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "selected-repo"
    selected.mkdir()
    (selected / "README.md").write_text("# Initially safe\n", encoding="utf-8")
    outside = tmp_path / "outside-tree"
    outside.mkdir()
    secret = b"race-secret-must-not-copy\n"
    (outside / "secret.txt").write_bytes(secret)
    displaced = tmp_path / "displaced-tree"
    destination = tmp_path / "archive"
    real_assert = sources._assert_contained_local_tree

    def replace_after_preflight(path: Path) -> None:
        real_assert(path)
        path.rename(displaced)
        path.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(sources, "_assert_contained_local_tree", replace_after_preflight)

    with pytest.raises(sources.UnsafeLocalSourceError, match="发生了变化"):
        sources._copy_dir(selected, destination)

    assert not destination.exists()
    assert all(secret not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file() and path != outside / "secret.txt")

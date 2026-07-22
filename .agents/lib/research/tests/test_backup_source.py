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


def _valid_png_bytes() -> bytes:
    import fitz  # type: ignore

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 60), False)
    pixmap.clear_with(0x336699)
    return pixmap.tobytes("png")


def _pdf_with_image_bytes() -> bytes:
    import fitz  # type: ignore

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Visual Source Paper")
    page.insert_text((72, 92), "This page contains a result figure and readable source text.")
    page.insert_image(fitz.Rect(72, 140, 232, 260), stream=_valid_png_bytes())
    data = doc.tobytes()
    doc.close()
    return data


_ARXIV_HTML = (
    "<!doctype html><html><head><title>Attention Test Paper</title></head><body>"
    "<blockquote class='abstract'>Abstract: we test dual-source ingestion.</blockquote>"
    "<article class='ltx_document'><h2 id='intro'>Introduction</h2>"
    "<p>Section one gives a complete account of transformer motivation, prior sequence models, "
    "the limits of recurrence, and the need for efficient long-range interaction.</p>"
    "<p>It also defines the evaluation setting and the evidence used by the paper.</p>"
    "<h2 id='method'>Method</h2><p>Section two explains attention, encoder and decoder blocks, "
    "optimization, regularization, and the exact interfaces between model components.</p>"
    "<p>The experiments compare controlled baselines and report reproducible measurements.</p>"
    "</article>"
    "</body></html>"
)

_PNG_BYTES = _valid_png_bytes()


def test_backup_source_non_html_non_pdf_url_archives_bytes_as_stored_unparsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Unsupported binary bytes remain auditable even when no parser exists.
    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        return b"\x00\x01\x02binary-blob", "application/octet-stream"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)

    payload = core.backup_source(tmp_path, "blog", "b-binary-123456", "https://example.com/thing.bin")

    assert payload["file_hash"] == hashlib.sha256(b"\x00\x01\x02binary-blob").hexdigest()
    assert payload["backup_status"] == "stored-unparsed"
    assert "backup_warning" in payload
    assert "application/octet-stream" in payload["backup_warning"]
    assert "WARN" in capsys.readouterr().err
    raw = core.unit_root(tmp_path, "blog", "b-binary-123456") / "source/source.bin"
    assert raw.read_bytes() == b"\x00\x01\x02binary-blob"
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
    document = raw.parent / "document.md"
    assert document.is_file()
    assert "[原始 PDF](source.pdf)" in document.read_text(encoding="utf-8")
    assert "^source-page-1" in document.read_text(encoding="utf-8")
    assert payload["markdown_hash"] == hashlib.sha256(document.read_bytes()).hexdigest()
    assert payload["materialization"]["status"] == "complete"
    assert (raw.parent / "source-map.yaml").is_file()
    assert (raw.parent / "conversion.yaml").is_file()
    chunks = payload["parse_chunks"]
    assert chunks and chunks[0]["label"].endswith(":page-1")
    assert chunks[0]["page"] == 1


def test_backup_source_pdf_extracts_local_hash_addressed_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _pdf_with_image_bytes()

    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (data, "application/pdf"))
    payload = sources.backup_source(tmp_path, "paper", "p-pdf-image-123456", "https://example.com/visual.pdf")

    assert payload["backup_status"] == "ok"
    source_root = core.unit_root(tmp_path, "paper", "p-pdf-image-123456") / "source"
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert "^source-page-1" in document
    assert "![PDF page 1 image](assets/image-" in document
    assets = list((source_root / "assets").glob("image-*.png"))
    assert len(assets) == 1
    source_map = core.load_yaml(source_root / "source-map.yaml", default={})
    assert source_map["assets"][0]["page"] == 1
    assert source_map["assets"][0]["locator_kind"] == "page"
    assert source_map["assets"][0]["path"] == f"assets/{assets[0].name}"


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
    source_root = core.unit_root(tmp_path, "paper", "p-arxiv-123456") / "source"
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert "## Introduction" in document
    assert "^source-section-intro" in document
    assert not (source_root / "snapshot.md").exists()


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


def test_backup_source_html_localizes_images_and_preserves_structured_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><head><title>Visual Paper</title></head><body>
    <article><h1 id="overview">Overview</h1><p>Readable paragraph.</p>
    <figure><img src="/figures/result.png" alt="Result chart"><figcaption>Figure 1. Success rate.</figcaption></figure>
    <table><tr><th>Method</th><th>Score</th></tr><tr><td>Ours</td><td>91</td></tr></table>
    <math alttext="x^2+y^2" display="block"></math></article></body></html>"""

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        if url.endswith("result.png"):
            return _PNG_BYTES, "image/png"
        return html, "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)
    payload = sources.backup_source(tmp_path, "blog", "b-visual-123456", "https://example.com/post")

    assert payload["backup_status"] == "ok"
    source_root = core.unit_root(tmp_path, "blog", "b-visual-123456") / "source"
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert "# Overview" in document
    assert "Readable paragraph." in document
    assert "Figure 1. Success rate." in document
    assert "| Method | Score |" in document
    assert "x^2+y^2" in document
    assert "https://example.com/figures/result.png" not in document
    assert "assets/image-" in document
    assets = list((source_root / "assets").glob("image-*.png"))
    assert len(assets) == 1
    assert assets[0].read_bytes() == _PNG_BYTES
    assert payload["materialization"]["asset_paths"] == [assets[0].relative_to(tmp_path).as_posix()]
    assert payload["markdown_path"] == (source_root / "document.md").relative_to(tmp_path).as_posix()


def test_html_materialization_v2_resolves_base_and_preserves_math_fragments_and_gallery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><head><title>Structured Paper</title>
    <base href="/html/2600.00001v2/"></head><body><article class="ltx_document">
    <h1 id="title">Structured Paper</h1>
    <p>We define <math alttext="\\Psi_{0}"></math> and cite <a href="#bib.bib1">Prior work</a>.</p>
    <figure><img src="x1.png" alt="[Uncaptioned image]"><img src="x2.png" alt="Panel [B]">
    <figcaption>Figure 1. Two evaluation panels.</figcaption></figure>
    <h2 id="results">Results</h2><p>Results remain grounded in the archived source.</p>
    <ol><li id="bib.bib1">Reference entry.</li></ol>
    </article></body></html>"""
    requested: list[str] = []

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        requested.append(url)
        if url.endswith(("x1.png", "x2.png")):
            return _PNG_BYTES, "image/png"
        return html, "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)
    payload = sources.backup_source(tmp_path, "blog", "b-structured-123456", "https://example.com/paper")

    source_root = core.unit_root(tmp_path, "blog", "b-structured-123456") / "source"
    document = (source_root / "document.md").read_text(encoding="utf-8")
    archive = (source_root / "archive.html").read_text(encoding="utf-8")
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    source_map = core.load_yaml(source_root / "source-map.yaml", default={})

    assert "https://example.com/html/2600.00001v2/x1.png" in requested
    assert "https://example.com/html/2600.00001v2/x2.png" in requested
    assert r"$\Psi_{0}$" in document
    assert r"\Psi\_{0}" not in document
    assert "![[" not in document
    assert "Uncaptioned image" in document and "Panel (B)" in document
    assert '<figure class="kb-source-gallery">' in document
    assert "](#^source-anchor-bib-bib1)" in document
    assert "^source-anchor-bib-bib1" in document
    assert "assets/image-" in archive and "Figure 1. Two evaluation panels." in archive
    assert conversion["schema"] == "research-source-markdown/v2"
    assert conversion["archive"] == "archive.html"
    assert conversion["archive_sha256"] == hashlib.sha256((source_root / "archive.html").read_bytes()).hexdigest()
    assert payload["materialization"]["archive_path"] == (source_root / "archive.html").relative_to(tmp_path).as_posix()
    assert any(item["anchor"] == "bib.bib1" for item in source_map["blocks"])

    archive_before = (source_root / "archive.html").read_bytes()
    sources.backup_source(tmp_path, "blog", "b-structured-123456", "https://example.com/paper")
    assert (source_root / "archive.html").read_bytes() == archive_before
    (source_root / "archive.html").write_text("human drift must be preserved\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable source bundle collision: archive.html"):
        sources.backup_source(tmp_path, "blog", "b-structured-123456", "https://example.com/paper")


def test_arxiv_fatal_html_is_rejected_before_write_and_falls_back_to_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.error import HTTPError

    fatal = b"""<!doctype html><html><head><title>Untitled Document</title></head><body>
    <article class="ltx_document"><span class="ltx_ERROR">\\seq</span>
    <p>Conversion to HTML had a Fatal error and exited abruptly.</p></article>
    <a class="ar5iv-severity-fatal">fatal</a></body></html>"""
    pdf = _minimal_pdf_bytes("Quality gate PDF fallback with grounded body text.")

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        if url.startswith("https://arxiv.org/html/"):
            raise HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        if url.startswith("https://ar5iv.labs.arxiv.org/html/"):
            return fatal, "text/html"
        if url.startswith("https://arxiv.org/pdf/"):
            return pdf, "application/pdf"
        raise AssertionError(url)

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)
    payload = sources.backup_source(tmp_path, "paper", "p-fatal-fallback-123456", "2605.12090")

    source_root = core.unit_root(tmp_path, "paper", "p-fatal-fallback-123456") / "source"
    assert payload["source_type"] == "pdf"
    assert payload["resolved_url"] == "https://arxiv.org/pdf/2605.12090"
    assert any("quality gate rejected" in item for item in payload["source_selection_attempts"])
    assert (source_root / "source.pdf").read_bytes() == pdf
    assert not (source_root / "source.html").exists()
    assert "Quality gate PDF fallback" in (source_root / "document.md").read_text(encoding="utf-8")


def test_latexml_error_marker_is_a_degraded_quality_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<html><head><title>Readable with residue</title></head><body><article>
    <h1>Paper</h1><p>A readable paragraph contains <span class="ltx_ERROR">\\badmacro</span>.</p>
    </article></body></html>"""
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    payload = sources.backup_source(tmp_path, "blog", "b-residue-123456", "https://example.com/residue")
    conversion = core.load_yaml(
        core.unit_root(tmp_path, "blog", "b-residue-123456") / "source/conversion.yaml", default={}
    )
    assert payload["backup_status"] == "degraded"
    assert conversion["quality"]["latexml_error_count"] == 1
    assert any("LaTeXML error marker" in item for item in conversion["warnings"])
    assert r"\badmacro" not in (
        core.unit_root(tmp_path, "blog", "b-residue-123456") / "source/document.md"
    ).read_text(encoding="utf-8")


def test_backup_source_html_keeps_remote_image_fallback_and_marks_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"<html><body><article><h1>Post</h1><img src='/missing.png' alt='Missing'></article></body></html>"

    def fake_fetch_url(url: str, **kwargs) -> tuple[bytes, str]:
        if url.endswith("missing.png"):
            raise RuntimeError("image unavailable")
        return html, "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)
    payload = sources.backup_source(tmp_path, "blog", "b-degraded-123456", "https://example.com/post")

    assert payload["backup_status"] == "degraded"
    assert payload["materialization"]["status"] == "degraded"
    document = (core.unit_root(tmp_path, "blog", "b-degraded-123456") / "source/document.md").read_text(encoding="utf-8")
    assert "https://example.com/missing.png" in document
    conversion = core.load_yaml(core.unit_root(tmp_path, "blog", "b-degraded-123456") / "source/conversion.yaml", default={})
    assert any("image unavailable" in warning for warning in conversion["warnings"])


def test_local_markdown_named_document_is_archived_without_overwriting_reading_view(tmp_path: Path) -> None:
    selected = tmp_path / "document.md"
    selected.write_text("# Original heading\n\nFull local content.\n", encoding="utf-8")

    payload = sources.backup_source(tmp_path, "blog", "b-local-md-123456", selected.as_posix())

    source_root = core.unit_root(tmp_path, "blog", "b-local-md-123456") / "source"
    assert (source_root / "original-document.md").read_text(encoding="utf-8").startswith("# Original heading")
    generated = (source_root / "document.md").read_text(encoding="utf-8")
    assert "[原始 Markdown](original-document.md)" in generated
    assert "Full local content." in generated
    assert "^source-section-original-heading" in generated
    assert payload["file_hash"] == hashlib.sha256((source_root / "original-document.md").read_bytes()).hexdigest()


def test_local_markdown_localizes_linked_images(tmp_path: Path) -> None:
    selected = tmp_path / "article.md"
    image = tmp_path / "figure.png"
    image.write_bytes(_PNG_BYTES)
    selected.write_text("# Results\n\n![Success chart](figure.png)\n", encoding="utf-8")

    payload = sources.backup_source(tmp_path, "blog", "b-local-assets-123456", selected.as_posix())

    source_root = core.unit_root(tmp_path, "blog", "b-local-assets-123456") / "source"
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assets = list((source_root / "assets").glob("image-*.png"))
    assert payload["backup_status"] == "ok"
    assert "![Success chart](assets/image-" in document
    assert "figure.png" not in document
    assert len(assets) == 1 and assets[0].read_bytes() == _PNG_BYTES


@pytest.mark.parametrize("bundle_name", ["document.md", "source-map.yaml", "conversion.yaml"])
def test_source_bundle_is_idempotent_and_refuses_overwrite(tmp_path: Path, bundle_name: str) -> None:
    selected = tmp_path / "immutable.md"
    selected.write_text("# Immutable source\n\nGrounded text.\n", encoding="utf-8")
    unit_id = "b-immutable-123456"

    sources.backup_source(tmp_path, "blog", unit_id, selected.as_posix())
    source_root = core.unit_root(tmp_path, "blog", unit_id) / "source"
    before = {path.relative_to(source_root).as_posix(): path.read_bytes() for path in source_root.rglob("*") if path.is_file()}

    sources.backup_source(tmp_path, "blog", unit_id, selected.as_posix())
    after = {path.relative_to(source_root).as_posix(): path.read_bytes() for path in source_root.rglob("*") if path.is_file()}
    assert after == before

    protected = source_root / bundle_name
    protected.write_text("human drift must be preserved\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable source bundle collision"):
        sources.backup_source(tmp_path, "blog", unit_id, selected.as_posix())
    assert protected.read_text(encoding="utf-8") == "human drift must be preserved\n"


def test_raw_source_bytes_are_idempotent_and_refuse_overwrite(tmp_path: Path) -> None:
    selected = tmp_path / "immutable-raw.md"
    original = b"# Immutable raw source\n\nOriginal bytes.\n"
    selected.write_bytes(original)
    unit_id = "b-immutable-raw-123456"

    sources.backup_source(tmp_path, "blog", unit_id, selected.as_posix())
    source_root = core.unit_root(tmp_path, "blog", unit_id) / "source"
    raw = source_root / selected.name
    document_before = (source_root / "document.md").read_bytes()

    sources.backup_source(tmp_path, "blog", unit_id, selected.as_posix())
    selected.write_text("# Changed upstream bytes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable source byte collision"):
        sources.backup_source(tmp_path, "blog", unit_id, selected.as_posix())

    assert raw.read_bytes() == original
    assert (source_root / "document.md").read_bytes() == document_before


def test_html_conversion_failure_preserves_raw_fallback_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"<html><body><h1>Grounded</h1><p>Readable source survives.</p></body></html>"
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))
    monkeypatch.setattr(sources, "materialize_html", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("converter broke")))

    payload = sources.backup_source(tmp_path, "blog", "b-fallback-123456", "https://example.com/fallback")

    source_root = core.unit_root(tmp_path, "blog", "b-fallback-123456") / "source"
    document = (source_root / "document.md").read_text(encoding="utf-8")
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    assert payload["backup_status"] == "degraded"
    assert payload["parse_chunks"]
    assert payload["materialization"]["converter"] == "fallback"
    assert "[原始 HTML](source.html)" in document
    assert "Markdown conversion unavailable" in document
    assert conversion["status"] == "degraded"
    assert any("converter broke" in warning for warning in conversion["warnings"])


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

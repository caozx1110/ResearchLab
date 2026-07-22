from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest

import research.core as core
import research.sources as sources


_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _source_root(root: Path, kind: str, unit_id: str) -> Path:
    return core.unit_root(root, kind, unit_id) / "source"


def test_html_equation_layout_table_becomes_one_numbered_display_math(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><head><title>Equation paper</title></head><body><article>
    <h1 id="method">Method</h1><p>The objective is</p>
    <table id="eq.loss" class="ltx_equation ltx_eqn_table"><tbody><tr>
      <td></td><td><math alttext="\\mathcal{L}=x_1+y" display="block"></math></td>
      <td></td><td><span class="ltx_tag ltx_tag_equation">(7)</span></td>
    </tr></tbody></table><p>after optimization.</p>
    </article></body></html>"""
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    payload = sources.backup_source(tmp_path, "paper", "p-equation-123456", "https://example.com/equation")

    source_root = _source_root(tmp_path, "paper", "p-equation-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert payload["backup_status"] == "ok"
    assert "\\mathcal{L}=x_1+y" in document
    assert "\\tag{7}" in document
    assert "|  |  |  |  |" not in document
    assert document.count("\\mathcal{L}=x_1+y") == 1


def test_html_complex_table_stays_lossless_and_passive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><head><title>Complex table</title></head><body><article>
    <h1>Results</h1>
    <table id="results" onmouseover="alert(1)">
      <tr><th colspan="2">Training</th><th rowspan="2">Score</th></tr>
      <tr><th>A</th><th>B</th></tr><tr><td>yes</td><td>no</td><td>91</td></tr>
      <tr><td colspan="3"><a href="javascript:alert(2)">unsafe link</a></td></tr>
    </table></article></body></html>"""
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    payload = sources.backup_source(tmp_path, "blog", "b-table-123456", "https://example.com/table")

    source_root = _source_root(tmp_path, "blog", "b-table-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    archive = (source_root / "archive.html").read_text(encoding="utf-8")
    assert payload["backup_status"] == "ok"
    assert "<table" in document and 'colspan="2"' in document and 'rowspan="2"' in document
    assert "onmouseover" not in document and "javascript:" not in document
    assert "onmouseover" not in archive and "javascript:" not in archive
    assert "| Training |" not in document


def test_markdown_frontmatter_code_setext_and_real_images_are_structural(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "article.md"
    image_with_parens = tmp_path / "figure (final).png"
    raw_image = tmp_path / "raw.png"
    image_with_parens.write_bytes(_PNG_BYTES)
    raw_image.write_bytes(_PNG_BYTES)
    selected.write_text(
        """---
title: Original source title
tags: [robotics, evaluation]
---

Visible Setext Heading
======================

![Real figure](<figure (final).png> "Result")

<img src="raw.png" alt="Raw HTML figure" onerror="alert(1)">

```markdown
# This is sample syntax, not a heading
![Example only](missing-in-code.png)
```

Inline sample: `![Not an image](missing-inline.png)`.
""",
        encoding="utf-8",
    )

    payload = sources.backup_source(tmp_path, "blog", "b-markdown-123456", selected.as_posix())

    source_root = _source_root(tmp_path, "blog", "b-markdown-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    assert payload["backup_status"] == "ok"
    assert "<summary>Source front matter</summary>" in document
    assert "title: Original source title" in document
    assert "^source-section-visible-setext-heading" in document
    assert "^source-section-this-is-sample" not in document
    assert "![Example only](missing-in-code.png)" in document
    assert "`![Not an image](missing-inline.png)`" in document
    assert "figure (final).png" not in document and 'src="raw.png"' not in document
    assert "onerror" not in document
    assert document.count("assets/image-") == 2
    assets = list((source_root / "assets").glob("image-*.png"))
    assert len(assets) == 1 and hashlib.sha256(assets[0].read_bytes()).digest() == hashlib.sha256(_PNG_BYTES).digest()
    assert conversion["quality"]["output"]["fenced_code_block_count"] == 1


def test_plain_text_markdown_like_content_is_literal(tmp_path: Path) -> None:
    selected = tmp_path / "notes.txt"
    selected.write_text(
        "# not a heading\n> not a quote\n---\n![not an image](missing.png)\n"
        "```unclosed literal fence\n<script>alert(1)</script>\n",
        encoding="utf-8",
    )

    payload = sources.backup_source(tmp_path, "blog", "b-text-123456", selected.as_posix())

    source_root = _source_root(tmp_path, "blog", "b-text-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert payload["backup_status"] == "ok"
    assert '<pre class="kb-source-plain-text"' in document
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document
    assert "^source-section-not-a-heading" not in document
    assert "![not an image](missing.png)" in document
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    assert conversion["quality"]["output"]["unclosed_fence"] is False
    assert conversion["quality"]["output"]["fenced_code_block_count"] == 0
    assert conversion["quality"]["output"]["image_count"] == 0


def test_unbalanced_markdown_fence_is_degraded_with_format_warning(tmp_path: Path) -> None:
    selected = tmp_path / "broken.md"
    selected.write_text("# Broken example\n\n```python\nprint('still open')\n", encoding="utf-8")

    payload = sources.backup_source(tmp_path, "blog", "b-broken-md-123456", selected.as_posix())

    source_root = _source_root(tmp_path, "blog", "b-broken-md-123456")
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    assert payload["backup_status"] == "degraded"
    assert conversion["quality"]["output"]["unclosed_fence"] is True
    assert any("unclosed fenced code block" in warning for warning in conversion["warnings"])


def test_pdf_materialization_records_common_format_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fitz  # type: ignore

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Format metrics PDF")
    page.insert_text((72, 92), "A readable paragraph on the first page.")
    data = pdf.tobytes()
    pdf.close()
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (data, "application/pdf"))

    payload = sources.backup_source(tmp_path, "paper", "p-pdf-format-123456", "https://example.com/format.pdf")

    conversion = core.load_yaml(
        _source_root(tmp_path, "paper", "p-pdf-format-123456") / "conversion.yaml", default={}
    )
    assert payload["backup_status"] == "ok"
    assert conversion["quality"]["output"]["heading_count"] >= 1
    assert conversion["quality"]["output"]["unclosed_fence"] is False
    assert conversion["quality"]["output"]["malformed_pipe_table_count"] == 0


def test_html_percent_fragment_mathjax_and_dynamic_code_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><head><title>HTML edges</title></head><body><article>
    <h1 id="sec:one">Section One</h1><p><a href="#sec%3Aone">jump</a></p>
    <script type="math/tex; mode=display">x_1+y</script>
    <pre><code class="language-python">print("``` inside")\n# literal code</code></pre>
    </article></body></html>"""
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    payload = sources.backup_source(tmp_path, "blog", "b-html-edge-123456", "https://example.com/edge")

    source_root = _source_root(tmp_path, "blog", "b-html-edge-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    assert payload["backup_status"] == "ok"
    assert "](#^source-section-sec-one)" in document
    assert "x_1+y" in document
    assert "````python" in document and "````\n" in document
    assert "# literal code" in document
    assert conversion["quality"]["output"]["unclosed_fence"] is False


def test_markdown_reference_multiline_html_and_obsidian_images_are_localized(tmp_path: Path) -> None:
    selected = tmp_path / "mixed.md"
    image = tmp_path / "figure.png"
    image.write_bytes(_PNG_BYTES)
    selected.write_text(
        """# Images

![Reference][fig]

[fig]: figure.png "reference title"

<img
  src="figure.png"
  alt="Multiline raw image"
  onload="alert(1)">

![[figure.png|Obsidian image]]

![[figure.png|320x200]]
""",
        encoding="utf-8",
    )

    payload = sources.backup_source(tmp_path, "blog", "b-mixed-images-123456", selected.as_posix())

    source_root = _source_root(tmp_path, "blog", "b-mixed-images-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert payload["backup_status"] == "ok"
    assert "[fig]: assets/image-" in document
    assert 'src="assets/image-' in document
    assert "![Obsidian image](assets/image-" in document
    assert 'width="320"' in document and 'height="200"' in document
    assert "onload" not in document and "figure.png" not in document
    assert len(list((source_root / "assets").glob("image-*.png"))) == 1


def test_pdf_missing_converter_page_is_recovered_from_native_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fitz  # type: ignore
    import pymupdf4llm  # type: ignore

    pdf = fitz.open()
    first = pdf.new_page()
    first.insert_text((72, 72), "Native first page text")
    second = pdf.new_page()
    second.insert_text((72, 72), "Native second page must survive")
    data = pdf.tobytes()
    pdf.close()
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (data, "application/pdf"))
    monkeypatch.setattr(
        pymupdf4llm,
        "to_markdown",
        lambda *args, **kwargs: [
            {"metadata": {"page_number": 1}, "text": "Native first page text", "page_boxes": []}
        ],
    )

    payload = sources.backup_source(tmp_path, "paper", "p-pdf-recovery-123456", "https://example.com/two.pdf")

    source_root = _source_root(tmp_path, "paper", "p-pdf-recovery-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    conversion = core.load_yaml(source_root / "conversion.yaml", default={})
    assert payload["backup_status"] == "degraded"
    assert "## Page 2" in document and "Native second page must survive" in document
    assert conversion["quality"]["output"]["native_text_recovery_pages"] == [2]


def test_arxiv_explicit_version_is_preserved_in_every_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><head><title>Versioned paper</title></head><body>
    <article class="ltx_document"><h1>Paper</h1>
    <p>This is a sufficiently structured versioned paper body with stable evidence text.</p>
    <p>Second paragraph ensures the quality gate sees a complete source.</p>
    <p>Third paragraph preserves the explicitly requested arXiv version.</p></article></body></html>"""
    requested: list[str] = []

    def fake_fetch(url: str, **kwargs):
        requested.append(url)
        return html, "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch)
    payload = sources.backup_source(tmp_path, "paper", "p-versioned-123456", "https://arxiv.org/abs/2603.12263v1")

    assert requested[0] == "https://arxiv.org/html/2603.12263v1"
    assert payload["original_uri"] == "https://arxiv.org/abs/2603.12263v1"
    assert payload["parse_metadata"]["arxiv_id"] == "2603.12263v1"


def test_remote_markdown_and_plain_text_are_archived_and_materialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    markdown_bytes = b"# Remote Markdown\n\nGrounded remote body.\n"
    text_bytes = "café source text\n# literal marker\n".encode("windows-1252")

    def fake_fetch(url: str, **kwargs):
        if url.endswith("readme.md"):
            return markdown_bytes, "text/markdown"
        return text_bytes, "text/plain; charset=windows-1252"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch)
    markdown_payload = sources.backup_source(
        tmp_path, "blog", "b-remote-md-123456", "https://example.com/readme.md"
    )
    text_payload = sources.backup_source(
        tmp_path, "blog", "b-remote-text-123456", "https://example.com/notes.txt"
    )

    markdown_root = _source_root(tmp_path, "blog", "b-remote-md-123456")
    text_root = _source_root(tmp_path, "blog", "b-remote-text-123456")
    assert markdown_payload["backup_status"] == "ok"
    assert (markdown_root / "source.md").read_bytes() == markdown_bytes
    assert "^source-section-remote-markdown" in (markdown_root / "document.md").read_text(encoding="utf-8")
    assert text_payload["backup_status"] == "ok"
    assert (text_root / "source.txt").read_bytes() == text_bytes
    text_document = (text_root / "document.md").read_text(encoding="utf-8")
    assert "café source text" in text_document
    assert "^source-section-literal-marker" not in text_document


def test_html_declared_legacy_charset_is_decoded_without_dropping_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = """<!doctype html><html><head><meta charset="windows-1252"><title>Café</title></head>
    <body><article><h1>Café results</h1><p>Résumé and naïve baseline remain intact.</p></article></body></html>""".encode(
        "windows-1252"
    )
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    payload = sources.backup_source(tmp_path, "blog", "b-charset-123456", "https://example.com/cafe")

    document = (_source_root(tmp_path, "blog", "b-charset-123456") / "document.md").read_text(
        encoding="utf-8"
    )
    assert payload["backup_status"] == "ok"
    assert "Café results" in document and "Résumé" in document and "naïve" in document
    assert payload["parse_metadata"]["source_encoding"] == "windows-1252"


def test_local_archive_name_is_reserved_and_directory_retry_is_immutable(tmp_path: Path) -> None:
    html = tmp_path / "archive.html"
    html.write_text("<html><body><main><h1>Local archive source</h1></main></body></html>", encoding="utf-8")
    html_payload = sources.backup_source(tmp_path, "blog", "b-local-archive-123456", html.as_posix())
    html_root = _source_root(tmp_path, "blog", "b-local-archive-123456")
    assert html_payload["backup_status"] == "ok"
    assert (html_root / "original-archive.html").is_file()
    assert (html_root / "archive.html").is_file()

    directory = tmp_path / "dataset-folder"
    directory.mkdir()
    (directory / "card.md").write_text("version one\n", encoding="utf-8")
    sources.backup_source(tmp_path, "dataset", "d-dir-123456", directory.as_posix())
    (directory / "card.md").write_text("version two\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable source directory collision"):
        sources.backup_source(tmp_path, "dataset", "d-dir-123456", directory.as_posix())


def test_local_legacy_charset_html_is_decoded_from_meta(tmp_path: Path) -> None:
    selected = tmp_path / "legacy.html"
    selected.write_bytes(
        """<!doctype html><html><head><meta charset="windows-1252"><title>Café</title></head>
        <body><main><h1>Résumé</h1><p>Local naïve baseline remains readable.</p></main></body></html>""".encode(
            "windows-1252"
        )
    )

    payload = sources.backup_source(
        tmp_path, "blog", "b-local-charset-123456", selected.as_posix()
    )

    source_root = _source_root(tmp_path, "blog", "b-local-charset-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert payload["backup_status"] == "ok"
    assert payload["parse_metadata"]["source_encoding"] == "windows-1252"
    assert "Résumé" in document and "naïve" in document


def test_materialization_collision_does_not_publish_partial_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit_id = "b-atomic-123456"
    source_root = _source_root(tmp_path, "blog", unit_id)
    source_root.mkdir(parents=True)
    (source_root / "document.md").write_text("human-owned collision\n", encoding="utf-8")
    html = b"""<!doctype html><html><body><main><h1>Atomic source</h1>
    <p>The converter must not leave an archive or map behind after collision.</p>
    <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB">
    </main></body></html>"""
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    with pytest.raises(ValueError, match="immutable source bundle collision: document.md"):
        sources.backup_source(tmp_path, "blog", unit_id, "https://example.com/atomic")

    assert (source_root / "document.md").read_text(encoding="utf-8") == "human-owned collision\n"
    assert (source_root / "source.html").read_bytes() == html
    assert not (source_root / "archive.html").exists()
    assert not (source_root / "source-map.yaml").exists()
    assert not (source_root / "conversion.yaml").exists()
    assert not (source_root / "assets").exists()


def test_html_control_obfuscated_active_urls_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = b"""<!doctype html><html><body><main><h1>Passive links</h1>
    <p><a href="java&#x09;script:alert(1)">paragraph link</a></p>
    <table><tr><th colspan="2">Unsafe</th></tr><tr>
    <td><a href="java&#x0a;script:alert(2)">table link</a></td><td>value</td>
    </tr></table></main></body></html>"""
    monkeypatch.setattr(sources, "fetch_url", lambda url, **kwargs: (html, "text/html"))

    payload = sources.backup_source(
        tmp_path, "blog", "b-passive-url-123456", "https://example.com/passive"
    )

    source_root = _source_root(tmp_path, "blog", "b-passive-url-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    archive = (source_root / "archive.html").read_text(encoding="utf-8")
    assert payload["backup_status"] == "ok"
    assert "javascript:" not in re.sub(r"[\x00-\x20\x7f]+", "", document).lower()
    assert "javascript:" not in re.sub(r"[\x00-\x20\x7f]+", "", archive).lower()


def test_markdown_raw_html_is_passive_and_multiline_code_span_is_literal(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "active.md"
    image = tmp_path / "x.png"
    image.write_bytes(_PNG_BYTES)
    selected.write_text(
        """# Safe reading

`<img
src="x.png">`

<iframe src="https://attacker.example/tracker"></iframe>
<a href="java&#x09;script:alert(1)" onclick="alert(2)">go</a>
<form action="https://attacker.example/submit"><button formaction="/other">send</button></form>
""",
        encoding="utf-8",
    )

    payload = sources.backup_source(
        tmp_path, "blog", "b-passive-markdown-123456", selected.as_posix()
    )

    source_root = _source_root(tmp_path, "blog", "b-passive-markdown-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    normalized = re.sub(r"[\x00-\x20\x7f]+", "", document).lower()
    assert payload["backup_status"] == "ok"
    assert '`<img\nsrc="x.png">`' in document
    assert "iframe" not in document.lower()
    assert "javascript:" not in normalized
    assert "onclick" not in document.lower()
    assert "action=" not in document.lower() and "formaction=" not in document.lower()
    assert not (source_root / "assets").exists()


def test_frontmatter_block_scalar_cannot_capture_heading_block_id(tmp_path: Path) -> None:
    selected = tmp_path / "frontmatter.md"
    selected.write_text(
        """---
description: |
  # sample heading
---

# Real heading

Grounded body.
""",
        encoding="utf-8",
    )

    sources.backup_source(
        tmp_path, "blog", "b-frontmatter-block-123456", selected.as_posix()
    )

    source_root = _source_root(tmp_path, "blog", "b-frontmatter-block-123456")
    document = (source_root / "document.md").read_text(encoding="utf-8")
    assert document.index("</details>") < document.index("# Real heading")
    assert document.index("# Real heading") < document.index("^source-section-real-heading")
    assert document.count("^source-section-real-heading") == 1


def test_unchanged_git_directory_retry_ignores_vcs_metadata(tmp_path: Path) -> None:
    directory = tmp_path / "repo"
    (directory / ".git").mkdir(parents=True)
    (directory / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (directory / ".gitmodules").write_text("[submodule]\n", encoding="utf-8")
    (directory / "README.md").write_text("# Dataset card\n", encoding="utf-8")

    first = sources.backup_source(
        tmp_path, "dataset", "d-git-directory-123456", directory.as_posix()
    )
    second = sources.backup_source(
        tmp_path, "dataset", "d-git-directory-123456", directory.as_posix()
    )

    archived = _source_root(tmp_path, "dataset", "d-git-directory-123456") / "repo"
    assert first["backup_status"] == "ok" and second["backup_status"] == "ok"
    assert (archived / "README.md").is_file()
    assert not (archived / ".git").exists() and not (archived / ".gitmodules").exists()


def test_xml_declaration_encoding_and_html_decode_warning_are_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    xml = '<?xml version="1.0" encoding="shift_jis"?><doc>日本語</doc>'.encode(
        "shift_jis"
    )
    legacy_html = "<html><body><main><h1>Café</h1><p>Résumé body.</p></main></body></html>".encode(
        "windows-1252"
    )

    def fake_fetch(url: str, **kwargs):
        if url.endswith("data.xml"):
            return xml, "application/xml"
        return legacy_html, "text/html"

    monkeypatch.setattr(sources, "fetch_url", fake_fetch)
    xml_payload = sources.backup_source(
        tmp_path, "dataset", "d-xml-encoding-123456", "https://example.com/data.xml"
    )
    html_payload = sources.backup_source(
        tmp_path, "blog", "b-html-warning-123456", "https://example.com/legacy"
    )

    xml_document = (
        _source_root(tmp_path, "dataset", "d-xml-encoding-123456") / "document.md"
    ).read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert xml_payload["parse_metadata"]["source_encoding"] == "shift_jis"
    assert "日本語" in xml_document
    assert html_payload["backup_status"] == "degraded"
    assert "decoded losslessly as latin-1" in captured.err

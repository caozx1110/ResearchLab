from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "skills" / "research-capture" / "scripts" / "capture.py"
SPEC = importlib.util.spec_from_file_location("research_capture_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


def test_exact_bytes_are_immutable_and_new_bytes_create_revisions(tmp_path: Path) -> None:
    original = b"---\nid: untrusted\n---\n\n# Original\n\n=not a formula\n"
    first = capture.capture_bytes(tmp_path, "src-markdown", "markdown", original, filename="note.md")

    assert first.stage == "evidence-ready"
    assert first.health == "ok"
    assert first.raw_path.read_bytes() == original
    assert first.source_map_path is not None
    manifest = capture.inspect_manifest(first.manifest_path)
    assert not {"claim", "summary", "assessment", "decision"}.intersection(manifest)

    retry = capture.capture_bytes(tmp_path, "src-markdown", "markdown", original, filename="note.md")
    assert retry.same_bytes is True
    assert retry.revision_id == first.revision_id
    assert retry.raw_path.read_bytes() == original

    first.raw_path.write_bytes(b"tampered revision")
    with pytest.raises(capture.ImmutableRevisionError):
        capture.capture_bytes(tmp_path, "src-markdown", "markdown", original, filename="note.md")
    first.raw_path.write_bytes(original)

    changed = capture.capture_bytes(
        tmp_path,
        "src-markdown",
        "markdown",
        original + b"\nA second revision.\n",
        filename="note.md",
    )
    assert changed.revision_id != first.revision_id
    assert first.raw_path.read_bytes() == original
    revisions = capture.inspect_manifest(changed.manifest_path)["revisions"]
    assert len(revisions) == 2
    assert {item["currency"] for item in revisions} == {"current", "stale"}
    current_index = (tmp_path / "Sources" / "src-markdown" / "index.md").read_text(encoding="utf-8")
    assert changed.revision_id in current_index


def test_selected_file_symlink_is_rejected_without_copying_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"private bytes")
    selected = tmp_path / "selected.md"
    selected.symlink_to(outside)

    with pytest.raises(capture.UnsafeInputError):
        capture.capture_file(tmp_path / "vault", "src-symlink", "markdown", selected)
    assert not (tmp_path / "vault" / "Sources").exists()


def test_html_reader_is_passive_and_maps_visible_blocks(tmp_path: Path) -> None:
    html_bytes = (
        b"<html><body><script>raise_secret()</script><main>"
        b"<h1 id='intro'>Readable source</h1><p>Grounded text.</p>"
        b"<a href='javascript:alert(1)'>safe visible label</a></main></body></html>"
    )
    result = capture.capture_bytes(tmp_path, "src-html", "web", html_bytes, filename="page.html")

    reader = result.reader_path.read_text(encoding="utf-8") if result.reader_path else ""
    assert "Readable source" in reader
    assert "Grounded text." in reader
    assert "raise_secret" not in reader
    assert result.stage == "evidence-ready"
    assert result.source_map_path is not None
    source_map = json.loads(result.source_map_path.read_text(encoding="utf-8"))
    assert source_map["raw_sha256"] == hashlib.sha256(html_bytes).hexdigest()
    assert any(block["locator"].get("fragment") == "intro" for block in source_map["blocks"])


def test_dot_md_url_skips_defuddle_and_preserves_markdown_bytes(tmp_path: Path) -> None:
    called = False

    def converter(_payload: bytes, **_context: object) -> object:
        nonlocal called
        called = True
        return {"markdown": "wrong"}

    raw = b"# Direct Markdown\n\n<script>not executed</script>\n"
    result = capture.capture_bytes(
        tmp_path,
        "src-direct-md",
        "web-html",
        raw,
        filename="README.md",
        requested_uri="https://example.test/README.md",
        adapter=capture.DefuddleAdapter(converter),
    )
    assert called is False
    assert result.source_kind == "markdown"
    assert result.raw_path.read_bytes() == raw
    reader = result.reader_path.read_text(encoding="utf-8") if result.reader_path else ""
    assert "&lt;script&gt;not executed&lt;/script&gt;" in reader


def test_csv_is_rendered_as_data_and_never_evaluated(tmp_path: Path) -> None:
    csv_bytes = b"name,value\nalpha,=1+1\nbeta,@cmd\n"
    result = capture.capture_bytes(tmp_path, "src-csv", "csv", csv_bytes, filename="rows.csv")

    assert result.stage == "evidence-ready"
    reader = result.reader_path.read_text(encoding="utf-8") if result.reader_path else ""
    assert "```csv" in reader
    assert "=1+1" in reader and "@cmd" in reader
    assert result.source_map_path is not None
    source_map = json.loads(result.source_map_path.read_text(encoding="utf-8"))
    assert source_map["blocks"][1]["locator"] == {"type": "csv", "file": "rows.csv", "row": 2}


def test_repo_tree_is_exact_passive_and_rejects_symlinks(tmp_path: Path) -> None:
    selected = tmp_path / "repo"
    (selected / "docs").mkdir(parents=True)
    (selected / "docs" / "README.md").write_bytes(b"# Read me\n")
    (selected / "run.py").write_bytes(b"raise RuntimeError('must not execute')\n")

    result = capture.capture_tree(
        tmp_path / "vault",
        "src-repo",
        "repo",
        selected,
        commit_identity="commit:abc123",
    )
    assert result.stage == "evidence-ready"
    assert (result.raw_path / "docs" / "README.md").read_bytes() == b"# Read me\n"
    reader = result.reader_path.read_text(encoding="utf-8") if result.reader_path else ""
    assert "must not execute" not in reader
    manifest = capture.inspect_manifest(result.manifest_path)
    revision = manifest["revisions"][0]
    assert revision["raw"]["entries"][1]["path"] == "run.py"
    unsafe = selected / "link"
    unsafe.symlink_to(selected / "run.py")
    with pytest.raises(capture.UnsafeInputError):
        capture.capture_tree(tmp_path / "other-vault", "src-repo-2", "repo", selected)


@pytest.mark.parametrize("source_kind", ["pdf", "office", "odf", "rtf", "epub", "binary"])
def test_unsupported_optional_formats_are_stored_unparsed(tmp_path: Path, source_kind: str) -> None:
    result = capture.capture_bytes(
        tmp_path,
        f"src-{source_kind}",
        source_kind,
        b"opaque source bytes",
        filename=f"source.{source_kind}",
    )

    assert result.stage == "captured"
    assert result.health == "degraded"
    assert result.reader_path is None
    assert "stored-unparsed" in result.diagnostics
    assert result.raw_path.read_bytes() == b"opaque source bytes"


def test_pdf_adapter_failure_and_missing_ocr_keep_raw_revision(tmp_path: Path) -> None:
    def broken(_payload: bytes, **_context: object) -> object:
        raise RuntimeError("converter unavailable")

    result = capture.capture_bytes(
        tmp_path,
        "src-pdf",
        "pdf",
        b"%PDF exact bytes",
        filename="source.pdf",
        adapter=capture.PdfAdapter(broken),
        ocr_available=False,
    )
    assert result.raw_path.read_bytes() == b"%PDF exact bytes"
    assert result.stage == "captured"
    assert result.health == "degraded"
    assert any("converter unavailable" in item for item in result.diagnostics)
    assert any("OCR adapter unavailable" in item for item in result.diagnostics)


def test_adapter_without_map_is_reader_ready_but_not_evidence_ready(tmp_path: Path) -> None:
    adapter = capture.AnyDocAdapter(
        lambda payload, **_context: {
            "markdown": "Candidate text from an optional converter.\n",
            "diagnostics": ["layout may be incomplete"],
        }
    )
    result = capture.capture_bytes(
        tmp_path,
        "src-office",
        "office",
        b"office exact bytes",
        filename="source.docx",
        adapter=adapter,
    )

    assert result.stage == "reader-ready"
    assert result.health == "degraded"
    assert result.source_map_path is None
    assert result.reader_path is not None
    assert "missing-source-map" in result.diagnostics


def test_optional_adapter_receives_published_exact_bytes_and_can_bind_a_map(tmp_path: Path) -> None:
    exact = b"Adapter reader line."
    observed: dict[str, object] = {}

    def converter(payload: bytes, **context: object) -> object:
        observed["payload"] = payload
        raw_paths = context["raw_paths"]
        assert isinstance(raw_paths, dict)
        raw_path = tmp_path / next(iter(raw_paths.values()))
        observed["published"] = raw_path.exists() and raw_path.read_bytes() == exact
        return {
            "markdown": "Adapter reader line.\n",
            "source_map": {
                "blocks": [
                    {
                        "quote": "Adapter reader line.",
                        "reader_line_start": 1,
                        "reader_line_end": 1,
                        "locator": {"type": "byte-range", "byte_start": 0, "byte_end": len(exact)},
                    }
                ]
            },
        }

    result = capture.capture_bytes(
        tmp_path,
        "src-adapter",
        "office",
        exact,
        filename="source.docx",
        adapter=capture.AnyDocAdapter(converter),
    )

    assert observed == {"payload": exact, "published": True}
    assert result.stage == "evidence-ready"
    assert result.health == "ok"


def test_invalid_adapter_map_is_not_published_as_evidence(tmp_path: Path) -> None:
    adapter = capture.AnyDocAdapter(
        lambda payload, **_context: {
            "markdown": "Candidate text.\n",
            "source_map": {"blocks": [{"quote": "not present", "reader_line_start": 1, "reader_line_end": 1}]},
        }
    )
    result = capture.capture_bytes(
        tmp_path,
        "src-odf",
        "odf",
        b"odf exact bytes",
        filename="source.odt",
        adapter=adapter,
    )

    assert result.stage == "reader-ready"
    assert result.health == "degraded"
    assert result.source_map_path is None
    assert any("invalid source map" in item for item in result.diagnostics)


def test_user_edited_reader_is_preserved_and_marked_stale(tmp_path: Path) -> None:
    first = capture.capture_bytes(tmp_path, "src-reader", "markdown", b"# First\n", filename="first.md")
    assert first.reader_path is not None
    first.reader_path.write_text("# User-owned reader edit\n", encoding="utf-8")

    second = capture.capture_bytes(tmp_path, "src-reader", "markdown", b"# Second\n", filename="second.md")
    assert second.reader_modified is True
    assert second.health == "stale"
    assert second.reader_path is not None
    assert second.reader_path.read_text(encoding="utf-8") == "# User-owned reader edit\n"
    normalized = tmp_path / "Sources" / "src-reader" / ".source" / "revisions" / second.revision_id / "normalized.md"
    assert "# Second" in normalized.read_text(encoding="utf-8")


def test_dataset_selected_members_are_explicit_and_immutable(tmp_path: Path) -> None:
    result = capture.capture_dataset(
        tmp_path,
        "src-dataset",
        {"data/sample.csv": b"id,value\n1,2\n", "README.md": b"# Dataset\n"},
        immutable_identity="dataset:fixed-v1",
    )
    assert result.stage == "evidence-ready"
    assert result.health == "ok"
    manifest = capture.inspect_manifest(result.manifest_path)
    entries = manifest["revisions"][0]["raw"]["entries"]
    assert [entry["path"] for entry in entries] == ["README.md", "data/sample.csv"]

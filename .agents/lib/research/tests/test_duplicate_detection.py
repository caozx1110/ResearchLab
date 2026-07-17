from __future__ import annotations

from pathlib import Path

from research.common import write_yaml_if_changed
from research.core import detect_duplicate, ensure_workspace, record_path


def _write_record(root: Path, record: dict) -> None:
    write_yaml_if_changed(record_path(root, record["kind"], record["id"]), record)


def test_detect_duplicate_by_url(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        {
            "id": "p-url-123456",
            "kind": "paper",
            "title": "URL Paper",
            "source": {"original_uri": "https://arxiv.org/abs/2506.01844", "file_hash": ""},
        },
    )

    duplicate = detect_duplicate(tmp_path, "paper", "https://arxiv.org/pdf/2506.01844.pdf")

    assert duplicate is not None
    assert duplicate["id"] == "p-url-123456"


def test_detect_duplicate_by_file_hash(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"same file")
    other = tmp_path / "other.pdf"
    other.write_bytes(b"same file")
    _write_record(
        tmp_path,
        {
                "id": "p-file-123456",
                "kind": "paper",
                "title": "File Paper",
                "source": {
                    "original_uri": source.as_posix(),
                    "file_hash": "af4d04be4d6d340894228fa7e72531980ee694ff02fd83bd9140ba9b0c449314",
                },
            },
        )

    duplicate = detect_duplicate(tmp_path, "paper", other.as_posix())

    assert duplicate is not None
    assert duplicate["id"] == "p-file-123456"


def test_detect_duplicate_by_arxiv_id_in_title(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        {
            "id": "p-arxiv-123456",
            "kind": "paper",
            "title": "A Study 2506.01844v2",
            "source": {"original_uri": "", "file_hash": ""},
        },
    )

    duplicate = detect_duplicate(tmp_path, "paper", "https://arxiv.org/abs/2506.01844v2", title="anything")

    assert duplicate is not None
    assert duplicate["id"] == "p-arxiv-123456"


def test_detect_duplicate_by_normalized_title(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        {
            "id": "p-title-123456",
            "kind": "paper",
            "title": "A  Robust, Vision-Language Action Model!",
            "source": {"original_uri": "", "file_hash": ""},
        },
    )

    duplicate = detect_duplicate(tmp_path, "paper", "https://example.com/source", title="A robust vision language action model")

    assert duplicate is not None
    assert duplicate["id"] == "p-title-123456"


def test_detect_duplicate_returns_none_for_distinct_source_and_title(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        {
            "id": "p-existing-123456",
            "kind": "paper",
            "title": "Existing Paper",
            "source": {"original_uri": "https://example.com/existing", "file_hash": ""},
        },
    )

    duplicate = detect_duplicate(tmp_path, "paper", "https://example.com/new", title="New Paper")

    assert duplicate is None

from __future__ import annotations

import importlib.util
import os
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "skills" / "research-capture" / "scripts" / "capture.py"
SPEC = importlib.util.spec_from_file_location("research_capture_v2_p1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


def _tree_snapshot(root: Path) -> list[tuple[str, int, bytes | None]]:
    snapshot: list[tuple[str, int, bytes | None]] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
        snapshot.append((relative, info.st_mode, data))
    return snapshot


@pytest.mark.parametrize(
    ("marker", "is_directory"),
    [
        ("kb", True),
        ("record.yaml", False),
        ("config/workspace-layout.yaml", False),
        ("obsidian/managed", True),
    ],
)
def test_legacy_workspace_stops_before_any_capture_write(
    tmp_path: Path,
    marker: str,
    is_directory: bool,
) -> None:
    vault_root = tmp_path / "vault"
    marker_path = vault_root / marker
    if is_directory:
        marker_path.mkdir(parents=True)
        (marker_path / "sentinel").write_bytes(b"legacy bytes")
    else:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_bytes(b"legacy bytes")
    before = _tree_snapshot(vault_root)

    with pytest.raises(capture.LegacyWorkspaceError):
        capture.capture_bytes(vault_root, "src-legacy", "markdown", b"# Must not write\n", filename="source.md")

    assert _tree_snapshot(vault_root) == before
    assert not (vault_root / "Sources").exists()


def test_reactivating_old_bytes_updates_currency_reader_index_and_manifest(tmp_path: Path) -> None:
    first = capture.capture_bytes(tmp_path, "src-cycle", "markdown", b"# Revision A\n", filename="source.md")
    second = capture.capture_bytes(tmp_path, "src-cycle", "markdown", b"# Revision B\n", filename="source.md")
    third = capture.capture_bytes(tmp_path, "src-cycle", "markdown", b"# Revision A\n", filename="source.md")

    assert third.same_bytes is True
    assert third.revision_id == first.revision_id
    assert third.revision_id != second.revision_id
    manifest = capture.inspect_manifest(third.manifest_path)
    assert manifest["current_revision_id"] == first.revision_id
    currencies = {item["revision_id"]: item["currency"] for item in manifest["revisions"]}
    assert currencies == {first.revision_id: "current", second.revision_id: "stale"}
    assert third.reader_path is not None
    assert "Revision A" in third.reader_path.read_text(encoding="utf-8")
    assert "Revision B" not in third.reader_path.read_text(encoding="utf-8")
    index_text = third.index_path.read_text(encoding="utf-8")
    assert first.revision_id in index_text
    assert second.revision_id not in index_text
    assert manifest["current_reader_sha256"] == capture.sha256_bytes(third.reader_path.read_bytes())
    assert manifest["current_index_sha256"] == capture.sha256_bytes(third.index_path.read_bytes())


def test_concurrent_different_bytes_keep_both_manifest_revisions(tmp_path: Path) -> None:
    condition = threading.Condition()
    entered = 0

    def converter(payload: bytes, **_context: object) -> object:
        nonlocal entered
        with condition:
            entered += 1
            condition.notify_all()
            condition.wait_for(lambda: entered >= 2, timeout=0.5)
        text = payload.decode("utf-8")
        return {
            "markdown": text,
            "source_map": {
                "blocks": [
                    {
                        "quote": text.strip(),
                        "reader_line_start": 1,
                        "reader_line_end": 1,
                        "locator": {"type": "byte-range", "byte_start": 0, "byte_end": len(payload.rstrip(b"\n"))},
                    }
                ]
            },
        }

    adapter = capture.AnyDocAdapter(converter)

    def ingest(data: bytes) -> capture.CaptureResult:
        return capture.capture_bytes(
            tmp_path,
            "src-concurrent",
            "office",
            data,
            filename="source.docx",
            adapter=adapter,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest, b"Revision Alpha\n"), executor.submit(ingest, b"Revision Beta\n")]
        results = [future.result(timeout=5) for future in futures]

    manifest = capture.inspect_manifest(results[0].manifest_path)
    assert {item["revision_id"] for item in manifest["revisions"]} == {result.revision_id for result in results}
    assert sum(item["currency"] == "current" for item in manifest["revisions"]) == 1
    current = next(item for item in manifest["revisions"] if item["currency"] == "current")
    reader_path = tmp_path / current["processing"]["reader_path"]
    assert manifest["current_revision_id"] == current["revision_id"]
    assert manifest["current_reader_sha256"] == capture.sha256_bytes(reader_path.read_bytes())


def test_unreplayable_pdf_locator_cannot_become_evidence_ready(tmp_path: Path) -> None:
    adapter = capture.PdfAdapter(
        lambda _payload, **_context: {
            "markdown": "Invented page text.\n",
            "source_map": {
                "blocks": [
                    {
                        "quote": "Invented page text.",
                        "reader_line_start": 1,
                        "reader_line_end": 1,
                        "locator": {"type": "pdf", "page": 999999},
                    }
                ]
            },
        }
    )

    result = capture.capture_bytes(
        tmp_path,
        "src-fake-pdf",
        "pdf",
        b"not a valid PDF",
        filename="source.pdf",
        adapter=adapter,
    )

    assert result.stage == "reader-ready"
    assert result.health == "degraded"
    assert result.source_map_path is None
    assert any("cannot be replayed" in diagnostic for diagnostic in result.diagnostics)


def test_object_lock_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    hidden_root = tmp_path / "Sources" / "src-lock" / ".source"
    hidden_root.mkdir(parents=True)
    outside = tmp_path / "outside.lock"
    outside.write_bytes(b"outside bytes")
    (hidden_root / "capture.lock").symlink_to(outside)

    with pytest.raises(capture.UnsafeInputError):
        capture.capture_bytes(tmp_path, "src-lock", "markdown", b"# Locked\n", filename="source.md")

    assert outside.read_bytes() == b"outside bytes"
    assert not (hidden_root / "manifest.json").exists()
    assert not (hidden_root / "revisions").exists()


def test_failed_manifest_commit_rolls_back_visible_capture_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = capture.capture_bytes(tmp_path, "src-rollback", "markdown", b"# Before\n", filename="source.md")
    assert first.reader_path is not None
    before_manifest = first.manifest_path.read_bytes()
    before_reader = first.reader_path.read_bytes()
    before_index = first.index_path.read_bytes()
    real_replace = capture.os.replace
    failed = False

    def fail_manifest_once(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal failed
        if Path(target).name == "manifest.json" and not failed:
            failed = True
            raise OSError("simulated manifest replace failure")
        real_replace(source, target)

    monkeypatch.setattr(capture.os, "replace", fail_manifest_once)

    with pytest.raises(OSError, match="simulated manifest replace failure"):
        capture.capture_bytes(tmp_path, "src-rollback", "markdown", b"# After\n", filename="source.md")

    assert first.manifest_path.read_bytes() == before_manifest
    assert first.reader_path.read_bytes() == before_reader
    assert first.index_path.read_bytes() == before_index
    assert not (tmp_path / "Sources" / "src-rollback" / ".source" / "transaction.json").exists()

    retried = capture.capture_bytes(tmp_path, "src-rollback", "markdown", b"# After\n", filename="source.md")
    manifest = capture.inspect_manifest(retried.manifest_path)
    assert retried.same_bytes is True
    assert len(manifest["revisions"]) == 2
    assert manifest["current_revision_id"] == retried.revision_id
    assert retried.reader_path is not None
    assert b"# After" in retried.reader_path.read_bytes()


def test_completed_transaction_with_leftover_journal_recovers_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture.capture_bytes(tmp_path, "src-recovery", "markdown", b"# Before\n", filename="source.md")
    real_remove = capture._remove_transaction_journal

    def interrupt_after_commit(_journal_path: Path) -> None:
        raise OSError("simulated interruption before journal cleanup")

    monkeypatch.setattr(capture, "_remove_transaction_journal", interrupt_after_commit)
    with pytest.raises(OSError, match="simulated interruption"):
        capture.capture_bytes(tmp_path, "src-recovery", "markdown", b"# After\n", filename="source.md")

    journal_path = tmp_path / "Sources" / "src-recovery" / ".source" / "transaction.json"
    assert journal_path.is_file()
    monkeypatch.setattr(capture, "_remove_transaction_journal", real_remove)

    recovered = capture.capture_bytes(tmp_path, "src-recovery", "markdown", b"# After\n", filename="source.md")
    assert recovered.same_bytes is True
    assert not journal_path.exists()
    assert recovered.reader_path is not None
    assert b"# After" in recovered.reader_path.read_bytes()
    manifest = capture.inspect_manifest(recovered.manifest_path)
    assert manifest["current_revision_id"] == recovered.revision_id
    assert sum(item["currency"] == "current" for item in manifest["revisions"]) == 1

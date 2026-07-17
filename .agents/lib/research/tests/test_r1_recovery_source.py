from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

import research.journal as journal
import research.sources as sources
from research.git_ops import (
    checkpoint_and_report,
    dirty_kb_paths,
    ensure_kb_git_repo,
    git_checkpoint,
)
from research.common import append_program_reporting_event, exclusive_file_lock, program_reporting_events_path
from research.confirm import write_record
from research.journal import abort_op, begin_op, journaled_op, load_op, operation_lock_path
from research.records import default_record
from research.yaml_io import load_yaml, write_yaml_if_changed


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_intake_module():
    script = _project_root() / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("r1_source_intake_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configure_kb_git(root: Path) -> None:
    ensure_kb_git_repo(root, create_initial_commit=False)
    subprocess.run(["git", "-C", str(root / "kb"), "config", "user.name", "R1 Tests"], check=True)
    subprocess.run(["git", "-C", str(root / "kb"), "config", "user.email", "r1@example.com"], check=True)
    git_checkpoint(
        root,
        "initial kb state",
        auto_init=False,
        target_paths=dirty_kb_paths(root),
    )


def test_checkpoint_rejects_missing_empty_and_broad_scopes(tmp_path: Path) -> None:
    ensure_kb_git_repo(tmp_path, create_initial_commit=False)

    for targets in (None, [], [""], [tmp_path / "kb"]):
        with pytest.raises(SystemExit, match="Checkpoint"):
            git_checkpoint(tmp_path, "must be scoped", auto_init=False, target_paths=targets)

    with pytest.raises(SystemExit, match="target_paths"):
        checkpoint_and_report(tmp_path, trigger="milestone", message="must be scoped")


def test_scoped_checkpoint_leaves_unrelated_tracked_and_untracked_drafts_dirty(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "units" / "papers" / "p-target" / "record.yaml"
    tracked_draft = tmp_path / "kb" / "notes" / "tracked.md"
    target.parent.mkdir(parents=True)
    tracked_draft.parent.mkdir(parents=True)
    target.write_text("target: original\n", encoding="utf-8")
    tracked_draft.write_text("tracked: original\n", encoding="utf-8")
    git_checkpoint(
        tmp_path,
        "seed scoped files",
        auto_init=False,
        target_paths=[target, tracked_draft],
    )

    target.write_text("target: changed\n", encoding="utf-8")
    tracked_draft.write_text("tracked: user draft\n", encoding="utf-8")
    untracked_draft = tmp_path / "kb" / "notes" / "untracked.md"
    untracked_draft.write_text("untracked draft\n", encoding="utf-8")

    result = git_checkpoint(
        tmp_path,
        "scoped checkpoint",
        auto_init=False,
        target_paths=[target],
    )

    assert result["files"] == ["units/papers/p-target/record.yaml"]
    status = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert " M notes/tracked.md" in status
    assert "?? notes/untracked.md" in status
    assert "p-target/record.yaml" not in status


def test_journaled_exception_restores_all_before_bytes_modes_and_removes_new_file(tmp_path: Path) -> None:
    first = tmp_path / "kb" / "notes" / "first.md"
    second = tmp_path / "kb" / "notes" / "second.md"
    created = tmp_path / "kb" / "notes" / "created.md"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first before\n")
    second.write_bytes(b"second before\n")
    os.chmod(first, 0o600)
    os.chmod(second, 0o640)

    with pytest.raises(RuntimeError, match="simulated second-file failure"):
        with journaled_op(tmp_path, "two-file-failure", [first, second, created]):
            first.write_bytes(b"first after\n")
            second.write_bytes(b"second after\n")
            created.write_bytes(b"new file\n")
            os.chmod(first, 0o644)
            os.chmod(second, 0o644)
            raise RuntimeError("simulated second-file failure")

    assert first.read_bytes() == b"first before\n"
    assert second.read_bytes() == b"second before\n"
    assert first.stat().st_mode & 0o777 == 0o600
    assert second.stat().st_mode & 0o777 == 0o640
    assert not created.exists()
    entries = sorted((tmp_path / "kb" / ".journal").glob("*.yaml"))
    entry = load_op(tmp_path, entries[-1].stem)
    assert entry["state"] == "abort"
    assert entry["before_snapshots"]["notes/created.md"]["kind"] == "absent"


def test_two_hundred_concurrent_reporting_appends_are_lossless_and_parseable(tmp_path: Path) -> None:
    program_id = "p-concurrent-reporting"

    def append(index: int) -> None:
        append_program_reporting_event(
            tmp_path,
            program_id,
            {
                "event_type": "test",
                "title": f"event-{index:03d}",
                "summary": f"summary-{index:03d}",
                "tags": ["r1"],
            },
            generated_by="r1-test",
        )

    with ThreadPoolExecutor(max_workers=24) as executor:
        list(executor.map(append, range(200)))

    path = program_reporting_events_path(tmp_path, program_id)
    payload = load_yaml(path)
    assert isinstance(payload, dict)
    items = payload["items"]
    assert len(items) == 200
    assert {item["title"] for item in items} == {f"event-{index:03d}" for index in range(200)}
    assert ".journal/" in (tmp_path / "kb" / ".gitignore").read_text(encoding="utf-8")


def test_failed_snapshot_restore_is_reported_and_never_marked_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "restore-failure.md"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    op_id = begin_op(tmp_path, "restore-failure", [target])
    target.write_text("after\n", encoding="utf-8")

    def fail_restore(*args, **kwargs):
        raise OSError("simulated restore I/O failure")

    monkeypatch.setattr(journal, "_restore_target", fail_restore)
    with pytest.raises(RuntimeError, match="simulated restore I/O failure"):
        abort_op(tmp_path, op_id, restore=True, error="original operation failed")

    entry = load_op(tmp_path, op_id)
    assert entry["state"] == "abort_failed"
    assert "simulated restore I/O failure" in entry["restoration_error"]
    assert entry["operation_error"] == "original operation failed"


def test_same_thread_outer_transaction_can_reenter_write_record_lock(tmp_path: Path) -> None:
    record = default_record("blog", title="Nested Transaction", maturity="lightweight")
    record["id"] = "b-nested-transaction"
    path = tmp_path / "kb" / "units" / "blogs" / record["id"] / "record.yaml"
    lock_path = operation_lock_path(tmp_path, path)

    with exclusive_file_lock(lock_path):
        with journaled_op(tmp_path, "outer-governance-mutation", [path]):
            written = write_record(tmp_path, record)

    assert written == path
    assert load_yaml(path)["revision"] == 1


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        (".html", "<html><body><h1 id='intro'>Intro</h1><p>HTML body.</p></body></html>"),
        (".md", "# Motivation\n\nMarkdown body.\n\n## Method\n\nSecond section."),
        (".txt", "First paragraph.\n\nSecond paragraph."),
    ],
)
def test_local_text_sources_write_nonempty_unit_id_parse_cache(
    tmp_path: Path,
    suffix: str,
    content: str,
) -> None:
    source = tmp_path / f"source{suffix}"
    source.write_text(content, encoding="utf-8")
    unit_id = f"b-local-{suffix.lstrip('.')}"

    payload = sources.backup_source(tmp_path, "blog", unit_id, source.as_posix())
    cache_path = sources.write_parse_cache(
        tmp_path / "kb" / "units" / "blogs" / unit_id,
        unit_id,
        payload,
    )

    assert payload["backup_status"] == "ok"
    assert payload["parse_chunks"]
    assert all(str(chunk["text"]).strip() for chunk in payload["parse_chunks"])
    assert cache_path is not None
    cache = load_yaml(cache_path)
    assert cache["unit_id"] == unit_id
    assert "paper_id" not in cache


def test_failed_url_creates_only_retryable_staging_then_same_url_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    url = "https://example.com/retryable-blog"
    available = False

    def fake_fetch_url(requested: str, **kwargs):
        if not available:
            raise RuntimeError("network unavailable")
        return (
            b"<html><head><title>Retryable Blog</title></head><body><h1>Intro</h1><p>Recovered source.</p></body></html>",
            "text/html",
        )

    monkeypatch.setattr(sources, "fetch_url", fake_fetch_url)
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *args, **kwargs: {"status": "disabled"})
    argv = [
        "intake.py",
        "--root",
        str(tmp_path),
        "add",
        "--kind",
        "blog",
        "--source",
        url,
        "--title",
        "Retryable Blog",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit, match="retry is safe"):
        intake.main()
    assert list((tmp_path / "kb" / "units" / "blogs").glob("*/record.yaml")) == []
    failures = list((tmp_path / "kb" / ".runtime" / "intake-staging").glob("**/failure.yaml"))
    assert len(failures) == 1
    assert load_yaml(failures[0])["status"] == "failed_retryable"

    available = True
    monkeypatch.setattr(sys, "argv", argv)
    assert intake.main() == 0

    records = list((tmp_path / "kb" / "units" / "blogs").glob("*/record.yaml"))
    assert len(records) == 1
    record = load_yaml(records[0])
    assert all(".runtime/intake-staging" not in item for item in record["source"]["backup_paths"])
    cache = load_yaml(records[0].parent / "parse-cache.yaml")
    assert cache["unit_id"] == record["id"]
    assert cache["chunks"]


def test_unsupported_local_binary_exits_nonzero_without_canonical_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    binary = tmp_path / "payload.bin"
    binary.write_bytes(b"\x00\x01\x02")
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *args, **kwargs: {"status": "disabled"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "intake.py",
            "--root",
            str(tmp_path),
            "add",
            "--kind",
            "blog",
            "--source",
            binary.as_posix(),
            "--title",
            "Unsupported Binary",
        ],
    )

    with pytest.raises(SystemExit, match="Unsupported local file type"):
        intake.main()
    assert list((tmp_path / "kb" / "units" / "blogs").glob("*/record.yaml")) == []


def test_rejected_legacy_record_does_not_poison_source_retry(tmp_path: Path) -> None:
    unit = tmp_path / "kb" / "units" / "blogs" / "b-rejected-legacy"
    archive = unit / "source" / "source.html"
    archive.parent.mkdir(parents=True)
    archive.write_text("<p>legacy</p>", encoding="utf-8")
    write_yaml_if_changed(
        unit / "record.yaml",
        {
            "id": "b-rejected-legacy",
            "kind": "blog",
            "title": "Rejected legacy",
            "status": "rejected",
            "confirmation_status": "rejected",
            "source": {
                "original_uri": "https://example.com/retry-source",
                "backup_kind": "url",
                "backup_paths": [archive.relative_to(tmp_path).as_posix()],
                "file_hash": "legacy-hash",
            },
        },
    )

    assert sources.detect_duplicate(tmp_path, "blog", "https://example.com/retry-source") is None


def test_storage_sync_never_rewrites_agent_rules_or_immutable_source_bytes(tmp_path: Path) -> None:
    root_rules = tmp_path / "AGENTS.md"
    agent_rules = tmp_path / ".agents" / "AGENTS.md"
    skill_rules = tmp_path / ".agents" / "skills" / "demo" / "SKILL.md"
    for path in (root_rules, agent_rules, skill_rules):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Keep raw/example and output/example byte-identical.\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (root_rules, agent_rules, skill_rules)}

    mutable_note = tmp_path / "kb" / "notes" / "migration.md"
    immutable_source = tmp_path / "kb" / "units" / "blogs" / "b-demo" / "source" / "source.md"
    immutable_cache = immutable_source.parents[1] / "parse-cache.yaml"
    for path in (mutable_note, immutable_source, immutable_cache):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Reference raw/example and output/example.\n", encoding="utf-8")
    source_before = immutable_source.read_bytes()
    cache_before = immutable_cache.read_bytes()

    result = sources.sync_storage_layout(tmp_path)

    assert all(path.read_bytes() == payload for path, payload in before.items())
    assert immutable_source.read_bytes() == source_before
    assert immutable_cache.read_bytes() == cache_before
    assert "kb/raw/example" in mutable_note.read_text(encoding="utf-8")
    assert "kb/notes/migration.md" in result["rewritten_files"]
    assert all(item.startswith("kb/") for item in result["rewritten_files"])

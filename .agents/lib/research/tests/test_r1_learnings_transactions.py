from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

import research.prefs as prefs_module
from research.journal import load_op
from research.learnings import (
    _text_similarity,
    learnings_path,
    load_learnings,
    log_learning,
    promote_learning,
    review_learning,
)
from research.paths import runtime_preferences_path
from research.prefs import load_runtime_preferences, write_runtime_preferences
from research.yaml_io import load_yaml


NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    return root


def _file_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _journal_entries(root: Path, op_type: str) -> list[dict]:
    journal_root = root / "kb" / ".journal"
    entries = [
        entry
        for entry in (load_yaml(path, default={}) for path in journal_root.glob("*.yaml"))
        if entry.get("op_type") == op_type
    ]
    return sorted(entries, key=lambda entry: int(entry.get("sequence_ns") or 0))


def test_concurrent_distinct_logs_keep_ten_unique_ids(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    texts = [
        "Lock every shared file update.",
        "Preserve evidence artifact bytes.",
        "Ask before confirming judgement.",
        "Never expose internal shell commands.",
        "Retry failed network intake safely.",
        "Keep report claims grounded.",
        "Reject symlink path escapes.",
        "Use resource limits in designs.",
        "Archive discussion conclusions.",
        "Prefer concise Chinese summaries.",
    ]
    count = len(texts)
    start = threading.Barrier(count)

    def create(index: int) -> tuple[dict, bool]:
        start.wait(timeout=5)
        return log_learning(
            root,
            category="recurring-issue",
            text=texts[index],
            context=f"worker-{index}",
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(create, range(count)))

    entries = load_learnings(root)
    expected_ids = [f"lrn-20260719-{index:03d}" for index in range(1, count + 1)]
    assert sorted(entry["id"] for entry in entries) == expected_ids
    assert sorted(entry[0]["id"] for entry in results) == expected_ids
    assert all(created for _, created in results)


def test_concurrent_equivalent_logs_merge_and_count_every_occurrence(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    count = 10
    start = threading.Barrier(count)

    def create(index: int) -> tuple[dict, bool]:
        start.wait(timeout=5)
        text = f"distinct learning {index}"
        # The surface forms differ, but the existing governance threshold
        # intentionally classifies every pair as an equivalent learning.
        assert _text_similarity("distinct learning 0", text) >= 0.86
        return log_learning(
            root,
            category="recurring-issue",
            text=text,
            context=f"worker-{index}",
            now=NOW,
        )

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(create, range(count)))

    entries = load_learnings(root)
    assert len(entries) == 1
    assert entries[0]["occurrences"] == count
    assert {entry[0]["id"] for entry in results} == {"lrn-20260719-001"}
    assert sum(1 for _, created in results if created) == 1


def test_review_is_a_root_transaction_covering_the_learning_file(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    entry, _ = log_learning(
        root,
        category="skill-defect",
        text="Review must not race another learning update.",
        now=NOW,
    )

    reviewed = review_learning(root, learning_id=entry["id"], status="confirmed")

    operations = _journal_entries(root, "review-learning")
    assert reviewed["status"] == "confirmed"
    assert len(operations) == 1
    assert operations[0]["state"] == "commit"
    assert operations[0]["parent_op_id"] == ""
    assert operations[0]["target_paths"] == ["memory/learnings.yaml"]


def test_promote_fault_restores_both_files_byte_for_byte(tmp_path: Path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(root, {"identity": {"default_confirmed_by": "research-lead"}})
    entry, _ = log_learning(
        root,
        category="user-preference",
        text="Prefer byte-for-byte rollback checks.",
        source="user",
        now=NOW,
    )
    memory_path = learnings_path(root)
    preferences_path = runtime_preferences_path(root)
    before_memory = memory_path.read_bytes()
    before_preferences = preferences_path.read_bytes()
    original_write = prefs_module.write_yaml_if_changed

    def fail_after_preferences_write(path: Path, payload: object) -> bool:
        changed = original_write(path, payload)
        if Path(path).resolve() == preferences_path.resolve():
            raise OSError("simulated preference write failure")
        return changed

    monkeypatch.setattr(prefs_module, "write_yaml_if_changed", fail_after_preferences_write)

    with pytest.raises(OSError, match="simulated preference write failure"):
        promote_learning(root, learning_id=entry["id"])

    assert memory_path.read_bytes() == before_memory
    assert preferences_path.read_bytes() == before_preferences
    operations = _journal_entries(root, "promote-learning")
    assert len(operations) == 1
    assert operations[0]["state"] == "abort"
    assert operations[0]["target_paths"] == [
        "config/runtime-preferences.yaml",
        "memory/learnings.yaml",
    ]
    root_operation = load_op(root, operations[0]["op_id"])
    assert root_operation["state"] == "abort"
    descendants = [
        entry
        for op_type in ("write-learnings", "write-runtime-preferences")
        for entry in _journal_entries(root, op_type)
        if entry.get("root_op_id") == root_operation["op_id"]
    ]
    assert {entry["op_type"] for entry in descendants} == {
        "write-learnings",
        "write-runtime-preferences",
    }
    assert all(entry["parent_op_id"] == root_operation["op_id"] for entry in descendants)


def test_standalone_preference_write_rolls_back_after_fault(tmp_path: Path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(root, {"identity": {"default_confirmed_by": "before"}})
    path = runtime_preferences_path(root)
    before = path.read_bytes()
    original_write = prefs_module.write_yaml_if_changed

    def fail_after_write(target: Path, payload: object) -> bool:
        changed = original_write(target, payload)
        raise OSError("simulated standalone preference failure")

    monkeypatch.setattr(prefs_module, "write_yaml_if_changed", fail_after_write)

    with pytest.raises(OSError, match="simulated standalone preference failure"):
        write_runtime_preferences(root, {"identity": {"default_confirmed_by": "after"}})

    assert path.read_bytes() == before
    operations = _journal_entries(root, "write-runtime-preferences")
    assert operations[-1]["state"] == "abort"
    assert operations[-1]["parent_op_id"] == ""


def test_concurrent_preference_merges_preserve_every_disjoint_key(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    count = 8
    start = threading.Barrier(count)

    def merge(index: int) -> None:
        start.wait(timeout=5)
        write_runtime_preferences(
            root,
            {"learned_preferences": {f"worker_{index}": f"value-{index}"}},
        )

    with ThreadPoolExecutor(max_workers=count) as pool:
        list(pool.map(merge, range(count)))

    learned = load_runtime_preferences(root)["learned_preferences"]
    assert {learned[f"worker_{index}"] for index in range(count)} == {
        f"value-{index}" for index in range(count)
    }


def test_learning_and_preference_reads_are_byte_identical_on_absent_root(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = _file_snapshot(root)

    assert load_learnings(root) == []
    assert load_runtime_preferences(root)["learned_preferences"] == {"items": []}
    assert load_learnings(root) == []
    assert load_runtime_preferences(root)["identity"]["default_confirmed_by"] == ""

    assert _file_snapshot(root) == before
    assert not (root / "kb").exists()

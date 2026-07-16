from pathlib import Path

import pytest

from research.confirm import write_record
from research.journal import abort_op, begin_op, commit_op, journal_entry_path, load_op
from research.records import default_record
from research import yaml_io
from research.yaml_io import load_yaml


def test_atomic_write_failure_does_not_clobber_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "record.yaml"
    target.write_text("original\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(yaml_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated interruption"):
        yaml_io.write_text_if_changed(target, "replacement\n")

    assert target.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".record.yaml.*.tmp")) == []


def test_operation_journal_tracks_begin_commit_and_abort(tmp_path: Path) -> None:
    target = tmp_path / "kb" / "units" / "papers" / "p-test" / "record.yaml"
    op_id = begin_op(tmp_path, "test-write", [target])

    begun = load_op(tmp_path, op_id)
    assert begun["state"] == "begin"
    assert begun["before_digests"] == {"units/papers/p-test/record.yaml": None}

    target.parent.mkdir(parents=True)
    target.write_text("value: one\n", encoding="utf-8")
    commit_op(tmp_path, op_id)
    committed = load_op(tmp_path, op_id)
    assert committed["state"] == "commit"
    assert committed["after_digests"]["units/papers/p-test/record.yaml"]

    abort_id = begin_op(tmp_path, "test-abort", [target])
    abort_op(tmp_path, abort_id)
    assert load_op(tmp_path, abort_id)["state"] == "abort"
    assert ".journal/" in (tmp_path / "kb" / ".gitignore").read_text(encoding="utf-8")


def test_write_record_creates_committed_journal_entry(tmp_path: Path) -> None:
    record = default_record("paper", title="Journal Test", maturity="lightweight")
    record["id"] = "p-journal-test"

    path = write_record(tmp_path, record)

    entries = list((tmp_path / "kb" / ".journal").glob("*.yaml"))
    assert len(entries) == 1
    entry = load_op(tmp_path, entries[0].stem)
    assert entry["state"] == "commit"
    assert entry["target_paths"] == [path.relative_to(tmp_path / "kb").as_posix()]
    assert entry["before_digests"] == {entry["target_paths"][0]: None}
    assert entry["after_digests"][entry["target_paths"][0]]
    assert journal_entry_path(tmp_path, entry["op_id"]) == entries[0]


def test_write_record_increments_revision_and_rejects_stale_cas(tmp_path: Path) -> None:
    record = default_record("paper", title="Revision Test", maturity="lightweight")
    record["id"] = "p-revision-test"

    path = write_record(tmp_path, record)
    first = load_yaml(path)
    assert first["revision"] == 1

    first["title"] = "Revision Two"
    write_record(tmp_path, first, expected_revision=1)
    second = load_yaml(path)
    assert second["revision"] == 2
    assert second["title"] == "Revision Two"

    first["title"] = "Stale Update"
    with pytest.raises(SystemExit, match="expected 1, found 2"):
        write_record(tmp_path, first, expected_revision=1)

    unchanged = load_yaml(path)
    assert unchanged["revision"] == 2
    assert unchanged["title"] == "Revision Two"


def test_write_record_uses_ignored_per_record_lock(tmp_path: Path) -> None:
    record = default_record("paper", title="Lock Test", maturity="lightweight")
    record["id"] = "p-lock-test"

    write_record(tmp_path, record)

    locks = list((tmp_path / "kb" / ".journal" / "locks").glob("*.lock"))
    assert len(locks) == 1
    assert locks[0].read_text(encoding="utf-8") == ""
    assert ".journal/" in (tmp_path / "kb" / ".gitignore").read_text(encoding="utf-8")

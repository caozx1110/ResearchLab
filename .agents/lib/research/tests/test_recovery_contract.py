import importlib.util
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys

import pytest

from research.confirm import write_record
from research.git_ops import (
    ensure_kb_git_repo,
    git_checkpoint,
    restore_operation,
    undo_last_operation,
)
from research.journal import abort_op, begin_op, commit_op, committed_ops, incomplete_ops, journal_entry_path, load_op
from research.records import default_record
from research import yaml_io
from research.yaml_io import load_yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_kb_module():
    script = _project_root() / ".agents" / "skills" / "knowledge-base-manager" / "scripts" / "kb.py"
    spec = importlib.util.spec_from_file_location("kb_script_for_recovery_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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

    with pytest.raises(SystemExit, match="Invalid operation id"):
        load_op(tmp_path, "../outside")


def test_incomplete_ops_lists_only_begin_state_entries(tmp_path: Path) -> None:
    first_target = tmp_path / "kb" / "notes" / "first.md"
    second_target = tmp_path / "kb" / "notes" / "second.md"
    first_op = begin_op(tmp_path, "first-write", [first_target])
    second_op = begin_op(tmp_path, "second-write", [second_target])
    second_target.parent.mkdir(parents=True, exist_ok=True)
    second_target.write_text("changed\n", encoding="utf-8")
    commit_op(tmp_path, second_op)

    entries = incomplete_ops(tmp_path)

    assert [entry["op_id"] for entry in entries] == [first_op]
    assert entries[0]["target_paths"] == ["notes/first.md"]
    assert entries[0]["before_digests"] == {"notes/first.md": None}
    assert entries[0]["started_at"]
    assert first_op not in {entry["op_id"] for entry in committed_ops(tmp_path)}


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


def test_manager_mutation_transaction_rejects_empty_scope(tmp_path: Path) -> None:
    kb = _load_kb_module()

    with pytest.raises(SystemExit, match="empty operation scope"):
        with kb.mutation_transaction(tmp_path, "unsafe-empty", []):
            pass

    assert not (tmp_path / "kb" / ".journal").exists()


def test_manager_index_uses_one_exact_multifile_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = _load_kb_module()
    planned = kb.mutation_targets(tmp_path, kb.index_mutation_targets(tmp_path))
    expected = sorted(path.relative_to(tmp_path / "kb").as_posix() for path in planned)
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "index"])

    assert kb.main() == 0

    entries = [entry for entry in committed_ops(tmp_path) if entry["op_type"] == "rebuild_index"]
    assert len(entries) == 1
    assert entries[0]["target_paths"] == expected
    assert entries[0]["target_paths"]


def test_storage_sync_planner_names_kb_destinations_not_external_sources(tmp_path: Path) -> None:
    kb = _load_kb_module()
    legacy = tmp_path / "raw" / "paper.pdf"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"pdf")

    planned = kb.storage_sync_operation_targets(tmp_path)

    assert tmp_path / "kb" / "raw" / "paper.pdf" in planned
    assert legacy not in planned
    assert all(path.is_relative_to(tmp_path / "kb") for path in planned)


def test_manual_checkpoint_clean_state_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_module()
    monkeypatch.setattr(kb, "dirty_kb_paths", lambda root: [])
    monkeypatch.setattr(
        kb,
        "git_checkpoint",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not checkpoint")),
    )
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "git-checkpoint", "--message", "manual"])

    assert kb.main() == 0

    assert "no kb changes to commit" in capsys.readouterr().out


def test_checkpoint_failure_occurs_after_outer_transaction_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = _load_kb_module()
    events: list[str] = []
    record = {"id": "p-order-test", "kind": "paper"}
    path = tmp_path / "kb" / "units" / "papers" / "p-order-test" / "record.yaml"

    @contextmanager
    def completed_transaction(root: Path, op_type: str, target_paths: list[Path]):
        events.append("transaction_begin")
        yield
        events.append("transaction_commit")

    monkeypatch.setattr(kb, "mutation_transaction", completed_transaction)
    monkeypatch.setattr(kb, "ensure_workspace", lambda root: events.append("mutate"))
    monkeypatch.setattr(kb, "locate_record", lambda root, unit_id: (record, path))
    monkeypatch.setattr(kb, "promote_record", lambda root, unit_id, **kwargs: path)
    monkeypatch.setattr(kb, "build_index", lambda root: events.append("index"))

    def fail_checkpoint(*args, **kwargs):
        events.append("checkpoint")
        assert events[-2] == "transaction_commit"
        raise RuntimeError("checkpoint failed")

    monkeypatch.setattr(kb, "checkpoint_and_report", fail_checkpoint)
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "promote", "--id", "p-order-test", "--status", "active"])

    with pytest.raises(RuntimeError, match="checkpoint failed"):
        kb.main()

    assert events == ["transaction_begin", "mutate", "index", "transaction_commit", "checkpoint"]


def test_outer_transaction_commit_failure_skips_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = _load_kb_module()
    events: list[str] = []
    record = {"id": "p-order-test", "kind": "paper"}
    path = tmp_path / "kb" / "units" / "papers" / "p-order-test" / "record.yaml"

    @contextmanager
    def failed_transaction(root: Path, op_type: str, target_paths: list[Path]):
        events.append("transaction_begin")
        yield
        events.append("transaction_commit_failed")
        raise OSError("outer commit failed")

    monkeypatch.setattr(kb, "mutation_transaction", failed_transaction)
    monkeypatch.setattr(kb, "ensure_workspace", lambda root: events.append("mutate"))
    monkeypatch.setattr(kb, "locate_record", lambda root, unit_id: (record, path))
    monkeypatch.setattr(kb, "promote_record", lambda root, unit_id, **kwargs: path)
    monkeypatch.setattr(kb, "build_index", lambda root: events.append("index"))
    monkeypatch.setattr(kb, "checkpoint_and_report", lambda *args, **kwargs: events.append("checkpoint"))
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "promote", "--id", "p-order-test", "--status", "active"])

    with pytest.raises(OSError, match="outer commit failed"):
        kb.main()

    assert events == ["transaction_begin", "mutate", "index", "transaction_commit_failed"]


def _configure_kb_git(root: Path) -> None:
    ensure_kb_git_repo(root, create_initial_commit=False)
    subprocess.run(["git", "-C", str(root / "kb"), "config", "user.name", "Recovery Tests"], check=True)
    subprocess.run(["git", "-C", str(root / "kb"), "config", "user.email", "recovery@example.com"], check=True)
    git_checkpoint(root, "initial kb state", auto_init=False)


def test_git_checkpoint_stages_only_target_paths(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "units" / "papers" / "p-target" / "record.yaml"
    unrelated = tmp_path / "kb" / "notes" / "unrelated.md"
    target.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    target.write_text("target: changed\n", encoding="utf-8")
    unrelated.write_text("unrelated\n", encoding="utf-8")

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
    assert "?? notes/" in status
    assert "record.yaml" not in status


def test_undo_and_restore_use_journal_digests_and_kb_history(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    record = default_record("paper", title="First Title", maturity="lightweight")
    record["id"] = "p-recovery-test"
    path = write_record(tmp_path, record)
    git_checkpoint(
        tmp_path,
        "create recovery record",
        auto_init=False,
        target_paths=[path, tmp_path / "kb" / ".gitignore"],
    )
    first_op = [entry for entry in committed_ops(tmp_path) if entry["op_type"] == "write_record"][-1]

    updated = load_yaml(path)
    updated["title"] = "Second Title"
    write_record(tmp_path, updated, expected_revision=1)
    git_checkpoint(tmp_path, "update recovery record", auto_init=False, target_paths=[path])
    second_op = [entry for entry in committed_ops(tmp_path) if entry["op_type"] == "write_record"][-1]

    undone = undo_last_operation(tmp_path)
    assert undone["op_id"] == second_op["op_id"]
    assert load_yaml(path)["title"] == "First Title"

    restored = restore_operation(tmp_path, first_op["op_id"])
    assert restored["op_id"] == first_op["op_id"]
    assert not path.exists()


def test_kb_resume_rolls_back_incomplete_operation_and_marks_it_aborted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "notes" / "resume-target.md"
    target.parent.mkdir(parents=True)
    target.write_text("before crash\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed resume target", auto_init=False, target_paths=[target])
    op_id = begin_op(tmp_path, "stranded-write", [target])
    target.write_text("after crash\n", encoding="utf-8")
    kb = _load_kb_module()
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "resume"])

    assert kb.main() == 0

    output = capsys.readouterr().out
    assert target.read_text(encoding="utf-8") == "before crash\n"
    assert load_op(tmp_path, op_id)["state"] == "abort"
    assert incomplete_ops(tmp_path) == []
    assert op_id in output
    assert "1 个目标" in output
    for forbidden in ["python3", ".py", "git ", "--"]:
        assert forbidden not in output


def test_kb_resume_clean_state_reports_nothing_to_recover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_module()
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "resume"])

    assert kb.main() == 0

    output = capsys.readouterr().out
    assert "没有未完成操作需要恢复" in output
    for forbidden in ["python3", ".py", "git ", "--"]:
        assert forbidden not in output


def test_kb_recovery_output_does_not_promise_redo_of_recovery_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_module()
    monkeypatch.setattr(kb, "undo_last_operation", lambda root: {"op_id": "op-business-latest"})
    monkeypatch.setattr(
        kb,
        "restore_operation",
        lambda root, op_id, **kwargs: {"op_id": op_id, "restored_paths": []},
    )

    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "undo"])
    assert kb.main() == 0
    undo_output = capsys.readouterr().out
    assert "继续撤销更早一次可撤销的业务操作" in undo_output
    assert "撤销当前恢复结果" not in undo_output

    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "restore", "op-target"])
    assert kb.main() == 0
    restore_output = capsys.readouterr().out
    assert "不会成为新的可撤销业务操作" in restore_output
    assert "撤销当前恢复结果" not in restore_output

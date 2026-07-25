import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from research.confirm import write_record
from research.git_ops import (
    dirty_kb_paths,
    ensure_kb_git_repo,
    git_checkpoint,
    restore_operation,
    undo_last_operation,
)
from research.journal import (
    abort_op,
    begin_op,
    commit_op,
    committed_ops,
    file_digest,
    incomplete_ops,
    journal_entry_path,
    journaled_op,
    load_op,
    mutation_transaction,
    target_path,
)
from research.prefs import ensure_workspace
from research.records import default_record
from research import git_ops, journal, yaml_io
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


def _load_paper_module():
    script = _project_root() / ".agents" / "skills" / "paper-analyst" / "scripts" / "paper.py"
    spec = importlib.util.spec_from_file_location("paper_script_for_checkpoint_recovery_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _lstat_state(path: Path) -> tuple[int, int, int, object]:
    metadata = path.lstat()
    if path.is_symlink():
        payload: object = os.readlink(path)
    elif path.is_file():
        payload = path.read_bytes()
    else:
        payload = None
    return metadata.st_dev, metadata.st_ino, metadata.st_mode, payload


def _tree_lstat_state(path: Path) -> dict[str, tuple[int, int, int, object]]:
    return {
        item.relative_to(path).as_posix() or ".": _lstat_state(item)
        for item in [path, *sorted(path.rglob("*"))]
    }


@pytest.mark.parametrize(
    ("skill", "script_name"),
    [
        ("paper-analyst", "paper.py"),
        ("blog-analyst", "blog.py"),
        ("dataset-analyst", "dataset.py"),
    ],
)
def test_analyzer_fill_checkpoint_scope_rejects_external_and_symlink_inputs(
    tmp_path: Path,
    skill: str,
    script_name: str,
) -> None:
    script = _project_root() / ".agents" / "skills" / skill / "scripts" / script_name
    module_name = f"{skill.replace('-', '_')}_fill_scope_test"
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    unit = tmp_path / "kb" / "units" / "kind" / "unit"
    unit.mkdir(parents=True)
    owned = unit / "fill.yaml"
    owned.write_text("value: owned\n", encoding="utf-8")
    external = tmp_path / "external-fill.yaml"
    external.write_text("value: external\n", encoding="utf-8")
    escaped = unit / "escaped-fill.yaml"
    escaped.symlink_to(external)

    assert module._unit_owned_fill_path(unit, owned) == owned
    assert module._unit_owned_fill_path(unit, external) is None
    assert module._unit_owned_fill_path(unit, escaped) is None


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
    ensure_workspace(tmp_path)
    gitignore = tmp_path / "kb" / ".gitignore"
    gitignore_before = gitignore.read_bytes()
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
    assert gitignore.read_bytes() == gitignore_before

    with pytest.raises(SystemExit, match="Invalid operation id"):
        load_op(tmp_path, "../outside")


def test_journaled_abort_without_target_writes_preserves_file_and_tree_identities(
    tmp_path: Path,
) -> None:
    file_target = tmp_path / "kb" / "notes" / "unchanged.md"
    tree_target = tmp_path / "kb" / "artifacts" / "unchanged-tree"
    file_target.parent.mkdir(parents=True)
    tree_target.mkdir(parents=True)
    file_target.write_bytes(b"unchanged file bytes\n")
    tree_child = tree_target / "child.txt"
    tree_child.write_bytes(b"unchanged tree bytes\n")
    (tree_target / "child-link").symlink_to("child.txt")
    os.chmod(file_target, 0o640)
    os.chmod(tree_target, 0o750)

    file_before = _lstat_state(file_target)
    tree_before = _tree_lstat_state(tree_target)
    operation_id = ""

    with pytest.raises(RuntimeError, match="expected validation rejection"):
        with journaled_op(
            tmp_path,
            "zero-write-validation-failure",
            [file_target, tree_target],
        ) as operation_id:
            raise RuntimeError("expected validation rejection")

    assert operation_id
    assert _lstat_state(file_target) == file_before
    assert _tree_lstat_state(tree_target) == tree_before
    entry = load_op(tmp_path, operation_id)
    assert entry["state"] == "abort"
    assert entry["after_digests"] == {}
    assert {
        key: file_digest(tmp_path / "kb" / key)
        for key in entry["target_paths"]
    } == entry["before_digests"]


def test_mutation_commit_guard_failure_restores_before_image_and_aborts_journal(
    tmp_path: Path,
) -> None:
    target = tmp_path / "kb" / "notes" / "guarded.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before commit guard\n")
    os.chmod(target, 0o640)
    operation_id = ""

    def reject_commit() -> None:
        assert target.read_bytes() == b"after transaction body\n"
        raise RuntimeError("commit guard rejected mutation")

    with pytest.raises(RuntimeError, match="commit guard rejected mutation"):
        with mutation_transaction(
            tmp_path,
            "commit-guard-rejection",
            [target],
            commit_guard=reject_commit,
        ) as operation_id:
            target.write_bytes(b"after transaction body\n")
            os.chmod(target, 0o600)

    assert operation_id
    assert target.read_bytes() == b"before commit guard\n"
    assert target.stat().st_mode & 0o777 == 0o640
    entry = load_op(tmp_path, operation_id)
    assert entry["state"] == "abort"
    assert entry["operation_error"] == "commit guard rejected mutation"
    assert entry["after_digests"] == {}
    assert "commit_guard" not in entry


def test_journaled_abort_mixed_targets_skips_unchanged_and_restores_only_divergence(
    tmp_path: Path,
) -> None:
    unchanged = tmp_path / "kb" / "notes" / "unchanged.md"
    changed = tmp_path / "kb" / "notes" / "changed.md"
    created = tmp_path / "kb" / "notes" / "created.md"
    unchanged.parent.mkdir(parents=True)
    unchanged.write_bytes(b"unchanged\n")
    changed.write_bytes(b"before\n")
    os.chmod(unchanged, 0o600)
    os.chmod(changed, 0o640)
    unchanged_before = _lstat_state(unchanged)
    changed_before_digest = file_digest(changed)
    operation_id = ""

    with pytest.raises(RuntimeError, match="mixed failure"):
        with journaled_op(
            tmp_path,
            "mixed-zero-churn-failure",
            [unchanged, changed, created],
        ) as operation_id:
            changed.write_bytes(b"after\n")
            os.chmod(changed, 0o600)
            created.write_bytes(b"created\n")
            raise RuntimeError("mixed failure")

    assert _lstat_state(unchanged) == unchanged_before
    assert changed.read_bytes() == b"before\n"
    assert changed.stat().st_mode & 0o777 == 0o640
    assert file_digest(changed) == changed_before_digest
    assert not created.exists() and not created.is_symlink()
    entry = load_op(tmp_path, operation_id)
    assert entry["state"] == "abort"
    assert entry["after_digests"] == {}
    assert {
        key: file_digest(tmp_path / "kb" / key)
        for key in entry["target_paths"]
    } == entry["before_digests"]


def test_explicit_abort_skips_unchanged_existing_and_absent_targets(tmp_path: Path) -> None:
    existing = tmp_path / "kb" / "notes" / "existing.md"
    absent = tmp_path / "kb" / "notes" / "absent.md"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"same before and after\n")
    os.chmod(existing, 0o600)
    existing_before = _lstat_state(existing)
    operation_id = begin_op(tmp_path, "explicit-zero-churn-abort", [existing, absent])

    abort_op(tmp_path, operation_id, restore=True, error="validation rejected")

    assert _lstat_state(existing) == existing_before
    assert not absent.exists() and not absent.is_symlink()
    entry = load_op(tmp_path, operation_id)
    assert entry["state"] == "abort"
    assert entry["operation_error"] == "validation rejected"
    assert {
        key: file_digest(tmp_path / "kb" / key)
        for key in entry["target_paths"]
    } == entry["before_digests"]


def _digest_in_bounded_subprocess(path: Path) -> str:
    environment = os.environ.copy()
    library_root = _project_root() / ".agents" / "lib"
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(library_root), existing_pythonpath) if part
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "from research.journal import file_digest; "
                "print(file_digest(Path(sys.argv[1])))"
            ),
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
        env=environment,
    )
    return completed.stdout.strip()


def test_file_digest_classifies_fifo_and_socket_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    fifo = tmp_path / "root-fifo"
    os.mkfifo(fifo)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "ordinary.txt").write_bytes(b"ordinary\n")
    os.mkfifo(tree / "child-fifo")

    digests = [_digest_in_bounded_subprocess(fifo), _digest_in_bounded_subprocess(tree)]
    if hasattr(socket, "AF_UNIX"):
        socket_path = tmp_path / "root-socket"
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            endpoint.bind(socket_path.name)
        finally:
            os.chdir(previous_cwd)
            endpoint.close()
        digests.append(_digest_in_bounded_subprocess(socket_path))

    assert all(len(digest) == 64 for digest in digests)
    assert len(set(digests)) == len(digests)


@pytest.mark.parametrize("location", ("root", "directory-child"))
def test_begin_snapshot_rejects_existing_fifo_before_business_mutation(
    tmp_path: Path,
    location: str,
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    kb = tmp_path / "kb"
    kb.mkdir()
    declared = kb / "notes" / "special-target"
    declared.parent.mkdir(parents=True)
    if location == "root":
        special = declared
    else:
        declared.mkdir()
        special = declared / "child-fifo"
    os.mkfifo(special)
    special_before = special.lstat()

    with pytest.raises(SystemExit, match="refuses special filesystem node"):
        begin_op(tmp_path, "existing-special", [declared])

    special_after = special.lstat()
    assert stat.S_ISFIFO(special_after.st_mode)
    assert (special_after.st_dev, special_after.st_ino) == (
        special_before.st_dev,
        special_before.st_ino,
    )
    assert list((kb / ".journal").glob("*.yaml")) == []


@pytest.mark.parametrize("location", ("root", "directory-child"))
def test_abort_restores_before_image_after_fifo_replacement(
    tmp_path: Path,
    location: str,
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    declared = tmp_path / "kb" / "notes" / "journal-target"
    declared.parent.mkdir(parents=True)
    if location == "root":
        declared.write_bytes(b"before root replacement\n")
        replaced = declared
        expected_digest = file_digest(declared)
    else:
        declared.mkdir()
        replaced = declared / "child.txt"
        replaced.write_bytes(b"before child replacement\n")
        expected_digest = file_digest(declared)
    operation_id = ""

    with pytest.raises(RuntimeError, match="force journal abort"):
        with journaled_op(tmp_path, "fifo-replacement", [declared]) as operation_id:
            replaced.unlink()
            os.mkfifo(replaced)
            raise RuntimeError("force journal abort")

    assert operation_id
    assert file_digest(declared) == expected_digest
    if location == "root":
        assert declared.read_bytes() == b"before root replacement\n"
    else:
        assert replaced.read_bytes() == b"before child replacement\n"
    entry = load_op(tmp_path, operation_id)
    assert entry["state"] == "abort"
    assert "restoration_error" not in entry
    assert entry["before_digests"] == {
        entry["target_paths"][0]: expected_digest,
    }


def test_resume_of_unchanged_incomplete_operation_preserves_target_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "unchanged-resume.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unchanged incomplete target\n")
    os.chmod(target, 0o640)
    target_before = _lstat_state(target)
    operation_id = begin_op(tmp_path, "unchanged-incomplete", [target])
    monkeypatch.setattr(
        git_ops,
        "git_checkpoint",
        lambda *args, **kwargs: {"committed": False, "files": []},
    )

    result = restore_operation(tmp_path, operation_id, recovery_type="resume")

    assert _lstat_state(target) == target_before
    assert result["restored_paths"] == ["notes/unchanged-resume.md"]
    recovery = load_op(tmp_path, result["recovery_op_id"])
    assert recovery["state"] == "commit"
    assert recovery["before_digests"] == recovery["after_digests"]
    abort_op(tmp_path, operation_id)
    assert load_op(tmp_path, operation_id)["state"] == "abort"
    assert incomplete_ops(tmp_path) == []


def test_restore_reports_paths_relative_to_canonical_kb_for_project_root_alias(
    tmp_path: Path,
) -> None:
    canonical_project = (tmp_path / "canonical-project").resolve()
    canonical_project.mkdir()
    try:
        # Exercise the exact macOS /var -> /private/var ancestor alias when the
        # temporary directory lives there; use an equivalent portable alias in CI.
        alias_project = Path("/var") / canonical_project.relative_to("/private/var")
        if alias_project.resolve() != canonical_project:
            raise ValueError
    except ValueError:
        alias_project = tmp_path / "project-alias"
        alias_project.symlink_to(canonical_project, target_is_directory=True)
    assert alias_project.resolve() == canonical_project

    ensure_workspace(alias_project)
    target = alias_project / "kb" / "notes" / "aliased-root.md"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    operation_id = begin_op(alias_project, "edit-through-project-alias", [target])
    target.write_text("after\n", encoding="utf-8")
    commit_op(alias_project, operation_id)

    result = restore_operation(alias_project, operation_id)

    assert target.read_text(encoding="utf-8") == "before\n"
    assert result["restored_paths"] == ["notes/aliased-root.md"]


@pytest.mark.parametrize("action", ["restore", "undo"])
def test_recovery_refuses_to_overwrite_changes_made_after_committed_operation(
    tmp_path: Path,
    action: str,
) -> None:
    target = tmp_path / "kb" / "notes" / "route.md"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    op_id = begin_op(tmp_path, "edit-route", [target])
    target.write_text("operation after-state\n", encoding="utf-8")
    commit_op(tmp_path, op_id)
    journal_files_before = {path.name: path.read_bytes() for path in (tmp_path / "kb/.journal").glob("*.yaml")}

    target.write_text("manual edit after operation\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="操作完成后又被修改"):
        if action == "restore":
            restore_operation(tmp_path, op_id)
        else:
            undo_last_operation(tmp_path)

    assert target.read_text(encoding="utf-8") == "manual edit after operation\n"
    assert {path.name: path.read_bytes() for path in (tmp_path / "kb/.journal").glob("*.yaml")} == journal_files_before
    assert load_op(tmp_path, op_id).get("undone_by") in (None, "")


def test_restore_refuses_committed_operation_with_incomplete_after_digests(tmp_path: Path) -> None:
    target = tmp_path / "kb" / "notes" / "route.md"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    op_id = begin_op(tmp_path, "edit-route", [target])
    target.write_text("after\n", encoding="utf-8")
    commit_op(tmp_path, op_id)
    entry_path = journal_entry_path(tmp_path, op_id)
    entry = load_yaml(entry_path)
    entry["after_digests"] = {}
    from research.common import write_yaml_if_changed

    write_yaml_if_changed(entry_path, entry)
    journal_files_before = {path.name: path.read_bytes() for path in (tmp_path / "kb/.journal").glob("*.yaml")}

    with pytest.raises(SystemExit, match="缺少完整的恢复后状态记录"):
        restore_operation(tmp_path, op_id)

    assert target.read_text(encoding="utf-8") == "after\n"
    assert {path.name: path.read_bytes() for path in (tmp_path / "kb/.journal").glob("*.yaml")} == journal_files_before


def test_incomplete_ops_lists_only_begin_state_entries(tmp_path: Path) -> None:
    first_target = tmp_path / "kb" / "notes" / "first.md"
    second_target = tmp_path / "kb" / "notes" / "second.md"
    second_op = begin_op(tmp_path, "second-write", [second_target])
    second_target.parent.mkdir(parents=True, exist_ok=True)
    second_target.write_text("changed\n", encoding="utf-8")
    commit_op(tmp_path, second_op)
    first_op = begin_op(tmp_path, "first-write", [first_target])

    entries = incomplete_ops(tmp_path)

    assert [entry["op_id"] for entry in entries] == [first_op]
    assert entries[0]["target_paths"] == ["notes/first.md"]
    assert entries[0]["before_digests"] == {"notes/first.md": None}
    assert entries[0]["started_at"]
    assert first_op not in {entry["op_id"] for entry in committed_ops(tmp_path)}


def test_incomplete_root_quarantines_new_root_before_journal_or_business_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "quarantine.md"
    target.parent.mkdir(parents=True)
    target.write_text("v0\n", encoding="utf-8")
    first_op = begin_op(tmp_path, "stranded-root", [target])
    target.write_text("partial-v1\n", encoding="utf-8")
    journal_before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
    }
    entered = False

    with pytest.raises(SystemExit, match="kb resume"):
        with journaled_op(tmp_path, "forbidden-second-root", [target]):
            entered = True
            target.write_text("v2\n", encoding="utf-8")

    assert entered is False
    assert target.read_text(encoding="utf-8") == "partial-v1\n"
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
    } == journal_before
    with pytest.raises(SystemExit, match="kb resume"):
        begin_op(
            tmp_path,
            "caller-labeled-recovery",
            [target],
            operation_role="recovery",
            attach_to_active=False,
        )
    with pytest.raises(SystemExit, match="active transaction context"):
        begin_op(tmp_path, "caller-forged-child", [target], parent_op_id=first_op)
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
    } == journal_before

    monkeypatch.setattr(
        git_ops,
        "git_checkpoint",
        lambda *args, **kwargs: {"committed": False, "files": []},
    )
    restore_operation(tmp_path, first_op, recovery_type="resume")
    abort_op(tmp_path, first_op)
    assert target.read_text(encoding="utf-8") == "v0\n"


@pytest.mark.parametrize(
    "malformed_kind",
    ("truncated", "unknown-state", "duplicate-key", "symlink", "fifo"),
)
def test_malformed_journal_entry_quarantines_before_new_runtime_or_business_write(
    tmp_path: Path,
    malformed_kind: str,
) -> None:
    journal_dir = tmp_path / "kb" / ".journal"
    journal_dir.mkdir(parents=True)
    entry_path = journal_dir / "broken.yaml"
    if malformed_kind == "truncated":
        entry_path.write_text("op_id: broken\nstate: abort\n", encoding="utf-8")
    elif malformed_kind == "unknown-state":
        entry_path.write_text("op_id: broken\nstate: unknown\n", encoding="utf-8")
    elif malformed_kind == "duplicate-key":
        entry_path.write_text(
            "op_id: broken\nop_id: broken\nstate: begin\n",
            encoding="utf-8",
        )
    elif malformed_kind == "symlink":
        outside = tmp_path / "outside-journal.yaml"
        outside.write_text("op_id: broken\nstate: begin\n", encoding="utf-8")
        entry_path.symlink_to(outside)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO creation is unavailable on this platform")
        os.mkfifo(entry_path)
    baseline = sorted(path.name for path in journal_dir.iterdir())
    target = tmp_path / "kb" / "notes" / "must-not-write.md"
    entered = False

    with pytest.raises(SystemExit):
        with mutation_transaction(tmp_path, "blocked-by-malformed-journal", [target]):
            entered = True
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("unsafe\n", encoding="utf-8")

    assert entered is False
    assert not target.exists()
    assert sorted(path.name for path in journal_dir.iterdir()) == baseline


def test_legacy_overlapping_roots_without_provable_order_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "legacy-stack.md"
    target.parent.mkdir(parents=True)
    target.write_text("v0\n", encoding="utf-8")
    first_op = begin_op(tmp_path, "legacy-first", [target])
    target.write_text("partial-v1\n", encoding="utf-8")

    # Test-only fixture for state written by versions that predate quarantine:
    # temporarily hide op1, create op2's real partial-state before-image, then
    # restore op1 to begin.  No production bypass is exposed.
    first_entry = load_op(tmp_path, first_op)
    first_entry["state"] = "abort"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, first_op), first_entry)
    second_op = begin_op(tmp_path, "legacy-second", [target])
    target.write_text("partial-v2\n", encoding="utf-8")
    first_entry["state"] = "begin"
    first_entry.pop("completed_at", None)
    first_entry["sequence_ns"] = 7
    first_entry["started_at"] = "2026-01-01T00:00:00Z"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, first_op), first_entry)
    second_entry = load_op(tmp_path, second_op)
    second_entry["sequence_ns"] = 1
    second_entry["started_at"] = "2025-01-01T00:00:00Z"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, second_op), second_entry)

    journals_before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
    }
    with pytest.raises(SystemExit, match="因果顺序无法证明"):
        incomplete_ops(tmp_path)
    assert target.read_text(encoding="utf-8") == "partial-v2\n"
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
    } == journals_before

    kb = _load_kb_module()
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "resume"])
    with pytest.raises(SystemExit, match="因果顺序无法证明"):
        kb.main()

    assert target.read_text(encoding="utf-8") == "partial-v2\n"
    assert load_op(tmp_path, second_op)["state"] == "begin"
    assert load_op(tmp_path, first_op)["state"] == "begin"
    assert {
        path.name: path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
    } == journals_before


def test_public_resume_recovers_disjoint_legacy_roots_in_stable_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "kb" / "notes" / "legacy-a.md"
    second = tmp_path / "kb" / "notes" / "legacy-b.md"
    first.parent.mkdir(parents=True)
    first.write_text("a0\n", encoding="utf-8")
    second.write_text("b0\n", encoding="utf-8")
    first_op = begin_op(tmp_path, "legacy-disjoint-first", [first])
    first.write_text("a-partial\n", encoding="utf-8")
    first_entry = load_op(tmp_path, first_op)
    first_entry["state"] = "abort"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, first_op), first_entry)
    second_op = begin_op(tmp_path, "legacy-disjoint-second", [second])
    second.write_text("b-partial\n", encoding="utf-8")
    first_entry["state"] = "begin"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, first_op), first_entry)

    expected_order = sorted([first_op, second_op])
    assert [entry["op_id"] for entry in incomplete_ops(tmp_path)] == expected_order
    monkeypatch.setattr(
        git_ops,
        "git_checkpoint",
        lambda *args, **kwargs: {"committed": False, "files": []},
    )
    kb = _load_kb_module()
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "resume"])
    assert kb.main() == 0

    assert first.read_text(encoding="utf-8") == "a0\n"
    assert second.read_text(encoding="utf-8") == "b0\n"
    assert load_op(tmp_path, first_op)["state"] == "abort"
    assert load_op(tmp_path, second_op)["state"] == "abort"
    assert incomplete_ops(tmp_path) == []


def test_concurrent_resume_consumes_one_root_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "single-consume.md"
    target.parent.mkdir(parents=True)
    target.write_text("v0\n", encoding="utf-8")
    operation_id = begin_op(tmp_path, "single-consume-source", [target])
    target.write_text("partial\n", encoding="utf-8")
    checkpoint_entered = threading.Event()
    checkpoint_release = threading.Event()
    checkpoint_calls = 0

    def paused_checkpoint(*args, **kwargs):
        nonlocal checkpoint_calls
        checkpoint_calls += 1
        checkpoint_entered.set()
        assert checkpoint_release.wait(timeout=5)
        return {"committed": False, "files": []}

    monkeypatch.setattr(git_ops, "git_checkpoint", paused_checkpoint)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(restore_operation, tmp_path, operation_id, recovery_type="resume")
        assert checkpoint_entered.wait(timeout=5)
        second = executor.submit(restore_operation, tmp_path, operation_id, recovery_type="resume")
        assert not second.done()
        checkpoint_release.set()
        first_result = first.result(timeout=5)
        second_result = second.result(timeout=5)

    assert checkpoint_calls == 1
    assert first_result.get("status") != "already-resumed"
    assert second_result["status"] == "already-resumed"
    assert target.read_text(encoding="utf-8") == "v0\n"
    source = load_op(tmp_path, operation_id)
    assert source["state"] == "abort"
    assert source["resumed_by"] == first_result["recovery_op_id"]


def test_failed_disjoint_resume_does_not_advance_to_later_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = [
        tmp_path / "kb" / "notes" / "failure-a.md",
        tmp_path / "kb" / "notes" / "failure-b.md",
    ]
    targets[0].parent.mkdir(parents=True)
    for index, target in enumerate(targets):
        target.write_text(f"v{index}\n", encoding="utf-8")
    first_op = begin_op(tmp_path, "failure-first", [targets[0]])
    targets[0].write_text("partial-a\n", encoding="utf-8")
    first_entry = load_op(tmp_path, first_op)
    first_entry["state"] = "abort"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, first_op), first_entry)
    second_op = begin_op(tmp_path, "failure-second", [targets[1]])
    targets[1].write_text("partial-b\n", encoding="utf-8")
    first_entry["state"] = "begin"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, first_op), first_entry)
    ordered = incomplete_ops(tmp_path)
    first_selected = str(ordered[0]["op_id"])
    later_selected = str(ordered[1]["op_id"])
    selected_target = targets[0] if first_selected == first_op else targets[1]
    later_target = targets[1] if later_selected == second_op else targets[0]
    later_before = later_target.read_bytes()

    def fail_checkpoint(*args, **kwargs):
        raise OSError("simulated recovery checkpoint failure")

    monkeypatch.setattr(git_ops, "git_checkpoint", fail_checkpoint)
    kb = _load_kb_module()
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(tmp_path), "resume"])
    with pytest.raises(OSError, match="checkpoint failure"):
        kb.main()

    assert selected_target.read_text(encoding="utf-8").startswith("v")
    assert later_target.read_bytes() == later_before
    assert load_op(tmp_path, first_selected)["state"] == "begin"
    assert load_op(tmp_path, later_selected)["state"] == "begin"


def test_resume_terminalizes_root_last_and_retries_after_descendant_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "root-last.md"
    target.parent.mkdir(parents=True)
    target.write_text("v0\n", encoding="utf-8")
    root_op = begin_op(
        tmp_path,
        "root-last-source",
        [target],
        coordination_scope="workspace-exclusive",
    )
    target.write_text("root-partial\n", encoding="utf-8")
    root_entry = load_op(tmp_path, root_op)
    root_entry["state"] = "abort"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, root_op), root_entry)
    child_op = begin_op(tmp_path, "root-last-child", [target])
    target.write_text("child-partial\n", encoding="utf-8")
    child_entry = load_op(tmp_path, child_op)
    child_entry["parent_op_id"] = root_op
    child_entry["root_op_id"] = root_op
    child_entry["transaction_depth"] = 1
    child_entry["coordination_scope"] = "inherited"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, child_op), child_entry)
    root_entry["state"] = "begin"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, root_op), root_entry)

    monkeypatch.setattr(
        git_ops,
        "git_checkpoint",
        lambda *args, **kwargs: {"committed": False, "files": []},
    )
    real_write = journal._write_journal_yaml
    failed = False

    def fail_child_terminal(project_root: Path, op_id: str, payload: object) -> None:
        nonlocal failed
        if (
            not failed
            and op_id == child_op
            and isinstance(payload, dict)
            and payload.get("state") == "abort"
        ):
            failed = True
            raise OSError("simulated descendant terminalization failure")
        real_write(project_root, op_id, payload)

    monkeypatch.setattr(journal, "_write_journal_yaml", fail_child_terminal)
    with pytest.raises(OSError, match="descendant terminalization"):
        restore_operation(tmp_path, root_op, recovery_type="resume")

    assert load_op(tmp_path, root_op)["state"] == "begin"
    assert load_op(tmp_path, child_op)["state"] == "begin"
    result = restore_operation(tmp_path, root_op, recovery_type="resume")
    assert result["recovery_op_id"]
    assert target.read_text(encoding="utf-8") == "v0\n"
    assert load_op(tmp_path, child_op)["state"] == "abort"
    assert load_op(tmp_path, root_op)["state"] == "abort"


def test_leaf_symlink_is_snapshotted_and_restored_as_lexical_target(tmp_path: Path) -> None:
    real = tmp_path / "kb" / "notes" / "real.txt"
    real.parent.mkdir(parents=True)
    real.write_text("referent\n", encoding="utf-8")
    alias = real.parent / "alias.txt"
    alias.symlink_to("real.txt")
    operation_id = ""

    with pytest.raises(RuntimeError, match="force lexical abort"):
        with journaled_op(tmp_path, "replace-leaf-symlink", [alias]) as operation_id:
            alias.unlink()
            alias.write_text("replacement\n", encoding="utf-8")
            raise RuntimeError("force lexical abort")

    assert operation_id
    entry = load_op(tmp_path, operation_id)
    assert entry["target_paths"] == ["notes/alias.txt"]
    assert entry["before_snapshots"]["notes/alias.txt"]["kind"] == "symlink"
    assert alias.is_symlink()
    assert os.readlink(alias) == "real.txt"
    assert real.read_text(encoding="utf-8") == "referent\n"


@pytest.mark.parametrize("link_kind", ("dangling", "relative", "absolute-outside"))
def test_leaf_symlink_abort_preserves_exact_link_text_and_never_touches_referent(
    tmp_path: Path,
    link_kind: str,
) -> None:
    notes = tmp_path / "kb" / "notes"
    notes.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-sentinel\n", encoding="utf-8")
    link_text = {
        "dangling": "missing.txt",
        "relative": "../outside.txt",
        "absolute-outside": outside.as_posix(),
    }[link_kind]
    alias = notes / "alias.txt"
    alias.symlink_to(link_text)

    with pytest.raises(RuntimeError, match="force exact-link abort"):
        with journaled_op(tmp_path, "exact-link-abort", [alias]):
            alias.unlink()
            alias.write_text("replacement\n", encoding="utf-8")
            raise RuntimeError("force exact-link abort")

    assert alias.is_symlink()
    assert os.readlink(alias) == link_text
    assert outside.read_text(encoding="utf-8") == "outside-sentinel\n"


def test_committed_leaf_symlink_undo_uses_lexical_git_scope(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    notes = tmp_path / "kb" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    alias = notes / "alias.txt"
    alias.symlink_to("missing-before.txt")
    git_checkpoint(tmp_path, "seed lexical symlink", auto_init=False, target_paths=[alias])

    with mutation_transaction(tmp_path, "change-lexical-symlink", [alias]):
        alias.unlink()
        alias.symlink_to("missing-after.txt")
    git_checkpoint(tmp_path, "checkpoint changed symlink", auto_init=False, target_paths=[alias])
    undo_last_operation(tmp_path)

    assert alias.is_symlink()
    assert os.readlink(alias) == "missing-before.txt"
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "ls-files", "--", "notes/alias.txt"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert tracked == ["notes/alias.txt"]


@pytest.mark.parametrize(
    "unsafe_target",
    ("absolute-key", "parent-key", "noncanonical-key"),
)
def test_target_path_rejects_unsafe_journal_keys(tmp_path: Path, unsafe_target: str) -> None:
    key = {
        "absolute-key": "/outside",
        "parent-key": "../outside",
        "noncanonical-key": "notes/../outside",
    }[unsafe_target]
    with pytest.raises(SystemExit):
        target_path(tmp_path, key)
    assert not (tmp_path / "kb" / ".journal").exists()


@pytest.mark.parametrize("unsafe_kind", ("outside", "parent-traversal", "symlink-ancestor"))
def test_declared_unsafe_target_fails_before_journal_and_business_write(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if unsafe_kind == "outside":
        declared = outside / "record.yaml"
    elif unsafe_kind == "parent-traversal":
        declared = Path(os.fspath(kb_root) + "/notes/../escaped.yaml")
    else:
        (kb_root / "linked").symlink_to(outside, target_is_directory=True)
        declared = kb_root / "linked" / "record.yaml"
    entered = False

    with pytest.raises(SystemExit):
        with mutation_transaction(tmp_path, "unsafe-declared-target", [declared]):
            entered = True
            declared.write_text("unsafe\n", encoding="utf-8")

    assert entered is False
    assert not (kb_root / ".journal").exists()
    assert not (outside / "record.yaml").exists()


@pytest.mark.parametrize("stage", ("snapshot", "commit-digest", "restore-digest"))
def test_anchored_journal_path_rejects_ancestor_swap_without_touching_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    notes = tmp_path / "kb" / "notes"
    notes.mkdir(parents=True)
    target = notes / "victim.txt"
    target.write_text("inside-before\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_target = outside / "victim.txt"
    outside_target.write_text("outside-sentinel\n", encoding="utf-8")
    operation_id = ""
    if stage != "snapshot":
        operation_id = begin_op(tmp_path, "anchored-source", [target])
        target.write_text("inside-after\n", encoding="utf-8")
        if stage == "restore-digest":
            commit_op(tmp_path, operation_id)

    real_anchored_parent = journal._anchored_target_parent
    swapped = False

    @contextmanager
    def swap_before_open(project_root: Path, key: str, *, create_missing: bool = False):
        nonlocal swapped
        if not swapped and key == "notes/victim.txt":
            swapped = True
            os.replace(notes, tmp_path / "parked-notes")
            notes.symlink_to(outside, target_is_directory=True)
        with real_anchored_parent(project_root, key, create_missing=create_missing) as anchored:
            yield anchored

    monkeypatch.setattr(journal, "_anchored_target_parent", swap_before_open)
    with pytest.raises(SystemExit, match="ancestor"):
        if stage == "snapshot":
            begin_op(tmp_path, "anchored-snapshot", [target])
        elif stage == "commit-digest":
            commit_op(tmp_path, operation_id)
        else:
            restore_operation(tmp_path, operation_id)

    assert swapped is True
    assert outside_target.read_text(encoding="utf-8") == "outside-sentinel\n"


def test_journal_entry_read_detects_ctime_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "ctime.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    operation_id = begin_op(tmp_path, "ctime-source", [target])
    entry_path = journal_entry_path(tmp_path, operation_id)
    original_read = journal._read_anchored_regular
    changed = False

    def mutate_after_read(parent_fd: int, name: str, metadata: os.stat_result) -> bytes:
        nonlocal changed
        raw = original_read(parent_fd, name, metadata)
        if name == entry_path.name and not changed:
            changed = True
            replacement = raw.replace(b"ctime-source", b"ctime-change", 1)
            assert len(replacement) == len(raw)
            descriptor = os.open(name, os.O_WRONLY, dir_fd=parent_fd)
            try:
                os.write(descriptor, replacement)
            finally:
                os.close(descriptor)
            os.utime(
                name,
                ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        return raw

    monkeypatch.setattr(journal, "_read_anchored_regular", mutate_after_read)
    with pytest.raises(SystemExit, match="读取期间发生变化"):
        journal.load_op_view(tmp_path, operation_id)
    assert changed is True


def test_snapshot_creation_rejects_journal_root_swap_without_outside_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "snapshot-root.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    parked = tmp_path / "parked-journal"
    outside = tmp_path / "outside-journal"
    outside.mkdir()
    original_snapshot = journal._snapshot_target
    swapped = False

    def swap_before_snapshot(project_root: Path, op_id: str, key: str) -> dict:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.replace(tmp_path / "kb" / ".journal", parked)
            (tmp_path / "kb" / ".journal").symlink_to(outside, target_is_directory=True)
        return original_snapshot(project_root, op_id, key)

    monkeypatch.setattr(journal, "_snapshot_target", swap_before_snapshot)
    with pytest.raises((SystemExit, RuntimeError)):
        begin_op(tmp_path, "journal-root-swap", [target])

    assert swapped is True
    assert list(outside.iterdir()) == []
    assert target.read_text(encoding="utf-8") == "before\n"


@pytest.mark.parametrize("target_kind", ("file", "directory"))
def test_restore_rejects_snapshot_ancestor_swap_before_target_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    target = tmp_path / "kb" / "notes" / ("victim.txt" if target_kind == "file" else "victim")
    target.parent.mkdir(parents=True)
    if target_kind == "file":
        target.write_text("before\n", encoding="utf-8")
    else:
        target.mkdir()
        (target / "child.txt").write_text("before\n", encoding="utf-8")
    operation_id = begin_op(tmp_path, "snapshot-ancestor-source", [target])
    entry = load_op(tmp_path, operation_id)
    if target_kind == "file":
        target.write_text("partial\n", encoding="utf-8")
    else:
        (target / "child.txt").write_text("partial\n", encoding="utf-8")

    key = entry["target_paths"][0]
    snapshot_path = str(entry["before_snapshots"][key]["snapshot_path"])
    outside = tmp_path / "outside-journal"
    outside_payload = outside / snapshot_path
    if target_kind == "file":
        outside_payload.parent.mkdir(parents=True)
        outside_payload.write_text("outside-evil\n", encoding="utf-8")
    else:
        outside_payload.mkdir(parents=True)
        (outside_payload / "child.txt").write_text("outside-evil\n", encoding="utf-8")
    outside_sentinel = outside / "sentinel.txt"
    outside_sentinel.write_text("outside-sentinel\n", encoding="utf-8")
    parked = tmp_path / "parked-journal"
    original_restore = journal._restore_target
    swapped = False

    def swap_before_restore(project_root: Path, restore_key: str, snapshot: dict) -> Path:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.replace(tmp_path / "kb" / ".journal", parked)
            (tmp_path / "kb" / ".journal").symlink_to(outside, target_is_directory=True)
        return original_restore(project_root, restore_key, snapshot)

    monkeypatch.setattr(journal, "_restore_target", swap_before_restore)
    with pytest.raises((SystemExit, RuntimeError)):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert swapped is True
    if target_kind == "file":
        assert target.read_text(encoding="utf-8") == "partial\n"
    else:
        assert (target / "child.txt").read_text(encoding="utf-8") == "partial\n"
    assert outside_sentinel.read_text(encoding="utf-8") == "outside-sentinel\n"


def test_replace_staged_preserves_previous_when_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.txt"
    staged = tmp_path / ".target.txt.staged"
    target.write_text("old\n", encoding="utf-8")
    staged.write_text("new\n", encoding="utf-8")
    parent_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original_replace = journal.os.replace
    calls = 0

    def fail_publish_and_rollback(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_replace(*args, **kwargs)
        if calls == 2:
            raise OSError("publish failed")
        raise OSError("rollback failed")

    monkeypatch.setattr(journal.os, "replace", fail_publish_and_rollback)
    try:
        with pytest.raises(RuntimeError, match="backup preserved"):
            journal._replace_staged_at(
                parent_fd,
                staged.name,
                target.name,
                expected_digest=str(journal._anchored_node_digest_at(parent_fd, staged.name)),
            )
    finally:
        os.close(parent_fd)

    backups = list(tmp_path.glob(".target.txt.previous-*"))
    assert not target.exists()
    assert not staged.exists()
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old\n"


def _restore_fixture(tmp_path: Path, target_kind: str) -> tuple[Path, str, dict, Path | None]:
    target = tmp_path / "kb" / "notes" / "durable-target"
    target.parent.mkdir(parents=True)
    outside: Path | None = None
    if target_kind == "file":
        target.write_bytes(b"old file bytes\n")
        os.chmod(target, 0o640)
    elif target_kind == "directory":
        outside = tmp_path / "outside-tree-referent.txt"
        outside.write_bytes(b"outside tree bytes\n")
        target.mkdir()
        os.chmod(target, 0o750)
        (target / "child.txt").write_bytes(b"old tree bytes\n")
        os.chmod(target / "child.txt", 0o600)
        (target / "child-link").symlink_to("child.txt")
        (target / "outside-link").symlink_to(outside)
    elif target_kind == "symlink":
        outside = tmp_path / "outside-referent.txt"
        outside.write_bytes(b"outside bytes\n")
        target.symlink_to(outside)
    elif target_kind != "absent":
        raise AssertionError(target_kind)

    operation_id = begin_op(tmp_path, f"durable-{target_kind}", [target])
    entry = load_op(tmp_path, operation_id)
    if target_kind == "file":
        target.write_bytes(b"new file bytes\n")
        os.chmod(target, 0o600)
    elif target_kind == "directory":
        parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            journal._remove_at(parent_fd, target.name)
        finally:
            os.close(parent_fd)
        target.mkdir()
        (target / "replacement.txt").write_bytes(b"new tree bytes\n")
    elif target_kind == "symlink":
        target.unlink()
        target.symlink_to("concurrent-link-target")
    else:
        target.write_bytes(b"created after absent snapshot\n")
    return target, operation_id, entry, outside


@pytest.mark.parametrize("target_kind", ["file", "directory", "symlink", "absent"])
def test_restore_fsyncs_anchored_parent_for_every_snapshot_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    target, operation_id, entry, outside = _restore_fixture(tmp_path, target_kind)
    parent_identity = target.parent.stat()
    original_fsync = journal.os.fsync
    parent_fsyncs = 0

    def record_parent_fsync(descriptor: int) -> None:
        nonlocal parent_fsyncs
        if journal._same_node(parent_identity, os.fstat(descriptor)):
            parent_fsyncs += 1
        original_fsync(descriptor)

    monkeypatch.setattr(journal.os, "fsync", record_parent_fsync)
    journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert parent_fsyncs >= 1
    if target_kind == "file":
        assert target.read_bytes() == b"old file bytes\n"
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
    elif target_kind == "directory":
        assert (target / "child.txt").read_bytes() == b"old tree bytes\n"
        assert stat.S_IMODE(target.stat().st_mode) == 0o750
        assert os.readlink(target / "child-link") == "child.txt"
        assert outside is not None
        assert Path(os.readlink(target / "outside-link")) == outside
        assert outside.read_bytes() == b"outside tree bytes\n"
    elif target_kind == "symlink":
        assert outside is not None
        assert target.is_symlink()
        assert Path(os.readlink(target)) == outside
        assert outside.read_bytes() == b"outside bytes\n"
    else:
        assert not target.exists()


@pytest.mark.parametrize("target_kind", ["file", "directory", "symlink"])
def test_post_publish_parent_fsync_failure_rolls_back_exact_old_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    target, operation_id, entry, outside = _restore_fixture(tmp_path, target_kind)
    state_before_restore = _tree_lstat_state(target) if target_kind == "directory" else None
    current_before_restore = _lstat_state(target) if target_kind != "directory" else None
    parent_identity = target.parent.stat()
    original_fsync = journal.os.fsync
    failed = False

    def fail_first_parent_fsync(descriptor: int) -> None:
        nonlocal failed
        if not failed and journal._same_node(parent_identity, os.fstat(descriptor)):
            failed = True
            raise OSError("post-publish parent fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(journal.os, "fsync", fail_first_parent_fsync)
    with pytest.raises(OSError, match="post-publish parent fsync failed"):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert failed is True
    if target_kind == "directory":
        assert _tree_lstat_state(target) != state_before_restore
        assert (target / "replacement.txt").read_bytes() == b"new tree bytes\n"
        assert not (target / "child.txt").exists()
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
        assert outside is not None and outside.read_bytes() == b"outside tree bytes\n"
    elif target_kind == "file":
        assert current_before_restore is not None
        assert target.read_bytes() == b"new file bytes\n"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    else:
        assert current_before_restore is not None
        assert os.readlink(target) == "concurrent-link-target"
        assert outside is not None and outside.read_bytes() == b"outside bytes\n"
    assert list(target.parent.glob(f".{target.name}.restore-*")) == []
    assert list(target.parent.glob(f".{target.name}.rollback-*")) == []
    assert list(target.parent.glob(f".{target.name}.previous-*")) == []


def test_post_publish_fsync_failure_restores_original_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, operation_id, entry, _ = _restore_fixture(tmp_path, "file")
    target.unlink()
    parent_identity = target.parent.stat()
    original_fsync = journal.os.fsync
    failed = False

    def fail_first_parent_fsync(descriptor: int) -> None:
        nonlocal failed
        if not failed and journal._same_node(parent_identity, os.fstat(descriptor)):
            failed = True
            raise OSError("post-publish parent fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(journal.os, "fsync", fail_first_parent_fsync)
    with pytest.raises(OSError, match="post-publish parent fsync failed"):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert failed is True
    assert not target.exists()
    assert list(target.parent.glob(f".{target.name}.restore-*")) == []
    assert list(target.parent.glob(f".{target.name}.failed-*")) == []


def test_absent_snapshot_parent_fsync_failure_restores_removed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, operation_id, entry, _ = _restore_fixture(tmp_path, "absent")
    os.chmod(target, 0o640)
    expected_bytes = target.read_bytes()
    parent_identity = target.parent.stat()
    original_fsync = journal.os.fsync
    failed = False

    def fail_first_parent_fsync(descriptor: int) -> None:
        nonlocal failed
        if not failed and journal._same_node(parent_identity, os.fstat(descriptor)):
            failed = True
            raise OSError("absent removal parent fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(journal.os, "fsync", fail_first_parent_fsync)
    with pytest.raises(OSError, match="absent removal parent fsync failed"):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert failed is True
    assert target.read_bytes() == expected_bytes
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert list(target.parent.glob(f".{target.name}.previous-*")) == []
    assert list(target.parent.glob(f".{target.name}.rollback-*")) == []


def test_verification_mismatch_after_replace_rolls_back_previous_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, operation_id, entry, _ = _restore_fixture(tmp_path, "file")
    original_replace = journal.os.replace

    def corrupt_after_publish(source, destination, *args, **kwargs):
        result = original_replace(source, destination, *args, **kwargs)
        if str(source).startswith(f".{target.name}.restore-file-") and destination == target.name:
            descriptor = os.open(
                target.name,
                os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=kwargs["dst_dir_fd"],
            )
            try:
                os.write(descriptor, b"corrupt after publication\n")
            finally:
                os.close(descriptor)
        return result

    monkeypatch.setattr(journal.os, "replace", corrupt_after_publish)
    with pytest.raises(RuntimeError, match="digest verification"):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert target.read_bytes() == b"new file bytes\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(target.parent.glob(f".{target.name}.previous-*")) == []


def test_concurrent_replacement_before_rollback_is_not_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, operation_id, entry, _ = _restore_fixture(tmp_path, "file")
    parent_identity = target.parent.stat()
    original_fsync = journal.os.fsync
    replaced = False

    def replace_target_then_fail(descriptor: int) -> None:
        nonlocal replaced
        if not replaced and journal._same_node(parent_identity, os.fstat(descriptor)):
            concurrent = target.parent / ".concurrent-target"
            concurrent.write_bytes(b"concurrent bytes\n")
            os.replace(concurrent, target)
            replaced = True
            raise OSError("post-publish parent fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(journal.os, "fsync", replace_target_then_fail)
    with pytest.raises(RuntimeError, match="backup preserved"):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert replaced is True
    assert target.read_bytes() == b"concurrent bytes\n"
    backups = list(target.parent.glob(f".{target.name}.previous-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"new file bytes\n"


def test_rollback_parent_fsync_failure_preserves_unique_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, operation_id, entry, _ = _restore_fixture(tmp_path, "file")
    parent_identity = target.parent.stat()
    original_fsync = journal.os.fsync
    parent_calls = 0

    def fail_publish_and_rollback_fsync(descriptor: int) -> None:
        nonlocal parent_calls
        if journal._same_node(parent_identity, os.fstat(descriptor)):
            parent_calls += 1
            if parent_calls <= 2:
                raise OSError(f"parent fsync failure {parent_calls}")
        original_fsync(descriptor)

    monkeypatch.setattr(journal.os, "fsync", fail_publish_and_rollback_fsync)
    with pytest.raises(RuntimeError, match="backup preserved"):
        journal.restore_before_snapshots(tmp_path, operation_id, source_entry=entry)

    assert parent_calls == 2
    backups = list(target.parent.glob(f".{target.name}.previous-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"new file bytes\n"
    assert target.read_bytes() == b"new file bytes\n"


@pytest.mark.parametrize("reader", ("single", "enumeration"))
def test_journal_entry_reads_fail_closed_when_root_is_swapped_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
) -> None:
    target = tmp_path / "kb" / "notes" / "entry-root.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    operation_id = begin_op(tmp_path, "entry-root-source", [target])
    parked = tmp_path / "parked-journal"
    outside = tmp_path / "outside-journal"
    outside.mkdir()
    outside_entry = outside / f"{operation_id}.yaml"
    outside_entry.write_text("outside-sentinel\n", encoding="utf-8")
    original_root = journal._anchored_journal_root_fd
    swapped = False

    @contextmanager
    def swap_after_root_open(project_root: Path, *, create: bool = False):
        nonlocal swapped
        with original_root(project_root, create=create) as descriptor:
            if descriptor is not None and not swapped:
                swapped = True
                os.replace(tmp_path / "kb" / ".journal", parked)
                (tmp_path / "kb" / ".journal").symlink_to(outside, target_is_directory=True)
            yield descriptor

    monkeypatch.setattr(journal, "_anchored_journal_root_fd", swap_after_root_open)
    with pytest.raises(SystemExit, match="访问期间发生变化"):
        if reader == "single":
            journal.load_op_view(tmp_path, operation_id)
        else:
            incomplete_ops(tmp_path)

    assert swapped is True
    assert outside_entry.read_text(encoding="utf-8") == "outside-sentinel\n"
    assert (parked / f"{operation_id}.yaml").exists()


def test_workspace_lock_rejects_journal_root_swap_without_outside_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "kb").mkdir()
    journal._ensure_journal_runtime(tmp_path)
    parked = tmp_path / "parked-journal"
    outside = tmp_path / "outside-journal"
    outside.mkdir()
    original_preflight = git_ops._preflight_journal_envelopes
    swapped = False

    def swap_after_preflight(project_root: Path) -> None:
        nonlocal swapped
        original_preflight(project_root)
        if not swapped:
            swapped = True
            os.replace(tmp_path / "kb" / ".journal", parked)
            (tmp_path / "kb" / ".journal").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(git_ops, "_preflight_journal_envelopes", swap_after_preflight)
    with pytest.raises((SystemExit, RuntimeError)):
        ensure_kb_git_repo(tmp_path, create_initial_commit=False)

    assert swapped is True
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "kb" / ".git").exists()


def test_journal_entry_write_stays_anchored_when_root_is_swapped_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "entry-write.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    operation_id = begin_op(tmp_path, "entry-write-source", [target])
    entry = load_op(tmp_path, operation_id)
    entry["op_type"] = "entry-write-changed"
    parked = tmp_path / "parked-journal"
    outside = tmp_path / "outside-journal"
    outside.mkdir()
    outside_entry = outside / f"{operation_id}.yaml"
    outside_entry.write_text("outside-sentinel\n", encoding="utf-8")
    original_root = journal._anchored_journal_root_fd
    swapped = False

    @contextmanager
    def swap_after_write_root_open(project_root: Path, *, create: bool = False):
        nonlocal swapped
        with original_root(project_root, create=create) as descriptor:
            if create and descriptor is not None and not swapped:
                swapped = True
                os.replace(tmp_path / "kb" / ".journal", parked)
                (tmp_path / "kb" / ".journal").symlink_to(outside, target_is_directory=True)
            yield descriptor

    monkeypatch.setattr(journal, "_anchored_journal_root_fd", swap_after_write_root_open)
    with pytest.raises(SystemExit, match="访问期间发生变化"):
        journal._write_journal_yaml(tmp_path, operation_id, entry)

    assert swapped is True
    assert outside_entry.read_text(encoding="utf-8") == "outside-sentinel\n"
    assert b"entry-write-changed" in (parked / f"{operation_id}.yaml").read_bytes()


def test_target_lock_rejects_swapped_runtime_ancestor_without_outside_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "locked.txt"
    target.parent.mkdir(parents=True)
    target.write_text("sentinel\n", encoding="utf-8")
    journal._ensure_journal_runtime(tmp_path)
    locks = tmp_path / "kb" / ".journal" / "locks"
    locks.mkdir()
    parked = tmp_path / "parked-locks"
    outside = tmp_path / "outside-locks"
    outside.mkdir()
    original_parent = journal._anchored_journal_parent
    swapped = False

    @contextmanager
    def swap_before_lock_parent(
        project_root: Path,
        relative_path: str,
        *,
        create_parents: bool = False,
    ):
        nonlocal swapped
        if relative_path.startswith("locks/") and not swapped:
            swapped = True
            os.replace(locks, parked)
            locks.symlink_to(outside, target_is_directory=True)
        with original_parent(
            project_root,
            relative_path,
            create_parents=create_parents,
        ) as anchored:
            yield anchored

    monkeypatch.setattr(journal, "_anchored_journal_parent", swap_before_lock_parent)
    with pytest.raises(RuntimeError, match="safe directory"):
        with journal.operation_lock(tmp_path, target):
            pytest.fail("unsafe target lock unexpectedly acquired")

    assert swapped is True
    assert list(outside.iterdir()) == []
    assert target.read_text(encoding="utf-8") == "sentinel\n"


@pytest.mark.parametrize(
    "tamper",
    (
        "target-missing",
        "target-duplicate",
        "target-noncanonical",
        "before-digest-missing",
        "before-snapshot-extra",
        "after-digest-missing",
        "legacy-snapshots-empty",
        "snapshot-path-escape",
        "snapshot-payload-missing",
        "snapshot-payload-drift",
        "snapshot-kind-invalid",
    ),
)
def test_recovery_rejects_malformed_target_sets_before_any_recovery_write(
    tmp_path: Path,
    tamper: str,
) -> None:
    first = tmp_path / "kb" / "notes" / "a.txt"
    second = tmp_path / "kb" / "notes" / "b.txt"
    first.parent.mkdir(parents=True)
    first.write_text("a0\n", encoding="utf-8")
    second.write_text("b0\n", encoding="utf-8")
    with journaled_op(tmp_path, "two-target-source", [first, second]) as operation_id:
        first.write_text("a1\n", encoding="utf-8")
        second.write_text("b1\n", encoding="utf-8")
    entry = load_op(tmp_path, operation_id)
    first_key, second_key = entry["target_paths"]
    if tamper == "target-missing":
        entry["target_paths"] = [first_key]
    elif tamper == "target-duplicate":
        entry["target_paths"] = [first_key, first_key, second_key]
    elif tamper == "target-noncanonical":
        entry["target_paths"] = ["notes/../notes/a.txt", second_key]
    elif tamper == "before-digest-missing":
        entry["before_digests"].pop(second_key)
    elif tamper == "before-snapshot-extra":
        entry["before_snapshots"]["notes/extra.txt"] = {"kind": "absent", "digest": None}
    elif tamper == "after-digest-missing":
        entry["after_digests"].pop(second_key)
    elif tamper == "legacy-snapshots-empty":
        entry["before_snapshots"] = {}
    elif tamper == "snapshot-path-escape":
        entry["before_snapshots"][first_key]["snapshot_path"] = "../outside"
    elif tamper == "snapshot-payload-missing":
        payload = tmp_path / "kb" / ".journal" / entry["before_snapshots"][first_key]["snapshot_path"]
        payload.unlink()
    elif tamper == "snapshot-payload-drift":
        payload = tmp_path / "kb" / ".journal" / entry["before_snapshots"][first_key]["snapshot_path"]
        payload.write_text("tampered snapshot bytes\n", encoding="utf-8")
    else:
        entry["before_snapshots"][first_key]["kind"] = "unknown"
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, operation_id), entry)
    journal_names = {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")}
    target_state = (_lstat_state(first), _lstat_state(second))

    with pytest.raises(SystemExit):
        restore_operation(tmp_path, operation_id)

    assert (_lstat_state(first), _lstat_state(second)) == target_state
    assert {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")} == journal_names


def test_recovery_rejects_raw_yaml_duplicate_mapping_keys(tmp_path: Path) -> None:
    target = tmp_path / "kb" / "notes" / "duplicate-map.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    with journaled_op(tmp_path, "duplicate-map-source", [target]) as operation_id:
        target.write_text("after\n", encoding="utf-8")
    entry = load_op(tmp_path, operation_id)
    key = entry["target_paths"][0]
    digest = entry["before_digests"][key]
    entry_path = journal_entry_path(tmp_path, operation_id)
    text = entry_path.read_text(encoding="utf-8")
    text = text.replace(
        "before_digests:\n",
        f"before_digests:\n  {key}: {digest}\n",
        1,
    )
    entry_path.write_text(text, encoding="utf-8")
    journal_names = {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")}

    with pytest.raises(SystemExit, match="重复字段"):
        restore_operation(tmp_path, operation_id)

    assert target.read_text(encoding="utf-8") == "after\n"
    assert {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")} == journal_names


def test_recovery_source_byte_cas_rejects_change_after_validation_before_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "kb" / "notes" / "source-cas.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    with journaled_op(tmp_path, "source-cas-operation", [target]) as operation_id:
        target.write_text("after\n", encoding="utf-8")
    real_validate = git_ops.validated_recovery_target_keys
    changed = False

    def mutate_after_validation(project_root: Path, entry: dict, *, require_after: bool):
        nonlocal changed
        keys = real_validate(project_root, entry, require_after=require_after)
        if not changed:
            changed = True
            replacement = load_op(tmp_path, operation_id)
            key = replacement["target_paths"][0]
            replacement["before_snapshots"][key] = {
                "kind": "absent",
                "mode": None,
                "digest": None,
            }
            yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, operation_id), replacement)
        return keys

    monkeypatch.setattr(git_ops, "validated_recovery_target_keys", mutate_after_validation)
    journal_names = {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")}
    with pytest.raises(SystemExit, match="执行前发生变化"):
        restore_operation(tmp_path, operation_id)

    assert changed is True
    assert target.read_text(encoding="utf-8") == "after\n"
    assert {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")} == journal_names


def test_resume_rejects_incomplete_journal_with_partial_snapshot_map(tmp_path: Path) -> None:
    first = tmp_path / "kb" / "notes" / "begin-a.txt"
    second = tmp_path / "kb" / "notes" / "begin-b.txt"
    first.parent.mkdir(parents=True)
    first.write_text("a0\n", encoding="utf-8")
    second.write_text("b0\n", encoding="utf-8")
    operation_id = begin_op(tmp_path, "malformed-begin", [first, second])
    first.write_text("a-partial\n", encoding="utf-8")
    second.write_text("b-partial\n", encoding="utf-8")
    entry = load_op(tmp_path, operation_id)
    entry["before_snapshots"].pop(entry["target_paths"][1])
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, operation_id), entry)
    journal_names = {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")}

    with pytest.raises(SystemExit, match="目标集合"):
        restore_operation(tmp_path, operation_id, recovery_type="resume")

    assert first.read_text(encoding="utf-8") == "a-partial\n"
    assert second.read_text(encoding="utf-8") == "b-partial\n"
    assert {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")} == journal_names


def test_undo_rejects_legacy_journal_without_before_snapshots(tmp_path: Path) -> None:
    target = tmp_path / "kb" / "notes" / "legacy-no-snapshot.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")
    with journaled_op(tmp_path, "legacy-source", [target]) as operation_id:
        target.write_text("after\n", encoding="utf-8")
    entry = load_op(tmp_path, operation_id)
    entry.pop("before_snapshots")
    yaml_io.write_yaml_if_changed(journal_entry_path(tmp_path, operation_id), entry)
    journal_names = {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")}

    with pytest.raises(SystemExit, match="恢复前状态记录"):
        undo_last_operation(tmp_path)

    assert target.read_text(encoding="utf-8") == "after\n"
    assert yaml_io.load_yaml(journal_entry_path(tmp_path, operation_id)).get("undone_by") in (None, "")
    assert {path.name for path in (tmp_path / "kb" / ".journal").glob("*.yaml")} == journal_names


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
    ensure_workspace(tmp_path)
    record = default_record("paper", title="Lock Test", maturity="lightweight")
    record["id"] = "p-lock-test"

    write_record(tmp_path, record)

    locks = list((tmp_path / "kb" / ".journal" / "locks").glob("*.lock"))
    assert len(locks) == 1
    assert locks[0].read_text(encoding="utf-8") == ""
    assert ".journal/" in (tmp_path / "kb" / ".gitignore").read_text(encoding="utf-8")


def test_manager_mutation_transaction_rejects_empty_scope(tmp_path: Path) -> None:
    kb = _load_kb_module()

    with pytest.raises(SystemExit, match="at least one explicit target path"):
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
    git_checkpoint(
        root,
        "initial kb state",
        auto_init=False,
        target_paths=dirty_kb_paths(root),
    )


def test_pending_root_blocks_manual_milestone_and_public_checkpoints_before_git_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "notes" / "pending-checkpoint.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("v0\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed checkpoint target", auto_init=False, target_paths=[target])
    operation_id = begin_op(tmp_path, "stranded-checkpoint-source", [target])
    target.write_text("partial-v1\n", encoding="utf-8")

    def git_state() -> tuple[str, str, str]:
        head = subprocess.run(
            ["git", "-C", str(tmp_path / "kb"), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        index = subprocess.run(
            ["git", "-C", str(tmp_path / "kb"), "ls-files", "--stage"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        status = subprocess.run(
            ["git", "-C", str(tmp_path / "kb"), "status", "--porcelain=v1"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return head, index, status

    before_git = git_state()
    before_journal = {
        path.relative_to(tmp_path / "kb" / ".journal").as_posix(): path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").rglob("*")
        if path.is_file()
    }
    kb = _load_kb_module()

    with pytest.raises(SystemExit, match="kb resume"):
        git_checkpoint(tmp_path, "manual while pending", auto_init=False, target_paths=[target])
    with pytest.raises(SystemExit, match="kb resume"):
        git_ops.maybe_auto_checkpoint(
            tmp_path,
            trigger="milestone",
            message="milestone while pending",
            target_paths=[target],
        )
    with pytest.raises(SystemExit, match="kb resume"):
        ensure_kb_git_repo(tmp_path, create_initial_commit=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["kb.py", "--root", str(tmp_path), "git-checkpoint", "--message", "public pending"],
    )
    with pytest.raises(SystemExit, match="kb resume"):
        kb.main()
    monkeypatch.setattr(
        sys,
        "argv",
        ["kb.py", "--root", str(tmp_path), "git-init", "--no-initial-commit"],
    )
    with pytest.raises(SystemExit, match="kb resume"):
        kb.main()

    assert target.read_text(encoding="utf-8") == "partial-v1\n"
    assert git_state() == before_git
    assert {
        path.relative_to(tmp_path / "kb" / ".journal").as_posix(): path.read_bytes()
        for path in (tmp_path / "kb" / ".journal").rglob("*")
        if path.is_file()
    } == before_journal
    assert load_op(tmp_path, operation_id)["state"] == "begin"


def test_symlinked_journal_root_blocks_checkpoint_without_git_or_target_write(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "notes" / "journal-root-symlink.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("v0\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed symlink-root target", auto_init=False, target_paths=[target])
    real_journal = tmp_path / "saved-journal-runtime"
    os.replace(tmp_path / "kb" / ".journal", real_journal)
    fake_journal = tmp_path / "outside-journal-runtime"
    fake_journal.mkdir()
    (tmp_path / "kb" / ".journal").symlink_to(fake_journal, target_is_directory=True)
    target.write_text("dirty\n", encoding="utf-8")

    def git_state() -> tuple[str, str, str]:
        return tuple(
            subprocess.run(
                ["git", "-C", str(tmp_path / "kb"), *args],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            for args in (
                ("rev-parse", "HEAD"),
                ("ls-files", "--stage"),
                ("status", "--porcelain=v1"),
            )
        )

    before = git_state()
    with pytest.raises(SystemExit, match="恢复隔离状态"):
        git_checkpoint(tmp_path, "must not checkpoint", auto_init=False, target_paths=[target])

    assert git_state() == before
    assert target.read_text(encoding="utf-8") == "dirty\n"
    assert list(fake_journal.iterdir()) == []


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


def test_paper_checkpoint_skips_absent_optional_artifacts_and_preserves_dirty_drafts(
    tmp_path: Path,
) -> None:
    """Paper verify declares optional figure outputs even when it creates none."""
    _configure_kb_git(tmp_path)
    unit = tmp_path / "kb" / "units" / "papers" / "p-optional-figures"
    record = unit / "record.yaml"
    note = unit / "note.md"
    claims = unit / "note-claims.yaml"
    structure = unit / "structure.yaml"
    figures_yaml = unit / "figures.yaml"
    figures = unit / "figures"
    tracked_draft = tmp_path / "kb" / "notes" / "tracked-draft.md"
    untracked_draft = tmp_path / "kb" / "notes" / "untracked-draft.md"

    tracked_draft.parent.mkdir(parents=True)
    tracked_draft.write_text("original draft\n", encoding="utf-8")
    git_checkpoint(
        tmp_path,
        "seed tracked draft",
        auto_init=False,
        target_paths=[tracked_draft],
    )

    unit.mkdir(parents=True)
    record.write_text("id: p-optional-figures\n", encoding="utf-8")
    note.write_text("# Verified note\n", encoding="utf-8")
    claims.write_text("claims: []\n", encoding="utf-8")
    structure.write_text("sections: []\n", encoding="utf-8")
    tracked_draft.write_text("user staged draft\n", encoding="utf-8")
    untracked_draft.write_text("user untracked draft\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "add", "--", "notes/tracked-draft.md"],
        check=True,
    )

    result = git_checkpoint(
        tmp_path,
        "verify paper note",
        auto_init=False,
        target_paths=[record, note, claims, structure, figures_yaml, figures],
    )

    expected = {
        "units/papers/p-optional-figures/note-claims.yaml",
        "units/papers/p-optional-figures/note.md",
        "units/papers/p-optional-figures/record.yaml",
        "units/papers/p-optional-figures/structure.yaml",
    }
    assert result["committed"] is True
    assert set(result["files"]) == expected
    committed = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "show", "--format=", "--name-only", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert {line for line in committed if line} == expected
    status = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "M  notes/tracked-draft.md" in status
    assert "?? notes/untracked-draft.md" in status
    assert not figures_yaml.exists()
    assert not figures.exists()


def test_paper_complete_note_verify_checkpoints_without_optional_figures(tmp_path: Path) -> None:
    """Exercise the real paper command wrapper that exposed the optional-path bug."""
    paper = _load_paper_module()
    _configure_kb_git(tmp_path)
    paper_id = "p-checkpoint-optional"
    record = default_record("paper", title="Optional figure regression", maturity="lightweight")
    record["id"] = paper_id
    record["status"] = "screened"
    record["payload"]["quick_screen"]["paper_type"] = "method_system"
    record_path = write_record(tmp_path, record)
    unit = record_path.parent
    source_text = (
        "Motivation evidence describes the research gap. "
        "Method evidence describes the proposed mechanism. "
        "Experiment evidence compares the measured outcome. "
        "Limitation evidence identifies the failure case. "
        "Insight evidence explains why the mechanism works."
    )
    chunks = [
        {
            "label": "source.pdf:page-1",
            "text": source_text,
            "page": 1,
            "locator": "page=1",
            "locator_kind": "page",
        }
    ]
    cache = unit / "parse-cache.yaml"
    yaml_io.write_yaml_if_changed(
        cache,
        {
            "unit_id": paper_id,
            "paper_id": paper_id,
            "source_type": "pdf",
            "locator_kind": "page",
            "chunks": chunks,
        },
    )
    quotes = {
        "motivation": "Motivation evidence describes the research gap",
        "method": "Method evidence describes the proposed mechanism",
        "experiment": "Experiment evidence compares the measured outcome",
        "limitation": "Limitation evidence identifies the failure case",
        "insight": "Insight evidence explains why the mechanism works",
    }
    fill_path = unit / "note-fill.yaml"
    yaml_io.write_yaml_if_changed(
        fill_path,
        paper.build_note_scaffold(record, chunks, "page", digest_chunks=1, digest_chars=1200),
    )
    git_checkpoint(
        tmp_path,
        "seed paper inputs",
        auto_init=False,
        target_paths=[record_path, cache, fill_path],
    )
    yaml_io.write_yaml_if_changed(
        fill_path,
        {
            "elements": [
                {
                    "element": element,
                    "claim_type": paper.ELEMENT_CLAIM_TYPE[element],
                    "content": f"Agent-authored {element} synthesis.",
                    "evidence_refs": [
                        {
                            "source_unit_id": paper_id,
                            "artifact": "parse-cache.yaml",
                            "locator": "page=1",
                            "quote": quote,
                            "summary": f"Evidence for {element}.",
                        }
                    ],
                }
                for element, quote in quotes.items()
            ]
        },
    )
    loaded = load_yaml(record_path)
    args = SimpleNamespace(
        phase="verify",
        mode="scaffold",
        input="",
        paper_id=paper_id,
    )

    assert paper._run_complete_note(
        args,
        tmp_path,
        loaded,
        unit,
        cache,
        chunks,
        {
            "auto_refresh_structure_after_note": True,
            "auto_extract_figures_after_note": False,
        },
        False,
    ) == 0

    assert (unit / "note.md").exists()
    assert (unit / "note-claims.yaml").exists()
    assert (unit / "structure.yaml").exists()
    assert not (unit / "figures.yaml").exists()
    assert not (unit / "figures").exists()
    committed = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "show", "--format=", "--name-only", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "units/papers/p-checkpoint-optional/note-fill.yaml" in committed
    assert "note-fill.yaml" not in subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_git_checkpoint_commits_tracked_deletion_with_absent_optional_target(
    tmp_path: Path,
) -> None:
    _configure_kb_git(tmp_path)
    target = tmp_path / "kb" / "units" / "papers" / "p-deleted" / "figures.yaml"
    optional = target.parent / "figures"
    target.parent.mkdir(parents=True)
    target.write_text("figures: []\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed tracked artifact", auto_init=False, target_paths=[target])
    target.unlink()
    subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "add", "--all", "--", "units/papers/p-deleted/figures.yaml"],
        check=True,
    )

    result = git_checkpoint(
        tmp_path,
        "remove tracked artifact",
        auto_init=False,
        target_paths=[target, optional],
    )

    assert result["committed"] is True
    assert result["files"] == ["units/papers/p-deleted/figures.yaml"]
    change = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "show", "--format=", "--name-status", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert change == "D\tunits/papers/p-deleted/figures.yaml"


def test_git_checkpoint_all_absent_optional_targets_is_noop(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    unit = tmp_path / "kb" / "units" / "papers" / "p-no-artifacts"

    before = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = git_checkpoint(
        tmp_path,
        "optional artifacts absent",
        auto_init=False,
        target_paths=[unit / "figures.yaml", unit / "figures"],
    )
    after = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert result == {
        "committed": False,
        "status": "no-changes",
        "message": "no checkpointable kb changes to commit",
    }
    assert after == before


def test_git_checkpoint_existing_empty_optional_directory_is_noop(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    optional = tmp_path / "kb" / "units" / "papers" / "p-empty" / "figures"
    optional.mkdir(parents=True)

    result = git_checkpoint(
        tmp_path,
        "empty optional directory",
        auto_init=False,
        target_paths=[optional],
    )

    assert result["committed"] is False
    assert result["status"] == "no-changes"


def test_git_checkpoint_ignored_only_optional_directory_is_noop(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    gitignore = tmp_path / "kb" / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + "optional-cache/\n", encoding="utf-8")
    git_checkpoint(tmp_path, "ignore optional cache", auto_init=False, target_paths=[gitignore])
    optional = tmp_path / "kb" / "optional-cache"
    optional.mkdir()
    (optional / "artifact.txt").write_text("ignored\n", encoding="utf-8")

    result = git_checkpoint(
        tmp_path,
        "ignored optional directory",
        auto_init=False,
        target_paths=[optional],
    )

    assert result["committed"] is False
    assert result["status"] == "no-changes"
    status = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""


def test_git_checkpoint_treats_optional_pathspec_metacharacters_as_literal(
    tmp_path: Path,
) -> None:
    _configure_kb_git(tmp_path)
    tracked = tmp_path / "kb" / "notes" / "actual.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("original\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed actual note", auto_init=False, target_paths=[tracked])
    tracked.write_text("user draft\n", encoding="utf-8")

    result = git_checkpoint(
        tmp_path,
        "literal optional target",
        auto_init=False,
        target_paths=[tmp_path / "kb" / "notes" / "*.md"],
    )

    assert result["committed"] is False
    status = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert " M notes/actual.md" in status


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


@pytest.mark.parametrize("journal_state", ["absent", "empty"])
def test_undo_without_candidate_does_not_materialize_or_change_runtime_tree(
    tmp_path: Path,
    journal_state: str,
) -> None:
    if journal_state == "empty":
        (tmp_path / "kb" / ".journal").mkdir(parents=True)

    def runtime_tree_snapshot():
        paths = [tmp_path, *sorted(tmp_path.rglob("*"))]
        return {
            path.relative_to(tmp_path).as_posix() or ".": (
                path.lstat().st_mode,
                path.lstat().st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
            for path in paths
        }

    before = runtime_tree_snapshot()

    with pytest.raises(SystemExit, match="没有可撤销的已提交操作"):
        undo_last_operation(tmp_path)

    assert runtime_tree_snapshot() == before
    if journal_state == "absent":
        assert not (tmp_path / "kb").exists()
    else:
        assert list((tmp_path / "kb" / ".journal").iterdir()) == []


def test_concurrent_undo_reselects_latest_candidate_inside_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_kb_git(tmp_path)
    record = default_record("paper", title="First Title", maturity="lightweight")
    record["id"] = "p-concurrent-undo"
    path = write_record(tmp_path, record)
    git_checkpoint(tmp_path, "create concurrent undo record", auto_init=False, target_paths=[path])
    first_op = [entry for entry in committed_ops(tmp_path) if entry["op_type"] == "write_record"][-1]

    updated = load_yaml(path)
    updated["title"] = "Second Title"
    write_record(tmp_path, updated, expected_revision=1)
    git_checkpoint(tmp_path, "update concurrent undo record", auto_init=False, target_paths=[path])
    second_op = [entry for entry in committed_ops(tmp_path) if entry["op_type"] == "write_record"][-1]

    real_latest_committed_op = git_ops.latest_committed_op
    preflight_reads_complete = threading.Barrier(2)
    thread_state = threading.local()

    def synchronized_latest_committed_op(project_root: Path):
        call_count = getattr(thread_state, "call_count", 0) + 1
        thread_state.call_count = call_count
        entry = real_latest_committed_op(project_root)
        if call_count == 1:
            preflight_reads_complete.wait(timeout=5)
        return entry

    monkeypatch.setattr(git_ops, "latest_committed_op", synchronized_latest_committed_op)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: undo_last_operation(tmp_path), range(2)))

    assert {result["op_id"] for result in results} == {first_op["op_id"], second_op["op_id"]}
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

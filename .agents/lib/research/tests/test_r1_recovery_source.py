from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

import research.journal as journal
import research.sources as sources
from research.git_ops import (
    checkpoint_and_report,
    dirty_kb_paths,
    ensure_kb_git_repo,
    git_checkpoint,
    maybe_auto_checkpoint,
    restore_operation,
    undo_last_operation,
)
from research.common import (
    append_program_reporting_event,
    current_runtime_capabilities,
    inspect_python_runtime,
    program_reporting_events_path,
)
from research.confirm import write_record
from research.journal import (
    abort_op,
    begin_op,
    commit_op,
    committed_ops,
    incomplete_ops,
    journal_entry_path,
    journal_subprocess_env,
    journaled_op,
    latest_committed_op,
    load_op,
    mutation_transaction,
    operation_lock_path,
)
from research.records import default_record
from research.prefs import ensure_workspace
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


def _load_config_module():
    script = _project_root() / ".agents" / "skills" / "research-config-manager" / "scripts" / "config.py"
    spec = importlib.util.spec_from_file_location("r1_research_config_script", script)
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


def test_fresh_workspace_mutation_bootstrap_never_writes_gitignore_outside_targets(tmp_path: Path) -> None:
    bare_root = tmp_path / "bare"
    operation_lock_path(bare_root, bare_root / "kb" / "notes" / "probe.md")
    assert (bare_root / "kb" / ".journal").is_dir()
    assert not (bare_root / "kb" / ".gitignore").exists()

    ensure_workspace(tmp_path)
    gitignore = tmp_path / "kb" / ".gitignore"
    before = gitignore.read_bytes()
    assert b".journal/" in before
    target = tmp_path / "kb" / "notes" / "bootstrap-abort.md"

    with pytest.raises(RuntimeError, match="abort fresh mutation"):
        with mutation_transaction(tmp_path, "fresh-workspace-mutation", [target]):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("partial\n", encoding="utf-8")
            raise RuntimeError("abort fresh mutation")

    assert gitignore.read_bytes() == before
    assert not target.exists()
    entries = [
        load_yaml(path)
        for path in (tmp_path / "kb" / ".journal").glob("*.yaml")
        if load_yaml(path).get("op_type") == "fresh-workspace-mutation"
    ]
    assert len(entries) == 1
    assert entries[0]["target_paths"] == ["notes/bootstrap-abort.md"]
    assert entries[0]["state"] == "abort"


def test_two_hundred_concurrent_reporting_appends_are_lossless_and_parseable(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
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

    with mutation_transaction(tmp_path, "outer-governance-mutation", [path]):
        written = write_record(tmp_path, record)

    assert written == path
    assert load_yaml(path)["revision"] == 1


def test_independent_descendant_waits_for_ancestor_abort_then_commits_without_clobber(tmp_path: Path) -> None:
    unit_dir = tmp_path / "kb" / "units" / "blogs" / "b-overlap"
    record_path = unit_dir / "record.yaml"
    record_path.parent.mkdir(parents=True)
    record_path.write_text("value: old\n", encoding="utf-8")
    ancestor_ready = threading.Event()
    release_ancestor = threading.Event()
    descendant_attempting = threading.Event()
    descendant_entered = threading.Event()
    errors: list[BaseException] = []

    def ancestor() -> None:
        try:
            with mutation_transaction(tmp_path, "ancestor-abort", [unit_dir]):
                record_path.write_text("value: ancestor-partial\n", encoding="utf-8")
                ancestor_ready.set()
                if not release_ancestor.wait(timeout=5):
                    raise TimeoutError("test did not release ancestor")
                raise RuntimeError("abort ancestor")
        except RuntimeError as exc:
            if str(exc) != "abort ancestor":
                errors.append(exc)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def descendant() -> None:
        try:
            if not ancestor_ready.wait(timeout=5):
                raise TimeoutError("ancestor did not start")
            descendant_attempting.set()
            with mutation_transaction(tmp_path, "descendant-commit", [record_path]):
                descendant_entered.set()
                record_path.write_text("value: descendant-commit\n", encoding="utf-8")
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=ancestor)
    second = threading.Thread(target=descendant)
    first.start()
    assert ancestor_ready.wait(timeout=5)
    second.start()
    assert descendant_attempting.wait(timeout=5)
    assert not descendant_entered.wait(timeout=0.25)
    release_ancestor.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert descendant_entered.is_set()
    assert record_path.read_text(encoding="utf-8") == "value: descendant-commit\n"
    states = {
        entry["op_type"]: entry["state"]
        for entry in [load_yaml(path) for path in (tmp_path / "kb" / ".journal").glob("*.yaml")]
        if entry.get("op_type") in {"ancestor-abort", "descendant-commit"}
    }
    assert states == {"ancestor-abort": "abort", "descendant-commit": "commit"}


def test_independent_disjoint_and_same_path_transactions_are_serialized_safely(tmp_path: Path) -> None:
    left = tmp_path / "kb" / "notes" / "left.md"
    right = tmp_path / "kb" / "notes" / "right.md"

    def write(path: Path, content: str) -> None:
        with mutation_transaction(tmp_path, f"write-{path.stem}", [path]):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda item: write(*item), [(left, "left\n"), (right, "right\n")]))
    assert left.read_bytes() == b"left\n"
    assert right.read_bytes() == b"right\n"

    counter = tmp_path / "kb" / "notes" / "counter.txt"
    counter.write_text("0\n", encoding="utf-8")

    def increment(index: int) -> None:
        with mutation_transaction(tmp_path, f"increment-{index}", [counter]):
            value = int(counter.read_text(encoding="utf-8"))
            time.sleep(0.005)
            counter.write_text(f"{value + 1}\n", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(increment, range(16)))
    assert counter.read_text(encoding="utf-8") == "16\n"


def test_same_process_nested_covered_target_inherits_root_transaction(tmp_path: Path) -> None:
    unit_dir = tmp_path / "kb" / "units" / "blogs" / "b-covered"
    record_path = unit_dir / "record.yaml"
    with mutation_transaction(tmp_path, "covered-root", [unit_dir]) as root_op_id:
        with mutation_transaction(tmp_path, "covered-child", [record_path]) as child_op_id:
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text("covered: true\n", encoding="utf-8")

    child = load_op(tmp_path, child_op_id)
    assert child["parent_op_id"] == root_op_id
    assert child["root_op_id"] == root_op_id
    assert child["undoable"] is False
    assert child["coordination_scope"] == "inherited"


def test_nested_target_outside_root_coverage_fails_closed(tmp_path: Path) -> None:
    unit_dir = tmp_path / "kb" / "units" / "blogs" / "b-covered"
    record_path = unit_dir / "record.yaml"
    record_path.parent.mkdir(parents=True)
    record_path.write_text("covered: true\n", encoding="utf-8")
    outside = tmp_path / "kb" / "notes" / "outside.md"
    with pytest.raises(SystemExit, match="must be covered"):
        with mutation_transaction(tmp_path, "coverage-abort-root", [unit_dir]):
            record_path.write_text("partial\n", encoding="utf-8")
            with mutation_transaction(tmp_path, "coverage-escape", [outside]):
                outside.write_text("must not happen\n", encoding="utf-8")
    assert record_path.read_text(encoding="utf-8") == "covered: true\n"
    assert not outside.exists()


def test_subprocess_nested_covered_target_inherits_without_deadlock_and_escape_fails(tmp_path: Path) -> None:
    unit_dir = tmp_path / "kb" / "units" / "blogs" / "b-subprocess"
    record_path = unit_dir / "record.yaml"
    outside = tmp_path / "kb" / "notes" / "subprocess-escape.md"
    lib_root = _project_root() / ".agents" / "lib"
    child_code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from research.journal import mutation_transaction
root = Path(sys.argv[2])
target = Path(sys.argv[3])
with mutation_transaction(root, sys.argv[4], [target]):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sys.argv[5], encoding='utf-8')
"""

    with mutation_transaction(tmp_path, "subprocess-root", [unit_dir]) as root_op_id:
        env = journal_subprocess_env(tmp_path)
        covered = subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                lib_root.as_posix(),
                tmp_path.as_posix(),
                record_path.as_posix(),
                "subprocess-covered-child",
                "covered by parent\n",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        assert covered.returncode == 0, covered.stderr
        escaped = subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                lib_root.as_posix(),
                tmp_path.as_posix(),
                outside.as_posix(),
                "subprocess-escape-child",
                "escape\n",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        assert escaped.returncode != 0
        assert "must be covered" in escaped.stderr

    assert record_path.read_bytes() == b"covered by parent\n"
    assert not outside.exists()
    child_entries = [
        entry
        for entry in committed_ops(tmp_path)
        if entry.get("op_type") == "subprocess-covered-child"
    ]
    assert len(child_entries) == 1
    assert child_entries[0]["root_op_id"] == root_op_id
    assert child_entries[0]["coordination_scope"] == "inherited"


def test_auto_checkpoint_bookkeeping_never_hides_latest_user_transaction(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    path = tmp_path / "kb" / "notes" / "undoable.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("before\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed undo target", auto_init=False, target_paths=[path])

    with mutation_transaction(tmp_path, "edit-note", [path]) as business_op_id:
        path.write_text("after\n", encoding="utf-8")
    checkpoint = maybe_auto_checkpoint(
        tmp_path,
        trigger="milestone",
        message="milestone: edit note",
        target_paths=[path],
    )

    assert checkpoint["committed"] is True
    entries = committed_ops(tmp_path)
    version_entries = [entry for entry in entries if entry["op_type"] == "write_versioning_state"]
    assert version_entries and all(entry["undoable"] is False for entry in version_entries)
    assert latest_committed_op(tmp_path)["op_id"] == business_op_id

    undone = undo_last_operation(tmp_path)

    assert undone["op_id"] == business_op_id
    assert path.read_bytes() == b"before\n"
    assert load_op(tmp_path, business_op_id)["undone_by"] == undone["recovery_op_id"]


def test_config_runtime_command_is_one_scoped_undoable_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _load_config_module()
    config.ensure_workspace(tmp_path)
    path = config.runtime_preferences_path(tmp_path)
    before = path.read_bytes()
    _configure_kb_git(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "config.py",
            "--root",
            str(tmp_path),
            "set-runtime-pref",
            "--section",
            "paper",
            "--key",
            "auto_complete_note",
            "--value",
            "true",
        ],
    )

    assert config.main() == 0
    operation = latest_committed_op(tmp_path)
    assert operation["op_type"] == "set-runtime-pref"
    assert operation["target_paths"] == ["config/runtime-preferences.yaml"]
    assert operation["undoable"] is True

    undo_last_operation(tmp_path)

    assert path.read_bytes() == before


def test_nested_crash_resume_restores_only_root_before_image_and_aborts_descendants(tmp_path: Path) -> None:
    _configure_kb_git(tmp_path)
    path = tmp_path / "kb" / "notes" / "nested-crash.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("outer before\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed nested crash target", auto_init=False, target_paths=[path])

    outer_op_id = begin_op(tmp_path, "outer-command", [path])
    path.write_text("outer partial\n", encoding="utf-8")
    inner_op_id = begin_op(tmp_path, "inner-write", [path], parent_op_id=outer_op_id)
    path.write_text("inner partial\n", encoding="utf-8")

    assert [entry["op_id"] for entry in incomplete_ops(tmp_path)] == [outer_op_id]
    restored = restore_operation(tmp_path, outer_op_id, recovery_type="resume")
    abort_op(tmp_path, outer_op_id)

    assert restored["op_id"] == outer_op_id
    assert path.read_bytes() == b"outer before\n"
    assert load_op(tmp_path, outer_op_id)["state"] == "abort"
    assert load_op(tmp_path, inner_op_id)["state"] == "abort"
    assert load_op(tmp_path, inner_op_id)["aborted_with_ancestor"] == outer_op_id
    assert incomplete_ops(tmp_path) == []


def test_legacy_root_business_entry_is_undoable_but_legacy_internal_entries_are_not(tmp_path: Path) -> None:
    def make_legacy(op_type: str, path: Path, content: str) -> str:
        op_id = begin_op(tmp_path, op_type, [path])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        commit_op(tmp_path, op_id)
        entry = load_op(tmp_path, op_id)
        for key in ("undoable", "operation_role", "parent_op_id", "root_op_id", "transaction_depth"):
            entry.pop(key, None)
        write_yaml_if_changed(journal_entry_path(tmp_path, op_id), entry)
        return op_id

    business_op_id = make_legacy("legacy-edit", tmp_path / "kb" / "notes" / "legacy.md", "business\n")
    make_legacy(
        "write_versioning_state",
        tmp_path / "kb" / ".runtime" / "versioning-state.yaml",
        "last_commit: legacy\n",
    )
    make_legacy("undo:legacy-edit", tmp_path / "kb" / "notes" / "legacy-recovery.md", "recovery\n")

    assert latest_committed_op(tmp_path)["op_id"] == business_op_id


def test_recovery_journal_commit_failure_never_advances_git_or_marks_business_undone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_kb_git(tmp_path)
    path = tmp_path / "kb" / "notes" / "recovery-fault.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("before\n", encoding="utf-8")
    git_checkpoint(tmp_path, "seed recovery fault", auto_init=False, target_paths=[path])
    with mutation_transaction(tmp_path, "faulted-undo-source", [path]) as business_op_id:
        path.write_text("after\n", encoding="utf-8")
    git_checkpoint(tmp_path, "business change", auto_init=False, target_paths=[path])
    head_before = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    real_commit_op = journal.commit_op

    def fail_recovery_commit(project_root: Path, op_id: str) -> None:
        if load_op(project_root, op_id).get("operation_role") == "recovery":
            raise OSError("simulated recovery journal commit failure")
        real_commit_op(project_root, op_id)

    monkeypatch.setattr(journal, "commit_op", fail_recovery_commit)
    with pytest.raises(OSError, match="simulated recovery journal commit failure"):
        undo_last_operation(tmp_path)

    head_after = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_after == head_before
    assert path.read_bytes() == b"after\n"
    assert not load_op(tmp_path, business_op_id).get("undone_by")


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
    assert ".runtime/intake-staging" not in record["source"]["markdown_path"]
    assert (tmp_path / record["source"]["markdown_path"]).is_file()
    materialization = record["source"]["materialization"]
    assert ".runtime/intake-staging" not in materialization["source_map_path"]
    assert ".runtime/intake-staging" not in materialization["conversion_path"]
    assert ".runtime/intake-staging" not in materialization["archive_path"]
    assert (tmp_path / materialization["source_map_path"]).is_file()
    assert (tmp_path / materialization["conversion_path"]).is_file()
    assert (tmp_path / materialization["archive_path"]).is_file()
    cache = load_yaml(records[0].parent / "parse-cache.yaml")
    assert cache["unit_id"] == record["id"]
    assert cache["chunks"]


def test_intake_uses_parsed_html_title_when_user_did_not_supply_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    html = (
        b"<!doctype html><html><head><title>Readable Query Planning Guide</title></head>"
        b"<body><main><h1>Query Planning</h1><p>Grounded technical documentation.</p>"
        b"</main></body></html>"
    )
    monkeypatch.setattr(sources, "fetch_url", lambda requested, **kwargs: (html, "text/html"))
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
            "https://example.com/queryplanner.html",
        ],
    )

    assert intake.main() == 0

    records = list((tmp_path / "kb" / "units" / "blogs").glob("*/record.yaml"))
    assert len(records) == 1
    record = load_yaml(records[0])
    assert record["title"] == "Readable Query Planning Guide"
    assert record["summary"] == ""


def test_intake_checkpoint_then_undo_restores_unit_index_governance_and_search_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    source = tmp_path / "transactional-source.md"
    source.write_text("# Transactional source\n\nGrounded body.\n", encoding="utf-8")
    stage_id = "blog-search-transactional"
    candidate_id = f"{stage_id}-candidate"
    stage_path = sources.stage_search_results(
        tmp_path,
        kind="blog",
        query="transactional source",
        stage_id=stage_id,
        candidates=[
            {
                "candidate_id": candidate_id,
                "title": "Transactional source",
                "url": source.as_posix(),
            }
        ],
    )
    tracked_paths = [
        tmp_path / "kb" / "taxonomy" / "topics.yaml",
        tmp_path / "kb" / "candidate-pools" / "pools.yaml",
        tmp_path / "kb" / "index.yaml",
        tmp_path / "kb" / "index.md",
        stage_path,
    ]
    before = {path: path.read_bytes() if path.exists() else None for path in tracked_paths}
    _configure_kb_git(tmp_path)
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
            source.as_posix(),
            "--title",
            "Transactional source",
            "--stage-id",
            stage_id,
            "--candidate-id",
            candidate_id,
        ],
    )

    assert intake.main() == 0
    units = list((tmp_path / "kb" / "units" / "blogs").glob("*/record.yaml"))
    assert len(units) == 1
    stage_after = load_yaml(stage_path)
    candidate_after = next(item for item in stage_after["candidates"] if item["candidate_id"] == candidate_id)
    assert candidate_after["status"] == "materialized"
    intake_op = latest_committed_op(tmp_path)
    assert intake_op["op_type"] == "source-intake-add"
    assert intake_op["undoable"] is True
    descendants = [
        entry
        for entry in committed_ops(tmp_path)
        if entry.get("root_op_id") == intake_op["op_id"] and entry["op_id"] != intake_op["op_id"]
    ]
    assert descendants and all(entry["undoable"] is False for entry in descendants)

    undone = undo_last_operation(tmp_path)

    assert undone["op_id"] == intake_op["op_id"]
    assert not units[0].parent.exists()
    for path, payload in before.items():
        if payload is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == payload


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


@pytest.mark.parametrize("source_shape", ["absolute-file-link", "nested-directory-link"])
def test_owner_intake_rejects_symlinks_before_identity_or_journal_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_shape: str,
) -> None:
    intake = _load_intake_module()
    secret = b"owner-intake-outside-secret\n"
    if source_shape == "absolute-file-link":
        outside = tmp_path / "outside-secret.md"
        outside.write_bytes(secret)
        selected = tmp_path / "selected-link.md"
        selected.symlink_to(outside)
        kind = "blog"
    else:
        outside = tmp_path / "outside-tree"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(secret)
        selected = tmp_path / "selected-repo"
        selected.mkdir()
        (selected / "README.md").write_text("# Safe before nested link\n", encoding="utf-8")
        (selected / "nested-link").symlink_to(outside, target_is_directory=True)
        kind = "repo"
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
            kind,
            "--source",
            selected.as_posix(),
        ],
    )

    with pytest.raises(SystemExit, match="符号链接"):
        intake.main()

    assert list((tmp_path / "kb" / "units").glob("**/record.yaml")) == []
    assert list((tmp_path / "kb" / ".runtime" / "intake-staging").glob("**/failure.yaml")) == []
    assert list((tmp_path / "kb" / ".journal" / "snapshots").glob("*")) == []
    copied = [
        path
        for path in (tmp_path / "kb").rglob("*")
        if path.is_file() and not path.is_symlink() and secret in path.read_bytes()
    ]
    assert copied == []


def test_owner_intake_preserves_relative_legacy_raw_remap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    legacy_target = tmp_path / "kb" / "raw" / "legacy-note.md"
    legacy_target.parent.mkdir(parents=True)
    legacy_target.write_text("# Legacy note\n\nGrounded body.\n", encoding="utf-8")
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
            "raw/legacy-note.md",
        ],
    )

    assert intake.main() == 0

    records = list((tmp_path / "kb" / "units" / "blogs").glob("*/record.yaml"))
    assert len(records) == 1
    record = load_yaml(records[0])
    assert record["source"]["original_uri"] == legacy_target.resolve().as_posix()
    assert legacy_target.read_text(encoding="utf-8") == "# Legacy note\n\nGrounded body.\n"


def test_repo_backup_excludes_vcs_metadata_before_canonical_materialization(tmp_path: Path) -> None:
    source_repo = tmp_path / "source-repo"
    (source_repo / ".git").mkdir(parents=True)
    (source_repo / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (source_repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    unit_dir = tmp_path / "kb" / ".runtime" / "intake-staging" / "r-staged" / "attempt"

    payload = sources.backup_source(
        tmp_path,
        "repo",
        "r-staged",
        source_repo.as_posix(),
        unit_dir=unit_dir,
    )

    archived_repo = tmp_path / payload["backup_paths"][0]
    assert (archived_repo / "README.md").read_bytes() == b"# Repository\n"
    assert not (archived_repo / ".git").exists()


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
    canonical_repo_source = tmp_path / "kb" / "units" / "repos" / "r-demo" / "source" / "repo"
    nested_git_config = canonical_repo_source / ".git" / "config"
    nested_git_config.parent.mkdir(parents=True)
    nested_git_config.write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    (canonical_repo_source / "README.md").write_text("Reference raw/repo without rewriting.\n", encoding="utf-8")
    canonical_repo_digest = journal.file_digest(canonical_repo_source)
    legacy_raw = tmp_path / "raw" / "legacy.bin"
    legacy_output = tmp_path / "output" / "legacy-report.md"
    legacy_raw.parent.mkdir(parents=True)
    legacy_output.parent.mkdir(parents=True)
    legacy_raw.write_bytes(b"legacy raw bytes\x00\xff")
    legacy_output.write_bytes(b"legacy output bytes\n")
    legacy_before = {legacy_raw: legacy_raw.read_bytes(), legacy_output: legacy_output.read_bytes()}

    result = sources.sync_storage_layout(tmp_path)

    assert all(path.read_bytes() == payload for path, payload in before.items())
    assert immutable_source.read_bytes() == source_before
    assert immutable_cache.read_bytes() == cache_before
    assert journal.file_digest(canonical_repo_source) == canonical_repo_digest
    assert nested_git_config.exists()
    assert "kb/raw/example" in mutable_note.read_text(encoding="utf-8")
    assert "kb/notes/migration.md" in result["rewritten_files"]
    assert all(item.startswith("kb/") for item in result["rewritten_files"])
    assert legacy_raw.read_bytes() == legacy_before[legacy_raw]
    assert legacy_output.read_bytes() == legacy_before[legacy_output]
    assert (tmp_path / "kb" / "raw" / "legacy.bin").read_bytes() == legacy_before[legacy_raw]
    assert (tmp_path / "kb" / "output" / "legacy-report.md").read_bytes() == legacy_before[legacy_output]
    assert set(result["preserved_legacy_roots"]) == {
        (tmp_path / "raw").as_posix(),
        (tmp_path / "output").as_posix(),
    }

    undone = undo_last_operation(tmp_path)

    assert undone["op_id"]
    assert mutable_note.read_text(encoding="utf-8") == "Reference raw/example and output/example.\n"
    assert not (tmp_path / "kb" / "raw" / "legacy.bin").exists()
    assert not (tmp_path / "kb" / "output" / "legacy-report.md").exists()
    assert legacy_raw.read_bytes() == legacy_before[legacy_raw]
    assert legacy_output.read_bytes() == legacy_before[legacy_output]
    assert journal.file_digest(canonical_repo_source) == canonical_repo_digest


def test_storage_sync_preserves_legacy_uri_when_destination_bytes_conflict(tmp_path: Path) -> None:
    legacy = tmp_path / "raw" / "collision.txt"
    destination = tmp_path / "kb" / "raw" / "collision.txt"
    legacy.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy truth\n")
    destination.write_bytes(b"different canonical bytes\n")
    record = default_record("blog", title="Storage collision", maturity="lightweight")
    record["id"] = "b-storage-collision"
    record["source"] = {
        "original_uri": legacy.as_posix(),
        "backup_kind": "local-file",
        "backup_paths": [],
        "file_hash": "",
    }
    record_path = write_record(tmp_path, record)

    result = sources.sync_storage_layout(tmp_path)

    assert legacy.read_bytes() == b"legacy truth\n"
    assert destination.read_bytes() == b"different canonical bytes\n"
    assert load_yaml(record_path)["source"]["original_uri"] == legacy.as_posix()
    assert result["conflicts"]
    assert any(
        item["source"] == legacy.as_posix()
        and item["destination"] == destination.as_posix()
        and item["source_digest"] != item["destination_digest"]
        for item in result["conflicts"]
    )


def test_runtime_capabilities_recognize_default_pymupdf_stack() -> None:
    current = current_runtime_capabilities()
    inspected = inspect_python_runtime(sys.executable)

    for payload in (current, inspected):
        modules = payload["modules"]
        assert payload["markdown_support"] is True
        if modules["pymupdf4llm"] or modules["fitz"]:
            assert payload["pdf_support"] is True
            assert payload["pdf_backend"] in {"pymupdf4llm", "fitz"}

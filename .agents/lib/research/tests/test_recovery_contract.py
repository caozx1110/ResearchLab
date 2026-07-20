import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
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
from research.journal import abort_op, begin_op, commit_op, committed_ops, incomplete_ops, journal_entry_path, load_op
from research.prefs import ensure_workspace
from research.records import default_record
from research import git_ops, yaml_io
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
    git_checkpoint(
        tmp_path,
        "seed paper inputs",
        auto_init=False,
        target_paths=[record_path, cache, fill_path],
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

from __future__ import annotations

from repo_paths import initialize_test_workspace

import hashlib
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml
from research.core import ensure_workspace
from research.preference_selection import eligible_preferences, record_effective_selection


def _experiment_module():
    project_root = REPO_ROOT
    script = project_root / "skills" / "experiment-workbench" / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_allocator_binding_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _new_experiment(tmp_path: Path, module, name: str) -> tuple[Path, Path, dict]:
    root = tmp_path / f"workspace-{name}"
    root.mkdir()
    initialize_test_workspace(root)
    plan = module.build_parser().parse_args(
        ["plan", "--title", f"allocator {name}", "--program-id", "program-r12"]
    )
    assert module._dispatch(plan, root) == 0
    record_path = next((root / "units" / "experiments").glob("*/record.yaml"))
    return root, record_path, load_yaml(record_path)


def _log_args(module, experiment_id: str, *, seed: int = 1, selection_id: str = ""):
    args = module.build_parser().parse_args(
        [
            "log-run",
            "--experiment-id",
            experiment_id,
            "--result-summary",
            f"allocator observation {seed}",
            "--config-revision",
            f"config-r12-{seed}",
            "--seed",
            str(seed),
        ]
    )
    args.preference_selection_id = selection_id
    return args


def _selection(
    root: Path,
    module,
    args,
    record: dict,
    unit_root: Path,
    *,
    selection_id: str,
) -> tuple[str, dict]:
    prepared = module.prepare_experiment_preference_inputs(root, args, record, unit_root)
    task_context = module.experiment_preference_context(args, record, prepared)
    eligible = eligible_preferences(root, skill="experiment-workbench", operation="log-run")
    selected = []
    excluded = []
    for item in eligible["items"]:
        if item["strength"] == "hard":
            selected.append(
                {
                    "preference_id": item["preference_id"],
                    "reason": "mechanical hard constraint",
                    "application": "enforce for this run",
                }
            )
        else:
            excluded.append(
                {"preference_id": item["preference_id"], "reason": "not selected for this run"}
            )
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "experiment-workbench",
            "operation": "log-run",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": task_context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    args.preference_selection_id = selection_id
    return selection_id, task_context


def _business_snapshot(unit_root: Path) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for path in sorted(unit_root.rglob("*"), key=lambda item: item.relative_to(unit_root).as_posix()):
        relative = path.relative_to(unit_root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            snapshot[relative] = ("symlink", os.readlink(path))
        elif stat.S_ISDIR(metadata.st_mode):
            snapshot[relative] = ("directory", stat.S_IMODE(metadata.st_mode))
        elif stat.S_ISREG(metadata.st_mode):
            snapshot[relative] = (
                "file",
                stat.S_IMODE(metadata.st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        else:
            snapshot[relative] = ("special", stat.S_IFMT(metadata.st_mode))
    return snapshot


@pytest.mark.parametrize("round_no", [1, 2])
def test_receipt_freezes_first_run_and_rejects_inserted_run_twice(
    tmp_path: Path,
    round_no: int,
) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, f"insert-{round_no}")
    args = _log_args(module, record["id"], seed=round_no)
    _, task_context = _selection(
        root,
        module,
        args,
        record,
        record_path.parent,
        selection_id=f"prefsel-r12-insert-{round_no}",
    )
    assert task_context["proposed_run_id"] == "run-001"
    assert task_context["proposed_run_path"] == "runs/run-001.md"
    assert len(task_context["run_allocator_directory_digest"]) == 64

    runs_dir = record_path.parent / "runs"
    runs_dir.mkdir()
    (runs_dir / "run-001.md").write_text("concurrent insertion\n", encoding="utf-8")
    before = _business_snapshot(record_path.parent)

    with pytest.raises(SystemExit, match="another task"):
        module._dispatch(args, root)

    assert _business_snapshot(record_path.parent) == before
    assert sorted(path.name for path in runs_dir.iterdir()) == ["run-001.md"]
    assert not (record_path.parent / "run-log.yaml").exists()


@pytest.mark.parametrize(
    "mutation",
    ["delete", "bytes", "entry", "directory", "symlink", "fifo"],
)
def test_allocator_drift_and_unsafe_entries_fail_closed_without_business_writes(
    tmp_path: Path,
    mutation: str,
) -> None:
    if mutation == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, f"drift-{mutation}")
    runs_dir = record_path.parent / "runs"
    runs_dir.mkdir()
    first_run = runs_dir / "run-001.md"
    first_run.write_text("bound run bytes\n", encoding="utf-8")
    args = _log_args(module, record["id"], seed=11)
    _selection(
        root,
        module,
        args,
        record,
        record_path.parent,
        selection_id=f"prefsel-r12-drift-{mutation}",
    )

    if mutation == "delete":
        first_run.unlink()
    elif mutation == "bytes":
        first_run.write_text("changed run bytes\n", encoding="utf-8")
    elif mutation == "entry":
        (runs_dir / "concurrent-note.txt").write_text("new entry\n", encoding="utf-8")
    elif mutation == "directory":
        first_run.unlink()
        first_run.mkdir()
    elif mutation == "symlink":
        outside = tmp_path / "outside-run.md"
        outside.write_text("outside\n", encoding="utf-8")
        first_run.unlink()
        first_run.symlink_to(outside)
    else:
        first_run.unlink()
        os.mkfifo(first_run)
    before = _business_snapshot(record_path.parent)

    with pytest.raises(SystemExit):
        module._dispatch(args, root)

    assert _business_snapshot(record_path.parent) == before
    assert not (record_path.parent / "run-log.yaml").exists()
    assert not (runs_dir / "run-002.md").exists()
    assert load_yaml(record_path) == record


@pytest.mark.parametrize("round_no", [1, 2])
def test_allocator_revalidation_catches_drift_after_receipt_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_no: int,
) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, f"late-drift-{round_no}")
    args = _log_args(module, record["id"], seed=20 + round_no)
    _selection(
        root,
        module,
        args,
        record,
        record_path.parent,
        selection_id=f"prefsel-r12-late-drift-{round_no}",
    )
    original_resolver = module.resolve_experiment_preferences

    def resolve_then_drift(*call_args, **call_kwargs):
        resolution = original_resolver(*call_args, **call_kwargs)
        runs_dir = record_path.parent / "runs"
        runs_dir.mkdir()
        (runs_dir / "run-001.md").write_text("inserted after receipt validation\n", encoding="utf-8")
        return resolution

    monkeypatch.setattr(module, "resolve_experiment_preferences", resolve_then_drift)

    with pytest.raises(SystemExit, match="inputs changed"):
        module._dispatch(args, root)

    assert sorted(path.name for path in (record_path.parent / "runs").iterdir()) == ["run-001.md"]
    assert not (record_path.parent / "run-log.yaml").exists()
    assert load_yaml(record_path) == record


def test_normal_first_and_subsequent_receipt_bound_allocations(tmp_path: Path) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, "normal")
    first = _log_args(module, record["id"], seed=31)
    first_prepared = module.prepare_experiment_preference_inputs(root, first, record, record_path.parent)
    assert first_prepared["run_allocator"]["proposed_run_id"] == "run-001"
    assert module._dispatch(first, root) == 0

    current_record = load_yaml(record_path)
    second = _log_args(module, record["id"], seed=32)
    _, second_context = _selection(
        root,
        module,
        second,
        current_record,
        record_path.parent,
        selection_id="prefsel-r12-normal-second",
    )
    assert second_context["proposed_run_id"] == "run-002"
    assert second_context["proposed_run_path"] == "runs/run-002.md"
    assert module._dispatch(second, root) == 0

    runs_dir = record_path.parent / "runs"
    assert sorted(path.name for path in runs_dir.iterdir()) == ["run-001.md", "run-002.md"]
    assert [item["id"] for item in load_yaml(record_path.parent / "run-log.yaml")["items"]] == [
        "run-001",
        "run-002",
    ]


def test_concurrent_receipts_do_not_fall_forward_to_an_alternate_id(tmp_path: Path) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, "concurrent")
    commands = []
    script = Path(module.__file__)
    for seed in (41, 42):
        args = _log_args(module, record["id"], seed=seed)
        selection_id, _ = _selection(
            root,
            module,
            args,
            record,
            record_path.parent,
            selection_id=f"prefsel-r12-concurrent-{seed}",
        )
        commands.append(
            [
                sys.executable,
                str(script),
                "--root",
                str(root),
                "log-run",
                "--experiment-id",
                record["id"],
                "--result-summary",
                f"allocator observation {seed}",
                "--config-revision",
                f"config-r12-{seed}",
                "--seed",
                str(seed),
                "--preference-selection-id",
                selection_id,
            ]
        )

    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for command in commands
    ]
    results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]

    assert sorted(returncode for _, _, returncode in results) == [0, 1], results
    runs_dir = record_path.parent / "runs"
    assert sorted(path.name for path in runs_dir.iterdir()) == ["run-001.md"]
    assert len(load_yaml(record_path.parent / "run-log.yaml")["items"]) == 1
    failed_stderr = next(stderr for _, stderr, returncode in results if returncode != 0)
    assert "another task" in failed_stderr


def test_exclusive_creation_rejects_leaf_race_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, "leaf-race")
    args = _log_args(module, record["id"], seed=51)
    _selection(
        root,
        module,
        args,
        record,
        record_path.parent,
        selection_id="prefsel-r12-leaf-race",
    )
    original_open = module.os.open
    inserted = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal inserted
        if path == "run-001.md" and flags & os.O_EXCL and not inserted:
            inserted = True
            (record_path.parent / "runs" / "run-001.md").write_text(
                "concurrent winner\n", encoding="utf-8"
            )
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "open", racing_open)

    with pytest.raises(SystemExit, match="exclusive creation"):
        module._dispatch(args, root)

    assert (record_path.parent / "runs" / "run-001.md").read_text(encoding="utf-8") == "concurrent winner\n"
    assert not (record_path.parent / "runs" / "run-002.md").exists()
    assert not (record_path.parent / "run-log.yaml").exists()
    assert load_yaml(record_path) == record


def test_transaction_recovery_removes_exclusive_run_after_later_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, "recovery")
    args = _log_args(module, record["id"], seed=61)
    targets = module._experiment_command_targets(args, root)

    def fail_after_run_write(*_args, **_kwargs):
        raise RuntimeError("injected post-run failure")

    monkeypatch.setattr(module, "append_list_item", fail_after_run_write)
    with pytest.raises(RuntimeError, match="injected post-run failure"):
        with module.command_mutation(root, "experiment-workbench:log-run", targets):
            module._dispatch(args, root)

    assert not (record_path.parent / "runs").exists()
    assert not (record_path.parent / "run-log.yaml").exists()
    assert load_yaml(record_path) == record


@pytest.mark.parametrize("unsafe_shape", ["root-fifo", "root-symlink", "child-fifo", "child-symlink"])
def test_cli_rejects_unsafe_allocator_before_journal_snapshot(
    tmp_path: Path,
    unsafe_shape: str,
) -> None:
    if "fifo" in unsafe_shape and not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, f"cli-{unsafe_shape}")
    runs_dir = record_path.parent / "runs"
    outside = tmp_path / f"outside-{unsafe_shape}"
    outside.mkdir()
    if unsafe_shape == "root-fifo":
        os.mkfifo(runs_dir)
    elif unsafe_shape == "root-symlink":
        runs_dir.symlink_to(outside, target_is_directory=True)
    else:
        runs_dir.mkdir()
        child = runs_dir / "run-001.md"
        if unsafe_shape == "child-fifo":
            os.mkfifo(child)
        else:
            outside_file = outside / "run.md"
            outside_file.write_text("outside bytes\n", encoding="utf-8")
            child.symlink_to(outside_file)
    before = _business_snapshot(record_path.parent)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--root",
            str(root),
            "log-run",
            "--experiment-id",
            record["id"],
            "--result-summary",
            "unsafe allocator must fail",
            "--config-revision",
            "config-r12-unsafe",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "run allocator" in result.stderr.lower()
    assert _business_snapshot(record_path.parent) == before
    assert not (record_path.parent / "run-log.yaml").exists()
    assert load_yaml(record_path) == record

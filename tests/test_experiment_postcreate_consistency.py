from __future__ import annotations

import hashlib
import importlib.util
import errno
import os
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml
from research.core import ensure_workspace
from research.preference_selection import eligible_preferences, record_effective_selection


MUTATIONS = (
    "delete",
    "overwrite",
    "same-byte-inode-replacement",
    "rename",
    "root-replacement",
    "file-to-directory",
    "symlink",
    "fifo",
    "socket",
    "extra-entry",
)


def _experiment_module():
    project_root = REPO_ROOT
    script = project_root / "skills" / "experiment-workbench" / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location(
        f"experiment_postcreate_consistency_{os.urandom(6).hex()}",
        script,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _new_experiment(tmp_path: Path, module, name: str) -> tuple[Path, Path, dict]:
    root = tmp_path / f"workspace-{name}"
    root.mkdir()
    ensure_workspace(root)
    plan = module.build_parser().parse_args(
        ["plan", "--title", f"postcreate {name}", "--program-id", "program-r12-postcreate"]
    )
    assert module._dispatch(plan, root) == 0
    record_path = next((root / "kb" / "units" / "experiments").glob("*/record.yaml"))
    return root, record_path, load_yaml(record_path)


def _log_args(module, experiment_id: str, seed: int):
    return module.build_parser().parse_args(
        [
            "log-run",
            "--experiment-id",
            experiment_id,
            "--result-summary",
            f"postcreate observation {seed}",
            "--config-revision",
            f"postcreate-config-{seed}",
            "--seed",
            str(seed),
        ]
    )


def _record_selection(root: Path, module, args, record: dict, unit_root: Path, selection_id: str) -> None:
    prepared = module.prepare_experiment_preference_inputs(root, args, record, unit_root)
    eligible = eligible_preferences(root, skill="experiment-workbench", operation="log-run")
    selected = []
    excluded = []
    for item in eligible["items"]:
        decision = {
            "preference_id": item["preference_id"],
            "reason": "postcreate transaction matrix",
        }
        if item["strength"] == "hard":
            selected.append({**decision, "application": "enforce for this run"})
        else:
            excluded.append(decision)
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "experiment-workbench",
            "operation": "log-run",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": module.experiment_preference_context(args, record, prepared),
            "selected": selected,
            "excluded": excluded,
        },
    )
    args.preference_selection_id = selection_id


def _business_snapshot(root: Path) -> dict[str, tuple]:
    kb = root / "kb"
    snapshot: dict[str, tuple] = {}
    for path in sorted(kb.rglob("*"), key=lambda item: item.relative_to(kb).as_posix()):
        relative = path.relative_to(kb)
        if relative.parts and relative.parts[0] in {".journal", ".runtime"}:
            continue
        metadata = path.lstat()
        name = relative.as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            snapshot[name] = ("symlink", os.readlink(path))
        elif stat.S_ISDIR(metadata.st_mode):
            snapshot[name] = ("directory", stat.S_IMODE(metadata.st_mode))
        elif stat.S_ISREG(metadata.st_mode):
            snapshot[name] = (
                "file",
                stat.S_IMODE(metadata.st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        else:
            snapshot[name] = ("special", stat.S_IFMT(metadata.st_mode))
    return snapshot


def _mutate_created_run(unit_root: Path, mutation: str, outside: Path) -> None:
    runs_dir = unit_root / "runs"
    run_path = runs_dir / "run-001.md"
    assert run_path.is_file()
    if mutation == "delete":
        run_path.unlink()
    elif mutation == "overwrite":
        run_path.write_bytes(b"postcreate overwrite\n")
    elif mutation == "same-byte-inode-replacement":
        payload = run_path.read_bytes()
        replacement = runs_dir / ".same-byte-replacement"
        replacement.write_bytes(payload)
        os.replace(replacement, run_path)
    elif mutation == "rename":
        run_path.rename(runs_dir / "renamed-run.md")
    elif mutation == "root-replacement":
        shutil.rmtree(runs_dir)
        runs_dir.mkdir()
    elif mutation == "file-to-directory":
        run_path.unlink()
        run_path.mkdir()
    elif mutation == "symlink":
        run_path.unlink()
        run_path.symlink_to(outside)
    elif mutation == "fifo":
        run_path.unlink()
        os.mkfifo(run_path)
    elif mutation == "socket":
        run_path.unlink()
        previous_cwd = Path.cwd()
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.chdir(runs_dir)
            try:
                endpoint.bind(run_path.name)
            except OSError as exc:
                if exc.errno in {
                    errno.EPERM,
                    errno.EACCES,
                    errno.EAFNOSUPPORT,
                    errno.EPROTONOSUPPORT,
                }:
                    pytest.skip("Unix-domain socket bind is unavailable in this environment")
                raise
        finally:
            os.chdir(previous_cwd)
            endpoint.close()
    elif mutation == "extra-entry":
        (runs_dir / "run-999.md").write_text("allocator collision\n", encoding="utf-8")
    else:  # pragma: no cover - guarded by the fixed matrix
        raise AssertionError(mutation)


def _run_log_transaction(module, root: Path, args) -> int:
    targets = module._experiment_command_targets(args, root)
    active_token = module._ACTIVE_MUTATION.set(True)
    checkpoint_token = module._PENDING_CHECKPOINT.set(None)
    created_run_guard_token = module._CREATED_RUN_COMMIT_GUARD.set(None)
    try:
        with module.command_mutation(
            root,
            "experiment-workbench:log-run",
            targets,
            commit_guard=module._validate_created_run_at_commit,
        ):
            result = module._dispatch(args, root)
        pending = module._PENDING_CHECKPOINT.get()
    finally:
        module._CREATED_RUN_COMMIT_GUARD.reset(created_run_guard_token)
        module._PENDING_CHECKPOINT.reset(checkpoint_token)
        module._ACTIVE_MUTATION.reset(active_token)
    if pending is not None:
        module.checkpoint_and_report(
            pending[0], trigger=pending[1], message=pending[2], target_paths=pending[3]
        )
    return result


@pytest.mark.parametrize("validation_round", ("before-business-write", "precommit"))
@pytest.mark.parametrize("use_receipt", (False, True), ids=("no-receipt", "receipt"))
@pytest.mark.parametrize("mutation", MUTATIONS)
def test_postcreate_mutation_matrix_fails_closed_in_both_validation_rounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validation_round: str,
    use_receipt: bool,
    mutation: str,
) -> None:
    if mutation == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable on this platform")
    if mutation == "socket" and not hasattr(socket, "AF_UNIX"):
        pytest.skip("Unix-domain sockets are unavailable on this platform")
    module = _experiment_module()
    case = f"{validation_round}-{use_receipt}-{mutation}"
    root, record_path, record = _new_experiment(tmp_path, module, case)
    args = _log_args(module, record["id"], seed=71)
    if use_receipt:
        _record_selection(
            root,
            module,
            args,
            record,
            record_path.parent,
            f"prefsel-r12-postcreate-{hashlib.sha256(case.encode()).hexdigest()[:16]}",
        )
    outside = tmp_path / f"outside-{hashlib.sha256(case.encode()).hexdigest()[:16]}.md"
    outside.write_bytes(b"outside sentinel\n")
    mutated = False

    if validation_round == "before-business-write":
        original_create = module._write_run_file_exclusive

        def create_then_mutate(*call_args, **call_kwargs):
            nonlocal mutated
            fact = original_create(*call_args, **call_kwargs)
            _mutate_created_run(record_path.parent, mutation, outside)
            mutated = True
            return fact

        monkeypatch.setattr(module, "_write_run_file_exclusive", create_then_mutate)
    else:
        original_build_index = module.build_index

        def index_then_mutate(*call_args, **call_kwargs):
            nonlocal mutated
            result = original_build_index(*call_args, **call_kwargs)
            if not mutated:
                _mutate_created_run(record_path.parent, mutation, outside)
                mutated = True
            return result

        monkeypatch.setattr(module, "build_index", index_then_mutate)

    before = _business_snapshot(root)
    with pytest.raises(SystemExit, match="created run"):
        _run_log_transaction(module, root, args)

    assert mutated
    assert _business_snapshot(root) == before
    assert outside.read_bytes() == b"outside sentinel\n"
    assert not (record_path.parent / "runs").exists()
    assert not (record_path.parent / "run-log.yaml").exists()
    assert load_yaml(record_path) == record


def test_postdispatch_run_replacement_fails_at_root_transaction_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, "root-precommit")
    args = _log_args(module, record["id"], seed=79)
    original_dispatch = module._dispatch
    mutated = False

    def dispatch_then_replace(*call_args, **call_kwargs):
        nonlocal mutated
        result = original_dispatch(*call_args, **call_kwargs)
        run_path = record_path.parent / "runs" / "run-001.md"
        replacement = run_path.with_name(".late-postdispatch-replacement")
        replacement.write_bytes(b"late post-dispatch replacement\n")
        os.replace(replacement, run_path)
        mutated = True
        return result

    monkeypatch.setattr(module, "_dispatch", dispatch_then_replace)
    before = _business_snapshot(root)

    with pytest.raises(SystemExit, match="created run"):
        _run_log_transaction(module, root, args)

    assert mutated
    assert _business_snapshot(root) == before
    assert not (record_path.parent / "runs").exists()
    assert not (record_path.parent / "run-log.yaml").exists()
    assert load_yaml(record_path) == record


@pytest.mark.parametrize("round_no", (1, 2))
@pytest.mark.parametrize("use_receipt", (False, True), ids=("no-receipt", "receipt"))
def test_success_freezes_complete_fact_and_runs_both_validations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_no: int,
    use_receipt: bool,
) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, f"success-{use_receipt}-{round_no}")
    args = _log_args(module, record["id"], seed=80 + round_no)
    if use_receipt:
        _record_selection(
            root,
            module,
            args,
            record,
            record_path.parent,
            f"prefsel-r12-postcreate-success-{round_no}",
        )
    facts: list[dict] = []
    validations: list[dict] = []
    original_create = module._write_run_file_exclusive
    original_validate = module._validate_created_run_fact

    def capture_create(*call_args, **call_kwargs):
        fact = original_create(*call_args, **call_kwargs)
        facts.append(fact)
        return fact

    def capture_validation(unit_root, fact):
        validations.append(fact)
        return original_validate(unit_root, fact)

    monkeypatch.setattr(module, "_write_run_file_exclusive", capture_create)
    monkeypatch.setattr(module, "_validate_created_run_fact", capture_validation)

    assert _run_log_transaction(module, root, args) == 0
    assert len(facts) == 1
    assert validations == [facts[0], facts[0]]
    fact = facts[0]
    assert fact["relative_path"] == "runs/run-001.md"
    assert len(fact["directory_entry_digest"]) == 64
    assert fact["entries"] == [fact["leaf"]]
    assert {"device", "inode", "mode"} <= fact["runs_root_identity"].keys()
    assert {
        "device",
        "inode",
        "mode",
        "size",
        "mtime_ns",
        "content_digest",
    } <= fact["leaf"].keys()
    assert (record_path.parent / "runs" / "run-001.md").is_file()
    assert [item["id"] for item in load_yaml(record_path.parent / "run-log.yaml")["items"]] == [
        "run-001"
    ]


def test_concurrent_no_receipt_allocations_remain_unique(tmp_path: Path) -> None:
    module = _experiment_module()
    root, record_path, record = _new_experiment(tmp_path, module, "concurrent-no-receipt")
    commands = [
        [
            sys.executable,
            str(Path(module.__file__)),
            "--root",
            str(root),
            "log-run",
            "--experiment-id",
            record["id"],
            "--result-summary",
            f"concurrent no-receipt observation {seed}",
            "--config-revision",
            f"concurrent-config-{seed}",
            "--seed",
            str(seed),
        ]
        for seed in range(91, 95)
    ]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for command in commands
    ]
    results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]

    failures = [
        f"process {index}: rc={returncode}\nstdout={stdout!r}\nstderr={stderr!r}"
        for index, (stdout, stderr, returncode) in enumerate(results)
        if returncode != 0
    ]
    assert not failures, "\n\n".join(failures)
    assert sorted(path.name for path in (record_path.parent / "runs").iterdir()) == [
        "run-001.md",
        "run-002.md",
        "run-003.md",
        "run-004.md",
    ]
    assert [item["id"] for item in load_yaml(record_path.parent / "run-log.yaml")["items"]] == [
        "run-001",
        "run-002",
        "run-003",
        "run-004",
    ]

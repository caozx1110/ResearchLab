"""Crash-safe operation journal for KB mutations."""
from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from .common import utc_now_iso
from .paths import kb_root
from .yaml_io import load_yaml, write_bytes_atomic, write_yaml_if_changed


JOURNAL_DIRNAME = ".journal"
SNAPSHOT_DIRNAME = "snapshots"
JOURNAL_PARENT_OP_ENV = "RESEARCH_JOURNAL_PARENT_OP"
JOURNAL_PARENT_ROOT_ENV = "RESEARCH_JOURNAL_PARENT_ROOT"

# Each entry is (resolved project root, operation id).  ContextVar keeps nested
# transactions correct across async contexts while the environment bridge below
# carries the same hierarchy into analyzer subprocesses spawned by one command.
_ACTIVE_OP_STACK: ContextVar[tuple[tuple[str, str], ...]] = ContextVar(
    "research_journal_active_ops",
    default=(),
)


def journal_root(project_root: Path) -> Path:
    return kb_root(project_root) / JOURNAL_DIRNAME


def journal_entry_path(project_root: Path, op_id: str) -> Path:
    if not op_id or Path(op_id).name != op_id:
        raise SystemExit(f"Invalid operation id: {op_id}")
    return journal_root(project_root) / f"{op_id}.yaml"


def operation_lock_path(project_root: Path, target_path: Path) -> Path:
    _ensure_journal_runtime(project_root)
    key = _target_key(project_root, target_path)
    name = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return journal_root(project_root) / "locks" / f"{name}.lock"


def workspace_transaction_lock_path(project_root: Path) -> Path:
    _ensure_journal_runtime(project_root)
    return journal_root(project_root) / "workspace-transaction.lock"


def file_digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    digest = hashlib.sha256()
    stat_result = path.lstat()
    mode = stat_result.st_mode & 0o7777
    if path.is_symlink():
        digest.update(f"symlink\0{mode}\0{os.readlink(path)}".encode("utf-8"))
        return digest.hexdigest()
    if path.is_dir():
        digest.update(f"directory\0{mode}\0".encode("utf-8"))
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix()
            child_stat = child.lstat()
            child_mode = child_stat.st_mode & 0o7777
            if child.is_symlink():
                digest.update(f"L\0{relative}\0{child_mode}\0{os.readlink(child)}\0".encode("utf-8"))
            elif child.is_dir():
                digest.update(f"D\0{relative}\0{child_mode}\0".encode("utf-8"))
            else:
                digest.update(f"F\0{relative}\0{child_mode}\0{child_stat.st_size}\0".encode("utf-8"))
                with child.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return digest.hexdigest()
    digest.update(f"file\0{mode}\0{stat_result.st_size}\0".encode("utf-8"))
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_key(project_root: Path, path: Path) -> str:
    root = kb_root(project_root).resolve()
    target = path.resolve()
    try:
        key = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise SystemExit(f"Journal target must be inside kb/: {path}") from exc
    if key in {"", ".", JOURNAL_DIRNAME} or key.startswith(f"{JOURNAL_DIRNAME}/"):
        raise SystemExit(f"Invalid journal target: {path}")
    return key


def _target_path(project_root: Path, key: str) -> Path:
    root = kb_root(project_root).resolve()
    target = (root / key).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"Invalid journal target: {key}") from exc
    if key in {"", ".", JOURNAL_DIRNAME} or key.startswith(f"{JOURNAL_DIRNAME}/"):
        raise SystemExit(f"Invalid journal target: {key}")
    return target


def target_path(project_root: Path, key: str) -> Path:
    return _target_path(project_root, key)


def _ensure_journal_runtime(project_root: Path) -> None:
    # Workspace initialization owns the canonical .gitignore.  Lock/journal
    # bootstrap may create ignored runtime state only; it must never perform an
    # undeclared write to a caller's versioned path set.
    journal_root(project_root).mkdir(parents=True, exist_ok=True)


def _snapshot_payload_path(project_root: Path, relative_path: str) -> Path:
    root = journal_root(project_root).resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Invalid journal snapshot path: {relative_path}") from exc
    return path


def _snapshot_target(project_root: Path, op_id: str, key: str) -> dict:
    target = _target_path(project_root, key)
    if not target.exists() and not target.is_symlink():
        return {"kind": "absent", "mode": None, "digest": None}

    mode = target.lstat().st_mode & 0o7777
    digest = file_digest(target)
    payload_root = journal_root(project_root) / SNAPSHOT_DIRNAME / op_id / hashlib.sha256(key.encode("utf-8")).hexdigest()
    payload_root.mkdir(parents=True, exist_ok=False)
    if target.is_symlink():
        return {
            "kind": "symlink",
            "mode": mode,
            "digest": digest,
            "link_target": os.readlink(target),
        }
    if target.is_dir():
        snapshot = payload_root / "tree"
        shutil.copytree(target, snapshot, symlinks=True, copy_function=shutil.copy2)
        if file_digest(snapshot) != digest:
            raise RuntimeError(f"Journal target changed while snapshotting: {key}")
        return {
            "kind": "directory",
            "mode": mode,
            "digest": digest,
            "snapshot_path": snapshot.relative_to(journal_root(project_root)).as_posix(),
        }

    snapshot = payload_root / "data"
    data = target.read_bytes()
    write_bytes_atomic(snapshot, data, mode=mode)
    if file_digest(target) != digest:
        raise RuntimeError(f"Journal target changed while snapshotting: {key}")
    return {
        "kind": "file",
        "mode": mode,
        "digest": digest,
        "snapshot_path": snapshot.relative_to(journal_root(project_root)).as_posix(),
    }


def _remove_target(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _restore_directory(snapshot: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged = target.parent / f".{target.name}.restore-{token}"
    previous = target.parent / f".{target.name}.previous-{token}"
    shutil.copytree(snapshot, staged, symlinks=True, copy_function=shutil.copy2)
    os.chmod(staged, mode)
    moved_previous = False
    try:
        if target.exists() or target.is_symlink():
            os.replace(target, previous)
            moved_previous = True
        os.replace(staged, target)
    except BaseException:
        if moved_previous and not target.exists() and previous.exists():
            os.replace(previous, target)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
        if previous.exists() or previous.is_symlink():
            _remove_target(previous)


def _restore_target(project_root: Path, key: str, snapshot: dict) -> Path:
    target = _target_path(project_root, key)
    kind = str(snapshot.get("kind") or "")
    mode_value = snapshot.get("mode")
    mode = int(mode_value) if mode_value is not None else 0o644
    if kind == "absent":
        _remove_target(target)
    elif kind == "file":
        payload = _snapshot_payload_path(project_root, str(snapshot.get("snapshot_path") or ""))
        if not payload.is_file():
            raise RuntimeError(f"Missing journal file snapshot for {key}")
        if target.exists() and target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        write_bytes_atomic(target, payload.read_bytes(), mode=mode)
    elif kind == "directory":
        payload = _snapshot_payload_path(project_root, str(snapshot.get("snapshot_path") or ""))
        if not payload.is_dir():
            raise RuntimeError(f"Missing journal directory snapshot for {key}")
        _restore_directory(payload, target, mode)
    elif kind == "symlink":
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.parent / f".{target.name}.restore-link-{uuid.uuid4().hex}"
        os.symlink(str(snapshot.get("link_target") or ""), staged)
        try:
            if target.exists() and target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            os.replace(staged, target)
        finally:
            if staged.is_symlink() or staged.exists():
                staged.unlink()
    else:
        raise RuntimeError(f"Unsupported journal snapshot kind for {key}: {kind or '<empty>'}")

    expected_digest = snapshot.get("digest")
    actual_digest = file_digest(target)
    if actual_digest != expected_digest:
        raise RuntimeError(
            f"Journal restore verification failed for {key}: expected {expected_digest}, found {actual_digest}"
        )
    return target


def load_op(project_root: Path, op_id: str) -> dict:
    entry = load_yaml(journal_entry_path(project_root, op_id), default=None)
    if not isinstance(entry, dict):
        raise SystemExit(f"Unknown operation: {op_id}")
    return entry


def _project_context_key(project_root: Path) -> str:
    return project_root.resolve().as_posix()


def current_operation_id(project_root: Path) -> str:
    """Return the innermost active operation for this workspace, if any."""
    project_key = _project_context_key(project_root)
    for active_root, op_id in reversed(_ACTIVE_OP_STACK.get()):
        if active_root == project_key:
            return op_id
    env_root = str(os.environ.get(JOURNAL_PARENT_ROOT_ENV) or "").strip()
    env_op = str(os.environ.get(JOURNAL_PARENT_OP_ENV) or "").strip()
    if env_op and env_root:
        try:
            if Path(env_root).resolve().as_posix() == project_key:
                return env_op
        except OSError:
            return ""
    return ""


def journal_subprocess_env(
    project_root: Path,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy an environment and attach the current transaction as parent.

    Subprocess journal entries then become non-undoable descendants of the
    command-level transaction instead of independent user operations.
    """
    env = dict(os.environ if base_env is None else base_env)
    parent_op_id = current_operation_id(project_root)
    if parent_op_id:
        env[JOURNAL_PARENT_OP_ENV] = parent_op_id
        env[JOURNAL_PARENT_ROOT_ENV] = _project_context_key(project_root)
    else:
        env.pop(JOURNAL_PARENT_OP_ENV, None)
        env.pop(JOURNAL_PARENT_ROOT_ENV, None)
    return env


def _nested_root_entry(
    project_root: Path,
    parent_op_id: str,
) -> tuple[dict, dict]:
    parent = load_op(project_root, parent_op_id)
    if parent.get("state") != "begin":
        raise SystemExit(f"Parent journal operation is not active: {parent_op_id}")
    root_op_id = str(parent.get("root_op_id") or parent.get("op_id") or "").strip()
    if not root_op_id:
        raise SystemExit(f"Parent journal operation has no root id: {parent_op_id}")
    root_entry = parent if root_op_id == parent_op_id else load_op(project_root, root_op_id)
    if root_entry.get("state") != "begin":
        raise SystemExit(f"Root journal operation is not active: {root_op_id}")
    return parent, root_entry


def _path_key_is_covered(key: str, declared_key: str) -> bool:
    key_path = Path(key)
    declared_path = Path(declared_key)
    return key_path == declared_path or declared_path in key_path.parents


def _validate_nested_target_keys(root_entry: dict, keys: Sequence[str]) -> None:
    declared = [str(item) for item in root_entry.get("target_paths", []) if str(item)]
    uncovered = [key for key in keys if not any(_path_key_is_covered(key, target) for target in declared)]
    if uncovered:
        root_op_id = str(root_entry.get("op_id") or "")
        raise SystemExit(
            "Nested journal targets must be covered by the root transaction "
            f"{root_op_id}: {', '.join(uncovered)}"
        )


def committed_ops(project_root: Path) -> list[dict]:
    root = journal_root(project_root)
    if not root.exists():
        return []
    ordered_entries: list[tuple[int, dict]] = []
    for path in root.glob("*.yaml"):
        entry = load_yaml(path, default=None)
        if not isinstance(entry, dict) or entry.get("state") != "commit":
            continue
        before = entry.get("before_digests", {})
        after = entry.get("after_digests", {})
        if isinstance(before, dict) and isinstance(after, dict) and before != after:
            sequence = int(entry.get("sequence_ns") or path.stat().st_mtime_ns)
            ordered_entries.append((sequence, entry))
    return [entry for _, entry in sorted(ordered_entries, key=lambda item: item[0])]


def incomplete_ops(project_root: Path) -> list[dict]:
    """Return only incomplete root transactions, never nested descendants.

    Restoring every nested snapshot independently is unsafe: an inner snapshot
    represents a partial state *after* its outer transaction began.  Resume must
    restore the root before-image once, then terminally abort all descendants.
    """
    root = journal_root(project_root)
    if not root.exists():
        return []
    ordered_entries: list[tuple[int, dict]] = []
    for path in root.glob("*.yaml"):
        entry = load_yaml(path, default=None)
        if not isinstance(entry, dict) or entry.get("state") != "begin":
            continue
        sequence = int(entry.get("sequence_ns") or path.stat().st_mtime_ns)
        ordered_entries.append((sequence, entry))
    begin_ids = {str(entry.get("op_id") or "") for _, entry in ordered_entries}
    root_entries = []
    for sequence, entry in ordered_entries:
        parent_op_id = str(entry.get("parent_op_id") or "")
        root_op_id = str(entry.get("root_op_id") or entry.get("op_id") or "")
        # Orphaned children are recoverable as roots of the remaining incomplete
        # set; valid descendants are suppressed in favor of their outer snapshot.
        if parent_op_id in begin_ids or (root_op_id in begin_ids and root_op_id != entry.get("op_id")):
            continue
        root_entries.append((sequence, entry))
    return [entry for _, entry in sorted(root_entries, key=lambda item: item[0])]


def _legacy_entry_is_internal(entry: dict) -> bool:
    """Central compatibility rule for pre-metadata journal entries only."""
    targets = {str(path) for path in entry.get("target_paths", [])}
    if targets and targets <= {".runtime/versioning-state.yaml"}:
        return True
    op_type = str(entry.get("op_type") or "")
    return op_type == "write_versioning_state" or op_type.startswith(("undo:", "restore:", "resume:"))


def _entry_is_undo_candidate(entry: dict) -> bool:
    op_id = str(entry.get("op_id") or "")
    if not op_id or str(entry.get("parent_op_id") or "") or str(entry.get("undone_by") or ""):
        return False
    root_op_id = str(entry.get("root_op_id") or op_id)
    if root_op_id != op_id:
        return False
    if "undoable" in entry:
        return entry.get("undoable") is True
    # Legacy journals predate hierarchy metadata.  Keep recoverable root business
    # entries usable, while one centralized migration rule excludes the two known
    # internal classes; all newly written entries use explicit metadata only.
    has_recovery_material = bool(entry.get("before_snapshots")) or bool(entry.get("before_digests"))
    return has_recovery_material and not _legacy_entry_is_internal(entry)


def latest_committed_op(project_root: Path) -> dict:
    entries = [entry for entry in committed_ops(project_root) if _entry_is_undo_candidate(entry)]
    if not entries:
        raise SystemExit("没有可撤销的已提交操作。")
    return entries[-1]


def begin_op(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
    *,
    undoable: bool = True,
    operation_role: str = "user",
    coordination_scope: str = "none",
    parent_op_id: str | None = None,
    attach_to_active: bool = True,
) -> str:
    _ensure_journal_runtime(project_root)
    journal_root(project_root).mkdir(parents=True, exist_ok=True)
    keys = sorted({_target_key(project_root, Path(path)) for path in target_paths})
    if not keys:
        raise SystemExit("Journal operation requires at least one explicit target path.")
    for index, key in enumerate(keys):
        key_path = Path(key)
        if any(key_path in Path(other).parents for other in keys[index + 1 :]):
            raise SystemExit(f"Journal targets cannot overlap: {key}")
    sequence_ns = time.time_ns()
    op_id = f"{sequence_ns}-{uuid.uuid4().hex[:12]}"
    resolved_parent_id = str(parent_op_id or "").strip()
    if not resolved_parent_id and attach_to_active:
        resolved_parent_id = current_operation_id(project_root)
    if resolved_parent_id:
        parent_entry, root_entry = _nested_root_entry(project_root, resolved_parent_id)
        _validate_nested_target_keys(root_entry, keys)
        root_op_id = str(root_entry.get("op_id") or "")
        transaction_depth = int(parent_entry.get("transaction_depth") or 0) + 1
        resolved_coordination_scope = (
            "inherited"
            if root_entry.get("coordination_scope") == "workspace-exclusive"
            else str(coordination_scope or "none")
        )
    else:
        root_op_id, transaction_depth = op_id, 0
        resolved_coordination_scope = str(coordination_scope or "none")
    before_snapshots = {key: _snapshot_target(project_root, op_id, key) for key in keys}
    entry = {
        "op_id": op_id,
        "op_type": str(op_type),
        "operation_role": str(operation_role or "user"),
        "coordination_scope": resolved_coordination_scope,
        "parent_op_id": resolved_parent_id,
        "root_op_id": root_op_id,
        "transaction_depth": transaction_depth,
        # Nested work is recovered by its root before-image and must never win
        # `kb undo`; bookkeeping/recovery callers opt out explicitly as well.
        "undoable": bool(undoable and not resolved_parent_id),
        "started_at": utc_now_iso(),
        "sequence_ns": sequence_ns,
        "target_paths": keys,
        "before_digests": {key: snapshot.get("digest") for key, snapshot in before_snapshots.items()},
        "before_snapshots": before_snapshots,
        "after_digests": {},
        "state": "begin",
    }
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)
    return op_id


def commit_op(project_root: Path, op_id: str) -> None:
    entry = load_op(project_root, op_id)
    keys = [str(key) for key in entry.get("target_paths", [])]
    entry["after_digests"] = {key: file_digest(_target_path(project_root, key)) for key in keys}
    entry["completed_at"] = utc_now_iso()
    entry["state"] = "commit"
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)


def restore_before_snapshots(project_root: Path, op_id: str) -> list[Path]:
    entry = load_op(project_root, op_id)
    snapshots = entry.get("before_snapshots", {})
    if not isinstance(snapshots, dict) or not snapshots:
        raise RuntimeError(f"Operation {op_id} has no before snapshots to restore.")
    restored: list[Path] = []
    for key in [str(item) for item in entry.get("target_paths", [])]:
        snapshot = snapshots.get(key)
        if not isinstance(snapshot, dict):
            raise RuntimeError(f"Operation {op_id} is missing the before snapshot for {key}.")
        restored.append(_restore_target(project_root, key, snapshot))
    return restored


def _descendant_entries(project_root: Path, op_id: str) -> list[tuple[Path, dict]]:
    root = journal_root(project_root)
    if not root.exists():
        return []
    entries: list[tuple[Path, dict]] = []
    for path in root.glob("*.yaml"):
        entry = load_yaml(path, default=None)
        if isinstance(entry, dict) and entry.get("op_id"):
            entries.append((path, entry))
    descendants: list[tuple[Path, dict]] = []
    frontier = {op_id}
    while frontier:
        children = [
            (path, entry)
            for path, entry in entries
            if str(entry.get("parent_op_id") or "") in frontier
            and str(entry.get("op_id") or "") != op_id
            and all(str(entry.get("op_id") or "") != str(found.get("op_id") or "") for _, found in descendants)
        ]
        if not children:
            break
        descendants.extend(children)
        frontier = {str(entry.get("op_id") or "") for _, entry in children}
    return sorted(
        descendants,
        key=lambda item: (int(item[1].get("transaction_depth") or 0), int(item[1].get("sequence_ns") or 0)),
        reverse=True,
    )


def _abort_descendants(project_root: Path, op_id: str, *, error: str = "") -> None:
    for path, entry in _descendant_entries(project_root, op_id):
        if entry.get("state") in {"abort", "abort_failed"}:
            continue
        entry["completed_at"] = utc_now_iso()
        entry["state"] = "abort"
        entry["aborted_with_ancestor"] = op_id
        if error:
            entry["operation_error"] = error
        write_yaml_if_changed(path, entry)


def abort_op(project_root: Path, op_id: str, *, restore: bool = False, error: str = "") -> None:
    if restore:
        try:
            restore_before_snapshots(project_root, op_id)
        except BaseException as exc:
            entry = load_op(project_root, op_id)
            entry["completed_at"] = utc_now_iso()
            entry["state"] = "abort_failed"
            entry["restoration_error"] = str(exc)
            if error:
                entry["operation_error"] = error
            write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)
            raise RuntimeError(f"Failed to restore operation {op_id}: {exc}") from exc
    entry = load_op(project_root, op_id)
    entry["completed_at"] = utc_now_iso()
    entry["state"] = "abort"
    if error:
        entry["operation_error"] = error
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)
    _abort_descendants(project_root, op_id, error=error)


def mark_op_undone(project_root: Path, op_id: str, recovery_op_id: str) -> None:
    entry = load_op(project_root, op_id)
    if not _entry_is_undo_candidate(entry):
        raise SystemExit(f"Operation is not undoable: {op_id}")
    entry["undone_by"] = recovery_op_id
    entry["undone_at"] = utc_now_iso()
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)


@contextmanager
def journaled_op(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
    *,
    undoable: bool = True,
    operation_role: str = "user",
    coordination_scope: str = "none",
    parent_op_id: str | None = None,
    attach_to_active: bool = True,
) -> Iterator[str]:
    op_id = begin_op(
        project_root,
        op_type,
        target_paths,
        undoable=undoable,
        operation_role=operation_role,
        coordination_scope=coordination_scope,
        parent_op_id=parent_op_id,
        attach_to_active=attach_to_active,
    )
    stack = _ACTIVE_OP_STACK.get()
    token = _ACTIVE_OP_STACK.set((*stack, (_project_context_key(project_root), op_id)))
    try:
        yield op_id
        commit_op(project_root, op_id)
    except BaseException as exc:
        abort_op(project_root, op_id, restore=True, error=str(exc))
        raise
    finally:
        _ACTIVE_OP_STACK.reset(token)


@contextmanager
def mutation_transaction(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
    *,
    undoable: bool = True,
    operation_role: str = "user",
    preflight: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Coordinate and journal one command-level mutation transaction.

    The default is a user-visible, undoable root operation.  When nested under
    another transaction (including through ``journal_subprocess_env``), the
    targets must be covered by the root's declared path set.  Valid descendants
    inherit the root's workspace lock and are recovered by its before-image.
    """
    targets = sorted(
        {Path(path).resolve() for path in target_paths},
        key=lambda path: path.as_posix(),
    )
    if not targets:
        raise SystemExit("Mutation transaction requires at least one explicit target path.")
    # Lazy import avoids common -> journal -> common initialization cycles.
    from .common import exclusive_file_lock

    parent_op_id = current_operation_id(project_root)
    if parent_op_id:
        _, root_entry = _nested_root_entry(project_root, parent_op_id)
        keys = [_target_key(project_root, path) for path in targets]
        _validate_nested_target_keys(root_entry, keys)
        if root_entry.get("coordination_scope") != "workspace-exclusive":
            raise SystemExit(
                "Nested mutation requires a root mutation_transaction with workspace coordination."
            )
        if preflight is not None:
            preflight()
        with journaled_op(
            project_root,
            op_type,
            targets,
            undoable=undoable,
            operation_role=operation_role,
            coordination_scope="inherited",
        ) as op_id:
            yield op_id
        return

    # The conservative workspace lease makes an independent directory target
    # mutually exclusive with every descendant target.  Nested subprocesses do
    # not reacquire it: their signed parent context is validated above, avoiding
    # parent-waits-child deadlocks during analyzer execution.
    with exclusive_file_lock(workspace_transaction_lock_path(project_root)):
        with ExitStack() as locks:
            for path in targets:
                locks.enter_context(exclusive_file_lock(operation_lock_path(project_root, path)))
            if preflight is not None:
                preflight()
            with journaled_op(
                project_root,
                op_type,
                targets,
                undoable=undoable,
                operation_role=operation_role,
                coordination_scope="workspace-exclusive",
            ) as op_id:
                yield op_id

"""Crash-safe operation journal for KB mutations."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
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


def _node_kind(metadata: os.stat_result) -> str:
    node_type = stat.S_IFMT(metadata.st_mode)
    if stat.S_ISREG(node_type):
        return "file"
    if stat.S_ISDIR(node_type):
        return "directory"
    if stat.S_ISLNK(node_type):
        return "symlink"
    return "special"


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _same_node(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        stat.S_IFMT(first.st_mode),
    ) == (
        second.st_dev,
        second.st_ino,
        stat.S_IFMT(second.st_mode),
    )


def _special_identity(metadata: os.stat_result) -> str:
    return "\0".join(
        str(value)
        for value in (
            stat.S_IFMT(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode),
            metadata.st_dev,
            metadata.st_ino,
            getattr(metadata, "st_rdev", 0),
        )
    )


def _open_regular_nonblocking(path: Path, expected: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"Journal file changed while opening: {path}") from exc
    opened = os.fstat(descriptor)
    if _node_kind(opened) != "file" or not _same_node(expected, opened):
        os.close(descriptor)
        raise RuntimeError(f"Journal file changed type or identity while opening: {path}")
    return descriptor


def _update_regular_digest(
    digest: "hashlib._Hash",
    path: Path,
    metadata: os.stat_result,
) -> None:
    descriptor = _open_regular_nonblocking(path, metadata)
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)


def _read_regular_bytes(path: Path, metadata: os.stat_result) -> bytes:
    chunks: list[bytes] = []
    descriptor = _open_regular_nonblocking(path, metadata)
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _copy_regular_nonblocking(
    source: Path,
    destination: Path,
    metadata: os.stat_result,
) -> None:
    source_descriptor = _open_regular_nonblocking(source, metadata)
    destination_descriptor = -1
    try:
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IMODE(metadata.st_mode),
        )
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_descriptor, view)
                view = view[written:]
    except BaseException:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
            destination_descriptor = -1
        if _lstat(destination) is not None:
            destination.unlink()
        raise
    finally:
        os.close(source_descriptor)
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
    shutil.copystat(source, destination, follow_symlinks=False)


def _special_nodes(path: Path) -> list[str]:
    metadata = _lstat(path)
    if metadata is None:
        return []
    kind = _node_kind(metadata)
    if kind == "special":
        return ["."]
    if kind != "directory":
        return []
    found: list[str] = []
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        child_metadata = _lstat(child)
        if child_metadata is not None and _node_kind(child_metadata) == "special":
            found.append(child.relative_to(path).as_posix())
    return found


def _assert_snapshot_target_supported(path: Path, key: str) -> None:
    special_nodes = _special_nodes(path)
    if special_nodes:
        raise SystemExit(
            "Journal snapshot refuses special filesystem nodes in "
            f"{key}: {', '.join(special_nodes)}"
        )


def file_digest(path: Path) -> str | None:
    metadata = _lstat(path)
    if metadata is None:
        return None
    digest = hashlib.sha256()
    mode = stat.S_IMODE(metadata.st_mode)
    kind = _node_kind(metadata)
    if kind == "symlink":
        digest.update(f"symlink\0{mode}\0{os.readlink(path)}".encode("utf-8"))
        return digest.hexdigest()
    if kind == "directory":
        digest.update(f"directory\0{mode}\0".encode("utf-8"))
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix()
            child_metadata = child.lstat()
            child_mode = stat.S_IMODE(child_metadata.st_mode)
            child_kind = _node_kind(child_metadata)
            if child_kind == "symlink":
                digest.update(f"L\0{relative}\0{child_mode}\0{os.readlink(child)}\0".encode("utf-8"))
            elif child_kind == "directory":
                digest.update(f"D\0{relative}\0{child_mode}\0".encode("utf-8"))
            elif child_kind == "file":
                digest.update(f"F\0{relative}\0{child_mode}\0{child_metadata.st_size}\0".encode("utf-8"))
                _update_regular_digest(digest, child, child_metadata)
            else:
                digest.update(
                    f"S\0{relative}\0{_special_identity(child_metadata)}\0".encode("utf-8")
                )
        return digest.hexdigest()
    if kind == "file":
        digest.update(f"file\0{mode}\0{metadata.st_size}\0".encode("utf-8"))
        _update_regular_digest(digest, path, metadata)
        return digest.hexdigest()
    digest.update(f"special\0{_special_identity(metadata)}\0".encode("utf-8"))
    return digest.hexdigest()


def _copy_safe_tree(source: Path, destination: Path) -> None:
    source_metadata = source.lstat()
    if _node_kind(source_metadata) != "directory":
        raise RuntimeError(f"Journal directory changed type while copying: {source}")
    destination.mkdir(mode=stat.S_IMODE(source_metadata.st_mode))
    try:
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            child_metadata = child.lstat()
            child_kind = _node_kind(child_metadata)
            copied = destination / child.name
            if child_kind == "directory":
                _copy_safe_tree(child, copied)
            elif child_kind == "symlink":
                os.symlink(os.readlink(child), copied)
                shutil.copystat(child, copied, follow_symlinks=False)
            elif child_kind == "file":
                _copy_regular_nonblocking(child, copied, child_metadata)
            else:
                raise RuntimeError(f"Journal refuses to copy special filesystem node: {child}")
        shutil.copystat(source, destination, follow_symlinks=False)
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination)
        raise


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
    target_metadata = _lstat(target)
    if target_metadata is None:
        return {"kind": "absent", "mode": None, "digest": None}

    kind = _node_kind(target_metadata)
    if kind == "special":
        raise SystemExit(f"Journal snapshot refuses special filesystem node: {key}")
    mode = stat.S_IMODE(target_metadata.st_mode)
    digest = file_digest(target)
    payload_root = journal_root(project_root) / SNAPSHOT_DIRNAME / op_id / hashlib.sha256(key.encode("utf-8")).hexdigest()
    payload_root.mkdir(parents=True, exist_ok=False)
    if kind == "symlink":
        return {
            "kind": "symlink",
            "mode": mode,
            "digest": digest,
            "link_target": os.readlink(target),
        }
    if kind == "directory":
        snapshot = payload_root / "tree"
        _copy_safe_tree(target, snapshot)
        if file_digest(snapshot) != digest:
            raise RuntimeError(f"Journal target changed while snapshotting: {key}")
        return {
            "kind": "directory",
            "mode": mode,
            "digest": digest,
            "snapshot_path": snapshot.relative_to(journal_root(project_root)).as_posix(),
        }

    snapshot = payload_root / "data"
    data = _read_regular_bytes(target, target_metadata)
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
    metadata = _lstat(path)
    if metadata is None:
        return
    if _node_kind(metadata) != "directory":
        path.unlink()
    else:
        shutil.rmtree(path)


def _restore_directory(snapshot: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged = target.parent / f".{target.name}.restore-{token}"
    previous = target.parent / f".{target.name}.previous-{token}"
    _copy_safe_tree(snapshot, staged)
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
        payload_metadata = _lstat(payload)
        if payload_metadata is None or _node_kind(payload_metadata) != "file":
            raise RuntimeError(f"Missing journal file snapshot for {key}")
        target_metadata = _lstat(target)
        if target_metadata is not None and _node_kind(target_metadata) == "directory":
            shutil.rmtree(target)
        write_bytes_atomic(target, _read_regular_bytes(payload, payload_metadata), mode=mode)
    elif kind == "directory":
        payload = _snapshot_payload_path(project_root, str(snapshot.get("snapshot_path") or ""))
        payload_metadata = _lstat(payload)
        if payload_metadata is None or _node_kind(payload_metadata) != "directory":
            raise RuntimeError(f"Missing journal directory snapshot for {key}")
        _restore_directory(payload, target, mode)
    elif kind == "symlink":
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.parent / f".{target.name}.restore-link-{uuid.uuid4().hex}"
        os.symlink(str(snapshot.get("link_target") or ""), staged)
        try:
            target_metadata = _lstat(target)
            if target_metadata is not None and _node_kind(target_metadata) == "directory":
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
    # Validate every declared target before creating any payload or journal
    # entry.  Existing FIFOs/sockets/devices must fail before the caller can
    # enter the business mutation body, and must never reach a copying reader.
    for key in keys:
        _assert_snapshot_target_supported(_target_path(project_root, key), key)
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
    try:
        before_snapshots = {key: _snapshot_target(project_root, op_id, key) for key in keys}
    except BaseException:
        operation_snapshots = journal_root(project_root) / SNAPSHOT_DIRNAME / op_id
        if operation_snapshots.exists():
            shutil.rmtree(operation_snapshots)
        raise
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
        target = _target_path(project_root, key)
        # Restoration is defined by the journal's existing digest contract.  If
        # the target never diverged from its before-state, replacing it would be
        # needless churn and can invalidate consumers that bind regular-file or
        # directory inode identity.  Keep returning every declared target so
        # recovery checkpoint/reporting behavior remains unchanged.
        if "digest" in snapshot and file_digest(target) == snapshot.get("digest"):
            restored.append(target)
            continue
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

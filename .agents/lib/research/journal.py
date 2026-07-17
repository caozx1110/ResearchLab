"""Crash-safe operation journal for KB mutations."""
from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from .common import utc_now_iso
from .paths import kb_root
from .yaml_io import load_yaml, write_bytes_atomic, write_text_if_changed, write_yaml_if_changed


JOURNAL_DIRNAME = ".journal"
SNAPSHOT_DIRNAME = "snapshots"


def journal_root(project_root: Path) -> Path:
    return kb_root(project_root) / JOURNAL_DIRNAME


def journal_entry_path(project_root: Path, op_id: str) -> Path:
    if not op_id or Path(op_id).name != op_id:
        raise SystemExit(f"Invalid operation id: {op_id}")
    return journal_root(project_root) / f"{op_id}.yaml"


def operation_lock_path(project_root: Path, target_path: Path) -> Path:
    _ensure_journal_ignored(project_root)
    key = _target_key(project_root, target_path)
    name = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return journal_root(project_root) / "locks" / f"{name}.lock"


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


def _ensure_journal_ignored(project_root: Path) -> None:
    root = journal_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    bootstrap_lock = root / ".journal.lock"
    with bootstrap_lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            _write_journal_ignore_rule(project_root)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_journal_ignore_rule(project_root: Path) -> None:
    path = kb_root(project_root) / ".gitignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if f"{JOURNAL_DIRNAME}/" in lines:
        return
    if lines and lines[-1]:
        lines.append("")
    lines.extend(["# Operation recovery journal", f"{JOURNAL_DIRNAME}/"])
    write_text_if_changed(path, "\n".join(lines).rstrip() + "\n")


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
    return [entry for _, entry in sorted(ordered_entries, key=lambda item: item[0])]


def latest_committed_op(project_root: Path) -> dict:
    entries = committed_ops(project_root)
    if not entries:
        raise SystemExit("没有可撤销的已提交操作。")
    return entries[-1]


def begin_op(project_root: Path, op_type: str, target_paths: Sequence[Path]) -> str:
    _ensure_journal_ignored(project_root)
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
    before_snapshots = {key: _snapshot_target(project_root, op_id, key) for key in keys}
    entry = {
        "op_id": op_id,
        "op_type": str(op_type),
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


@contextmanager
def journaled_op(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
) -> Iterator[str]:
    op_id = begin_op(project_root, op_type, target_paths)
    try:
        yield op_id
    except BaseException as exc:
        abort_op(project_root, op_id, restore=True, error=str(exc))
        raise
    commit_op(project_root, op_id)

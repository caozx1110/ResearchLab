"""Crash-safe operation journal for KB mutations."""
from __future__ import annotations

import hashlib
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from .common import utc_now_iso
from .paths import kb_root
from .yaml_io import load_yaml, write_text_if_changed, write_yaml_if_changed


JOURNAL_DIRNAME = ".journal"


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
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_key(project_root: Path, path: Path) -> str:
    root = kb_root(project_root).resolve()
    target = path.resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise SystemExit(f"Journal target must be inside kb/: {path}") from exc


def _target_path(project_root: Path, key: str) -> Path:
    root = kb_root(project_root).resolve()
    target = (root / key).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"Invalid journal target: {key}") from exc
    return target


def target_path(project_root: Path, key: str) -> Path:
    return _target_path(project_root, key)


def _ensure_journal_ignored(project_root: Path) -> None:
    path = kb_root(project_root) / ".gitignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if f"{JOURNAL_DIRNAME}/" in lines:
        return
    if lines and lines[-1]:
        lines.append("")
    lines.extend(["# Operation recovery journal", f"{JOURNAL_DIRNAME}/"])
    write_text_if_changed(path, "\n".join(lines).rstrip() + "\n")


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


def latest_committed_op(project_root: Path) -> dict:
    entries = committed_ops(project_root)
    if not entries:
        raise SystemExit("没有可撤销的已提交操作。")
    return entries[-1]


def begin_op(project_root: Path, op_type: str, target_paths: Sequence[Path]) -> str:
    _ensure_journal_ignored(project_root)
    journal_root(project_root).mkdir(parents=True, exist_ok=True)
    keys = sorted({_target_key(project_root, Path(path)) for path in target_paths})
    sequence_ns = time.time_ns()
    op_id = f"{sequence_ns}-{uuid.uuid4().hex[:12]}"
    entry = {
        "op_id": op_id,
        "op_type": str(op_type),
        "started_at": utc_now_iso(),
        "sequence_ns": sequence_ns,
        "target_paths": keys,
        "before_digests": {key: file_digest(_target_path(project_root, key)) for key in keys},
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


def abort_op(project_root: Path, op_id: str) -> None:
    entry = load_op(project_root, op_id)
    entry["completed_at"] = utc_now_iso()
    entry["state"] = "abort"
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
    except BaseException:
        abort_op(project_root, op_id)
        raise
    commit_op(project_root, op_id)

"""Crash-safe operation journal for KB mutations."""
from __future__ import annotations

import hashlib
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
    return journal_root(project_root) / f"{op_id}.yaml"


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
    return kb_root(project_root) / key


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


def begin_op(project_root: Path, op_type: str, target_paths: Sequence[Path]) -> str:
    _ensure_journal_ignored(project_root)
    journal_root(project_root).mkdir(parents=True, exist_ok=True)
    keys = sorted({_target_key(project_root, Path(path)) for path in target_paths})
    op_id = f"{utc_now_iso().replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:12]}"
    entry = {
        "op_id": op_id,
        "op_type": str(op_type),
        "started_at": utc_now_iso(),
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
    entry["state"] = "commit"
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)


def abort_op(project_root: Path, op_id: str) -> None:
    entry = load_op(project_root, op_id)
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

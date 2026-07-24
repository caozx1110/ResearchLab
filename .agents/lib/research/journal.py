"""Crash-safe operation journal for KB mutations."""
from __future__ import annotations

import hashlib
import fcntl
import copy
import os
import shutil
import stat
import time
import threading
import uuid
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from .common import utc_now_iso
from .paths import kb_root
from . import yaml_io
from .yaml_io import write_bytes_atomic, write_yaml_if_changed


JOURNAL_DIRNAME = ".journal"
SNAPSHOT_DIRNAME = "snapshots"
JOURNAL_PARENT_OP_ENV = "RESEARCH_JOURNAL_PARENT_OP"
JOURNAL_PARENT_ROOT_ENV = "RESEARCH_JOURNAL_PARENT_ROOT"
MAX_JOURNAL_ENTRY_BYTES = 8 * 1024 * 1024
KNOWN_JOURNAL_STATES = {"begin", "commit", "abort", "abort_failed"}

# Each entry is (resolved project root, operation id).  ContextVar keeps nested
# transactions correct across async contexts while the environment bridge below
# carries the same hierarchy into analyzer subprocesses spawned by one command.
_ACTIVE_OP_STACK: ContextVar[tuple[tuple[str, str], ...]] = ContextVar(
    "research_journal_active_ops",
    default=(),
)

# Recovery has to create one bookkeeping journal while the crashed root that it
# is repairing is still in ``begin`` state.  Keep that exception private and
# context-bound: the public ``operation_role`` label is metadata, not an
# authorization switch that arbitrary callers may use to bypass quarantine.
_RECOVERY_BEGIN_DEPTH: ContextVar[int] = ContextVar(
    "research_journal_recovery_begin_depth",
    default=0,
)
_JOURNAL_ENVELOPE_CACHE_LOCK = threading.Lock()
_JOURNAL_ENVELOPE_CACHE: dict[str, tuple[tuple[int, int, int, int, int], dict]] = {}


def journal_root(project_root: Path) -> Path:
    return kb_root(project_root) / JOURNAL_DIRNAME


def journal_entry_path(project_root: Path, op_id: str) -> Path:
    if not op_id or Path(op_id).name != op_id:
        raise SystemExit(f"Invalid operation id: {op_id}")
    return journal_root(project_root) / f"{op_id}.yaml"


def _existing_journal_root(project_root: Path) -> Path | None:
    root = journal_root(project_root)
    metadata = _lstat(root)
    if metadata is None:
        return None
    if _node_kind(metadata) != "directory":
        raise SystemExit("操作日志运行目录类型异常；知识库已进入恢复隔离状态。")
    return root


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


def _same_read_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        _same_node(first, second)
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and first.st_ctime_ns == second.st_ctime_ns
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


def _read_regular_bytes(
    path: Path,
    metadata: os.stat_result,
    *,
    max_bytes: int | None = None,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    descriptor = _open_regular_nonblocking(path, metadata)
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise RuntimeError("Journal entry exceeded the bounded read limit.")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _yaml_has_duplicate_mapping_key(node: object) -> bool:
    node_id = getattr(node, "id", "")
    if node_id == "mapping":
        seen: set[tuple[str, str]] = set()
        for key_node, value_node in getattr(node, "value", []):
            identity = (
                str(getattr(key_node, "tag", "")),
                str(getattr(key_node, "value", "")),
            )
            if identity in seen or _yaml_has_duplicate_mapping_key(value_node):
                return True
            seen.add(identity)
        return False
    if node_id == "sequence":
        return any(_yaml_has_duplicate_mapping_key(item) for item in getattr(node, "value", []))
    return False


def _load_journal_entry_view(path: Path) -> tuple[dict, str]:
    metadata = _lstat(path)
    if metadata is None or _node_kind(metadata) != "file":
        raise SystemExit("操作日志包含非普通条目；知识库已进入恢复隔离状态。")
    if metadata.st_size <= 0 or metadata.st_size > MAX_JOURNAL_ENTRY_BYTES:
        raise SystemExit("操作日志条目为空或过大；知识库已进入恢复隔离状态。")
    try:
        raw = _read_regular_bytes(path, metadata, max_bytes=MAX_JOURNAL_ENTRY_BYTES)
    except RuntimeError as exc:
        raise SystemExit("操作日志条目超过安全读取上限；知识库已进入恢复隔离状态。") from exc
    current = _lstat(path)
    if (
        current is None
        or not _same_node(metadata, current)
        or current.st_size != metadata.st_size
        or current.st_mtime_ns != metadata.st_mtime_ns
    ):
        raise SystemExit("操作日志在读取期间发生变化；已停止当前操作。")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit("操作日志不是有效的 UTF-8 文本；知识库已进入恢复隔离状态。") from exc
    parser = yaml_io._yaml
    if parser is None:
        raise RuntimeError("PyYAML is required to validate operation journals safely.")
    try:
        node = parser.compose(text)
        if node is None or _yaml_has_duplicate_mapping_key(node):
            raise SystemExit("操作日志包含空内容或重复字段；知识库已进入恢复隔离状态。")
        payload = parser.safe_load(text)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SystemExit("操作日志无法完整解析；知识库已进入恢复隔离状态。") from exc
    if not isinstance(payload, dict):
        raise SystemExit("操作日志条目结构无效；知识库已进入恢复隔离状态。")
    if str(payload.get("op_id") or "") != path.stem:
        raise SystemExit("操作日志条目标识不一致；知识库已进入恢复隔离状态。")
    if str(payload.get("state") or "") not in KNOWN_JOURNAL_STATES:
        raise SystemExit("操作日志包含未知状态；知识库已进入恢复隔离状态。")
    _validate_journal_envelope_structure(payload)
    return payload, hashlib.sha256(raw).hexdigest()


def _load_journal_entry_file(path: Path) -> dict:
    metadata = _lstat(path)
    if metadata is None or _node_kind(metadata) != "file":
        raise SystemExit("操作日志包含非普通条目；知识库已进入恢复隔离状态。")
    signature = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    cache_key = path.absolute().as_posix()
    with _JOURNAL_ENVELOPE_CACHE_LOCK:
        cached = _JOURNAL_ENVELOPE_CACHE.get(cache_key)
        if cached is not None and cached[0] == signature:
            return copy.deepcopy(cached[1])
    payload, _ = _load_journal_entry_view(path)
    with _JOURNAL_ENVELOPE_CACHE_LOCK:
        _JOURNAL_ENVELOPE_CACHE[cache_key] = (signature, copy.deepcopy(payload))
    return payload


def _validate_journal_envelope_structure(entry: Mapping[str, object]) -> None:
    op_type = entry.get("op_type")
    if not isinstance(op_type, str) or not op_type.strip():
        raise SystemExit("操作日志缺少完整的操作类型；知识库已进入恢复隔离状态。")
    targets = entry.get("target_paths")
    before_digests = entry.get("before_digests")
    before_snapshots = entry.get("before_snapshots")
    after_digests = entry.get("after_digests")
    if (
        not isinstance(targets, list)
        or not targets
        or not isinstance(before_digests, dict)
        or not isinstance(after_digests, dict)
    ):
        raise SystemExit("操作日志信封不完整；知识库已进入恢复隔离状态。")
    if not isinstance(before_snapshots, dict):
        raise SystemExit("操作日志缺少完整的恢复前状态记录；知识库已进入恢复隔离状态。")
    keys = [_validate_target_key(item) for item in targets]
    if len(keys) != len(set(keys)):
        raise SystemExit("操作日志包含重复的恢复目标；知识库已进入恢复隔离状态。")
    expected = set(keys)
    for mapping in (before_digests, before_snapshots):
        if {_validate_target_key(key) for key in mapping} != expected:
            raise SystemExit("操作日志的恢复目标集合不一致；知识库已进入恢复隔离状态。")
    state = str(entry.get("state") or "")
    after_keys = {_validate_target_key(key) for key in after_digests}
    if state == "commit" and after_keys != expected:
        raise SystemExit("操作日志缺少完整的恢复后状态记录；知识库已进入恢复隔离状态。")
    if state == "begin" and after_keys:
        raise SystemExit("未完成操作日志包含意外后状态；知识库已进入恢复隔离状态。")
    if any(not isinstance(before_snapshots.get(key), dict) for key in keys):
        raise SystemExit("操作日志包含无效的恢复快照；知识库已进入恢复隔离状态。")


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


@contextmanager
def _anchored_target_parent(
    project_root: Path,
    key: str,
    *,
    create_missing: bool = False,
) -> Iterator[tuple[int | None, str]]:
    """Open a target parent from canonical KB root with no-follow traversal."""
    canonical_key = _validate_target_key(key)
    parts = canonical_key.split("/")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        descriptor = os.open(_canonical_kb_root(project_root), flags)
        descriptors.append(descriptor)
        for part in parts[:-1]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_missing:
                    yield None, parts[-1]
                    return
                os.mkdir(part, 0o755, dir_fd=descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            except OSError as exc:
                raise SystemExit("Journal target ancestor changed or is not a safe directory.") from exc
            descriptors.append(child)
            descriptor = child
        yield descriptor, parts[-1]
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _open_regular_at(parent_fd: int, name: str, expected: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise RuntimeError("Journal target changed while opening an anchored file.") from exc
    opened = os.fstat(descriptor)
    if _node_kind(opened) != "file" or not _same_node(expected, opened):
        os.close(descriptor)
        raise RuntimeError("Journal target changed type or identity while opening an anchored file.")
    return descriptor


def _update_digest_from_fd(digest: "hashlib._Hash", descriptor: int) -> int:
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return total
        total += len(chunk)
        digest.update(chunk)


def _update_anchored_directory_digest(
    digest: "hashlib._Hash",
    directory_fd: int,
    prefix: str = "",
) -> None:
    for name in sorted(os.listdir(directory_fd)):
        relative = f"{prefix}/{name}" if prefix else name
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        mode = stat.S_IMODE(metadata.st_mode)
        kind = _node_kind(metadata)
        if kind == "symlink":
            digest.update(
                f"L\0{relative}\0{mode}\0{os.readlink(name, dir_fd=directory_fd)}\0".encode("utf-8")
            )
        elif kind == "directory":
            digest.update(f"D\0{relative}\0{mode}\0".encode("utf-8"))
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            try:
                if not _same_node(metadata, os.fstat(child_fd)):
                    raise RuntimeError("Journal directory changed during anchored digest.")
                _update_anchored_directory_digest(digest, child_fd, relative)
                if not _same_read_identity(metadata, os.fstat(child_fd)):
                    raise RuntimeError("Journal directory changed during anchored digest.")
            finally:
                os.close(child_fd)
        elif kind == "file":
            digest.update(f"F\0{relative}\0{mode}\0{metadata.st_size}\0".encode("utf-8"))
            child_fd = _open_regular_at(directory_fd, name, metadata)
            try:
                total = _update_digest_from_fd(digest, child_fd)
                if total != metadata.st_size or not _same_read_identity(metadata, os.fstat(child_fd)):
                    raise RuntimeError("Journal file changed during anchored digest.")
            finally:
                os.close(child_fd)
        else:
            digest.update(f"S\0{relative}\0{_special_identity(metadata)}\0".encode("utf-8"))


def _anchored_target_digest(project_root: Path, key: str) -> str | None:
    with _anchored_target_parent(project_root, key) as (parent_fd, leaf):
        if parent_fd is None:
            return None
        metadata = _lstat_at(parent_fd, leaf)
        if metadata is None:
            return None
        digest = hashlib.sha256()
        mode = stat.S_IMODE(metadata.st_mode)
        kind = _node_kind(metadata)
        if kind == "symlink":
            digest.update(
                f"symlink\0{mode}\0{os.readlink(leaf, dir_fd=parent_fd)}".encode("utf-8")
            )
        elif kind == "directory":
            digest.update(f"directory\0{mode}\0".encode("utf-8"))
            directory_fd = os.open(
                leaf,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                if not _same_node(metadata, os.fstat(directory_fd)):
                    raise RuntimeError("Journal target changed during anchored digest.")
                _update_anchored_directory_digest(digest, directory_fd)
                if not _same_read_identity(metadata, os.fstat(directory_fd)):
                    raise RuntimeError("Journal target changed during anchored digest.")
            finally:
                os.close(directory_fd)
        elif kind == "file":
            digest.update(f"file\0{mode}\0{metadata.st_size}\0".encode("utf-8"))
            descriptor = _open_regular_at(parent_fd, leaf, metadata)
            try:
                total = _update_digest_from_fd(digest, descriptor)
                if total != metadata.st_size or not _same_read_identity(metadata, os.fstat(descriptor)):
                    raise RuntimeError("Journal target changed during anchored digest.")
            finally:
                os.close(descriptor)
        else:
            digest.update(f"special\0{_special_identity(metadata)}\0".encode("utf-8"))
        return digest.hexdigest()


def target_digest(project_root: Path, key: str) -> str | None:
    return _anchored_target_digest(project_root, key)


def _read_anchored_regular(parent_fd: int, name: str, metadata: os.stat_result) -> bytes:
    descriptor = _open_regular_at(parent_fd, name, metadata)
    chunks: list[bytes] = []
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                data = b"".join(chunks)
                if len(data) != metadata.st_size or not _same_read_identity(metadata, os.fstat(descriptor)):
                    raise RuntimeError("Journal target changed during anchored read.")
                return data
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _copy_anchored_tree_to_path(source_fd: int, destination: Path) -> None:
    source_metadata = os.fstat(source_fd)
    destination.mkdir(mode=stat.S_IMODE(source_metadata.st_mode))
    try:
        for name in sorted(os.listdir(source_fd)):
            metadata = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            kind = _node_kind(metadata)
            copied = destination / name
            if kind == "directory":
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=source_fd,
                )
                try:
                    if not _same_node(metadata, os.fstat(child_fd)):
                        raise RuntimeError("Journal directory changed while snapshotting.")
                    _copy_anchored_tree_to_path(child_fd, copied)
                finally:
                    os.close(child_fd)
            elif kind == "symlink":
                os.symlink(os.readlink(name, dir_fd=source_fd), copied)
            elif kind == "file":
                data = _read_anchored_regular(source_fd, name, metadata)
                write_bytes_atomic(copied, data, mode=stat.S_IMODE(metadata.st_mode))
            else:
                raise RuntimeError("Journal refuses special filesystem nodes in anchored snapshot.")
        os.chmod(destination, stat.S_IMODE(source_metadata.st_mode))
        if not _same_read_identity(source_metadata, os.fstat(source_fd)):
            raise RuntimeError("Journal directory changed while snapshotting.")
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination)
        raise


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


def _validate_target_key(key: object) -> str:
    """Validate one canonical, lexical KB-relative journal key."""
    if not isinstance(key, str) or not key or key.startswith("/") or "\\" in key:
        raise SystemExit("Journal target key is not a safe KB-relative path.")
    parts = key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SystemExit("Journal target key is not a canonical KB-relative path.")
    canonical = Path(*parts).as_posix()
    if canonical != key:
        raise SystemExit("Journal target key is not canonical.")
    if key == JOURNAL_DIRNAME or key.startswith(f"{JOURNAL_DIRNAME}/"):
        raise SystemExit("Journal runtime paths cannot be mutation targets.")
    return key


def _canonical_kb_root(project_root: Path) -> Path:
    return kb_root(project_root).resolve()


def _assert_safe_target_ancestors(root: Path, key: str) -> None:
    current = root
    for part in key.split("/")[:-1]:
        current = current / part
        metadata = _lstat(current)
        if metadata is None:
            return
        kind = _node_kind(metadata)
        if kind == "symlink":
            raise SystemExit("Journal target has a symlink ancestor inside kb/.")
        if kind != "directory":
            raise SystemExit("Journal target has a non-directory ancestor inside kb/.")


def _target_key(project_root: Path, path: Path) -> str:
    """Map a declared path to a lexical key without dereferencing its leaf."""
    declared = Path(path)
    if ".." in declared.parts:
        raise SystemExit("Journal target may not contain parent traversal.")
    lexical_root = Path(os.path.abspath(os.fspath(kb_root(project_root))))
    canonical_root = lexical_root.resolve()
    absolute_target = Path(os.path.abspath(os.fspath(declared)))
    relative: Path | None = None
    for candidate_root in (lexical_root, canonical_root):
        try:
            relative = absolute_target.relative_to(candidate_root)
            break
        except ValueError:
            continue
    if relative is None:
        raise SystemExit("Journal target must be lexically inside kb/.")
    key = _validate_target_key(relative.as_posix())
    _assert_safe_target_ancestors(canonical_root, key)
    return key


def _target_path(project_root: Path, key: str) -> Path:
    canonical_key = _validate_target_key(key)
    root = _canonical_kb_root(project_root)
    _assert_safe_target_ancestors(root, canonical_key)
    return root.joinpath(*canonical_key.split("/"))


def target_path(project_root: Path, key: str) -> Path:
    return _target_path(project_root, key)


def _ensure_journal_runtime(project_root: Path) -> None:
    # Workspace initialization owns the canonical .gitignore.  Lock/journal
    # bootstrap may create ignored runtime state only; it must never perform an
    # undeclared write to a caller's versioned path set.
    root = journal_root(project_root)
    metadata = _lstat(root)
    if metadata is not None and _node_kind(metadata) != "directory":
        raise SystemExit("操作日志运行目录类型异常；知识库已进入恢复隔离状态。")
    root.mkdir(parents=True, exist_ok=True)


def _snapshot_payload_path(project_root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or relative_path.startswith("/"):
        raise RuntimeError("Invalid journal snapshot path.")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or Path(*parts).as_posix() != relative_path:
        raise RuntimeError("Invalid journal snapshot path.")
    root = journal_root(project_root).resolve()
    current = root
    for part in parts[:-1]:
        current = current / part
        metadata = _lstat(current)
        if metadata is None or _node_kind(metadata) != "directory":
            raise RuntimeError("Invalid journal snapshot ancestor.")
    return root.joinpath(*parts)


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _preflight_snapshot_material(
    project_root: Path,
    op_id: str,
    key: str,
    snapshot: object,
    before_digest: object,
) -> None:
    if not isinstance(snapshot, dict):
        raise SystemExit("操作日志包含无效的恢复快照；已停止恢复。")
    kind = snapshot.get("kind")
    mode = snapshot.get("mode")
    digest = snapshot.get("digest")
    if digest != before_digest:
        raise SystemExit("操作日志的恢复快照与摘要不一致；已停止恢复。")
    if kind == "absent":
        if mode is not None or digest is not None:
            raise SystemExit("操作日志包含无效的空目标快照；已停止恢复。")
        return
    if kind not in {"file", "directory", "symlink"}:
        raise SystemExit("操作日志包含未知的快照类型；已停止恢复。")
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
        raise SystemExit("操作日志包含无效的快照权限；已停止恢复。")
    if not _valid_digest(digest):
        raise SystemExit("操作日志包含无效的快照摘要；已停止恢复。")
    if kind == "symlink":
        link_target = snapshot.get("link_target")
        if not isinstance(link_target, str) or not link_target:
            raise SystemExit("操作日志包含无效的符号链接快照；已停止恢复。")
        expected = hashlib.sha256(
            f"symlink\0{mode}\0{link_target}".encode("utf-8")
        ).hexdigest()
        if expected != digest:
            raise SystemExit("操作日志的符号链接快照摘要不匹配；已停止恢复。")
        return

    leaf = "data" if kind == "file" else "tree"
    expected_relative = (
        Path(SNAPSHOT_DIRNAME)
        / op_id
        / hashlib.sha256(key.encode("utf-8")).hexdigest()
        / leaf
    ).as_posix()
    if snapshot.get("snapshot_path") != expected_relative:
        raise SystemExit("操作日志的快照材料位置无效；已停止恢复。")
    try:
        payload = _snapshot_payload_path(project_root, expected_relative)
    except RuntimeError as exc:
        raise SystemExit("操作日志的快照材料路径无效；已停止恢复。") from exc
    payload_metadata = _lstat(payload)
    if payload_metadata is None or _node_kind(payload_metadata) != kind:
        raise SystemExit("操作日志缺少完整的快照材料；已停止恢复。")
    if _special_nodes(payload):
        raise SystemExit("操作日志快照包含不支持的特殊节点；已停止恢复。")
    try:
        payload_digest = file_digest(payload)
    except (OSError, RuntimeError) as exc:
        raise SystemExit("操作日志快照材料读取失败；已停止恢复。") from exc
    if payload_digest != digest:
        raise SystemExit("操作日志快照材料摘要不匹配；已停止恢复。")


def _snapshot_target(project_root: Path, op_id: str, key: str) -> dict:
    with _anchored_target_parent(project_root, key) as (parent_fd, leaf):
        if parent_fd is None:
            return {"kind": "absent", "mode": None, "digest": None}
        target_metadata = _lstat_at(parent_fd, leaf)
        if target_metadata is None:
            return {"kind": "absent", "mode": None, "digest": None}
        kind = _node_kind(target_metadata)
        if kind == "special":
            raise SystemExit(f"Journal snapshot refuses special filesystem node: {key}")
        mode = stat.S_IMODE(target_metadata.st_mode)
        digest = _anchored_target_digest(project_root, key)
        payload_root = (
            journal_root(project_root)
            / SNAPSHOT_DIRNAME
            / op_id
            / hashlib.sha256(key.encode("utf-8")).hexdigest()
        )
        payload_root.mkdir(parents=True, exist_ok=False)
        if kind == "symlink":
            return {
                "kind": "symlink",
                "mode": mode,
                "digest": digest,
                "link_target": os.readlink(leaf, dir_fd=parent_fd),
            }
        if kind == "directory":
            snapshot = payload_root / "tree"
            directory_fd = os.open(
                leaf,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                if not _same_node(target_metadata, os.fstat(directory_fd)):
                    raise RuntimeError(f"Journal target changed while snapshotting: {key}")
                _copy_anchored_tree_to_path(directory_fd, snapshot)
            finally:
                os.close(directory_fd)
            if file_digest(snapshot) != digest:
                raise RuntimeError(f"Journal target changed while snapshotting: {key}")
            return {
                "kind": "directory",
                "mode": mode,
                "digest": digest,
                "snapshot_path": snapshot.relative_to(journal_root(project_root)).as_posix(),
            }

        snapshot = payload_root / "data"
        data = _read_anchored_regular(parent_fd, leaf, target_metadata)
        write_bytes_atomic(snapshot, data, mode=mode)
        if _anchored_target_digest(project_root, key) != digest:
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


def _remove_at(parent_fd: int, name: str) -> None:
    metadata = _lstat_at(parent_fd, name)
    if metadata is None:
        return
    if _node_kind(metadata) != "directory":
        os.unlink(name, dir_fd=parent_fd)
        return
    directory_fd = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        if not _same_node(metadata, os.fstat(directory_fd)):
            raise RuntimeError("Journal target directory changed while removing it.")
        for child in os.listdir(directory_fd):
            _remove_at(directory_fd, child)
    finally:
        os.close(directory_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _copy_snapshot_tree_to_fd(source: Path, parent_fd: int, name: str) -> None:
    source_metadata = source.lstat()
    if _node_kind(source_metadata) != "directory":
        raise RuntimeError("Journal directory snapshot changed type.")
    os.mkdir(name, stat.S_IMODE(source_metadata.st_mode), dir_fd=parent_fd)
    destination_fd = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            metadata = child.lstat()
            kind = _node_kind(metadata)
            if kind == "directory":
                _copy_snapshot_tree_to_fd(child, destination_fd, child.name)
            elif kind == "symlink":
                os.symlink(os.readlink(child), child.name, dir_fd=destination_fd)
            elif kind == "file":
                descriptor = os.open(
                    child.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    stat.S_IMODE(metadata.st_mode),
                    dir_fd=destination_fd,
                )
                try:
                    data = _read_regular_bytes(child, metadata)
                    view = memoryview(data)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
                finally:
                    os.close(descriptor)
            else:
                raise RuntimeError("Journal snapshot contains a special filesystem node.")
        os.fchmod(destination_fd, stat.S_IMODE(source_metadata.st_mode))
    except BaseException:
        os.close(destination_fd)
        _remove_at(parent_fd, name)
        raise
    else:
        os.close(destination_fd)


def _replace_staged_at(parent_fd: int, staged: str, target: str) -> None:
    previous = f".{target}.previous-{uuid.uuid4().hex}"
    moved_previous = False
    try:
        if _lstat_at(parent_fd, target) is not None:
            os.replace(target, previous, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            moved_previous = True
        os.replace(staged, target, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except BaseException:
        if moved_previous and _lstat_at(parent_fd, target) is None:
            os.replace(previous, target, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        raise
    finally:
        if _lstat_at(parent_fd, staged) is not None:
            _remove_at(parent_fd, staged)
        if _lstat_at(parent_fd, previous) is not None:
            _remove_at(parent_fd, previous)


def _restore_target(project_root: Path, key: str, snapshot: dict) -> Path:
    target = _target_path(project_root, key)
    kind = str(snapshot.get("kind") or "")
    mode_value = snapshot.get("mode")
    mode = int(mode_value) if mode_value is not None else 0o644
    with _anchored_target_parent(
        project_root,
        key,
        create_missing=kind != "absent",
    ) as (parent_fd, leaf):
        if parent_fd is None:
            if kind == "absent":
                return target
            raise RuntimeError(f"Missing anchored target parent for {key}")
        if kind == "absent":
            _remove_at(parent_fd, leaf)
        elif kind == "file":
            payload = _snapshot_payload_path(project_root, str(snapshot.get("snapshot_path") or ""))
            payload_metadata = _lstat(payload)
            if payload_metadata is None or _node_kind(payload_metadata) != "file":
                raise RuntimeError(f"Missing journal file snapshot for {key}")
            staged = f".{leaf}.restore-file-{uuid.uuid4().hex}"
            descriptor = os.open(
                staged,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode,
                dir_fd=parent_fd,
            )
            try:
                data = _read_regular_bytes(payload, payload_metadata)
                view = memoryview(data)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fchmod(descriptor, mode)
            finally:
                os.close(descriptor)
            _replace_staged_at(parent_fd, staged, leaf)
        elif kind == "directory":
            payload = _snapshot_payload_path(project_root, str(snapshot.get("snapshot_path") or ""))
            payload_metadata = _lstat(payload)
            if payload_metadata is None or _node_kind(payload_metadata) != "directory":
                raise RuntimeError(f"Missing journal directory snapshot for {key}")
            staged = f".{leaf}.restore-tree-{uuid.uuid4().hex}"
            _copy_snapshot_tree_to_fd(payload, parent_fd, staged)
            _replace_staged_at(parent_fd, staged, leaf)
        elif kind == "symlink":
            staged = f".{leaf}.restore-link-{uuid.uuid4().hex}"
            os.symlink(str(snapshot.get("link_target") or ""), staged, dir_fd=parent_fd)
            _replace_staged_at(parent_fd, staged, leaf)
        else:
            raise RuntimeError(f"Unsupported journal snapshot kind for {key}: {kind or '<empty>'}")

    expected_digest = snapshot.get("digest")
    actual_digest = _anchored_target_digest(project_root, key)
    if actual_digest != expected_digest:
        raise RuntimeError(
            f"Journal restore verification failed for {key}: expected {expected_digest}, found {actual_digest}"
        )
    return target


def load_op(project_root: Path, op_id: str) -> dict:
    return load_op_view(project_root, op_id)[0]


def load_op_view(project_root: Path, op_id: str) -> tuple[dict, str]:
    if _existing_journal_root(project_root) is None:
        raise SystemExit("找不到指定的操作日志。")
    path = journal_entry_path(project_root, op_id)
    if _lstat(path) is None:
        raise SystemExit("找不到指定的操作日志。")
    return _load_journal_entry_view(path)


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
    if not _nested_context_has_live_workspace_lease(project_root, parent_op_id):
        raise SystemExit("Nested journal parent is not backed by a live workspace lease.")
    parent = load_op(project_root, parent_op_id)
    if parent.get("state") != "begin":
        raise SystemExit(f"Parent journal operation is not active: {parent_op_id}")
    root_op_id = str(parent.get("root_op_id") or parent.get("op_id") or "").strip()
    if not root_op_id:
        raise SystemExit(f"Parent journal operation has no root id: {parent_op_id}")
    root_entry = parent if root_op_id == parent_op_id else load_op(project_root, root_op_id)
    if root_entry.get("state") != "begin":
        raise SystemExit(f"Root journal operation is not active: {root_op_id}")
    if root_entry.get("coordination_scope") != "workspace-exclusive":
        raise SystemExit("Nested journal work requires a workspace-coordinated root operation.")
    return parent, root_entry


def _nested_context_has_live_workspace_lease(project_root: Path, parent_op_id: str) -> bool:
    project_key = _project_context_key(project_root)
    if any(
        active_root == project_key and active_op_id == parent_op_id
        for active_root, active_op_id in _ACTIVE_OP_STACK.get()
    ):
        return True
    env_root = str(os.environ.get(JOURNAL_PARENT_ROOT_ENV) or "").strip()
    env_op = str(os.environ.get(JOURNAL_PARENT_OP_ENV) or "").strip()
    if env_op != parent_op_id or not env_root:
        return False
    try:
        if Path(env_root).resolve().as_posix() != project_key:
            return False
    except OSError:
        return False
    lock_path = workspace_transaction_lock_path(project_root)
    metadata = _lstat(lock_path)
    if metadata is None or _node_kind(metadata) != "file":
        return False
    descriptor = os.open(
        lock_path,
        os.O_RDWR | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            return False
    finally:
        os.close(descriptor)


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
    root = _existing_journal_root(project_root)
    if root is None:
        return []
    ordered_entries: list[tuple[int, dict]] = []
    for path in root.glob("*.yaml"):
        entry = _load_journal_entry_file(path)
        if entry.get("state") != "commit":
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
    root = _existing_journal_root(project_root)
    if root is None:
        return []
    ordered_entries: list[tuple[str, dict]] = []
    for path in root.glob("*.yaml"):
        entry = _load_journal_entry_file(path)
        if entry.get("state") != "begin":
            continue
        ordered_entries.append((path.name, entry))
    begin_by_id = {
        str(entry.get("op_id") or ""): entry
        for _, entry in ordered_entries
    }
    begin_ids = set(begin_by_id)
    keys_by_id = {
        op_id: validated_recovery_target_keys(project_root, entry, require_after=False)
        for op_id, entry in begin_by_id.items()
    }
    root_entries: list[tuple[str, dict]] = []
    for journal_name, entry in ordered_entries:
        op_id = str(entry.get("op_id") or "")
        parent_op_id = str(entry.get("parent_op_id") or "")
        root_op_id = str(entry.get("root_op_id") or entry.get("op_id") or "")
        if parent_op_id or root_op_id != op_id:
            if parent_op_id not in begin_ids or root_op_id not in begin_ids:
                raise SystemExit("未完成子操作缺少有效根操作；知识库已进入恢复隔离状态。")
            root_entry = begin_by_id[root_op_id]
            _validate_nested_target_keys(root_entry, keys_by_id[op_id])
            continue
        root_entries.append((journal_name, entry))

    roots_with_keys = [
        (
            journal_name,
            entry,
            validated_recovery_target_keys(project_root, entry, require_after=False),
        )
        for journal_name, entry in root_entries
    ]
    for index, (_, _, keys) in enumerate(roots_with_keys):
        for _, _, other_keys in roots_with_keys[index + 1 :]:
            if any(
                _path_key_is_covered(key, other)
                or _path_key_is_covered(other, key)
                for key in keys
                for other in other_keys
            ):
                raise SystemExit(
                    "检测到多个因果顺序无法证明且目标重叠的未完成操作；已停止自动恢复。"
                )
    # Disjoint roots commute, so filename order is deterministic without
    # pretending wall clock, mtime, or UUID allocation proves causality.
    return [entry for _, entry, _ in sorted(roots_with_keys, key=lambda item: item[0])]


def _assert_no_incomplete_root(project_root: Path) -> None:
    if _RECOVERY_BEGIN_DEPTH.get() > 0:
        return
    if incomplete_ops(project_root):
        raise SystemExit("检测到未完成的知识库操作；请先使用 kb resume 完成恢复。")


def _preflight_journal_envelopes(project_root: Path) -> None:
    """Read-only malformed-entry gate used before creating a lease file.

    A valid live begin root is not an error here: the authoritative check must
    wait for the workspace lease, because the owner may be about to commit or
    abort it.  Malformed entries cannot self-heal and fail immediately.
    """
    root = _existing_journal_root(project_root)
    if root is None:
        return
    for path in root.glob("*.yaml"):
        _load_journal_entry_file(path)


@contextmanager
def _recovery_workspace_scope() -> Iterator[None]:
    """Narrow internal authorization for recovery journal + checkpoint work."""
    depth = _RECOVERY_BEGIN_DEPTH.get()
    token = _RECOVERY_BEGIN_DEPTH.set(depth + 1)
    try:
        yield
    finally:
        _RECOVERY_BEGIN_DEPTH.reset(token)


def validated_recovery_target_keys(
    project_root: Path,
    entry: Mapping[str, object],
    *,
    require_after: bool,
) -> list[str]:
    """Fail closed unless every recovery target collection is identical.

    This check intentionally runs before recovery locks or a recovery journal
    are created.  It also revalidates lexical containment against the current
    filesystem so a newly introduced symlink ancestor cannot redirect restore.
    """
    raw_targets = entry.get("target_paths")
    op_id = str(entry.get("op_id") or "")
    if not op_id or Path(op_id).name != op_id:
        raise SystemExit("操作日志缺少有效的操作标识；已停止恢复。")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise SystemExit("该操作的恢复目标集合不完整；已停止恢复。")
    keys = [_validate_target_key(item) for item in raw_targets]
    if len(keys) != len(set(keys)):
        raise SystemExit("该操作的恢复目标集合包含重复项；已停止恢复。")
    expected = set(keys)

    before_digests = entry.get("before_digests")
    before_snapshots = entry.get("before_snapshots")
    if not isinstance(before_digests, dict) or not isinstance(before_snapshots, dict):
        raise SystemExit("该操作缺少完整的恢复前状态记录；已停止恢复。")
    for mapping in (before_digests, before_snapshots):
        mapping_keys = [_validate_target_key(key) for key in mapping]
        if len(mapping_keys) != len(set(mapping_keys)) or set(mapping_keys) != expected:
            raise SystemExit("该操作的恢复目标集合不一致；已停止恢复。")

    for key in keys:
        _preflight_snapshot_material(
            project_root,
            op_id,
            key,
            before_snapshots.get(key),
            before_digests.get(key),
        )

    if require_after:
        after_digests = entry.get("after_digests")
        if not isinstance(after_digests, dict):
            raise SystemExit("该操作缺少完整的恢复后状态记录；为避免覆盖后续改动，已停止恢复。")
        after_keys = [_validate_target_key(key) for key in after_digests]
        if len(after_keys) != len(set(after_keys)) or set(after_keys) != expected:
            raise SystemExit("该操作缺少完整的恢复后状态记录；为避免覆盖后续改动，已停止恢复。")

    for key in keys:
        _target_path(project_root, key)
    return keys


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
    requested_parent_id = str(parent_op_id or "").strip()
    active_parent_id = current_operation_id(project_root) if attach_to_active else ""
    if requested_parent_id and requested_parent_id != active_parent_id:
        raise SystemExit("Explicit journal parent does not match the active transaction context.")
    resolved_parent_id = requested_parent_id or active_parent_id

    if not resolved_parent_id:
        # Direct begin_op/journaled_op callers do not otherwise own the
        # command-level workspace lease.  Acquire it here so quarantine and the
        # creation of this root journal are one atomic decision.  The common
        # lock is thread-reentrant when mutation_transaction already owns it.
        from .common import exclusive_file_lock

        _preflight_journal_envelopes(project_root)
        with exclusive_file_lock(workspace_transaction_lock_path(project_root)):
            _assert_no_incomplete_root(project_root)
            return _begin_op_with_keys(
                project_root,
                op_type,
                keys,
                undoable=undoable,
                operation_role=operation_role,
                coordination_scope=coordination_scope,
                resolved_parent_id="",
            )
    return _begin_op_with_keys(
        project_root,
        op_type,
        keys,
        undoable=undoable,
        operation_role=operation_role,
        coordination_scope=coordination_scope,
        resolved_parent_id=resolved_parent_id,
    )


def _begin_op_with_keys(
    project_root: Path,
    op_type: str,
    keys: Sequence[str],
    *,
    undoable: bool,
    operation_role: str,
    coordination_scope: str,
    resolved_parent_id: str,
) -> str:
    # Recheck target topology inside the root workspace lease (or inside the
    # inherited parent lease for nested work) before any snapshot/journal write.
    for key in keys:
        target = _target_path(project_root, key)
        _assert_snapshot_target_supported(target, key)
    _ensure_journal_runtime(project_root)
    sequence_ns = time.time_ns()
    op_id = f"{sequence_ns}-{uuid.uuid4().hex[:12]}"
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
    keys = validated_recovery_target_keys(project_root, entry, require_after=False)
    entry["after_digests"] = {key: _anchored_target_digest(project_root, key) for key in keys}
    entry["completed_at"] = utc_now_iso()
    entry["state"] = "commit"
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)


def restore_before_snapshots(
    project_root: Path,
    op_id: str,
    *,
    source_entry: Mapping[str, object] | None = None,
) -> list[Path]:
    entry = dict(source_entry) if source_entry is not None else load_op(project_root, op_id)
    if str(entry.get("op_id") or "") != op_id:
        raise RuntimeError("Recovery source entry identity changed.")
    keys = validated_recovery_target_keys(project_root, entry, require_after=False)
    snapshots = entry.get("before_snapshots", {})
    if not isinstance(snapshots, dict) or not snapshots:
        raise RuntimeError(f"Operation {op_id} has no before snapshots to restore.")
    restored: list[Path] = []
    for key in keys:
        snapshot = snapshots.get(key)
        if not isinstance(snapshot, dict):
            raise RuntimeError(f"Operation {op_id} is missing the before snapshot for {key}.")
        target = _target_path(project_root, key)
        # Restoration is defined by the journal's existing digest contract.  If
        # the target never diverged from its before-state, replacing it would be
        # needless churn and can invalidate consumers that bind regular-file or
        # directory inode identity.  Keep returning every declared target so
        # recovery checkpoint/reporting behavior remains unchanged.
        if "digest" in snapshot and _anchored_target_digest(project_root, key) == snapshot.get("digest"):
            restored.append(target)
            continue
        restored.append(_restore_target(project_root, key, snapshot))
    return restored


def _descendant_entries(project_root: Path, op_id: str) -> list[tuple[Path, dict]]:
    root = _existing_journal_root(project_root)
    if root is None:
        return []
    entries: list[tuple[Path, dict]] = []
    for path in root.glob("*.yaml"):
        entry = _load_journal_entry_file(path)
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


def terminalize_resumed_op(
    project_root: Path,
    op_id: str,
    *,
    source_entry: Mapping[str, object],
    source_digest: str,
    recovery_op_id: str,
) -> None:
    """Consume one resumed root with a source-entry byte CAS.

    Descendants are terminalized first; the root is the final durable marker.
    Therefore an interruption cannot advertise a consumed root while a child is
    still live, and a remaining begin root is safe to resume again.
    """
    current, current_digest = load_op_view(project_root, op_id)
    if current_digest != source_digest or current != dict(source_entry):
        raise SystemExit("恢复来源操作日志已变化；已停止完成本次恢复。")
    descendants = _descendant_entries(project_root, op_id)
    completed_at = utc_now_iso()
    for path, descendant in descendants:
        if descendant.get("state") in {"abort", "abort_failed"}:
            continue
        descendant["completed_at"] = completed_at
        descendant["state"] = "abort"
        descendant["aborted_with_ancestor"] = op_id
        write_yaml_if_changed(path, descendant)
    terminal = dict(source_entry)
    terminal["completed_at"] = completed_at
    terminal["state"] = "abort"
    terminal["resumed_at"] = completed_at
    terminal["resumed_by"] = recovery_op_id
    write_yaml_if_changed(journal_entry_path(project_root, op_id), terminal)


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
    # Root-last terminalization keeps the authoritative root recoverable when a
    # descendant journal write is interrupted.  A retry may safely revisit
    # already-aborted descendants before finally consuming the root.
    _abort_descendants(project_root, op_id, error=error)
    entry["completed_at"] = utc_now_iso()
    entry["state"] = "abort"
    if error:
        entry["operation_error"] = error
    write_yaml_if_changed(journal_entry_path(project_root, op_id), entry)


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
def _recovery_journaled_op(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
) -> Iterator[str]:
    """Create the one non-undoable journal used by explicit recovery.

    The private ContextVar is the sole incomplete-root quarantine exception;
    setting operation_role="recovery" on the public primitive is insufficient.
    Callers must already hold the workspace and exact-target leases.
    """
    with _recovery_workspace_scope():
        with journaled_op(
            project_root,
            op_type,
            target_paths,
            undoable=False,
            operation_role="recovery",
            coordination_scope="workspace-exclusive",
            attach_to_active=False,
        ) as op_id:
            yield op_id


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
    keys = sorted({_target_key(project_root, Path(path)) for path in target_paths})
    if not keys:
        raise SystemExit("Mutation transaction requires at least one explicit target path.")
    targets = [_target_path(project_root, key) for key in keys]
    # Lazy import avoids common -> journal -> common initialization cycles.
    from .common import exclusive_file_lock

    parent_op_id = current_operation_id(project_root)
    if parent_op_id:
        _, root_entry = _nested_root_entry(project_root, parent_op_id)
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
    _preflight_journal_envelopes(project_root)
    with exclusive_file_lock(workspace_transaction_lock_path(project_root)):
        _assert_no_incomplete_root(project_root)
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

"""Trusted activation and revalidation for the workspace-root data layout.

The marker is an authority boundary, not a discovery hint.  Ordinary runtime
code may resolve only a byte-canonical marker.  The one creation primitive is
called by the explicit ``kb init`` owner after a zero-write collision preflight.
"""
from __future__ import annotations

import hashlib
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path

from .path_contract import (
    CANONICAL_ARTIFACT_TOP_LEVEL,
    OPERATIONAL_STATE_TOP_LEVEL,
    RESERVED_WORKSPACE_TOP_LEVEL,
    DataLayout,
    PathContractError,
    RootRoles,
)


WORKSPACE_LAYOUT_SCHEMA = "research-workspace-layout/v1"
WORKSPACE_LAYOUT_MARKER_RELATIVE = Path("config/workspace-layout.yaml")
WORKSPACE_RULES_RELATIVE = Path(".agents/WORKSPACE_RULES.md")
WORKSPACE_LAYOUT_MARKER_BYTES = (
    b"schema: research-workspace-layout/v1\n"
    b"layout: workspace-root\n"
)
_MAX_MARKER_BYTES = 4096
_MAX_WORKSPACE_RULES_BYTES = 64 * 1024


class WorkspaceLayoutError(PathContractError):
    """The workspace layout is missing, ambiguous, stale, or unsafe."""


def _node_kind(metadata: os.stat_result) -> str:
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    return "special"


def _node_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _read_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        *_node_identity(metadata),
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _lexical_absolute(value: str | Path) -> Path:
    text = os.fspath(value)
    path = Path(text)
    if (
        not text
        or "\x00" in text
        or "\\" in text
        or not path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise WorkspaceLayoutError("workspace root must be an unambiguous absolute path")
    return Path(os.path.normpath(text))


def layout_marker_path(workspace_root: str | Path) -> Path:
    return _lexical_absolute(workspace_root) / WORKSPACE_LAYOUT_MARKER_RELATIVE


@dataclass(frozen=True)
class WorkspaceLayoutSnapshot:
    """Exact root and marker identity consumed by one operation boundary."""

    roots: RootRoles
    workspace_identity: tuple[int, int, int]
    marker_identity: tuple[int, int, int, int, int, int]
    marker_digest: str


def _workspace_metadata(workspace: Path) -> os.stat_result:
    try:
        metadata = workspace.lstat()
    except FileNotFoundError as exc:
        raise WorkspaceLayoutError("workspace root does not exist") from exc
    kind = _node_kind(metadata)
    if kind == "symlink":
        raise WorkspaceLayoutError("workspace root must not be a symlink")
    if kind != "directory":
        raise WorkspaceLayoutError("workspace root must be a regular directory")
    return metadata


def _read_marker(workspace: Path) -> tuple[bytes, os.stat_result]:
    config = workspace / "config"
    marker = config / "workspace-layout.yaml"
    try:
        config_metadata = config.lstat()
    except FileNotFoundError as exc:
        raise WorkspaceLayoutError(
            "工作区尚未通过 kb init 激活 workspace-root layout。"
        ) from exc
    config_kind = _node_kind(config_metadata)
    if config_kind == "symlink":
        raise WorkspaceLayoutError("workspace layout marker has a symlink ancestor")
    if config_kind != "directory":
        raise WorkspaceLayoutError("workspace layout marker parent is a special node")
    try:
        marker_metadata = marker.lstat()
    except FileNotFoundError as exc:
        raise WorkspaceLayoutError(
            "工作区尚未通过 kb init 激活 workspace-root layout。"
        ) from exc
    marker_kind = _node_kind(marker_metadata)
    if marker_kind == "symlink":
        raise WorkspaceLayoutError("workspace layout marker must not be a symlink")
    if marker_kind != "file":
        raise WorkspaceLayoutError("workspace layout marker must be a regular file")
    if marker_metadata.st_size > _MAX_MARKER_BYTES:
        raise WorkspaceLayoutError("workspace layout marker is oversized")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(marker, flags)
    except OSError as exc:
        raise WorkspaceLayoutError("workspace layout marker changed while opening") from exc
    try:
        opened = os.fstat(descriptor)
        if _node_kind(opened) != "file" or _node_identity(opened) != _node_identity(
            marker_metadata
        ):
            raise WorkspaceLayoutError("workspace layout marker identity changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024, _MAX_MARKER_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_MARKER_BYTES:
                raise WorkspaceLayoutError("workspace layout marker is oversized")
        data = b"".join(chunks)
        closed_identity = os.fstat(descriptor)
        if _read_identity(opened) != _read_identity(closed_identity):
            raise WorkspaceLayoutError("workspace layout marker changed while reading")
    finally:
        os.close(descriptor)
    if data != WORKSPACE_LAYOUT_MARKER_BYTES:
        raise WorkspaceLayoutError("workspace layout marker is unknown or non-canonical")
    return data, marker_metadata


def resolve_workspace_roots(
    workspace_root: str | Path,
    product_bundle_root: str | Path,
) -> WorkspaceLayoutSnapshot:
    """Resolve a byte-canonical active workspace without following marker links."""

    workspace = _lexical_absolute(workspace_root)
    workspace_metadata = _workspace_metadata(workspace)
    data, marker_metadata = _read_marker(workspace)
    roots = RootRoles.for_layout(
        workspace,
        _lexical_absolute(product_bundle_root),
        DataLayout.WORKSPACE_ROOT,
    )
    return WorkspaceLayoutSnapshot(
        roots=roots,
        workspace_identity=_node_identity(workspace_metadata),
        marker_identity=_read_identity(marker_metadata),
        marker_digest=hashlib.sha256(data).hexdigest(),
    )


def require_current_workspace_layout(snapshot: WorkspaceLayoutSnapshot) -> None:
    """Reject reuse of a root/marker capability after identity or byte drift."""

    current = resolve_workspace_roots(
        snapshot.roots.workspace_root,
        snapshot.roots.product_bundle_root,
    )
    if current != snapshot:
        raise WorkspaceLayoutError("workspace layout identity changed during the operation")


def require_workspace_rules(workspace_root: str | Path) -> None:
    """Require the installed minimal rule layer before any workspace write."""

    workspace = _lexical_absolute(workspace_root)
    _workspace_metadata(workspace)
    agents = workspace / ".agents"
    rules = workspace / WORKSPACE_RULES_RELATIVE
    message = (
        "Workspace rules are missing or unsafe; only read-only kb help or "
        "kb doctor rescue is allowed until the installation is repaired."
    )
    try:
        agents_metadata = agents.lstat()
        rules_metadata = rules.lstat()
    except FileNotFoundError as exc:
        raise WorkspaceLayoutError(message) from exc
    if _node_kind(agents_metadata) != "directory" or _node_kind(rules_metadata) != "file":
        raise WorkspaceLayoutError(message)
    if not 0 < rules_metadata.st_size <= _MAX_WORKSPACE_RULES_BYTES:
        raise WorkspaceLayoutError(message)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        agents_descriptor = os.open(agents, directory_flags)
    except OSError as exc:
        raise WorkspaceLayoutError(message) from exc
    try:
        if _node_identity(os.fstat(agents_descriptor)) != _node_identity(agents_metadata):
            raise WorkspaceLayoutError(message)
        try:
            anchored_metadata = os.stat(
                "WORKSPACE_RULES.md",
                dir_fd=agents_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise WorkspaceLayoutError(message) from exc
        if _read_identity(anchored_metadata) != _read_identity(rules_metadata):
            raise WorkspaceLayoutError(message)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open("WORKSPACE_RULES.md", flags, dir_fd=agents_descriptor)
        except OSError as exc:
            raise WorkspaceLayoutError(message) from exc
        try:
            opened = os.fstat(descriptor)
            if _read_identity(opened) != _read_identity(anchored_metadata):
                raise WorkspaceLayoutError(message)
            chunks: list[bytes] = []
            remaining = opened.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    raise WorkspaceLayoutError(message)
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise WorkspaceLayoutError(message)
            if _read_identity(opened) != _read_identity(os.fstat(descriptor)):
                raise WorkspaceLayoutError(message)
            content = b"".join(chunks)
        finally:
            os.close(descriptor)
        try:
            current_agents_metadata = agents.lstat()
        except OSError as exc:
            raise WorkspaceLayoutError(message) from exc
        if _node_identity(current_agents_metadata) != _node_identity(agents_metadata):
            raise WorkspaceLayoutError(message)
    finally:
        os.close(agents_descriptor)
    if not content.startswith(b"# WORKSPACE_RULES "):
        raise WorkspaceLayoutError(message)


def _preflight_initialization(workspace: Path) -> os.stat_result:
    root_metadata = _workspace_metadata(workspace)
    allowed_integration = set(RESERVED_WORKSPACE_TOP_LEVEL) - {".git"}
    for entry in os.scandir(workspace):
        name = entry.name
        if name in allowed_integration:
            # Integration targets are outside canonical ownership and are never
            # traversed, journaled, or staged by this initializer.
            continue
        path = workspace / name
        metadata = path.lstat()
        kind = _node_kind(metadata)
        if name == ".git":
            raise WorkspaceLayoutError("an existing Git repository has no layout marker")
        if name == "kb":
            raise WorkspaceLayoutError("a legacy kb directory requires explicit migration")
        if name == ".gitignore" and kind == "file":
            continue
        if kind == "symlink":
            raise WorkspaceLayoutError("workspace initialization collision is a symlink")
        if kind == "special":
            raise WorkspaceLayoutError("workspace initialization collision is a special node")
        if name in CANONICAL_ARTIFACT_TOP_LEVEL or name in OPERATIONAL_STATE_TOP_LEVEL:
            raise WorkspaceLayoutError("workspace contains a partial canonical layout")
        raise WorkspaceLayoutError("workspace contains an unknown top-level collision")
    return root_metadata


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("workspace layout marker write made no progress")
        view = view[written:]


def _create_marker(workspace: Path, expected_root: os.stat_result) -> None:
    root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(workspace, root_flags)
    config_fd = -1
    temporary = (
        f".workspace-layout.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    created_config = False
    try:
        if _node_identity(os.fstat(root_fd)) != _node_identity(expected_root):
            raise WorkspaceLayoutError("workspace root identity changed before activation")
        try:
            os.mkdir("config", 0o755, dir_fd=root_fd)
            created_config = True
        except FileExistsError as exc:
            raise WorkspaceLayoutError("workspace config collision appeared during activation") from exc
        config_fd = os.open("config", root_flags, dir_fd=root_fd)
        marker_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o644,
            dir_fd=config_fd,
        )
        try:
            _write_all(marker_fd, WORKSPACE_LAYOUT_MARKER_BYTES)
            os.fsync(marker_fd)
        finally:
            os.close(marker_fd)
        os.replace(
            temporary,
            "workspace-layout.yaml",
            src_dir_fd=config_fd,
            dst_dir_fd=config_fd,
        )
        os.fsync(config_fd)
        if _node_identity(os.fstat(root_fd)) != _node_identity(expected_root):
            raise WorkspaceLayoutError("workspace root identity changed during activation")
    except BaseException:
        if config_fd >= 0:
            try:
                os.unlink(temporary, dir_fd=config_fd)
            except FileNotFoundError:
                pass
            try:
                os.unlink("workspace-layout.yaml", dir_fd=config_fd)
            except FileNotFoundError:
                pass
        if created_config:
            try:
                os.rmdir("config", dir_fd=root_fd)
            except OSError:
                pass
        raise
    finally:
        if config_fd >= 0:
            os.close(config_fd)
        os.close(root_fd)


def initialize_workspace_layout(
    workspace_root: str | Path,
    product_bundle_root: str | Path,
) -> WorkspaceLayoutSnapshot:
    """Activate one safe, new dedicated workspace; never migrate or guess."""

    workspace = _lexical_absolute(workspace_root)
    try:
        return resolve_workspace_roots(workspace, product_bundle_root)
    except WorkspaceLayoutError:
        if layout_marker_path(workspace).exists() or layout_marker_path(workspace).is_symlink():
            raise
    root_metadata = _preflight_initialization(workspace)
    _create_marker(workspace, root_metadata)
    return resolve_workspace_roots(workspace, product_bundle_root)


__all__ = [
    "WORKSPACE_LAYOUT_MARKER_BYTES",
    "WORKSPACE_LAYOUT_MARKER_RELATIVE",
    "WORKSPACE_LAYOUT_SCHEMA",
    "WORKSPACE_RULES_RELATIVE",
    "WorkspaceLayoutError",
    "WorkspaceLayoutSnapshot",
    "initialize_workspace_layout",
    "layout_marker_path",
    "require_current_workspace_layout",
    "require_workspace_rules",
    "resolve_workspace_roots",
]

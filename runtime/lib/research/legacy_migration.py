"""Explicit, receipt-bound migration from the retired ``workspace/kb`` layout.

The detector is read-only and deliberately does not activate either layout.
Mutation is private to the routed maintenance workflow: a caller must first
freeze a plan, then supply current-user-message authorization to apply or
rollback it.  Ordinary runtime and installer paths consume only the detector
and never call the mutation functions.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

from .path_contract import (
    CANONICAL_ARTIFACT_TOP_LEVEL,
    OPERATIONAL_STATE_TOP_LEVEL,
    RESERVED_WORKSPACE_TOP_LEVEL,
    WORKSPACE_GITIGNORE_LINES,
)
from .workspace_layout import (
    WORKSPACE_LAYOUT_MARKER_BYTES,
    WORKSPACE_LAYOUT_MARKER_RELATIVE,
)


PLAN_SCHEMA = "research-legacy-layout-migration-plan/v1"
RECOVERY_SCHEMA = "research-legacy-layout-migration-recovery/v1"
MIGRATION_COMMIT_MESSAGE = "chore: migrate knowledge workspace to root layout"
ROLLBACK_COMMIT_MESSAGE = "chore: rollback knowledge workspace root migration"
LEGACY_MIGRATION_GUIDANCE = (
    "检测到旧版知识库布局；已停止写入。请先阅读“迁移旧知识库到工作区根目录”指南，"
    "完成显式检查、授权与迁移后再继续。"
)
_MAX_CONTROL_FILE_BYTES = 4 * 1024 * 1024
_MAX_RECOVERY_RECEIPT_BYTES = 32 * 1024 * 1024
_MIGRATABLE_TOP_LEVEL = frozenset(
    {*CANONICAL_ARTIFACT_TOP_LEVEL, *OPERATIONAL_STATE_TOP_LEVEL}
)
_ROOT_INTEGRATION_TOP_LEVEL = frozenset(RESERVED_WORKSPACE_TOP_LEVEL)
_STABLE_TREE_EXCLUDES = frozenset(
    {".git", ".gitignore", WORKSPACE_LAYOUT_MARKER_RELATIVE.as_posix()}
)
_JOURNAL_BEGIN_RE = re.compile(r"(?m)^state:\s*begin\s*(?:#.*)?$")


class LegacyMigrationError(RuntimeError):
    """The detector, preflight, migration, or rollback failed closed."""


class LegacyLayoutState(str, Enum):
    ACTIVE_ROOT = "root"
    NO_LAYOUT = "no-layout"
    ELIGIBLE_LEGACY = "eligible-legacy"
    PARTIAL_AMBIGUOUS = "partial-ambiguous"
    OUTER_GIT = "outer-git"
    COLLISION = "collision"
    DIRTY = "dirty"
    INCOMPLETE_JOURNAL = "incomplete-journal"
    SYMLINK = "symlink"
    SPECIAL_NODE = "special-node"


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


def _identity_payload(metadata: os.stat_result) -> list[int]:
    return list(_read_identity(metadata))


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _bytes_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _lexical_absolute(value: str | Path) -> Path:
    text = os.fspath(value)
    candidate = Path(text)
    if (
        not text
        or "\x00" in text
        or "\\" in text
        or not candidate.is_absolute()
        or any(part in {".", ".."} for part in candidate.parts)
    ):
        raise LegacyMigrationError("workspace root must be an unambiguous absolute path")
    return Path(os.path.normpath(text))


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LegacyMigrationError("filesystem identity could not be inspected") from exc


def _unsafe_absolute_ancestor(path: Path) -> str | None:
    """Return the first unsafe ancestor kind without following it deliberately."""

    current = Path(path.anchor)
    for component in path.parts[1:-1]:
        current = current / component
        metadata = _lstat(current)
        if metadata is None:
            return None
        kind = _node_kind(metadata)
        if kind == "symlink":
            return "symlink"
        if kind != "directory":
            return "special"
    return None


def _safe_read(path: Path, *, limit: int = _MAX_CONTROL_FILE_BYTES) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    if _node_kind(before) != "file":
        raise LegacyMigrationError("expected a stable regular file")
    if before.st_size < 0 or before.st_size > limit:
        raise LegacyMigrationError("control file is oversized")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if _read_identity(opened) != _read_identity(before):
            raise LegacyMigrationError("file identity changed while opening")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise LegacyMigrationError("file changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise LegacyMigrationError("file grew while reading")
        if _read_identity(opened) != _read_identity(os.fstat(descriptor)):
            raise LegacyMigrationError("file identity changed while reading")
        return b"".join(chunks), opened
    finally:
        os.close(descriptor)


def _stable_file_digest(path: Path, expected: os.stat_result) -> str:
    """Digest an arbitrary artifact without buffering it or following links."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if _read_identity(opened) != _read_identity(expected) or _node_kind(opened) != "file":
            raise LegacyMigrationError("legacy file identity changed while opening")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if _read_identity(opened) != _read_identity(os.fstat(descriptor)):
            raise LegacyMigrationError("legacy file identity changed while hashing")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _file_receipt(path: Path) -> dict[str, Any]:
    metadata = _lstat(path)
    if metadata is None:
        return {"state": "absent"}
    kind = _node_kind(metadata)
    if kind != "file":
        return {"state": kind, "identity": _identity_payload(metadata)}
    content, stable = _safe_read(path)
    return {
        "state": "file",
        "identity": _identity_payload(stable),
        "mode": stat.S_IMODE(stable.st_mode),
        "size": len(content),
        "sha256": _bytes_digest(content),
    }


class _UnsafeTree(LegacyMigrationError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _walk_tree(
    root: Path,
    *,
    exclude: frozenset[str] = frozenset(),
    digest_content: bool,
) -> str:
    """Walk without following links; optionally digest exact file bytes."""

    root_metadata = root.lstat()
    if _node_kind(root_metadata) != "directory":
        raise _UnsafeTree(_node_kind(root_metadata))
    rows: list[bytes] = []
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath("."))]
    while stack:
        directory, relative = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise LegacyMigrationError("legacy tree could not be scanned") from exc
        for entry in entries:
            child_relative = (
                PurePosixPath(entry.name)
                if relative == PurePosixPath(".")
                else relative / entry.name
            )
            rel_text = child_relative.as_posix()
            if rel_text in exclude or any(
                rel_text.startswith(f"{prefix}/") for prefix in exclude
            ):
                continue
            metadata = entry.stat(follow_symlinks=False)
            kind = _node_kind(metadata)
            if kind == "symlink":
                raise _UnsafeTree("symlink")
            if kind == "special":
                raise _UnsafeTree("special")
            header = f"{rel_text}\0{kind}\0{stat.S_IMODE(metadata.st_mode):04o}\0"
            if kind == "directory":
                rows.append(header.encode("utf-8"))
                stack.append((Path(entry.path), child_relative))
            elif digest_content:
                # Keep path, type, mode, and bytes in one row.  Sorting separate
                # path/content rows would permit two files to swap bytes without
                # changing the multiset digest.
                rows.append(
                    f"{header}{_stable_file_digest(Path(entry.path), metadata)}".encode(
                        "utf-8"
                    )
                )
            else:
                rows.append(header.encode("utf-8"))
    if _node_identity(root_metadata) != _node_identity(root.lstat()):
        raise LegacyMigrationError("legacy tree root changed while scanning")
    digest = hashlib.sha256()
    for row in sorted(rows):
        digest.update(len(row).to_bytes(8, "big"))
        digest.update(row)
    return digest.hexdigest()


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    # Porcelain reads such as status are allowed to refresh the index unless
    # optional locks are disabled.  A detector must be byte-for-byte read-only.
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            os.fspath(repo),
            *args,
        ],
        check=False,
        capture_output=True,
        env=environment,
    )
    if check and result.returncode != 0:
        raise LegacyMigrationError("legacy Git repository failed a read-only integrity check")
    return result


@dataclass(frozen=True)
class GitReceipt:
    head: str
    head_ref: str
    tree: str
    refs_sha256: str
    refs: tuple[str, ...]
    index_sha256: str
    tracked_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "head_ref": self.head_ref,
            "tree": self.tree,
            "refs_sha256": self.refs_sha256,
            "refs": list(self.refs),
            "index_sha256": self.index_sha256,
            "tracked_paths": list(self.tracked_paths),
        }


def _git_receipt(repo: Path) -> tuple[GitReceipt, bool]:
    expected_git = repo / ".git"
    git_dir = _run_git(repo, "rev-parse", "--absolute-git-dir").stdout.decode("utf-8").strip()
    try:
        same_git_dir = Path(git_dir).resolve(strict=True) == expected_git.resolve(strict=True)
    except OSError as exc:
        raise LegacyMigrationError("legacy Git directory could not be verified") from exc
    if not same_git_dir:
        raise LegacyMigrationError("legacy Git ownership is indirect or ambiguous")
    worktrees = _run_git(repo, "worktree", "list", "--porcelain").stdout
    worktree_rows = [line for line in worktrees.splitlines() if line.startswith(b"worktree ")]
    if len(worktree_rows) != 1:
        raise LegacyMigrationError("legacy Git repository has linked worktrees")
    try:
        worktree_path = Path(worktree_rows[0][len(b"worktree ") :].decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise LegacyMigrationError("legacy Git worktree path is not UTF-8") from exc
    try:
        if worktree_path.resolve(strict=True) != repo.resolve(strict=True):
            raise LegacyMigrationError("legacy Git worktree ownership is ambiguous")
    except OSError as exc:
        raise LegacyMigrationError("legacy Git worktree could not be verified") from exc
    if _run_git(repo, "fsck", "--no-dangling").returncode != 0:
        raise LegacyMigrationError("legacy Git object database is not healthy")
    head = _run_git(repo, "rev-parse", "--verify", "HEAD").stdout.decode("ascii").strip()
    head_ref_result = _run_git(repo, "symbolic-ref", "-q", "HEAD", check=False)
    if head_ref_result.returncode != 0:
        raise LegacyMigrationError("legacy Git HEAD must name a local branch")
    head_ref = head_ref_result.stdout.decode("utf-8").strip()
    if not head_ref.startswith("refs/heads/"):
        raise LegacyMigrationError("legacy Git HEAD does not name a local branch")
    tree = _run_git(repo, "rev-parse", "HEAD^{tree}").stdout.decode("ascii").strip()
    refs = _run_git(repo, "show-ref", "--head").stdout
    try:
        refs_rows = tuple(sorted(line for line in refs.decode("utf-8").splitlines() if line))
    except UnicodeDecodeError as exc:
        raise LegacyMigrationError("legacy Git refs are not UTF-8") from exc
    tracked_raw = _run_git(repo, "ls-files", "-z").stdout
    try:
        tracked_paths = tuple(
            sorted(item.decode("utf-8") for item in tracked_raw.split(b"\0") if item)
        )
    except UnicodeDecodeError as exc:
        raise LegacyMigrationError("legacy Git index paths are not UTF-8") from exc
    if not tracked_paths:
        raise LegacyMigrationError("legacy Git repository has no tracked canonical files")
    for relative in tracked_paths:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise LegacyMigrationError("legacy Git index contains an unsafe path")
        top = path.parts[0]
        if top not in CANONICAL_ARTIFACT_TOP_LEVEL:
            raise LegacyMigrationError("legacy Git index contains a non-canonical top-level path")
    staged = _run_git(repo, "ls-files", "-s", "-z").stdout
    for row in (item for item in staged.split(b"\0") if item):
        mode = row.split(b" ", 1)[0]
        if mode not in {b"100644", b"100755"}:
            raise LegacyMigrationError("legacy Git index contains a symlink or special entry")
    status = _run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    index_path = expected_git / "index"
    index_metadata = _lstat(index_path)
    if index_metadata is None:
        index_sha256 = _bytes_digest(b"")
    elif _node_kind(index_metadata) != "file":
        raise LegacyMigrationError("legacy Git index is not a regular file")
    else:
        index_sha256 = _stable_file_digest(index_path, index_metadata)
    return (
        GitReceipt(
            head=head,
            head_ref=head_ref,
            tree=tree,
            refs_sha256=_bytes_digest(refs),
            refs=refs_rows,
            index_sha256=index_sha256,
            tracked_paths=tracked_paths,
        ),
        bool(status.stdout),
    )


def _marker_probe(workspace: Path) -> tuple[str, str]:
    config = workspace / "config"
    marker = workspace / WORKSPACE_LAYOUT_MARKER_RELATIVE
    config_metadata = _lstat(config)
    if config_metadata is None:
        return "missing", ""
    config_kind = _node_kind(config_metadata)
    if config_kind in {"symlink", "special"}:
        return config_kind, ""
    if config_kind != "directory":
        return "special", ""
    marker_metadata = _lstat(marker)
    if marker_metadata is None:
        return "missing", ""
    marker_kind = _node_kind(marker_metadata)
    if marker_kind in {"symlink", "special"}:
        return marker_kind, ""
    if marker_kind != "file":
        return "special", ""
    try:
        content, _ = _safe_read(marker, limit=4096)
    except LegacyMigrationError:
        return "unknown", ""
    return (
        ("canonical", _bytes_digest(content))
        if content == WORKSPACE_LAYOUT_MARKER_BYTES
        else ("unknown", _bytes_digest(content))
    )


def _journal_is_incomplete(legacy: Path) -> bool:
    journal = legacy / ".journal"
    metadata = _lstat(journal)
    if metadata is None:
        return False
    if _node_kind(metadata) != "directory":
        return True
    for entry in sorted(os.scandir(journal), key=lambda item: item.name):
        if not entry.name.endswith(".yaml"):
            continue
        item_metadata = entry.stat(follow_symlinks=False)
        if _node_kind(item_metadata) != "file":
            return True
        try:
            content, _ = _safe_read(Path(entry.path), limit=_MAX_CONTROL_FILE_BYTES)
            text = content.decode("utf-8")
        except (LegacyMigrationError, UnicodeDecodeError):
            return True
        if _JOURNAL_BEGIN_RE.search(text):
            return True
    return False


@dataclass(frozen=True)
class LegacyDetection:
    state: LegacyLayoutState
    reason: str
    workspace_identity: tuple[int, ...] = ()
    legacy_identity: tuple[int, ...] = ()
    movable_entries: tuple[str, ...] = ()
    entry_identities: tuple[tuple[str, tuple[int, ...]], ...] = ()
    stable_tree_sha256: str = ""
    root_receipts: tuple[tuple[str, str], ...] = ()
    git: GitReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": self.state.value,
            "reason": self.reason,
            "workspace_identity": list(self.workspace_identity),
            "legacy_identity": list(self.legacy_identity),
            "movable_entries": list(self.movable_entries),
            "entry_identities": [
                [name, list(identity)] for name, identity in self.entry_identities
            ],
            "stable_tree_sha256": self.stable_tree_sha256,
            "root_receipts": [[name, digest] for name, digest in self.root_receipts],
            "git": self.git.to_dict() if self.git is not None else None,
        }
        payload["fingerprint"] = _json_digest(payload)
        return payload

    @property
    def fingerprint(self) -> str:
        return str(self.to_dict()["fingerprint"])


def _detection(
    state: LegacyLayoutState,
    reason: str,
    **kwargs: Any,
) -> LegacyDetection:
    return LegacyDetection(state=state, reason=reason, **kwargs)


def detect_legacy_layout(workspace_root: str | Path) -> LegacyDetection:
    """Classify one workspace without creating, repairing, locking, or writing."""

    workspace = _lexical_absolute(workspace_root)
    ancestor_kind = _unsafe_absolute_ancestor(workspace)
    if ancestor_kind == "symlink":
        return _detection(LegacyLayoutState.SYMLINK, "workspace-ancestor-symlink")
    if ancestor_kind == "special":
        return _detection(LegacyLayoutState.SPECIAL_NODE, "workspace-ancestor-special")
    workspace_metadata = _lstat(workspace)
    if workspace_metadata is None:
        return _detection(LegacyLayoutState.NO_LAYOUT, "workspace-missing")
    workspace_kind = _node_kind(workspace_metadata)
    if workspace_kind == "symlink":
        return _detection(LegacyLayoutState.SYMLINK, "workspace-root-symlink")
    if workspace_kind != "directory":
        return _detection(LegacyLayoutState.SPECIAL_NODE, "workspace-root-special")

    marker_state, _marker_digest = _marker_probe(workspace)
    legacy = workspace / "kb"
    legacy_metadata = _lstat(legacy)
    if marker_state == "canonical":
        if legacy_metadata is not None:
            legacy_kind = _node_kind(legacy_metadata)
            if legacy_kind == "symlink":
                return _detection(
                    LegacyLayoutState.SYMLINK,
                    "root-marker-and-legacy-symlink-coexist",
                )
            if legacy_kind != "directory":
                return _detection(
                    LegacyLayoutState.SPECIAL_NODE,
                    "root-marker-and-legacy-special-coexist",
                )
            return _detection(
                LegacyLayoutState.PARTIAL_AMBIGUOUS,
                "root-marker-and-legacy-directory-coexist",
                workspace_identity=tuple(_identity_payload(workspace_metadata)),
            )
        return _detection(
            LegacyLayoutState.ACTIVE_ROOT,
            "canonical-root-marker",
            workspace_identity=tuple(_identity_payload(workspace_metadata)),
        )
    if marker_state == "symlink":
        return _detection(LegacyLayoutState.SYMLINK, "layout-marker-symlink")
    if marker_state in {"special", "unknown"}:
        return _detection(
            LegacyLayoutState.SPECIAL_NODE
            if marker_state == "special"
            else LegacyLayoutState.PARTIAL_AMBIGUOUS,
            "unsafe-or-unknown-root-marker",
        )

    root_git = _lstat(workspace / ".git")
    if root_git is not None:
        if _node_kind(root_git) == "symlink":
            return _detection(LegacyLayoutState.SYMLINK, "outer-git-symlink")
        return _detection(LegacyLayoutState.OUTER_GIT, "workspace-already-has-git")
    if legacy_metadata is None:
        root_names = {entry.name for entry in os.scandir(workspace)}
        partial_root_names = {
            *(CANONICAL_ARTIFACT_TOP_LEVEL - {".gitignore"}),
            *OPERATIONAL_STATE_TOP_LEVEL,
        }
        if root_names & partial_root_names:
            return _detection(
                LegacyLayoutState.PARTIAL_AMBIGUOUS,
                "partial-root-layout-without-marker",
            )
        return _detection(
            LegacyLayoutState.NO_LAYOUT,
            "no-root-marker-or-legacy-directory",
            workspace_identity=tuple(_identity_payload(workspace_metadata)),
        )
    legacy_kind = _node_kind(legacy_metadata)
    if legacy_kind == "symlink":
        return _detection(LegacyLayoutState.SYMLINK, "legacy-root-symlink")
    if legacy_kind != "directory":
        return _detection(LegacyLayoutState.SPECIAL_NODE, "legacy-root-special")
    if workspace_metadata.st_dev != legacy_metadata.st_dev:
        return _detection(LegacyLayoutState.PARTIAL_AMBIGUOUS, "cross-filesystem-legacy-root")

    allowed_root = {*_ROOT_INTEGRATION_TOP_LEVEL, ".gitignore", "kb"}
    for entry in sorted(os.scandir(workspace), key=lambda item: item.name):
        metadata = entry.stat(follow_symlinks=False)
        kind = _node_kind(metadata)
        if kind == "symlink":
            return _detection(LegacyLayoutState.SYMLINK, "workspace-integration-symlink")
        if kind == "special":
            return _detection(LegacyLayoutState.SPECIAL_NODE, "workspace-integration-special")
        if entry.name not in allowed_root:
            return _detection(LegacyLayoutState.COLLISION, "unknown-workspace-root-entry")

    legacy_entries = {
        entry.name: entry.stat(follow_symlinks=False)
        for entry in sorted(os.scandir(legacy), key=lambda item: item.name)
    }
    if ".git" not in legacy_entries:
        return _detection(LegacyLayoutState.PARTIAL_AMBIGUOUS, "legacy-git-missing")
    allowed_legacy = {*_MIGRATABLE_TOP_LEVEL, ".git"}
    for name, metadata in legacy_entries.items():
        kind = _node_kind(metadata)
        if kind == "symlink":
            return _detection(LegacyLayoutState.SYMLINK, "legacy-top-level-symlink")
        if kind == "special":
            return _detection(LegacyLayoutState.SPECIAL_NODE, "legacy-top-level-special")
        if name not in allowed_legacy:
            return _detection(LegacyLayoutState.PARTIAL_AMBIGUOUS, "unknown-legacy-entry")
        if name == ".git" and kind != "directory":
            return _detection(LegacyLayoutState.PARTIAL_AMBIGUOUS, "legacy-git-is-indirect")
        if name in CANONICAL_ARTIFACT_TOP_LEVEL and name != ".gitignore":
            collision = _lstat(workspace / name)
            if collision is not None:
                return _detection(LegacyLayoutState.COLLISION, "canonical-root-collision")
        if name in OPERATIONAL_STATE_TOP_LEVEL and _lstat(workspace / name) is not None:
            return _detection(LegacyLayoutState.COLLISION, "operational-root-collision")
    root_ignore = _lstat(workspace / ".gitignore")
    if root_ignore is not None and _node_kind(root_ignore) != "file":
        return _detection(
            LegacyLayoutState.SYMLINK
            if _node_kind(root_ignore) == "symlink"
            else LegacyLayoutState.SPECIAL_NODE,
            "root-gitignore-unsafe",
        )

    try:
        _walk_tree(legacy, exclude=frozenset({".git"}), digest_content=False)
        _walk_tree(legacy / ".git", digest_content=False)
        stable_tree_sha256 = _walk_tree(
            legacy,
            exclude=_STABLE_TREE_EXCLUDES,
            digest_content=True,
        )
    except _UnsafeTree as exc:
        return _detection(
            LegacyLayoutState.SYMLINK
            if exc.kind == "symlink"
            else LegacyLayoutState.SPECIAL_NODE,
            "unsafe-node-inside-legacy-tree",
        )
    except LegacyMigrationError:
        return _detection(LegacyLayoutState.PARTIAL_AMBIGUOUS, "legacy-tree-raced-or-unreadable")
    if _journal_is_incomplete(legacy):
        return _detection(LegacyLayoutState.INCOMPLETE_JOURNAL, "legacy-journal-has-begin")
    try:
        git_receipt, dirty = _git_receipt(legacy)
    except LegacyMigrationError:
        return _detection(LegacyLayoutState.PARTIAL_AMBIGUOUS, "legacy-git-invalid")
    if dirty:
        return _detection(LegacyLayoutState.DIRTY, "legacy-git-dirty")

    snapshot_paths = (
        ".gitignore",
        "AGENTS.md",
        ".agents/.install-manifest.json",
        ".agents/VERSION",
        ".agents/WORKSPACE_RULES.md",
    )
    root_receipts: list[tuple[str, str]] = []
    for relative in snapshot_paths:
        try:
            receipt = _file_receipt(workspace / relative)
        except LegacyMigrationError:
            return _detection(
                LegacyLayoutState.PARTIAL_AMBIGUOUS,
                "root-owned-file-raced-or-oversized",
            )
        if receipt["state"] in {"symlink", "special", "directory"}:
            return _detection(LegacyLayoutState.SYMLINK if receipt["state"] == "symlink" else LegacyLayoutState.SPECIAL_NODE, "unsafe-root-owned-file")
        root_receipts.append((relative, _json_digest(receipt)))
    movable_entries = tuple(
        sorted(
            name
            for name in legacy_entries
            if name in _MIGRATABLE_TOP_LEVEL and name != ".gitignore"
        )
    )
    entry_identities = tuple(
        sorted(
            (name, tuple(_identity_payload(metadata)))
            for name, metadata in legacy_entries.items()
        )
    )
    return _detection(
        LegacyLayoutState.ELIGIBLE_LEGACY,
        "eligible-legacy-workspace",
        workspace_identity=tuple(_identity_payload(workspace_metadata)),
        legacy_identity=tuple(_identity_payload(legacy_metadata)),
        movable_entries=movable_entries,
        entry_identities=entry_identities,
        stable_tree_sha256=stable_tree_sha256,
        root_receipts=tuple(root_receipts),
        git=git_receipt,
    )


@dataclass(frozen=True)
class MigrationPlan:
    schema: str
    operation_id: str
    workspace_root: str
    recovery_name: str
    detection_fingerprint: str
    old_head: str
    old_head_ref: str
    old_tree: str
    old_refs_sha256: str
    old_refs: tuple[str, ...]
    old_index_sha256: str
    stable_tree_sha256: str
    movable_entries: tuple[str, ...]
    entry_identities: tuple[tuple[str, tuple[int, ...]], ...]
    workspace_identity: tuple[int, ...]
    legacy_identity: tuple[int, ...]
    legacy_mode: int
    plan_sha256: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "operation_id": self.operation_id,
            "workspace_root": self.workspace_root,
            "recovery_name": self.recovery_name,
            "detection_fingerprint": self.detection_fingerprint,
            "old_head": self.old_head,
            "old_head_ref": self.old_head_ref,
            "old_tree": self.old_tree,
            "old_refs_sha256": self.old_refs_sha256,
            "old_refs": list(self.old_refs),
            "old_index_sha256": self.old_index_sha256,
            "stable_tree_sha256": self.stable_tree_sha256,
            "movable_entries": list(self.movable_entries),
            "entry_identities": [
                [name, list(identity)] for name, identity in self.entry_identities
            ],
            "workspace_identity": list(self.workspace_identity),
            "legacy_identity": list(self.legacy_identity),
            "legacy_mode": self.legacy_mode,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "plan_sha256": self.plan_sha256}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MigrationPlan":
        try:
            plan = cls(
                schema=str(payload["schema"]),
                operation_id=str(payload["operation_id"]),
                workspace_root=str(payload["workspace_root"]),
                recovery_name=str(payload["recovery_name"]),
                detection_fingerprint=str(payload["detection_fingerprint"]),
                old_head=str(payload["old_head"]),
                old_head_ref=str(payload["old_head_ref"]),
                old_tree=str(payload["old_tree"]),
                old_refs_sha256=str(payload["old_refs_sha256"]),
                old_refs=tuple(str(item) for item in payload["old_refs"]),
                old_index_sha256=str(payload["old_index_sha256"]),
                stable_tree_sha256=str(payload["stable_tree_sha256"]),
                movable_entries=tuple(str(item) for item in payload["movable_entries"]),
                entry_identities=tuple(
                    (str(item[0]), tuple(int(value) for value in item[1]))
                    for item in payload["entry_identities"]
                ),
                workspace_identity=tuple(int(item) for item in payload["workspace_identity"]),
                legacy_identity=tuple(int(item) for item in payload["legacy_identity"]),
                legacy_mode=int(payload["legacy_mode"]),
                plan_sha256=str(payload["plan_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LegacyMigrationError("migration plan has an invalid schema") from exc
        if plan.schema != PLAN_SCHEMA or not re.fullmatch(r"[0-9a-f]{24}", plan.operation_id):
            raise LegacyMigrationError("migration plan has an invalid identity")
        if plan.recovery_name != f".workspace-oss-migration-{plan.operation_id}":
            raise LegacyMigrationError("migration plan recovery identity is invalid")
        try:
            canonical_workspace = _lexical_absolute(plan.workspace_root).as_posix()
        except LegacyMigrationError as exc:
            raise LegacyMigrationError("migration plan workspace identity is invalid") from exc
        if canonical_workspace != plan.workspace_root:
            raise LegacyMigrationError("migration plan workspace path is not canonical")
        movable_allowed = _MIGRATABLE_TOP_LEVEL - {".gitignore"}
        if (
            len(set(plan.movable_entries)) != len(plan.movable_entries)
            or tuple(sorted(plan.movable_entries)) != plan.movable_entries
            or any(
                name not in movable_allowed
                or PurePosixPath(name).parts != (name,)
                for name in plan.movable_entries
            )
        ):
            raise LegacyMigrationError("migration plan movable inventory is invalid")
        identities = dict(plan.entry_identities)
        expected_entry_names = {*plan.movable_entries, ".git"}
        if (
            len(identities) != len(plan.entry_identities)
            or frozenset(identities)
            not in {frozenset(expected_entry_names), frozenset({*expected_entry_names, ".gitignore"})}
            or any(len(identity) != 6 for identity in identities.values())
            or len(plan.workspace_identity) != 6
            or len(plan.legacy_identity) != 6
        ):
            raise LegacyMigrationError("migration plan filesystem receipts are invalid")
        sha_values = (
            plan.detection_fingerprint,
            plan.old_head,
            plan.old_tree,
            plan.old_refs_sha256,
            plan.old_index_sha256,
            plan.stable_tree_sha256,
        )
        if any(not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) for value in sha_values):
            raise LegacyMigrationError("migration plan digest receipt is invalid")
        if not plan.old_head_ref.startswith("refs/heads/") or not 0 <= plan.legacy_mode <= 0o7777:
            raise LegacyMigrationError("migration plan Git or mode receipt is invalid")
        if _json_digest(plan.unsigned_dict()) != plan.plan_sha256:
            raise LegacyMigrationError("migration plan digest is invalid")
        return plan

    @classmethod
    def from_json(cls, value: str) -> "MigrationPlan":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise LegacyMigrationError("migration plan is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LegacyMigrationError("migration plan must be a JSON object")
        return cls.from_dict(payload)


def plan_legacy_migration(workspace_root: str | Path) -> MigrationPlan:
    workspace = _lexical_absolute(workspace_root)
    detection = detect_legacy_layout(workspace)
    if detection.state is not LegacyLayoutState.ELIGIBLE_LEGACY or detection.git is None:
        raise LegacyMigrationError(f"legacy migration is not eligible: {detection.state.value}")
    parent = workspace.parent
    parent_metadata = parent.lstat()
    workspace_metadata = workspace.lstat()
    if _node_kind(parent_metadata) != "directory" or parent_metadata.st_dev != workspace_metadata.st_dev:
        raise LegacyMigrationError("private recovery material must use the same filesystem")
    operation_id = uuid.uuid4().hex[:24]
    recovery_name = f".workspace-oss-migration-{operation_id}"
    if _lstat(parent / recovery_name) is not None:
        raise LegacyMigrationError("private recovery material already exists")
    unsigned = {
        "schema": PLAN_SCHEMA,
        "operation_id": operation_id,
        "workspace_root": workspace.as_posix(),
        "recovery_name": recovery_name,
        "detection_fingerprint": detection.fingerprint,
        "old_head": detection.git.head,
        "old_head_ref": detection.git.head_ref,
        "old_tree": detection.git.tree,
        "old_refs_sha256": detection.git.refs_sha256,
        "old_refs": list(detection.git.refs),
        "old_index_sha256": detection.git.index_sha256,
        "stable_tree_sha256": detection.stable_tree_sha256,
        "movable_entries": list(detection.movable_entries),
        "entry_identities": [
            [name, list(identity)] for name, identity in detection.entry_identities
        ],
        "workspace_identity": list(detection.workspace_identity),
        "legacy_identity": list(detection.legacy_identity),
        "legacy_mode": stat.S_IMODE((workspace / "kb").lstat().st_mode),
    }
    return MigrationPlan.from_dict({**unsigned, "plan_sha256": _json_digest(unsigned)})


def _plan_matches_detection(plan: MigrationPlan, detection: LegacyDetection) -> bool:
    git = detection.git
    return bool(
        detection.state is LegacyLayoutState.ELIGIBLE_LEGACY
        and git is not None
        and detection.fingerprint == plan.detection_fingerprint
        and detection.workspace_identity == plan.workspace_identity
        and detection.legacy_identity == plan.legacy_identity
        and detection.movable_entries == plan.movable_entries
        and detection.entry_identities == plan.entry_identities
        and detection.stable_tree_sha256 == plan.stable_tree_sha256
        and git.head == plan.old_head
        and git.head_ref == plan.old_head_ref
        and git.tree == plan.old_tree
        and git.refs_sha256 == plan.old_refs_sha256
        and git.refs == plan.old_refs
        and git.index_sha256 == plan.old_index_sha256
    )


def _require_current_message_authorization(
    user_authorization: str,
    authorization_source: str,
) -> str:
    authorization = str(user_authorization or "").strip()
    if authorization_source != "user_message" or not authorization:
        raise LegacyMigrationError(
            "migration requires explicit authorization from the current user message"
        )
    return _bytes_digest(authorization.encode("utf-8"))


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


@contextmanager
def _exclusive_workspace(workspace: Path, expected_identity: Sequence[int]) -> Iterator[int]:
    descriptor = -1
    try:
        descriptor = os.open(workspace, _directory_flags())
        opened = os.fstat(descriptor)
        # Directory mtime/ctime necessarily changes as the migration moves
        # children.  The long-lived root capability is dev/inode/type; exact
        # content currentness is independently bound by the plan/receipt/tree
        # and Git digests at each operation boundary.
        if list(_node_identity(opened)) != list(expected_identity[:3]):
            raise LegacyMigrationError("workspace identity is stale")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LegacyMigrationError("workspace has another active lifecycle operation") from exc
        current = os.stat(workspace, follow_symlinks=False)
        if _read_identity(current) != _read_identity(opened):
            raise LegacyMigrationError("workspace identity changed before lock acquisition")
        yield descriptor
    finally:
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        count = os.write(descriptor, view)
        if count <= 0:
            raise LegacyMigrationError("atomic write made no progress")
        view = view[count:]


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    parent = path.parent
    parent_metadata = parent.lstat()
    if _node_kind(parent_metadata) != "directory":
        raise LegacyMigrationError("write parent is not a real directory")
    parent_fd = os.open(parent, _directory_flags())
    if _node_identity(os.fstat(parent_fd)) != _node_identity(parent_metadata):
        os.close(parent_fd)
        raise LegacyMigrationError("write parent identity changed while opening")
    temporary = f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            mode,
            dir_fd=parent_fd,
        )
        _write_all(descriptor, content)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _atomic_create(path: Path, content: bytes, mode: int) -> None:
    """Create one control file without an overwrite race."""

    parent = path.parent
    parent_metadata = parent.lstat()
    if _node_kind(parent_metadata) != "directory":
        raise LegacyMigrationError("create parent is not a real directory")
    parent_fd = os.open(parent, _directory_flags())
    if _node_identity(os.fstat(parent_fd)) != _node_identity(parent_metadata):
        os.close(parent_fd)
        raise LegacyMigrationError("create parent identity changed while opening")
    temporary = f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    linked = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            mode,
            dir_fd=parent_fd,
        )
        _write_all(descriptor, content)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(
                temporary,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise LegacyMigrationError("control target appeared after preflight") from exc
        linked = True
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except BaseException:
        if linked:
            try:
                os.unlink(path.name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        if linked:
            try:
                os.fsync(parent_fd)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _capture_file(path: Path) -> dict[str, Any]:
    metadata = _lstat(path)
    if metadata is None:
        return {"state": "absent"}
    if _node_kind(metadata) != "file":
        raise LegacyMigrationError("recovery input is not a stable regular file")
    content, stable = _safe_read(path)
    return {
        "state": "file",
        "mode": stat.S_IMODE(stable.st_mode),
        "sha256": _bytes_digest(content),
        "data_base64": base64.b64encode(content).decode("ascii"),
    }


def _snapshot_bytes(snapshot: Mapping[str, Any]) -> bytes:
    if snapshot.get("state") != "file":
        raise LegacyMigrationError("recovery snapshot does not contain a file")
    try:
        content = base64.b64decode(str(snapshot["data_base64"]), validate=True)
    except (KeyError, ValueError) as exc:
        raise LegacyMigrationError("recovery snapshot bytes are invalid") from exc
    if _bytes_digest(content) != str(snapshot.get("sha256") or ""):
        raise LegacyMigrationError("recovery snapshot digest is invalid")
    return content


def _restore_file(path: Path, snapshot: Mapping[str, Any]) -> None:
    state = str(snapshot.get("state") or "")
    current = _lstat(path)
    if state == "absent":
        if current is None:
            return
        if _node_kind(current) != "file":
            raise LegacyMigrationError("recovery target became unsafe")
        path.unlink()
        return
    if state != "file":
        raise LegacyMigrationError("recovery snapshot state is invalid")
    if current is not None and _node_kind(current) != "file":
        raise LegacyMigrationError("recovery target became unsafe")
    _atomic_write(path, _snapshot_bytes(snapshot), int(snapshot.get("mode") or 0o644))


def _recovery_path(plan: MigrationPlan) -> Path:
    return Path(plan.workspace_root).parent / plan.recovery_name


def _receipt_path(recovery: Path) -> Path:
    return recovery / "receipt.json"


def _receipt_unsigned(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "receipt_sha256"}


def _write_recovery_receipt(recovery: Path, payload: dict[str, Any]) -> None:
    unsigned = _receipt_unsigned(payload)
    sealed = {**unsigned, "receipt_sha256": _json_digest(unsigned)}
    _atomic_write(
        _receipt_path(recovery),
        json.dumps(sealed, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n",
        0o600,
    )
    payload.clear()
    payload.update(sealed)


def _load_recovery_receipt(recovery: Path) -> dict[str, Any]:
    recovery_metadata = recovery.lstat()
    if (
        _node_kind(recovery_metadata) != "directory"
        or recovery_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(recovery_metadata.st_mode) & 0o077
    ):
        raise LegacyMigrationError("private recovery directory is unsafe")
    recovery_fd = os.open(recovery, _directory_flags())
    try:
        if _read_identity(os.fstat(recovery_fd)) != _read_identity(recovery_metadata):
            raise LegacyMigrationError("private recovery directory identity changed")
        try:
            receipt_metadata = os.stat(
                "receipt.json",
                dir_fd=recovery_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise LegacyMigrationError("private recovery receipt is missing") from exc
        if (
            _node_kind(receipt_metadata) != "file"
            or receipt_metadata.st_size < 0
            or receipt_metadata.st_size > _MAX_RECOVERY_RECEIPT_BYTES
        ):
            raise LegacyMigrationError("private recovery receipt is unsafe or oversized")
        descriptor = os.open(
            "receipt.json",
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=recovery_fd,
        )
        try:
            opened = os.fstat(descriptor)
            if _read_identity(opened) != _read_identity(receipt_metadata):
                raise LegacyMigrationError("private recovery receipt identity changed")
            chunks: list[bytes] = []
            remaining = opened.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise LegacyMigrationError("private recovery receipt changed while reading")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1) or _read_identity(opened) != _read_identity(
                os.fstat(descriptor)
            ):
                raise LegacyMigrationError("private recovery receipt changed while reading")
            content = b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(recovery_fd)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyMigrationError("private recovery receipt is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema") != RECOVERY_SCHEMA:
        raise LegacyMigrationError("private recovery receipt has an invalid schema")
    expected = str(payload.get("receipt_sha256") or "")
    if _json_digest(_receipt_unsigned(payload)) != expected:
        raise LegacyMigrationError("private recovery receipt digest is invalid")
    return payload


def _record_stage(recovery: Path, receipt: dict[str, Any], stage: str) -> None:
    stages = receipt.setdefault("completed_stages", [])
    if not isinstance(stages, list):
        raise LegacyMigrationError("private recovery receipt stages are invalid")
    if stage not in stages:
        stages.append(stage)
    receipt["state"] = "applying"
    _write_recovery_receipt(recovery, receipt)


def _inject_fault(stage: str, requested: str | None) -> None:
    if requested == stage:
        raise LegacyMigrationError(f"injected migration failure after {stage}")


def _create_recovery_material(
    plan: MigrationPlan,
    authorization_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    workspace = Path(plan.workspace_root)
    legacy = workspace / "kb"
    recovery = _recovery_path(plan)
    parent = recovery.parent
    parent_metadata = parent.lstat()
    workspace_metadata = workspace.lstat()
    if parent_metadata.st_dev != workspace_metadata.st_dev:
        raise LegacyMigrationError("private recovery material is on another filesystem")
    try:
        os.mkdir(recovery, 0o700)
    except FileExistsError as exc:
        raise LegacyMigrationError("private recovery material already exists") from exc
    try:
        receipt = {
            "schema": RECOVERY_SCHEMA,
            "operation_id": plan.operation_id,
            "workspace_root": plan.workspace_root,
            "plan": plan.to_dict(),
            "authorization_sha256": authorization_sha256,
            "state": "applying",
            "completed_stages": [],
            "migration_head": "",
            "rollback_head": "",
            "original_files": {
                "root_gitignore": _capture_file(workspace / ".gitignore"),
                "legacy_gitignore": _capture_file(legacy / ".gitignore"),
                "root_agents": _capture_file(workspace / "AGENTS.md"),
                "install_manifest": _capture_file(
                    workspace / ".agents/.install-manifest.json"
                ),
                "bundle_version": _capture_file(workspace / ".agents/VERSION"),
                "workspace_rules": _capture_file(
                    workspace / ".agents/WORKSPACE_RULES.md"
                ),
            },
        }
        _write_recovery_receipt(recovery, receipt)
    except BaseException:
        # No workspace mutation has happened yet.  Remove only the regular
        # receipt we created and the still-empty private directory; never
        # recurse through an unexpected node.
        receipt_metadata = _lstat(_receipt_path(recovery))
        if receipt_metadata is not None and _node_kind(receipt_metadata) == "file":
            _receipt_path(recovery).unlink()
        try:
            recovery.rmdir()
        except OSError:
            pass
        raise
    return recovery, receipt


def _merge_gitignore(root_snapshot: Mapping[str, Any], legacy_snapshot: Mapping[str, Any]) -> bytes:
    root_bytes = _snapshot_bytes(root_snapshot) if root_snapshot.get("state") == "file" else b""
    legacy_bytes = _snapshot_bytes(legacy_snapshot) if legacy_snapshot.get("state") == "file" else b""
    for label, content in (("root", root_bytes), ("legacy", legacy_bytes)):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LegacyMigrationError(f"{label} ignore file is not UTF-8") from exc
    merged = bytearray(root_bytes)
    if merged and not merged.endswith(b"\n"):
        merged.extend(b"\n")
    if legacy_bytes and legacy_bytes != root_bytes:
        if merged:
            merged.extend(b"\n# Preserved legacy knowledge-base ignore rules\n")
        merged.extend(legacy_bytes)
        if not merged.endswith(b"\n"):
            merged.extend(b"\n")
    text_lines = bytes(merged).decode("utf-8").splitlines()
    missing = [line for line in WORKSPACE_GITIGNORE_LINES if line and line not in text_lines]
    if missing:
        if merged and not merged.endswith(b"\n"):
            merged.extend(b"\n")
        if merged:
            merged.extend(b"\n")
        merged.extend(b"# Workspace-root anchored ignore contract\n")
        merged.extend("\n".join(missing).encode("utf-8"))
        merged.extend(b"\n")
    if not merged:
        merged.extend("\n".join(WORKSPACE_GITIGNORE_LINES).encode("utf-8"))
        merged.extend(b"\n")
    return bytes(merged)


def _merged_gitignore_mode(
    root_snapshot: Mapping[str, Any],
    legacy_snapshot: Mapping[str, Any],
) -> int:
    for snapshot in (root_snapshot, legacy_snapshot):
        if snapshot.get("state") == "file":
            mode = int(snapshot.get("mode") or 0)
            if not 0 < mode <= 0o7777:
                raise LegacyMigrationError("ignore file mode receipt is invalid")
            return mode
    return 0o644


def _move_no_replace(
    source: Path,
    destination: Path,
    *,
    expected_identity: Sequence[int] | None = None,
) -> None:
    source_metadata = source.lstat()
    if _node_kind(source_metadata) not in {"file", "directory"}:
        raise LegacyMigrationError("migration source became unsafe")
    if expected_identity is not None and tuple(_identity_payload(source_metadata)) != tuple(
        expected_identity
    ):
        raise LegacyMigrationError("migration source identity is stale")
    if _lstat(destination) is not None:
        raise LegacyMigrationError("migration destination appeared after preflight")
    os.rename(source, destination)
    moved = destination.lstat()
    if _node_identity(moved) != _node_identity(source_metadata):
        raise LegacyMigrationError("migration move did not preserve filesystem identity")


def _remove_regular(path: Path) -> None:
    metadata = _lstat(path)
    if metadata is None:
        return
    if _node_kind(metadata) != "file":
        raise LegacyMigrationError("migration control target became unsafe")
    path.unlink()


def _ensure_config_directory(workspace: Path) -> tuple[Path, bool]:
    config = workspace / "config"
    metadata = _lstat(config)
    if metadata is None:
        config.mkdir(mode=0o755)
        return config, True
    if _node_kind(metadata) != "directory":
        raise LegacyMigrationError("root config target became unsafe")
    return config, False


def _write_layout_marker(workspace: Path) -> None:
    config, _ = _ensure_config_directory(workspace)
    marker = config / "workspace-layout.yaml"
    if _lstat(marker) is not None:
        raise LegacyMigrationError("workspace layout marker appeared after preflight")
    _atomic_create(marker, WORKSPACE_LAYOUT_MARKER_BYTES, 0o644)


def _literal_pathspec(relative: str) -> str:
    return f":(literal){relative}"


def _verify_original_refs(plan: MigrationPlan, repo: Path, *, current_head: str) -> None:
    current_rows = tuple(
        sorted(
            line
            for line in _run_git(repo, "show-ref", "--head").stdout.decode("utf-8").splitlines()
            if line
        )
    )
    original_other = {
        row
        for row in plan.old_refs
        if not row.endswith(" HEAD") and not row.endswith(f" {plan.old_head_ref}")
    }
    current_other = {
        row
        for row in current_rows
        if not row.endswith(" HEAD") and not row.endswith(f" {plan.old_head_ref}")
    }
    if original_other != current_other:
        raise LegacyMigrationError("non-current Git refs changed during migration")
    expected_current = {
        f"{current_head} HEAD",
        f"{current_head} {plan.old_head_ref}",
    }
    if not expected_current.issubset(set(current_rows)):
        raise LegacyMigrationError("current Git branch receipt is inconsistent")
    if _run_git(repo, "cat-file", "-e", f"{plan.old_head}^{{commit}}", check=False).returncode != 0:
        raise LegacyMigrationError("original Git HEAD is no longer reachable")


def _verify_integration_snapshots(workspace: Path, receipt: Mapping[str, Any]) -> None:
    files = receipt.get("original_files")
    if not isinstance(files, dict):
        raise LegacyMigrationError("private recovery file receipts are invalid")
    for key, relative in (
        ("root_agents", "AGENTS.md"),
        ("install_manifest", ".agents/.install-manifest.json"),
        ("bundle_version", ".agents/VERSION"),
        ("workspace_rules", ".agents/WORKSPACE_RULES.md"),
    ):
        expected = files.get(key)
        if not isinstance(expected, dict):
            raise LegacyMigrationError("private recovery file receipt is missing")
        current = _capture_file(workspace / relative)
        if current != expected:
            raise LegacyMigrationError("workspace integration bytes changed during migration")


def _allowed_untracked_integration(relative: str) -> bool:
    path = PurePosixPath(relative)
    return bool(path.parts and path.parts[0] in _ROOT_INTEGRATION_TOP_LEVEL)


def _create_migration_commit(plan: MigrationPlan, workspace: Path) -> str:
    tracked_changes = {
        line
        for line in _run_git(workspace, "diff", "--name-only").stdout.decode("utf-8").splitlines()
        if line
    }
    if not tracked_changes.issubset({".gitignore"}):
        raise LegacyMigrationError("unexpected tracked bytes changed during migration")
    staged = _run_git(workspace, "diff", "--cached", "--name-only").stdout
    if staged.strip():
        raise LegacyMigrationError("legacy Git index became staged during migration")
    untracked = tuple(
        item.decode("utf-8")
        for item in _run_git(workspace, "ls-files", "--others", "--exclude-standard", "-z").stdout.split(b"\0")
        if item
    )
    expected_marker = WORKSPACE_LAYOUT_MARKER_RELATIVE.as_posix()
    unexpected = [
        item
        for item in untracked
        if item != expected_marker and not _allowed_untracked_integration(item)
    ]
    if unexpected:
        raise LegacyMigrationError("unexpected untracked canonical path appeared during migration")
    pathspecs = [_literal_pathspec(".gitignore"), _literal_pathspec(expected_marker)]
    _run_git(workspace, "add", "--", *pathspecs)
    commit = _run_git(
        workspace,
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "--no-verify",
        "--only",
        "-m",
        MIGRATION_COMMIT_MESSAGE,
        "--",
        *pathspecs,
    )
    if commit.returncode != 0:
        raise LegacyMigrationError("migration commit could not be created")
    head = _run_git(workspace, "rev-parse", "HEAD").stdout.decode("ascii").strip()
    parent = _run_git(workspace, "rev-parse", "HEAD^").stdout.decode("ascii").strip()
    if parent != plan.old_head:
        raise LegacyMigrationError("migration commit did not preserve original HEAD as its parent")
    return head


def _stable_root_digest(workspace: Path) -> str:
    return _walk_tree(
        workspace,
        exclude=frozenset(
            {
                ".git",
                ".gitignore",
                WORKSPACE_LAYOUT_MARKER_RELATIVE.as_posix(),
                *(_ROOT_INTEGRATION_TOP_LEVEL),
            }
        ),
        digest_content=True,
    )


def apply_legacy_migration(
    plan: MigrationPlan,
    *,
    user_authorization: str,
    authorization_source: str,
    _fault_after: str | None = None,
    _auto_rollback: bool = True,
) -> dict[str, Any]:
    """Apply one frozen plan; private fault hooks exist only for acceptance tests."""

    if not isinstance(plan, MigrationPlan):
        raise LegacyMigrationError("migration apply requires a validated plan")
    # Reparse the serialized shape so a manually constructed dataclass cannot
    # bypass schema or digest validation.
    plan = MigrationPlan.from_dict(plan.to_dict())
    authorization_sha256 = _require_current_message_authorization(
        user_authorization,
        authorization_source,
    )
    workspace = _lexical_absolute(plan.workspace_root)
    recovery: Path | None = None
    receipt: dict[str, Any] | None = None
    with _exclusive_workspace(workspace, plan.workspace_identity):
        current = detect_legacy_layout(workspace)
        if not _plan_matches_detection(plan, current):
            raise LegacyMigrationError("migration preflight is stale")
        try:
            recovery, receipt = _create_recovery_material(plan, authorization_sha256)
            _record_stage(recovery, receipt, "recovery-prepared")
            _inject_fault("recovery-prepared", _fault_after)

            # Recovery capture itself must not widen the plan.  Re-run the
            # complete read-only receipt before the first destructive move.
            if not _plan_matches_detection(plan, detect_legacy_layout(workspace)):
                raise LegacyMigrationError("migration preflight changed after recovery capture")

            legacy = workspace / "kb"
            original_files = receipt["original_files"]
            merged_ignore = _merge_gitignore(
                original_files["root_gitignore"],
                original_files["legacy_gitignore"],
            )
            merged_ignore_mode = _merged_gitignore_mode(
                original_files["root_gitignore"],
                original_files["legacy_gitignore"],
            )
            if _capture_file(workspace / ".gitignore") != original_files["root_gitignore"]:
                raise LegacyMigrationError("root ignore bytes changed before migration")
            if _capture_file(legacy / ".gitignore") != original_files["legacy_gitignore"]:
                raise LegacyMigrationError("legacy ignore bytes changed before migration")
            expected_entries = dict(plan.entry_identities)
            _move_no_replace(
                legacy / ".git",
                workspace / ".git",
                expected_identity=expected_entries[".git"],
            )
            _record_stage(recovery, receipt, "git-moved")
            _inject_fault("git-moved", _fault_after)

            for name in plan.movable_entries:
                _move_no_replace(
                    legacy / name,
                    workspace / name,
                    expected_identity=expected_entries[name],
                )
            _record_stage(recovery, receipt, "entries-moved")
            _inject_fault("entries-moved", _fault_after)

            if _capture_file(workspace / ".gitignore") != original_files["root_gitignore"]:
                raise LegacyMigrationError("root ignore bytes changed before merge")
            if _capture_file(legacy / ".gitignore") != original_files["legacy_gitignore"]:
                raise LegacyMigrationError("legacy ignore bytes changed before merge")
            _atomic_write(workspace / ".gitignore", merged_ignore, merged_ignore_mode)
            _remove_regular(legacy / ".gitignore")
            try:
                legacy.rmdir()
            except OSError as exc:
                raise LegacyMigrationError("legacy wrapper is not empty after exact moves") from exc
            _record_stage(recovery, receipt, "ignore-merged")
            _inject_fault("ignore-merged", _fault_after)

            _write_layout_marker(workspace)
            _record_stage(recovery, receipt, "marker-written")
            _inject_fault("marker-written", _fault_after)

            if _stable_root_digest(workspace) != plan.stable_tree_sha256:
                raise LegacyMigrationError("canonical bytes changed during migration")
            _verify_integration_snapshots(workspace, receipt)
            _verify_original_refs(plan, workspace, current_head=plan.old_head)
            migration_head = _create_migration_commit(plan, workspace)
            receipt["migration_head"] = migration_head
            _record_stage(recovery, receipt, "commit-created")
            _inject_fault("commit-created", _fault_after)

            _verify_original_refs(plan, workspace, current_head=migration_head)
            if _stable_root_digest(workspace) != plan.stable_tree_sha256:
                raise LegacyMigrationError("canonical bytes changed after migration commit")
            _verify_integration_snapshots(workspace, receipt)
            receipt["state"] = "migrated"
            _write_recovery_receipt(recovery, receipt)
            return {
                "state": "migrated",
                "operation_id": plan.operation_id,
                "old_head": plan.old_head,
                "migration_head": migration_head,
                "recovery_material": recovery.as_posix(),
                "stable_tree_sha256": plan.stable_tree_sha256,
            }
        except BaseException as exc:
            if recovery is not None and receipt is not None and _auto_rollback:
                try:
                    _rollback_partial_locked(plan, recovery, receipt)
                except BaseException as rollback_exc:
                    receipt["state"] = "rollback-incomplete"
                    receipt["rollback_error"] = type(rollback_exc).__name__
                    _write_recovery_receipt(recovery, receipt)
                    raise LegacyMigrationError(
                        "migration failed and exact rollback is incomplete; private recovery material was preserved"
                    ) from rollback_exc
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError("legacy migration failed closed") from exc


def _remove_marker_for_rollback(workspace: Path) -> None:
    marker = workspace / WORKSPACE_LAYOUT_MARKER_RELATIVE
    _remove_regular(marker)


def _reset_migration_ref_without_checkout(plan: MigrationPlan, workspace: Path) -> None:
    if _lstat(workspace / ".git") is None:
        return
    current_result = _run_git(workspace, "rev-parse", "--verify", "HEAD", check=False)
    if current_result.returncode != 0:
        return
    current = current_result.stdout.decode("ascii").strip()
    if current == plan.old_head:
        return
    parent = _run_git(workspace, "rev-parse", f"{current}^", check=False)
    if parent.returncode != 0 or parent.stdout.decode("ascii").strip() != plan.old_head:
        raise LegacyMigrationError("partial migration HEAD cannot be safely restored")
    _run_git(workspace, "update-ref", plan.old_head_ref, plan.old_head, current)
    _run_git(workspace, "read-tree", plan.old_head)


def _rollback_partial_locked(
    plan: MigrationPlan,
    recovery: Path,
    receipt: dict[str, Any],
) -> None:
    workspace = Path(plan.workspace_root)
    legacy = workspace / "kb"
    original_files = receipt.get("original_files")
    if not isinstance(original_files, dict):
        raise LegacyMigrationError("private recovery snapshots are missing")
    _reset_migration_ref_without_checkout(plan, workspace)
    _remove_marker_for_rollback(workspace)
    if _lstat(legacy) is None:
        legacy.mkdir(mode=plan.legacy_mode)
    elif _node_kind(legacy.lstat()) != "directory":
        raise LegacyMigrationError("legacy rollback target is unsafe")

    for name in reversed(plan.movable_entries):
        source = workspace / name
        destination = legacy / name
        source_metadata = _lstat(source)
        destination_metadata = _lstat(destination)
        if source_metadata is not None and destination_metadata is None:
            _move_no_replace(source, destination)
        elif source_metadata is not None and destination_metadata is not None:
            raise LegacyMigrationError("partial rollback found duplicate canonical entries")
    root_git = workspace / ".git"
    legacy_git = legacy / ".git"
    if _lstat(root_git) is not None and _lstat(legacy_git) is None:
        _move_no_replace(root_git, legacy_git)
    elif _lstat(root_git) is not None and _lstat(legacy_git) is not None:
        raise LegacyMigrationError("partial rollback found duplicate Git metadata")

    _restore_file(legacy / ".gitignore", original_files["legacy_gitignore"])
    _restore_file(workspace / ".gitignore", original_files["root_gitignore"])
    config = workspace / "config"
    if "config" not in plan.movable_entries and _lstat(config) is not None:
        try:
            config.rmdir()
        except OSError as exc:
            raise LegacyMigrationError("migration-created config directory is not empty") from exc
    if _stable_legacy_digest(legacy) != plan.stable_tree_sha256:
        raise LegacyMigrationError("partial rollback did not restore canonical bytes")
    restored_head = _run_git(legacy, "rev-parse", "HEAD").stdout.decode("ascii").strip()
    if restored_head != plan.old_head:
        raise LegacyMigrationError("partial rollback did not restore original Git HEAD")
    _verify_original_refs(plan, legacy, current_head=plan.old_head)
    _verify_integration_snapshots(workspace, receipt)
    receipt["state"] = "rolled-back-after-failure"
    _write_recovery_receipt(recovery, receipt)


def _stable_legacy_digest(legacy: Path) -> str:
    return _walk_tree(
        legacy,
        exclude=_STABLE_TREE_EXCLUDES,
        digest_content=True,
    )


def _create_reverse_commit(plan: MigrationPlan, workspace: Path, receipt: Mapping[str, Any]) -> str:
    original_files = receipt["original_files"]
    legacy_ignore = original_files["legacy_gitignore"]
    if legacy_ignore.get("state") == "file":
        _atomic_write(
            workspace / ".gitignore",
            _snapshot_bytes(legacy_ignore),
            int(legacy_ignore.get("mode") or 0o644),
        )
    else:
        _remove_regular(workspace / ".gitignore")
    _remove_marker_for_rollback(workspace)
    pathspecs = [
        _literal_pathspec(".gitignore"),
        _literal_pathspec(WORKSPACE_LAYOUT_MARKER_RELATIVE.as_posix()),
    ]
    _run_git(workspace, "add", "--", *pathspecs)
    _run_git(
        workspace,
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "--no-verify",
        "--only",
        "-m",
        ROLLBACK_COMMIT_MESSAGE,
        "--",
        *pathspecs,
    )
    rollback_head = _run_git(workspace, "rev-parse", "HEAD").stdout.decode("ascii").strip()
    migration_head = str(receipt.get("migration_head") or "")
    parent = _run_git(workspace, "rev-parse", "HEAD^").stdout.decode("ascii").strip()
    if not migration_head or parent != migration_head:
        raise LegacyMigrationError("rollback commit does not descend from the migration commit")
    return rollback_head


def rollback_legacy_migration(
    workspace_root: str | Path,
    recovery_material: str | Path,
    *,
    user_authorization: str,
    authorization_source: str,
    expected_receipt_sha256: str,
    _fault_after: str | None = None,
) -> dict[str, Any]:
    """Reverse a completed migration with a commit, or finish partial recovery."""

    authorization_sha256 = _require_current_message_authorization(
        user_authorization,
        authorization_source,
    )
    workspace = _lexical_absolute(workspace_root)
    recovery = _lexical_absolute(recovery_material)
    if recovery.parent != workspace.parent or not recovery.name.startswith(
        ".workspace-oss-migration-"
    ):
        raise LegacyMigrationError("recovery material is not the unique workspace sibling")
    receipt = _load_recovery_receipt(recovery)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_receipt_sha256 or ""):
        raise LegacyMigrationError("rollback requires an exact recovery receipt digest")
    if receipt.get("receipt_sha256") != expected_receipt_sha256:
        raise LegacyMigrationError("recovery receipt is stale")
    plan_payload = receipt.get("plan")
    if not isinstance(plan_payload, dict):
        raise LegacyMigrationError("recovery receipt is missing its migration plan")
    plan = MigrationPlan.from_dict(plan_payload)
    if plan.workspace_root != workspace.as_posix() or recovery != _recovery_path(plan):
        raise LegacyMigrationError("recovery receipt targets another workspace")

    state = str(receipt.get("state") or "")
    if state not in {"applying", "rollback-incomplete", "migrated"}:
        raise LegacyMigrationError("recovery receipt is not eligible for rollback")
    with _exclusive_workspace(workspace, plan.workspace_identity):
        try:
            # Rollback is a new destructive decision.  Bind its own current
            # user-message authorization instead of requiring the migration
            # sentence to be repeated byte-for-byte.
            receipt["rollback_authorization_sha256"] = authorization_sha256
            _write_recovery_receipt(recovery, receipt)
            if state in {"applying", "rollback-incomplete"}:
                _rollback_partial_locked(plan, recovery, receipt)
                return {
                    "state": "rolled-back-after-failure",
                    "operation_id": plan.operation_id,
                    "head": plan.old_head,
                    "recovery_material": recovery.as_posix(),
                }
            migration_head = str(receipt.get("migration_head") or "")
            current_head = _run_git(workspace, "rev-parse", "HEAD").stdout.decode("ascii").strip()
            if current_head != migration_head:
                raise LegacyMigrationError("migrated Git HEAD changed after the frozen receipt")
            status = _run_git(workspace, "status", "--porcelain=v1", "--untracked-files=no")
            if status.stdout:
                raise LegacyMigrationError("migrated workspace is dirty")
            if _stable_root_digest(workspace) != plan.stable_tree_sha256:
                raise LegacyMigrationError("migrated canonical bytes changed after the receipt")
            _verify_integration_snapshots(workspace, receipt)
            _verify_original_refs(plan, workspace, current_head=migration_head)
            rollback_head = _create_reverse_commit(plan, workspace, receipt)
            receipt["rollback_head"] = rollback_head
            receipt["state"] = "rolling-back"
            _write_recovery_receipt(recovery, receipt)
            _inject_fault("rollback-commit-created", _fault_after)

            legacy = workspace / "kb"
            legacy.mkdir(mode=plan.legacy_mode)
            for name in reversed(plan.movable_entries):
                _move_no_replace(workspace / name, legacy / name)
            _move_no_replace(workspace / ".git", legacy / ".git")
            root_ignore_snapshot = receipt["original_files"]["root_gitignore"]
            # The reverse commit restored the legacy tracked ignore bytes at
            # root. Move those exact bytes back into the legacy repository,
            # then restore the pre-migration workspace-owned ignore file.
            if _lstat(workspace / ".gitignore") is not None:
                _move_no_replace(workspace / ".gitignore", legacy / ".gitignore")
            _restore_file(workspace / ".gitignore", root_ignore_snapshot)
            if "config" not in plan.movable_entries and _lstat(workspace / "config") is not None:
                (workspace / "config").rmdir()
            _inject_fault("rollback-entries-moved", _fault_after)

            if _stable_legacy_digest(legacy) != plan.stable_tree_sha256:
                raise LegacyMigrationError("rollback did not restore canonical bytes")
            restored_head = _run_git(legacy, "rev-parse", "HEAD").stdout.decode("ascii").strip()
            if restored_head != rollback_head:
                raise LegacyMigrationError("rollback Git HEAD is inconsistent")
            if _run_git(legacy, "merge-base", "--is-ancestor", plan.old_head, rollback_head, check=False).returncode != 0:
                raise LegacyMigrationError("rollback history no longer contains original HEAD")
            _verify_integration_snapshots(workspace, receipt)
            receipt["state"] = "rolled-back"
            _write_recovery_receipt(recovery, receipt)
            return {
                "state": "rolled-back",
                "operation_id": plan.operation_id,
                "old_head": plan.old_head,
                "migration_head": migration_head,
                "rollback_head": rollback_head,
                "recovery_material": recovery.as_posix(),
            }
        except BaseException as exc:
            receipt["state"] = "rollback-incomplete"
            receipt["rollback_error"] = type(exc).__name__
            _write_recovery_receipt(recovery, receipt)
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError(
                "rollback is incomplete; private recovery material was preserved"
            ) from exc


__all__ = [
    "LEGACY_MIGRATION_GUIDANCE",
    "LegacyDetection",
    "LegacyLayoutState",
    "LegacyMigrationError",
    "MigrationPlan",
    "apply_legacy_migration",
    "detect_legacy_layout",
    "plan_legacy_migration",
    "rollback_legacy_migration",
]

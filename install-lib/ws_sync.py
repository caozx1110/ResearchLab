#!/usr/bin/env python3
"""Copy-project sync helper for workspace-oss installs.

The helper intentionally manages only two reachable areas:

* ``DIR/.agents`` subtree
* the single root-level ``DIR/AGENTS.md`` file

It never enumerates or mutates sibling runtime/data directories such as
``DIR/kb`` or ``DIR/.venv``.

Release contents come only from the tracked allowlist below. The repository
``LICENSE`` is installed as ``DIR/.agents/LICENSE``. Install, update, and
reinstall stage and validate the complete managed set before committing it;
an exception during commit restores every touched managed path and manifest.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional


PLAN_JSONL = False


def dry_run_info(
    operation: str,
    path: Path,
    *,
    source: Optional[Path] = None,
    content: bytes | None = None,
) -> None:
    """Keep human dry-run output stable while offering exact JSON to the installer."""
    if PLAN_JSONL:
        payload: dict[str, str] = {"operation": operation, "path": str(path)}
        if source is not None:
            payload["source"] = str(source)
        if content is not None:
            payload["content_sha256"] = hashlib.sha256(content).hexdigest()
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if operation in {"copy", "overwrite"} and source is not None:
        info(f"[dry-run] {operation} {source} -> {path}")
    elif operation == "write-manifest":
        info(f"[dry-run] write manifest {path}")
    else:
        info(f"[dry-run] {operation} {path}")


INSTALL_NAME = "workspace-oss"
INSTALL_MODE = "copy-project"
MANIFEST_REL = Path(".agents/.install-manifest.json")
MANIFEST_NAME = ".install-manifest.json"
SCHEMA = 1
LOCAL_CHECKOUT_STRATEGY = "local-checkout"
REMOTE_BRANCH_STRATEGY = "remote-branch"
SOURCE_STRATEGIES = (LOCAL_CHECKOUT_STRATEGY, REMOTE_BRANCH_STRATEGY)
DEFAULT_LEGACY_AGENTS = {"claude": True, "codex": False}
BEGIN_MARKER = "# >>> workspace-oss managed >>>"
END_MARKER = "# <<< workspace-oss managed <<<"
CLAUDE_INCLUDE_BLOCK = (
    f"{BEGIN_MARKER}\n"
    "<!-- Managed by workspace-oss install.sh. AGENTS.md is the source of truth; refresh this block by rerunning install.sh. -->\n"
    "@AGENTS.md\n"
    f"{END_MARKER}\n"
).encode("utf-8")
CLAUDE_SKILLS_REL = ".claude/skills"
CLAUDE_SKILLS_TARGET = "../.agents/skills"
RELEASE_FILE_MAP = {
    "runtime/WORKSPACE_RULES.md": ".agents/WORKSPACE_RULES.md",
    "runtime/requirements.txt": ".agents/requirements.txt",
    "runtime/VERSION": ".agents/VERSION",
    "LICENSE": ".agents/LICENSE",
}
RELEASE_PREFIX_MAP = (
    ("skills/", ".agents/skills/"),
    ("runtime/lib/research/", ".agents/lib/research/"),
)
EXCLUDED_DIRS = {"__pycache__", ".venv", "tests"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store", MANIFEST_NAME, "eval_research_value.py", "skill_validator.py"}
# Snapshot enumeration must additionally prune VCS internals that git-based
# enumeration never sees.
SNAPSHOT_EXCLUDED_DIRS = EXCLUDED_DIRS | {".git"}
# Stable machine token: install.sh keys its actionable Chinese guidance on it.
NOT_GIT_WORKTREE_TOKEN = "source-not-git-worktree"
NOT_GIT_WORKTREE_GUIDANCE = (
    "从 GitHub 下载的 ZIP 包不是 git 仓库；请改用 git clone，"
    "或在源码目录执行 git init && git add -A && git commit 后重试；"
    "也可以在明确接受风险后使用 --allow-snapshot-source 按确定性文件清单打包"
    "（快照模式无法区分未跟踪文件）。"
)
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_EXPECTED_MANIFEST_UNSET = object()


class SyncError(RuntimeError):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def info(message: str) -> None:
    print(message)


def warn(message: str) -> None:
    print(f"warn: {message}", file=sys.stderr)


def die(message: str, code: int = 1) -> None:
    raise SyncError(message, code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def operation_timestamp(value: str) -> str:
    if not value:
        return utc_now()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        die("operation time must use canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_dir(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        die(f"{label} is not a directory: {path}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_bytes(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read()


def should_exclude(path: Path) -> bool:
    if path.name in EXCLUDED_NAMES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    if any(part in EXCLUDED_DIRS for part in path.parts):
        return True
    if any(part.upper().startswith("RESEARCH_VALUE") for part in path.parts):
        return True
    return False


def rel_text(path: Path) -> str:
    return path.as_posix()


def _source_is_git_worktree(source_root: Path) -> bool:
    """Explicitly detect whether the source directory sits inside a git worktree."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == b"true"


def _snapshot_release_files(source_root: Path) -> list[str]:
    """Deterministic non-git enumeration of the packageable release set.

    Walks only the release roots (``skills``, ``runtime``, and ``LICENSE``),
    sorted for stable output, pruning VCS/runtime junk (.git/.venv/__pycache__/
    tests/.DS_Store/*.pyc …). Unlike ``git ls-files`` this cannot distinguish
    untracked files, which is why it stays behind the explicit
    ``--allow-snapshot-source`` opt-in.
    """
    names: list[str] = []
    license_path = source_root / "LICENSE"
    if license_path.is_file() and not license_path.is_symlink():
        names.append("LICENSE")
    for release_root in (source_root / "skills", source_root / "runtime"):
        for current_root, dirs, files in os.walk(release_root, followlinks=False):
            current = Path(current_root)
            dirs[:] = sorted(
                name
                for name in dirs
                if name not in SNAPSHOT_EXCLUDED_DIRS and not name.upper().startswith("RESEARCH_VALUE")
            )
            for name in sorted(files):
                relative = (current / name).relative_to(source_root)
                if should_exclude(relative):
                    continue
                names.append(relative.as_posix())
    return sorted(names)


def tracked_release_files(source_root: Path, *, allow_snapshot: bool = False) -> list[str]:
    if _source_is_git_worktree(source_root):
        try:
            result = subprocess.run(
                ["git", "-C", str(source_root), "ls-files", "-z", "--", "skills", "runtime", "LICENSE"],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            die(
                f"{NOT_GIT_WORKTREE_TOKEN}: 无法枚举源码目录的 git 跟踪文件：{source_root}：{exc}。"
                f"{NOT_GIT_WORKTREE_GUIDANCE}"
            )
        tracked = sorted(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)
        if any(rel == "skills" or rel.startswith("skills/") for rel in tracked) and any(
            rel == "runtime" or rel.startswith("runtime/") for rel in tracked
        ):
            return tracked
        # Inside some git worktree, but the release tree itself is untracked
        # (e.g. a ZIP unpacked into an unrelated repository) — same remediation.
    if allow_snapshot:
        print(
            "snapshot-source: 快照模式无法区分未跟踪文件；已按确定性文件清单打包，"
            "排除 .git、.venv、__pycache__、.DS_Store 等目录和文件。",
            file=sys.stderr,
        )
        return _snapshot_release_files(source_root)
    die(f"{NOT_GIT_WORKTREE_TOKEN}: 源码目录不是可打包的 git 仓库：{source_root}。{NOT_GIT_WORKTREE_GUIDANCE}")
    return []  # unreachable; keeps the signature obviously total


def release_destination(rel: str) -> str | None:
    mapped = RELEASE_FILE_MAP.get(rel)
    if mapped is not None:
        return mapped
    path = Path(rel)
    if should_exclude(path):
        return None
    for source_prefix, destination_prefix in RELEASE_PREFIX_MAP:
        if rel.startswith(source_prefix):
            return destination_prefix + rel[len(source_prefix) :]
    return None


def assert_no_symlinked_source_subdirs(source_root: Path, rel: str) -> None:
    path = source_root / rel
    for parent in path.parents:
        if parent == source_root:
            break
        if parent.is_symlink():
            die(f"source release path contains a symlinked subdirectory: {parent}; refuse to package")


def source_items(
    repo: Path,
    source: Path | None,
    *,
    allow_snapshot: bool = False,
) -> dict[str, tuple[Path, str]]:
    source_root = (source or repo).resolve()
    skills_src = source_root / "skills"
    runtime_src = source_root / "runtime"
    agents_md_src = runtime_src / "AGENTS.md"
    workspace_rules_src = runtime_src / "WORKSPACE_RULES.md"
    if not skills_src.is_dir():
        die(f"source skills directory not found: {skills_src}")
    if not runtime_src.is_dir():
        die(f"source runtime directory not found: {runtime_src}")
    if not agents_md_src.is_file():
        die(f"source AGENTS.md not found: {agents_md_src}")
    if not workspace_rules_src.is_file():
        die(f"source WORKSPACE_RULES.md not found: {workspace_rules_src}")
    items: dict[str, tuple[Path, str]] = {}
    for rel in tracked_release_files(source_root, allow_snapshot=allow_snapshot):
        destination = release_destination(rel)
        if destination is None:
            continue
        assert_no_symlinked_source_subdirs(source_root, rel)
        path = source_root / rel
        if path.is_symlink() or not path.is_file():
            die(f"allowlisted release file is not a regular file: {path}")
        if destination in items:
            die(f"multiple source release files map to the same destination: {destination}")
        items[destination] = (path, sha256_file(path))
    items["AGENTS.md"] = (agents_md_src, sha256_file(agents_md_src))
    return dict(sorted(items.items()))


def source_release_actual_nonempty(repo: Path, source: Path | None) -> bool:
    source_root = (source or repo).resolve()
    for release_root in (source_root / "skills", source_root / "runtime"):
        for _root, dirs, files in os.walk(release_root):
            if dirs or files:
                return True
    return False


class ManifestSnapshot:
    __slots__ = ("payload", "content", "device", "inode", "mode")

    def __init__(self, payload: dict[str, Any], content: bytes, device: int, inode: int, mode: int) -> None:
        self.payload = payload
        self.content = content
        self.device = device
        self.inode = inode
        self.mode = mode


class ManifestExpectation:
    __slots__ = ("kind", "device", "inode", "mode", "byte_sha256")

    def __init__(
        self,
        kind: str,
        device: int = 0,
        inode: int = 0,
        mode: int = 0,
        byte_sha256: str = "",
    ) -> None:
        self.kind = kind
        self.device = device
        self.inode = inode
        self.mode = mode
        self.byte_sha256 = byte_sha256


def manifest_snapshot_state(snapshot: ManifestSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {"type": "absent"}
    return {
        "type": "regular",
        "mode": f"{stat.S_IMODE(snapshot.mode):04o}",
        "byte_sha256": hashlib.sha256(snapshot.content).hexdigest(),
        "device": snapshot.device,
        "inode": snapshot.inode,
    }


def emit_plan_manifest_expectation(snapshot: ManifestSnapshot | None, *, dry_run: bool) -> None:
    if dry_run and PLAN_JSONL:
        print(
            json.dumps(
                {"operation": "manifest-expectation", "state": manifest_snapshot_state(snapshot)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def _same_node(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _same_read_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        _same_node(left, right)
        and left.st_mode == right.st_mode
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


@contextmanager
def workspace_lease(dst_root: Path) -> Iterator[int]:
    """Take the shared lifecycle/rebind lease on the stable workspace root."""

    root = Path(dst_root).expanduser().resolve(strict=False)
    root_fd = -1
    entered = False
    try:
        root_fd = os.open(str(root), _directory_open_flags())
        before = os.fstat(root_fd)
        if not stat.S_ISDIR(before.st_mode):
            die("workspace root is not a real directory")
        fcntl.flock(root_fd, fcntl.LOCK_EX)
        current = os.stat(str(root), follow_symlinks=False)
        if not _same_node(before, current):
            die("workspace root changed before lifecycle lease")
        entered = True
        yield root_fd
    except SyncError:
        raise
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        if entered:
            raise
        die(f"workspace root cannot be safely locked: {exc}")
    finally:
        if root_fd >= 0:
            try:
                fcntl.flock(root_fd, fcntl.LOCK_UN)
            finally:
                os.close(root_fd)


def _open_agents_at(root_fd: int, *, required: bool) -> int:
    try:
        lexical = os.stat(".agents", dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        if required:
            die("managed .agents root is missing")
        return -1
    except OSError as exc:
        die(f"managed .agents root cannot be verified: {exc}")
    if not stat.S_ISDIR(lexical.st_mode):
        die("managed .agents root is not a real directory")
    try:
        descriptor = os.open(".agents", _directory_open_flags(), dir_fd=root_fd)
    except OSError as exc:
        die(f"managed .agents root cannot be safely opened: {exc}")
    if not _same_node(lexical, os.fstat(descriptor)):
        os.close(descriptor)
        die("managed .agents root changed while it was opened")
    return descriptor


def _parse_manifest(content: bytes) -> dict[str, Any]:
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        die(f"manifest is unreadable or invalid JSON: {exc}")
    if not isinstance(data, dict):
        die("manifest has invalid schema")
    if data.get("schema") != SCHEMA or data.get("install_name") != INSTALL_NAME or data.get("install_mode") != INSTALL_MODE:
        die(f"manifest is not a {INSTALL_NAME} {INSTALL_MODE} manifest")
    files = data.get("files")
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        die("manifest files map is invalid")
    return data


def _manifest_snapshot_at(root_fd: int, *, required: bool) -> ManifestSnapshot | None:
    agents_fd = _open_agents_at(root_fd, required=required)
    if agents_fd < 0:
        return None
    descriptor = -1
    try:
        try:
            lexical_before = os.stat(MANIFEST_NAME, dir_fd=agents_fd, follow_symlinks=False)
        except FileNotFoundError:
            if required:
                die("install manifest is missing")
            return None
        except OSError as exc:
            die(f"install manifest cannot be verified: {exc}")
        if not stat.S_ISREG(lexical_before.st_mode):
            die("install manifest is not a regular file")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = os.open(MANIFEST_NAME, flags, dir_fd=agents_fd)
        except OSError as exc:
            die(f"install manifest cannot be safely opened: {exc}")
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not _same_node(lexical_before, before):
            die("install manifest is not a stable regular file")
        if before.st_size <= 0:
            die("install manifest is empty")
        if before.st_size > MAX_MANIFEST_BYTES:
            die("install manifest is too large")
        chunks: list[bytes] = []
        total = 0
        while total < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - total))
            if not chunk:
                die("install manifest changed while it was read")
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        lexical_after = os.stat(MANIFEST_NAME, dir_fd=agents_fd, follow_symlinks=False)
        if (
            total != before.st_size
            or not _same_read_identity(before, after)
            or not _same_read_identity(after, lexical_after)
        ):
            die("install manifest changed while it was read")
        content = b"".join(chunks)
        return ManifestSnapshot(_parse_manifest(content), content, after.st_dev, after.st_ino, after.st_mode)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(agents_fd)


def load_manifest_snapshot(dst_root: Path, *, required: bool = True) -> ManifestSnapshot | None:
    with workspace_lease(dst_root) as root_fd:
        return _manifest_snapshot_at(root_fd, required=required)


def load_manifest(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    snapshot = load_manifest_snapshot(path.parent.parent, required=required)
    return snapshot.payload if snapshot is not None else None


def _manifest_expectation(value: str) -> ManifestExpectation | object:
    text = str(value or "").strip()
    if not text:
        return _EXPECTED_MANIFEST_UNSET
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        die(f"expected manifest state is invalid JSON: {exc}")
    if not isinstance(payload, dict):
        die("expected manifest state is invalid")
    kind = str(payload.get("type") or "")
    if kind == "absent":
        return ManifestExpectation("absent")
    digest = str(payload.get("byte_sha256") or "")
    mode_text = str(payload.get("mode") or "")
    device = payload.get("device")
    inode = payload.get("inode")
    if (
        kind != "regular"
        or not isinstance(device, int)
        or device < 0
        or not isinstance(inode, int)
        or inode <= 0
        or not re.fullmatch(r"0[0-7]{3}", mode_text)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        die("expected manifest state is invalid")
    return ManifestExpectation("regular", device, inode, int(mode_text, 8), digest)


def _snapshot_matches_expectation(current: ManifestSnapshot | None, expected: ManifestExpectation) -> bool:
    if expected.kind == "absent":
        return current is None
    if current is None:
        return False
    return bool(
        current.device == expected.device
        and current.inode == expected.inode
        and stat.S_IMODE(current.mode) == expected.mode
        and hmac.compare_digest(hashlib.sha256(current.content).hexdigest(), expected.byte_sha256)
    )


def _validate_planned_snapshot(
    current: ManifestSnapshot | None,
    planned: ManifestExpectation | object,
) -> ManifestSnapshot | ManifestExpectation | None:
    if planned is _EXPECTED_MANIFEST_UNSET:
        return current
    assert isinstance(planned, ManifestExpectation)
    if not _snapshot_matches_expectation(current, planned):
        die("install manifest changed after Agent plan verification; replan before writing")
    return planned


def _validate_expected_manifest_at(
    root_fd: int,
    expected: ManifestSnapshot | ManifestExpectation | None,
) -> None:
    current = _manifest_snapshot_at(root_fd, required=False)
    if isinstance(expected, ManifestExpectation):
        if not _snapshot_matches_expectation(current, expected):
            die("install manifest changed after planning; replan before writing")
        return
    if expected is None:
        if current is not None:
            die("install manifest changed after planning; replan before writing")
        return
    if current is None:
        die("install manifest changed after planning; replan before writing")
    same_identity = (
        current.device == expected.device
        and current.inode == expected.inode
        and stat.S_IMODE(current.mode) == stat.S_IMODE(expected.mode)
    )
    same_digest = hmac.compare_digest(hashlib.sha256(current.content).digest(), hashlib.sha256(expected.content).digest())
    if not same_identity or not same_digest:
        die("install manifest changed after planning; replan before writing")


def path_for_rel(dst_root: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        die(f"manifest contains unsafe path: {rel}")
    if rel in {"AGENTS.md", "CLAUDE.md", CLAUDE_SKILLS_REL}:
        return dst_root / rel_path
    if rel_path.parts[:1] != (".agents",):
        die(f"manifest path is outside managed set: {rel}")
    return dst_root / rel_path


def agents_root(dst_root: Path) -> Path:
    return dst_root / ".agents"


def manifest_path(dst_root: Path) -> Path:
    return dst_root / MANIFEST_REL


def is_under_agents(path: Path, dst_root: Path) -> bool:
    agents = agents_root(dst_root).resolve(strict=False)
    try:
        candidate = path.resolve(strict=False)
    except OSError:
        candidate = path.absolute()
    return candidate == agents or agents in candidate.parents


def assert_write_target(path: Path, dst_root: Path) -> None:
    if path in {dst_root / "AGENTS.md", dst_root / "CLAUDE.md", dst_root / CLAUDE_SKILLS_REL}:
        return
    if not is_under_agents(path, dst_root):
        die(f"refusing to write outside .agents: {path}")
    if not is_under_agents(path.parent, dst_root):
        die(f"refusing to write outside .agents: {path}")


def assert_delete_target(path: Path, dst_root: Path) -> None:
    if path.name == MANIFEST_NAME:
        die(f"refusing to delete manifest through file set: {path}")
    if path in {dst_root / "CLAUDE.md", dst_root / CLAUDE_SKILLS_REL}:
        return
    if not is_under_agents(path, dst_root):
        die(f"refusing to delete outside .agents: {path}")


def assert_no_symlinked_agent_subdirs(dst_root: Path) -> None:
    root = agents_root(dst_root)
    for current_root, dirs, _files in os.walk(root, followlinks=False):
        root_path = Path(current_root)
        for name in dirs:
            directory = root_path / name
            if directory.is_symlink():
                die(f"managed .agents contains a symlinked subdirectory: {directory}; refuse to sync")


def tree_checksum(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[rel].encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def current_files_from_items(items: dict[str, tuple[Path, str]]) -> dict[str, str]:
    return {rel: digest for rel, (_path, digest) in sorted(items.items())}


def managed_agents_block(source: Path) -> bytes:
    body = source.read_text(encoding="utf-8").rstrip("\n")
    rendered = (
        f"{BEGIN_MARKER}\n"
        "<!-- Managed by workspace-oss. Content outside this block is user-owned. -->\n"
        f"{body}\n"
        f"{END_MARKER}\n"
    )
    return rendered.encode("utf-8")


def managed_agents_separator(existing: bytes | None) -> bytes:
    if not existing:
        return b""
    return b"\n" if existing.endswith(b"\n") else b"\n\n"


def agents_md_roundtrip_metadata(existing: bytes | None, separator: bytes) -> dict[str, Any]:
    before = existing if existing is not None else b""
    return {
        "schema": 1,
        "before_existed": existing is not None,
        "before_size": len(before),
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "separator_hex": separator.hex(),
    }


def managed_block_span(content: bytes) -> tuple[int, int] | None:
    text = content.decode("utf-8")
    lines = text.splitlines(keepends=True)
    begin_indexes = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN_MARKER]
    end_indexes = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END_MARKER]
    if not begin_indexes and not end_indexes:
        return None
    if len(begin_indexes) != 1 or len(end_indexes) != 1 or begin_indexes[0] >= end_indexes[0]:
        die("AGENTS.md has malformed workspace-oss managed block markers")
    start = sum(len(line.encode("utf-8")) for line in lines[: begin_indexes[0]])
    end = sum(len(line.encode("utf-8")) for line in lines[: end_indexes[0] + 1])
    return start, end


def extract_managed_block(content: bytes) -> bytes | None:
    span = managed_block_span(content)
    if span is None:
        return None
    return content[span[0] : span[1]]


def merge_managed_agents(existing: bytes | None, block: bytes, *, legacy_digest: str = "") -> bytes:
    if existing is None:
        return block
    if legacy_digest and hashlib.sha256(existing).hexdigest() == legacy_digest:
        return block
    span = managed_block_span(existing)
    if span is not None:
        return existing[: span[0]] + block + existing[span[1] :]
    separator = managed_agents_separator(existing)
    return existing + separator + block


def _restore_agents_md_roundtrip(
    existing: bytes,
    span: tuple[int, int],
    metadata: object,
) -> object:
    if not isinstance(metadata, dict) or set(metadata) != {
        "schema",
        "before_existed",
        "before_size",
        "before_sha256",
        "separator_hex",
    }:
        return NotImplemented
    before_existed = metadata.get("before_existed")
    before_size = metadata.get("before_size")
    before_sha256 = metadata.get("before_sha256")
    separator_hex = metadata.get("separator_hex")
    if (
        metadata.get("schema") != 1
        or not isinstance(before_existed, bool)
        or not isinstance(before_size, int)
        or isinstance(before_size, bool)
        or before_size < 0
        or not isinstance(before_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", before_sha256) is None
        or not isinstance(separator_hex, str)
        or separator_hex not in {"", "0a", "0a0a"}
    ):
        return NotImplemented
    separator = bytes.fromhex(separator_hex)
    start, end = span
    if start != before_size + len(separator):
        return NotImplemented
    prefix = existing[:before_size]
    if (
        existing[before_size:start] != separator
        or hashlib.sha256(prefix).hexdigest() != before_sha256
    ):
        return NotImplemented
    suffix = existing[end:]
    restored = prefix + suffix
    if before_existed or restored:
        return restored
    return None


def remove_managed_agents(existing: bytes, manifest: dict[str, Any]) -> bytes | None:
    try:
        span = managed_block_span(existing)
    except (SyncError, UnicodeDecodeError):
        warn("preserving AGENTS.md during uninstall: managed block cannot be verified")
        return existing
    if span is not None:
        expected = str(manifest.get("agents_md_sha") or "")
        actual = hashlib.sha256(existing[span[0] : span[1]]).hexdigest()
        if not expected or actual != expected:
            warn(
                "preserving AGENTS.md during uninstall: managed block drift "
                f"expected={expected or '<missing>'} actual={actual}"
            )
            return existing
        if "agents_md_roundtrip" in manifest:
            restored = _restore_agents_md_roundtrip(
                existing,
                span,
                manifest.get("agents_md_roundtrip"),
            )
            if restored is not NotImplemented:
                return restored
            warn(
                "preserving AGENTS.md separator because managed-block round-trip metadata "
                "is invalid or no longer matches"
            )
        remaining = existing[: span[0]] + existing[span[1] :]
        return remaining if remaining.strip() else None
    if manifest.get("agents_md") == "managed":
        expected = str(manifest.get("agents_md_sha") or manifest.get("files", {}).get("AGENTS.md") or "")
        if expected and hashlib.sha256(existing).hexdigest() == expected:
            return None
        warn("preserving AGENTS.md during uninstall: managed content drift")
    elif manifest.get("agents_md") == "managed-block":
        warn("preserving AGENTS.md during uninstall: managed block is missing")
    return existing


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _symlink_points_to_path(link: Path, destination: Path) -> bool:
    if not link.is_symlink():
        return False
    target = Path(os.readlink(link))
    candidate = target if target.is_absolute() else link.parent / target
    return Path(os.path.abspath(os.fspath(candidate))) == Path(os.path.abspath(os.fspath(destination)))


def project_claude_changes(
    dst_root: Path,
    *,
    enabled: bool,
    uninstalling: bool,
    source_skills: Path,
) -> tuple[
    dict[str, tuple[bytes, int]],
    list[str],
    dict[str, str],
    dict[str, set[str]],
    dict[str, str],
    dict[str, str],
]:
    """Plan project Claude integration for the lifecycle transaction."""

    writes: dict[str, tuple[bytes, int]] = {}
    removals: list[str] = []
    symlink_writes: dict[str, str] = {}
    symlink_removals: dict[str, set[str]] = {}
    write_operations: dict[str, str] = {}
    removal_operations: dict[str, str] = {}
    if not enabled:
        return writes, removals, symlink_writes, symlink_removals, write_operations, removal_operations

    claude_dir = dst_root / ".claude"
    try:
        claude_mode = claude_dir.lstat().st_mode
    except FileNotFoundError:
        claude_mode = 0
    except OSError as exc:
        die(f"project Claude directory cannot be verified: {exc}")
    if claude_mode and (stat.S_ISLNK(claude_mode) or not stat.S_ISDIR(claude_mode)):
        die("project Claude directory is not a real directory")

    skills = dst_root / CLAUDE_SKILLS_REL
    if uninstalling:
        if skills.is_symlink():
            actual = os.readlink(skills)
            accepted = {CLAUDE_SKILLS_TARGET, str(source_skills)}
            if actual in accepted:
                symlink_removals[CLAUDE_SKILLS_REL] = accepted
                removal_operations[CLAUDE_SKILLS_REL] = "remove-symlink"
            else:
                warn("preserving project Claude skills link: target differs from the managed link")
        elif _lexists(skills):
            warn("preserving project Claude skills path: it is not a managed symlink")
    elif not _lexists(skills):
        symlink_writes[CLAUDE_SKILLS_REL] = CLAUDE_SKILLS_TARGET
        write_operations[CLAUDE_SKILLS_REL] = "symlink"
    elif skills.is_symlink() and os.readlink(skills) == CLAUDE_SKILLS_TARGET:
        pass
    elif skills.is_symlink():
        warn("preserving project Claude skills link: target differs from the managed link")
    else:
        warn("preserving project Claude skills path: it is not a managed symlink")

    claude_file = dst_root / "CLAUDE.md"
    if claude_file.is_symlink():
        if not _symlink_points_to_path(claude_file, dst_root / "AGENTS.md"):
            die("project CLAUDE.md is an unrelated symlink")
        return writes, removals, symlink_writes, symlink_removals, write_operations, removal_operations
    if _lexists(claude_file) and not claude_file.is_file():
        die("project CLAUDE.md is not a regular file")

    if uninstalling:
        if claude_file.is_file():
            existing = read_bytes(claude_file)
            span = managed_block_span(existing)
            if span is not None:
                remaining = existing[: span[0]] + existing[span[1] :]
                if remaining.strip():
                    writes["CLAUDE.md"] = (remaining, path_mode(claude_file))
                    write_operations["CLAUDE.md"] = "remove-managed-block"
                else:
                    removals.append("CLAUDE.md")
                removal_operations["CLAUDE.md"] = "remove-managed-block"
    else:
        existing = read_bytes(claude_file) if claude_file.is_file() else None
        rendered = merge_managed_agents(existing, CLAUDE_INCLUDE_BLOCK)
        if existing != rendered:
            writes["CLAUDE.md"] = (rendered, path_mode(claude_file))
            write_operations["CLAUDE.md"] = "write-managed-block"

    return writes, removals, symlink_writes, symlink_removals, write_operations, removal_operations


def managed_uninstall_components(path: Path, dst_root: Path) -> list[Path]:
    root = agents_root(dst_root)
    try:
        relative = path.relative_to(root)
    except ValueError:
        die(f"refusing to inspect uninstall path outside .agents: {path}")
    return [
        root,
        *(root / Path(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1)),
    ]


def inspect_managed_uninstall_path(path: Path, dst_root: Path) -> tuple[str, str]:
    """Inspect a manifest file without traversing symlinked path components."""

    components = managed_uninstall_components(path, dst_root)
    for index, component in enumerate(components):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            return ("missing", "<missing>")
        except OSError as exc:
            return ("unreadable", f"<{type(exc).__name__}>")
        if stat.S_ISLNK(mode):
            return ("symlink", f"<symlink:{component.relative_to(dst_root)}>")
        is_leaf = index == len(components) - 1
        if not is_leaf and not stat.S_ISDIR(mode):
            return ("type-change", f"<not-a-directory:{component.relative_to(dst_root)}>")
        if is_leaf:
            if not stat.S_ISREG(mode):
                return ("type-change", "<not-a-regular-file>")
            try:
                return ("regular", sha256_file(component))
            except OSError as exc:
                return ("unreadable", f"<{type(exc).__name__}>")
    return ("missing", "<missing>")


def inspect_managed_uninstall_directory(path: Path, dst_root: Path) -> tuple[str, str]:
    """Inspect a managed directory without traversing symlinked path components."""

    for component in managed_uninstall_components(path, dst_root):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            return ("missing", "<missing>")
        except OSError as exc:
            return ("unreadable", f"<{type(exc).__name__}>")
        if stat.S_ISLNK(mode):
            return ("symlink", f"<symlink:{component.relative_to(dst_root)}>")
        if not stat.S_ISDIR(mode):
            return ("type-change", f"<not-a-directory:{component.relative_to(dst_root)}>")
    return ("directory", "<directory>")


def assert_uninstall_manifest_boundary(dst_root: Path) -> None:
    """Fail closed before reading an uninstall manifest through changed path types."""

    root = agents_root(dst_root)
    manifest = manifest_path(dst_root)
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        die(f"managed .agents root not found during uninstall: {root}")
    except OSError as exc:
        die(f"managed .agents root cannot be verified during uninstall: {root}: {exc}")
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        die(f"managed .agents root is not a real directory; refusing uninstall: {root}")

    try:
        manifest_mode = manifest.lstat().st_mode
    except FileNotFoundError:
        die(f"manifest not found: {manifest}")
    except OSError as exc:
        die(f"manifest cannot be verified during uninstall: {manifest}: {exc}")
    if stat.S_ISLNK(manifest_mode) or not stat.S_ISREG(manifest_mode):
        die(f"manifest is not a regular file; refusing uninstall: {manifest}")


def is_standard_cpython_cache(source_path: Path, cache_name: str) -> bool:
    """Match standard CPython cache names for this source across interpreter ABIs."""

    pattern = rf"{re.escape(source_path.stem)}\.cpython-[0-9]+(?:\.opt-[12])?\.pyc"
    return re.fullmatch(pattern, cache_name) is not None


def managed_bytecode_cache_sources(files: dict[str, str], dst_root: Path) -> dict[Path, list[Path]]:
    cache_sources: dict[Path, list[Path]] = {}
    for rel in files:
        if not rel.startswith(".agents/") or not rel.endswith(".py"):
            continue
        source_path = path_for_rel(dst_root, rel)
        cache_sources.setdefault(source_path.parent / "__pycache__", []).append(source_path)
    return cache_sources


def preserve_changed_bytecode_cache_types(files: dict[str, str], dst_root: Path, preserve: set[Path]) -> None:
    """Protect matching cache paths whose type changed before any directory pruning."""

    for cache_dir, sources in managed_bytecode_cache_sources(files, dst_root).items():
        state, _detail = inspect_managed_uninstall_directory(cache_dir, dst_root)
        if state != "directory":
            continue
        try:
            entries = list(cache_dir.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not any(is_standard_cpython_cache(source, entry.name) for source in sources):
                continue
            try:
                mode = entry.lstat().st_mode
            except OSError:
                continue
            if not stat.S_ISREG(mode):
                preserve.add(entry)


def remove_managed_bytecode_caches(
    files: dict[str, str],
    dst_root: Path,
    *,
    dry_run: bool,
    preserve: set[Path] | None = None,
    planned_removals: set[Path] | None = None,
) -> bool:
    """Remove only bytecode caches attributable to manifest-owned Python modules."""

    cache_sources = managed_bytecode_cache_sources(files, dst_root)

    removed_any = False
    for cache_dir, sources in sorted(cache_sources.items(), key=lambda item: str(item[0])):
        state, detail = inspect_managed_uninstall_directory(cache_dir, dst_root)
        if state == "missing":
            continue
        if state != "directory":
            warn(
                "preserving managed runtime cache during uninstall: "
                f"{cache_dir.relative_to(dst_root)} reason={state} actual={detail}"
            )
            continue
        try:
            entries = list(cache_dir.iterdir())
        except OSError as exc:
            warn(
                "preserving managed runtime cache during uninstall: "
                f"{cache_dir.relative_to(dst_root)} reason=unreadable actual=<{type(exc).__name__}>"
            )
            continue
        for entry in entries:
            if not any(is_standard_cpython_cache(source, entry.name) for source in sources):
                continue
            try:
                mode = entry.lstat().st_mode
            except OSError as exc:
                warn(
                    "preserving managed runtime cache during uninstall: "
                    f"{entry.relative_to(dst_root)} reason=unreadable actual=<{type(exc).__name__}>"
                )
                continue
            if not stat.S_ISREG(mode):
                warn(
                    "preserving managed runtime cache during uninstall: "
                    f"{entry.relative_to(dst_root)} reason=type-change"
                )
                if preserve is not None:
                    preserve.add(entry)
                continue
            if planned_removals is not None:
                planned_removals.add(entry)
            removed_any = remove_file(entry, dst_root, dry_run=dry_run) or removed_any
    return removed_any


def managed_bytecode_cache_removals(
    files: dict[str, str],
    dst_root: Path,
    preserve: set[Path],
) -> list[str]:
    """Collect safe cache-file removals for the main uninstall transaction."""

    removals: list[str] = []
    for cache_dir, sources in sorted(managed_bytecode_cache_sources(files, dst_root).items(), key=lambda item: str(item[0])):
        state, detail = inspect_managed_uninstall_directory(cache_dir, dst_root)
        if state == "missing":
            continue
        if state != "directory":
            warn(
                "preserving managed runtime cache during uninstall: "
                f"{cache_dir.relative_to(dst_root)} reason={state} actual={detail}"
            )
            continue
        try:
            entries = list(cache_dir.iterdir())
        except OSError as exc:
            warn(
                "preserving managed runtime cache during uninstall: "
                f"{cache_dir.relative_to(dst_root)} reason=unreadable actual=<{type(exc).__name__}>"
            )
            continue
        for entry in entries:
            if not any(is_standard_cpython_cache(source, entry.name) for source in sources):
                continue
            try:
                mode = entry.lstat().st_mode
            except OSError as exc:
                warn(
                    "preserving managed runtime cache during uninstall: "
                    f"{entry.relative_to(dst_root)} reason=unreadable actual=<{type(exc).__name__}>"
                )
                continue
            if not stat.S_ISREG(mode):
                warn(
                    "preserving managed runtime cache during uninstall: "
                    f"{entry.relative_to(dst_root)} reason=type-change"
                )
                preserve.add(entry)
                continue
            removals.append(entry.relative_to(dst_root).as_posix())
    return removals


def planned_empty_directories_after_removals(dst_root: Path, removals: set[Path]) -> list[Path]:
    """Return the exact directory prune set without mutating the target tree."""

    root = agents_root(dst_root)
    if not root.is_dir() or root.is_symlink():
        return []
    directories = sorted(
        [root, *(path for path in root.rglob("*") if path.is_dir() and not path.is_symlink())],
        key=lambda path: (len(path.parts), path.as_posix()),
        reverse=True,
    )
    removable_dirs: set[Path] = set()
    for directory in directories:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        if all(entry in removals or entry in removable_dirs for entry in entries):
            removable_dirs.add(directory)
    return sorted(removable_dirs, key=lambda path: (len(path.parts), path.as_posix()), reverse=True)


def path_mode(path: Path, default: int = 0o644) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return default


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), _directory_open_flags())
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _restore_backup(backup: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = backup.with_name(f".{backup.name}.restore-{os.urandom(6).hex()}")
    try:
        shutil.copy2(backup, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _restore_symlink(target: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore-{os.urandom(6).hex()}")
    try:
        os.symlink(target, temporary)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def transactional_apply(
    dst_root: Path,
    writes: dict[str, tuple[bytes, int]],
    removals: list[str],
    manifest: dict[str, Any] | None,
    *,
    dry_run: bool,
    preserve: set[Path] | None = None,
    delete_manifest: bool = False,
    expected_manifest: ManifestSnapshot | ManifestExpectation | None | object = _EXPECTED_MANIFEST_UNSET,
    symlink_writes: dict[str, str] | None = None,
    symlink_removals: dict[str, set[str]] | None = None,
    write_operations: dict[str, str] | None = None,
    removal_operations: dict[str, str] | None = None,
    remove_agents_root: bool = False,
    project_claude: tuple[bool, bool, Path] | None = None,
    _lease_root_fd: int | None = None,
    _root_preexisting: bool | None = None,
) -> bool:
    if manifest is not None and delete_manifest:
        die("transaction cannot both replace and delete the install manifest")
    writes = dict(writes)
    removals = list(removals)
    links_to_write = dict(symlink_writes or {})
    links_to_remove = {rel: set(targets) for rel, targets in (symlink_removals or {}).items()}
    write_kinds = dict(write_operations or {})
    removal_kinds = dict(removal_operations or {})
    root = agents_root(dst_root)
    if not dry_run and _lease_root_fd is None:
        with workspace_lease(dst_root) as lease_root_fd:
            try:
                root_mode = root.lstat().st_mode
                root_preexisting = True
            except FileNotFoundError:
                root_preexisting = False
                root_mode = 0
            if root_preexisting and (stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode)):
                die("managed .agents root is not a real directory")
            try:
                root.mkdir(parents=True, exist_ok=True)
                if not root_preexisting:
                    os.fsync(lease_root_fd)
                return transactional_apply(
                    dst_root,
                    writes,
                    removals,
                    manifest,
                    dry_run=False,
                    preserve=preserve,
                    delete_manifest=delete_manifest,
                    expected_manifest=expected_manifest,
                    symlink_writes=links_to_write,
                    symlink_removals=links_to_remove,
                    write_operations=write_kinds,
                    removal_operations=removal_kinds,
                    remove_agents_root=remove_agents_root,
                    project_claude=project_claude,
                    _lease_root_fd=lease_root_fd,
                    _root_preexisting=root_preexisting,
                )
            except BaseException:
                if not root_preexisting and root.is_dir():
                    try:
                        root.rmdir()
                        os.fsync(lease_root_fd)
                    except OSError:
                        pass
                raise

    if not dry_run and expected_manifest is not _EXPECTED_MANIFEST_UNSET:
        assert expected_manifest is None or isinstance(expected_manifest, (ManifestSnapshot, ManifestExpectation))
        assert _lease_root_fd is not None
        _validate_expected_manifest_at(_lease_root_fd, expected_manifest)

    if project_claude is not None:
        enabled, uninstalling, source_skills = project_claude
        (
            claude_writes,
            claude_removals,
            claude_link_writes,
            claude_link_removals,
            claude_write_operations,
            claude_removal_operations,
        ) = project_claude_changes(
            dst_root,
            enabled=enabled,
            uninstalling=uninstalling,
            source_skills=source_skills,
        )
        writes.update(claude_writes)
        removals.extend(claude_removals)
        links_to_write.update(claude_link_writes)
        links_to_remove.update(claude_link_removals)
        write_kinds.update(claude_write_operations)
        removal_kinds.update(claude_removal_operations)

    overlapping = (set(writes) & set(removals)) | (set(links_to_write) & set(links_to_remove))
    if overlapping or (set(writes) | set(removals)) & (set(links_to_write) | set(links_to_remove)):
        die("transaction contains overlapping managed targets")

    changed_writes: dict[str, tuple[bytes, int]] = {}
    for rel, (content, mode) in sorted(writes.items()):
        path = path_for_rel(dst_root, rel)
        assert_write_target(path, dst_root)
        if _lexists(path) and (path.is_symlink() or not path.is_file()):
            die(f"managed file target is not a regular file: {path}")
        if not path.exists() or read_bytes(path) != content or path_mode(path) != mode:
            changed_writes[rel] = (content, mode)

    changed_removals = []
    for rel in sorted(set(removals)):
        path = path_for_rel(dst_root, rel)
        if rel == "AGENTS.md":
            assert_write_target(path, dst_root)
        else:
            assert_delete_target(path, dst_root)
        if _lexists(path):
            if path.is_symlink() or not path.is_file():
                die(f"managed removal target is not a regular file: {path}")
            changed_removals.append(rel)

    changed_link_writes: dict[str, str] = {}
    for rel, target in sorted(links_to_write.items()):
        path = path_for_rel(dst_root, rel)
        assert_write_target(path, dst_root)
        if not _lexists(path):
            changed_link_writes[rel] = target
        elif not path.is_symlink() or os.readlink(path) != target:
            die(f"managed symlink target changed before commit: {path}")

    changed_link_removals: dict[str, str] = {}
    for rel, accepted in sorted(links_to_remove.items()):
        path = path_for_rel(dst_root, rel)
        assert_delete_target(path, dst_root)
        if not _lexists(path):
            continue
        if not path.is_symlink():
            die(f"managed symlink removal target changed type: {path}")
        actual = os.readlink(path)
        if actual not in accepted:
            die(f"managed symlink removal target changed before commit: {path}")
        changed_link_removals[rel] = actual

    manifest_changed = False
    manifest_deleted = False
    manifest_bytes = b""
    if manifest is not None:
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        target_manifest = manifest_path(dst_root)
        if _lexists(target_manifest) and (target_manifest.is_symlink() or not target_manifest.is_file()):
            die(f"manifest target is not a regular file: {target_manifest}")
        manifest_changed = not target_manifest.exists() or read_bytes(target_manifest) != manifest_bytes
    elif delete_manifest:
        target_manifest = manifest_path(dst_root)
        if _lexists(target_manifest):
            if target_manifest.is_symlink() or not target_manifest.is_file():
                die("manifest target is not a regular file")
            manifest_deleted = True

    if dry_run:
        write_targets = [path_for_rel(dst_root, rel) for rel in changed_writes]
        write_targets.extend(path_for_rel(dst_root, rel) for rel in changed_link_writes)
        if manifest_changed:
            write_targets.append(manifest_path(dst_root))
        missing_parents: set[Path] = set()
        for target in write_targets:
            parent = target.parent
            while parent != dst_root and dst_root in parent.parents:
                if not parent.exists():
                    missing_parents.add(parent)
                parent = parent.parent
        for directory in sorted(missing_parents, key=lambda path: (len(path.parts), path.as_posix())):
            dry_run_info("mkdir", directory)
        for rel, (content, _mode) in changed_writes.items():
            dry_run_info(write_kinds.get(rel, "write"), path_for_rel(dst_root, rel), content=content)
        for rel, target in changed_link_writes.items():
            dry_run_info(write_kinds.get(rel, "symlink"), path_for_rel(dst_root, rel), source=Path(target))
        for rel in changed_removals:
            dry_run_info(removal_kinds.get(rel, "delete"), path_for_rel(dst_root, rel))
        for rel in changed_link_removals:
            dry_run_info(removal_kinds.get(rel, "remove-symlink"), path_for_rel(dst_root, rel))
        if manifest_changed:
            dry_run_info("write-manifest", manifest_path(dst_root), content=manifest_bytes)
        if manifest_deleted:
            dry_run_info("delete", manifest_path(dst_root))
        planned_removals = {
            *(path_for_rel(dst_root, rel) for rel in changed_removals),
            *(path_for_rel(dst_root, rel) for rel in changed_link_removals),
        }
        if manifest_deleted:
            planned_removals.add(manifest_path(dst_root))
        if remove_agents_root:
            for directory in planned_empty_directories_after_removals(dst_root, planned_removals):
                dry_run_info("rmdir", directory)
        return bool(
            changed_writes
            or changed_removals
            or changed_link_writes
            or changed_link_removals
            or manifest_changed
            or manifest_deleted
        )

    if not (
        changed_writes
        or changed_removals
        or changed_link_writes
        or changed_link_removals
        or manifest_changed
        or manifest_deleted
    ):
        return False

    root_preexisting = bool(_root_preexisting)
    root_mode = stat.S_IMODE(root.lstat().st_mode)
    stage = Path(tempfile.mkdtemp(prefix=".workspace-oss-stage-", dir=dst_root))
    staged_files = stage / "files"
    staged_links = stage / "links"
    backups = stage / "backups"
    backups_by_path: dict[Path, tuple[str, Path | str | None]] = {}
    committed: list[Path] = []
    created_dirs: list[Path] = []
    agents_root_removed = False
    failed = False
    rollback_complete = True

    def ensure_destination_directory(directory: Path) -> None:
        try:
            relative = directory.relative_to(dst_root)
        except ValueError:
            die(f"transaction directory is outside workspace: {directory}")
        current = dst_root
        for component in relative.parts:
            child = current / component
            try:
                child_mode = child.lstat().st_mode
            except FileNotFoundError:
                child.mkdir()
                created_dirs.append(child)
                if current == dst_root:
                    assert _lease_root_fd is not None
                    os.fsync(_lease_root_fd)
                else:
                    _fsync_directory(current)
            else:
                if stat.S_ISLNK(child_mode) or not stat.S_ISDIR(child_mode):
                    die(f"transaction directory changed type before commit: {child}")
            current = child

    try:
        for rel, (content, mode) in changed_writes.items():
            staged = staged_files / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
            staged.chmod(mode)
            with staged.open("rb") as handle:
                os.fsync(handle.fileno())
            _fsync_directory(staged.parent)
            if hashlib.sha256(staged.read_bytes()).digest() != hashlib.sha256(content).digest():
                die(f"staged file validation failed: {rel}")
        for rel, target in changed_link_writes.items():
            staged = staged_links / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, staged)
            _fsync_directory(staged.parent)
        if manifest_changed:
            staged_manifest = staged_files / MANIFEST_REL
            staged_manifest.parent.mkdir(parents=True, exist_ok=True)
            staged_manifest.write_bytes(manifest_bytes)
            with staged_manifest.open("rb") as handle:
                os.fsync(handle.fileno())
            _fsync_directory(staged_manifest.parent)

        ordered_paths = [path_for_rel(dst_root, rel) for rel in changed_writes]
        ordered_paths.extend(path_for_rel(dst_root, rel) for rel in changed_removals)
        ordered_paths.extend(path_for_rel(dst_root, rel) for rel in changed_link_writes)
        ordered_paths.extend(path_for_rel(dst_root, rel) for rel in changed_link_removals)
        if manifest_changed or manifest_deleted:
            ordered_paths.append(manifest_path(dst_root))
        for index, path in enumerate(ordered_paths):
            backup: tuple[str, Path | str | None] = ("absent", None)
            if path.is_symlink():
                backup = ("symlink", os.readlink(path))
            elif path.exists():
                backup = backups / str(index)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
                with backup.open("rb") as handle:
                    os.fsync(handle.fileno())
                _fsync_directory(backup.parent)
                backup = ("regular", backup)
            backups_by_path[path] = backup

        for rel in changed_writes:
            destination = path_for_rel(dst_root, rel)
            ensure_destination_directory(destination.parent)
            os.replace(staged_files / rel, destination)
            committed.append(destination)
            _fsync_directory(destination.parent)
        for rel in changed_link_writes:
            destination = path_for_rel(dst_root, rel)
            ensure_destination_directory(destination.parent)
            os.replace(staged_links / rel, destination)
            committed.append(destination)
            _fsync_directory(destination.parent)
        for rel in changed_link_removals:
            destination = path_for_rel(dst_root, rel)
            destination.unlink()
            committed.append(destination)
            _fsync_directory(destination.parent)
        for rel in changed_removals:
            destination = path_for_rel(dst_root, rel)
            destination.unlink()
            committed.append(destination)
            _fsync_directory(destination.parent)
        if manifest_changed:
            target_manifest = manifest_path(dst_root)
            target_manifest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_files / MANIFEST_REL, target_manifest)
            committed.append(target_manifest)
            _fsync_directory(target_manifest.parent)
        elif manifest_deleted:
            target_manifest = manifest_path(dst_root)
            target_manifest.unlink()
            committed.append(target_manifest)
            _fsync_directory(target_manifest.parent)
        prune_empty_dirs(dst_root, dry_run=False, preserve=preserve)
        if remove_agents_root and root.is_dir():
            try:
                next(root.iterdir())
                warn(f".agents not empty after uninstall; preserving user files: {root}")
            except StopIteration:
                root.rmdir()
                agents_root_removed = True
                assert _lease_root_fd is not None
                os.fsync(_lease_root_fd)
    except BaseException:
        failed = True
        if agents_root_removed:
            try:
                root.mkdir(mode=root_mode)
                assert _lease_root_fd is not None
                os.fsync(_lease_root_fd)
            except OSError as rollback_exc:
                rollback_complete = False
                warn(f"rollback could not recreate {root}: {rollback_exc}")

        def restore_path(path: Path) -> None:
            kind, value = backups_by_path[path]
            if kind == "absent":
                if _lexists(path):
                    path.unlink()
                    _fsync_directory(path.parent)
            elif kind == "regular":
                assert isinstance(value, Path)
                _restore_backup(value, path)
            else:
                assert isinstance(value, str)
                _restore_symlink(value, path)

        manifest_target = manifest_path(dst_root)
        if manifest_target in committed:
            try:
                restore_path(manifest_target)
            except OSError as rollback_exc:
                rollback_complete = False
                warn(f"rollback could not restore {manifest_target}: {rollback_exc}")
        rollback_order = [path for path in reversed(committed) if path != manifest_target]
        for path in rollback_order:
            try:
                restore_path(path)
            except OSError as rollback_exc:
                rollback_complete = False
                warn(f"rollback could not restore {path}: {rollback_exc}")
        prune_empty_dirs(dst_root, dry_run=False, preserve=preserve)
        for directory in sorted(set(created_dirs), key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
                _fsync_directory(directory.parent)
            except OSError:
                pass
        raise
    finally:
        if not failed or rollback_complete:
            shutil.rmtree(stage, ignore_errors=True)
        else:
            warn("rollback was incomplete; recovery material was preserved")
        if failed and not root_preexisting and root.is_dir():
            try:
                root.rmdir()
            except OSError:
                pass
    return True


def write_file_if_needed(src: Path, dst: Path, dst_root: Path, *, dry_run: bool) -> bool:
    src_bytes = read_bytes(src)
    exists = dst.exists()
    same = exists and not dst.is_symlink() and dst.is_file() and read_bytes(dst) == src_bytes
    if same:
        return False
    assert_write_target(dst, dst_root)
    action = "overwrite" if exists else "copy"
    if dry_run:
        dry_run_info(action, dst, source=src, content=src_bytes)
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
    with tmp.open("wb") as handle:
        handle.write(src_bytes)
    shutil.copystat(src, tmp, follow_symlinks=True)
    os.replace(tmp, dst)
    return True


def remove_file(path: Path, dst_root: Path, *, dry_run: bool) -> bool:
    assert_delete_target(path, dst_root)
    if not path.exists() and not path.is_symlink():
        return False
    if dry_run:
        dry_run_info("delete", path)
        return True
    path.unlink()
    _fsync_directory(path.parent)
    return True


def prune_empty_dirs(dst_root: Path, *, dry_run: bool, preserve: set[Path] | None = None) -> None:
    root = agents_root(dst_root)
    if not root.is_dir():
        return
    preserved = preserve or set()
    dirs = sorted([p for p in root.rglob("*") if not p.is_symlink() and p.is_dir()], key=lambda p: len(p.parts), reverse=True)
    for directory in dirs:
        if directory == root:
            continue
        if any(directory == path or path in directory.parents for path in preserved):
            continue
        if not is_under_agents(directory, dst_root):
            continue
        try:
            next(directory.iterdir())
        except StopIteration:
            if dry_run:
                dry_run_info("rmdir", directory)
            else:
                directory.rmdir()
        except OSError:
            continue


def write_manifest(dst_root: Path, manifest: dict[str, Any], *, dry_run: bool) -> bool:
    path = manifest_path(dst_root)
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == rendered:
                return False
        except OSError:
            pass
    if dry_run:
        dry_run_info("write-manifest", path)
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(rendered, encoding="utf-8")
    os.replace(tmp, path)
    return True


def print_diff(*, old_commit: str, new_commit: str, added: list[str], changed: list[str], removed: list[str]) -> None:
    info(f"clean-sync: source {old_commit or '-'} -> {new_commit or '-'}")
    info(f"clean-sync: added={len(added)} changed={len(changed)} removed={len(removed)}")
    if added:
        info("clean-sync added:")
        for rel in added:
            info(f"  + {rel}")
    if changed:
        info("clean-sync changed:")
        for rel in changed:
            info(f"  * {rel}")
    if removed:
        info("clean-sync removed:")
        for rel in removed:
            info(f"  - {rel}")


def detect_drift(dst_root: Path, old_files: dict[str, str], new_files: dict[str, str]) -> list[tuple[str, str, str, str]]:
    drift: list[tuple[str, str, str, str]] = []
    for rel, expected_hash in sorted(old_files.items()):
        if rel == "AGENTS.md":
            continue
        path = path_for_rel(dst_root, rel)
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            drift.append((rel, expected_hash, "<symlink>", "managed-drift"))
            continue
        if not path.is_file():
            drift.append((rel, expected_hash, "<not-a-file>", "managed-drift"))
            continue
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            drift.append((rel, expected_hash, actual_hash, "managed-drift"))
    for rel in sorted(set(new_files) - set(old_files)):
        if rel == "AGENTS.md":
            continue
        new_hash = new_files[rel]
        path = path_for_rel(dst_root, rel)
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            drift.append((rel, new_hash, "<symlink>", "collides-with-local"))
            continue
        if not path.is_file():
            drift.append((rel, new_hash, "<not-a-file>", "collides-with-local"))
            continue
        actual_hash = sha256_file(path)
        if actual_hash != new_hash:
            drift.append((rel, new_hash, actual_hash, "collides-with-local"))
    return drift


def source_enumeration_looks_collapsed(
    repo: Path,
    source: Path | None,
    *,
    old_files: dict[str, str],
    new_files: dict[str, str],
    removed: list[str],
) -> bool:
    if not source_release_actual_nonempty(repo, source):
        return False
    old_agent_count = sum(1 for rel in old_files if rel.startswith(".agents/"))
    new_agent_count = sum(1 for rel in new_files if rel.startswith(".agents/"))
    if new_agent_count == 0:
        return True
    if old_agent_count == 0:
        return False
    return len(removed) / old_agent_count >= 0.9


def parse_agents(value: str) -> dict[str, bool]:
    if not value:
        return dict(DEFAULT_LEGACY_AGENTS)
    agents = {"claude": False, "codex": False}
    for raw_name in value.split(","):
        name = raw_name.strip()
        if not name:
            continue
        if name not in agents:
            die(f"unknown agent in --agents: {name}")
        agents[name] = True
    return agents


def normalize_manifest_agents(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return dict(DEFAULT_LEGACY_AGENTS)
    return {
        "claude": bool(value.get("claude", False)),
        "codex": bool(value.get("codex", False)),
    }


def agents_md_drift(dst_root: Path, manifest: dict[str, Any]) -> tuple[str, str, str, str] | None:
    path = dst_root / "AGENTS.md"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        return ("AGENTS.md", str(manifest.get("agents_md_sha") or ""), "<not-a-file>", "managed-drift")
    existing = read_bytes(path)
    if manifest.get("agents_md") == "managed-block":
        block = extract_managed_block(existing)
        expected = str(manifest.get("agents_md_sha") or "")
        if block is None:
            return ("AGENTS.md", expected, "<missing-block>", "managed-drift")
        actual = hashlib.sha256(block).hexdigest()
        if expected and actual != expected:
            return ("AGENTS.md", expected, actual, "managed-drift")
        return None
    expected = str(manifest.get("agents_md_sha") or manifest.get("files", {}).get("AGENTS.md") or "")
    actual = hashlib.sha256(existing).hexdigest()
    if expected and actual != expected:
        return ("AGENTS.md", expected, actual, "managed-drift")
    return None


def build_writes(
    dst_root: Path,
    items: dict[str, tuple[Path, str]],
    *,
    legacy_agents_digest: str = "",
    existing_roundtrip: object = None,
) -> tuple[dict[str, tuple[bytes, int]], str, dict[str, Any] | None]:
    writes: dict[str, tuple[bytes, int]] = {}
    for rel, (source, _digest) in items.items():
        if rel == "AGENTS.md":
            continue
        writes[rel] = (read_bytes(source), path_mode(source))
    agents_source = items["AGENTS.md"][0]
    block = managed_agents_block(agents_source)
    agents_path = dst_root / "AGENTS.md"
    existing = read_bytes(agents_path) if agents_path.exists() and agents_path.is_file() and not agents_path.is_symlink() else None
    roundtrip = existing_roundtrip if isinstance(existing_roundtrip, dict) else None
    if existing is None:
        roundtrip = agents_md_roundtrip_metadata(None, b"")
    elif legacy_agents_digest and hashlib.sha256(existing).hexdigest() == legacy_agents_digest:
        roundtrip = agents_md_roundtrip_metadata(None, b"")
    elif managed_block_span(existing) is None:
        roundtrip = agents_md_roundtrip_metadata(existing, managed_agents_separator(existing))
    writes["AGENTS.md"] = (
        merge_managed_agents(existing, block, legacy_digest=legacy_agents_digest),
        path_mode(agents_path),
    )
    return writes, hashlib.sha256(block).hexdigest(), roundtrip


def read_source_version(repo: Path, source: Path | None) -> str:
    """Read the bundle semver from the source's runtime/VERSION (empty if absent)."""
    version_file = (source or repo).resolve() / "runtime" / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_manifest(
    *,
    repo: Path,
    source_commit: str,
    source_origin: str,
    source_checkout: str,
    source_branch: str,
    source_strategy: str,
    version: str,
    installed_at: str,
    agents: dict[str, bool],
    files: dict[str, str],
    agents_md_sha: str,
    agents_md_roundtrip: dict[str, Any] | None,
    updated_at: str,
) -> dict[str, Any]:
    if source_strategy not in SOURCE_STRATEGIES:
        die(f"invalid source strategy: {source_strategy}")
    payload = {
        "schema": SCHEMA,
        "install_name": INSTALL_NAME,
        "install_mode": INSTALL_MODE,
        # source_repo remains as a compatibility alias for older updater builds;
        # source_origin/source_checkout are the R1 provenance contract.
        "source_repo": source_checkout,
        "source_origin": source_origin,
        "source_checkout": source_checkout,
        "source_branch": source_branch,
        "source_strategy": source_strategy,
        "source_commit": source_commit,
        "version": version,
        "installed_at": installed_at,
        "updated_at": updated_at,
        "agents": agents,
        "agents_md": "managed-block",
        "agents_md_sha": agents_md_sha,
        "files": files,
        "tree_checksum": tree_checksum(files),
    }
    if agents_md_roundtrip is not None:
        payload["agents_md_roundtrip"] = agents_md_roundtrip
    return payload


def preserved_source_strategy(
    manifest: dict[str, Any],
    *,
    requested: str | None,
    source_origin: str,
) -> str:
    if requested:
        return requested
    recorded = str(manifest.get("source_strategy") or "").strip()
    if recorded:
        if recorded not in SOURCE_STRATEGIES:
            die(f"manifest contains invalid source strategy: {recorded}")
        return recorded
    if source_origin and source_origin != "local":
        return REMOTE_BRANCH_STRATEGY
    return LOCAL_CHECKOUT_STRATEGY


def writes_need_change(dst_root: Path, writes: dict[str, tuple[bytes, int]], removals: list[str]) -> bool:
    for rel, (content, mode) in writes.items():
        path = path_for_rel(dst_root, rel)
        if not path.exists() or path.is_symlink() or not path.is_file():
            return True
        if read_bytes(path) != content or path_mode(path) != mode:
            return True
    return any(path_for_rel(dst_root, rel).exists() or path_for_rel(dst_root, rel).is_symlink() for rel in removals)


def install(args: argparse.Namespace) -> int:
    repo = resolve_dir(args.repo, "repo")
    dst_root = resolve_dir(args.dir, "dir")
    source = resolve_dir(args.source, "source") if args.source else None
    items = source_items(repo, source, allow_snapshot=args.allow_snapshot_source)
    files = current_files_from_items(items)
    agents = parse_agents(args.agents)
    installed_at = operation_timestamp(args.operation_time)
    existing_snapshot = load_manifest_snapshot(dst_root, required=False)
    expected_manifest = _validate_planned_snapshot(
        existing_snapshot,
        _manifest_expectation(args.expected_manifest_state),
    )
    emit_plan_manifest_expectation(existing_snapshot, dry_run=args.dry_run)
    existing_manifest = existing_snapshot.payload if existing_snapshot is not None else None
    if existing_manifest is not None:
        die("copy-project install already exists; use update or reinstall")
    if manifest_path(dst_root).exists():
        die(f"refusing to overwrite an unrecognized manifest: {manifest_path(dst_root)}")
    existing_agents = dst_root / "AGENTS.md"
    if existing_agents.exists() and existing_agents.is_file() and not existing_agents.is_symlink():
        try:
            existing_agents_bytes = read_bytes(existing_agents)
            if managed_block_span(existing_agents_bytes) is not None:
                die("existing AGENTS.md contains an unverified workspace-oss managed block")
        except UnicodeDecodeError:
            die("existing AGENTS.md is not valid UTF-8")
    assert_no_symlinked_agent_subdirs(dst_root)
    drift = detect_drift(dst_root, {}, files)
    if drift and not args.force:
        for rel, expected_hash, actual_hash, reason in drift:
            warn(f"  MODIFIED {rel} reason={reason} expected={expected_hash} actual={actual_hash}")
        die("copy-project install collides with local files; rerun with --force only if they may be replaced", code=3)
    writes, agents_md_sha, agents_md_roundtrip = build_writes(dst_root, items)
    install_origin = str(args.source_origin or "local").strip()
    install_checkout = str(args.source_checkout or "")
    install_strategy = preserved_source_strategy(
        {},
        requested=args.source_strategy,
        source_origin=install_origin,
    )
    manifest = build_manifest(
        repo=repo,
        source_commit=args.source_commit or "",
        source_origin=install_origin,
        source_checkout=install_checkout,
        source_branch=str(args.source_branch or "").strip(),
        source_strategy=install_strategy,
        version=read_source_version(repo, source),
        installed_at=installed_at,
        agents=agents,
        files=files,
        agents_md_sha=agents_md_sha,
        agents_md_roundtrip=agents_md_roundtrip,
        updated_at=installed_at,
    )
    changed = transactional_apply(
        dst_root,
        writes,
        [],
        manifest,
        dry_run=args.dry_run,
        expected_manifest=expected_manifest,
        project_claude=(bool(agents.get("claude")), False, repo / ".agents" / "skills"),
    )
    if changed:
        info(f"copy-project install complete: {dst_root}")
    else:
        info(f"copy-project install verified: {dst_root}")
    return 0


def update(args: argparse.Namespace) -> int:
    repo = resolve_dir(args.repo, "repo")
    dst_root = resolve_dir(args.dir, "dir")
    source = resolve_dir(args.source, "source") if args.source else None
    if not agents_root(dst_root).is_dir() or agents_root(dst_root).is_symlink():
        die(f"copy-project update requires a real .agents directory: {agents_root(dst_root)}")
    manifest_snapshot = load_manifest_snapshot(dst_root, required=True)
    assert manifest_snapshot is not None
    expected_manifest = _validate_planned_snapshot(
        manifest_snapshot,
        _manifest_expectation(args.expected_manifest_state),
    )
    emit_plan_manifest_expectation(manifest_snapshot, dry_run=args.dry_run)
    manifest = manifest_snapshot.payload
    assert_no_symlinked_agent_subdirs(dst_root)

    items = source_items(repo, source, allow_snapshot=args.allow_snapshot_source)
    new_files = current_files_from_items(items)
    old_files = dict(manifest["files"])
    old_commit = str(manifest.get("source_commit") or "")
    new_commit = args.source_commit or ""

    added = sorted(set(new_files) - set(old_files))
    changed_names = sorted(rel for rel in set(new_files) & set(old_files) if new_files[rel] != old_files[rel])
    removed = sorted(rel for rel in set(old_files) - set(new_files) if rel != "AGENTS.md" and rel.startswith(".agents/"))
    print_diff(old_commit=old_commit, new_commit=new_commit, added=added, changed=changed_names, removed=removed)
    collapsed = source_enumeration_looks_collapsed(repo, source, old_files=old_files, new_files=new_files, removed=removed)
    if collapsed and not args.force:
        die("source enumeration produced near-empty tree; refusing mass deletion; rerun with --force only if intentional")
    if collapsed and args.force:
        warn("source enumeration produced near-empty tree; continuing because --force was set")

    drift = detect_drift(dst_root, old_files, new_files)
    agents_drift = agents_md_drift(dst_root, manifest)
    if agents_drift is not None:
        drift.append(agents_drift)
    if drift and not args.force:
        warn("local modifications inside managed .agents block update")
        for rel, expected_hash, actual_hash, reason in drift:
            warn(f"  MODIFIED {rel} reason={reason} expected={expected_hash} actual={actual_hash}")
        die("copy-project update aborted; rerun with --force to overwrite managed drift", code=3)
    if drift and args.force:
        warn("local modifications inside managed .agents will be overwritten because --force was set")
        for rel, _expected_hash, actual_hash, reason in drift:
            warn(f"  MODIFIED {rel} reason={reason} actual={actual_hash}")

    legacy_agents_digest = ""
    if manifest.get("agents_md") != "managed-block":
        legacy_agents_digest = str(manifest.get("agents_md_sha") or old_files.get("AGENTS.md") or "")
    writes, agents_md_sha, agents_md_roundtrip = build_writes(
        dst_root,
        items,
        legacy_agents_digest=legacy_agents_digest,
        existing_roundtrip=manifest.get("agents_md_roundtrip"),
    )
    manifest_agents = normalize_manifest_agents(manifest.get("agents"))
    effective_origin = str(args.source_origin or manifest.get("source_origin") or "local").strip()
    effective_checkout = str(
        args.source_checkout or manifest.get("source_checkout") or manifest.get("source_repo") or ""
    )
    effective_branch = str(args.source_branch or manifest.get("source_branch") or "").strip()
    effective_strategy = preserved_source_strategy(
        manifest,
        requested=args.source_strategy,
        source_origin=effective_origin,
    )

    changed = (
        old_files != new_files
        or old_commit != new_commit
        or str(manifest.get("source_origin") or "") != effective_origin
        or str(manifest.get("source_checkout") or manifest.get("source_repo") or "")
        != effective_checkout
        or str(manifest.get("source_branch") or "") != effective_branch
        or str(manifest.get("source_strategy") or "") != effective_strategy
        or manifest.get("agents_md") != "managed-block"
        or writes_need_change(dst_root, writes, removed)
    )

    new_manifest: dict[str, Any] | None = None
    if changed:
        updated_at = operation_timestamp(args.operation_time)
        installed_at = str(manifest.get("installed_at") or utc_now())
        agents = manifest_agents
        new_manifest = build_manifest(
            repo=repo,
            source_commit=new_commit,
            source_origin=effective_origin,
            source_checkout=effective_checkout,
            source_branch=effective_branch,
            source_strategy=effective_strategy,
            version=read_source_version(repo, source),
            installed_at=installed_at,
            agents=agents,
            files=new_files,
            agents_md_sha=agents_md_sha,
            agents_md_roundtrip=agents_md_roundtrip,
            updated_at=updated_at,
        )
    transaction_changed = transactional_apply(
        dst_root,
        writes,
        removed,
        new_manifest,
        dry_run=args.dry_run,
        expected_manifest=expected_manifest,
        project_claude=(bool(manifest_agents.get("claude")), False, repo / ".agents" / "skills"),
    )
    if not changed and not transaction_changed:
        info("clean-sync: no changes; manifest unchanged")
    return 0


def reinstall(args: argparse.Namespace) -> int:
    repo = resolve_dir(args.repo, "repo")
    dst_root = resolve_dir(args.dir, "dir")
    source = resolve_dir(args.source, "source") if args.source else None
    manifest_snapshot = load_manifest_snapshot(dst_root, required=True)
    assert manifest_snapshot is not None
    expected_manifest = _validate_planned_snapshot(
        manifest_snapshot,
        _manifest_expectation(args.expected_manifest_state),
    )
    emit_plan_manifest_expectation(manifest_snapshot, dry_run=args.dry_run)
    manifest = manifest_snapshot.payload
    assert_no_symlinked_agent_subdirs(dst_root)
    items = source_items(repo, source, allow_snapshot=args.allow_snapshot_source)
    old_files = dict(manifest["files"])
    new_files = current_files_from_items(items)
    collisions = [entry for entry in detect_drift(dst_root, old_files, new_files) if entry[3] == "collides-with-local"]
    agents_drift = agents_md_drift(dst_root, manifest)
    blocked_drift = [*collisions, *([agents_drift] if agents_drift is not None else [])]
    if blocked_drift and not args.force:
        for rel, expected_hash, actual_hash, reason in blocked_drift:
            warn(f"  MODIFIED {rel} reason={reason} expected={expected_hash} actual={actual_hash}")
        die("copy-project reinstall collides with local files; rerun with --force only if they may be replaced", code=3)
    if blocked_drift and args.force:
        warn("local managed-block drift will be overwritten because --force was set")
    legacy_agents_digest = ""
    if manifest.get("agents_md") != "managed-block":
        legacy_agents_digest = str(manifest.get("agents_md_sha") or old_files.get("AGENTS.md") or "")
    writes, agents_md_sha, agents_md_roundtrip = build_writes(
        dst_root,
        items,
        legacy_agents_digest=legacy_agents_digest,
        existing_roundtrip=manifest.get("agents_md_roundtrip"),
    )
    manifest_agents = normalize_manifest_agents(manifest.get("agents"))
    removed = sorted(rel for rel in set(old_files) - set(new_files) if rel != "AGENTS.md" and rel.startswith(".agents/"))
    effective_origin = str(args.source_origin or manifest.get("source_origin") or "local").strip()
    effective_strategy = preserved_source_strategy(
        manifest,
        requested=args.source_strategy,
        source_origin=effective_origin,
    )
    operation_time = operation_timestamp(args.operation_time)
    new_manifest = build_manifest(
        repo=repo,
        source_commit=args.source_commit or "",
        source_origin=effective_origin,
        source_checkout=str(args.source_checkout or manifest.get("source_checkout") or manifest.get("source_repo") or ""),
        source_branch=str(args.source_branch or manifest.get("source_branch") or "").strip(),
        source_strategy=effective_strategy,
        version=read_source_version(repo, source),
        installed_at=operation_time,
        agents=manifest_agents,
        files=new_files,
        agents_md_sha=agents_md_sha,
        agents_md_roundtrip=agents_md_roundtrip,
        updated_at=operation_time,
    )
    transactional_apply(
        dst_root,
        writes,
        removed,
        new_manifest,
        dry_run=args.dry_run,
        expected_manifest=expected_manifest,
        project_claude=(bool(manifest_agents.get("claude")), False, repo / ".agents" / "skills"),
    )
    info(f"copy-project reinstall complete: {dst_root}")
    return 0


def _uninstall_locked(
    args: argparse.Namespace,
    dst_root: Path,
    manifest_snapshot: ManifestSnapshot,
    expected_manifest: ManifestSnapshot | ManifestExpectation,
    lease_root_fd: int,
) -> int:
    manifest = manifest_snapshot.payload
    files = dict(manifest["files"])
    preserved_paths: set[Path] = set()
    transaction_removals: list[str] = []
    transaction_writes: dict[str, tuple[bytes, int]] = {}
    planned_removals: set[Path] = set()
    for rel in sorted(files, reverse=True):
        if rel == "AGENTS.md":
            continue
        if not rel.startswith(".agents/"):
            continue
        path = path_for_rel(dst_root, rel)
        state, actual = inspect_managed_uninstall_path(path, dst_root)
        if state == "missing":
            continue
        expected = str(files[rel])
        if state != "regular" or actual != expected:
            reason = "content-drift" if state == "regular" else state
            warn(
                f"preserving managed path during uninstall: {rel} "
                f"reason={reason} expected={expected} actual={actual}"
            )
            preserved_paths.add(path)
            continue
        transaction_removals.append(rel)
        planned_removals.add(path)

    preserve_changed_bytecode_cache_types(files, dst_root, preserved_paths)
    transaction_removals.extend(managed_bytecode_cache_removals(files, dst_root, preserved_paths))

    agents_path = dst_root / "AGENTS.md"
    if agents_path.is_symlink():
        warn("preserving AGENTS.md during uninstall: path is a symlink")
    elif agents_path.exists() and not agents_path.is_file():
        warn("preserving AGENTS.md during uninstall: path is not a regular file")
    elif agents_path.exists():
        remaining = remove_managed_agents(read_bytes(agents_path), manifest)
        if remaining is None:
            transaction_removals.append("AGENTS.md")
            planned_removals.add(agents_path)
        elif remaining != read_bytes(agents_path):
            transaction_writes["AGENTS.md"] = (remaining, path_mode(agents_path))

    manifest_agents = normalize_manifest_agents(manifest.get("agents"))
    (
        claude_writes,
        claude_removals,
        claude_link_writes,
        claude_link_removals,
        claude_write_operations,
        claude_removal_operations,
    ) = project_claude_changes(
        dst_root,
        enabled=bool(manifest_agents.get("claude")),
        uninstalling=True,
        source_skills=Path(args.repo).expanduser().resolve() / ".agents" / "skills",
    )
    transaction_writes.update(claude_writes)
    transaction_removals.extend(claude_removals)

    removed_any = transactional_apply(
        dst_root,
        transaction_writes,
        transaction_removals,
        None,
        dry_run=args.dry_run,
        preserve=preserved_paths,
        delete_manifest=True,
        expected_manifest=expected_manifest,
        symlink_writes=claude_link_writes,
        symlink_removals=claude_link_removals,
        write_operations=claude_write_operations,
        removal_operations=claude_removal_operations,
        remove_agents_root=True,
        _lease_root_fd=lease_root_fd,
        _root_preexisting=True,
    )
    if removed_any:
        info(f"copy-project uninstall complete: {dst_root}")
    else:
        info(f"copy-project uninstall found no managed files: {dst_root}")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    _repo = resolve_dir(args.repo, "repo")
    dst_root = resolve_dir(args.dir, "dir")
    assert_uninstall_manifest_boundary(dst_root)
    with workspace_lease(dst_root) as lease_root_fd:
        manifest_snapshot = _manifest_snapshot_at(lease_root_fd, required=True)
        assert manifest_snapshot is not None
        expected_manifest = _validate_planned_snapshot(
            manifest_snapshot,
            _manifest_expectation(args.expected_manifest_state),
        )
        emit_plan_manifest_expectation(manifest_snapshot, dry_run=args.dry_run)
        assert isinstance(expected_manifest, (ManifestSnapshot, ManifestExpectation))
        return _uninstall_locked(args, dst_root, manifest_snapshot, expected_manifest, lease_root_fd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="workspace-oss copy-project sync helper")
    parser.add_argument("action", choices=("install", "update", "reinstall", "uninstall"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--source-origin", default="")
    parser.add_argument("--source-checkout", default="")
    parser.add_argument("--source-branch", default="")
    parser.add_argument("--source-strategy", choices=SOURCE_STRATEGIES, default=None)
    parser.add_argument("--operation-time", default="", help=argparse.SUPPRESS)
    parser.add_argument("--source", default="")
    parser.add_argument("--agents", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-snapshot-source",
        action="store_true",
        help="源码不是 git 仓库时，明确接受按确定性文件清单打包（快照模式无法区分未跟踪文件）",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-jsonl", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--expected-manifest-state", default="", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    global PLAN_JSONL
    parser = build_parser()
    args = parser.parse_args(argv)
    PLAN_JSONL = bool(args.plan_jsonl)
    try:
        if args.action == "install":
            return install(args)
        if args.action == "update":
            return update(args)
        if args.action == "reinstall":
            return reinstall(args)
        if args.action == "uninstall":
            return uninstall(args)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

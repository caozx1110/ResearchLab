from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

import fcntl


MANIFEST_REL = Path(".agents/.install-manifest.json")
CACHE_CHECKOUT_PREFIX = "ResearchLab"
LOCAL_ORIGIN = "local"
LOCAL_CHECKOUT_STRATEGY = "local-checkout"
REMOTE_BRANCH_STRATEGY = "remote-branch"
SOURCE_STRATEGIES = {LOCAL_CHECKOUT_STRATEGY, REMOTE_BRANCH_STRATEGY}
INSTALL_MANIFEST_SCHEMA = 1
INSTALL_NAME = "workspace-oss"
INSTALL_MODE = "copy-project"
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class SourceProvenance:
    origin: str
    checkout: Path | None
    branch: str
    strategy: str = ""

    @property
    def effective_strategy(self) -> str:
        if self.strategy:
            return self.strategy
        return LOCAL_CHECKOUT_STRATEGY if self.origin == LOCAL_ORIGIN else REMOTE_BRANCH_STRATEGY

    @property
    def is_local(self) -> bool:
        return self.effective_strategy == LOCAL_CHECKOUT_STRATEGY


@dataclass(frozen=True)
class InstallManifestSnapshot:
    payload: dict[str, Any]
    content: bytes
    device: int
    inode: int
    mode: int

    def expectation(self) -> dict[str, Any]:
        return {
            "type": "regular",
            "mode": f"{stat.S_IMODE(self.mode):04o}",
            "byte_sha256": _manifest_digest(self.content),
            "device": self.device,
            "inode": self.inode,
        }


class SourceChoiceRequired(RuntimeError):
    pass


class SourceRebindError(ValueError):
    """A stable private failure raised before an update-source rebind writes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _run_process(argv: Sequence[str], *, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=True,
        capture_output=capture_output,
        text=True,
    )


def _run_git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_process(("git", "-C", str(checkout), *args))


def _git_output(checkout: Path, *args: str) -> str:
    return _run_git(checkout, *args).stdout.strip()


def _checkout_origin(checkout: Path) -> str:
    try:
        return _git_output(checkout, "remote", "get-url", "origin")
    except (AttributeError, OSError, subprocess.SubprocessError):
        return ""


def _checkout_branch(checkout: Path) -> str:
    try:
        return _git_output(checkout, "symbolic-ref", "--quiet", "--short", "HEAD")
    except (AttributeError, OSError, subprocess.SubprocessError):
        return ""


def _valid_branch_name(branch: str) -> bool:
    text = str(branch or "").strip()
    return bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", text)
        and ".." not in text
        and "//" not in text
        and "@{" not in text
        and not text.endswith(("/", ".", ".lock"))
    )


def _pull_checkout(checkout: Path, *, branch: str) -> None:
    _run_git(checkout, "pull", "--ff-only", "origin", branch)


def _fetch_checkout(checkout: Path, *, branch: str) -> None:
    _run_git(checkout, "fetch", "--quiet", "origin", branch)


def _clone_checkout(origin: str, destination: Path, *, branch: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run_process(("git", "clone", "--depth", "1", "--branch", branch, "--", origin, str(destination)))


def _cached_checkout(cache_dir: Path, origin: str, branch: str) -> Path:
    digest = hashlib.sha256(f"{origin}\0{branch}".encode("utf-8")).hexdigest()[:12]
    return cache_dir.expanduser() / f"{CACHE_CHECKOUT_PREFIX}-{digest}"


def _validate_checkout_origin(checkout: Path, origin: str) -> None:
    actual = _checkout_origin(checkout)
    if not actual:
        raise RuntimeError("the recorded source checkout has no origin remote")
    if actual != origin:
        raise RuntimeError("the recorded source checkout no longer matches its manifest origin")


def _validate_checkout_branch(checkout: Path, branch: str) -> None:
    actual = _checkout_branch(checkout)
    if not actual:
        raise SourceChoiceRequired("记录的更新源处于 detached HEAD；需要重新选择更新分支。")
    if actual != branch:
        raise SourceChoiceRequired("记录的更新源已切换分支；需要重新选择更新分支。")


def _prepare_cached_checkout(cache_dir: Path, origin: str, *, pull: bool, branch: str) -> Path:
    if not origin or origin == LOCAL_ORIGIN:
        raise SourceChoiceRequired("本地更新源不可用；需要重新选择源码位置。")
    if not _valid_branch_name(branch):
        raise SourceChoiceRequired("安装记录缺少有效更新分支；需要重新选择更新源。")
    checkout = _cached_checkout(cache_dir, origin, branch)
    if is_git_checkout(checkout):
        _validate_checkout_origin(checkout, origin)
        _validate_checkout_branch(checkout, branch)
        if pull:
            _pull_checkout(checkout, branch=branch)
        else:
            _fetch_checkout(checkout, branch=branch)
        return checkout
    if checkout.exists():
        raise RuntimeError("update cache is not a git checkout")
    _clone_checkout(origin, checkout, branch=branch)
    return checkout


def _source_commit(checkout: Path) -> str:
    if not is_git_checkout(checkout):
        return "local"
    return _git_output(checkout, "rev-parse", "HEAD")


def _invoke_ws_sync(
    source_checkout: Path,
    install_root: Path,
    source_commit: str,
    provenance: SourceProvenance,
    expected_manifest_state: str,
) -> None:
    sync_script = source_checkout / "install-lib" / "ws_sync.py"
    if not sync_script.is_file():
        raise RuntimeError("the update source is missing its workspace sync helper")
    argv = [
        sys.executable or "python3",
        str(sync_script),
        "update",
        "--repo",
        str(source_checkout),
        "--dir",
        str(install_root),
        "--source-commit",
        source_commit,
        "--source-origin",
        provenance.origin,
        "--source-branch",
        provenance.branch,
        "--source-strategy",
        provenance.effective_strategy,
        "--expected-manifest-state",
        expected_manifest_state,
    ]
    if provenance.checkout is not None:
        argv.extend(["--source-checkout", str(provenance.checkout)])
    _run_process(argv)


def read_local_version(install_root: Path) -> str:
    version_path = Path(install_root) / ".agents" / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return version or "0.0.0"


def read_source_version(source_root: Path) -> str:
    version_path = Path(source_root) / "runtime" / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return version or "0.0.0"


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def parse_semver(value: str) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
    """Return a precedence key implementing SemVer 2.0 prerelease ordering."""
    match = SEMVER_PATTERN.fullmatch(str(value).strip())
    if match is None:
        return (0, 0, 0, 0, ())
    major, minor, patch = (int(match.group(index)) for index in range(1, 4))
    prerelease = match.group(4)
    if prerelease is None:
        return (major, minor, patch, 1, ())
    identifiers: list[tuple[int, int | str]] = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            # SemVer forbids leading zeroes in numeric prerelease identifiers.
            if len(identifier) > 1 and identifier.startswith("0"):
                return (0, 0, 0, 0, ())
            identifiers.append((0, int(identifier)))
        else:
            identifiers.append((1, identifier))
    return (major, minor, patch, 0, tuple(identifiers))


def compare_versions(local: str, remote: str) -> int:
    local_version = parse_semver(local)
    remote_version = parse_semver(remote)
    return (local_version > remote_version) - (local_version < remote_version)


def is_git_checkout(path: Path) -> bool:
    return (Path(path) / ".git").exists()


def is_source_checkout(path: Path) -> bool:
    candidate = Path(path)
    return (
        candidate.is_dir()
        and (candidate / "install-lib" / "ws_sync.py").is_file()
        and (candidate / "runtime" / "VERSION").is_file()
    )


def _manifest_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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
def _locked_manifest_directory(install_root: Path) -> Iterator[tuple[Path, int, int]]:
    """Lock the stable workspace root, then anchor ``.agents`` below it."""
    root = Path(install_root).expanduser().resolve(strict=False)
    root_fd = -1
    agents_fd = -1
    try:
        try:
            root_fd = os.open(str(root), _directory_open_flags())
            root_status = os.fstat(root_fd)
            if not stat.S_ISDIR(root_status.st_mode):
                raise SourceRebindError("unsafe-install-root", "the install root is not a regular directory")
            fcntl.flock(root_fd, fcntl.LOCK_EX)
            current_root = os.stat(str(root), follow_symlinks=False)
            if not _same_node(root_status, current_root):
                raise SourceRebindError("unsafe-install-root", "the install root changed before locking")
            agents_status = os.stat(".agents", dir_fd=root_fd, follow_symlinks=False)
            if not stat.S_ISDIR(agents_status.st_mode):
                raise SourceRebindError("unsafe-manifest-ancestor", "the manifest ancestor is not a directory")
            agents_fd = os.open(".agents", _directory_open_flags(), dir_fd=root_fd)
            if not _same_node(agents_status, os.fstat(agents_fd)):
                raise SourceRebindError("unsafe-manifest-ancestor", "the manifest ancestor changed during validation")
            current_agents = os.stat(".agents", dir_fd=root_fd, follow_symlinks=False)
            if not _same_node(current_agents, os.fstat(agents_fd)):
                raise SourceRebindError("unsafe-manifest-ancestor", "the manifest ancestor changed before locking")
        except SourceRebindError:
            raise
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            raise SourceRebindError("unsafe-manifest-path", "the install manifest path cannot be safely opened") from exc
        yield root, root_fd, agents_fd
    finally:
        if agents_fd >= 0:
            os.close(agents_fd)
        if root_fd >= 0:
            try:
                fcntl.flock(root_fd, fcntl.LOCK_UN)
            finally:
                os.close(root_fd)


def _assert_anchored_agents(root_fd: int, agents_fd: int) -> None:
    try:
        current = os.stat(".agents", dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        raise SourceRebindError("unsafe-manifest-ancestor", "the manifest ancestor is no longer available") from exc
    if not stat.S_ISDIR(current.st_mode) or not _same_node(current, os.fstat(agents_fd)):
        raise SourceRebindError("unsafe-manifest-ancestor", "the manifest ancestor changed during rebind")


def _read_manifest_at(
    agents_fd: int,
    *,
    required: bool = True,
) -> tuple[dict[str, Any], bytes, os.stat_result] | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        try:
            lexical_before = os.stat(MANIFEST_REL.name, dir_fd=agents_fd, follow_symlinks=False)
        except FileNotFoundError:
            if not required:
                return None
            raise
        if not stat.S_ISREG(lexical_before.st_mode):
            raise SourceRebindError("unsafe-manifest-leaf", "the install manifest is not a regular file")
        descriptor = os.open(MANIFEST_REL.name, flags, dir_fd=agents_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not _same_node(lexical_before, before):
            raise SourceRebindError("unsafe-manifest-leaf", "the install manifest is not a regular file")
        if before.st_size <= 0:
            raise SourceRebindError("invalid-manifest-size", "the install manifest is empty")
        if before.st_size > _MAX_MANIFEST_BYTES:
            raise SourceRebindError("manifest-too-large", "the install manifest is too large")
        chunks: list[bytes] = []
        total = 0
        while total < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - total))
            if not chunk:
                raise SourceRebindError("manifest-raced", "the install manifest changed while it was read")
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        lexical = os.stat(MANIFEST_REL.name, dir_fd=agents_fd, follow_symlinks=False)
        if (
            total != before.st_size
            or not stat.S_ISREG(lexical.st_mode)
            or not _same_read_identity(before, after)
            or not _same_read_identity(after, lexical)
        ):
            raise SourceRebindError("manifest-raced", "the install manifest changed while it was read")
        content = b"".join(chunks)
    except SourceRebindError:
        raise
    except (FileNotFoundError, OSError) as exc:
        raise SourceRebindError("unsafe-manifest-leaf", "the install manifest cannot be safely read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceRebindError("invalid-manifest-json", "the install manifest is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SourceRebindError("invalid-manifest-shape", "the install manifest is not an object")
    return payload, content, after


def _manifest_snapshot(install_root: Path, *, required: bool = True) -> InstallManifestSnapshot | None:
    with _locked_manifest_directory(install_root) as (_root, root_fd, agents_fd):
        _assert_anchored_agents(root_fd, agents_fd)
        result = _read_manifest_at(agents_fd, required=required)
        if result is None:
            return None
        payload, content, status = result
        return InstallManifestSnapshot(payload, content, status.st_dev, status.st_ino, status.st_mode)


def _snapshot_matches_current(install_root: Path, expected: InstallManifestSnapshot) -> bool:
    try:
        current = _manifest_snapshot(install_root)
    except SourceRebindError:
        return False
    assert current is not None
    return bool(
        current.device == expected.device
        and current.inode == expected.inode
        and stat.S_IMODE(current.mode) == stat.S_IMODE(expected.mode)
        and hmac.compare_digest(_manifest_digest(current.content), _manifest_digest(expected.content))
    )


def _manifest_expectation_json(snapshot: InstallManifestSnapshot) -> str:
    return json.dumps(snapshot.expectation(), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _validate_install_manifest(payload: dict[str, Any]) -> None:
    if (
        payload.get("schema") != INSTALL_MANIFEST_SCHEMA
        or payload.get("install_name") != INSTALL_NAME
        or payload.get("install_mode") != INSTALL_MODE
    ):
        raise SourceRebindError("unrecognized-manifest", "the manifest does not describe a copy install")
    files = payload.get("files")
    if not isinstance(files, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in files.items()):
        raise SourceRebindError("invalid-manifest-files", "the manifest files map is invalid")


def _valid_origin(origin: str) -> bool:
    return bool(
        origin
        and not origin.startswith("-")
        and len(origin) <= 4096
        and not any(ord(character) < 32 for character in origin)
    )


def _strict_source_checkout(path: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    helper = path / "install-lib" / "ws_sync.py"
    version = path / "runtime" / "VERSION"
    return helper.is_file() and not helper.is_symlink() and version.is_file() and not version.is_symlink()


def _write_manifest_at(
    root_fd: int,
    agents_fd: int,
    *,
    expected_content: bytes,
    replacement: bytes,
    mode: int,
    precommit_check: Callable[[], None] | None = None,
) -> None:
    """CAS and atomically replace the manifest through the anchored directory."""
    _assert_anchored_agents(root_fd, agents_fd)
    _payload, current, _status = _read_manifest_at(agents_fd)
    if not hmac.compare_digest(_manifest_digest(current), _manifest_digest(expected_content)):
        raise SourceRebindError("stale-manifest", "the install manifest changed before rebind")
    token = os.urandom(12).hex()
    temporary_name = f".{MANIFEST_REL.name}.{token}.tmp"
    rollback_name = f".{MANIFEST_REL.name}.{token}.rollback"
    restore_name = f".{MANIFEST_REL.name}.{token}.restore"
    descriptor = -1
    preserve_recovery = False

    def stage(name: str, content: bytes) -> os.stat_result:
        nonlocal descriptor
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            mode & 0o777,
            dir_fd=agents_fd,
        )
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short manifest write")
                view = view[written:]
            os.fchmod(descriptor, mode & 0o777)
            os.fsync(descriptor)
            return os.fstat(descriptor)
        finally:
            os.close(descriptor)
            descriptor = -1

    try:
        replacement_status = stage(temporary_name, replacement)
        stage(rollback_name, expected_content)
        # Make the rollback material durable before the operation can replace
        # the only committed copy of the old manifest.
        os.fsync(agents_fd)
        _assert_anchored_agents(root_fd, agents_fd)
        _payload, current, _status = _read_manifest_at(agents_fd)
        if not hmac.compare_digest(_manifest_digest(current), _manifest_digest(expected_content)):
            raise SourceRebindError("stale-manifest", "the install manifest changed before commit")
        if precommit_check is not None:
            precommit_check()
        os.replace(
            temporary_name,
            MANIFEST_REL.name,
            src_dir_fd=agents_fd,
            dst_dir_fd=agents_fd,
        )
        try:
            os.fsync(agents_fd)
        except OSError as commit_exc:
            preserve_recovery = True
            try:
                current_status = os.stat(MANIFEST_REL.name, dir_fd=agents_fd, follow_symlinks=False)
                if not stat.S_ISREG(current_status.st_mode) or not _same_node(current_status, replacement_status):
                    raise SourceRebindError(
                        "manifest-recovery-incomplete",
                        "the manifest commit failed and its target changed before recovery",
                    )
                os.link(
                    rollback_name,
                    restore_name,
                    src_dir_fd=agents_fd,
                    dst_dir_fd=agents_fd,
                    follow_symlinks=False,
                )
                os.replace(
                    restore_name,
                    MANIFEST_REL.name,
                    src_dir_fd=agents_fd,
                    dst_dir_fd=agents_fd,
                )
                os.fsync(agents_fd)
            except SourceRebindError:
                raise
            except OSError as recovery_exc:
                raise SourceRebindError(
                    "manifest-recovery-incomplete",
                    "the manifest commit failed and the previous manifest could not be durably restored",
                ) from recovery_exc
            preserve_recovery = False
            raise SourceRebindError(
                "manifest-commit-failed",
                "the manifest commit failed; the previous manifest was restored",
            ) from commit_exc
    except SourceRebindError:
        raise
    except OSError as exc:
        raise SourceRebindError("manifest-write-failed", "the install manifest could not be safely written") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for cleanup_name in (temporary_name, restore_name, rollback_name):
            if preserve_recovery and cleanup_name == rollback_name:
                continue
            try:
                os.unlink(cleanup_name, dir_fd=agents_fd)
            except FileNotFoundError:
                pass


def _load_manifest(install_root: Path) -> dict[str, Any] | None:
    try:
        snapshot = _manifest_snapshot(install_root, required=False)
    except SourceRebindError:
        return None
    return snapshot.payload if snapshot is not None else None


def source_choice_request(install_root: Path) -> dict[str, Any]:
    """Build a private, digest-bound Agent contract for one source choice."""
    with _locked_manifest_directory(install_root) as (_root, root_fd, agents_fd):
        _assert_anchored_agents(root_fd, agents_fd)
        manifest, content, _status = _read_manifest_at(agents_fd)
        _validate_install_manifest(manifest)

        recorded_origin = str(manifest.get("source_origin") or "").strip()
        recorded_branch = str(manifest.get("source_branch") or "").strip()
        recorded_strategy = str(manifest.get("source_strategy") or "").strip()
        checkout_text = str(manifest.get("source_checkout") or manifest.get("source_repo") or "").strip()
        checkout = Path(checkout_text).expanduser().resolve(strict=False) if checkout_text else None
        checkout_valid = checkout is not None and _strict_source_checkout(checkout)

        actual_origin = _checkout_origin(checkout) if checkout_valid and is_git_checkout(checkout) else ""
        actual_branch = _checkout_branch(checkout) if checkout_valid and is_git_checkout(checkout) else ""
        checkout_is_git = bool(checkout_valid and checkout is not None and is_git_checkout(checkout))
        origin = recorded_origin if _valid_origin(recorded_origin) else (
            actual_origin if _valid_origin(actual_origin) else ""
        )
        branch = recorded_branch if _valid_branch_name(recorded_branch) else (
            actual_branch if _valid_branch_name(actual_branch) else ""
        )
        local_checkout_reusable = bool(
            checkout_valid
            and (
                not checkout_is_git
                or (
                    _valid_branch_name(actual_branch)
                    and branch == actual_branch
                    and (
                        (actual_origin and origin == actual_origin)
                        or (not actual_origin and origin in {"", LOCAL_ORIGIN})
                    )
                )
            )
        )

        current: dict[str, str] = {}
        if origin:
            current["source_origin"] = origin
        if branch:
            current["source_branch"] = branch
        if recorded_strategy in SOURCE_STRATEGIES:
            current["source_strategy"] = recorded_strategy
        if checkout_valid:
            current["source_checkout"] = str(checkout)

        digest = _manifest_digest(content)
        base_apply: dict[str, Any] = {
            "verb": "update",
            "expected_manifest_digest": digest,
        }

        # A detached checkout with a validated non-local origin has one safe
        # non-mutating route: bind an explicit remote branch.  The checkout is
        # deliberately omitted from the apply contract.
        if origin and origin != LOCAL_ORIGIN and not branch:
            apply = {
                **base_apply,
                "source_origin": origin,
                "source_strategy": REMOTE_BRANCH_STRATEGY,
                "provide": ["source_branch"],
            }
            return {
                "fields": ["source_branch"],
                "current": current,
                "manifest_digest": digest,
                "apply": apply,
            }

        alternatives: list[dict[str, Any]] = []
        remote_fields: list[str] = []
        remote_template = {**base_apply, "source_strategy": REMOTE_BRANCH_STRATEGY}
        if origin and origin != LOCAL_ORIGIN:
            remote_template["source_origin"] = origin
        else:
            remote_fields.append("source_origin")
        if branch:
            remote_template["source_branch"] = branch
        else:
            remote_fields.append("source_branch")
        remote_template["provide"] = remote_fields
        alternatives.append(
            {
                "source_strategy": REMOTE_BRANCH_STRATEGY,
                "fields": remote_fields,
                "apply": remote_template,
            }
        )

        local_fields: list[str] = []
        local_template = {**base_apply, "source_strategy": LOCAL_CHECKOUT_STRATEGY}
        if local_checkout_reusable and checkout is not None:
            local_template["source_checkout"] = str(checkout)
            if origin:
                local_template["source_origin"] = origin
            if branch:
                local_template["source_branch"] = branch
        else:
            local_fields.append("source_checkout")
        local_template["provide"] = local_fields
        alternatives.append(
            {
                "source_strategy": LOCAL_CHECKOUT_STRATEGY,
                "fields": local_fields,
                "apply": local_template,
            }
        )
        return {
            "fields": ["source_strategy"],
            "current": current,
            "manifest_digest": digest,
            "alternatives": alternatives,
        }


def rebind_source(
    install_root: Path,
    *,
    expected_manifest_digest: str,
    source_origin: str = "",
    source_checkout: str = "",
    source_branch: str = "",
    source_strategy: str = "",
) -> dict[str, Any]:
    """CAS-rebind copy-install provenance without fetching or applying code."""
    expected = str(expected_manifest_digest or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise SourceRebindError("invalid-manifest-digest", "the expected manifest digest is invalid")
    strategy = str(source_strategy or "").strip()
    if strategy not in SOURCE_STRATEGIES:
        raise SourceRebindError("invalid-source-strategy", "the selected source strategy is invalid")

    with _locked_manifest_directory(install_root) as (_root, root_fd, agents_fd):
        _assert_anchored_agents(root_fd, agents_fd)
        manifest, content, status = _read_manifest_at(agents_fd)
        _validate_install_manifest(manifest)
        if not hmac.compare_digest(_manifest_digest(content), expected):
            raise SourceRebindError("stale-manifest", "the install manifest changed after source selection")

        origin = str(source_origin or "").strip()
        branch = str(source_branch or "").strip()
        checkout_value = ""
        commit = ""
        precommit_check: Callable[[], None] | None = None

        if strategy == REMOTE_BRANCH_STRATEGY:
            if not _valid_origin(origin) or origin == LOCAL_ORIGIN:
                raise SourceRebindError("invalid-source-origin", "remote-branch requires a non-local source origin")
            if not _valid_branch_name(branch):
                raise SourceRebindError("invalid-source-branch", "remote-branch requires a valid explicit branch")
        else:
            checkout_text = str(source_checkout or "").strip()
            if not checkout_text or any(ord(character) < 32 for character in checkout_text):
                raise SourceRebindError("invalid-source-checkout", "local-checkout requires a source checkout")
            checkout = Path(checkout_text).expanduser().resolve(strict=False)
            if not _strict_source_checkout(checkout):
                raise SourceRebindError("invalid-source-checkout", "the selected checkout is not a bundle source")
            checkout_value = str(checkout)
            git_checkout = is_git_checkout(checkout)
            actual_origin = _checkout_origin(checkout) if git_checkout else ""
            actual_branch = _checkout_branch(checkout) if git_checkout else ""
            if not origin:
                origin = actual_origin or LOCAL_ORIGIN
            if not branch and _valid_branch_name(actual_branch):
                branch = actual_branch
            if not _valid_origin(origin):
                raise SourceRebindError("invalid-source-origin", "the selected source origin is invalid")
            if git_checkout:
                if origin != LOCAL_ORIGIN:
                    if not actual_origin or not hmac.compare_digest(actual_origin, origin):
                        raise SourceRebindError("source-origin-mismatch", "the checkout origin does not match the selection")
                elif actual_origin:
                    raise SourceRebindError("source-origin-mismatch", "the checkout has a different verifiable origin")
                if not _valid_branch_name(actual_branch):
                    raise SourceRebindError(
                        "source-branch-mismatch",
                        "a Git source checkout must be on an attached branch",
                    )
                if not _valid_branch_name(branch) or not hmac.compare_digest(actual_branch, branch):
                    raise SourceRebindError("source-branch-mismatch", "the checkout branch does not match the selection")
            elif origin != LOCAL_ORIGIN or branch:
                raise SourceRebindError(
                    "source-origin-mismatch",
                    "a non-Git checkout must use local origin without a branch",
                )
            try:
                commit = _source_commit(checkout)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SourceRebindError("invalid-source-commit", "the selected checkout commit cannot be verified") from exc

            def validate_checkout_at_commit() -> None:
                if not _strict_source_checkout(checkout) or is_git_checkout(checkout) != git_checkout:
                    raise SourceRebindError("invalid-source-checkout", "the selected checkout changed before rebind")
                if git_checkout:
                    final_origin = _checkout_origin(checkout)
                    final_branch = _checkout_branch(checkout)
                    if origin == LOCAL_ORIGIN:
                        if final_origin:
                            raise SourceRebindError("source-origin-mismatch", "the checkout origin changed before rebind")
                    elif final_origin != origin:
                        raise SourceRebindError("source-origin-mismatch", "the checkout origin changed before rebind")
                    if final_branch != branch or not _valid_branch_name(final_branch):
                        raise SourceRebindError("source-branch-mismatch", "the checkout branch changed before rebind")
                    try:
                        final_commit = _source_commit(checkout)
                    except (OSError, subprocess.SubprocessError) as exc:
                        raise SourceRebindError(
                            "invalid-source-commit",
                            "the selected checkout commit cannot be reverified",
                        ) from exc
                    if not hmac.compare_digest(final_commit, commit):
                        raise SourceRebindError("source-commit-mismatch", "the checkout HEAD changed before rebind")
                elif origin != LOCAL_ORIGIN or branch:
                    raise SourceRebindError("source-origin-mismatch", "the local bundle binding changed before rebind")

            precommit_check = validate_checkout_at_commit

        replacement = dict(manifest)
        replacement.update(
            {
                "source_repo": checkout_value,
                "source_origin": origin,
                "source_checkout": checkout_value,
                "source_branch": branch,
                "source_strategy": strategy,
                "source_commit": commit,
            }
        )
        rendered = (json.dumps(replacement, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if rendered != content:
            _write_manifest_at(
                root_fd,
                agents_fd,
                expected_content=content,
                replacement=rendered,
                mode=status.st_mode,
                precommit_check=precommit_check,
            )
        return {
            "status": "rebound",
            "source_origin": origin,
            "source_checkout": checkout_value,
            "source_branch": branch,
            "source_strategy": strategy,
            "source_commit": commit,
            "manifest_digest": _manifest_digest(rendered),
        }


def _source_provenance_from_manifest(root: Path, manifest: dict[str, Any]) -> SourceProvenance | None:
    origin = str(manifest.get("source_origin") or "").strip()
    branch = str(manifest.get("source_branch") or "").strip()
    strategy = str(manifest.get("source_strategy") or "").strip()
    if strategy and strategy not in SOURCE_STRATEGIES:
        return None

    if strategy == LOCAL_CHECKOUT_STRATEGY:
        checkout_text = str(manifest.get("source_checkout") or "").strip()
        if not checkout_text:
            return None
        checkout = Path(checkout_text).expanduser().resolve(strict=False)
        if not is_source_checkout(checkout):
            return None
        if not origin:
            origin = _checkout_origin(checkout) or LOCAL_ORIGIN
        if is_git_checkout(checkout):
            actual_origin = _checkout_origin(checkout)
            actual_branch = _checkout_branch(checkout)
            if not _valid_branch_name(actual_branch) or not _valid_branch_name(branch) or actual_branch != branch:
                return None
            if origin == LOCAL_ORIGIN:
                if actual_origin:
                    return None
            elif not actual_origin or actual_origin != origin:
                return None
        elif origin != LOCAL_ORIGIN or branch:
            return None
        return SourceProvenance(origin, checkout, branch, LOCAL_CHECKOUT_STRATEGY)

    checkout_text = str(manifest.get("source_checkout") or manifest.get("source_repo") or "").strip()
    checkout = Path(checkout_text).expanduser().resolve(strict=False) if checkout_text else None
    if checkout is not None and not is_source_checkout(checkout):
        checkout = None

    if strategy == REMOTE_BRANCH_STRATEGY:
        if not origin or origin == LOCAL_ORIGIN or not _valid_branch_name(branch):
            return None
        return SourceProvenance(origin, checkout, branch, REMOTE_BRANCH_STRATEGY)

    # Legacy manifests occasionally carried a useful source_repo. Preserve that
    # explicit source, but never infer the canonical upstream when no source exists.
    if not origin and checkout is not None:
        origin = _checkout_origin(checkout) or LOCAL_ORIGIN
    if not origin:
        return None
    if origin == LOCAL_ORIGIN:
        if checkout is None:
            return None
        if is_git_checkout(checkout):
            actual_branch = _checkout_branch(checkout)
            if _checkout_origin(checkout) or not _valid_branch_name(actual_branch) or actual_branch != branch:
                return None
        elif branch:
            return None
        return SourceProvenance(origin, checkout, branch, LOCAL_CHECKOUT_STRATEGY)
    if not _valid_branch_name(branch):
        return None
    return SourceProvenance(origin, checkout, branch, REMOTE_BRANCH_STRATEGY)


def _provenance_state(
    install_root: Path,
) -> tuple[SourceProvenance | None, InstallManifestSnapshot | None]:
    root = Path(install_root).expanduser().resolve(strict=False)
    snapshot = None
    if not is_source_checkout(root) or (root / MANIFEST_REL).exists():
        try:
            snapshot = _manifest_snapshot(root, required=False)
        except SourceRebindError:
            return None, None
    if snapshot is not None:
        return _source_provenance_from_manifest(root, snapshot.payload), snapshot
    if is_git_checkout(root):
        origin = _checkout_origin(root) or LOCAL_ORIGIN
        branch = _checkout_branch(root)
        if not _valid_branch_name(branch):
            return None, None
        strategy = LOCAL_CHECKOUT_STRATEGY if origin == LOCAL_ORIGIN else REMOTE_BRANCH_STRATEGY
        return SourceProvenance(origin, root, branch, strategy), None
    return None, None


def source_provenance(install_root: Path) -> SourceProvenance | None:
    provenance, _snapshot = _provenance_state(install_root)
    return provenance


def resolve_source_checkout(install_root: Path) -> Path | None:
    provenance = source_provenance(install_root)
    return provenance.checkout if provenance is not None else None


def resolve_origin_url(checkout: Path | None) -> str:
    if checkout is None:
        return ""
    return _checkout_origin(checkout) or LOCAL_ORIGIN


def _resolve_checkout(provenance: SourceProvenance, cache_dir: Path, *, pull: bool) -> Path:
    checkout = provenance.checkout
    if provenance.is_local:
        if checkout is None or not is_source_checkout(checkout):
            raise SourceChoiceRequired("记录的本地更新源已不可用；需要重新选择源码位置。")
        if is_git_checkout(checkout):
            if not _valid_branch_name(provenance.branch):
                raise SourceChoiceRequired("记录的本地更新源缺少有效分支；需要重新选择更新源。")
            _validate_checkout_branch(checkout, provenance.branch)
        elif provenance.origin != LOCAL_ORIGIN or provenance.branch:
            raise SourceChoiceRequired("记录的本地更新源绑定无效；需要重新选择更新源。")
        if provenance.origin != LOCAL_ORIGIN:
            actual_origin = _checkout_origin(checkout)
            if not actual_origin or actual_origin != provenance.origin:
                raise SourceChoiceRequired("记录的本地更新源已更换远端；需要重新选择更新源。")
        elif is_git_checkout(checkout) and _checkout_origin(checkout):
            raise SourceChoiceRequired("记录的本地更新源已更换远端；需要重新选择更新源。")
        return checkout
    if provenance.effective_strategy != REMOTE_BRANCH_STRATEGY:
        raise SourceChoiceRequired("安装记录包含无法识别的更新策略；需要重新选择更新源。")
    if checkout is not None:
        if is_git_checkout(checkout):
            if not _valid_branch_name(provenance.branch):
                raise SourceChoiceRequired("安装记录缺少有效更新分支；需要重新选择更新源。")
            _validate_checkout_origin(checkout, provenance.origin)
            if pull:
                _validate_checkout_branch(checkout, provenance.branch)
            if pull:
                _pull_checkout(checkout, branch=provenance.branch)
            else:
                _fetch_checkout(checkout, branch=provenance.branch)
            return checkout
    return _prepare_cached_checkout(cache_dir, provenance.origin, pull=pull, branch=provenance.branch)


def fetch_remote_version(provenance: SourceProvenance, cache_dir: Path) -> str:
    checkout = _resolve_checkout(provenance, Path(cache_dir), pull=False)
    if provenance.is_local or not is_git_checkout(checkout):
        return read_source_version(checkout)
    version = _git_output(checkout, "show", f"origin/{provenance.branch}:runtime/VERSION")
    return version or "0.0.0"


def _needs_source_result(local: str, message: str = "安装记录缺少可追溯更新源，需要用户选择。") -> dict[str, str]:
    return {
        "local": local,
        "remote": "unknown",
        "status": "needs_source_choice",
        "message": message,
    }


def check(install_root: Path, cache_dir: Path) -> dict[str, str]:
    root = Path(install_root)
    local = read_source_version(root) if is_source_checkout(root) else read_local_version(root)
    provenance = source_provenance(install_root)
    if provenance is None:
        return _needs_source_result(local)
    try:
        remote = fetch_remote_version(provenance, cache_dir)
    except SourceChoiceRequired as exc:
        return _needs_source_result(local, str(exc))
    except Exception:
        return {"local": local, "remote": "unknown", "status": "unknown"}
    status = "update_available" if compare_versions(local, remote) < 0 else "up_to_date"
    return {
        "local": local,
        "remote": remote,
        "status": status,
        "source_origin": provenance.origin,
        "source_branch": provenance.branch,
    }


def _error_result(before: str, message: str) -> dict[str, str]:
    return {"before": before, "after": before, "status": "error", "message": message}


def apply(install_root: Path, cache_dir: Path) -> dict[str, Any]:
    root = Path(install_root).expanduser().resolve(strict=False)
    source_mode = is_source_checkout(root)
    before = read_source_version(root) if source_mode else read_local_version(root)
    provenance, manifest_snapshot = _provenance_state(root)
    if provenance is None:
        return {
            "before": before,
            "after": before,
            "status": "needs_source_choice",
            "message": "安装记录缺少可追溯更新源，需要用户选择。",
        }
    try:
        source_checkout = _resolve_checkout(provenance, Path(cache_dir), pull=True)
        if source_checkout.resolve(strict=False) == root and is_git_checkout(root):
            after = read_source_version(root) if source_mode else read_local_version(root)
            return {"before": before, "after": after, "status": "updated"}
        source_version = read_source_version(source_checkout)
        if compare_versions(before, source_version) >= 0:
            if manifest_snapshot is not None and not _snapshot_matches_current(root, manifest_snapshot):
                return _error_result(before, "更新未完成：安装记录已变化，请重新执行更新。")
            return {"before": before, "after": before, "status": "up_to_date"}
        source_commit = _source_commit(source_checkout)
        effective_checkout = provenance.checkout
        effective = SourceProvenance(
            provenance.origin,
            effective_checkout,
            provenance.branch,
            provenance.effective_strategy,
        )
        if manifest_snapshot is None:
            return _error_result(before, "更新未完成：安装记录已变化，请重新执行更新。")
        _invoke_ws_sync(
            source_checkout,
            root,
            source_commit,
            effective,
            _manifest_expectation_json(manifest_snapshot),
        )
        return {"before": before, "after": read_local_version(root), "status": "updated"}
    except SourceChoiceRequired as exc:
        return {
            "before": before,
            "after": before,
            "status": "needs_source_choice",
            "message": str(exc),
        }
    except subprocess.CalledProcessError:
        return _error_result(before, "更新未完成：本地修改、分支分叉或安装内容漂移需要先处理。")
    except Exception:
        return _error_result(before, "更新未完成：暂时无法访问记录的更新源或同步安装内容。")

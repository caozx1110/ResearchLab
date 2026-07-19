from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


MANIFEST_REL = Path(".agents/.install-manifest.json")
CACHE_CHECKOUT_PREFIX = "ResearchLab"
LOCAL_ORIGIN = "local"


@dataclass(frozen=True)
class SourceProvenance:
    origin: str
    checkout: Path | None
    branch: str

    @property
    def is_local(self) -> bool:
        return self.origin == LOCAL_ORIGIN


class SourceChoiceRequired(RuntimeError):
    pass


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
    _run_process(("git", "clone", "--depth", "1", "--branch", branch, origin, str(destination)))


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
    return is_git_checkout(candidate) or (candidate / "install-lib" / "ws_sync.py").is_file()


def _load_manifest(install_root: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads((Path(install_root) / MANIFEST_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def source_provenance(install_root: Path) -> SourceProvenance | None:
    root = Path(install_root).expanduser().resolve(strict=False)
    if is_git_checkout(root):
        origin = _checkout_origin(root) or LOCAL_ORIGIN
        branch = _checkout_branch(root)
        if origin != LOCAL_ORIGIN and not _valid_branch_name(branch):
            return None
        return SourceProvenance(origin, root, branch)

    manifest = _load_manifest(root)
    if manifest is None:
        return None
    origin = str(manifest.get("source_origin") or "").strip()
    branch = str(manifest.get("source_branch") or "").strip()
    checkout_text = str(manifest.get("source_checkout") or manifest.get("source_repo") or "").strip()
    checkout = Path(checkout_text).expanduser().resolve(strict=False) if checkout_text else None
    if checkout is not None and not is_source_checkout(checkout):
        checkout = None

    # Legacy manifests occasionally carried a useful source_repo. Preserve that
    # explicit source, but never infer the canonical upstream when no source exists.
    if not origin and checkout is not None:
        origin = _checkout_origin(checkout) or LOCAL_ORIGIN
    if not origin:
        return None
    if origin != LOCAL_ORIGIN and not _valid_branch_name(branch):
        return None
    return SourceProvenance(origin, checkout, branch)


def resolve_source_checkout(install_root: Path) -> Path | None:
    provenance = source_provenance(install_root)
    return provenance.checkout if provenance is not None else None


def resolve_origin_url(checkout: Path | None) -> str:
    if checkout is None:
        return ""
    return _checkout_origin(checkout) or LOCAL_ORIGIN


def _resolve_checkout(provenance: SourceProvenance, cache_dir: Path, *, pull: bool) -> Path:
    checkout = provenance.checkout
    if checkout is not None:
        if provenance.is_local:
            return checkout
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
    if provenance.is_local:
        raise SourceChoiceRequired("记录的本地更新源已不可用；需要重新选择源码位置。")
    return _prepare_cached_checkout(cache_dir, provenance.origin, pull=pull, branch=provenance.branch)


def fetch_remote_version(provenance: SourceProvenance, cache_dir: Path) -> str:
    checkout = _resolve_checkout(provenance, Path(cache_dir), pull=False)
    if provenance.is_local or not is_git_checkout(checkout):
        return read_local_version(checkout)
    version = _git_output(checkout, "show", f"origin/{provenance.branch}:.agents/VERSION")
    return version or "0.0.0"


def _needs_source_result(local: str, message: str = "安装记录缺少可追溯更新源，需要用户选择。") -> dict[str, str]:
    return {
        "local": local,
        "remote": "unknown",
        "status": "needs_source_choice",
        "message": message,
    }


def check(install_root: Path, cache_dir: Path) -> dict[str, str]:
    local = read_local_version(install_root)
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
    before = read_local_version(root)
    provenance = source_provenance(root)
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
            return {"before": before, "after": read_local_version(root), "status": "updated"}
        source_version = read_local_version(source_checkout)
        if compare_versions(before, source_version) >= 0:
            return {"before": before, "after": before, "status": "up_to_date"}
        source_commit = _source_commit(source_checkout)
        effective_checkout = provenance.checkout
        if provenance.is_local and effective_checkout is None:
            effective_checkout = source_checkout
        effective = SourceProvenance(provenance.origin, effective_checkout, provenance.branch)
        _invoke_ws_sync(source_checkout, root, source_commit, effective)
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

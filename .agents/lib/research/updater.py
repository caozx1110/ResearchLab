from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


CANONICAL_ORIGIN = "https://github.com/caozx1110/ResearchLab.git"
DEFAULT_BRANCH = "main"
MANIFEST_REL = Path(".agents/.install-manifest.json")
CACHE_CHECKOUT_NAME = "ResearchLab"


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


def _pull_checkout(checkout: Path) -> None:
    _run_git(checkout, "pull", "--ff-only", "origin", DEFAULT_BRANCH)


def _fetch_checkout(checkout: Path) -> None:
    _run_git(checkout, "fetch", "--quiet", "origin", DEFAULT_BRANCH)


def _clone_checkout(origin: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run_process(("git", "clone", "--depth", "1", "--branch", DEFAULT_BRANCH, origin, str(destination)))


def _cached_checkout(cache_dir: Path) -> Path:
    return cache_dir.expanduser() / CACHE_CHECKOUT_NAME


def _prepare_cached_checkout(cache_dir: Path, *, pull: bool) -> Path:
    checkout = _cached_checkout(cache_dir)
    if is_git_checkout(checkout):
        if pull:
            _pull_checkout(checkout)
        else:
            _fetch_checkout(checkout)
        return checkout
    if checkout.exists():
        raise RuntimeError("update cache is not a git checkout")
    _clone_checkout(CANONICAL_ORIGIN, checkout)
    return checkout


def _source_commit(checkout: Path) -> str:
    return _git_output(checkout, "rev-parse", "HEAD")


def _invoke_ws_sync(source_checkout: Path, install_root: Path, source_commit: str) -> None:
    sync_script = source_checkout / "install-lib" / "ws_sync.py"
    if not sync_script.is_file():
        raise RuntimeError("the update source is missing its workspace sync helper")
    _run_process(
        (
            sys.executable or "python3",
            str(sync_script),
            "update",
            "--repo",
            str(source_checkout),
            "--dir",
            str(install_root),
            "--source-commit",
            source_commit,
        )
    )


def read_local_version(install_root: Path) -> str:
    version_path = Path(install_root) / ".agents" / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return version or "0.0.0"


def parse_semver(value: str) -> tuple[int, int, int]:
    parts = str(value).strip().split(".")
    parsed: list[int] = []
    for index in range(3):
        try:
            parsed.append(int(parts[index]))
        except (IndexError, TypeError, ValueError):
            parsed.append(0)
    return tuple(parsed)  # type: ignore[return-value]


def compare_versions(local: str, remote: str) -> int:
    local_version = parse_semver(local)
    remote_version = parse_semver(remote)
    return (local_version > remote_version) - (local_version < remote_version)


def is_git_checkout(path: Path) -> bool:
    return (Path(path) / ".git").exists()


def resolve_source_checkout(install_root: Path) -> Path | None:
    root = Path(install_root)
    if is_git_checkout(root):
        return root
    manifest_path = root / MANIFEST_REL
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    source_repo = manifest.get("source_repo") if isinstance(manifest, dict) else None
    if not isinstance(source_repo, str) or not source_repo.strip():
        return None
    source = Path(source_repo).expanduser()
    return source if is_git_checkout(source) else None


def resolve_origin_url(checkout: Path | None) -> str:
    if checkout is None:
        return CANONICAL_ORIGIN
    try:
        return _git_output(checkout, "remote", "get-url", "origin") or CANONICAL_ORIGIN
    except (OSError, subprocess.SubprocessError):
        return CANONICAL_ORIGIN


def fetch_remote_version(checkout: Path | None, cache_dir: Path) -> str:
    if checkout is not None:
        _fetch_checkout(checkout)
        version = _git_output(checkout, "show", f"origin/{DEFAULT_BRANCH}:.agents/VERSION")
        return version or "0.0.0"
    cached = _prepare_cached_checkout(Path(cache_dir), pull=False)
    if is_git_checkout(cached):
        try:
            version = _git_output(cached, "show", f"origin/{DEFAULT_BRANCH}:.agents/VERSION")
        except subprocess.SubprocessError:
            version = read_local_version(cached)
        return version or "0.0.0"
    return read_local_version(cached)


def check(install_root: Path, cache_dir: Path) -> dict[str, str]:
    local = read_local_version(install_root)
    try:
        checkout = resolve_source_checkout(install_root)
        remote = fetch_remote_version(checkout, cache_dir)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return {"local": local, "remote": "unknown", "status": "unknown"}
    status = "update_available" if compare_versions(local, remote) < 0 else "up_to_date"
    return {"local": local, "remote": remote, "status": status}


def _error_result(before: str, message: str) -> dict[str, str]:
    return {"before": before, "after": before, "status": "error", "message": message}


def apply(install_root: Path, cache_dir: Path) -> dict[str, Any]:
    root = Path(install_root)
    before = read_local_version(root)
    try:
        if is_git_checkout(root):
            _pull_checkout(root)
            return {"before": before, "after": read_local_version(root), "status": "updated"}

        source_checkout = resolve_source_checkout(root)
        if source_checkout is not None:
            _pull_checkout(source_checkout)
        else:
            source_checkout = _prepare_cached_checkout(Path(cache_dir), pull=True)
        source_commit = _source_commit(source_checkout)
        _invoke_ws_sync(source_checkout, root, source_commit)
        return {"before": before, "after": read_local_version(root), "status": "updated"}
    except subprocess.CalledProcessError:
        return _error_result(before, "更新未完成：本地修改、分支分叉或安装内容漂移需要先手动处理。")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return _error_result(before, "更新未完成：暂时无法访问更新源或同步安装内容。")

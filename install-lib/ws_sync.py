#!/usr/bin/env python3
"""Copy-project sync helper for workspace-oss installs.

The helper intentionally manages only two reachable areas:

* ``DIR/.agents`` subtree
* the single root-level ``DIR/AGENTS.md`` file

It never enumerates or mutates sibling runtime/data directories such as
``DIR/kb`` or ``DIR/.venv``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INSTALL_NAME = "workspace-oss"
INSTALL_MODE = "copy-project"
MANIFEST_REL = Path(".agents/.install-manifest.json")
MANIFEST_NAME = ".install-manifest.json"
SCHEMA = 1
DEFAULT_LEGACY_AGENTS = {"claude": True, "codex": False}
RELEASE_FILE_MAP = {
    ".agents/AGENTS.md": ".agents/AGENTS.md",
    ".agents/VERSION": ".agents/VERSION",
    "LICENSE": ".agents/LICENSE",
}
RELEASE_PREFIXES = (
    ".agents/skills/",
    ".agents/lib/research/",
)
EXCLUDED_DIRS = {"__pycache__", ".venv", "tests"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".DS_Store", MANIFEST_NAME, "eval_research_value.py"}


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


def tracked_release_files(source_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "ls-files", "-z", "--", ".agents", "LICENSE"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        die(f"source must be a git worktree so untracked files cannot be packaged: {source_root}: {exc}")
    return sorted(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)


def release_destination(rel: str) -> str | None:
    mapped = RELEASE_FILE_MAP.get(rel)
    if mapped is not None:
        return mapped
    if not rel.startswith(RELEASE_PREFIXES):
        return None
    path = Path(rel)
    if should_exclude(path):
        return None
    return rel


def assert_no_symlinked_source_subdirs(source_root: Path, rel: str) -> None:
    path = source_root / rel
    for parent in path.parents:
        if parent == source_root:
            break
        if parent.is_symlink():
            die(f"source release path contains a symlinked subdirectory: {parent}; refuse to package")


def source_items(repo: Path, source: Path | None) -> dict[str, tuple[Path, str]]:
    source_root = (source or repo).resolve()
    agents_src = source_root / ".agents"
    agents_md_src = source_root / ".agents" / "AGENTS.md"
    if not agents_src.is_dir():
        die(f"source .agents directory not found: {agents_src}")
    if not agents_md_src.is_file():
        die(f"source AGENTS.md not found: {agents_md_src}")
    items: dict[str, tuple[Path, str]] = {}
    for rel in tracked_release_files(source_root):
        destination = release_destination(rel)
        if destination is None:
            continue
        assert_no_symlinked_source_subdirs(source_root, rel)
        path = source_root / rel
        if path.is_symlink() or not path.is_file():
            die(f"allowlisted release file is not a regular file: {path}")
        items[destination] = (path, sha256_file(path))
    items["AGENTS.md"] = (agents_md_src, sha256_file(agents_md_src))
    return dict(sorted(items.items()))


def source_agents_actual_nonempty(repo: Path, source: Path | None) -> bool:
    source_root = (source or repo).resolve()
    agents_src = source_root / ".agents"
    for _root, dirs, files in os.walk(agents_src):
        if dirs or files:
            return True
    return False


def load_manifest(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            die(f"manifest not found: {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"manifest is unreadable or invalid JSON: {path}: {exc}")
    if not isinstance(data, dict):
        die(f"manifest has invalid schema: {path}")
    if data.get("schema") != SCHEMA or data.get("install_name") != INSTALL_NAME or data.get("install_mode") != INSTALL_MODE:
        die(f"manifest is not a {INSTALL_NAME} {INSTALL_MODE} manifest: {path}")
    files = data.get("files")
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        die(f"manifest files map is invalid: {path}")
    return data


def path_for_rel(dst_root: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        die(f"manifest contains unsafe path: {rel}")
    if rel == "AGENTS.md":
        return dst_root / "AGENTS.md"
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
    if path == dst_root / "AGENTS.md":
        return
    if not is_under_agents(path, dst_root):
        die(f"refusing to write outside .agents: {path}")
    if not is_under_agents(path.parent, dst_root):
        die(f"refusing to write outside .agents: {path}")


def assert_delete_target(path: Path, dst_root: Path) -> None:
    if path.name == MANIFEST_NAME:
        die(f"refusing to delete manifest through file set: {path}")
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


def write_file_if_needed(src: Path, dst: Path, dst_root: Path, *, dry_run: bool) -> bool:
    src_bytes = read_bytes(src)
    exists = dst.exists()
    same = exists and not dst.is_symlink() and dst.is_file() and read_bytes(dst) == src_bytes
    if same:
        return False
    assert_write_target(dst, dst_root)
    action = "overwrite" if exists else "copy"
    if dry_run:
        info(f"[dry-run] {action} {src} -> {dst}")
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
        info(f"[dry-run] delete {path}")
        return True
    path.unlink()
    return True


def prune_empty_dirs(dst_root: Path, *, dry_run: bool) -> None:
    root = agents_root(dst_root)
    if not root.is_dir():
        return
    dirs = sorted([p for p in root.rglob("*") if not p.is_symlink() and p.is_dir()], key=lambda p: len(p.parts), reverse=True)
    for directory in dirs:
        if directory == root:
            continue
        if not is_under_agents(directory, dst_root):
            continue
        try:
            next(directory.iterdir())
        except StopIteration:
            if dry_run:
                info(f"[dry-run] rmdir {directory}")
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
        info(f"[dry-run] write manifest {path}")
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
    if not source_agents_actual_nonempty(repo, source):
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


def managed_agents_md_state(dst_root: Path, files: dict[str, str]) -> tuple[str, str]:
    digest = files.get("AGENTS.md", "")
    path = dst_root / "AGENTS.md"
    if digest and path.exists() and path.is_file() and sha256_file(path) == digest:
        return "managed", digest
    return "user", digest


def install(args: argparse.Namespace) -> int:
    repo = resolve_dir(args.repo, "repo")
    dst_root = resolve_dir(args.dir, "dir")
    source = resolve_dir(args.source, "source") if args.source else None
    items = source_items(repo, source)
    files = current_files_from_items(items)
    agents = parse_agents(args.agents)
    installed_at = utc_now()

    changed = False
    for rel, (src, _digest) in items.items():
        changed = write_file_if_needed(src, path_for_rel(dst_root, rel), dst_root, dry_run=args.dry_run) or changed

    agents_md_state, agents_md_sha = managed_agents_md_state(dst_root, files)
    manifest = {
        "schema": SCHEMA,
        "install_name": INSTALL_NAME,
        "install_mode": INSTALL_MODE,
        "source_repo": str(repo),
        "source_commit": args.source_commit or "",
        "installed_at": installed_at,
        "updated_at": installed_at,
        "agents": agents,
        "agents_md": agents_md_state,
        "agents_md_sha": agents_md_sha,
        "files": files,
        "tree_checksum": tree_checksum(files),
    }
    write_manifest(dst_root, manifest, dry_run=args.dry_run)
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
    manifest = load_manifest(manifest_path(dst_root), required=True)
    assert manifest is not None
    manifest_repo = str(manifest.get("source_repo") or "")
    if manifest_repo and Path(manifest_repo).expanduser().resolve(strict=False) != repo:
        warn(f"manifest source_repo differs from current repo: {manifest_repo} != {repo}")
    assert_no_symlinked_agent_subdirs(dst_root)

    items = source_items(repo, source)
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
    if drift and not args.force:
        warn("local modifications inside managed .agents block update")
        for rel, expected_hash, actual_hash, reason in drift:
            warn(f"  MODIFIED {rel} reason={reason} expected={expected_hash} actual={actual_hash}")
        die("copy-project update aborted; rerun with --force to overwrite managed drift", code=3)
    if drift and args.force:
        warn("local modifications inside managed .agents will be overwritten because --force was set")
        for rel, _expected_hash, actual_hash, reason in drift:
            warn(f"  MODIFIED {rel} reason={reason} actual={actual_hash}")

    changed = False
    for rel, (src, _digest) in items.items():
        changed = write_file_if_needed(src, path_for_rel(dst_root, rel), dst_root, dry_run=args.dry_run) or changed
    for rel in removed:
        changed = remove_file(path_for_rel(dst_root, rel), dst_root, dry_run=args.dry_run) or changed
    prune_empty_dirs(dst_root, dry_run=args.dry_run)

    if old_files != new_files or old_commit != new_commit:
        changed = True

    if changed:
        installed_at = str(manifest.get("installed_at") or utc_now())
        agents_md_state, agents_md_sha = managed_agents_md_state(dst_root, new_files)
        agents = normalize_manifest_agents(manifest.get("agents"))
        new_manifest = {
            "schema": SCHEMA,
            "install_name": INSTALL_NAME,
            "install_mode": INSTALL_MODE,
            "source_repo": str(repo),
            "source_commit": new_commit,
            "installed_at": installed_at,
            "updated_at": utc_now(),
            "agents": agents,
            "agents_md": agents_md_state,
            "agents_md_sha": agents_md_sha,
            "files": new_files,
            "tree_checksum": tree_checksum(new_files),
        }
        write_manifest(dst_root, new_manifest, dry_run=args.dry_run)
    else:
        info("clean-sync: no changes; manifest unchanged")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    _repo = resolve_dir(args.repo, "repo")
    dst_root = resolve_dir(args.dir, "dir")
    manifest = load_manifest(manifest_path(dst_root), required=True)
    assert manifest is not None
    files = dict(manifest["files"])
    removed_any = False
    for rel in sorted(files, reverse=True):
        if rel == "AGENTS.md":
            continue
        if not rel.startswith(".agents/"):
            continue
        removed_any = remove_file(path_for_rel(dst_root, rel), dst_root, dry_run=args.dry_run) or removed_any
    if manifest_path(dst_root).exists() or manifest_path(dst_root).is_symlink():
        if args.dry_run:
            info(f"[dry-run] delete {manifest_path(dst_root)}")
        else:
            manifest_path(dst_root).unlink()
        removed_any = True
    prune_empty_dirs(dst_root, dry_run=args.dry_run)
    root = agents_root(dst_root)
    if root.exists() and root.is_dir():
        try:
            next(root.iterdir())
            warn(f".agents not empty after uninstall; preserving user files: {root}")
        except StopIteration:
            if args.dry_run:
                info(f"[dry-run] rmdir {root}")
            else:
                root.rmdir()
    if removed_any:
        info(f"copy-project uninstall complete: {dst_root}")
    else:
        info(f"copy-project uninstall found no managed files: {dst_root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="workspace-oss copy-project sync helper")
    parser.add_argument("action", choices=("install", "update", "uninstall"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--agents", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            return install(args)
        if args.action == "update":
            return update(args)
        if args.action == "uninstall":
            return uninstall(args)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

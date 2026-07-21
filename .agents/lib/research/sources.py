"""Source backup/archival, duplicate detection, source-search staging, and storage layout sync.

Dual-source ingestion (SSOT 3.1 decision A, B4): arxiv sources prefer the HTML
edition (arxiv.org/html -> ar5iv Labs -> abs fallback) so no PDF parsing is needed and
locators are section/anchor; non-arxiv PDFs are downloaded as real bytes and parsed
with the always-available lightweight PyMuPDF4LLM backend with page=N locators.
Every archived source persists real bytes + a real sha256 and reports an explicit
backup status/warning (fixing the G7 silent-failure where PDFs stored nothing).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import (
    FETCH_MAX_BYTES,
    FetchTooLarge,
    clean_text,
    ensure_dir,
    fetch_url,
    file_sha256,
    html_to_text,
    infer_topics_and_tags,
    is_url,
    load_yaml,
    normalize_remote_url,
    normalize_title,
    parse_arxiv_id,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
)
from .paths import (
    TEXT_REWRITE_SUFFIXES,
    _deep_fill_missing,
    _legacy_storage_map,
    _slug_list,
    kb_root,
    normalize_storage_reference,
    output_storage_root,
    raw_storage_root,
    record_path,
    rel,
    resolve_local_reference,
    search_stage_path,
    unit_root,
)
from .records import (
    iter_records,
)
from .prefs import (
    ensure_workspace,
)
from .confirm import (
    write_record,
)
from .journal import mutation_transaction

WEB_SNAPSHOT_MAX_CHARS = 120_000

# Hard cap for downloaded PDF/source bytes (SSOT 3.1: "size cap, e.g. 50MB").
SOURCE_DOWNLOAD_MAX_BYTES = min(FETCH_MAX_BYTES, 50 * 1024 * 1024)

# Parse-cache page budget: parse enough of the document to ground evidence
# quotes (screening only reads the front, but notes/evidence may cite anywhere).
PARSE_CACHE_PAGE_LIMIT = 80
PARSE_CACHE_PER_PAGE_CHAR_LIMIT = 8000
PARSE_CACHE_SECTION_LIMIT = 200
PARSE_CACHE_PER_SECTION_CHAR_LIMIT = 8000


def _storage_content_digest(path: Path) -> str | None:
    """Digest file/tree content and relative names, independent of permissions."""
    if not path.exists() and not path.is_symlink():
        return None
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(f"L\0{path.readlink()}".encode("utf-8"))
        return digest.hexdigest()
    if path.is_file():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        if child.is_symlink():
            digest.update(f"L\0{relative}\0{child.readlink()}\0".encode("utf-8"))
        elif child.is_dir():
            digest.update(f"D\0{relative}\0".encode("utf-8"))
        else:
            digest.update(f"F\0{relative}\0".encode("utf-8"))
            with child.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _record_storage_conflict(conflicts: list[dict[str, str]], src: Path, dst: Path, *, reason: str) -> None:
    item = {
        "source": src.as_posix(),
        "destination": dst.as_posix(),
        "source_digest": str(_storage_content_digest(src) or ""),
        "destination_digest": str(_storage_content_digest(dst) or ""),
        "reason": reason,
    }
    if item not in conflicts:
        conflicts.append(item)


def _copy_legacy_tree_item(
    src: Path,
    dst: Path,
    *,
    conflicts: list[dict[str, str]] | None = None,
) -> list[tuple[Path, Path]]:
    """Copy legacy workspace data into kb/ without mutating its source."""
    conflicts = conflicts if conflicts is not None else []
    copied: list[tuple[Path, Path]] = []
    if not src.exists():
        return copied
    if src.is_symlink():
        # A workspace-level legacy symlink can escape the workspace.  Preserve it
        # in place and require an explicit user migration instead of dereferencing.
        _record_storage_conflict(conflicts, src, dst, reason="legacy-symlink-not-copied")
        return copied
    if dst.is_symlink():
        _record_storage_conflict(conflicts, src, dst, reason="destination-symlink-conflict")
        return copied
    if src.is_dir():
        if dst.exists() and (not dst.is_dir() or dst.is_symlink()):
            _record_storage_conflict(conflicts, src, dst, reason="destination-kind-conflict")
            return copied
        ensure_dir(dst)
        for child in sorted(src.iterdir()):
            copied.extend(_copy_legacy_tree_item(child, dst / child.name, conflicts=conflicts))
        if _storage_content_digest(src) != _storage_content_digest(dst):
            _record_storage_conflict(conflicts, src, dst, reason="destination-tree-conflict")
        return copied
    if dst.exists():
        if _storage_content_digest(src) != _storage_content_digest(dst):
            _record_storage_conflict(conflicts, src, dst, reason="destination-byte-conflict")
        return copied
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    copied.append((src, dst))
    return copied


def _copy_into_raw(backup: Path, target: Path) -> bool:
    if target.exists():
        return True
    ensure_dir(target.parent)
    if backup.is_dir():
        shutil.copytree(backup, target)
        return True
    shutil.copy2(backup, target)
    return True


def _rewrite_storage_text(text: str, project_root: Path) -> str:
    old_abs_raw = (project_root / "raw").resolve().as_posix()
    new_abs_raw = raw_storage_root(project_root).resolve().as_posix()
    old_abs_output = (project_root / "output").resolve().as_posix()
    new_abs_output = output_storage_root(project_root).resolve().as_posix()
    updated = text.replace(old_abs_raw, new_abs_raw).replace(old_abs_output, new_abs_output)
    updated = re.sub(r"(?<!kb/)raw/", "kb/raw/", updated)
    updated = re.sub(r"(?<!kb/)output/", "kb/output/", updated)
    return updated


def _storage_rewrite_paths(project_root: Path) -> list[Path]:
    """Return mutable KB text only; runtime code/rules and evidence stay untouched."""
    root = kb_root(project_root).resolve()
    paths: list[Path] = []
    for path in (root.rglob("*") if root.exists() else []):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            continue
        if any(part in {".git", ".journal", ".runtime"} for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] == "raw":
            continue
        if "source" in relative.parts:
            continue
        if path.name == "record.yaml":
            # Record source URIs require byte-equivalence checks; never rewrite
            # them with a blind text substitution.
            continue
        if path.name.startswith("parse-cache") and path.suffix.lower() in {".yaml", ".yml"}:
            continue
        if path.suffix.lower() not in TEXT_REWRITE_SUFFIXES:
            continue
        paths.append(path)
    return paths


def storage_sync_target_paths(project_root: Path) -> list[Path]:
    """Plan every KB-local path that storage sync may mutate."""
    targets: set[Path] = set()
    for name, destination_root in (("raw", raw_storage_root(project_root)), ("output", output_storage_root(project_root))):
        source_root = project_root / name
        if source_root.is_dir() and not source_root.is_symlink():
            targets.update(destination_root / child.name for child in source_root.iterdir())

    for record in iter_records(project_root):
        source = record.get("source", {})
        if not isinstance(source, dict):
            continue
        original_uri = str(source.get("original_uri") or "").strip()
        if not original_uri or is_url(original_uri):
            continue
        _, remapped_path = _legacy_storage_map(project_root, original_uri)
        if remapped_path is None:
            continue
        normalized_uri = remapped_path.resolve().as_posix() if remapped_path.exists() else remapped_path.as_posix()
        if normalized_uri != original_uri:
            kind = str(record.get("kind") or "")
            unit_id = str(record.get("id") or "")
            if kind and unit_id:
                targets.add(record_path(project_root, kind, unit_id))
        if not remapped_path.exists():
            for rel_backup in source.get("backup_paths", []):
                if (project_root / str(rel_backup)).exists():
                    targets.add(remapped_path)
                    break

    for path in _storage_rewrite_paths(project_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _rewrite_storage_text(text, project_root) != text:
            targets.add(path)

    return sorted(targets, key=lambda path: path.as_posix())


def _sync_storage_layout_unlocked(project_root: Path) -> dict[str, Any]:
    copied_paths: list[tuple[Path, Path]] = []
    conflicts: list[dict[str, str]] = []
    preserved_legacy_roots: list[str] = []
    for name, destination_root in (("raw", raw_storage_root(project_root)), ("output", output_storage_root(project_root))):
        source_root = project_root / name
        if not source_root.exists():
            continue
        preserved_legacy_roots.append(source_root.as_posix())
        ensure_dir(destination_root)
        for child in sorted(source_root.iterdir()):
            copied_paths.extend(
                _copy_legacy_tree_item(child, destination_root / child.name, conflicts=conflicts)
            )

    updated_records: list[str] = []
    hydrated_paths: list[str] = []
    for record in iter_records(project_root):
        source = record.get("source", {})
        if not isinstance(source, dict):
            continue
        original_uri = str(source.get("original_uri") or "").strip()
        if not original_uri or is_url(original_uri):
            continue
        old_path, remapped_path = _legacy_storage_map(project_root, original_uri)
        if remapped_path is None:
            continue
        backup_candidates = []
        for rel_backup in source.get("backup_paths", []):
            backup = project_root / str(rel_backup)
            if backup.exists():
                backup_candidates.append(backup)
        if not remapped_path.exists() and backup_candidates:
            _copy_into_raw(backup_candidates[0], remapped_path)
            hydrated_paths.append(rel(project_root, remapped_path))
        reference_sources = [path for path in [old_path, *backup_candidates] if path is not None and path.exists()]
        equivalent_source = next(
            (
                path
                for path in reference_sources
                if remapped_path.exists()
                and _storage_content_digest(path) == _storage_content_digest(remapped_path)
            ),
            None,
        )
        if not remapped_path.exists() or equivalent_source is None:
            conflict_source = reference_sources[0] if reference_sources else (old_path or Path(original_uri))
            _record_storage_conflict(
                conflicts,
                conflict_source,
                remapped_path,
                reason="record-reference-not-byte-equivalent",
            )
            continue
        normalized_uri = remapped_path.resolve().as_posix()
        if normalized_uri != original_uri:
            source["original_uri"] = normalized_uri
            record["source"] = source
            write_record(project_root, record)
            updated_records.append(str(record.get("id") or ""))

    rewritten_files: list[str] = []
    for path in _storage_rewrite_paths(project_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = _rewrite_storage_text(text, project_root)
        if updated != text:
            write_text_if_changed(path, updated)
            rewritten_files.append(rel(project_root, path))

    return {
        # Compatibility key: these are logical migrations, now implemented as
        # non-destructive copies so every mutation remains journalable in kb/**.
        "moved_paths": [(src.as_posix(), dst.as_posix()) for src, dst in copied_paths],
        "copied_paths": [(src.as_posix(), dst.as_posix()) for src, dst in copied_paths],
        "preserved_legacy_roots": preserved_legacy_roots,
        "conflicts": conflicts,
        "updated_records": updated_records,
        "hydrated_paths": hydrated_paths,
        "rewritten_files": rewritten_files,
        # Canonical source evidence is immutable.  New directory intake excludes
        # VCS metadata while still in staging; storage sync never prunes it later.
        "removed_nested_git": [],
    }


def sync_storage_layout(project_root: Path) -> dict[str, Any]:
    ensure_workspace(project_root)
    targets = storage_sync_target_paths(project_root)
    if not targets:
        return _sync_storage_layout_unlocked(project_root)
    with mutation_transaction(project_root, "storage-sync", targets):
        return _sync_storage_layout_unlocked(project_root)


def build_search_stage_id(kind: str, query: str) -> str:
    base = slugify(query, max_words=8) or kind
    short_hash = hashlib.sha1(f"{kind}:{query}".encode("utf-8")).hexdigest()[:8]
    return f"{kind}-search-{base}-{short_hash}"


def load_search_stage(project_root: Path, stage_id: str) -> dict[str, Any]:
    payload = load_yaml(search_stage_path(project_root, stage_id), default={})
    if not isinstance(payload, dict) or not payload.get("id"):
        raise SystemExit(f"Search stage not found: {stage_id}")
    return payload


def stage_search_results(
    project_root: Path,
    *,
    kind: str,
    query: str,
    candidates: list[dict[str, Any]],
    stage_id: str = "",
    note: str = "",
) -> Path:
    ensure_workspace(project_root)
    current_stage_id = stage_id or build_search_stage_id(kind, query)
    path = search_stage_path(project_root, current_stage_id)
    with mutation_transaction(project_root, "stage_search_results", [path]):
        return _stage_search_results_unlocked(
            project_root,
            path=path,
            current_stage_id=current_stage_id,
            kind=kind,
            query=query,
            candidates=candidates,
            note=note,
        )


def _stage_search_results_unlocked(
    project_root: Path,
    *,
    path: Path,
    current_stage_id: str,
    kind: str,
    query: str,
    candidates: list[dict[str, Any]],
    note: str,
) -> Path:
    existing = load_yaml(path, default={})
    if not isinstance(existing, dict):
        existing = {}
    payload = _deep_fill_missing(
        existing,
        {
            "id": current_stage_id,
            "kind": "source-search-stage",
            "status": "staged",
            "source_kind": kind,
            "query": query,
            "note": note,
            "generated_by": "source-intake",
            "generated_at": utc_now_iso(),
            "candidates": [],
            "history": [],
        },
    )
    known_urls = {str(item.get("url") or "") for item in payload.get("candidates", []) if isinstance(item, dict)}
    query_topics, query_tags = infer_topics_and_tags(query, project_root=project_root)
    for index, candidate in enumerate(candidates, start=1):
        url = str(candidate.get("url") or "").strip()
        title = str(candidate.get("title") or "").strip()
        if not url or url in known_urls:
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            seed = title or url or f"{current_stage_id}:{index}"
            candidate_id = f"{current_stage_id}-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:6]}"
        payload["candidates"].append(
            {
                "candidate_id": candidate_id,
                "title": title,
                "url": url,
                "status": "staged",
                "note": str(candidate.get("note") or "").strip(),
                "topics": _slug_list(candidate.get("topics")) or _slug_list(query_topics),
                "tags": _slug_list(candidate.get("tags")) or _slug_list(query_tags),
                "pool_hints": _slug_list(candidate.get("pool_hints")),
            }
        )
        known_urls.add(url)
    payload["history"].append({"timestamp": utc_now_iso(), "action": "staged", "summary": f"Captured {len(candidates)} candidates."})
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(path, payload)
    return path


def resolve_search_candidate(project_root: Path, stage_id: str, candidate_id: str) -> dict[str, Any]:
    payload = load_search_stage(project_root, stage_id)
    for candidate in payload.get("candidates", []):
        if str(candidate.get("candidate_id") or "") == candidate_id:
            return dict(candidate)
    raise SystemExit(f"Candidate `{candidate_id}` not found in stage `{stage_id}`")


def mark_search_candidate(
    project_root: Path,
    stage_id: str,
    candidate_id: str,
    *,
    status: str,
    record_id: str = "",
) -> Path:
    path = search_stage_path(project_root, stage_id)
    with mutation_transaction(project_root, "mark_search_candidate", [path]):
        payload = load_search_stage(project_root, stage_id)
        found = False
        for candidate in payload.get("candidates", []):
            if str(candidate.get("candidate_id") or "") != candidate_id:
                continue
            candidate["status"] = status
            if record_id:
                candidate["record_id"] = record_id
            found = True
            break
        if not found:
            raise SystemExit(f"Candidate `{candidate_id}` not found in stage `{stage_id}`")
        payload.setdefault("history", []).append(
            {
                "timestamp": utc_now_iso(),
                "action": "candidate-updated",
                "summary": f"{candidate_id} -> {status}",
            }
        )
        write_yaml_if_changed(path, payload)
    return path


class UnsafeLocalSourceError(RuntimeError):
    """A selected local source cannot be archived without following links."""


def _path_exists_without_following(path: Path) -> bool:
    try:
        path.lstat()
    except (FileNotFoundError, OSError):
        return False
    return True


def _local_source_candidates(project_root: Path, source: str) -> list[Path]:
    """Return lexical local candidates without resolving a symlink leaf."""
    text = str(source or "").strip()
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return [candidate]
    original, remapped = _legacy_storage_map(project_root, text)
    return [path for path in (remapped, original) if path is not None]


def _validate_open_directory_no_links(source_fd: int) -> None:
    try:
        entries = sorted(os.scandir(source_fd), key=lambda entry: entry.name)
    except OSError as exc:
        raise UnsafeLocalSourceError("无法安全遍历这份本地资料。") from exc
    for entry in entries:
        try:
            child_stat = os.stat(entry.name, dir_fd=source_fd, follow_symlinks=False)
        except OSError as exc:
            raise UnsafeLocalSourceError("无法安全检查这份本地资料。") from exc
        if stat.S_ISLNK(child_stat.st_mode):
            raise UnsafeLocalSourceError("这份本地资料包含符号链接；为避免读取范围外的内容，已停止入库。")
        if stat.S_ISDIR(child_stat.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                child_fd = os.open(entry.name, flags, dir_fd=source_fd)
            except OSError as exc:
                raise UnsafeLocalSourceError("本地资料在检查时发生了变化，已停止入库。") from exc
            try:
                if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                    raise UnsafeLocalSourceError("本地资料在检查时发生了类型变化，已停止入库。")
                _validate_open_directory_no_links(child_fd)
            finally:
                os.close(child_fd)
        elif not stat.S_ISREG(child_stat.st_mode):
            raise UnsafeLocalSourceError("这份本地资料包含不支持的文件类型，已停止入库。")


def _assert_contained_local_tree(path: Path) -> None:
    """Validate a local source with lstat/openat traversal, rejecting every link."""
    try:
        root_stat = path.lstat()
    except OSError as exc:
        raise UnsafeLocalSourceError("无法安全读取这份本地资料。") from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise UnsafeLocalSourceError("这份本地资料包含符号链接；为避免读取范围外的内容，已停止入库。")
    if stat.S_ISREG(root_stat.st_mode):
        return
    if not stat.S_ISDIR(root_stat.st_mode):
        raise UnsafeLocalSourceError("这份本地资料不是普通文件或目录，已停止入库。")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(path, flags)
    except OSError as exc:
        raise UnsafeLocalSourceError("本地资料在检查时发生了变化，已停止入库。") from exc
    try:
        if not stat.S_ISDIR(os.fstat(source_fd).st_mode):
            raise UnsafeLocalSourceError("本地资料在检查时发生了类型变化，已停止入库。")
        _validate_open_directory_no_links(source_fd)
    finally:
        os.close(source_fd)


def validate_local_source(project_root: Path, source: str) -> Path | None:
    """Return a safe lexical source path, or None when the reference is absent."""
    for candidate in _local_source_candidates(project_root, source):
        if not _path_exists_without_following(candidate):
            continue
        _assert_contained_local_tree(candidate)
        return candidate
    return None


def _copy_regular_file_no_links(src: Path, dst: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(src, flags)
    except OSError as exc:
        raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
    try:
        source_stat = os.fstat(descriptor)
        if not stat.S_ISREG(source_stat.st_mode):
            raise UnsafeLocalSourceError("本地资料在复制前发生了类型变化，已停止入库。")
        ensure_dir(dst.parent)
        with os.fdopen(descriptor, "rb", closefd=False) as source_handle, dst.open("xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
    finally:
        os.close(descriptor)


def _file_sha256_no_links(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UnsafeLocalSourceError("本地资料在读取前发生了变化，已停止入库。") from exc
    digest = hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise UnsafeLocalSourceError("本地资料在读取前发生了类型变化，已停止入库。")
        with os.fdopen(descriptor, "rb", closefd=False) as source_handle:
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _copy_open_directory_no_links(source_fd: int, dst: Path) -> None:
    """Copy a directory through openat-style descriptors; never follow links."""
    dst.mkdir()
    try:
        entries = sorted(os.scandir(source_fd), key=lambda item: item.name)
    except OSError as exc:
        raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
    for entry in entries:
        if entry.name in {".git", ".gitmodules"}:
            continue
        try:
            child_stat = os.stat(entry.name, dir_fd=source_fd, follow_symlinks=False)
        except OSError as exc:
            raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
        if stat.S_ISLNK(child_stat.st_mode):
            raise UnsafeLocalSourceError("这份本地资料包含符号链接；为避免读取范围外的内容，已停止入库。")
        destination = dst / entry.name
        if stat.S_ISDIR(child_stat.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                child_fd = os.open(entry.name, flags, dir_fd=source_fd)
            except OSError as exc:
                raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
            try:
                if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                    raise UnsafeLocalSourceError("本地资料在复制前发生了类型变化，已停止入库。")
                _copy_open_directory_no_links(child_fd, destination)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(child_stat.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                child_fd = os.open(entry.name, flags, dir_fd=source_fd)
            except OSError as exc:
                raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
            try:
                if not stat.S_ISREG(os.fstat(child_fd).st_mode):
                    raise UnsafeLocalSourceError("本地资料在复制前发生了类型变化，已停止入库。")
                with os.fdopen(child_fd, "rb", closefd=False) as source_handle, destination.open("xb") as destination_handle:
                    shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            finally:
                os.close(child_fd)
        else:
            raise UnsafeLocalSourceError("这份本地资料包含不支持的文件类型，已停止入库。")


def _copy_dir(src: Path, dst: Path) -> None:
    _assert_contained_local_tree(src)
    if dst.exists():
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(src, flags)
    except OSError as exc:
        raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
    try:
        if not stat.S_ISDIR(os.fstat(source_fd).st_mode):
            raise UnsafeLocalSourceError("本地资料在复制前发生了类型变化，已停止入库。")
        _copy_open_directory_no_links(source_fd, dst)
    except Exception:
        if dst.exists() and not dst.is_symlink():
            shutil.rmtree(dst)
        raise
    finally:
        os.close(source_fd)


def _is_html_response(content_type: str, text: str) -> bool:
    normalized = content_type.lower().strip()
    if normalized in {"text/html", "application/xhtml+xml"} or normalized.endswith("+html"):
        return True
    prefix = text[:1000].lower()
    return "<html" in prefix or "<!doctype html" in prefix


def _truncate_snapshot_text(text: str) -> str:
    if len(text) <= WEB_SNAPSHOT_MAX_CHARS:
        return text
    trimmed = text[:WEB_SNAPSHOT_MAX_CHARS].rsplit(" ", 1)[0].rstrip()
    return (trimmed or text[:WEB_SNAPSHOT_MAX_CHARS]).rstrip() + "\n\n[truncated]\n"


# --- arxiv source resolution (SSOT 3.1: HTML-first) -----------------------

_ARXIV_HOST_RE = re.compile(r"(?:^|\.)arxiv\.org$|(?:^|\.)ar5iv\.", re.IGNORECASE)


def _arxiv_id_from_source(source: str) -> str:
    """Bare arxiv id (no version) for an arxiv URL or raw id, else ''."""
    text = str(source or "").strip()
    if not text:
        return ""
    if is_url(text):
        from urllib.parse import urlparse

        if not _ARXIV_HOST_RE.search(urlparse(text).netloc.lower()):
            return ""
    arxiv_id = parse_arxiv_id(text)
    return arxiv_id.split("v", 1)[0] if arxiv_id else ""


def _arxiv_html_candidates(arxiv_id: str) -> list[dict[str, str]]:
    """Ordered HTML editions: native arxiv HTML -> ar5iv Labs -> abs fallback."""
    return [
        {"url": f"https://arxiv.org/html/{arxiv_id}", "edition": "arxiv-html", "degraded": ""},
        {
            "url": f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
            "edition": "ar5iv-labs",
            "degraded": "",
        },
        {
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "edition": "arxiv-abs",
            "degraded": "arxiv HTML/ar5iv editions unavailable; archived abstract page only (no full body).",
        },
    ]


# --- PDF parsing (SSOT 3.1: lightweight PyMuPDF4LLM default) ----------------


def _pymupdf4llm_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pymupdf4llm") is not None and importlib.util.find_spec("fitz") is not None


def _pdf_to_page_chunks(
    pdf_path: Path,
    *,
    page_limit: int = PARSE_CACHE_PAGE_LIMIT,
    per_page_char_limit: int = PARSE_CACHE_PER_PAGE_CHAR_LIMIT,
) -> list[dict[str, Any]]:
    """Parse a PDF into per-page chunks (label ``<name>:page-N``) via PyMuPDF4LLM.

    Returns [] when the lightweight backend is unavailable so callers degrade to
    an explicit warning rather than a silent empty parse."""
    if not _pymupdf4llm_available():
        return []
    import fitz  # type: ignore
    import pymupdf4llm  # type: ignore

    chunks: list[dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as doc:
        total = doc.page_count
        pages = list(range(min(page_limit, total)))
        page_data = pymupdf4llm.to_markdown(doc, pages=pages, page_chunks=True, show_progress=False)
    for entry in page_data:
        if not isinstance(entry, dict):
            continue
        page_number = (entry.get("metadata") or {}).get("page")
        if not isinstance(page_number, int):
            page_number = len(chunks) + 1
        text = clean_text(str(entry.get("text") or ""))
        if not text:
            continue
        if per_page_char_limit and len(text) > per_page_char_limit:
            text = text[:per_page_char_limit].rsplit(" ", 1)[0].rstrip() + " ..."
        chunks.append({"label": f"{pdf_path.name}:page-{page_number}", "text": text, "page": page_number})
    return chunks


def _abstract_from_text(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(?is)\babstract\b[:.\-\s]*(.+?)(?:\n\s*\n|\b1\s+introduction\b|\bintroduction\b)", text)
    return clean_text(match.group(1))[:2000] if match else ""


def _pdf_metadata(pdf_path: Path, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Best-effort lightweight metadata from a parsed PDF (title/abstract/year)."""
    title = ""
    year: int | None = None
    if _pymupdf4llm_available():
        import fitz  # type: ignore

        with fitz.open(str(pdf_path)) as doc:
            meta = doc.metadata or {}
        embedded = clean_text(str(meta.get("title") or ""))
        if len(embedded.split()) >= 3:
            title = embedded
        for key in ("creationDate", "modDate"):
            match = re.search(r"D:(\d{4})", str(meta.get(key) or ""))
            if match:
                year = int(match.group(1))
                break
    first_page = chunks[0]["text"] if chunks else ""
    if not title and first_page:
        # F8: a paper title often spans several physical lines (e.g. a short tail
        # line like "Weighting"). Collect the leading contiguous title block instead
        # of taking only the first qualifying line, then join. The first line must
        # look title-shaped (3-20 words); continuation lines are accepted more
        # loosely (short tails ok), stopping at an author list / affiliation /
        # abstract / link / blank line.
        title_lines: list[str] = []
        for raw_line in first_page.splitlines():
            line = clean_text(raw_line).lstrip("# ").strip()
            if not line:
                if title_lines:
                    break
                continue
            lowered = line.lower()
            if lowered.startswith("abstract") or "http" in lowered or "arxiv:" in lowered or "@" in line:
                if title_lines:
                    break
                continue
            words = len(line.split())
            if not title_lines:
                if 3 <= words <= 20:
                    title_lines.append(line)
                # else keep scanning for the first title-shaped line
            elif words <= 20 and line.count(",") < 2:
                title_lines.append(line)  # continuation line (short tails allowed)
            else:
                break  # author list (>=2 commas) or over-long line ends the title
        title = " ".join(title_lines)
    arxiv_id = _arxiv_id_from_source(pdf_path.name) or parse_arxiv_id("\n".join(c["text"] for c in chunks[:2]))
    if arxiv_id and year is None:
        year = 2000 + int(arxiv_id[:2])
    return {"title": title, "abstract": _abstract_from_text(first_page), "year": year, "arxiv_id": arxiv_id}


# --- HTML section parsing (SSOT B4: section/anchor locators, no page nums) --


def _slug_anchor(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]
    return slug or fallback


def _clip(text: str, limit: int) -> str:
    if limit and len(text) > limit:
        return text[:limit].rsplit(" ", 1)[0].rstrip() + " ..."
    return text


def _html_to_section_chunks(
    html: str,
    *,
    section_limit: int = PARSE_CACHE_SECTION_LIMIT,
    per_section_char_limit: int = PARSE_CACHE_PER_SECTION_CHAR_LIMIT,
) -> list[dict[str, Any]]:
    """Split HTML into section chunks keyed by heading anchor (no page numbers).

    Labels use ``section:<anchor>`` (never ``page-N``) so downstream evidence
    verification treats them as HTML section/anchor locators per SSOT B4. Falls
    back to a single whole-document chunk when no headings are present."""
    heading_re = re.compile(r"(?is)<(h[1-6])\b([^>]*)>(.*?)</\1>")
    matches = list(heading_re.finditer(html))
    chunks: list[dict[str, Any]] = []

    def _emit(anchor: str, heading_html: str, body_html: str) -> None:
        heading_text = clean_text(html_to_text(heading_html)) if heading_html else ""
        body = clean_text(html_to_text(body_html))
        combined = clean_text(f"{heading_text}\n{body}") if heading_text else body
        if not combined:
            return
        chunks.append(
            {
                "label": f"section:{anchor}",
                "text": _clip(combined, per_section_char_limit),
                "page": None,
                "locator_kind": "section",
                "anchor": anchor,
                "heading": heading_text,
            }
        )

    if not matches:
        body = clean_text(html_to_text(html))
        if body:
            chunks.append(
                {
                    "label": "section:document",
                    "text": _clip(body, per_section_char_limit),
                    "page": None,
                    "locator_kind": "section",
                    "anchor": "document",
                    "heading": "",
                }
            )
        return chunks

    _emit("preamble", "", html[: matches[0].start()])
    for index, match in enumerate(matches):
        id_match = re.search(r"""id\s*=\s*["']([^"']+)["']""", match.group(2) or "")
        heading_html = match.group(3) or ""
        anchor = id_match.group(1).strip() if id_match else _slug_anchor(clean_text(html_to_text(heading_html)), f"s{index + 1}")
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        _emit(anchor, heading_html, html[match.end():body_end])
        if len(chunks) >= section_limit:
            break
    return chunks


def _text_to_section_chunks(
    text: str,
    *,
    markdown: bool,
    section_limit: int = PARSE_CACHE_SECTION_LIMIT,
    per_section_char_limit: int = PARSE_CACHE_PER_SECTION_CHAR_LIMIT,
) -> list[dict[str, Any]]:
    """Split Markdown or plain text into stable section-located chunks."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks: list[dict[str, Any]] = []

    def emit(anchor: str, heading: str, body: str) -> None:
        cleaned_heading = clean_text(heading)
        cleaned_body = clean_text(body)
        combined = clean_text(f"{cleaned_heading}\n{cleaned_body}") if cleaned_heading else cleaned_body
        if not combined or len(chunks) >= section_limit:
            return
        chunks.append(
            {
                "label": f"section:{anchor}",
                "text": _clip(combined, per_section_char_limit),
                "page": None,
                "locator_kind": "section",
                "anchor": anchor,
                "heading": cleaned_heading,
            }
        )

    if markdown:
        heading_re = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
        matches = list(heading_re.finditer(normalized))
        if matches:
            emit("preamble", "", normalized[: matches[0].start()])
            used_anchors: set[str] = set()
            for index, match in enumerate(matches):
                heading = match.group(2).strip()
                base_anchor = _slug_anchor(heading, f"s{index + 1}")
                anchor = base_anchor
                suffix = 2
                while anchor in used_anchors:
                    anchor = f"{base_anchor}-{suffix}"
                    suffix += 1
                used_anchors.add(anchor)
                body_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
                emit(anchor, heading, normalized[match.end() : body_end])
            return chunks

    paragraphs = [clean_text(item) for item in re.split(r"\n\s*\n+", normalized) if clean_text(item)]
    for index, paragraph in enumerate(paragraphs[:section_limit], start=1):
        emit(f"paragraph-{index}", "", paragraph)
    return chunks


def _html_metadata(html: str) -> dict[str, Any]:
    title = ""
    title_match = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", html)
    if title_match:
        title = clean_text(html_to_text(title_match.group(1)))
    abstract = ""
    abs_match = re.search(r"""(?is)<blockquote[^>]*class=["'][^"']*abstract[^"']*["'][^>]*>(.*?)</blockquote>""", html)
    if abs_match:
        abstract = re.sub(r"(?i)^abstract[:.\-\s]*", "", clean_text(html_to_text(abs_match.group(1))))[:2000]
    return {"title": title, "abstract": abstract}


# --- parse-cache writer + source-record projection --------------------------

# Only keys in the on-disk source contract (SCHEMAS.md) belong in record.source;
# status/warning/locator metadata travel via the return value + stderr + parse-cache.
SOURCE_RECORD_KEYS = ("original_uri", "backup_paths", "backup_kind", "file_hash")


def source_record_fields(source_info: dict[str, Any]) -> dict[str, Any]:
    """Project a backup_source() result down to the on-disk source schema keys.

    Keeps backup_status / backup_warning / locator metadata out of record.source
    (historical pollution guard — see SCHEMAS source contract)."""
    return {key: source_info[key] for key in SOURCE_RECORD_KEYS if key in source_info}


def write_parse_cache(unit_dir: Path, unit_id: str, source_info: dict[str, Any]) -> Path | None:
    """Write a unit-generic parse-cache from a backup_source result.

    Uses the canonical ``unit_id`` header while preserving the chunk shape that
    analyzer compatibility readers consume (no cold-start empty parse),
    and adds ``source_type`` / ``locator_kind`` so downstream evidence (原则2/B4)
    can tell PDF (page=N) from HTML (section/anchor). Returns None when nothing
    was parsed."""
    chunks = source_info.get("parse_chunks") or []
    if not chunks:
        return None
    cache_path = unit_dir / "parse-cache.yaml"
    write_yaml_if_changed(
        cache_path,
        {
            "unit_id": unit_id,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source_type": source_info.get("source_type", ""),
            "locator_kind": source_info.get("locator_kind", ""),
            "parse_backend": source_info.get("parse_backend", ""),
            "cache_policy": {
                "page_limit": PARSE_CACHE_PAGE_LIMIT,
                "per_page_char_limit": PARSE_CACHE_PER_PAGE_CHAR_LIMIT,
                "section_limit": PARSE_CACHE_SECTION_LIMIT,
            },
            "chunks": chunks,
        },
    )
    return cache_path


def _warn(message: str, source_label: str) -> None:
    sys.stderr.write(f"[research/sources.backup_source] WARN: {message} source={source_label}\n")


def _store_bytes(root: Path, name: str, data: bytes) -> Path:
    dst = root / name
    if not dst.exists():
        dst.write_bytes(data)
    return dst


def _backup_arxiv_html(project_root: Path, root: Path, arxiv_id: str, original_source: str) -> dict[str, Any]:
    """Download the best available HTML edition of an arxiv paper (HTML-first)."""
    txt = root / "source-url.txt"
    write_text_if_changed(txt, original_source.strip() + "\n")
    backup_paths = [rel(project_root, txt)]
    abs_uri = f"https://arxiv.org/abs/{arxiv_id}"
    attempts: list[str] = []
    for candidate in _arxiv_html_candidates(arxiv_id):
        url = candidate["url"]
        try:
            content, content_type = fetch_url(url, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"{candidate['edition']}({url}): {exc}")
            continue
        raw_bytes = content if isinstance(content, bytes) else str(content).encode("utf-8")
        html = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
        if not _is_html_response(content_type, html):
            attempts.append(f"{candidate['edition']}({url}): non-HTML content_type={content_type or 'unknown'}")
            continue
        raw = _store_bytes(root, "source.html", raw_bytes)
        backup_paths.append(rel(project_root, raw))
        chunks = _html_to_section_chunks(html)
        body = _truncate_snapshot_text(html_to_text(html))
        if body:
            snapshot = root / "snapshot.md"
            write_text_if_changed(snapshot, f"# Source Snapshot ({candidate['edition']})\n\nSource: {url}\n\n{body.rstrip()}\n")
            backup_paths.append(rel(project_root, snapshot))
        result: dict[str, Any] = {
            "original_uri": abs_uri,
            "backup_paths": backup_paths,
            "backup_kind": "url",
            "file_hash": file_sha256(raw),
            "backup_status": "ok",
            "source_type": "arxiv-abs" if candidate["edition"] == "arxiv-abs" else "arxiv-html",
            "locator_kind": "section",
            "parse_backend": "html-sectioner",
            "parse_chunks": chunks,
            "resolved_url": url,
            "parse_metadata": {**_html_metadata(html), "arxiv_id": arxiv_id},
        }
        warnings: list[str] = []
        if candidate["degraded"]:
            result["backup_status"] = "degraded"
            warnings.append(candidate["degraded"])
        if not chunks:
            warnings.append("HTML edition parsed to zero section chunks.")
        if warnings:
            result["backup_warning"] = " ".join(warnings)
            _warn(result["backup_warning"], abs_uri)
        return result

    warning = "arxiv HTML resolution failed for all editions: " + "; ".join(attempts)
    result = {
        "original_uri": abs_uri,
        "backup_paths": backup_paths,
        "backup_kind": "url",
        "file_hash": "",
        "backup_status": "failed",
        "source_type": "arxiv",
        "locator_kind": "",
        "backup_warning": warning,
    }
    _warn(warning, abs_uri)
    return result


def _backup_pdf_bytes(
    project_root: Path,
    root: Path,
    data: bytes,
    original_uri: str,
    *,
    backup_kind: str,
    file_name: str = "source.pdf",
    extra_backup_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Persist PDF bytes + real sha256 and parse to page chunks (page=N locators)."""
    raw = _store_bytes(root, file_name, data)
    backup_paths = list(extra_backup_paths or [])
    backup_paths.append(rel(project_root, raw))
    result: dict[str, Any] = {
        "original_uri": original_uri,
        "backup_paths": backup_paths,
        "backup_kind": backup_kind,
        "file_hash": file_sha256(raw),
        "backup_status": "ok",
        "source_type": "pdf",
        "locator_kind": "page",
        "parse_backend": "pymupdf4llm" if _pymupdf4llm_available() else "",
    }
    chunks = _pdf_to_page_chunks(raw)
    result["parse_chunks"] = chunks
    if not _pymupdf4llm_available():
        result["backup_status"] = "stored-unparsed"
        result["backup_warning"] = (
            "PDF stored with real bytes+sha256 but not parsed: PyMuPDF4LLM backend unavailable "
            "(install pymupdf4llm to enable page-level parsing)."
        )
        _warn(result["backup_warning"], original_uri)
    elif not chunks:
        result["backup_status"] = "stored-unparsed"
        result["backup_warning"] = "PDF stored with real bytes+sha256 but PyMuPDF4LLM extracted no text (scanned/image-only?)."
        _warn(result["backup_warning"], original_uri)
    else:
        result["parse_metadata"] = _pdf_metadata(raw, chunks)
    return result


def _looks_like_pdf(url: str, content_type: str, data: bytes) -> bool:
    if content_type == "application/pdf":
        return True
    if url.split("?", 1)[0].lower().endswith(".pdf"):
        return True
    return data[:5] == b"%PDF-"


def _backup_generic_url(project_root: Path, root: Path, source: str) -> dict[str, Any]:
    """Non-arxiv URL: real download, PDF->page chunks, HTML->section chunks."""
    original_uri = normalize_remote_url(source)
    txt = root / "source-url.txt"
    write_text_if_changed(txt, source.strip() + "\n")
    backup_paths = [rel(project_root, txt)]
    try:
        content, content_type = fetch_url(source, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
    except FetchTooLarge as exc:
        warning = f"URL source exceeded the {SOURCE_DOWNLOAD_MAX_BYTES}-byte size cap and was not archived: {exc}"
        result = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": "", "backup_status": "failed", "backup_warning": warning}
        _warn(warning, original_uri)
        return result
    except Exception as exc:  # noqa: BLE001
        warning = f"URL source could not be downloaded: {exc}"
        result = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": "", "backup_status": "failed", "backup_warning": warning}
        _warn(warning, original_uri)
        return result

    data = content if isinstance(content, bytes) else str(content).encode("utf-8")
    if _looks_like_pdf(source, content_type, data):
        return _backup_pdf_bytes(project_root, root, data, original_uri, backup_kind="url", extra_backup_paths=backup_paths)

    html = data.decode("utf-8", errors="ignore")
    if _is_html_response(content_type, html):
        raw = _store_bytes(root, "source.html", data)
        backup_paths.append(rel(project_root, raw))
        chunks = _html_to_section_chunks(html)
        body = _truncate_snapshot_text(html_to_text(html))
        if body:
            snapshot = root / "snapshot.md"
            write_text_if_changed(snapshot, f"# Source Snapshot\n\nSource: {original_uri}\n\n{body.rstrip()}\n")
            backup_paths.append(rel(project_root, snapshot))
        result = {
            "original_uri": original_uri,
            "backup_paths": backup_paths,
            "backup_kind": "url",
            "file_hash": file_sha256(raw),
            "backup_status": "ok",
            "source_type": "html",
            "locator_kind": "section",
            "parse_backend": "html-sectioner",
            "parse_chunks": chunks,
            "parse_metadata": _html_metadata(html),
        }
        if not chunks:
            result["backup_status"] = "degraded"
            result["backup_warning"] = "URL source produced an empty HTML section parse."
            _warn(result["backup_warning"], original_uri)
        return result

    warning = f"URL source archived by reference only (unsupported content_type={content_type or 'unknown'}); no text/bytes snapshot."
    result = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": "", "backup_status": "failed", "backup_warning": warning}
    _warn(warning, original_uri)
    return result


def _backup_local(project_root: Path, root: Path, source: str) -> dict[str, Any]:
    """Local file/dir: copy bytes, then parse every supported text/PDF type."""
    src = validate_local_source(project_root, source)
    if src is None:
        raise SystemExit(f"Source not found: {source}")
    dst = root / src.name
    source_stat = src.lstat()
    if stat.S_ISDIR(source_stat.st_mode):
        _copy_dir(src, dst)
        return {"original_uri": src.as_posix(), "backup_paths": [rel(project_root, dst)], "backup_kind": "directory", "file_hash": "", "backup_status": "ok", "source_type": "directory", "locator_kind": ""}
    if not dst.exists():
        _copy_regular_file_no_links(src, dst)
    result: dict[str, Any] = {
        "original_uri": src.as_posix(),
        "backup_paths": [rel(project_root, dst)],
        "backup_kind": "file",
        "file_hash": file_sha256(dst),
        "backup_status": "ok",
    }
    if src.suffix.lower() == ".pdf":
        chunks = _pdf_to_page_chunks(dst)
        result["source_type"] = "pdf"
        result["locator_kind"] = "page"
        result["parse_backend"] = "pymupdf4llm" if _pymupdf4llm_available() else ""
        result["parse_chunks"] = chunks
        if not _pymupdf4llm_available():
            result["backup_status"] = "stored-unparsed"
            result["backup_warning"] = "Local PDF stored with real sha256 but not parsed: PyMuPDF4LLM backend unavailable."
            _warn(result["backup_warning"], src.as_posix())
        elif not chunks:
            result["backup_status"] = "stored-unparsed"
            result["backup_warning"] = "Local PDF stored with real sha256 but PyMuPDF4LLM extracted no text (scanned/image-only?)."
            _warn(result["backup_warning"], src.as_posix())
        else:
            result["parse_metadata"] = _pdf_metadata(dst, chunks)
        return result

    suffix = src.suffix.lower()
    if suffix in {".html", ".htm", ".md", ".markdown", ".txt"}:
        try:
            text = dst.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            result.update(
                {
                    "backup_status": "failed",
                    "source_type": "unsupported-text-encoding",
                    "locator_kind": "",
                    "backup_warning": f"Local text source is not valid UTF-8: {exc}",
                }
            )
            _warn(result["backup_warning"], src.as_posix())
            return result
        if suffix in {".html", ".htm"}:
            chunks = _html_to_section_chunks(text)
            source_type = "html"
            parse_backend = "html-sectioner"
            metadata = _html_metadata(text)
        else:
            chunks = _text_to_section_chunks(text, markdown=suffix in {".md", ".markdown"})
            source_type = "markdown" if suffix in {".md", ".markdown"} else "text"
            parse_backend = "markdown-sectioner" if source_type == "markdown" else "text-sectioner"
            metadata = {}
        result.update(
            {
                "source_type": source_type,
                "locator_kind": "section",
                "parse_backend": parse_backend,
                "parse_chunks": chunks,
            }
        )
        if metadata:
            result["parse_metadata"] = metadata
        if not chunks:
            result["backup_status"] = "failed"
            result["backup_warning"] = f"Local {source_type} source parsed to zero non-empty sections."
            _warn(result["backup_warning"], src.as_posix())
        return result

    result.update(
        {
            "backup_status": "failed",
            "source_type": "unsupported",
            "locator_kind": "",
            "backup_warning": f"Unsupported local file type: {suffix or '<no extension>'}",
        }
    )
    _warn(result["backup_warning"], src.as_posix())
    return result


def source_backup_error(project_root: Path, kind: str, source_info: dict[str, Any]) -> str:
    """Return why a staged source is not ready for canonical materialization."""
    status = str(source_info.get("backup_status") or "").strip()
    if status not in {"ok", "degraded"}:
        return str(source_info.get("backup_warning") or f"source backup status is {status or 'missing'}")
    backup_paths = [str(item).strip() for item in source_info.get("backup_paths", []) if str(item).strip()]
    if not backup_paths:
        return "source backup produced no archived paths"
    missing_paths = [item for item in backup_paths if not (project_root / item).exists()]
    if missing_paths:
        return f"source backup paths are missing: {', '.join(missing_paths)}"
    source_type = str(source_info.get("source_type") or "").strip()
    if source_type == "directory":
        return "" if kind == "repo" else "local directories are supported only for repo intake"
    if not str(source_info.get("file_hash") or "").strip():
        return "source backup has no byte hash"
    chunks = [item for item in source_info.get("parse_chunks", []) if isinstance(item, dict)]
    if not chunks or not any(str(item.get("text") or "").strip() for item in chunks):
        return "source parse produced no non-empty chunks"
    return ""


def rebase_source_backup_paths(
    project_root: Path,
    source_info: dict[str, Any],
    *,
    from_unit_dir: Path,
    to_unit_dir: Path,
) -> dict[str, Any]:
    """Project staged backup paths onto their post-materialization unit paths."""
    rebased = dict(source_info)
    paths: list[str] = []
    staging_root = from_unit_dir.resolve()
    for item in source_info.get("backup_paths", []):
        archived = (project_root / str(item)).resolve()
        try:
            relative = archived.relative_to(staging_root)
        except ValueError as exc:
            raise SystemExit(f"Staged source path escaped its transaction root: {item}") from exc
        paths.append(rel(project_root, to_unit_dir / relative))
    rebased["backup_paths"] = paths
    return rebased


def backup_source(
    project_root: Path,
    kind: str,
    unit_id: str,
    source: str,
    *,
    unit_dir: Path | None = None,
) -> dict[str, Any]:
    """Archive a source as real bytes + real sha256, returning an explicit status.

    Dispatch (SSOT 3.1 decision A / B4):
      * arxiv URL or id  -> HTML-first (arxiv.org/html -> ar5iv Labs -> abs), section locators
      * other URL, PDF   -> real download + PyMuPDF4LLM page chunks, page=N locators
      * other URL, HTML  -> real download + section chunks, section/anchor locators
      * local file/dir   -> copy + sha256; local PDFs also get page=N chunks

    The result always carries ``backup_status`` (ok|degraded|stored-unparsed|failed)
    and, on any non-ok path, an explicit ``backup_warning`` (also emitted to stderr).
    Neither status nor warning belongs in record.source — callers must persist only
    ``source_record_fields(result)`` there (G7 fix: no more silent ``file_hash=""``).
    """
    destination_unit = (unit_dir or unit_root(project_root, kind, unit_id)).resolve()
    try:
        destination_unit.relative_to(kb_root(project_root).resolve())
    except ValueError as exc:
        raise SystemExit(f"Source transaction destination must stay inside kb/: {destination_unit}") from exc
    # Validate a selected local tree before creating even a staging/canonical
    # destination.  Missing references may still be bare arxiv ids and are
    # resolved below; existing links or special files fail closed here.
    if not is_url(source):
        validate_local_source(project_root, source)
    root = destination_unit / "source"
    ensure_dir(root)
    if is_url(source):
        arxiv_id = _arxiv_id_from_source(source)
        if arxiv_id:
            return _backup_arxiv_html(project_root, root, arxiv_id, source)
        return _backup_generic_url(project_root, root, source)
    # A bare arxiv id (not a URL, not an existing local path) is still an arxiv source.
    arxiv_id = _arxiv_id_from_source(source)
    if arxiv_id and resolve_local_reference(project_root, normalize_storage_reference(project_root, source)) is None:
        maybe_local = Path(normalize_storage_reference(project_root, source)).expanduser()
        if not maybe_local.exists():
            return _backup_arxiv_html(project_root, root, arxiv_id, source)
    return _backup_local(project_root, root, source)


def _record_blocks_source_retry(project_root: Path, record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").strip().lower()
    confirmation_status = str(record.get("confirmation_status") or "").strip().lower()
    if status in {"failed", "failed_retryable", "rejected"} or confirmation_status == "rejected":
        return False
    payload = record.get("payload", {})
    if isinstance(payload, dict):
        workflow_state = str(payload.get("workflow_state") or "").strip().lower()
        nested_workflow = payload.get("workflow", {})
        if isinstance(nested_workflow, dict):
            workflow_state = workflow_state or str(nested_workflow.get("state") or "").strip().lower()
        if workflow_state in {"failed", "failed_retryable", "rejected"}:
            return False

    source = record.get("source", {})
    if not isinstance(source, dict):
        return False
    backup_kind = str(source.get("backup_kind") or "").strip()
    backup_paths = [str(item).strip() for item in source.get("backup_paths", []) if str(item).strip()]
    existing = [(project_root / item) for item in backup_paths if (project_root / item).exists()]
    if backup_kind == "directory":
        return any(path.is_dir() for path in existing)
    return bool(str(source.get("file_hash") or "").strip()) and bool(existing)


def detect_duplicate(project_root: Path, kind: str, source: str, *, title: str = "") -> dict[str, Any] | None:
    local_path = None if is_url(source) else validate_local_source(project_root, source)
    normalized = normalize_remote_url(source) if is_url(source) else normalize_storage_reference(project_root, source)
    file_hash = ""
    candidate_arxiv_id = parse_arxiv_id(source)
    candidate_title = normalize_title(title) if title else ""
    if not is_url(source):
        path = local_path or resolve_local_reference(project_root, normalized) or Path(normalized).expanduser().resolve()
        if path.exists() and path.is_file() and not path.is_symlink():
            file_hash = _file_sha256_no_links(path)
            normalized = path.as_posix()
            if not candidate_arxiv_id:
                candidate_arxiv_id = parse_arxiv_id(path.name)
        elif path.exists():
            normalized = path.as_posix()
    for record in iter_records(project_root, kind=kind):
        if not _record_blocks_source_retry(project_root, record):
            continue
        record_source = record.get("source", {})
        record_original_uri = str(record_source.get("original_uri") or "")
        record_normalized = normalize_remote_url(record_original_uri) if is_url(record_original_uri) else record_original_uri
        if normalized and normalized == record_normalized:
            return record
        if file_hash and file_hash == str(record_source.get("file_hash") or ""):
            return record
        if kind == "paper":
            record_arxiv_id = parse_arxiv_id(
                "\n".join(
                    [
                        record_original_uri,
                        str(record.get("title") or ""),
                        str(record.get("payload", {}).get("basic_info", {}).get("source_url") or ""),
                    ]
                )
            )
            if candidate_arxiv_id and record_arxiv_id and candidate_arxiv_id == record_arxiv_id:
                return record
            if candidate_title and candidate_title == normalize_title(str(record.get("title") or "")):
                return record
    return None


__all__ = [
    "WEB_SNAPSHOT_MAX_CHARS",
    "UnsafeLocalSourceError",
    "validate_local_source",
    "_copy_legacy_tree_item",
    "_copy_into_raw",
    "_rewrite_storage_text",
    "storage_sync_target_paths",
    "sync_storage_layout",
    "build_search_stage_id",
    "load_search_stage",
    "stage_search_results",
    "resolve_search_candidate",
    "mark_search_candidate",
    "_copy_dir",
    "_is_html_response",
    "_truncate_snapshot_text",
    "SOURCE_RECORD_KEYS",
    "source_record_fields",
    "source_backup_error",
    "rebase_source_backup_paths",
    "write_parse_cache",
    "backup_source",
    "detect_duplicate",
]

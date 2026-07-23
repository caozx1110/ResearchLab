"""Source backup/archival, duplicate detection, source-search staging, and storage layout sync.

Dual-source ingestion (SSOT 3.1 decision A, B4): arxiv sources prefer quality-gated
HTML (arxiv.org/html -> ar5iv Labs), then PDF, then an abstract-only fallback;
non-arxiv PDFs are downloaded as real bytes and parsed
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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

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
from .openalex import sanitize_openalex_provenance
from .source_materials import (
    ARCHIVE_NAME,
    ASSETS_DIR_NAME,
    CONVERSION_NAME,
    DOCUMENT_NAME,
    SOURCE_MAP_NAME,
    _extract_source_frontmatter,
    _markdown_heading_positions,
    html_reading_fragment,
    inspect_html_quality,
    materialization_paths,
    materialize_fallback,
    materialize_html,
    materialize_pdf,
    materialize_text,
    source_fields as materialization_source_fields,
)
from .yaml_io import write_bytes_atomic

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
    existing_candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
    known_urls = {str(item.get("url") or "") for item in existing_candidates}
    known_candidate_ids = {str(item.get("candidate_id") or ""): item for item in existing_candidates}
    query_topics, query_tags = infer_topics_and_tags(query, project_root=project_root)
    for index, candidate in enumerate(candidates, start=1):
        url = str(candidate.get("url") or "").strip()
        title = str(candidate.get("title") or "").strip()
        if not url:
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            seed = title or url or f"{current_stage_id}:{index}"
            candidate_id = f"{current_stage_id}-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:6]}"
        provenance: dict[str, Any] = {}
        raw_provenance = candidate.get("provenance")
        raw_openalex = raw_provenance.get("openalex") if isinstance(raw_provenance, dict) else None
        sanitized_openalex = sanitize_openalex_provenance(raw_openalex)
        if sanitized_openalex:
            provenance["openalex"] = sanitized_openalex
        existing_candidate = known_candidate_ids.get(candidate_id)
        if existing_candidate is None and url in known_urls:
            continue
        if existing_candidate is not None:
            if provenance:
                existing_candidate["provenance"] = provenance
            continue
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
                **({"provenance": provenance} if provenance else {}),
            }
        )
        known_urls.add(url)
        known_candidate_ids[candidate_id] = payload["candidates"][-1]
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
    if _path_exists_without_following(dst):
        if _file_sha256_no_links(src) != _file_sha256_no_links(dst):
            raise ValueError(f"immutable source byte collision: {dst.name}")
        return
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


def _directory_manifest(root: Path) -> list[tuple[str, str, str]]:
    manifest: list[tuple[str, str, str]] = []
    excluded = {".git", ".gitmodules"}
    for current_text, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_text)
        directory_names[:] = sorted(name for name in directory_names if name not in excluded)
        for name in directory_names:
            path = current / name
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode):
                raise UnsafeLocalSourceError("本地资料目录包含符号链接，已停止入库。")
            if not stat.S_ISDIR(status.st_mode):
                raise UnsafeLocalSourceError("本地资料目录包含不支持的文件类型，已停止入库。")
            manifest.append(("dir", path.relative_to(root).as_posix(), ""))
        for name in sorted(item for item in file_names if item not in excluded):
            path = current / name
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode):
                raise UnsafeLocalSourceError("本地资料目录包含符号链接，已停止入库。")
            if not stat.S_ISREG(status.st_mode):
                raise UnsafeLocalSourceError("本地资料目录包含不支持的文件类型，已停止入库。")
            manifest.append(("file", path.relative_to(root).as_posix(), file_sha256(path)))
    return sorted(manifest, key=lambda item: (item[1], item[0]))


def _copy_dir(src: Path, dst: Path) -> None:
    _assert_contained_local_tree(src)
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() or not dst.is_dir():
            raise ValueError(f"immutable source directory collision: {dst.name}")
        if _directory_manifest(src) != _directory_manifest(dst):
            raise ValueError(f"immutable source directory collision: {dst.name}")
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(src, flags)
    except OSError as exc:
        raise UnsafeLocalSourceError("本地资料在复制前发生了变化，已停止入库。") from exc
    try:
        if not stat.S_ISDIR(os.fstat(source_fd).st_mode):
            raise UnsafeLocalSourceError("本地资料在复制前发生了类型变化，已停止入库。")
        ensure_dir(dst.parent)
        with tempfile.TemporaryDirectory(prefix=f".{dst.name}.stage-", dir=dst.parent) as temporary:
            staged = Path(temporary) / dst.name
            _copy_open_directory_no_links(source_fd, staged)
            os.replace(staged, dst)
    except Exception:
        try:
            if (
                dst.exists()
                and not dst.is_symlink()
                and _directory_manifest(dst) == _directory_manifest(src)
            ):
                return
        except (OSError, UnsafeLocalSourceError):
            pass
        raise
    finally:
        os.close(source_fd)


def _is_html_response(content_type: str, text: str) -> bool:
    normalized = content_type.split(";", 1)[0].lower().strip()
    if normalized in {"text/html", "application/xhtml+xml"} or normalized.endswith("+html"):
        return True
    prefix = text[:1000].lower()
    return "<html" in prefix or "<!doctype html" in prefix


def _decode_source_text(data: bytes, content_type: str = "") -> tuple[str, str, str]:
    """Decode downloaded text without silently discarding source bytes."""
    candidates: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates.append("utf-16")
    charset = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, flags=re.IGNORECASE)
    if charset:
        candidates.append(charset.group(1))
    prefix = data[:8192].decode("latin-1")
    xml_declaration = re.search(
        r"(?is)^\s*<\?xml\b[^>]*\bencoding\s*=\s*[\"']([^\"']+)[\"']",
        prefix,
    )
    if xml_declaration:
        candidates.append(xml_declaration.group(1))
    meta = re.search(
        r"(?is)<meta\b[^>]*(?:charset\s*=\s*[\"']?([^\s\"'/>;]+)|content\s*=\s*[\"'][^\"']*charset=([^\s\"';>]+))",
        prefix,
    )
    if meta:
        candidates.append(str(meta.group(1) or meta.group(2)))
    candidates.append("utf-8")
    attempted: set[str] = set()
    for encoding in candidates:
        normalized = encoding.strip().lower()
        if not normalized or normalized in attempted:
            continue
        attempted.add(normalized)
        try:
            return data.decode(normalized), normalized, ""
        except (LookupError, UnicodeDecodeError):
            continue
    return (
        data.decode("latin-1"),
        "latin-1",
        "Source text was not valid UTF-8 and declared no usable charset; decoded losslessly as latin-1",
    )


def _truncate_snapshot_text(text: str) -> str:
    if len(text) <= WEB_SNAPSHOT_MAX_CHARS:
        return text
    trimmed = text[:WEB_SNAPSHOT_MAX_CHARS].rsplit(" ", 1)[0].rstrip()
    return (trimmed or text[:WEB_SNAPSHOT_MAX_CHARS]).rstrip() + "\n\n[truncated]\n"


# --- arxiv source resolution (SSOT 3.1: HTML-first) -----------------------

_ARXIV_HOST_RE = re.compile(r"(?:^|\.)arxiv\.org$|(?:^|\.)ar5iv\.", re.IGNORECASE)


def _arxiv_id_from_source(source: str) -> str:
    """Exact arxiv id, including an explicitly requested version, else ''."""
    text = str(source or "").strip()
    if not text:
        return ""
    if is_url(text):
        if not _ARXIV_HOST_RE.search(urlparse(text).netloc.lower()):
            return ""
    arxiv_id = parse_arxiv_id(text)
    return arxiv_id or ""


def _arxiv_html_candidates(arxiv_id: str) -> list[dict[str, str]]:
    """Ordered full-text HTML editions; PDF/abstract fallback is handled separately."""
    return [
        {"url": f"https://arxiv.org/html/{arxiv_id}", "edition": "arxiv-html", "degraded": ""},
        {
            "url": f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}",
            "edition": "ar5iv-labs",
            "degraded": "",
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

    with fitz.open(str(pdf_path)) as doc:
        total = doc.page_count
        pages = list(range(min(page_limit, total)))
        page_data = pymupdf4llm.to_markdown(doc, pages=pages, page_chunks=True, show_progress=False)
    return _pdf_page_data_to_chunks(
        pdf_path,
        page_data,
        page_limit=page_limit,
        per_page_char_limit=per_page_char_limit,
    )


def _pdf_page_data_to_chunks(
    pdf_path: Path,
    page_data: Any,
    *,
    page_limit: int = PARSE_CACHE_PAGE_LIMIT,
    per_page_char_limit: int = PARSE_CACHE_PER_PAGE_CHAR_LIMIT,
) -> list[dict[str, Any]]:
    """Project full PyMuPDF4LLM page dictionaries into the bounded cache view."""
    chunks: list[dict[str, Any]] = []
    entries = page_data if isinstance(page_data, list) else []
    for entry in entries[:page_limit]:
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        page_number = metadata.get("page_number") or metadata.get("page")
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
    reading_html, _root_info = html_reading_fragment(html)
    selected_html = reading_html or html
    heading_re = re.compile(r"(?is)<(h[1-6])\b([^>]*)>(.*?)</\1>")
    matches = list(heading_re.finditer(selected_html))
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
        body = clean_text(html_to_text(selected_html))
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

    _emit("preamble", "", selected_html[: matches[0].start()])
    for index, match in enumerate(matches):
        id_match = re.search(r"""id\s*=\s*["']([^"']+)["']""", match.group(2) or "")
        heading_html = match.group(3) or ""
        anchor = id_match.group(1).strip() if id_match else _slug_anchor(clean_text(html_to_text(heading_html)), f"s{index + 1}")
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(selected_html)
        _emit(anchor, heading_html, selected_html[match.end():body_end])
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
        _frontmatter, normalized = _extract_source_frontmatter(normalized)
        lines = normalized.splitlines()
        positions = _markdown_heading_positions(normalized)
        if positions:
            entries: list[tuple[int, int, str]] = []
            for marker_line, heading in positions:
                heading_line = marker_line
                if marker_line > 0 and re.match(r"^ {0,3}(?:=+|-+)[ \t]*$", lines[marker_line]):
                    heading_line = marker_line - 1
                entries.append((heading_line, marker_line + 1, heading))
            emit("preamble", "", "\n".join(lines[: entries[0][0]]))
            used_anchors: set[str] = set()
            for index, (heading_line, body_start, heading) in enumerate(entries):
                base_anchor = _slug_anchor(heading, f"s{index + 1}")
                anchor = base_anchor
                suffix = 2
                while anchor in used_anchors:
                    anchor = f"{base_anchor}-{suffix}"
                    suffix += 1
                used_anchors.add(anchor)
                body_end = entries[index + 1][0] if index + 1 < len(entries) else len(lines)
                emit(anchor, heading, "\n".join(lines[body_start:body_end]))
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
SOURCE_RECORD_KEYS = (
    "original_uri",
    "backup_paths",
    "backup_kind",
    "file_hash",
    "markdown_path",
    "markdown_hash",
    "materialization",
)


def source_record_fields(source_info: dict[str, Any]) -> dict[str, Any]:
    """Project a backup_source() result down to the on-disk source schema keys.

    Keeps backup_status / backup_warning / locator metadata out of record.source
    (historical pollution guard — see SCHEMAS source contract)."""
    return {key: source_info[key] for key in SOURCE_RECORD_KEYS if key in source_info}


def _attach_materialization(project_root: Path, source_info: dict[str, Any], result: dict[str, Any]) -> None:
    """Attach additive source fields and archived paths without hiding degradation."""
    source_info.update(materialization_source_fields(project_root, result))
    existing = [str(item) for item in source_info.get("backup_paths", [])]
    for path in materialization_paths(result):
        relative = rel(project_root, path)
        if relative not in existing:
            existing.append(relative)
    source_info["backup_paths"] = existing
    warnings = [str(item).strip() for item in result.get("warnings", []) if str(item).strip()]
    if warnings:
        prior = str(source_info.get("backup_warning") or "").strip()
        source_info["backup_warning"] = " ".join([item for item in [prior, *warnings] if item])
        if source_info.get("backup_status") == "ok":
            source_info["backup_status"] = "degraded"


def _materialize_safely(
    factory: Callable[[], dict[str, Any]],
    *,
    source_root: Path,
    raw_path: Path,
    source_type: str,
    source_uri: str,
) -> dict[str, Any]:
    """Keep preserved source bytes usable when a converter rejects the input."""
    try:
        return factory()
    except ValueError as exc:
        if str(exc).startswith("immutable source bundle collision:"):
            raise
        return materialize_fallback(
            source_root,
            raw_path,
            source_type=source_type,
            source_uri=source_uri,
            error=exc,
        )
    except Exception as exc:  # noqa: BLE001
        return materialize_fallback(
            source_root,
            raw_path,
            source_type=source_type,
            source_uri=source_uri,
            error=exc,
        )


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
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() or not dst.is_file() or file_sha256(dst) != hashlib.sha256(data).hexdigest():
            raise ValueError(f"immutable source byte collision: {name}")
        return dst
    write_bytes_atomic(dst, data)
    return dst


def _backup_arxiv_html(project_root: Path, root: Path, arxiv_id: str, original_source: str) -> dict[str, Any]:
    """Download quality-gated HTML, then PDF, then an abstract-only page."""
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
        if isinstance(content, bytes):
            html, source_encoding, decode_warning = _decode_source_text(content, content_type)
        else:
            html, source_encoding, decode_warning = str(content), "utf-8", ""
        if not _is_html_response(content_type, html):
            attempts.append(f"{candidate['edition']}({url}): non-HTML content_type={content_type or 'unknown'}")
            continue
        quality = inspect_html_quality(html, require_full_text=True)
        if decode_warning:
            quality["warnings"] = [*quality.get("warnings", []), decode_warning]
        if not quality["accepted"]:
            reason = "; ".join(str(item) for item in quality["rejection_reasons"])
            attempts.append(f"{candidate['edition']}({url}): quality gate rejected: {reason}")
            continue
        chunks = _html_to_section_chunks(html)
        if not chunks:
            attempts.append(f"{candidate['edition']}({url}): parsed to zero section chunks")
            continue
        raw = _store_bytes(root, "source.html", raw_bytes)
        backup_paths.append(rel(project_root, raw))
        result: dict[str, Any] = {
            "original_uri": abs_uri,
            "backup_paths": backup_paths,
            "backup_kind": "url",
            "file_hash": file_sha256(raw),
            "backup_status": "ok",
            "source_type": "arxiv-html",
            "locator_kind": "section",
            "parse_backend": "html-sectioner",
            "parse_chunks": chunks,
            "resolved_url": url,
            "parse_metadata": {
                **_html_metadata(html),
                "arxiv_id": arxiv_id,
                "source_encoding": source_encoding,
            },
        }
        materialized = _materialize_safely(
            lambda: materialize_html(
                root,
                raw,
                html,
                source_uri=abs_uri,
                resolved_url=url,
                fetch_image=fetch_url,
                initial_quality=quality,
            ),
            source_root=root,
            raw_path=raw,
            source_type="html",
            source_uri=abs_uri,
        )
        _attach_materialization(project_root, result, materialized)
        if result.get("backup_warning"):
            _warn(result["backup_warning"], abs_uri)
        result["source_selection_attempts"] = attempts
        return result

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        pdf_content, pdf_content_type = fetch_url(pdf_url, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
        pdf_bytes = pdf_content if isinstance(pdf_content, bytes) else str(pdf_content).encode("utf-8")
        if not _looks_like_pdf(pdf_url, pdf_content_type, pdf_bytes):
            attempts.append(f"arxiv-pdf({pdf_url}): non-PDF content_type={pdf_content_type or 'unknown'}")
        else:
            result = _backup_pdf_bytes(
                project_root,
                root,
                pdf_bytes,
                abs_uri,
                backup_kind="url",
                extra_backup_paths=backup_paths,
            )
            result["resolved_url"] = pdf_url
            result["source_selection_attempts"] = attempts
            return result
    except Exception as exc:  # noqa: BLE001
        attempts.append(f"arxiv-pdf({pdf_url}): {exc}")

    abstract_url = abs_uri
    try:
        content, content_type = fetch_url(abstract_url, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
        raw_bytes = content if isinstance(content, bytes) else str(content).encode("utf-8")
        if isinstance(content, bytes):
            html, source_encoding, decode_warning = _decode_source_text(content, content_type)
        else:
            html, source_encoding, decode_warning = str(content), "utf-8", ""
        if not _is_html_response(content_type, html):
            attempts.append(f"arxiv-abs({abstract_url}): non-HTML content_type={content_type or 'unknown'}")
        else:
            quality = inspect_html_quality(html)
            if quality["accepted"]:
                quality["warnings"] = [
                    *[str(item) for item in quality.get("warnings", [])],
                    *([decode_warning] if decode_warning else []),
                    "Full-text HTML and PDF were unavailable; archived abstract page only",
                ]
                raw = _store_bytes(root, "source.html", raw_bytes)
                fallback_paths = [*backup_paths, rel(project_root, raw)]
                chunks = _html_to_section_chunks(html)
                result = {
                    "original_uri": abs_uri,
                    "backup_paths": fallback_paths,
                    "backup_kind": "url",
                    "file_hash": file_sha256(raw),
                    "backup_status": "degraded",
                    "source_type": "arxiv-abs",
                    "locator_kind": "section",
                    "parse_backend": "html-sectioner",
                    "parse_chunks": chunks,
                    "resolved_url": abstract_url,
                    "parse_metadata": {
                        **_html_metadata(html),
                        "arxiv_id": arxiv_id,
                        "source_encoding": source_encoding,
                    },
                    "source_selection_attempts": attempts,
                }
                materialized = _materialize_safely(
                    lambda: materialize_html(
                        root,
                        raw,
                        html,
                        source_uri=abs_uri,
                        resolved_url=abstract_url,
                        fetch_image=fetch_url,
                        initial_quality=quality,
                    ),
                    source_root=root,
                    raw_path=raw,
                    source_type="html",
                    source_uri=abs_uri,
                )
                _attach_materialization(project_root, result, materialized)
                _warn(result["backup_warning"], abs_uri)
                return result
            attempts.append(
                f"arxiv-abs({abstract_url}): quality gate rejected: "
                + "; ".join(str(item) for item in quality["rejection_reasons"])
            )
    except Exception as exc:  # noqa: BLE001
        attempts.append(f"arxiv-abs({abstract_url}): {exc}")

    warning = "arxiv source resolution failed for HTML, PDF, and abstract editions: " + "; ".join(attempts)
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
    materialized: dict[str, Any] | None = None
    chunks: list[dict[str, Any]] = []
    if _pymupdf4llm_available():
        materialized = _materialize_safely(
            lambda: materialize_pdf(root, raw, source_uri=original_uri),
            source_root=root,
            raw_path=raw,
            source_type="pdf",
            source_uri=original_uri,
        )
        chunks = _pdf_page_data_to_chunks(raw, materialized.get("page_data"))
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
    if materialized is not None:
        _attach_materialization(project_root, result, materialized)
    return result


def _looks_like_pdf(url: str, content_type: str, data: bytes) -> bool:
    if content_type.split(";", 1)[0].strip().lower() == "application/pdf":
        return True
    if url.split("?", 1)[0].lower().endswith(".pdf"):
        return True
    return data[:5] == b"%PDF-"


def _huggingface_dataset_readme_url(source: str) -> str:
    parsed = urlparse(source)
    if (parsed.hostname or "").lower() not in {"huggingface.co", "www.huggingface.co"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "datasets":
        return ""
    owner, repository = parts[1], parts[2]
    if not all(re.fullmatch(r"[A-Za-z0-9._-]+", value) for value in (owner, repository)):
        return ""
    return f"https://huggingface.co/datasets/{owner}/{repository}/resolve/main/README.md"


def _backup_huggingface_dataset_card(
    project_root: Path,
    root: Path,
    source: str,
    original_uri: str,
    backup_paths: list[str],
) -> tuple[dict[str, Any] | None, str]:
    readme_url = _huggingface_dataset_readme_url(source)
    if not readme_url:
        return None, ""
    try:
        content, content_type = fetch_url(
            readme_url,
            binary=True,
            max_bytes=SOURCE_DOWNLOAD_MAX_BYTES,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"Hugging Face dataset card endpoint was unavailable: {exc}"
    data = content if isinstance(content, bytes) else str(content).encode("utf-8")
    markdown, source_encoding, decode_warning = _decode_source_text(data, content_type)
    frontmatter, card_body = _extract_source_frontmatter(markdown)
    headings = _markdown_heading_positions(card_body)
    normalized = clean_text(markdown)
    card_markers = re.search(r"(?im)^(?:dataset_info|configs|license|task_categories):", markdown)
    dataset_identity = bool(card_markers or re.search(r"\bdataset\b", normalized, flags=re.IGNORECASE))
    if _is_html_response(content_type, markdown) or len(normalized) < 200 or not headings or not dataset_identity:
        return None, "Hugging Face README endpoint did not return a substantive dataset card."

    resolved_receipt = _store_bytes(
        root,
        "source-resolved-url.txt",
        (readme_url + "\n").encode("utf-8"),
    )
    raw = _store_bytes(root, "source.md", data)
    archived_paths = [*backup_paths, rel(project_root, resolved_receipt), rel(project_root, raw)]
    chunks = _text_to_section_chunks(markdown, markdown=True)
    pretty_name_match = re.search(r"(?m)^pretty_name\s*:\s*(.+?)\s*$", frontmatter)
    pretty_name = ""
    if pretty_name_match:
        pretty_name = clean_text(pretty_name_match.group(1).strip().strip("'\""))
    result: dict[str, Any] = {
        "original_uri": original_uri,
        "resolved_url": readme_url,
        "backup_paths": archived_paths,
        "backup_kind": "url",
        "file_hash": file_sha256(raw),
        "backup_status": "degraded" if decode_warning else "ok",
        "source_type": "markdown",
        "locator_kind": "section",
        "parse_backend": "markdown-sectioner",
        "parse_chunks": chunks,
        "parse_metadata": {
            "title": pretty_name or headings[0][1],
            "source_encoding": source_encoding,
            "content_type": content_type.split(";", 1)[0].strip().lower(),
            "resolved_url": readme_url,
        },
    }
    if decode_warning:
        result["backup_warning"] = decode_warning
    materialized = _materialize_safely(
        lambda: materialize_text(
            root,
            raw,
            markdown,
            source_uri=original_uri,
            markdown=True,
            fetch_image=fetch_url,
            asset_base_uri=readme_url,
        ),
        source_root=root,
        raw_path=raw,
        source_type="markdown",
        source_uri=original_uri,
    )
    _attach_materialization(project_root, result, materialized)
    if result.get("backup_warning"):
        _warn(str(result["backup_warning"]), original_uri)
    return result, ""


def _backup_generic_url(project_root: Path, root: Path, source: str, *, kind: str) -> dict[str, Any]:
    """Non-arxiv URL: real download, PDF->page chunks, HTML->section chunks."""
    original_uri = normalize_remote_url(source)
    txt = root / "source-url.txt"
    write_text_if_changed(txt, source.strip() + "\n")
    backup_paths = [rel(project_root, txt)]
    dataset_adapter_warning = ""
    if kind == "dataset":
        adapted, dataset_adapter_warning = _backup_huggingface_dataset_card(
            project_root,
            root,
            source,
            original_uri,
            backup_paths,
        )
        if adapted is not None:
            return adapted
    try:
        content, content_type = fetch_url(source, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
    except FetchTooLarge as exc:
        warning = f"URL source exceeded the {SOURCE_DOWNLOAD_MAX_BYTES}-byte size cap and was not archived: {exc}"
        if dataset_adapter_warning:
            warning = f"{dataset_adapter_warning} {warning}"
        result = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": "", "backup_status": "failed", "backup_warning": warning}
        _warn(warning, original_uri)
        return result
    except Exception as exc:  # noqa: BLE001
        warning = f"URL source could not be downloaded: {exc}"
        if dataset_adapter_warning:
            warning = f"{dataset_adapter_warning} {warning}"
        result = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": "", "backup_status": "failed", "backup_warning": warning}
        _warn(warning, original_uri)
        return result

    data = content if isinstance(content, bytes) else str(content).encode("utf-8")
    if _looks_like_pdf(source, content_type, data):
        return _backup_pdf_bytes(project_root, root, data, original_uri, backup_kind="url", extra_backup_paths=backup_paths)

    html, source_encoding, decode_warning = _decode_source_text(data, content_type)
    if _is_html_response(content_type, html):
        raw = _store_bytes(root, "source.html", data)
        backup_paths.append(rel(project_root, raw))
        chunks = _html_to_section_chunks(html)
        quality = inspect_html_quality(html)
        if dataset_adapter_warning:
            quality["warnings"] = list(
                dict.fromkeys([*quality.get("warnings", []), dataset_adapter_warning])
            )
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
            "parse_metadata": {**_html_metadata(html), "source_encoding": source_encoding},
        }
        if decode_warning:
            result["backup_warning"] = decode_warning
            result["backup_status"] = "degraded"
        if dataset_adapter_warning:
            prior = str(result.get("backup_warning") or "").strip()
            result["backup_warning"] = " ".join(
                item for item in [prior, dataset_adapter_warning] if item
            )
            result["backup_status"] = "degraded"
        materialized = _materialize_safely(
            lambda: materialize_html(
                root,
                raw,
                html,
                source_uri=original_uri,
                resolved_url=original_uri,
                fetch_image=fetch_url,
                initial_quality=quality,
            ),
            source_root=root,
            raw_path=raw,
            source_type="html",
            source_uri=original_uri,
        )
        _attach_materialization(project_root, result, materialized)
        if decode_warning:
            _warn(decode_warning, original_uri)
        if dataset_adapter_warning:
            _warn(dataset_adapter_warning, original_uri)
        if not chunks:
            result["backup_status"] = "degraded"
            prior = str(result.get("backup_warning") or "").strip()
            result["backup_warning"] = " ".join(item for item in [prior, "URL source produced an empty HTML section parse."] if item)
            _warn(result["backup_warning"], original_uri)
        return result

    normalized_type = content_type.split(";", 1)[0].strip().lower()
    suffix = Path(urlparse(original_uri).path).suffix.lower()
    is_markdown = normalized_type in {"text/markdown", "text/x-markdown"} or suffix in {".md", ".markdown"}
    is_text = (
        is_markdown
        or normalized_type.startswith("text/")
        or normalized_type in {"application/json", "application/ld+json", "application/xml", "application/xhtml+xml"}
        or normalized_type.endswith(("+json", "+xml"))
    )
    if is_text:
        raw_name = "source.md" if is_markdown else "source.txt"
        raw = _store_bytes(root, raw_name, data)
        backup_paths.append(rel(project_root, raw))
        chunks = _text_to_section_chunks(html, markdown=is_markdown)
        parsed_title = next(
            (str(chunk.get("heading") or "").strip() for chunk in chunks if str(chunk.get("heading") or "").strip()),
            "",
        )
        source_type = "markdown" if is_markdown else "text"
        result = {
            "original_uri": original_uri,
            "backup_paths": backup_paths,
            "backup_kind": "url",
            "file_hash": file_sha256(raw),
            "backup_status": "degraded" if decode_warning else "ok",
            "source_type": source_type,
            "locator_kind": "section",
            "parse_backend": "markdown-sectioner" if is_markdown else "text-sectioner",
            "parse_chunks": chunks,
            "parse_metadata": {
                "title": parsed_title,
                "source_encoding": source_encoding,
                "content_type": normalized_type,
            },
        }
        if decode_warning:
            result["backup_warning"] = decode_warning
        materialized = _materialize_safely(
            lambda: materialize_text(
                root,
                raw,
                html,
                source_uri=original_uri,
                markdown=is_markdown,
                fetch_image=fetch_url,
            ),
            source_root=root,
            raw_path=raw,
            source_type=source_type,
            source_uri=original_uri,
        )
        _attach_materialization(project_root, result, materialized)
        if result.get("backup_warning"):
            _warn(str(result["backup_warning"]), original_uri)
        return result

    raw = _store_bytes(root, "source.bin", data)
    backup_paths.append(rel(project_root, raw))
    warning = (
        f"URL source bytes were archived but not parsed (unsupported content_type={normalized_type or 'unknown'})."
    )
    result = {
        "original_uri": original_uri,
        "backup_paths": backup_paths,
        "backup_kind": "url",
        "file_hash": file_sha256(raw),
        "backup_status": "stored-unparsed",
        "backup_warning": warning,
        "source_type": "unsupported",
        "locator_kind": "",
    }
    _warn(warning, original_uri)
    return result


def _backup_local(project_root: Path, root: Path, source: str) -> dict[str, Any]:
    """Local file/dir: copy bytes, then parse every supported text/PDF type."""
    src = validate_local_source(project_root, source)
    if src is None:
        raise SystemExit(f"Source not found: {source}")
    reserved_names = {DOCUMENT_NAME, SOURCE_MAP_NAME, CONVERSION_NAME, ARCHIVE_NAME, ASSETS_DIR_NAME}
    archived_name = f"original-{src.name}" if src.name in reserved_names else src.name
    dst = root / archived_name
    source_stat = src.lstat()
    if stat.S_ISDIR(source_stat.st_mode):
        _copy_dir(src, dst)
        return {"original_uri": src.as_posix(), "backup_paths": [rel(project_root, dst)], "backup_kind": "directory", "file_hash": "", "backup_status": "ok", "source_type": "directory", "locator_kind": ""}
    _copy_regular_file_no_links(src, dst)
    result: dict[str, Any] = {
        "original_uri": src.as_posix(),
        "backup_paths": [rel(project_root, dst)],
        "backup_kind": "file",
        "file_hash": file_sha256(dst),
        "backup_status": "ok",
    }
    if src.suffix.lower() == ".pdf":
        materialized: dict[str, Any] | None = None
        chunks: list[dict[str, Any]] = []
        if _pymupdf4llm_available():
            materialized = _materialize_safely(
                lambda: materialize_pdf(root, dst, source_uri=src.as_posix()),
                source_root=root,
                raw_path=dst,
                source_type="pdf",
                source_uri=src.as_posix(),
            )
            chunks = _pdf_page_data_to_chunks(dst, materialized.get("page_data"))
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
        if materialized is not None:
            _attach_materialization(project_root, result, materialized)
        return result

    suffix = src.suffix.lower()
    if suffix in {".html", ".htm", ".md", ".markdown", ".txt"}:
        source_content_type = (
            "text/html"
            if suffix in {".html", ".htm"}
            else "text/markdown"
            if suffix in {".md", ".markdown"}
            else "text/plain"
        )
        text, source_encoding, decode_warning = _decode_source_text(
            dst.read_bytes(), source_content_type
        )
        if decode_warning:
            result["backup_status"] = "degraded"
            result["backup_warning"] = decode_warning
        if suffix in {".html", ".htm"}:
            chunks = _html_to_section_chunks(text)
            source_type = "html"
            parse_backend = "html-sectioner"
            metadata = _html_metadata(text)
            materialized = _materialize_safely(
                lambda: materialize_html(
                    root,
                    dst,
                    text,
                    source_uri=src.as_posix(),
                    resolved_url=src.as_uri(),
                    fetch_image=None,
                    local_asset_root=src.parent,
                ),
                source_root=root,
                raw_path=dst,
                source_type="html",
                source_uri=src.as_posix(),
            )
        else:
            chunks = _text_to_section_chunks(text, markdown=suffix in {".md", ".markdown"})
            source_type = "markdown" if suffix in {".md", ".markdown"} else "text"
            parse_backend = "markdown-sectioner" if source_type == "markdown" else "text-sectioner"
            metadata = {
                "title": next(
                    (
                        str(chunk.get("heading") or "").strip()
                        for chunk in chunks
                        if str(chunk.get("heading") or "").strip()
                    ),
                    "",
                )
            }
            materialized = _materialize_safely(
                lambda: materialize_text(
                    root,
                    dst,
                    text,
                    source_uri=src.as_posix(),
                    markdown=source_type == "markdown",
                    fetch_image=fetch_url,
                    local_asset_root=src.parent,
                ),
                source_root=root,
                raw_path=dst,
                source_type=source_type,
                source_uri=src.as_posix(),
            )
        result.update(
            {
                "source_type": source_type,
                "locator_kind": "section",
                "parse_backend": parse_backend,
                "parse_chunks": chunks,
            }
        )
        metadata["source_encoding"] = source_encoding
        result["parse_metadata"] = metadata
        _attach_materialization(project_root, result, materialized)
        if decode_warning:
            _warn(decode_warning, src.as_posix())
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
    staging_root = from_unit_dir.resolve()

    def rebase_path(item: Any) -> str:
        archived = (project_root / str(item)).resolve()
        try:
            relative = archived.relative_to(staging_root)
        except ValueError as exc:
            raise SystemExit(f"Staged source path escaped its transaction root: {item}") from exc
        return rel(project_root, to_unit_dir / relative)

    rebased["backup_paths"] = [rebase_path(item) for item in source_info.get("backup_paths", [])]
    if str(source_info.get("markdown_path") or "").strip():
        rebased["markdown_path"] = rebase_path(source_info["markdown_path"])
    materialization = source_info.get("materialization")
    if isinstance(materialization, dict):
        rebased_materialization = dict(materialization)
        for key in ("source_map_path", "conversion_path", "archive_path"):
            if str(materialization.get(key) or "").strip():
                rebased_materialization[key] = rebase_path(materialization[key])
        rebased_materialization["asset_paths"] = [
            rebase_path(item) for item in materialization.get("asset_paths", [])
        ]
        rebased["materialization"] = rebased_materialization
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
      * arxiv URL or id  -> quality-gated HTML (arxiv.org/html -> ar5iv Labs), PDF, then abstract
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
    if kind == "repo" and is_url(source):
        raise SystemExit(
            "远程代码仓库尚未本地化；请让 AI 先建立安全的本地只读快照，再重新入库。"
            "系统没有创建不可扫描的代码仓库单元。"
        )
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
        return _backup_generic_url(project_root, root, source, kind=kind)
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


def detect_duplicate(
    project_root: Path,
    kind: str,
    source: str,
    *,
    title: str = "",
    candidate_file_hash: str = "",
) -> dict[str, Any] | None:
    local_path = None if is_url(source) else validate_local_source(project_root, source)
    normalized = normalize_remote_url(source) if is_url(source) else normalize_storage_reference(project_root, source)
    file_hash = str(candidate_file_hash or "").strip().lower()
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
        if file_hash and file_hash == str(record_source.get("file_hash") or "").strip().lower():
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

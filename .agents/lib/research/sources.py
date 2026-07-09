"""Source backup/archival, duplicate detection, source-search staging, and storage layout sync.

Dual-source ingestion (SSOT 3.1 decision A, B4): arxiv sources prefer the HTML
edition (arxiv.org/html -> ar5iv -> abs fallback) so no PDF parsing is needed and
locators are section/anchor; non-arxiv PDFs are downloaded as real bytes and parsed
with the always-available lightweight PyMuPDF4LLM backend with page=N locators.
Every archived source persists real bytes + a real sha256 and reports an explicit
backup status/warning (fixing the G7 silent-failure where PDFs stored nothing).
"""
from __future__ import annotations

import hashlib
import re
import shutil
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
    rel,
    resolve_local_reference,
    search_stage_path,
    unit_root,
    units_root,
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

WEB_SNAPSHOT_MAX_CHARS = 120_000

# Hard cap for downloaded PDF/source bytes (SSOT 3.1: "size cap, e.g. 50MB").
SOURCE_DOWNLOAD_MAX_BYTES = min(FETCH_MAX_BYTES, 50 * 1024 * 1024)

# Parse-cache page budget: parse enough of the document to ground evidence
# quotes (screening only reads the front, but notes/evidence may cite anywhere).
PARSE_CACHE_PAGE_LIMIT = 80
PARSE_CACHE_PER_PAGE_CHAR_LIMIT = 8000
PARSE_CACHE_SECTION_LIMIT = 200
PARSE_CACHE_PER_SECTION_CHAR_LIMIT = 8000


def _move_tree_item(src: Path, dst: Path) -> list[tuple[Path, Path]]:
    moved: list[tuple[Path, Path]] = []
    if not src.exists():
        return moved
    if src.is_dir():
        ensure_dir(dst)
        for child in sorted(src.iterdir()):
            moved.extend(_move_tree_item(child, dst / child.name))
        if src.exists():
            try:
                src.rmdir()
            except OSError:
                pass
        return moved
    if dst.exists():
        return moved
    ensure_dir(dst.parent)
    shutil.move(str(src), str(dst))
    moved.append((src, dst))
    return moved


def _copy_into_raw(backup: Path, target: Path) -> bool:
    if target.exists():
        return True
    ensure_dir(target.parent)
    if backup.is_dir():
        shutil.copytree(backup, target)
        return True
    shutil.copy2(backup, target)
    return True


def prune_nested_repo_metadata(project_root: Path) -> list[str]:
    removed: list[str] = []
    repo_sources_root = units_root(project_root) / "repos"
    if not repo_sources_root.exists():
        return removed
    for path in repo_sources_root.glob("*/source/*/.git"):
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(rel(project_root, path))
    return removed


def _rewrite_storage_text(text: str, project_root: Path) -> str:
    old_abs_raw = (project_root / "raw").resolve().as_posix()
    new_abs_raw = raw_storage_root(project_root).resolve().as_posix()
    old_abs_output = (project_root / "output").resolve().as_posix()
    new_abs_output = output_storage_root(project_root).resolve().as_posix()
    updated = text.replace(old_abs_raw, new_abs_raw).replace(old_abs_output, new_abs_output)
    updated = re.sub(r"(?<!kb/)raw/", "kb/raw/", updated)
    updated = re.sub(r"(?<!kb/)output/", "kb/output/", updated)
    return updated


def sync_storage_layout(project_root: Path) -> dict[str, Any]:
    ensure_workspace(project_root)
    moved_paths: list[tuple[Path, Path]] = []
    for name, destination_root in (("raw", raw_storage_root(project_root)), ("output", output_storage_root(project_root))):
        source_root = project_root / name
        if not source_root.exists():
            continue
        ensure_dir(destination_root)
        for child in sorted(source_root.iterdir()):
            moved_paths.extend(_move_tree_item(child, destination_root / child.name))
        try:
            source_root.rmdir()
        except OSError:
            pass

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
        normalized_uri = remapped_path.resolve().as_posix() if remapped_path.exists() else remapped_path.as_posix()
        if normalized_uri != original_uri:
            source["original_uri"] = normalized_uri
            record["source"] = source
            write_record(project_root, record)
            updated_records.append(str(record.get("id") or ""))

    rewritten_files: list[str] = []
    for root in [kb_root(project_root), project_root / ".agents", project_root / "AGENTS.md"]:
        if isinstance(root, Path) and root.is_file():
            paths = [root]
        else:
            paths = list(root.rglob("*")) if isinstance(root, Path) and root.exists() else []
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_REWRITE_SUFFIXES and path.name not in {"AGENTS.md", "SKILL.md"}:
                continue
            if ".git" in path.parts or ("source" in path.parts and path.suffix.lower() not in {".md", ".markdown", ".txt"}):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            updated = _rewrite_storage_text(text, project_root)
            if updated != text:
                write_text_if_changed(path, updated)
                rewritten_files.append(rel(project_root, path))

    removed_nested_git = prune_nested_repo_metadata(project_root)

    return {
        "moved_paths": [(src.as_posix(), dst.as_posix()) for src, dst in moved_paths],
        "updated_records": updated_records,
        "hydrated_paths": hydrated_paths,
        "rewritten_files": rewritten_files,
        "removed_nested_git": removed_nested_git,
    }


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
    path = search_stage_path(project_root, stage_id)
    write_yaml_if_changed(path, payload)
    return path


def _copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", ".gitmodules"))


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
    """Ordered HTML editions: native arxiv HTML -> ar5iv -> abs fallback."""
    return [
        {"url": f"https://arxiv.org/html/{arxiv_id}", "edition": "arxiv-html", "degraded": ""},
        {"url": f"https://ar5iv.org/abs/{arxiv_id}", "edition": "ar5iv", "degraded": ""},
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
        for raw_line in first_page.splitlines():
            line = clean_text(raw_line).lstrip("# ").strip()
            if 3 <= len(line.split()) <= 20 and not line.lower().startswith("abstract"):
                title = line
                break
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
    """Write a paper-analyst-compatible parse-cache from a backup_source result.

    Mirrors paper.py's ``{paper_id, generated_at, cache_policy, chunks}`` shape so
    screen/complete-note reuse it (no PyPDF2 needed, no cold-start empty parse),
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
            "paper_id": unit_id,
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


def backup_source(project_root: Path, kind: str, unit_id: str, source: str) -> dict[str, Any]:
    root = unit_root(project_root, kind, unit_id) / "source"
    ensure_dir(root)
    if is_url(source):
        original_uri = normalize_remote_url(source)
        txt = root / "source-url.txt"
        write_text_if_changed(txt, source.strip() + "\n")
        backup_paths = [rel(project_root, txt)]
        file_hash = ""
        backup_warning = ""
        try:
            content, content_type = fetch_url(source, timeout=15)
            if isinstance(content, str) and _is_html_response(content_type, content):
                body = _truncate_snapshot_text(html_to_text(content))
                if body:
                    snapshot_text = f"# Source Snapshot\n\nSource: {original_uri}\n\n{body.rstrip()}\n"
                    snapshot = root / "snapshot.md"
                    write_text_if_changed(snapshot, snapshot_text)
                    backup_paths.append(rel(project_root, snapshot))
                    file_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
                else:
                    backup_warning = "URL source produced an empty text snapshot."
            else:
                content_label = content_type or type(content).__name__
                backup_warning = f"URL source was not archived as a text snapshot: content_type={content_label}."
        except Exception as exc:  # noqa: BLE001
            backup_warning = f"URL source could not be archived as a text snapshot: {exc}"
        payload = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": file_hash}
        if backup_warning:
            payload["backup_warning"] = backup_warning
            sys.stderr.write(f"[research/core.backup_source] WARN: {backup_warning} source={original_uri}\n")
        return payload

    normalized_source = normalize_storage_reference(project_root, source)
    resolved_source = resolve_local_reference(project_root, normalized_source)
    src = resolved_source or Path(normalized_source).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"Source not found: {source}")
    dst = root / src.name
    if src.is_dir():
        _copy_dir(src, dst)
        file_hash = ""
        backup_kind = "directory"
    else:
        if not dst.exists():
            shutil.copy2(src, dst)
        file_hash = file_sha256(src)
        backup_kind = "file"
    return {
        "original_uri": src.as_posix(),
        "backup_paths": [rel(project_root, dst)],
        "backup_kind": backup_kind,
        "file_hash": file_hash,
    }


def detect_duplicate(project_root: Path, kind: str, source: str, *, title: str = "") -> dict[str, Any] | None:
    normalized = normalize_remote_url(source) if is_url(source) else normalize_storage_reference(project_root, source)
    file_hash = ""
    candidate_arxiv_id = parse_arxiv_id(source)
    candidate_title = normalize_title(title) if title else ""
    if not is_url(source):
        path = resolve_local_reference(project_root, normalized) or Path(normalized).expanduser().resolve()
        if path.exists() and path.is_file():
            file_hash = file_sha256(path)
            normalized = path.as_posix()
            if not candidate_arxiv_id:
                candidate_arxiv_id = parse_arxiv_id(path.name)
        elif path.exists():
            normalized = path.as_posix()
    for record in iter_records(project_root, kind=kind):
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
    "_move_tree_item",
    "_copy_into_raw",
    "prune_nested_repo_metadata",
    "_rewrite_storage_text",
    "sync_storage_layout",
    "build_search_stage_id",
    "load_search_stage",
    "stage_search_results",
    "resolve_search_candidate",
    "mark_search_candidate",
    "_copy_dir",
    "_is_html_response",
    "_truncate_snapshot_text",
    "backup_source",
    "detect_duplicate",
]

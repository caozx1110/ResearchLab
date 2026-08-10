"""Source backup/archival, duplicate detection, source-search staging, and storage layout sync.

Dual-source ingestion (tracked in `docs/DESIGN.md`, "数据模型"): arxiv sources prefer quality-gated
HTML (arxiv.org/html -> ar5iv Labs), then PDF, then an abstract-only fallback;
non-arxiv PDFs are downloaded as real bytes and parsed
with the always-available lightweight PyMuPDF4LLM backend with page=N locators.
Every archived source persists real bytes + a real sha256 and reports an explicit
backup status/warning (fixing the G7 silent-failure where PDFs stored nothing).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yaml

from .common import (
    FETCH_MAX_BYTES,
    FetchTooLarge,
    clean_text,
    ensure_dir,
    extract_pdf_record,
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
    workspace_root_roles,
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
from .path_contract import (
    PathContractError,
    TargetClass,
    classify_data_relative_path,
    logical_ref_to_physical_path,
)
from .source_materials import (
    ARCHIVE_NAME,
    ASSETS_DIR_NAME,
    CONVERSION_NAME,
    DOCUMENT_NAME,
    MATERIALIZATION_SCHEMA,
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
    publish_source_candidate,
    rebase_materialization_result,
    source_fields as materialization_source_fields,
)
from .yaml_io import write_bytes_atomic

WEB_SNAPSHOT_MAX_CHARS = 120_000

# Hard cap for downloaded PDF/source bytes (docs/DESIGN.md, "数据模型").
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
        try:
            target_class = classify_data_relative_path(relative.as_posix())
        except PathContractError:
            continue
        if target_class is not TargetClass.CANONICAL_ARTIFACT:
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
        if source_root.absolute() == destination_root.absolute():
            continue
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
        if source_root.absolute() == destination_root.absolute():
            continue
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


SEARCH_MODES = {"exploratory", "bounded-systematic", "systematic"}
SEARCH_QUERY_INTENTS = {
    "seed",
    "terminology",
    "method",
    "benchmark",
    "survey",
    "backward-citation",
    "forward-citation",
    "gap-followup",
}
SEARCH_QUERY_OUTCOMES = {
    "success",
    "partial",
    "failed_retryable",
    "failed_terminal",
    "blocked",
}
SEARCH_RETRIEVAL_STATUSES = {
    "discovered",
    "fetching",
    "fetched",
    "failed_retryable",
    "failed_terminal",
    "needs_fulltext",
    "staged",
}
SEARCH_EVIDENCE_LEVELS = {"snippet", "title", "abstract", "fulltext"}
SEARCH_SCREENING_DECISIONS = {"unassessed", "include", "maybe", "exclude"}
SEARCH_REVIEW_MODES = {"independent", "assisted"}
SEARCH_REVIEWER_ACTOR_TYPES = {"agent", "human"}
SEARCH_REVIEW_PHASES = {"title_abstract", "fulltext"}
SEARCH_ADJUDICATION_MODES = {"consensus", "third_reviewer", "user"}
SEARCH_STOP_REASONS = {
    "in_progress",
    "target_met",
    "saturated",
    "budget_exhausted",
    "blocked_no_search_tool",
    "blocked",
    "user_stop",
}
SEARCH_BUDGET_FIELDS = {
    "max_queries",
    "max_candidates",
    "max_full_reads",
    "max_citation_hops",
}
SEARCH_USAGE_FIELDS = {
    "queries",
    "candidates_seen",
    "full_reads",
    "citation_hops",
    "retryable_failures",
}

_LITERATURE_TERMINAL_STOP_REASONS = {
    "target_met",
    "saturated",
    "budget_exhausted",
    "user_stop",
}
_SEARCH_STAGE_ENUMERATION_MAX_BYTES = 8 * 1024 * 1024
_LITERATURE_SEARCH_STAGE_TOP_LEVEL_FIELDS = frozenset(
    {
        "id",
        "kind",
        "status",
        "source_kind",
        "query",
        "note",
        "generated_by",
        "generated_at",
        "entry_skill",
        "mode",
        "run_id",
        "monitor_binding",
        "scope",
        "review_protocol",
        "reviewers",
        "preference_context",
        "budget",
        "usage",
        "queries",
        "candidates",
        "coverage",
        "coverage_history",
        "frontier",
        "frontier_history",
        "stop",
        "stop_history",
        "partial",
        "history",
    }
)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys at every mapping depth."""


class _DuplicateYamlMappingKey(yaml.YAMLError):
    """Internal non-disclosing signal for a duplicate persisted YAML key."""


def _construct_unique_yaml_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise _DuplicateYamlMappingKey
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_yaml_mapping,
)
SEARCH_FLOW_COUNT_FIELDS = {
    "identified",
    "duplicates_removed",
    "title_abstract_screened",
    "title_abstract_excluded",
    "fulltext_sought",
    "fulltext_unavailable",
    "fulltext_assessed",
    "excluded_with_reason",
    "included",
    "automation_excluded",
}


def _bounded_search_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_search_id(value: Any, *, field: str) -> str:
    identifier = _bounded_search_text(value, 128)
    if not identifier or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier) is None:
        raise SystemExit(f"Literature search {field} must be an ASCII-safe identifier.")
    return identifier


def _safe_search_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SystemExit(f"Literature search {field} must be an integer of at least {minimum}.")
    return value


def _safe_search_url(value: Any) -> str:
    raw = _bounded_search_text(value, 4096)
    if not raw:
        return ""
    _reject_sensitive_search_text(raw, field="candidate URL")
    parsed = urlparse(raw)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return ""
    host = (parsed.hostname or "").lower()
    try:
        parsed_port = parsed.port
    except ValueError:
        return ""
    port = f":{parsed_port}" if parsed_port is not None else ""
    netloc = f"{host}{port}"
    path = re.sub(r"/+", "/", parsed.path or "/")
    query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
    tracking_keys = {"fbclid", "gclid", "ref", "referrer", "source"}
    kept_pairs = [
        (key, item)
        for key, item in query_pairs
        if not key.lower().startswith("utm_") and key.lower() not in tracking_keys
    ]
    if host in {"arxiv.org", "www.arxiv.org"}:
        arxiv_id = _canonical_search_arxiv_id(raw)
        if arxiv_id:
            path = f"/abs/{arxiv_id}"
        kept_pairs = []
    elif host in {"doi.org", "dx.doi.org"}:
        kept_pairs = []
    query = urlencode(sorted(kept_pairs), doseq=True)
    return urlunparse((parsed.scheme.lower(), netloc, path.rstrip("/") or "/", "", query, ""))


def _search_stage_locator(value: Any) -> str:
    remote = _safe_search_url(value)
    if remote:
        return remote
    local_reference = _bounded_search_text(value, 4096)
    if local_reference and not urlparse(local_reference).scheme:
        return local_reference
    return ""


def _canonical_search_doi(value: Any) -> str:
    doi = _bounded_search_text(value, 512)
    if not doi:
        return ""
    doi = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
        "",
        doi,
        flags=re.IGNORECASE,
    ).strip()
    doi = doi.split("?", 1)[0].split("#", 1)[0].rstrip(".,")
    if re.fullmatch(r"10\.\d{4,9}/[-._;()/:+A-Z0-9]+", doi, flags=re.IGNORECASE) is None:
        return ""
    return f"https://doi.org/{doi.lower()}"


def _reject_sensitive_search_text(value: str, *, field: str) -> None:
    if re.search(
        r"(?i)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|cookie|secret|token|signature|sig|x-amz-(?:credential|signature|security-token))\s*(?:=|:|%3d)|bearer\s+[A-Za-z0-9._~+/-]+",
        value,
    ):
        raise SystemExit(f"Literature search {field} contains sensitive request material.")


def _canonical_search_arxiv_id(value: Any) -> str:
    arxiv_id = parse_arxiv_id(_bounded_search_text(value, 256))
    return re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)


def _canonical_search_pmid(value: Any) -> str:
    pmid = _bounded_search_text(value, 32)
    return pmid if re.fullmatch(r"[1-9]\d{0,15}", pmid) else ""


def _search_string_list(value: Any, *, field: str, item_limit: int = 300) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise SystemExit(f"Literature search {field} must be a list.")
    cleaned: list[str] = []
    for item in value:
        text = _bounded_search_text(item, item_limit)
        if not text:
            raise SystemExit(f"Literature search {field} contains an invalid item.")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _freeze_search_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_search_value(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_freeze_search_value(item) for item in value)
    return value


def _sanitize_search_scope(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search scope must be a mapping.")
    scope: dict[str, Any] = {}
    for key in ("facets", "inclusion", "exclusion", "languages", "source_types", "channels"):
        if key in raw:
            scope[key] = _search_string_list(raw.get(key), field=f"scope.{key}")
    for key in ("as_of", "date_range", "result_depth", "screening", "disagreement_resolution"):
        if key in raw:
            text = _bounded_search_text(raw.get(key), 1000)
            if not text:
                raise SystemExit(f"Literature search scope.{key} must be non-empty text.")
            scope[key] = text
    if "target_count" in raw:
        scope["target_count"] = _safe_search_int(
            raw.get("target_count"), field="scope.target_count", minimum=1
        )
    if "screeners" in raw:
        scope["screeners"] = _safe_search_int(
            raw.get("screeners"), field="scope.screeners", minimum=1
        )
    if "reproducible" in raw:
        if not isinstance(raw.get("reproducible"), bool):
            raise SystemExit("Literature search scope.reproducible must be true or false.")
        scope["reproducible"] = raw["reproducible"]
    return scope


def _validate_systematic_scope(mode: str, scope: dict[str, Any]) -> None:
    if mode == "exploratory":
        return
    required = (
        "inclusion",
        "exclusion",
        "languages",
        "source_types",
        "channels",
        "date_range",
        "result_depth",
        "screening",
        "screeners",
    )
    missing = [key for key in required if not scope.get(key)]
    if missing:
        raise SystemExit(
            "Systematic literature search requires a frozen scope: " + ", ".join(missing) + "."
        )
    reproducible = scope.get("reproducible") is True
    if mode == "systematic" and not reproducible:
        raise SystemExit("A systematic literature search must declare a reproducible search scope.")
    if mode == "bounded-systematic" and reproducible:
        raise SystemExit("Use systematic mode when the full search scope is reproducible.")


def _sanitize_search_budget(raw: Any) -> dict[str, int]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search budget must be a mapping.")
    budget: dict[str, int] = {}
    for key in SEARCH_BUDGET_FIELDS:
        if key in raw:
            budget[key] = _safe_search_int(raw[key], field=f"budget.{key}", minimum=1)
    return budget


def _sanitize_search_usage(raw: Any) -> dict[str, int]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search usage must be a mapping.")
    usage: dict[str, int] = {}
    for key in SEARCH_USAGE_FIELDS:
        if key in raw:
            usage[key] = _safe_search_int(raw[key], field=f"usage.{key}")
    return usage


def _sanitize_search_query(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit("Literature search query events must be mappings.")
    query_id = _safe_search_id(raw.get("query_id"), field="query_id")
    text = _bounded_search_text(raw.get("text"), 2000)
    if not text:
        raise SystemExit("Literature search query events require text.")
    intent = _bounded_search_text(raw.get("intent"), 64)
    if intent not in SEARCH_QUERY_INTENTS:
        raise SystemExit("Literature search query intent is not supported.")
    channel = _bounded_search_text(raw.get("channel"), 128)
    tool = _bounded_search_text(raw.get("tool"), 128)
    selection_reason = _bounded_search_text(raw.get("selection_reason"), 1000)
    if not channel or not tool or not selection_reason:
        raise SystemExit("Literature search query events require channel, tool, and selection_reason.")
    outcome = _bounded_search_text(raw.get("outcome"), 64)
    if outcome not in SEARCH_QUERY_OUTCOMES:
        raise SystemExit("Literature search query outcome is not supported.")
    facet = _bounded_search_text(raw.get("facet"), 300)
    searched_at = _bounded_search_text(raw.get("searched_at"), 80)
    result_depth = _bounded_search_text(raw.get("result_depth"), 300)
    if not facet or not searched_at or not result_depth or "result_count" not in raw:
        raise SystemExit(
            "Literature search query events require facet, searched_at, result_depth, and result_count."
        )
    try:
        parsed_time = datetime.fromisoformat(searched_at.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit("Literature search query searched_at must be an ISO-8601 timestamp.") from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise SystemExit("Literature search query searched_at must include a timezone.")
    event: dict[str, Any] = {
        "query_id": query_id,
        "text": text,
        "intent": intent,
        "channel": channel,
        "tool": tool,
        "selection_reason": selection_reason,
        "outcome": outcome,
        "facet": facet,
        "searched_at": searched_at,
        "result_depth": result_depth,
        "result_count": _safe_search_int(raw["result_count"], field="query.result_count"),
    }
    if "reproducible" in raw:
        if not isinstance(raw.get("reproducible"), bool):
            raise SystemExit("Literature search query reproducible must be true or false.")
        event["reproducible"] = raw["reproducible"]
    error_class = _bounded_search_text(raw.get("error_class"), 128)
    if error_class:
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", error_class) is None:
            raise SystemExit("Literature search query error_class must be a safe slug.")
        event["error_class"] = error_class
    return event


def _sanitize_search_coverage(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search coverage must be a mapping.")
    coverage: dict[str, Any] = {}
    if "round" in raw:
        coverage["round"] = _safe_search_int(raw["round"], field="coverage.round")
    for key in ("covered_facets", "uncovered_facets"):
        if key in raw:
            coverage[key] = _search_string_list(raw.get(key), field=f"coverage.{key}")
    for key in ("new_candidates", "deduplicated", "new_relevant"):
        if key in raw:
            coverage[key] = _safe_search_int(raw[key], field=f"coverage.{key}")
    for key in ("notes", "concentration_risk", "bias_risk"):
        text = _bounded_search_text(raw.get(key), 1500)
        if text:
            coverage[key] = text
    if "flow_counts" in raw:
        raw_counts = raw.get("flow_counts")
        if not isinstance(raw_counts, dict):
            raise SystemExit("Literature search coverage.flow_counts must be a mapping.")
        counts: dict[str, int] = {}
        for key in SEARCH_FLOW_COUNT_FIELDS:
            if key in raw_counts:
                counts[key] = _safe_search_int(
                    raw_counts[key], field=f"coverage.flow_counts.{key}"
                )
        coverage["flow_counts"] = counts
    return coverage


def _sanitize_search_frontier(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise SystemExit("Literature search frontier must be a list.")
    frontier: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise SystemExit("Literature search frontier items must be mappings.")
        candidate_id = _safe_search_id(item.get("candidate_id"), field="frontier candidate_id")
        status = _bounded_search_text(item.get("status"), 64) or "pending"
        if status not in {"pending", "expanded", "skipped", "failed_retryable"}:
            raise SystemExit("Literature search frontier status is not supported.")
        reason = _bounded_search_text(item.get("priority_reason"), 1000)
        if not reason:
            raise SystemExit("Literature search frontier items require priority_reason.")
        entry: dict[str, Any] = {
            "candidate_id": candidate_id,
            "priority_reason": reason,
            "status": status,
        }
        direction = _bounded_search_text(item.get("direction"), 32)
        if direction:
            if direction not in {"backward", "forward"}:
                raise SystemExit("Literature search frontier direction is not supported.")
            entry["direction"] = direction
        parent = _bounded_search_text(item.get("parent_candidate_id"), 128)
        if parent:
            entry["parent_candidate_id"] = _safe_search_id(
                parent, field="frontier parent_candidate_id"
            )
        frontier.append(entry)
    return frontier


def _sanitize_search_stop(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search stop state must be a mapping.")
    reason = _bounded_search_text(raw.get("reason"), 64) or "in_progress"
    if reason not in SEARCH_STOP_REASONS:
        raise SystemExit("Literature search stop reason is not supported.")
    rationale = _bounded_search_text(raw.get("rationale"), 1500)
    if reason != "in_progress" and not rationale:
        raise SystemExit("A terminal literature search stop reason requires rationale.")
    stop: dict[str, Any] = {"reason": reason}
    if rationale:
        stop["rationale"] = rationale
    if "uncovered_facets" in raw:
        stop["uncovered_facets"] = _search_string_list(
            raw.get("uncovered_facets"), field="stop.uncovered_facets"
        )
    return stop


def _search_sha256(value: object) -> str:
    rendered = repr(_freeze_search_value(value)).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _sanitize_search_review_protocol(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search review_protocol must be a mapping.")
    reviewer_ids = _search_string_list(
        raw.get("required_reviewer_ids"), field="review_protocol.required_reviewer_ids", item_limit=128
    )
    reviewer_ids = [
        _safe_search_id(item, field="review_protocol reviewer_id") for item in reviewer_ids
    ]
    if len(reviewer_ids) < 2:
        raise SystemExit("Multi-reviewer search requires at least two reviewer ids.")
    mode = _bounded_search_text(raw.get("mode"), 32)
    if mode not in SEARCH_REVIEW_MODES:
        raise SystemExit("Literature search review_protocol mode is not supported.")
    phases = _search_string_list(raw.get("phases"), field="review_protocol.phases", item_limit=32)
    if not phases or any(phase not in SEARCH_REVIEW_PHASES for phase in phases):
        raise SystemExit("Literature search review_protocol phases are not supported.")
    phase_rank = {"title_abstract": 0, "fulltext": 1}
    if len(set(phases)) != len(phases) or phases != sorted(phases, key=phase_rank.__getitem__):
        raise SystemExit("Literature search review_protocol phases must use canonical screening order.")
    adjudication_mode = _bounded_search_text(raw.get("adjudication_mode"), 32)
    if adjudication_mode not in SEARCH_ADJUDICATION_MODES:
        raise SystemExit("Literature search adjudication mode is not supported.")
    return {
        "required_reviewer_ids": reviewer_ids,
        "mode": mode,
        "phases": phases,
        "adjudication_mode": adjudication_mode,
    }


def _sanitize_search_reviewers(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise SystemExit("Literature search reviewers must be a list.")
    reviewers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise SystemExit("Literature search reviewers must be mappings.")
        reviewer_id = _safe_search_id(item.get("reviewer_id"), field="reviewer_id")
        if reviewer_id in seen:
            raise SystemExit("Literature search reviewer ids must be unique.")
        seen.add(reviewer_id)
        actor_type = _bounded_search_text(item.get("actor_type"), 32)
        if actor_type not in SEARCH_REVIEWER_ACTOR_TYPES:
            raise SystemExit("Literature search reviewer actor_type is not supported.")
        execution_id = _safe_search_id(item.get("execution_id"), field="reviewer execution_id")
        reviewer: dict[str, Any] = {
            "reviewer_id": reviewer_id,
            "actor_type": actor_type,
            "role": "screener",
            "execution_id": execution_id,
        }
        if actor_type == "human":
            attestation = _bounded_search_text(item.get("attestation"), 1000)
            authorization_source = _bounded_search_text(item.get("authorization_source"), 64)
            if not attestation or authorization_source != "user_message":
                raise SystemExit(
                    "A human literature reviewer requires a current user-message attestation."
                )
            reviewer["attestation"] = attestation
            reviewer["authorization_source"] = authorization_source
        reviewers.append(reviewer)
    return reviewers


def _sanitize_search_state(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search state must be a mapping.")
    state: dict[str, Any] = {}
    entry_skill = _bounded_search_text(raw.get("entry_skill"), 128)
    if entry_skill:
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", entry_skill) is None:
            raise SystemExit("Literature search entry_skill must be a safe slug.")
        state["entry_skill"] = entry_skill
    mode = _bounded_search_text(raw.get("mode"), 64)
    if mode:
        if mode not in SEARCH_MODES:
            raise SystemExit("Literature search mode is not supported.")
        state["mode"] = mode
    if "run_id" in raw:
        state["run_id"] = _safe_search_id(raw.get("run_id"), field="run_id")
    if "monitor_binding" in raw:
        binding = raw.get("monitor_binding")
        if not isinstance(binding, dict) or set(binding) != {"run_id", "task_digest"}:
            raise SystemExit("Literature search monitor binding is invalid.")
        task_digest = _bounded_search_text(binding.get("task_digest"), 64)
        if re.fullmatch(r"[0-9a-f]{64}", task_digest) is None:
            raise SystemExit("Literature search monitor task digest is invalid.")
        state["monitor_binding"] = {
            "run_id": _safe_search_id(binding.get("run_id"), field="monitor run_id"),
            "task_digest": task_digest,
        }
    if "scope" in raw:
        state["scope"] = _sanitize_search_scope(raw.get("scope"))
    if "review_protocol" in raw:
        state["review_protocol"] = _sanitize_search_review_protocol(raw.get("review_protocol"))
    if "reviewers" in raw:
        state["reviewers"] = _sanitize_search_reviewers(raw.get("reviewers"))
    if "preference_context" in raw:
        context = raw.get("preference_context")
        if not isinstance(context, dict) or set(context) != {
            "task_context_digest",
            "selection_binding",
            "hard_value_digests",
        }:
            raise SystemExit("Literature search preference context is invalid.")
        task_digest = _bounded_search_text(context.get("task_context_digest"), 64)
        if re.fullmatch(r"[0-9a-f]{64}", task_digest) is None:
            raise SystemExit("Literature search preference task context digest is invalid.")
        raw_binding = context.get("selection_binding")
        if not isinstance(raw_binding, dict):
            raise SystemExit("Literature search preference selection binding is invalid.")
        binding: dict[str, str] = {}
        if raw_binding:
            if set(raw_binding) != {
                "selection_id",
                "selection_digest",
                "task_context_digest",
                "skill",
                "operation",
            }:
                raise SystemExit("Literature search preference selection binding is invalid.")
            selection_id = _bounded_search_text(raw_binding.get("selection_id"), 96)
            selection_digest = _bounded_search_text(raw_binding.get("selection_digest"), 64)
            binding_task_digest = _bounded_search_text(raw_binding.get("task_context_digest"), 64)
            if (
                re.fullmatch(r"prefsel-[a-z0-9][a-z0-9-]{5,80}", selection_id) is None
                or re.fullmatch(r"[0-9a-f]{64}", selection_digest) is None
                or binding_task_digest != task_digest
                or raw_binding.get("skill") != "literature-search"
                or raw_binding.get("operation") != "search"
            ):
                raise SystemExit("Literature search preference selection binding is invalid.")
            binding = {
                "selection_id": selection_id,
                "selection_digest": selection_digest,
                "task_context_digest": binding_task_digest,
                "skill": "literature-search",
                "operation": "search",
            }
        raw_hard_digests = context.get("hard_value_digests")
        if not isinstance(raw_hard_digests, dict):
            raise SystemExit("Literature search hard preference digests are invalid.")
        hard_digests: dict[str, str] = {}
        for path, digest in raw_hard_digests.items():
            if path != "profile.constraints" or re.fullmatch(r"[0-9a-f]{64}", str(digest or "")) is None:
                raise SystemExit("Literature search hard preference digests are invalid.")
            hard_digests[path] = str(digest)
        state["preference_context"] = {
            "task_context_digest": task_digest,
            "selection_binding": binding,
            "hard_value_digests": hard_digests,
        }
    if "budget" in raw:
        state["budget"] = _sanitize_search_budget(raw.get("budget"))
    if "usage" in raw:
        state["usage"] = _sanitize_search_usage(raw.get("usage"))
    if "queries" in raw:
        if not isinstance(raw.get("queries"), list):
            raise SystemExit("Literature search queries must be a list.")
        state["queries"] = [_sanitize_search_query(item) for item in raw["queries"]]
    if "coverage" in raw:
        state["coverage"] = _sanitize_search_coverage(raw.get("coverage"))
    if "frontier" in raw:
        state["frontier"] = _sanitize_search_frontier(raw.get("frontier"))
    if "stop" in raw:
        state["stop"] = _sanitize_search_stop(raw.get("stop"))
    if "partial" in raw:
        if not isinstance(raw.get("partial"), bool):
            raise SystemExit("Literature search partial must be true or false.")
        state["partial"] = raw["partial"]
    effective_mode = str(state.get("mode") or "exploratory")
    _validate_systematic_scope(effective_mode, dict(state.get("scope") or {}))
    return state


def _sanitize_search_identities(raw: Any, *, legacy_candidate: Any = None) -> dict[str, str]:
    identities: dict[str, str] = {}
    if raw not in (None, {}):
        if not isinstance(raw, dict):
            raise SystemExit("Literature search candidate identities must be a mapping.")
        doi = _canonical_search_doi(raw.get("doi"))
        arxiv_id = _canonical_search_arxiv_id(raw.get("arxiv_id"))
        pmid = _canonical_search_pmid(raw.get("pmid"))
        for key, value in (("doi", doi), ("arxiv_id", arxiv_id), ("pmid", pmid)):
            if raw.get(key) not in (None, "") and not value:
                raise SystemExit(f"Literature search candidate {key} is invalid.")
            if value:
                identities[key] = value
    if isinstance(legacy_candidate, dict):
        provenance = legacy_candidate.get("provenance")
        openalex = provenance.get("openalex") if isinstance(provenance, dict) else None
        if isinstance(openalex, dict) and "doi" not in identities:
            legacy_doi = _canonical_search_doi(openalex.get("doi"))
            if legacy_doi:
                identities["doi"] = legacy_doi
    return identities


def _sanitize_search_discoveries(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise SystemExit("Literature search discovered_by must be a list.")
    discoveries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise SystemExit("Literature search discovery entries must be mappings.")
        query_id = _safe_search_id(item.get("query_id"), field="discovery query_id")
        edge_type = _bounded_search_text(item.get("edge_type"), 32) or "direct"
        if edge_type not in {"direct", "reference", "cited_by"}:
            raise SystemExit("Literature search discovery edge_type is not supported.")
        entry: dict[str, Any] = {"query_id": query_id, "edge_type": edge_type}
        for key, limit in (
            ("source_locator", 500),
            ("channel", 128),
            ("tool", 128),
            ("discovered_at", 80),
        ):
            text = _bounded_search_text(item.get(key), limit)
            if text:
                if key == "source_locator":
                    _reject_sensitive_search_text(text, field="discovery source_locator")
                    text = _safe_search_url(text) or text
                entry[key] = text
        parent = _bounded_search_text(item.get("parent_candidate_id"), 128)
        if parent:
            entry["parent_candidate_id"] = _safe_search_id(
                parent, field="discovery parent_candidate_id"
            )
        if edge_type != "direct" and "parent_candidate_id" not in entry:
            raise SystemExit("Citation discovery edges require parent_candidate_id.")
        discoveries.append(entry)
    return discoveries


def _sanitize_search_fetch(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search candidate fetch must be a mapping.")
    status = _bounded_search_text(raw.get("status"), 64)
    if status not in SEARCH_RETRIEVAL_STATUSES:
        raise SystemExit("Literature search candidate fetch status is not supported.")
    result: dict[str, Any] = {"status": status}
    if "attempts" in raw:
        result["attempts"] = _safe_search_int(raw["attempts"], field="candidate.fetch.attempts")
    error_class = _bounded_search_text(raw.get("error_class"), 128)
    if error_class:
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", error_class) is None:
            raise SystemExit("Literature search candidate fetch error_class must be a safe slug.")
        result["error_class"] = error_class
    updated_at = _bounded_search_text(raw.get("updated_at"), 80)
    if updated_at:
        result["updated_at"] = updated_at
    return result


def _sanitize_search_screening(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search candidate screening must be a mapping.")
    decision = _bounded_search_text(raw.get("decision"), 32) or "unassessed"
    if decision not in SEARCH_SCREENING_DECISIONS:
        raise SystemExit("Literature search screening decision is not supported.")
    screening: dict[str, Any] = {"decision": decision}
    if decision == "unassessed":
        return screening
    basis = _bounded_search_text(raw.get("basis"), 32)
    if basis not in {"title", "abstract", "fulltext"}:
        raise SystemExit("Literature search screening requires title, abstract, or fulltext basis.")
    phase = _bounded_search_text(raw.get("phase"), 32)
    if not phase:
        phase = "fulltext" if basis == "fulltext" else "title_abstract"
    if phase not in {"automation", "title_abstract", "fulltext"}:
        raise SystemExit("Literature search screening phase is not supported.")
    if phase == "fulltext" and basis != "fulltext":
        raise SystemExit("Fulltext screening phase requires fulltext evidence basis.")
    if phase != "fulltext" and basis == "fulltext":
        raise SystemExit("Fulltext evidence basis requires fulltext screening phase.")
    rationale = _bounded_search_text(raw.get("rationale"), 1500)
    evidence = raw.get("evidence")
    if not rationale or not isinstance(evidence, list) or not evidence:
        raise SystemExit("Literature search screening requires rationale and evidence.")
    safe_evidence: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise SystemExit("Literature search screening evidence must be a mapping.")
        quote = _bounded_search_text(item.get("quote"), 800)
        locator = _bounded_search_text(item.get("locator"), 500)
        if not quote or not locator:
            raise SystemExit("Literature search screening evidence requires quote and locator.")
        _reject_sensitive_search_text(locator, field="screening evidence locator")
        locator = _safe_search_url(locator) or locator
        safe_evidence.append({"quote": quote, "locator": locator})
    screening.update(
        {"phase": phase, "basis": basis, "rationale": rationale, "evidence": safe_evidence}
    )
    reviewer = _bounded_search_text(raw.get("reviewer"), 128)
    if reviewer:
        screening["reviewer"] = reviewer
    return screening


def _validate_search_timestamp(value: Any, *, field: str) -> str:
    text = _bounded_search_text(value, 80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"Literature search {field} must be an ISO-8601 timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit(f"Literature search {field} must include a timezone.")
    return text


def _sanitize_search_screening_decision(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit("Literature search screening decisions must be mappings.")
    decision_id = _safe_search_id(raw.get("decision_id"), field="screening decision_id")
    reviewer_id = _safe_search_id(raw.get("reviewer_id"), field="screening reviewer_id")
    screening = _sanitize_search_screening(raw)
    if screening.get("decision") == "unassessed":
        raise SystemExit("A per-reviewer screening decision cannot be unassessed.")
    phase = str(screening.get("phase") or "")
    if phase not in SEARCH_REVIEW_PHASES:
        raise SystemExit("Per-reviewer decisions support title_abstract or fulltext phases only.")
    entry: dict[str, Any] = {
        "decision_id": decision_id,
        "reviewer_id": reviewer_id,
        "phase": phase,
        "decision": screening["decision"],
        "basis": screening["basis"],
        "rationale": screening["rationale"],
        "evidence": screening["evidence"],
        "decided_at": _validate_search_timestamp(raw.get("decided_at"), field="decision decided_at"),
    }
    supersedes = _bounded_search_text(raw.get("supersedes_decision_id"), 128)
    if supersedes:
        entry["supersedes_decision_id"] = _safe_search_id(
            supersedes, field="supersedes_decision_id"
        )
    entry["evidence_digest"] = _search_sha256(entry["evidence"])
    entry["decision_digest"] = _search_sha256(entry)
    return entry


def _validate_search_decision_phase_order(decisions: list[dict[str, Any]]) -> None:
    phase_rank = {"title_abstract": 0, "fulltext": 1}
    highest = -1
    for decision in decisions:
        rank = phase_rank.get(str(decision.get("phase") or ""), -1)
        if rank < highest:
            raise SystemExit(
                "Literature search screening decisions cannot return to an earlier phase."
            )
        highest = max(highest, rank)


def _sanitize_search_adjudication(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit("Literature search adjudications must be mappings.")
    adjudication_id = _safe_search_id(raw.get("adjudication_id"), field="adjudication_id")
    phase = _bounded_search_text(raw.get("phase"), 32)
    if phase not in SEARCH_REVIEW_PHASES:
        raise SystemExit("Literature search adjudication phase is not supported.")
    input_ids = _search_string_list(
        raw.get("input_decision_ids"), field="adjudication.input_decision_ids", item_limit=128
    )
    input_ids = [_safe_search_id(item, field="adjudication decision id") for item in input_ids]
    if len(input_ids) < 2:
        raise SystemExit("Literature search adjudication requires at least two input decisions.")
    status = _bounded_search_text(raw.get("status"), 32)
    if status not in {"pending", "resolved"}:
        raise SystemExit("Literature search adjudication status is not supported.")
    result: dict[str, Any] = {
        "adjudication_id": adjudication_id,
        "phase": phase,
        "input_decision_ids": input_ids,
        "status": status,
    }
    if status == "resolved":
        final_decision = _bounded_search_text(raw.get("final_decision"), 32)
        if final_decision not in SEARCH_SCREENING_DECISIONS - {"unassessed"}:
            raise SystemExit("Resolved adjudication requires a final screening decision.")
        resolved_by = _bounded_search_text(raw.get("resolved_by"), 128)
        rationale = _bounded_search_text(raw.get("rationale"), 1500)
        if not resolved_by or not rationale:
            raise SystemExit("Resolved adjudication requires resolved_by and rationale.")
        evidence = raw.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise SystemExit("Resolved adjudication requires evidence.")
        safe_evidence: list[dict[str, str]] = []
        for item in evidence:
            if not isinstance(item, dict):
                raise SystemExit("Adjudication evidence must be a mapping.")
            quote = _bounded_search_text(item.get("quote"), 800)
            locator = _bounded_search_text(item.get("locator"), 500)
            if not quote or not locator:
                raise SystemExit("Adjudication evidence requires quote and locator.")
            _reject_sensitive_search_text(locator, field="adjudication evidence locator")
            safe_evidence.append({"quote": quote, "locator": _safe_search_url(locator) or locator})
        result.update(
            {
                "final_decision": final_decision,
                "resolved_by": resolved_by,
                "rationale": rationale,
                "evidence": safe_evidence,
                "resolved_at": _validate_search_timestamp(
                    raw.get("resolved_at"), field="adjudication resolved_at"
                ),
            }
        )
        if resolved_by == "current-user":
            authorization = _bounded_search_text(raw.get("user_authorization"), 1500)
            authorization_source = _bounded_search_text(raw.get("authorization_source"), 64)
            if not authorization or authorization_source != "user_message":
                raise SystemExit("User adjudication requires current user-message authorization.")
            result["user_authorization"] = authorization
            result["authorization_source"] = authorization_source
    input_digest = _bounded_search_text(raw.get("input_digest"), 64)
    if input_digest:
        if re.fullmatch(r"[0-9a-f]{64}", input_digest) is None:
            raise SystemExit("Literature search adjudication input digest is invalid.")
        result["input_digest"] = input_digest
    return result


def _active_search_decisions(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = [
        item for item in candidate.get("screening_decisions", []) if isinstance(item, dict)
    ]
    by_id = {str(item.get("decision_id") or ""): item for item in decisions}
    if len(by_id) != len(decisions):
        raise SystemExit("Literature search screening decision ids must be unique.")
    superseded: set[str] = set()
    for item in decisions:
        prior_id = str(item.get("supersedes_decision_id") or "")
        if not prior_id:
            continue
        prior = by_id.get(prior_id)
        if prior is None:
            raise SystemExit("Literature search screening supersedes an unknown decision.")
        if (
            prior.get("reviewer_id") != item.get("reviewer_id")
            or prior.get("phase") != item.get("phase")
        ):
            raise SystemExit("A screening decision may supersede only the same reviewer and phase.")
        if prior_id in superseded:
            raise SystemExit("A screening decision cannot be superseded more than once.")
        superseded.add(prior_id)
    active = [item for item in decisions if str(item.get("decision_id") or "") not in superseded]
    keys = [(str(item.get("reviewer_id") or ""), str(item.get("phase") or "")) for item in active]
    if len(keys) != len(set(keys)):
        raise SystemExit("A reviewer may have only one active decision per phase and candidate.")
    return active


def _validate_persisted_multi_reviewer_ledgers(payload: dict[str, Any]) -> None:
    """Re-sanitize append-only ledgers before any resume/terminal derivation."""
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        raw_decisions = candidate.get("screening_decisions", [])
        if raw_decisions not in (None, []) and not isinstance(raw_decisions, list):
            raise SystemExit("Persisted literature screening ledger is invalid.")
        for raw in raw_decisions or []:
            sanitized = _sanitize_search_screening_decision(raw)
            if sanitized != raw:
                raise SystemExit("Persisted literature screening decision digest is stale or invalid.")
        _validate_search_decision_phase_order(raw_decisions or [])
        raw_adjudications = candidate.get("adjudications", [])
        if raw_adjudications not in (None, []) and not isinstance(raw_adjudications, list):
            raise SystemExit("Persisted literature adjudication ledger is invalid.")
        for raw in raw_adjudications or []:
            sanitized = _sanitize_search_adjudication(raw)
            if sanitized != raw:
                raise SystemExit("Persisted literature adjudication is not canonical.")


def _derive_multi_reviewer_screening(
    candidate: dict[str, Any],
    *,
    protocol: dict[str, Any],
    reviewers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required = [str(item) for item in protocol.get("required_reviewer_ids", [])]
    active = _active_search_decisions(candidate)
    for item in active:
        if str(item.get("reviewer_id") or "") not in reviewers:
            raise SystemExit("Literature search decision references an unknown reviewer.")
    phases = [str(item) for item in protocol.get("phases", [])]
    chosen: list[dict[str, Any]] = []
    chosen_phase = ""
    for phase in reversed(phases):
        decisions = [item for item in active if str(item.get("phase") or "") == phase]
        by_reviewer = {str(item.get("reviewer_id") or ""): item for item in decisions}
        if all(reviewer_id in by_reviewer for reviewer_id in required):
            chosen = [by_reviewer[reviewer_id] for reviewer_id in required]
            chosen_phase = phase
            break
    if not chosen:
        return {"status": "incomplete", "decision": "unassessed", "derived_from": []}
    decisions = {str(item.get("decision") or "") for item in chosen}
    decision_ids = [str(item.get("decision_id") or "") for item in chosen]
    if len(decisions) == 1:
        decision = next(iter(decisions))
        result = {
            "status": "consensus",
            "phase": chosen_phase,
            "decision": decision,
            "derived_from": decision_ids,
        }
        result["digest"] = _search_sha256(result)
        return result
    adjudications = [
        item for item in candidate.get("adjudications", []) if isinstance(item, dict)
    ]
    matching = [
        item
        for item in adjudications
        if str(item.get("phase") or "") == chosen_phase
        and set(item.get("input_decision_ids", [])) == set(decision_ids)
    ]
    resolved = [item for item in matching if str(item.get("status") or "") == "resolved"]
    if len(resolved) > 1:
        raise SystemExit("Literature search conflict has multiple resolved adjudications.")
    if not resolved:
        return {
            "status": "conflict",
            "phase": chosen_phase,
            "decision": "unassessed",
            "derived_from": decision_ids,
        }
    adjudication = resolved[0]
    resolved_by = str(adjudication.get("resolved_by") or "")
    if resolved_by != "current-user" and resolved_by not in reviewers:
        raise SystemExit("Literature search adjudication resolver is unknown.")
    adjudication_mode = str(protocol.get("adjudication_mode") or "")
    if adjudication_mode == "user" and resolved_by != "current-user":
        raise SystemExit("User-mode literature adjudication must be resolved by the current user.")
    if adjudication_mode == "third_reviewer":
        if resolved_by == "current-user" or resolved_by in required:
            raise SystemExit("Third-reviewer adjudication requires a distinct reviewer.")
        if str(protocol.get("mode") or "") == "independent":
            resolver_execution = str(reviewers[resolved_by].get("execution_id") or "")
            required_executions = {str(reviewers[item].get("execution_id") or "") for item in required}
            if not resolver_execution or resolver_execution in required_executions:
                raise SystemExit("Independent third-reviewer adjudication requires a distinct execution/context id.")
    input_digest = _search_sha256(chosen)
    if adjudication.get("input_digest") not in (None, "", input_digest):
        raise SystemExit("Literature search adjudication input binding is stale or invalid.")
    result = {
        "status": "adjudicated",
        "phase": chosen_phase,
        "decision": str(adjudication.get("final_decision") or ""),
        "derived_from": [*decision_ids, str(adjudication.get("adjudication_id") or "")],
        "input_digest": input_digest,
    }
    result["digest"] = _search_sha256(result)
    adjudication["input_digest"] = input_digest
    return result


def _validate_multi_reviewer_stage(payload: dict[str, Any]) -> None:
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    screeners = int(scope.get("screeners") or 1)
    protocol = (
        payload.get("review_protocol")
        if isinstance(payload.get("review_protocol"), dict)
        else {}
    )
    reviewer_rows = [item for item in payload.get("reviewers", []) if isinstance(item, dict)]
    if screeners <= 1 and not protocol and not reviewer_rows:
        for candidate in payload.get("candidates", []):
            if isinstance(candidate, dict) and candidate.get("screening_decisions"):
                raise SystemExit("Per-reviewer decisions require a multi-reviewer protocol.")
        return
    required = [str(item) for item in protocol.get("required_reviewer_ids", [])]
    if screeners < 2 or len(required) != screeners:
        raise SystemExit("scope.screeners must match the multi-reviewer protocol.")
    reviewers = {str(item.get("reviewer_id") or ""): item for item in reviewer_rows}
    if len(reviewers) != len(reviewer_rows) or any(item not in reviewers for item in required):
        raise SystemExit("Multi-reviewer protocol references an unknown reviewer.")
    if str(protocol.get("mode") or "") == "independent":
        execution_ids = [str(reviewers[item].get("execution_id") or "") for item in required]
        if any(not execution_id for execution_id in execution_ids) or len(set(execution_ids)) != len(
            execution_ids
        ):
            raise SystemExit(
                "Independent literature reviewers require distinct execution/context ids."
            )
    resolution = " ".join(str(scope.get("disagreement_resolution") or "").casefold().replace("_", " ").replace("-", " ").split())
    adjudication_mode = str(protocol.get("adjudication_mode") or "")
    expected_resolution = "third reviewer" if adjudication_mode == "third_reviewer" else "user"
    if resolution != expected_resolution:
        raise SystemExit("scope.disagreement_resolution must match the review adjudication mode.")
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("screening"):
            screening = candidate.get("screening")
            if (
                isinstance(screening, dict)
                and screening.get("decision") == "exclude"
                and screening.get("phase") == "automation"
            ):
                if candidate.get("screening_decisions") or candidate.get("adjudications"):
                    raise SystemExit("Automation exclusion cannot be mixed with reviewer decisions.")
                effective = {
                    "status": "automation-excluded",
                    "phase": "automation",
                    "decision": "exclude",
                    "derived_from": [],
                    "screening_digest": _search_sha256(screening),
                }
                effective["digest"] = _search_sha256(effective)
                candidate["effective_screening"] = effective
                continue
            if isinstance(screening, dict) and screening.get("decision") not in {None, "", "unassessed"}:
                raise SystemExit("Multi-reviewer search cannot use a legacy single screening.")
            candidate.pop("screening", None)
        decisions = [
            item for item in candidate.get("screening_decisions", []) if isinstance(item, dict)
        ]
        by_id = {str(item.get("decision_id") or ""): item for item in decisions}
        for adjudication in candidate.get("adjudications", []):
            if not isinstance(adjudication, dict):
                continue
            inputs = [str(item) for item in adjudication.get("input_decision_ids", [])]
            if any(item not in by_id for item in inputs):
                raise SystemExit("Literature search adjudication references an unknown decision.")
            if any(str(by_id[item].get("phase") or "") != adjudication.get("phase") for item in inputs):
                raise SystemExit("Literature search adjudication mixes screening phases.")
        candidate["effective_screening"] = _derive_multi_reviewer_screening(
            candidate,
            protocol=protocol,
            reviewers=reviewers,
        )


def _sanitize_search_metadata(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("Literature search candidate metadata must be a mapping.")
    metadata: dict[str, Any] = {}
    for key, limit in (
        ("publication_date", 32),
        ("publication_type", 128),
        ("language", 64),
        ("venue", 300),
    ):
        text = _bounded_search_text(raw.get(key), limit)
        if text:
            metadata[key] = text
    if "publication_year" in raw:
        year = _safe_search_int(raw["publication_year"], field="candidate.metadata.publication_year")
        if year > 9999:
            raise SystemExit("Literature search publication_year is invalid.")
        metadata["publication_year"] = year
    if "is_retracted" in raw:
        if not isinstance(raw.get("is_retracted"), bool):
            raise SystemExit("Literature search is_retracted must be true or false.")
        metadata["is_retracted"] = raw["is_retracted"]
    if "authors" in raw:
        metadata["authors"] = _search_string_list(
            raw.get("authors"), field="candidate.metadata.authors", item_limit=300
        )
    return metadata


def _sanitize_search_candidate(
    raw: Any,
    *,
    stage_id: str,
    index: int,
    allow_local_reference: bool = False,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit("Literature search candidates must be mappings.")
    raw_url = raw.get("url")
    url = _safe_search_url(raw_url)
    if not url and allow_local_reference:
        local_reference = _bounded_search_text(raw_url, 4096)
        if local_reference and not urlparse(local_reference).scheme:
            url = local_reference
    if raw_url not in (None, "") and not url:
        raise SystemExit("Literature search candidate URL must be a safe http(s) URL.")
    if not url:
        raise SystemExit("Literature search candidates require a URL.")
    title = _bounded_search_text(raw.get("title"), 1000)
    candidate_id = _bounded_search_text(raw.get("candidate_id"), 128)
    if candidate_id:
        candidate_id = _safe_search_id(candidate_id, field="candidate_id")
    else:
        seed = title or url or f"{stage_id}:{index}"
        candidate_id = f"{stage_id}-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:8]}"
    candidate_note = _bounded_search_text(raw.get("note"), 2000)
    if candidate_note:
        _reject_sensitive_search_text(candidate_note, field="candidate note")
    candidate: dict[str, Any] = {
        "candidate_id": candidate_id,
        "title": title,
        "url": url,
        "note": candidate_note,
        "topics": _slug_list(raw.get("topics")),
        "tags": _slug_list(raw.get("tags")),
        "pool_hints": _slug_list(raw.get("pool_hints")),
    }
    identities = _sanitize_search_identities(raw.get("identities"))
    if identities:
        candidate["identities"] = identities
    if "discovered_by" in raw:
        candidate["discovered_by"] = _sanitize_search_discoveries(raw.get("discovered_by"))
    if "fetch" in raw:
        candidate["fetch"] = _sanitize_search_fetch(raw.get("fetch"))
    evidence_level = _bounded_search_text(raw.get("evidence_level"), 32)
    if evidence_level:
        if evidence_level not in SEARCH_EVIDENCE_LEVELS:
            raise SystemExit("Literature search candidate evidence_level is not supported.")
        candidate["evidence_level"] = evidence_level
    if "screening" in raw:
        candidate["screening"] = _sanitize_search_screening(raw.get("screening"))
    if "screening_decisions" in raw:
        if not isinstance(raw.get("screening_decisions"), list):
            raise SystemExit("Literature search screening_decisions must be a list.")
        candidate["screening_decisions"] = [
            _sanitize_search_screening_decision(item)
            for item in raw["screening_decisions"]
        ]
        _validate_search_decision_phase_order(candidate["screening_decisions"])
    if "adjudications" in raw:
        if not isinstance(raw.get("adjudications"), list):
            raise SystemExit("Literature search adjudications must be a list.")
        candidate["adjudications"] = [
            _sanitize_search_adjudication(item) for item in raw["adjudications"]
        ]
    if candidate.get("screening") and candidate.get("screening_decisions"):
        raise SystemExit("Use either legacy single screening or per-reviewer decisions, not both.")
    if "metadata" in raw:
        candidate["metadata"] = _sanitize_search_metadata(raw.get("metadata"))
    screening = candidate.get("screening") if isinstance(candidate.get("screening"), dict) else {}
    if screening.get("decision") not in (None, "", "unassessed"):
        level_rank = {"snippet": 0, "title": 1, "abstract": 2, "fulltext": 3}
        evidence_level = str(candidate.get("evidence_level") or "")
        basis = str(screening.get("basis") or "")
        if level_rank.get(evidence_level, -1) < level_rank.get(basis, -1):
            raise SystemExit("Literature search screening basis exceeds the candidate evidence level.")
    for decision in candidate.get("screening_decisions", []):
        level_rank = {"snippet": 0, "title": 1, "abstract": 2, "fulltext": 3}
        evidence_level = str(candidate.get("evidence_level") or "")
        basis = str(decision.get("basis") or "")
        if level_rank.get(evidence_level, -1) < level_rank.get(basis, -1):
            raise SystemExit("Literature search screening basis exceeds the candidate evidence level.")
    return candidate


def _candidate_search_identities(candidate: dict[str, Any]) -> dict[str, str]:
    return _sanitize_search_identities(candidate.get("identities"), legacy_candidate=candidate)


def _candidate_identity_conflicts(existing: dict[str, str], incoming: dict[str, str]) -> bool:
    return any(
        existing.get(key) and incoming.get(key) and existing[key] != incoming[key]
        for key in ("doi", "arxiv_id", "pmid")
    )


def _merge_search_state(payload: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in (
        "entry_skill",
        "mode",
        "scope",
        "run_id",
        "monitor_binding",
        "review_protocol",
        "reviewers",
        "preference_context",
    ):
        if key not in incoming:
            continue
        if key in payload and payload.get(key) not in (None, {}, "") and payload.get(key) != incoming[key]:
            raise SystemExit(f"Literature search {key} cannot change when resuming a stage.")
        payload[key] = incoming[key]

    if "budget" in incoming:
        existing_budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
        for key, value in existing_budget.items():
            if key in incoming["budget"] and incoming["budget"][key] != value:
                raise SystemExit("Literature search budget cannot change when resuming a stage.")
        payload["budget"] = {**incoming["budget"], **existing_budget}

    if "queries" in incoming:
        existing_queries = [item for item in payload.get("queries", []) if isinstance(item, dict)]
        by_id = {str(item.get("query_id") or ""): item for item in existing_queries}
        for event in incoming["queries"]:
            prior = by_id.get(event["query_id"])
            if prior is not None:
                if _freeze_search_value(prior) != _freeze_search_value(event):
                    raise SystemExit("Literature search query_id conflicts with an existing event.")
                continue
            existing_queries.append(event)
            by_id[event["query_id"]] = event
        payload["queries"] = existing_queries

    if "usage" in incoming:
        existing_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        merged_usage = dict(existing_usage)
        for key, value in incoming["usage"].items():
            if value < int(existing_usage.get(key, 0)):
                raise SystemExit("Literature search usage cannot decrease when resuming a stage.")
            merged_usage[key] = value
        payload["usage"] = merged_usage

    if "coverage" in incoming:
        prior_coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        next_coverage = incoming["coverage"]
        prior_round = int(prior_coverage.get("round", 0)) if prior_coverage else 0
        next_round = int(next_coverage.get("round", prior_round)) if next_coverage else prior_round
        if next_round < prior_round:
            raise SystemExit("Literature search coverage round cannot decrease.")
        if prior_coverage and _freeze_search_value(prior_coverage) != _freeze_search_value(next_coverage):
            history = [
                item for item in payload.get("coverage_history", []) if isinstance(item, dict)
            ]
            snapshot = {"replaced_at": utc_now_iso(), "coverage": prior_coverage}
            if not history or _freeze_search_value(history[-1].get("coverage")) != _freeze_search_value(prior_coverage):
                history.append(snapshot)
            payload["coverage_history"] = history
        payload["coverage"] = next_coverage

    if "frontier" in incoming:
        existing_frontier = [
            item for item in payload.get("frontier", []) if isinstance(item, dict)
        ]
        frontier_history = [
            item for item in payload.get("frontier_history", []) if isinstance(item, dict)
        ]

        def frontier_key(item: dict[str, Any]) -> tuple[str, str, str]:
            return (
                str(item.get("candidate_id") or ""),
                str(item.get("direction") or ""),
                str(item.get("parent_candidate_id") or ""),
            )

        by_key = {frontier_key(item): item for item in existing_frontier}
        for action in incoming["frontier"]:
            prior = by_key.get(frontier_key(action))
            if prior is None:
                existing_frontier.append(action)
                by_key[frontier_key(action)] = action
                continue
            if _freeze_search_value(prior) != _freeze_search_value(action):
                prior_status = str(prior.get("status") or "pending")
                next_status = str(action.get("status") or "pending")
                if prior_status in {"expanded", "skipped"} and next_status != prior_status:
                    raise SystemExit("Literature search frontier terminal status cannot regress.")
                frontier_history.append({"replaced_at": utc_now_iso(), "action": dict(prior)})
                prior.clear()
                prior.update(action)
        payload["frontier"] = existing_frontier
        if frontier_history:
            payload["frontier_history"] = frontier_history

    if "stop" in incoming:
        prior_stop = payload.get("stop") if isinstance(payload.get("stop"), dict) else {}
        next_stop = incoming["stop"]
        prior_reason = str(prior_stop.get("reason") or "in_progress")
        next_reason = str(next_stop.get("reason") or "in_progress")
        if prior_reason in {"target_met", "saturated", "budget_exhausted", "user_stop"}:
            if next_reason != prior_reason:
                raise SystemExit(
                    "A completed literature search run cannot be reopened; start a fresh run_id."
                )
        if prior_stop and _freeze_search_value(prior_stop) != _freeze_search_value(next_stop):
            history = [item for item in payload.get("stop_history", []) if isinstance(item, dict)]
            history.append({"replaced_at": utc_now_iso(), "stop": prior_stop})
            payload["stop_history"] = history
        payload["stop"] = next_stop
    if "partial" in incoming:
        payload["partial"] = incoming["partial"]

    mode = str(payload.get("mode") or "exploratory")
    _validate_systematic_scope(mode, dict(payload.get("scope") or {}))
    if payload.get("entry_skill") == "literature-search":
        missing_budget = sorted(SEARCH_BUDGET_FIELDS - set(payload.get("budget") or {}))
        if missing_budget:
            raise SystemExit("Literature search requires all persisted hard-budget fields.")
    queries = [item for item in payload.get("queries", []) if isinstance(item, dict)]
    if mode == "systematic" and any(item.get("reproducible") is not True for item in queries):
        raise SystemExit("Every query event in systematic mode must be reproducible.")
    stop = payload.get("stop") if isinstance(payload.get("stop"), dict) else {}
    partial = payload.get("partial")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    if mode == "bounded-systematic" and partial is not True:
        raise SystemExit("A bounded-systematic literature search must remain partial.")
    if (
        mode != "exploratory"
        and stop.get("reason") not in (None, "", "in_progress", "blocked_no_search_tool")
    ):
        if stop.get("reason") != "user_stop" and not queries:
            raise SystemExit("A terminal systematic search requires at least one query event.")
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        counts = coverage.get("flow_counts") if isinstance(coverage.get("flow_counts"), dict) else {}
        missing_counts = sorted(SEARCH_FLOW_COUNT_FIELDS - set(counts))
        if missing_counts:
            raise SystemExit(
                "A terminal systematic search requires complete screening flow counts."
            )
        if counts:
            identified = int(counts["identified"])
            duplicates = int(counts["duplicates_removed"])
            automated = int(counts["automation_excluded"])
            screened = int(counts["title_abstract_screened"])
            title_excluded = int(counts["title_abstract_excluded"])
            fulltext_sought = int(counts["fulltext_sought"])
            unavailable = int(counts["fulltext_unavailable"])
            assessed = int(counts["fulltext_assessed"])
            excluded = int(counts["excluded_with_reason"])
            included = int(counts["included"])
            if not (
                duplicates + automated + screened == identified
                and title_excluded + fulltext_sought == screened
                and unavailable + assessed == fulltext_sought
                and excluded + included == assessed
            ):
                raise SystemExit("Systematic literature search flow counts are not arithmetically consistent.")
            query_results = sum(int(item.get("result_count", 0)) for item in queries)
            if identified != query_results:
                raise SystemExit(
                    "Systematic literature search identified count must match recorded query results."
                )
    if payload.get("entry_skill") == "literature-search" and int(
        usage.get("queries", 0)
    ) != len(queries):
        raise SystemExit("Literature search usage.queries must match the persisted query count.")
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    usage_to_budget = {
        "queries": "max_queries",
        "candidates_seen": "max_candidates",
        "full_reads": "max_full_reads",
        "citation_hops": "max_citation_hops",
    }
    for usage_key, budget_key in usage_to_budget.items():
        if budget_key in budget and int(usage.get(usage_key, 0)) > int(budget[budget_key]):
            raise SystemExit(f"Literature search {usage_key} exceeds its persisted hard budget.")
    if "max_queries" in budget and len(queries) > int(budget["max_queries"]):
        raise SystemExit("Literature search query events exceed the persisted hard budget.")
    if stop.get("reason") == "budget_exhausted":
        if partial is not True:
            raise SystemExit("A budget-exhausted literature search must remain partial.")
        if not any(
            int(usage.get(usage_key, 0)) >= int(budget.get(budget_key, 1))
            for usage_key, budget_key in usage_to_budget.items()
        ):
            raise SystemExit(
                "Literature search cannot claim budget_exhausted before reaching a hard budget."
            )


def build_search_stage_id(kind: str, query: str) -> str:
    normalized_query = " ".join(str(query or "").split())
    base = slugify(normalized_query, max_words=8) or kind
    short_hash = hashlib.sha1(f"{kind}:{normalized_query}".encode("utf-8")).hexdigest()[:8]
    return f"{kind}-search-{base}-{short_hash}"


def build_literature_search_stage_id(
    query: str,
    *,
    mode: str = "exploratory",
    scope: dict[str, Any] | None = None,
    run_id: str = "",
) -> str:
    normalized_query = " ".join(str(query or "").split())
    safe_mode = _bounded_search_text(mode, 64) or "exploratory"
    if safe_mode not in SEARCH_MODES:
        raise SystemExit("Literature search mode is not supported.")
    safe_scope = _sanitize_search_scope(scope)
    _validate_systematic_scope(safe_mode, safe_scope)
    safe_run_id = _safe_search_id(run_id, field="run_id") if run_id else ""
    base = slugify(normalized_query, max_words=8) or "paper"
    identity = _freeze_search_value(
        {
            "kind": "paper",
            "query": normalized_query,
            "mode": safe_mode,
            "scope": safe_scope,
            "run_id": safe_run_id,
        }
    )
    short_hash = hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:12]
    return f"paper-search-{base}-{short_hash}"


def _safe_search_stage_id(stage_id: str) -> str:
    return _safe_search_id(stage_id, field="stage_id")


def _validate_search_stage_target(project_root: Path, path: Path) -> None:
    expected_root = search_stage_path(project_root, "safe-probe").parent
    if path.parent != expected_root:
        raise SystemExit("Search stage target must stay inside the source-search directory.")
    cursor = kb_root(project_root)
    if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
        raise SystemExit("Search stage directory contains an unsafe path component.")
    for component in ("synthesis", "source-search"):
        cursor = cursor / component
        if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
            raise SystemExit("Search stage directory contains an unsafe path component.")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SystemExit("Search stage target must be a regular file or a missing path.")


def _validate_search_stage_identity(
    existing: Any,
    *,
    stage_id: str,
    source_kind: str,
    query: str,
) -> None:
    if existing in (None, {}, []):
        return
    if not isinstance(existing, dict):
        raise SystemExit("Existing search stage is not a valid mapping.")
    expected = {
        "id": stage_id,
        "kind": "source-search-stage",
        "source_kind": str(source_kind or "").strip(),
        "query": " ".join(str(query or "").split()),
    }
    actual = {
        "id": str(existing.get("id") or "").strip(),
        "kind": str(existing.get("kind") or "").strip(),
        "source_kind": str(existing.get("source_kind") or "").strip(),
        "query": " ".join(str(existing.get("query") or "").split()),
    }
    if actual != expected:
        raise SystemExit("Search stage identity does not match the existing staged query.")


def load_search_stage(project_root: Path, stage_id: str) -> dict[str, Any]:
    safe_stage_id = _safe_search_stage_id(stage_id)
    path = search_stage_path(project_root, safe_stage_id)
    _validate_search_stage_target(project_root, path)
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict) or not payload.get("id"):
        raise SystemExit(f"Search stage not found: {stage_id}")
    return payload


def _exact_search_binding_digest(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _unchanged_stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_node_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _revalidate_search_stage_ancestor_chain(
    root: Path,
    expected: list[tuple[int, int, int]],
) -> None:
    """Prove the lexical root still names the descriptor chain we read."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        try:
            current = os.open(root, flags)
        except OSError as exc:
            raise SystemExit("Literature search stage ancestor chain changed.") from exc
        descriptors.append(current)
        if _directory_node_identity(os.fstat(current)) != expected[0]:
            raise SystemExit("Literature search stage ancestor chain changed.")
        for index, component in enumerate(("synthesis", "source-search"), start=1):
            try:
                metadata = os.stat(component, dir_fd=current, follow_symlinks=False)
                child = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                raise SystemExit("Literature search stage ancestor chain changed.") from exc
            descriptors.append(child)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or _directory_node_identity(metadata) != expected[index]
                or _directory_node_identity(os.fstat(child)) != expected[index]
            ):
                raise SystemExit("Literature search stage ancestor chain changed.")
            current = child
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _anchored_search_stage_bytes(
    project_root: Path,
    *,
    only_stage_id: str = "",
) -> list[tuple[str, bytes]]:
    """Read canonical stage leaves without following any workspace symlink.

    This is a portfolio/status read path, so it deliberately avoids directory
    creation and ordinary path reopenings.  Every accepted leaf is bounded,
    regular, and stable across the descriptor read and lexical re-check.
    """
    # Keep the read path pure for an as-yet uninitialised workspace.  Do not
    # call ``resolve()`` here: it follows a project-root symlink before the
    # descriptor-level ``O_NOFOLLOW`` checks get a chance to reject it.
    root = project_root.absolute()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    ancestor_identities: list[tuple[int, int, int]] = []
    try:
        try:
            current_fd = os.open(root, directory_flags)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise SystemExit("Literature search workspace root is unsafe or unavailable.") from exc
        descriptors.append(current_fd)
        ancestor_identities.append(_directory_node_identity(os.fstat(current_fd)))
        for component in ("synthesis", "source-search"):
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                return []
            except OSError as exc:
                raise SystemExit("Literature search stage directory contains an unsafe component.") from exc
            descriptors.append(next_fd)
            ancestor_identities.append(_directory_node_identity(os.fstat(next_fd)))
            current_fd = next_fd

        results: list[tuple[str, bytes]] = []
        try:
            names = (
                [f"{_safe_search_stage_id(only_stage_id)}.yaml"]
                if only_stage_id
                else sorted(os.listdir(current_fd))
            )
        except OSError as exc:
            raise SystemExit("Literature search stage directory cannot be enumerated safely.") from exc
        for name in names:
            if not name.endswith(".yaml"):
                continue
            stage_id = name[:-5]
            try:
                if _safe_search_stage_id(stage_id) != stage_id:
                    raise SystemExit("Literature search stage filename is not canonical.")
                lexical_before = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                if only_stage_id:
                    return []
                raise SystemExit("Literature search stage leaf changed while enumerating.") from None
            except (OSError, ValueError) as exc:
                raise SystemExit("Literature search stage leaf is unsafe.") from exc
            if not stat.S_ISREG(lexical_before.st_mode):
                raise SystemExit("Literature search stage leaf must be a regular file, not a symlink or special file.")
            if lexical_before.st_size > _SEARCH_STAGE_ENUMERATION_MAX_BYTES:
                raise SystemExit("Literature search stage exceeds the safe read limit.")
            try:
                leaf_fd = os.open(name, file_flags, dir_fd=current_fd)
            except OSError as exc:
                raise SystemExit("Literature search stage leaf cannot be opened safely.") from exc
            try:
                opened_before = os.fstat(leaf_fd)
                if (
                    not stat.S_ISREG(opened_before.st_mode)
                    or _unchanged_stat_identity(opened_before) != _unchanged_stat_identity(lexical_before)
                ):
                    raise SystemExit("Literature search stage leaf changed before reading.")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = os.read(leaf_fd, min(1024 * 1024, _SEARCH_STAGE_ENUMERATION_MAX_BYTES + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _SEARCH_STAGE_ENUMERATION_MAX_BYTES:
                        raise SystemExit("Literature search stage exceeds the safe read limit.")
                    chunks.append(chunk)
                opened_after = os.fstat(leaf_fd)
            finally:
                os.close(leaf_fd)
            try:
                lexical_after = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            except OSError as exc:
                raise SystemExit("Literature search stage leaf changed while reading.") from exc
            expected = _unchanged_stat_identity(opened_before)
            if (
                _unchanged_stat_identity(opened_after) != expected
                or _unchanged_stat_identity(lexical_after) != expected
                or total != opened_after.st_size
            ):
                raise SystemExit("Literature search stage leaf changed while reading.")
            results.append((stage_id, b"".join(chunks)))
        for descriptor, expected in zip(descriptors, ancestor_identities):
            if _directory_node_identity(os.fstat(descriptor)) != expected:
                raise SystemExit("Literature search stage ancestor chain changed while reading.")
        _revalidate_search_stage_ancestor_chain(root, ancestor_identities)
        return results
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _canonical_literature_stage(
    stage_id: str,
    raw_bytes: bytes,
) -> dict[str, Any] | None:
    try:
        decoded = raw_bytes.decode("utf-8")
        payload = yaml.load(decoded, Loader=_UniqueKeySafeLoader)
    except _DuplicateYamlMappingKey as exc:
        raise SystemExit("Literature search stage contains a duplicate mapping key.") from exc
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SystemExit("Literature search stage is not valid UTF-8 YAML.") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Literature search stage must be a mapping.")
    if (
        payload.get("id") != stage_id
        or payload.get("kind") != "source-search-stage"
        or not str(payload.get("source_kind") or "").strip()
    ):
        raise SystemExit("Literature search stage identity is not canonical.")
    if payload.get("entry_skill") != "literature-search":
        return None
    if payload.get("source_kind") != "paper":
        raise SystemExit("A literature-search stage must contain paper candidates.")
    unknown_fields = set(payload) - _LITERATURE_SEARCH_STAGE_TOP_LEVEL_FIELDS
    if unknown_fields:
        raise SystemExit("Literature search stage contains an unknown top-level field.")
    required_fields = {
        "id",
        "kind",
        "status",
        "source_kind",
        "query",
        "note",
        "generated_by",
        "generated_at",
        "entry_skill",
        "mode",
        "budget",
        "usage",
        "queries",
        "candidates",
        "stop",
        "partial",
        "history",
    }
    if required_fields - set(payload):
        raise SystemExit("Literature search stage is missing required canonical fields.")
    if payload.get("status") != "staged" or payload.get("generated_by") != "literature-search":
        raise SystemExit("Literature search stage status or generator is not canonical.")
    query = payload.get("query")
    note = payload.get("note")
    if (
        not isinstance(query, str)
        or not query.strip()
        or " ".join(query.split()) != query
        or len(query) > 4000
        or not isinstance(note, str)
        or _bounded_search_text(note, 2000) != note
    ):
        raise SystemExit("Literature search stage query or note is not canonical.")
    if _validate_search_timestamp(payload.get("generated_at"), field="stage generated_at") != payload.get(
        "generated_at"
    ):
        raise SystemExit("Literature search stage generated_at is not canonical.")

    def exact_history(raw: object, *, label: str) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise SystemExit(f"Literature search {label} must be a list.")
        result: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"timestamp", "action", "summary"}:
                raise SystemExit(f"Literature search {label} is not canonical.")
            timestamp = _validate_search_timestamp(item.get("timestamp"), field=f"{label} timestamp")
            action = _bounded_search_text(item.get("action"), 64)
            summary = _bounded_search_text(item.get("summary"), 2000)
            if action not in {"staged", "candidate-updated"} or not summary:
                raise SystemExit(f"Literature search {label} is not canonical.")
            result.append({"timestamp": timestamp, "action": action, "summary": summary})
        return result

    if exact_history(payload.get("history"), label="stage history") != payload.get("history"):
        raise SystemExit("Literature search stage history is not canonical.")

    def exact_replacement_history(
        raw: object,
        *,
        label: str,
        value_key: str,
        sanitizer,
    ) -> list[dict[str, Any]]:
        if raw in (None, []):
            return []
        if not isinstance(raw, list):
            raise SystemExit(f"Literature search {label} must be a list.")
        result: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"replaced_at", value_key}:
                raise SystemExit(f"Literature search {label} is not canonical.")
            replaced_at = _validate_search_timestamp(
                item.get("replaced_at"), field=f"{label} replaced_at"
            )
            value = item.get(value_key)
            canonical = sanitizer(value)
            if canonical != value:
                raise SystemExit(f"Literature search {label} is not canonical.")
            result.append({"replaced_at": replaced_at, value_key: canonical})
        return result

    def exact_frontier_history_action(value: object) -> dict[str, Any]:
        canonical = _sanitize_search_frontier([value])
        if len(canonical) != 1:
            raise SystemExit("Literature search frontier_history is not canonical.")
        return canonical[0]

    for history_field, value_key, sanitizer in (
        ("coverage_history", "coverage", _sanitize_search_coverage),
        ("frontier_history", "action", exact_frontier_history_action),
        ("stop_history", "stop", _sanitize_search_stop),
    ):
        if history_field in payload and exact_replacement_history(
            payload[history_field],
            label=history_field,
            value_key=value_key,
            sanitizer=sanitizer,
        ) != payload[history_field]:
            raise SystemExit(f"Literature search {history_field} is not canonical.")

    persisted_state = {
        key: copy.deepcopy(payload[key])
        for key in (
            "entry_skill",
            "mode",
            "run_id",
            "monitor_binding",
            "scope",
            "review_protocol",
            "reviewers",
            "preference_context",
        )
        if key in payload
    }
    if _sanitize_search_state(persisted_state) != persisted_state:
        raise SystemExit("Literature search stage state is not canonical.")
    for field, sanitizer in (
        ("budget", _sanitize_search_budget),
        ("usage", _sanitize_search_usage),
        ("coverage", _sanitize_search_coverage),
        ("frontier", _sanitize_search_frontier),
    ):
        if field in payload and sanitizer(payload[field]) != payload[field]:
            raise SystemExit(f"Literature search stage {field} is not canonical.")
    raw_queries = payload.get("queries", [])
    if not isinstance(raw_queries, list):
        raise SystemExit("Literature search stage queries must be a list.")
    canonical_queries = [_sanitize_search_query(item) for item in raw_queries]
    if canonical_queries != raw_queries:
        raise SystemExit("Literature search stage query ledger is not canonical.")
    query_ids = [str(item.get("query_id") or "") for item in canonical_queries]
    if len(query_ids) != len(set(query_ids)):
        raise SystemExit("Literature search stage query ids must be unique.")
    if "partial" in payload and not isinstance(payload.get("partial"), bool):
        raise SystemExit("Literature search stage partial flag must be true or false.")
    stop = payload.get("stop")
    if not isinstance(stop, dict):
        raise SystemExit("Literature search stage has no canonical stop state.")
    stop_reason = str(stop.get("reason") or "")
    if stop_reason not in SEARCH_STOP_REASONS or _sanitize_search_stop(stop) != stop:
        raise SystemExit("Literature search stage stop state is not canonical.")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
        raise SystemExit("Literature search stage candidates are not canonical.")
    candidate_ids: set[str] = set()
    candidate_input_fields = {
        "candidate_id",
        "title",
        "url",
        "note",
        "topics",
        "tags",
        "pool_hints",
        "identities",
        "discovered_by",
        "fetch",
        "evidence_level",
        "screening",
        "screening_decisions",
        "adjudications",
        "metadata",
    }
    candidate_allowed_fields = candidate_input_fields | {
        "status",
        "record_id",
        "screening_history",
        "effective_screening",
        "provenance",
    }
    fulltext_count = 0
    citation_hops = 0
    for index, candidate in enumerate(candidates, start=1):
        if set(candidate) - candidate_allowed_fields:
            raise SystemExit("Literature search candidate contains an unknown field.")
        candidate_id = _safe_search_id(candidate.get("candidate_id"), field="candidate_id")
        if candidate_id in candidate_ids:
            raise SystemExit("Literature search stage candidate ids must be unique.")
        candidate_ids.add(candidate_id)
        identities = candidate.get("identities") if isinstance(candidate.get("identities"), dict) else {}
        status_value = str(candidate.get("status") or "")
        if status_value not in {"staged", "materialized", "duplicate"}:
            raise SystemExit("Literature search stage candidate status is not canonical.")
        record_id = str(candidate.get("record_id") or "")
        if status_value in {"materialized", "duplicate"} and not record_id:
            raise SystemExit("A materialized literature candidate requires a record binding.")
        if status_value == "staged" and record_id:
            raise SystemExit("A staged literature candidate cannot carry a record binding.")
        if record_id:
            _safe_search_id(record_id, field="record_id")
        provenance = candidate.get("provenance")
        legacy_identity_migration = False
        if provenance not in (None, {}):
            if not isinstance(provenance, dict) or set(provenance) != {"openalex"}:
                raise SystemExit("Literature search legacy provenance is not canonical.")
            openalex = provenance.get("openalex")
            if not isinstance(openalex, dict) or set(openalex) not in (
                {"doi"},
                {"work_id", "doi"},
            ):
                raise SystemExit("Literature search legacy provenance is not canonical.")
            if "work_id" in openalex and re.fullmatch(
                r"W[0-9]+", str(openalex.get("work_id") or "")
            ) is None:
                raise SystemExit("Literature search legacy provenance work id is invalid.")
            if not _canonical_search_doi(openalex.get("doi")):
                raise SystemExit("Literature search legacy provenance DOI is invalid.")
            migrated_identities = _candidate_search_identities(candidate)
            legacy_identity_migration = (
                "doi" not in identities
                and migrated_identities
                == {**identities, "doi": _canonical_search_doi(openalex.get("doi"))}
            )
        if _candidate_search_identities(candidate) != identities and not legacy_identity_migration:
            raise SystemExit("Literature search stage candidate identity is not canonical.")
        persisted_candidate = {
            key: copy.deepcopy(value)
            for key, value in candidate.items()
            if key in candidate_input_fields
        }
        sanitized_candidate = _sanitize_search_candidate(
            persisted_candidate,
            stage_id=stage_id,
            index=index,
            allow_local_reference=False,
        )
        if legacy_identity_migration:
            sanitized_candidate["identities"] = copy.deepcopy(
                persisted_candidate.get("identities", {})
            )
        if sanitized_candidate != persisted_candidate:
            raise SystemExit("Literature search stage candidate is not canonical.")
        if not candidate.get("discovered_by"):
            raise SystemExit("Literature search stage candidate has no discovery edge.")
        for discovery in candidate.get("discovered_by", []):
            required_discovery = {
                "query_id",
                "edge_type",
                "source_locator",
                "channel",
                "tool",
                "discovered_at",
            }
            if discovery.get("edge_type") != "direct":
                required_discovery.add("parent_candidate_id")
            if set(discovery) != required_discovery:
                raise SystemExit("Literature search discovery edge is not canonical.")
            if not all(str(discovery.get(key) or "").strip() for key in required_discovery):
                raise SystemExit("Literature search discovery edge is incomplete.")
            _validate_search_timestamp(
                discovery.get("discovered_at"), field="candidate discovery discovered_at"
            )
        fetch = candidate.get("fetch")
        if not isinstance(fetch, dict) or _sanitize_search_fetch(fetch) != fetch:
            raise SystemExit("Literature search candidate fetch is not canonical.")
        if fetch.get("updated_at"):
            _validate_search_timestamp(fetch.get("updated_at"), field="candidate fetch updated_at")
        screening_history = candidate.get("screening_history", [])
        if exact_replacement_history(
            screening_history,
            label="candidate screening_history",
            value_key="screening",
            sanitizer=_sanitize_search_screening,
        ) != screening_history:
            raise SystemExit("Literature search candidate screening history is not canonical.")
        if str(candidate.get("evidence_level") or "") == "fulltext":
            fulltext_count += 1
        for discovery in candidate.get("discovered_by", []):
            if str(discovery.get("query_id") or "") not in set(query_ids):
                raise SystemExit("Literature search discovery references an unknown query event.")
            if discovery.get("edge_type") in {"reference", "cited_by"}:
                citation_hops += 1

    frontier = payload.get("frontier") if isinstance(payload.get("frontier"), list) else []
    for action in frontier:
        if str(action.get("candidate_id") or "") not in candidate_ids:
            raise SystemExit("Literature search frontier references an unknown candidate.")
        parent_id = str(action.get("parent_candidate_id") or "")
        if parent_id and parent_id not in candidate_ids:
            raise SystemExit("Literature search frontier references an unknown parent candidate.")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    if int(usage.get("queries", 0)) < len(raw_queries):
        raise SystemExit("Literature search usage is below the persisted query ledger.")
    if int(usage.get("candidates_seen", 0)) < len(candidates):
        raise SystemExit("Literature search usage is below the persisted candidate ledger.")
    if int(usage.get("full_reads", 0)) < fulltext_count:
        raise SystemExit("Literature search usage is below the persisted fulltext ledger.")
    if int(usage.get("citation_hops", 0)) < citation_hops:
        raise SystemExit("Literature search usage is below the persisted citation ledger.")
    for budget_field, actual in (
        ("max_queries", len(raw_queries)),
        ("max_candidates", len(candidates)),
        ("max_full_reads", fulltext_count),
        ("max_citation_hops", citation_hops),
    ):
        if budget_field in budget and actual > int(budget[budget_field]):
            raise SystemExit("Literature search stage exceeds its persisted hard budget.")

    multi_reviewer = int((payload.get("scope") or {}).get("screeners") or 1) > 1
    if multi_reviewer:
        effective_before = [copy.deepcopy(item.get("effective_screening")) for item in candidates]
        derived = copy.deepcopy(payload)
        _validate_persisted_multi_reviewer_ledgers(derived)
        _validate_multi_reviewer_stage(derived)
        effective_after = [copy.deepcopy(item.get("effective_screening")) for item in derived["candidates"]]
        if effective_after != effective_before:
            raise SystemExit("Literature search effective screening is stale or invalid.")
    else:
        for candidate in candidates:
            screening = candidate.get("screening")
            if not isinstance(screening, dict) or _sanitize_search_screening(screening) != screening:
                raise SystemExit("Literature search candidate screening is not canonical.")
    return payload


def literature_stage_snapshot(project_root: Path, stage_id: str) -> dict[str, Any]:
    """Return one strict stage payload and exact-byte digest from one anchored read."""
    safe_stage_id = _safe_search_stage_id(stage_id)
    rows = _anchored_search_stage_bytes(project_root, only_stage_id=safe_stage_id)
    if len(rows) != 1 or rows[0][0] != safe_stage_id:
        raise SystemExit("Literature search stage does not exist or is unsafe.")
    raw_bytes = rows[0][1]
    payload = _canonical_literature_stage(safe_stage_id, raw_bytes)
    if payload is None:
        raise SystemExit("The selected stage is not owned by literature-search.")
    return {
        "stage_id": safe_stage_id,
        "raw_bytes": raw_bytes,
        "byte_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "payload": payload,
    }


def literature_candidate_semantic_digest(candidate: Mapping[str, object]) -> str:
    """Bind every candidate field except the mutable materialization marker."""
    return _exact_search_binding_digest(
        {
            key: value
            for key, value in candidate.items()
            if key not in {"status", "record_id"}
        }
    )


def literature_search_continuations(
    project_root: Path,
    *,
    excluded_stage_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return safe, content-bound standalone literature continuation facts.

    The projection intentionally omits query text, titles, URLs, notes,
    rationales, and evidence quotes.  Exact bytes and semantic components are
    represented by digests so Agent planning stales on every relevant change.
    """
    excluded = set(excluded_stage_ids or set())
    continuations: list[dict[str, Any]] = []
    for stage_id, raw_bytes in _anchored_search_stage_bytes(project_root):
        payload = _canonical_literature_stage(stage_id, raw_bytes)
        if payload is None or stage_id in excluded or payload.get("monitor_binding"):
            continue
        stop = payload["stop"]
        stop_reason = str(stop.get("reason") or "")
        terminal = stop_reason in _LITERATURE_TERMINAL_STOP_REASONS
        selectable: list[dict[str, Any]] = []
        for candidate in payload["candidates"]:
            multi = int((payload.get("scope") or {}).get("screeners") or 1) > 1
            screening = candidate.get("effective_screening" if multi else "screening")
            screening = screening if isinstance(screening, dict) else {}
            decision = str(screening.get("decision") or "unassessed")
            candidate_status = str(candidate.get("status") or "")
            if decision not in {"include", "maybe"} or candidate_status in {"materialized", "duplicate"}:
                continue
            identity = {
                key: candidate.get(key)
                for key in ("candidate_id", "title", "url", "identities")
            }
            exact_candidate = {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "identity_digest": _exact_search_binding_digest(identity),
                "semantic_digest": literature_candidate_semantic_digest(candidate),
                "screening_decision": decision,
                "screening_status": str(screening.get("status") or ""),
                "screening_phase": str(screening.get("phase") or ""),
                "screening_digest": _exact_search_binding_digest(screening),
                "candidate_status": candidate_status,
                "record_id": str(candidate.get("record_id") or ""),
            }
            exact_candidate["candidate_binding_digest"] = _exact_search_binding_digest(exact_candidate)
            selectable.append(exact_candidate)
        if terminal and not selectable:
            continue
        continuations.append(
            {
                "stage_id": stage_id,
                "path": f"kb/synthesis/source-search/{stage_id}.yaml",
                "stage_byte_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "stop_reason": stop_reason,
                "stop_digest": _exact_search_binding_digest(stop),
                "continuation": "select" if terminal else "resume",
                "candidates": sorted(selectable, key=lambda item: item["candidate_id"]),
            }
        )
    return continuations


def stage_search_results(
    project_root: Path,
    *,
    kind: str,
    query: str,
    candidates: list[dict[str, Any]],
    stage_id: str = "",
    note: str = "",
    search_state: dict[str, Any] | None = None,
) -> Path:
    sanitized_state = _sanitize_search_state(search_state)
    if sanitized_state.get("entry_skill") == "literature-search" and not isinstance(query, str):
        raise SystemExit("Literature search requires a textual original research question.")
    normalized_query = " ".join(str(query or "").split())
    current_stage_id = (
        _safe_search_stage_id(stage_id)
        if stage_id
        else build_search_stage_id(kind, normalized_query)
    )
    if not isinstance(note, str):
        raise SystemExit("Search stage note must be text.")
    sanitized_note = _bounded_search_text(note, 2000)
    if sanitized_note:
        _reject_sensitive_search_text(sanitized_note, field="note")
    allow_local_reference = sanitized_state.get("entry_skill") != "literature-search"
    sanitized_candidates = [
        _sanitize_search_candidate(
            candidate,
            stage_id=current_stage_id,
            index=index,
            allow_local_reference=allow_local_reference,
        )
        for index, candidate in enumerate(candidates, start=1)
    ]
    if not allow_local_reference and any(
        not candidate.get("discovered_by") for candidate in sanitized_candidates
    ):
        raise SystemExit("Literature search candidates require at least one discovery edge.")
    path = search_stage_path(project_root, current_stage_id)
    _validate_search_stage_target(project_root, path)
    existing = load_yaml(path, default={})
    _validate_search_stage_identity(
        existing,
        stage_id=current_stage_id,
        source_kind=kind,
        query=normalized_query,
    )
    _stage_search_results_unlocked(
        project_root,
        path=path,
        current_stage_id=current_stage_id,
        kind=kind,
        query=normalized_query,
        candidates=copy.deepcopy(sanitized_candidates),
        note=sanitized_note,
        search_state=sanitized_state,
        validate_only=True,
    )
    ensure_workspace(project_root)

    def validate_locked_identity() -> None:
        _validate_search_stage_target(project_root, path)
        _validate_search_stage_identity(
            load_yaml(path, default={}),
            stage_id=current_stage_id,
            source_kind=kind,
            query=normalized_query,
        )
        _stage_search_results_unlocked(
            project_root,
            path=path,
            current_stage_id=current_stage_id,
            kind=kind,
            query=normalized_query,
            candidates=copy.deepcopy(sanitized_candidates),
            note=sanitized_note,
            search_state=sanitized_state,
            validate_only=True,
        )

    with mutation_transaction(
        project_root,
        "stage_search_results",
        [path],
        preflight=validate_locked_identity,
    ):
        return _stage_search_results_unlocked(
            project_root,
            path=path,
            current_stage_id=current_stage_id,
            kind=kind,
            query=normalized_query,
            candidates=sanitized_candidates,
            note=sanitized_note,
            search_state=sanitized_state,
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
    search_state: dict[str, Any],
    validate_only: bool = False,
) -> Path:
    existing = load_yaml(path, default={})
    if not isinstance(existing, dict):
        existing = {}
    _validate_persisted_multi_reviewer_ledgers(existing)
    existing_stop = existing.get("stop") if isinstance(existing.get("stop"), dict) else {}
    if (
        existing.get("entry_skill") == "literature-search"
        and existing_stop.get("reason")
        in {"target_met", "saturated", "budget_exhausted", "user_stop"}
        and (candidates or search_state)
    ):
        raise SystemExit(
            "A completed literature search run cannot be resumed; start a fresh run_id."
        )
    payload = _deep_fill_missing(
        existing,
        {
            "id": current_stage_id,
            "kind": "source-search-stage",
            "status": "staged",
            "source_kind": kind,
            "query": query,
            "note": note,
            "generated_by": (
                "literature-search"
                if search_state.get("entry_skill") == "literature-search"
                else "source-intake"
            ),
            "generated_at": utc_now_iso(),
            "candidates": [],
            "history": [],
        },
    )
    _merge_search_state(payload, search_state)
    existing_candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
    payload["candidates"] = existing_candidates
    known_urls: dict[str, dict[str, Any]] = {}
    known_candidate_ids = {str(item.get("candidate_id") or ""): item for item in existing_candidates}
    known_identities: dict[str, dict[str, dict[str, Any]]] = {
        "doi": {},
        "arxiv_id": {},
        "pmid": {},
    }

    def register_identity(
        mapping: dict[str, dict[str, Any]],
        identity: str,
        candidate: dict[str, Any],
    ) -> None:
        if not identity:
            return
        prior = mapping.get(identity)
        if prior is not None and prior is not candidate:
            raise SystemExit("Search candidate identities conflict within the existing stage.")
        mapping[identity] = candidate

    for item in existing_candidates:
        existing_url = _search_stage_locator(item.get("url"))
        register_identity(known_urls, existing_url, item)
        for key, value in _candidate_search_identities(item).items():
            register_identity(known_identities[key], value, item)

    if payload.get("entry_skill") == "literature-search":
        # Query text is not evidence for semantic classification.  The runtime
        # Agent may supply topics/tags explicitly after reading the candidate.
        query_topics, query_tags = [], []
    else:
        query_topics, query_tags = infer_topics_and_tags(query, project_root=project_root)
    for index, candidate in enumerate(candidates, start=1):
        url = candidate["url"]
        title = candidate["title"]
        candidate_id = candidate["candidate_id"]
        identities = _candidate_search_identities(candidate)
        identity_matches = [
            match
            for match in (
                known_candidate_ids.get(candidate_id),
                known_identities["doi"].get(identities.get("doi", "")),
                known_identities["arxiv_id"].get(identities.get("arxiv_id", "")),
                known_identities["pmid"].get(identities.get("pmid", "")),
                known_urls.get(url),
            )
            if match is not None
        ]
        unique_matches = {id(match): match for match in identity_matches}
        if len(unique_matches) > 1:
            raise SystemExit("Search candidate identities conflict within the existing stage.")
        existing_candidate = next(iter(unique_matches.values()), None)
        if existing_candidate is not None:
            existing_identities = _candidate_search_identities(existing_candidate)
            if _candidate_identity_conflicts(existing_identities, identities):
                raise SystemExit("Search candidate carries conflicting strong identities.")
            existing_url = _search_stage_locator(existing_candidate.get("url"))
            shared_strong_identity = any(
                existing_identities.get(key)
                and existing_identities.get(key) == identities.get(key)
                for key in ("doi", "arxiv_id", "pmid")
            )
            matched_by_candidate_id = known_candidate_ids.get(candidate_id) is existing_candidate
            if matched_by_candidate_id and existing_url and existing_url != url and not shared_strong_identity:
                raise SystemExit("Search candidate_id cannot be reused for a different unresolved URL.")
            if title:
                existing_candidate["title"] = title
            existing_candidate["url"] = url
            known_urls[url] = existing_candidate
            if identities:
                merged_identities = {**existing_identities, **identities}
                existing_candidate["identities"] = merged_identities
                for key, value in merged_identities.items():
                    register_identity(known_identities[key], value, existing_candidate)
            if candidate.get("discovered_by"):
                prior_discoveries = [
                    item
                    for item in existing_candidate.get("discovered_by", [])
                    if isinstance(item, dict)
                ]
                seen_discoveries = {_freeze_search_value(item) for item in prior_discoveries}
                for discovery in candidate["discovered_by"]:
                    frozen = _freeze_search_value(discovery)
                    if frozen not in seen_discoveries:
                        prior_discoveries.append(discovery)
                        seen_discoveries.add(frozen)
                existing_candidate["discovered_by"] = prior_discoveries
            if candidate.get("fetch"):
                prior_fetch = existing_candidate.get("fetch")
                if isinstance(prior_fetch, dict):
                    prior_attempts = int(prior_fetch.get("attempts", 0))
                    next_attempts = int(candidate["fetch"].get("attempts", prior_attempts))
                    if next_attempts < prior_attempts:
                        raise SystemExit("Literature search fetch attempts cannot decrease.")
                    prior_status = str(prior_fetch.get("status") or "")
                    next_status = str(candidate["fetch"].get("status") or "")
                    if prior_status in {"fetched", "staged", "failed_terminal"}:
                        if prior_status in {"fetched", "failed_terminal"} or next_status != "fetched":
                            candidate["fetch"]["status"] = prior_status
                existing_candidate["fetch"] = candidate["fetch"]
            if candidate.get("evidence_level"):
                level_rank = {"snippet": 0, "title": 1, "abstract": 2, "fulltext": 3}
                prior_level = str(existing_candidate.get("evidence_level") or "")
                next_level = str(candidate["evidence_level"])
                if level_rank.get(next_level, -1) >= level_rank.get(prior_level, -1):
                    existing_candidate["evidence_level"] = next_level
            if candidate.get("screening"):
                prior_screening = existing_candidate.get("screening")
                prior_decision = (
                    str(prior_screening.get("decision") or "unassessed")
                    if isinstance(prior_screening, dict)
                    else "unassessed"
                )
                next_decision = str(candidate["screening"].get("decision") or "unassessed")
                if not (prior_decision != "unassessed" and next_decision == "unassessed"):
                    if (
                        isinstance(prior_screening, dict)
                        and prior_screening
                        and _freeze_search_value(prior_screening)
                        != _freeze_search_value(candidate["screening"])
                    ):
                        history = [
                            item
                            for item in existing_candidate.get("screening_history", [])
                            if isinstance(item, dict)
                        ]
                        history.append({"replaced_at": utc_now_iso(), "screening": prior_screening})
                        existing_candidate["screening_history"] = history
                    existing_candidate["screening"] = candidate["screening"]
            if candidate.get("screening_decisions"):
                if existing_candidate.get("screening"):
                    raise SystemExit("Legacy screening cannot be mixed with a multi-reviewer ledger.")
                decisions = [
                    item
                    for item in existing_candidate.get("screening_decisions", [])
                    if isinstance(item, dict)
                ]
                by_id = {str(item.get("decision_id") or ""): item for item in decisions}
                for decision in candidate["screening_decisions"]:
                    decision_id = str(decision.get("decision_id") or "")
                    prior = by_id.get(decision_id)
                    if prior is not None:
                        if _freeze_search_value(prior) != _freeze_search_value(decision):
                            raise SystemExit("Literature search decision_id conflicts with existing history.")
                        continue
                    decisions.append(decision)
                    by_id[decision_id] = decision
                _validate_search_decision_phase_order(decisions)
                existing_candidate["screening_decisions"] = decisions
            if candidate.get("adjudications"):
                adjudications = [
                    item
                    for item in existing_candidate.get("adjudications", [])
                    if isinstance(item, dict)
                ]
                by_id = {
                    str(item.get("adjudication_id") or ""): item for item in adjudications
                }
                for adjudication in candidate["adjudications"]:
                    adjudication_id = str(adjudication.get("adjudication_id") or "")
                    prior = by_id.get(adjudication_id)
                    if prior is not None:
                        prior_semantic = {key: value for key, value in prior.items() if key != "input_digest"}
                        incoming_semantic = {
                            key: value for key, value in adjudication.items() if key != "input_digest"
                        }
                        if _freeze_search_value(prior_semantic) != _freeze_search_value(incoming_semantic):
                            raise SystemExit(
                                "Literature search adjudication_id conflicts with existing history."
                            )
                        continue
                    adjudications.append(adjudication)
                    by_id[adjudication_id] = adjudication
                existing_candidate["adjudications"] = adjudications
            if candidate.get("metadata"):
                prior_metadata = existing_candidate.get("metadata")
                if not isinstance(prior_metadata, dict):
                    prior_metadata = {}
                existing_candidate["metadata"] = {**prior_metadata, **candidate["metadata"]}
            for list_key, fallback in (
                ("topics", query_topics),
                ("tags", query_tags),
                ("pool_hints", []),
            ):
                incoming_values = candidate.get(list_key) or fallback
                if incoming_values:
                    existing_candidate[list_key] = sorted(
                        set(_slug_list(existing_candidate.get(list_key))) | set(_slug_list(incoming_values))
                    )
            continue

        new_candidate = {
            **candidate,
            "status": "staged",
            "note": candidate.get("note", ""),
            "topics": candidate.get("topics") or _slug_list(query_topics),
            "tags": candidate.get("tags") or _slug_list(query_tags),
            "pool_hints": candidate.get("pool_hints") or [],
            "fetch": candidate.get("fetch") or {"status": "staged", "attempts": 0},
            "screening": candidate.get("screening") or {"decision": "unassessed"},
        }
        if candidate.get("screening_decisions"):
            new_candidate.pop("screening", None)
        payload["candidates"].append(new_candidate)
        known_urls[url] = new_candidate
        known_candidate_ids[candidate_id] = new_candidate
        for key, value in identities.items():
            register_identity(known_identities[key], value, new_candidate)

    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    if "max_candidates" in budget and len(payload["candidates"]) > int(budget["max_candidates"]):
        raise SystemExit("Literature search candidate count exceeds its persisted hard budget.")
    _validate_multi_reviewer_stage(payload)
    persisted_query_ids = {
        str(item.get("query_id") or "")
        for item in payload.get("queries", [])
        if isinstance(item, dict)
    }
    candidate_ids = {
        str(item.get("candidate_id") or "")
        for item in payload["candidates"]
        if isinstance(item, dict)
    }
    citation_edges = 0
    discovery_occurrences = 0
    discovery_occurrences_by_query: dict[str, int] = {}
    fulltext_candidates = 0
    for candidate in payload["candidates"]:
        if payload.get("entry_skill") == "literature-search" and not candidate.get("discovered_by"):
            raise SystemExit("Literature search candidates require at least one discovery edge.")
        if str(candidate.get("evidence_level") or "") == "fulltext":
            fulltext_candidates += 1
        for discovery in candidate.get("discovered_by", []):
            if (
                isinstance(discovery, dict)
                and str(discovery.get("query_id") or "") not in persisted_query_ids
            ):
                raise SystemExit("Literature search discovery references an unknown query event.")
            if not isinstance(discovery, dict):
                continue
            discovery_occurrences += 1
            discovery_query_id = str(discovery.get("query_id") or "")
            discovery_occurrences_by_query[discovery_query_id] = (
                discovery_occurrences_by_query.get(discovery_query_id, 0) + 1
            )
            if discovery.get("edge_type") in {"reference", "cited_by"}:
                citation_edges += 1
                if str(discovery.get("parent_candidate_id") or "") not in candidate_ids:
                    raise SystemExit(
                        "Literature search citation discovery references an unknown parent candidate."
                    )
    for action in payload.get("frontier", []):
        if not isinstance(action, dict):
            continue
        if str(action.get("candidate_id") or "") not in candidate_ids:
            raise SystemExit("Literature search frontier references an unknown candidate.")
        parent_id = str(action.get("parent_candidate_id") or "")
        if parent_id and parent_id not in candidate_ids:
            raise SystemExit("Literature search frontier references an unknown parent candidate.")
    if payload.get("entry_skill") == "literature-search":
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        if int(usage.get("candidates_seen", 0)) < len(payload["candidates"]):
            raise SystemExit(
                "Literature search usage.candidates_seen cannot be below the persisted candidate count."
            )
        if int(usage.get("full_reads", 0)) < fulltext_candidates:
            raise SystemExit(
                "Literature search usage.full_reads cannot be below the persisted fulltext count."
            )
        if int(usage.get("citation_hops", 0)) < citation_edges:
            raise SystemExit(
                "Literature search usage.citation_hops cannot be below the persisted citation edge count."
            )
        if "max_full_reads" in budget and fulltext_candidates > int(budget["max_full_reads"]):
            raise SystemExit("Literature search fulltext candidates exceed the persisted hard budget.")
        if "max_citation_hops" in budget and citation_edges > int(budget["max_citation_hops"]):
            raise SystemExit("Literature search citation edges exceed the persisted hard budget.")
        stop = payload.get("stop") if isinstance(payload.get("stop"), dict) else {}
        mode = str(payload.get("mode") or "exploratory")
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        counts = coverage.get("flow_counts") if isinstance(coverage.get("flow_counts"), dict) else {}
        if mode != "exploratory" and stop.get("reason") not in (None, "", "in_progress") and counts:
            if int(counts.get("identified", 0)) != int(usage.get("candidates_seen", 0)):
                raise SystemExit(
                    "Systematic literature search identified count must match usage.candidates_seen."
                )
            included_candidates = 0
            assessed_fulltext_candidates = 0
            title_abstract_excluded_candidates = 0
            automation_excluded_candidates = 0
            unavailable_fulltext_candidates = 0
            for candidate in payload["candidates"]:
                multi = int((payload.get("scope") or {}).get("screeners") or 1) > 1
                screening_key = "effective_screening" if multi else "screening"
                screening = candidate.get(screening_key) if isinstance(candidate.get(screening_key), dict) else {}
                decision = str(screening.get("decision") or "unassessed")
                phase = str(screening.get("phase") or "")
                if multi and str(screening.get("status") or "") in {"incomplete", "conflict"}:
                    raise SystemExit(
                        "Terminal multi-reviewer search requires complete screening and adjudication."
                    )
                if decision == "include":
                    if phase != "fulltext":
                        raise SystemExit(
                            "Terminal systematic inclusion requires a fulltext screening decision."
                        )
                    included_candidates += 1
                if decision in {"include", "exclude"} and phase == "fulltext":
                    assessed_fulltext_candidates += 1
                if decision == "exclude" and phase == "title_abstract":
                    title_abstract_excluded_candidates += 1
                if decision == "exclude" and phase == "automation":
                    automation_excluded_candidates += 1
                fetch = candidate.get("fetch") if isinstance(candidate.get("fetch"), dict) else {}
                if fetch.get("status") == "failed_terminal":
                    unavailable_fulltext_candidates += 1
            expected_candidates = int(counts.get("identified", 0)) - int(
                counts.get("duplicates_removed", 0)
            )
            if len(payload["candidates"]) != expected_candidates:
                raise SystemExit(
                    "Systematic literature search candidate ledger must cover every non-duplicate result."
                )
            if discovery_occurrences != int(counts.get("identified", 0)):
                raise SystemExit(
                    "Systematic literature search discovery ledger must cover every identified result."
                )
            for query_event in payload.get("queries", []):
                if not isinstance(query_event, dict):
                    continue
                query_id = str(query_event.get("query_id") or "")
                if discovery_occurrences_by_query.get(query_id, 0) != int(
                    query_event.get("result_count", 0)
                ):
                    raise SystemExit(
                        "Systematic literature search discovery occurrences must match each query result count."
                    )
            if int(counts.get("duplicates_removed", 0)) != discovery_occurrences - len(
                payload["candidates"]
            ):
                raise SystemExit(
                    "Systematic literature search duplicate count must match discovery occurrences."
                )
            if int(counts.get("included", 0)) != included_candidates:
                raise SystemExit(
                    "Systematic literature search included count must match persisted screening decisions."
                )
            if int(counts.get("fulltext_assessed", 0)) != assessed_fulltext_candidates:
                raise SystemExit(
                    "Systematic literature search fulltext assessed count must match persisted screening decisions."
                )
            if int(counts.get("title_abstract_excluded", 0)) != title_abstract_excluded_candidates:
                raise SystemExit(
                    "Systematic literature search title/abstract exclusions must match persisted screening decisions."
                )
            if int(counts.get("automation_excluded", 0)) != automation_excluded_candidates:
                raise SystemExit(
                    "Systematic literature search automation exclusions must match persisted screening decisions."
                )
            if int(counts.get("fulltext_unavailable", 0)) != unavailable_fulltext_candidates:
                raise SystemExit(
                    "Systematic literature search unavailable fulltexts must match terminal fetch failures."
                )
            if int(usage.get("full_reads", 0)) < int(counts.get("fulltext_assessed", 0)):
                raise SystemExit(
                    "Systematic literature search fulltext assessments exceed recorded full reads."
                )
    payload["history"].append(
        {
            "timestamp": utc_now_iso(),
            "action": "staged",
            "summary": (
                f"Captured {len(candidates)} candidate inputs; "
                f"the stage now holds {len(payload['candidates'])}."
            ),
        }
    )
    payload["generated_at"] = utc_now_iso()
    if validate_only:
        return path
    _validate_search_stage_target(project_root, path)
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
    safe_stage_id = _safe_search_stage_id(stage_id)
    path = search_stage_path(project_root, safe_stage_id)
    _validate_search_stage_target(project_root, path)

    def validate_locked_target() -> None:
        _validate_search_stage_target(project_root, path)

    with mutation_transaction(
        project_root,
        "mark_search_candidate",
        [path],
        preflight=validate_locked_target,
    ):
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
        _validate_search_stage_target(project_root, path)
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


# --- arxiv source resolution (docs/DESIGN.md, "数据模型": HTML-first) -----

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


# --- PDF parsing (docs/DESIGN.md, "Runtime bootstrap": PyMuPDF4LLM) --------


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


def _pdf_metadata(
    project_root: Path,
    pdf_path: Path,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
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
    richer: dict[str, Any] = {}
    try:
        richer = extract_pdf_record(pdf_path, project_root=project_root)
    except (OSError, RuntimeError, UnicodeError, ValueError):
        richer = {}
    return {
        "title": str(richer.get("title") or title),
        "authors": [str(item) for item in richer.get("authors", []) if str(item).strip()],
        "abstract": str(richer.get("abstract") or _abstract_from_text(first_page)),
        "year": richer.get("year") or year,
        "arxiv_id": str(richer.get("arxiv_id") or arxiv_id or ""),
        "doi": str(richer.get("doi") or ""),
        "venue": "",
        "bibtex": {
            "entry_type": "misc",
            "venue_field": "",
            "volume": "",
            "number": "",
            "pages": "",
            "publisher": "",
            "primary_class": "",
        },
    }


# --- HTML sections (.agents/lib/research/SCHEMAS.md#evidence-claims) ---------


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
    verification treats them as HTML section/anchor locators per
    `.agents/lib/research/SCHEMAS.md#evidence-claims`. Falls
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


class _CitationMetaParser(HTMLParser):
    """Collect repeated scholarly ``<meta>`` facts without interpreting prose."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        fields = {str(key).casefold(): str(value or "") for key, value in attrs}
        name = (fields.get("name") or fields.get("property") or "").strip().casefold()
        content = clean_text(fields.get("content") or "")
        if name and content:
            self.values.setdefault(name, []).append(content)


def _html_metadata(html: str) -> dict[str, Any]:
    parser = _CitationMetaParser()
    try:
        parser.feed(html)
    except (UnicodeError, ValueError):
        parser = _CitationMetaParser()

    def first(*names: str) -> str:
        for name in names:
            values = parser.values.get(name.casefold(), [])
            if values:
                return values[0]
        return ""

    title = ""
    title_match = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", html)
    if title_match:
        title = clean_text(html_to_text(title_match.group(1)))
    abstract = ""
    abs_match = re.search(r"""(?is)<blockquote[^>]*class=["'][^"']*abstract[^"']*["'][^>]*>(.*?)</blockquote>""", html)
    if abs_match:
        abstract = re.sub(r"(?i)^abstract[:.\-\s]*", "", clean_text(html_to_text(abs_match.group(1))))[:2000]
    title = first("citation_title", "dc.title") or title
    abstract = first("citation_abstract", "description", "dc.description") or abstract
    publication = first("citation_publication_date", "citation_date", "dc.date")
    year_match = re.search(r"\b(19|20)\d{2}\b", publication)
    venue = first("citation_journal_title", "citation_conference_title")
    entry_type = (
        "article"
        if first("citation_journal_title")
        else "inproceedings"
        if first("citation_conference_title")
        else "misc"
    )
    first_page = first("citation_firstpage")
    last_page = first("citation_lastpage")
    pages = f"{first_page}--{last_page}" if first_page and last_page else first_page or last_page
    return {
        "title": title,
        "authors": list(parser.values.get("citation_author", [])),
        "abstract": abstract[:2000],
        "year": int(year_match.group(0)) if year_match else None,
        "arxiv_id": first("citation_arxiv_id"),
        "doi": first("citation_doi"),
        "venue": venue,
        "bibtex": {
            "entry_type": entry_type,
            "venue_field": (
                "journal"
                if entry_type == "article"
                else "booktitle"
                if entry_type == "inproceedings"
                else ""
            ),
            "volume": first("citation_volume"),
            "number": first("citation_issue"),
            "pages": pages,
            "publisher": first("citation_publisher"),
        },
    }


# --- parse-cache writer + source-record projection --------------------------

# Only keys in the on-disk source contract (SCHEMAS.md) belong in record.source;
# status/warning/locator metadata travel via the return value + stderr + parse-cache.
SOURCE_RECORD_KEYS = (
    "original_uri",
    "source_origin",
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


def _source_path_reference(
    project_root: Path,
    path: Path,
    *,
    staging_root: Path | None = None,
) -> str:
    """Encode canonical refs as ``kb/...`` and private staging refs locally."""

    if staging_root is None:
        return rel(project_root, path)
    base = staging_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("private source staging path escaped its owned root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("private source staging path is not canonical")
    return relative.as_posix()


def _source_reference_path(
    project_root: Path,
    value: Any,
    *,
    staging_root: Path | None = None,
) -> Path:
    """Resolve one path emitted by :func:`_source_path_reference`."""

    text = str(value or "").strip()
    relative = Path(text)
    if (
        not text
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("source archive reference is not canonical")
    if staging_root is not None:
        base = staging_root.resolve(strict=True)
        candidate = base.joinpath(*relative.parts)
        try:
            candidate.resolve(strict=False).relative_to(base)
        except ValueError as exc:
            raise ValueError("private source archive reference escaped staging") from exc
        return candidate
    if text.startswith("kb/"):
        return logical_ref_to_physical_path(
            workspace_root_roles(project_root).roots,
            text,
        )
    return kb_root(project_root).joinpath(*relative.parts)


def _scoped_materialization_source_fields(
    project_root: Path,
    result: dict[str, Any],
    *,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    if staging_root is None:
        return materialization_source_fields(project_root, result)

    def encode(value: Any) -> str:
        return _source_path_reference(
            project_root,
            Path(value),
            staging_root=staging_root,
        )

    materialization = {
        "schema": MATERIALIZATION_SCHEMA,
        "status": str(result["status"]),
        "converter": str(result["converter"]),
        "converter_version": str(result["converter_version"]),
        "source_map_path": encode(result["source_map_path"]),
        "conversion_path": encode(result["conversion_path"]),
        "asset_paths": [encode(path) for path in result.get("asset_paths", [])],
    }
    archive_path = result.get("archive_path")
    if isinstance(archive_path, Path):
        materialization["archive_path"] = encode(archive_path)
        materialization["archive_hash"] = str(result.get("archive_hash") or "")
    return {
        "markdown_path": encode(result["document_path"]),
        "markdown_hash": str(result["document_hash"]),
        "materialization": materialization,
    }


def _attach_materialization(
    project_root: Path,
    source_info: dict[str, Any],
    result: dict[str, Any],
    *,
    staging_root: Path | None = None,
) -> None:
    """Attach additive source fields and archived paths without hiding degradation."""
    source_info.update(
        _scoped_materialization_source_fields(
            project_root,
            result,
            staging_root=staging_root,
        )
    )
    existing = [str(item) for item in source_info.get("backup_paths", [])]
    for path in materialization_paths(result):
        relative = _source_path_reference(
            project_root,
            path,
            staging_root=staging_root,
        )
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
    and adds ``source_type`` / ``locator_kind`` so downstream evidence under
    `.agents/lib/research/SCHEMAS.md#evidence-claims` can tell PDF (page=N) from HTML
    (section/anchor). Returns None when nothing
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


def _source_selection_attempt(edition: str, rationale: str) -> str:
    """Return one bounded, de-sensitive source-selection audit line."""
    safe_edition = re.sub(r"[^a-z0-9-]+", "-", str(edition).strip().lower()).strip("-")[:40]
    safe_rationale = clean_text(str(rationale or "selection failed"))
    safe_rationale = re.sub(r"(?i)https?://\S+", "[source]", safe_rationale)
    safe_rationale = safe_rationale.replace("\x00", "")[:220].rstrip()
    return f"{safe_edition or 'source'}: {safe_rationale or 'selection failed'}"


def _source_selection_error_rationale(prefix: str, exc: Exception) -> str:
    error_class = re.sub(r"[^A-Za-z0-9]+", "-", exc.__class__.__name__).strip("-").lower()
    return f"{prefix} ({error_class or 'error'})"


def _html_media_counts(materialized: dict[str, Any]) -> tuple[int, int, int]:
    quality = materialized.get("quality") if isinstance(materialized.get("quality"), dict) else {}
    output = quality.get("output") if isinstance(quality.get("output"), dict) else {}

    def count(key: str) -> int:
        value = output.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    return (
        count("source_image_count"),
        count("localized_image_count"),
        count("image_localization_failure_count"),
    )


def _arxiv_html_media_rejection(materialized: dict[str, Any]) -> str:
    source_count, localized_count, failure_count = _html_media_counts(materialized)
    if source_count >= 4 and failure_count * 2 >= source_count:
        return (
            "media localization rejected "
            f"({failure_count}/{source_count} failed; {localized_count} localized)"
        )
    return ""


def _rebase_candidate_source_info(
    project_root: Path,
    source_info: dict[str, Any],
    *,
    staged_root: Path,
    source_root: Path,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Rebase project-relative paths owned by one chosen scratch candidate."""
    rebased = dict(source_info)
    staged_root_resolved = staged_root.resolve()

    def rebase_path(value: Any) -> str:
        absolute = _source_reference_path(
            project_root,
            value,
            staging_root=staging_root,
        ).resolve()
        try:
            relative = absolute.relative_to(staged_root_resolved)
        except ValueError:
            return str(value)
        return _source_path_reference(
            project_root,
            source_root / relative,
            staging_root=staging_root,
        )

    rebased["backup_paths"] = [rebase_path(item) for item in source_info.get("backup_paths", [])]
    if str(source_info.get("markdown_path") or "").strip():
        rebased["markdown_path"] = rebase_path(source_info["markdown_path"])
    materialization = source_info.get("materialization")
    if isinstance(materialization, dict):
        rebound = dict(materialization)
        for key in ("source_map_path", "conversion_path", "archive_path"):
            if str(materialization.get(key) or "").strip():
                rebound[key] = rebase_path(materialization[key])
        rebound["asset_paths"] = [
            rebase_path(item) for item in materialization.get("asset_paths", [])
        ]
        rebased["materialization"] = rebound
    return rebased


def _backup_arxiv_html(
    project_root: Path,
    root: Path,
    arxiv_id: str,
    original_source: str,
    *,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Download quality-gated HTML, then PDF, then an abstract-only page."""
    txt = root / "source-url.txt"
    write_text_if_changed(txt, original_source.strip() + "\n")
    backup_paths = [
        _source_path_reference(project_root, txt, staging_root=staging_root)
    ]
    abs_uri = f"https://arxiv.org/abs/{arxiv_id}"
    attempts: list[str] = []
    for candidate in _arxiv_html_candidates(arxiv_id):
        url = candidate["url"]
        try:
            content, content_type = fetch_url(url, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                _source_selection_attempt(
                    candidate["edition"], _source_selection_error_rationale("fetch failed", exc)
                )
            )
            continue
        raw_bytes = content if isinstance(content, bytes) else str(content).encode("utf-8")
        if isinstance(content, bytes):
            html, source_encoding, decode_warning = _decode_source_text(content, content_type)
        else:
            html, source_encoding, decode_warning = str(content), "utf-8", ""
        if not _is_html_response(content_type, html):
            attempts.append(
                _source_selection_attempt(candidate["edition"], "response was not HTML")
            )
            continue
        quality = inspect_html_quality(html, require_full_text=True)
        if decode_warning:
            quality["warnings"] = [*quality.get("warnings", []), decode_warning]
        if not quality["accepted"]:
            reason = "; ".join(str(item) for item in quality["rejection_reasons"])
            attempts.append(
                _source_selection_attempt(
                    candidate["edition"], f"quality gate rejected: {reason}"
                )
            )
            continue
        chunks = _html_to_section_chunks(html)
        if not chunks:
            attempts.append(
                _source_selection_attempt(candidate["edition"], "parsed to zero section chunks")
            )
            continue
        with tempfile.TemporaryDirectory(
            prefix=f".{root.name}-{candidate['edition']}-", dir=root.parent
        ) as temporary:
            staged_root = Path(temporary)
            staged_raw = _store_bytes(staged_root, "source.html", raw_bytes)
            materialized = _materialize_safely(
                lambda: materialize_html(
                    staged_root,
                    staged_raw,
                    html,
                    source_uri=abs_uri,
                    resolved_url=url,
                    fetch_image=fetch_url,
                    initial_quality=quality,
                ),
                source_root=staged_root,
                raw_path=staged_raw,
                source_type="html",
                source_uri=abs_uri,
            )
            media_rejection = _arxiv_html_media_rejection(materialized)
            if media_rejection:
                attempts.append(
                    _source_selection_attempt(candidate["edition"], media_rejection)
                )
                continue
            publish_source_candidate(staged_root, root)
            materialized = rebase_materialization_result(
                materialized, staged_root, root
            )
        raw = root / "source.html"
        result: dict[str, Any] = {
            "original_uri": abs_uri,
            "backup_paths": [
                *backup_paths,
                _source_path_reference(project_root, raw, staging_root=staging_root),
            ],
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
        _attach_materialization(
            project_root,
            result,
            materialized,
            staging_root=staging_root,
        )
        if result.get("backup_warning"):
            _warn(result["backup_warning"], abs_uri)
        result["source_selection_attempts"] = attempts
        return result

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    try:
        pdf_content, pdf_content_type = fetch_url(pdf_url, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES)
    except Exception as exc:  # noqa: BLE001
        attempts.append(
            _source_selection_attempt(
                "arxiv-pdf", _source_selection_error_rationale("fetch failed", exc)
            )
        )
    else:
        pdf_bytes = pdf_content if isinstance(pdf_content, bytes) else str(pdf_content).encode("utf-8")
        if not _looks_like_pdf(pdf_url, pdf_content_type, pdf_bytes):
            attempts.append(_source_selection_attempt("arxiv-pdf", "response was not PDF"))
        else:
            with tempfile.TemporaryDirectory(
                prefix=f".{root.name}-arxiv-pdf-", dir=root.parent
            ) as temporary:
                staged_root = Path(temporary)
                result = _backup_pdf_bytes(
                    project_root,
                    staged_root,
                    pdf_bytes,
                    abs_uri,
                    backup_kind="url",
                    extra_backup_paths=backup_paths,
                    staging_root=staging_root,
                )
                publish_source_candidate(staged_root, root)
                result = _rebase_candidate_source_info(
                    project_root,
                    result,
                    staged_root=staged_root,
                    source_root=root,
                    staging_root=staging_root,
                )
            result["resolved_url"] = pdf_url
            result["source_selection_attempts"] = attempts
            return result

    abstract_url = abs_uri
    try:
        abstract_response = fetch_url(
            abstract_url, binary=True, max_bytes=SOURCE_DOWNLOAD_MAX_BYTES
        )
    except Exception as exc:  # noqa: BLE001
        attempts.append(
            _source_selection_attempt(
                "arxiv-abs", _source_selection_error_rationale("fetch failed", exc)
            )
        )
    else:
        content, content_type = abstract_response
        raw_bytes = content if isinstance(content, bytes) else str(content).encode("utf-8")
        if isinstance(content, bytes):
            html, source_encoding, decode_warning = _decode_source_text(content, content_type)
        else:
            html, source_encoding, decode_warning = str(content), "utf-8", ""
        if not _is_html_response(content_type, html):
            attempts.append(_source_selection_attempt("arxiv-abs", "response was not HTML"))
        else:
            quality = inspect_html_quality(html)
            if quality["accepted"]:
                quality["warnings"] = [
                    *[str(item) for item in quality.get("warnings", [])],
                    *([decode_warning] if decode_warning else []),
                    "Full-text HTML and PDF were unavailable; archived abstract page only",
                ]
                chunks = _html_to_section_chunks(html)
                with tempfile.TemporaryDirectory(
                    prefix=f".{root.name}-arxiv-abs-", dir=root.parent
                ) as temporary:
                    staged_root = Path(temporary)
                    staged_raw = _store_bytes(staged_root, "source.html", raw_bytes)
                    materialized = _materialize_safely(
                        lambda: materialize_html(
                            staged_root,
                            staged_raw,
                            html,
                            source_uri=abs_uri,
                            resolved_url=abstract_url,
                            fetch_image=fetch_url,
                            initial_quality=quality,
                        ),
                        source_root=staged_root,
                        raw_path=staged_raw,
                        source_type="html",
                        source_uri=abs_uri,
                    )
                    publish_source_candidate(staged_root, root)
                    materialized = rebase_materialization_result(
                        materialized, staged_root, root
                    )
                raw = root / "source.html"
                result = {
                    "original_uri": abs_uri,
                    "backup_paths": [
                        *backup_paths,
                        _source_path_reference(
                            project_root,
                            raw,
                            staging_root=staging_root,
                        ),
                    ],
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
                _attach_materialization(
                    project_root,
                    result,
                    materialized,
                    staging_root=staging_root,
                )
                _warn(result["backup_warning"], abs_uri)
                return result
            attempts.append(
                _source_selection_attempt(
                    "arxiv-abs",
                    "quality gate rejected: "
                    + "; ".join(str(item) for item in quality["rejection_reasons"]),
                )
            )

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
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Persist PDF bytes + real sha256 and parse to page chunks (page=N locators)."""
    raw = _store_bytes(root, file_name, data)
    backup_paths = list(extra_backup_paths or [])
    backup_paths.append(
        _source_path_reference(project_root, raw, staging_root=staging_root)
    )
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
            "PDF stored with real bytes+sha256 but not parsed: PyMuPDF4LLM backend unavailable. "
            "The managed runtime prepares this backend automatically on the next kb command; "
            "retry the same intake afterwards (retry is safe), or run kb doctor to check readiness."
        )
        _warn(result["backup_warning"], original_uri)
    elif not chunks:
        result["backup_status"] = "stored-unparsed"
        result["backup_warning"] = "PDF stored with real bytes+sha256 but PyMuPDF4LLM extracted no text (scanned/image-only?)."
        _warn(result["backup_warning"], original_uri)
    else:
        result["parse_metadata"] = _pdf_metadata(project_root, raw, chunks)
    if materialized is not None:
        _attach_materialization(
            project_root,
            result,
            materialized,
            staging_root=staging_root,
        )
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
    *,
    staging_root: Path | None = None,
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
    archived_paths = [
        *backup_paths,
        _source_path_reference(
            project_root,
            resolved_receipt,
            staging_root=staging_root,
        ),
        _source_path_reference(project_root, raw, staging_root=staging_root),
    ]
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
    _attach_materialization(
        project_root,
        result,
        materialized,
        staging_root=staging_root,
    )
    if result.get("backup_warning"):
        _warn(str(result["backup_warning"]), original_uri)
    return result, ""


def _backup_generic_url(
    project_root: Path,
    root: Path,
    source: str,
    *,
    kind: str,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Non-arxiv URL: real download, PDF->page chunks, HTML->section chunks."""
    original_uri = normalize_remote_url(source)
    txt = root / "source-url.txt"
    write_text_if_changed(txt, source.strip() + "\n")
    backup_paths = [
        _source_path_reference(project_root, txt, staging_root=staging_root)
    ]
    dataset_adapter_warning = ""
    if kind == "dataset":
        adapted, dataset_adapter_warning = _backup_huggingface_dataset_card(
            project_root,
            root,
            source,
            original_uri,
            backup_paths,
            staging_root=staging_root,
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
        return _backup_pdf_bytes(
            project_root,
            root,
            data,
            original_uri,
            backup_kind="url",
            extra_backup_paths=backup_paths,
            staging_root=staging_root,
        )

    html, source_encoding, decode_warning = _decode_source_text(data, content_type)
    if _is_html_response(content_type, html):
        raw = _store_bytes(root, "source.html", data)
        backup_paths.append(
            _source_path_reference(project_root, raw, staging_root=staging_root)
        )
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
        _attach_materialization(
            project_root,
            result,
            materialized,
            staging_root=staging_root,
        )
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
        backup_paths.append(
            _source_path_reference(project_root, raw, staging_root=staging_root)
        )
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
        _attach_materialization(
            project_root,
            result,
            materialized,
            staging_root=staging_root,
        )
        if result.get("backup_warning"):
            _warn(str(result["backup_warning"]), original_uri)
        return result

    raw = _store_bytes(root, "source.bin", data)
    backup_paths.append(
        _source_path_reference(project_root, raw, staging_root=staging_root)
    )
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


def _backup_local(
    project_root: Path,
    root: Path,
    source: str,
    *,
    staging_root: Path | None = None,
) -> dict[str, Any]:
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
        return {
            "original_uri": src.as_posix(),
            "backup_paths": [
                _source_path_reference(project_root, dst, staging_root=staging_root)
            ],
            "backup_kind": "directory",
            "file_hash": "",
            "backup_status": "ok",
            "source_type": "directory",
            "locator_kind": "",
        }
    _copy_regular_file_no_links(src, dst)
    result: dict[str, Any] = {
        "original_uri": src.as_posix(),
        "backup_paths": [
            _source_path_reference(project_root, dst, staging_root=staging_root)
        ],
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
            result["backup_warning"] = (
                "Local PDF stored with real sha256 but not parsed: PyMuPDF4LLM backend unavailable. "
                "The managed runtime prepares this backend automatically on the next kb command; "
                "retry the same intake afterwards (retry is safe), or run kb doctor to check readiness."
            )
            _warn(result["backup_warning"], src.as_posix())
        elif not chunks:
            result["backup_status"] = "stored-unparsed"
            result["backup_warning"] = "Local PDF stored with real sha256 but PyMuPDF4LLM extracted no text (scanned/image-only?)."
            _warn(result["backup_warning"], src.as_posix())
        else:
            result["parse_metadata"] = _pdf_metadata(project_root, dst, chunks)
        if materialized is not None:
            _attach_materialization(
                project_root,
                result,
                materialized,
                staging_root=staging_root,
            )
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
        _attach_materialization(
            project_root,
            result,
            materialized,
            staging_root=staging_root,
        )
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


def source_backup_error(
    project_root: Path,
    kind: str,
    source_info: dict[str, Any],
    *,
    staging_root: Path | None = None,
) -> str:
    """Return why a staged source is not ready for canonical materialization."""
    status = str(source_info.get("backup_status") or "").strip()
    if status not in {"ok", "degraded"}:
        return str(source_info.get("backup_warning") or f"source backup status is {status or 'missing'}")
    backup_paths = [str(item).strip() for item in source_info.get("backup_paths", []) if str(item).strip()]
    if not backup_paths:
        return "source backup produced no archived paths"
    missing_paths = [
        item
        for item in backup_paths
        if not _source_reference_path(
            project_root,
            item,
            staging_root=staging_root,
        ).exists()
    ]
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
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Project staged backup paths onto their post-materialization unit paths."""
    rebased = dict(source_info)
    staged_unit_root = from_unit_dir.resolve()

    def rebase_path(item: Any) -> str:
        archived = _source_reference_path(
            project_root,
            item,
            staging_root=staging_root,
        ).resolve()
        try:
            relative = archived.relative_to(staged_unit_root)
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
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Archive a source as real bytes + real sha256, returning an explicit status.

    Dispatch (`docs/DESIGN.md`, "数据模型";
    `.agents/lib/research/SCHEMAS.md#evidence-claims`):
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
        destination_unit.relative_to(
            (staging_root if staging_root is not None else kb_root(project_root)).resolve()
        )
    except ValueError as exc:
        raise SystemExit(
            f"Source transaction destination escaped its owned data root: {destination_unit}"
        ) from exc
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
            return _backup_arxiv_html(
                project_root,
                root,
                arxiv_id,
                source,
                staging_root=staging_root,
            )
        return _backup_generic_url(
            project_root,
            root,
            source,
            kind=kind,
            staging_root=staging_root,
        )
    # A bare arxiv id (not a URL, not an existing local path) is still an arxiv source.
    arxiv_id = _arxiv_id_from_source(source)
    if arxiv_id and resolve_local_reference(project_root, normalize_storage_reference(project_root, source)) is None:
        maybe_local = Path(normalize_storage_reference(project_root, source)).expanduser()
        if not maybe_local.exists():
            return _backup_arxiv_html(
                project_root,
                root,
                arxiv_id,
                source,
                staging_root=staging_root,
            )
    return _backup_local(
        project_root,
        root,
        source,
        staging_root=staging_root,
    )


def _record_blocks_source_retry(project_root: Path, record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").strip().lower()
    confirmation_status = str(record.get("confirmation_status") or "").strip().lower()
    if status in {"failed", "failed_retryable", "rejected", "archived"} or confirmation_status == "rejected":
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
    existing: list[Path] = []
    for item in backup_paths:
        try:
            candidate = _source_reference_path(project_root, item)
        except (SystemExit, ValueError):
            continue
        if candidate.exists() and not candidate.is_symlink():
            existing.append(candidate)
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
    source_origin: str = "",
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
        if source_origin and str(record_source.get("source_origin") or "") != source_origin:
            continue
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
    "literature_stage_snapshot",
    "literature_candidate_semantic_digest",
    "literature_search_continuations",
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

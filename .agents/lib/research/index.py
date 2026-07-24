"""Governance catalogs, KB index build, linting, search, and id-compaction maintenance."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .common import (
    ensure_dir,
    infer_topics_and_tags,
    load_yaml,
    normalize_ref_key,
    parse_wikilinks,
    program_root as common_program_root,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_duplicate_key_issues,
)
from .ids import (
    UNIT_KIND_PREFIXES,
    canonical_unit_id,
    canonical_unit_id_with_hash,
    is_canonical_unit_id,
)
from .retrieval import (
    extract_parse_cache_passages,
    extract_record_passages,
    passage_result,
    rank_passages,
    rank_records,
    tokenize_query,
)
from .paths import (
    TEXT_REWRITE_SUFFIXES,
    UNIT_KIND_DIRS,
    _deep_fill_missing,
    _slug_list,
    _text_list,
    _unique_text_list,
    candidate_pools_path,
    config_root,
    kb_root,
    passage_search_cache_path,
    record_path,
    rel,
    synthesis_root,
    topic_taxonomy_path,
    unit_root,
)
from .records import (
    INFORMATION_TYPES,
    MATURITY_LEVELS,
    _extract_unit_id_hash,
    append_history,
    default_record,
    iter_records,
    locate_record,
    normalize_record_schema,
    record_summary,
    trusted_claim_source_roots,
)
from .evidence import (
    confirmation_claims,
    record_external_source_contract,
    verification_receipt_violations,
)
from .journal import incomplete_ops
from .git_ops import dirty_kb_paths, kb_repo_exists
from .prefs import (
    DEFAULT_CANDIDATE_POOLS,
    DEFAULT_TOPIC_TAXONOMY,
    ensure_workspace,
)
from .confirm import (
    confirmation_track,
    has_complete_confirmation_receipt,
    validate_write,
    write_record,
)

STATUS_VALUES = {
    "draft",
    "screened",
    "pending",
    "active",
    "selected",
    "rejected",
    "archived",
    "planned",
    "running",
    "completed",
    "failed",
}


CONFIRMATION_VALUES = {"auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"}

PASSAGE_INDEX_REVISION = "passages-v2"
PASSAGE_SEARCH_LIMIT = 5


class PassageCacheError(RuntimeError):
    """A derived passage cache could not be rebuilt safely."""

AUDIT_CATEGORIES = ("schema", "integrity", "recovery", "security", "quality")
AUDIT_SEVERITIES = ("error", "warning", "info")
_AUDIT_INTERNAL_DIRS = {".git", ".journal", ".runtime"}
_AUDIT_GIT_EXCLUDED_PREFIXES = (".journal/", ".runtime/", "raw/", "output/", "user/kb/")


def load_topic_taxonomy(project_root: Path) -> dict[str, Any]:
    payload = load_yaml(topic_taxonomy_path(project_root), default={})
    if not isinstance(payload, dict):
        payload = {}
    normalized = _deep_fill_missing(payload, {**DEFAULT_TOPIC_TAXONOMY, "generated_at": utc_now_iso()})
    topics: dict[str, Any] = {}
    for key, item in normalized.get("topics", {}).items():
        topic = slugify(str(item.get("id") or key), max_words=12)
        if not topic:
            continue
        topics[topic] = {
            "id": topic,
            "aliases": _slug_list(item.get("aliases")),
            "tags": _slug_list(item.get("tags")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": _text_list(item.get("member_ids")),
            "count": int(item.get("count") or 0),
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    tags: dict[str, Any] = {}
    for key, item in normalized.get("tags", {}).items():
        tag = slugify(str(item.get("id") or key), max_words=12)
        if not tag:
            continue
        tags[tag] = {
            "id": tag,
            "aliases": _slug_list(item.get("aliases")),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": _text_list(item.get("member_ids")),
            "count": int(item.get("count") or 0),
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    normalized["topics"] = {key: topics[key] for key in sorted(topics)}
    normalized["tags"] = {key: tags[key] for key in sorted(tags)}
    normalized["generated_at"] = utc_now_iso()
    return normalized


def write_topic_taxonomy(project_root: Path, payload: dict[str, Any]) -> Path:
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(topic_taxonomy_path(project_root), payload)
    return topic_taxonomy_path(project_root)


def load_candidate_pools(project_root: Path) -> dict[str, Any]:
    payload = load_yaml(candidate_pools_path(project_root), default={})
    if not isinstance(payload, dict):
        payload = {}
    normalized = _deep_fill_missing(payload, {**DEFAULT_CANDIDATE_POOLS, "generated_at": utc_now_iso()})
    pools: dict[str, Any] = {}
    for key, item in normalized.get("pools", {}).items():
        pool = slugify(str(item.get("id") or key), max_words=12)
        if not pool:
            continue
        pools[pool] = {
            "id": pool,
            "summary": str(item.get("summary") or "").strip(),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "tags": _slug_list(item.get("tags")),
            "member_ids": _text_list(item.get("member_ids")),
            "kinds": _slug_list(item.get("kinds")),
            "status": str(item.get("status") or "active"),
        }
    normalized["pools"] = {key: pools[key] for key in sorted(pools)}
    normalized["generated_at"] = utc_now_iso()
    return normalized


def write_candidate_pools(project_root: Path, payload: dict[str, Any]) -> Path:
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(candidate_pools_path(project_root), payload)
    return candidate_pools_path(project_root)


def apply_record_governance(
    project_root: Path,
    record: dict[str, Any],
    *,
    explicit_topics: list[str] | None = None,
    explicit_tags: list[str] | None = None,
    explicit_pools: list[str] | None = None,
    infer_missing: bool = True,
    source_label: str = "",
) -> dict[str, Any]:
    normalized = normalize_record_schema(record)
    signal_text = " ".join(
        [
            str(normalized.get("title") or ""),
            str(normalized.get("summary") or ""),
            str(normalized.get("source", {}).get("original_uri") or ""),
            str(normalized.get("payload", {}).get("basic_info", {}).get("title") or ""),
            str(normalized.get("payload", {}).get("basic_info", {}).get("name") or ""),
        ]
    ).strip()
    inferred_topics, inferred_tags = ([], [])
    if infer_missing and signal_text:
        inferred_topics, inferred_tags = infer_topics_and_tags(signal_text, project_root=project_root)
    topic_sources = list(normalized.get("taxonomy", {}).get("topic_sources", []))
    tag_sources = list(normalized.get("taxonomy", {}).get("tag_sources", []))
    pool_sources = list(normalized.get("taxonomy", {}).get("pool_sources", []))
    topics = set(normalized.get("topics", []))
    tags = set(normalized.get("tags", []))
    pools = set(normalized.get("candidate_pools", []))
    for item in explicit_topics or []:
        topic = slugify(str(item), max_words=12)
        if topic:
            topics.add(topic)
    for item in explicit_tags or []:
        tag = slugify(str(item), max_words=12)
        if tag:
            tags.add(tag)
    for item in explicit_pools or []:
        pool = slugify(str(item), max_words=12)
        if pool:
            pools.add(pool)
    for item in inferred_topics:
        topic = slugify(str(item), max_words=12)
        if topic:
            topics.add(topic)
    for item in inferred_tags:
        tag = slugify(str(item), max_words=12)
        if tag:
            tags.add(tag)
    if explicit_topics or inferred_topics:
        topic_sources.append(source_label or ("manual" if explicit_topics else "inferred"))
    if explicit_tags or inferred_tags:
        tag_sources.append(source_label or ("manual" if explicit_tags else "inferred"))
    if explicit_pools:
        pool_sources.append(source_label or "manual")
    normalized["topics"] = sorted(topics)
    normalized["tags"] = sorted(tags)
    normalized["candidate_pools"] = sorted(pools)
    taxonomy = normalized.get("taxonomy", {})
    primary_topic = normalized["topics"][0] if normalized["topics"] else ""
    taxonomy["primary_topic"] = primary_topic
    taxonomy["secondary_topics"] = [topic for topic in normalized["topics"] if topic != primary_topic]
    taxonomy["canonical_tags"] = list(normalized["tags"])
    taxonomy["topic_sources"] = sorted(set(_text_list(topic_sources)))
    taxonomy["tag_sources"] = sorted(set(_text_list(tag_sources)))
    taxonomy["pool_sources"] = sorted(set(_text_list(pool_sources)))
    normalized["taxonomy"] = taxonomy
    return normalized


def _unit_id_slug_ref_key(unit_id: str) -> str:
    parts = unit_id.split("-")
    if len(parts) < 3 or parts[0] not in set(UNIT_KIND_PREFIXES.values()):
        return ""
    if not re.fullmatch(r"[0-9a-f]{6,40}", parts[-1]):
        return ""
    return normalize_ref_key("-".join(parts[1:-1]))


def _record_wikilink_ref_keys(record: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    unit_id = str(record.get("id") or "")
    for value in [unit_id, _unit_id_slug_ref_key(unit_id), str(record.get("title") or "")]:
        key = normalize_ref_key(value)
        if key:
            keys.add(key)
    for legacy_id in _unique_text_list(record.get("legacy_ids")):
        for value in [legacy_id, _unit_id_slug_ref_key(legacy_id)]:
            key = normalize_ref_key(value)
            if key:
                keys.add(key)
    return keys


def _unit_markdown_paths(project_root: Path, record: dict[str, Any]) -> list[Path]:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    if kind not in UNIT_KIND_DIRS or not unit_id:
        return []
    root = unit_root(project_root, kind, unit_id)
    if _path_has_symlink_component(project_root, root) or not root.is_dir():
        return []
    paths = _safe_files_below(root, suffixes={".md", ".markdown"})
    excluded_parts = {"source", "raw", "output", "obsidian", ".runtime", ".journal", ".git"}
    readable: list[Path] = []
    for path in paths:
        relative_parts = path.relative_to(root).parts
        if relative_parts == ("source", "document.md"):
            readable.append(path)
            continue
        if excluded_parts.intersection(relative_parts):
            continue
        readable.append(path)
    return readable


def _wikilink_target_exists(project_root: Path, target: str, ref_keys: set[str]) -> bool:
    candidates = [target.strip(), normalize_ref_key(target)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            locate_record(project_root, candidate, fuzzy=False)
            return True
        except SystemExit:
            pass
    return normalize_ref_key(target) in ref_keys


def refresh_record_schemas(project_root: Path, *, unit_ids: list[str] | None = None, kind: str | None = None) -> list[Path]:
    ensure_workspace(project_root)
    paths: list[Path] = []
    if unit_ids:
        for unit_id in unit_ids:
            record, _ = locate_record(project_root, unit_id)
            paths.append(write_record(project_root, record))
        return paths
    for record in iter_records(project_root, kind=kind):
        paths.append(write_record(project_root, record))
    return paths


def _has_declared_members(item: dict[str, Any]) -> bool:
    return bool(_text_list(item.get("member_ids"))) or int(item.get("count") or 0) > 0


def _preserve_empty_governance_seeds(taxonomy: dict[str, Any], pools: dict[str, Any], existing_taxonomy: dict[str, Any], existing_pools: dict[str, Any]) -> None:
    for topic, item in existing_taxonomy.get("topics", {}).items():
        if topic in taxonomy["topics"] or _has_declared_members(item):
            continue
        taxonomy["topics"][topic] = {
            "id": topic,
            "aliases": _slug_list(item.get("aliases")),
            "tags": _slug_list(item.get("tags")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": [],
            "count": 0,
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    for tag, item in existing_taxonomy.get("tags", {}).items():
        if tag in taxonomy["tags"] or _has_declared_members(item):
            continue
        taxonomy["tags"][tag] = {
            "id": tag,
            "aliases": _slug_list(item.get("aliases")),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": [],
            "count": 0,
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    for pool, item in existing_pools.get("pools", {}).items():
        if pool in pools["pools"] or _has_declared_members(item):
            continue
        pools["pools"][pool] = {
            "id": pool,
            "summary": str(item.get("summary") or "").strip(),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "tags": _slug_list(item.get("tags")),
            "member_ids": [],
            "kinds": [],
            "status": str(item.get("status") or "active"),
        }


def rebuild_governance_catalogs(project_root: Path, *, records: list[dict[str, Any]] | None = None) -> tuple[Path, Path]:
    ensure_workspace(project_root)
    records = records if records is not None else iter_records(project_root)
    existing_taxonomy = load_topic_taxonomy(project_root)
    existing_pools = load_candidate_pools(project_root)
    taxonomy = {**existing_taxonomy, "topics": {}, "tags": {}}
    pools = {**existing_pools, "pools": {}}

    for record in records:
        unit_id = str(record.get("id") or "")
        record_tags = _slug_list(record.get("tags"))
        record_topics = _slug_list(record.get("topics"))
        record_pools = _slug_list(record.get("candidate_pools"))
        for topic in record_topics:
            base = existing_taxonomy.get("topics", {}).get(topic, {})
            item = taxonomy["topics"].setdefault(
                topic,
                {
                    "id": topic,
                    "aliases": _slug_list(base.get("aliases")),
                    "tags": [],
                    "pools": [],
                    "member_ids": [],
                    "count": 0,
                    "note": str(base.get("note") or "").strip(),
                    "status": str(base.get("status") or "active"),
                },
            )
            item["count"] += 1
            item["member_ids"] = sorted(set(item["member_ids"]) | {unit_id})
            item["tags"] = sorted(set(item["tags"]) | set(record_tags))
            item["pools"] = sorted(set(item["pools"]) | set(record_pools))
        for tag in record_tags:
            base = existing_taxonomy.get("tags", {}).get(tag, {})
            item = taxonomy["tags"].setdefault(
                tag,
                {
                    "id": tag,
                    "aliases": _slug_list(base.get("aliases")),
                    "topic_hints": [],
                    "pools": [],
                    "member_ids": [],
                    "count": 0,
                    "note": str(base.get("note") or "").strip(),
                    "status": str(base.get("status") or "active"),
                },
            )
            item["count"] += 1
            item["member_ids"] = sorted(set(item["member_ids"]) | {unit_id})
            item["topic_hints"] = sorted(set(item["topic_hints"]) | set(record_topics))
            item["pools"] = sorted(set(item["pools"]) | set(record_pools))
        for pool in record_pools:
            base = existing_pools.get("pools", {}).get(pool, {})
            item = pools["pools"].setdefault(
                pool,
                {
                    "id": pool,
                    "summary": str(base.get("summary") or "").strip(),
                    "topic_hints": [],
                    "tags": [],
                    "member_ids": [],
                    "kinds": [],
                    "status": str(base.get("status") or "active"),
                },
            )
            item["member_ids"] = sorted(set(item["member_ids"]) | {unit_id})
            item["topic_hints"] = sorted(set(item["topic_hints"]) | set(record_topics))
            item["tags"] = sorted(set(item["tags"]) | set(record_tags))
            item["kinds"] = sorted(set(item["kinds"]) | {str(record.get("kind") or "")})

    _preserve_empty_governance_seeds(taxonomy, pools, existing_taxonomy, existing_pools)
    taxonomy["topics"] = {key: taxonomy["topics"][key] for key in sorted(taxonomy["topics"])}
    taxonomy["tags"] = {key: taxonomy["tags"][key] for key in sorted(taxonomy["tags"])}
    pools["pools"] = {key: pools["pools"][key] for key in sorted(pools["pools"])}

    taxonomy_path = write_topic_taxonomy(project_root, taxonomy)
    pools_path = write_candidate_pools(project_root, pools)
    return taxonomy_path, pools_path


def build_index(project_root: Path) -> tuple[Path, Path]:
    ensure_workspace(project_root)
    records = iter_records(project_root)
    rebuild_governance_catalogs(project_root, records=records)
    items = []
    for record in sorted(records, key=lambda x: (str(x.get("kind")), str(x.get("title")))):
        items.append(
            {
                "id": record.get("id"),
                "kind": record.get("kind"),
                "title": record.get("title"),
                "status": record.get("status"),
                "maturity": record.get("maturity"),
                "confirmation_status": record.get("confirmation_status"),
                "tags": record.get("tags", []),
                "topics": record.get("topics", []),
                "candidate_pools": record.get("candidate_pools", []),
                "summary": record_summary(record),
                "path": rel(project_root, record_path(project_root, str(record.get("kind")), str(record.get("id")))),
            }
        )
    yaml_path = kb_root(project_root) / "index.yaml"
    md_path = kb_root(project_root) / "index.md"
    write_yaml_if_changed(
        yaml_path,
        {
            "id": "kb-index",
            "generated_at": utc_now_iso(),
            "items": items,
            "counts": {kind: len([item for item in items if item["kind"] == kind]) for kind in UNIT_KIND_DIRS},
        },
    )
    lines = ["# Research KB Index", ""]
    for kind in UNIT_KIND_DIRS:
        lines.extend([f"## {kind.title()}s", ""])
        kind_rows = [item for item in items if item["kind"] == kind]
        if not kind_rows:
            lines.append("- 暂无条目")
        for item in kind_rows:
            pools = ", ".join(item["candidate_pools"]) if item["candidate_pools"] else "-"
            lines.append(
                f"- `{item['id']}` · {item['title']} · status={item['status']} · maturity={item['maturity']} · confirm={item['confirmation_status']} · pools={pools}"
            )
        lines.append("")
    write_text_if_changed(md_path, "\n".join(lines).strip() + "\n")
    try:
        rebuild_passage_cache(project_root, records=records)
    except (OSError, sqlite3.Error, PassageCacheError):
        # The passage database is a derived acceleration cache.  A cache
        # failure must never roll back or otherwise alter the canonical index.
        pass
    return yaml_path, md_path


def _safe_files_below(base: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    """List regular files without ever traversing a symlinked directory."""
    if base.is_symlink() or not base.is_dir():
        return []
    paths: list[Path] = []
    for current, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _AUDIT_INTERNAL_DIRS and not (current_path / name).is_symlink()
        )
        for name in sorted(filenames):
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                continue
            if suffixes is None or path.suffix.lower() in suffixes:
                paths.append(path)
    return sorted(paths, key=lambda path: path.as_posix())


def _read_regular_bytes(path: Path) -> bytes | None:
    """Read one regular file without following a final-component symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _path_has_symlink_component(project_root: Path, path: Path) -> bool:
    root = Path(os.path.abspath(project_root))
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _project_relative_artifact(project_root: Path, path: Path) -> str:
    root = Path(os.path.abspath(project_root))
    candidate = Path(os.path.abspath(path))
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise PassageCacheError("passage artifact escapes the project root") from exc


def passage_corpus(
    project_root: Path,
    *,
    records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], str]:
    """Extract passages plus the exact source manifest they were derived from."""
    record_list = list(records) if records is not None else list(iter_records(project_root))
    passages: list[dict[str, Any]] = []
    manifest_by_artifact: dict[str, str] = {}
    for record in sorted(
        record_list,
        key=lambda item: (str(item.get("kind") or ""), str(item.get("id") or "")),
    ):
        kind = str(record.get("kind") or "")
        unit_id = str(record.get("id") or "")
        if kind not in UNIT_KIND_DIRS or not unit_id:
            continue
        canonical_record_path = record_path(project_root, kind, unit_id)
        if _path_has_symlink_component(project_root, canonical_record_path):
            continue
        record_bytes = _read_regular_bytes(canonical_record_path)
        if record_bytes is None:
            continue
        record_artifact = _project_relative_artifact(project_root, canonical_record_path)
        record_digest = hashlib.sha256(record_bytes).hexdigest()
        manifest_by_artifact[record_artifact] = record_digest
        documents: list[dict[str, str]] = []
        for markdown_path in _unit_markdown_paths(project_root, record):
            markdown_bytes = _read_regular_bytes(markdown_path)
            if markdown_bytes is None:
                continue
            try:
                markdown_text = markdown_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            artifact = _project_relative_artifact(project_root, markdown_path)
            digest = hashlib.sha256(markdown_bytes).hexdigest()
            manifest_by_artifact[artifact] = digest
            documents.append({"artifact": artifact, "text": markdown_text, "source_digest": digest})
        passage_record = copy.deepcopy(record)
        passage_record["summary"] = record_summary(record)
        passages.extend(
            extract_record_passages(
                passage_record,
                record_artifact=record_artifact,
                record_digest=record_digest,
                markdown_documents=documents,
            )
        )
        unit_directory = unit_root(project_root, kind, unit_id)
        for cache_name in ("parse-cache.yaml", "parse-cache.yml"):
            parse_cache_path = unit_directory / cache_name
            if _path_has_symlink_component(project_root, parse_cache_path):
                continue
            parse_cache_bytes = _read_regular_bytes(parse_cache_path)
            if parse_cache_bytes is None:
                continue
            try:
                parse_cache = yaml.safe_load(parse_cache_bytes.decode("utf-8"))
            except (UnicodeDecodeError, yaml.YAMLError):
                continue
            if not isinstance(parse_cache, dict) or not isinstance(parse_cache.get("chunks"), list):
                continue
            chunks = [item for item in parse_cache["chunks"] if isinstance(item, dict)]
            if not any(str(item.get("text") or "").strip() for item in chunks):
                continue
            artifact = _project_relative_artifact(project_root, parse_cache_path)
            digest = hashlib.sha256(parse_cache_bytes).hexdigest()
            manifest_by_artifact[artifact] = digest
            passages.extend(
                extract_parse_cache_passages(
                    passage_record,
                    artifact=artifact,
                    chunks=chunks,
                    source_digest=digest,
                )
            )
    manifest = [
        {"artifact": artifact, "digest": manifest_by_artifact[artifact]}
        for artifact in sorted(manifest_by_artifact)
    ]
    corpus_digest = _passage_corpus_digest(manifest)
    passages.sort(
        key=lambda item: (
            str(item.get("unit_id") or ""),
            str(item.get("artifact") or ""),
            str(item.get("locator") or ""),
            str(item.get("passage_id") or ""),
        )
    )
    return passages, manifest, corpus_digest


_PASSAGE_DIGEST_FIELDS = (
    "passage_id",
    "unit_id",
    "kind",
    "title",
    "summary",
    "heading",
    "text",
    "artifact",
    "locator",
    "line_start",
    "line_end",
    "source_digest",
)


def _passage_corpus_digest(manifest: list[dict[str, str]]) -> str:
    digest_payload = {
        "revision": PASSAGE_INDEX_REVISION,
        "sources": manifest,
    }
    return hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _valid_passage_source_manifest(manifest: list[dict[str, str]]) -> bool:
    for item in manifest:
        artifact = str(item.get("artifact") or "")
        digest = str(item.get("digest") or "")
        artifact_path = Path(artifact)
        if (
            not artifact
            or "\\" in artifact
            or artifact_path.is_absolute()
            or artifact_path.as_posix() != artifact
            or artifact_path.parts[:2] != ("kb", "units")
            or any(part in {"", ".", ".."} for part in artifact_path.parts)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            return False
    return True


def _passages_digest(passages: list[dict[str, Any]]) -> str:
    normalized = [
        {
            field: (
                int(item.get(field) or 0)
                if field in {"line_start", "line_end"}
                else str(item.get(field) or "")
            )
            for field in _PASSAGE_DIGEST_FIELDS
        }
        for item in passages
    ]
    normalized.sort(
        key=lambda item: (
            item["unit_id"],
            item["artifact"],
            item["locator"],
            item["passage_id"],
        )
    )
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ensure_cache_parent(cache_path: Path) -> None:
    for directory in [cache_path.parent.parent, cache_path.parent]:
        if directory.is_symlink():
            raise PassageCacheError("passage cache parent is a symlink")
        if directory.exists() and not directory.is_dir():
            raise PassageCacheError("passage cache parent is not a directory")
        directory.mkdir(parents=False, exist_ok=True)
    if cache_path.is_symlink():
        raise PassageCacheError("passage cache path is a symlink")
    if cache_path.exists() and not cache_path.is_file():
        raise PassageCacheError("passage cache path is not a regular file")


def _fsync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def rebuild_passage_cache(
    project_root: Path,
    *,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Atomically replace the derived FTS5 database, preserving any prior cache on failure."""
    passages, manifest, corpus_digest = passage_corpus(project_root, records=records)
    passages_digest = _passages_digest(passages)
    cache_path = passage_search_cache_path(project_root)
    if _path_has_symlink_component(project_root, cache_path.parent):
        raise PassageCacheError("passage cache parent contains a symlink")
    _ensure_cache_parent(cache_path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".passages-", suffix=".sqlite3", dir=cache_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE metadata (revision TEXT NOT NULL, corpus_digest TEXT NOT NULL, "
            "passages_digest TEXT NOT NULL, passage_count INTEGER NOT NULL, source_count INTEGER NOT NULL)"
        )
        connection.execute("CREATE TABLE sources (artifact TEXT PRIMARY KEY, digest TEXT NOT NULL)")
        connection.execute(
            "CREATE VIRTUAL TABLE passages USING fts5("
            "passage_id UNINDEXED, unit_id UNINDEXED, kind UNINDEXED, "
            "title UNINDEXED, summary UNINDEXED, heading, body, artifact UNINDEXED, locator UNINDEXED, "
            "line_start UNINDEXED, line_end UNINDEXED, source_digest UNINDEXED, "
            "tokenize='unicode61')"
        )
        connection.execute(
            "INSERT INTO metadata VALUES (?, ?, ?, ?, ?)",
            (PASSAGE_INDEX_REVISION, corpus_digest, passages_digest, len(passages), len(manifest)),
        )
        connection.executemany(
            "INSERT INTO sources (artifact, digest) VALUES (?, ?)",
            [(item["artifact"], item["digest"]) for item in manifest],
        )
        connection.executemany(
            "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item["passage_id"],
                    item["unit_id"],
                    item["kind"],
                    item["title"],
                    item["summary"],
                    item["heading"],
                    item["text"],
                    item["artifact"],
                    item["locator"],
                    item["line_start"],
                    item["line_end"],
                    item["source_digest"],
                )
                for item in passages
            ],
        )
        connection.commit()
        connection.close()
        connection = None
        file_descriptor = os.open(temporary_path, os.O_RDONLY)
        try:
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        os.replace(temporary_path, cache_path)
        _fsync_directory(cache_path.parent)
    except Exception:
        if connection is not None:
            connection.close()
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return {
        "health": "current",
        "revision": PASSAGE_INDEX_REVISION,
        "corpus_digest": corpus_digest,
        "passages_digest": passages_digest,
        "passage_count": len(passages),
        "source_count": len(manifest),
    }


def _read_only_cache_connection(cache_path: Path) -> sqlite3.Connection:
    absolute_cache = Path(os.path.abspath(cache_path))
    connection = sqlite3.connect(f"{absolute_cache.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _sqlite_health_for_error(exc: sqlite3.Error) -> str:
    message = str(exc).lower()
    if "fts5" in message or "no such module" in message:
        return "unavailable"
    return "corrupt"


def passage_cache_health(
    project_root: Path,
    *,
    manifest: list[dict[str, str]],
    corpus_digest: str,
    passages_digest: str,
    passage_count: int,
) -> str:
    cache_path = passage_search_cache_path(project_root)
    if _path_has_symlink_component(project_root, cache_path):
        return "corrupt"
    if not cache_path.exists():
        return "missing"
    if not cache_path.is_file():
        return "corrupt"
    try:
        connection = _read_only_cache_connection(cache_path)
        try:
            metadata = connection.execute(
                "SELECT revision, corpus_digest, passages_digest, passage_count, source_count FROM metadata"
            ).fetchall()
            if len(metadata) != 1:
                return "corrupt"
            row = metadata[0]
            cached_manifest = [
                {"artifact": item["artifact"], "digest": item["digest"]}
                for item in connection.execute("SELECT artifact, digest FROM sources ORDER BY artifact")
            ]
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            cached_passages = [
                {
                    "passage_id": item["passage_id"],
                    "unit_id": item["unit_id"],
                    "kind": item["kind"],
                    "title": item["title"],
                    "summary": item["summary"],
                    "heading": item["heading"],
                    "text": item["body"],
                    "artifact": item["artifact"],
                    "locator": item["locator"],
                    "line_start": item["line_start"],
                    "line_end": item["line_end"],
                    "source_digest": item["source_digest"],
                }
                for item in connection.execute(
                    "SELECT passage_id, unit_id, kind, title, summary, heading, body, artifact, locator, "
                    "line_start, line_end, source_digest FROM passages ORDER BY passage_id"
                )
            ]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return _sqlite_health_for_error(exc)
    if not integrity or str(integrity[0]).lower() != "ok":
        return "corrupt"
    if str(row["revision"]) != PASSAGE_INDEX_REVISION:
        return "stale"
    try:
        cached_source_count = int(row["source_count"])
        cached_passage_count = int(row["passage_count"])
        cached_passages_digest = _passages_digest(cached_passages)
    except (TypeError, ValueError):
        return "corrupt"
    if not _valid_passage_source_manifest(cached_manifest):
        return "corrupt"
    if cached_source_count != len(cached_manifest) or str(row["corpus_digest"]) != _passage_corpus_digest(cached_manifest):
        return "corrupt"
    if cached_passage_count != len(cached_passages) or str(row["passages_digest"]) != cached_passages_digest:
        return "corrupt"
    if (
        str(row["corpus_digest"]) != corpus_digest
        or cached_source_count != len(manifest)
        or cached_manifest != manifest
    ):
        return "stale"
    if str(row["passages_digest"]) != passages_digest or cached_passage_count != passage_count:
        # With identical canonical sources, deterministic extraction must produce
        # identical rows. A coherent but different cached row set is corruption,
        # not canonical staleness.
        return "corrupt"
    return "current"


def _fts_query_text(query: str) -> str:
    tokens = tokenize_query(query)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _query_passage_cache(
    project_root: Path,
    query: str,
    *,
    allowed_unit_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not allowed_unit_ids or limit <= 0:
        return []
    connection = _read_only_cache_connection(passage_search_cache_path(project_root))
    try:
        rows = connection.execute(
            "SELECT passage_id, unit_id, kind, title, summary, heading, body, artifact, locator, "
            "line_start, line_end, source_digest, "
            "bm25(passages, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0) AS score "
            "FROM passages WHERE passages MATCH ? ORDER BY score, unit_id, artifact, locator",
            (_fts_query_text(query),),
        )
        query_tokens = tokenize_query(query)
        results: list[dict[str, Any]] = []
        for row in rows:
            if str(row["unit_id"]) not in allowed_unit_ids:
                continue
            passage = {
                "unit_id": row["unit_id"],
                "kind": row["kind"],
                "title": row["title"],
                "summary": row["summary"],
                "heading": row["heading"],
                "text": row["body"],
                "artifact": row["artifact"],
                "locator": row["locator"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "source_digest": row["source_digest"],
            }
            results.append(passage_result(passage, query_tokens, score=-float(row["score"])))
            if len(results) >= limit:
                break
        return results
    finally:
        connection.close()


def _safe_record_files(project_root: Path) -> list[Path]:
    """Return canonical record files without following unit/file symlinks."""
    paths: list[Path] = []
    units = kb_root(project_root) / "units"
    for dirname in UNIT_KIND_DIRS.values():
        kind_root = units / dirname
        if kind_root.is_symlink() or not kind_root.is_dir():
            continue
        try:
            entries = sorted(os.scandir(kind_root), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path) / "record.yaml"
            if path.is_symlink() or not path.is_file():
                continue
            paths.append(path)
    return sorted(paths, key=lambda path: path.as_posix())


def _safe_lint_records(project_root: Path) -> list[dict[str, Any]]:
    """Read canonical records while refusing symlinked unit directories/files."""
    items: list[dict[str, Any]] = []
    for path in _safe_record_files(project_root):
        payload = load_yaml(path, default={})
        if not isinstance(payload, dict):
            continue
        try:
            items.append(normalize_record_schema(payload, project_root=project_root))
        except SystemExit:
            items.append(payload)
    return items


def lint_workspace_integrity(project_root: Path, *, records: list[dict[str, Any]] | None = None) -> list[str]:
    issues: list[str] = []
    yaml_paths: list[Path] = []
    records = list(records) if records is not None else _safe_lint_records(project_root)

    for record in records:
        kind = str(record.get("kind") or "")
        unit_id = str(record.get("id") or "")
        if kind in UNIT_KIND_DIRS and unit_id:
            yaml_paths.append(record_path(project_root, kind, unit_id))

    for base in [kb_root(project_root) / "programs", config_root(project_root), synthesis_root(project_root)]:
        yaml_paths.extend(_safe_files_below(base, suffixes={".yaml", ".yml"}))

    seen_paths: set[Path] = set()
    for path in yaml_paths:
        if path in seen_paths or not path.exists():
            continue
        seen_paths.add(path)
        if "source" in path.parts or path.parts[-3:-1] == ("user", "kb"):
            continue
        for issue in yaml_duplicate_key_issues(path):
            prefix = f"{project_root.as_posix()}/"
            issues.append(issue.replace(prefix, ""))

    wikilink_ref_keys: set[str] = set()
    for record in records:
        wikilink_ref_keys.update(_record_wikilink_ref_keys(record))
    for record in records:
        for path in _unit_markdown_paths(project_root, record):
            try:
                markdown = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for target in parse_wikilinks(markdown):
                if normalize_ref_key(target) not in wikilink_ref_keys:
                    issues.append(f"{rel(project_root, path)}: broken wikilink `{target}`")

    programs_root = kb_root(project_root) / "programs"
    if programs_root.is_symlink() or not programs_root.is_dir():
        return issues

    records_by_id = {
        str(record.get("id") or ""): record
        for record in records
        if str(record.get("id") or "")
    }
    state_files = [
        path
        for path in _safe_files_below(programs_root, suffixes={".yaml"})
        if path.name == "state.yaml" and path.parent.parent == programs_root
    ]
    for state_file in state_files:
        program_id = state_file.parent.name
        state_payload = load_yaml(state_file, default={})
        if not isinstance(state_payload, dict):
            issues.append(f"{rel(project_root, state_file)}: invalid YAML payload")
            continue
        active_unit_ids = _text_list(state_payload.get("active_unit_ids"))
        for unit_id in active_unit_ids:
            record = records_by_id.get(unit_id)
            if record is None:
                issues.append(f"{rel(project_root, state_file)}: active_unit_id `{unit_id}` not found")
                continue
            if program_id not in _slug_list(record.get("program_ids")):
                issues.append(f"{rel(project_root, state_file)}: `{unit_id}` missing reverse program_ids link to `{program_id}`")

    for record in records:
        unit_id = str(record.get("id") or "")
        for program_id in _slug_list(record.get("program_ids")):
            state_file = common_program_root(project_root, program_id) / "state.yaml"
            if not state_file.exists():
                issues.append(f"{unit_id}: references missing program `{program_id}`")
                continue
            state_payload = load_yaml(state_file, default={})
            if not isinstance(state_payload, dict):
                issues.append(f"{unit_id}: referenced program `{program_id}` has invalid state payload")
                continue
            if unit_id not in _text_list(state_payload.get("active_unit_ids")):
                issues.append(f"{unit_id}: program `{program_id}` missing reverse active_unit_ids link")

    return issues


def lint_records(project_root: Path) -> tuple[str, list[str]]:
    issues: list[str] = []
    records = _safe_lint_records(project_root)
    for raw_record in records:
        try:
            record = normalize_record_schema(raw_record)
        except SystemExit as exc:
            issues.append(str(exc))
            continue
        unit_id = str(record.get("id") or "")
        kind = str(record.get("kind") or "")
        if not unit_id:
            issues.append("record without id")
        if kind not in UNIT_KIND_DIRS:
            issues.append(f"{unit_id}: invalid kind `{kind}`")
        if kind in UNIT_KIND_DIRS and not is_canonical_unit_id(kind, unit_id):
            issues.append(f"{unit_id}: non-canonical id, run `kb.py compact-ids --apply`")
        if str(record.get("status") or "") not in STATUS_VALUES:
            issues.append(f"{unit_id}: invalid status `{record.get('status')}`")
        if str(record.get("maturity") or "") not in MATURITY_LEVELS:
            issues.append(f"{unit_id}: invalid maturity `{record.get('maturity')}`")
        if str(record.get("confirmation_status") or "") not in CONFIRMATION_VALUES:
            issues.append(f"{unit_id}: invalid confirmation_status `{record.get('confirmation_status')}`")
        info_types = record.get("information_types", [])
        if not isinstance(info_types, list) or not set(info_types).issubset(INFORMATION_TYPES):
            issues.append(f"{unit_id}: invalid information_types")
        if not isinstance(record.get("payload"), dict) or not record.get("payload"):
            issues.append(f"{unit_id}: missing payload")
        if not isinstance(record.get("taxonomy"), dict):
            issues.append(f"{unit_id}: missing taxonomy block")
        if not isinstance(record.get("candidate_pools"), list):
            issues.append(f"{unit_id}: invalid candidate_pools")
        for violation in validate_write(record):
            issues.append(violation)
    issues.extend(lint_workspace_integrity(project_root, records=records))
    return ("PASS" if not issues else "FAIL"), issues


def _audit_subject(project_root: Path, path: Path) -> str:
    """Return a lexical, project-relative subject without resolving symlinks."""
    project = Path(os.path.abspath(project_root))
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(project)
    except ValueError:
        return "kb"
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return "kb"
    return relative.as_posix()


def _audit_finding(
    code: str,
    category: str,
    severity: str,
    subject: str,
    message: str,
) -> dict[str, str]:
    safe_subject = str(subject or "kb").replace("\\", "/").strip("/") or "kb"
    if Path(safe_subject).is_absolute() or ".." in Path(safe_subject).parts:
        safe_subject = "kb"
    return {
        "code": str(code),
        "category": category if category in AUDIT_CATEGORIES else "integrity",
        "severity": severity if severity in AUDIT_SEVERITIES else "error",
        "subject": safe_subject,
        "message": " ".join(str(message).split()),
    }


def _lint_finding(issue: str) -> dict[str, str]:
    text = str(issue or "")
    lowered = text.lower()
    subject = "kb"
    match = re.match(r"(kb/[A-Za-z0-9._/-]+):", text)
    if match and ".." not in Path(match.group(1)).parts:
        subject = match.group(1)
    if "broken wikilink" in lowered:
        return _audit_finding(
            "INTEGRITY_BROKEN_WIKILINK", "integrity", "error", subject,
            "A Markdown wikilink target is missing.",
        )
    if "program" in lowered or "active_unit_id" in lowered or "reverse" in lowered:
        return _audit_finding(
            "INTEGRITY_PROGRAM_LINK", "integrity", "error", subject,
            "Program and unit links are inconsistent.",
        )
    if "duplicate" in lowered and "key" in lowered:
        return _audit_finding(
            "SCHEMA_DUPLICATE_YAML_KEY", "schema", "error", subject,
            "A YAML document contains a duplicate key.",
        )
    return _audit_finding(
        "SCHEMA_RECORD_INVALID", "schema", "error", subject,
        "A record violates the existing schema or lifecycle contract.",
    )


def _symlink_findings(project_root: Path) -> tuple[list[dict[str, str]], bool]:
    root = kb_root(project_root)
    findings: list[dict[str, str]] = []
    if root.is_symlink():
        findings.append(_audit_finding(
            "SECURITY_SYMLINK_ESCAPE", "security", "error", "kb",
            "The KB root is a symlink and does not define a contained KB boundary.",
        ))
        return findings, True
    if not root.is_dir():
        return findings, False

    lexical_root = Path(os.path.abspath(root))
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        candidates = sorted(set(dirnames + filenames))
        for name in candidates:
            path = current_path / name
            if not path.is_symlink():
                continue
            raw_target = os.readlink(path)
            target = Path(raw_target) if Path(raw_target).is_absolute() else path.parent / raw_target
            lexical_target = Path(os.path.abspath(target))
            try:
                lexical_target.relative_to(lexical_root)
            except ValueError:
                findings.append(_audit_finding(
                    "SECURITY_SYMLINK_ESCAPE", "security", "error",
                    _audit_subject(project_root, path),
                    "A KB symlink resolves outside the KB boundary.",
                ))
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _AUDIT_INTERNAL_DIRS and not (current_path / name).is_symlink()
        )
    return findings, False


def _record_audit_entries(project_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    entries: list[tuple[Path, dict[str, Any]]] = []
    for path in _safe_record_files(project_root):
        payload = load_yaml(path, default={})
        if isinstance(payload, dict):
            entries.append((path, payload))
    return entries


def _binding_findings(
    project_root: Path,
    entries: list[tuple[Path, dict[str, Any]]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path, record in entries:
        payload = record.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        verification = payload.get("verification")
        has_verification = isinstance(verification, dict)
        violations: list[str] = []
        try:
            source_roots = trusted_claim_source_roots(
                project_root,
                record,
                verification_root=path.parent,
            )
        except ValueError:
            source_roots = {}
            violations = ["verification evidence source is not canonically contained"]
        if has_verification:
            if not violations:
                violations = verification_receipt_violations(
                    record,
                    path.parent,
                    external_source=record_external_source_contract(record),
                    source_roots=source_roots,
                    check_artifacts=True,
                )
            if verification.get("invalidation") and not violations:
                violations = ["verification receipt is marked invalid"]
            if violations:
                findings.append(_audit_finding(
                    "INTEGRITY_VERIFICATION_BINDING_STALE", "integrity", "error",
                    _audit_subject(project_root, path),
                    "The stored verification receipt is missing, invalid, or stale.",
                ))
        if str(record.get("confirmation_status") or "") == "confirmed":
            confirmation_invalid = not has_complete_confirmation_receipt(
                record,
                verification_root=path.parent,
                external_source=record_external_source_contract(record),
                source_roots=source_roots,
            )
            if confirmation_track(record) == "judgement" and violations:
                confirmation_invalid = True
            if confirmation_invalid:
                findings.append(_audit_finding(
                    "INTEGRITY_CONFIRMATION_BINDING_INVALID", "integrity", "error",
                    _audit_subject(project_root, path),
                    "The current confirmation is not bound to current verified content.",
                ))
    return findings


def _recovery_findings(project_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for entry in incomplete_ops(project_root):
        op_id = str(entry.get("op_id") or "")
        safe_op_id = op_id if re.fullmatch(r"[A-Za-z0-9._-]+", op_id) else "incomplete-operation"
        findings.append(_audit_finding(
            "RECOVERY_INCOMPLETE_OPERATION", "recovery", "error",
            f"kb/.journal/{safe_op_id}.yaml",
            "An operation journal entry is incomplete and requires recovery.",
        ))

    if kb_repo_exists(project_root):
        try:
            dirty_paths = dirty_kb_paths(project_root)
        except SystemExit:
            findings.append(_audit_finding(
                "RECOVERY_GIT_INSPECTION_FAILED", "recovery", "error", "kb",
                "The nested KB Git state could not be inspected safely.",
            ))
        else:
            kb = kb_root(project_root)
            for path in dirty_paths:
                try:
                    relative = path.relative_to(kb).as_posix()
                except ValueError:
                    continue
                if relative == ".DS_Store" or any(
                    relative == prefix.rstrip("/") or relative.startswith(prefix)
                    for prefix in _AUDIT_GIT_EXCLUDED_PREFIXES
                ):
                    continue
                findings.append(_audit_finding(
                    "RECOVERY_DIRTY_PRODUCT_FILE", "recovery", "warning",
                    _audit_subject(project_root, path),
                    "A product-owned KB file has uncheckpointed Git changes.",
                ))
    return findings


def _paper_quality_findings(
    project_root: Path,
    entries: list[tuple[Path, dict[str, Any]]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path, record in entries:
        if str(record.get("kind") or "") != "paper" or str(record.get("maturity") or "") != "complete":
            continue
        payload = record.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        basic = payload.get("basic_info")
        basic = basic if isinstance(basic, dict) else {}
        missing = [
            field
            for field in ("authors", "year", "abstract")
            if basic.get(field) in (None, "", [], {})
        ]
        if missing:
            findings.append(_audit_finding(
                "QUALITY_PAPER_METADATA_MISSING", "quality", "warning",
                _audit_subject(project_root, path),
                "Complete paper analysis is missing metadata fields: " + ", ".join(missing) + ".",
            ))

        taxonomy = record.get("taxonomy")
        taxonomy = taxonomy if isinstance(taxonomy, dict) else {}
        topics = set(_slug_list(record.get("topics")))
        topics.update(_slug_list(taxonomy.get("secondary_topics")))
        primary = str(taxonomy.get("primary_topic") or "").strip()
        if primary:
            topics.add(primary)
        tags = set(_slug_list(record.get("tags")))
        tags.update(_slug_list(taxonomy.get("canonical_tags")))
        if topics.issubset({"uncategorized"}) and tags.issubset({"research"}):
            findings.append(_audit_finding(
                "QUALITY_PAPER_TAXONOMY_DEFAULT", "quality", "warning",
                _audit_subject(project_root, path),
                "Complete paper analysis still has only default or empty taxonomy metadata.",
            ))
    return findings


def _figure_quality_findings(project_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    paper_root = kb_root(project_root) / "units" / UNIT_KIND_DIRS["paper"]
    for path in _safe_files_below(paper_root, suffixes={".yaml", ".yml"}):
        if path.name != "figures.yaml":
            continue
        payload = load_yaml(path, default={})
        if not isinstance(payload, dict):
            continue
        candidates = payload.get("candidate_figures")
        if not isinstance(candidates, list):
            continue
        identities: list[str] = []
        suspicious = False
        for item in candidates:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip().lower()
            identity = str(item.get("figure") or item.get("id") or "").strip().lower()
            if not identity and label:
                identity = f"{str(item.get('kind') or 'figure').strip().lower()}:{label}"
            if identity:
                identities.append(identity)
            if re.fullmatch(r"[a-z]{2,}", label):
                suspicious = True
        if len(identities) != len(set(identities)):
            findings.append(_audit_finding(
                "QUALITY_FIGURE_DUPLICATE_IDENTITY", "quality", "warning",
                _audit_subject(project_root, path),
                "Figure candidates contain duplicate identities.",
            ))
        if suspicious:
            findings.append(_audit_finding(
                "QUALITY_FIGURE_SUSPICIOUS_LABEL", "quality", "warning",
                _audit_subject(project_root, path),
                "Figure candidates contain a suspicious multi-letter nonnumeric label.",
            ))
    return findings


def _audit_counts(findings: list[dict[str, str]]) -> dict[str, int]:
    counts = {"total": len(findings)}
    counts.update({severity: 0 for severity in AUDIT_SEVERITIES})
    counts.update({category: 0 for category in AUDIT_CATEGORIES})
    for finding in findings:
        counts[finding["severity"]] += 1
        counts[finding["category"]] += 1
    return counts


def audit_workspace(project_root: Path) -> dict[str, Any]:
    """Run deterministic, layered, byte-read-only mechanical KB health checks."""
    root = Path(project_root)
    findings, unsafe_root = _symlink_findings(root)
    if not unsafe_root:
        _, lint_issues = lint_records(root)
        findings.extend(_lint_finding(issue) for issue in lint_issues)
        entries = _record_audit_entries(root)
        findings.extend(_binding_findings(root, entries))
        findings.extend(_recovery_findings(root))
        findings.extend(_paper_quality_findings(root, entries))
        findings.extend(_figure_quality_findings(root))

    unique = {
        (item["code"], item["category"], item["severity"], item["subject"], item["message"]): item
        for item in findings
    }
    stable = sorted(
        unique.values(),
        key=lambda item: (
            AUDIT_CATEGORIES.index(item["category"]),
            AUDIT_SEVERITIES.index(item["severity"]),
            item["code"],
            item["subject"],
            item["message"],
        ),
    )
    counts = _audit_counts(stable)
    status = "FAIL" if counts["error"] else ("WARN" if stable else "PASS")
    return {"status": status, "counts": counts, "findings": stable}


def search_records(
    project_root: Path,
    query: str,
    *,
    kind: str | None = None,
    pool: str | None = None,
    confirmation_status: str | None = None,
) -> list[dict[str, Any]]:
    normalized_pool = slugify(str(pool), max_words=12) if pool else ""
    filtered: list[dict[str, Any]] = []
    for record in iter_records(project_root, kind=kind):
        if normalized_pool and normalized_pool not in record.get("candidate_pools", []):
            continue
        if confirmation_status and str(record.get("confirmation_status") or "") != confirmation_status:
            continue
        filtered.append(record)
    return rank_records(filtered, query, markdown_paths_for=lambda record: _unit_markdown_paths(project_root, record))


def search_passages(
    project_root: Path,
    query: str,
    *,
    kind: str | None = None,
    pool: str | None = None,
    confirmation_status: str | None = None,
    limit: int = PASSAGE_SEARCH_LIMIT,
) -> dict[str, Any]:
    """Return passage hits and derived-index health without mutating the workspace."""
    all_records = list(iter_records(project_root))
    normalized_pool = slugify(str(pool), max_words=12) if pool else ""
    filtered: list[dict[str, Any]] = []
    for record in all_records:
        if kind and str(record.get("kind") or "") != kind:
            continue
        if normalized_pool and normalized_pool not in record.get("candidate_pools", []):
            continue
        if confirmation_status and str(record.get("confirmation_status") or "") != confirmation_status:
            continue
        filtered.append(record)
    passages, manifest, corpus_digest = passage_corpus(project_root, records=all_records)
    passages_digest = _passages_digest(passages)
    health = passage_cache_health(
        project_root,
        manifest=manifest,
        corpus_digest=corpus_digest,
        passages_digest=passages_digest,
        passage_count=len(passages),
    )
    if not tokenize_query(query) or limit <= 0:
        return {"health": health, "results": []}
    allowed_unit_ids = {str(record.get("id") or "") for record in filtered}
    eligible_passages = [item for item in passages if str(item.get("unit_id") or "") in allowed_unit_ids]
    if health != "current":
        return {"health": health, "results": rank_passages(eligible_passages, query, limit=limit)}
    try:
        results = _query_passage_cache(
            project_root,
            query,
            allowed_unit_ids=allowed_unit_ids,
            limit=limit,
        )
    except sqlite3.Error as exc:
        health = _sqlite_health_for_error(exc)
        return {"health": health, "results": rank_passages(eligible_passages, query, limit=limit)}

    # unicode61 and substring tokenization differ at some CJK/ASCII boundaries.
    # Keep FTS/BM25 as the primary order, then deterministically fill any missed
    # lexical passages so mixed queries cannot lose correct results.
    seen = {(str(item["unit_id"]), str(item["locator"])) for item in results}
    for fallback in rank_passages(eligible_passages, query, limit=limit):
        key = (str(fallback["unit_id"]), str(fallback["locator"]))
        if key in seen:
            continue
        results.append(fallback)
        seen.add(key)
        if len(results) >= limit:
            break
    return {"health": health, "results": results[:limit]}


def govern_records(
    project_root: Path,
    *,
    unit_ids: list[str] | None = None,
    kind: str | None = None,
    explicit_topics: list[str] | None = None,
    explicit_tags: list[str] | None = None,
    explicit_pools: list[str] | None = None,
    infer_missing: bool = True,
    source_label: str = "",
) -> list[Path]:
    ensure_workspace(project_root)
    written: list[Path] = []
    if unit_ids:
        for unit_id in unit_ids:
            record, _ = locate_record(project_root, unit_id)
            updated = apply_record_governance(
                project_root,
                record,
                explicit_topics=explicit_topics,
                explicit_tags=explicit_tags,
                explicit_pools=explicit_pools,
                infer_missing=infer_missing,
                source_label=source_label,
            )
            append_history(updated, action="governed", summary="Updated topics / tags / candidate pools.")
            written.append(write_record(project_root, updated))
        return written
    for record in iter_records(project_root, kind=kind):
        updated = apply_record_governance(
            project_root,
            record,
            explicit_topics=explicit_topics,
            explicit_tags=explicit_tags,
            explicit_pools=explicit_pools,
            infer_missing=infer_missing,
            source_label=source_label,
        )
        append_history(updated, action="governed", summary="Updated topics / tags / candidate pools.")
        written.append(write_record(project_root, updated))
    return written


def _sorted_id_pairs(mapping: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True)


def _replace_ids_in_text(text: str, mapping: dict[str, str]) -> str:
    updated = text
    for old_id, new_id in _sorted_id_pairs(mapping):
        updated = updated.replace(old_id, new_id)
    return updated


def _replace_ids_in_object(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_ids_in_object(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_ids_in_object(item, mapping) for item in value]
    if isinstance(value, str):
        return _replace_ids_in_text(value, mapping)
    return value


def _text_rewrite_allowed(project_root: Path, path: Path) -> bool:
    if path.name == "record.yaml":
        return False
    if path.suffix.lower() not in TEXT_REWRITE_SUFFIXES:
        return False
    try:
        rel_path = path.resolve().relative_to(kb_root(project_root).resolve())
    except ValueError:
        return False
    if rel_path.parts[:2] == ("user", "kb"):
        return False
    if "source" in rel_path.parts:
        return False
    return True


def _rename_paths_with_ids(project_root: Path, mapping: dict[str, str]) -> list[tuple[Path, Path]]:
    if not mapping:
        return []
    root = kb_root(project_root)
    renamed: list[tuple[Path, Path]] = []
    paths = sorted(root.rglob("*"), key=lambda item: (len(item.parts), len(item.as_posix())), reverse=True)
    for path in paths:
        if not path.exists():
            continue
        try:
            rel_path = path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if rel_path.parts[:2] == ("user", "kb"):
            continue
        if "source" in rel_path.parts:
            continue
        updated_name = _replace_ids_in_text(path.name, mapping)
        if updated_name == path.name:
            continue
        destination = path.with_name(updated_name)
        if destination.exists():
            continue
        path.rename(destination)
        renamed.append((path, destination))
    return renamed


def compact_unit_ids(project_root: Path, *, kind: str | None = None, apply: bool = False) -> dict[str, Any]:
    ensure_workspace(project_root)
    records = iter_records(project_root, kind=kind)
    occupied_ids = {str(record.get("id") or "") for record in records if str(record.get("id") or "")}
    reserved_new_ids: set[str] = set()
    changes: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}

    for record in records:
        item_kind = str(record.get("kind") or "")
        old_id = str(record.get("id") or "")
        title = str(record.get("title") or "")
        source_uri = str(record.get("source", {}).get("original_uri") or "")
        if not old_id or item_kind not in UNIT_KIND_DIRS:
            continue
        old_hash = _extract_unit_id_hash(old_id)
        new_id = canonical_unit_id_with_hash(item_kind, title=title, source=source_uri, hash_value=old_hash)
        if new_id != old_id and (new_id in reserved_new_ids or new_id in occupied_ids):
            for hash_size in (10, 12, 16):
                candidate = canonical_unit_id(item_kind, title=title, source=source_uri, hash_size=hash_size)
                if candidate == old_id or (candidate not in reserved_new_ids and (candidate not in occupied_ids or candidate == old_id)):
                    new_id = candidate
                    break
        reserved_new_ids.add(new_id)
        if new_id == old_id:
            continue
        mapping[old_id] = new_id
        changes.append(
            {
                "kind": item_kind,
                "title": title,
                "old_id": old_id,
                "new_id": new_id,
            }
        )

    summary = {
        "changed": len(changes),
        "mapping": mapping,
        "items": changes,
        "renamed_paths": [],
    }
    if not apply or not changes:
        return summary

    for item in changes:
        old_root = unit_root(project_root, item["kind"], item["old_id"])
        new_root = unit_root(project_root, item["kind"], item["new_id"])
        if new_root.exists() and new_root != old_root:
            raise SystemExit(f"Target unit path already exists: {rel(project_root, new_root)}")

    for item in changes:
        old_root = unit_root(project_root, item["kind"], item["old_id"])
        new_root = unit_root(project_root, item["kind"], item["new_id"])
        ensure_dir(new_root.parent)
        if old_root.exists() and old_root != new_root:
            old_root.rename(new_root)

    for record in records:
        original_id = str(record.get("id") or "")
        updated = _replace_ids_in_object(copy.deepcopy(record), mapping)
        current_id = mapping.get(original_id, original_id)
        updated["id"] = current_id
        legacy_ids = _unique_text_list(updated.get("legacy_ids"))
        if original_id in mapping:
            legacy_ids.append(original_id)
        updated["legacy_ids"] = [item for item in _unique_text_list(legacy_ids) if item and item != current_id]
        write_record(project_root, updated)

    renamed_paths = _rename_paths_with_ids(project_root, mapping)
    for path in kb_root(project_root).rglob("*"):
        if not path.is_file() or not _text_rewrite_allowed(project_root, path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated_content = _replace_ids_in_text(content, mapping)
        if updated_content != content:
            write_text_if_changed(path, updated_content)

    rebuild_governance_catalogs(project_root)
    build_index(project_root)

    summary["renamed_paths"] = [
        {"old": rel(project_root, old_path), "new": rel(project_root, new_path)}
        for old_path, new_path in renamed_paths
    ]
    return summary


def dataset_migration_plan(project_root: Path, repo_id: str) -> dict[str, Any]:
    """Build a byte-read-only plan for rehoming a known dataset misfiled as repo."""
    record, old_record_path = locate_record(project_root, repo_id, kind="repo", fuzzy=False)
    source_uri = str(record.get("source", {}).get("original_uri") or "").strip()
    if "huggingface.co/datasets/" not in source_uri.lower():
        raise SystemExit("Repo-to-dataset migration only accepts recognized dataset sources.")
    new_id = canonical_unit_id("dataset", title=str(record.get("title") or ""), source=source_uri)
    old_root = old_record_path.parent
    new_root = unit_root(project_root, "dataset", new_id)
    if new_root.exists() and new_root != old_root:
        raise SystemExit(f"Target dataset unit already exists: {rel(project_root, new_root)}")
    reference_paths: list[Path] = []
    root = kb_root(project_root)
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative_parts = path.relative_to(root).parts
            if (
                not relative_parts
                or relative_parts[0] in _AUDIT_INTERNAL_DIRS
                or "source" in relative_parts
                or "raw" in relative_parts
                or path.name == "parse-cache.yaml"
                or path.suffix.lower() not in TEXT_REWRITE_SUFFIXES
            ):
                continue
            try:
                if repo_id in path.read_text(encoding="utf-8"):
                    reference_paths.append(path)
            except (OSError, UnicodeDecodeError):
                continue
    return {
        "changed": True,
        "old_id": repo_id,
        "new_id": new_id,
        "title": str(record.get("title") or ""),
        "source_uri": source_uri,
        "old_root": old_root,
        "new_root": new_root,
        "reference_paths": sorted(set(reference_paths), key=lambda path: path.as_posix()),
    }


def dataset_migration_targets(project_root: Path, plan: dict[str, Any]) -> list[Path]:
    """Return the exact path set a repo-to-dataset migration may mutate."""
    old_root = Path(plan["old_root"])
    new_root = Path(plan["new_root"])
    external_references = [
        Path(path)
        for path in plan.get("reference_paths", [])
        if old_root not in Path(path).parents and new_root not in Path(path).parents
    ]
    return sorted(
        {
            old_root,
            new_root,
            *external_references,
            kb_root(project_root) / "index.yaml",
            kb_root(project_root) / "index.md",
            topic_taxonomy_path(project_root),
            candidate_pools_path(project_root),
        },
        key=lambda path: path.as_posix(),
    )


def migrate_repo_to_dataset(project_root: Path, repo_id: str) -> dict[str, Any]:
    """Apply one already-journaled repo-to-dataset migration.

    The old judgement text and confirmation receipt remain as audit metadata, but
    canonical claims/verification are cleared because the confirmation subject and
    evidence contract changed. A runtime agent must fill and verify the dataset
    profile before the user confirms it again.
    """
    plan = dataset_migration_plan(project_root, repo_id)
    record, _old_path = locate_record(project_root, repo_id, kind="repo", fuzzy=False)
    old_root = Path(plan["old_root"])
    new_root = Path(plan["new_root"])
    ensure_dir(new_root.parent)
    old_root.rename(new_root)

    migrated = default_record(
        "dataset",
        title=str(record.get("title") or ""),
        maturity=str(record.get("maturity") or "complete"),
        source=copy.deepcopy(record.get("source") or {}),
    )
    for key in (
        "created_at",
        "first_ingested_at",
        "confidence",
        "tags",
        "topics",
        "candidate_pools",
        "program_ids",
        "priority",
        "links",
        "reuse_flags",
        "taxonomy",
        "artifacts",
    ):
        if key in record:
            migrated[key] = copy.deepcopy(record[key])
    migrated["id"] = str(plan["new_id"])
    migrated["legacy_ids"] = _unique_text_list([*record.get("legacy_ids", []), repo_id])
    migrated["status"] = "active"
    migrated["maturity"] = "complete"
    migrated["confirmation_status"] = "pending_user_confirmation"
    migrated["needs_human_confirmation"] = True
    migrated["information_types"] = sorted(
        {str(item) for item in record.get("information_types", [])} | {"fact", "inference", "evaluation", "unverified"}
    )
    migrated["revision"] = int(record.get("revision", 0) or 0)
    old_payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    capabilities = old_payload.get("capability", {}).get("core_capabilities", [])
    entrypoints = old_payload.get("structure", {}).get("entrypoints", [])
    reuse_points = old_payload.get("reuse", {}).get("directly_reusable", [])
    migrated["payload"]["profile"]["positioning"] = str(capabilities[0]) if capabilities else ""
    migrated["payload"]["access"]["schema_access"] = str(entrypoints[0]) if entrypoints else ""
    migrated["payload"]["reuse"]["supported_uses"] = [str(item) for item in reuse_points if str(item).strip()]
    migrated["payload"]["state"]["profile_status"] = "awaiting_agent_fill"
    migrated["history"] = copy.deepcopy(record.get("history") or [])
    migrated["migration"] = {
        "from_kind": "repo",
        "from_id": repo_id,
        "reason": "recognized_dataset_source",
        "previous_confirmation": copy.deepcopy(record.get("confirmation") or {}),
    }
    append_history(
        migrated,
        action="repo-migrated-to-dataset",
        summary="Reclassified a recognized dataset source; prior confirmation retained for audit only.",
        information_types=["fact", "unverified"],
    )
    migrated = _replace_ids_in_object(migrated, {repo_id: str(plan["new_id"])})
    migrated["legacy_ids"] = _unique_text_list([*record.get("legacy_ids", []), repo_id])
    migrated["migration"]["from_id"] = repo_id
    migrated["migration"]["previous_confirmation"] = copy.deepcopy(record.get("confirmation") or {})
    write_record(project_root, migrated)

    mapping = {repo_id: str(plan["new_id"])}
    for path in plan.get("reference_paths", []):
        original_path = Path(path)
        path = new_root / original_path.relative_to(old_root) if old_root in original_path.parents else original_path
        if not path.exists() or path == new_root / "record.yaml":
            continue
        if path.name == "record.yaml":
            payload = load_yaml(path, default={})
            if isinstance(payload, dict):
                write_record(project_root, _replace_ids_in_object(payload, mapping))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        write_text_if_changed(path, _replace_ids_in_text(text, mapping))

    rebuild_governance_catalogs(project_root)
    build_index(project_root)
    return {
        **plan,
        "renamed_paths": [{"old": rel(project_root, old_root), "new": rel(project_root, new_root)}],
    }


__all__ = [
    "STATUS_VALUES",
    "CONFIRMATION_VALUES",
    "PASSAGE_INDEX_REVISION",
    "PASSAGE_SEARCH_LIMIT",
    "PassageCacheError",
    "load_topic_taxonomy",
    "write_topic_taxonomy",
    "load_candidate_pools",
    "write_candidate_pools",
    "apply_record_governance",
    "_unit_id_slug_ref_key",
    "_record_wikilink_ref_keys",
    "_unit_markdown_paths",
    "_wikilink_target_exists",
    "refresh_record_schemas",
    "_has_declared_members",
    "_preserve_empty_governance_seeds",
    "rebuild_governance_catalogs",
    "build_index",
    "passage_corpus",
    "rebuild_passage_cache",
    "passage_cache_health",
    "lint_workspace_integrity",
    "lint_records",
    "audit_workspace",
    "search_records",
    "search_passages",
    "govern_records",
    "_sorted_id_pairs",
    "_replace_ids_in_text",
    "_replace_ids_in_object",
    "_text_rewrite_allowed",
    "_rename_paths_with_ids",
    "compact_unit_ids",
    "dataset_migration_plan",
    "dataset_migration_targets",
    "migrate_repo_to_dataset",
]

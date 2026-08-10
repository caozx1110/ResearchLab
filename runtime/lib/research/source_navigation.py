"""Safe, read-only navigation from evidence locators to Markdown source views.

Canonical evidence continues to identify the original artifact and locator.  This
module only derives a reader-facing navigation target when the immutable Markdown
view is current and a source-map entry is both unique and present in the document.
Missing or ambiguous precision falls back to the document; an unsafe or stale
document yields no link at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .common import workspace_root_roles
from .path_contract import (
    PathContractError,
    TargetClass,
    assert_no_follow_target,
    logical_ref_to_physical_path,
)
from .paths import kb_root
from .records import ProjectFileSnapshot, snapshot_project_file
from .relations import BLOCK_ID_RE
from .yaml_io import StrictYamlError, load_yaml_bytes_strict


_MAX_SOURCE_MAP_BYTES = 4 * 1024 * 1024
_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SourceReadingTarget:
    """One safe Markdown target relative to the active KB/Vault root."""

    markdown_path: str
    block_id: str = ""

    @property
    def precision(self) -> str:
        return "exact" if self.block_id else "document"

    @property
    def obsidian_path(self) -> str:
        path = PurePosixPath(self.markdown_path).with_suffix("").as_posix()
        return f"{path}#^{self.block_id}" if self.block_id else path


def _document_contains_unique_block(document: ProjectFileSnapshot, block_id: str) -> bool:
    if not BLOCK_ID_RE.fullmatch(block_id):
        return False
    pattern = rb"(?m)^\^" + re.escape(block_id.encode("ascii")) + rb"\r?$"
    matches = re.finditer(pattern, document.raw_bytes)
    return sum(1 for _match in matches) == 1


def resolve_canonical_source_path(
    project_root: Path,
    raw: Any,
    *,
    suffix: str | None,
) -> Path | None:
    """Resolve one persisted ``kb/...`` source path without following links."""

    text = " ".join(str(raw or "").split())
    if not text:
        return None
    lexical = PurePosixPath(text)
    if lexical.is_absolute() or not lexical.parts or lexical.parts[0] != "kb":
        return None
    if any(part in {"", ".", ".."} for part in lexical.parts):
        return None
    if suffix is not None and lexical.suffix.lower() != suffix:
        return None
    roots = workspace_root_roles(project_root).roots
    try:
        candidate = logical_ref_to_physical_path(roots, text)
        assessment = assert_no_follow_target(
            roots,
            candidate,
            allowed_classes=(TargetClass.CANONICAL_ARTIFACT,),
        )
        resolved = assessment.physical_path.resolve(strict=True)
    except (OSError, PathContractError, ValueError):
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return resolved


def _vault_markdown_path(project_root: Path, document: Path) -> str:
    try:
        relative = document.relative_to(kb_root(project_root).resolve(strict=True))
    except (OSError, ValueError):
        return ""
    path = PurePosixPath(relative.as_posix())
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return ""
    return path.as_posix()


def _source_map_payload(
    project_root: Path,
    source: Mapping[str, Any],
) -> tuple[dict[str, Any], ProjectFileSnapshot | None]:
    materialization = source.get("materialization")
    materialization = materialization if isinstance(materialization, Mapping) else {}
    raw_path = materialization.get("source_map_path")
    if PurePosixPath(str(raw_path or "").strip()).suffix.lower() != ".yaml":
        return {}, None
    source_map = snapshot_project_file(
        project_root,
        str(raw_path or "").strip(),
        max_bytes=_MAX_SOURCE_MAP_BYTES,
    )
    if source_map is None:
        return {}, None
    try:
        payload = load_yaml_bytes_strict(source_map.raw_bytes)
    except (RuntimeError, StrictYamlError):
        return {}, source_map
    if not isinstance(payload, dict) or payload.get("schema") != "research-source-map/v1":
        return {}, source_map
    return payload, source_map


def _matching_block_ids(payload: Mapping[str, Any], locator: str) -> set[str]:
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return set()
    page_match = re.fullmatch(r"page\s*=\s*(\d+)", locator, flags=re.IGNORECASE)
    section_match = re.fullmatch(
        r"(?:section|anchor)\s*:\s*(.+)",
        locator,
        flags=re.IGNORECASE,
    )
    document_locator = locator.casefold() in {"section", "document"}
    if not (page_match or section_match or document_locator):
        return set()
    matches: set[str] = set()
    for item in blocks:
        if not isinstance(item, Mapping):
            continue
        block_id = " ".join(str(item.get("block_id") or "").split())
        if not BLOCK_ID_RE.fullmatch(block_id):
            continue
        locator_kind = " ".join(str(item.get("locator_kind") or "").split()).casefold()
        matched = False
        if page_match and locator_kind == "page":
            try:
                matched = int(item.get("page")) == int(page_match.group(1))
            except (TypeError, ValueError):
                matched = False
        elif section_match and locator_kind == "section":
            target = section_match.group(1).strip()
            if target:
                matched = target in {
                    " ".join(str(item.get("anchor") or "").split()),
                    " ".join(str(item.get("heading") or "").split()),
                }
        elif document_locator and locator_kind == "section":
            matched = " ".join(str(item.get("anchor") or "").split()).casefold() == "document"
        if matched:
            matches.add(block_id)
    return matches


def resolve_source_reading_targets(
    project_root: Path,
    source: Mapping[str, Any] | Any,
    locators: Sequence[Any],
) -> tuple[SourceReadingTarget | None, ...]:
    """Resolve many locators against one anchored document/map snapshot."""

    requested = tuple(locators)
    if not isinstance(source, Mapping):
        return tuple(None for _item in requested)
    raw_document = str(source.get("markdown_path") or "").strip()
    if PurePosixPath(raw_document).suffix.lower() != ".md":
        return tuple(None for _item in requested)
    document = snapshot_project_file(
        project_root,
        raw_document,
        max_bytes=_MAX_DOCUMENT_BYTES,
    )
    if document is None:
        return tuple(None for _item in requested)
    expected_hash = " ".join(str(source.get("markdown_hash") or "").split()).casefold()
    if expected_hash:
        if not _SHA256_RE.fullmatch(expected_hash) or document.byte_sha256 != expected_hash:
            return tuple(None for _item in requested)
    markdown_path = _vault_markdown_path(project_root, document.path)
    if not markdown_path:
        return tuple(None for _item in requested)

    payload, source_map = _source_map_payload(project_root, source)
    source_map_current = bool(payload) and source_map is not None and source_map.is_current()
    if not document.is_current():
        return tuple(None for _item in requested)
    document_target = SourceReadingTarget(markdown_path=markdown_path)
    resolved: list[SourceReadingTarget | None] = []
    for locator in requested:
        normalized_locator = " ".join(str(locator or "").split())
        candidates = _matching_block_ids(payload, normalized_locator)
        if source_map_current and len(candidates) == 1:
            block_id = next(iter(candidates))
            if _document_contains_unique_block(document, block_id):
                resolved.append(
                    SourceReadingTarget(
                        markdown_path=markdown_path,
                        block_id=block_id,
                    )
                )
                continue
        resolved.append(document_target)
    return tuple(resolved)


def resolve_source_reading_target(
    project_root: Path,
    source: Mapping[str, Any] | Any,
    locator: Any,
) -> SourceReadingTarget | None:
    """Return an exact source block, a document fallback, or no unsafe link."""

    return resolve_source_reading_targets(project_root, source, (locator,))[0]


__all__ = [
    "SourceReadingTarget",
    "resolve_canonical_source_path",
    "resolve_source_reading_target",
    "resolve_source_reading_targets",
]

"""Mechanical relation normalization and inverse-edge projection.

This module deliberately knows nothing about research semantics beyond the
declared relation registry.  It never proposes or confirms a relationship.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable


LOCATOR_KINDS = frozenset({"unit", "heading", "block"})
BLOCK_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")
RELATION_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)?$")

RELATION_INVERSES: dict[str, str] = {
    "cites": "cited_by",
    "cited_by": "cites",
    "builds_on": "extended_by",
    "extended_by": "builds_on",
    "implements": "implemented_by",
    "implemented_by": "implements",
    "uses_dataset": "used_by",
    "used_by": "uses_dataset",
    "supports": "supported_by",
    "supported_by": "supports",
    "contradicts": "contradicted_by",
    "contradicted_by": "contradicts",
    "part_of": "contains",
    "contains": "part_of",
    "related_to": "related_to",
    "similar_to": "similar_to",
}

SYMMETRIC_RELATIONS = frozenset(
    relation for relation, inverse in RELATION_INVERSES.items() if relation == inverse
)


def normalize_relation_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    legacy = text.startswith("reverse:")
    if legacy:
        text = text.split(":", 1)[1]
    text = re.sub(r"[\s-]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or not text[0].isalpha():
        raise SystemExit(f"Invalid relation name: {value!r}")
    relation = f"reverse:{text}" if legacy else text
    if not RELATION_RE.fullmatch(relation):
        raise SystemExit(f"Invalid relation name: {value!r}")
    return relation


def inverse_relation(relation: str) -> str:
    normalized = normalize_relation_name(relation)
    if normalized.startswith("reverse:"):
        return normalized.split(":", 1)[1]
    return RELATION_INVERSES.get(normalized, f"reverse:{normalized}")


def stable_block_id(value: Any, *, prefix: str = "block") -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    candidate = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-").lower()
    if candidate and BLOCK_ID_RE.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    safe_prefix = re.sub(r"[^A-Za-z0-9-]+", "-", prefix).strip("-").lower() or "block"
    return f"{safe_prefix}-{digest}"


def normalize_locator(value: Any, *, field: str = "locator") -> dict[str, str] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise SystemExit(f"{field} must be a mapping with kind/value.")
    kind = str(value.get("kind") or "").strip().casefold()
    if kind not in LOCATOR_KINDS:
        raise SystemExit(f"{field}.kind must be one of: {', '.join(sorted(LOCATOR_KINDS))}")
    locator_value = re.sub(r"\s+", " ", str(value.get("value") or "")).strip()
    if kind == "unit":
        return {"kind": "unit", "value": ""}
    if not locator_value:
        raise SystemExit(f"{field}.value is required for {kind} locators.")
    if kind == "heading":
        if any(token in locator_value for token in ("#", "|", "[[", "]]")):
            raise SystemExit(f"{field}.value contains characters that cannot form a heading link.")
        return {"kind": "heading", "value": locator_value}
    return {"kind": "block", "value": stable_block_id(locator_value)}


def normalize_link(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit("Each record link must be a mapping.")
    target_id = str(value.get("target_id") or "").strip()
    if not target_id:
        raise SystemExit("Each record link requires target_id.")
    normalized: dict[str, Any] = {
        "target_id": target_id,
        "relation": normalize_relation_name(value.get("relation") or "related_to"),
        "note": str(value.get("note") or "").strip(),
    }
    for field in ("source_locator", "target_locator"):
        locator = normalize_locator(value.get(field), field=field)
        if locator and locator.get("kind") != "unit":
            normalized[field] = locator
    return normalized


def normalize_links(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for value in values:
        if not isinstance(value, dict) or not str(value.get("target_id") or "").strip():
            continue
        link = normalize_link(value)
        identity = link_identity(link)
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(link)
    return normalized


def link_identity(link: dict[str, Any]) -> tuple[Any, ...]:
    def locator_identity(name: str) -> tuple[str, str]:
        locator = link.get(name)
        if not isinstance(locator, dict):
            return ("", "")
        return (str(locator.get("kind") or ""), str(locator.get("value") or ""))

    return (
        str(link.get("target_id") or ""),
        str(link.get("relation") or ""),
        locator_identity("source_locator"),
        locator_identity("target_locator"),
    )


def project_relation_edges(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return explicit forward edges plus unpaired legacy reverse edges.

    Old records stored ``B --reverse:r--> A`` beside ``A --r--> B``.  Matching
    legacy copies are folded.  An orphan legacy copy is converted back to its
    forward shape and marked so audit can request migration without losing it.
    """
    explicit: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    explicit_keys: set[tuple[Any, ...]] = set()

    for record in records:
        source_id = str(record.get("id") or "").strip()
        if not source_id:
            continue
        for raw_link in record.get("links", []):
            try:
                link = normalize_link(raw_link)
            except SystemExit:
                continue
            relation = str(link["relation"])
            edge = {
                "source_id": source_id,
                "target_id": str(link["target_id"]),
                "relation": relation,
                "note": str(link.get("note") or ""),
                "source_locator": link.get("source_locator"),
                "target_locator": link.get("target_locator"),
                "provenance": "explicit",
            }
            if relation.startswith("reverse:"):
                legacy.append(edge)
                continue
            key = _edge_identity(edge)
            if key in explicit_keys:
                continue
            explicit_keys.add(key)
            explicit.append(edge)

    converted: list[dict[str, Any]] = []
    for edge in legacy:
        forward = {
            "source_id": edge["target_id"],
            "target_id": edge["source_id"],
            "relation": str(edge["relation"]).split(":", 1)[1],
            "note": edge["note"],
            "source_locator": edge.get("target_locator"),
            "target_locator": edge.get("source_locator"),
            "provenance": "legacy_reverse",
        }
        if _edge_identity(forward) in explicit_keys:
            continue
        key = _edge_identity(forward)
        if any(_edge_identity(item) == key for item in converted):
            continue
        converted.append(forward)
    return sorted(
        [*explicit, *converted],
        key=lambda edge: (
            str(edge["source_id"]),
            str(edge["relation"]),
            str(edge["target_id"]),
            str(edge.get("provenance") or ""),
        ),
    )


def _edge_identity(edge: dict[str, Any]) -> tuple[Any, ...]:
    link = {
        "target_id": edge.get("target_id"),
        "relation": edge.get("relation"),
        "source_locator": edge.get("source_locator"),
        "target_locator": edge.get("target_locator"),
    }
    return (str(edge.get("source_id") or ""), *link_identity(link))


__all__ = [
    "LOCATOR_KINDS",
    "BLOCK_ID_RE",
    "RELATION_INVERSES",
    "SYMMETRIC_RELATIONS",
    "normalize_relation_name",
    "inverse_relation",
    "stable_block_id",
    "normalize_locator",
    "normalize_link",
    "normalize_links",
    "link_identity",
    "project_relation_edges",
]

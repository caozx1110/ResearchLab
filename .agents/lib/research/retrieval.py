"""Lightweight full-text retrieval helpers for records."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Callable

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*|[^\W\x00-\x7f]+", re.IGNORECASE)

FIELD_WEIGHTS = {
    "title": 8,
    "summary": 5,
    "tags": 6,
    "topics": 6,
    "candidate_pools": 5,
    "payload": 2,
    "markdown": 1,
}


def tokenize_query(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def _leaf_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        items: list[str] = []
        for child in value.values():
            items.extend(_leaf_text(child))
        return items
    if isinstance(value, list):
        items = []
        for child in value:
            items.extend(_leaf_text(child))
        return items
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def _read_markdown(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(chunks)


def record_search_fields(record: dict[str, Any], *, markdown_paths: list[Path] | None = None) -> dict[str, str]:
    return {
        "title": str(record.get("title") or ""),
        "summary": str(record.get("summary") or ""),
        "tags": " ".join(str(item) for item in record.get("tags", []) if str(item).strip()),
        "topics": " ".join(str(item) for item in record.get("topics", []) if str(item).strip()),
        "candidate_pools": " ".join(str(item) for item in record.get("candidate_pools", []) if str(item).strip()),
        "payload": " ".join(_leaf_text(record.get("payload", {}))),
        "markdown": _read_markdown(markdown_paths or []),
    }


def score_record(record: dict[str, Any], query_tokens: list[str], *, markdown_paths: list[Path] | None = None) -> dict[str, Any]:
    fields = record_search_fields(record, markdown_paths=markdown_paths)
    score = 0
    reasons: list[str] = []
    for field, text in fields.items():
        lowered = text.lower()
        matched = [token for token in query_tokens if token in lowered]
        if not matched:
            continue
        weight = FIELD_WEIGHTS[field]
        score += weight * len(set(matched))
        reasons.append(f"{field}:{','.join(sorted(set(matched))[:3])}")
    return {"score": score, "reasons": reasons, "matched": score > 0}


def rank_records(
    records: list[dict[str, Any]],
    query: str,
    *,
    markdown_paths_for: Callable[[dict[str, Any]], list[Path]] | None = None,
) -> list[dict[str, Any]]:
    query_tokens = tokenize_query(query)
    if not query_tokens:
        return list(records)
    ranked: list[dict[str, Any]] = []
    for record in records:
        payload = score_record(record, query_tokens, markdown_paths=(markdown_paths_for(record) if markdown_paths_for else []))
        if not payload["matched"]:
            continue
        item = copy.deepcopy(record)
        item["_search_score"] = payload["score"]
        item["_search_reasons"] = payload["reasons"]
        ranked.append(item)
    ranked.sort(key=lambda item: (-int(item.get("_search_score") or 0), str(item.get("kind") or ""), str(item.get("title") or ""), str(item.get("id") or "")))
    return ranked

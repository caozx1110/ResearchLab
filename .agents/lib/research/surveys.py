"""Pure survey upstream bindings and consumer-side freshness checks.

The helpers in this module compare deterministic bytes and metadata only. They
never interpret research content, write a survey, or promote a judgement.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .common import file_sha256
from .records import iter_records, locate_record


def _canonical_digest_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _canonical_digest_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_digest_value(item) for item in value]
    if isinstance(value, str):
        return " ".join(value.split())
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return " ".join(str(value).split())


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        _canonical_digest_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_content_digest(record: dict[str, Any]) -> str:
    content = copy.deepcopy(record)
    for volatile in ("created_at", "updated_at", "history", "confirmation"):
        content.pop(volatile, None)
    return _canonical_digest(content)


def _evidence_artifact_bindings(unit_dir: Path) -> list[dict[str, str]]:
    if not unit_dir.is_dir() or unit_dir.is_symlink():
        raise SystemExit(f"Survey source unit is not a safe directory: {unit_dir.name}")
    bindings: list[dict[str, str]] = []
    for path in sorted(unit_dir.rglob("*"), key=lambda item: item.relative_to(unit_dir).as_posix()):
        artifact = path.relative_to(unit_dir).as_posix()
        if path.is_symlink() or not path.is_file() or artifact == "record.yaml":
            continue
        bindings.append({"artifact": artifact, "byte_sha256": file_sha256(path)})
    return bindings


def build_unit_binding(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    unit_id = str(record.get("id") or "").strip()
    unit_kind = str(record.get("kind") or "").strip()
    if not unit_id or not unit_kind:
        raise SystemExit("Survey source unit requires canonical id and kind.")
    current, record_file = locate_record(root, unit_id, kind=unit_kind, fuzzy=False)
    if str(current.get("id") or "") != unit_id or str(current.get("kind") or "") != unit_kind:
        raise SystemExit(f"Survey source identity changed while anchoring: {unit_kind}/{unit_id}")
    confirmation = current.get("confirmation")
    return {
        "id": unit_id,
        "kind": unit_kind,
        "title": str(current.get("title") or ""),
        "record_content_digest": _record_content_digest(current),
        "confirmation_receipt_digest": (
            _canonical_digest(confirmation) if isinstance(confirmation, dict) and confirmation else ""
        ),
        "evidence_artifacts": _evidence_artifact_bindings(record_file.parent),
    }


def unit_bindings_equal(left: object, right: object) -> bool:
    return _canonical_digest_value(left) == _canonical_digest_value(right)


def select_survey_records(
    records: list[dict[str, Any]],
    *,
    query: str = "",
    kind: str = "",
    topic: str = "",
    tag: str = "",
    pool: str = "",
) -> list[dict[str, Any]]:
    tokens = [token for token in query.lower().split() if token]
    selected: list[dict[str, Any]] = []
    for record in records:
        if kind and str(record.get("kind") or "") != kind:
            continue
        if topic and topic not in record.get("topics", []):
            continue
        if tag and tag not in record.get("tags", []):
            continue
        if pool and pool not in record.get("candidate_pools", []):
            continue
        haystack = " ".join(
            [
                str(record.get("title") or ""),
                str(record.get("summary") or ""),
                " ".join(record.get("tags", [])),
                " ".join(record.get("topics", [])),
                " ".join(record.get("candidate_pools", [])),
            ]
        ).lower()
        if tokens and not all(token in haystack for token in tokens):
            continue
        selected.append(record)
    return selected


def survey_staleness(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    """Byte-level pure read of one verified survey's current upstream state."""
    binding = payload.get("consumer_binding") if isinstance(payload, dict) else None
    if not isinstance(binding, dict):
        return {"stale": True, "reasons": ["missing consumer_binding"], "new_unit_ids": []}
    stored_units = binding.get("units")
    stored_unit_ids = binding.get("unit_ids")
    filters = binding.get("selection_filters")
    if not isinstance(stored_units, list) or not isinstance(stored_unit_ids, list) or not isinstance(filters, dict):
        return {"stale": True, "reasons": ["consumer_binding is incomplete"], "new_unit_ids": []}

    reasons: list[str] = []
    stored_by_id = {
        str(item.get("id") or ""): item
        for item in stored_units
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    if set(str(unit_id) for unit_id in stored_unit_ids) != set(stored_by_id):
        reasons.append("consumer_binding.unit_ids does not match units")
    for unit_id, stored in sorted(stored_by_id.items()):
        try:
            current = build_unit_binding(root, stored)
        except (OSError, SystemExit):
            reasons.append(f"deleted or unreadable unit: {unit_id}")
            continue
        if not unit_bindings_equal(current, stored):
            reasons.append(f"changed unit: {unit_id}")

    selected = select_survey_records(
        iter_records(root),
        query=str(filters.get("query") or ""),
        kind=str(filters.get("kind") or ""),
        topic=str(filters.get("topic") or ""),
        tag=str(filters.get("tag") or ""),
        pool=str(filters.get("pool") or ""),
    )
    current_ids = {str(record.get("id") or "") for record in selected if str(record.get("id") or "")}
    new_unit_ids = sorted(current_ids - set(stored_by_id))
    reasons.extend(f"new matching unit: {unit_id}" for unit_id in new_unit_ids)
    return {"stale": bool(reasons), "reasons": reasons, "new_unit_ids": new_unit_ids}


__all__ = ["build_unit_binding", "select_survey_records", "survey_staleness", "unit_bindings_equal"]

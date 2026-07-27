"""Build a bounded, read-only context pack from an existing retrieval result.

The pack has two deliberately separate lanes:

* ``formal`` contains only canonical claims covered by a current human
  ConfirmationReceipt and current record/evidence snapshots.
* ``navigation`` carries record summaries and already-computed passage excerpts
  as unconfirmed hints.  It never upgrades those derived strings into claims.

This module does not search, summarize, write a cache, or mutate the knowledge
base.  Callers pass the records/passages from the same retrieval round so
``kb find`` does not pay for a second search.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from .evidence import confirmation_claims, validate_claims
from .judgements import judgement_confirmation_is_current
from .records import (
    CanonicalRecordSnapshot,
    iter_canonical_record_snapshots,
    normalize_record_snapshot,
    require_current_record_snapshot,
    trusted_claim_source_roots,
)


CONTEXT_PACK_SCHEMA = "context-pack/v1"
MAX_UNITS = 5
MAX_CLAIMS_PER_UNIT = 3
MAX_REFS_PER_CLAIM = 2
MAX_UTF8_BYTES = 6000

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_ABSOLUTE_FRAGMENT = re.compile(r"(?:^|[\s'\"(=:])(?:/[A-Za-z0-9._-]+/|[A-Za-z]:[\\/])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_OMISSION_KEYS = (
    "duplicate_canonical_unit_id",
    "missing_or_unsafe_unit",
    "rejected_unit",
    "unit_limit",
    "pending_confirmation_claim",
    "stale_confirmation_claim",
    "duplicate_claim_id",
    "invalid_claim",
    "incomplete_evidence",
    "claim_limit",
    "evidence_ref_limit",
    "unsafe_navigation",
    "byte_budget",
    "aggregate_recheck",
)


def serialized_context_pack_size(pack: Mapping[str, Any]) -> int:
    """Return the conservative pretty-JSON UTF-8 size used by the budget."""
    return len(
        json.dumps(
            pack,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _single_line(value: Any) -> str:
    return " ".join(_text(value).split())


def _has_absolute_path(text: str) -> bool:
    return bool(Path(text).is_absolute() or _WINDOWS_ABSOLUTE.match(text) or _ABSOLUTE_FRAGMENT.search(text))


def _safe_descriptive_text(value: Any, project_root: Path) -> str:
    text = _text(value)
    if not text or _CONTROL.search(text):
        return ""
    root_text = project_root.as_posix().rstrip("/")
    if (
        (root_text and root_text in text)
        or _has_absolute_path(text)
    ):
        return ""
    return text


def _safe_verbatim_text(value: Any, project_root: Path) -> str:
    text = "" if value is None else str(value)
    root_text = project_root.as_posix().rstrip("/")
    if (
        not text.strip()
        or _CONTROL.search(text)
        or (root_text and root_text in text)
        or _has_absolute_path(text)
    ):
        return ""
    return text


def _safe_relative_artifact(value: Any) -> str:
    artifact = _text(value)
    if (
        not artifact
        or _CONTROL.search(artifact)
        or "://" in artifact
        or Path(artifact).is_absolute()
        or _WINDOWS_ABSOLUTE.match(artifact)
    ):
        return ""
    parts = Path(artifact).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return ""
    return Path(*parts).as_posix()


def _safe_locator(value: Any) -> str:
    locator = _text(value)
    if (
        not locator
        or _CONTROL.search(locator)
        or _has_absolute_path(locator)
    ):
        return ""
    return locator


def _candidate_unit_ids(
    matched_records: Sequence[Mapping[str, Any]],
    passages: Sequence[Mapping[str, Any]],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for items, field in ((passages, "unit_id"), (matched_records, "id")):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            unit_id = _text(item.get(field))
            if unit_id and unit_id not in seen:
                seen.add(unit_id)
                ordered.append(unit_id)
    return ordered


def _snapshot_index(
    project_root: Path,
) -> dict[str, CanonicalRecordSnapshot | None]:
    index: dict[str, CanonicalRecordSnapshot | None] = {}
    for snapshot in iter_canonical_record_snapshots(project_root):
        if snapshot.unit_id in index:
            index[snapshot.unit_id] = None
        else:
            index[snapshot.unit_id] = snapshot
    return index


def _navigation_passage(
    passage: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any] | None:
    artifact = _safe_relative_artifact(passage.get("artifact"))
    locator = _safe_locator(passage.get("locator"))
    excerpt = _safe_descriptive_text(passage.get("excerpt"), project_root)
    heading = _safe_descriptive_text(passage.get("heading"), project_root)
    if not artifact or not locator or not excerpt:
        return None
    try:
        line_start = max(0, int(passage.get("line_start") or 0))
        line_end = max(0, int(passage.get("line_end") or 0))
    except (TypeError, ValueError, OverflowError):
        line_start = line_end = 0
    if line_start and line_end < line_start:
        line_start = line_end = 0
    return {
        "confirmation_bound": False,
        "excerpt": excerpt,
        "artifact": artifact,
        "locator": locator,
        "heading": _single_line(heading),
        "line_start": line_start,
        "line_end": line_end,
    }


def _formal_claim(
    claim: Mapping[str, Any],
    omissions: Counter[str],
    project_root: Path,
) -> dict[str, Any] | None:
    if validate_claims([claim]):
        omissions["invalid_claim"] += 1
        return None
    text = _safe_descriptive_text(claim.get("text"), project_root)
    if not text:
        omissions["invalid_claim"] += 1
        return None
    refs = claim.get("evidence_refs")
    refs = list(refs) if isinstance(refs, (list, tuple)) else []
    if not refs:
        omissions["incomplete_evidence"] += 1
        return None
    exported_refs: list[dict[str, str]] = []
    for ref in refs:
        if not isinstance(ref, Mapping):
            omissions["incomplete_evidence"] += 1
            return None
        artifact = _safe_relative_artifact(ref.get("artifact"))
        locator = _safe_locator(ref.get("locator"))
        source_unit_id = _text(ref.get("source_unit_id"))
        quote = _safe_verbatim_text(ref.get("quote"), project_root)
        if not source_unit_id or not artifact or not locator or not quote:
            omissions["incomplete_evidence"] += 1
            return None
        exported_refs.append(
            {
                "source_unit_id": source_unit_id,
                "artifact": artifact,
                "locator": locator,
                "quote": quote,
            }
        )
    if len(exported_refs) > MAX_REFS_PER_CLAIM:
        omissions["evidence_ref_limit"] += len(exported_refs) - MAX_REFS_PER_CLAIM
    return {
        "confirmation_bound": True,
        "id": _text(claim.get("id")),
        "text": text,
        "claim_type": _text(claim.get("claim_type")),
        "evidence_refs": exported_refs[:MAX_REFS_PER_CLAIM],
    }


def _current_formal_claims(
    project_root: Path,
    snapshot: CanonicalRecordSnapshot,
    record: dict[str, Any],
    omissions: Counter[str],
) -> tuple[list[dict[str, Any]], tuple[Callable[[], bool], ...]]:
    claims = confirmation_claims(record)
    if _text(record.get("confirmation_status")) != "confirmed":
        omissions["pending_confirmation_claim"] += len(claims)
        return [], ()
    try:
        receipt_current = judgement_confirmation_is_current(
            project_root,
            record,
            snapshot.path,
            record_snapshot=snapshot,
        )
        source_roots = trusted_claim_source_roots(
            project_root,
            record,
            verification_root=snapshot.path.parent,
            expected_record_snapshot=snapshot,
        )
    except (OSError, RuntimeError, UnicodeError, TypeError, ValueError, SystemExit):
        receipt_current = False
        source_roots = {}
    if not receipt_current:
        omissions["stale_confirmation_claim"] += max(1, len(claims))
        return [], ()

    receipt = record.get("confirmation")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    receipt_ids = {
        _text(item)
        for item in receipt.get("claim_ids", [])
        if _text(item)
    } if isinstance(receipt.get("claim_ids"), list) else set()
    id_counts = Counter(_text(claim.get("id")) for claim in claims)
    duplicate_ids = {claim_id for claim_id, count in id_counts.items() if claim_id and count > 1}

    exported: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = _text(claim.get("id"))
        if claim_id in duplicate_ids:
            omissions["duplicate_claim_id"] += 1
            continue
        if not claim_id or claim_id not in receipt_ids:
            omissions["stale_confirmation_claim"] += 1
            continue
        item = _formal_claim(claim, omissions, project_root)
        if item is not None:
            exported.append(item)
    if len(exported) > MAX_CLAIMS_PER_UNIT:
        omissions["claim_limit"] += len(exported) - MAX_CLAIMS_PER_UNIT
        exported = exported[:MAX_CLAIMS_PER_UNIT]
    validators = tuple(
        source.is_current
        for source in source_roots.values()
        if callable(getattr(source, "is_current", None))
    )
    return exported, validators


def _recheck_formal_unit(
    project_root: Path,
    snapshot: CanonicalRecordSnapshot,
    record: dict[str, Any],
    evidence_validators: tuple[Callable[[], bool], ...],
) -> bool:
    try:
        require_current_record_snapshot(project_root, snapshot)
        if not all(bool(validate()) for validate in evidence_validators):
            return False
        return judgement_confirmation_is_current(
            project_root,
            record,
            snapshot.path,
            record_snapshot=snapshot,
        )
    except (OSError, RuntimeError, UnicodeError, TypeError, ValueError, SystemExit):
        return False


def _apply_budget(pack: dict[str, Any], max_utf8_bytes: int) -> None:
    omissions = pack["omissions"]
    units = pack["units"]
    while serialized_context_pack_size(pack) > max_utf8_bytes:
        removed = False
        for unit in reversed(units):
            passages = unit["navigation"]["passages"]
            if passages:
                passages.pop()
                omissions["byte_budget"] += 1
                removed = True
                break
        if removed:
            continue
        for unit in reversed(units):
            summary = unit["navigation"].get("summary")
            if summary is not None:
                unit["navigation"]["summary"] = None
                omissions["byte_budget"] += 1
                removed = True
                break
        if removed:
            continue
        for unit in reversed(units):
            claims = unit["formal"]["claims"]
            if claims:
                claims.pop()
                omissions["byte_budget"] += 1
                removed = True
                break
        if removed:
            continue
        if units:
            units.pop()
            omissions["byte_budget"] += 1
            continue
        if pack.get("query"):
            pack["query"] = ""
            omissions["byte_budget"] += 1
            continue
        break


def build_context_pack(
    project_root: Path,
    *,
    query: str,
    matched_records: Sequence[Mapping[str, Any]],
    passages: Sequence[Mapping[str, Any]],
    max_utf8_bytes: int = MAX_UTF8_BYTES,
) -> dict[str, Any]:
    """Assemble ``context-pack/v1`` without rerunning retrieval or writing files.

    Candidate order is the passage order followed by record-result order.  The
    supplied mappings select candidates and provide navigation excerpts only;
    formal content is always reloaded from unique canonical record snapshots.
    """
    if max_utf8_bytes <= 0:
        raise ValueError("max_utf8_bytes must be positive")
    root = project_root.absolute()
    omissions: Counter[str] = Counter({key: 0 for key in _OMISSION_KEYS})
    snapshots = _snapshot_index(root)
    passages_by_unit: dict[str, list[Mapping[str, Any]]] = {}
    for passage in passages:
        if isinstance(passage, Mapping):
            passages_by_unit.setdefault(_text(passage.get("unit_id")), []).append(passage)

    units: list[dict[str, Any]] = []
    formal_rechecks: list[
        tuple[dict[str, Any], CanonicalRecordSnapshot, dict[str, Any], tuple[Callable[[], bool], ...]]
    ] = []
    for unit_id in _candidate_unit_ids(matched_records, passages):
        if len(units) >= MAX_UNITS:
            omissions["unit_limit"] += 1
            continue
        if unit_id not in snapshots:
            omissions["missing_or_unsafe_unit"] += 1
            continue
        snapshot = snapshots[unit_id]
        if snapshot is None:
            omissions["duplicate_canonical_unit_id"] += 1
            continue
        record = normalize_record_snapshot(snapshot, root)
        if record is None:
            omissions["missing_or_unsafe_unit"] += 1
            continue
        if _text(record.get("confirmation_status")) == "rejected":
            omissions["rejected_unit"] += 1
            continue

        claims, validators = _current_formal_claims(root, snapshot, record, omissions)
        navigation_passages: list[dict[str, Any]] = []
        seen_navigation: set[tuple[str, str, str]] = set()
        for passage in passages_by_unit.get(unit_id, []):
            item = _navigation_passage(passage, root)
            if item is None:
                omissions["unsafe_navigation"] += 1
                continue
            identity = (item["artifact"], item["locator"], item["excerpt"])
            if identity in seen_navigation:
                continue
            seen_navigation.add(identity)
            navigation_passages.append(item)
        summary_text = _safe_descriptive_text(record.get("summary"), root)
        summary = (
            {"confirmation_bound": False, "text": summary_text}
            if summary_text and not _CONTROL.search(summary_text)
            else None
        )
        unit = {
            "unit_id": unit_id,
            "kind": _text(record.get("kind")),
            "title": _single_line(_safe_descriptive_text(record.get("title"), root)) or unit_id,
            "formal": {"confirmation_bound": True, "claims": claims},
            "navigation": {
                "confirmation_bound": False,
                "summary": summary,
                "passages": navigation_passages,
            },
        }
        units.append(unit)
        if claims:
            formal_rechecks.append((unit, snapshot, record, validators))

    for unit, snapshot, record, validators in formal_rechecks:
        if _recheck_formal_unit(root, snapshot, record, validators):
            continue
        removed_count = len(unit["formal"]["claims"])
        unit["formal"]["claims"] = []
        omissions["aggregate_recheck"] += removed_count

    pack: dict[str, Any] = {
        "schema": CONTEXT_PACK_SCHEMA,
        "query": _single_line(_safe_descriptive_text(query, root)),
        "limits": {
            "units": MAX_UNITS,
            "claims_per_unit": MAX_CLAIMS_PER_UNIT,
            "evidence_refs_per_claim": MAX_REFS_PER_CLAIM,
            "utf8_bytes": max_utf8_bytes,
        },
        "units": units,
        "omissions": {key: int(omissions[key]) for key in _OMISSION_KEYS},
    }
    _apply_budget(pack, max_utf8_bytes)
    return pack


__all__ = [
    "CONTEXT_PACK_SCHEMA",
    "MAX_UNITS",
    "MAX_CLAIMS_PER_UNIT",
    "MAX_REFS_PER_CLAIM",
    "MAX_UTF8_BYTES",
    "build_context_pack",
    "serialized_context_pack_size",
]

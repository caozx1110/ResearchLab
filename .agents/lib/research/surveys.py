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

from .common import file_sha256, utc_now_iso
from .confirm import has_complete_confirmation_receipt
from .records import (
    iter_records,
    locate_record,
    trusted_claim_source_roots,
    trusted_project_path,
)


COMPOSITE_SURVEY_STAGES = (
    "search",
    "selection",
    "intake_analysis",
    "synthesis",
    "review_confirmation",
)
COMPOSITE_STAGE_STATUSES = {"pending", "in_progress", "blocked", "completed"}
COMPOSITE_STATE_STATUSES = {"in_progress", "blocked", "completed"}
COMPOSITE_STATE_FIELDS = {
    "schema_version",
    "kind",
    "id",
    "request_digest",
    "mode",
    "selection_filters",
    "current_stage",
    "status",
    "created_at",
    "updated_at",
    "revision",
    "stages",
}
COMPOSITE_STAGE_FIELDS = {
    "id",
    "order",
    "status",
    "inputs",
    "outputs",
    "blocker",
    "resume_action",
}


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
    for volatile in (
        "created_at",
        "first_ingested_at",
        "updated_at",
        "last_human_confirmed_at",
        "history",
        "confirmation",
    ):
        content.pop(volatile, None)
    return _canonical_digest(content)


def survey_content_digest(payload: dict[str, Any]) -> str:
    """Bind all agent-authored survey substance, not only canonical claim text."""
    anchor = payload.get("kb_anchor") if isinstance(payload, dict) else None
    anchor = anchor if isinstance(anchor, dict) else {}
    return _canonical_digest(
        {
            "mode": payload.get("mode"),
            "slug": payload.get("slug"),
            "program_ids": payload.get("program_ids"),
            "filters": payload.get("filters"),
            "as_of": anchor.get("as_of"),
            "sections": payload.get("sections"),
            "comparison_matrix": payload.get("comparison_matrix"),
        }
    )


def survey_artifact_path(root: Path, slug: str, mode: str = "survey") -> Path:
    """Resolve a canonical survey path without trusting an owner-supplied path."""
    clean_slug = str(slug or "").strip()
    clean_mode = str(mode or "").strip()
    if (
        not clean_slug
        or Path(clean_slug).name != clean_slug
        or clean_slug in {".", ".."}
        or clean_mode not in {"survey", "review", "taxonomy"}
    ):
        raise ValueError("survey identity is not canonical")
    return root / "kb" / "synthesis" / clean_slug / f"{clean_mode}.yaml"


def survey_source_roots(root: Path, record: dict[str, Any], artifact_path: Path) -> dict[str, Path]:
    """Resolve survey evidence sources from canonical unit identities."""
    root = root.resolve()
    artifact_path = artifact_path.resolve()
    verification_root = trusted_project_path(
        root,
        artifact_path.parent,
        allowed_root=root / "kb" / "synthesis",
        require="dir",
    )
    return trusted_claim_source_roots(root, record, verification_root=verification_root)


def survey_input_eligibility_violations(root: Path, record: dict[str, Any]) -> list[str]:
    """Return why a unit cannot be an input to a new survey.

    This is a mechanical confirmation/containment/byte check.  It does not rank
    sources or decide whether a paper is relevant.
    """
    unit_id = str(record.get("id") or "").strip()
    unit_kind = str(record.get("kind") or "").strip()
    if not unit_id or not unit_kind:
        return ["missing canonical unit identity"]
    try:
        current, record_file = locate_record(root, unit_id, kind=unit_kind, fuzzy=False)
    except (OSError, SystemExit):
        return ["canonical unit is missing or unreadable"]
    if str(current.get("confirmation_status") or "") != "confirmed":
        return ["unit is not confirmed"]
    try:
        source_roots = trusted_claim_source_roots(
            root,
            current,
            verification_root=record_file.parent,
        )
    except ValueError:
        return ["unit evidence source is not canonically contained"]
    if not has_complete_confirmation_receipt(
        current,
        verification_root=record_file.parent,
        source_roots=source_roots,
    ):
        return ["unit confirmation receipt is missing or stale"]
    return []


def select_current_confirmed_survey_records(
    root: Path,
    records: list[dict[str, Any]],
    **filters: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select matching inputs and partition out mechanically ineligible units."""
    selected = select_survey_records(records, **filters)
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for record in selected:
        violations = survey_input_eligibility_violations(root, record)
        if violations:
            excluded.append(
                {
                    "id": str(record.get("id") or ""),
                    "kind": str(record.get("kind") or ""),
                    "reasons": violations,
                }
            )
        else:
            eligible.append(record)
    return eligible, excluded


def evidence_gap_handoff(
    *,
    filters: dict[str, str],
    excluded: list[dict[str, Any]] | None = None,
    composite_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured discovery/intake/analysis handoff with an optional durable binding."""
    return {
        "status": "evidence_gap",
        "reason": "no_current_confirmed_units",
        "selection_filters": {str(key): str(value or "") for key, value in filters.items()},
        "excluded_inputs": copy.deepcopy(excluded or []),
        "composite_handoff": {
            "entry_stage": "search",
            "ordered_stages": list(COMPOSITE_SURVEY_STAGES),
            "resume_action": "discover_select_intake_analyze_then_retry_synthesis",
            "state_binding": copy.deepcopy(composite_binding or {}),
        },
    }


def composite_survey_request_digest(
    *,
    filters: dict[str, str],
    as_of: str,
    mode: str,
) -> str:
    return _canonical_digest(
        {
            "filters": {str(key): str(value or "") for key, value in filters.items()},
            "as_of": str(as_of or ""),
            "mode": str(mode or ""),
        }
    )


def composite_survey_state_path(root: Path, *, slug: str, composite_id: str) -> Path:
    safe_slug = str(slug or "").strip()
    safe_id = str(composite_id or "").strip()
    for label, value in (("slug", safe_slug), ("composite id", safe_id)):
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError(f"composite survey {label} is not canonical")
    return root / "kb" / "synthesis" / safe_slug / "composite-requests" / f"{safe_id}.yaml"


def new_composite_survey_state(
    *,
    composite_id: str,
    request_digest: str,
    mode: str,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a durable, semantics-free stage ledger for a composite survey."""
    identifier = str(composite_id or "").strip()
    digest = str(request_digest or "").strip()
    if not identifier or Path(identifier).name != identifier or identifier in {".", ".."}:
        raise ValueError("composite survey id is not canonical")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("composite survey request_digest must be lowercase sha256")
    if mode not in {"kb_only", "discovery"}:
        raise ValueError("composite survey mode must be kb_only or discovery")
    now = utc_now_iso()
    return {
        "schema_version": 1,
        "kind": "composite_survey_state",
        "id": identifier,
        "request_digest": digest,
        "mode": mode,
        "selection_filters": copy.deepcopy(filters or {}),
        "revision": 1,
        "current_stage": COMPOSITE_SURVEY_STAGES[0],
        "status": "in_progress",
        "created_at": now,
        "updated_at": now,
        "stages": [
            {
                "id": stage,
                "order": index,
                "status": "in_progress" if index == 0 else "pending",
                "inputs": [],
                "outputs": [],
                "blocker": {},
                "resume_action": "",
            }
            for index, stage in enumerate(COMPOSITE_SURVEY_STAGES)
        ],
    }


def composite_survey_state_violations(state: object) -> list[str]:
    """Validate stage order and resumability without interpreting research intent."""
    if not isinstance(state, dict):
        return ["composite survey state must be a mapping"]
    violations: list[str] = []
    if set(state) != COMPOSITE_STATE_FIELDS:
        violations.append("composite survey state fields are not canonical")
    if state.get("kind") != "composite_survey_state" or state.get("schema_version") != 1:
        violations.append("composite survey state kind/schema_version is invalid")
    identifier = str(state.get("id") or "")
    if not identifier or Path(identifier).name != identifier or identifier in {".", ".."}:
        violations.append("composite survey id is invalid")
    digest = str(state.get("request_digest") or "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        violations.append("composite survey request digest is invalid")
    if state.get("mode") not in {"kb_only", "discovery"}:
        violations.append("composite survey mode is invalid")
    filters = state.get("selection_filters")
    if not isinstance(filters, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in filters.items()
    ):
        violations.append("composite survey filters are invalid")
    if state.get("status") not in COMPOSITE_STATE_STATUSES:
        violations.append("composite survey status is invalid")
    if not str(state.get("created_at") or "") or not str(state.get("updated_at") or ""):
        violations.append("composite survey timestamps are missing")
    if type(state.get("revision")) is not int or int(state.get("revision") or 0) < 1:
        violations.append("composite survey revision is invalid")
    stages = state.get("stages")
    if not isinstance(stages, list) or [item.get("id") for item in stages if isinstance(item, dict)] != list(COMPOSITE_SURVEY_STAGES):
        return violations + ["composite survey stages are missing or out of order"]
    active: list[str] = []
    completed_prefix = True
    for index, item in enumerate(stages):
        if not isinstance(item, dict):
            violations.append(f"stage[{index}] must be a mapping")
            continue
        if set(item) != COMPOSITE_STAGE_FIELDS:
            violations.append(f"stage[{index}] fields are not canonical")
        if item.get("order") != index:
            violations.append(f"stage[{index}] order is invalid")
        status = str(item.get("status") or "")
        if status not in COMPOSITE_STAGE_STATUSES:
            violations.append(f"stage[{index}] status is invalid")
        if status in {"in_progress", "blocked"}:
            active.append(str(item.get("id") or ""))
        if status == "blocked" and (
            not isinstance(item.get("blocker"), dict)
            or not item.get("blocker")
            or not str(item.get("resume_action") or "").strip()
        ):
            violations.append(f"stage[{index}] blocked state lacks blocker/resume_action")
        if not isinstance(item.get("inputs"), list) or not isinstance(item.get("outputs"), list):
            violations.append(f"stage[{index}] inputs/outputs must be lists")
        if status == "completed" and not completed_prefix:
            violations.append(f"stage[{index}] completed before an earlier stage")
        if status != "completed":
            completed_prefix = False
    if len(active) > 1:
        violations.append("composite survey state has multiple active stages")
    current = str(state.get("current_stage") or "")
    if str(state.get("status") or "") == "completed":
        if any(item.get("status") != "completed" for item in stages):
            violations.append("completed composite survey has unfinished stages")
    elif active != [current]:
        violations.append("current_stage does not match the active stage")
    return violations


def update_composite_survey_stage(
    state: dict[str, Any],
    stage_id: str,
    *,
    status: str,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    blocker: dict[str, Any] | None = None,
    resume_action: str = "",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Return an updated stage ledger; callers persist it under their own journal."""
    violations = composite_survey_state_violations(state)
    if violations:
        raise ValueError("invalid composite survey state: " + "; ".join(violations))
    if expected_revision is not None and state.get("revision") != expected_revision:
        raise ValueError("composite survey state changed after it was displayed")
    if stage_id not in COMPOSITE_SURVEY_STAGES or status not in COMPOSITE_STAGE_STATUSES:
        raise ValueError("invalid composite survey stage update")
    updated = copy.deepcopy(state)
    index = COMPOSITE_SURVEY_STAGES.index(stage_id)
    if any(updated["stages"][prior]["status"] != "completed" for prior in range(index)):
        raise ValueError("cannot advance past an incomplete composite survey stage")
    if status == "completed" and index + 1 < len(COMPOSITE_SURVEY_STAGES):
        next_stage = updated["stages"][index + 1]
        next_stage["status"] = "in_progress"
        updated["current_stage"] = next_stage["id"]
    else:
        updated["current_stage"] = stage_id
    stage = updated["stages"][index]
    stage.update(
        {
            "status": status,
            "inputs": copy.deepcopy(inputs or []),
            "outputs": copy.deepcopy(outputs or []),
            "blocker": copy.deepcopy(blocker or {}),
            "resume_action": str(resume_action or ""),
        }
    )
    if status == "completed" and index + 1 == len(COMPOSITE_SURVEY_STAGES):
        updated["status"] = "completed"
    elif status == "blocked":
        updated["status"] = "blocked"
    else:
        updated["status"] = "in_progress"
    updated["updated_at"] = utc_now_iso()
    updated["revision"] = int(state["revision"]) + 1
    violations = composite_survey_state_violations(updated)
    if violations:
        raise ValueError("invalid composite survey stage transition: " + "; ".join(violations))
    return updated


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
    eligibility = survey_input_eligibility_violations(root, current)
    if eligibility:
        raise SystemExit(f"Survey source unit is not currently confirmed: {unit_id}")
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

    selected, _excluded = select_current_confirmed_survey_records(
        root,
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


def survey_lifecycle_violations(payload: object, root: Path) -> list[str]:
    """Return why a survey judgement's own/upstream byte bindings are stale."""
    if not isinstance(payload, dict):
        return ["survey judgement must be a mapping"]
    if payload.get("governance_status") == "needs_agent_repair":
        return ["legacy survey requires agent repair and re-verification"]
    if payload.get("kind") != "survey_judgement" or payload.get("owner") != "literature-synthesizer":
        return ["survey judgement owner identity is invalid"]
    program_ids = payload.get("program_ids", [])
    if not isinstance(program_ids, list) or program_ids != sorted(set(program_ids)) or any(
        not isinstance(item, str)
        or not item
        or Path(item).name != item
        or item in {".", ".."}
        for item in program_ids
    ):
        return ["survey judgement program_ids are invalid"]
    stored_digest = str(payload.get("survey_content_digest") or "")
    if len(stored_digest) != 64 or stored_digest != survey_content_digest(payload):
        return ["survey content digest is missing or stale"]
    canonical = payload.get("payload")
    claims = canonical.get("claims") if isinstance(canonical, dict) else None
    if not isinstance(claims, list) or not claims:
        return ["survey canonical claims are missing"]
    if any(str(claim.get("survey_content_digest") or "") != stored_digest for claim in claims if isinstance(claim, dict)):
        return ["survey canonical claims do not bind current survey content"]
    freshness = survey_staleness(payload, root)
    return [str(reason) for reason in freshness.get("reasons", [])] if freshness.get("stale") else []


__all__ = [
    "COMPOSITE_SURVEY_STAGES",
    "build_unit_binding",
    "composite_survey_state_violations",
    "composite_survey_request_digest",
    "composite_survey_state_path",
    "evidence_gap_handoff",
    "new_composite_survey_state",
    "select_current_confirmed_survey_records",
    "select_survey_records",
    "survey_artifact_path",
    "survey_content_digest",
    "survey_input_eligibility_violations",
    "survey_lifecycle_violations",
    "survey_source_roots",
    "survey_staleness",
    "unit_bindings_equal",
    "update_composite_survey_stage",
]

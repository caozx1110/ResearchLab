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

from .common import file_sha256, load_yaml, utc_now_iso
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
    "source_intake",
    "unit_analysis",
    "synthesis",
    "review_confirmation",
    "report_consumption",
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
COMPOSITE_BINDING_KIND = "composite-stage-binding"
COMPOSITE_BINDING_FIELDS = {
    "schema_version",
    "kind",
    "stage_id",
    "refs",
    "artifacts",
    "facts",
    "binding_digest",
}
COMPOSITE_ARTIFACT_FIELDS = {
    "role",
    "path",
    "artifact_kind",
    "artifact_id",
    "content_sha256",
}
TERMINAL_SEARCH_REASONS = {"target_met", "saturated", "budget_exhausted", "user_stop"}


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


def _exact_digest(value: object) -> str:
    encoded = json.dumps(
        value,
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
    reason: str = "no_current_confirmed_units",
) -> dict[str, Any]:
    """Structured discovery/intake/analysis handoff with an optional durable binding."""
    return {
        "status": "evidence_gap",
        "reason": str(reason or "no_current_confirmed_units"),
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


def pending_composite_survey_states(root: Path) -> list[dict[str, Any]]:
    """Discover current durable survey routes without mutating or interpreting them."""
    synthesis = root / "kb" / "synthesis"
    if not synthesis.exists():
        return []
    if synthesis.is_symlink() or not synthesis.is_dir():
        raise SystemExit("Survey synthesis root is unsafe.")
    pending: list[dict[str, Any]] = []
    for survey_root in sorted(synthesis.iterdir(), key=lambda item: item.name):
        if survey_root.is_symlink() or not survey_root.is_dir():
            continue
        requests = survey_root / "composite-requests"
        if not requests.exists():
            continue
        if requests.is_symlink() or not requests.is_dir():
            raise SystemExit("Composite survey request root is unsafe.")
        for path in sorted(requests.glob("*.yaml"), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                raise SystemExit("Composite survey state is unsafe.")
            state = load_yaml(path, default={})
            violations = composite_survey_state_violations(state)
            if violations:
                raise SystemExit("Composite survey state is invalid: " + "; ".join(violations))
            current_violations = composite_survey_current_violations(root, state)
            projected = (
                composite_survey_repair_projection(root, state)
                if current_violations
                else copy.deepcopy(state)
            )
            if projected.get("status") == "completed":
                continue
            pending.append(
                {
                    "slug": survey_root.name,
                    "path": path.relative_to(root).as_posix(),
                    "state": projected,
                    "state_digest": _canonical_digest(state),
                }
            )
    return pending


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
    root: Path | None = None,
) -> dict[str, Any]:
    """Return an updated ledger; completed transitions require the owner verifier."""
    violations = composite_survey_state_violations(state)
    if violations:
        raise ValueError("invalid composite survey state: " + "; ".join(violations))
    if expected_revision is not None and state.get("revision") != expected_revision:
        raise ValueError("composite survey state changed after it was displayed")
    if stage_id not in COMPOSITE_SURVEY_STAGES or status not in COMPOSITE_STAGE_STATUSES:
        raise ValueError("invalid composite survey stage update")
    updated = copy.deepcopy(state)
    invalid_stage = _first_invalid_completed_stage(root, updated) if root is not None else ""
    if invalid_stage and status != "completed":
        raise ValueError(
            f"composite survey must repair stale completed stage {invalid_stage} first"
        )
    if status == "completed":
        if root is None:
            raise ValueError("completed composite survey transitions require a workspace verifier")
        if invalid_stage:
            if stage_id != invalid_stage:
                raise ValueError(
                    f"composite survey must repair stale completed stage {invalid_stage} first"
                )
            updated = _reset_composite_from_stage(updated, invalid_stage)
        elif stage_id != str(updated.get("current_stage") or ""):
            raise ValueError("only the current composite survey stage may be completed")
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
    persisted_outputs = copy.deepcopy(outputs or [])
    if status == "completed":
        persisted_outputs = [
            build_composite_stage_binding(root, stage_id, refs=outputs or [])
        ]
    stage.update(
        {
            "status": status,
            "inputs": copy.deepcopy(inputs or []),
            "outputs": persisted_outputs,
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
    if root is not None:
        current_violations = composite_survey_current_violations(root, updated)
        if current_violations:
            raise ValueError(
                "invalid composite survey artifact binding: " + "; ".join(current_violations)
            )
    return updated


def _safe_component(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or Path(text).name != text or text in {".", ".."}:
        raise ValueError(f"composite survey {label} is not canonical")
    return text


def _trusted_artifact(
    root: Path,
    path: Path,
    *,
    role: str,
    artifact_kind: str,
    artifact_id: str,
    content: object,
) -> dict[str, str]:
    canonical = trusted_project_path(
        root,
        path,
        allowed_root=root / "kb",
        require="file",
    )
    return {
        "role": role,
        "path": canonical.relative_to(root.resolve()).as_posix(),
        "artifact_kind": artifact_kind,
        "artifact_id": artifact_id,
        "content_sha256": _exact_digest(content),
    }


def _search_candidate_snapshot(stage: dict[str, Any]) -> list[dict[str, Any]]:
    """Exclude only downstream materialization markers from a terminal search result."""
    snapshot: list[dict[str, Any]] = []
    for raw in stage.get("candidates", []):
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        item.pop("status", None)
        item.pop("record_id", None)
        snapshot.append(item)
    return snapshot


def literature_candidate_identity_digest(candidate: dict[str, Any]) -> str:
    """Bind provider-neutral staged identity without materialization bookkeeping."""
    return _exact_digest(
        {
            key: candidate.get(key)
            for key in ("candidate_id", "title", "url", "identities")
        }
    )


def _materialized_unit_snapshot(
    record: dict[str, Any],
    *,
    selection_receipt: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "kind": record.get("kind"),
        "status": record.get("status"),
        "source": record.get("source"),
        "selection_receipt": selection_receipt,
    }


def _normalized_unit_refs(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("composite survey unit refs must be a non-empty list")
    units: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"kind", "id"}:
            raise ValueError("composite survey unit refs are not canonical")
        units.append(
            {
                "kind": _safe_component(item.get("kind"), label="unit kind"),
                "id": _safe_component(item.get("id"), label="unit id"),
            }
        )
    ordered = sorted(units, key=lambda item: (item["kind"], item["id"]))
    if ordered != units or len({(item["kind"], item["id"]) for item in units}) != len(units):
        raise ValueError("composite survey unit refs must be unique and sorted")
    return units


def _record_for_ref(root: Path, unit: dict[str, str]) -> tuple[dict[str, Any], Path]:
    try:
        record, path = locate_record(root, unit["id"], kind=unit["kind"], fuzzy=False)
        path = trusted_project_path(root, path, allowed_root=root / "kb" / "units", require="file")
    except (OSError, SystemExit, ValueError) as exc:
        raise ValueError(f"canonical unit is missing or unsafe: {unit['kind']}/{unit['id']}") from exc
    if str(record.get("id") or "") != unit["id"] or str(record.get("kind") or "") != unit["kind"]:
        raise ValueError(f"canonical unit identity changed: {unit['kind']}/{unit['id']}")
    return record, path


def _search_stage(root: Path, stage_id: object) -> tuple[dict[str, Any], Path]:
    safe_id = _safe_component(stage_id, label="literature stage id")
    from .paths import search_stage_path
    from .sources import _stage_search_results_unlocked, load_search_stage

    try:
        payload = load_search_stage(root, safe_id)
        path = trusted_project_path(
            root,
            search_stage_path(root, safe_id),
            allowed_root=root / "kb" / "synthesis" / "source-search",
            require="file",
        )
        _stage_search_results_unlocked(
            root,
            path=path,
            current_stage_id=safe_id,
            kind=str(payload.get("source_kind") or ""),
            query=str(payload.get("query") or ""),
            candidates=[],
            note=str(payload.get("note") or ""),
            search_state={},
            validate_only=True,
        )
    except (OSError, SystemExit, ValueError) as exc:
        raise ValueError("literature search stage is missing or unsafe") from exc
    if (
        payload.get("entry_skill") != "literature-search"
        or payload.get("kind") != "source-search-stage"
        or payload.get("id") != safe_id
    ):
        raise ValueError("literature search stage identity is invalid")
    return payload, path


def _selected_candidates(stage: dict[str, Any], candidate_ids: list[str]) -> list[dict[str, Any]]:
    candidates = {
        str(item.get("candidate_id") or ""): item
        for item in stage.get("candidates", [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "")
    }
    selected: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        candidate = candidates.get(candidate_id)
        if not candidate:
            raise ValueError(f"selected candidate is missing from literature stage: {candidate_id}")
        selected.append(
            {
                "candidate_id": candidate_id,
                "identity_digest": literature_candidate_identity_digest(candidate),
            }
        )
    return selected


def _survey_for_ref(root: Path, ref: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    slug = _safe_component(ref.get("slug"), label="survey slug")
    mode = str(ref.get("mode") or "survey").strip()
    try:
        path = trusted_project_path(
            root,
            survey_artifact_path(root, slug, mode),
            allowed_root=root / "kb" / "synthesis",
            require="file",
        )
    except ValueError as exc:
        raise ValueError("survey judgement is missing or unsafe") from exc
    payload = load_yaml(path, default={})
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "survey_judgement"
        or payload.get("owner") != "literature-synthesizer"
        or str(payload.get("slug") or "") != slug
        or str(payload.get("mode") or "") != mode
    ):
        raise ValueError("survey judgement identity is invalid")
    return payload, path


def _normalize_stage_refs(stage_id: str, refs: object) -> dict[str, Any]:
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        raise ValueError("completed composite survey stage requires exactly one canonical ref")
    ref = refs[0]
    if stage_id == "search":
        if set(ref) != {"kind", "stage_id"} or ref.get("kind") != "literature-search-stage":
            raise ValueError("search completion ref is invalid")
        return {"kind": "literature-search-stage", "stage_id": _safe_component(ref.get("stage_id"), label="literature stage id")}
    if stage_id == "selection":
        if set(ref) != {"kind", "stage_id", "candidate_ids", "user_authorization", "authorization_source"} or ref.get("kind") != "literature-search-selection":
            raise ValueError("selection completion ref is invalid")
        raw_ids = ref.get("candidate_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError("selection completion requires candidate ids")
        ids = [_safe_component(item, label="candidate id") for item in raw_ids]
        if ids != sorted(set(ids)):
            raise ValueError("selection candidate ids must be unique and sorted")
        authorization = str(ref.get("user_authorization") or "").strip()
        if not authorization or len(authorization.encode("utf-8")) > 4096:
            raise ValueError("selection completion requires bounded current-user authorization")
        if ref.get("authorization_source") != "user_message":
            raise ValueError("selection completion authorization must come from user_message")
        return {
            "kind": "literature-search-selection",
            "stage_id": _safe_component(ref.get("stage_id"), label="literature stage id"),
            "candidate_ids": ids,
            "user_authorization": authorization,
            "authorization_source": "user_message",
        }
    if stage_id in {"source_intake", "unit_analysis"}:
        expected_kind = "materialized-units" if stage_id == "source_intake" else "confirmed-units"
        if set(ref) != {"kind", "stage_id", "units"} or ref.get("kind") != expected_kind:
            raise ValueError(f"{stage_id} completion ref is invalid")
        return {"kind": expected_kind, "stage_id": _safe_component(ref.get("stage_id"), label="literature stage id"), "units": _normalized_unit_refs(ref.get("units"))}
    if stage_id in {"synthesis", "review_confirmation"}:
        expected_kind = "verified-survey" if stage_id == "synthesis" else "confirmed-survey"
        if set(ref) != {"kind", "slug", "mode"} or ref.get("kind") != expected_kind:
            raise ValueError(f"{stage_id} completion ref is invalid")
        mode = str(ref.get("mode") or "").strip()
        if mode not in {"survey", "review", "taxonomy"}:
            raise ValueError("survey mode is invalid")
        return {"kind": expected_kind, "slug": _safe_component(ref.get("slug"), label="survey slug"), "mode": mode}
    if stage_id == "report_consumption":
        common = {
            "survey_slug": _safe_component(ref.get("survey_slug"), label="survey slug"),
            "survey_mode": str(ref.get("survey_mode") or "").strip(),
        }
        if ref.get("kind") == "program-reporting-events":
            if set(ref) != {"kind", "program_ids", "survey_slug", "survey_mode"}:
                raise ValueError("report consumption ref is invalid")
            raw_programs = ref.get("program_ids")
            if not isinstance(raw_programs, list) or not raw_programs:
                raise ValueError("report consumption requires linked program ids")
            program_ids = [
                _safe_component(item, label="program id") for item in raw_programs
            ]
            if program_ids != sorted(set(program_ids)):
                raise ValueError("report consumption program ids must be unique and sorted")
            return {"kind": "program-reporting-events", "program_ids": program_ids, **common}
        if ref.get("kind") == "not-applicable-report-consumption":
            if set(ref) != {"kind", "reason", "survey_slug", "survey_mode"} or ref.get("reason") != "no_linked_programs":
                raise ValueError("not-applicable report consumption ref is invalid")
            return {"kind": "not-applicable-report-consumption", "reason": "no_linked_programs", **common}
        raise ValueError("report consumption ref is invalid")
    raise ValueError("unsupported composite survey stage")


def build_composite_stage_binding(root: Path, stage_id: str, *, refs: object) -> dict[str, Any]:
    """Build one closed binding from canonical bytes; no research meaning is inferred."""
    if stage_id not in COMPOSITE_SURVEY_STAGES:
        raise ValueError("unsupported composite survey stage")
    root = root.resolve()
    ref = _normalize_stage_refs(stage_id, refs)
    artifacts: list[dict[str, str]] = []
    facts: dict[str, Any]
    if stage_id == "search":
        stage, path = _search_stage(root, ref["stage_id"])
        stop = stage.get("stop") if isinstance(stage.get("stop"), dict) else {}
        reason = str(stop.get("reason") or "")
        if reason not in TERMINAL_SEARCH_REASONS or not str(stop.get("rationale") or "").strip():
            raise ValueError("literature search stage is not terminal")
        terminal_snapshot = {
            "id": stage.get("id"),
            "kind": stage.get("kind"),
            "entry_skill": stage.get("entry_skill"),
            "source_kind": stage.get("source_kind"),
            "query": stage.get("query"),
            "mode": stage.get("mode"),
            "scope": stage.get("scope"),
            "queries": stage.get("queries"),
            "candidates": _search_candidate_snapshot(stage),
            "coverage": stage.get("coverage"),
            "frontier": stage.get("frontier"),
            "stop": stage.get("stop"),
            "partial": stage.get("partial"),
        }
        artifacts.append(_trusted_artifact(root, path, role="literature-search-stage", artifact_kind="source-search-stage", artifact_id=ref["stage_id"], content=terminal_snapshot))
        facts = {"terminal_stop_reason": reason, "candidate_set_digest": _exact_digest(_search_candidate_snapshot(stage))}
    elif stage_id == "selection":
        stage, path = _search_stage(root, ref["stage_id"])
        selected = _selected_candidates(stage, ref["candidate_ids"])
        artifacts.append(_trusted_artifact(root, path, role="literature-search-stage", artifact_kind="source-search-stage", artifact_id=ref["stage_id"], content=_search_candidate_snapshot(stage)))
        facts = {
            "candidate_set_digest": _exact_digest(_search_candidate_snapshot(stage)),
            "selected_candidates": selected,
            "authorization_digest": _exact_digest(
                {
                    "user_authorization": ref["user_authorization"],
                    "authorization_source": ref["authorization_source"],
                }
            ),
        }
    elif stage_id == "source_intake":
        stage, stage_path = _search_stage(root, ref["stage_id"])
        artifacts.append(_trusted_artifact(root, stage_path, role="literature-search-stage", artifact_kind="source-search-stage", artifact_id=ref["stage_id"], content=[{"candidate_id": item.get("candidate_id"), "status": item.get("status"), "record_id": item.get("record_id")} for item in stage.get("candidates", []) if isinstance(item, dict) and str(item.get("record_id") or "") in {unit["id"] for unit in ref["units"]}]))
        facts_units: list[dict[str, str]] = []
        for unit in ref["units"]:
            record, record_path = _record_for_ref(root, unit)
            source_search = record.get("payload", {}).get("source_search", {})
            source_search = source_search if isinstance(source_search, dict) else {}
            candidate_ids = [str(item) for item in source_search.get("candidate_ids", [])]
            matching = [item for item in stage.get("candidates", []) if isinstance(item, dict) and str(item.get("record_id") or "") == unit["id"] and str(item.get("candidate_id") or "") in candidate_ids and str(item.get("status") or "") in {"materialized", "duplicate"}]
            if ref["stage_id"] not in source_search.get("stage_ids", []) or not matching or str(record.get("status") or "") != "active" or not isinstance(record.get("source"), dict) or not record.get("source"):
                raise ValueError(f"canonical unit is not a current materialization: {unit['kind']}/{unit['id']}")
            receipts = [
                item
                for item in source_search.get("selections", [])
                if isinstance(item, dict)
                and item.get("stage_id") == ref["stage_id"]
                and item.get("candidate_id") == str(matching[0].get("candidate_id") or "")
            ]
            if len(receipts) != 1:
                raise ValueError("materialized unit lacks an exact source-intake selection receipt")
            receipt = receipts[0]
            candidate = matching[0]
            if receipt.get("candidate_identity_digest") != literature_candidate_identity_digest(candidate):
                raise ValueError("materialized unit selection identity does not match the staged candidate")
            authorization = {
                "user_authorization": receipt.get("user_authorization"),
                "authorization_source": receipt.get("authorization_source"),
            }
            if (
                str(authorization.get("authorization_source") or "") != "user_message"
                or not str(authorization.get("user_authorization") or "").strip()
            ):
                raise ValueError("materialized unit lacks current-user selection authorization")
            artifacts.append(_trusted_artifact(root, record_path, role="materialized-unit", artifact_kind=unit["kind"], artifact_id=unit["id"], content=_materialized_unit_snapshot(record, selection_receipt=receipt)))
            facts_units.append(
                {
                    **unit,
                    "candidate_id": str(matching[0].get("candidate_id") or ""),
                    "authorization_digest": _exact_digest(authorization),
                }
            )
        facts = {"units": facts_units}
    elif stage_id == "unit_analysis":
        _stage, stage_path = _search_stage(root, ref["stage_id"])
        artifacts.append(_trusted_artifact(root, stage_path, role="literature-search-stage", artifact_kind="source-search-stage", artifact_id=ref["stage_id"], content={"id": ref["stage_id"], "source_kind": _stage.get("source_kind")}))
        bindings: list[dict[str, Any]] = []
        for unit in ref["units"]:
            record, record_path = _record_for_ref(root, unit)
            binding = build_unit_binding(root, record)
            artifacts.append(_trusted_artifact(root, record_path, role="confirmed-unit", artifact_kind=unit["kind"], artifact_id=unit["id"], content=binding))
            bindings.append(binding)
        facts = {"unit_bindings": bindings}
    elif stage_id in {"synthesis", "review_confirmation"}:
        survey, path = _survey_for_ref(root, ref)
        violations = survey_lifecycle_violations(survey, root)
        if violations:
            raise ValueError("survey judgement is stale: " + "; ".join(violations))
        if stage_id == "synthesis":
            from .evidence import verification_receipt_violations
            violations = verification_receipt_violations(survey, path.parent, source_roots=survey_source_roots(root, survey, path))
            if violations:
                raise ValueError("survey judgement is not currently verified: " + "; ".join(violations))
            verification = survey.get("payload", {}).get("verification", {})
            facts = {"survey_content_digest": str(survey.get("survey_content_digest") or ""), "verification_receipt_digest": _canonical_digest(verification), "unit_ids": sorted(str(item) for item in survey.get("consumer_binding", {}).get("unit_ids", []))}
            role = "verified-survey"
        else:
            from .judgements import judgement_confirmation_is_current
            if not judgement_confirmation_is_current(root, survey, path):
                raise ValueError("survey judgement confirmation is missing or stale")
            facts = {"survey_content_digest": str(survey.get("survey_content_digest") or ""), "confirmation_receipt_digest": _canonical_digest(survey.get("confirmation", {}))}
            role = "confirmed-survey"
        survey_binding_content = {
            "survey_content_digest": survey.get("survey_content_digest"),
            "consumer_binding": survey.get("consumer_binding"),
            "verification": survey.get("payload", {}).get("verification", {}),
        }
        if stage_id == "review_confirmation":
            survey_binding_content["confirmation"] = survey.get("confirmation", {})
        artifacts.append(_trusted_artifact(root, path, role=role, artifact_kind="survey_judgement", artifact_id=str(survey.get("id") or ""), content=survey_binding_content))
    else:
        from .common import program_reporting_events_path
        from .judgements import confirmation_binding, judgement_confirmation_is_current

        if ref["survey_mode"] not in {"survey", "review", "taxonomy"}:
            raise ValueError("report consumption survey mode is invalid")
        survey_ref = {"slug": ref["survey_slug"], "mode": ref["survey_mode"]}
        survey, survey_path = _survey_for_ref(root, survey_ref)
        if not judgement_confirmation_is_current(root, survey, survey_path):
            raise ValueError("report consumption references a stale survey confirmation")
        expected_confirmation = confirmation_binding(survey, owner="literature-synthesizer", path=survey_path.relative_to(root).as_posix())
        survey_program_ids = survey.get("program_ids")
        survey_program_ids = survey_program_ids if isinstance(survey_program_ids, list) else []
        if ref["kind"] == "not-applicable-report-consumption":
            if survey_program_ids:
                raise ValueError("report consumption is applicable to linked survey programs")
            artifacts.append(
                _trusted_artifact(
                    root,
                    survey_path,
                    role="confirmed-global-survey",
                    artifact_kind="survey_judgement",
                    artifact_id=str(survey.get("id") or ""),
                    content={
                        "survey_content_digest": survey.get("survey_content_digest"),
                        "confirmation": survey.get("confirmation"),
                    },
                )
            )
            facts = {
                "outcome": "not_applicable",
                "reason": "no_linked_programs",
                "confirmation_binding_digest": _exact_digest(expected_confirmation),
            }
        else:
            if ref["program_ids"] != survey_program_ids:
                raise ValueError("report consumption must cover every linked survey program")
            event_facts: list[dict[str, str]] = []
            for program_id in ref["program_ids"]:
                events_path = program_reporting_events_path(root, program_id)
                events_path = trusted_project_path(root, events_path, allowed_root=root / "kb" / "programs", require="file")
                event_doc = load_yaml(events_path, default={})
                events = [item for item in event_doc.get("items", []) if isinstance(item, dict)] if isinstance(event_doc, dict) else []
                matches = [
                    item
                    for item in events
                    if item.get("event_type") == "survey-confirmed"
                    and item.get("confirmation_binding") == expected_confirmation
                ]
                if len(matches) != 1:
                    raise ValueError("program reporting event does not consume the current survey confirmation")
                artifacts.append(_trusted_artifact(root, events_path, role="program-reporting-events", artifact_kind="program-reporting-events", artifact_id=program_id, content=matches[0]))
                event_facts.append({"program_id": program_id, "event_digest": _exact_digest(matches[0])})
            facts = {
                "events": event_facts,
                "confirmation_binding_digest": _exact_digest(expected_confirmation),
            }

    binding: dict[str, Any] = {
        "schema_version": 1,
        "kind": COMPOSITE_BINDING_KIND,
        "stage_id": stage_id,
        "refs": [ref],
        "artifacts": artifacts,
        "facts": facts,
        "binding_digest": "",
    }
    binding["binding_digest"] = _exact_digest({key: value for key, value in binding.items() if key != "binding_digest"})
    return binding


def _completed_stage_binding(stage: object) -> dict[str, Any] | None:
    if not isinstance(stage, dict) or stage.get("status") != "completed":
        return None
    outputs = stage.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1 or not isinstance(outputs[0], dict):
        return None
    binding = outputs[0]
    if set(binding) != COMPOSITE_BINDING_FIELDS or binding.get("kind") != COMPOSITE_BINDING_KIND or binding.get("schema_version") != 1:
        return None
    artifacts = binding.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or any(not isinstance(item, dict) or set(item) != COMPOSITE_ARTIFACT_FIELDS for item in artifacts):
        return None
    return binding


def _completed_binding_violations(root: Path, stage: dict[str, Any]) -> list[str]:
    stage_id = str(stage.get("id") or "")
    binding = _completed_stage_binding(stage)
    if binding is None:
        return [f"completed stage {stage_id} lacks a closed artifact binding"]
    if binding.get("stage_id") != stage_id:
        return [f"completed stage {stage_id} binding identity is invalid"]
    expected_digest = _exact_digest({key: value for key, value in binding.items() if key != "binding_digest"})
    if binding.get("binding_digest") != expected_digest:
        return [f"completed stage {stage_id} binding digest is stale"]
    try:
        current = build_composite_stage_binding(root, stage_id, refs=binding.get("refs"))
    except (OSError, SystemExit, ValueError) as exc:
        return [f"completed stage {stage_id} is not current: {exc}"]
    if current != binding:
        return [f"completed stage {stage_id} canonical artifact binding changed"]
    return []


def _chain_violation_items(state: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the earliest downstream stage made invalid by each broken edge."""
    bindings = {
        str(stage.get("id") or ""): _completed_stage_binding(stage)
        for stage in state.get("stages", [])
        if isinstance(stage, dict) and stage.get("status") == "completed"
    }
    violations: list[tuple[str, str]] = []
    search = bindings.get("search")
    selection = bindings.get("selection")
    intake = bindings.get("source_intake")
    analysis = bindings.get("unit_analysis")
    synthesis = bindings.get("synthesis")
    review = bindings.get("review_confirmation")
    report = bindings.get("report_consumption")
    if search and selection and search["refs"][0]["stage_id"] != selection["refs"][0]["stage_id"]:
        violations.append(
            ("selection", "selection does not bind the completed literature search stage")
        )
    if selection and intake:
        selected_ids = [
            item.get("candidate_id")
            for item in selection["facts"].get("selected_candidates", [])
        ]
        intake_items = intake["facts"].get("units", [])
        intake_ids = sorted(item.get("candidate_id") for item in intake_items)
        authorization_digest = selection["facts"].get("authorization_digest")
        if (
            selection["refs"][0]["stage_id"] != intake["refs"][0]["stage_id"]
            or selected_ids != intake_ids
            or any(item.get("authorization_digest") != authorization_digest for item in intake_items)
        ):
            violations.append(
                (
                    "source_intake",
                    "source intake does not bind the selected candidates and authorization",
                )
            )
    if intake and analysis:
        intake_units = [{"kind": item.get("kind"), "id": item.get("id")} for item in intake["facts"].get("units", [])]
        analysis_units = [{"kind": item.get("kind"), "id": item.get("id")} for item in analysis["refs"][0].get("units", [])]
        if intake_units != analysis_units:
            violations.append(
                ("unit_analysis", "unit analysis does not bind the materialized units")
            )
    if analysis and synthesis:
        analysis_ids = sorted(item.get("id") for item in analysis["refs"][0].get("units", []))
        if analysis_ids != synthesis["facts"].get("unit_ids"):
            violations.append(
                ("synthesis", "synthesis does not bind the confirmed analysis units")
            )
    if synthesis and review and (synthesis["refs"][0]["slug"], synthesis["refs"][0]["mode"]) != (review["refs"][0]["slug"], review["refs"][0]["mode"]):
        violations.append(
            (
                "review_confirmation",
                "review confirmation does not bind the verified survey",
            )
        )
    if review and report and (review["refs"][0]["slug"], review["refs"][0]["mode"]) != (report["refs"][0]["survey_slug"], report["refs"][0]["survey_mode"]):
        violations.append(
            (
                "report_consumption",
                "report consumption does not bind the confirmed survey",
            )
        )
    return violations


def _chain_violations(state: dict[str, Any]) -> list[str]:
    return [message for _stage_id, message in _chain_violation_items(state)]


def composite_survey_current_violations(root: Path, state: object) -> list[str]:
    """Revalidate every completed-prefix artifact before resume/status/next trust it."""
    structural = composite_survey_state_violations(state)
    if structural:
        return structural
    assert isinstance(state, dict)
    violations: list[str] = []
    for stage in state.get("stages", []):
        if not isinstance(stage, dict) or stage.get("status") != "completed":
            break
        violations.extend(_completed_binding_violations(root.resolve(), stage))
    violations.extend(_chain_violations(state))
    return violations


def _first_invalid_completed_stage(root: Path, state: dict[str, Any]) -> str:
    for stage in state.get("stages", []):
        if not isinstance(stage, dict) or stage.get("status") != "completed":
            break
        if _completed_binding_violations(root.resolve(), stage):
            return str(stage.get("id") or "")
    chain_violations = _chain_violation_items(state)
    if chain_violations:
        return chain_violations[0][0]
    return ""


def _reset_composite_from_stage(state: dict[str, Any], stage_id: str) -> dict[str, Any]:
    reset = copy.deepcopy(state)
    index = COMPOSITE_SURVEY_STAGES.index(stage_id)
    for current, stage in enumerate(reset["stages"]):
        if current < index:
            continue
        stage["status"] = "in_progress" if current == index else "pending"
        stage["inputs"] = []
        stage["outputs"] = []
        stage["blocker"] = {}
        stage["resume_action"] = ""
    reset["current_stage"] = stage_id
    reset["status"] = "in_progress"
    return reset


def composite_survey_repair_projection(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Return a no-write blocked projection at the earliest stale completed stage."""
    stage_id = _first_invalid_completed_stage(root, state)
    if not stage_id:
        return copy.deepcopy(state)
    projected = _reset_composite_from_stage(state, stage_id)
    stage = projected["stages"][COMPOSITE_SURVEY_STAGES.index(stage_id)]
    stage["status"] = "blocked"
    stage["blocker"] = {"code": "stale_composite_stage_binding"}
    stage["resume_action"] = "rebuild_current_stage_binding"
    projected["status"] = "blocked"
    return projected


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
    "build_composite_stage_binding",
    "build_unit_binding",
    "composite_survey_current_violations",
    "composite_survey_repair_projection",
    "composite_survey_state_violations",
    "composite_survey_request_digest",
    "composite_survey_state_path",
    "evidence_gap_handoff",
    "literature_candidate_identity_digest",
    "new_composite_survey_state",
    "pending_composite_survey_states",
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

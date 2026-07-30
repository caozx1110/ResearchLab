"""Mechanical research-monitor subscriptions and frozen run receipts.

This module deliberately has no network client and no research-content
classifier.  It stores user/Agent supplied schedules and assessments, validates
their references, and provides read-only due facts to later consumers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import file_sha256, load_list_document, program_reporting_events_path, utc_now_iso
from .journal import mutation_transaction
from .paths import kb_root, search_stage_path, source_search_root, synthesis_root, units_root
from .preference_selection import (
    canonical_digest,
    operation_contract,
    regular_file_binding,
    regular_tree_binding,
    resolve_task_preferences,
    selection_binding,
)
from .records import (
    CanonicalRecordSnapshot,
    CanonicalUnitSnapshot,
    iter_canonical_record_snapshots,
    normalize_record_snapshot,
    snapshot_canonical_unit_artifacts,
)
from .yaml_io import load_yaml, write_yaml_if_changed, yaml_duplicate_key_issues


SCHEMA_VERSION = 1
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SUBSCRIPTION_KINDS = {"literature", "survey-freshness", "unit-recheck"}
SUBSCRIPTION_STATUSES = {"active", "paused", "completed"}
RUN_STATES = {
    "planned",
    "running",
    "blocked",
    "failed_retryable",
    "completed",
    "cancelled",
}
TERMINAL_RUN_STATES = {"completed", "cancelled"}
RUN_TRANSITIONS = {
    "planned": {"running", "cancelled"},
    "running": {"blocked", "failed_retryable", "completed", "cancelled"},
    "blocked": {"running", "cancelled"},
    "failed_retryable": {"running", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
STOP_REASONS_BY_STATE = {
    "planned": {"in_progress"},
    "running": {"in_progress"},
    "blocked": {"blocked", "blocked_no_search_tool"},
    "failed_retryable": {"failed_retryable"},
    "completed": {"completed", "budget_exhausted", "user_stop"},
    "cancelled": {"cancelled", "user_stop"},
}
REVIEW_OUTCOMES = {
    "new",
    "duplicate",
    "contradiction_candidate",
    "worth_reviewing",
    "no_material_change",
}
OUTCOME_DISPOSITION_STATES = {
    "unresolved",
    "acknowledged",
    "materialized",
    "sent_to_review",
    "dismissed",
}
OUTCOME_FINAL_DISPOSITIONS = OUTCOME_DISPOSITION_STATES - {"unresolved"}
OUTCOME_DISPOSITION_FIELDS = {
    "state",
    "actor",
    "at",
    "reason",
    "target_ref",
    "user_authorization",
    "authorization_source",
}
OUTCOME_DISPOSITIONS_BY_CLASSIFICATION = {
    "new": {"acknowledged", "materialized", "dismissed"},
    "worth_reviewing": {"acknowledged", "materialized", "dismissed"},
    "contradiction_candidate": {"acknowledged", "sent_to_review", "dismissed"},
    "duplicate": {"acknowledged", "dismissed"},
    "no_material_change": {"acknowledged", "dismissed"},
}
REFERENCE_KINDS = {"literature-candidate", "survey-output", "artifact"}
MAX_TEXT = 4000
MAX_COLLECTION = 500
PREFERENCE_SKILL = "research-monitor"
PREFERENCE_OPERATION = "create-subscription"
PREFERENCE_BINDING_FIELDS = {
    "selection_id",
    "selection_digest",
    "task_context_digest",
    "skill",
    "operation",
}
SUBSCRIPTION_FIELDS = {
    "schema_version",
    "id",
    "kind",
    "status",
    "title",
    "program_ids",
    "target",
    "scope_snapshot",
    "scope_digest",
    "preference_binding",
    "budget",
    "cadence",
    "next_due_at",
    "active_run_id",
    "last_completed_run_id",
    "created_at",
    "updated_at",
    "revision",
    "history",
}
RUN_FIELDS = {
    "schema_version",
    "id",
    "subscription_id",
    "scheduled_for",
    "state",
    "frozen_subscription",
    "outputs",
    "review_outcomes",
    "stop",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "revision",
    "history",
    "content_digest",
}
FROZEN_SUBSCRIPTION_FIELDS = {
    "subscription_revision",
    "subscription_content_digest",
    "kind",
    "target",
    "scope_snapshot",
    "scope_digest",
    "budget",
    "cadence",
    "preference_binding",
}
LEGACY_SUBSCRIPTION_FIELDS = SUBSCRIPTION_FIELDS - {"preference_binding"}
LEGACY_FROZEN_SUBSCRIPTION_FIELDS = FROZEN_SUBSCRIPTION_FIELDS - {
    "subscription_content_digest",
    "preference_binding",
}
HISTORY_FIELDS = {"at", "action", "revision", "status"}


def monitoring_root(project_root: Path) -> Path:
    return kb_root(project_root) / "monitoring"


def subscriptions_root(project_root: Path) -> Path:
    return monitoring_root(project_root) / "subscriptions"


def runs_root(project_root: Path) -> Path:
    return monitoring_root(project_root) / "runs"


def _program_reporting_paths(project_root: Path, program_ids: Iterable[str]) -> list[Path]:
    programs_root = kb_root(project_root) / "programs"
    paths: list[Path] = []
    for raw_program_id in program_ids:
        program_id = _safe_id(raw_program_id, field="program id")
        program = programs_root / program_id
        if programs_root.is_symlink() or program.is_symlink() or not program.is_dir():
            raise SystemExit(f"Research monitor program does not exist: {program_id}")
        workflow = program / "workflow"
        if workflow.is_symlink() or (workflow.exists() and not workflow.is_dir()):
            raise SystemExit(f"Research monitor program workflow is unsafe: {program_id}")
        paths.append(program_reporting_events_path(project_root, program_id))
    return paths


def _append_completion_events_unlocked(
    project_root: Path,
    *,
    subscription: dict[str, Any],
    run: dict[str, Any],
    completed_at: str,
) -> None:
    outcome_count = len([item for item in run.get("review_outcomes", []) if isinstance(item, dict)])
    for program_id in subscription.get("program_ids", []):
        path = program_reporting_events_path(project_root, str(program_id))
        payload = load_list_document(
            path,
            f"{program_id}-reporting-events",
            "research-monitor",
        )
        payload["program_id"] = str(program_id)
        payload["generated_by"] = "research-monitor"
        payload["generated_at"] = completed_at
        items = [item for item in payload.get("items", []) if isinstance(item, dict)]
        if not any(
            item.get("event_type") == "monitor-run-completed"
            and item.get("monitor_run_id") == run.get("id")
            for item in items
        ):
            items.append(
                {
                    "timestamp": completed_at,
                    "source_skill": "research-monitor",
                    "event_type": "monitor-run-completed",
                    "title": f"Monitoring run completed: {subscription.get('title') or subscription.get('id')}",
                    "summary": (
                        f"The bounded monitoring run completed and produced {outcome_count} review outcome(s); "
                        "each outcome remains subject to its separate disposition or review gate."
                    ),
                    "stage": "monitoring",
                    "tags": ["monitor", "completed"],
                    "artifacts": [run_path(project_root, str(run.get("id") or "")).relative_to(project_root).as_posix()],
                    "idea_ids": [],
                    "paper_ids": [],
                    "repo_ids": [],
                    "epistemic_type": "operational",
                    "information_types": ["fact"],
                    "monitor_subscription_id": str(subscription.get("id") or ""),
                    "monitor_run_id": str(run.get("id") or ""),
                    "monitor_run_completion_revision": int(run.get("revision") or 0),
                }
            )
        payload["items"] = items
        write_yaml_if_changed(path, payload)


def _safe_id(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if SAFE_ID_RE.fullmatch(text) is None or text in {".", ".."}:
        raise SystemExit(f"Research monitor {field} must be an ASCII-safe identifier.")
    return text


def subscription_path(project_root: Path, subscription_id: str) -> Path:
    return subscriptions_root(project_root) / f"{_safe_id(subscription_id, field='subscription id')}.yaml"


def run_path(project_root: Path, run_id: str) -> Path:
    return runs_root(project_root) / f"{_safe_id(run_id, field='run id')}.yaml"


def _bounded_text(value: Any, *, field: str, required: bool = False, limit: int = MAX_TEXT) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = " ".join(value.split())
    else:
        raise SystemExit(f"Research monitor {field} must be text.")
    if required and not text:
        raise SystemExit(f"Research monitor {field} is required.")
    if len(text) > limit:
        raise SystemExit(f"Research monitor {field} is too long.")
    return text


def _safe_string_list(value: Any, *, field: str) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_COLLECTION:
        raise SystemExit(f"Research monitor {field} must be a bounded list.")
    result: list[str] = []
    for item in value:
        text = _bounded_text(item, field=field, required=True, limit=256)
        if text not in result:
            result.append(text)
    return result


def _parse_aware_datetime(value: Any, *, field: str) -> datetime:
    text = _bounded_text(value, field=field, required=True, limit=80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"Research monitor {field} must be an ISO-8601 timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit(f"Research monitor {field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _now(value: datetime | str | None) -> datetime:
    if value is None:
        return _parse_aware_datetime(utc_now_iso(), field="current time")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SystemExit("Research monitor current time must include a timezone.")
        return value.astimezone(timezone.utc)
    return _parse_aware_datetime(value, field="current time")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise SystemExit("Research monitor frozen values must contain only JSON-compatible data.")


def value_digest(value: Any) -> str:
    encoded = json.dumps(
        _canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sanitize_preference_binding(value: Any) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or set(value) != PREFERENCE_BINDING_FIELDS:
        raise SystemExit("Research monitor preference binding is invalid.")
    result = {key: str(value.get(key) or "").strip() for key in PREFERENCE_BINDING_FIELDS}
    if not result["selection_id"].startswith("prefsel-"):
        raise SystemExit("Research monitor preference selection id is invalid.")
    for field in ("selection_digest", "task_context_digest"):
        if SHA256_RE.fullmatch(result[field]) is None:
            raise SystemExit("Research monitor preference binding digest is invalid.")
    if result["skill"] != PREFERENCE_SKILL or result["operation"] != PREFERENCE_OPERATION:
        raise SystemExit("Research monitor preference binding belongs to another consumer.")
    return result


def _run_content_digest(document: dict[str, Any]) -> str:
    return value_digest({key: value for key, value in document.items() if key != "content_digest"})


def monitor_task_binding(document: dict[str, Any]) -> dict[str, str]:
    frozen = document.get("frozen_subscription")
    if not isinstance(frozen, dict):
        raise SystemExit("Research monitor run lacks a frozen subscription.")
    run_id = _safe_id(document.get("id"), field="run id")
    task = {
        "run_id": run_id,
        "subscription_id": _safe_id(document.get("subscription_id"), field="subscription id"),
        "scheduled_for": _utc_iso(
            _parse_aware_datetime(document.get("scheduled_for"), field="scheduled_for")
        ),
        "kind": str(frozen.get("kind") or ""),
        "target": frozen.get("target"),
        "scope_digest": str(frozen.get("scope_digest") or ""),
        "budget": frozen.get("budget") or {},
    }
    # Preserve the exact legacy v1 task digest for receipts frozen before R11.
    # New receipts bind the current subscription bytes and value-free selection.
    if "subscription_content_digest" in frozen:
        task["subscription_content_digest"] = str(frozen["subscription_content_digest"])
        task["preference_binding"] = frozen.get("preference_binding") or {}
    return {"run_id": run_id, "task_digest": value_digest(task)}


def _safe_json_value(value: Any, *, field: str, depth: int = 0) -> Any:
    if depth > 8:
        raise SystemExit(f"Research monitor {field} is too deeply nested.")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SystemExit(f"Research monitor {field} contains a non-finite number.")
        return value
    if isinstance(value, str):
        return _bounded_text(value, field=field, limit=MAX_TEXT)
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION:
            raise SystemExit(f"Research monitor {field} is too large.")
        return [_safe_json_value(item, field=field, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION:
            raise SystemExit(f"Research monitor {field} is too large.")
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = _bounded_text(key, field=f"{field} key", required=True, limit=128)
            if "provider" in safe_key.casefold():
                raise SystemExit(f"Research monitor {field} cannot persist provider fields.")
            if safe_key in result:
                raise SystemExit(f"Research monitor {field} contains a duplicate key.")
            result[safe_key] = _safe_json_value(item, field=field, depth=depth + 1)
        return result
    raise SystemExit(f"Research monitor {field} contains an unsupported value.")


def _assert_safe_business_path(project_root: Path, path: Path, *, allowed_root: Path) -> None:
    project = project_root.resolve()
    candidate = path if path.is_absolute() else project / path
    try:
        relative = candidate.relative_to(project)
    except ValueError as exc:
        raise SystemExit("Research monitor path escapes the project root.") from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise SystemExit("Research monitor path contains an unsafe component.")
    cursor = project
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SystemExit("Research monitor path contains a symlink component.")
        if cursor.exists() and cursor != candidate and not cursor.is_dir():
            raise SystemExit("Research monitor path has a non-directory ancestor.")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise SystemExit("Research monitor path escapes its allowed root.") from exc
    if candidate.exists() and not candidate.is_file():
        raise SystemExit("Research monitor document must be a regular file.")


def _load_document(path: Path, *, expected_id: str, allowed_root: Path, project_root: Path) -> dict[str, Any]:
    _assert_safe_business_path(project_root, path, allowed_root=allowed_root)
    if not path.is_file():
        raise SystemExit(f"Research monitor document does not exist: {expected_id}")
    if yaml_duplicate_key_issues(path):
        raise SystemExit(f"Research monitor document has duplicate YAML keys: {expected_id}")
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict) or str(payload.get("id") or "") != expected_id:
        raise SystemExit(f"Research monitor document identity is invalid: {expected_id}")
    return payload


def load_subscription(project_root: Path, subscription_id: str) -> dict[str, Any]:
    safe_id = _safe_id(subscription_id, field="subscription id")
    document = _load_document(
        subscription_path(project_root, safe_id),
        expected_id=safe_id,
        allowed_root=subscriptions_root(project_root),
        project_root=project_root,
    )
    _validate_subscription_document(document)
    return document


def load_run(project_root: Path, run_id: str) -> dict[str, Any]:
    safe_id = _safe_id(run_id, field="run id")
    document = _load_document(
        run_path(project_root, safe_id),
        expected_id=safe_id,
        allowed_root=runs_root(project_root),
        project_root=project_root,
    )
    _validate_run_document(project_root, document)
    return document


def _expected_revision(document: dict[str, Any], expected: Any, *, subject: str) -> int:
    try:
        wanted = int(expected)
        current = int(document.get("revision", 0))
    except (TypeError, ValueError):
        raise SystemExit(f"Research monitor {subject} revision is invalid.") from None
    if wanted < 1 or current != wanted:
        raise SystemExit(
            f"Research monitor {subject} revision conflict: expected {wanted}, found {current}."
        )
    return current


def _sanitize_cadence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit("Research monitor cadence must be a mapping.")
    unknown = sorted(set(value) - {"every_days", "timezone", "anchor_at"})
    if unknown:
        raise SystemExit("Research monitor cadence contains unsupported fields.")
    every_days = value.get("every_days")
    if isinstance(every_days, bool):
        raise SystemExit("Research monitor cadence.every_days must be an integer.")
    try:
        every_days = int(every_days)
    except (TypeError, ValueError):
        raise SystemExit("Research monitor cadence.every_days must be an integer.") from None
    if every_days < 1 or every_days > 3650:
        raise SystemExit("Research monitor cadence.every_days must be between 1 and 3650.")
    timezone_name = _bounded_text(
        value.get("timezone"), field="cadence.timezone", required=True, limit=128
    )
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise SystemExit("Research monitor cadence.timezone is not recognized.") from None
    anchor = _parse_aware_datetime(value.get("anchor_at"), field="cadence.anchor_at")
    # The named zone is part of the user-facing schedule contract even though
    # canonical arithmetic uses the exact anchored instant in UTC.
    anchor.astimezone(zone)
    return {
        "every_days": every_days,
        "timezone": timezone_name,
        "anchor_at": _utc_iso(anchor),
    }


def _sanitize_target(kind: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit("Research monitor target must be a mapping.")
    if kind == "literature":
        unknown = sorted(set(value) - {"question"})
        if unknown:
            raise SystemExit("Literature monitor target contains unsupported fields.")
        return {
            "question": _bounded_text(
                value.get("question"), field="target.question", required=True
            )
        }
    if kind == "survey-freshness":
        unknown = sorted(set(value) - {"survey_path", "survey_sha256"})
        if unknown:
            raise SystemExit("Survey monitor target contains unsupported fields.")
        path = _bounded_text(value.get("survey_path"), field="target.survey_path", required=True)
        digest = _bounded_text(
            value.get("survey_sha256"), field="target.survey_sha256", required=True, limit=64
        )
        if SHA256_RE.fullmatch(digest) is None:
            raise SystemExit("Survey monitor target digest must be lowercase SHA-256.")
        return {"survey_path": path, "survey_sha256": digest}
    unknown = sorted(set(value) - {"unit_ids"})
    if unknown:
        raise SystemExit("Unit recheck target contains unsupported fields.")
    unit_ids = [_safe_id(item, field="target unit id") for item in _safe_string_list(value.get("unit_ids"), field="target.unit_ids")]
    if not unit_ids:
        raise SystemExit("Unit recheck target requires at least one unit id.")
    return {"unit_ids": unit_ids}


def _sanitize_budget(value: Any) -> dict[str, int]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise SystemExit("Research monitor budget must be a mapping.")
    allowed = {"max_queries", "max_candidates", "max_full_reads", "max_citation_hops"}
    if set(value) - allowed:
        raise SystemExit("Research monitor budget contains unsupported fields.")
    result: dict[str, int] = {}
    for key, raw in value.items():
        if isinstance(raw, bool):
            raise SystemExit(f"Research monitor budget.{key} must be a positive integer.")
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            raise SystemExit(f"Research monitor budget.{key} must be a positive integer.") from None
        if parsed < 1:
            raise SystemExit(f"Research monitor budget.{key} must be a positive integer.")
        result[key] = parsed
    return result


def _positive_revision(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise SystemExit(f"Research monitor {field} must be a positive integer.")
    try:
        revision = int(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Research monitor {field} must be a positive integer.") from None
    if revision < 1:
        raise SystemExit(f"Research monitor {field} must be a positive integer.")
    return revision


def _canonical_timestamp(value: Any, *, field: str, allow_empty: bool = False) -> str:
    if allow_empty and value in (None, ""):
        return ""
    return _utc_iso(_parse_aware_datetime(value, field=field))


def _sanitize_history(value: Any, *, statuses: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_COLLECTION:
        raise SystemExit("Research monitor history must be a bounded list.")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != HISTORY_FIELDS:
            raise SystemExit("Research monitor history entry is invalid.")
        revision = _positive_revision(item.get("revision"), field="history revision")
        if item.get("revision") != revision:
            raise SystemExit("Research monitor history revision is not canonical.")
        status = _bounded_text(item.get("status"), field="history status", required=True, limit=64)
        if status not in statuses:
            raise SystemExit("Research monitor history status is unsupported.")
        result.append(
            {
                "at": _canonical_timestamp(item.get("at"), field="history at"),
                "action": _bounded_text(
                    item.get("action"), field="history action", required=True, limit=256
                ),
                "revision": revision,
                "status": status,
            }
        )
    return result


def _validate_subscription_document(document: dict[str, Any]) -> None:
    if frozenset(document) not in {
        frozenset(SUBSCRIPTION_FIELDS),
        frozenset(LEGACY_SUBSCRIPTION_FIELDS),
    }:
        raise SystemExit("Research monitor subscription contains unsupported or missing fields.")
    if type(document.get("schema_version")) is not int or document.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("Research monitor subscription schema version is unsupported.")
    _safe_id(document.get("id"), field="subscription id")
    kind = str(document.get("kind") or "")
    if kind not in SUBSCRIPTION_KINDS:
        raise SystemExit("Research monitor subscription kind is unsupported.")
    if document.get("status") not in SUBSCRIPTION_STATUSES:
        raise SystemExit("Research monitor subscription status is unsupported.")
    revision = _positive_revision(document.get("revision"), field="subscription revision")
    if document.get("revision") != revision:
        raise SystemExit("Research monitor subscription revision is not canonical.")
    title = _bounded_text(document.get("title"), field="title", limit=500)
    if title != document.get("title"):
        raise SystemExit("Research monitor subscription title is not canonical.")
    target = _sanitize_target(kind, document.get("target"))
    if target != document.get("target"):
        raise SystemExit("Research monitor subscription target is not canonical.")
    raw_scope = document.get("scope_snapshot")
    scope = _safe_json_value(raw_scope, field="scope_snapshot")
    if (
        not isinstance(scope, dict)
        or scope != raw_scope
        or document.get("scope_digest") != value_digest(scope)
    ):
        raise SystemExit("Research monitor subscription scope binding is stale or invalid.")
    preference_binding = _sanitize_preference_binding(document.get("preference_binding"))
    if "preference_binding" in document and preference_binding != document.get("preference_binding"):
        raise SystemExit("Research monitor subscription preference binding is not canonical.")
    cadence = _sanitize_cadence(document.get("cadence"))
    if cadence != document.get("cadence"):
        raise SystemExit("Research monitor subscription cadence is not canonical.")
    if _canonical_timestamp(document.get("next_due_at"), field="next_due_at") != document.get("next_due_at"):
        raise SystemExit("Research monitor next_due_at is not canonical.")
    budget = _sanitize_budget(document.get("budget") or {})
    if budget != document.get("budget"):
        raise SystemExit("Research monitor subscription budget is not canonical.")
    program_ids = document.get("program_ids") or []
    canonical_program_ids = [
        _safe_id(item, field="program id")
        for item in _safe_string_list(program_ids, field="program_ids")
    ]
    if canonical_program_ids != program_ids:
        raise SystemExit("Research monitor program_ids are not canonical.")
    for field in ("active_run_id", "last_completed_run_id"):
        value = _bounded_text(document.get(field), field=field, limit=128)
        if value:
            _safe_id(value, field=field)
        if value != document.get(field):
            raise SystemExit(f"Research monitor {field} is not canonical.")
    for field in ("created_at", "updated_at"):
        if _canonical_timestamp(document.get(field), field=field) != document.get(field):
            raise SystemExit(f"Research monitor {field} is not canonical.")
    history = _sanitize_history(document.get("history"), statuses=SUBSCRIPTION_STATUSES)
    if history != document.get("history"):
        raise SystemExit("Research monitor subscription history is not canonical.")


def _validate_run_document(project_root: Path, document: dict[str, Any]) -> None:
    if set(document) != RUN_FIELDS:
        raise SystemExit("Research monitor run contains unsupported or missing fields.")
    if type(document.get("schema_version")) is not int or document.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("Research monitor run schema version is unsupported.")
    _safe_id(document.get("id"), field="run id")
    _safe_id(document.get("subscription_id"), field="subscription id")
    state = str(document.get("state") or "")
    if state not in RUN_STATES:
        raise SystemExit("Research monitor run state is unsupported.")
    revision = _positive_revision(document.get("revision"), field="run revision")
    if document.get("revision") != revision:
        raise SystemExit("Research monitor run revision is not canonical.")
    if _canonical_timestamp(document.get("scheduled_for"), field="scheduled_for") != document.get("scheduled_for"):
        raise SystemExit("Research monitor scheduled_for is not canonical.")
    frozen = document.get("frozen_subscription")
    if not isinstance(frozen, dict) or frozenset(frozen) not in {
        frozenset(FROZEN_SUBSCRIPTION_FIELDS),
        frozenset(LEGACY_FROZEN_SUBSCRIPTION_FIELDS),
    }:
        raise SystemExit("Research monitor run lacks a frozen subscription.")
    if frozen.get("kind") not in SUBSCRIPTION_KINDS:
        raise SystemExit("Research monitor frozen subscription kind is unsupported.")
    frozen_revision = _positive_revision(
        frozen.get("subscription_revision"), field="frozen subscription revision"
    )
    if frozen.get("subscription_revision") != frozen_revision:
        raise SystemExit("Research monitor frozen subscription revision is not canonical.")
    if "subscription_content_digest" in frozen and SHA256_RE.fullmatch(
        str(frozen.get("subscription_content_digest") or "")
    ) is None:
        raise SystemExit("Research monitor frozen subscription content binding is invalid.")
    target = _sanitize_target(str(frozen["kind"]), frozen.get("target"))
    if target != frozen.get("target"):
        raise SystemExit("Research monitor frozen target is not canonical.")
    raw_scope = frozen.get("scope_snapshot")
    scope = _safe_json_value(raw_scope, field="frozen scope")
    if (
        not isinstance(scope, dict)
        or scope != raw_scope
        or frozen.get("scope_digest") != value_digest(scope)
    ):
        raise SystemExit("Research monitor frozen run scope is invalid.")
    budget = _sanitize_budget(frozen.get("budget") or {})
    if budget != frozen.get("budget"):
        raise SystemExit("Research monitor frozen budget is not canonical.")
    cadence = _sanitize_cadence(frozen.get("cadence"))
    if cadence != frozen.get("cadence"):
        raise SystemExit("Research monitor frozen cadence is not canonical.")
    preference_binding = _sanitize_preference_binding(frozen.get("preference_binding"))
    if "preference_binding" in frozen and preference_binding != frozen.get("preference_binding"):
        raise SystemExit("Research monitor frozen preference binding is not canonical.")
    stop = _sanitize_stop(document.get("stop"), state=state)
    if stop != document.get("stop"):
        raise SystemExit("Research monitor run stop is not canonical.")
    for field in ("created_at", "updated_at"):
        if _canonical_timestamp(document.get(field), field=field) != document.get(field):
            raise SystemExit(f"Research monitor {field} is not canonical.")
    for field in ("started_at", "completed_at"):
        if _canonical_timestamp(document.get(field), field=field, allow_empty=True) != document.get(field):
            raise SystemExit(f"Research monitor {field} is not canonical.")
    expected_content_digest = str(document.get("content_digest") or "")
    if SHA256_RE.fullmatch(expected_content_digest) is None or expected_content_digest != _run_content_digest(document):
        raise SystemExit("Research monitor run receipt content digest is stale or invalid.")
    task_binding = monitor_task_binding(document)
    outputs = _sanitize_outputs(project_root, document.get("outputs"), expected_monitor_binding=task_binding)
    if outputs != document.get("outputs"):
        raise SystemExit("Research monitor run outputs are not canonical.")
    # Legacy rc.6 receipts did not persist a disposition object.  They remain
    # readable and are treated as unresolved by the read model; every new or
    # subsequently resolved receipt writes the explicit disposition.
    outcomes = _sanitize_review_outcomes(
        project_root,
        document.get("review_outcomes"),
        add_default_disposition=False,
    )
    if outcomes != document.get("review_outcomes"):
        raise SystemExit("Research monitor review outcomes are not canonical.")
    _validate_outcome_links(outputs, outcomes)
    history = _sanitize_history(document.get("history"), statuses=RUN_STATES)
    if history != document.get("history"):
        raise SystemExit("Research monitor run history is not canonical.")
    if state in TERMINAL_RUN_STATES and not document.get("completed_at"):
        raise SystemExit("Research monitor terminal run lacks a completion time.")
    if state == "completed" and str(document.get("stop", {}).get("reason") or "") != "user_stop":
        _validate_completion_outputs(document, outputs)


def build_subscription_id(kind: str, target: dict[str, Any], cadence: dict[str, Any]) -> str:
    prefix = {"literature": "lit", "survey-freshness": "survey", "unit-recheck": "unit"}.get(kind)
    if prefix is None:
        raise SystemExit("Research monitor subscription kind is unsupported.")
    return f"monitor-{prefix}-{value_digest({'target': target, 'cadence': cadence})[:16]}"


def _canonical_unit_record_path(project_root: Path, unit_id: str) -> Path:
    matches: list[Path] = []
    root = units_root(project_root)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise SystemExit("Research monitor unit root is unsafe.")
    for kind_root in sorted(root.iterdir(), key=lambda item: item.name) if root.exists() else []:
        if kind_root.is_symlink() or not kind_root.is_dir():
            raise SystemExit("Research monitor unit root contains an unsafe entry.")
        candidate = kind_root / unit_id / "record.yaml"
        if not candidate.exists() and not candidate.is_symlink():
            continue
        _assert_safe_business_path(project_root, candidate, allowed_root=root)
        if candidate.is_file():
            record = load_yaml(candidate, default={})
            if isinstance(record, dict) and str(record.get("id") or "") == unit_id:
                matches.append(candidate)
    if len(matches) != 1:
        raise SystemExit("Research monitor unit target must resolve to one canonical record.")
    return matches[0]


def _same_record_snapshot(
    left: CanonicalRecordSnapshot,
    right: CanonicalRecordSnapshot,
) -> bool:
    return (
        left.kind == right.kind
        and left.unit_id == right.unit_id
        and left.path == right.path
        and left.raw_bytes == right.raw_bytes
        and left.file_identity == right.file_identity
    )


def _materialized_unit_snapshot(
    project_root: Path,
    unit_id: str,
) -> CanonicalUnitSnapshot:
    matches = [
        snapshot
        for snapshot in iter_canonical_record_snapshots(project_root)
        if snapshot.unit_id == unit_id
    ]
    if len(matches) != 1:
        raise SystemExit("Materialized monitor outcome target is not a canonical unit.")
    selected = matches[0]
    if normalize_record_snapshot(selected, project_root) is None:
        raise SystemExit("Materialized monitor outcome target is not a canonical unit.")
    current = snapshot_canonical_unit_artifacts(
        project_root,
        selected.kind,
        selected.unit_id,
        (),
    )
    if (
        current is None
        or not _same_record_snapshot(selected, current.record)
        or not current.is_current()
    ):
        raise SystemExit("Materialized monitor outcome target is not a canonical unit.")
    return current


def _subscription_reference_bindings(
    project_root: Path,
    *,
    kind: str,
    target: dict[str, Any],
    program_ids: list[str],
) -> dict[str, str]:
    bindings: list[dict[str, str]] = []
    for program_id in program_ids:
        program = kb_root(project_root) / "programs" / program_id
        binding = regular_tree_binding(
            program,
            logical_identity=f"program:{program_id}",
            trusted_root=project_root,
        )
        bindings.append({"kind": "program", "id": program_id, **binding})
    if kind == "survey-freshness":
        survey_path = _trusted_referenced_file(
            project_root,
            str(target.get("survey_path") or ""),
            allowed_roots=(synthesis_root(project_root),),
        )
        binding = regular_file_binding(
            survey_path,
            logical_identity=f"survey:{target.get('survey_path')}",
            trusted_root=project_root,
        )
        bindings.append({"kind": "survey", "id": str(target.get("survey_path") or ""), **binding})
    elif kind == "unit-recheck":
        for unit_id in target.get("unit_ids") or []:
            record = _canonical_unit_record_path(project_root, str(unit_id))
            binding = regular_file_binding(
                record,
                logical_identity=f"unit:{unit_id}:record.yaml",
                trusted_root=project_root,
            )
            bindings.append({"kind": "unit", "id": str(unit_id), **binding})
    bindings.sort(key=lambda item: (item["kind"], item["id"]))
    return {
        "identity_digest": canonical_digest(
            [
                {"kind": item["kind"], "id": item["id"], "identity_digest": item["identity_digest"]}
                for item in bindings
            ]
        ),
        "bytes_digest": canonical_digest(
            [
                {"kind": item["kind"], "id": item["id"], "bytes_digest": item["bytes_digest"]}
                for item in bindings
            ]
        ),
    }


def _normalize_subscription_request(
    project_root: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit("Research monitor subscription input must be a mapping.")
    allowed = {
        "subscription_id",
        "kind",
        "title",
        "program_ids",
        "target",
        "scope",
        "budget",
        "cadence",
    }
    if set(payload) - allowed:
        raise SystemExit("Research monitor subscription input contains unsupported fields.")
    kind = _bounded_text(payload.get("kind"), field="kind", required=True, limit=64)
    if kind not in SUBSCRIPTION_KINDS:
        raise SystemExit("Research monitor subscription kind is unsupported.")
    target = _sanitize_target(kind, payload.get("target"))
    cadence = _sanitize_cadence(payload.get("cadence"))
    subscription_id = (
        _safe_id(payload.get("subscription_id"), field="subscription id")
        if payload.get("subscription_id")
        else build_subscription_id(kind, target, cadence)
    )
    raw_scope = payload.get("scope")
    if raw_scope is None:
        raw_scope = {}
    scope = _safe_json_value(raw_scope, field="scope")
    if not isinstance(scope, dict):
        raise SystemExit("Research monitor scope must be a mapping.")
    program_ids = [
        _safe_id(item, field="program id")
        for item in _safe_string_list(payload.get("program_ids"), field="program_ids")
    ]
    _program_reporting_paths(project_root, program_ids)
    _validate_new_subscription_target(project_root, kind, target)
    return {
        "subscription_id": subscription_id,
        "kind": kind,
        "title": _bounded_text(payload.get("title"), field="title", limit=500),
        "program_ids": program_ids,
        "target": target,
        "scope": scope,
        "budget": _sanitize_budget(payload.get("budget")),
        "cadence": cadence,
    }


def monitor_subscription_preference_context(
    project_root: Path,
    payload: dict[str, Any],
) -> dict[str, object]:
    """Return exact finalized request/reference inputs for Agent selection."""
    request = _normalize_subscription_request(project_root, payload)
    references = _subscription_reference_bindings(
        project_root,
        kind=str(request["kind"]),
        target=dict(request["target"]),
        program_ids=list(request["program_ids"]),
    )
    return {
        "canonical_id": str(request["subscription_id"]),
        "canonical_kind": "research-monitor-subscription",
        "operation": PREFERENCE_OPERATION,
        "request_digest": canonical_digest(request),
        "subscription_id": str(request["subscription_id"]),
        "target_digest": canonical_digest(request["target"]),
        "cadence_digest": canonical_digest(request["cadence"]),
        "scope_digest": canonical_digest(request["scope"]),
        "budget_digest": canonical_digest(request["budget"]),
        "program_ids_digest": canonical_digest(request["program_ids"]),
        "reference_bindings_identity_digest": references["identity_digest"],
        "reference_bindings_bytes_digest": references["bytes_digest"],
        "operation_contract_digest": canonical_digest(
            operation_contract(skill=PREFERENCE_SKILL, operation=PREFERENCE_OPERATION)
        ),
    }


def _resolve_subscription_preference_binding(
    project_root: Path,
    *,
    selection_id: str,
    context: dict[str, object],
) -> dict[str, str]:
    if not str(selection_id or "").strip():
        return {}
    try:
        effective = resolve_task_preferences(
            project_root,
            selection_id=str(selection_id).strip(),
            skill=PREFERENCE_SKILL,
            operation=PREFERENCE_OPERATION,
            canonical_inputs=context,
        )
    except ValueError as exc:
        raise SystemExit(f"Research monitor preference receipt is stale or invalid: {exc}") from exc
    return _sanitize_preference_binding(selection_binding(effective))


def create_subscription(
    project_root: Path,
    payload: dict[str, Any],
    *,
    now: datetime | str | None = None,
    preference_selection_id: str = "",
) -> Path:
    request = _normalize_subscription_request(project_root, payload)
    context = monitor_subscription_preference_context(project_root, payload)
    preference_binding = _resolve_subscription_preference_binding(
        project_root,
        selection_id=preference_selection_id,
        context=context,
    )
    kind = str(request["kind"])
    target = dict(request["target"])
    cadence = dict(request["cadence"])
    subscription_id = str(request["subscription_id"])
    path = subscription_path(project_root, subscription_id)
    _assert_safe_business_path(project_root, path, allowed_root=subscriptions_root(project_root))
    created_at = _utc_iso(_now(now))
    document = {
        "schema_version": SCHEMA_VERSION,
        "id": subscription_id,
        "kind": kind,
        "status": "active",
        "title": request["title"],
        "program_ids": list(request["program_ids"]),
        "target": target,
        "scope_snapshot": dict(request["scope"]),
        "scope_digest": value_digest(request["scope"]),
        "preference_binding": preference_binding,
        "budget": dict(request["budget"]),
        "cadence": cadence,
        "next_due_at": cadence["anchor_at"],
        "active_run_id": "",
        "last_completed_run_id": "",
        "created_at": created_at,
        "updated_at": created_at,
        "revision": 1,
        "history": [],
    }

    def preflight() -> None:
        _assert_safe_business_path(project_root, path, allowed_root=subscriptions_root(project_root))
        if path.exists() or path.is_symlink():
            raise SystemExit(f"Research monitor subscription already exists: {subscription_id}")
        current_request = _normalize_subscription_request(project_root, payload)
        current_context = monitor_subscription_preference_context(project_root, payload)
        current_binding = _resolve_subscription_preference_binding(
            project_root,
            selection_id=preference_selection_id,
            context=current_context,
        )
        if current_request != request or current_context != context or current_binding != preference_binding:
            raise SystemExit("Research monitor subscription inputs changed before write.")

    with mutation_transaction(
        project_root,
        "research-monitor:create-subscription",
        [path],
        preflight=preflight,
    ):
        current_context = monitor_subscription_preference_context(project_root, payload)
        current_binding = _resolve_subscription_preference_binding(
            project_root,
            selection_id=preference_selection_id,
            context=current_context,
        )
        if current_context != context or current_binding != preference_binding:
            raise SystemExit("Research monitor subscription inputs changed before write.")
        write_yaml_if_changed(path, document)
    return path


def _history_snapshot(document: dict[str, Any], *, at: str, action: str) -> dict[str, Any]:
    return {
        "at": at,
        "action": action,
        "revision": int(document.get("revision", 0)),
        "status": str(document.get("status") or document.get("state") or ""),
    }


def set_subscription_status(
    project_root: Path,
    subscription_id: str,
    *,
    expected_revision: int,
    status: str,
    now: datetime | str | None = None,
) -> Path:
    if status not in SUBSCRIPTION_STATUSES:
        raise SystemExit("Research monitor subscription status is unsupported.")
    path = subscription_path(project_root, subscription_id)
    changed_at = _utc_iso(_now(now))

    def preflight() -> None:
        current = load_subscription(project_root, subscription_id)
        _expected_revision(current, expected_revision, subject="subscription")
        if current.get("status") == "completed" and status != "completed":
            raise SystemExit("A completed research monitor subscription cannot be reopened.")
        if status == "completed" and current.get("active_run_id"):
            raise SystemExit("An active research monitor run must finish before subscription completion.")

    with mutation_transaction(
        project_root,
        "research-monitor:set-subscription-status",
        [path],
        preflight=preflight,
    ):
        current = load_subscription(project_root, subscription_id)
        if current.get("status") == status:
            return path
        current.setdefault("history", []).append(
            _history_snapshot(current, at=changed_at, action=f"status->{status}")
        )
        current["status"] = status
        current["updated_at"] = changed_at
        current["revision"] = int(current["revision"]) + 1
        write_yaml_if_changed(path, current)
    return path


def _iter_documents(root: Path, *, label: str) -> Iterable[Path]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise SystemExit(f"Research monitor {label} root is unsafe.")
    documents: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.is_symlink() or not child.is_file() or child.suffix != ".yaml":
            raise SystemExit(f"Research monitor {label} contains an unsafe entry.")
        documents.append(child)
    return documents


def due_subscriptions(
    project_root: Path,
    *,
    now: datetime | str | None = None,
) -> list[dict[str, Any]]:
    current_time = _now(now)
    due: list[dict[str, Any]] = []
    for path in _iter_documents(subscriptions_root(project_root), label="subscriptions"):
        subscription_id = path.stem
        subscription = load_subscription(project_root, subscription_id)
        active_run_id = str(subscription.get("active_run_id") or "")
        if active_run_id:
            active_run = load_run(project_root, active_run_id)
            if (
                active_run.get("subscription_id") != subscription_id
                or active_run.get("state") in TERMINAL_RUN_STATES
            ):
                raise SystemExit("Research monitor subscription has an invalid active run link.")
        if subscription.get("status") != "active" or active_run_id:
            continue
        due_at = _parse_aware_datetime(subscription.get("next_due_at"), field="next_due_at")
        if due_at > current_time:
            continue
        cadence = _sanitize_cadence(subscription.get("cadence"))
        missed_windows = _elapsed_cadence_windows(cadence, due_at, current_time)
        due.append(
            {
                "subscription_id": subscription_id,
                "kind": subscription.get("kind"),
                "title": subscription.get("title") or subscription_id,
                "program_ids": list(subscription.get("program_ids") or []),
                "due_at": _utc_iso(due_at),
                "overdue_windows": missed_windows,
                "subscription_revision": int(subscription.get("revision", 0)),
                "scope_digest": str(subscription.get("scope_digest") or ""),
            }
        )
    return sorted(due, key=lambda item: (item["due_at"], item["subscription_id"]))


def active_monitor_runs(project_root: Path) -> list[dict[str, Any]]:
    """Pure projection of every valid non-terminal subscription-owned run."""
    active: list[dict[str, Any]] = []
    for path in _iter_documents(subscriptions_root(project_root), label="subscriptions"):
        subscription_id = path.stem
        subscription = load_subscription(project_root, subscription_id)
        run_id = str(subscription.get("active_run_id") or "")
        if not run_id:
            continue
        run = load_run(project_root, run_id)
        state = str(run.get("state") or "")
        if (
            str(run.get("subscription_id") or "") != subscription_id
            or state in TERMINAL_RUN_STATES
            or state not in RUN_STATES - TERMINAL_RUN_STATES
        ):
            raise SystemExit("Research monitor subscription has an invalid active run link.")
        active.append(
            {
                "subscription_id": subscription_id,
                "subscription_title": str(subscription.get("title") or subscription_id),
                "subscription_status": str(subscription.get("status") or ""),
                "subscription_revision": int(subscription.get("revision") or 0),
                "subscription_content_digest": value_digest(subscription),
                "subscription_scope_digest": str(subscription.get("scope_digest") or ""),
                "preference_binding": deepcopy(subscription.get("preference_binding") or {}),
                "program_ids": list(subscription.get("program_ids") or []),
                "run_id": run_id,
                "run_state": state,
                "run_revision": int(run.get("revision") or 0),
                "run_content_digest": str(run.get("content_digest") or ""),
                "scheduled_for": str(run.get("scheduled_for") or ""),
                "stop": deepcopy(run.get("stop") or {}),
            }
        )
    return sorted(active, key=lambda item: (item["subscription_id"], item["run_id"]))


def _run_id(subscription_id: str, scheduled_for: str) -> str:
    suffix = value_digest({"subscription_id": subscription_id, "scheduled_for": scheduled_for})[:16]
    return f"monitor-run-{suffix}"


def create_due_run(
    project_root: Path,
    subscription_id: str,
    *,
    expected_subscription_revision: int,
    now: datetime | str | None = None,
) -> Path:
    current_time = _now(now)
    initial = load_subscription(project_root, subscription_id)
    scheduled_for = _utc_iso(
        _parse_aware_datetime(initial.get("next_due_at"), field="next_due_at")
    )
    run_id = _run_id(subscription_id, scheduled_for)
    subscription_file = subscription_path(project_root, subscription_id)
    receipt_file = run_path(project_root, run_id)
    targets = [subscription_file, receipt_file]

    def preflight() -> None:
        subscription = load_subscription(project_root, subscription_id)
        _expected_revision(
            subscription, expected_subscription_revision, subject="subscription"
        )
        if subscription.get("status") != "active":
            raise SystemExit("Only an active research monitor subscription can create a due run.")
        if subscription.get("active_run_id"):
            raise SystemExit("Research monitor subscription already has an active run.")
        due_at = _parse_aware_datetime(subscription.get("next_due_at"), field="next_due_at")
        if due_at > current_time:
            raise SystemExit("Research monitor subscription is not due yet.")
        expected_run_id = _run_id(subscription_id, _utc_iso(due_at))
        if expected_run_id != run_id or receipt_file.exists() or receipt_file.is_symlink():
            raise SystemExit("Research monitor due window already has a run receipt.")
        _assert_safe_business_path(project_root, receipt_file, allowed_root=runs_root(project_root))

    with mutation_transaction(
        project_root,
        "research-monitor:create-due-run",
        targets,
        preflight=preflight,
    ):
        subscription = load_subscription(project_root, subscription_id)
        created_at = _utc_iso(current_time)
        frozen = {
            "subscription_revision": int(subscription["revision"]),
            "subscription_content_digest": value_digest(subscription),
            "kind": subscription["kind"],
            "target": deepcopy(subscription["target"]),
            "scope_snapshot": deepcopy(subscription["scope_snapshot"]),
            "scope_digest": subscription["scope_digest"],
            "budget": deepcopy(subscription.get("budget") or {}),
            "cadence": deepcopy(subscription["cadence"]),
            "preference_binding": deepcopy(subscription.get("preference_binding") or {}),
        }
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "id": run_id,
            "subscription_id": subscription_id,
            "scheduled_for": scheduled_for,
            "state": "planned",
            "frozen_subscription": frozen,
            "outputs": {
                "literature_stage_ids": [],
                "literature_stage_bindings": [],
                "survey_bindings": [],
                "unit_ids": [],
            },
            "review_outcomes": [],
            "stop": {"reason": "in_progress", "rationale": ""},
            "created_at": created_at,
            "updated_at": created_at,
            "started_at": "",
            "completed_at": "",
            "revision": 1,
            "history": [],
        }
        receipt["content_digest"] = _run_content_digest(receipt)
        subscription.setdefault("history", []).append(
            _history_snapshot(subscription, at=created_at, action=f"run-created:{run_id}")
        )
        # A legacy neutral v1 subscription graduates to the closed R11 shape
        # on its next mutation; the frozen digest above still names the exact
        # pre-mutation subscription that this run consumed.
        subscription.setdefault("preference_binding", {})
        subscription["active_run_id"] = run_id
        subscription["updated_at"] = created_at
        subscription["revision"] = int(subscription["revision"]) + 1
        write_yaml_if_changed(receipt_file, receipt)
        write_yaml_if_changed(subscription_file, subscription)
    return receipt_file


def _sanitize_stop(value: Any, *, state: str) -> dict[str, str]:
    if value is None:
        value = {"reason": "in_progress", "rationale": ""}
    if not isinstance(value, dict) or set(value) - {"reason", "rationale"}:
        raise SystemExit("Research monitor stop must be a reason/rationale mapping.")
    reason = _bounded_text(value.get("reason"), field="stop.reason", required=True, limit=64)
    if reason not in STOP_REASONS_BY_STATE[state]:
        raise SystemExit("Research monitor stop reason does not match the run state.")
    rationale = _bounded_text(value.get("rationale"), field="stop.rationale", limit=2000)
    if state not in {"planned", "running"} and not rationale:
        raise SystemExit("Research monitor stopped state requires a rationale.")
    return {"reason": reason, "rationale": rationale}


def transition_run(
    project_root: Path,
    run_id: str,
    *,
    expected_revision: int,
    state: str,
    stop: dict[str, Any] | None = None,
    now: datetime | str | None = None,
) -> Path:
    if state not in RUN_STATES or state in TERMINAL_RUN_STATES:
        raise SystemExit("Use the terminal run operation for completed or cancelled runs.")
    path = run_path(project_root, run_id)
    changed_at = _utc_iso(_now(now))
    safe_stop = _sanitize_stop(stop, state=state)

    def preflight() -> None:
        current = load_run(project_root, run_id)
        _expected_revision(current, expected_revision, subject="run")
        prior_state = str(current.get("state") or "")
        if state not in RUN_TRANSITIONS.get(prior_state, set()):
            raise SystemExit(f"Research monitor run cannot transition from {prior_state} to {state}.")

    with mutation_transaction(
        project_root,
        "research-monitor:transition-run",
        [path],
        preflight=preflight,
    ):
        current = load_run(project_root, run_id)
        current.setdefault("history", []).append(
            _history_snapshot(current, at=changed_at, action=f"state->{state}")
        )
        current["state"] = state
        current["stop"] = safe_stop
        if state == "running" and not current.get("started_at"):
            current["started_at"] = changed_at
        current["updated_at"] = changed_at
        current["revision"] = int(current["revision"]) + 1
        current["content_digest"] = _run_content_digest(current)
        write_yaml_if_changed(path, current)
    return path


def _trusted_referenced_file(
    project_root: Path,
    relative_path: str,
    *,
    allowed_roots: tuple[Path, ...],
) -> Path:
    text = _bounded_text(relative_path, field="reference path", required=True, limit=1000)
    candidate = project_root / text
    if Path(text).is_absolute():
        raise SystemExit("Research monitor references must be project-relative.")
    for allowed in allowed_roots:
        try:
            candidate.resolve(strict=False).relative_to(allowed.resolve())
        except ValueError:
            continue
        _assert_safe_business_path(project_root, candidate, allowed_root=allowed)
        if not candidate.is_file():
            raise SystemExit("Research monitor referenced file does not exist.")
        return candidate
    raise SystemExit("Research monitor reference escapes its allowed roots.")


def _load_literature_stage(
    project_root: Path,
    stage_id: str,
    *,
    require_terminal: bool = False,
    expected_monitor_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    safe_id = _safe_id(stage_id, field="literature stage id")
    path = search_stage_path(project_root, safe_id)
    _assert_safe_business_path(project_root, path, allowed_root=source_search_root(project_root))
    if not path.is_file() or yaml_duplicate_key_issues(path):
        raise SystemExit("Research monitor literature stage is missing or unsafe.")
    stage = load_yaml(path, default={})
    if (
        not isinstance(stage, dict)
        or str(stage.get("id") or "") != safe_id
        or str(stage.get("kind") or "") != "source-search-stage"
        or str(stage.get("entry_skill") or "") != "literature-search"
    ):
        raise SystemExit("Research monitor reference is not a literature-search stage.")
    stop = stage.get("stop") if isinstance(stage.get("stop"), dict) else {}
    if require_terminal and stop.get("reason") not in {
        "target_met",
        "saturated",
        "budget_exhausted",
        "user_stop",
    }:
        raise SystemExit("Research monitor linked literature-search stage is not complete.")
    if expected_monitor_binding is not None and stage.get("monitor_binding") != expected_monitor_binding:
        raise SystemExit("Research monitor literature stage is bound to another frozen run.")
    return stage


def _sanitize_survey_binding(project_root: Path, value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {"path", "byte_sha256"}:
        raise SystemExit("Research monitor survey binding is invalid.")
    path_text = _bounded_text(value.get("path"), field="survey path", required=True, limit=1000)
    if not path_text.endswith("/survey.yaml"):
        raise SystemExit("Research monitor survey binding must reference survey.yaml.")
    path = _trusted_referenced_file(
        project_root, path_text, allowed_roots=(synthesis_root(project_root),)
    )
    digest = _bounded_text(
        value.get("byte_sha256"), field="survey digest", required=True, limit=64
    )
    if SHA256_RE.fullmatch(digest) is None or file_sha256(path) != digest:
        raise SystemExit("Research monitor survey binding digest is stale or invalid.")
    return {"path": path.relative_to(project_root).as_posix(), "byte_sha256": digest}


def _validate_new_subscription_target(
    project_root: Path, kind: str, target: dict[str, Any]
) -> None:
    if kind == "survey-freshness":
        _sanitize_survey_binding(
            project_root,
            {
                "path": target.get("survey_path"),
                "byte_sha256": target.get("survey_sha256"),
            },
        )
        return
    if kind != "unit-recheck":
        return
    for unit_id in target.get("unit_ids") or []:
        _canonical_unit_record_path(project_root, str(unit_id))


def _sanitize_outputs(
    project_root: Path,
    value: Any,
    *,
    expected_monitor_binding: dict[str, str] | None = None,
) -> dict[str, Any]:
    if value in (None, {}):
        value = {}
    allowed = {"literature_stage_ids", "literature_stage_bindings", "survey_bindings", "unit_ids"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise SystemExit("Research monitor outputs contain unsupported fields.")
    stage_ids = [
        _safe_id(item, field="literature stage id")
        for item in _safe_string_list(value.get("literature_stage_ids"), field="literature_stage_ids")
    ]
    stage_bindings: list[dict[str, str]] = []
    for stage_id in stage_ids:
        _load_literature_stage(
            project_root,
            stage_id,
            require_terminal=True,
            expected_monitor_binding=expected_monitor_binding,
        )
        stage_file = search_stage_path(project_root, stage_id)
        stage_bindings.append({"stage_id": stage_id, "byte_sha256": file_sha256(stage_file)})
    supplied_bindings = value.get("literature_stage_bindings")
    if supplied_bindings not in (None, []) and supplied_bindings != stage_bindings:
        raise SystemExit("Research monitor literature stage byte binding is stale or invalid.")
    raw_surveys = value.get("survey_bindings") or []
    if not isinstance(raw_surveys, list) or len(raw_surveys) > MAX_COLLECTION:
        raise SystemExit("Research monitor survey bindings must be a bounded list.")
    surveys = [_sanitize_survey_binding(project_root, item) for item in raw_surveys]
    if len({item["path"] for item in surveys}) != len(surveys):
        raise SystemExit("Research monitor survey bindings must be unique.")
    unit_ids = [
        _safe_id(item, field="output unit id")
        for item in _safe_string_list(value.get("unit_ids"), field="outputs.unit_ids")
    ]
    return {
        "literature_stage_ids": stage_ids,
        "literature_stage_bindings": stage_bindings,
        "survey_bindings": surveys,
        "unit_ids": unit_ids,
    }


def _sanitize_reference(project_root: Path, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit("Research monitor outcome reference must be a mapping.")
    kind = _bounded_text(value.get("kind"), field="reference kind", required=True, limit=64)
    if kind not in REFERENCE_KINDS:
        raise SystemExit("Research monitor outcome reference kind is unsupported.")
    if kind == "literature-candidate":
        if set(value) - {"kind", "stage_id", "candidate_id"}:
            raise SystemExit("Research monitor literature candidate reference is invalid.")
        stage_id = _safe_id(value.get("stage_id"), field="literature stage id")
        candidate_id = _safe_id(value.get("candidate_id"), field="candidate id")
        stage = _load_literature_stage(project_root, stage_id)
        candidates = [item for item in stage.get("candidates", []) if isinstance(item, dict)]
        if not any(str(item.get("candidate_id") or "") == candidate_id for item in candidates):
            raise SystemExit("Research monitor outcome references an unknown literature candidate.")
        return {"kind": kind, "stage_id": stage_id, "candidate_id": candidate_id}
    if kind == "survey-output":
        if set(value) - {"kind", "path", "byte_sha256"}:
            raise SystemExit("Research monitor survey outcome reference is invalid.")
        binding = _sanitize_survey_binding(project_root, value)
        return {"kind": kind, **binding}
    if set(value) - {"kind", "path", "byte_sha256", "locator", "quote"}:
        raise SystemExit("Research monitor artifact reference is invalid.")
    path_text = _bounded_text(value.get("path"), field="artifact path", required=True, limit=1000)
    path = _trusted_referenced_file(
        project_root,
        path_text,
        allowed_roots=(units_root(project_root), synthesis_root(project_root)),
    )
    digest = _bounded_text(
        value.get("byte_sha256"), field="artifact digest", required=True, limit=64
    )
    if SHA256_RE.fullmatch(digest) is None or file_sha256(path) != digest:
        raise SystemExit("Research monitor artifact binding digest is stale or invalid.")
    quote = _bounded_text(value.get("quote"), field="artifact quote", required=True, limit=1000)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise SystemExit("Research monitor artifact evidence must be readable UTF-8 text.") from None
    if quote not in text:
        raise SystemExit("Research monitor artifact quote is not verbatim evidence.")
    return {
        "kind": kind,
        "path": path.relative_to(project_root).as_posix(),
        "byte_sha256": digest,
        "locator": _bounded_text(value.get("locator"), field="artifact locator", required=True, limit=500),
        "quote": quote,
    }


def _sanitize_outcome_disposition(
    value: Any,
    *,
    classification: str,
) -> dict[str, str]:
    if value in (None, {}):
        return {
            "state": "unresolved",
            "actor": "",
            "at": "",
            "reason": "",
            "target_ref": "",
            "user_authorization": "",
            "authorization_source": "",
        }
    if not isinstance(value, dict) or set(value) != OUTCOME_DISPOSITION_FIELDS:
        raise SystemExit("Research monitor outcome disposition is invalid.")
    state = _bounded_text(value.get("state"), field="outcome disposition state", required=True, limit=64)
    if state not in OUTCOME_DISPOSITION_STATES:
        raise SystemExit("Research monitor outcome disposition state is unsupported.")
    actor = _bounded_text(value.get("actor"), field="outcome disposition actor", limit=200)
    at = _canonical_timestamp(
        value.get("at"),
        field="outcome disposition at",
        allow_empty=True,
    )
    reason = _bounded_text(value.get("reason"), field="outcome disposition reason", limit=1000)
    target_ref = _bounded_text(value.get("target_ref"), field="outcome disposition target", limit=500)
    user_authorization = _bounded_text(
        value.get("user_authorization"),
        field="outcome disposition authorization",
        limit=1000,
    )
    authorization_source = _bounded_text(
        value.get("authorization_source"),
        field="outcome disposition authorization source",
        limit=64,
    )
    if state == "unresolved":
        if any((actor, at, reason, target_ref, user_authorization, authorization_source)):
            raise SystemExit("Unresolved monitor outcomes cannot contain a completed disposition.")
    else:
        if state not in OUTCOME_DISPOSITIONS_BY_CLASSIFICATION.get(classification, set()):
            raise SystemExit("Research monitor outcome disposition does not match its classification.")
        if not actor or not at or not reason:
            raise SystemExit("Resolved monitor outcomes require actor, time, and reason.")
        if state in {"materialized", "sent_to_review"} and not target_ref:
            raise SystemExit("Materialized or review-routed outcomes require a target reference.")
        if state == "materialized" and (
            authorization_source != "user_message" or not user_authorization
        ):
            raise SystemExit("Materializing a monitor candidate requires current user authorization.")
        if authorization_source and authorization_source != "user_message":
            raise SystemExit("Research monitor authorization_source is unsupported.")
    return {
        "state": state,
        "actor": actor,
        "at": at,
        "reason": reason,
        "target_ref": target_ref,
        "user_authorization": user_authorization,
        "authorization_source": authorization_source,
    }


def _sanitize_review_outcomes(
    project_root: Path,
    value: Any,
    *,
    add_default_disposition: bool = True,
) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_COLLECTION:
        raise SystemExit("Research monitor review outcomes must be a bounded list.")
    outcomes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {
            "outcome_id",
            "classification",
            "subject_ref",
            "rationale",
            "references",
            "disposition",
        }:
            raise SystemExit("Research monitor review outcome is invalid.")
        outcome_id = _safe_id(item.get("outcome_id"), field="outcome id")
        if outcome_id in seen:
            raise SystemExit("Research monitor review outcome ids must be unique.")
        seen.add(outcome_id)
        classification = _bounded_text(
            item.get("classification"), field="outcome classification", required=True, limit=64
        )
        if classification not in REVIEW_OUTCOMES:
            raise SystemExit("Research monitor review outcome classification is unsupported.")
        raw_refs = item.get("references") or []
        if not isinstance(raw_refs, list) or len(raw_refs) > MAX_COLLECTION:
            raise SystemExit("Research monitor review outcome references must be a bounded list.")
        references = [_sanitize_reference(project_root, ref) for ref in raw_refs]
        if classification != "no_material_change" and not references:
            raise SystemExit("Research monitor substantive review outcome requires references.")
        if classification == "contradiction_candidate" and len(
            {value_digest(reference) for reference in references}
        ) < 2:
            raise SystemExit("Research monitor contradiction candidate requires both sides of evidence.")
        normalized = {
            "outcome_id": outcome_id,
            "classification": classification,
            "subject_ref": _bounded_text(
                item.get("subject_ref"), field="outcome subject", required=True, limit=500
            ),
            "rationale": _bounded_text(
                item.get("rationale"), field="outcome rationale", required=True, limit=2000
            ),
            "references": references,
        }
        if "disposition" in item or add_default_disposition:
            normalized["disposition"] = _sanitize_outcome_disposition(
                item.get("disposition"),
                classification=classification,
            )
        outcomes.append(normalized)
    return outcomes


def _validate_outcome_links(
    outputs: dict[str, Any], outcomes: list[dict[str, Any]]
) -> None:
    stages = set(outputs.get("literature_stage_ids") or [])
    surveys = {
        (str(item.get("path") or ""), str(item.get("byte_sha256") or ""))
        for item in outputs.get("survey_bindings") or []
        if isinstance(item, dict)
    }
    for outcome in outcomes:
        for reference in outcome.get("references") or []:
            if reference.get("kind") == "literature-candidate" and reference.get("stage_id") not in stages:
                raise SystemExit(
                    "Research monitor outcome references a literature stage not linked by this run."
                )
            if reference.get("kind") == "survey-output" and (
                str(reference.get("path") or ""),
                str(reference.get("byte_sha256") or ""),
            ) not in surveys:
                raise SystemExit(
                    "Research monitor outcome references a survey not linked by this run."
                )


def _validate_completion_outputs(document: dict[str, Any], outputs: dict[str, Any]) -> None:
    frozen = document.get("frozen_subscription")
    if not isinstance(frozen, dict):
        raise SystemExit("Research monitor run lacks a frozen subscription.")
    kind = str(frozen.get("kind") or "")
    target = frozen.get("target") if isinstance(frozen.get("target"), dict) else {}
    if kind == "literature":
        if not outputs.get("literature_stage_ids"):
            raise SystemExit("Completed literature monitoring requires a linked literature-search run.")
        return
    if kind == "survey-freshness":
        bindings = outputs.get("survey_bindings") or []
        if not bindings:
            raise SystemExit("Completed survey monitoring requires a bound survey output.")
        expected_path = str(target.get("survey_path") or "")
        if {str(item.get("path") or "") for item in bindings if isinstance(item, dict)} != {expected_path}:
            raise SystemExit("Completed survey monitoring must bind the frozen survey target.")
        return
    expected_units = set(target.get("unit_ids") or [])
    if set(outputs.get("unit_ids") or []) != expected_units:
        raise SystemExit("Completed unit recheck must cover every frozen target unit.")


def _next_due_after(cadence: dict[str, Any], after: datetime) -> str:
    safe = _sanitize_cadence(cadence)
    anchor = _parse_aware_datetime(safe["anchor_at"], field="cadence.anchor_at")
    zone = ZoneInfo(str(safe["timezone"]))
    local_anchor = anchor.astimezone(zone)
    local_after = after.astimezone(zone)
    if local_after < local_anchor:
        return _utc_iso(local_anchor)
    interval = timedelta(days=int(safe["every_days"]))
    windows = max(0, math.floor((local_after - local_anchor) / interval)) + 1
    candidate = local_anchor + windows * interval
    while candidate <= local_after:
        windows += 1
        candidate = local_anchor + windows * interval
    return _utc_iso(candidate)


def _elapsed_cadence_windows(
    cadence: dict[str, Any], due_at: datetime, current_time: datetime
) -> int:
    safe = _sanitize_cadence(cadence)
    zone = ZoneInfo(str(safe["timezone"]))
    local_due = due_at.astimezone(zone)
    local_now = current_time.astimezone(zone)
    if local_now < local_due:
        return 0
    interval = timedelta(days=int(safe["every_days"]))
    windows = max(0, math.floor((local_now - local_due) / interval))
    while local_due + (windows + 1) * interval <= local_now:
        windows += 1
    while windows > 0 and local_due + windows * interval > local_now:
        windows -= 1
    return windows


def finish_run(
    project_root: Path,
    run_id: str,
    *,
    expected_run_revision: int,
    expected_subscription_revision: int,
    state: str,
    stop: dict[str, Any],
    outputs: dict[str, Any] | None = None,
    review_outcomes: list[dict[str, Any]] | None = None,
    now: datetime | str | None = None,
) -> Path:
    if state not in TERMINAL_RUN_STATES:
        raise SystemExit("Research monitor terminal state must be completed or cancelled.")
    changed_time = _now(now)
    changed_at = _utc_iso(changed_time)
    safe_stop = _sanitize_stop(stop, state=state)
    initial_run = load_run(project_root, run_id)
    task_binding = monitor_task_binding(initial_run)
    safe_outputs = _sanitize_outputs(
        project_root,
        outputs,
        expected_monitor_binding=task_binding,
    )
    safe_outcomes = _sanitize_review_outcomes(project_root, review_outcomes)
    _validate_outcome_links(safe_outputs, safe_outcomes)
    subscription_id = _safe_id(initial_run.get("subscription_id"), field="subscription id")
    receipt_file = run_path(project_root, run_id)
    subscription_file = subscription_path(project_root, subscription_id)
    initial_subscription = load_subscription(project_root, subscription_id)
    reporting_paths = (
        _program_reporting_paths(project_root, initial_subscription.get("program_ids", []))
        if state == "completed"
        else []
    )

    def preflight() -> None:
        current_run = load_run(project_root, run_id)
        current_task_binding = monitor_task_binding(current_run)
        if current_task_binding != task_binding:
            raise SystemExit("Research monitor frozen task binding changed during completion.")
        checked_outputs = _sanitize_outputs(
            project_root,
            safe_outputs,
            expected_monitor_binding=current_task_binding,
        )
        checked_outcomes = _sanitize_review_outcomes(project_root, safe_outcomes)
        _validate_outcome_links(checked_outputs, checked_outcomes)
        current_subscription = load_subscription(project_root, subscription_id)
        if state == "completed":
            current_reporting_paths = _program_reporting_paths(
                project_root,
                current_subscription.get("program_ids", []),
            )
            if current_reporting_paths != reporting_paths:
                raise SystemExit("Research monitor program reporting targets changed during completion.")
        _expected_revision(current_run, expected_run_revision, subject="run")
        _expected_revision(
            current_subscription,
            expected_subscription_revision,
            subject="subscription",
        )
        prior_state = str(current_run.get("state") or "")
        if state not in RUN_TRANSITIONS.get(prior_state, set()):
            raise SystemExit(f"Research monitor run cannot transition from {prior_state} to {state}.")
        if current_subscription.get("active_run_id") != run_id:
            raise SystemExit("Research monitor subscription does not own this active run.")
        if str(current_run.get("subscription_id") or "") != subscription_id:
            raise SystemExit("Research monitor run changed its subscription identity.")
        frozen = current_run.get("frozen_subscription")
        if not isinstance(frozen, dict) or frozen.get("scope_digest") != value_digest(
            frozen.get("scope_snapshot") or {}
        ):
            raise SystemExit("Research monitor frozen run scope is invalid.")
        for field in (
            "kind",
            "target",
            "scope_snapshot",
            "scope_digest",
            "budget",
            "cadence",
            "preference_binding",
        ):
            if current_subscription.get(field) != frozen.get(field):
                raise SystemExit(
                    "Research monitor subscription changed after this run was frozen."
                )
        if current_subscription.get("next_due_at") != current_run.get("scheduled_for"):
            raise SystemExit("Research monitor subscription due window changed during its run.")
        if state == "completed" and safe_stop["reason"] != "user_stop":
            _validate_completion_outputs(current_run, checked_outputs)

    with mutation_transaction(
        project_root,
        "research-monitor:finish-run",
        [receipt_file, subscription_file, *reporting_paths],
        preflight=preflight,
    ):
        current_run = load_run(project_root, run_id)
        current_subscription = load_subscription(project_root, subscription_id)
        current_run.setdefault("history", []).append(
            _history_snapshot(current_run, at=changed_at, action=f"state->{state}")
        )
        current_run["state"] = state
        current_run["stop"] = safe_stop
        current_run["outputs"] = safe_outputs
        current_run["review_outcomes"] = safe_outcomes
        current_run["completed_at"] = changed_at
        current_run["updated_at"] = changed_at
        current_run["revision"] = int(current_run["revision"]) + 1
        current_run["content_digest"] = _run_content_digest(current_run)

        current_subscription.setdefault("history", []).append(
            _history_snapshot(current_subscription, at=changed_at, action=f"run-finished:{run_id}")
        )
        current_subscription["active_run_id"] = ""
        if state == "completed":
            current_subscription["last_completed_run_id"] = run_id
        if current_subscription.get("status") != "completed":
            current_subscription["next_due_at"] = _next_due_after(
                current_run["frozen_subscription"]["cadence"], changed_time
            )
        current_subscription["updated_at"] = changed_at
        current_subscription["revision"] = int(current_subscription["revision"]) + 1
        write_yaml_if_changed(receipt_file, current_run)
        write_yaml_if_changed(subscription_file, current_subscription)
        if state == "completed":
            _append_completion_events_unlocked(
                project_root,
                subscription=current_subscription,
                run=current_run,
                completed_at=changed_at,
            )
    return receipt_file


def unresolved_monitor_outcomes(project_root: Path) -> list[dict[str, Any]]:
    """Return completed outcomes that still require an Agent or user disposition.

    This is a pure read model.  Legacy receipts without the R7 disposition
    object are surfaced as unresolved without mutating their bytes.
    """
    unresolved: list[dict[str, Any]] = []
    for path in _iter_documents(runs_root(project_root), label="runs"):
        run = load_run(project_root, path.stem)
        if str(run.get("state") or "") != "completed":
            continue
        subscription_id = str(run.get("subscription_id") or "")
        subscription = load_subscription(project_root, subscription_id)
        outcomes = _sanitize_review_outcomes(
            project_root,
            run.get("review_outcomes"),
            add_default_disposition=True,
        )
        for outcome in outcomes:
            disposition = outcome.get("disposition")
            disposition = disposition if isinstance(disposition, dict) else {}
            if str(disposition.get("state") or "unresolved") != "unresolved":
                continue
            binding = {
                "run_id": str(run.get("id") or ""),
                "run_revision": int(run.get("revision") or 0),
                "run_content_digest": str(run.get("content_digest") or ""),
                "outcome_id": str(outcome.get("outcome_id") or ""),
                "classification": str(outcome.get("classification") or ""),
                "subject_ref": str(outcome.get("subject_ref") or ""),
                "references": deepcopy(outcome.get("references") or []),
            }
            unresolved.append(
                {
                    **binding,
                    "outcome_binding_digest": value_digest(binding),
                    "subscription_id": subscription_id,
                    "subscription_title": str(subscription.get("title") or subscription_id),
                    "program_ids": list(subscription.get("program_ids") or []),
                    "rationale": str(outcome.get("rationale") or ""),
                    "disposition_state": "unresolved",
                }
            )
    return sorted(
        unresolved,
        key=lambda item: (
            str(item.get("run_id") or ""),
            str(item.get("outcome_id") or ""),
        ),
    )


def set_outcome_disposition(
    project_root: Path,
    run_id: str,
    outcome_id: str,
    *,
    expected_run_revision: int,
    expected_run_content_digest: str,
    state: str,
    actor: str,
    reason: str,
    target_ref: str = "",
    user_authorization: str = "",
    authorization_source: str = "",
    now: datetime | str | None = None,
) -> Path:
    """Resolve one completed monitor outcome with revision/content CAS."""
    if state not in OUTCOME_FINAL_DISPOSITIONS:
        raise SystemExit("Research monitor outcome disposition must be terminal.")
    safe_run_id = _safe_id(run_id, field="run id")
    safe_outcome_id = _safe_id(outcome_id, field="outcome id")
    changed_at = _utc_iso(_now(now))
    candidate_disposition = {
        "state": state,
        "actor": actor,
        "at": changed_at,
        "reason": reason,
        "target_ref": target_ref,
        "user_authorization": user_authorization,
        "authorization_source": authorization_source,
    }
    receipt_file = run_path(project_root, safe_run_id)

    def checked_document() -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        current = load_run(project_root, safe_run_id)
        _expected_revision(current, expected_run_revision, subject="run")
        if str(current.get("content_digest") or "") != str(expected_run_content_digest or ""):
            raise SystemExit("Research monitor run changed after the outcome was displayed.")
        if str(current.get("state") or "") != "completed":
            raise SystemExit("Only a completed research monitor run can resolve outcomes.")
        outcomes = _sanitize_review_outcomes(
            project_root,
            current.get("review_outcomes"),
            add_default_disposition=True,
        )
        matches = [index for index, item in enumerate(outcomes) if item.get("outcome_id") == safe_outcome_id]
        if len(matches) != 1:
            raise SystemExit("Research monitor outcome is unavailable or ambiguous.")
        index = matches[0]
        disposition = outcomes[index].get("disposition")
        if not isinstance(disposition, dict) or disposition.get("state") != "unresolved":
            raise SystemExit("Research monitor outcome was already resolved.")
        outcomes[index]["disposition"] = _sanitize_outcome_disposition(
            candidate_disposition,
            classification=str(outcomes[index].get("classification") or ""),
        )
        if state == "materialized":
            _materialized_unit_snapshot(project_root, str(target_ref or ""))
        if state == "sent_to_review":
            from .judgements import discover_pending_judgements

            target_kind, separator, target_id = str(target_ref or "").partition(":")
            matching_cards = [
                card
                for card in discover_pending_judgements(project_root)
                if str(card.get("subject", {}).get("kind") or "") == target_kind
                and str(card.get("subject", {}).get("id") or "") == target_id
            ]
            if not separator or len(matching_cards) != 1:
                raise SystemExit("Review-routed monitor outcome target is not uniquely ready.")
        return current, outcomes, index

    def preflight() -> None:
        checked_document()

    with mutation_transaction(
        project_root,
        "research-monitor:set-outcome-disposition",
        [receipt_file],
        preflight=preflight,
    ):
        current, outcomes, _index = checked_document()
        current.setdefault("history", []).append(
            _history_snapshot(
                current,
                at=changed_at,
                action=f"outcome:{safe_outcome_id}->{state}",
            )
        )
        current["review_outcomes"] = outcomes
        current["updated_at"] = changed_at
        current["revision"] = int(current["revision"]) + 1
        current["content_digest"] = _run_content_digest(current)
        write_yaml_if_changed(receipt_file, current)
    return receipt_file


__all__ = [
    "active_monitor_runs",
    "OUTCOME_DISPOSITION_STATES",
    "RUN_STATES",
    "SUBSCRIPTION_KINDS",
    "SUBSCRIPTION_STATUSES",
    "build_subscription_id",
    "create_due_run",
    "create_subscription",
    "due_subscriptions",
    "finish_run",
    "load_run",
    "load_subscription",
    "monitor_task_binding",
    "monitor_subscription_preference_context",
    "monitoring_root",
    "run_path",
    "runs_root",
    "set_subscription_status",
    "set_outcome_disposition",
    "subscription_path",
    "unresolved_monitor_outcomes",
    "subscriptions_root",
    "transition_run",
    "value_digest",
]

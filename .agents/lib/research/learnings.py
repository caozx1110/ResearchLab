"""Lightweight learnings memory for research workflows."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .confirm import is_ai_signer, require_confirmation_provenance, require_user_authorization
from .core import kb_root, load_runtime_preferences, runtime_preferences_path
from .journal import current_operation_id, load_op, mutation_transaction, target_digest
from .records import snapshot_project_file
from .yaml_io import StrictYamlError, load_yaml, load_yaml_bytes_strict, write_yaml_if_changed

CATEGORIES = {"skill-defect", "user-preference", "recurring-issue"}
SOURCES = {"agent", "user"}
STATUSES = {"pending", "confirmed", "dismissed"}
REVIEW_STATUSES = {"confirmed", "dismissed"}
RECALL_KINDS = {"prefs", "gotchas", "defects", "all"}
PREFERENCE_OBSERVATION_SCHEMA = "preference-observation/v1"
PREFERENCE_SUBJECT_KIND = "user_preference"
PREFERENCE_SCOPE_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
PREFERENCE_TEXT_LIMIT = 1000


def learnings_path(project_root: Path) -> Path:
    return kb_root(project_root) / "memory" / "learnings.yaml"


def load_learnings(project_root: Path) -> list[dict[str, Any]]:
    payload = load_yaml(learnings_path(project_root), default=[])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def write_learnings(project_root: Path, entries: list[dict[str, Any]]) -> Path:
    path = learnings_path(project_root)
    with mutation_transaction(project_root, "write-learnings", [path]):
        write_yaml_if_changed(path, entries)
    return path


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _normalize_text(value: str) -> str:
    chars = [ch.lower() if ch.isalnum() else " " for ch in value]
    return " ".join("".join(chars).split())


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _preference_operations(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return sorted({str(item).strip().casefold() for item in values if str(item).strip()})


def preference_learning_payload(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the exact observation bytes represented canonically, excluding its decision."""
    return {
        "id": str(entry.get("id") or ""),
        "created_at": str(entry.get("created_at") or ""),
        "category": str(entry.get("category") or ""),
        "text": str(entry.get("text") or ""),
        "observation": str(entry.get("observation") or ""),
        "source": str(entry.get("source") or ""),
        "skill": str(entry.get("skill") or ""),
        "operations": _preference_operations(entry.get("operations")),
        "context": str(entry.get("context") or ""),
        "occurrences": _entry_occurrences(entry),
        "last_seen_at": str(entry.get("last_seen_at") or ""),
    }


def preference_learning_digest(entry: dict[str, Any]) -> str:
    return _canonical_digest(preference_learning_payload(entry))


def preference_scope_digest(entry: dict[str, Any]) -> str:
    return _canonical_digest(
        {
            "skill": str(entry.get("skill") or "").strip().casefold(),
            "operations": _preference_operations(entry.get("operations")),
        }
    )


def preference_confirmation_digest(receipt: object) -> str:
    return _canonical_digest(receipt if isinstance(receipt, dict) else {})


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(sequence, overlap)


def _next_learning_id(entries: list[dict[str, Any]], now: datetime) -> str:
    date = now.strftime("%Y%m%d")
    pattern = re.compile(rf"^lrn-{date}-(\d{{3}})$")
    existing = []
    for entry in entries:
        match = pattern.match(str(entry.get("id") or ""))
        if match:
            existing.append(int(match.group(1)))
    return f"lrn-{date}-{max(existing, default=0) + 1:03d}"


def _validate_enum(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _entry_occurrences(entry: dict[str, Any]) -> int:
    try:
        return max(1, int(entry.get("occurrences") or 1))
    except (TypeError, ValueError):
        return 1


def log_learning(
    project_root: Path,
    *,
    category: str,
    text: str,
    source: str = "agent",
    skill: str = "",
    operation: str = "",
    observation: str = "",
    context: str = "",
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    category = _validate_enum(category, CATEGORIES, "category")
    source = _validate_enum(source, SOURCES, "source")
    text = str(text or "").strip()
    if not text:
        raise ValueError("text must not be empty")
    skill = str(skill or "").strip().casefold()
    operation = str(operation or "").strip().casefold()
    observation = str(observation or "").strip()
    if category == "user-preference" and any(not value for value in (skill, operation, observation)):
        raise ValueError(
            "user-preference observations require skill, operation, and verbatim observation"
        )
    if category == "user-preference" and (
        PREFERENCE_SCOPE_TOKEN_RE.fullmatch(skill) is None
        or PREFERENCE_SCOPE_TOKEN_RE.fullmatch(operation) is None
        or len(text) > PREFERENCE_TEXT_LIMIT
        or len(observation) > PREFERENCE_TEXT_LIMIT
    ):
        raise ValueError("user-preference observation or scope is invalid")

    timestamp = _now(now)
    timestamp_text = timestamp.isoformat()
    path = learnings_path(project_root)
    with mutation_transaction(project_root, "log-learning", [path]):
        entries = load_learnings(project_root)
        best_match: dict[str, Any] | None = None
        best_score = 0.0
        for entry in entries:
            if str(entry.get("category") or "") != category:
                continue
            if category == "user-preference" and str(entry.get("status") or "") != "pending":
                continue
            if category == "user-preference" and str(entry.get("skill") or "").strip().casefold() != skill:
                continue
            score = _text_similarity(text, str(entry.get("text") or ""))
            if score > best_score and score >= 0.86:
                best_match = entry
                best_score = score

        if best_match is not None:
            best_match["occurrences"] = _entry_occurrences(best_match) + 1
            best_match["last_seen_at"] = timestamp_text
            if category == "user-preference":
                best_match["skill"] = skill
                best_match["operations"] = sorted(
                    set(_preference_operations(best_match.get("operations"))) | {operation}
                )
                best_match["observation"] = observation
            write_learnings(project_root, entries)
            return best_match, False

        entry = {
            "id": _next_learning_id(entries, timestamp),
            "created_at": timestamp_text,
            "category": category,
            "text": text,
            "source": source,
            "skill": skill,
            "operations": [operation] if operation else [],
            "observation": observation,
            "context": str(context or "").strip(),
            "status": "pending",
            "occurrences": 1,
            "last_seen_at": timestamp_text,
        }
        entries.append(entry)
        write_learnings(project_root, entries)
        return entry, True


def find_learning(project_root: Path, learning_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries = load_learnings(project_root)
    for entry in entries:
        if str(entry.get("id") or "") == learning_id:
            return entries, entry
    raise ValueError(f"learning not found: {learning_id}")


def _strict_learning_snapshot(
    project_root: Path,
) -> tuple[object, list[dict[str, Any]]] | None:
    relative = learnings_path(project_root).relative_to(project_root)
    snapshot = snapshot_project_file(project_root, relative, max_bytes=8 * 1024 * 1024)
    if snapshot is None:
        return None
    try:
        payload = load_yaml_bytes_strict(snapshot.raw_bytes)
    except (RuntimeError, StrictYamlError):
        return None
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        return None
    if not snapshot.is_current():
        return None
    return snapshot, [dict(item) for item in payload]


def preference_snapshot_binding(
    entry: dict[str, Any],
    *,
    container_digest: str,
) -> dict[str, Any]:
    learning_id = str(entry.get("id") or "").strip()
    observation = str(entry.get("observation") or "").strip()
    digest = preference_learning_digest(entry)
    return {
        "subject": {
            "kind": PREFERENCE_SUBJECT_KIND,
            "id": learning_id,
            "owner": "skill-evolution-advisor",
            "path": "kb/memory/learnings.yaml",
        },
        "confirmation_status": "pending_user_confirmation",
        "content_digest": digest,
        "verification": {
            "schema": PREFERENCE_OBSERVATION_SCHEMA,
            "learning_digest": digest,
            "observation_digest": _canonical_digest(observation),
            "scope_digest": preference_scope_digest(entry),
            "container_digest": container_digest,
        },
    }


def _valid_pending_preference(entry: dict[str, Any]) -> bool:
    learning_id = str(entry.get("id") or "").strip()
    text = str(entry.get("text") or "").strip()
    observation = str(entry.get("observation") or "").strip()
    skill = str(entry.get("skill") or "").strip().casefold()
    operations = _preference_operations(entry.get("operations"))
    return bool(
        re.fullmatch(r"lrn-[0-9]{8}-[0-9]{3}", learning_id)
        and str(entry.get("category") or "") == "user-preference"
        and str(entry.get("status") or "") == "pending"
        and text
        and len(text) <= PREFERENCE_TEXT_LIMIT
        and observation
        and len(observation) <= PREFERENCE_TEXT_LIMIT
        and PREFERENCE_SCOPE_TOKEN_RE.fullmatch(skill)
        and operations
        and all(PREFERENCE_SCOPE_TOKEN_RE.fullmatch(item) for item in operations)
    )


def discover_pending_preference_review_cards(
    project_root: Path,
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Pure-read projection of at most two grounded preference observations."""
    captured = _strict_learning_snapshot(project_root)
    if captured is None:
        return []
    snapshot, entries = captured
    container_digest = target_digest(project_root, "memory/learnings.yaml")
    if not container_digest or not snapshot.is_current():
        return []
    counts: dict[str, int] = {}
    for entry in entries:
        learning_id = str(entry.get("id") or "")
        counts[learning_id] = counts.get(learning_id, 0) + 1
    cards: list[dict[str, Any]] = []
    for entry in entries:
        learning_id = str(entry.get("id") or "")
        if counts.get(learning_id) != 1 or not _valid_pending_preference(entry):
            continue
        observation = str(entry.get("observation") or "").strip()
        operations = _preference_operations(entry.get("operations"))
        binding = preference_snapshot_binding(entry, container_digest=container_digest)
        cards.append(
            {
                "subject": dict(binding["subject"]),
                "priority": "normal",
                "updated_at": str(entry.get("last_seen_at") or entry.get("created_at") or ""),
                "substance": {
                    "preference": {
                        "text": str(entry.get("text") or "").strip(),
                        "skill": str(entry.get("skill") or "").strip().casefold(),
                        "operations": operations,
                        "observation": observation,
                    }
                },
                "claims": [
                    {
                        "id": f"claim-{learning_id}-preference",
                        "text": str(entry.get("text") or "").strip(),
                        "claim_type": "user_opinion",
                        "confirmation_status": "pending_user_confirmation",
                        "evidence_refs": [
                            {
                                "source_unit_id": learning_id,
                                "artifact": "learnings.yaml",
                                "locator": f"observation={learning_id}",
                                "quote": observation,
                            }
                        ],
                    }
                ],
                "verification": dict(binding["verification"]),
                "confirm_route": {
                    "owner": "skill-evolution-advisor",
                    "action": "confirm-preference",
                    "id": learning_id,
                },
                "reject_route": {
                    "owner": "skill-evolution-advisor",
                    "action": "dismiss-preference",
                    "id": learning_id,
                },
                "snapshot_binding": binding,
            }
        )
    if not snapshot.is_current():
        return []
    return sorted(cards, key=lambda item: (str(item.get("updated_at") or ""), str(item["subject"]["id"])))[: max(0, min(int(limit), 2))]


def current_preference_review_card(
    project_root: Path,
    learning_id: str,
) -> dict[str, Any]:
    matches = [
        card
        for card in discover_pending_preference_review_cards(project_root, limit=2)
        if str(card.get("subject", {}).get("id") or "") == learning_id
    ]
    if len(matches) != 1:
        raise ValueError("preference observation is no longer uniquely ready")
    return matches[0]


def review_learning(project_root: Path, *, learning_id: str, status: str) -> dict[str, Any]:
    status = _validate_enum(status, REVIEW_STATUSES, "status")
    _existing_entries, existing = find_learning(project_root, learning_id)
    if str(existing.get("category") or "") == "user-preference":
        raise ValueError("user preferences must be decided through the unified kb review snapshot")
    path = learnings_path(project_root)
    with mutation_transaction(project_root, "review-learning", [path]):
        entries, entry = find_learning(project_root, learning_id)
        if str(entry.get("category") or "") == "user-preference":
            raise ValueError("user preferences must be decided through the unified kb review snapshot")
        entry["status"] = status
        write_learnings(project_root, entries)
        return entry


def _learned_preference_item(entry: dict[str, Any]) -> dict[str, Any]:
    receipt = entry.get("confirmation")
    receipt = dict(receipt) if isinstance(receipt, dict) else {}
    return {
        "id": str(entry.get("id") or ""),
        "text": str(entry.get("text") or ""),
        "source": str(entry.get("source") or ""),
        "skill": str(entry.get("skill") or ""),
        "operations": _preference_operations(entry.get("operations")),
        "context": str(entry.get("context") or ""),
        "learning_binding": {
            "learning_digest": preference_learning_digest(entry),
            "observation_digest": _canonical_digest(str(entry.get("observation") or "")),
            "scope_digest": preference_scope_digest(entry),
            "receipt_digest": preference_confirmation_digest(receipt),
        },
    }


def promote_learning(project_root: Path, *, learning_id: str) -> tuple[dict[str, Any], Path]:
    del project_root, learning_id
    raise ValueError("direct preference promotion is retired; use the unified kb review snapshot")


def _preference_receipt_is_current(entry: dict[str, Any]) -> bool:
    receipt = entry.get("confirmation")
    if not isinstance(receipt, dict):
        return False
    subject = receipt.get("subject")
    if not isinstance(subject, dict):
        return False
    return bool(
        receipt.get("decision") == "confirmed"
        and str(subject.get("kind") or "") == PREFERENCE_SUBJECT_KIND
        and str(subject.get("id") or "") == str(entry.get("id") or "")
        and str(receipt.get("content_digest") or "") == preference_learning_digest(entry)
        and str(receipt.get("observation_digest") or "")
        == _canonical_digest(str(entry.get("observation") or ""))
        and str(receipt.get("scope_digest") or "") == preference_scope_digest(entry)
        and str(receipt.get("authorization_source") or "") == "user_message"
        and str(receipt.get("user_authorization") or "").strip()
        and str(receipt.get("by") or "").strip()
        and not is_ai_signer(str(receipt.get("by") or ""))
        and isinstance(receipt.get("evidence"), list)
        and bool([item for item in receipt.get("evidence", []) if str(item).strip()])
    )


def learned_preference_item_is_current(
    entry: dict[str, Any],
    runtime_item: dict[str, Any],
) -> bool:
    if (
        str(entry.get("category") or "") != "user-preference"
        or str(entry.get("status") or "") != "confirmed"
        or not _preference_receipt_is_current(entry)
    ):
        return False
    expected = _learned_preference_item(entry)
    return runtime_item == expected


def current_learned_preference_items(
    project_root: Path,
    runtime_items: object,
) -> list[dict[str, Any]]:
    """Fail-closed current view; legacy or forged runtime items stay historical only."""
    if not isinstance(runtime_items, list):
        return []
    captured = _strict_learning_snapshot(project_root)
    if captured is None:
        return []
    snapshot, entries = captured
    counts: dict[str, int] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        learning_id = str(entry.get("id") or "")
        counts[learning_id] = counts.get(learning_id, 0) + 1
        by_id[learning_id] = entry
    current: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in runtime_items:
        if not isinstance(raw, dict):
            continue
        learning_id = str(raw.get("id") or "")
        entry = by_id.get(learning_id)
        if (
            not learning_id
            or learning_id in seen
            or counts.get(learning_id) != 1
            or entry is None
            or not learned_preference_item_is_current(entry, raw)
        ):
            continue
        seen.add(learning_id)
        current.append(dict(raw))
    if not snapshot.is_current():
        return []
    return sorted(current, key=lambda item: str(item.get("id") or ""))


def _preference_entry_for_bound_item(
    project_root: Path,
    item: dict[str, Any],
    *,
    allow_container_drift: bool = False,
    require_runtime_target: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    subject = item.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    learning_id = str(subject.get("id") or "")
    card = current_preference_review_card(project_root, learning_id)
    expected_routes = {
        "subject": card.get("subject"),
        "confirm_route": card.get("confirm_route"),
        "reject_route": card.get("reject_route"),
        "snapshot_binding": card.get("snapshot_binding"),
    }
    actual_routes = {
        "subject": item.get("subject"),
        "confirm_route": item.get("confirm_route"),
        "reject_route": item.get("reject_route"),
        "snapshot_binding": item.get("snapshot_binding"),
    }
    if allow_container_drift:
        operation_id = current_operation_id(project_root)
        operation = load_op(project_root, operation_id) if operation_id else {}
        if (
            str(operation.get("op_type") or "")
            not in {"kb-cli:dialogue-review-batch", "kb-cli:obsidian-review-batch"}
            or "memory/learnings.yaml" not in set(operation.get("target_paths") or [])
            or (
                require_runtime_target
                and "config/runtime-preferences.yaml" not in set(operation.get("target_paths") or [])
            )
        ):
            raise ValueError("preference review apply requires the unified review coordinator")
        actual_binding = actual_routes.get("snapshot_binding")
        actual_binding = dict(actual_binding) if isinstance(actual_binding, dict) else {}
        actual_verification = actual_binding.get("verification")
        actual_verification = (
            dict(actual_verification) if isinstance(actual_verification, dict) else {}
        )
        container_digest = str(actual_verification.get("container_digest") or "")
        if (
            not container_digest
            or str(operation.get("before_digests", {}).get("memory/learnings.yaml") or "")
            != container_digest
        ):
            raise ValueError("preference review container binding is stale")
        expected_binding = expected_routes.get("snapshot_binding")
        expected_binding = dict(expected_binding) if isinstance(expected_binding, dict) else {}
        expected_verification = expected_binding.get("verification")
        expected_verification = (
            dict(expected_verification) if isinstance(expected_verification, dict) else {}
        )
        expected_verification["container_digest"] = container_digest
        expected_binding["verification"] = expected_verification
        expected_routes["snapshot_binding"] = expected_binding
    if actual_routes != expected_routes:
        raise ValueError("preference review snapshot is stale")
    entries = load_learnings(project_root)
    matches = [entry for entry in entries if str(entry.get("id") or "") == learning_id]
    if len(matches) != 1 or not _valid_pending_preference(matches[0]):
        raise ValueError("preference observation is no longer uniquely ready")
    return entries, matches[0]


def prepare_preference_review_decision(
    project_root: Path,
    item: dict[str, Any],
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
) -> dict[str, Any]:
    _entries, entry = _preference_entry_for_bound_item(project_root, item)
    if decision == "confirm":
        require_confirmation_provenance(
            confirmed_by=actor,
            evidence=evidence,
            project_root=project_root,
        )
    if decision not in {"confirm", "reject"}:
        raise ValueError("preference review decision is invalid")
    require_user_authorization(
        user_authorization=user_authorization,
        authorization_source=authorization_source,
    )
    return {
        "owner": "skill-evolution-advisor",
        "decision": decision,
        "learning_id": str(entry.get("id") or ""),
        "target_paths": [
            learnings_path(project_root),
            *([runtime_preferences_path(project_root)] if decision == "confirm" else []),
        ],
    }


def apply_preference_review_decision(
    project_root: Path,
    item: dict[str, Any],
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
) -> list[Path]:
    if not current_operation_id(project_root):
        raise ValueError("preference review apply requires the unified root transaction")
    if decision == "confirm":
        require_confirmation_provenance(
            confirmed_by=actor,
            evidence=evidence,
            project_root=project_root,
        )
    if decision not in {"confirm", "reject"}:
        raise ValueError("preference review decision is invalid")
    require_user_authorization(
        user_authorization=user_authorization,
        authorization_source=authorization_source,
    )
    entries, entry = _preference_entry_for_bound_item(
        project_root,
        item,
        allow_container_drift=True,
        require_runtime_target=decision == "confirm",
    )
    learning_id = str(entry.get("id") or "")
    if decision == "confirm":
        preferences = load_runtime_preferences(project_root)
        learned = preferences.get("learned_preferences")
        learned = dict(learned) if isinstance(learned, dict) else {}
        items = [dict(value) for value in learned.get("items", []) if isinstance(value, dict)]
        items = [value for value in items if str(value.get("id") or "") != learning_id]
        confirmed_actor, evidence_items = require_confirmation_provenance(
            confirmed_by=actor,
            evidence=evidence,
            project_root=project_root,
        )
        authorization, source = require_user_authorization(
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
        digest = preference_learning_digest(entry)
        receipt = {
            "by": confirmed_actor,
            "at": _now().isoformat(),
            "evidence": evidence_items,
            "method": "kb review",
            "decision": "confirmed",
            "subject": {"kind": PREFERENCE_SUBJECT_KIND, "id": learning_id},
            "content_digest": digest,
            "observation_digest": _canonical_digest(str(entry.get("observation") or "")),
            "scope_digest": preference_scope_digest(entry),
            "prior_information_types": ["user_opinion"],
            "user_authorization": authorization,
            "authorization_source": source,
        }
        entry["status"] = "confirmed"
        entry["confirmation"] = receipt
        items.append(_learned_preference_item(entry))
        learned["items"] = sorted(items, key=lambda value: str(value.get("id") or ""))
        preferences["learned_preferences"] = learned
        write_yaml_if_changed(learnings_path(project_root), entries)
        write_yaml_if_changed(runtime_preferences_path(project_root), preferences)
        return [learnings_path(project_root), runtime_preferences_path(project_root)]
    else:
        require_user_authorization(
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
        entry["status"] = "dismissed"
        entry.pop("confirmation", None)
    write_yaml_if_changed(learnings_path(project_root), entries)
    return [learnings_path(project_root)]


def _confirmed_entries(entries: list[dict[str, Any]], category: str, limit: int) -> list[dict[str, Any]]:
    selected = [
        entry
        for entry in entries
        if str(entry.get("category") or "") == category and str(entry.get("status") or "") == "confirmed"
        and (category != "user-preference" or _preference_receipt_is_current(entry))
    ]
    return _sort_entries(selected)[:limit]


def _pending_defects(entries: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    selected = [
        entry
        for entry in entries
        if str(entry.get("category") or "") == "skill-defect" and str(entry.get("status") or "") == "pending"
    ]
    sorted_entries = _sort_entries(selected)
    return sorted_entries if limit is None else sorted_entries[:limit]


def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda entry: (_entry_occurrences(entry), str(entry.get("last_seen_at") or "")),
        reverse=True,
    )


def _format_entry(entry: dict[str, Any]) -> str:
    occurrences = _entry_occurrences(entry)
    suffix = f" (x{occurrences})" if occurrences > 1 else ""
    skill = str(entry.get("skill") or "").strip()
    skill_suffix = f" [skill: {skill}]" if skill else ""
    return f"- `{entry.get('id')}` {entry.get('text', '')}{suffix}{skill_suffix}"


def _append_entry_section(lines: list[str], title: str, entries: list[dict[str, Any]]) -> None:
    lines.extend([title, ""])
    if not entries:
        lines.append("- none")
    else:
        lines.extend(_format_entry(entry) for entry in entries)


def render_recall_digest(entries: list[dict[str, Any]], *, kind: str = "all", limit: int = 5) -> str:
    kind = _validate_enum(kind, RECALL_KINDS, "kind")
    limit = max(1, int(limit or 5))
    lines = ["## Recall Digest", ""]

    if kind in {"prefs", "all"}:
        _append_entry_section(lines, "Known habits", _confirmed_entries(entries, "user-preference", limit))
        lines.append("")
    if kind in {"gotchas", "all"}:
        _append_entry_section(lines, "Known gotchas", _confirmed_entries(entries, "recurring-issue", limit))
        lines.append("")
    if kind == "defects":
        _append_entry_section(lines, "Pending skill defects", _pending_defects(entries, limit))
    elif kind == "all":
        lines.append(f"Pending skill defects: {len(_pending_defects(entries))}")

    return "\n".join(lines).strip() + "\n"

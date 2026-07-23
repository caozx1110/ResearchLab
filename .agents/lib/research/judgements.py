"""Shared discovery and binding contract for cross-owner judgement artifacts.

Owner files remain authoritative for their domain-specific fields.  This module
only recognizes the governance envelope shared by every judgement:
canonical ``payload.claims``, a current verification receipt, and (after human
approval) a current ConfirmationReceipt.  Discovery is deliberately
fail-closed: incomplete, stale, rejected, or already-confirmed artifacts never
become public review cards.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .common import load_yaml
from .confirm import has_complete_confirmation_receipt
from .evidence import (
    JUDGEMENT_CLAIM_TYPES,
    UNCONFIRMABLE_CLAIM_TYPES,
    confirmation_claim_ids,
    confirmation_claims,
    confirmation_content_digest,
    validate_claims,
    verification_receipt_violations,
)


UNIT_OWNER_BY_KIND = {
    "paper": "paper-analyst",
    "repo": "repo-analyst",
    "dataset": "dataset-analyst",
    "blog": "blog-analyst",
    "idea": "idea-workbench",
    "experiment": "experiment-workbench",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_relative_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError("judgement artifact path escapes the project root") from exc


def _unit_path(root: Path, unit_id: str) -> Path | None:
    matches = list((root / "kb" / "units").glob(f"*/*/record.yaml"))
    for path in matches:
        if path.parent.name == unit_id:
            return path
    return None


def _source_roots(root: Path, record: dict[str, Any], artifact_path: Path) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    subject_id = _text(record.get("id"))
    subject_kind = _text(record.get("kind"))
    program_id = _text(record.get("program_id"))
    for claim in confirmation_claims(record):
        for ref in claim.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            source_id = _text(ref.get("source_unit_id"))
            if not source_id or source_id in roots:
                continue
            if source_id == subject_id and subject_kind in UNIT_OWNER_BY_KIND:
                roots[source_id] = artifact_path.parent
                continue
            if source_id.startswith("program:"):
                candidate_program = source_id.split(":", 1)[1]
                roots[source_id] = root / "kb" / "programs" / candidate_program
                continue
            source_path = _unit_path(root, source_id)
            if source_path is not None:
                roots[source_id] = source_path.parent
                continue
            if program_id and source_id == f"program:{program_id}":
                roots[source_id] = root / "kb" / "programs" / program_id
    return roots


def _verification_root(root: Path, record: dict[str, Any], artifact_path: Path) -> Path:
    program_id = _text(record.get("program_id"))
    if _text(record.get("kind")) == "program_decision" and program_id:
        return root / "kb" / "programs" / program_id
    return artifact_path.parent


def readiness_violations(root: Path, record: Any, artifact_path: Path) -> list[str]:
    """Return why a judgement must not appear in the human review inbox."""
    if not isinstance(record, dict):
        return ["judgement artifact must be a mapping"]
    if _text(record.get("confirmation_status")) != "pending_user_confirmation":
        return ["confirmation_status is not pending_user_confirmation"]
    claims = confirmation_claims(record)
    if not claims:
        return ["canonical payload.claims must be non-empty"]
    violations = validate_claims(claims)
    claim_types = {_text(claim.get("claim_type")) for claim in claims}
    if claim_types & UNCONFIRMABLE_CLAIM_TYPES:
        violations.append("canonical claims still contain unverified claim types")
    if not claim_types & JUDGEMENT_CLAIM_TYPES:
        violations.append("artifact has no judgement-class canonical claim")
    if any(_text(claim.get("confirmation_status")) != "pending_user_confirmation" for claim in claims):
        violations.append("canonical claim confirmation status is not pending_user_confirmation")
    verification_root = _verification_root(root, record, artifact_path)
    violations.extend(
        verification_receipt_violations(
            record,
            verification_root,
            source_roots=_source_roots(root, record, artifact_path),
        )
    )
    return violations


def _default_route(record: dict[str, Any], owner: str) -> dict[str, str]:
    subject_id = _text(record.get("id"))
    kind = _text(record.get("kind"))
    if kind == "program_decision":
        return {
            "owner": owner,
            "action": "confirm-decision",
            "program_id": _text(record.get("program_id")),
            "decision_id": subject_id,
        }
    if kind == "idea_discussion_conclusion":
        return {
            "owner": owner,
            "action": "confirm-discussion",
            "idea_id": _text(record.get("idea_id")),
            "subject_id": subject_id,
        }
    return {"owner": owner, "action": "confirm", "subject_id": subject_id}


def pending_judgement_card(
    root: Path,
    record: Any,
    *,
    owner: str,
    artifact_path: Path,
) -> dict[str, Any] | None:
    """Build one internal review card, or ``None`` unless it is truly ready."""
    if readiness_violations(root, record, artifact_path):
        return None
    assert isinstance(record, dict)
    route = record.get("review_route")
    if not isinstance(route, dict):
        route = _default_route(record, owner)
    return {
        "subject": {
            "kind": _text(record.get("kind")),
            "id": _text(record.get("id")),
            "owner": owner,
            "path": _safe_relative_path(root, artifact_path),
        },
        "claims": confirmation_claims(record),
        "verification": dict(record.get("payload", {}).get("verification", {})),
        "confirmation_status": "pending_user_confirmation",
        "priority": _text(record.get("priority")) or "normal",
        "updated_at": _text(record.get("updated_at") or record.get("timestamp")),
        "confirm_route": {str(key): _text(value) for key, value in route.items()},
    }


def _list_items(path: Path) -> Iterable[dict[str, Any]]:
    payload = load_yaml(path, default={})
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _candidate_artifacts(root: Path) -> Iterable[tuple[dict[str, Any], str, Path]]:
    for path in sorted((root / "kb" / "units").glob("*/*/record.yaml")):
        record = load_yaml(path, default={})
        if isinstance(record, dict):
            owner = UNIT_OWNER_BY_KIND.get(_text(record.get("kind")), _text(record.get("owner")) or "unknown")
            yield record, owner, path
    for path in sorted((root / "kb" / "programs").glob("*/workflow/decisions.yaml")):
        for item in _list_items(path):
            yield item, "research-orchestrator", path
    for path in sorted((root / "kb" / "units" / "ideas").glob("*/discussion-judgements.yaml")):
        for item in _list_items(path):
            yield item, "idea-workbench", path
    for path in sorted((root / "kb" / "programs").glob("*/design/*-repo-choice.yaml")):
        payload = load_yaml(path, default={})
        if isinstance(payload, dict):
            yield payload, _text(payload.get("owner")) or "method-designer", path


def discover_pending_judgements(root: str | Path) -> list[dict[str, Any]]:
    """Return all cross-owner ``ready_for_review`` cards in deterministic order."""
    project_root = Path(root).resolve()
    cards = [
        card
        for record, owner, path in _candidate_artifacts(project_root)
        if (card := pending_judgement_card(project_root, record, owner=owner, artifact_path=path)) is not None
    ]
    priority = {"critical": 4, "high": 3, "normal": 2, "low": 1}
    return sorted(
        cards,
        key=lambda card: (
            -priority.get(_text(card.get("priority")).casefold(), 2),
            _text(card.get("updated_at")),
            _text(card.get("subject", {}).get("id")),
        ),
    )


def confirmation_binding(record: dict[str, Any], *, owner: str = "", path: str = "") -> dict[str, Any]:
    """Build the event binding for a verified or confirmed judgement subject."""
    verification = record.get("payload", {}).get("verification", {})
    verification = verification if isinstance(verification, dict) else {}
    subject = {"kind": _text(record.get("kind")), "id": _text(record.get("id"))}
    if owner:
        subject["owner"] = owner
    if path:
        subject["path"] = path
    return {
        "subject": subject,
        "claim_ids": confirmation_claim_ids(record),
        "content_digest": confirmation_content_digest(record),
        "verification": {
            key: _text(verification.get(key))
            for key in ("verified_at", "claims_digest", "evidence_digest")
        },
    }


def load_bound_judgement(root: str | Path, subject: Any) -> tuple[dict[str, Any], Path]:
    """Resolve a report binding without trusting an escaping path from the event."""
    project_root = Path(root).resolve()
    if not isinstance(subject, dict):
        raise ValueError("confirmation subject must be a mapping")
    subject_id = _text(subject.get("id"))
    subject_kind = _text(subject.get("kind"))
    relative = _text(subject.get("path"))
    candidates: list[Path] = []
    if relative:
        candidate = (project_root / relative).resolve()
        _safe_relative_path(project_root, candidate)
        candidates.append(candidate)
    unit = _unit_path(project_root, subject_id)
    if unit is not None:
        candidates.append(unit)
    if subject_kind == "program_decision":
        candidates.extend((project_root / "kb" / "programs").glob("*/workflow/decisions.yaml"))
    if subject_kind == "idea_discussion_conclusion":
        candidates.extend((project_root / "kb" / "units" / "ideas").glob("*/discussion-judgements.yaml"))
    for path in candidates:
        payload = load_yaml(path, default={})
        records = payload.get("items") if isinstance(payload, dict) and isinstance(payload.get("items"), list) else [payload]
        for record in records:
            if not isinstance(record, dict):
                continue
            if _text(record.get("id")) == subject_id and _text(record.get("kind")) == subject_kind:
                return record, path
    raise ValueError(f"bound judgement not found: {subject_kind}:{subject_id}")


__all__ = [
    "confirmation_binding",
    "discover_pending_judgements",
    "load_bound_judgement",
    "pending_judgement_card",
    "readiness_violations",
]

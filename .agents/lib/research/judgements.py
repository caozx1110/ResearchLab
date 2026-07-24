"""Shared discovery and binding contract for cross-owner judgement artifacts.

Owner files remain authoritative for their domain-specific fields.  This module
only recognizes the governance envelope shared by every judgement:
canonical ``payload.claims``, a current verification receipt, and (after human
approval) a current ConfirmationReceipt.  Discovery is deliberately
fail-closed: incomplete, stale, rejected, or already-confirmed artifacts never
become public review cards.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import yaml

from .common import load_yaml, utc_now_iso
from .confirm import has_complete_confirmation_receipt
from .evidence import (
    CONFIRMABLE_CONTENT_FIELDS,
    CONFIRMABLE_CONTENT_SECTIONS,
    JUDGEMENT_CLAIM_TYPES,
    UNCONFIRMABLE_CLAIM_TYPES,
    confirmation_claim_ids,
    confirmation_claims,
    confirmation_content_digest,
    record_external_source_contract,
    validate_claims,
    verification_receipt_violations,
)
from .records import (
    trusted_claim_source_roots,
    trusted_program_root,
    trusted_project_path,
    trusted_unit_record_path,
)
from .surveys import (
    survey_artifact_path,
    survey_content_digest,
    survey_lifecycle_violations,
    survey_source_roots,
)


UNIT_OWNER_BY_KIND = {
    "paper": "paper-analyst",
    "repo": "repo-analyst",
    "dataset": "dataset-analyst",
    "blog": "blog-analyst",
    "idea": "idea-workbench",
    "experiment": "experiment-workbench",
}
UNIT_DIR_BY_KIND = {
    "paper": "papers",
    "repo": "repos",
    "dataset": "datasets",
    "blog": "blogs",
    "idea": "ideas",
    "experiment": "experiments",
}
REQUIRED_SIDE_SUBSTANCE_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "program_decision": (("decision", "text"),),
    "idea_discussion_conclusion": (("discussion_conclusion", "text"),),
    "method_selection": (
        ("method_selection", "proposed_repo_id"),
        ("method_selection", "selection_reason"),
    ),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_relative_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved = trusted_project_path(
        resolved_root,
        path,
        allowed_root=resolved_root / "kb",
        require="file",
    )
    return resolved.relative_to(resolved_root).as_posix()


def _unit_path(root: Path, unit_id: str) -> Path | None:
    try:
        return trusted_unit_record_path(root, unit_id)
    except ValueError:
        return None


def _identity_violations(root: Path, record: dict[str, Any], owner: str, artifact_path: Path) -> list[str]:
    kind = _text(record.get("kind"))
    subject_id = _text(record.get("id"))
    violations: list[str] = []
    try:
        _safe_relative_path(root, artifact_path)
    except ValueError:
        violations.append("judgement artifact path escapes the project root")
    if not subject_id:
        return ["judgement subject id is empty"]
    expected_owner = UNIT_OWNER_BY_KIND.get(kind)
    expected_path: Path | None = None
    if expected_owner:
        expected_path = root / "kb" / "units" / UNIT_DIR_BY_KIND[kind] / subject_id / "record.yaml"
    elif kind == "program_decision":
        program_id = _text(record.get("program_id"))
        expected_owner = "research-orchestrator"
        if not program_id:
            violations.append("program decision has no program_id")
        else:
            expected_path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    elif kind == "idea_discussion_conclusion":
        idea_id = _text(record.get("idea_id"))
        expected_owner = "idea-workbench"
        if not idea_id:
            violations.append("discussion conclusion has no idea_id")
        else:
            expected_path = root / "kb" / "units" / "ideas" / idea_id / "discussion-judgements.yaml"
    elif kind == "method_selection":
        program_id = _text(record.get("program_id"))
        idea_id = _text(record.get("idea_id"))
        expected_owner = "method-designer"
        if not program_id or not idea_id:
            violations.append("method selection has no canonical program_id/idea_id")
        else:
            if subject_id != f"method-selection:{program_id}:{idea_id}":
                violations.append("method selection id does not match program_id/idea_id")
            expected_path = root / "kb" / "programs" / program_id / "design" / f"{idea_id}-repo-choice.yaml"
        payload = record.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        selection = payload.get("method_selection")
        selection = selection if isinstance(selection, dict) else {}
        proposed_repo_id = _text(record.get("proposed_repo_id"))
        if proposed_repo_id != _text(selection.get("proposed_repo_id")):
            violations.append("method selection operative and confirmable proposed_repo_id differ")
        if _text(record.get("selected_repo_id")) or _text(selection.get("selected_repo_id")):
            violations.append("pending method selection already contains selected_repo_id")
    elif kind == "survey_judgement":
        expected_owner = "literature-synthesizer"
        slug = _text(record.get("slug"))
        mode = _text(record.get("mode"))
        if subject_id != f"survey:{mode}:{slug}":
            violations.append("survey judgement id does not match mode/slug")
        try:
            expected_path = survey_artifact_path(root, slug, mode)
        except ValueError:
            violations.append("survey judgement has no canonical mode/slug")
    else:
        violations.append(f"unsupported judgement kind: {kind or '<empty>'}")
    if expected_owner and owner != expected_owner:
        violations.append("judgement owner does not match canonical kind owner")
    if kind not in UNIT_OWNER_BY_KIND and _text(record.get("owner")) != expected_owner:
        violations.append("side judgement record.owner does not match canonical kind owner")
    if expected_path is not None:
        try:
            safe_artifact = trusted_project_path(
                root,
                artifact_path,
                allowed_root=root / "kb",
                require="file",
            )
            safe_expected = trusted_project_path(
                root,
                expected_path,
                allowed_root=root / "kb",
                require="file",
            )
        except ValueError:
            violations.append("judgement artifact path is not a canonical safe file")
        else:
            if safe_artifact != safe_expected:
                violations.append("judgement artifact path does not match canonical subject identity")
    return violations


def _source_roots(root: Path, record: dict[str, Any], artifact_path: Path) -> dict[str, Path]:
    if _text(record.get("kind")) == "survey_judgement":
        return survey_source_roots(root, record, artifact_path)
    return trusted_claim_source_roots(
        root,
        record,
        verification_root=_verification_root(root, record, artifact_path),
    )


def _verification_root(root: Path, record: dict[str, Any], artifact_path: Path) -> Path:
    program_id = _text(record.get("program_id"))
    if _text(record.get("kind")) == "program_decision" and program_id:
        return trusted_program_root(root, program_id)
    return trusted_project_path(
        root,
        artifact_path.parent,
        allowed_root=root / "kb",
        require="dir",
    )


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
    if _text(record.get("kind")) == "survey_judgement":
        violations.extend(survey_lifecycle_violations(record, root))
    try:
        verification_root = _verification_root(root, record, artifact_path)
        source_roots = _source_roots(root, record, artifact_path)
    except ValueError:
        violations.append("judgement evidence source is not canonically contained")
    else:
        violations.extend(
            verification_receipt_violations(
                record,
                verification_root,
                source_roots=source_roots,
            )
        )
    return violations


def judgement_confirmation_is_current(root: Path, record: dict[str, Any], artifact_path: Path) -> bool:
    """Validate a judgement receipt against canonical identity and current evidence bytes."""
    root = root.resolve()
    artifact_path = artifact_path.resolve()
    if _text(record.get("kind")) == "survey_judgement" and survey_lifecycle_violations(record, root):
        return False
    try:
        verification_root = _verification_root(root, record, artifact_path)
        source_roots = _source_roots(root, record, artifact_path)
    except ValueError:
        return False
    return has_complete_confirmation_receipt(
        record,
        verification_root=verification_root,
        source_roots=source_roots,
        external_source=record_external_source_contract(record),
    )


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
            "action": "discuss",
            "phase": "confirm",
            "idea_id": _text(record.get("idea_id")),
            "conclusion_id": subject_id,
        }
    if kind == "method_selection":
        return {
            "owner": owner,
            "action": "confirm-selection",
            "program_id": _text(record.get("program_id")),
            "idea_id": _text(record.get("idea_id")),
        }
    if kind == "survey_judgement":
        return {
            "owner": owner,
            "action": "confirm",
            "slug": _text(record.get("slug")),
            "mode": _text(record.get("mode")),
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
    if not isinstance(record, dict):
        return None
    if _identity_violations(root, record, owner, artifact_path) or readiness_violations(root, record, artifact_path):
        return None
    route = _default_route(record, owner)
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    substance = {
        section: payload.get(section)
        for section in CONFIRMABLE_CONTENT_SECTIONS.get(_text(record.get("kind")), ())
        if payload.get(section) not in (None, "", [], {})
    }
    if _text(record.get("kind")) == "survey_judgement":
        substance = {
            "filters": record.get("filters") if isinstance(record.get("filters"), dict) else {},
            "as_of": (record.get("kb_anchor") or {}).get("as_of") if isinstance(record.get("kb_anchor"), dict) else "",
            "sections": record.get("sections") if isinstance(record.get("sections"), list) else [],
            "comparison_matrix": record.get("comparison_matrix") if isinstance(record.get("comparison_matrix"), dict) else {},
        }
        if not substance["sections"] or not substance["comparison_matrix"]:
            return None
    selected_fields = CONFIRMABLE_CONTENT_FIELDS.get(_text(record.get("kind")), {})
    if selected_fields:
        has_substance = any(
            isinstance(payload.get(section), dict)
            and any(payload[section].get(field) not in (None, "", [], {}) for field in fields)
            for section, fields in selected_fields.items()
        )
        if not has_substance:
            return None
    for section, field in REQUIRED_SIDE_SUBSTANCE_FIELDS.get(_text(record.get("kind")), ()):
        section_value = payload.get(section)
        value = section_value.get(field) if isinstance(section_value, dict) else None
        if value in (None, "", [], {}) or (isinstance(value, str) and not value.strip()):
            return None
    snapshot_binding = judgement_snapshot_binding(
        record,
        owner=owner,
        path=_safe_relative_path(root, artifact_path),
    )
    card = {
        "subject": {
            "kind": _text(record.get("kind")),
            "id": _text(record.get("id")),
            "owner": owner,
            "path": _safe_relative_path(root, artifact_path),
        },
        "claims": confirmation_claims(record),
        "substance": substance,
        "content_digest": snapshot_binding["content_digest"],
        "verification": dict(payload.get("verification", {})),
        "snapshot_binding": snapshot_binding,
        "confirmation_status": "pending_user_confirmation",
        "priority": _text(record.get("priority")) or "normal",
        "updated_at": _text(record.get("updated_at") or record.get("timestamp")),
        "confirm_route": {str(key): _text(value) for key, value in route.items()},
    }
    if _text(record.get("kind")) == "survey_judgement":
        card["reject_route"] = {
            "owner": owner,
            "action": "reject",
            "slug": _text(record.get("slug")),
            "mode": _text(record.get("mode")),
        }
        card["program_ids"] = [
            _text(item) for item in record.get("program_ids", []) if _text(item)
        ]
    return card


def _safe_candidate_file(root: Path, path: Path) -> Path | None:
    try:
        return trusted_project_path(
            root,
            path,
            allowed_root=root / "kb",
            require="file",
        )
    except ValueError:
        return None


def _list_items(root: Path, path: Path) -> Iterable[dict[str, Any]]:
    safe_path = _safe_candidate_file(root, path)
    if safe_path is None:
        return []
    try:
        payload = load_yaml(safe_path, default={})
    except (OSError, UnicodeError, yaml.YAMLError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _candidate_artifacts(root: Path) -> Iterable[tuple[dict[str, Any], str, Path]]:
    for path in sorted((root / "kb" / "units").glob("*/*/record.yaml")):
        safe_path = _safe_candidate_file(root, path)
        if safe_path is None:
            continue
        try:
            record = load_yaml(safe_path, default={})
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(record, dict):
            owner = UNIT_OWNER_BY_KIND.get(_text(record.get("kind")), _text(record.get("owner")) or "unknown")
            yield record, owner, safe_path
    for path in sorted((root / "kb" / "programs").glob("*/workflow/decisions.yaml")):
        safe_path = _safe_candidate_file(root, path)
        if safe_path is None:
            continue
        for item in _list_items(root, safe_path):
            yield item, "research-orchestrator", safe_path
    for path in sorted((root / "kb" / "units" / "ideas").glob("*/discussion-judgements.yaml")):
        safe_path = _safe_candidate_file(root, path)
        if safe_path is None:
            continue
        for item in _list_items(root, safe_path):
            yield item, "idea-workbench", safe_path
    for path in sorted((root / "kb" / "programs").glob("*/design/*-repo-choice.yaml")):
        safe_path = _safe_candidate_file(root, path)
        if safe_path is None:
            continue
        try:
            payload = load_yaml(safe_path, default={})
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(payload, dict):
            yield payload, "method-designer", safe_path
    for path in sorted((root / "kb" / "synthesis").glob("*/*.yaml")):
        if path.name.endswith("-fill.yaml"):
            continue
        safe_path = _safe_candidate_file(root, path)
        if safe_path is None:
            continue
        try:
            payload = load_yaml(safe_path, default={})
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if isinstance(payload, dict) and _text(payload.get("kind")) == "survey_judgement":
            yield payload, "literature-synthesizer", safe_path


def discover_pending_judgements(root: str | Path) -> list[dict[str, Any]]:
    """Return all cross-owner ``ready_for_review`` cards in deterministic order."""
    project_root = Path(root).resolve()
    raw_candidates = list(_candidate_artifacts(project_root))
    subject_counts: dict[tuple[str, str], int] = {}
    for record, owner, path in raw_candidates:
        if _identity_violations(project_root, record, owner, path):
            continue
        key = (_text(record.get("kind")), _text(record.get("id")))
        subject_counts[key] = subject_counts.get(key, 0) + 1
    candidates = [
        card
        for record, owner, path in raw_candidates
        if (card := pending_judgement_card(project_root, record, owner=owner, artifact_path=path)) is not None
    ]
    cards = [
        card
        for card in candidates
        if subject_counts.get(
            (_text(card.get("subject", {}).get("kind")), _text(card.get("subject", {}).get("id"))),
            0,
        )
        == 1
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


def apply_judgement_rejection(
    record: dict[str, Any],
    *,
    reason: str = "",
    rejected_at: str = "",
) -> None:
    """Reject one pending, substantive judgement without fabricating a receipt."""
    if _text(record.get("confirmation_status")) != "pending_user_confirmation":
        raise ValueError("only a pending judgement can be rejected")
    claims = confirmation_claims(record)
    if not claims:
        raise ValueError("a judgement without canonical claims cannot be rejected")
    for claim in claims:
        claim["confirmation_status"] = "rejected"
    record["confirmation_status"] = "rejected"
    # Rejection is terminal for the inbox but does not erase that this remains
    # judgement-class material governed by a human gate.
    record["needs_human_confirmation"] = True
    record.pop("confirmation", None)
    record["rejection"] = {
        "at": rejected_at or utc_now_iso(),
        "reason": _text(reason),
    }


def judgement_snapshot_binding(
    record: dict[str, Any],
    *,
    owner: str = "",
    path: str = "",
) -> dict[str, Any]:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    verification = payload.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    content_digest = (
        survey_content_digest(record)
        if _text(record.get("kind")) == "survey_judgement"
        else confirmation_content_digest(record)
    )
    return {
        "subject": {
            "kind": _text(record.get("kind")),
            "id": _text(record.get("id")),
            "owner": _text(owner),
            "path": _text(path),
        },
        "confirmation_status": _text(record.get("confirmation_status")),
        "content_digest": content_digest,
        "verification": {
            key: _text(verification.get(key))
            for key in ("verified_at", "claims_digest", "evidence_digest")
        },
    }


def require_judgement_snapshot(
    record: dict[str, Any],
    *,
    expected_snapshot: str | dict[str, Any],
    owner: str,
    path: str,
    root: str | Path | None = None,
) -> None:
    if isinstance(expected_snapshot, str):
        try:
            expected = json.loads(expected_snapshot)
        except json.JSONDecodeError as exc:
            raise ValueError("review snapshot binding is not valid JSON") from exc
    else:
        expected = expected_snapshot
    if not isinstance(expected, dict):
        raise ValueError("review snapshot binding is incomplete")
    subject = expected.get("subject")
    verification = expected.get("verification")
    judgement_claim_present = any(
        _text(claim.get("claim_type")) in JUDGEMENT_CLAIM_TYPES
        for claim in confirmation_claims(record)
    )
    if (
        not isinstance(subject, dict)
        or not isinstance(verification, dict)
        or _text(expected.get("confirmation_status")) != "pending_user_confirmation"
        or not _text(expected.get("content_digest"))
        or (
            judgement_claim_present
            and any(not _text(verification.get(key)) for key in ("verified_at", "claims_digest", "evidence_digest"))
        )
    ):
        raise ValueError("review snapshot binding is incomplete")
    if root is not None and judgement_claim_present:
        project_root = Path(root).resolve()
        artifact_path = (project_root / path).resolve()
        identity_owner = UNIT_OWNER_BY_KIND.get(_text(record.get("kind")), owner)
        if _identity_violations(project_root, record, identity_owner, artifact_path):
            raise ValueError("review subject no longer has its canonical owner or path identity")
        subject_kind = _text(record.get("kind"))
        subject_id = _text(record.get("id"))
        matches = [
            card
            for card in discover_pending_judgements(project_root)
            if _text(card.get("subject", {}).get("kind")) == subject_kind
            and _text(card.get("subject", {}).get("id")) == subject_id
        ]
        if len(matches) != 1:
            raise ValueError("review subject is no longer uniquely ready under its canonical owner")
    if judgement_snapshot_binding(record, owner=owner, path=path) != expected:
        raise ValueError("review snapshot is stale; show the current judgement before applying a decision")


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
        candidate = project_root / relative
        candidates.append(
            trusted_project_path(
                project_root,
                candidate,
                allowed_root=project_root / "kb",
                require="file",
            )
        )
    unit = _unit_path(project_root, subject_id)
    if unit is not None:
        candidates.append(unit)
    if subject_kind == "program_decision":
        candidates.extend((project_root / "kb" / "programs").glob("*/workflow/decisions.yaml"))
    if subject_kind == "idea_discussion_conclusion":
        candidates.extend((project_root / "kb" / "units" / "ideas").glob("*/discussion-judgements.yaml"))
    if subject_kind == "survey_judgement":
        candidates.extend((project_root / "kb" / "synthesis").glob("*/*.yaml"))
    for path in candidates:
        try:
            safe_path = trusted_project_path(
                project_root,
                path,
                allowed_root=project_root / "kb",
                require="file",
            )
        except ValueError:
            continue
        payload = load_yaml(safe_path, default={})
        records = payload.get("items") if isinstance(payload, dict) and isinstance(payload.get("items"), list) else [payload]
        for record in records:
            if not isinstance(record, dict):
                continue
            if _text(record.get("id")) == subject_id and _text(record.get("kind")) == subject_kind:
                owner = _text(subject.get("owner")) or UNIT_OWNER_BY_KIND.get(subject_kind) or _text(record.get("owner"))
                if _identity_violations(project_root, record, owner, safe_path):
                    continue
                return record, safe_path
    raise ValueError(f"bound judgement not found: {subject_kind}:{subject_id}")


__all__ = [
    "apply_judgement_rejection",
    "confirmation_binding",
    "discover_pending_judgements",
    "judgement_snapshot_binding",
    "judgement_confirmation_is_current",
    "load_bound_judgement",
    "pending_judgement_card",
    "require_judgement_snapshot",
    "readiness_violations",
]

"""Confirmation gate: provenance, validate_write, confirm/apply, link and promote."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    load_yaml,
    utc_now_iso,
    write_yaml_if_changed,
)
from .journal import mutation_transaction
from .evidence import (
    JUDGEMENT_CLAIM_TYPES,
    UNCONFIRMABLE_CLAIM_TYPES,
    confirmation_claims,
    confirmation_claim_ids,
    confirmation_content_digest,
    confirmation_evidence_digest,
    record_external_source_contract,
    validate_claims,
    verification_receipt_violations,
    verify_claim_evidence,
)
from .paths import (
    UNIT_KIND_DIRS,
    _text_list,
    unit_root,
)
from .records import (
    _record_needs_gate,
    append_history,
    kind_payload_skeleton,
    locate_record,
    normalize_record_schema,
)
from .prefs import (
    load_runtime_preferences,
)
from .relations import link_identity, normalize_link

GATED_CONFIRMATION_VALUES = {"pending_user_confirmation", "rejected"}


# Self-sign red line: an AI identity may never confirm its own pending record.
# The public set remains for compatibility/documentation; detection below uses
# token boundaries so compound identities cannot evade an exact-string denylist.
AI_SIGNER_NAMES = {
    "ai", "assistant", "agent", "bot", "llm",
    "codex", "chatgpt", "gpt", "openai",
    "claude", "anthropic", "sonnet", "opus", "haiku", "fable",
    "gemini", "bard", "google-ai",
    "llama", "mistral", "cohere", "grok", "copilot", "qwen", "deepseek",
}

AI_SIGNER_TOKENS = {
    "ai", "assistant", "agent", "bot", "llm", "codex", "chatgpt", "gpt",
    "openai", "anthropic", "gemini", "bard", "llama", "mistral", "cohere",
    "grok", "copilot", "qwen", "deepseek",
}
AI_MODEL_NAME_TOKENS = {"claude", "sonnet", "opus", "haiku", "fable"}
AI_MODEL_CONTEXT_TOKENS = {"code", "assistant", "agent", "ai", "model", "anthropic"}


CONFIRM_UNIT_STATUS_BY_KIND = {
    "paper": "active",
    "repo": "active",
    "dataset": "active",
    "blog": "active",
}


CONFIRM_UNIT_SUMMARY_BY_KIND = {
    "paper": "Paper analysis confirmed by user.",
    "repo": "Repo analysis confirmed by user.",
    "dataset": "Dataset analysis confirmed by user.",
    "blog": "Blog analysis confirmed by user.",
    "idea": "Idea content confirmed by user.",
    "experiment": "Experiment findings confirmed by user.",
}


def is_ai_signer(actor: str) -> bool:
    normalized = str(actor or "").strip().casefold()
    if normalized in AI_SIGNER_NAMES:
        return True
    tokens = re.findall(r"[a-z0-9]+", normalized)
    token_set = set(tokens)
    if token_set & AI_SIGNER_TOKENS:
        return True
    return bool(token_set & AI_MODEL_NAME_TOKENS and token_set & AI_MODEL_CONTEXT_TOKENS)


# Substance-check (SSOT §3.11 / Principle 3 — plug the hollow confirmation gate).
#
# Per kind, the payload section(s) that hold the *substantive analysis* (the region
# that becomes hollow when an analyst confirms an empty note). Paper intentionally
# uses `core_content` so the emptiness caliber matches the G5 research-value harness
# (`paper_core_content_empty`): a paper whose 8 core_content fields are ALL empty is
# hollow. Field names are read from the schema SSOT (records.kind_payload_skeleton),
# so this stays aligned with the canonical fields the harness scans.
SUBSTANCE_CONTENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "paper": ("core_content",),
    "repo": ("capability",),
    "dataset": ("profile", "composition", "access", "quality"),
    "blog": ("content",),
    "idea": ("problem", "hypothesis"),
    "experiment": ("results", "diagnosis"),
}


def _is_empty_value(value: Any) -> bool:
    """Emptiness predicate matching the G5 research-value harness caliber.

    None / whitespace-only string / empty list|dict|tuple|set all count as empty
    (mirrors eval_research_value._is_empty_value so the two agree that an all-empty
    core_content is hollow).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def has_substantive_content(record: dict[str, Any], kind: str | None = None) -> bool:
    """True when the record carries real analytical content (not a hollow template).

    For a paper this is exactly ``not paper_core_content_empty(record)`` in the G5
    harness: substantive iff at least one of the 8 canonical ``core_content`` fields
    is non-empty. Other kinds use the analogous core-analysis section(s) declared in
    ``SUBSTANCE_CONTENT_SECTIONS``. Unknown kinds are *not* judged (returns True) so
    the gate only tightens the kinds it understands, never blocks an unknown one.
    """
    unit_kind = str(kind or record.get("kind") or "")
    sections = SUBSTANCE_CONTENT_SECTIONS.get(unit_kind)
    if not sections:
        return True
    payload = record.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    skeleton = kind_payload_skeleton(unit_kind)
    for section_key in sections:
        canonical_fields = skeleton.get(section_key) or {}
        record_section = payload.get(section_key)
        if not isinstance(record_section, dict):
            record_section = {}
        for field in canonical_fields:
            if not _is_empty_value(record_section.get(field)):
                return True
    return False


def confirmation_track(record: dict[str, Any]) -> str:
    """Two-track classification of a pending item (SSOT §3.11 decision ①).

    - ``'judgement'`` — the record carries AI inference/evaluation/user_opinion (or an
      AI source), i.e. it already needs the confirmation gate. Confirming it as fact
      requires substance (``has_substantive_content``) *and* evidence provenance.
    - ``'fact'`` — pure factual metadata (title/authors/arxiv/links). Eligible for
      light / auto confirmation (no deep substance check, but self-signing is still
      forbidden via ``require_confirmation_provenance``).

    Reuses ``_record_needs_gate`` so the track boundary is identical to the existing
    governance gate rather than a parallel, drifting rule.
    """
    needs_gate, _ai_info_types, _source_is_ai = _record_needs_gate(record)
    claim_types = _canonical_claim_types(record)
    claim_floor = JUDGEMENT_CLAIM_TYPES | UNCONFIRMABLE_CLAIM_TYPES
    return "judgement" if needs_gate or bool(claim_types & claim_floor) else "fact"


def _canonical_claim_types(record: dict[str, Any]) -> set[str]:
    return {
        str(claim.get("claim_type") or "")
        for claim in confirmation_claims(record)
        if isinstance(claim, dict)
    }


def _require_confirmable_claim_types(record: dict[str, Any]) -> None:
    blocked = sorted(_canonical_claim_types(record) & UNCONFIRMABLE_CLAIM_TYPES)
    if blocked:
        raise SystemExit(
            "Cannot confirm canonical claims with unconfirmable claim_type(s): "
            + ", ".join(blocked)
            + ". Resolve or replace unverified claims before confirmation."
        )


def default_confirmed_by(project_root: Path | None = None) -> str:
    if project_root is None:
        return ""
    preferences = load_runtime_preferences(project_root)
    identity = preferences.get("identity", {})
    if not isinstance(identity, dict):
        return ""
    return str(identity.get("default_confirmed_by") or "").strip()


def require_confirmation_provenance(
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    project_root: Path | None = None,
) -> tuple[str, list[str]]:
    actor = str(confirmed_by or "").strip()
    if not actor:
        actor = default_confirmed_by(project_root)
    evidence_items = _text_list([evidence] if isinstance(evidence, str) else evidence)
    if not actor:
        raise SystemExit("Human confirmation requires --confirmed-by or identity.default_confirmed_by.")
    if is_ai_signer(actor):
        # Governance red line: no self-signing — an AI identity cannot confirm its own
        # pending record. Wires the pre-existing is_ai_signer/AI_SIGNER_NAMES guard into
        # the provenance check (added rejection only; all prior checks preserved).
        raise SystemExit(
            f"Self-signing is forbidden: confirmed_by={actor!r} is an AI identity; "
            f"an AI cannot confirm its own pending record — provide a human confirmer."
        )
    if not evidence_items:
        raise SystemExit("Human confirmation requires at least one --evidence.")
    return actor, evidence_items


def require_user_authorization(
    *,
    user_authorization: str,
    authorization_source: str,
) -> tuple[str, str]:
    """Validate the human-origin attestation carried by the host/agent.

    This is deliberately an audit/attestation check, not a claim of cryptographic
    identity authentication. The host/agent remains responsible for faithfully
    transcribing the user's message.
    """
    authorization = str(user_authorization or "").strip()
    source = str(authorization_source or "").strip()
    if not authorization:
        raise SystemExit("Judgement confirmation requires user_authorization with the user's exact words.")
    if source != "user_message":
        raise SystemExit("Judgement confirmation requires authorization_source=user_message.")
    return authorization, source


def _trusted_claim_source_roots(project_root: Path, record: dict[str, Any]) -> dict[str, Path]:
    """Resolve cross-unit evidence roots from canonical KB records, never claim paths."""
    roots: dict[str, Path] = {}
    record_id = str(record.get("id") or "").strip()
    record_kind = str(record.get("kind") or "").strip()
    for claim in confirmation_claims(record):
        for ref in claim.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            source_unit_id = str(ref.get("source_unit_id") or "").strip()
            if not source_unit_id or source_unit_id in roots:
                continue
            if source_unit_id == record_id:
                roots[source_unit_id] = unit_root(project_root, record_kind, record_id)
                continue
            _source_record, source_path = locate_record(project_root, source_unit_id)
            roots[source_unit_id] = source_path.parent
    return roots


def apply_confirmation(
    record: dict[str, Any],
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    user_authorization: str = "",
    authorization_source: str = "",
    method: str = "cli",
    project_root: Path | None = None,
    verification_root: Path | None = None,
    trusted_source_roots: dict[str, Path] | None = None,
) -> dict[str, Any]:
    _require_confirmable_claim_types(record)
    actor, evidence_items = require_confirmation_provenance(
        confirmed_by=confirmed_by,
        evidence=evidence,
        project_root=project_root,
    )
    track = confirmation_track(record)
    claims = confirmation_claims(record)
    authorization = ""
    source = ""
    if track == "judgement":
        if not claims:
            raise SystemExit("Judgement confirmation requires non-empty canonical payload.claims.")
        authorization, source = require_user_authorization(
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
    claim_violations = validate_claims(claims)
    if claim_violations:
        raise SystemExit("Confirmation claim violations:\n  - " + "\n  - ".join(claim_violations))
    evidence_root: Path | None = verification_root
    external_source = record_external_source_contract(record)
    source_roots: dict[str, Path] | None = trusted_source_roots
    if project_root is not None and evidence_root is None:
        evidence_root = unit_root(
            project_root,
            str(record.get("kind") or ""),
            str(record.get("id") or ""),
        )
    if project_root is not None and source_roots is None:
        source_roots = _trusted_claim_source_roots(project_root, record)
    claims_with_evidence = [claim for claim in claims if claim.get("evidence_refs")]
    if claims_with_evidence:
        if evidence_root is None:
            raise SystemExit("Cannot verify claim evidence for confirmation without project_root.")
        evidence_violations = [
            violation
            for claim in claims_with_evidence
            for violation in verify_claim_evidence(
                claim,
                evidence_root,
                external_source=external_source,
                source_roots=source_roots,
            )
        ]
        if evidence_violations:
            raise SystemExit("Confirmation evidence violations:\n  - " + "\n  - ".join(evidence_violations))
    if track == "judgement":
        if evidence_root is None:
            raise SystemExit("Cannot validate judgement verification without project_root.")
        verification_violations = verification_receipt_violations(
            record,
            evidence_root,
            external_source=external_source,
            source_roots=source_roots,
        )
        if verification_violations:
            raise SystemExit(
                "Judgement verification receipt is missing or stale:\n  - "
                + "\n  - ".join(verification_violations)
            )
    now = utc_now_iso()
    prior_information_types = _text_list(record.get("information_types"))
    record["confirmation_status"] = "confirmed"
    record["needs_human_confirmation"] = False
    record["last_human_confirmed_at"] = now
    receipt = {
        "by": actor,
        "at": now,
        "evidence": evidence_items,
        "method": str(method or "cli").strip() or "cli",
        "decision": "confirmed",
        "subject": {
            "kind": str(record.get("kind") or ""),
            "id": str(record.get("id") or ""),
        },
        "claim_ids": confirmation_claim_ids(record),
        "content_digest": confirmation_content_digest(record),
        "evidence_digest": confirmation_evidence_digest(record, evidence_items),
        "prior_information_types": prior_information_types,
    }
    if track == "judgement":
        verification = record.get("payload", {}).get("verification", {})
        receipt.update(
            {
                "verified_at": str(verification.get("verified_at") or ""),
                "user_authorization": authorization,
                "authorization_source": source,
            }
        )
    record["confirmation"] = receipt
    return record


def _has_complete_confirmation_receipt(record: dict[str, Any]) -> bool:
    claims = confirmation_claims(record)
    if validate_claims(claims) or (_canonical_claim_types(record) & UNCONFIRMABLE_CLAIM_TYPES):
        return False
    receipt = record.get("confirmation")
    if not isinstance(receipt, dict) or receipt.get("decision") != "confirmed":
        return False
    actor = str(receipt.get("by") or "").strip()
    if not actor or is_ai_signer(actor) or not _text_list(receipt.get("evidence")):
        return False
    subject = receipt.get("subject")
    if not isinstance(subject, dict):
        return False
    if str(subject.get("kind") or "") != str(record.get("kind") or ""):
        return False
    if str(subject.get("id") or "") != str(record.get("id") or ""):
        return False
    claim_ids = receipt.get("claim_ids")
    if not isinstance(claim_ids, list):
        return False
    if not isinstance(receipt.get("prior_information_types"), list):
        return False
    if not all(
        re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field) or "")) is not None
        for field in ("content_digest", "evidence_digest")
    ):
        return False
    if str(receipt.get("content_digest") or "") != confirmation_content_digest(record):
        return False
    if str(receipt.get("evidence_digest") or "") != confirmation_evidence_digest(record, receipt.get("evidence")):
        return False
    current_claim_ids = confirmation_claim_ids(record)
    if sorted(str(item) for item in claim_ids) != current_claim_ids:
        return False
    if confirmation_track(record) == "judgement":
        if not current_claim_ids:
            return False
        if not str(receipt.get("user_authorization") or "").strip():
            return False
        if str(receipt.get("authorization_source") or "") != "user_message":
            return False
        payload = record.get("payload")
        verification = payload.get("verification") if isinstance(payload, dict) else None
        if not isinstance(verification, dict):
            return False
        if str(receipt.get("verified_at") or "") != str(verification.get("verified_at") or ""):
            return False
        if verification_receipt_violations(record, None, check_artifacts=False):
            return False
    return True


def has_complete_confirmation_receipt(record: dict[str, Any]) -> bool:
    """Public structural/current-content validator for downstream consumers."""
    return _has_complete_confirmation_receipt(record)


def confirm_unit(
    record: dict[str, Any],
    kind: str | None = None,
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    user_authorization: str = "",
    authorization_source: str = "",
    method: str = "cli",
    project_root: Path | None = None,
) -> dict[str, Any]:
    unit_kind = str(kind or record.get("kind") or "")
    if unit_kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {unit_kind}")
    _require_confirmable_claim_types(record)
    # Substance gate (SSOT §3.11 / Principle 3). This is the PRIMARY user confirm path
    # (paper.py confirm / kb.py confirm / interactive kb review), so the hollow-gate
    # check must live here too, not only in promote_record. Evaluate track + substance
    # on the ORIGINAL record before confirmation mutates gate state. Confirmation keeps
    # the record's epistemic types; confirmation_status carries the human decision.
    # Fact-track basic metadata is exempt (light confirm). Runs before apply_confirmation
    # (and thus before any write by the caller), so a rejected record stays pending.
    if confirmation_track(record) == "judgement" and not has_substantive_content(record, unit_kind):
        raise SystemExit(
            f"Refusing to confirm hollow unit {str(record.get('id'))!r}: core content is empty / "
            f"template-only — a judgement-track record cannot be confirmed as fact. "
            f"Fill the analysis (e.g. payload.core_content) before confirming."
        )
    record = apply_confirmation(
        record,
        confirmed_by=confirmed_by,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        method=method,
        project_root=project_root,
    )
    if unit_kind in CONFIRM_UNIT_STATUS_BY_KIND:
        record["status"] = CONFIRM_UNIT_STATUS_BY_KIND[unit_kind]
    elif unit_kind == "experiment" and str(record.get("status") or "") == "running":
        record["status"] = "completed"
    confirmed_information_types = _text_list(record.get("information_types")) or ["fact"]
    append_history(
        record,
        action=f"{unit_kind}-confirmed",
        summary=CONFIRM_UNIT_SUMMARY_BY_KIND.get(unit_kind, f"{unit_kind} record confirmed by user."),
        information_types=confirmed_information_types,
    )
    return record


def validate_write(record: dict[str, Any], *, strict: bool | None = None) -> list[str]:
    """Confirmation gate contract check (see lib/research/SCHEMAS.md#confirmation-gate).

    AI-derived records (information_types ∩ {inference, evaluation, user_opinion}
    or source.kind == "ai") must carry confirmation_status ∈
    {pending_user_confirmation, rejected} and needs_human_confirmation = true.

    Returns the list of contract violations (empty when clean). Judgement-track
    violations raise SystemExit by default; set RESEARCH_VALIDATE_FAILOPEN=1 or
    pass strict=False explicitly to downgrade violations to stderr warnings.
    """
    if strict is None:
        strict = os.getenv("RESEARCH_VALIDATE_FAILOPEN") != "1"
    record_needs_gate, ai_info_types, source_is_ai = _record_needs_gate(record)
    claim_floor_types = _canonical_claim_types(record) & (
        JUDGEMENT_CLAIM_TYPES | UNCONFIRMABLE_CLAIM_TYPES
    )
    needs_gate = record_needs_gate or bool(claim_floor_types)
    if not needs_gate:
        return []
    violations: list[str] = []
    confirmation = str(record.get("confirmation_status") or "")
    receipt_confirmed = confirmation == "confirmed" and _has_complete_confirmation_receipt(record)
    if confirmation not in GATED_CONFIRMATION_VALUES and not receipt_confirmed:
        reason_parts = []
        if ai_info_types:
            reason_parts.append(f"information_types={sorted(ai_info_types)}")
        if source_is_ai:
            reason_parts.append("source.kind=ai")
        if claim_floor_types:
            reason_parts.append(f"canonical claim_types={sorted(claim_floor_types)}")
        violations.append(
            f"record {record.get('id')!r}: confirmation_status={confirmation!r} "
            f"too strong for AI-derived record ({', '.join(reason_parts)}); "
            f"expected pending_user_confirmation or rejected."
        )
    if not receipt_confirmed and not record.get("needs_human_confirmation"):
        violations.append(
            f"record {record.get('id')!r}: needs_human_confirmation must be true "
            f"for AI-derived record."
        )
    if violations:
        msg = "validate_write contract violations:\n  - " + "\n  - ".join(violations)
        if strict:
            raise SystemExit(msg)
        sys.stderr.write(f"[research/core.validate_write] WARN: {msg}\n")
    return violations


def write_record(
    project_root: Path,
    record: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> Path:
    supplied_revision = record.get("revision") if "revision" in record else None
    supplied_has_revision = "revision" in record
    normalized = normalize_record_schema(record, project_root=project_root)
    validate_write(normalized)
    root = unit_root(project_root, str(normalized["kind"]), str(normalized["id"]))
    path = root / "record.yaml"
    with mutation_transaction(project_root, "write_record", [path]):
        ensure_dir(root)
        current_revision = 0
        if path.exists():
            current = load_yaml(path, default={})
            if not isinstance(current, dict):
                raise SystemExit(f"Invalid on-disk record payload: {path}")
            try:
                current_revision = max(0, int(current.get("revision", 0)))
            except (TypeError, ValueError) as exc:
                raise SystemExit(f"Invalid on-disk record revision: {path}") from exc
        if expected_revision is None:
            if path.exists() and not supplied_has_revision:
                raise SystemExit(
                    f"Record revision missing for existing {normalized['id']}; "
                    "reload the record before writing or pass an explicit expected_revision."
                )
            try:
                effective_expected_revision = int(supplied_revision) if path.exists() else 0
            except (TypeError, ValueError) as exc:
                raise SystemExit(
                    f"Invalid expected record revision for {normalized['id']}: {supplied_revision!r}"
                ) from exc
        else:
            try:
                effective_expected_revision = max(0, int(expected_revision))
            except (TypeError, ValueError) as exc:
                raise SystemExit(
                    f"Invalid explicit expected_revision for {normalized['id']}: {expected_revision!r}"
                ) from exc
        if current_revision != effective_expected_revision:
            raise SystemExit(
                f"Record revision conflict for {normalized['id']}: "
                f"expected {effective_expected_revision}, found {current_revision}"
            )
        normalized["revision"] = current_revision + 1
        normalized["updated_at"] = utc_now_iso()
        write_yaml_if_changed(path, normalized)
        record["revision"] = normalized["revision"]
        record["updated_at"] = normalized["updated_at"]
    return path


def link_records(
    project_root: Path,
    from_id: str,
    to_id: str,
    relation: str,
    note: str = "",
    *,
    source_locator: dict[str, str] | None = None,
    target_locator: dict[str, str] | None = None,
) -> None:
    from_record, _ = locate_record(project_root, from_id)
    locate_record(project_root, to_id)
    link = normalize_link(
        {
            "target_id": to_id,
            "relation": relation,
            "note": note,
            "source_locator": source_locator,
            "target_locator": target_locator,
        }
    )
    links = from_record.setdefault("links", [])
    identity = link_identity(link)
    existing = next((item for item in links if link_identity(item) == identity), None)
    if existing is not None:
        if note and str(existing.get("note") or "") != str(link.get("note") or ""):
            existing["note"] = str(link.get("note") or "")
            append_history(
                from_record,
                action="link_updated",
                summary=f"Updated link to {to_id} as {link['relation']}.",
                artifacts=[],
            )
            write_record(project_root, from_record)
        return
    links.append(link)
    append_history(from_record, action="linked", summary=f"Linked to {to_id} as {link['relation']}.", artifacts=[])
    write_record(project_root, from_record)


def promote_record(
    project_root: Path,
    unit_id: str,
    *,
    status: str | None = None,
    maturity: str | None = None,
    confirmation_status: str | None = None,
    confirmed_by: str = "",
    evidence: list[str] | None = None,
    user_authorization: str = "",
    authorization_source: str = "",
    confirmation_method: str = "kb.py promote",
) -> Path:
    record, _ = locate_record(project_root, unit_id)
    if status:
        record["status"] = status
    if maturity:
        record["maturity"] = maturity
    if confirmation_status:
        if confirmation_status == "confirmed":
            _require_confirmable_claim_types(record)
            # Substance gate (SSOT §3.11 / Principle 3): a judgement-track record must
            # carry real content before it can be confirmed as fact. This ADDED check
            # is layered on top of the existing provenance rule (never relaxes it) and
            # runs before any mutation is written, so a rejected record stays pending
            # on disk. Fact-track basic metadata is exempt (light/auto confirm track).
            if confirmation_track(record) == "judgement" and not has_substantive_content(
                record, str(record.get("kind") or "")
            ):
                raise SystemExit(
                    f"Refusing to confirm hollow unit {unit_id!r}: core content is empty / "
                    f"template-only — a judgement-track record cannot be confirmed as fact. "
                    f"Fill the analysis (e.g. payload.core_content) before promoting to confirmed."
                )
            apply_confirmation(
                record,
                confirmed_by=confirmed_by,
                evidence=evidence or [],
                user_authorization=user_authorization,
                authorization_source=authorization_source,
                method=confirmation_method,
                project_root=project_root,
            )
        else:
            record["confirmation_status"] = confirmation_status
    append_history(record, action="promoted", summary="Updated record lifecycle state.")
    return write_record(project_root, record)


__all__ = [
    "GATED_CONFIRMATION_VALUES",
    "AI_SIGNER_NAMES",
    "AI_SIGNER_TOKENS",
    "CONFIRM_UNIT_STATUS_BY_KIND",
    "CONFIRM_UNIT_SUMMARY_BY_KIND",
    "SUBSTANCE_CONTENT_SECTIONS",
    "is_ai_signer",
    "has_substantive_content",
    "confirmation_track",
    "default_confirmed_by",
    "require_confirmation_provenance",
    "require_user_authorization",
    "apply_confirmation",
    "has_complete_confirmation_receipt",
    "confirm_unit",
    "validate_write",
    "write_record",
    "link_records",
    "promote_record",
]

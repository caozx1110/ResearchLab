"""Confirmation gate: provenance, validate_write, confirm/apply, link and promote."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    utc_now_iso,
    write_yaml_if_changed,
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

GATED_CONFIRMATION_VALUES = {"pending_user_confirmation", "rejected"}


AI_SIGNER_NAMES = {"ai", "assistant", "codex", "chatgpt", "gpt", "openai"}


CONFIRM_UNIT_STATUS_BY_KIND = {
    "paper": "active",
    "repo": "active",
    "blog": "active",
}


CONFIRM_UNIT_SUMMARY_BY_KIND = {
    "paper": "Paper analysis confirmed by user.",
    "repo": "Repo analysis confirmed by user.",
    "blog": "Blog analysis confirmed by user.",
    "idea": "Idea content confirmed by user.",
    "experiment": "Experiment findings confirmed by user.",
}


def is_ai_signer(actor: str) -> bool:
    return str(actor or "").strip().lower() in AI_SIGNER_NAMES


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
    return "judgement" if needs_gate else "fact"


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
    if not evidence_items:
        raise SystemExit("Human confirmation requires at least one --evidence.")
    return actor, evidence_items


def apply_confirmation(
    record: dict[str, Any],
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    method: str = "cli",
    project_root: Path | None = None,
) -> dict[str, Any]:
    actor, evidence_items = require_confirmation_provenance(
        confirmed_by=confirmed_by,
        evidence=evidence,
        project_root=project_root,
    )
    now = utc_now_iso()
    record["confirmation_status"] = "confirmed"
    record["needs_human_confirmation"] = False
    record["last_human_confirmed_at"] = now
    record["confirmation"] = {
        "by": actor,
        "at": now,
        "evidence": evidence_items,
        "method": str(method or "cli").strip() or "cli",
    }
    return record


def confirm_unit(
    record: dict[str, Any],
    kind: str | None = None,
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    method: str = "cli",
    project_root: Path | None = None,
) -> dict[str, Any]:
    unit_kind = str(kind or record.get("kind") or "")
    if unit_kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {unit_kind}")
    record = apply_confirmation(
        record,
        confirmed_by=confirmed_by,
        evidence=evidence,
        method=method,
        project_root=project_root,
    )
    if unit_kind in CONFIRM_UNIT_STATUS_BY_KIND:
        record["status"] = CONFIRM_UNIT_STATUS_BY_KIND[unit_kind]
    elif unit_kind == "experiment" and str(record.get("status") or "") == "running":
        record["status"] = "completed"
    record["information_types"] = ["fact"]
    append_history(
        record,
        action=f"{unit_kind}-confirmed",
        summary=CONFIRM_UNIT_SUMMARY_BY_KIND.get(unit_kind, f"{unit_kind} record confirmed by user."),
        information_types=["fact"],
    )
    return record


def validate_write(record: dict[str, Any], *, strict: bool | None = None) -> list[str]:
    """Confirmation gate contract check (see lib/research/SCHEMAS.md#confirmation-gate).

    AI-derived records (information_types ∩ {inference, evaluation, user_opinion}
    or source.kind == "ai") must carry confirmation_status ∈
    {pending_user_confirmation, rejected} and needs_human_confirmation = true.

    Returns the list of contract violations (empty when clean). In strict mode
    raises SystemExit; otherwise emits a stderr warning. Default is non-strict;
    set RESEARCH_VALIDATE_STRICT=1 to opt into strict.
    """
    if strict is None:
        strict = os.getenv("RESEARCH_VALIDATE_STRICT") == "1"
    needs_gate, ai_info_types, source_is_ai = _record_needs_gate(record)
    if not needs_gate:
        return []
    violations: list[str] = []
    confirmation = str(record.get("confirmation_status") or "")
    if confirmation not in GATED_CONFIRMATION_VALUES:
        reason_parts = []
        if ai_info_types:
            reason_parts.append(f"information_types={sorted(ai_info_types)}")
        if source_is_ai:
            reason_parts.append("source.kind=ai")
        violations.append(
            f"record {record.get('id')!r}: confirmation_status={confirmation!r} "
            f"too strong for AI-derived record ({', '.join(reason_parts)}); "
            f"expected pending_user_confirmation or rejected."
        )
    if not record.get("needs_human_confirmation"):
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


def write_record(project_root: Path, record: dict[str, Any]) -> Path:
    normalized = normalize_record_schema(record)
    validate_write(normalized)
    root = unit_root(project_root, str(normalized["kind"]), str(normalized["id"]))
    ensure_dir(root)
    path = root / "record.yaml"
    normalized["updated_at"] = utc_now_iso()
    write_yaml_if_changed(path, normalized)
    return path


def link_records(project_root: Path, from_id: str, to_id: str, relation: str, note: str = "") -> None:
    from_record, _ = locate_record(project_root, from_id)
    to_record, _ = locate_record(project_root, to_id)
    link = {"target_id": to_id, "relation": relation, "note": note}
    back_link = {"target_id": from_id, "relation": f"reverse:{relation}", "note": note}
    if link not in from_record.setdefault("links", []):
        from_record["links"].append(link)
        append_history(from_record, action="linked", summary=f"Linked to {to_id} as {relation}.", artifacts=[])
        write_record(project_root, from_record)
    if back_link not in to_record.setdefault("links", []):
        to_record["links"].append(back_link)
        append_history(to_record, action="linked", summary=f"Linked to {from_id} as reverse:{relation}.", artifacts=[])
        write_record(project_root, to_record)


def promote_record(
    project_root: Path,
    unit_id: str,
    *,
    status: str | None = None,
    maturity: str | None = None,
    confirmation_status: str | None = None,
    confirmed_by: str = "",
    evidence: list[str] | None = None,
    confirmation_method: str = "kb.py promote",
) -> Path:
    record, _ = locate_record(project_root, unit_id)
    if status:
        record["status"] = status
    if maturity:
        record["maturity"] = maturity
    if confirmation_status:
        if confirmation_status == "confirmed":
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
    "CONFIRM_UNIT_STATUS_BY_KIND",
    "CONFIRM_UNIT_SUMMARY_BY_KIND",
    "SUBSTANCE_CONTENT_SECTIONS",
    "is_ai_signer",
    "has_substantive_content",
    "confirmation_track",
    "default_confirmed_by",
    "require_confirmation_provenance",
    "apply_confirmation",
    "confirm_unit",
    "validate_write",
    "write_record",
    "link_records",
    "promote_record",
]

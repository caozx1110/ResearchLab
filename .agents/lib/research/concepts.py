"""Mechanical concept-unit scaffolding, verification, and upstream bindings.

This module never derives a definition or decides that two research units share
a concept.  It creates fillable cells, verifies runtime-Agent authored text
against verbatim evidence, and binds the result to current confirmed units.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from .common import utc_now_iso
from .evidence import build_verification_receipt, validate_claims, verify_claim_evidence
from .ids import build_unit_id
from .records import (
    append_history,
    default_record,
    trusted_claim_source_roots,
    unit_root,
)
from .relations import normalize_links, normalize_relation_name
from .surveys import build_unit_binding, unit_bindings_equal


CONCEPT_SCHEMA_VERSION = 1
CONCEPT_MIN_INPUT_UNITS = 3
CONCEPT_SOURCE_KINDS = frozenset({"paper", "repo", "dataset", "blog", "idea", "experiment"})


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _claim_id(prefix: str, value: str = "") -> str:
    if not value:
        return prefix
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _fillable_claim(claim_id: str, *, claim_type: str = "evaluation") -> dict[str, Any]:
    return {
        "id": claim_id,
        "content": "",
        "claim_type": claim_type,
        "evidence_refs": [],
    }


def build_concept_scaffold(
    root: Path,
    *,
    canonical_name: str,
    records: list[dict[str, Any]],
    as_of: str,
) -> dict[str, Any]:
    """Return an empty concept fill; selected units must already be confirmed."""
    name = _text(canonical_name)
    if not name:
        raise ValueError("concept canonical name is required")
    if not _text(as_of):
        raise ValueError("concept prepare requires an as-of anchor")
    if len(records) < CONCEPT_MIN_INPUT_UNITS:
        raise ValueError(f"concept prepare requires at least {CONCEPT_MIN_INPUT_UNITS} confirmed units")
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        unit_id = _text(record.get("id"))
        kind = _text(record.get("kind"))
        if not unit_id or kind not in CONCEPT_SOURCE_KINDS:
            raise ValueError("concept inputs must be supported canonical source units")
        if unit_id in seen:
            raise ValueError(f"concept input unit is duplicated: {unit_id}")
        seen.add(unit_id)
        try:
            binding = build_unit_binding(root, record)
        except (OSError, SystemExit) as exc:
            raise ValueError(f"concept input is not currently confirmed: {unit_id}") from exc
        bindings.append(binding)
    bindings.sort(key=lambda item: (str(item.get("kind") or ""), str(item.get("id") or "")))
    concept_id = build_unit_id("concept", name, "")
    associations = []
    for binding in bindings:
        target_id = str(binding["id"])
        associations.append(
            {
                "target_id": target_id,
                "target_kind": str(binding["kind"]),
                "relation": "related_to",
                "role": _fillable_claim(_claim_id("claim-concept-association", target_id)),
            }
        )
    return {
        "schema_version": CONCEPT_SCHEMA_VERSION,
        "kind": "concept_fill",
        "concept_id": concept_id,
        "status": "awaiting_agent_fill",
        "concept": {
            "canonical_name": name,
            "aliases": [],
            "definition": _fillable_claim("claim-concept-definition"),
            "scope_note": _fillable_claim("claim-concept-scope", claim_type="inference"),
        },
        "anchor": {
            "as_of": _text(as_of),
            "unit_ids": [str(item["id"]) for item in bindings],
            "units": bindings,
        },
        "associations": associations,
        "fill_contract": {
            "script_authorship": "none",
            "minimum_input_units": CONCEPT_MIN_INPUT_UNITS,
            "required_claim_fields": ["id", "content", "claim_type", "evidence_refs"],
            "evidence_ref_fields": ["source_unit_id", "artifact", "locator", "quote"],
            "rule": (
                "The runtime Agent writes the definition, optional scope note, and each association role. "
                "Every authored judgement must cite verbatim evidence from the frozen input units."
            ),
        },
    }


def _claim_from_cell(cell: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(cell.get("id")),
        "text": _text(cell.get("content")),
        "claim_type": _text(cell.get("claim_type")),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": copy.deepcopy(cell.get("evidence_refs") or []),
    }


def _binding_index(anchor: Any, violations: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
    if not isinstance(anchor, dict):
        violations.append("anchor: missing or not a mapping")
        return {}, ""
    as_of = _text(anchor.get("as_of"))
    if not as_of:
        violations.append("anchor.as_of: missing")
    raw_units = anchor.get("units")
    if not isinstance(raw_units, list):
        violations.append("anchor.units: must be a list")
        raw_units = []
    if len(raw_units) < CONCEPT_MIN_INPUT_UNITS:
        violations.append(f"anchor.units: requires at least {CONCEPT_MIN_INPUT_UNITS} units")
    bindings: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_units):
        if not isinstance(item, dict):
            violations.append(f"anchor.units[{index}]: must be a mapping")
            continue
        unit_id = _text(item.get("id"))
        kind = _text(item.get("kind"))
        if not unit_id or kind not in CONCEPT_SOURCE_KINDS:
            violations.append(f"anchor.units[{index}]: unsupported canonical identity")
            continue
        if unit_id in bindings:
            violations.append(f"anchor.units[{index}]: duplicate unit id '{unit_id}'")
            continue
        bindings[unit_id] = item
    unit_ids = anchor.get("unit_ids")
    if not isinstance(unit_ids, list) or [str(item) for item in unit_ids] != [
        str(item.get("id") or "") for item in raw_units if isinstance(item, dict)
    ]:
        violations.append("anchor.unit_ids: must preserve the exact anchor.units order")
    return bindings, as_of


def concept_links_from_associations(associations: Any) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    if not isinstance(associations, list):
        return links
    for association in associations:
        if not isinstance(association, dict):
            continue
        links.append(
            {
                "target_id": _text(association.get("target_id")),
                "relation": _text(association.get("relation")) or "related_to",
                "note": _text(association.get("role")),
            }
        )
    return normalize_links(links)


def concept_lifecycle_violations(root: Path, record: Any) -> list[str]:
    """Return mechanical anchor/projection staleness for a concept record."""
    if not isinstance(record, dict) or _text(record.get("kind")) != "concept":
        return []
    violations: list[str] = []
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    bindings, _as_of = _binding_index(payload.get("anchor"), violations)
    for unit_id, binding in bindings.items():
        try:
            current = build_unit_binding(root, binding)
        except (OSError, SystemExit):
            violations.append(f"anchor unit is no longer current and confirmed: {unit_id}")
            continue
        if not unit_bindings_equal(current, binding):
            violations.append(f"anchor unit content, confirmation, or evidence changed: {unit_id}")
    associations = payload.get("associations")
    if not isinstance(associations, list):
        violations.append("payload.associations must be a list")
        associations = []
    targets = [_text(item.get("target_id")) for item in associations if isinstance(item, dict)]
    if len(targets) != len(set(targets)) or set(targets) != set(bindings):
        violations.append("payload.associations must cover each anchored unit exactly once")
    expected_links = concept_links_from_associations(associations)
    try:
        actual_links = normalize_links(record.get("links"))
    except SystemExit:
        violations.append("concept links are invalid")
    else:
        if actual_links != expected_links:
            violations.append("concept links do not match the confirmed association projection")
    return violations


def verify_concept_fill(root: Path, fill: Any) -> tuple[list[str], dict[str, Any] | None]:
    """Verify a runtime-Agent fill and return a pending canonical concept record."""
    violations: list[str] = []
    if not isinstance(fill, dict):
        return ["concept fill must be a mapping"], None
    if fill.get("schema_version") != CONCEPT_SCHEMA_VERSION or _text(fill.get("kind")) != "concept_fill":
        violations.append("concept fill schema or kind is invalid")
    concept = fill.get("concept")
    if not isinstance(concept, dict):
        violations.append("concept: missing or not a mapping")
        concept = {}
    name = _text(concept.get("canonical_name"))
    expected_id = build_unit_id("concept", name, "") if name else ""
    if not name:
        violations.append("concept.canonical_name: required")
    if _text(fill.get("concept_id")) != expected_id:
        violations.append("concept_id does not match the canonical name")
    bindings, _as_of = _binding_index(fill.get("anchor"), violations)
    for unit_id, binding in bindings.items():
        try:
            current = build_unit_binding(root, binding)
        except (OSError, SystemExit):
            violations.append(f"anchor unit is no longer current and confirmed: {unit_id}")
            continue
        if not unit_bindings_equal(current, binding):
            violations.append(f"anchor unit content, confirmation, or evidence changed: {unit_id}")

    claims: list[dict[str, Any]] = []
    definition_cell = concept.get("definition")
    if not isinstance(definition_cell, dict):
        violations.append("concept.definition: must be a fillable claim")
    else:
        definition_claim = _claim_from_cell(definition_cell)
        claims.append(definition_claim)
        if not definition_claim["text"]:
            violations.append("concept.definition: runtime Agent content is required")
        if not definition_claim["evidence_refs"]:
            violations.append("concept.definition: verbatim evidence is required")
    scope_text = ""
    scope_cell = concept.get("scope_note")
    if not isinstance(scope_cell, dict):
        violations.append("concept.scope_note: must be a fillable claim")
    else:
        scope_claim = _claim_from_cell(scope_cell)
        scope_text = scope_claim["text"]
        if scope_text:
            claims.append(scope_claim)
            if not scope_claim["evidence_refs"]:
                violations.append("concept.scope_note: non-empty content requires verbatim evidence")

    raw_associations = fill.get("associations")
    if not isinstance(raw_associations, list):
        violations.append("associations: must be a list")
        raw_associations = []
    associations: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for index, item in enumerate(raw_associations):
        label = f"associations[{index}]"
        if not isinstance(item, dict):
            violations.append(f"{label}: must be a mapping")
            continue
        target_id = _text(item.get("target_id"))
        target_kind = _text(item.get("target_kind"))
        binding = bindings.get(target_id)
        if not target_id or binding is None or target_id in seen_targets:
            violations.append(f"{label}: target must reference one unique anchored unit")
            continue
        seen_targets.add(target_id)
        if target_kind != _text(binding.get("kind")):
            violations.append(f"{label}: target_kind does not match the anchor")
        try:
            relation = normalize_relation_name(item.get("relation") or "related_to")
        except SystemExit:
            violations.append(f"{label}: relation is invalid")
            relation = "related_to"
        role_cell = item.get("role")
        if not isinstance(role_cell, dict):
            violations.append(f"{label}.role: must be a fillable claim")
            continue
        role_claim = _claim_from_cell(role_cell)
        if not role_claim["text"]:
            violations.append(f"{label}.role: runtime Agent content is required")
        if not role_claim["evidence_refs"]:
            violations.append(f"{label}.role: verbatim evidence is required")
        for ref in role_claim.get("evidence_refs") or []:
            if isinstance(ref, dict) and _text(ref.get("source_unit_id")) != target_id:
                violations.append(f"{label}.role: evidence must come from its target unit")
        claims.append(role_claim)
        associations.append(
            {
                "target_id": target_id,
                "target_kind": target_kind,
                "relation": relation,
                "role": role_claim["text"],
                "claim_id": role_claim["id"],
            }
        )
    if seen_targets != set(bindings):
        violations.append("associations must cover every anchored unit exactly once")

    claim_ids = [_text(claim.get("id")) for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        violations.append("concept claim ids must be unique")
    violations.extend(f"claim-structure: {item}" for item in validate_claims(claims))
    for claim in claims:
        for ref_index, ref in enumerate(claim.get("evidence_refs") or []):
            if not isinstance(ref, dict):
                continue
            source_id = _text(ref.get("source_unit_id"))
            binding = bindings.get(source_id)
            if binding is None:
                violations.append(f"{claim['id']}.evidence_refs[{ref_index}]: source is outside the anchor")
                continue
            artifact = _text(ref.get("artifact"))
            anchored_artifacts = {
                _text(item.get("artifact"))
                for item in binding.get("evidence_artifacts", [])
                if isinstance(item, dict)
            }
            if artifact not in anchored_artifacts:
                violations.append(f"{claim['id']}.evidence_refs[{ref_index}]: artifact was not frozen by prepare")
            if isinstance(ref.get("external_source"), dict):
                violations.append(f"{claim['id']}.evidence_refs[{ref_index}]: external source refs are not supported in concept fills")
                continue
            source_kind = _text(binding.get("kind"))
            if source_kind in CONCEPT_SOURCE_KINDS and artifact in anchored_artifacts:
                for evidence_violation in verify_claim_evidence(
                    {**claim, "evidence_refs": [ref]},
                    unit_root(root, source_kind, source_id),
                ):
                    violations.append(f"{claim['id']}: {evidence_violation}")

    aliases = []
    seen_aliases: set[str] = set()
    raw_aliases = concept.get("aliases")
    if not isinstance(raw_aliases, list):
        violations.append("concept.aliases: must be a list")
        raw_aliases = []
    for value in raw_aliases:
        alias = _text(value)
        if alias and alias != name and alias not in seen_aliases:
            seen_aliases.add(alias)
            aliases.append(alias)

    if violations:
        return violations, None
    record = default_record(
        "concept",
        title=name,
        maturity="complete",
        source={"kind": "ai", "generated_by": "literature-synthesizer"},
    )
    record["id"] = expected_id
    record["status"] = "draft"
    record["summary"] = claims[0]["text"]
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = sorted({str(claim["claim_type"]) for claim in claims})
    record["links"] = concept_links_from_associations(associations)
    record["payload"] = {
        "concept": {
            "canonical_name": name,
            "aliases": aliases,
            "definition": claims[0]["text"],
            "scope_note": scope_text,
        },
        "associations": associations,
        "anchor": copy.deepcopy(fill.get("anchor")),
        "claims": claims,
        "verification": {},
        "state": {"concept_status": "pending_user_confirmation"},
    }
    source_roots = trusted_claim_source_roots(
        root,
        record,
        verification_root=unit_root(root, "concept", expected_id),
    )
    try:
        build_verification_receipt(
            record,
            unit_root(root, "concept", expected_id),
            source_roots=source_roots,
            verified_at=utc_now_iso(),
        )
    except SystemExit as exc:
        return [str(exc)], None
    append_history(
        record,
        action="concept-verified",
        summary="Concept definition and associations verified against anchored units.",
        information_types=list(record["information_types"]),
    )
    lifecycle = concept_lifecycle_violations(root, record)
    if lifecycle:
        return lifecycle, None
    return [], record


__all__ = [
    "CONCEPT_MIN_INPUT_UNITS",
    "CONCEPT_SCHEMA_VERSION",
    "CONCEPT_SOURCE_KINDS",
    "build_concept_scaffold",
    "concept_lifecycle_violations",
    "concept_links_from_associations",
    "verify_concept_fill",
]

"""Pure contracts for evidence-bound, section-level paper drafting.

The functions in this module do not write files and never author prose.  They
build empty Agent fill scaffolds, validate exact upstream bindings, mechanically
copy evidence from confirmed support claims, and render already-confirmed
sections as Markdown or escaped LaTeX.  Filesystem snapshot capture,
ConfirmationReceipt validation, recovery transactions, and publication writes
remain owner/integration responsibilities.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .evidence import CLAIM_TYPES, UNCONFIRMABLE_CLAIM_TYPES, validate_claims


PAPER_DRAFT_SCHEMA_VERSION = 1
PAPER_DRAFT_MANIFEST_KIND = "paper_draft_manifest"
PAPER_DRAFT_FILL_KIND = "paper_draft_section_fill"
PAPER_DRAFT_SECTION_KIND = "paper_draft_section"
PAPER_DRAFT_OWNER = "report-author"

SECTION_IDENTITIES = (
    "introduction",
    "related-work",
    "method",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)
SECTION_TITLES = {
    "introduction": "Introduction",
    "related-work": "Related Work",
    "method": "Method",
    "experiments": "Experiments",
    "results": "Results",
    "discussion": "Discussion",
    "conclusion": "Conclusion",
}

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_REFERENCE_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}")
_MANIFEST_FIELDS = {
    "schema_version",
    "kind",
    "program_id",
    "as_of",
    "outline",
    "sections",
    "catalogs",
    "anchor_digest",
}
_FILL_FIELDS = {
    "schema_version",
    "kind",
    "program_id",
    "section_id",
    "section_title",
    "manifest_anchor_digest",
    "status",
    "paragraphs",
    "fill_contract",
}
_PARAGRAPH_FIELDS = {
    "paragraph_id",
    "prose",
    "claim_type",
    "support_claim_refs",
    "citation_keys",
    "figure_refs",
}
_EVIDENCE_REF_FIELDS = ("source_unit_id", "artifact", "locator", "quote")

BindingResolver = Callable[[str], Optional[Mapping[str, Any]]]
SectionPredicate = Callable[[Mapping[str, Any]], bool]


def _exact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _exact_digest(value: Any) -> str:
    return hashlib.sha256(_exact_json(value).encode("utf-8")).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _valid_digest(value: Any) -> bool:
    return _DIGEST_RE.fullmatch(str(value or "")) is not None


def _valid_reference_key(value: Any) -> bool:
    return _REFERENCE_KEY_RE.fullmatch(str(value or "")) is not None


def _catalog_entries(
    values: Mapping[str, Mapping[str, Any]],
    *,
    key_name: str,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{label} catalog must be a mapping")
    entries: list[dict[str, Any]] = []
    for raw_key, raw_binding in values.items():
        key = str(raw_key or "")
        if not _valid_reference_key(key):
            raise ValueError(f"{label} catalog has an invalid stable key: {key!r}")
        if not isinstance(raw_binding, Mapping) or not raw_binding:
            raise ValueError(f"{label} catalog binding must be a non-empty mapping: {key}")
        binding = copy.deepcopy(dict(raw_binding))
        entries.append({key_name: key, "binding": binding})
    entries.sort(key=lambda item: str(item[key_name]))
    return entries


def _claim_binding_violations(binding: Any, *, label: str) -> list[str]:
    if not isinstance(binding, Mapping):
        return [f"{label}: binding must be a mapping"]
    violations: list[str] = []
    for field in ("source_unit_id", "claim_id"):
        if not _text(binding.get(field)):
            violations.append(f"{label}: missing {field}")
    if _text(binding.get("confirmation_status")) != "confirmed":
        violations.append(f"{label}: support claim is not confirmed")
    for field in (
        "claim_digest",
        "record_content_digest",
        "confirmation_receipt_digest",
        "evidence_digest",
    ):
        if not _valid_digest(binding.get(field)):
            violations.append(f"{label}: {field} must be a sha256 digest")
    refs = binding.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        violations.append(f"{label}: support claim needs verbatim evidence_refs")
        refs = []
    for index, ref in enumerate(refs):
        ref_label = f"{label}.evidence_refs[{index}]"
        if not isinstance(ref, Mapping):
            violations.append(f"{ref_label}: must be a mapping")
            continue
        for field in _EVIDENCE_REF_FIELDS:
            if not isinstance(ref.get(field), str) or not str(ref[field]).strip():
                violations.append(f"{ref_label}: missing {field}")
    return violations


def _catalog_index(
    manifest: Mapping[str, Any],
    *,
    catalog_name: str,
    key_name: str,
    violations: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    catalogs = manifest.get("catalogs")
    raw_entries = catalogs.get(catalog_name) if isinstance(catalogs, Mapping) else None
    if not isinstance(raw_entries, list):
        if violations is not None:
            violations.append(f"manifest.catalogs.{catalog_name} must be a list")
        return found
    previous = ""
    for index, item in enumerate(raw_entries):
        label = f"manifest.catalogs.{catalog_name}[{index}]"
        if not isinstance(item, Mapping) or set(item) != {key_name, "binding"}:
            if violations is not None:
                violations.append(f"{label} must contain exactly {key_name} and binding")
            continue
        key = str(item.get(key_name) or "")
        binding = item.get("binding")
        if not _valid_reference_key(key):
            if violations is not None:
                violations.append(f"{label}.{key_name} is invalid")
            continue
        if key in found:
            if violations is not None:
                violations.append(f"{label}.{key_name} is duplicated")
            continue
        if previous and key <= previous and violations is not None:
            violations.append(f"manifest.catalogs.{catalog_name} must be strictly sorted")
        previous = key
        if not isinstance(binding, Mapping) or not binding:
            if violations is not None:
                violations.append(f"{label}.binding must be a non-empty mapping")
            continue
        found[key] = copy.deepcopy(dict(binding))
    return found


def _manifest_anchor_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest.get("schema_version"),
        "kind": manifest.get("kind"),
        "program_id": manifest.get("program_id"),
        "as_of": manifest.get("as_of"),
        "outline": manifest.get("outline"),
        "sections": manifest.get("sections"),
        "catalogs": manifest.get("catalogs"),
    }


def draft_manifest_anchor_digest(manifest: Mapping[str, Any]) -> str:
    """Digest exact outline/catalog/section bindings, preserving prose bytes."""
    return _exact_digest(_manifest_anchor_payload(manifest))


def draft_manifest_structure_violations(manifest: Any) -> list[str]:
    violations: list[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest must be a mapping"]
    if set(manifest) != _MANIFEST_FIELDS:
        violations.append("manifest has missing or unexpected top-level fields")
    if manifest.get("schema_version") != PAPER_DRAFT_SCHEMA_VERSION:
        violations.append("manifest schema_version is invalid")
    if _text(manifest.get("kind")) != PAPER_DRAFT_MANIFEST_KIND:
        violations.append("manifest kind is invalid")
    if not _valid_reference_key(manifest.get("program_id")):
        violations.append("manifest program_id is invalid")
    if not _text(manifest.get("as_of")):
        violations.append("manifest as_of is required")
    outline = manifest.get("outline")
    if not isinstance(outline, Mapping) or set(outline) != {"byte_sha256", "byte_count"}:
        violations.append("manifest outline binding must contain byte_sha256 and byte_count")
    else:
        if not _valid_digest(outline.get("byte_sha256")):
            violations.append("manifest outline byte_sha256 is invalid")
        if not isinstance(outline.get("byte_count"), int) or int(outline.get("byte_count", -1)) < 0:
            violations.append("manifest outline byte_count is invalid")
    expected_sections = [
        {"id": section_id, "title": SECTION_TITLES[section_id], "order": order}
        for order, section_id in enumerate(SECTION_IDENTITIES, start=1)
    ]
    if manifest.get("sections") != expected_sections:
        violations.append("manifest sections must be the fixed ordered seven-section identity list")
    claim_index = _catalog_index(
        manifest,
        catalog_name="claims",
        key_name="ref_key",
        violations=violations,
    )
    _catalog_index(
        manifest,
        catalog_name="bibliography",
        key_name="citation_key",
        violations=violations,
    )
    _catalog_index(
        manifest,
        catalog_name="figures",
        key_name="ref_key",
        violations=violations,
    )
    catalogs = manifest.get("catalogs")
    if not isinstance(catalogs, Mapping) or set(catalogs) != {"claims", "bibliography", "figures"}:
        violations.append("manifest catalogs must contain exactly claims, bibliography, and figures")
    for key, binding in claim_index.items():
        violations.extend(_claim_binding_violations(binding, label=f"claim catalog {key}"))
    if not _valid_digest(manifest.get("anchor_digest")):
        violations.append("manifest anchor_digest is invalid")
    elif str(manifest.get("anchor_digest")) != draft_manifest_anchor_digest(manifest):
        violations.append("manifest anchor_digest does not match its exact contents")
    return violations


def build_draft_manifest(
    *,
    program_id: str,
    outline_bytes: bytes,
    claim_catalog: Mapping[str, Mapping[str, Any]],
    bibliography_catalog: Mapping[str, Mapping[str, Any]],
    figure_catalog: Mapping[str, Mapping[str, Any]],
    as_of: str,
) -> dict[str, Any]:
    """Freeze exact outline bytes and deterministic, owner-built catalogs."""
    if not _valid_reference_key(program_id):
        raise ValueError("program_id must be a stable reference-safe identity")
    if not isinstance(outline_bytes, bytes):
        raise TypeError("outline_bytes must be bytes")
    if not _text(as_of):
        raise ValueError("manifest as_of is required")
    manifest: dict[str, Any] = {
        "schema_version": PAPER_DRAFT_SCHEMA_VERSION,
        "kind": PAPER_DRAFT_MANIFEST_KIND,
        "program_id": program_id,
        "as_of": str(as_of),
        "outline": {
            "byte_sha256": _bytes_digest(outline_bytes),
            "byte_count": len(outline_bytes),
        },
        "sections": [
            {"id": section_id, "title": SECTION_TITLES[section_id], "order": order}
            for order, section_id in enumerate(SECTION_IDENTITIES, start=1)
        ],
        "catalogs": {
            "claims": _catalog_entries(claim_catalog, key_name="ref_key", label="claim"),
            "bibliography": _catalog_entries(
                bibliography_catalog,
                key_name="citation_key",
                label="bibliography",
            ),
            "figures": _catalog_entries(figure_catalog, key_name="ref_key", label="figure"),
        },
        "anchor_digest": "",
    }
    manifest["anchor_digest"] = draft_manifest_anchor_digest(manifest)
    violations = draft_manifest_structure_violations(manifest)
    if violations:
        raise ValueError("invalid paper draft manifest: " + "; ".join(violations))
    return manifest


def draft_manifest_currentness_violations(
    manifest: Any,
    *,
    outline_bytes: bytes,
    claim_catalog: Mapping[str, Mapping[str, Any]],
    bibliography_catalog: Mapping[str, Mapping[str, Any]],
    figure_catalog: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Compare a frozen manifest with exact current owner-provided snapshots."""
    violations = draft_manifest_structure_violations(manifest)
    if violations or not isinstance(manifest, Mapping):
        return violations
    try:
        current = build_draft_manifest(
            program_id=str(manifest["program_id"]),
            outline_bytes=outline_bytes,
            claim_catalog=claim_catalog,
            bibliography_catalog=bibliography_catalog,
            figure_catalog=figure_catalog,
            as_of=str(manifest["as_of"]),
        )
    except (TypeError, ValueError) as exc:
        return [f"current manifest inputs are invalid: {exc}"]
    if current["outline"] != manifest.get("outline"):
        violations.append("paper outline bytes changed")
    if current["catalogs"] != manifest.get("catalogs"):
        violations.append("paper draft claim, bibliography, or figure catalog changed")
    if current["anchor_digest"] != manifest.get("anchor_digest"):
        violations.append("paper draft manifest anchor is stale")
    return violations


def _manifest_section(manifest: Mapping[str, Any], section_id: str) -> dict[str, Any] | None:
    for section in manifest.get("sections", []):
        if isinstance(section, Mapping) and section.get("id") == section_id:
            return dict(section)
    return None


def build_section_fill_scaffold(manifest: Mapping[str, Any], section_id: str) -> dict[str, Any]:
    """Return one empty paragraph cell; only a runtime Agent may fill prose."""
    violations = draft_manifest_structure_violations(manifest)
    if violations:
        raise ValueError("invalid paper draft manifest: " + "; ".join(violations))
    section = _manifest_section(manifest, section_id)
    if section is None:
        raise ValueError(f"unknown paper draft section: {section_id}")
    return {
        "schema_version": PAPER_DRAFT_SCHEMA_VERSION,
        "kind": PAPER_DRAFT_FILL_KIND,
        "program_id": str(manifest["program_id"]),
        "section_id": section_id,
        "section_title": str(section["title"]),
        "manifest_anchor_digest": str(manifest["anchor_digest"]),
        "status": "awaiting_agent_fill",
        "paragraphs": [
            {
                "paragraph_id": "paragraph-001",
                "prose": "",
                "claim_type": "",
                "support_claim_refs": [],
                "citation_keys": [],
                "figure_refs": [],
            }
        ],
        "fill_contract": {
            "script_authorship": "none",
            "prose_format": "plain_text",
            "raw_latex": "forbidden",
            "support_rule": "Every paragraph cites at least one frozen current confirmed claim.",
        },
    }


def _string_ref_list(value: Any, *, label: str, required: bool) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    if not isinstance(value, list):
        return [], [f"{label} must be a list"]
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        key = str(item or "")
        if not _valid_reference_key(key):
            violations.append(f"{label}[{index}] is not a valid stable key")
            continue
        if key in seen:
            violations.append(f"{label}[{index}] is duplicated")
            continue
        seen.add(key)
        result.append(key)
    if required and not result:
        violations.append(f"{label} must not be empty")
    return result, violations


def section_fill_shape_violations(fill: Any, manifest: Any) -> list[str]:
    violations = draft_manifest_structure_violations(manifest)
    if not isinstance(fill, Mapping):
        return [*violations, "section fill must be a mapping"]
    if set(fill) != _FILL_FIELDS:
        violations.append("section fill has missing or unexpected top-level fields")
    if fill.get("schema_version") != PAPER_DRAFT_SCHEMA_VERSION:
        violations.append("section fill schema_version is invalid")
    if _text(fill.get("kind")) != PAPER_DRAFT_FILL_KIND:
        violations.append("section fill kind is invalid")
    if not isinstance(manifest, Mapping):
        return violations
    if _text(fill.get("program_id")) != _text(manifest.get("program_id")):
        violations.append("section fill program_id does not match the manifest")
    section_id = _text(fill.get("section_id"))
    section = _manifest_section(manifest, section_id)
    if section is None:
        violations.append("section fill has an unknown section_id")
    elif _text(fill.get("section_title")) != _text(section.get("title")):
        violations.append("section fill title does not match its fixed section identity")
    if _text(fill.get("manifest_anchor_digest")) != _text(manifest.get("anchor_digest")):
        violations.append("section fill manifest binding is stale")
    if _text(fill.get("status")) != "awaiting_agent_fill":
        violations.append("section fill status is invalid")
    contract = fill.get("fill_contract")
    if not isinstance(contract, Mapping) or contract.get("raw_latex") != "forbidden":
        violations.append("section fill contract must forbid raw LaTeX")
    paragraphs = fill.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        violations.append("section fill paragraphs must be a non-empty list")
        return violations
    seen_ids: set[str] = set()
    for index, paragraph in enumerate(paragraphs):
        label = f"paragraphs[{index}]"
        if not isinstance(paragraph, Mapping):
            violations.append(f"{label} must be a mapping")
            continue
        if set(paragraph) != _PARAGRAPH_FIELDS:
            violations.append(f"{label} has missing or unexpected fields (raw markup is forbidden)")
        paragraph_id = _text(paragraph.get("paragraph_id"))
        expected_id = f"paragraph-{index + 1:03d}"
        if paragraph_id != expected_id:
            violations.append(f"{label}.paragraph_id must be {expected_id}")
        if paragraph_id in seen_ids:
            violations.append(f"{label}.paragraph_id is duplicated")
        seen_ids.add(paragraph_id)
        prose = paragraph.get("prose")
        if not isinstance(prose, str) or not prose.strip():
            violations.append(f"{label}.prose requires runtime-Agent authored text")
        elif "\x00" in prose:
            violations.append(f"{label}.prose contains a forbidden NUL byte")
        claim_type = _text(paragraph.get("claim_type"))
        if claim_type not in CLAIM_TYPES or claim_type in UNCONFIRMABLE_CLAIM_TYPES:
            violations.append(f"{label}.claim_type must be a confirmable epistemic type")
        for field, required in (
            ("support_claim_refs", True),
            ("citation_keys", True),
            ("figure_refs", False),
        ):
            _values, ref_violations = _string_ref_list(
                paragraph.get(field),
                label=f"{label}.{field}",
                required=required,
            )
            violations.extend(ref_violations)
    return violations


def _current_binding(
    key: str,
    *,
    frozen: Mapping[str, Any],
    resolver: BindingResolver | None,
    label: str,
    violations: list[str],
) -> dict[str, Any] | None:
    if resolver is None:
        violations.append(f"{label} {key} cannot be checked without a current binding resolver")
        return None
    try:
        current = resolver(key)
    except Exception as exc:  # integration callbacks are an untrusted boundary
        violations.append(f"{label} {key} currentness check failed: {type(exc).__name__}")
        return None
    if not isinstance(current, Mapping):
        violations.append(f"{label} {key} is missing or no longer current")
        return None
    if dict(current) != dict(frozen):
        violations.append(f"{label} {key} binding changed")
        return None
    return copy.deepcopy(dict(current))


def _section_anchor(
    manifest: Mapping[str, Any],
    *,
    section_id: str,
    support_keys: Iterable[str],
    citation_keys: Iterable[str],
    figure_keys: Iterable[str],
) -> dict[str, Any]:
    claim_index = _catalog_index(manifest, catalog_name="claims", key_name="ref_key")
    bib_index = _catalog_index(
        manifest,
        catalog_name="bibliography",
        key_name="citation_key",
    )
    figure_index = _catalog_index(manifest, catalog_name="figures", key_name="ref_key")
    return {
        "manifest_anchor_digest": str(manifest.get("anchor_digest") or ""),
        "outline_byte_sha256": str((manifest.get("outline") or {}).get("byte_sha256") or ""),
        "section_id": section_id,
        "support_claims": [
            {"ref_key": key, "binding": copy.deepcopy(claim_index[key])}
            for key in sorted(set(support_keys))
        ],
        "citations": [
            {"citation_key": key, "binding": copy.deepcopy(bib_index[key])}
            for key in sorted(set(citation_keys))
        ],
        "figures": [
            {"ref_key": key, "binding": copy.deepcopy(figure_index[key])}
            for key in sorted(set(figure_keys))
        ],
    }


def paper_draft_section_anchor_digest(record_or_anchor: Mapping[str, Any]) -> str:
    anchor: Any = record_or_anchor
    if "payload" in record_or_anchor:
        payload = record_or_anchor.get("payload")
        anchor = payload.get("anchor") if isinstance(payload, Mapping) else None
    return _exact_digest(anchor if isinstance(anchor, Mapping) else {})


def paper_draft_section_content_digest(record: Mapping[str, Any]) -> str:
    payload = record.get("payload") if isinstance(record, Mapping) else None
    payload = payload if isinstance(payload, Mapping) else {}
    return _exact_digest(
        {
            "kind": record.get("kind") if isinstance(record, Mapping) else None,
            "id": record.get("id") if isinstance(record, Mapping) else None,
            "program_id": record.get("program_id") if isinstance(record, Mapping) else None,
            "section_id": record.get("section_id") if isinstance(record, Mapping) else None,
            "paper_draft_section": payload.get("paper_draft_section"),
            "claims": payload.get("claims"),
            "anchor": payload.get("anchor"),
        }
    )


def verify_section_fill(
    fill: Any,
    manifest: Any,
    *,
    resolve_support: BindingResolver | None,
    resolve_citation: BindingResolver | None,
    resolve_figure: BindingResolver | None,
    verified_at: str = "",
) -> tuple[list[str], dict[str, Any] | None]:
    """Validate Agent prose and build one pending, evidence-carrying judgement."""
    violations = section_fill_shape_violations(fill, manifest)
    if not isinstance(fill, Mapping) or not isinstance(manifest, Mapping):
        return violations, None
    claim_index = _catalog_index(manifest, catalog_name="claims", key_name="ref_key")
    bib_index = _catalog_index(
        manifest,
        catalog_name="bibliography",
        key_name="citation_key",
    )
    figure_index = _catalog_index(manifest, catalog_name="figures", key_name="ref_key")
    paragraphs = fill.get("paragraphs") if isinstance(fill.get("paragraphs"), list) else []
    canonical_paragraphs: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    used_support: list[str] = []
    used_citations: list[str] = []
    used_figures: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if not isinstance(paragraph, Mapping):
            continue
        label = f"paragraphs[{index}]"
        support_keys, _ = _string_ref_list(
            paragraph.get("support_claim_refs"), label=f"{label}.support_claim_refs", required=True
        )
        citation_keys, _ = _string_ref_list(
            paragraph.get("citation_keys"), label=f"{label}.citation_keys", required=True
        )
        figure_keys, _ = _string_ref_list(
            paragraph.get("figure_refs"), label=f"{label}.figure_refs", required=False
        )
        evidence_refs: list[dict[str, Any]] = []
        for key in support_keys:
            frozen = claim_index.get(key)
            if frozen is None:
                violations.append(f"{label}.support_claim_refs references unknown claim: {key}")
                continue
            current = _current_binding(
                key,
                frozen=frozen,
                resolver=resolve_support,
                label="support claim",
                violations=violations,
            )
            if current is None:
                continue
            binding_violations = _claim_binding_violations(current, label=f"support claim {key}")
            violations.extend(binding_violations)
            if not binding_violations:
                evidence_refs.extend(copy.deepcopy(current["evidence_refs"]))
        for key in citation_keys:
            frozen = bib_index.get(key)
            if frozen is None:
                violations.append(f"{label}.citation_keys references unknown citation: {key}")
                continue
            _current_binding(
                key,
                frozen=frozen,
                resolver=resolve_citation,
                label="citation",
                violations=violations,
            )
        for key in figure_keys:
            frozen = figure_index.get(key)
            if frozen is None:
                violations.append(f"{label}.figure_refs references unknown figure: {key}")
                continue
            _current_binding(
                key,
                frozen=frozen,
                resolver=resolve_figure,
                label="figure",
                violations=violations,
            )
        paragraph_id = _text(paragraph.get("paragraph_id"))
        prose = paragraph.get("prose") if isinstance(paragraph.get("prose"), str) else ""
        claim = {
            "id": f"claim-paper-draft-{_text(fill.get('section_id'))}-{paragraph_id}",
            "text": prose,
            "claim_type": _text(paragraph.get("claim_type")),
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": evidence_refs,
        }
        claims.append(claim)
        canonical_paragraphs.append(
            {
                "paragraph_id": paragraph_id,
                "prose": prose,
                "claim_type": claim["claim_type"],
                "support_claim_refs": support_keys,
                "citation_keys": citation_keys,
                "figure_refs": figure_keys,
                "claim_id": claim["id"],
            }
        )
        used_support.extend(support_keys)
        used_citations.extend(citation_keys)
        used_figures.extend(figure_keys)
    violations.extend(f"claim structure: {item}" for item in validate_claims(claims))
    if violations:
        return violations, None
    section_id = _text(fill.get("section_id"))
    section = _manifest_section(manifest, section_id)
    if section is None:  # already reported by shape validation; keep total
        return ["section fill has an unknown section_id"], None
    program_id = _text(manifest.get("program_id"))
    record: dict[str, Any] = {
        "schema_version": PAPER_DRAFT_SCHEMA_VERSION,
        "id": f"paper-draft-section:{program_id}:{section_id}",
        "kind": PAPER_DRAFT_SECTION_KIND,
        "owner": PAPER_DRAFT_OWNER,
        "program_id": program_id,
        "section_id": section_id,
        "status": "draft",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": sorted({str(claim["claim_type"]) for claim in claims}),
        "payload": {
            "paper_draft_section": {
                "section_id": section_id,
                "title": str(section["title"]),
                "order": int(section["order"]),
                "paragraphs": canonical_paragraphs,
            },
            "claims": claims,
            "anchor": _section_anchor(
                manifest,
                section_id=section_id,
                support_keys=used_support,
                citation_keys=used_citations,
                figure_keys=used_figures,
            ),
            "verification": {
                "verified_at": str(verified_at or ""),
                "integration_status": "requires_evidence_receipt",
            },
        },
    }
    return [], record


def _anchor_binding_index(anchor: Mapping[str, Any], name: str, key_name: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    entries = anchor.get(name)
    if not isinstance(entries, list):
        return result
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        key = _text(item.get(key_name))
        binding = item.get("binding")
        if key and isinstance(binding, Mapping) and key not in result:
            result[key] = dict(binding)
    return result


def paper_draft_section_lifecycle_violations(
    record: Any,
    manifest: Any,
    *,
    resolve_support: BindingResolver | None,
    resolve_citation: BindingResolver | None,
    resolve_figure: BindingResolver | None,
    manifest_is_current: Callable[[Mapping[str, Any]], bool] | None = None,
) -> list[str]:
    """Return mechanical reasons a verified/confirmed section is stale."""
    violations = draft_manifest_structure_violations(manifest)
    if not isinstance(record, Mapping):
        return [*violations, "paper draft section record must be a mapping"]
    if not isinstance(manifest, Mapping):
        return violations
    program_id = _text(manifest.get("program_id"))
    section_id = _text(record.get("section_id"))
    expected_id = f"paper-draft-section:{program_id}:{section_id}"
    if _text(record.get("kind")) != PAPER_DRAFT_SECTION_KIND:
        violations.append("paper draft section kind is invalid")
    if _text(record.get("owner")) != PAPER_DRAFT_OWNER:
        violations.append("paper draft section owner is invalid")
    if _text(record.get("program_id")) != program_id or _text(record.get("id")) != expected_id:
        violations.append("paper draft section canonical identity is invalid")
    section = _manifest_section(manifest, section_id)
    if section is None:
        violations.append("paper draft section is absent from the manifest")
    if manifest_is_current is None:
        violations.append("paper draft manifest currentness was not checked")
    else:
        try:
            if not manifest_is_current(manifest):
                violations.append("paper draft manifest is stale")
        except Exception as exc:
            violations.append(f"paper draft manifest currentness check failed: {type(exc).__name__}")
    payload = record.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    substance = payload.get("paper_draft_section")
    substance = substance if isinstance(substance, Mapping) else {}
    anchor = payload.get("anchor")
    anchor = anchor if isinstance(anchor, Mapping) else {}
    if set(anchor) != {
        "manifest_anchor_digest",
        "outline_byte_sha256",
        "section_id",
        "support_claims",
        "citations",
        "figures",
    }:
        violations.append("paper draft section anchor has missing or unexpected fields")
    if _text(anchor.get("manifest_anchor_digest")) != _text(manifest.get("anchor_digest")):
        violations.append("paper draft section manifest anchor changed")
    manifest_outline = manifest.get("outline")
    manifest_outline = manifest_outline if isinstance(manifest_outline, Mapping) else {}
    if _text(anchor.get("outline_byte_sha256")) != _text(manifest_outline.get("byte_sha256")):
        violations.append("paper draft section outline binding changed")
    if _text(anchor.get("section_id")) != section_id:
        violations.append("paper draft section anchor identity changed")
    if section is not None and (
        _text(substance.get("section_id")) != section_id
        or _text(substance.get("title")) != _text(section.get("title"))
        or substance.get("order") != section.get("order")
    ):
        violations.append("paper draft section substance does not match its fixed section identity")
    frozen_indexes = (
        ("support_claims", "ref_key", resolve_support, "support claim"),
        ("citations", "citation_key", resolve_citation, "citation"),
        ("figures", "ref_key", resolve_figure, "figure"),
    )
    anchor_indexes: dict[str, dict[str, dict[str, Any]]] = {}
    for name, key_name, resolver, label in frozen_indexes:
        index = _anchor_binding_index(anchor, name, key_name)
        anchor_indexes[name] = index
        raw_items = anchor.get(name)
        expected_items = [
            {key_name: key, "binding": binding}
            for key, binding in sorted(index.items())
        ]
        if raw_items != expected_items:
            violations.append(f"paper draft section anchor {name} must be exact, unique, and sorted")
        for key, binding in index.items():
            _current_binding(
                key,
                frozen=binding,
                resolver=resolver,
                label=label,
                violations=violations,
            )
    paragraphs = substance.get("paragraphs")
    claims = payload.get("claims")
    if not isinstance(paragraphs, list) or not isinstance(claims, list) or len(paragraphs) != len(claims):
        violations.append("paper draft section paragraphs and claims must align one-to-one")
    else:
        used_support: list[str] = []
        used_citations: list[str] = []
        used_figures: list[str] = []
        for index, (paragraph, claim) in enumerate(zip(paragraphs, claims)):
            if not isinstance(paragraph, Mapping) or not isinstance(claim, Mapping):
                violations.append(f"paper draft section paragraph/claim {index} is malformed")
                continue
            if (
                _text(paragraph.get("claim_id")) != _text(claim.get("id"))
                or paragraph.get("prose") != claim.get("text")
                or _text(paragraph.get("claim_type")) != _text(claim.get("claim_type"))
            ):
                violations.append(f"paper draft paragraph {index} does not match its canonical claim")
            support_index = _anchor_binding_index(anchor, "support_claims", "ref_key")
            paragraph_support = paragraph.get("support_claim_refs")
            paragraph_citations = paragraph.get("citation_keys")
            paragraph_figures = paragraph.get("figure_refs")
            if not all(isinstance(value, list) for value in (paragraph_support, paragraph_citations, paragraph_figures)):
                violations.append(f"paper draft paragraph {index} reference fields must be lists")
                paragraph_support = []
                paragraph_citations = []
                paragraph_figures = []
            used_support.extend(str(value) for value in paragraph_support)
            used_citations.extend(str(value) for value in paragraph_citations)
            used_figures.extend(str(value) for value in paragraph_figures)
            expected_refs = [
                copy.deepcopy(ref)
                for key in paragraph_support
                if key in support_index
                for ref in support_index[key].get("evidence_refs", [])
                if isinstance(ref, Mapping)
            ]
            if claim.get("evidence_refs") != expected_refs:
                violations.append(f"paper draft claim {index} evidence is not the mechanical support projection")
        for name, used in (
            ("support_claims", used_support),
            ("citations", used_citations),
            ("figures", used_figures),
        ):
            if set(used) != set(anchor_indexes.get(name, {})):
                violations.append(f"paper draft paragraph refs do not match anchor {name}")
    violations.extend(f"claim structure: {item}" for item in validate_claims(claims))
    return violations


def _publication_section_index(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    section_is_current: SectionPredicate,
    confirmation_is_current: SectionPredicate,
) -> tuple[list[str], list[Mapping[str, Any]]]:
    violations = draft_manifest_structure_violations(manifest)
    found: dict[str, Mapping[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            violations.append(f"publication sections[{index}] must be a mapping")
            continue
        section_id = _text(record.get("section_id"))
        if section_id not in SECTION_IDENTITIES:
            violations.append(f"publication sections[{index}] has an unknown section identity")
            continue
        if section_id in found:
            violations.append(f"publication section is duplicated: {section_id}")
            continue
        found[section_id] = record
        if _text(record.get("kind")) != PAPER_DRAFT_SECTION_KIND or _text(record.get("owner")) != PAPER_DRAFT_OWNER:
            violations.append(f"publication section has invalid kind/owner: {section_id}")
        expected_id = f"paper-draft-section:{_text(manifest.get('program_id'))}:{section_id}"
        if (
            _text(record.get("program_id")) != _text(manifest.get("program_id"))
            or _text(record.get("id")) != expected_id
        ):
            violations.append(f"publication section has invalid canonical identity: {section_id}")
        if _text(record.get("confirmation_status")) != "confirmed":
            violations.append(f"publication section is not confirmed: {section_id}")
        payload = record.get("payload")
        verification = payload.get("verification") if isinstance(payload, Mapping) else None
        if not isinstance(verification, Mapping) or not _text(verification.get("verified_at")):
            violations.append(f"publication section has no verification receipt: {section_id}")
        elif any(
            not _valid_digest(verification.get(field))
            for field in ("claims_digest", "evidence_digest")
        ):
            violations.append(f"publication section verification receipt is incomplete: {section_id}")
        try:
            if not section_is_current(record):
                violations.append(f"publication section is stale: {section_id}")
        except Exception as exc:
            violations.append(f"publication section currentness check failed for {section_id}: {type(exc).__name__}")
        try:
            if not confirmation_is_current(record):
                violations.append(f"publication section receipt is missing or stale: {section_id}")
        except Exception as exc:
            violations.append(f"publication section receipt check failed for {section_id}: {type(exc).__name__}")
    missing = [section_id for section_id in SECTION_IDENTITIES if section_id not in found]
    if missing:
        violations.append("publication requires all seven sections: missing " + ", ".join(missing))
    ordered = [found[section_id] for section_id in SECTION_IDENTITIES if section_id in found]
    supplied_order = [_text(record.get("section_id")) for record in records]
    if not missing and supplied_order != list(SECTION_IDENTITIES):
        violations.append("publication sections must be supplied in manifest order")
    return violations, ordered


def validate_publication_sections(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    section_is_current: SectionPredicate,
    confirmation_is_current: SectionPredicate,
) -> list[str]:
    violations, _ordered = _publication_section_index(
        manifest,
        records,
        section_is_current=section_is_current,
        confirmation_is_current=confirmation_is_current,
    )
    return violations


def _escape_markdown_plain_text(text: str) -> str:
    escaped = text.replace("\\", "\\\\")
    escaped = re.sub(r"([`*_{}\[\]()#+.!|>~-])", r"\\\1", escaped)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "  \n")


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(char, char) for char in text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")


def _renderable_sections(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    section_is_current: SectionPredicate,
    confirmation_is_current: SectionPredicate,
) -> list[Mapping[str, Any]]:
    violations, ordered = _publication_section_index(
        manifest,
        records,
        section_is_current=section_is_current,
        confirmation_is_current=confirmation_is_current,
    )
    if violations:
        raise ValueError("paper draft publication gate failed: " + "; ".join(violations))
    return ordered


def render_paper_draft_markdown(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    section_is_current: SectionPredicate,
    confirmation_is_current: SectionPredicate,
    title: str = "",
) -> str:
    ordered = _renderable_sections(
        manifest,
        records,
        section_is_current=section_is_current,
        confirmation_is_current=confirmation_is_current,
    )
    lines = [f"# {_escape_markdown_plain_text(title or str(manifest['program_id']))}", ""]
    for record in ordered:
        substance = record["payload"]["paper_draft_section"]
        lines.extend([f"## {_escape_markdown_plain_text(str(substance['title']))}", ""])
        for paragraph in substance["paragraphs"]:
            lines.append(_escape_markdown_plain_text(str(paragraph["prose"])))
            citations = list(paragraph.get("citation_keys") or [])
            figures = list(paragraph.get("figure_refs") or [])
            if citations:
                lines.extend(["", "Citations: " + "; ".join(f"[@{key}]" for key in citations)])
            if figures:
                lines.extend(["", "Figure refs: " + ", ".join(f"`{key}`" for key in figures)])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_paper_draft_latex(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    section_is_current: SectionPredicate,
    confirmation_is_current: SectionPredicate,
    title: str = "",
) -> str:
    ordered = _renderable_sections(
        manifest,
        records,
        section_is_current=section_is_current,
        confirmation_is_current=confirmation_is_current,
    )
    lines = [
        r"\documentclass{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{graphicx}",
        r"\title{" + _escape_latex(title or str(manifest["program_id"])) + "}",
        r"\begin{document}",
        r"\maketitle",
        "",
    ]
    for record in ordered:
        substance = record["payload"]["paper_draft_section"]
        lines.extend([r"\section{" + _escape_latex(str(substance["title"])) + "}", ""])
        for paragraph in substance["paragraphs"]:
            lines.append(_escape_latex(str(paragraph["prose"])))
            citations = list(paragraph.get("citation_keys") or [])
            figures = list(paragraph.get("figure_refs") or [])
            if citations:
                lines.append(r"\cite{" + ",".join(citations) + "}")
            if figures:
                lines.append(
                    r"\textit{Figure references: "
                    + _escape_latex(", ".join(figures))
                    + "}"
                )
            lines.append("")
    lines.extend([r"\bibliographystyle{plain}", r"\bibliography{references}", r"\end{document}", ""])
    return "\n".join(lines)


def build_publication_manifest(
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    markdown_bytes: bytes,
    latex_bytes: bytes,
    bibliography_bytes: bytes,
    published_at: str,
    section_is_current: SectionPredicate,
    confirmation_is_current: SectionPredicate,
) -> dict[str, Any]:
    ordered = _renderable_sections(
        manifest,
        records,
        section_is_current=section_is_current,
        confirmation_is_current=confirmation_is_current,
    )
    if not all(isinstance(value, bytes) for value in (markdown_bytes, latex_bytes, bibliography_bytes)):
        raise TypeError("publication artifacts must be bytes")
    if not _text(published_at):
        raise ValueError("published_at is required")
    return {
        "schema_version": PAPER_DRAFT_SCHEMA_VERSION,
        "kind": "paper_draft_publication_manifest",
        "program_id": str(manifest["program_id"]),
        "published_at": str(published_at),
        "draft_manifest_digest": str(manifest["anchor_digest"]),
        "sections": [
            {
                "section_id": str(record["section_id"]),
                "record_id": str(record["id"]),
                "content_digest": paper_draft_section_content_digest(record),
                "confirmation_receipt_digest": _exact_digest(record.get("confirmation", {})),
            }
            for record in ordered
        ],
        "artifacts": [
            {
                "role": role,
                "filename": filename,
                "byte_sha256": _bytes_digest(content),
                "byte_count": len(content),
            }
            for role, filename, content in (
                ("markdown", "paper-draft.md", markdown_bytes),
                ("latex", "paper-draft.tex", latex_bytes),
                ("bibliography", "references.bib", bibliography_bytes),
            )
        ],
    }


__all__ = [
    "PAPER_DRAFT_FILL_KIND",
    "PAPER_DRAFT_MANIFEST_KIND",
    "PAPER_DRAFT_OWNER",
    "PAPER_DRAFT_SCHEMA_VERSION",
    "PAPER_DRAFT_SECTION_KIND",
    "SECTION_IDENTITIES",
    "SECTION_TITLES",
    "build_draft_manifest",
    "build_publication_manifest",
    "build_section_fill_scaffold",
    "draft_manifest_anchor_digest",
    "draft_manifest_currentness_violations",
    "draft_manifest_structure_violations",
    "paper_draft_section_anchor_digest",
    "paper_draft_section_content_digest",
    "paper_draft_section_lifecycle_violations",
    "render_paper_draft_latex",
    "render_paper_draft_markdown",
    "section_fill_shape_violations",
    "validate_publication_sections",
    "verify_section_fill",
]

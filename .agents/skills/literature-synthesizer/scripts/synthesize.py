#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, ensure_dir, file_sha256, load_yaml, print_resolved_project_roots, slugify, utc_now_iso, write_text_if_changed, write_yaml_if_changed
from research.core import iter_records, project_root, rel, synthesis_root, unit_root
from research.evidence import validate_claims, verify_claim_evidence
from research.journal import mutation_transaction
from research.surveys import build_unit_binding, select_survey_records, survey_staleness, unit_bindings_equal


SECTION_SPECS = (
    ("scope_positioning", "Scope & Positioning", "fact"),
    ("background_terms", "Background & Terms", "fact"),
    ("taxonomy", "Taxonomy", "fact"),
    ("cross_cutting", "Datasets, Benchmarks & Metrics", "evaluation"),
    ("trends", "Trends", "inference"),
    ("gaps_challenges", "Gaps, Controversies & Open Challenges", "inference"),
    ("conclusion", "Conclusion", "inference"),
)


def fillable_claim(claim_id: str, claim_type: str, **extra: object) -> dict:
    return {
        "id": claim_id,
        "content": "",
        "claim_type": claim_type,
        "evidence_refs": [],
        **extra,
    }


def build_survey_scaffold(
    records: list[dict],
    *,
    root: Path,
    query: str,
    kind: str,
    topic: str,
    tag: str,
    pool: str,
    mode: str,
    as_of: str,
) -> dict:
    """Build a fillable survey structure; the script authors no conclusions."""
    subject = query or topic or tag or pool or kind or mode
    slug = slugify(subject, max_words=8) or mode
    units = [build_unit_binding(root, record) for record in records if str(record.get("id") or "")]
    sections = []
    for section_id, title, claim_type in SECTION_SPECS:
        section = {"id": section_id, "title": title}
        if section_id == "taxonomy":
            section["dimensions"] = [{"id": "taxonomy-dimension-1", "label": ""}]
            section["cells"] = [
                fillable_claim(
                    "taxonomy-cell-1",
                    claim_type,
                    row_label="",
                    column_label="",
                )
            ]
        elif section_id == "trends":
            section["items"] = [
                fillable_claim(
                    "trend-1",
                    claim_type,
                    trajectory="",
                    as_of=as_of,
                )
            ]
        elif section_id == "gaps_challenges":
            section["items"] = [
                fillable_claim(
                    "gap-1",
                    claim_type,
                    gap_type="",
                    as_of=as_of,
                )
            ]
        else:
            section["claims"] = [fillable_claim(f"{section_id}-1", claim_type)]
        sections.append(section)
    return {
        "schema_version": 1,
        "mode": mode,
        "slug": slug,
        "status": "awaiting_agent_fill",
        "filters": {"query": query, "kind": kind, "topic": topic, "tag": tag, "pool": pool},
        "kb_anchor": {
            "as_of": as_of,
            "unit_ids": [unit["id"] for unit in units],
            "units": units,
        },
        "fill_contract": {
            "required_section_ids": [section_id for section_id, _, _ in SECTION_SPECS],
            "required_claim_fields": ["id", "content", "claim_type", "evidence_refs"],
            "evidence_rule": (
                "The runtime agent fills every required claim cell with one or more verbatim evidence_refs. "
                "The script only validates structure and evidence; it never authors survey conclusions."
            ),
            "evidence_ref_fields": ["source_unit_id", "artifact", "locator", "quote"],
            "epistemic_rule": "claim_type=inference is inferred; fact/evaluation are observed.",
        },
        "sections": sections,
        "comparison_matrix": {
            "dimensions": [{"id": "dimension-1", "label": ""}],
            "methods": [{"id": "method-1", "label": "", "source_unit_ids": []}],
            "cells": [
                fillable_claim(
                    "matrix-cell-1",
                    "evaluation",
                    method_id="method-1",
                    dimension_id="dimension-1",
                )
            ],
        },
    }


def survey_claim_entries(payload: dict) -> tuple[list[str], list[tuple[str, dict, bool]]]:
    violations: list[str] = []
    entries: list[tuple[str, dict, bool]] = []
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list):
        return ["sections: must be a list"], entries
    sections = {
        str(section.get("id") or ""): section
        for section in raw_sections
        if isinstance(section, dict) and str(section.get("id") or "")
    }
    required_ids = [section_id for section_id, _, _ in SECTION_SPECS]
    for section_id in required_ids:
        section = sections.get(section_id)
        if section is None:
            violations.append(f"section '{section_id}': missing")
            continue
        key = "cells" if section_id == "taxonomy" else "items" if section_id in {"trends", "gaps_challenges"} else "claims"
        items = section.get(key)
        if not isinstance(items, list) or not items:
            violations.append(f"section '{section_id}': {key} must contain at least one fillable claim")
            continue
        for index, item in enumerate(items):
            label = f"section '{section_id}' {key}[{index}]"
            if not isinstance(item, dict):
                violations.append(f"{label}: must be a mapping")
                continue
            if section_id == "taxonomy":
                if not str(item.get("row_label") or "").strip():
                    violations.append(f"{label}: row_label is required")
                if not str(item.get("column_label") or "").strip():
                    violations.append(f"{label}: column_label is required")
            elif section_id == "trends" and not str(item.get("trajectory") or "").strip():
                violations.append(f"{label}: trajectory is required")
            elif section_id == "gaps_challenges" and not str(item.get("gap_type") or "").strip():
                violations.append(f"{label}: gap_type is required")
            entries.append((label, item, True))

    matrix = payload.get("comparison_matrix")
    if not isinstance(matrix, dict):
        violations.append("comparison_matrix: missing or not a mapping")
        return violations, entries
    dimensions = matrix.get("dimensions")
    methods = matrix.get("methods")
    cells = matrix.get("cells")
    if not isinstance(dimensions, list) or not dimensions:
        violations.append("comparison_matrix.dimensions: must contain at least one dimension")
    if not isinstance(methods, list) or not methods:
        violations.append("comparison_matrix.methods: must contain at least one method")
    dimension_ids: set[str] = set()
    for index, dimension in enumerate(dimensions if isinstance(dimensions, list) else []):
        if not isinstance(dimension, dict):
            violations.append(f"comparison_matrix.dimensions[{index}]: must be a mapping")
            continue
        dimension_id = str(dimension.get("id") or "").strip()
        if not dimension_id or not str(dimension.get("label") or "").strip():
            violations.append(f"comparison_matrix.dimensions[{index}]: id and label are required")
        else:
            dimension_ids.add(dimension_id)
    method_ids: set[str] = set()
    for index, method in enumerate(methods if isinstance(methods, list) else []):
        if not isinstance(method, dict):
            violations.append(f"comparison_matrix.methods[{index}]: must be a mapping")
            continue
        method_id = str(method.get("id") or "").strip()
        if not method_id or not str(method.get("label") or "").strip():
            violations.append(f"comparison_matrix.methods[{index}]: id and label are required")
        else:
            method_ids.add(method_id)
    if not isinstance(cells, list) or not cells:
        violations.append("comparison_matrix.cells: must contain at least one cell")
    else:
        for index, cell in enumerate(cells):
            label = f"comparison_matrix.cells[{index}]"
            if not isinstance(cell, dict):
                violations.append(f"{label}: must be a mapping")
                continue
            if str(cell.get("method_id") or "").strip() not in method_ids:
                violations.append(f"{label}: method_id must reference comparison_matrix.methods")
            if str(cell.get("dimension_id") or "").strip() not in dimension_ids:
                violations.append(f"{label}: dimension_id must reference comparison_matrix.dimensions")
            entries.append((label, cell, True))
    return violations, entries


def claim_from_cell(cell: dict) -> dict:
    return {
        "id": str(cell.get("id") or "").strip(),
        "text": " ".join(str(cell.get("content") or "").split()),
        "claim_type": str(cell.get("claim_type") or "").strip(),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": cell.get("evidence_refs") or [],
    }


def verify_survey_fill(payload: dict, root: Path) -> tuple[list[str], dict]:
    """Verify every agent-authored claim and each ref against its cited unit."""
    violations, entries = survey_claim_entries(payload)
    anchor = payload.get("kb_anchor")
    if not isinstance(anchor, dict):
        violations.append("kb_anchor: missing or not a mapping")
        anchor = {}
    as_of = str(anchor.get("as_of") or "").strip()
    if not as_of:
        violations.append("kb_anchor.as_of: missing")
    unit_items = anchor.get("units")
    if not isinstance(unit_items, list):
        violations.append("kb_anchor.units: must be a list")
        unit_items = []
    anchored_units: dict[str, str] = {}
    anchored_bindings: dict[str, dict] = {}
    for index, item in enumerate(unit_items):
        if not isinstance(item, dict):
            violations.append(f"kb_anchor.units[{index}]: must be a mapping")
            continue
        unit_id = str(item.get("id") or "").strip()
        unit_kind = str(item.get("kind") or "").strip()
        if not unit_id or not unit_kind:
            violations.append(f"kb_anchor.units[{index}]: id and kind are required")
            continue
        if unit_id in anchored_units:
            violations.append(f"kb_anchor.units[{index}]: duplicate unit id '{unit_id}'")
            continue
        anchored_units[unit_id] = unit_kind
        anchored_bindings[unit_id] = item
        for field in ("title", "record_content_digest", "confirmation_receipt_digest", "evidence_artifacts"):
            if field not in item:
                violations.append(f"kb_anchor.units[{index}]: missing {field}")
        try:
            current_binding = build_unit_binding(root, item)
        except (OSError, SystemExit) as exc:
            violations.append(f"kb_anchor.units[{index}]: cannot reload canonical unit: {exc}")
        else:
            if not unit_bindings_equal(current_binding, item):
                violations.append(
                    f"kb_anchor.units[{index}]: canonical unit content, confirmation, or evidence changed; prepare again"
                )
    unit_ids = anchor.get("unit_ids")
    if not isinstance(unit_ids, list):
        violations.append("kb_anchor.unit_ids: must be a list")
    elif set(str(unit_id) for unit_id in unit_ids) != set(anchored_units):
        violations.append("kb_anchor.unit_ids: must match kb_anchor.units exactly")

    claims: list[tuple[str, dict, bool]] = []
    for label, cell, evidence_required in entries:
        claim = claim_from_cell(cell)
        claims.append((label, claim, evidence_required))
        if not claim["text"]:
            violations.append(f"{label}: empty content — the runtime agent must fill it")
        refs = claim.get("evidence_refs") or []
        if evidence_required and not refs:
            violations.append(f"{label}: evidence_refs must contain at least one verbatim citation")
        if label.startswith("section 'trends'") or label.startswith("section 'gaps_challenges'"):
            if str(cell.get("as_of") or "").strip() != as_of:
                violations.append(f"{label}: as_of must match kb_anchor.as_of")

    structural_claims = [claim for _, claim, _ in claims]
    for violation in validate_claims(structural_claims):
        violations.append(f"claim-structure: {violation}")

    for label, claim, _ in claims:
        refs = claim.get("evidence_refs") or []
        if not isinstance(refs, list):
            continue
        for index, ref_item in enumerate(refs):
            if not isinstance(ref_item, dict):
                violations.append(f"{label} evidence_refs[{index}]: must be a mapping")
                continue
            source_unit_id = str(ref_item.get("source_unit_id") or "").strip()
            if not source_unit_id:
                violations.append(f"{label} evidence_refs[{index}]: source_unit_id is required")
                continue
            source_kind = anchored_units.get(source_unit_id)
            if not source_kind:
                violations.append(
                    f"{label} evidence_refs[{index}]: source_unit_id '{source_unit_id}' is not in kb_anchor.units"
                )
                continue
            anchored_artifacts = {
                str(item.get("artifact") or "")
                for item in anchored_bindings[source_unit_id].get("evidence_artifacts", [])
                if isinstance(item, dict)
            }
            artifact = str(ref_item.get("artifact") or "").strip()
            if artifact not in anchored_artifacts:
                violations.append(
                    f"{label} evidence_refs[{index}]: artifact '{artifact}' was not present in the prepared unit binding"
                )
                continue
            single_ref_claim = {**claim, "evidence_refs": [ref_item]}
            try:
                source_unit_dir = unit_root(root, source_kind, source_unit_id)
            except SystemExit:
                violations.append(
                    f"{label} evidence_refs[{index}]: source unit '{source_unit_id}' has unsupported kind '{source_kind}'"
                )
                continue
            for violation in verify_claim_evidence(single_ref_claim, source_unit_dir):
                violations.append(f"{label}: {violation}")

    verified = copy.deepcopy(payload)
    if not violations:
        # Evidence verification is not human confirmation.  Until surveys gain a
        # first-class ConfirmationReceipt route, keep them explicitly pending so
        # report consumers cannot mistake a grounded AI synthesis for settled fact.
        verified["status"] = "pending_user_confirmation"
        verified["evidence_verification_status"] = "verified"
        verified["confirmation_status"] = "pending_user_confirmation"
        verified["needs_human_confirmation"] = True
        verified["governance_status"] = "needs_agent_repair"
        verified["consumer_binding"] = {
            "selection_filters": copy.deepcopy(verified.get("filters") or {}),
            "unit_ids": [str(item.get("id") or "") for item in unit_items if isinstance(item, dict)],
            "units": copy.deepcopy(unit_items),
            "verified_at": utc_now_iso(),
        }
        for _, cell, _ in survey_claim_entries(verified)[1]:
            cell["epistemic_status"] = "verified_pending_confirmation"
    return violations, verified


def _escape_table_cell(value: object) -> str:
    return " ".join(str(value or "").split()).replace("|", "\\|") or "-"


def render_verified_summary(payload: dict) -> str:
    filters = payload.get("filters") or {}
    subject = filters.get("query") or filters.get("topic") or filters.get("tag") or filters.get("pool") or filters.get("kind") or "survey"
    lines = [
        f"# Survey: {subject}",
        "",
        "> Pending / Unverified judgement: evidence has been checked, but no current human ConfirmationReceipt exists.",
        "",
        f"KB anchor: `{payload.get('kb_anchor', {}).get('as_of', '')}`",
        "",
    ]
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        lines.extend([f"## {section.get('title') or section.get('id')}", ""])
        key = "cells" if section.get("id") == "taxonomy" else "items" if section.get("id") in {"trends", "gaps_challenges"} else "claims"
        for cell in section.get(key) or []:
            if not isinstance(cell, dict):
                continue
            status = cell.get("epistemic_status") or ""
            prefix = f"**{status.title()}**" if status else ""
            lines.append(f"- {prefix}: {cell.get('content', '')}")
        lines.append("")

    matrix = payload.get("comparison_matrix") or {}
    dimensions = [item for item in matrix.get("dimensions") or [] if isinstance(item, dict)]
    methods = [item for item in matrix.get("methods") or [] if isinstance(item, dict)]
    cells = [item for item in matrix.get("cells") or [] if isinstance(item, dict)]
    cell_map = {(str(item.get("method_id") or ""), str(item.get("dimension_id") or "")): item for item in cells}
    lines.extend(["## Comparison Matrix", ""])
    lines.append("| Method | " + " | ".join(_escape_table_cell(item.get("label")) for item in dimensions) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in dimensions) + " |")
    for method in methods:
        method_id = str(method.get("id") or "")
        values = [
            _escape_table_cell((cell_map.get((method_id, str(dimension.get("id") or ""))) or {}).get("content"))
            for dimension in dimensions
        ]
        lines.append(f"| {_escape_table_cell(method.get('label'))} | " + " | ".join(values) + " |")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthesize research units in core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("survey", "review", "taxonomy"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("action", choices=("prepare", "verify"))
        cmd.add_argument("--field", default="")
        cmd.add_argument("--query", default="")
        cmd.add_argument("--as-of", default="")
        cmd.add_argument("--input", default="")
        cmd.add_argument("--kind", default="")
        cmd.add_argument("--topic", default="")
        cmd.add_argument("--tag", default="")
        cmd.add_argument("--pool", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    mode = args.command
    query = getattr(args, "field", "") or getattr(args, "query", "")
    if args.action == "verify":
        if args.input:
            fill_path = Path(args.input)
            if not fill_path.is_absolute():
                fill_path = root / fill_path
        else:
            if not any((query, args.topic, args.tag, args.pool, args.kind)):
                raise SystemExit(f"{mode} verify requires --input or selection filters")
            input_slug = slugify(query or args.topic or args.tag or args.pool or args.kind or mode, max_words=8) or mode
            fill_path = synthesis_root(root) / input_slug / f"{mode}-fill.yaml"
        if not fill_path.exists():
            raise SystemExit(f"{mode} verify input not found: {fill_path}")
        fill = load_yaml(fill_path, default={})
        if not isinstance(fill, dict):
            raise SystemExit(f"{mode} verify input is not a mapping: {fill_path}")
        output_slug = slugify(str(fill.get("slug") or "survey"), max_words=8) or "survey"
        verified_root = synthesis_root(root) / output_slug
        yaml_path = verified_root / f"{mode}.yaml"
        md_path = verified_root / "summary.md"
        with mutation_transaction(root, f"verify-{mode}", [yaml_path, md_path]):
            violations, payload = verify_survey_fill(fill, root)
            if str(fill.get("mode") or "") != mode:
                violations.append(f"mode mismatch: command is '{mode}' but scaffold mode is '{fill.get('mode')}'")
            if violations:
                print(f"[reject] {mode} fill failed verification:", file=sys.stderr)
                for violation in violations:
                    print(f"  - {violation}", file=sys.stderr)
                return 1
            ensure_dir(verified_root)
            write_yaml_if_changed(yaml_path, payload)
            write_text_if_changed(md_path, render_verified_summary(payload))
        print(rel(root, yaml_path))
        print(rel(root, md_path))
        return 0
    slug = slugify(query or args.topic or args.tag or args.pool or args.kind or mode, max_words=8) or mode
    out_root = synthesis_root(root) / slug
    if args.action == "prepare":
        if not any((query, args.topic, args.tag, args.pool, args.kind)):
            raise SystemExit(f"{mode} prepare requires --field/--query or another selection filter")
        if not args.as_of:
            raise SystemExit(f"{mode} prepare requires --as-of to anchor the selected KB snapshot")
        fill_path = out_root / f"{mode}-fill.yaml"
        with mutation_transaction(root, f"prepare-{mode}", [fill_path]):
            selected = select_survey_records(
                iter_records(root),
                query=query,
                kind=args.kind,
                topic=args.topic,
                tag=args.tag,
                pool=args.pool,
            )
            payload = build_survey_scaffold(
                selected,
                root=root,
                query=query,
                kind=args.kind,
                topic=args.topic,
                tag=args.tag,
                pool=args.pool,
                mode=mode,
                as_of=args.as_of,
            )
            ensure_dir(out_root)
            write_yaml_if_changed(fill_path, payload)
        print(rel(root, fill_path))
        return 0
    raise SystemExit(f"unsupported action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())

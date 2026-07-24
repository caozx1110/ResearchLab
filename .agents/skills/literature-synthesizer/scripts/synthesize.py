#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
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

from research.common import add_project_root_argument, ensure_dir, file_sha256, load_list_document, load_yaml, print_resolved_project_roots, program_reporting_events_path, slugify, utc_now_iso, write_text_if_changed, write_yaml_if_changed
from research.core import iter_records, project_root, rel, synthesis_root, unit_root
from research.confirm import apply_confirmation
from research.evidence import (
    build_verification_receipt,
    validate_claims,
    verification_receipt_violations,
    verify_claim_evidence,
)
from research.judgements import apply_judgement_rejection, confirmation_binding, require_judgement_snapshot
from research.journal import mutation_transaction
from research.preference_selection import resolve_operation_preferences
from research.surveys import (
    build_unit_binding,
    composite_survey_current_violations,
    composite_survey_request_digest,
    composite_survey_repair_projection,
    composite_survey_state_path,
    composite_survey_state_violations,
    evidence_gap_handoff,
    new_composite_survey_state,
    select_current_confirmed_survey_records,
    survey_artifact_path,
    survey_content_digest,
    survey_lifecycle_violations,
    survey_source_roots,
    survey_staleness,
    unit_bindings_equal,
    update_composite_survey_stage,
)


SECTION_SPECS = (
    ("scope_positioning", "Scope & Positioning", "fact"),
    ("background_terms", "Background & Terms", "fact"),
    ("taxonomy", "Taxonomy", "fact"),
    ("cross_cutting", "Datasets, Benchmarks & Metrics", "evaluation"),
    ("trends", "Trends", "inference"),
    ("gaps_challenges", "Gaps, Controversies & Open Challenges", "inference"),
    ("conclusion", "Conclusion", "inference"),
)
MAX_COMPOSITE_INPUT_BYTES = 256 * 1024
EXPLICIT_EXTERNAL_DISCOVERY_MARKERS = (
    "systematic",
    "scoping review",
    "meta-analysis",
    "meta analysis",
    "systematic mapping",
    "review recent papers",
    "系统综述",
    "系统映射",
    "元分析",
    "外部检索",
)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthesis_preference_context(
    *,
    query: str,
    kind: str,
    topic: str,
    tag: str,
    pool: str,
    mode: str,
    as_of: str,
    program_ids: list[str] | None = None,
    discovery_mode: str = "kb_only",
    search_protocol_digest: str = "",
    input_unit_bindings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    normalized_bindings = sorted(
        [copy.deepcopy(item) for item in input_unit_bindings or [] if isinstance(item, dict)],
        key=lambda item: (str(item.get("kind") or ""), str(item.get("id") or "")),
    )
    return {
        "mode": str(mode or ""),
        "discovery_mode": str(discovery_mode or "kb_only"),
        "search_protocol_digest": str(search_protocol_digest or _canonical_digest({})),
        "selection_digest": _canonical_digest(
            {
                "query": " ".join(str(query or "").split()),
                "kind": str(kind or ""),
                "topic": str(topic or ""),
                "tag": str(tag or ""),
                "pool": str(pool or ""),
            }
        ),
        "as_of": str(as_of or ""),
        "program_ids": sorted({str(item or "").strip() for item in program_ids or [] if str(item or "").strip()}),
        "input_units_digest": _canonical_digest(normalized_bindings),
    }


def synthesis_input_unit_bindings(
    root: Path,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Read the exact current unit snapshot selected by prepare."""
    return sorted(
        [build_unit_binding(root, record) for record in records],
        key=lambda item: (str(item.get("kind") or ""), str(item.get("id") or "")),
    )


def validated_synthesis_program_ids(root: Path, program_ids: list[str] | None) -> list[str]:
    linked = sorted({str(item or "").strip() for item in program_ids or [] if str(item or "").strip()})
    for program_id in linked:
        if Path(program_id).name != program_id or program_id in {".", ".."}:
            raise ValueError("survey program id is not canonical")
        program = root / "kb" / "programs" / program_id
        if program.is_symlink() or not program.is_dir():
            raise ValueError(f"survey program does not exist: {program_id}")
    return linked


def resolve_synthesis_preferences(
    root: Path,
    *,
    selection_id: str,
    query: str,
    kind: str,
    topic: str,
    tag: str,
    pool: str,
    mode: str,
    as_of: str,
    program_ids: list[str] | None = None,
    discovery_mode: str = "kb_only",
    search_protocol_digest: str = "",
    input_unit_bindings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    try:
        return resolve_operation_preferences(
            root,
            selection_id=selection_id,
            skill="literature-synthesizer",
            operation="synthesize",
            canonical_inputs=synthesis_preference_context(
                query=query,
                kind=kind,
                topic=topic,
                tag=tag,
                pool=pool,
                mode=mode,
                as_of=as_of,
                program_ids=program_ids,
                discovery_mode=discovery_mode,
                search_protocol_digest=search_protocol_digest,
                input_unit_bindings=input_unit_bindings,
            ),
        )
    except ValueError as exc:
        raise SystemExit(f"Synthesis preference selection is invalid: {exc}") from exc


def synthesis_preference_state(resolution: dict[str, object]) -> dict[str, object]:
    return {
        "task_context_digest": str(resolution.get("task_context_digest") or ""),
        "selection_binding": dict(resolution.get("binding") or {}),
        "hard_value_digests": dict(resolution.get("hard_value_digests") or {}),
    }


def _assert_composite_path_safe(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SystemExit("Composite survey state escaped the synthesis boundary.") from exc
    if relative.parts[:2] != ("kb", "synthesis"):
        raise SystemExit("Composite survey state escaped the synthesis boundary.")
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
            raise SystemExit("Composite survey state has an unsafe ancestor.")
    allowed = (root / "kb" / "synthesis").resolve()
    try:
        path.resolve().relative_to(allowed)
    except ValueError as exc:
        raise SystemExit("Composite survey state escaped the synthesis boundary.") from exc
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SystemExit("Composite survey state target is unsafe.")


def _load_composite_input(path: Path) -> dict[str, object]:
    try:
        stat = path.lstat()
    except OSError:
        raise SystemExit("Composite survey input could not be read.") from None
    if path.is_symlink() or not path.is_file() or stat.st_size > MAX_COMPOSITE_INPUT_BYTES:
        raise SystemExit("Composite survey input must be a bounded regular JSON file.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SystemExit("Composite survey input is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise SystemExit("Composite survey input must be a JSON object.")
    return payload


def _load_frozen_search_protocol(
    root: Path,
    *,
    discovery_mode: str,
    input_value: str,
) -> dict[str, object]:
    if discovery_mode == "kb_only":
        if input_value:
            raise SystemExit("KB-only synthesis cannot carry an external search protocol.")
        return {}
    if not input_value:
        raise SystemExit("External-discovery synthesis requires a frozen search protocol input.")
    path = Path(input_value).expanduser()
    if not path.is_absolute():
        path = root / path
    protocol = _load_composite_input(path)
    allowed = {"mode", "scope", "budget", "review_protocol", "reviewers"}
    if set(protocol) - allowed or protocol.get("mode") != discovery_mode:
        raise SystemExit("Frozen search protocol mode or fields are invalid.")
    if not isinstance(protocol.get("scope"), dict) or not protocol["scope"]:
        raise SystemExit("Frozen search protocol requires a non-empty scope.")
    if not isinstance(protocol.get("budget"), dict) or not protocol["budget"]:
        raise SystemExit("Frozen search protocol requires a non-empty budget.")
    if discovery_mode in {"bounded-systematic", "systematic"}:
        required_scope = {
            "inclusion",
            "exclusion",
            "languages",
            "source_types",
            "channels",
            "date_range",
            "result_depth",
            "screening",
            "screeners",
        }
        if not required_scope <= set(protocol["scope"]):
            raise SystemExit("Systematic search protocol scope is incomplete.")
    for key in ("review_protocol", "reviewers"):
        value = protocol.get(key, {} if key == "review_protocol" else [])
        if key == "review_protocol" and not isinstance(value, dict):
            raise SystemExit("Frozen search review protocol must be a mapping.")
        if key == "reviewers" and not isinstance(value, list):
            raise SystemExit("Frozen search reviewers must be a list.")
    return protocol


def _load_composite_state(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Composite survey state is unavailable or unsafe.")
    payload = load_yaml(path, default={})
    violations = composite_survey_state_violations(payload)
    if violations:
        raise SystemExit("Composite survey state is invalid: " + "; ".join(violations))
    return payload


def ensure_evidence_gap_composite(
    root: Path,
    *,
    slug: str,
    filters: dict[str, str],
    as_of: str,
    program_ids: list[str] | None = None,
    preference_context: dict[str, object] | None = None,
    discovery_mode: str = "kb_only",
    search_protocol: dict[str, object] | None = None,
) -> dict[str, object]:
    linked_program_ids = sorted({str(item) for item in program_ids or [] if str(item)})
    for program_id in linked_program_ids:
        if Path(program_id).name != program_id or program_id in {".", ".."}:
            raise SystemExit("Survey program id is not canonical.")
        program = root / "kb" / "programs" / program_id
        if program.is_symlink() or not program.is_dir():
            raise SystemExit(f"Survey program does not exist: {program_id}")
    request_filters = {
        **filters,
        "program_ids": ",".join(linked_program_ids),
        "preference_context_digest": _canonical_digest(preference_context or {}),
        "discovery_mode": str(discovery_mode or "kb_only"),
        "search_protocol": json.dumps(
            search_protocol or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    request_digest = composite_survey_request_digest(
        filters=request_filters,
        as_of=as_of,
        mode="discovery",
    )
    composite_id = f"survey-{slug}-{request_digest[:12]}"
    path = composite_survey_state_path(root, slug=slug, composite_id=composite_id)
    _assert_composite_path_safe(root, path)
    with mutation_transaction(root, "prepare-composite-survey-gap", [path]):
        if path.exists():
            state = _load_composite_state(path)
            if state.get("request_digest") != request_digest:
                raise SystemExit("Composite survey id is already bound to another request.")
        else:
            state = new_composite_survey_state(
                composite_id=composite_id,
                request_digest=request_digest,
                mode="discovery",
                filters={**request_filters, "as_of": str(as_of or "")},
            )
            state = update_composite_survey_stage(
                state,
                "search",
                status="blocked",
                blocker={
                    "code": (
                        "external_discovery_required"
                        if discovery_mode != "kb_only"
                        else "no_current_confirmed_units"
                    )
                },
                resume_action="run_agent_literature_search",
                inputs=[{"kind": "effective_preferences", "context": copy.deepcopy(preference_context or {})}],
                expected_revision=1,
            )
            ensure_dir(path.parent)
            write_yaml_if_changed(path, state)
    return {
        "composite_id": composite_id,
        "request_digest": request_digest,
        "revision": int(state.get("revision") or 0),
        "current_stage": str(state.get("current_stage") or ""),
        "state": str(state.get("status") or ""),
        "state_path": rel(root, path),
    }


def handle_composite_command(root: Path, args: argparse.Namespace) -> int:
    path = composite_survey_state_path(
        root,
        slug=str(args.slug or ""),
        composite_id=str(args.composite_id or ""),
    )
    _assert_composite_path_safe(root, path)
    if args.action == "status":
        state = _load_composite_state(path)
        current = (
            composite_survey_repair_projection(root, state)
            if composite_survey_current_violations(root, state)
            else state
        )
        print(json.dumps(current, ensure_ascii=False, sort_keys=True))
        return 0
    input_path = Path(args.input).expanduser()
    if not input_path.is_absolute():
        input_path = root / input_path
    request = _load_composite_input(input_path)
    allowed = {"stage_id", "status", "inputs", "outputs", "blocker", "resume_action"}
    if set(request) - allowed:
        raise SystemExit("Composite survey update contains unsupported fields.")

    def load_checked() -> dict[str, object]:
        state = _load_composite_state(path)
        if int(state.get("revision") or 0) != int(args.expected_revision):
            raise SystemExit("Composite survey state changed after it was displayed.")
        return state

    with mutation_transaction(root, "update-composite-survey", [path], preflight=load_checked):
        state = load_checked()
        try:
            updated = update_composite_survey_stage(
                state,
                str(request.get("stage_id") or ""),
                status=str(request.get("status") or ""),
                inputs=request.get("inputs") if isinstance(request.get("inputs"), list) else [],
                outputs=request.get("outputs") if isinstance(request.get("outputs"), list) else [],
                blocker=request.get("blocker") if isinstance(request.get("blocker"), dict) else {},
                resume_action=str(request.get("resume_action") or ""),
                expected_revision=int(args.expected_revision),
                root=root,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        write_yaml_if_changed(path, updated)
    print(json.dumps(updated, ensure_ascii=False, sort_keys=True))
    return 0


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
    program_ids: list[str] | None = None,
    preference_context: dict[str, object] | None = None,
    discovery_mode: str = "kb_only",
    search_protocol_digest: str = "",
    input_unit_bindings: list[dict[str, object]] | None = None,
) -> dict:
    """Build a fillable survey structure; the script authors no conclusions."""
    if not records:
        raise ValueError("survey scaffold requires at least one current confirmed input unit")
    subject = query or topic or tag or pool or kind or mode
    slug = slugify(subject, max_words=8) or mode
    linked_program_ids = validated_synthesis_program_ids(root, program_ids)
    units = (
        synthesis_input_unit_bindings(root, records)
        if input_unit_bindings is None
        else sorted(
            [copy.deepcopy(item) for item in input_unit_bindings if isinstance(item, dict)],
            key=lambda item: (str(item.get("kind") or ""), str(item.get("id") or "")),
        )
    )
    effective_protocol_digest = str(search_protocol_digest or _canonical_digest({}))
    if preference_context is None:
        preference_context = synthesis_preference_state(
            resolve_synthesis_preferences(
                root,
                selection_id="",
                query=query,
                kind=kind,
                topic=topic,
                tag=tag,
                pool=pool,
                mode=mode,
                as_of=as_of,
                program_ids=linked_program_ids,
                discovery_mode=discovery_mode,
                search_protocol_digest=effective_protocol_digest,
                input_unit_bindings=units,
            )
        )
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
        "program_ids": linked_program_ids,
        "discovery_mode": str(discovery_mode or "kb_only"),
        "search_protocol_digest": effective_protocol_digest,
        "filters": {
            "query": query,
            "kind": kind,
            "topic": topic,
            "tag": tag,
            "pool": pool,
            "preference_context_digest": _canonical_digest(preference_context),
        },
        "preference_context": copy.deepcopy(preference_context),
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
    claim = {
        "id": str(cell.get("id") or "").strip(),
        "text": " ".join(str(cell.get("content") or "").split()),
        "claim_type": str(cell.get("claim_type") or "").strip(),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": cell.get("evidence_refs") or [],
    }
    # Bind domain fields authored by the runtime Agent without interpreting them.
    for key in ("row_label", "column_label", "trajectory", "as_of", "gap_type", "method_id", "dimension_id"):
        if key in cell:
            claim[key] = copy.deepcopy(cell.get(key))
    return claim


def verify_survey_fill(payload: dict, root: Path) -> tuple[list[str], dict]:
    """Verify every agent-authored claim and each ref against its cited unit."""
    violations, entries = survey_claim_entries(payload)
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    anchor_for_preferences = payload.get("kb_anchor") if isinstance(payload.get("kb_anchor"), dict) else {}
    current_input_bindings: list[dict[str, object]] = []
    try:
        current_selected, _current_excluded = select_current_confirmed_survey_records(
            root,
            iter_records(root),
            query=str(filters.get("query") or ""),
            kind=str(filters.get("kind") or ""),
            topic=str(filters.get("topic") or ""),
            tag=str(filters.get("tag") or ""),
            pool=str(filters.get("pool") or ""),
        )
        current_input_bindings = synthesis_input_unit_bindings(root, current_selected)
    except (OSError, SystemExit) as exc:
        violations.append(f"preference_context: current input selection is unavailable: {exc}")
    preference_context = payload.get("preference_context")
    if not isinstance(preference_context, dict):
        violations.append("preference_context: missing or not a mapping")
    else:
        selection_binding = preference_context.get("selection_binding")
        selection_binding = selection_binding if isinstance(selection_binding, dict) else {}
        try:
            current_preferences = resolve_synthesis_preferences(
                root,
                selection_id=str(selection_binding.get("selection_id") or ""),
                query=str(filters.get("query") or ""),
                kind=str(filters.get("kind") or ""),
                topic=str(filters.get("topic") or ""),
                tag=str(filters.get("tag") or ""),
                pool=str(filters.get("pool") or ""),
                mode=str(payload.get("mode") or ""),
                as_of=str(anchor_for_preferences.get("as_of") or ""),
                program_ids=payload.get("program_ids") if isinstance(payload.get("program_ids"), list) else [],
                discovery_mode=str(payload.get("discovery_mode") or "kb_only"),
                search_protocol_digest=str(
                    payload.get("search_protocol_digest") or _canonical_digest({})
                ),
                input_unit_bindings=current_input_bindings,
            )
        except SystemExit as exc:
            violations.append(str(exc))
        else:
            current_state = synthesis_preference_state(current_preferences)
            if current_state != preference_context:
                violations.append("preference_context: canonical preferences changed; prepare again")
            if str(filters.get("preference_context_digest") or "") != _canonical_digest(preference_context):
                violations.append("filters.preference_context_digest: does not match preference_context")
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

    program_ids = payload.get("program_ids", [])
    if not isinstance(program_ids, list) or program_ids != sorted(set(program_ids)):
        violations.append("program_ids: must be a sorted unique list")
    else:
        for program_id in program_ids:
            if (
                not isinstance(program_id, str)
                or not program_id
                or Path(program_id).name != program_id
                or program_id in {".", ".."}
            ):
                violations.append("program_ids: contains an invalid program id")
                continue
            program = root / "kb" / "programs" / program_id
            if program.is_symlink() or not program.is_dir():
                violations.append(f"program_ids: program does not exist: {program_id}")

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
        verified_at = utc_now_iso()
        verified["status"] = "pending_user_confirmation"
        verified["evidence_verification_status"] = "verified"
        verified["confirmation_status"] = "pending_user_confirmation"
        verified["needs_human_confirmation"] = True
        verified["governance_status"] = "ready_for_review"
        verified["kind"] = "survey_judgement"
        verified["id"] = f"survey:{verified.get('mode')}:{verified.get('slug')}"
        verified["owner"] = "literature-synthesizer"
        verified["information_types"] = ["evaluation", "inference"]
        verified["priority"] = str(verified.get("priority") or "normal")
        verified["updated_at"] = verified_at
        verified["consumer_binding"] = {
            "selection_filters": copy.deepcopy(verified.get("filters") or {}),
            "unit_ids": [str(item.get("id") or "") for item in unit_items if isinstance(item, dict)],
            "units": copy.deepcopy(unit_items),
            "verified_at": verified_at,
            "preference_context": copy.deepcopy(verified.get("preference_context") or {}),
        }
        for _, cell, _ in survey_claim_entries(verified)[1]:
            cell["epistemic_status"] = "verified_pending_confirmation"
        content_digest = survey_content_digest(verified)
        canonical_claims = [claim_from_cell(cell) for _, cell, _ in survey_claim_entries(verified)[1]]
        for claim in canonical_claims:
            claim["survey_content_digest"] = content_digest
        verified["survey_content_digest"] = content_digest
        verified["payload"] = {"claims": canonical_claims}
        verified["review_route"] = {
            "owner": "literature-synthesizer",
            "action": "confirm",
            "slug": str(verified.get("slug") or ""),
            "mode": str(verified.get("mode") or "survey"),
        }
        source_roots = {
            unit_id: unit_root(root, unit_kind, unit_id)
            for unit_id, unit_kind in anchored_units.items()
        }
        try:
            build_verification_receipt(
                verified,
                synthesis_root(root) / str(verified.get("slug") or "survey"),
                source_roots=source_roots,
                verified_at=verified_at,
            )
        except SystemExit as exc:
            violations.append(str(exc))
    return violations, verified


def _escape_table_cell(value: object) -> str:
    return " ".join(str(value or "").split()).replace("|", "\\|") or "-"


def render_verified_summary(payload: dict) -> str:
    filters = payload.get("filters") or {}
    subject = filters.get("query") or filters.get("topic") or filters.get("tag") or filters.get("pool") or filters.get("kind") or "survey"
    confirmation_status = str(payload.get("confirmation_status") or "")
    if confirmation_status == "confirmed":
        governance_line = "> Confirmed judgement: the current content and evidence bindings have a human ConfirmationReceipt."
    elif confirmation_status == "rejected":
        governance_line = "> Rejected judgement: retained for audit and excluded from review/reporting."
    else:
        governance_line = "> Pending / Unverified judgement: evidence has been checked, but no current human ConfirmationReceipt exists."
    lines = [
        f"# Survey: {subject}",
        "",
        governance_line,
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


def _load_survey_judgement(root: Path, *, slug: str, mode: str) -> tuple[dict, Path]:
    path = survey_artifact_path(root, slug, mode)
    if not path.is_file() or path.is_symlink():
        raise ValueError("survey judgement does not exist as a canonical regular file")
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict):
        raise ValueError("survey judgement is not a mapping")
    if str(payload.get("slug") or "") != slug or str(payload.get("mode") or "") != mode:
        raise ValueError("survey judgement identity does not match its canonical path")
    return payload, path


def _require_current_survey(root: Path, record: dict, path: Path) -> None:
    violations = survey_lifecycle_violations(record, root)
    if violations:
        raise ValueError("survey judgement is stale: " + "; ".join(violations))
    filters = record.get("filters") if isinstance(record.get("filters"), dict) else {}
    anchor = record.get("kb_anchor") if isinstance(record.get("kb_anchor"), dict) else {}
    preference_context = record.get("preference_context")
    if not isinstance(preference_context, dict):
        raise ValueError("survey preference context is missing; prepare the survey again")
    selection_binding = preference_context.get("selection_binding")
    selection_binding = selection_binding if isinstance(selection_binding, dict) else {}
    try:
        current_selected, _current_excluded = select_current_confirmed_survey_records(
            root,
            iter_records(root),
            query=str(filters.get("query") or ""),
            kind=str(filters.get("kind") or ""),
            topic=str(filters.get("topic") or ""),
            tag=str(filters.get("tag") or ""),
            pool=str(filters.get("pool") or ""),
        )
        current_input_bindings = synthesis_input_unit_bindings(root, current_selected)
        current_preferences = resolve_synthesis_preferences(
            root,
            selection_id=str(selection_binding.get("selection_id") or ""),
            query=str(filters.get("query") or ""),
            kind=str(filters.get("kind") or ""),
            topic=str(filters.get("topic") or ""),
            tag=str(filters.get("tag") or ""),
            pool=str(filters.get("pool") or ""),
            mode=str(record.get("mode") or ""),
            as_of=str(anchor.get("as_of") or ""),
            program_ids=record.get("program_ids") if isinstance(record.get("program_ids"), list) else [],
            discovery_mode=str(record.get("discovery_mode") or "kb_only"),
            search_protocol_digest=str(
                record.get("search_protocol_digest") or _canonical_digest({})
            ),
            input_unit_bindings=current_input_bindings,
        )
    except (OSError, SystemExit) as exc:
        raise ValueError(f"survey preferences are stale: {exc}") from exc
    if (
        synthesis_preference_state(current_preferences) != preference_context
        or str(filters.get("preference_context_digest") or "") != _canonical_digest(preference_context)
    ):
        raise ValueError("survey preferences changed after verification; prepare the survey again")
    source_roots = survey_source_roots(root, record, path)
    verification_violations = verification_receipt_violations(
        record,
        path.parent,
        source_roots=source_roots,
    )
    if verification_violations:
        raise ValueError("survey verification is stale: " + "; ".join(verification_violations))


def _survey_reporting_paths(root: Path, record: dict) -> list[Path]:
    paths: list[Path] = []
    for program_id in record.get("program_ids", []):
        program = root / "kb" / "programs" / str(program_id)
        if program.is_symlink() or not program.is_dir():
            raise ValueError(f"survey program is no longer available: {program_id}")
        paths.append(program_reporting_events_path(root, str(program_id)))
    return paths


def _append_survey_reporting_events(root: Path, record: dict, path: Path) -> list[Path]:
    written: list[Path] = []
    binding = confirmation_binding(
        record,
        owner="literature-synthesizer",
        path=rel(root, path),
    )
    filters = record.get("filters") if isinstance(record.get("filters"), dict) else {}
    subject = next((str(filters.get(key) or "") for key in ("query", "topic", "tag", "pool", "kind") if str(filters.get(key) or "")), str(record.get("slug") or "survey"))
    for program_id in record.get("program_ids", []):
        events_path = program_reporting_events_path(root, str(program_id))
        payload = load_list_document(
            events_path,
            f"{program_id}-reporting-events",
            "research-orchestrator",
        )
        payload["program_id"] = str(program_id)
        payload["generated_by"] = "research-orchestrator"
        items = [item for item in payload.get("items", []) if isinstance(item, dict)]
        duplicate = any(
            item.get("event_type") == "survey-confirmed"
            and item.get("confirmation_binding") == binding
            for item in items
        )
        if not duplicate:
            items.append(
                {
                    "timestamp": utc_now_iso(),
                    "source_skill": "literature-synthesizer",
                    "event_type": "survey-confirmed",
                    "title": f"Confirmed survey: {subject}",
                    "summary": "A current evidence-bound survey judgement received human confirmation.",
                    "stage": "survey",
                    "tags": ["survey", "confirmed"],
                    "artifacts": [rel(root, path), rel(root, path.parent / "summary.md")],
                    "idea_ids": [],
                    "paper_ids": [],
                    "repo_ids": [],
                    "epistemic_type": "judgement",
                    "information_types": ["evaluation", "inference"],
                    "confirmation_status": "confirmed",
                    "confirmation_binding": binding,
                }
            )
        payload["items"] = items
        payload["generated_at"] = utc_now_iso()
        write_yaml_if_changed(events_path, payload)
        written.append(events_path)
    return written


def prepare_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> dict:
    """Pure-read preflight for the public cross-owner review coordinator."""
    route_key = "confirm_route" if decision == "confirm" else "reject_route"
    route = item.get(route_key) if isinstance(item, dict) else None
    route = route if isinstance(route, dict) else {}
    expected_action = "confirm" if decision == "confirm" else "reject"
    if route.get("owner") != "literature-synthesizer" or route.get("action") != expected_action:
        raise ValueError("survey review route is invalid")
    slug = str(route.get("slug") or "")
    mode = str(route.get("mode") or "survey")
    record, path = _load_survey_judgement(root, slug=slug, mode=mode)
    if str(record.get("confirmation_status") or "") != "pending_user_confirmation":
        raise ValueError("survey judgement is no longer pending review")
    _require_current_survey(root, record, path)
    snapshot = item.get("snapshot_binding")
    if not isinstance(snapshot, dict):
        raise ValueError("survey review snapshot is missing")
    require_judgement_snapshot(
        record,
        expected_snapshot=snapshot,
        owner="literature-synthesizer",
        path=rel(root, path),
        root=root,
    )
    candidate = copy.deepcopy(record)
    if decision == "confirm":
        apply_confirmation(
            candidate,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="literature-synthesizer confirm",
            project_root=root,
            verification_root=path.parent,
            trusted_source_roots=survey_source_roots(root, candidate, path),
        )
    elif decision == "reject":
        apply_judgement_rejection(candidate, reason=rejection_reason)
    else:
        raise ValueError("survey review decision is invalid")
    target_paths = [path, path.parent / "summary.md"]
    if decision == "confirm":
        target_paths.extend(_survey_reporting_paths(root, candidate))
    return {
        "owner": "literature-synthesizer",
        "decision": decision,
        "slug": slug,
        "mode": mode,
        "target_paths": target_paths,
    }


def apply_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> list[Path]:
    """Apply one preflighted decision inside the coordinator's root transaction."""
    plan = prepare_review_batch_decision(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        rejection_reason=rejection_reason,
    )
    record, path = _load_survey_judgement(root, slug=plan["slug"], mode=plan["mode"])
    if decision == "confirm":
        apply_confirmation(
            record,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="literature-synthesizer confirm",
            project_root=root,
            verification_root=path.parent,
            trusted_source_roots=survey_source_roots(root, record, path),
        )
        record["status"] = "confirmed"
        record["governance_status"] = "confirmed"
    else:
        apply_judgement_rejection(record, reason=rejection_reason)
        record["status"] = "rejected"
        record["governance_status"] = "rejected"
    write_yaml_if_changed(path, record)
    write_text_if_changed(path.parent / "summary.md", render_verified_summary(record))
    if decision == "confirm":
        _append_survey_reporting_events(root, record, path)
    return list(plan["target_paths"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthesize research units in core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("survey", "review", "taxonomy"):
        cmd = subparsers.add_parser(name)
        actions = ("prepare", "verify", "confirm", "reject") if name == "survey" else ("prepare", "verify")
        cmd.add_argument("action", choices=actions)
        cmd.add_argument("--field", default="")
        cmd.add_argument("--query", default="")
        cmd.add_argument("--as-of", default="")
        cmd.add_argument("--input", default="")
        cmd.add_argument("--kind", default="")
        cmd.add_argument("--topic", default="")
        cmd.add_argument("--tag", default="")
        cmd.add_argument("--pool", default="")
        cmd.add_argument("--expected-snapshot", default="")
        cmd.add_argument("--confirmed-by", default="")
        cmd.add_argument("--evidence", action="append", default=[])
        cmd.add_argument("--user-authorization", default="")
        cmd.add_argument("--authorization-source", default="")
        cmd.add_argument("--rejection-reason", default="")
        cmd.add_argument("--program-id", action="append", default=[])
        cmd.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)
        cmd.add_argument(
            "--discovery-mode",
            choices=("kb_only", "exploratory", "bounded-systematic", "systematic"),
            default="kb_only",
            help=argparse.SUPPRESS,
        )
        cmd.add_argument("--search-protocol-input", default="", help=argparse.SUPPRESS)
    composite = subparsers.add_parser("composite")
    composite.add_argument("action", choices=("status", "update"))
    composite.add_argument("--slug", required=True)
    composite.add_argument("--composite-id", required=True)
    composite.add_argument("--expected-revision", type=int, default=0)
    composite.add_argument("--input", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    mode = args.command
    if mode == "composite":
        if args.action == "update" and (not args.input or int(args.expected_revision or 0) < 1):
            raise SystemExit("Composite survey update requires input and expected revision.")
        return handle_composite_command(root, args)
    query = getattr(args, "field", "") or getattr(args, "query", "")
    if args.action in {"confirm", "reject"}:
        if not args.expected_snapshot:
            raise SystemExit("survey review decision requires an expected snapshot")
        try:
            snapshot = json.loads(args.expected_snapshot)
        except json.JSONDecodeError as exc:
            raise SystemExit("survey expected snapshot is not valid JSON") from exc
        if not isinstance(snapshot, dict):
            raise SystemExit("survey expected snapshot must be a mapping")
        subject = snapshot.get("subject")
        subject = subject if isinstance(subject, dict) else {}
        subject_id = str(subject.get("id") or "")
        prefix = "survey:survey:"
        if not subject_id.startswith(prefix):
            raise SystemExit("survey expected snapshot has an invalid subject")
        slug = subject_id[len(prefix):]
        route = {
            "owner": "literature-synthesizer",
            "action": "confirm" if args.action == "confirm" else "reject",
            "slug": slug,
            "mode": "survey",
        }
        item = {
            "snapshot_binding": snapshot,
            "confirm_route" if args.action == "confirm" else "reject_route": route,
        }
        plan = prepare_review_batch_decision(
            root,
            item,
            args.action,
            actor=args.confirmed_by,
            evidence=args.evidence,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
            rejection_reason=args.rejection_reason,
        )
        with mutation_transaction(root, f"{args.action}-survey", plan["target_paths"]):
            apply_review_batch_decision(
                root,
                item,
                args.action,
                actor=args.confirmed_by,
                evidence=args.evidence,
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
                rejection_reason=args.rejection_reason,
            )
        print("Survey review decision recorded.")
        return 0
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
        filters = {
            "query": query,
            "kind": args.kind,
            "topic": args.topic,
            "tag": args.tag,
            "pool": args.pool,
        }
        normalized_query = query.casefold()
        explicit_external = any(
            marker in normalized_query for marker in EXPLICIT_EXTERNAL_DISCOVERY_MARKERS
        )
        if explicit_external and args.discovery_mode == "kb_only":
            raise SystemExit(
                "An explicit systematic or external-discovery survey cannot use KB-only synthesis."
            )
        try:
            linked_program_ids = validated_synthesis_program_ids(root, args.program_id)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        search_protocol = _load_frozen_search_protocol(
            root,
            discovery_mode=str(args.discovery_mode or "kb_only"),
            input_value=str(args.search_protocol_input or ""),
        )
        selected, excluded = select_current_confirmed_survey_records(root, iter_records(root), **filters)
        input_unit_bindings = synthesis_input_unit_bindings(root, selected)
        search_protocol_digest = _canonical_digest(search_protocol)
        preferences = resolve_synthesis_preferences(
            root,
            selection_id=str(args.preference_selection_id or ""),
            query=query,
            kind=args.kind,
            topic=args.topic,
            tag=args.tag,
            pool=args.pool,
            mode=mode,
            as_of=args.as_of,
            program_ids=linked_program_ids,
            discovery_mode=str(args.discovery_mode or "kb_only"),
            search_protocol_digest=search_protocol_digest,
            input_unit_bindings=input_unit_bindings,
        )
        preference_context = synthesis_preference_state(preferences)
        discovery_required = args.discovery_mode != "kb_only"
        if discovery_required or not selected:
            binding = ensure_evidence_gap_composite(
                root,
                slug=slug,
                filters=filters,
                as_of=args.as_of,
                program_ids=linked_program_ids,
                preference_context=preference_context,
                discovery_mode=str(args.discovery_mode or "kb_only"),
                search_protocol=search_protocol,
            )
            print(
                json.dumps(
                    evidence_gap_handoff(
                        filters=filters,
                        excluded=excluded,
                        composite_binding=binding,
                        reason=(
                            "external_discovery_required"
                            if discovery_required
                            else "no_current_confirmed_units"
                        ),
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 2
        fill_path = out_root / f"{mode}-fill.yaml"
        with mutation_transaction(root, f"prepare-{mode}", [fill_path]):
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
                program_ids=linked_program_ids,
                preference_context=preference_context,
                discovery_mode=str(args.discovery_mode or "kb_only"),
                search_protocol_digest=search_protocol_digest,
                input_unit_bindings=input_unit_bindings,
            )
            ensure_dir(out_root)
            write_yaml_if_changed(fill_path, payload)
        print(rel(root, fill_path))
        return 0
    raise SystemExit(f"unsupported action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())

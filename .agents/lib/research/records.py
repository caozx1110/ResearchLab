"""Record schema: templates, payload skeletons, normalization, history, and store access (iter/locate)."""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .common import (
    load_yaml,
    parse_iso_datetime,
    utc_now_iso,
)
from .evidence import (
    JUDGEMENT_CLAIM_TYPES,
    UNCONFIRMABLE_CLAIM_TYPES,
    confirmation_claims,
    confirmation_content_digest,
    record_external_source_contract,
    validate_claims,
    verification_receipt_violations,
)
from .ids import (
    build_unit_id,
)
from .journal import mutation_transaction
from .paths import (
    UNIT_KIND_DIRS,
    _artifact_list,
    _deep_fill_missing,
    _slug_list,
    _text_list,
    _unique_text_list,
    kind_dir,
    record_path,
    unit_root,
    units_root,
)

INFORMATION_TYPES = {"fact", "inference", "evaluation", "user_opinion", "unverified"}


MATURITY_LEVELS = {"lightweight", "complete"}


DEFAULT_REUSE_FLAGS = {
    "review": False,
    "idea": False,
    "experiment_design": False,
    "paper_writing": False,
    "weekly_report": False,
    "ppt": False,
}


AI_INFORMATION_TYPES = {"inference", "evaluation", "user_opinion"}
WORKFLOW_STATES = {
    "source_ready",
    "awaiting_agent_fill",
    "ready_to_verify",
    "ready_for_review",
    "done",
    "failed_retryable",
}


@contextmanager
def command_mutation(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
) -> Iterator[None]:
    """Delegate command-scoped recovery and locking to the canonical transaction."""
    with mutation_transaction(project_root, op_type, target_paths):
        yield


def _trusted_claim_source_roots(project_root: Path, record: dict[str, Any]) -> dict[str, Path]:
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
            for source_kind in UNIT_KIND_DIRS:
                candidate = record_path(project_root, source_kind, source_unit_id)
                if candidate.exists():
                    roots[source_unit_id] = candidate.parent
                    break
    return roots


def kind_payload_skeleton(kind: str, title: str = "") -> dict[str, Any]:
    if kind == "paper":
        return {
            "basic_info": {
                "title": title,
                "authors": [],
                "institutions": [],
                "venue": "",
                "year": "",
                "source_url": "",
                "code_url": "",
                "project_url": "",
                "abstract": "",
                "arxiv_id": "",
                "doi": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "quick_screen": {
                "paper_type": "",
                "worth_deep_reading": "unknown",
                "judgement_reason": [],
                "backing_strength": "",
                "result_strength": "",
                "experiment_quality": "",
                "reliability": "",
                "novelty": "",
                "relevance_to_current_research": "",
                "screening_mode": "",
                "screening_evidence_pages": [],
                "risks": [],
                "keyword_hits": {},
                "takeaways": [],
                "recommended_next_action": "",
            },
            "core_content": {
                "research_problem": "",
                "motivation": "",
                "story": "",
                "method": "",
                "innovations": [],
                "changes_and_effects": [],
                "mechanism": "",
                "why_it_might_work": "",
            },
            "structure": {
                "refresh_status": "not_started",
                "detected_sections": [],
                "paper_outline": [],
                "open_questions": [],
            },
            "figures": {
                "extraction_status": "not_started",
                "candidate_figures": [],
                "key_figures": [],
            },
            "critique": {
                "assumptions": [],
                "weak_spots": [],
                "experiment_gaps": [],
                "reliability_risks": [],
                "failure_scenarios": [],
                "improvements": [],
                "key_insights": [],
            },
            "state": {
                "reading_status": "unread",
                "needs_reread": False,
                "useful_for_review": False,
                "useful_for_experiment": False,
                "useful_for_writing": False,
                "full_note_status": "not_started",
                "note_generation_mode": "scaffold",
            },
        }
    if kind == "repo":
        return {
            "basic_info": {
                "name": title,
                "owner": "",
                "url": "",
                "paper_url": "",
                "license": "",
                "last_activity": "",
                "environment": [],
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "capability": {
                "problem": "",
                "core_capabilities": [],
                "inputs": [],
                "outputs": [],
                "supported_tasks": [],
                "unsupported_tasks": [],
                "boundary": "",
                "candidate_roles": [],
            },
            "structure": {
                "scan_status": "not_started",
                "scan_applicability": "unknown",
                "scan_reason": "",
                "repo_root": "",
                "top_level_dirs": [],
                "top_level_files": [],
                "languages": [],
                "core_modules": [],
                "entrypoint_candidates": [],
                "entrypoints": [],
                "training_flow": [],
                "inference_flow": [],
                "config_system": [],
                "data_flow": [],
                "critical_modules": [],
            },
            "reuse": {
                "directly_reusable": [],
                "worth_borrowing": [],
                "worth_modifying": [],
                "modification_difficulty": [],
                "pipeline_value": [],
            },
            "risk": {
                "engineering_complexity": "",
                "dependency_weight": "",
                "reproduction_barrier": "",
                "performance_boundary": "",
                "constraints": [],
                "not_suitable_for": [],
            },
        }
    if kind == "dataset":
        return {
            "basic_info": {
                "name": title,
                "owner": "",
                "url": "",
                "platform": "",
                "license": "",
                "version": "",
                "last_updated": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "profile": {
                "positioning": "",
                "scale": "",
                "platform": "",
                "license": "",
            },
            "composition": {
                "summary": "",
                "modalities": [],
                "tasks": [],
                "embodiment": [],
                "scenes": [],
            },
            "access": {
                "schema_access": "",
                "formats": [],
                "splits": [],
                "schema": [],
                "entrypoints": [],
            },
            "quality": {
                "suitability_risks": "",
                "known_issues": [],
                "constraints": [],
                "risks": [],
            },
            "reuse": {
                "supported_uses": [],
                "unsupported_uses": [],
            },
            "state": {
                "profile_status": "not_started",
            },
        }
    if kind == "blog":
        return {
            "basic_info": {
                "title": title,
                "author": "",
                "platform": "",
                "year": "",
                "url": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "positioning": {
                "content_type": "",
                "best_reading_stage": "",
                "main_value": "",
            },
            "content": {
                "key_points": [],
                "hard_parts_explained": [],
                "intuitions": [],
                "supports": [],
            },
            "credibility": {
                "reference_mode": "",
                "good_for_reference": [],
                "needs_verification": [],
                "best_use": "",
            },
        }
    if kind == "idea":
        return {
            "origin": {
                "title": title,
                "source": "",
                "theme": "",
            },
            "candidate": {
                "bundle_id": "",
                "strategy": "",
                "pool": "",
            },
            "problem": {
                "problem_definition": "",
                "pain_point": "",
                "target_improvement": "",
                "scope": "",
            },
            "hypothesis": {
                "core_hypothesis": "",
                "why_it_might_work": "",
                "key_mechanism": "",
                "difference_from_prior_work": "",
            },
            "analysis": {
                "related_work": [],
                "novelty": "",
                "incremental_or_new_direction": "",
                "feasibility": "",
                "minimum_validation_path": "",
                "risks": [],
                "next_actions": [],
            },
            "review": {
                "review_status": "not_started",
                "recommendation": "pending_confirmation",
                "score_breakdown": {},
                "evidence_gaps": [],
                "killer_questions": [],
            },
            "selection": {
                "selected_rank": "",
                "selected_reason": "",
                "selected_by": "",
                "selected_at": "",
                "selection_evidence": [],
                "selection_method": "",
            },
            "state": {
                "progress_state": "spark",
                "worth_pursuing": "unknown",
            },
        }
    if kind == "experiment":
        return {
            "basic_info": {
                "title": title,
                "program_id": "",
                "idea_id": "",
                "goal": "",
                "owner": "",
            },
            "setup": {
                "data": [],
                "model": "",
                "hyperparameters": {},
                "runtime": {},
                "hardware": [],
                "environment": [],
            },
            "process": {
                "change_summary": [],
                "delta_from_previous": [],
                "why_this_run": "",
                "tested_hypothesis": "",
            },
            "results": {
                "metrics": {},
                "metric_contract": {
                    "shape": "name -> {name, value, unit, direction}",
                    "directions": ["higher-better", "lower-better", "neutral", "unknown"],
                },
                "comparison": [],
                "met_expectation": "unknown",
                "abnormalities": [],
                "artifacts": [],
            },
            "diagnosis": {
                "failure_modes": [],
                "likely_causes": [],
                "ruled_out_causes": [],
                "unknowns": [],
                "next_actions": [],
                "comparison_context": {},
            },
        }
    raise SystemExit(f"Unsupported unit kind: {kind}")


def _extract_unit_id_hash(unit_id: str) -> str:
    match = re.search(r"-([0-9a-f]{6,16})$", unit_id.strip().lower())
    return match.group(1) if match else ""


def _record_template(kind: str, *, title: str, maturity: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    unit_id = build_unit_id(kind, title, str(source.get("original_uri") if source else ""))
    now = utc_now_iso()
    return {
        "id": unit_id,
        "legacy_ids": [],
        "kind": kind,
        "title": title,
        "status": "draft",
        "maturity": maturity if maturity in MATURITY_LEVELS else "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "confidence": 0.9,
        "created_at": now,
        "first_ingested_at": now,
        "updated_at": now,
        "last_human_confirmed_at": "",
        "tags": [],
        "topics": [],
        "candidate_pools": [],
        "program_ids": [],
        "priority": "normal",
        "summary": "",
        "links": [],
        "reuse_flags": dict(DEFAULT_REUSE_FLAGS),
        "taxonomy": {
            "primary_topic": "",
            "secondary_topics": [],
            "canonical_tags": [],
            "topic_sources": [],
            "tag_sources": [],
            "pool_sources": [],
        },
        "artifacts": [],
        "source": source or {},
        "payload": kind_payload_skeleton(kind, title),
        "history": [],
    }


def record_summary(record: dict[str, Any]) -> str:
    summary = str(record.get("summary") or "").strip()
    if summary:
        return summary
    payload = record.get("payload", {})
    if record.get("kind") == "paper":
        reason = payload.get("quick_screen", {}).get("judgement_reason", [])
        if reason:
            return str(reason[0])
        takeaways = payload.get("quick_screen", {}).get("takeaways", [])
        if takeaways:
            return str(takeaways[0])
    if record.get("kind") == "repo":
        boundary = payload.get("capability", {}).get("boundary")
        if boundary:
            return str(boundary)
        capabilities = payload.get("capability", {}).get("core_capabilities", [])
        if capabilities:
            return str(capabilities[0])
    if record.get("kind") == "dataset":
        positioning = payload.get("profile", {}).get("positioning")
        if positioning:
            return str(positioning)
        composition = payload.get("composition", {}).get("summary")
        if composition:
            return str(composition)
    if record.get("kind") == "idea":
        problem = payload.get("problem", {}).get("problem_definition")
        if problem:
            return str(problem)
        hypothesis = payload.get("hypothesis", {}).get("core_hypothesis")
        if hypothesis:
            return str(hypothesis)
    if record.get("kind") == "experiment":
        goal = payload.get("basic_info", {}).get("goal")
        if goal:
            return str(goal)
    return ""


def append_history(
    record: dict[str, Any],
    *,
    action: str,
    summary: str,
    information_types: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    record.setdefault("history", []).append(
        {
            "timestamp": utc_now_iso(),
            "action": action,
            "summary": summary,
            "information_types": information_types or ["fact"],
            "artifacts": artifacts or [],
        }
    )
    record["updated_at"] = utc_now_iso()


def default_record(kind: str, *, title: str, maturity: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    record = _record_template(kind, title=title, maturity=maturity, source=source)
    append_history(record, action="created", summary=f"Created {kind} record.")
    return record


def normalize_record_schema(record: dict[str, Any], *, project_root: Path | None = None) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SystemExit("Invalid record payload")
    kind = str(record.get("kind") or "")
    if kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    title = str(record.get("title") or "")
    maturity = str(record.get("maturity") or "lightweight")
    source = record.get("source", {})
    if isinstance(source, dict):
        source = {key: value for key, value in source.items() if key != "backup_warning"}
        record = {**record, "source": source}
    else:
        source = {}
    template = _record_template(kind, title=title, maturity=maturity, source=source)
    normalized = _deep_fill_missing(record, template)
    normalized["title"] = title or str(normalized.get("title") or normalized["id"])
    normalized["status"] = str(normalized.get("status") or "draft")
    normalized["maturity"] = str(normalized.get("maturity") or "lightweight")
    normalized["confirmation_status"] = str(normalized.get("confirmation_status") or "auto_confirmed")
    try:
        normalized["revision"] = max(0, int(normalized.get("revision", 0)))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Invalid record revision: expected a non-negative integer") from exc
    normalized["legacy_ids"] = [
        item
        for item in _unique_text_list(normalized.get("legacy_ids"))
        if item and item != str(normalized.get("id") or "")
    ]
    normalized["information_types"] = sorted(
        item for item in {str(value) for value in normalized.get("information_types", [])} if item in INFORMATION_TYPES
    ) or ["fact"]
    confirmation_invalidated = False
    verification = normalized.get("payload", {}).get("verification") if isinstance(normalized.get("payload"), dict) else None
    if isinstance(verification, dict):
        evidence_root = None
        if project_root is not None:
            evidence_root = unit_root(
                project_root,
                str(normalized.get("kind") or ""),
                str(normalized.get("id") or ""),
            )
        verification_violations = verification_receipt_violations(
            normalized,
            evidence_root,
            external_source=record_external_source_contract(normalized),
            source_roots=_trusted_claim_source_roots(project_root, normalized) if project_root is not None else None,
            check_artifacts=project_root is not None,
        )
        if verification_violations:
            verification["invalidation"] = {
                "reason": "verification_stale",
                "violations": verification_violations,
            }
            if normalized.get("confirmation_status") == "confirmed":
                confirmation_invalidated = True
                normalized["confirmation_status"] = "pending_user_confirmation"
                normalized["needs_human_confirmation"] = True
    confirmation = normalized.get("confirmation")
    if isinstance(confirmation, dict) and confirmation.get("content_digest"):
        stored_digest = str(confirmation.get("content_digest") or "")
        current_digest = confirmation_content_digest(normalized)
        if current_digest != stored_digest:
            confirmation_invalidated = True
            normalized["confirmation_status"] = "pending_user_confirmation"
            normalized["needs_human_confirmation"] = True
            confirmation["invalidation"] = {
                "reason": "confirmable_content_changed",
                "stored_content_digest": stored_digest,
                "current_content_digest": current_digest,
            }
    normalized["needs_human_confirmation"] = (
        confirmation_invalidated
        or (
            (
                _record_needs_gate(normalized)[0]
                or bool(
                    {
                        str(claim.get("claim_type") or "")
                        for claim in confirmation_claims(normalized)
                        if isinstance(claim, dict)
                    }
                    & (JUDGEMENT_CLAIM_TYPES | UNCONFIRMABLE_CLAIM_TYPES)
                )
            )
            and normalized["confirmation_status"] != "confirmed"
        )
    )
    normalized["tags"] = _slug_list(normalized.get("tags"))
    normalized["topics"] = _slug_list(normalized.get("topics"))
    normalized["candidate_pools"] = _slug_list(normalized.get("candidate_pools"))
    normalized["program_ids"] = _slug_list(normalized.get("program_ids"))
    normalized["artifacts"] = _artifact_list(normalized.get("artifacts"))
    normalized["links"] = [dict(item) for item in normalized.get("links", []) if isinstance(item, dict) and item.get("target_id")]
    normalized["history"] = [dict(item) for item in normalized.get("history", []) if isinstance(item, dict)]
    if not normalized["history"]:
        append_history(normalized, action="created", summary=f"Backfilled history for {kind} record.")
    taxonomy = normalized.get("taxonomy", {})
    if not isinstance(taxonomy, dict):
        taxonomy = {}
    taxonomy.setdefault("primary_topic", normalized["topics"][0] if normalized["topics"] else "")
    taxonomy["secondary_topics"] = [topic for topic in normalized["topics"] if topic != taxonomy["primary_topic"]]
    taxonomy["canonical_tags"] = list(normalized["tags"])
    taxonomy["topic_sources"] = _text_list(taxonomy.get("topic_sources"))
    taxonomy["tag_sources"] = _text_list(taxonomy.get("tag_sources"))
    taxonomy["pool_sources"] = _text_list(taxonomy.get("pool_sources"))
    normalized["taxonomy"] = taxonomy
    payload = normalized.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    normalized["payload"] = _deep_fill_missing(payload, kind_payload_skeleton(kind, normalized["title"]))
    return normalized


def _record_needs_gate(record: dict[str, Any]) -> tuple[bool, set[str], bool]:
    info_types = {str(value) for value in record.get("information_types") or []}
    ai_info_types = info_types & AI_INFORMATION_TYPES
    source = record.get("source") or {}
    source_is_ai = isinstance(source, dict) and str(source.get("kind") or "").lower() == "ai"
    return bool(ai_info_types) or source_is_ai, ai_info_types, source_is_ai


def _workflow_marker(record: dict[str, Any]) -> str:
    kind = str(record.get("kind") or "")
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    state = payload.get("state")
    state = state if isinstance(state, dict) else {}
    if kind in {"paper", "blog"}:
        return str(state.get("full_note_status") or "")
    if kind == "repo":
        return str(state.get("capability_fill_status") or "")
    if kind == "dataset":
        return str(state.get("profile_status") or "")
    if kind == "idea":
        review = payload.get("review")
        analysis = payload.get("analysis")
        review = review if isinstance(review, dict) else {}
        analysis = analysis if isinstance(analysis, dict) else {}
        return str(review.get("review_status") or analysis.get("analysis_status") or "")
    if kind == "experiment":
        diagnosis = payload.get("diagnosis")
        diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
        return str(diagnosis.get("verification_status") or state.get("diagnosis_status") or "")
    return ""


def _has_unverified_judgement_signal(record: dict[str, Any]) -> bool:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    quick_screen = payload.get("quick_screen")
    quick_screen = quick_screen if isinstance(quick_screen, dict) else {}
    for key in (
        "worth_deep_reading",
        "judgement_reason",
        "backing_strength",
        "result_strength",
        "experiment_quality",
        "reliability",
        "novelty",
        "relevance_to_current_research",
        "screening_mode",
        "risks",
        "takeaways",
        "recommended_next_action",
    ):
        value = quick_screen.get(key)
        if value not in (None, "", "unknown", False, [], {}):
            return True
    return False


def _has_substantive_judgement_content(record: dict[str, Any]) -> bool:
    """Reuse the confirmation gate's substance criterion without import cycling."""
    from .confirm import has_substantive_content

    return has_substantive_content(record, str(record.get("kind") or ""))


def record_workflow_state(record: dict[str, Any]) -> str:
    """Single pure classifier shared by next/review/status/auto callers."""
    status = str(record.get("status") or "").strip().lower()
    confirmation_status = str(record.get("confirmation_status") or "")
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    source = record.get("source")
    source = source if isinstance(source, dict) else {}
    marker = _workflow_marker(record).strip().lower()
    claims = confirmation_claims(record)
    information_types = {str(value) for value in record.get("information_types") or []}
    claim_types = {str(claim.get("claim_type") or "") for claim in claims}
    unconfirmable_claims = bool(claim_types & UNCONFIRMABLE_CLAIM_TYPES)
    judgement_claims_present = bool(claim_types & JUDGEMENT_CLAIM_TYPES)
    judgement_record = bool(
        _record_needs_gate(record)[0]
        or "unverified" in information_types
        or judgement_claims_present
        or _has_unverified_judgement_signal(record)
    )
    needs_gate = (
        _record_needs_gate(record)[0]
        or "unverified" in information_types
        or bool(claim_types & (JUDGEMENT_CLAIM_TYPES | UNCONFIRMABLE_CLAIM_TYPES))
        or _has_unverified_judgement_signal(record)
    )
    failure_markers = {
        status,
        marker,
        str(source.get("status") or "").strip().lower(),
        str(payload.get("workflow_status") or "").strip().lower(),
    }
    if confirmation_status == "rejected":
        return "done"
    if failure_markers & {"failed_retryable", "retryable_failure", "failed-retryable"}:
        return "failed_retryable"
    if status in {"archived", "completed"}:
        return "done"

    verification = payload.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    claims_structurally_complete = (
        bool(claims)
        and not unconfirmable_claims
        and not validate_claims(claims)
    )
    judgement_material_complete = (
        claims_structurally_complete
        and judgement_claims_present
        and _has_substantive_judgement_content(record)
    )
    receipt_violations = verification_receipt_violations(
        record,
        None,
        check_artifacts=False,
    )
    verification_current = (
        claims_structurally_complete
        and not verification.get("invalidation")
        and not receipt_violations
        and (not judgement_record or judgement_material_complete)
    )
    requires_reverification = (
        judgement_record
        and not verification_current
        and (
            confirmation_status == "confirmed"
            or bool(verification)
        )
    )
    if requires_reverification:
        return "ready_to_verify" if judgement_material_complete else "awaiting_agent_fill"
    if confirmation_status == "confirmed":
        return "done"
    if marker in {"awaiting_agent_fill", "agent_fill_required"}:
        return "awaiting_agent_fill"
    if marker in {"ready_to_verify", "agent_fill_complete"}:
        if judgement_record and not judgement_material_complete:
            return "awaiting_agent_fill"
        return "ready_to_verify"
    if confirmation_status == "pending_user_confirmation":
        if verification_current:
            return "ready_for_review"
        if marker in {"pending_user_confirmation", "ready_for_review"}:
            return "awaiting_agent_fill" if needs_gate else "ready_for_review"
        if marker == "not_started":
            return "source_ready" if needs_gate else "ready_for_review"
        if not marker and str(record.get("kind") or "") in {"paper", "blog", "repo", "dataset", "idea"}:
            return "source_ready" if needs_gate else "ready_for_review"
        if needs_gate or marker:
            return "awaiting_agent_fill"
        return "ready_for_review"
    return "source_ready"


def is_ready_for_human_review(record: dict[str, Any]) -> bool:
    return record_workflow_state(record) == "ready_for_review"


def iter_records(project_root: Path, *, kind: str | None = None) -> list[dict[str, Any]]:
    kinds = [kind] if kind else list(UNIT_KIND_DIRS)
    items: list[dict[str, Any]] = []
    for item_kind in kinds:
        root = units_root(project_root) / kind_dir(item_kind)
        if not root.exists():
            continue
        for path in sorted(root.glob("*/record.yaml")):
            payload = load_yaml(path, default={})
            if isinstance(payload, dict):
                try:
                    items.append(normalize_record_schema(payload, project_root=project_root))
                except SystemExit:
                    items.append(payload)
    return items


def _record_lookup_path(project_root: Path, record: dict[str, Any]) -> Path | None:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    if kind not in UNIT_KIND_DIRS or not unit_id:
        return None
    return record_path(project_root, kind, unit_id)


def _record_hash_suffix(unit_id: str) -> str:
    suffix = unit_id.rsplit("-", 1)[-1].lower()
    if re.fullmatch(r"[0-9a-f]{6,40}", suffix):
        return suffix
    return ""


def _ambiguous_record_reference(reference: str, records: list[dict[str, Any]]) -> None:
    candidate_ids = sorted({str(record.get("id") or "") for record in records if str(record.get("id") or "")})
    if candidate_ids:
        raise SystemExit(f"Ambiguous record reference: {reference}\nCandidates:\n- " + "\n- ".join(candidate_ids))
    raise SystemExit(f"Ambiguous record reference: {reference}")


def _resolve_unique_record_reference(reference: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    if len(records) == 1:
        return records[0]
    _ambiguous_record_reference(reference, records)
    return None


def _record_modified_sort_key(project_root: Path, record: dict[str, Any]) -> tuple[float, float, str]:
    path = _record_lookup_path(project_root, record)
    mtime = path.stat().st_mtime if path and path.exists() else 0.0
    timestamp = str(record.get("updated_at") or record.get("created_at") or record.get("first_ingested_at") or "")
    parsed = parse_iso_datetime(timestamp)
    return (mtime, parsed.timestamp() if parsed else 0.0, str(record.get("id") or ""))


def locate_record(project_root: Path, unit_id: str, *, kind: str | None = None, fuzzy: bool = True) -> tuple[dict[str, Any], Path]:
    exact_reference = str(unit_id)
    reference = exact_reference.strip()
    search_kinds = [kind] if kind else list(UNIT_KIND_DIRS)
    for search_kind in search_kinds:
        if search_kind not in UNIT_KIND_DIRS:
            raise SystemExit(f"Unsupported unit kind: {search_kind}")
    for search_kind in search_kinds:
        path = record_path(project_root, search_kind, exact_reference)
        if path.exists():
            payload = load_yaml(path, default={})
            if isinstance(payload, dict):
                return normalize_record_schema(payload, project_root=project_root), path
    records = iter_records(project_root, kind=kind) if kind else iter_records(project_root)
    for record in records:
        if exact_reference in _unique_text_list(record.get("legacy_ids")):
            current_kind = str(record.get("kind") or "")
            current_id = str(record.get("id") or "")
            if current_kind in UNIT_KIND_DIRS and current_id:
                return record, record_path(project_root, current_kind, current_id)
    if not fuzzy:
        raise SystemExit(f"Record not found: {unit_id}")
    folded = reference.casefold()
    if folded in {"last", "current"}:
        modified_records = [record for record in records if _record_lookup_path(project_root, record)]
        if modified_records:
            resolved = max(modified_records, key=lambda record: _record_modified_sort_key(project_root, record))
            path = _record_lookup_path(project_root, resolved)
            if path:
                return resolved, path
    if folded:
        prefix_matches = [
            record
            for record in records
            if str(record.get("id") or "").casefold().startswith(folded)
            or bool(_record_hash_suffix(str(record.get("id") or "")).casefold().startswith(folded))
        ]
        resolved = _resolve_unique_record_reference(reference, prefix_matches)
        if resolved:
            path = _record_lookup_path(project_root, resolved)
            if path:
                return resolved, path
        title_reference = folded
        title_matches = [
            record
            for record in records
            if title_reference in str(record.get("title") or "").casefold()
        ]
        resolved = _resolve_unique_record_reference(reference, title_matches)
        if resolved:
            path = _record_lookup_path(project_root, resolved)
            if path:
                return resolved, path
    raise SystemExit(f"Record not found: {unit_id}")


__all__ = [
    "INFORMATION_TYPES",
    "MATURITY_LEVELS",
    "DEFAULT_REUSE_FLAGS",
    "AI_INFORMATION_TYPES",
    "WORKFLOW_STATES",
    "command_mutation",
    "kind_payload_skeleton",
    "_extract_unit_id_hash",
    "_record_template",
    "record_summary",
    "append_history",
    "default_record",
    "normalize_record_schema",
    "_record_needs_gate",
    "record_workflow_state",
    "is_ready_for_human_review",
    "iter_records",
    "_record_lookup_path",
    "_record_hash_suffix",
    "_ambiguous_record_reference",
    "_resolve_unique_record_reference",
    "_record_modified_sort_key",
    "locate_record",
]

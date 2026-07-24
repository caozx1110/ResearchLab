#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Mapping

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

from research.common import add_project_root_argument, ensure_dir, load_yaml, print_resolved_project_roots, slugify, utc_now_iso, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.core import (
    append_history,
    apply_confirmation,
    apply_record_governance,
    build_index,
    build_unit_id,
    candidate_pools_path,
    command_mutation,
    default_record,
    ensure_workspace,
    iter_records,
    kb_root,
    locate_record,
    checkpoint_and_report,
    project_root,
    record_path,
    rel,
    require_confirmation_provenance,
    require_user_authorization,
    synthesis_root,
    topic_taxonomy_path,
    write_record,
)
from research.evidence import attach_claims, build_verification_receipt, validate_claims, verify_claim_evidence
from research.judgements import apply_judgement_rejection, readiness_violations, require_judgement_snapshot
from research.preference_selection import (
    canonical_digest,
    regular_file_binding,
    resolve_operation_preferences,
    task_context_digest,
)

PREFERENCE_SKILL = "idea-workbench"
PREFERENCE_OPERATIONS = {"generate", "analyze", "review", "discuss"}
GENERATION_FILL_NAME = "generation-fill.yaml"
GENERATION_ORIENTATION_NAME = "generation-orientation.yaml"
GENERATION_CORPUS_NAME = "generation-evidence-corpus.yaml"
MAX_GENERATED_CANDIDATES = 12

DISCUSSION_CLAIMS = (
    ("challenge", "evaluation"),
    ("probe", "inference"),
    ("counter-example", "evaluation"),
    ("constructive-suggestion", "inference"),
    ("conclusion", "evaluation"),
)

ANALYSIS_CLAIMS = (
    ("novelty", "evaluation"),
    ("feasibility", "evaluation"),
    ("recommendation", "evaluation"),
    ("killer-question", "inference"),
)

EVIDENCE_REF_FORMAT = {
    "source_unit_id": "canonical KB unit id, for example p-... or r-...",
    "artifact": "artifact path relative to that unit directory, for example parse-cache.yaml",
    "locator": "page=N, section, anchor, or file:line",
    "quote": "short verbatim span; verify checks it against the cited unit artifact",
    "summary": "optional one-line explanation of relevance",
}

_PENDING_CHECKPOINT: ContextVar[tuple[Path, str, str, list[Path]] | None] = ContextVar(
    "idea_pending_checkpoint", default=None
)
_ACTIVE_MUTATION: ContextVar[bool] = ContextVar("idea_active_mutation", default=False)


def _index_checkpoint_paths(root: Path) -> list[Path]:
    return [
        kb_root(root) / "index.yaml",
        kb_root(root) / "index.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
    ]


def _queue_checkpoint(root: Path, *, trigger: str, message: str, target_paths: list[Path]) -> dict:
    if _ACTIVE_MUTATION.get():
        _PENDING_CHECKPOINT.set((root, trigger, message, target_paths))
        return {"committed": False, "status": "pending-transaction-commit"}
    return checkpoint_and_report(root, trigger=trigger, message=message, target_paths=target_paths)


def _idea_command_targets(args, root: Path) -> list[Path]:
    targets = list(_index_checkpoint_paths(root))
    if args.command == "capture":
        idea_id = build_unit_id("idea", args.title, args.source)
        return [record_path(root, "idea", idea_id), *targets]
    if args.command == "generate":
        bundle_id = generation_bundle_id(args)
        working_root = bundle_root(root, bundle_id)
        private_targets = [
            working_root / GENERATION_FILL_NAME,
            working_root / GENERATION_ORIENTATION_NAME,
            working_root / GENERATION_CORPUS_NAME,
        ]
        if args.phase == "prepare":
            return private_targets
        plan = generation_materialization_plan(root, args, bundle_id=bundle_id)
        args._generation_plan = plan
        idea_paths = [record_path(root, "idea", item["idea_id"]) for item in plan["candidates"]]
        return [bundle_index_path(root, bundle_id), *idea_paths, *private_targets, *targets]
    if args.command in {"review-assist", "select-best"}:
        idea_ids = list(args.idea_id)
        bundle_id = args.bundle_id
        if bundle_id:
            payload = load_yaml(bundle_index_path(root, bundle_id), default={})
            idea_ids = list(payload.get("idea_ids", [])) if isinstance(payload, dict) else []
        elif args.pool:
            normalized_pool = slugify(args.pool, max_words=12)
            idea_ids = [
                record["id"] for record in iter_records(root, kind="idea")
                if normalized_pool in record.get("candidate_pools", [])
            ]
            bundle_id = normalized_pool or "idea-pool"
        else:
            bundle_id = f"idea-review-{hashlib.sha1(' '.join(idea_ids).encode('utf-8')).hexdigest()[:8]}"
        bundle = bundle_root(root, bundle_id)
        extra = [bundle / "review-assist.md"] if args.command == "review-assist" else [bundle / "selection.yaml"]
        return [bundle_index_path(root, bundle_id), *extra, *[record_path(root, "idea", idea_id) for idea_id in idea_ids], *targets]
    record, path = locate_record(root, args.idea_id, kind="idea")
    unit = path.parent
    if args.command in {"analyze", "review"}:
        return [
            path,
            unit / f"{args.command}-fill.yaml",
            unit / f"{args.command}-orientation.yaml",
            unit / f"{args.command}-evidence-corpus.yaml",
            unit / f"{args.command}.yaml",
            unit / "idea-card.md",
            *targets,
        ]
    if args.command in {"discuss", "spar"}:
        return [
            path,
            unit / "discussion-fill.yaml",
            unit / "discuss-orientation.yaml",
            unit / "discuss-evidence-corpus.yaml",
            unit / "discussion-judgements.yaml",
            *targets,
        ]
    return [path, *targets]


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)
    parser.add_argument("--user-authorization", default="")
    parser.add_argument("--authorization-source", default="")


def descriptive_counts(record: dict) -> dict:
    related_count = len(record["payload"]["analysis"].get("related_work", []))
    next_action_count = len(record["payload"]["analysis"].get("next_actions", []))
    link_count = len(record.get("links", []))
    return {
        "related_work_items": related_count,
        "next_action_items": next_action_count,
        "linked_units": link_count,
        "note": "Descriptive orientation only; these counts are not scores or verdicts.",
    }


def review_payload(record: dict) -> dict:
    analysis = record["payload"]["analysis"]
    review = record["payload"]["review"]
    return {
        "idea_id": record["id"],
        "status": review.get("review_status") or "not_started",
        "information_types": ["inference", "evaluation", "unverified"],
        "novelty": analysis.get("novelty", ""),
        "feasibility": analysis.get("feasibility", ""),
        "recommendation": review.get("recommendation") or "pending_confirmation",
        "killer_questions": review.get("killer_questions", []),
        "claims": review.get("claims", []),
        "descriptive_counts": descriptive_counts(record),
    }


def _idea_discussion_decision_context(
    root: Path,
    idea_id: str,
    conclusion_id: str,
    expected_snapshot: str,
) -> tuple[dict, Path, Path, list[dict], dict, Path]:
    record, path = locate_record(root, idea_id, kind="idea")
    unit_root = path.parent
    judgements = load_discussion_judgements(unit_root, record["id"])
    matches = [item for item in judgements if str(item.get("id") or "") == conclusion_id]
    if len(matches) != 1:
        raise ValueError("discussion conclusion is no longer uniquely available")
    selected = matches[0]
    sidecar_path = discussion_judgements_path(unit_root)
    violations = readiness_violations(root, selected, sidecar_path)
    if violations:
        raise ValueError("Discussion conclusion is not ready for this decision")
    require_judgement_snapshot(
        selected,
        expected_snapshot=expected_snapshot,
        owner="idea-workbench",
        path=rel(root, sidecar_path),
        root=root,
    )
    return record, path, unit_root, judgements, selected, sidecar_path


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
    route = item.get("confirm_route" if decision == "confirm" else "reject_route")
    route = route if isinstance(route, dict) else {}
    expected_phase = "confirm" if decision == "confirm" else "reject"
    if route.get("owner") != "idea-workbench" or route.get("action") != "discuss" or route.get("phase") != expected_phase:
        raise ValueError("idea review route is invalid")
    snapshot = item.get("snapshot_binding")
    if not isinstance(snapshot, dict):
        raise ValueError("idea review snapshot is missing")
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    record, path, unit_root, _judgements, selected, sidecar_path = _idea_discussion_decision_context(
        root,
        str(route.get("idea_id") or ""),
        str(route.get("conclusion_id") or ""),
        snapshot_text,
    )
    candidate = dict(selected)
    if decision == "confirm":
        claims = candidate.get("payload", {}).get("claims", [])
        apply_confirmation(
            candidate,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="idea.py discuss confirm",
            project_root=root,
            verification_root=unit_root,
            trusted_source_roots=_trusted_claim_source_roots(root, claims),
        )
    elif decision == "reject":
        apply_judgement_rejection(candidate, reason=rejection_reason)
    else:
        raise ValueError("idea review decision is invalid")
    return {
        "owner": "idea-workbench",
        "decision": decision,
        "idea_id": str(record["id"]),
        "conclusion_id": str(route.get("conclusion_id") or ""),
        "target_paths": [path, sidecar_path],
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
    route = item["confirm_route" if decision == "confirm" else "reject_route"]
    snapshot_text = json.dumps(item["snapshot_binding"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    record, _path, unit_root, judgements, selected, sidecar_path = _idea_discussion_decision_context(
        root, plan["idea_id"], plan["conclusion_id"], snapshot_text
    )
    if decision == "reject":
        apply_judgement_rejection(selected, reason=rejection_reason)
        selected["updated_at"] = utc_now_iso()
        for projection in record.setdefault("payload", {}).setdefault("discussion", {}).setdefault("conclusions", []):
            if isinstance(projection, dict) and str(projection.get("judgement_id") or "") == plan["conclusion_id"]:
                projection["confirmation_status"] = "rejected"
                projection["rejection"] = dict(selected.get("rejection") or {})
        action, summary, information_types = (
            "idea-discussion-rejected",
            "Rejected one evidence-grounded discussion conclusion.",
            ["user_opinion", "evaluation"],
        )
    else:
        claims = selected.get("payload", {}).get("claims", [])
        apply_confirmation(
            selected,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="idea.py discuss confirm",
            project_root=root,
            verification_root=unit_root,
            trusted_source_roots=_trusted_claim_source_roots(root, claims),
        )
        selected["updated_at"] = utc_now_iso()
        for projection in record.setdefault("payload", {}).setdefault("discussion", {}).setdefault("conclusions", []):
            if isinstance(projection, dict) and str(projection.get("judgement_id") or "") == plan["conclusion_id"]:
                projection["confirmation_status"] = "confirmed"
                projection["confirmation"] = {
                    "by": selected.get("confirmation", {}).get("by", ""),
                    "at": selected.get("confirmation", {}).get("at", ""),
                }
        action, summary, information_types = (
            "idea-discussion-confirmed",
            "Confirmed one evidence-grounded discussion conclusion.",
            ["inference", "evaluation"],
        )
    write_discussion_judgements(unit_root, record["id"], judgements)
    append_history(record, action=action, summary=summary, information_types=information_types, artifacts=[rel(root, sidecar_path)])
    write_record(root, record)
    return list(plan["target_paths"])


def idea_card(record: dict, review: dict) -> str:
    return f"""# {record.get('title', '')}

## 问题定义

{record['payload']['problem'].get('problem_definition') or '待补充。'}

## 核心假设

{record['payload']['hypothesis'].get('core_hypothesis') or '待补充。'}

## 新意与相关工作

- 新意判断：{review.get('novelty')}
- related work：{", ".join(record['payload']['analysis'].get('related_work', [])) or '-'}

## 可行性分析

- 可行性：{review.get('feasibility')}
- 最小验证路径：{record['payload']['analysis'].get('minimum_validation_path') or '待补充。'}

## Review 摘要

- recommendation：{review.get('recommendation')}
- evidence-backed claims：{len(review.get('claims', []))}

## 下一步

{chr(10).join(f"- {item}" for item in (record['payload']['analysis'].get('next_actions') or ['待补充下一步']))}
"""


def bundle_root(root: Path, bundle_id: str) -> Path:
    return synthesis_root(root) / "idea-pools" / bundle_id


def bundle_index_path(root: Path, bundle_id: str) -> Path:
    return bundle_root(root, bundle_id) / "index.yaml"


def generation_bundle_id(args) -> str:
    return args.bundle_id or (
        f"idea-bundle-{slugify(args.title, max_words=6) or 'ideas'}-"
        f"{hashlib.sha1(args.title.encode('utf-8')).hexdigest()[:6]}"
    )


def _idea_phase_contract(operation: str) -> dict[str, object]:
    if operation == "generate":
        fillable = [
            "candidates[].title",
            "candidates[].strategy",
            "candidates[].problem",
            "candidates[].hypothesis",
            "candidates[].next_actions",
        ]
        verify = "validate-all-slots-then-atomically-materialize-records-and-bundle"
    elif operation == "discuss":
        fillable = ["reviewer", "conclusion", "claims[].text", "claims[].evidence_refs"]
        verify = "validate-evidence-and-persist-one-agent-authored-conclusion"
    else:
        fillable = ["reviewer", "selection_rank", "claims[].text", "claims[].evidence_refs"]
        verify = "validate-evidence-and-persist-agent-authored-judgements"
    return {
        "prepare": "owner-writes-empty-scaffold-and-immutable-orientation",
        "author": "runtime-agent",
        "verify": verify,
        "fillable_fields": fillable,
    }


def generation_request_context(args, *, bundle_id: str) -> dict[str, object]:
    return {
        "title": str(args.title),
        "problem": str(args.problem),
        "hypothesis": str(args.hypothesis),
        "source": str(args.source),
        "count": int(args.count),
        "pool": str(args.pool),
        "bundle_id": bundle_id,
    }


def idea_preference_orientation(
    operation: str,
    *,
    canonical_id: str,
    request_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if operation not in PREFERENCE_OPERATIONS:
        raise ValueError("unsupported idea preference operation")
    payload: dict[str, object] = {
        "schema": "idea-preference-orientation/v1",
        "canonical_id": canonical_id,
        "canonical_kind": "idea-generation-bundle" if operation == "generate" else "idea",
        "skill": PREFERENCE_SKILL,
        "operation": operation,
        "phase_contract": _idea_phase_contract(operation),
        "evidence_corpus": "frozen-pre-authoring-canonical-unit-artifacts",
    }
    if operation == "generate":
        if request_context is None:
            raise ValueError("idea generation orientation requires exact request context")
        payload.update(
            {
                "request_context_digest": canonical_digest(dict(request_context)),
                "candidate_count": int(request_context["count"]),
                "slot_ids": [
                    f"candidate-{index:02d}"
                    for index in range(1, int(request_context["count"]) + 1)
                ],
            }
        )
    return payload


def _evidence_corpus_snapshot(
    root: Path,
    *,
    excluded_paths: set[Path] | None = None,
) -> dict[str, object]:
    """Freeze value-free identity/byte bindings for pre-authoring KB artifacts."""
    excluded = {path.absolute() for path in excluded_paths or set()}
    units = kb_root(root) / "units"
    entries: list[dict[str, str]] = []
    if units.exists():
        if units.is_symlink() or not units.is_dir():
            raise ValueError("canonical unit corpus is unsafe")
        for path in sorted(units.rglob("*"), key=lambda item: item.as_posix()):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("canonical unit corpus contains a symlink")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("canonical unit corpus contains a non-regular artifact")
            if path.absolute() in excluded:
                continue
            binding = regular_file_binding(
                path,
                logical_identity=path.relative_to(root).as_posix(),
                trusted_root=root,
            )
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "identity_digest": binding["identity_digest"],
                    "bytes_digest": binding["bytes_digest"],
                }
            )
    return {
        "schema": "idea-evidence-corpus/v1",
        "entries": entries,
        "identity_digest": canonical_digest(
            [{"path": item["path"], "identity_digest": item["identity_digest"]} for item in entries]
        ),
        "bytes_digest": canonical_digest(
            [{"path": item["path"], "bytes_digest": item["bytes_digest"]} for item in entries]
        ),
    }


def _corpus_exclusions(unit_root: Path, operation: str) -> set[Path]:
    if operation == "discuss":
        return {
            unit_root / "discussion-fill.yaml",
            unit_root / "discuss-orientation.yaml",
            unit_root / "discuss-evidence-corpus.yaml",
        }
    return {
        unit_root / f"{operation}-fill.yaml",
        unit_root / f"{operation}-orientation.yaml",
        unit_root / f"{operation}-evidence-corpus.yaml",
    }


def _load_current_corpus(
    root: Path,
    corpus_path: Path,
    *,
    excluded_paths: set[Path],
) -> dict[str, object]:
    frozen = load_yaml(corpus_path, default={})
    current = _evidence_corpus_snapshot(root, excluded_paths=excluded_paths)
    if frozen != current:
        raise ValueError("frozen pre-authoring evidence corpus is stale or modified")
    return current


def idea_preference_context(
    root: Path,
    *,
    operation: str,
    canonical_id: str,
    orientation_path: Path,
    corpus_path: Path,
    excluded_paths: set[Path],
    record_path_value: Path | None = None,
    request_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    expected_orientation = idea_preference_orientation(
        operation,
        canonical_id=canonical_id,
        request_context=request_context,
    )
    orientation = load_yaml(orientation_path, default={})
    if orientation != expected_orientation:
        raise ValueError("immutable idea authoring orientation was modified")
    orientation_binding = regular_file_binding(
        orientation_path,
        logical_identity=orientation_path.name,
        trusted_root=root,
    )
    corpus = _load_current_corpus(
        root,
        corpus_path,
        excluded_paths=excluded_paths,
    )
    common = {
        "canonical_id": canonical_id,
        "canonical_kind": "idea-generation-bundle" if operation == "generate" else "idea",
        "operation": operation,
        "phase_contract_digest": canonical_digest(expected_orientation["phase_contract"]),
        "immutable_orientation_identity_digest": orientation_binding["identity_digest"],
        "immutable_orientation_bytes_digest": orientation_binding["bytes_digest"],
        "evidence_corpus_identity_digest": str(corpus["identity_digest"]),
        "evidence_corpus_bytes_digest": str(corpus["bytes_digest"]),
    }
    if operation == "generate":
        if request_context is None:
            raise ValueError("idea generation preference context requires exact request context")
        return {
            **common,
            "request_context_digest": canonical_digest(dict(request_context)),
            "candidate_count": int(request_context["count"]),
            "bundle_id_digest": canonical_digest(request_context["bundle_id"]),
            "pool_digest": canonical_digest(request_context["pool"]),
            "source_digest": canonical_digest(request_context["source"]),
        }
    if record_path_value is None:
        raise ValueError("semantic idea preference context requires the canonical record")
    record_binding = regular_file_binding(
        record_path_value,
        logical_identity="record.yaml",
        trusted_root=root,
    )
    return {
        **common,
        "record_identity_digest": record_binding["identity_digest"],
        "record_bytes_digest": record_binding["bytes_digest"],
    }


def _preference_consumer_view(operation: str, context: Mapping[str, object]) -> dict[str, object]:
    return {
        "skill": PREFERENCE_SKILL,
        "operation": operation,
        "task_context": dict(context),
        "task_context_digest": task_context_digest(
            skill=PREFERENCE_SKILL,
            operation=operation,
            canonical_inputs=context,
        ),
    }


def _validate_preference_consumer_view(
    fill: Mapping[str, object],
    *,
    operation: str,
    context: Mapping[str, object],
) -> None:
    if fill.get("preference_consumer") != _preference_consumer_view(operation, context):
        raise ValueError("idea preference consumer binding is stale or modified")


def resolve_idea_preferences(
    root: Path,
    *,
    operation: str,
    context: Mapping[str, object],
    selection_id: str,
) -> dict[str, object]:
    return resolve_operation_preferences(
        root,
        selection_id=selection_id,
        skill=PREFERENCE_SKILL,
        operation=operation,
        canonical_inputs=context,
    )


def generation_scaffold(
    request_context: Mapping[str, object],
    preference_context: Mapping[str, object],
) -> dict[str, object]:
    count = int(request_context["count"])
    return {
        "schema": "idea-generation-fill/v1",
        "bundle_id": str(request_context["bundle_id"]),
        "request_context": dict(request_context),
        "preference_consumer": _preference_consumer_view("generate", preference_context),
        "agent_instructions": {
            "task": "Author genuinely distinct research candidates from the supplied context and selected task preferences.",
            "semantic_boundary": "The script supplies empty slots only; every title, strategy, problem, hypothesis, and next action is authored by the runtime Agent.",
            "selection_boundary": "Do not choose a winner; candidate selection remains a separate user-governed step.",
        },
        "candidates": [
            {
                "slot_id": f"candidate-{index:02d}",
                "title": "",
                "strategy": "",
                "problem": "",
                "hypothesis": "",
                "next_actions": [],
            }
            for index in range(1, count + 1)
        ],
    }


def _bounded_agent_text(value: object, *, field: str, limit: int = 4000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be filled by the runtime Agent")
    if len(text) > limit:
        raise ValueError(f"{field} is too long")
    return text


def _generation_fill_path(root: Path, args, *, bundle_id: str) -> Path:
    candidate = Path(args.input) if str(args.input or "") else bundle_root(root, bundle_id) / GENERATION_FILL_NAME
    if not candidate.is_absolute():
        candidate = bundle_root(root, bundle_id) / candidate
    try:
        candidate.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("idea generation fill must remain inside the workspace") from exc
    return candidate


def generation_materialization_plan(root: Path, args, *, bundle_id: str) -> dict[str, object]:
    request_context = generation_request_context(args, bundle_id=bundle_id)
    if int(request_context["count"]) < 1 or int(request_context["count"]) > MAX_GENERATED_CANDIDATES:
        raise ValueError(f"idea generation count must be between 1 and {MAX_GENERATED_CANDIDATES}")
    working_root = bundle_root(root, bundle_id)
    orientation_path = working_root / GENERATION_ORIENTATION_NAME
    corpus_path = working_root / GENERATION_CORPUS_NAME
    context = idea_preference_context(
        root,
        operation="generate",
        canonical_id=bundle_id,
        orientation_path=orientation_path,
        corpus_path=corpus_path,
        excluded_paths=set(),
        request_context=request_context,
    )
    fill_path = _generation_fill_path(root, args, bundle_id=bundle_id)
    fill_binding = regular_file_binding(
        fill_path,
        logical_identity=f"{bundle_id}/{GENERATION_FILL_NAME}",
        trusted_root=root,
    )
    fill = load_yaml(fill_path, default={})
    if not isinstance(fill, dict):
        raise ValueError("idea generation fill must be a mapping")
    expected_keys = {
        "schema",
        "bundle_id",
        "request_context",
        "preference_consumer",
        "agent_instructions",
        "candidates",
    }
    if set(fill) != expected_keys or fill.get("schema") != "idea-generation-fill/v1":
        raise ValueError("idea generation fill shape is invalid")
    if fill.get("bundle_id") != bundle_id or fill.get("request_context") != request_context:
        raise ValueError("idea generation request context was modified")
    _validate_preference_consumer_view(fill, operation="generate", context=context)
    raw_candidates = fill.get("candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) != int(request_context["count"]):
        raise ValueError("idea generation fill must contain every requested candidate slot")
    candidates: list[dict[str, object]] = []
    semantic_digests: set[str] = set()
    idea_ids: set[str] = set()
    exact_fields = {"slot_id", "title", "strategy", "problem", "hypothesis", "next_actions"}
    for index, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict) or set(raw) != exact_fields:
            raise ValueError("idea generation candidate shape is invalid")
        slot_id = f"candidate-{index:02d}"
        if raw.get("slot_id") != slot_id:
            raise ValueError("idea generation candidate slots are missing or reordered")
        title = _bounded_agent_text(raw.get("title"), field=f"{slot_id}.title", limit=500)
        strategy = _bounded_agent_text(raw.get("strategy"), field=f"{slot_id}.strategy", limit=1000)
        problem = _bounded_agent_text(raw.get("problem"), field=f"{slot_id}.problem")
        hypothesis = _bounded_agent_text(raw.get("hypothesis"), field=f"{slot_id}.hypothesis")
        raw_actions = raw.get("next_actions")
        if not isinstance(raw_actions, list) or not raw_actions or len(raw_actions) > 20:
            raise ValueError(f"{slot_id}.next_actions must be a nonempty bounded list")
        next_actions = [
            _bounded_agent_text(item, field=f"{slot_id}.next_actions", limit=1000)
            for item in raw_actions
        ]
        semantic = {
            "title": title,
            "strategy": strategy,
            "problem": problem,
            "hypothesis": hypothesis,
            "next_actions": next_actions,
        }
        semantic_digest = canonical_digest(semantic)
        if semantic_digest in semantic_digests:
            raise ValueError("idea generation candidates must be genuinely distinct")
        semantic_digests.add(semantic_digest)
        idea_id = build_unit_id("idea", title, str(request_context["source"]))
        if idea_id in idea_ids:
            raise ValueError("idea generation candidate identities must be unique")
        idea_ids.add(idea_id)
        candidates.append({"slot_id": slot_id, "idea_id": idea_id, **semantic})
    return {
        "bundle_id": bundle_id,
        "request_context": request_context,
        "preference_context": context,
        "fill_path": fill_path,
        "fill_binding": fill_binding,
        "candidates": candidates,
    }


def ensure_bundle(root: Path, bundle_id: str, *, title: str, source: str, pool: str, strategy: str = "generated") -> dict:
    ensure_dir(bundle_root(root, bundle_id))
    existing = load_yaml(bundle_index_path(root, bundle_id), default={})
    if isinstance(existing, dict) and existing.get("id"):
        return existing
    payload = {
        **yaml_default(bundle_id, "idea-workbench", status="active", confidence=0.7),
        "title": title,
        "source": source,
        "pool": pool,
        "strategy": strategy,
        "idea_ids": [],
        "selected_id": "",
    }
    write_yaml_if_changed(bundle_index_path(root, bundle_id), payload)
    return payload


def update_bundle(root: Path, bundle_id: str, *, idea_ids: list[str] | None = None, selected_id: str = "") -> Path:
    payload = ensure_bundle(root, bundle_id, title=bundle_id, source="", pool="", strategy="generated")
    if idea_ids is not None:
        payload["idea_ids"] = sorted(set(payload.get("idea_ids", [])) | set(idea_ids))
    if selected_id:
        payload["selected_id"] = selected_id
    write_yaml_if_changed(bundle_index_path(root, bundle_id), payload)
    return bundle_index_path(root, bundle_id)


def resolve_idea_records(root: Path, *, idea_ids: list[str], pool: str, bundle_id: str) -> tuple[list[dict], str]:
    if bundle_id:
        payload = ensure_bundle(root, bundle_id, title=bundle_id, source="", pool="", strategy="review")
        idea_ids = list(payload.get("idea_ids", []))
    elif pool:
        normalized_pool = slugify(pool, max_words=12)
        idea_ids = [record["id"] for record in iter_records(root, kind="idea") if normalized_pool in record.get("candidate_pools", [])]
        bundle_id = normalized_pool or "idea-pool"
        update_bundle(root, bundle_id, idea_ids=idea_ids)
    records = []
    for idea_id in idea_ids:
        record, _ = locate_record(root, idea_id, kind="idea")
        if record.get("kind") == "idea":
            records.append(record)
    if not records:
        raise SystemExit("No idea records resolved for this command.")
    bundle_name = bundle_id or f"idea-review-{hashlib.sha1(' '.join(idea_ids).encode('utf-8')).hexdigest()[:8]}"
    return records, bundle_name


def review_assist_markdown(records: list[dict]) -> str:
    lines = ["# Idea Review Assist", ""]
    for record in records:
        review = record["payload"].get("review", {})
        lines.extend(
            [
                f"## {record.get('title', '')}",
                "",
                f"- idea_id: `{record.get('id')}`",
                f"- review status: {review.get('review_status') or 'not_started'}",
                f"- evidence-backed claims: {len(review.get('claims', []))}",
                f"- recommendation: {review.get('recommendation') or 'pending_confirmation'}",
                f"- novelty: {record['payload']['analysis'].get('novelty') or '待补充'}",
                f"- feasibility: {record['payload']['analysis'].get('feasibility') or '待补充'}",
                f"- next actions: {', '.join(record['payload']['analysis'].get('next_actions', [])) or '-'}",
                "",
            ]
        )
    lines.extend(
        [
            "## 比较问题",
            "",
            "- 哪个 idea 的最小验证路径最短？",
            "- 哪个 idea 的 repo / data 依赖最少？",
            "- 哪个 idea 即使失败也最容易留下可复用 insight？",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def print_idea_resolution(root: Path, requested_id: str, record: dict, path: Path) -> None:
    actual_id = str(record.get("id") or "")
    if requested_id == actual_id:
        return
    print(f"normalized idea id: {requested_id} -> {actual_id}")
    print(f"canonical idea record: {path.relative_to(root)}")


def print_created_idea(root: Path, record: dict, path: Path) -> None:
    print(f"[ok] created idea_id: {record['id']}")
    print(f"[ok] created {path.relative_to(root)}")


def mark_idea_selected(
    root: Path,
    record: dict,
    *,
    confirmed_by: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    method: str,
    selected_rank: str = "",
    selected_reason: str = "",
) -> dict:
    actor, evidence_items = require_confirmation_provenance(
        confirmed_by=confirmed_by,
        evidence=evidence,
        project_root=root,
    )
    authorization, source = require_user_authorization(
        user_authorization=user_authorization,
        authorization_source=authorization_source,
    )
    selection = record.setdefault("payload", {}).setdefault("selection", {})
    record["status"] = "selected"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    if selected_rank:
        selection["selected_rank"] = selected_rank
    if selected_reason:
        selection["selected_reason"] = selected_reason
    selection["selected_by"] = actor
    selection["selected_at"] = utc_now_iso()
    selection["selection_evidence"] = evidence_items
    selection["selection_method"] = method
    selection["user_authorization"] = authorization
    selection["authorization_source"] = source
    return record


def discussion_scaffold(
    record: dict,
    *,
    preference_context: Mapping[str, object] | None = None,
) -> dict:
    payload = {
        "idea_id": record["id"],
        "mode": "sparring",
        "idea_context": {
            "title": record.get("title", ""),
            "problem": record["payload"]["problem"].get("problem_definition", ""),
            "hypothesis": record["payload"]["hypothesis"].get("core_hypothesis", ""),
            "difference_from_prior_work": record["payload"]["hypothesis"].get("difference_from_prior_work", ""),
            "minimum_validation_path": record["payload"]["analysis"].get("minimum_validation_path", ""),
        },
        "agent_instructions": {
            "role": "Act as a domain expert/reviewer: challenge, probe, retrieve counter-examples from KB units, trace the argument chain, and offer a constructive suggestion.",
            "evidence_rule": "Fill every judgement claim and attach at least one verbatim evidence_ref. The script authors no argument and only verifies evidence.",
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "reviewer": "",
        "conclusion": "",
        "claims": [
            {
                "id": role,
                "role": role,
                "text": "",
                "claim_type": claim_type,
                "confirmation_status": "pending_user_confirmation",
                "evidence_refs": [],
            }
            for role, claim_type in DISCUSSION_CLAIMS
        ],
    }
    if preference_context is not None:
        payload["preference_consumer"] = _preference_consumer_view(
            "discuss", preference_context
        )
    return payload


def analysis_scaffold(
    record: dict,
    *,
    mode: str,
    preference_context: Mapping[str, object] | None = None,
) -> dict:
    payload = {
        "idea_id": record["id"],
        "mode": mode,
        "idea_context": {
            "title": record.get("title", ""),
            "problem": record["payload"]["problem"],
            "hypothesis": record["payload"]["hypothesis"],
            "related_work": record["payload"]["analysis"].get("related_work", []),
            "minimum_validation_path": record["payload"]["analysis"].get("minimum_validation_path", ""),
            "risks": record["payload"]["analysis"].get("risks", []),
        },
        "agent_instructions": {
            "task": "Produce novelty, feasibility, recommendation, and killer-question judgements from retrieved KB evidence.",
            "evidence_rule": "Fill every claim and attach at least one verbatim evidence_ref. The script does not infer a verdict from metadata counts.",
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "descriptive_counts": descriptive_counts(record),
        "reviewer": "",
        "selection_rank": "" if mode == "review" else None,
        "claims": [
            {
                "id": role,
                "role": role,
                "text": "",
                "claim_type": claim_type,
                "confirmation_status": "pending_user_confirmation",
                "evidence_refs": [],
            }
            for role, claim_type in ANALYSIS_CLAIMS
        ],
    }
    if mode != "review":
        payload.pop("selection_rank")
    if preference_context is not None:
        payload["preference_consumer"] = _preference_consumer_view(mode, preference_context)
    return payload


def _verify_cross_unit_claims(root: Path, claims: object) -> list[str]:
    violations = validate_claims(claims)
    if not isinstance(claims, list):
        return violations
    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        refs = claim.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for ref_index, evidence_ref in enumerate(refs):
            where = f"claims[{claim_index}].evidence_refs[{ref_index}]"
            if not isinstance(evidence_ref, dict):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            if not source_unit_id:
                violations.append(f"{where}: missing source_unit_id")
                continue
            try:
                source_record, source_path = locate_record(root, source_unit_id, fuzzy=False)
            except SystemExit:
                violations.append(f"{where}: source unit not found: {source_unit_id}")
                continue
            if str(source_record.get("id") or "") != source_unit_id:
                violations.append(f"{where}: source_unit_id must be canonical: {source_unit_id}")
                continue
            single_ref_claim = {**claim, "evidence_refs": [evidence_ref]}
            for violation in verify_claim_evidence(single_ref_claim, source_path.parent):
                violations.append(f"{where}: {violation}")
    return violations


def _trusted_claim_source_roots(root: Path, claims: list[dict]) -> dict[str, Path]:
    source_roots: dict[str, Path] = {}
    for claim in claims:
        for evidence_ref in claim.get("evidence_refs") or []:
            if not isinstance(evidence_ref, dict):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            if source_unit_id and source_unit_id not in source_roots:
                _source_record, source_path = locate_record(root, source_unit_id, fuzzy=False)
                source_roots[source_unit_id] = source_path.parent
    return source_roots


def _claims_corpus_violations(root: Path, claims: list[dict], corpus: Mapping[str, object]) -> list[str]:
    frozen_paths = {
        str(item.get("path") or "")
        for item in corpus.get("entries", [])
        if isinstance(item, Mapping)
    }
    violations: list[str] = []
    for claim_index, claim in enumerate(claims):
        for ref_index, evidence_ref in enumerate(claim.get("evidence_refs") or []):
            if not isinstance(evidence_ref, dict):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            artifact = str(evidence_ref.get("artifact") or "").strip()
            if not source_unit_id or not artifact:
                continue
            try:
                _source_record, source_path = locate_record(root, source_unit_id, fuzzy=False)
                relative = (source_path.parent / artifact).absolute().relative_to(root.absolute()).as_posix()
            except (SystemExit, ValueError):
                continue
            if relative not in frozen_paths:
                violations.append(
                    f"claims[{claim_index}].evidence_refs[{ref_index}]: "
                    "artifact was not present in the frozen pre-authoring evidence corpus"
                )
    return violations


def _persist_idea_preference_binding(
    record: dict,
    *,
    operation: str,
    binding: Mapping[str, object],
) -> None:
    if not binding:
        return
    record.setdefault("payload", {}).setdefault("preference_selections", {})[operation] = dict(
        binding
    )


def verify_discussion_fill(root: Path, fill: object, idea_id: str) -> tuple[list[str], list[dict]]:
    if not isinstance(fill, dict):
        return ["discussion fill must be a mapping"], []
    violations: list[str] = []
    if str(fill.get("idea_id") or "") != idea_id:
        violations.append(f"idea_id must match {idea_id}")
    if not str(fill.get("reviewer") or "").strip():
        violations.append("reviewer must be filled")
    if not str(fill.get("conclusion") or "").strip():
        violations.append("conclusion must be filled")
    claims = fill.get("claims")
    expected_roles = {role for role, _ in DISCUSSION_CLAIMS}
    actual_roles = {
        str(claim.get("role") or claim.get("id") or "")
        for claim in claims or []
        if isinstance(claim, dict)
    }
    if actual_roles != expected_roles or not isinstance(claims, list) or len(claims) != len(expected_roles):
        violations.append(f"claims must contain exactly these roles: {sorted(expected_roles)}")
    conclusion_claims = [
        claim for claim in claims or []
        if isinstance(claim, dict) and str(claim.get("role") or claim.get("id") or "") == "conclusion"
    ]
    if conclusion_claims and str(conclusion_claims[0].get("text") or "").strip() != str(fill.get("conclusion") or "").strip():
        violations.append("the canonical conclusion claim text must exactly match conclusion")
    violations.extend(_verify_cross_unit_claims(root, claims))
    return violations, [dict(claim) for claim in claims or [] if isinstance(claim, dict)]


def verify_analysis_fill(root: Path, fill: object, idea_id: str, *, mode: str) -> tuple[list[str], list[dict]]:
    if not isinstance(fill, dict):
        return [f"{mode} fill must be a mapping"], []
    violations: list[str] = []
    if str(fill.get("idea_id") or "") != idea_id:
        violations.append(f"idea_id must match {idea_id}")
    if str(fill.get("mode") or "") != mode:
        violations.append(f"mode must be {mode}")
    if not str(fill.get("reviewer") or "").strip():
        violations.append("reviewer must be filled")
    claims = fill.get("claims")
    expected_roles = {role for role, _ in ANALYSIS_CLAIMS}
    actual_roles = {
        str(claim.get("role") or claim.get("id") or "")
        for claim in claims or []
        if isinstance(claim, dict)
    }
    if actual_roles != expected_roles or not isinstance(claims, list) or len(claims) != len(expected_roles):
        violations.append(f"claims must contain exactly these roles: {sorted(expected_roles)}")
    if mode == "review" and fill.get("selection_rank") not in (None, ""):
        try:
            if int(fill["selection_rank"]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            violations.append("selection_rank must be a positive integer when provided")
    violations.extend(_verify_cross_unit_claims(root, claims))
    return violations, [dict(claim) for claim in claims or [] if isinstance(claim, dict)]


def _claims_by_role(claims: list[dict]) -> dict[str, dict]:
    return {str(claim.get("role") or claim.get("id") or ""): claim for claim in claims}


def persist_analysis(record: dict, fill: dict, claims: list[dict], *, mode: str) -> None:
    by_role = _claims_by_role(claims)
    analysis = record["payload"]["analysis"]
    analysis["novelty"] = str(by_role["novelty"]["text"]).strip()
    analysis["feasibility"] = str(by_role["feasibility"]["text"]).strip()
    analysis["claims"] = claims
    analysis["analyzed_by"] = str(fill["reviewer"]).strip()
    analysis["analyzed_at"] = utc_now_iso()
    if mode == "review":
        review = record["payload"]["review"]
        review["review_status"] = "pending_user_confirmation"
        review["recommendation"] = str(by_role["recommendation"]["text"]).strip()
        review["killer_questions"] = [str(by_role["killer-question"]["text"]).strip()]
        review["claims"] = claims
        review["reviewed_by"] = str(fill["reviewer"]).strip()
        review["reviewed_at"] = utc_now_iso()
        review.pop("score_breakdown", None)
        if fill.get("selection_rank") not in (None, ""):
            review["selection_rank"] = int(fill["selection_rank"])


def run_analysis_phase(args, root: Path, record: dict, unit_root: Path, *, mode: str) -> int:
    fill_path = unit_root / f"{mode}-fill.yaml"
    orientation_path = unit_root / f"{mode}-orientation.yaml"
    corpus_path = unit_root / f"{mode}-evidence-corpus.yaml"
    exclusions = _corpus_exclusions(unit_root, mode)
    result_path = unit_root / f"{mode}.yaml"
    if args.phase == "prepare":
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        if mode == "analyze":
            record["payload"]["analysis"]["analysis_status"] = "awaiting_agent_fill"
        else:
            record["payload"]["review"]["review_status"] = "awaiting_agent_fill"
        append_history(
            record,
            action=f"idea-{mode}-scaffolded",
            summary=f"Prepared an empty evidence-first {mode} scaffold.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, fill_path)],
        )
        write_record(root, record)
        write_yaml_if_changed(
            orientation_path,
            idea_preference_orientation(mode, canonical_id=str(record["id"])),
        )
        write_yaml_if_changed(
            corpus_path,
            _evidence_corpus_snapshot(root, excluded_paths=exclusions),
        )
        preference_context = idea_preference_context(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=unit_root / "record.yaml",
        )
        write_yaml_if_changed(
            fill_path,
            analysis_scaffold(
                record,
                mode=mode,
                preference_context=preference_context,
            ),
        )
        print(f"[ok] prepared evidence-first {mode} scaffold")
        _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: prepare idea {mode} {record['id']}",
            target_paths=[unit_root / "record.yaml", fill_path, orientation_path, corpus_path],
        )
        return 0

    try:
        preference_context = idea_preference_context(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=unit_root / "record.yaml",
        )
        preference_resolution = resolve_idea_preferences(
            root,
            operation=mode,
            context=preference_context,
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
        )
    except ValueError as exc:
        print(f"[reject] {mode} preference receipt: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    candidate_path = Path(args.input) if args.input else fill_path
    if not candidate_path.is_absolute():
        candidate_path = unit_root / candidate_path
    if not candidate_path.exists():
        raise SystemExit(f"{mode} verify input not found")
    fill = load_yaml(candidate_path, default={})
    try:
        if not isinstance(fill, Mapping):
            raise ValueError(f"{mode} fill must be a mapping")
        _validate_preference_consumer_view(fill, operation=mode, context=preference_context)
    except ValueError as exc:
        print(f"[reject] {mode} preference binding: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    violations, claims = verify_analysis_fill(root, fill, record["id"], mode=mode)
    corpus = load_yaml(corpus_path, default={})
    if isinstance(corpus, Mapping):
        violations.extend(_claims_corpus_violations(root, claims, corpus))
    if violations:
        print(f"[reject] {mode} failed evidence verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    try:
        rechecked_context = idea_preference_context(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=unit_root / "record.yaml",
        )
        rechecked_resolution = resolve_idea_preferences(
            root,
            operation=mode,
            context=rechecked_context,
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
        )
        if (
            rechecked_context != preference_context
            or rechecked_resolution.get("task_context_digest")
            != preference_resolution.get("task_context_digest")
            or rechecked_resolution.get("binding") != preference_resolution.get("binding")
        ):
            raise ValueError("idea authoring inputs changed before write")
    except ValueError as exc:
        print(f"[reject] {mode} write-boundary preference check: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    persist_analysis(record, fill, claims, mode=mode)
    preference_binding = dict(preference_resolution.get("binding") or {})
    _persist_idea_preference_binding(
        record,
        operation=mode,
        binding=preference_binding,
    )
    attach_claims(record.setdefault("payload", {}), claims)
    build_verification_receipt(
        record,
        unit_root,
        source_roots=_trusted_claim_source_roots(root, claims),
    )
    record["status"] = "pending"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = sorted(set(record.get("information_types", [])) | {"inference", "evaluation", "unverified"})
    if mode == "analyze":
        record["payload"]["analysis"]["analysis_status"] = "pending_user_confirmation"
    else:
        record["maturity"] = "complete"
    payload = {
        "idea_id": record["id"],
        "mode": mode,
        "status": "pending_user_confirmation",
        "reviewer": str(fill["reviewer"]).strip(),
        "verified_at": utc_now_iso(),
        "claims": claims,
        "descriptive_counts": descriptive_counts(record),
    }
    if preference_binding:
        payload["preference_selection"] = preference_binding
    if mode == "review" and fill.get("selection_rank") not in (None, ""):
        payload["selection_rank"] = int(fill["selection_rank"])
    write_yaml_if_changed(result_path, payload)
    artifacts = [rel(root, result_path)]
    if mode == "review":
        card_path = unit_root / "idea-card.md"
        write_text_if_changed(card_path, idea_card(record, review_payload(record)))
        artifacts.append(rel(root, card_path))
    append_history(
        record,
        action=f"idea-{mode}-verified",
        summary=f"Verified and persisted agent-authored evidence-first {mode} judgements.",
        information_types=["inference", "evaluation", "unverified"],
        artifacts=artifacts,
    )
    write_record(root, record)
    build_index(root)
    print(f"[ok] verified evidence and persisted {mode} judgements")
    _queue_checkpoint(
        root, trigger="milestone", message=f"milestone: verify idea {mode} {record['id']}",
        target_paths=[unit_root / "record.yaml", result_path, orientation_path, corpus_path, *([unit_root / "idea-card.md"] if mode == "review" else []), *_index_checkpoint_paths(root)],
    )
    return 0


def discussion_judgements_path(unit_root: Path) -> Path:
    return unit_root / "discussion-judgements.yaml"


def load_discussion_judgements(unit_root: Path, idea_id: str) -> list[dict]:
    payload = load_yaml(discussion_judgements_path(unit_root), default={})
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return []
    return [item for item in payload["items"] if isinstance(item, dict)]


def write_discussion_judgements(unit_root: Path, idea_id: str, items: list[dict]) -> Path:
    path = discussion_judgements_path(unit_root)
    write_yaml_if_changed(
        path,
        {
            "id": f"{idea_id}-discussion-judgements",
            "kind": "judgement_collection",
            "owner": "idea-workbench",
            "items": items,
        },
    )
    return path


def persist_discussion_conclusion(
    root: Path,
    unit_root: Path,
    record: dict,
    fill: dict,
    claims: list[dict],
    *,
    preference_binding: Mapping[str, object] | None = None,
) -> tuple[dict, dict]:
    verified_at = utc_now_iso()
    digest_source = f"{record['id']}\n{fill['reviewer']}\n{fill['conclusion']}\n{verified_at}"
    conclusion = {
        "id": f"discussion-{hashlib.sha1(digest_source.encode('utf-8')).hexdigest()[:10]}",
        "conclusion": str(fill["conclusion"]).strip(),
        "reviewer": str(fill["reviewer"]).strip(),
        "verified_at": verified_at,
        "verification": "evidence_verified",
        "claims": claims,
    }
    judgement = {
        "id": conclusion["id"],
        "kind": "idea_discussion_conclusion",
        "owner": "idea-workbench",
        "idea_id": record["id"],
        "timestamp": verified_at,
        "updated_at": verified_at,
        "priority": "normal",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["inference", "evaluation", "unverified"],
        "payload": {
            "discussion_conclusion": {
                "text": conclusion["conclusion"],
                "reviewer": conclusion["reviewer"],
            },
        },
        "review_route": {
            "owner": "idea-workbench",
            "action": "discuss",
            "phase": "confirm",
            "idea_id": record["id"],
            "conclusion_id": conclusion["id"],
        },
    }
    if preference_binding:
        judgement["preference_selection"] = dict(preference_binding)
    attach_claims(judgement["payload"], claims)
    build_verification_receipt(
        judgement,
        unit_root,
        source_roots=_trusted_claim_source_roots(root, claims),
        verified_at=verified_at,
    )
    items = load_discussion_judgements(unit_root, record["id"])
    items.append(judgement)
    write_discussion_judgements(unit_root, record["id"], items)
    conclusion["judgement_id"] = judgement["id"]
    conclusion["confirmation_status"] = "pending_user_confirmation"
    if preference_binding:
        conclusion["preference_selection"] = dict(preference_binding)
        _persist_idea_preference_binding(
            record,
            operation="discuss",
            binding=preference_binding,
        )
    discussion = record.setdefault("payload", {}).setdefault("discussion", {})
    discussion.setdefault("conclusions", []).append(conclusion)
    return conclusion, judgement


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage idea units in core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--title", required=True)
    capture.add_argument("--source", default="discussion")
    capture.add_argument("--problem", default="")
    capture.add_argument("--hypothesis", default="")
    capture.add_argument("--pool", default="")

    generate = subparsers.add_parser("generate")
    generate.add_argument("--title", required=True)
    generate.add_argument("--source", default="discussion")
    generate.add_argument("--problem", default="")
    generate.add_argument("--hypothesis", default="")
    generate.add_argument("--count", type=int, default=4)
    generate.add_argument("--pool", default="")
    generate.add_argument("--bundle-id", default="")
    generate.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    generate.add_argument("--input", default="")
    generate.add_argument("--preference-selection-id", default="")

    for name in ("analyze", "review", "select", "archive"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--idea-id", required=True)
        if name in {"analyze", "review"}:
            cmd.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
            cmd.add_argument("--input", default="")
            cmd.add_argument("--preference-selection-id", default="")
        if name == "select":
            add_confirmation_arguments(cmd)

    discuss = subparsers.add_parser("discuss", aliases=["spar"])
    discuss.add_argument("--idea-id", "--id", dest="idea_id", required=True)
    discuss.add_argument("--phase", choices=["prepare", "verify", "confirm", "reject"], default="prepare")
    discuss.add_argument("--input", default="")
    discuss.add_argument("--conclusion-id", default="")
    discuss.add_argument("--confirmed-by", default="")
    discuss.add_argument("--evidence", action="append", default=[])
    discuss.add_argument("--user-authorization", default="")
    discuss.add_argument("--authorization-source", default="")
    discuss.add_argument("--reason", default="")
    discuss.add_argument("--expected-snapshot", default="")
    discuss.add_argument("--preference-selection-id", default="")

    assist = subparsers.add_parser("review-assist")
    assist.add_argument("--idea-id", action="append", default=[])
    assist.add_argument("--pool", default="")
    assist.add_argument("--bundle-id", default="")

    select_best = subparsers.add_parser("select-best")
    select_best.add_argument("--idea-id", action="append", default=[])
    select_best.add_argument("--pool", default="")
    select_best.add_argument("--bundle-id", default="")
    add_confirmation_arguments(select_best)
    return parser


def _dispatch(args, root: Path) -> int:
    if args.command == "capture":
        record = default_record("idea", title=args.title, maturity="lightweight", source={"original_uri": args.source})
        record["status"] = "draft"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["user_opinion", "inference", "unverified"]
        record["payload"]["origin"]["source"] = args.source
        record["payload"]["problem"]["problem_definition"] = args.problem
        record["payload"]["hypothesis"]["core_hypothesis"] = args.hypothesis
        record["summary"] = args.problem or f"Captured idea: {args.title}"
        record = apply_record_governance(
            root,
            record,
            explicit_pools=[args.pool] if args.pool else [],
            infer_missing=True,
            source_label="idea-workbench",
        )
        path = write_record(root, record)
        build_index(root)
        print_created_idea(root, record, path)
        checkpoint = _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: capture idea {record['id']}",
            target_paths=[path, *_index_checkpoint_paths(root)],
        )
        return 0

    if args.command == "generate":
        bundle_id = generation_bundle_id(args)
        if args.count < 1 or args.count > MAX_GENERATED_CANDIDATES:
            raise SystemExit(
                f"Idea generation count must be between 1 and {MAX_GENERATED_CANDIDATES}."
            )
        working_root = bundle_root(root, bundle_id)
        orientation_path = working_root / GENERATION_ORIENTATION_NAME
        corpus_path = working_root / GENERATION_CORPUS_NAME
        fill_path = working_root / GENERATION_FILL_NAME
        request_context = generation_request_context(args, bundle_id=bundle_id)
        if args.phase == "prepare":
            if bundle_index_path(root, bundle_id).exists() or bundle_index_path(root, bundle_id).is_symlink():
                raise SystemExit("This idea generation bundle has already been materialized.")
            write_yaml_if_changed(
                orientation_path,
                idea_preference_orientation(
                    "generate",
                    canonical_id=bundle_id,
                    request_context=request_context,
                ),
            )
            write_yaml_if_changed(corpus_path, _evidence_corpus_snapshot(root))
            preference_context = idea_preference_context(
                root,
                operation="generate",
                canonical_id=bundle_id,
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=set(),
                request_context=request_context,
            )
            write_yaml_if_changed(
                fill_path,
                generation_scaffold(request_context, preference_context),
            )
            print("已准备空白候选槽位；runtime agent 填写后可继续校验并一次性生成 idea。")
            _queue_checkpoint(
                root,
                trigger="milestone",
                message=f"milestone: prepare idea generation {bundle_id}",
                target_paths=[orientation_path, corpus_path, fill_path],
            )
            return 0

        try:
            planned = getattr(args, "_generation_plan", None)
            current_plan = generation_materialization_plan(root, args, bundle_id=bundle_id)
            if not isinstance(planned, dict) or (
                planned.get("fill_binding") != current_plan.get("fill_binding")
                or planned.get("candidates") != current_plan.get("candidates")
                or planned.get("preference_context") != current_plan.get("preference_context")
            ):
                raise ValueError("idea generation fill changed after transaction target discovery")
            preference_resolution = resolve_idea_preferences(
                root,
                operation="generate",
                context=current_plan["preference_context"],
                selection_id=str(args.preference_selection_id or ""),
            )
        except ValueError as exc:
            print(f"[reject] idea generation: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

        candidate_records: list[tuple[dict, Path]] = []
        for candidate in current_plan["candidates"]:
            path = record_path(root, "idea", str(candidate["idea_id"]))
            if path.exists() or path.is_symlink():
                raise SystemExit("Idea generation would overwrite an existing candidate record.")
            record = default_record(
                "idea",
                title=str(candidate["title"]),
                maturity="lightweight",
                source={"original_uri": args.source},
            )
            record["status"] = "draft"
            record["confirmation_status"] = "pending_user_confirmation"
            record["needs_human_confirmation"] = True
            record["information_types"] = ["user_opinion", "inference", "unverified"]
            record["payload"]["origin"]["source"] = args.source
            record["payload"]["candidate"]["bundle_id"] = bundle_id
            record["payload"]["candidate"]["slot_id"] = candidate["slot_id"]
            record["payload"]["candidate"]["strategy"] = candidate["strategy"]
            record["payload"]["candidate"]["pool"] = args.pool
            record["payload"]["candidate"]["generation_context"] = dict(request_context)
            record["payload"]["problem"]["problem_definition"] = candidate["problem"]
            record["payload"]["hypothesis"]["core_hypothesis"] = candidate["hypothesis"]
            record["payload"]["analysis"]["next_actions"] = list(candidate["next_actions"])
            record["summary"] = candidate["problem"]
            preference_binding = dict(preference_resolution.get("binding") or {})
            _persist_idea_preference_binding(
                record,
                operation="generate",
                binding=preference_binding,
            )
            record = apply_record_governance(
                root,
                record,
                explicit_pools=[args.pool] if args.pool else [],
                infer_missing=True,
                source_label="idea-workbench",
            )
            if str(record.get("id") or "") != str(candidate["idea_id"]):
                raise SystemExit("Idea generation candidate identity changed during normalization.")
            candidate_records.append((record, path))

        preference_binding = dict(preference_resolution.get("binding") or {})
        bundle_payload = {
            **yaml_default(bundle_id, "idea-workbench", status="active", confidence=0.7),
            "title": args.title,
            "source": args.source,
            "pool": args.pool,
            "strategy": "runtime-agent-authored",
            "generation_context": dict(request_context),
            "idea_ids": [str(record["id"]) for record, _path in candidate_records],
            "selected_id": "",
        }
        if preference_binding:
            bundle_payload["preference_selection"] = preference_binding

        try:
            final_plan = generation_materialization_plan(root, args, bundle_id=bundle_id)
            final_resolution = resolve_idea_preferences(
                root,
                operation="generate",
                context=final_plan["preference_context"],
                selection_id=str(args.preference_selection_id or ""),
            )
            if (
                final_plan.get("fill_binding") != current_plan.get("fill_binding")
                or final_plan.get("candidates") != current_plan.get("candidates")
                or final_plan.get("preference_context") != current_plan.get("preference_context")
                or final_resolution.get("task_context_digest")
                != preference_resolution.get("task_context_digest")
                or final_resolution.get("binding") != preference_resolution.get("binding")
            ):
                raise ValueError("idea generation inputs changed before write")
        except ValueError as exc:
            print(f"[reject] idea generation write-boundary check: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

        created: list[str] = []
        for record, path in candidate_records:
            write_record(root, record)
            created.append(str(record["id"]))
        index_path = bundle_index_path(root, bundle_id)
        write_yaml_if_changed(index_path, bundle_payload)
        build_index(root)
        print(f"已校验并一次性生成 {len(created)} 个 Agent 撰写的 idea 候选。")
        checkpoint = _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: generate idea bundle {bundle_id}",
            target_paths=[index_path, *[record_path(root, "idea", idea_id) for idea_id in created], *_index_checkpoint_paths(root)],
        )
        return 0

    if args.command in {"review-assist", "select-best"}:
        records, bundle_id = resolve_idea_records(root, idea_ids=args.idea_id, pool=args.pool, bundle_id=args.bundle_id)
        ensure_bundle(root, bundle_id, title=bundle_id, source="", pool=args.pool, strategy="review")
        if args.command == "review-assist":
            assist_path = bundle_root(root, bundle_id) / "review-assist.md"
            write_text_if_changed(assist_path, review_assist_markdown(records))
            update_bundle(root, bundle_id, idea_ids=[record["id"] for record in records])
            build_index(root)
            print(f"[ok] wrote {assist_path.relative_to(root)}")
            checkpoint = _queue_checkpoint(
                root, trigger="milestone", message=f"milestone: review assist bundle {bundle_id}",
                target_paths=[assist_path, bundle_index_path(root, bundle_id), *_index_checkpoint_paths(root)],
            )
            return 0
        scored_records = []
        for record in records:
            review = record["payload"]["review"]
            rank = review.get("selection_rank")
            if rank not in (None, ""):
                scored_records.append((int(rank), record))
                continue
            legacy_total = review.get("score_breakdown", {}).get("total")
            if legacy_total not in (None, ""):
                scored_records.append((-int(legacy_total), record))
                continue
            raise SystemExit(f"Idea {record['id']} has no verified selection_rank; run evidence-first review before select-best.")
        scored_records.sort(key=lambda item: (item[0], str(item[1].get("id"))))
        selected = scored_records[0][1]
        for _, record in scored_records:
            if record["id"] == selected["id"]:
                record = mark_idea_selected(
                    root,
                    record,
                    confirmed_by=args.confirmed_by,
                    evidence=args.evidence,
                    user_authorization=args.user_authorization,
                    authorization_source=args.authorization_source,
                    method="idea.py select-best",
                    selected_rank="1",
                    selected_reason="Highest reviewed total score in explicit select-best command.",
                )
            append_history(
                record,
                action="idea-selected" if record["id"] == selected["id"] else "idea-reviewed-for-selection",
                summary="Explicit multi-candidate selection executed.",
                information_types=["user_opinion", "evaluation"] if record["id"] == selected["id"] else ["evaluation"],
            )
            write_record(root, record)
        selection_path = bundle_root(root, bundle_id) / "selection.yaml"
        write_yaml_if_changed(
            selection_path,
            {
                **yaml_default(f"{bundle_id}-selection", "idea-workbench", status="selected", confidence=0.72),
                "bundle_id": bundle_id,
                "selected_id": selected["id"],
                "ranked_ids": [record["id"] for _, record in scored_records],
            },
        )
        update_bundle(root, bundle_id, idea_ids=[record["id"] for _, record in scored_records], selected_id=selected["id"])
        build_index(root)
        print(f"[ok] selected {selected['id']}")
        print(f"[ok] wrote {selection_path.relative_to(root)}")
        checkpoint = _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: select best idea in {bundle_id}",
            target_paths=[selection_path, bundle_index_path(root, bundle_id), *[record_path(root, "idea", record["id"]) for _, record in scored_records], *_index_checkpoint_paths(root)],
        )
        return 0

    record, path = locate_record(root, args.idea_id, kind="idea")
    if record.get("kind") != "idea":
        raise SystemExit(f"{args.idea_id} is not an idea record")
    print_idea_resolution(root, args.idea_id, record, path)
    unit_root = path.parent

    if args.command in {"discuss", "spar"}:
        scaffold_path = unit_root / "discussion-fill.yaml"
        orientation_path = unit_root / "discuss-orientation.yaml"
        corpus_path = unit_root / "discuss-evidence-corpus.yaml"
        exclusions = _corpus_exclusions(unit_root, "discuss")
        if args.phase == "prepare":
            append_history(
                record,
                action="idea-discussion-scaffolded",
                summary="Prepared an empty evidence-first sparring conclusion scaffold.",
                information_types=["inference", "evaluation", "unverified"],
                artifacts=[rel(root, scaffold_path)],
            )
            write_record(root, record)
            write_yaml_if_changed(
                orientation_path,
                idea_preference_orientation("discuss", canonical_id=str(record["id"])),
            )
            write_yaml_if_changed(
                corpus_path,
                _evidence_corpus_snapshot(root, excluded_paths=exclusions),
            )
            preference_context = idea_preference_context(
                root,
                operation="discuss",
                canonical_id=str(record["id"]),
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=exclusions,
                record_path_value=unit_root / "record.yaml",
            )
            write_yaml_if_changed(
                scaffold_path,
                discussion_scaffold(record, preference_context=preference_context),
            )
            print("[ok] prepared an empty evidence-first sparring conclusion")
            _queue_checkpoint(
                root, trigger="milestone", message=f"milestone: prepare idea discussion {record['id']}",
                target_paths=[unit_root / "record.yaml", scaffold_path, orientation_path, corpus_path],
            )
            return 0

        if args.phase in {"confirm", "reject"}:
            if not str(args.conclusion_id or "").strip():
                raise SystemExit("Discussion decision requires a conclusion id.")
            try:
                snapshot = json.loads(args.expected_snapshot)
                item = {
                    "snapshot_binding": snapshot,
                    "confirm_route": {
                        "owner": "idea-workbench", "action": "discuss", "phase": "confirm",
                        "idea_id": record["id"], "conclusion_id": args.conclusion_id,
                    },
                    "reject_route": {
                        "owner": "idea-workbench", "action": "discuss", "phase": "reject",
                        "idea_id": record["id"], "conclusion_id": args.conclusion_id,
                    },
                }
                apply_review_batch_decision(
                    root,
                    item,
                    args.phase,
                    actor=str(getattr(args, "confirmed_by", "") or ""),
                    evidence=list(getattr(args, "evidence", []) or []),
                    user_authorization=str(getattr(args, "user_authorization", "") or ""),
                    authorization_source=str(getattr(args, "authorization_source", "") or ""),
                    rejection_reason=str(getattr(args, "reason", "") or ""),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise SystemExit(str(exc)) from exc
            print(f"[ok] {args.phase}ed discussion conclusion {args.conclusion_id}")
            _queue_checkpoint(
                root,
                trigger="milestone",
                message=f"milestone: {args.phase} idea discussion {record['id']}",
                target_paths=[unit_root / "record.yaml", discussion_judgements_path(unit_root)],
            )
            return 0

        try:
            preference_context = idea_preference_context(
                root,
                operation="discuss",
                canonical_id=str(record["id"]),
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=exclusions,
                record_path_value=unit_root / "record.yaml",
            )
            preference_resolution = resolve_idea_preferences(
                root,
                operation="discuss",
                context=preference_context,
                selection_id=str(args.preference_selection_id or ""),
            )
        except ValueError as exc:
            print(f"[reject] discuss preference receipt: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        fill_path = Path(args.input) if args.input else scaffold_path
        if not fill_path.is_absolute():
            fill_path = unit_root / fill_path
        if not fill_path.exists():
            raise SystemExit("Discussion fill is missing; prepare or provide the agent-filled conclusion first.")
        fill = load_yaml(fill_path, default={})
        try:
            if not isinstance(fill, Mapping):
                raise ValueError("discussion fill must be a mapping")
            _validate_preference_consumer_view(
                fill,
                operation="discuss",
                context=preference_context,
            )
        except ValueError as exc:
            print(f"[reject] discuss preference binding: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        violations, claims = verify_discussion_fill(root, fill, record["id"])
        corpus = load_yaml(corpus_path, default={})
        if isinstance(corpus, Mapping):
            violations.extend(_claims_corpus_violations(root, claims, corpus))
        if violations:
            print("[reject] discussion conclusion failed verification:", file=sys.stderr)
            for violation in violations:
                print(f"  - {violation}", file=sys.stderr)
            raise SystemExit(1)
        try:
            rechecked_context = idea_preference_context(
                root,
                operation="discuss",
                canonical_id=str(record["id"]),
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=exclusions,
                record_path_value=unit_root / "record.yaml",
            )
            rechecked_resolution = resolve_idea_preferences(
                root,
                operation="discuss",
                context=rechecked_context,
                selection_id=str(args.preference_selection_id or ""),
            )
            if (
                rechecked_context != preference_context
                or rechecked_resolution.get("task_context_digest")
                != preference_resolution.get("task_context_digest")
                or rechecked_resolution.get("binding") != preference_resolution.get("binding")
            ):
                raise ValueError("idea discussion inputs changed before write")
        except ValueError as exc:
            print(f"[reject] discuss write-boundary preference check: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        conclusion, _judgement = persist_discussion_conclusion(
            root,
            unit_root,
            record,
            fill,
            claims,
            preference_binding=dict(preference_resolution.get("binding") or {}),
        )
        append_history(
            record,
            action="idea-discussion-verified",
            summary="Verified and persisted one evidence-grounded sparring conclusion.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, fill_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] verified + persisted discussion conclusion {conclusion['id']}")
        _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: verify idea discussion {record['id']}",
            target_paths=[unit_root / "record.yaml", discussion_judgements_path(unit_root), orientation_path, corpus_path, *_index_checkpoint_paths(root)],
        )
        return 0

    if args.command == "analyze":
        return run_analysis_phase(args, root, record, unit_root, mode="analyze")

    if args.command == "review":
        return run_analysis_phase(args, root, record, unit_root, mode="review")

    if args.command == "select":
        record = mark_idea_selected(
            root,
            record,
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
            method="idea.py select",
            selected_reason="Idea explicitly selected for method design.",
        )
        append_history(
            record,
            action="idea-selected",
            summary="Idea explicitly selected for method design.",
            information_types=["user_opinion", "evaluation"],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] selected {record['id']}")
        checkpoint = _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: select idea {record['id']}",
            target_paths=[unit_root / "record.yaml", *_index_checkpoint_paths(root)],
        )
        return 0

    if args.command == "archive":
        record["status"] = "archived"
        append_history(record, action="idea-archived", summary="Idea archived or merged into another direction.", information_types=["fact"])
        write_record(root, record)
        build_index(root)
        print(f"[ok] archived {record['id']}")
        checkpoint = _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: archive idea {record['id']}",
            target_paths=[unit_root / "record.yaml", *_index_checkpoint_paths(root)],
        )
        return 0
    return 1


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_workspace(root)
    try:
        targets = _idea_command_targets(args, root)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    active_token = _ACTIVE_MUTATION.set(True)
    checkpoint_token = _PENDING_CHECKPOINT.set(None)
    try:
        with command_mutation(root, f"idea-workbench:{args.command}", targets):
            result = _dispatch(args, root)
        pending = _PENDING_CHECKPOINT.get()
    finally:
        _PENDING_CHECKPOINT.reset(checkpoint_token)
        _ACTIVE_MUTATION.reset(active_token)
    if pending is not None:
        checkpoint_and_report(
            pending[0], trigger=pending[1], message=pending[2], target_paths=pending[3]
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())

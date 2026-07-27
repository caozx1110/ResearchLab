#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
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
from research.evidence import EvidenceSourceSnapshot, attach_claims, build_verification_receipt, validate_claims, verify_claim_evidence
from research.judgements import apply_judgement_rejection, readiness_violations, require_judgement_snapshot
from research.journal import mutation_transaction
from research.preference_selection import (
    canonical_digest,
    regular_file_binding,
    resolve_operation_preferences,
    task_context_digest,
)
from research.records import trusted_claim_source_roots

PREFERENCE_SKILL = "idea-workbench"
PREFERENCE_OPERATIONS = {"generate", "analyze", "review", "discuss"}
GENERATION_FILL_NAME = "generation-fill.yaml"
GENERATION_ORIENTATION_NAME = "generation-orientation.yaml"
GENERATION_CORPUS_NAME = "generation-evidence-corpus.yaml"
MAX_GENERATED_CANDIDATES = 12
AUTHORING_ANCHOR_SCHEMA = "idea-authoring-anchor/v1"
PREPARED_BUNDLE_SCHEMA = "idea-generation-bundle/v1"
AUTHORING_ANCHOR_KEYS = {
    "schema",
    "operation",
    "canonical_id",
    "request_context_digest",
    "orientation_binding",
    "corpus_commitment",
}
PREPARED_BUNDLE_KEYS = {
    "schema",
    "id",
    "owner",
    "status",
    "request_context_digest",
    "authoring_contract",
}
HEX_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
CANONICAL_UNIT_DIRECTORIES = {"papers", "repos", "datasets", "blogs", "ideas", "experiments", "concepts"}
MAX_CORPUS_FILE_BYTES = 16 * 1024 * 1024
MAX_CORPUS_TOTAL_BYTES = 256 * 1024 * 1024
MAX_CORPUS_ENTRIES = 20_000
MAX_CORPUS_DEPTH = 64
CITABLE_TEXT_SUFFIXES = {
    ".bash", ".bib", ".c", ".cc", ".cfg", ".conf", ".cpp", ".css", ".csv",
    ".go", ".h", ".hpp", ".htm", ".html", ".ini", ".java", ".js", ".json",
    ".jsonl", ".jsx", ".kt", ".m", ".markdown", ".md", ".mm", ".php", ".py",
    ".rb", ".rs", ".rst", ".scss", ".sh", ".sql", ".swift", ".tex", ".toml",
    ".ts", ".tsv", ".tsx", ".txt", ".xml", ".yaml", ".yml", ".zsh",
}
CITABLE_TEXT_NAMES = {
    "authors", "changelog", "citation", "codeowners", "contributing", "copying",
    "license", "makefile", "notice", "readme",
}

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


def _generic_bundle_id(args) -> str:
    if str(args.bundle_id or ""):
        return str(args.bundle_id)
    if str(args.pool or ""):
        return slugify(args.pool, max_words=12) or "idea-pool"
    idea_ids = list(args.idea_id)
    return f"idea-review-{hashlib.sha1(' '.join(idea_ids).encode('utf-8')).hexdigest()[:8]}"


def _assert_safe_generic_bundle_path(root: Path, bundle_id: str) -> None:
    lexical_root = root.absolute()
    pool_root = (synthesis_root(root) / "idea-pools").absolute()
    bundle = bundle_root(root, bundle_id).absolute()
    try:
        relative_bundle = bundle.relative_to(pool_root)
        relative_to_workspace = bundle.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("idea bundle path escaped its managed directory") from exc
    if not relative_bundle.parts:
        raise ValueError("idea bundle id must identify one managed bundle")
    cursor = lexical_root
    if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
        raise ValueError("idea bundle path has an unsafe workspace root")
    for part in relative_to_workspace.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
            raise ValueError("idea bundle path has a symlink or non-directory ancestor")
    index_path = bundle / "index.yaml"
    if index_path.is_symlink() or (index_path.exists() and not index_path.is_file()):
        raise ValueError("idea bundle index must be a lexical regular file")


def _generic_bundle_preflight(args, root: Path) -> None:
    bundle_id = _generic_bundle_id(args)
    planned = str(getattr(args, "_planned_generic_bundle_id", "") or "")
    if planned and planned != bundle_id:
        raise SystemExit("Idea bundle resolution changed before the operation lock.")
    try:
        _assert_safe_generic_bundle_path(root, bundle_id)
        existing = load_yaml(bundle_index_path(root, bundle_id), default={})
        if _is_prepared_generation_bundle(existing):
            raise ValueError(
                "prepared idea generation bundle cannot be used by generic bundle operations"
            )
    except ValueError as exc:
        raise SystemExit("Idea bundle state is unsafe or reserved.") from exc


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
            return [bundle_index_path(root, bundle_id), *private_targets]
        plan = generation_materialization_plan(root, args, bundle_id=bundle_id)
        args._generation_plan = plan
        idea_paths = [record_path(root, "idea", item["idea_id"]) for item in plan["candidates"]]
        return [bundle_index_path(root, bundle_id), *idea_paths, *targets]
    if args.command in {"review-assist", "select-best"}:
        idea_ids = list(args.idea_id)
        bundle_id = _generic_bundle_id(args)
        _assert_safe_generic_bundle_path(root, bundle_id)
        args._planned_generic_bundle_id = bundle_id
        if args.bundle_id:
            payload = load_yaml(bundle_index_path(root, bundle_id), default={})
            idea_ids = list(payload.get("idea_ids", [])) if isinstance(payload, dict) else []
        elif args.pool:
            normalized_pool = slugify(args.pool, max_words=12)
            idea_ids = [
                record["id"] for record in iter_records(root, kind="idea")
                if normalized_pool in record.get("candidate_pools", [])
            ]
        existing_bundle = load_yaml(bundle_index_path(root, bundle_id), default={})
        if _is_prepared_generation_bundle(existing_bundle):
            raise ValueError(
                "prepared idea generation bundle cannot be used by generic bundle operations"
            )
        bundle = bundle_root(root, bundle_id)
        extra = [bundle / "review-assist.md"] if args.command == "review-assist" else [bundle / "selection.yaml"]
        return [bundle_index_path(root, bundle_id), *extra, *[record_path(root, "idea", idea_id) for idea_id in idea_ids], *targets]
    record, path = locate_record(root, args.idea_id, kind="idea")
    args._planned_idea_id = str(record.get("id") or "")
    args._planned_idea_path = path.absolute().as_posix()
    unit = path.parent
    if args.command in {"analyze", "review"}:
        if args.phase == "prepare":
            return [
                path,
                unit / f"{args.command}-fill.yaml",
                unit / f"{args.command}-orientation.yaml",
                unit / f"{args.command}-evidence-corpus.yaml",
            ]
        return [
            path,
            unit / f"{args.command}.yaml",
            *([unit / "idea-card.md"] if args.command == "review" else []),
            *targets,
        ]
    if args.command in {"discuss", "spar"}:
        if args.phase == "prepare":
            return [
                path,
                unit / "discussion-fill.yaml",
                unit / "discuss-orientation.yaml",
                unit / "discuss-evidence-corpus.yaml",
            ]
        return [
            path,
            unit / "discussion-judgements.yaml",
            *targets,
        ]
    return [path, *targets]


def _assert_planned_idea_resolution(args, record: Mapping[str, object], path: Path) -> None:
    planned_id = str(getattr(args, "_planned_idea_id", "") or "")
    planned_path = str(getattr(args, "_planned_idea_path", "") or "")
    if planned_id and (
        planned_id != str(record.get("id") or "")
        or planned_path != path.absolute().as_posix()
    ):
        raise SystemExit("Idea resolution changed before the operation lock; no changes were made.")


def _prepare_contract_tuple_state(
    root: Path,
    *,
    operation: str,
    canonical_id: str,
    corpus_path: Path,
    orientation_path: Path,
    request_context: Mapping[str, object] | None = None,
) -> str:
    corpus_exists = corpus_path.exists() or corpus_path.is_symlink()
    orientation_exists = orientation_path.exists() or orientation_path.is_symlink()
    if not corpus_exists and not orientation_exists:
        return "new"
    if corpus_exists != orientation_exists:
        raise ValueError("idea authoring contract tuple is incomplete")
    corpus, corpus_binding = _validated_frozen_corpus(root, corpus_path)
    schema_version = 1 if corpus.get("schema") == "idea-evidence-corpus/v1" else 2
    orientation, _orientation_binding = _bound_yaml(
        orientation_path,
        logical_identity=orientation_path.name,
        trusted_root=root,
    )
    static_digest = (
        str(orientation.get("static_scaffold_digest") or "")
        if schema_version == 2 and isinstance(orientation, Mapping)
        else ""
    )
    expected_orientation = idea_preference_orientation(
        operation,
        canonical_id=canonical_id,
        corpus_commitment=_corpus_commitment(corpus, corpus_binding),
        request_context=request_context,
        schema_version=schema_version,
        static_scaffold_digest=static_digest,
    )
    if orientation != expected_orientation:
        raise ValueError("idea authoring contract tuple is mixed or stale")
    return "legacy" if schema_version == 1 else "v2"


def _generation_prepare_has_current_owner(
    root: Path,
    *,
    bundle_id: str,
    request_context: Mapping[str, object],
) -> bool:
    index_path = bundle_index_path(root, bundle_id)
    if index_path.exists() or index_path.is_symlink():
        idea_preference_context(
            root,
            operation="generate",
            canonical_id=bundle_id,
            orientation_path=bundle_root(root, bundle_id) / GENERATION_ORIENTATION_NAME,
            corpus_path=bundle_root(root, bundle_id) / GENERATION_CORPUS_NAME,
            excluded_paths=set(),
            request_context=request_context,
        )
        return True
    working_root = bundle_root(root, bundle_id)
    tuple_state = _prepare_contract_tuple_state(
        root,
        operation="generate",
        canonical_id=bundle_id,
        corpus_path=working_root / GENERATION_CORPUS_NAME,
        orientation_path=working_root / GENERATION_ORIENTATION_NAME,
        request_context=request_context,
    )
    if tuple_state == "v2":
        raise ValueError("unanchored v2 idea generation task cannot be adopted")
    return False


def _require_existing_semantic_anchor_if_v2(
    root: Path,
    *,
    operation: str,
    record: Mapping[str, object],
    unit_root: Path,
    allow_consumed_without_anchor: bool,
) -> None:
    contracts = _record_authoring_contracts(record)
    other_active = set(contracts) - {operation}
    if other_active:
        raise ValueError("another semantic idea authoring operation is already active")
    corpus_path = unit_root / f"{operation}-evidence-corpus.yaml"
    tuple_state = _prepare_contract_tuple_state(
        root,
        operation=operation,
        canonical_id=str(record["id"]),
        corpus_path=corpus_path,
        orientation_path=unit_root / f"{operation}-orientation.yaml",
    )
    if tuple_state == "new":
        if contracts:
            raise ValueError("active semantic idea owner anchor has no contract tuple")
        return
    if tuple_state == "legacy":
        if contracts:
            raise ValueError("legacy semantic idea task cannot carry a v2 owner anchor")
        return
    if operation not in contracts:
        if allow_consumed_without_anchor:
            return
        raise ValueError("unanchored v2 semantic idea authoring task cannot be adopted")
    idea_preference_context(
        root,
        operation=operation,
        canonical_id=str(record["id"]),
        orientation_path=unit_root / f"{operation}-orientation.yaml",
        corpus_path=corpus_path,
        excluded_paths=_corpus_exclusions(unit_root, operation),
        record_path_value=unit_root / "record.yaml",
    )


def _idea_prepare_preflight(args, root: Path) -> None:
    """Run lossless prepare guards under locks and before journal snapshots."""
    if getattr(args, "phase", "") != "prepare":
        return
    if args.command == "generate":
        bundle_id = generation_bundle_id(args)
        request_context = generation_request_context(args, bundle_id=bundle_id)
        working_root = bundle_root(root, bundle_id)
        try:
            _generation_prepare_has_current_owner(
                root,
                bundle_id=bundle_id,
                request_context=request_context,
            )
        except ValueError as exc:
            raise SystemExit("This idea generation bundle is terminal or its prepared state changed.") from exc
        _guard_existing_empty_fill(
            root,
            working_root / GENERATION_FILL_NAME,
            generation_scaffold(request_context, None),
        )
        _guard_existing_contract_target(root, working_root / GENERATION_ORIENTATION_NAME)
        _guard_existing_contract_target(root, working_root / GENERATION_CORPUS_NAME)
        return
    if args.command not in {"analyze", "review", "discuss", "spar"}:
        return
    record, path = locate_record(root, args.idea_id, kind="idea")
    _assert_planned_idea_resolution(args, record, path)
    unit_root = path.parent
    if args.command in {"discuss", "spar"}:
        consumed_bindings = _consumed_fill_bindings(root, record, unit_root, "discuss")
        try:
            _require_existing_semantic_anchor_if_v2(
                root,
                operation="discuss",
                record=record,
                unit_root=unit_root,
                allow_consumed_without_anchor=bool(consumed_bindings),
            )
        except ValueError as exc:
            raise SystemExit("Existing idea discussion contract is stale or unanchored.") from exc
        _guard_existing_empty_fill(
            root,
            unit_root / "discussion-fill.yaml",
            discussion_scaffold(record, preference_context=None),
            consumed_bindings=consumed_bindings,
        )
        _guard_existing_contract_target(root, unit_root / "discuss-orientation.yaml")
        _guard_existing_contract_target(root, unit_root / "discuss-evidence-corpus.yaml")
        return
    consumed_bindings = _consumed_fill_bindings(root, record, unit_root, args.command)
    try:
        _require_existing_semantic_anchor_if_v2(
            root,
            operation=args.command,
            record=record,
            unit_root=unit_root,
            allow_consumed_without_anchor=bool(consumed_bindings),
        )
    except ValueError as exc:
        raise SystemExit("Existing idea authoring contract is stale or unanchored.") from exc
    fill_path = unit_root / f"{args.command}-fill.yaml"
    if getattr(args, "refresh_corpus", False):
        _load_refreshable_analysis_fill(
            root,
            record,
            unit_root,
            mode=args.command,
        )
    else:
        _guard_existing_empty_fill(
            root,
            fill_path,
            analysis_scaffold(record, mode=args.command, preference_context=None),
            consumed_bindings=consumed_bindings,
        )
    _guard_existing_contract_target(root, unit_root / f"{args.command}-orientation.yaml")
    _guard_existing_contract_target(root, unit_root / f"{args.command}-evidence-corpus.yaml")


def _idea_verify_preflight(args, root: Path) -> None:
    if getattr(args, "phase", "") != "verify":
        return
    if args.command == "generate":
        bundle_id = generation_bundle_id(args)
        try:
            plan = generation_materialization_plan(root, args, bundle_id=bundle_id)
            resolve_idea_preferences(
                root,
                operation="generate",
                context=plan["preference_context"],
                selection_id=str(args.preference_selection_id or ""),
            )
        except ValueError as exc:
            print(f"[reject] idea generate 验证失败：{exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    if args.command not in {"analyze", "review", "discuss", "spar"}:
        return
    record, path = locate_record(root, args.idea_id, kind="idea")
    _assert_planned_idea_resolution(args, record, path)
    unit_root = path.parent
    operation = "discuss" if args.command in {"discuss", "spar"} else args.command
    fill_path = (
        unit_root / "discussion-fill.yaml"
        if operation == "discuss"
        else unit_root / f"{operation}-fill.yaml"
    )
    orientation_path = unit_root / f"{operation}-orientation.yaml"
    corpus_path = unit_root / f"{operation}-evidence-corpus.yaml"
    exclusions = _corpus_exclusions(unit_root, operation)
    candidate_path = _resolve_verify_input(
        root,
        unit_root,
        fill_path.name,
        args.input,
        operation=operation,
    )
    try:
        context = idea_preference_context(
            root,
            operation=operation,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=path,
        )
        resolve_idea_preferences(
            root,
            operation=operation,
            context=context,
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
        )
        fill, _binding = _bound_yaml(
            candidate_path,
            logical_identity=candidate_path.relative_to(root).as_posix(),
            trusted_root=root,
        )
        if not isinstance(fill, Mapping):
            raise ValueError("idea fill must be a mapping")
        expected = (
            discussion_scaffold(record, preference_context=context)
            if operation == "discuss"
            else analysis_scaffold(record, mode=operation, preference_context=context)
        )
        _validate_owner_static_fill(fill, expected, operation=operation)
        _validate_preference_consumer_view(fill, operation=operation, context=context)
        violations, claims = (
            verify_discussion_fill(root, fill, str(record["id"]))
            if operation == "discuss"
            else verify_analysis_fill(root, fill, str(record["id"]), mode=operation)
        )
        corpus, _corpus_binding = _validated_frozen_corpus(root, corpus_path)
        violations.extend(
            _claim_input_violations(
                root,
                claims,
                corpus,
                consumer_id=str(record["id"]),
            )
        )
        if violations:
            raise ValueError("idea fill or cited evidence failed verification: " + "; ".join(violations))
    except ValueError as exc:
        print(f"[reject] idea {operation} 验证失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _idea_transaction_preflight(args, root: Path) -> None:
    if getattr(args, "refresh_corpus", False) and getattr(args, "phase", "") != "prepare":
        raise SystemExit("证据集刷新只适用于准备阶段；未做修改。")
    if args.command in {"review-assist", "select-best"}:
        _generic_bundle_preflight(args, root)
        return
    _idea_prepare_preflight(args, root)
    _idea_verify_preflight(args, root)


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
            trusted_source_roots=_trusted_claim_source_roots(
                root,
                claims,
                consumer_id=str(record["id"]),
            ),
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
            trusted_source_roots=_trusted_claim_source_roots(
                root,
                claims,
                consumer_id=str(record["id"]),
            ),
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
    corpus_commitment: Mapping[str, str],
    request_context: Mapping[str, object] | None = None,
    schema_version: int = 2,
    static_scaffold_digest: str = "",
) -> dict[str, object]:
    if operation not in PREFERENCE_OPERATIONS:
        raise ValueError("unsupported idea preference operation")
    payload: dict[str, object] = {
        "schema": f"idea-preference-orientation/v{schema_version}",
        "canonical_id": canonical_id,
        "canonical_kind": "idea-generation-bundle" if operation == "generate" else "idea",
        "skill": PREFERENCE_SKILL,
        "operation": operation,
        "phase_contract": _idea_phase_contract(operation),
        "evidence_corpus": "frozen-pre-authoring-canonical-unit-artifacts",
    }
    if schema_version == 2:
        static_scaffold_digest = static_scaffold_digest or canonical_digest({})
        if not HEX_DIGEST_RE.fullmatch(static_scaffold_digest):
            raise ValueError("idea orientation requires a static scaffold digest")
        payload["evidence_corpus_commitment"] = dict(corpus_commitment)
        payload["static_scaffold_digest"] = static_scaffold_digest
    elif schema_version != 1:
        raise ValueError("unsupported idea orientation schema")
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
    entries: list[dict[str, object]] = []
    total_bytes = 0
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
            if path.absolute() in excluded or _is_authoring_control_artifact(path):
                continue
            if not _is_citable_text_artifact(path):
                continue
            relative_to_units = path.relative_to(units)
            if len(relative_to_units.parts) > MAX_CORPUS_DEPTH:
                raise ValueError("citable idea evidence corpus exceeds the path-depth budget")
            if metadata.st_size > MAX_CORPUS_FILE_BYTES:
                raise ValueError("citable idea evidence artifact exceeds the per-file byte budget")
            if len(entries) >= MAX_CORPUS_ENTRIES:
                raise ValueError("citable idea evidence corpus exceeds the entry budget")
            total_bytes += metadata.st_size
            if total_bytes > MAX_CORPUS_TOTAL_BYTES:
                raise ValueError("citable idea evidence corpus exceeds the total byte budget")
            binding = regular_file_binding(
                path,
                logical_identity=path.relative_to(root).as_posix(),
                trusted_root=root,
            )
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                raise ValueError("citable idea evidence artifact is unreadable") from exc
            if binding != regular_file_binding(
                path,
                logical_identity=path.relative_to(root).as_posix(),
                trusted_root=root,
            ):
                raise ValueError("citable idea evidence artifact changed while it was read")
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "identity_digest": binding["identity_digest"],
                    "bytes_digest": binding["bytes_digest"],
                    "size": metadata.st_size,
                }
            )
    return {
        "schema": "idea-evidence-corpus/v2",
        "entries": entries,
        "identity_digest": canonical_digest(
            [{"path": item["path"], "identity_digest": item["identity_digest"], "size": item["size"]} for item in entries]
        ),
        "bytes_digest": canonical_digest(
            [{"path": item["path"], "bytes_digest": item["bytes_digest"], "size": item["size"]} for item in entries]
        ),
    }


def _corpus_exclusions(unit_root: Path, operation: str) -> set[Path]:
    if operation == "discuss":
        return {
            unit_root / "record.yaml",
            unit_root / "discussion-fill.yaml",
            unit_root / "discuss-orientation.yaml",
            unit_root / "discuss-evidence-corpus.yaml",
            unit_root / "discussion-judgements.yaml",
        }
    excluded = {
        unit_root / "record.yaml",
        unit_root / f"{operation}-fill.yaml",
        unit_root / f"{operation}-orientation.yaml",
        unit_root / f"{operation}-evidence-corpus.yaml",
        unit_root / f"{operation}.yaml",
    }
    if operation == "review":
        excluded.add(unit_root / "idea-card.md")
    return excluded


def _is_authoring_control_artifact(path: Path) -> bool:
    name = path.name
    return any(
        name.endswith(suffix)
        for suffix in ("-fill.yaml", "-orientation.yaml", "-evidence-corpus.yaml")
    )


def _is_citable_text_artifact(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in CITABLE_TEXT_SUFFIXES:
        return True
    stem = path.name.lower().split(".", 1)[0]
    return stem in CITABLE_TEXT_NAMES


def _describe_probe_path(root: Path, candidate: Path) -> str:
    try:
        return candidate.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return str(candidate)


def _resolve_verify_input(
    root: Path,
    unit_root: Path,
    default_name: str,
    explicit: object,
    *,
    operation: str,
) -> Path:
    """Resolve a verify ``--input`` the same way blog/repo analysts do.

    A bare filename or relative path is probed against the unit directory
    first, then against the project root; an absolute path is used as given.
    A missing input always fails loudly with every probed location instead of
    exiting silently.
    """
    text = str(explicit or "").strip()
    if not text:
        default_path = unit_root / default_name
        if default_path.exists() or default_path.is_symlink():
            return default_path
        print(
            f"[reject] idea {operation} verify input not found：默认填写文件 "
            f"{_describe_probe_path(root, default_path)} 不存在；"
            f"请先运行 --phase prepare 生成骨架，或用 --input 指定已填写的文件。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raw = Path(text).expanduser()
    candidates = [raw] if raw.is_absolute() else [unit_root / raw, root / raw]
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.absolute().as_posix()
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    for candidate in deduped:
        if candidate.exists() or candidate.is_symlink():
            try:
                candidate.absolute().relative_to(root.absolute())
            except ValueError:
                print(
                    f"[reject] idea {operation} 验证输入必须位于工作区内；"
                    f"请把文件放到工作区后改用仓库相对路径或裸文件名。",
                    file=sys.stderr,
                )
                raise SystemExit(1) from None
            return candidate
    tried = "、".join(_describe_probe_path(root, candidate) for candidate in deduped)
    print(
        f"[reject] idea {operation} verify input not found：找不到验证输入 {text}；"
        f"尝试过 {tried}。裸文件名按 unit 目录解析，也接受仓库相对路径或绝对路径。",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _bound_yaml(
    path: Path,
    *,
    logical_identity: str,
    trusted_root: Path,
) -> tuple[object, dict[str, str]]:
    """Load YAML only when one exact safe regular-file binding spans the parse."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("idea authoring artifact is missing or unsafe") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CORPUS_FILE_BYTES:
        raise ValueError("idea authoring artifact is unsafe or exceeds the YAML byte budget")
    before = regular_file_binding(
        path,
        logical_identity=logical_identity,
        trusted_root=trusted_root,
    )
    try:
        payload = load_yaml(path, default={})
    except Exception as exc:  # YAML parser/runtime failures must fail closed.
        raise ValueError("idea authoring artifact is unreadable or malformed") from exc
    after = regular_file_binding(
        path,
        logical_identity=logical_identity,
        trusted_root=trusted_root,
    )
    if before != after:
        raise ValueError("idea authoring artifact changed while it was read")
    return payload, before


def _validated_frozen_corpus(
    root: Path,
    corpus_path: Path,
) -> tuple[dict[str, object], dict[str, str]]:
    payload, binding = _bound_yaml(
        corpus_path,
        logical_identity=corpus_path.relative_to(root).as_posix(),
        trusted_root=root,
    )
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "entries",
        "identity_digest",
        "bytes_digest",
    }:
        raise ValueError("frozen pre-authoring evidence corpus is malformed")
    schema = payload.get("schema")
    if schema not in {"idea-evidence-corpus/v1", "idea-evidence-corpus/v2"}:
        raise ValueError("frozen pre-authoring evidence corpus schema is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("frozen pre-authoring evidence corpus entries are malformed")
    normalized: list[dict[str, object]] = []
    previous = ""
    total_bytes = 0
    if len(entries) > MAX_CORPUS_ENTRIES:
        raise ValueError("frozen pre-authoring evidence corpus exceeds the entry budget")
    for item in entries:
        expected_entry_keys = {"path", "identity_digest", "bytes_digest"}
        if schema == "idea-evidence-corpus/v2":
            expected_entry_keys.add("size")
        if not isinstance(item, dict) or set(item) != expected_entry_keys:
            raise ValueError("frozen pre-authoring evidence corpus entry is malformed")
        relative_text = item.get("path")
        identity_digest = item.get("identity_digest")
        bytes_digest = item.get("bytes_digest")
        if not all(isinstance(value, str) for value in (relative_text, identity_digest, bytes_digest)):
            raise ValueError("frozen pre-authoring evidence corpus entry values are malformed")
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or relative.as_posix() != relative_text
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.parts[:2] != ("kb", "units")
            or len(relative.parts) < 5
            or relative.parts[2] not in CANONICAL_UNIT_DIRECTORIES
            or not relative.parts[3].strip()
            or (schema == "idea-evidence-corpus/v2" and _is_authoring_control_artifact(relative))
            or (schema == "idea-evidence-corpus/v2" and not _is_citable_text_artifact(relative))
            or (schema == "idea-evidence-corpus/v2" and len(relative.parts[2:]) > MAX_CORPUS_DEPTH)
        ):
            raise ValueError("frozen pre-authoring evidence corpus path is unsafe")
        if relative_text <= previous:
            raise ValueError("frozen pre-authoring evidence corpus paths are duplicated or unsorted")
        if not HEX_DIGEST_RE.fullmatch(identity_digest) or not HEX_DIGEST_RE.fullmatch(bytes_digest):
            raise ValueError("frozen pre-authoring evidence corpus digest is malformed")
        previous = relative_text
        normalized_item: dict[str, object] = {
            "path": relative_text,
            "identity_digest": identity_digest,
            "bytes_digest": bytes_digest,
        }
        if schema == "idea-evidence-corpus/v2":
            size = item.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ValueError("frozen pre-authoring evidence corpus size is malformed")
            if size > MAX_CORPUS_FILE_BYTES:
                raise ValueError("frozen pre-authoring evidence artifact exceeds the per-file byte budget")
            total_bytes += size
            if total_bytes > MAX_CORPUS_TOTAL_BYTES:
                raise ValueError("frozen pre-authoring evidence corpus exceeds the total byte budget")
            normalized_item["size"] = size
        normalized.append(normalized_item)
    if schema == "idea-evidence-corpus/v2":
        expected_identity = canonical_digest(
            [{"path": item["path"], "identity_digest": item["identity_digest"], "size": item["size"]} for item in normalized]
        )
        expected_bytes = canonical_digest(
            [{"path": item["path"], "bytes_digest": item["bytes_digest"], "size": item["size"]} for item in normalized]
        )
    else:
        expected_identity = canonical_digest(
            [{"path": item["path"], "identity_digest": item["identity_digest"]} for item in normalized]
        )
        expected_bytes = canonical_digest(
            [{"path": item["path"], "bytes_digest": item["bytes_digest"]} for item in normalized]
        )
    if payload.get("identity_digest") != expected_identity or payload.get("bytes_digest") != expected_bytes:
        raise ValueError("frozen pre-authoring evidence corpus digest is invalid")
    return payload, binding


def _corpus_commitment(
    corpus: Mapping[str, object],
    binding: Mapping[str, str],
) -> dict[str, str]:
    return {
        "manifest_identity_digest": str(corpus["identity_digest"]),
        "manifest_bytes_digest": str(corpus["bytes_digest"]),
        "corpus_file_identity_digest": str(binding["identity_digest"]),
        "corpus_file_bytes_digest": str(binding["bytes_digest"]),
    }


def _authoring_request_digest(
    operation: str,
    request_context: Mapping[str, object] | None,
) -> str:
    if operation == "generate":
        if request_context is None:
            raise ValueError("idea generation anchor requires exact request context")
        return canonical_digest(dict(request_context))
    return canonical_digest({})


def _authoring_anchor(
    *,
    operation: str,
    canonical_id: str,
    request_context: Mapping[str, object] | None,
    orientation_binding: Mapping[str, str],
    corpus_commitment: Mapping[str, str],
) -> dict[str, object]:
    anchor: dict[str, object] = {
        "schema": AUTHORING_ANCHOR_SCHEMA,
        "operation": operation,
        "canonical_id": canonical_id,
        "request_context_digest": _authoring_request_digest(operation, request_context),
        "orientation_binding": dict(orientation_binding),
        "corpus_commitment": dict(corpus_commitment),
    }
    _validate_authoring_anchor(anchor, operation=operation, canonical_id=canonical_id)
    return anchor


def _validate_authoring_anchor(
    anchor: object,
    *,
    operation: str,
    canonical_id: str,
) -> dict[str, object]:
    if not isinstance(anchor, dict) or set(anchor) != AUTHORING_ANCHOR_KEYS:
        raise ValueError("idea authoring owner anchor is missing or malformed")
    if (
        anchor.get("schema") != AUTHORING_ANCHOR_SCHEMA
        or anchor.get("operation") != operation
        or anchor.get("canonical_id") != canonical_id
        or not HEX_DIGEST_RE.fullmatch(str(anchor.get("request_context_digest") or ""))
    ):
        raise ValueError("idea authoring owner anchor identity is invalid")
    orientation_binding = anchor.get("orientation_binding")
    corpus_commitment = anchor.get("corpus_commitment")
    if (
        not isinstance(orientation_binding, dict)
        or set(orientation_binding) != {"identity_digest", "bytes_digest"}
        or not all(HEX_DIGEST_RE.fullmatch(str(value or "")) for value in orientation_binding.values())
        or not isinstance(corpus_commitment, dict)
        or set(corpus_commitment) != {
            "manifest_identity_digest",
            "manifest_bytes_digest",
            "corpus_file_identity_digest",
            "corpus_file_bytes_digest",
        }
        or not all(HEX_DIGEST_RE.fullmatch(str(value or "")) for value in corpus_commitment.values())
    ):
        raise ValueError("idea authoring owner anchor bindings are malformed")
    return anchor


def _record_authoring_contracts(record: Mapping[str, object]) -> dict[str, object]:
    payload = record.get("payload")
    contracts = payload.get("idea_authoring_contracts") if isinstance(payload, Mapping) else None
    if contracts is None:
        return {}
    if not isinstance(contracts, Mapping):
        raise ValueError("idea authoring owner contract registry is malformed")
    canonical_id = str(record.get("id") or "")
    normalized = dict(contracts)
    if len(normalized) > 1 or any(
        operation not in {"analyze", "review", "discuss"}
        for operation in normalized
    ):
        raise ValueError("an idea may have only one active semantic authoring contract")
    for operation, anchor in normalized.items():
        _validate_authoring_anchor(
            anchor,
            operation=operation,
            canonical_id=canonical_id,
        )
    return normalized


def _record_authoring_anchor(
    record: Mapping[str, object],
    operation: str,
) -> object:
    return _record_authoring_contracts(record).get(operation)


def _persist_record_authoring_anchor(
    record: dict,
    operation: str,
    anchor: Mapping[str, object],
) -> None:
    contracts = _record_authoring_contracts(record)
    if set(contracts) - {operation}:
        raise ValueError("another semantic idea authoring operation is already active")
    record.setdefault("payload", {}).setdefault("idea_authoring_contracts", {})[
        operation
    ] = dict(anchor)


def _consume_record_authoring_anchor(record: dict, operation: str) -> None:
    payload = record.setdefault("payload", {})
    contracts = payload.get("idea_authoring_contracts")
    if not isinstance(contracts, dict) or operation not in contracts:
        raise ValueError("active idea authoring owner anchor is missing at consumption")
    del contracts[operation]
    if not contracts:
        payload.pop("idea_authoring_contracts", None)


def _authoring_provenance(anchor: Mapping[str, object] | None) -> dict[str, str]:
    if anchor is None:
        return {"mode": "legacy-unanchored/v1"}
    return {
        "mode": "owner-anchored/v1",
        "authoring_contract_digest": canonical_digest(dict(anchor)),
    }


def _prepared_generation_bundle(
    bundle_id: str,
    request_context: Mapping[str, object],
    anchor: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": PREPARED_BUNDLE_SCHEMA,
        "id": bundle_id,
        "owner": "idea-workbench",
        "status": "prepared",
        "request_context_digest": canonical_digest(dict(request_context)),
        "authoring_contract": dict(anchor),
    }


def _load_prepared_generation_bundle(
    root: Path,
    *,
    bundle_id: str,
    request_context: Mapping[str, object],
    current_anchor: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, str]]:
    index_path = bundle_index_path(root, bundle_id)
    payload, binding = _bound_yaml(
        index_path,
        logical_identity=index_path.relative_to(root).as_posix(),
        trusted_root=root,
    )
    expected = _prepared_generation_bundle(bundle_id, request_context, current_anchor)
    if payload != expected or not isinstance(payload, dict) or set(payload) != PREPARED_BUNDLE_KEYS:
        raise ValueError("idea generation prepared bundle state is stale or malformed")
    return payload, binding


def _is_prepared_generation_bundle(payload: object) -> bool:
    return isinstance(payload, Mapping) and (
        payload.get("schema") == PREPARED_BUNDLE_SCHEMA
        or payload.get("status") == "prepared"
        or "authoring_contract" in payload
        or "request_context_digest" in payload
    )


def _has_current_v2_corpus(root: Path, corpus_path: Path) -> bool:
    corpus, _binding = _validated_frozen_corpus(root, corpus_path)
    return corpus.get("schema") == "idea-evidence-corpus/v2"


def _write_authoring_contract(
    root: Path,
    *,
    operation: str,
    canonical_id: str,
    orientation_path: Path,
    corpus_path: Path,
    excluded_paths: set[Path],
    request_context: Mapping[str, object] | None = None,
    static_scaffold: Mapping[str, object],
) -> dict[str, object]:
    write_yaml_if_changed(
        corpus_path,
        _evidence_corpus_snapshot(root, excluded_paths=excluded_paths),
    )
    corpus, binding = _validated_frozen_corpus(root, corpus_path)
    write_yaml_if_changed(
        orientation_path,
        idea_preference_orientation(
            operation,
            canonical_id=canonical_id,
            corpus_commitment=_corpus_commitment(corpus, binding),
            request_context=request_context,
            static_scaffold_digest=canonical_digest(dict(static_scaffold)),
        ),
    )
    orientation_binding = regular_file_binding(
        orientation_path,
        logical_identity=orientation_path.name,
        trusted_root=root,
    )
    return _authoring_anchor(
        operation=operation,
        canonical_id=canonical_id,
        request_context=request_context,
        orientation_binding=orientation_binding,
        corpus_commitment=_corpus_commitment(corpus, binding),
    )


def _guard_existing_empty_fill(
    root: Path,
    fill_path: Path,
    expected_static_scaffold: Mapping[str, object],
    *,
    consumed_bindings: list[Mapping[str, object]] | None = None,
) -> dict[str, object] | None:
    """Reject before prepare writes unless the old fill is an owner-empty scaffold."""
    if not fill_path.exists() and not fill_path.is_symlink():
        return None
    try:
        payload, binding = _bound_yaml(
            fill_path,
            logical_identity=fill_path.relative_to(root).as_posix(),
            trusted_root=root,
        )
    except ValueError as exc:
        raise SystemExit(
            "已有填写文件不安全或无法读取；为避免覆盖，准备操作已停止。"
        ) from exc
    if not isinstance(payload, dict) or "preference_consumer" not in payload:
        raise SystemExit("已有填写内容无法确认为空白模板；为避免覆盖，准备操作已停止。")
    static_projection = dict(payload)
    static_projection.pop("preference_consumer")
    if static_projection != dict(expected_static_scaffold):
        if any(dict(item) == binding for item in consumed_bindings or []):
            return payload
        raise SystemExit("已有 Agent 填写或模板改动；为避免覆盖，准备操作已停止。")
    return payload


def _consumed_fill_bindings(
    root: Path,
    record: Mapping[str, object],
    unit_root: Path,
    operation: str,
) -> list[Mapping[str, object]]:
    payload = record.get("payload") if isinstance(record, Mapping) else None
    consumptions = payload.get("idea_authoring_consumptions") if isinstance(payload, Mapping) else None
    record_binding = consumptions.get(operation) if isinstance(consumptions, Mapping) else None
    if not isinstance(record_binding, Mapping):
        return []
    if operation in {"analyze", "review"}:
        result_path = unit_root / f"{operation}.yaml"
        try:
            result, _result_binding = _bound_yaml(
                result_path,
                logical_identity=result_path.relative_to(root).as_posix(),
                trusted_root=root,
            )
        except ValueError:
            return []
        if (
            isinstance(result, Mapping)
            and result.get("idea_id") == record.get("id")
            and result.get("mode") == operation
            and result.get("consumed_fill_binding") == record_binding
        ):
            return [record_binding]
        return []
    if operation == "discuss":
        sidecar_path = discussion_judgements_path(unit_root)
        try:
            sidecar, _sidecar_binding = _bound_yaml(
                sidecar_path,
                logical_identity=sidecar_path.relative_to(root).as_posix(),
                trusted_root=root,
            )
        except ValueError:
            return []
        items = sidecar.get("items") if isinstance(sidecar, Mapping) else None
        if isinstance(items, list) and any(
            isinstance(item, Mapping)
            and item.get("idea_id") == record.get("id")
            and item.get("consumed_fill_binding") == record_binding
            for item in items
        ):
            return [record_binding]
    return []


def _guard_existing_contract_target(root: Path, path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    try:
        regular_file_binding(
            path,
            logical_identity=path.relative_to(root).as_posix(),
            trusted_root=root,
        )
    except ValueError as exc:
        raise SystemExit("已有准备契约不安全；为避免误写，准备操作已停止。") from exc


def _owner_static_fill_projection(
    fill: Mapping[str, object],
    *,
    operation: str,
) -> dict[str, object]:
    projection = copy.deepcopy(dict(fill))
    if operation == "generate":
        candidates = projection.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("idea generation fill shape is invalid")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("idea generation candidate shape is invalid")
            for field, empty in (
                ("title", ""),
                ("strategy", ""),
                ("problem", ""),
                ("hypothesis", ""),
                ("next_actions", []),
            ):
                candidate[field] = empty
    else:
        projection["reviewer"] = ""
        if operation == "discuss":
            projection["conclusion"] = ""
        elif operation == "review":
            projection["selection_rank"] = ""
        claims = projection.get("claims")
        if not isinstance(claims, list):
            raise ValueError("idea fill claims are malformed")
        for claim in claims:
            if not isinstance(claim, dict):
                raise ValueError("idea fill claim is malformed")
            claim["text"] = ""
            claim["evidence_refs"] = []
    return projection


def _validate_owner_static_fill(
    fill: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    operation: str,
) -> None:
    projection = _owner_static_fill_projection(fill, operation=operation)
    if projection != dict(expected):
        raise ValueError("immutable idea fill scaffold was modified")


def _load_refreshable_analysis_fill(
    root: Path,
    record: Mapping[str, object],
    unit_root: Path,
    *,
    mode: str,
) -> dict[str, object]:
    """Load a safe nonempty analysis fill while tolerating only record-byte drift."""
    fill_path = unit_root / f"{mode}-fill.yaml"
    try:
        fill, _binding = _bound_yaml(
            fill_path,
            logical_identity=fill_path.relative_to(root).as_posix(),
            trusted_root=root,
        )
        if not isinstance(fill, Mapping):
            raise ValueError("fill is not a mapping")
        static_fill = copy.deepcopy(dict(fill))
        consumer = static_fill.pop("preference_consumer", None)
        orientation, _orientation_binding = _bound_yaml(
            unit_root / f"{mode}-orientation.yaml",
            logical_identity=f"{mode}-orientation.yaml",
            trusted_root=root,
        )
        if (
            not isinstance(orientation, Mapping)
            or orientation.get("schema") != "idea-preference-orientation/v2"
            or canonical_digest(_owner_static_fill_projection(static_fill, operation=mode))
            != orientation.get("static_scaffold_digest")
        ):
            raise ValueError("immutable fill does not match its owner orientation")
        if not isinstance(consumer, Mapping) or not isinstance(consumer.get("task_context"), Mapping):
            raise ValueError("missing preference consumer")
        old_context = dict(consumer["task_context"])
        if dict(consumer) != _preference_consumer_view(mode, old_context):
            raise ValueError("modified preference consumer")
        current_context = idea_preference_context(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=unit_root / f"{mode}-orientation.yaml",
            corpus_path=unit_root / f"{mode}-evidence-corpus.yaml",
            excluded_paths=_corpus_exclusions(unit_root, mode),
            record_path_value=unit_root / "record.yaml",
        )
        old_context.pop("record_bytes_digest", None)
        current_context.pop("record_bytes_digest", None)
        if old_context != current_context:
            raise ValueError("stale authoring context")
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("已有填写内容或准备契约已变化，无法安全刷新；未做修改。") from exc
    return copy.deepcopy(dict(fill))


def _restore_analysis_mutable_fields(
    scaffold: dict[str, object],
    preserved: Mapping[str, object],
    *,
    mode: str,
) -> dict[str, object]:
    scaffold["reviewer"] = copy.deepcopy(preserved["reviewer"])
    if mode == "review":
        scaffold["selection_rank"] = copy.deepcopy(preserved["selection_rank"])
    source_claims = preserved["claims"]
    target_claims = scaffold["claims"]
    assert isinstance(source_claims, list) and isinstance(target_claims, list)
    assert len(source_claims) == len(target_claims)
    for source, target in zip(source_claims, target_claims):
        assert isinstance(source, Mapping) and isinstance(target, dict)
        target["text"] = copy.deepcopy(source["text"])
        target["evidence_refs"] = copy.deepcopy(source["evidence_refs"])
    return scaffold


def _assert_bound_fill_unchanged(
    root: Path,
    fill_path: Path,
    *,
    initial_fill: object,
    initial_binding: Mapping[str, str],
) -> None:
    current_fill, current_binding = _bound_yaml(
        fill_path,
        logical_identity=fill_path.relative_to(root).as_posix(),
        trusted_root=root,
    )
    if current_binding != initial_binding or current_fill != initial_fill:
        raise ValueError("Agent-authored idea fill changed before write")


def _assert_semantic_write_boundary(
    root: Path,
    *,
    operation: str,
    canonical_id: str,
    orientation_path: Path,
    corpus_path: Path,
    excluded_paths: set[Path],
    record_path_value: Path,
    fill_path: Path,
    initial_fill: object,
    initial_fill_binding: Mapping[str, str],
    initial_context: Mapping[str, object],
    initial_resolution: Mapping[str, object],
    initial_corpus: Mapping[str, object],
    initial_corpus_binding: Mapping[str, str],
    initial_record_binding: Mapping[str, str],
    claims: list[dict],
    selection_id: str,
) -> None:
    context = idea_preference_context(
        root,
        operation=operation,
        canonical_id=canonical_id,
        orientation_path=orientation_path,
        corpus_path=corpus_path,
        excluded_paths=excluded_paths,
        record_path_value=record_path_value,
    )
    resolution = resolve_idea_preferences(
        root,
        operation=operation,
        context=context,
        selection_id=selection_id,
    )
    if (
        context != initial_context
        or resolution.get("task_context_digest") != initial_resolution.get("task_context_digest")
        or resolution.get("binding") != initial_resolution.get("binding")
        or resolution.get("hard_value_digests") != initial_resolution.get("hard_value_digests")
    ):
        raise ValueError("idea authoring inputs changed before write")
    current_record_binding = regular_file_binding(
        record_path_value,
        logical_identity="record.yaml",
        trusted_root=root,
    )
    if current_record_binding != initial_record_binding:
        raise ValueError("canonical idea record changed before write")
    _assert_bound_fill_unchanged(
        root,
        fill_path,
        initial_fill=initial_fill,
        initial_binding=initial_fill_binding,
    )
    corpus, corpus_binding = _validated_frozen_corpus(root, corpus_path)
    if corpus != initial_corpus or corpus_binding != initial_corpus_binding:
        raise ValueError("frozen idea evidence corpus changed before write")
    if _claim_input_violations(
        root,
        claims,
        corpus,
        consumer_id=canonical_id,
    ):
        raise ValueError("cited idea evidence changed before write")


def _load_current_corpus(
    root: Path,
    corpus_path: Path,
    *,
    excluded_paths: set[Path],
) -> tuple[dict[str, object], dict[str, str]]:
    # `excluded_paths` remains part of the owner API for compatibility.  The
    # frozen manifest is intentionally not compared with the mutable live KB.
    del excluded_paths
    return _validated_frozen_corpus(root, corpus_path)


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
    corpus, corpus_binding = _load_current_corpus(
        root,
        corpus_path,
        excluded_paths=excluded_paths,
    )
    commitment = _corpus_commitment(corpus, corpus_binding)
    schema_version = 1 if corpus.get("schema") == "idea-evidence-corpus/v1" else 2
    orientation, orientation_binding = _bound_yaml(
        orientation_path,
        logical_identity=orientation_path.name,
        trusted_root=root,
    )
    static_digest = (
        str(orientation.get("static_scaffold_digest") or "")
        if schema_version == 2 and isinstance(orientation, Mapping)
        else ""
    )
    expected_orientation = idea_preference_orientation(
        operation,
        canonical_id=canonical_id,
        corpus_commitment=commitment,
        request_context=request_context,
        schema_version=schema_version,
        static_scaffold_digest=static_digest,
    )
    if orientation != expected_orientation:
        raise ValueError("immutable idea authoring orientation was modified")
    current_anchor = _authoring_anchor(
        operation=operation,
        canonical_id=canonical_id,
        request_context=request_context,
        orientation_binding=orientation_binding,
        corpus_commitment=commitment,
    )
    owner_anchor: object = None
    record: object = None
    record_binding: dict[str, str] | None = None
    if operation == "generate":
        if request_context is None:
            raise ValueError("idea generation preference context requires exact request context")
        if corpus.get("schema") == "idea-evidence-corpus/v2":
            prepared, _prepared_binding = _load_prepared_generation_bundle(
                root,
                bundle_id=canonical_id,
                request_context=request_context,
                current_anchor=current_anchor,
            )
            owner_anchor = prepared.get("authoring_contract")
        elif bundle_index_path(root, canonical_id).exists() or bundle_index_path(
            root, canonical_id
        ).is_symlink():
            raise ValueError("legacy idea generation cannot carry a v2 prepared owner bundle")
    else:
        if record_path_value is None:
            raise ValueError("semantic idea preference context requires the canonical record")
        record, record_binding = _bound_yaml(
            record_path_value,
            logical_identity="record.yaml",
            trusted_root=root,
        )
        if not isinstance(record, Mapping):
            raise ValueError("canonical idea record is malformed")
        owner_anchor = _record_authoring_anchor(record, operation)
        if corpus.get("schema") == "idea-evidence-corpus/v1":
            if owner_anchor is not None:
                raise ValueError("legacy semantic idea task cannot carry a v2 owner anchor")
            payload = record.get("payload")
            consumptions = payload.get("idea_authoring_consumptions") if isinstance(payload, Mapping) else None
            if isinstance(consumptions, Mapping) and operation in consumptions:
                raise ValueError("legacy unanchored idea authoring task was already consumed")
    if corpus.get("schema") == "idea-evidence-corpus/v2":
        _validate_authoring_anchor(
            owner_anchor,
            operation=operation,
            canonical_id=canonical_id,
        )
        if owner_anchor != current_anchor:
            raise ValueError("idea authoring owner anchor does not match current contract")
        owner_anchor_digest = canonical_digest(owner_anchor)
    else:
        owner_anchor_digest = canonical_digest({})
    phase_contract_digest = (
        canonical_digest(expected_orientation["phase_contract"])
        if corpus.get("schema") == "idea-evidence-corpus/v1"
        else canonical_digest(
            {
                "phase_contract": expected_orientation["phase_contract"],
                "owner_anchor_digest": owner_anchor_digest,
            }
        )
    )
    common = {
        "canonical_id": canonical_id,
        "canonical_kind": "idea-generation-bundle" if operation == "generate" else "idea",
        "operation": operation,
        "phase_contract_digest": phase_contract_digest,
        "immutable_orientation_identity_digest": orientation_binding["identity_digest"],
        "immutable_orientation_bytes_digest": orientation_binding["bytes_digest"],
        "evidence_corpus_identity_digest": str(corpus["identity_digest"]),
        "evidence_corpus_bytes_digest": str(corpus["bytes_digest"]),
    }
    if operation == "generate":
        return {
            **common,
            "request_context_digest": canonical_digest(dict(request_context)),
            "candidate_count": int(request_context["count"]),
            "bundle_id_digest": canonical_digest(request_context["bundle_id"]),
            "pool_digest": canonical_digest(request_context["pool"]),
            "source_digest": canonical_digest(request_context["source"]),
        }
    assert record_binding is not None
    return {
        **common,
        "record_identity_digest": (
            record_binding["identity_digest"]
            if corpus.get("schema") == "idea-evidence-corpus/v1"
            else canonical_digest(
                {"logical_identity": record_path_value.relative_to(root).as_posix()}
            )
        ),
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
    preference_context: Mapping[str, object] | None,
) -> dict[str, object]:
    count = int(request_context["count"])
    payload: dict[str, object] = {
        "schema": "idea-generation-fill/v1",
        "bundle_id": str(request_context["bundle_id"]),
        "request_context": dict(request_context),
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
    if preference_context is not None:
        payload["preference_consumer"] = _preference_consumer_view(
            "generate", preference_context
        )
    return payload


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
    text = str(args.input or "").strip()
    if not text:
        candidate = bundle_root(root, bundle_id) / GENERATION_FILL_NAME
    else:
        raw = Path(text).expanduser()
        if raw.is_absolute():
            candidate = raw
        else:
            # Align with the other verify inputs: bundle-relative first, then
            # project-root relative when only the latter exists.
            bundle_candidate = bundle_root(root, bundle_id) / raw
            root_candidate = root / raw
            candidate = bundle_candidate
            if not (bundle_candidate.exists() or bundle_candidate.is_symlink()) and (
                root_candidate.exists() or root_candidate.is_symlink()
            ):
                candidate = root_candidate
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
    index_path = bundle_index_path(root, bundle_id)
    if index_path.exists() or index_path.is_symlink():
        prepared_bundle, prepared_bundle_binding = _bound_yaml(
            index_path,
            logical_identity=index_path.relative_to(root).as_posix(),
            trusted_root=root,
        )
        corpus, corpus_binding = _validated_frozen_corpus(root, corpus_path)
        orientation, orientation_binding = _bound_yaml(
            orientation_path,
            logical_identity=orientation_path.name,
            trusted_root=root,
        )
        expected_orientation = idea_preference_orientation(
            "generate",
            canonical_id=bundle_id,
            corpus_commitment=_corpus_commitment(corpus, corpus_binding),
            request_context=request_context,
            static_scaffold_digest=str(
                orientation.get("static_scaffold_digest")
                if isinstance(orientation, Mapping)
                else ""
            ),
        )
        if orientation != expected_orientation:
            raise ValueError("immutable idea generation orientation was modified")
        current_anchor = _authoring_anchor(
            operation="generate",
            canonical_id=bundle_id,
            request_context=request_context,
            orientation_binding=orientation_binding,
            corpus_commitment=_corpus_commitment(corpus, corpus_binding),
        )
        if prepared_bundle != _prepared_generation_bundle(
            bundle_id, request_context, current_anchor
        ):
            raise ValueError("idea generation prepared bundle is malformed")
        authoring_contract = _validate_authoring_anchor(
            prepared_bundle.get("authoring_contract"),
            operation="generate",
            canonical_id=bundle_id,
        )
        authoring_provenance = _authoring_provenance(authoring_contract)
    else:
        corpus, _corpus_binding = _validated_frozen_corpus(root, corpus_path)
        if corpus.get("schema") != "idea-evidence-corpus/v1":
            raise ValueError("v2 idea generation requires a prepared owner bundle")
        prepared_bundle_binding = {}
        authoring_contract = None
        authoring_provenance = _authoring_provenance(None)
    fill_path = _generation_fill_path(root, args, bundle_id=bundle_id)
    fill, fill_binding = _bound_yaml(
        fill_path,
        logical_identity=fill_path.relative_to(root).as_posix(),
        trusted_root=root,
    )
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
    _validate_owner_static_fill(
        fill,
        generation_scaffold(request_context, context),
        operation="generate",
    )
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
        "prepared_bundle_binding": prepared_bundle_binding,
        "authoring_contract": (
            dict(authoring_contract) if authoring_contract is not None else {}
        ),
        "authoring_provenance": authoring_provenance,
        "fill_path": fill_path,
        "fill_binding": fill_binding,
        "candidates": candidates,
    }


def ensure_bundle(root: Path, bundle_id: str, *, title: str, source: str, pool: str, strategy: str = "generated") -> dict:
    _assert_safe_generic_bundle_path(root, bundle_id)
    ensure_dir(bundle_root(root, bundle_id))
    _assert_safe_generic_bundle_path(root, bundle_id)
    existing = load_yaml(bundle_index_path(root, bundle_id), default={})
    if _is_prepared_generation_bundle(existing):
        raise ValueError("prepared idea generation bundle cannot be used by generic bundle operations")
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


def _claim_source_record(
    claims: list[dict],
    *,
    consumer_id: str = "",
    consumer_kind: str = "idea",
) -> dict[str, object]:
    return {
        "id": consumer_id,
        "kind": consumer_kind,
        "payload": {"claims": claims},
    }


def _trusted_claim_source_roots(
    root: Path,
    claims: list[dict],
    *,
    consumer_id: str = "",
    consumer_kind: str = "idea",
) -> dict[str, Path | EvidenceSourceSnapshot]:
    return trusted_claim_source_roots(
        root,
        _claim_source_record(
            claims,
            consumer_id=consumer_id,
            consumer_kind=consumer_kind,
        ),
    )


def _verify_cross_unit_claims(
    root: Path,
    claims: object,
    *,
    source_roots: dict[str, Path | EvidenceSourceSnapshot] | None = None,
) -> list[str]:
    violations = validate_claims(claims)
    if not isinstance(claims, list):
        return violations
    if source_roots is None:
        try:
            source_roots = _trusted_claim_source_roots(root, claims)
        except ValueError:
            violations.append("cross-unit evidence sources are missing, ambiguous, or unsafe")
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
            single_ref_claim = {**claim, "evidence_refs": [evidence_ref]}
            for violation in verify_claim_evidence(
                single_ref_claim,
                None,
                source_roots=source_roots,
            ):
                violations.append(f"{where}: {violation}")
    return violations


def _claims_corpus_violations(
    root: Path,
    claims: list[dict],
    corpus: Mapping[str, object],
    *,
    source_roots: Mapping[str, Path | EvidenceSourceSnapshot],
) -> list[str]:
    frozen_entries = {
        str(item.get("path") or ""): item
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
            if _is_authoring_control_artifact(Path(artifact)):
                violations.append(
                    f"claims[{claim_index}].evidence_refs[{ref_index}]: "
                    "Agent authoring control artifacts cannot be cited"
                )
                continue
            source = source_roots.get(source_unit_id)
            if not isinstance(source, EvidenceSourceSnapshot):
                continue
            try:
                snapshot = source.artifact_snapshot(artifact)
                relative = snapshot.path.relative_to(root.absolute()).as_posix()
            except ValueError:
                violations.append(
                    f"claims[{claim_index}].evidence_refs[{ref_index}]: "
                    "frozen evidence artifact is missing or unsafe"
                )
                continue
            frozen = frozen_entries.get(relative)
            if not isinstance(frozen, Mapping):
                violations.append(
                    f"claims[{claim_index}].evidence_refs[{ref_index}]: "
                    "artifact was not present in the frozen pre-authoring evidence corpus"
                )
                continue
            device, inode, mode, size, _modified, _changed = snapshot.file_identity
            if (
                not stat.S_ISREG(mode)
                or size > MAX_CORPUS_FILE_BYTES
                or (
                    corpus.get("schema") == "idea-evidence-corpus/v2"
                    and size != frozen.get("size")
                )
            ):
                violations.append(
                    f"claims[{claim_index}].evidence_refs[{ref_index}]: "
                    "frozen evidence artifact is missing or unsafe"
                )
                continue
            current = {
                "identity_digest": canonical_digest(
                    {
                        "logical_identity": relative,
                        "device": device,
                        "inode": inode,
                        "mode": stat.S_IMODE(mode),
                    }
                ),
                "bytes_digest": snapshot.byte_sha256,
            }
            if current != {
                "identity_digest": str(frozen.get("identity_digest") or ""),
                "bytes_digest": str(frozen.get("bytes_digest") or ""),
            }:
                violations.append(
                    f"claims[{claim_index}].evidence_refs[{ref_index}]: "
                    "frozen evidence artifact identity or bytes changed"
                )
    return violations


def _corpus_source_unit_ids(corpus: Mapping[str, object]) -> list[str]:
    """List every unit id whose artifacts are citable inside the frozen corpus."""
    entries = corpus.get("entries") if isinstance(corpus, Mapping) else None
    unit_ids: set[str] = set()
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, Mapping):
            continue
        parts = Path(str(item.get("path") or "")).parts
        if len(parts) >= 4 and parts[:2] == ("kb", "units"):
            unit_ids.add(parts[3])
    return sorted(unit_ids)


def _corpus_scope_hint(corpus: Mapping[str, object]) -> str:
    allowed = _corpus_source_unit_ids(corpus)
    if allowed:
        listing = f"共 {len(allowed)} 个：{', '.join(allowed)}"
    else:
        listing = "0 个（当前冻结语料为空）"
    return (
        f"冻结证据语料内可引用的 source_unit_id {listing}；"
        "如需引用清单外的 unit：先将其入库并链接到本 idea（kb link），"
        "再重新运行 --phase prepare 重新冻结证据语料后重填"
    )


def _claim_input_violations(
    root: Path,
    claims: list[dict],
    corpus: Mapping[str, object],
    *,
    consumer_id: str = "",
    consumer_kind: str = "idea",
) -> list[str]:
    try:
        source_roots = _trusted_claim_source_roots(
            root,
            claims,
            consumer_id=consumer_id,
            consumer_kind=consumer_kind,
        )
    except ValueError:
        return [
            "cross-unit evidence sources are missing, ambiguous, or unsafe；"
            + _corpus_scope_hint(corpus)
        ]
    before = _claims_corpus_violations(
        root,
        claims,
        corpus,
        source_roots=source_roots,
    )
    if before:
        return _with_corpus_scope_hint(before, corpus)
    evidence = _verify_cross_unit_claims(root, claims, source_roots=source_roots)
    after = _claims_corpus_violations(
        root,
        claims,
        corpus,
        source_roots=source_roots,
    )
    return _with_corpus_scope_hint([*evidence, *after], corpus)


def _with_corpus_scope_hint(violations: list[str], corpus: Mapping[str, object]) -> list[str]:
    """Append the citable-unit inventory once when a corpus-scope violation exists."""
    if any(
        "frozen pre-authoring evidence corpus" in violation
        or "cross-unit evidence sources are missing" in violation
        for violation in violations
    ):
        violations = [*violations, _corpus_scope_hint(corpus)]
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
    violations.extend(validate_claims(claims))
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
    violations.extend(validate_claims(claims))
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
        refresh_corpus = bool(getattr(args, "refresh_corpus", False))
        consumed_bindings = _consumed_fill_bindings(root, record, unit_root, mode)
        try:
            _require_existing_semantic_anchor_if_v2(
                root,
                operation=mode,
                record=record,
                unit_root=unit_root,
                allow_consumed_without_anchor=bool(consumed_bindings),
            )
        except ValueError as exc:
            raise SystemExit(
                "Existing idea authoring contract is stale, unanchored, or conflicts with another active operation."
            ) from exc
        existing_fill = (
            _load_refreshable_analysis_fill(root, record, unit_root, mode=mode)
            if refresh_corpus
            else _guard_existing_empty_fill(
                root,
                fill_path,
                analysis_scaffold(record, mode=mode, preference_context=None),
                consumed_bindings=consumed_bindings,
            )
        )
        if existing_fill is not None:
            try:
                current_context = idea_preference_context(
                    root,
                    operation=mode,
                    canonical_id=str(record["id"]),
                    orientation_path=orientation_path,
                    corpus_path=corpus_path,
                    excluded_paths=exclusions,
                    record_path_value=unit_root / "record.yaml",
                )
                if existing_fill == analysis_scaffold(
                    record,
                    mode=mode,
                    preference_context=current_context,
                ) and _has_current_v2_corpus(root, corpus_path):
                    print(f"[ok] evidence-first {mode} scaffold is already prepared")
                    return 0
            except ValueError:
                pass
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        if mode == "analyze":
            record["payload"]["analysis"]["analysis_status"] = "awaiting_agent_fill"
        else:
            record["payload"]["review"]["review_status"] = "awaiting_agent_fill"
        if not any(
            isinstance(item, Mapping) and item.get("action") == f"idea-{mode}-scaffolded"
            for item in record.get("history", [])
        ):
            append_history(
                record,
                action=f"idea-{mode}-scaffolded",
                summary=f"Prepared an empty evidence-first {mode} scaffold.",
                information_types=["inference", "evaluation", "unverified"],
                artifacts=[rel(root, fill_path)],
            )
        write_record(root, record)
        anchor = _write_authoring_contract(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            static_scaffold=analysis_scaffold(record, mode=mode, preference_context=None),
        )
        _persist_record_authoring_anchor(record, mode, anchor)
        write_record(root, record)
        preference_context = idea_preference_context(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=unit_root / "record.yaml",
        )
        refreshed_scaffold = analysis_scaffold(
            record,
            mode=mode,
            preference_context=preference_context,
        )
        if refresh_corpus:
            assert existing_fill is not None
            refreshed_scaffold = _restore_analysis_mutable_fields(
                refreshed_scaffold,
                existing_fill,
                mode=mode,
            )
        write_yaml_if_changed(fill_path, refreshed_scaffold)
        print(
            f"[ok] {'refreshed evidence corpus and preserved Agent fill' if refresh_corpus else f'prepared evidence-first {mode} scaffold'}"
        )
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
        record_runtime_binding = regular_file_binding(
            unit_root / "record.yaml",
            logical_identity="record.yaml",
            trusted_root=root,
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
    candidate_path = _resolve_verify_input(
        root,
        unit_root,
        fill_path.name,
        args.input,
        operation=mode,
    )
    try:
        fill, fill_binding = _bound_yaml(
            candidate_path,
            logical_identity=candidate_path.relative_to(root).as_posix(),
            trusted_root=root,
        )
        if not isinstance(fill, Mapping):
            raise ValueError(f"{mode} fill must be a mapping")
        _validate_owner_static_fill(
            fill,
            analysis_scaffold(record, mode=mode, preference_context=preference_context),
            operation=mode,
        )
        _validate_preference_consumer_view(fill, operation=mode, context=preference_context)
    except ValueError as exc:
        print(f"[reject] {mode} preference binding: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    violations, claims = verify_analysis_fill(root, fill, record["id"], mode=mode)
    try:
        corpus, corpus_binding = _validated_frozen_corpus(root, corpus_path)
    except ValueError as exc:
        print(f"[reject] {mode} evidence corpus: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    active_anchor = (
        _validate_authoring_anchor(
            _record_authoring_anchor(record, mode),
            operation=mode,
            canonical_id=str(record["id"]),
        )
        if corpus.get("schema") == "idea-evidence-corpus/v2"
        else None
    )
    authoring_provenance = _authoring_provenance(active_anchor)
    violations.extend(
        _claim_input_violations(
            root,
            claims,
            corpus,
            consumer_id=str(record["id"]),
        )
    )
    if violations:
        print(f"[reject] {mode} failed evidence verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    try:
        _assert_semantic_write_boundary(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=unit_root / "record.yaml",
            fill_path=candidate_path,
            initial_fill=fill,
            initial_fill_binding=fill_binding,
            initial_context=preference_context,
            initial_resolution=preference_resolution,
            initial_corpus=corpus,
            initial_corpus_binding=corpus_binding,
            initial_record_binding=record_runtime_binding,
            claims=claims,
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
        )
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
    record["payload"].setdefault("idea_authoring_consumptions", {})[mode] = dict(fill_binding)
    build_verification_receipt(
        record,
        unit_root,
        source_roots=_trusted_claim_source_roots(
            root,
            claims,
            consumer_id=str(record["id"]),
        ),
    )
    try:
        _assert_semantic_write_boundary(
            root,
            operation=mode,
            canonical_id=str(record["id"]),
            orientation_path=orientation_path,
            corpus_path=corpus_path,
            excluded_paths=exclusions,
            record_path_value=unit_root / "record.yaml",
            fill_path=candidate_path,
            initial_fill=fill,
            initial_fill_binding=fill_binding,
            initial_context=preference_context,
            initial_resolution=preference_resolution,
            initial_corpus=corpus,
            initial_corpus_binding=corpus_binding,
            initial_record_binding=record_runtime_binding,
            claims=claims,
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
        )
    except ValueError as exc:
        print(f"[reject] {mode} final write-boundary check: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if active_anchor is not None:
        _consume_record_authoring_anchor(record, mode)
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
        "consumed_fill_binding": dict(fill_binding),
        "authoring_provenance": authoring_provenance,
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
        target_paths=[unit_root / "record.yaml", fill_path, result_path, orientation_path, corpus_path, *([unit_root / "idea-card.md"] if mode == "review" else []), *_index_checkpoint_paths(root)],
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
    fill_binding: Mapping[str, str],
    authoring_provenance: Mapping[str, str],
    preference_binding: Mapping[str, object] | None = None,
) -> tuple[dict, dict, list[dict]]:
    verified_at = utc_now_iso()
    digest_source = f"{record['id']}\n{fill['reviewer']}\n{fill['conclusion']}\n{verified_at}"
    conclusion = {
        "id": f"discussion-{hashlib.sha1(digest_source.encode('utf-8')).hexdigest()[:10]}",
        "conclusion": str(fill["conclusion"]).strip(),
        "reviewer": str(fill["reviewer"]).strip(),
        "verified_at": verified_at,
        "verification": "evidence_verified",
        "claims": claims,
        "consumed_fill_binding": dict(fill_binding),
        "authoring_provenance": dict(authoring_provenance),
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
        "consumed_fill_binding": dict(fill_binding),
        "authoring_provenance": dict(authoring_provenance),
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
        source_roots=_trusted_claim_source_roots(
            root,
            claims,
            consumer_id=str(record["id"]),
        ),
        verified_at=verified_at,
    )
    items = load_discussion_judgements(unit_root, record["id"])
    items.append(judgement)
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
    record["payload"].setdefault("idea_authoring_consumptions", {})["discuss"] = dict(
        fill_binding
    )
    return conclusion, judgement, items


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
            cmd.add_argument("--refresh-corpus", action="store_true")
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
            try:
                has_prepared_owner = _generation_prepare_has_current_owner(
                    root,
                    bundle_id=bundle_id,
                    request_context=request_context,
                )
            except ValueError as exc:
                raise SystemExit(
                    "This idea generation bundle is terminal or its prepared state changed."
                ) from exc
            static_scaffold = generation_scaffold(request_context, None)
            existing_fill = _guard_existing_empty_fill(
                root,
                fill_path,
                static_scaffold,
            )
            if existing_fill is not None:
                try:
                    current_context = idea_preference_context(
                        root,
                        operation="generate",
                        canonical_id=bundle_id,
                        orientation_path=orientation_path,
                        corpus_path=corpus_path,
                        excluded_paths=set(),
                        request_context=request_context,
                    )
                    if (
                        existing_fill == generation_scaffold(request_context, current_context)
                        and _has_current_v2_corpus(root, corpus_path)
                    ):
                        print("空白候选槽位已经准备完成。")
                        return 0
                except ValueError:
                    pass
            if has_prepared_owner:
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
                print("空白候选槽位已经恢复为当前准备状态。")
                _queue_checkpoint(
                    root,
                    trigger="milestone",
                    message=f"milestone: restore idea generation fill {bundle_id}",
                    target_paths=[fill_path],
                )
                return 0
            anchor = _write_authoring_contract(
                root,
                operation="generate",
                canonical_id=bundle_id,
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=set(),
                request_context=request_context,
                static_scaffold=generation_scaffold(request_context, None),
            )
            write_yaml_if_changed(
                bundle_index_path(root, bundle_id),
                _prepared_generation_bundle(bundle_id, request_context, anchor),
            )
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
                target_paths=[
                    bundle_index_path(root, bundle_id),
                    orientation_path,
                    corpus_path,
                    fill_path,
                ],
            )
            return 0

        try:
            planned = getattr(args, "_generation_plan", None)
            current_plan = generation_materialization_plan(root, args, bundle_id=bundle_id)
            if not isinstance(planned, dict) or (
                planned.get("fill_binding") != current_plan.get("fill_binding")
                or planned.get("prepared_bundle_binding")
                != current_plan.get("prepared_bundle_binding")
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
            "authoring_provenance": dict(current_plan["authoring_provenance"]),
            "consumed_fill_binding": dict(current_plan["fill_binding"]),
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
                or final_plan.get("prepared_bundle_binding")
                != current_plan.get("prepared_bundle_binding")
                or final_plan.get("candidates") != current_plan.get("candidates")
                or final_plan.get("preference_context") != current_plan.get("preference_context")
                or final_resolution.get("task_context_digest")
                != preference_resolution.get("task_context_digest")
                or final_resolution.get("binding") != preference_resolution.get("binding")
                or final_resolution.get("hard_value_digests")
                != preference_resolution.get("hard_value_digests")
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
    _assert_planned_idea_resolution(args, record, path)
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
            consumed_bindings = _consumed_fill_bindings(
                root, record, unit_root, "discuss"
            )
            try:
                _require_existing_semantic_anchor_if_v2(
                    root,
                    operation="discuss",
                    record=record,
                    unit_root=unit_root,
                    allow_consumed_without_anchor=bool(consumed_bindings),
                )
            except ValueError as exc:
                raise SystemExit(
                    "Existing idea discussion contract is stale, unanchored, or conflicts with another active operation."
                ) from exc
            existing_fill = _guard_existing_empty_fill(
                root,
                scaffold_path,
                discussion_scaffold(record, preference_context=None),
                consumed_bindings=consumed_bindings,
            )
            if existing_fill is not None:
                try:
                    current_context = idea_preference_context(
                        root,
                        operation="discuss",
                        canonical_id=str(record["id"]),
                        orientation_path=orientation_path,
                        corpus_path=corpus_path,
                        excluded_paths=exclusions,
                        record_path_value=unit_root / "record.yaml",
                    )
                    if existing_fill == discussion_scaffold(
                        record,
                        preference_context=current_context,
                    ) and _has_current_v2_corpus(root, corpus_path):
                        print("[ok] evidence-first sparring conclusion is already prepared")
                        return 0
                except ValueError:
                    pass
            if not any(
                isinstance(item, Mapping) and item.get("action") == "idea-discussion-scaffolded"
                for item in record.get("history", [])
            ):
                append_history(
                    record,
                    action="idea-discussion-scaffolded",
                    summary="Prepared an empty evidence-first sparring conclusion scaffold.",
                    information_types=["inference", "evaluation", "unverified"],
                    artifacts=[rel(root, scaffold_path)],
                )
            write_record(root, record)
            anchor = _write_authoring_contract(
                root,
                operation="discuss",
                canonical_id=str(record["id"]),
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=exclusions,
                static_scaffold=discussion_scaffold(record, preference_context=None),
            )
            _persist_record_authoring_anchor(record, "discuss", anchor)
            write_record(root, record)
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
            record_runtime_binding = regular_file_binding(
                unit_root / "record.yaml",
                logical_identity="record.yaml",
                trusted_root=root,
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
        fill_path = _resolve_verify_input(
            root,
            unit_root,
            scaffold_path.name,
            args.input,
            operation="discuss",
        )
        try:
            fill, fill_binding = _bound_yaml(
                fill_path,
                logical_identity=fill_path.relative_to(root).as_posix(),
                trusted_root=root,
            )
            if not isinstance(fill, Mapping):
                raise ValueError("discussion fill must be a mapping")
            _validate_owner_static_fill(
                fill,
                discussion_scaffold(record, preference_context=preference_context),
                operation="discuss",
            )
            _validate_preference_consumer_view(
                fill,
                operation="discuss",
                context=preference_context,
            )
        except ValueError as exc:
            print(f"[reject] discuss preference binding: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        violations, claims = verify_discussion_fill(root, fill, record["id"])
        try:
            corpus, corpus_binding = _validated_frozen_corpus(root, corpus_path)
        except ValueError as exc:
            print(f"[reject] discuss evidence corpus: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        active_anchor = (
            _validate_authoring_anchor(
                _record_authoring_anchor(record, "discuss"),
                operation="discuss",
                canonical_id=str(record["id"]),
            )
            if corpus.get("schema") == "idea-evidence-corpus/v2"
            else None
        )
        authoring_provenance = _authoring_provenance(active_anchor)
        violations.extend(
            _claim_input_violations(
                root,
                claims,
                corpus,
                consumer_id=str(record["id"]),
            )
        )
        if violations:
            print("[reject] discussion conclusion failed verification:", file=sys.stderr)
            for violation in violations:
                print(f"  - {violation}", file=sys.stderr)
            raise SystemExit(1)
        try:
            _assert_semantic_write_boundary(
                root,
                operation="discuss",
                canonical_id=str(record["id"]),
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=exclusions,
                record_path_value=unit_root / "record.yaml",
                fill_path=fill_path,
                initial_fill=fill,
                initial_fill_binding=fill_binding,
                initial_context=preference_context,
                initial_resolution=preference_resolution,
                initial_corpus=corpus,
                initial_corpus_binding=corpus_binding,
                initial_record_binding=record_runtime_binding,
                claims=claims,
                selection_id=str(args.preference_selection_id or ""),
            )
        except ValueError as exc:
            print(f"[reject] discuss write-boundary preference check: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        conclusion, _judgement, judgement_items = persist_discussion_conclusion(
            root,
            unit_root,
            record,
            fill,
            claims,
            fill_binding=fill_binding,
            authoring_provenance=authoring_provenance,
            preference_binding=dict(preference_resolution.get("binding") or {}),
        )
        try:
            _assert_semantic_write_boundary(
                root,
                operation="discuss",
                canonical_id=str(record["id"]),
                orientation_path=orientation_path,
                corpus_path=corpus_path,
                excluded_paths=exclusions,
                record_path_value=unit_root / "record.yaml",
                fill_path=fill_path,
                initial_fill=fill,
                initial_fill_binding=fill_binding,
                initial_context=preference_context,
                initial_resolution=preference_resolution,
                initial_corpus=corpus,
                initial_corpus_binding=corpus_binding,
                initial_record_binding=record_runtime_binding,
                claims=claims,
                selection_id=str(args.preference_selection_id or ""),
            )
        except ValueError as exc:
            print(f"[reject] discuss final write-boundary check: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if active_anchor is not None:
            _consume_record_authoring_anchor(record, "discuss")
        write_discussion_judgements(unit_root, record["id"], judgement_items)
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
            target_paths=[unit_root / "record.yaml", scaffold_path, discussion_judgements_path(unit_root), orientation_path, corpus_path, *_index_checkpoint_paths(root)],
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
    print(f"[reject] idea 命令 {args.command} 未被任何处理分支接受，没有做出任何修改。", file=sys.stderr)
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
        with mutation_transaction(
            root,
            f"idea-workbench:{args.command}",
            targets,
            preflight=lambda: _idea_transaction_preflight(args, root),
        ):
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

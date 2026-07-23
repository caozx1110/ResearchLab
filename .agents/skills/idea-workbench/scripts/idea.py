#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from contextvars import ContextVar
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

STRATEGIES = [
    ("narrow-scope", "把问题边界收窄到一个最小可证伪切口。"),
    ("repo-first", "优先复用现有 repo，只改动一个关键模块。"),
    ("evaluation-first", "先围绕评测与 failure probe 定义 idea。"),
    ("mechanism-first", "优先提出清晰机制假设与 kill test。"),
]

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
        bundle_id = args.bundle_id or f"idea-bundle-{slugify(args.title, max_words=6) or 'ideas'}-{hashlib.sha1(args.title.encode('utf-8')).hexdigest()[:6]}"
        idea_paths = [
            record_path(root, "idea", build_unit_id("idea", variant["title"], args.source))
            for variant in generated_variants(args.title, args.problem, args.hypothesis, max(1, args.count))
        ]
        return [bundle_index_path(root, bundle_id), *idea_paths, *targets]
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
        return [path, unit / f"{args.command}-fill.yaml", unit / f"{args.command}.yaml", unit / "idea-card.md", *targets]
    if args.command in {"discuss", "spar"}:
        return [path, unit / "discussion-fill.yaml", unit / "discussion-judgements.yaml", *targets]
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


def generated_variants(title: str, problem: str, hypothesis: str, count: int) -> list[dict]:
    variants = []
    for index in range(count):
        strategy_id, strategy_text = STRATEGIES[index % len(STRATEGIES)]
        variant_title = f"{title} / {strategy_id}"
        variants.append(
            {
                "title": variant_title,
                "strategy": strategy_id,
                "problem": problem or f"{title} 的研究问题，优先考虑：{strategy_text}",
                "hypothesis": hypothesis or f"假设通过 `{strategy_id}` 的切口，可以更快验证 `{title}` 是否值得继续推进。",
                "next_actions": ["补一条最小验证路径", "补一组 paper / repo 对照", f"围绕 `{strategy_id}` 定义 kill test"],
            }
        )
    return variants


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


def discussion_scaffold(record: dict) -> dict:
    return {
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


def analysis_scaffold(record: dict, *, mode: str) -> dict:
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
    result_path = unit_root / f"{mode}.yaml"
    if args.phase == "prepare":
        write_yaml_if_changed(fill_path, analysis_scaffold(record, mode=mode))
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
        print(f"[ok] prepared evidence-first {mode} scaffold")
        _queue_checkpoint(
            root, trigger="milestone", message=f"milestone: prepare idea {mode} {record['id']}",
            target_paths=[unit_root / "record.yaml", fill_path],
        )
        return 0

    candidate_path = Path(args.input) if args.input else fill_path
    if not candidate_path.is_absolute():
        candidate_path = unit_root / candidate_path
    if not candidate_path.exists():
        raise SystemExit(f"{mode} verify input not found")
    fill = load_yaml(candidate_path, default={})
    violations, claims = verify_analysis_fill(root, fill, record["id"], mode=mode)
    if violations:
        print(f"[reject] {mode} failed evidence verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    persist_analysis(record, fill, claims, mode=mode)
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
        target_paths=[unit_root / "record.yaml", result_path, *([unit_root / "idea-card.md"] if mode == "review" else []), *_index_checkpoint_paths(root)],
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

    for name in ("analyze", "review", "select", "archive"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--idea-id", required=True)
        if name in {"analyze", "review"}:
            cmd.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
            cmd.add_argument("--input", default="")
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
        bundle_id = args.bundle_id or f"idea-bundle-{slugify(args.title, max_words=6) or 'ideas'}-{hashlib.sha1(args.title.encode('utf-8')).hexdigest()[:6]}"
        ensure_bundle(root, bundle_id, title=args.title, source=args.source, pool=args.pool, strategy="generated")
        created: list[str] = []
        for variant in generated_variants(args.title, args.problem, args.hypothesis, max(1, args.count)):
            record = default_record("idea", title=variant["title"], maturity="lightweight", source={"original_uri": args.source})
            record["status"] = "draft"
            record["confirmation_status"] = "pending_user_confirmation"
            record["needs_human_confirmation"] = True
            record["information_types"] = ["user_opinion", "inference", "unverified"]
            record["payload"]["origin"]["source"] = args.source
            record["payload"]["candidate"]["bundle_id"] = bundle_id
            record["payload"]["candidate"]["strategy"] = variant["strategy"]
            record["payload"]["candidate"]["pool"] = args.pool
            record["payload"]["problem"]["problem_definition"] = variant["problem"]
            record["payload"]["hypothesis"]["core_hypothesis"] = variant["hypothesis"]
            record["payload"]["analysis"]["next_actions"] = variant["next_actions"]
            record["summary"] = variant["problem"]
            record = apply_record_governance(
                root,
                record,
                explicit_pools=[args.pool] if args.pool else [],
                infer_missing=True,
                source_label="idea-workbench",
            )
            path = write_record(root, record)
            created.append(str(record["id"]))
            print_created_idea(root, record, path)
        index_path = update_bundle(root, bundle_id, idea_ids=created)
        build_index(root)
        print(f"[ok] wrote {index_path.relative_to(root)}")
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
        if args.phase == "prepare":
            write_yaml_if_changed(scaffold_path, discussion_scaffold(record))
            append_history(
                record,
                action="idea-discussion-scaffolded",
                summary="Prepared an empty evidence-first sparring conclusion scaffold.",
                information_types=["inference", "evaluation", "unverified"],
                artifacts=[rel(root, scaffold_path)],
            )
            write_record(root, record)
            print("[ok] prepared an empty evidence-first sparring conclusion")
            _queue_checkpoint(
                root, trigger="milestone", message=f"milestone: prepare idea discussion {record['id']}",
                target_paths=[unit_root / "record.yaml", scaffold_path],
            )
            return 0

        if args.phase in {"confirm", "reject"}:
            if not str(args.conclusion_id or "").strip():
                raise SystemExit("Discussion decision requires a conclusion id.")
            judgements = load_discussion_judgements(unit_root, record["id"])
            matches = [
                item
                for item in judgements
                if str(item.get("id") or "") == str(args.conclusion_id)
            ]
            if not matches:
                raise SystemExit("Discussion conclusion is not available for this decision.")
            if len(matches) != 1:
                raise SystemExit("Discussion conclusion id is duplicated and requires repair.")
            selected = matches[0]
            sidecar_path = discussion_judgements_path(unit_root)
            violations = readiness_violations(root, selected, sidecar_path)
            if violations:
                raise SystemExit("Discussion conclusion is not ready for this decision:\n  - " + "\n  - ".join(violations))
            try:
                require_judgement_snapshot(
                    selected,
                    expected_snapshot=args.expected_snapshot,
                    owner="idea-workbench",
                    path=rel(root, sidecar_path),
                    root=root,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            if args.phase == "reject":
                apply_judgement_rejection(selected, reason=args.reason)
                selected["updated_at"] = utc_now_iso()
                write_discussion_judgements(unit_root, record["id"], judgements)
                for projection in record.setdefault("payload", {}).setdefault("discussion", {}).setdefault("conclusions", []):
                    if isinstance(projection, dict) and str(projection.get("judgement_id") or "") == str(args.conclusion_id):
                        projection["confirmation_status"] = "rejected"
                        projection["rejection"] = dict(selected.get("rejection") or {})
                append_history(
                    record,
                    action="idea-discussion-rejected",
                    summary="Rejected one evidence-grounded discussion conclusion.",
                    information_types=["user_opinion", "evaluation"],
                    artifacts=[rel(root, sidecar_path)],
                )
                write_record(root, record)
                print(f"[ok] rejected discussion conclusion {args.conclusion_id}")
                _queue_checkpoint(
                    root,
                    trigger="milestone",
                    message=f"milestone: reject idea discussion {record['id']}",
                    target_paths=[unit_root / "record.yaml", sidecar_path],
                )
                return 0
            claims = selected.get("payload", {}).get("claims", [])
            apply_confirmation(
                selected,
                confirmed_by=args.confirmed_by,
                evidence=args.evidence,
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
                method="idea.py discuss confirm",
                project_root=root,
                verification_root=unit_root,
                trusted_source_roots=_trusted_claim_source_roots(root, claims),
            )
            selected["updated_at"] = utc_now_iso()
            write_discussion_judgements(unit_root, record["id"], judgements)
            for projection in record.setdefault("payload", {}).setdefault("discussion", {}).setdefault("conclusions", []):
                if isinstance(projection, dict) and str(projection.get("judgement_id") or "") == str(args.conclusion_id):
                    projection["confirmation_status"] = "confirmed"
                    projection["confirmation"] = {
                        "by": selected.get("confirmation", {}).get("by", ""),
                        "at": selected.get("confirmation", {}).get("at", ""),
                    }
            append_history(
                record,
                action="idea-discussion-confirmed",
                summary="Confirmed one evidence-grounded discussion conclusion.",
                information_types=["inference", "evaluation"],
                artifacts=[rel(root, discussion_judgements_path(unit_root))],
            )
            write_record(root, record)
            print(f"[ok] confirmed discussion conclusion {args.conclusion_id}")
            _queue_checkpoint(
                root,
                trigger="milestone",
                message=f"milestone: confirm idea discussion {record['id']}",
                target_paths=[unit_root / "record.yaml", discussion_judgements_path(unit_root)],
            )
            return 0

        fill_path = Path(args.input) if args.input else scaffold_path
        if not fill_path.is_absolute():
            fill_path = unit_root / fill_path
        if not fill_path.exists():
            raise SystemExit("Discussion fill is missing; prepare or provide the agent-filled conclusion first.")
        fill = load_yaml(fill_path, default={})
        violations, claims = verify_discussion_fill(root, fill, record["id"])
        if violations:
            print("[reject] discussion conclusion failed verification:", file=sys.stderr)
            for violation in violations:
                print(f"  - {violation}", file=sys.stderr)
            raise SystemExit(1)
        conclusion, _judgement = persist_discussion_conclusion(root, unit_root, record, fill, claims)
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
            target_paths=[unit_root / "record.yaml", discussion_judgements_path(unit_root), *_index_checkpoint_paths(root)],
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
    targets = _idea_command_targets(args, root)
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

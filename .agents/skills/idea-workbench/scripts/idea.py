#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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

from research.common import ensure_dir, load_yaml, slugify, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.v2 import (
    append_history,
    apply_confirmation,
    apply_record_governance,
    build_index,
    default_record,
    ensure_v2_workspace,
    iter_records,
    locate_record,
    checkpoint_and_report,
    project_root,
    rel,
    synthesis_root,
    write_record,
)

STRATEGIES = [
    ("narrow-scope", "把问题边界收窄到一个最小可证伪切口。"),
    ("repo-first", "优先复用现有 repo，只改动一个关键模块。"),
    ("evaluation-first", "先围绕评测与 failure probe 定义 idea。"),
    ("mechanism-first", "优先提出清晰机制假设与 kill test。"),
]


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)


def review_payload(record: dict) -> dict:
    related_count = len(record["payload"]["analysis"].get("related_work", []))
    next_action_count = len(record["payload"]["analysis"].get("next_actions", []))
    link_count = len(record.get("links", []))
    novelty_score = min(5, 2 + (1 if record["payload"]["hypothesis"].get("difference_from_prior_work") else 0) + (1 if related_count else 0))
    feasibility_score = min(5, 2 + (1 if record["payload"]["analysis"].get("minimum_validation_path") else 0) + (1 if next_action_count else 0))
    evidence_score = min(5, 1 + min(2, link_count) + (1 if related_count else 0))
    total = novelty_score + feasibility_score + evidence_score
    recommendation = "pending_confirmation"
    if total >= 11:
        recommendation = "promising"
    elif total <= 7:
        recommendation = "needs-revision"
    return {
        "idea_id": record["id"],
        "status": "pending_user_confirmation",
        "information_types": ["inference", "evaluation", "unverified"],
        "novelty": record["payload"]["analysis"].get("novelty") or "待人工确认与现有工作相比的真正新意。",
        "feasibility": record["payload"]["analysis"].get("feasibility") or "待人工确认最小验证路径、资源与风险。",
        "evidence_gaps": [
            "需要补 paper / repo 对照来验证 novelty。"
            if related_count == 0
            else "需要进一步确认这些 related work 是否真的覆盖当前假设。"
        ],
        "killer_questions": [
            "如果只允许做一个最小实验，这个 idea 还能被有效证伪吗？",
            "如果复用现有 repo，关键改动面是否足够清晰？",
        ],
        "score_breakdown": {
            "novelty": novelty_score,
            "feasibility": feasibility_score,
            "evidence": evidence_score,
            "total": total,
        },
        "recommendation": recommendation,
    }


def analysis_payload(record: dict) -> dict:
    review = review_payload(record)
    return {
        "idea_id": record["id"],
        "status": "pending_user_confirmation",
        "information_types": ["inference", "evaluation", "unverified"],
        "novelty": review["novelty"],
        "feasibility": review["feasibility"],
        "recommendation": review["recommendation"],
        "next_actions": record["payload"]["analysis"].get("next_actions") or ["补相关 paper / repo 对照", "明确最小可验证实验"],
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
- scores：{review.get('score_breakdown')}

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
        if not bundle_id:
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
        total = review.get("score_breakdown", {}).get("total", "n/a")
        lines.extend(
            [
                f"## {record.get('title', '')}",
                "",
                f"- idea_id: `{record.get('id')}`",
                f"- total score: {total}",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage idea units in v2.")
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
        if name == "select":
            add_confirmation_arguments(cmd)

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


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    ensure_v2_workspace(root)

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
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: capture idea {record['id']}")
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
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: generate idea bundle {bundle_id}")
        return 0

    if args.command in {"review-assist", "select-best"}:
        records, bundle_id = resolve_idea_records(root, idea_ids=args.idea_id, pool=args.pool, bundle_id=args.bundle_id)
        ensure_bundle(root, bundle_id, title=bundle_id, source="", pool=args.pool, strategy="review")
        if args.command == "review-assist":
            for record in records:
                if record["payload"]["review"].get("review_status") == "not_started":
                    review = review_payload(record)
                    record["payload"]["review"]["review_status"] = "pending_user_confirmation"
                    record["payload"]["review"]["recommendation"] = review["recommendation"]
                    record["payload"]["review"]["score_breakdown"] = review["score_breakdown"]
                    record["payload"]["review"]["evidence_gaps"] = review["evidence_gaps"]
                    record["payload"]["review"]["killer_questions"] = review["killer_questions"]
                    write_record(root, record)
            assist_path = bundle_root(root, bundle_id) / "review-assist.md"
            write_text_if_changed(assist_path, review_assist_markdown(records))
            update_bundle(root, bundle_id, idea_ids=[record["id"] for record in records])
            build_index(root)
            print(f"[ok] wrote {assist_path.relative_to(root)}")
            checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: review assist bundle {bundle_id}")
            return 0
        scored_records = []
        for record in records:
            review = record["payload"]["review"]
            total = int(review.get("score_breakdown", {}).get("total") or review_payload(record)["score_breakdown"]["total"])
            scored_records.append((total, record))
        scored_records.sort(key=lambda item: (-item[0], str(item[1].get("id"))))
        selected = scored_records[0][1]
        for _, record in scored_records:
            if record["id"] == selected["id"]:
                record["status"] = "selected"
                record = apply_confirmation(record, confirmed_by=args.confirmed_by, evidence=args.evidence, method="idea.py select-best", project_root=root)
                record["payload"]["selection"]["selected_rank"] = "1"
                record["payload"]["selection"]["selected_reason"] = "Highest reviewed total score in explicit select-best command."
            append_history(
                record,
                action="idea-selected" if record["id"] == selected["id"] else "idea-reviewed-for-selection",
                summary="Explicit multi-candidate selection executed.",
                information_types=["fact"],
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
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: select best idea in {bundle_id}")
        return 0

    record, path = locate_record(root, args.idea_id, kind="idea")
    if record.get("kind") != "idea":
        raise SystemExit(f"{args.idea_id} is not an idea record")
    print_idea_resolution(root, args.idea_id, record, path)
    unit_root = path.parent

    if args.command == "analyze":
        analysis_path = unit_root / "analysis.yaml"
        payload = analysis_payload(record)
        write_yaml_if_changed(analysis_path, payload)
        record["payload"]["analysis"]["novelty"] = payload["novelty"]
        record["payload"]["analysis"]["feasibility"] = payload["feasibility"]
        record["payload"]["analysis"]["next_actions"] = payload["next_actions"]
        record["status"] = "pending"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        append_history(
            record,
            action="idea-analyzed",
            summary="Generated novelty and feasibility analysis.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, analysis_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] canonical idea id: {record['id']}")
        print(f"[ok] wrote {analysis_path.relative_to(root)}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: analyze idea {record['id']}")
        return 0

    if args.command == "review":
        review_path = unit_root / "review.yaml"
        card_path = unit_root / "idea-card.md"
        payload = review_payload(record)
        write_yaml_if_changed(review_path, payload)
        write_text_if_changed(card_path, idea_card(record, payload))
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["payload"]["review"]["review_status"] = "pending_user_confirmation"
        record["payload"]["review"]["recommendation"] = payload["recommendation"]
        record["payload"]["review"]["score_breakdown"] = payload["score_breakdown"]
        record["payload"]["review"]["evidence_gaps"] = payload["evidence_gaps"]
        record["payload"]["review"]["killer_questions"] = payload["killer_questions"]
        append_history(
            record,
            action="idea-reviewed",
            summary="Created review-ready idea card and review payload.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, review_path), rel(root, card_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] canonical idea id: {record['id']}")
        print(f"[ok] wrote {review_path.relative_to(root)}")
        print(f"[ok] wrote {card_path.relative_to(root)}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: review idea {record['id']}")
        return 0

    if args.command == "select":
        record["status"] = "selected"
        record = apply_confirmation(record, confirmed_by=args.confirmed_by, evidence=args.evidence, method="idea.py select", project_root=root)
        append_history(record, action="idea-selected", summary="Idea explicitly selected for method design.", information_types=["fact"])
        write_record(root, record)
        build_index(root)
        print(f"[ok] selected {record['id']}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: select idea {record['id']}")
        return 0

    if args.command == "archive":
        record["status"] = "archived"
        append_history(record, action="idea-archived", summary="Idea archived or merged into another direction.", information_types=["fact"])
        write_record(root, record)
        build_index(root)
        print(f"[ok] archived {record['id']}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: archive idea {record['id']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import Counter
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

from research.common import add_project_root_argument, ensure_dir, print_resolved_project_roots, slugify, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.core import iter_records, project_root, rel, synthesis_root


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
    units = [
        {
            "id": str(record.get("id") or ""),
            "kind": str(record.get("kind") or ""),
            "title": str(record.get("title") or ""),
        }
        for record in records
        if str(record.get("id") or "")
    ]
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
                "The runtime agent fills every required claim cell. Taxonomy cells, comparison-matrix "
                "cells, trends, and gaps require one or more verbatim evidence_refs. The script only "
                "validates structure and evidence; it never authors survey conclusions."
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


def select_records(
    records: list[dict],
    *,
    query: str = "",
    kind: str = "",
    topic: str = "",
    tag: str = "",
    pool: str = "",
) -> list[dict]:
    tokens = [token for token in query.lower().split() if token]
    selected = []
    for record in records:
        if kind and str(record.get("kind") or "") != kind:
            continue
        if topic and topic not in record.get("topics", []):
            continue
        if tag and tag not in record.get("tags", []):
            continue
        if pool and pool not in record.get("candidate_pools", []):
            continue
        haystack = " ".join(
            [
                str(record.get("title") or ""),
                str(record.get("summary") or ""),
                " ".join(record.get("tags", [])),
                " ".join(record.get("topics", [])),
                " ".join(record.get("candidate_pools", [])),
            ]
        ).lower()
        if tokens and not all(token in haystack for token in tokens):
            continue
        selected.append(record)
    return selected


def top_counts(records: list[dict], field: str, limit: int = 10) -> list[dict]:
    counter: Counter[str] = Counter()
    for record in records:
        for item in record.get(field, []):
            counter[str(item)] += 1
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def build_survey_payload(records: list[dict], *, query: str, kind: str, topic: str, tag: str, pool: str, mode: str) -> dict:
    observed = [
        f"共选中 {len(records)} 条知识单元。",
        f"kind 过滤：{kind or '全部'}；topic：{topic or '全部'}；tag：{tag or '全部'}；pool：{pool or '全部'}。",
    ]
    inferred = [
        "当前结果仍偏索引级综合，适合作为后续深读、选题或 pool 清理的起点。",
        "如需更强结论，应优先补人工确认过的高价值 paper / repo / idea。",
    ]
    suggested = [
        "围绕 top topics / top tags 继续收窄范围。",
        "把高频但未确认的条目转给对应 analyst skill。",
    ]
    return {
        **yaml_default(f"{mode}-{slugify(query or topic or tag or pool or kind or 'survey', max_words=8)}", "literature-synthesizer", status="ready", confidence=0.68),
        "mode": mode,
        "filters": {"query": query, "kind": kind, "topic": topic, "tag": tag, "pool": pool},
        "items": [
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "status": item.get("status"),
                "confirmation_status": item.get("confirmation_status"),
                "topics": item.get("topics", []),
                "tags": item.get("tags", []),
                "candidate_pools": item.get("candidate_pools", []),
                "summary": item.get("summary"),
            }
            for item in records
        ],
        "clusters": {
            "topics": top_counts(records, "topics"),
            "tags": top_counts(records, "tags"),
            "candidate_pools": top_counts(records, "candidate_pools"),
            "kinds": [{"name": name, "count": count} for name, count in Counter(str(record.get("kind") or "") for record in records).most_common()],
        },
        "Observed": observed,
        "Inferred": inferred,
        "Suggested": suggested,
        "OpenQuestions": [
            "是否需要基于当前池子继续分出 narrower topic？",
            "是否需要把其中某个 cluster 提升成长期可复用的 synthesis 页面？",
        ],
    }


def render_summary(payload: dict) -> str:
    lines = [f"# {payload['mode'].title()}: {payload['filters'].get('query') or payload['filters'].get('topic') or payload['filters'].get('tag') or payload['filters'].get('pool') or payload['filters'].get('kind') or 'all'}", ""]
    lines.extend(["## Snapshot", ""])
    for item in payload.get("Observed", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Clusters", ""])
    for cluster_name, values in payload.get("clusters", {}).items():
        names = ", ".join(f"{item['name']}({item['count']})" for item in values[:8]) or "-"
        lines.append(f"- {cluster_name}: {names}")
    lines.extend(["", "## Items", ""])
    for item in payload.get("items", []):
        lines.append(
            f"- `{item['id']}` · {item['title']} · {item.get('kind')} · "
            f"confirm={item.get('confirmation_status')} · topics={','.join(item.get('topics', [])) or '-'}"
        )
    lines.extend(["", "## Inferred", ""])
    for item in payload.get("Inferred", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Suggested", ""])
    for item in payload.get("Suggested", []):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthesize research units in core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, label in (("survey", "field"), ("review", "query")):
        cmd = subparsers.add_parser(name)
        if name == "survey":
            cmd.add_argument("action", nargs="?", choices=("prepare", "verify"), default="legacy")
            cmd.add_argument("--field", default="")
            cmd.add_argument("--query", default="")
            cmd.add_argument("--as-of", default="")
            cmd.add_argument("--input", default="")
        else:
            cmd.add_argument(f"--{label}", required=True)
        cmd.add_argument("--kind", default="")
        cmd.add_argument("--topic", default="")
        cmd.add_argument("--tag", default="")
        cmd.add_argument("--pool", default="")

    taxonomy = subparsers.add_parser("taxonomy")
    taxonomy.add_argument("--query", default="")
    taxonomy.add_argument("--kind", default="")
    taxonomy.add_argument("--topic", default="")
    taxonomy.add_argument("--tag", default="")
    taxonomy.add_argument("--pool", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    mode = args.command
    query = getattr(args, "field", "") or getattr(args, "query", "")
    slug = slugify(query or args.topic or args.tag or args.pool or args.kind or mode, max_words=8) or mode
    out_root = synthesis_root(root) / slug
    ensure_dir(out_root)
    selected = select_records(
        iter_records(root),
        query=query,
        kind=args.kind,
        topic=args.topic,
        tag=args.tag,
        pool=args.pool,
    )
    if mode == "survey" and args.action == "prepare":
        if not query:
            raise SystemExit("survey prepare requires --field or --query")
        if not args.as_of:
            raise SystemExit("survey prepare requires --as-of to anchor the selected KB snapshot")
        payload = build_survey_scaffold(
            selected,
            query=query,
            kind=args.kind,
            topic=args.topic,
            tag=args.tag,
            pool=args.pool,
            mode=mode,
            as_of=args.as_of,
        )
        fill_path = out_root / "survey-fill.yaml"
        write_yaml_if_changed(fill_path, payload)
        print(rel(root, fill_path))
        return 0
    payload = build_survey_payload(
        selected,
        query=query,
        kind=args.kind,
        topic=args.topic,
        tag=args.tag,
        pool=args.pool,
        mode=mode,
    )
    yaml_name = "taxonomy.yaml" if mode == "taxonomy" else f"{mode}.yaml"
    md_name = "taxonomy.md" if mode == "taxonomy" else "summary.md"
    yaml_path = out_root / yaml_name
    md_path = out_root / md_name
    write_yaml_if_changed(yaml_path, payload)
    write_text_if_changed(md_path, render_summary(payload))
    print(rel(root, yaml_path))
    print(rel(root, md_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

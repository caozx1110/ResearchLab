#!/usr/bin/env python3
"""Build a program-scoped literature map from the shared literature library."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import inspect
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11 import common as research_common
from research_v11.common import (
    append_program_reporting_event,
    bootstrap_workspace,
    ensure_research_runtime,
    find_project_root,
    load_literature_records,
    load_yaml,
    normalize_title,
    query_keyword_terms,
    research_root,
    utc_now_iso,
    write_yaml_if_changed,
    yaml_default,
)
from research_v11.retrieval import load_query_tags, score_literature_relevance

QUERY_STOPWORDS = {
    "about",
    "after",
    "before",
    "between",
    "build",
    "current",
    "experiment",
    "experiments",
    "goal",
    "goals",
    "improve",
    "improving",
    "method",
    "methods",
    "paper",
    "papers",
    "problem",
    "question",
    "research",
    "result",
    "results",
    "system",
    "using",
    "with",
}
STAGE_ORDER = (
    "problem-framing",
    "literature-analysis",
    "idea-generation",
    "idea-review",
    "method-design",
    "implementation-planning",
)

def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def append_wiki_log_event(project_root: Path, event: dict[str, Any], *, generated_by: str) -> None:
    helper = getattr(research_common, "append_wiki_log_event", None)
    if not callable(helper):
        return
    event_type = str(event.get("type") or event.get("event_type") or "event").strip() or "event"
    title = str(event.get("title") or event_type).strip() or event_type
    summary = str(event.get("summary") or event.get("message") or "").strip()
    occurred_at = event.get("timestamp") or event.get("occurred_at") or utc_now_iso()
    metadata = {
        key: value
        for key, value in event.items()
        if key not in {"type", "event_type", "title", "summary", "message", "timestamp", "occurred_at"}
    }
    signature: inspect.Signature | None = None
    try:
        signature = inspect.signature(helper)
    except (TypeError, ValueError):
        signature = None
    parameters = signature.parameters if signature is not None else {}
    if "event_type" in parameters and "title" in parameters:
        helper(
            project_root,
            event_type,
            title,
            summary=summary,
            metadata=metadata,
            occurred_at=occurred_at,
            generated_by=generated_by,
        )
        return
    if "event" in parameters:
        helper(project_root=project_root, event=event, generated_by=generated_by)
        return
    raise TypeError(
        "Unsupported append_wiki_log_event helper signature; expected "
        "`(project_root, event_type, title, ...)` or `(project_root, event, ...)`."
    )


def rebuild_wiki_index_markdown(project_root: Path) -> None:
    helper = getattr(research_common, "rebuild_wiki_index_markdown", None)
    if not callable(helper):
        return
    try:
        helper(project_root)
    except TypeError:
        helper(project_root=project_root)


def query_terms(text: str) -> list[str]:
    return query_keyword_terms(text, stopwords=QUERY_STOPWORDS)


def stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(str(stage or "").strip())
    except ValueError:
        return -1


def should_promote_stage(current_stage: str, target_stage: str) -> bool:
    current_rank = stage_rank(current_stage)
    target_rank = stage_rank(target_stage)
    if target_rank < 0:
        return False
    if current_rank < 0:
        return True
    return target_rank >= current_rank


def charter_query_text(charter: dict[str, Any]) -> str:
    parts = [
        str(charter.get("question") or ""),
        str(charter.get("goal") or ""),
    ]
    for item in charter.get("success_metrics", []):
        parts.append(str(item))
    for item in charter.get("non_goals", []):
        parts.append(str(item))
    constraints = charter.get("constraints", {})
    if isinstance(constraints, dict):
        parts.extend(str(value) for value in constraints.values() if str(value).strip())
    return "\n".join(part for part in parts if str(part).strip())


def build_map(program_id: str) -> dict[str, Any]:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    charter_path = research_root(project_root) / "programs" / program_id / "charter.yaml"
    literature_index_path = research_root(project_root) / "library" / "literature" / "index.yaml"
    taxonomy_path = research_root(project_root) / "library" / "literature" / "tag-taxonomy.yaml"
    charter = load_yaml(charter_path, default={})
    if not isinstance(charter, dict):
        raise SystemExit(f"Missing program charter: {charter_path}")

    query = charter_query_text(charter)
    query_profile = {
        "text": query,
        "normalized_text": normalize_title(query),
        "terms": query_terms(query),
        "tag_labels": load_query_tags(project_root, query),
    }
    records = load_literature_records(project_root)
    ranked_records: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (
            record,
            score_literature_relevance(
                record,
                normalized_query_text=query_profile["normalized_text"],
                query_terms=query_profile["terms"],
                query_tags=query_profile["tag_labels"],
                tokenize=query_terms,
            ),
        )
        for record in records
    ]
    ranked = sorted(
        ranked_records,
        key=lambda item: (
            -item[1]["score"],
            -(int(item[0].get("year") or 0)),
            item[0].get("id", ""),
        ),
    )
    selected_pairs = ranked[: min(12, len(ranked))]
    selected = [record for record, _breakdown in selected_pairs]
    topic_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in selected:
        if record.get("topics"):
            for topic in record["topics"]:
                topic_buckets[str(topic)].append(record)
        else:
            topic_buckets["uncategorized"].append(record)
    topic_counts = Counter({topic: len(items) for topic, items in topic_buckets.items()})
    dominant_topics = [topic for topic, _count in topic_counts.most_common(3)]

    payload = {
        **yaml_default(f"{program_id}-literature-map", "literature-analyst", status="active", confidence=0.72),
        "inputs": [
            charter_path.relative_to(project_root).as_posix(),
            literature_index_path.relative_to(project_root).as_posix(),
            taxonomy_path.relative_to(project_root).as_posix(),
            *[f"lit:{item['id']}" for item in selected],
        ],
        "program_id": program_id,
        "retrieval": {
            "query_text": query,
            "query_terms": query_profile["terms"],
            "query_tags": query_profile["tag_labels"],
            "selected_sources": [
                {
                    "source_id": record["id"],
                    "title": record.get("canonical_title", ""),
                    "short_summary": record.get("short_summary", ""),
                    "tags": record.get("tags", []),
                    "topics": record.get("topics", []),
                    "score": breakdown["score"],
                    "reasons": breakdown["reasons"],
                }
                for record, breakdown in selected_pairs
            ],
        },
        "problem_frame": {
            "Observed": [
                f"为当前 program 选出了 {len(selected)} 条文献证据。",
                "本轮检索优先参考 curated tags/topics 和 short summary，而不是直接展开全文。",
            ],
            "Inferred": [f"当前主导主题包括：{', '.join(dominant_topics) or 'uncategorized'}。"],
            "Suggested": ["先围绕主导主题生成初始 idea 变体，再决定是否扩到更边缘的方向。"],
            "OpenQuestions": ["最相关的新工作是否已经入库，还是应该触发 literature-scout 再补一轮？"],
        },
        "clusters": [
            {
                "cluster_id": f"{program_id}-cluster-{idx + 1}",
                "topic": topic,
                "literature_refs": [item["id"] for item in items[:6]],
                "Observed": [f"共有 {len(items)} 条入选文献提到主题 `{topic}`。"],
                "Inferred": ["这个簇很可能对应一个可复用的 baseline 家族。"],
                "Suggested": ["从这个簇中挑 1 篇代表性工作，与当前候选 idea 做正面对照。"],
                "OpenQuestions": [],
            }
            for idx, (topic, items) in enumerate(sorted(topic_buckets.items(), key=lambda item: (-len(item[1]), item[0])))
        ],
        "agreements": [
            {
                "Observed": [f"Many selected entries converge on `{topic}` as a recurring theme."]
                if topic
                else ["当前入选文献在主题上存在明显重叠。"],
                "Inferred": ["这个主题可以作为稳定的比较轴。"],
                "Suggested": ["优先围绕这个主题设计早期 ablation。"],
                "OpenQuestions": [],
            }
            for topic in dominant_topics[:2]
        ],
        "conflicts": [
            {
                "Observed": ["当前证据池混合了不同 source kind。"],
                "Inferred": ["论文、博客和项目页给出的实现线索可能并不完全一致。"],
                "Suggested": ["把实现关键 claim 先下沉到 `note.md`，人工核对后再上升为 program 结论。"],
                "OpenQuestions": [],
            }
        ],
        "gaps": [
            {
                "Observed": ["当前地图只基于本地已有的结构化条目构建。"],
                "Inferred": ["如果该方向进展很快，仍可能缺少新近 novelty 检查。"],
                "Suggested": ["一旦 idea-review-board 判定证据不足，就触发 literature-scout。"],
                "OpenQuestions": ["在最终选 idea 前，是否还需要补充更新的外部来源？"],
            }
        ],
        "candidate_directions": [
            {
                "title": f"围绕 {topic} 先走一条更轻量的实现路径",
                "Observed": [f"`{topic}` 在当前入选证据里重复出现。"],
                "Inferred": ["一个受约束的变体有机会基于现有 repo 快速验证。"],
                "Suggested": ["让 idea-forge 基于这个方向分叉出至少一个 proposal。"],
                "OpenQuestions": [],
            }
            for topic in dominant_topics[:3]
        ],
        "paper_refs": [item["id"] for item in selected],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a program-scoped literature map from the shared library.")
    parser.add_argument("--program-id", required=True)
    args = parser.parse_args()

    project_root = find_project_root()
    ensure_research_runtime(project_root, "literature-analyst")
    payload = build_map(args.program_id)
    program_root = research_root(project_root) / "programs" / args.program_id
    output_path = research_root(project_root) / "programs" / args.program_id / "evidence" / "literature-map.yaml"
    write_yaml_if_changed(output_path, payload)
    state_path = program_root / "workflow" / "state.yaml"
    state = load_yaml(state_path, default={})
    if isinstance(state, dict):
        state["generated_at"] = utc_now_iso()
        state["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root)), output_path.relative_to(project_root).as_posix()]
        if should_promote_stage(str(state.get("stage") or ""), "literature-analysis"):
            state["stage"] = "literature-analysis"
        write_yaml_if_changed(state_path, state)
    retrieval = payload.get("retrieval", {}) if isinstance(payload, dict) else {}
    selected_sources = retrieval.get("selected_sources", []) if isinstance(retrieval, dict) else []
    query_tags = retrieval.get("query_tags", []) if isinstance(retrieval, dict) else []
    query_tags = query_tags if isinstance(query_tags, list) else []
    source_ids = [
        str(item.get("source_id") or "").strip()
        for item in selected_sources
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    ]
    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "literature-analyst",
            "event_type": "literature-map-updated",
            "title": "文献证据地图已刷新",
            "summary": (
                f"为当前文献地图选出 {len(source_ids)} 个 canonical source"
                + (f"，重点覆盖 tags：{', '.join(str(tag) for tag in query_tags[:3])}。" if query_tags else "。")
            ),
            "artifacts": [
                output_path.relative_to(project_root).as_posix(),
                state_path.relative_to(project_root).as_posix(),
            ],
            "paper_ids": source_ids,
            "stage": "literature-analysis",
            "tags": [str(tag) for tag in query_tags if str(tag).strip()],
            "next_action": "如需补充新近证据，转 literature-scout；如需 proposal，转 idea-forge。",
        },
        generated_by="literature-analyst",
    )
    append_wiki_log_event(
        project_root,
        {
            "source_skill": "literature-analyst",
            "event_type": "reporting",
            "title": "Program 文献地图已生成",
            "summary": f"已为 program `{args.program_id}` 生成文献地图，纳入 {len(source_ids)} 条 source。",
            "program_id": args.program_id,
            "source_id": source_ids[0] if len(source_ids) == 1 else "",
            "source_ids": source_ids,
            "artifacts": [
                relative_path(project_root, output_path),
                relative_path(project_root, state_path),
            ],
            "query_tags": [str(tag) for tag in query_tags if str(tag).strip()],
        },
        generated_by="literature-analyst",
    )
    rebuild_wiki_index_markdown(project_root)
    print(f"[ok] wrote {output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

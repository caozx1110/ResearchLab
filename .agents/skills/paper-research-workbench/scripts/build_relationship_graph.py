#!/usr/bin/env python3
"""Build cross-paper relationship edges and a readable graph report."""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path
from typing import Any

from _paper_utils import (
    ensure_dir,
    find_project_root,
    load_yaml,
    text_tokens,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
)


def project_root_from_script() -> Path:
    return find_project_root(Path(__file__).resolve())


def load_metadata_records(papers_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if isinstance(payload, dict) and payload.get("paper_id"):
            records.append(payload)
    return records


def relation_score(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_topics = set(left.get("topics") or [])
    right_topics = set(right.get("topics") or [])
    shared_topics = sorted(left_topics & right_topics)

    left_tags = set(left.get("tags") or [])
    right_tags = set(right.get("tags") or [])
    shared_tags = sorted(left_tags & right_tags)

    left_authors = set(left.get("authors") or [])
    right_authors = set(right.get("authors") or [])
    shared_authors = sorted(left_authors & right_authors)

    left_tokens = set(text_tokens(str(left.get("title") or "")))
    right_tokens = set(text_tokens(str(right.get("title") or "")))
    shared_title_tokens = sorted(
        token
        for token in (left_tokens & right_tokens)
        if token not in {"model", "paper", "robot", "robots"}
    )

    score = 0.0
    relation_types: list[str] = []
    if shared_topics:
        score += 3.0 * len(shared_topics)
        relation_types.append("shared-topic")
    if shared_tags:
        score += 1.2 * min(len(shared_tags), 4)
        relation_types.append("shared-tag")
    if shared_authors:
        score += 0.5 * min(len(shared_authors), 6)
        relation_types.append("shared-author")
    if shared_title_tokens:
        score += 0.4 * min(len(shared_title_tokens), 4)
        relation_types.append("title-overlap")

    left_year = left.get("year")
    right_year = right.get("year")
    if isinstance(left_year, int) and isinstance(right_year, int):
        if abs(left_year - right_year) <= 1:
            score += 0.5
            relation_types.append("nearby-year")

    if score < 3.0:
        return None

    return {
        "source_paper_id": left.get("paper_id"),
        "target_paper_id": right.get("paper_id"),
        "score": round(score, 2),
        "relation_types": relation_types,
        "shared_topics": shared_topics,
        "shared_tags": shared_tags,
        "shared_authors": shared_authors,
        "shared_title_tokens": shared_title_tokens,
    }


def build_relationships(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for left, right in combinations(records, 2):
        edge = relation_score(left, right)
        if edge is not None:
            edges.append(edge)
    edges.sort(
        key=lambda edge: (
            -float(edge["score"]),
            str(edge["source_paper_id"]),
            str(edge["target_paper_id"]),
        )
    )
    return edges


def short_label(record: dict[str, Any], max_len: int = 38) -> str:
    title = str(record.get("title") or record.get("paper_id") or "")
    if len(title) <= max_len:
        return title
    return title[: max_len - 3].rstrip() + "..."


def render_mermaid(records: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    lookup = {str(record["paper_id"]): record for record in records}
    lines = ["```mermaid", "graph TD"]
    for record in records:
        paper_id = str(record["paper_id"])
        node_id = paper_id.replace("-", "_")
        label = short_label(record).replace('"', "'")
        lines.append(f'    {node_id}["{label}"]')
    for edge in edges[:24]:
        source = str(edge["source_paper_id"]).replace("-", "_")
        target = str(edge["target_paper_id"]).replace("-", "_")
        lines.append(f'    {source} ---|{edge["score"]}| {target}')
    lines.append("```")
    return "\n".join(lines)


def render_edge_lines(edges: list[dict[str, Any]]) -> str:
    if not edges:
        return "- 目前还没有高置信的跨论文关系边。"
    lines: list[str] = []
    for edge in edges:
        rationale_parts: list[str] = []
        if edge["shared_topics"]:
            rationale_parts.append("共同主题=" + ", ".join(edge["shared_topics"]))
        if edge["shared_tags"]:
            rationale_parts.append("共同标签=" + ", ".join(edge["shared_tags"]))
        if edge["shared_authors"]:
            rationale_parts.append("共同作者=" + ", ".join(edge["shared_authors"][:4]))
        lines.append(
            f"- `{edge['source_paper_id']}` <-> `{edge['target_paper_id']}`"
            f" | 关系分数={edge['score']}"
            f" | {'; '.join(rationale_parts)}"
        )
    return "\n".join(lines)


def write_graph_report(
    *,
    records: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    output_path: Path,
) -> None:
    topic_counts: dict[str, int] = {}
    for record in records:
        for topic in record.get("topics") or []:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    top_topics = sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))

    lines = [
        "# 论文关系图",
        "",
        f"- 生成时间：{utc_now_iso()}",
        f"- 论文数量：{len(records)}",
        f"- 关系边数量：{len(edges)}",
        "",
        "## 高频主题",
        "",
    ]
    if top_topics:
        lines.extend([f"- {topic}: {count}" for topic, count in top_topics[:10]])
    else:
        lines.append("- 还没有可用主题。")

    lines.extend(
        [
            "",
            "## 图谱",
            "",
            render_mermaid(records, edges),
            "",
            "## 关系解释",
            "",
            render_edge_lines(edges[:40]),
            "",
        ]
    )
    write_text_if_changed(output_path, "\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build cross-paper relationships and graph outputs.",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Paper metadata root (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--index-root",
        default="doc/papers/index",
        help="Index output root (default: doc/papers/index)",
    )
    parser.add_argument(
        "--graph-root",
        default="doc/papers/user/graph",
        help="Human-readable graph output root (default: doc/papers/user/graph)",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    papers_root = (project_root / args.papers_root).resolve()
    index_root = (project_root / args.index_root).resolve()
    graph_root = (project_root / args.graph_root).resolve()
    ensure_dir(index_root)
    ensure_dir(graph_root)

    records = load_metadata_records(papers_root)
    if not records:
        raise SystemExit(f"No metadata files found under: {papers_root}")

    edges = build_relationships(records)
    payload = {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "paper_count": len(records),
        "edge_count": len(edges),
        "edges": edges,
    }
    write_yaml_if_changed(index_root / "relationships.yaml", payload)
    write_graph_report(records=records, edges=edges, output_path=graph_root / "paper-relationships.md")
    print(f"[OK] relationships built: edges={len(edges)}")


if __name__ == "__main__":
    main()

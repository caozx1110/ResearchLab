#!/usr/bin/env python3
"""Build AI-friendly paper knowledge base files."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from _paper_utils import (
    ensure_dir,
    find_project_root,
    load_yaml,
    relative_to_project,
    utc_now_iso,
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


def build_neighbor_map(relationships: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    neighbor_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in relationships.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_paper_id") or "")
        target = str(edge.get("target_paper_id") or "")
        if not source or not target:
            continue
        payload = {
            "paper_id": target,
            "score": edge.get("score"),
            "relation_types": edge.get("relation_types") or [],
            "shared_topics": edge.get("shared_topics") or [],
            "shared_tags": edge.get("shared_tags") or [],
            "shared_authors": edge.get("shared_authors") or [],
        }
        neighbor_map[source].append(payload)
        reverse_payload = dict(payload)
        reverse_payload["paper_id"] = source
        neighbor_map[target].append(reverse_payload)

    for neighbors in neighbor_map.values():
        neighbors.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("paper_id"))))
    return dict(neighbor_map)


def write_paper_kb_files(
    *,
    records: list[dict[str, Any]],
    neighbor_map: dict[str, list[dict[str, Any]]],
    kb_root: Path,
    project_root: Path,
    user_root: Path,
) -> list[dict[str, Any]]:
    papers_root = kb_root / "papers"
    ensure_dir(papers_root)
    summaries: list[dict[str, Any]] = []

    for record in records:
        paper_id = str(record.get("paper_id") or "")
        if not paper_id:
            continue
        paper_dir = papers_root / paper_id
        ensure_dir(paper_dir)
        workspace_paper_dir = project_root / "doc" / "papers" / "papers" / paper_id
        user_paper_dir = user_root / "papers" / paper_id
        kb_payload = {
            "schema_version": 1,
            "paper_id": paper_id,
            "title": record.get("title"),
            "year": record.get("year"),
            "arxiv_id": record.get("arxiv_id"),
            "doi": record.get("doi"),
            "authors": record.get("authors") or [],
            "tags": record.get("tags") or [],
            "topics": record.get("topics") or [],
            "abstract": record.get("abstract"),
            "source_pdf": (record.get("source") or {}).get("pdf"),
            "identity_key": (record.get("ingest") or {}).get("identity_key"),
            "neighbors": neighbor_map.get(paper_id, [])[:12],
            "artifact_paths": {
                "metadata": relative_to_project(workspace_paper_dir / "metadata.yaml", project_root),
                "note": relative_to_project(user_paper_dir / "note.md", project_root),
                "ideas": relative_to_project(user_paper_dir / "ideas.md", project_root),
                "feasibility": relative_to_project(user_paper_dir / "feasibility.md", project_root),
                "text": relative_to_project(workspace_paper_dir / "_artifacts" / "text.md", project_root),
                "sections": relative_to_project(workspace_paper_dir / "_artifacts" / "sections.json", project_root),
            },
            "knowledge_surfaces": {
                "human_hub": "doc/papers/user/index.html",
                "human_graph": "doc/papers/user/graph.html",
                "topic_maps": "doc/papers/user/topic-maps/",
                "human_frontier_ideas": "doc/papers/user/syntheses/frontier-ideas.md",
                "ai_graph": "doc/papers/ai/graph.yaml",
                "ai_corpus": "doc/papers/ai/corpus.yaml",
                "ai_frontier_ideas": "doc/papers/ai/frontier-ideas.yaml",
            },
        }
        write_yaml_if_changed(paper_dir / "node.yaml", kb_payload)
        summaries.append(
            {
                "paper_id": paper_id,
                "title": record.get("title"),
                "topics": record.get("topics") or [],
                "tags": record.get("tags") or [],
                "neighbor_count": len(neighbor_map.get(paper_id, [])),
                "node_path": relative_to_project(paper_dir / "node.yaml", project_root),
            }
        )
    return summaries


def build_cluster_index(records: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    bucket: dict[str, list[str]] = defaultdict(list)
    for record in records:
        paper_id = str(record.get("paper_id") or "")
        for value in record.get(key_name) or []:
            if isinstance(value, str) and paper_id:
                bucket[value].append(paper_id)
    items = []
    for value in sorted(bucket):
        paper_ids = sorted(set(bucket[value]))
        items.append({"name": value, "count": len(paper_ids), "paper_ids": paper_ids})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build AI-friendly paper knowledge base files.",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Paper metadata root (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--relationships-path",
        default="doc/papers/index/relationships.yaml",
        help="Relationship index path (default: doc/papers/index/relationships.yaml)",
    )
    parser.add_argument(
        "--kb-root",
        default="doc/papers/ai",
        help="Knowledge base output root (default: doc/papers/ai)",
    )
    parser.add_argument(
        "--user-root",
        default="doc/papers/user",
        help="User-readable output root (default: doc/papers/user)",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    papers_root = (project_root / args.papers_root).resolve()
    relationships_path = (project_root / args.relationships_path).resolve()
    kb_root = (project_root / args.kb_root).resolve()
    user_root = (project_root / args.user_root).resolve()
    ensure_dir(kb_root)

    records = load_metadata_records(papers_root)
    if not records:
        raise SystemExit(f"No metadata files found under: {papers_root}")
    relationships = load_yaml(relationships_path)
    if not isinstance(relationships, dict):
        raise SystemExit(f"Invalid or missing relationship index: {relationships_path}")

    neighbor_map = build_neighbor_map(relationships)
    paper_summaries = write_paper_kb_files(
        records=records,
        neighbor_map=neighbor_map,
        kb_root=kb_root,
        project_root=project_root,
        user_root=user_root,
    )
    graph_payload = {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "paper_count": len(records),
        "edge_count": relationships.get("edge_count"),
        "neighbors": neighbor_map,
    }
    write_yaml_if_changed(kb_root / "graph.yaml", graph_payload)
    corpus_payload = {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "paper_count": len(records),
        "knowledge_surfaces": {
            "human_hub": "doc/papers/user/index.html",
            "human_graph": "doc/papers/user/graph.html",
            "human_frontier_ideas": "doc/papers/user/syntheses/frontier-ideas.md",
            "ai_graph": "doc/papers/ai/graph.yaml",
            "ai_frontier_ideas": "doc/papers/ai/frontier-ideas.yaml",
        },
        "topic_clusters": build_cluster_index(records, "topics"),
        "tag_clusters": build_cluster_index(records, "tags"),
        "papers": paper_summaries,
    }
    write_yaml_if_changed(kb_root / "corpus.yaml", corpus_payload)
    print(f"[OK] AI KB built: papers={len(records)}")


if __name__ == "__main__":
    main()

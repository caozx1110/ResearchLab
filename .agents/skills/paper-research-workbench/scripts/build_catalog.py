#!/usr/bin/env python3
"""Build index files from parsed paper metadata."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from _paper_utils import ensure_dir, find_project_root, load_yaml, utc_now_iso, write_yaml_if_changed


def project_root_from_script() -> Path:
    return find_project_root(Path(__file__).resolve())


def load_metadata_records(papers_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if not isinstance(payload, dict):
            continue
        payload["_metadata_path"] = str(metadata_path)
        records.append(payload)
    return records


def sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(record: dict[str, Any]) -> tuple[int, str]:
        year = record.get("year")
        year_value = int(year) if isinstance(year, int) else -1
        paper_id = str(record.get("paper_id", ""))
        return (-year_value, paper_id)

    return sorted(records, key=key)


def build_papers_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    papers: list[dict[str, Any]] = []
    for record in sort_records(records):
        source = record.get("source") or {}
        ingest = record.get("ingest") or {}
        papers.append(
            {
                "paper_id": record.get("paper_id"),
                "title": record.get("title"),
                "year": record.get("year"),
                "arxiv_id": record.get("arxiv_id"),
                "tags": record.get("tags") or [],
                "topics": record.get("topics") or [],
                "source_pdf": source.get("pdf"),
                "source_aliases": source.get("aliases") or [],
                "parsed_at": source.get("parsed_at"),
                "last_status": ingest.get("last_status"),
                "identity_key": ingest.get("identity_key"),
            }
        )
    return {
        "schema_version": 2,
        "generated_at": utc_now_iso(),
        "paper_count": len(papers),
        "papers": papers,
    }


def build_map_index(
    *,
    records: list[dict[str, Any]],
    key_name: str,
    item_key: str,
) -> dict[str, Any]:
    bucket: dict[str, set[str]] = defaultdict(set)
    for record in records:
        paper_id = record.get("paper_id")
        values = record.get(key_name) or []
        if not paper_id or not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if normalized:
                bucket[normalized].add(str(paper_id))

    items = []
    for value in sorted(bucket):
        paper_ids = sorted(bucket[value])
        items.append(
            {
                item_key: value,
                "count": len(paper_ids),
                "paper_ids": paper_ids,
            }
        )
    return {
        "schema_version": 2,
        "generated_at": utc_now_iso(),
        "count": len(items),
        f"{item_key}s": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build paper catalog index files under doc/papers/index.",
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
    args = parser.parse_args()

    project_root = project_root_from_script()
    papers_root = (project_root / args.papers_root).resolve()
    index_root = (project_root / args.index_root).resolve()
    ensure_dir(index_root)

    records = load_metadata_records(papers_root)
    if not records:
        raise SystemExit(f"No metadata files found under: {papers_root}")

    papers_index = build_papers_index(records)
    tags_index = build_map_index(records=records, key_name="tags", item_key="tag")
    topics_index = build_map_index(records=records, key_name="topics", item_key="topic")

    write_yaml_if_changed(index_root / "papers.yaml", papers_index)
    write_yaml_if_changed(index_root / "tags.yaml", tags_index)
    write_yaml_if_changed(index_root / "topics.yaml", topics_index)

    print(
        "[OK] Built index files:",
        f"papers={papers_index['paper_count']}",
        f"tags={tags_index['count']}",
        f"topics={topics_index['count']}",
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate topic map markdown files from paper metadata and topic index."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _paper_utils import ensure_dir, load_yaml, slugify, utc_now_iso, write_text_if_changed


def project_root_from_script() -> Path:
    # <project>/skills/paper-research-workbench/scripts/refresh_topic_maps.py
    return Path(__file__).resolve().parents[3]


def render(template: str, context: dict[str, str]) -> str:
    output = template
    for key, value in context.items():
        output = output.replace(f"{{{{{key}}}}}", value)
    return output


def load_paper_lookup(papers_root: Path) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if isinstance(payload, dict) and payload.get("paper_id"):
            lookup[str(payload["paper_id"])] = payload
    return lookup


def abstract_brief(text: str | None, max_len: int = 180) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def build_paper_list(
    *,
    paper_ids: list[str],
    lookup: dict[str, dict[str, Any]],
) -> str:
    rows: list[str] = []
    items = [lookup[paper_id] for paper_id in paper_ids if paper_id in lookup]
    items.sort(key=lambda item: (item.get("year") or 0, item.get("paper_id") or ""), reverse=True)
    for item in items:
        paper_id = str(item.get("paper_id", ""))
        title = str(item.get("title", "Untitled"))
        year = item.get("year") or "n/a"
        tags = ", ".join(item.get("tags") or [])
        brief = abstract_brief(item.get("abstract"))
        row = f"- **{title}** ({year}) | id: `{paper_id}` | tags: {tags}"
        if brief:
            row += f" | 摘要摘录：{brief}"
        rows.append(row)
    if not rows:
        return "- 该主题下暂时还没有论文。"
    return "\n".join(rows)


def write_topic_files(
    *,
    topics_payload: dict[str, Any],
    paper_lookup: dict[str, dict[str, Any]],
    output_root: Path,
    template: str,
) -> None:
    topics = topics_payload.get("topics") or []
    index_lines = [
        "# 主题图谱总览",
        "",
        f"- 生成时间：{utc_now_iso()}",
        "",
    ]
    for entry in topics:
        topic = str(entry.get("topic", "")).strip()
        if not topic:
            continue
        paper_ids = entry.get("paper_ids") or []
        if not isinstance(paper_ids, list):
            continue
        paper_list = build_paper_list(paper_ids=paper_ids, lookup=paper_lookup)
        out_name = f"{slugify(topic, max_words=8)}.md"
        out_path = output_root / out_name
        context = {
            "TOPIC": topic,
            "GENERATED_AT": utc_now_iso(),
            "PAPER_COUNT": str(len(paper_ids)),
            "PAPER_LIST": paper_list,
        }
        write_text_if_changed(out_path, render(template, context))
        index_lines.append(f"- [{topic}]({out_name})（{len(paper_ids)} 篇）")

    write_text_if_changed(output_root / "index.md", "\n".join(index_lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh doc/papers/topic-maps from topics index.",
    )
    parser.add_argument(
        "--topics-index",
        default="doc/papers/index/topics.yaml",
        help="Topics index path (default: doc/papers/index/topics.yaml)",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Paper root path (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--output-root",
        default="doc/papers/user/topic-maps",
        help="Topic map output root (default: doc/papers/user/topic-maps)",
    )
    parser.add_argument(
        "--template",
        default="skills/paper-research-workbench/assets/templates/topic-map-template.md",
        help="Topic map template file",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    topics_index = (project_root / args.topics_index).resolve()
    papers_root = (project_root / args.papers_root).resolve()
    output_root = (project_root / args.output_root).resolve()
    template_path = (project_root / args.template).resolve()
    ensure_dir(output_root)

    topics_payload = load_yaml(topics_index)
    if not isinstance(topics_payload, dict):
        raise SystemExit(f"Invalid or missing topics index: {topics_index}")
    paper_lookup = load_paper_lookup(papers_root)
    template = template_path.read_text(encoding="utf-8")

    write_topic_files(
        topics_payload=topics_payload,
        paper_lookup=paper_lookup,
        output_root=output_root,
        template=template,
    )
    print("[OK] topic maps refreshed")


if __name__ == "__main__":
    main()

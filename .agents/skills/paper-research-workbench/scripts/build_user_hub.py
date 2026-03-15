#!/usr/bin/env python3
"""Build a local HTML hub for human-readable paper workspace outputs."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from _paper_utils import (
    compact_text,
    ensure_dir,
    find_project_root,
    find_skill_root,
    load_yaml,
    relative_to_project,
    resolve_from_project_or_skill,
    slugify,
    utc_now_iso,
    write_json_if_changed,
    write_text_if_changed,
)


def project_root_from_script() -> Path:
    return find_project_root(Path(__file__).resolve())


def skill_root_from_script() -> Path:
    return find_skill_root(Path(__file__).resolve())


def load_metadata_records(papers_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if isinstance(payload, dict) and payload.get("paper_id"):
            records.append(payload)
    records.sort(key=lambda item: (item.get("year") or 0, item.get("paper_id") or ""), reverse=True)
    return records


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[1]
    return text


def markdown_preview(path: Path, max_lines: int = 4) -> str:
    if not path.exists():
        return ""
    text = strip_frontmatter(path.read_text(encoding="utf-8"))
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        return ""
    return compact_text(" ".join(lines[:max_lines]), max_len=220)


def relative_path(from_dir: Path, target: Path) -> str:
    return os.path.relpath(target, start=from_dir)


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
            "score": float(edge.get("score") or 0.0),
            "shared_topics": edge.get("shared_topics") or [],
            "shared_tags": edge.get("shared_tags") or [],
        }
        reverse = dict(payload)
        reverse["paper_id"] = source
        neighbor_map[source].append(payload)
        neighbor_map[target].append(reverse)
    for values in neighbor_map.values():
        values.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("paper_id") or "")))
    return dict(neighbor_map)


def build_payload(
    *,
    project_root: Path,
    papers_root: Path,
    user_root: Path,
    ai_root: Path,
    relationships_path: Path,
    topics_index_path: Path,
    frontier_ideas_path: Path,
) -> dict[str, Any]:
    records = load_metadata_records(papers_root)
    relationships = load_yaml(relationships_path) or {}
    topics_index = load_yaml(topics_index_path) or {}
    frontier_ideas = load_yaml(frontier_ideas_path) or {}
    neighbor_map = build_neighbor_map(relationships if isinstance(relationships, dict) else {})
    title_lookup = {
        str(record.get("paper_id") or ""): str(record.get("title") or record.get("paper_id") or "")
        for record in records
    }

    papers: list[dict[str, Any]] = []
    for record in records:
        paper_id = str(record.get("paper_id") or "")
        if not paper_id:
            continue
        user_paper_dir = user_root / "papers" / paper_id
        note_path = user_paper_dir / "note.md"
        ideas_path = user_paper_dir / "ideas.md"
        feasibility_path = user_paper_dir / "feasibility.md"
        papers.append(
            {
                "paper_id": paper_id,
                "title": str(record.get("title") or paper_id),
                "year": record.get("year"),
                "authors": record.get("authors") or [],
                "tags": record.get("tags") or [],
                "topics": record.get("topics") or [],
                "abstract": record.get("abstract") or "",
                "abstract_brief": compact_text(str(record.get("abstract") or ""), max_len=220),
                "arxiv_id": record.get("arxiv_id"),
                "doi": record.get("doi"),
                "source_pdf": record.get("source", {}).get("pdf") if isinstance(record.get("source"), dict) else None,
                "source_pdf_link": relative_path(user_root, project_root / str((record.get("source") or {}).get("pdf") or "")) if (record.get("source") or {}).get("pdf") else "",
                "metadata_path": relative_to_project(papers_root / paper_id / "metadata.yaml", project_root),
                "note_path": relative_path(user_root, note_path),
                "ideas_path": relative_path(user_root, ideas_path),
                "feasibility_path": relative_path(user_root, feasibility_path),
                "ai_node_path": relative_path(user_root, ai_root / "papers" / paper_id / "node.yaml"),
                "note_preview": markdown_preview(note_path),
                "idea_preview": markdown_preview(ideas_path),
                "feasibility_preview": markdown_preview(feasibility_path),
                "neighbors": [
                    {
                        "paper_id": str(item.get("paper_id") or ""),
                        "title": title_lookup.get(str(item.get("paper_id") or ""), str(item.get("paper_id") or "")),
                        "score": item.get("score"),
                        "shared_topics": item.get("shared_topics") or [],
                        "shared_tags": item.get("shared_tags") or [],
                    }
                    for item in neighbor_map.get(paper_id, [])[:6]
                ],
            }
        )

    payload = {
        "generated_at": utc_now_iso(),
        "paper_count": len(papers),
        "edge_count": int((relationships or {}).get("edge_count") or len((relationships or {}).get("edges") or [])),
        "topic_count": int((topics_index or {}).get("count") or len((topics_index or {}).get("topics") or [])),
        "idea_count": len((frontier_ideas or {}).get("ideas") or []),
        "papers": papers,
        "edges": (relationships or {}).get("edges") or [],
        "topics": [
            {
                **topic,
                "file_name": f"{slugify(str(topic.get('topic') or ''), max_words=8)}.md",
            }
            for topic in ((topics_index or {}).get("topics") or [])
            if isinstance(topic, dict)
        ],
        "frontier_ideas": (frontier_ideas or {}).get("ideas") or [],
    }
    return payload


def render_html_from_assets(
    payload: dict[str, Any],
    *,
    default_tab: str,
    template_path: Path,
    css_path: Path,
    js_path: Path,
    page_title: str,
) -> str:
    template = template_path.read_text(encoding="utf-8")
    css_text = css_path.read_text(encoding="utf-8")
    js_text = js_path.read_text(encoding="utf-8")
    data_json = json.dumps(payload, ensure_ascii=False)
    data_json = data_json.replace("</", "<\\/")
    data_json = data_json.replace("<!--", "<\\!--")
    context = {
        "PAGE_TITLE": page_title,
        "DEFAULT_TAB": default_tab,
        "INLINE_CSS": css_text,
        "INLINE_JS": js_text,
        "DATA_JSON": data_json,
    }
    output = template
    for key, value in context.items():
        output = output.replace(f"{{{{{key}}}}}", value)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a self-contained local HTML hub for user-readable paper outputs.",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Internal paper data root (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--user-root",
        default="doc/papers/user",
        help="User-readable output root (default: doc/papers/user)",
    )
    parser.add_argument(
        "--ai-root",
        default="doc/papers/ai",
        help="AI-readable output root (default: doc/papers/ai)",
    )
    parser.add_argument(
        "--relationships-path",
        default="doc/papers/index/relationships.yaml",
        help="Relationship index path",
    )
    parser.add_argument(
        "--topics-index",
        default="doc/papers/index/topics.yaml",
        help="Topics index path",
    )
    parser.add_argument(
        "--frontier-ideas-path",
        default="doc/papers/ai/frontier-ideas.yaml",
        help="Structured frontier ideas path",
    )
    parser.add_argument(
        "--ui-template",
        default="assets/ui/hub-template.html",
        help="UI HTML template path (default: assets/ui/hub-template.html)",
    )
    parser.add_argument(
        "--ui-css",
        default="assets/ui/hub.css",
        help="UI CSS path (default: assets/ui/hub.css)",
    )
    parser.add_argument(
        "--ui-js",
        default="assets/ui/hub.js",
        help="UI JS path (default: assets/ui/hub.js)",
    )
    parser.add_argument(
        "--page-title",
        default="Paper Research Hub",
        help="Page title for generated HTML",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    skill_root = skill_root_from_script()
    papers_root = (project_root / args.papers_root).resolve()
    user_root = (project_root / args.user_root).resolve()
    ai_root = (project_root / args.ai_root).resolve()
    relationships_path = (project_root / args.relationships_path).resolve()
    topics_index_path = (project_root / args.topics_index).resolve()
    frontier_ideas_path = (project_root / args.frontier_ideas_path).resolve()
    ui_template_path = resolve_from_project_or_skill(
        args.ui_template,
        project_root=project_root,
        skill_root=skill_root,
    ).resolve()
    ui_css_path = resolve_from_project_or_skill(
        args.ui_css,
        project_root=project_root,
        skill_root=skill_root,
    ).resolve()
    ui_js_path = resolve_from_project_or_skill(
        args.ui_js,
        project_root=project_root,
        skill_root=skill_root,
    ).resolve()

    required_ui = {
        "ui-template": ui_template_path,
        "ui-css": ui_css_path,
        "ui-js": ui_js_path,
    }
    for label, path in required_ui.items():
        if not path.exists():
            raise SystemExit(f"Missing {label} file: {path}")

    ensure_dir(user_root)
    ensure_dir(user_root / "data")

    payload = build_payload(
        project_root=project_root,
        papers_root=papers_root,
        user_root=user_root,
        ai_root=ai_root,
        relationships_path=relationships_path,
        topics_index_path=topics_index_path,
        frontier_ideas_path=frontier_ideas_path,
    )

    write_json_if_changed(user_root / "data" / "hub.json", payload)
    write_json_if_changed(user_root / "data" / "papers.json", {"papers": payload["papers"]})
    write_json_if_changed(user_root / "data" / "graph.json", {"edges": payload["edges"]})
    write_json_if_changed(user_root / "data" / "frontier-ideas.json", {"ideas": payload["frontier_ideas"]})
    write_json_if_changed(user_root / "data" / "topics.json", {"topics": payload["topics"]})
    write_text_if_changed(
        user_root / "index.html",
        render_html_from_assets(
            payload,
            default_tab="overview",
            template_path=ui_template_path,
            css_path=ui_css_path,
            js_path=ui_js_path,
            page_title=args.page_title,
        ),
    )
    write_text_if_changed(
        user_root / "graph.html",
        render_html_from_assets(
            payload,
            default_tab="graph",
            template_path=ui_template_path,
            css_path=ui_css_path,
            js_path=ui_js_path,
            page_title=args.page_title,
        ),
    )
    print(f"[OK] user hub built: papers={payload['paper_count']}")


if __name__ == "__main__":
    main()

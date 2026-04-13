#!/usr/bin/env python3
"""Record literature search results for later ingestion."""

from __future__ import annotations

import argparse
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
    bootstrap_workspace,
    canonicalize_url,
    ensure_research_runtime,
    find_project_root,
    research_root,
    utc_now_iso,
    write_yaml_if_changed,
    yaml_default,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a literature search result set.")
    parser.add_argument("--search-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--program-id", default="")
    parser.add_argument("--candidate-url", action="append", default=[])
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "literature-scout")
    output_path = research_root(project_root) / "library" / "search" / "results" / f"{args.search_id}.yaml"
    candidate_urls = [canonicalize_url(url) for url in args.candidate_url]
    payload = {
        **yaml_default(args.search_id, "literature-scout", status="captured", confidence=0.55),
        "inputs": ([f"program:{args.program_id}"] if args.program_id else []) + candidate_urls,
        "query": args.query,
        "program_id": args.program_id,
        "note": args.note,
        "candidates": [
            {
                "candidate_id": f"{args.search_id}-{idx + 1}",
                "url": url,
                "status": "shortlisted",
            }
            for idx, url in enumerate(candidate_urls)
        ],
    }
    write_yaml_if_changed(output_path, payload)
    append_wiki_log_event(
        project_root,
        {
            "source_skill": "literature-scout",
            "event_type": "query",
            "title": "Literature search results captured",
            "summary": f"Captured query `{args.query}` with {len(candidate_urls)} candidate URL(s).",
            "program_id": str(args.program_id or "").strip(),
            "search_id": args.search_id,
            "artifacts": [relative_path(project_root, output_path)],
            "query": args.query,
        },
        generated_by="literature-scout",
    )
    rebuild_wiki_index_markdown(project_root)
    print(f"[ok] wrote {output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

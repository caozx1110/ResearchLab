#!/usr/bin/env python3
"""Record literature search results for later ingestion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

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
    print(f"[ok] wrote {output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    raise SystemExit("Could not locate the managed research runtime.")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument
from research.core import project_root
from research.openalex import DEFAULT_PER_PAGE, MAX_PER_PAGE, OpenAlexClient, OpenAlexError
from research.sources import stage_search_results


def pull_and_stage(
    root: Path,
    *,
    query: str,
    limit: int = DEFAULT_PER_PAGE,
    stage_id: str = "",
    note: str = "",
    include_retracted: bool = False,
    client: OpenAlexClient | None = None,
) -> tuple[Path, list[dict]]:
    candidates = (client or OpenAlexClient()).search_works(
        query,
        per_page=limit,
        include_retracted=include_retracted,
    )
    path = stage_search_results(
        root,
        kind="paper",
        query=query,
        candidates=candidates,
        stage_id=stage_id,
        note=note,
    )
    return path, candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage one bounded page of OpenAlex paper candidates.")
    add_project_root_argument(parser)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_PER_PAGE, choices=range(1, MAX_PER_PAGE + 1))
    parser.add_argument("--stage-id", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--include-retracted", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    try:
        _, candidates = pull_and_stage(
            root,
            query=args.query,
            limit=args.limit,
            stage_id=args.stage_id,
            note=args.note,
            include_retracted=args.include_retracted,
        )
    except OpenAlexError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"找到 {len(candidates)} 个候选，已暂存；下一步将由 Agent 去重并阅读。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    raise SystemExit("Could not locate .agents/lib")

from research.common import ensure_dir, write_text_if_changed
from research.v2 import build_index, lint_records, project_root, search_records, synthesis_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Thin wiki adapter for v2.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    query = subparsers.add_parser("query")
    query.add_argument("--question", required=True)
    add = subparsers.add_parser("add")
    add.add_argument("--kind", required=True, choices=["paper", "repo", "blog"])
    add.add_argument("--source", required=True)
    subparsers.add_parser("lint")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    if args.command == "lint":
        status, issues = lint_records(root)
        print(f"status: {status}")
        for issue in issues:
            print(f"- {issue}")
        return 0 if status == "PASS" else 1
    if args.command == "add":
        if args.kind == "paper":
            print("route: source-intake -> paper-analyst")
        elif args.kind == "repo":
            print("route: source-intake -> repo-analyst")
        else:
            print("route: source-intake -> blog-analyst")
        print(f"source: {args.source}")
        return 0
    results = search_records(root, args.question)
    out_root = synthesis_root(root) / "wiki"
    ensure_dir(out_root)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in args.question).strip("-")[:64] or "query"
    path = out_root / f"{slug}.md"
    lines = [f"# Wiki Query: {args.question}", "", "## Results", ""]
    for item in results[:20]:
        lines.append(f"- `{item['id']}` · {item['kind']} · {item['title']} · {item.get('summary', '')}")
    if len(lines) == 4:
        lines.append("- 暂无匹配结果")
    write_text_if_changed(path, "\n".join(lines).strip() + "\n")
    build_index(root)
    print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

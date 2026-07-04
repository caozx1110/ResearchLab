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

from research.common import write_text_if_changed
from research.v2 import iter_records, project_root, user_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh v2 user-facing navigation pages.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("refresh")
    subparsers.add_parser("current-state")
    subparsers.add_parser("reading-list")
    return parser


def render_current(records: list[dict]) -> str:
    lines = ["# Current State", "", "## Confirmed Highlights", ""]
    confirmed = [item for item in records if item.get("confirmation_status") == "confirmed"]
    for item in confirmed[:12]:
        lines.append(f"- `{item['id']}` · {item['kind']} · {item['title']} · {item.get('summary', '')}")
    if len(lines) == 4:
        lines.append("- 暂无已确认条目")
    return "\n".join(lines).strip() + "\n"


def render_navigation(records: list[dict]) -> str:
    lines = ["# Research Navigation", "", "## 快速入口", "", "- `kb/index.md`", "- `kb/user/current-state.md`", "- `kb/user/reading-lists/current-reading.md`", ""]
    lines.append("## 待读 / 待确认")
    lines.append("")
    for item in [item for item in records if item.get("confirmation_status") != "confirmed"][:12]:
        lines.append(f"- `{item['id']}` · {item['kind']} · {item['title']} · confirm={item.get('confirmation_status')}")
    if lines[-1] == "":
        lines.append("- 暂无")
    return "\n".join(lines).strip() + "\n"


def render_reading_list(records: list[dict]) -> str:
    papers = [item for item in records if item.get("kind") == "paper"]
    blogs = [item for item in records if item.get("kind") == "blog"]
    lines = ["# Current Reading", "", "## Papers", ""]
    for item in papers[:12]:
        lines.append(f"- `{item['id']}` · {item['title']} · confirm={item.get('confirmation_status')}")
    if len(lines) == 4:
        lines.append("- 暂无")
    lines.extend(["", "## Blogs", ""])
    start = len(lines)
    for item in blogs[:12]:
        lines.append(f"- `{item['id']}` · {item['title']} · confirm={item.get('confirmation_status')}")
    if len(lines) == start:
        lines.append("- 暂无")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    records = iter_records(root)
    current_path = user_root(root) / "current-state.md"
    nav_path = user_root(root) / "navigation.md"
    reading_path = user_root(root) / "reading-lists" / "current-reading.md"

    if args.command in {"refresh", "current-state"}:
        write_text_if_changed(current_path, render_current(records))
    if args.command == "refresh":
        write_text_if_changed(nav_path, render_navigation(records))
        write_text_if_changed(reading_path, render_reading_list(records))
        print(current_path.relative_to(root))
        print(nav_path.relative_to(root))
        print(reading_path.relative_to(root))
        return 0
    if args.command == "current-state":
        print(current_path.relative_to(root))
        return 0
    write_text_if_changed(reading_path, render_reading_list(records))
    print(reading_path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

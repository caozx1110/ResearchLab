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

from research.common import append_program_reporting_event, ensure_dir, write_text_if_changed
from research.v2 import project_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive a program discussion note.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    archive = subparsers.add_parser("archive")
    archive.add_argument("--program-id", required=True)
    archive.add_argument("--title", required=True)
    archive.add_argument("--summary", required=True)
    archive.add_argument("--decision", default="")
    archive.add_argument("--tradeoff", action="append", default=[])
    archive.add_argument("--open-question", action="append", default=[])
    archive.add_argument("--next-action", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    out_root = root / "kb" / "programs" / args.program_id / "discussions"
    ensure_dir(out_root)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in args.title).strip("-")[:64] or "discussion"
    path = out_root / f"{slug}.md"
    lines = [
        f"# {args.title}",
        "",
        "## Summary",
        "",
        args.summary,
        "",
        "## Current Conclusion",
        "",
        args.decision or "待确认",
        "",
        "## Tradeoffs",
        "",
        *[f"- {item}" for item in (args.tradeoff or ["待补充"])],
        "",
        "## Open Questions",
        "",
        *[f"- {item}" for item in (args.open_question or ["暂无"])],
        "",
        "## Next Actions",
        "",
        *[f"- {item}" for item in (args.next_action or ["暂无"])],
        "",
    ]
    write_text_if_changed(path, "\n".join(lines))
    append_program_reporting_event(
        root,
        args.program_id,
        {
            "source_skill": "discussion-archivist",
            "event_type": "discussion-archived",
            "title": args.title,
            "summary": args.summary,
            "stage": "discussion",
            "artifacts": [path.relative_to(root).as_posix()],
            "tags": ["discussion"],
        },
        generated_by="discussion-archivist",
    )
    print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

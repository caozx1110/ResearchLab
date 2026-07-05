#!/usr/bin/env python3
"""Capture, recall, promote, and review lightweight v2 learnings."""

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

from research.common import add_project_root_argument, print_resolved_project_roots
from research.learnings import (
    CATEGORIES,
    RECALL_KINDS,
    REVIEW_STATUSES,
    SOURCES,
    load_learnings,
    log_learning,
    promote_learning,
    render_recall_digest,
    review_learning,
)
from research.v2 import project_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    log_parser = subparsers.add_parser("log", help="Capture a lightweight learning.")
    log_parser.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    log_parser.add_argument("--text", required=True)
    log_parser.add_argument("--source", choices=sorted(SOURCES), default="agent")
    log_parser.add_argument("--skill", default="")
    log_parser.add_argument("--context", default="")

    recall_parser = subparsers.add_parser("recall", help="Print confirmed habits/gotchas or pending defects.")
    recall_parser.add_argument("--kind", choices=sorted(RECALL_KINDS), default="all")
    recall_parser.add_argument("--limit", type=int, default=5)

    promote_parser = subparsers.add_parser("promote", help="Promote a user-preference into runtime preferences.")
    promote_parser.add_argument("--id", required=True)

    review_parser = subparsers.add_parser("review", help="Mark a pending learning as confirmed or dismissed.")
    review_parser.add_argument("--id", required=True)
    review_parser.add_argument("--status", required=True, choices=sorted(REVIEW_STATUSES))

    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)

    try:
        if args.command == "log":
            entry, created = log_learning(
                root,
                category=args.category,
                text=args.text,
                source=args.source,
                skill=args.skill,
                context=args.context,
            )
            action = "created" if created else "bumped"
            print(f"[ok] {action} {entry['id']} occurrences={entry['occurrences']}")
            return 0

        if args.command == "recall":
            print(render_recall_digest(load_learnings(root), kind=args.kind, limit=args.limit).rstrip())
            return 0

        if args.command == "promote":
            entry, path = promote_learning(root, learning_id=args.id)
            print(f"[ok] promoted {entry['id']} -> {path.relative_to(root)}")
            return 0

        if args.command == "review":
            entry = review_learning(root, learning_id=args.id, status=args.status)
            print(f"[ok] reviewed {entry['id']} status={entry['status']}")
            return 0
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

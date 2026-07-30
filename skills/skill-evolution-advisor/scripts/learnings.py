#!/usr/bin/env python3
"""Capture, recall, promote, and review lightweight learnings."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, print_resolved_project_roots
from research.learnings import (
    CATEGORIES,
    RECALL_KINDS,
    REVIEW_STATUSES,
    SOURCES,
    apply_preference_review_decision,
    load_learnings,
    log_learning,
    prepare_preference_review_decision,
    promote_learning,
    render_recall_digest,
    review_learning,
)
from research.core import project_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    log_parser = subparsers.add_parser("log", help="Capture a lightweight learning.")
    log_parser.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    log_parser.add_argument("--text", required=True)
    log_parser.add_argument("--source", choices=sorted(SOURCES), default="agent")
    log_parser.add_argument("--skill", default="")
    log_parser.add_argument("--operation", default="")
    log_parser.add_argument("--observation", default="")
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


def prepare_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> dict:
    del rejection_reason
    return prepare_preference_review_decision(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
    )


def apply_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> list[Path]:
    del rejection_reason
    return apply_preference_review_decision(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
    )


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
                operation=args.operation,
                observation=args.observation,
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
    apply_preference_review_decision,

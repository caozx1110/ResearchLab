#!/usr/bin/env python3
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

from research.common import add_project_root_argument, append_program_reporting_event, ensure_dir, print_resolved_project_roots, program_reporting_events_path, simple_slug, write_text_if_changed
from research.core import checkpoint_and_report, project_root
from research.journal import mutation_transaction


def next_available_path(root: Path, slug: str, suffix: str) -> Path:
    path = root / f"{slug}{suffix}"
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = root / f"{slug}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive a program discussion note.")
    add_project_root_argument(parser)
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
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    out_root = root / "kb" / "programs" / args.program_id / "discussions"
    slug = simple_slug(args.title, "discussion")
    lines = [
        f"# {args.title}",
        "",
        "> Pending / Unverified judgement: this archive is a discussion projection, not a confirmed conclusion.",
        "",
        "## Summary",
        "",
        args.summary,
        "",
        "## Proposed Conclusion",
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
    event_path = program_reporting_events_path(root, args.program_id)
    with mutation_transaction(root, "archive-discussion", [out_root, event_path]):
        ensure_dir(out_root)
        path = next_available_path(out_root, slug, ".md")
        write_text_if_changed(path, "\n".join(lines))
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "discussion-archivist",
                "event_type": "discussion-conclusion",
                "title": args.title,
                "summary": args.summary,
                "stage": "discussion",
                "artifacts": [path.relative_to(root).as_posix()],
                "tags": ["discussion", "pending", "needs-agent-repair"],
                "epistemic_type": "judgement",
                "information_types": ["inference", "evaluation", "unverified"],
                "confirmation_status": "pending_user_confirmation",
                "needs_human_confirmation": True,
                "governance_status": "needs_agent_repair",
            },
            generated_by="discussion-archivist",
        )
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: archive discussion for {args.program_id}",
        target_paths=[path, event_path],
    )
    print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

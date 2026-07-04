#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.common import add_project_root_argument, load_program_reporting_events, print_resolved_project_roots, write_text_if_changed
from research.v2 import ensure_v2_workspace, checkpoint_and_report, project_root, user_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate v2 reports.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("weekly", "ppt-materials", "stage-summary", "writing-materials"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--program-id", required=True)
        cmd.add_argument("--stage", default="")
        cmd.add_argument("--limit", type=int, default=20)
    return parser


def normalize_events(events: list[dict[str, Any]], *, stage: str = "", limit: int = 20) -> list[dict[str, Any]]:
    filtered = []
    for item in events:
        if stage and str(item.get("stage") or "").strip() != stage:
            continue
        filtered.append(item)
    if limit > 0:
        filtered = filtered[-limit:]
    return filtered


def render_event_line(event: dict[str, Any]) -> str:
    timestamp = str(event.get("timestamp") or "unknown-time")
    source_skill = str(event.get("source_skill") or "unknown-skill")
    event_type = str(event.get("event_type") or "update")
    title = str(event.get("title") or "Untitled event")
    summary = str(event.get("summary") or "").strip()
    stage = str(event.get("stage") or "").strip()
    suffix = f" · stage={stage}" if stage else ""
    return f"- [{timestamp}] `{event_type}` / `{source_skill}` · {title}{suffix} · {summary}"


def render_lines(title: str, events: list[dict[str, Any]], *, report_kind: str) -> str:
    lines = [f"# {title}", ""]
    if report_kind == "ppt-materials":
        lines.extend(["## Slide Candidates", ""])
    elif report_kind == "writing-materials":
        lines.extend(["## Writing Claims & Evidence", ""])
    elif report_kind == "stage-summary":
        lines.extend(["## Stage Events", ""])
    else:
        lines.extend(["## Reporting Events", ""])

    for event in events:
        lines.append(render_event_line(event))

    if len(lines) == 4:
        lines.append("- 暂无 reporting-events，请先通过 `research-orchestrator` 或其他技能写入事件。")

    highlighted_artifacts = []
    highlighted_tags = []
    for event in events:
        highlighted_artifacts.extend(str(item) for item in event.get("artifacts", []) if str(item).strip())
        highlighted_tags.extend(str(item) for item in event.get("tags", []) if str(item).strip())

    lines.extend(["", "## Reopen Pointers", ""])
    if highlighted_artifacts:
        for item in highlighted_artifacts[:12]:
            lines.append(f"- `{item}`")
    else:
        lines.append("- 暂无关联 artifact")

    lines.extend(["", "## Tags", ""])
    unique_tags = []
    seen = set()
    for tag in highlighted_tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)
    if unique_tags:
        for tag in unique_tags[:12]:
            lines.append(f"- `{tag}`")
    else:
        lines.append("- 暂无标签")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_v2_workspace(root)
    reports_root = root / "kb" / "programs" / args.program_id / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    events = normalize_events(load_program_reporting_events(root, args.program_id), stage=args.stage, limit=args.limit)
    if args.command == "weekly":
        path = reports_root / "weekly.md"
        write_text_if_changed(path, render_lines(f"Weekly Report: {args.program_id}", events, report_kind="weekly"))
    elif args.command == "ppt-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-ppt-materials.md"
        write_text_if_changed(path, render_lines(f"PPT Materials: {args.program_id}", events, report_kind="ppt-materials"))
    elif args.command == "writing-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-writing-materials.md"
        write_text_if_changed(path, render_lines(f"Writing Materials: {args.program_id}", events, report_kind="writing-materials"))
    else:
        path = reports_root / "stage-summary.md"
        write_text_if_changed(path, render_lines(f"Stage Summary: {args.program_id}", events, report_kind="stage-summary"))
    print(path.relative_to(root))
    checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: generate {args.command} for {args.program_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

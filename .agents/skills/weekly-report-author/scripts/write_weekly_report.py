#!/usr/bin/env python3
"""Write a weekly report for a research program."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research import common as research_common
from research.common import find_project_root, research_root, utc_now_iso


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


def load_conductor_module() -> Any:
    skills_root = Path(__file__).resolve().parents[2]
    module_path = skills_root / "research-conductor" / "scripts" / "manage_workspace.py"
    if not module_path.exists():
        raise SystemExit(f"Missing research-conductor implementation: {module_path}")
    spec = importlib.util.spec_from_file_location("research_conductor_manage_workspace", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", default="", help="Optional inclusive UTC end date in YYYY-MM-DD format")
    parser.add_argument("--max-detailed-papers", type=int, default=8)
    parser.add_argument("--max-detailed-repos", type=int, default=6)
    return parser


def resolve_report_path(module: Any, project_root: Path, args: argparse.Namespace) -> Path | None:
    weekly_dir = research_root(project_root) / "programs" / args.program_id / "weekly"
    if hasattr(module, "report_window"):
        window_start, window_end = module.report_window(args.days, args.end_date)
        inclusive_end = window_end - timedelta(seconds=1)
        report_name = f"{window_start.date().isoformat()}_to_{inclusive_end.date().isoformat()}.md"
        candidate = weekly_dir / report_name
        if candidate.exists():
            return candidate
    reports = sorted(weekly_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def main() -> int:
    args = build_parser().parse_args()
    module = load_conductor_module()
    exit_code = int(module.write_weekly_report(args))
    if exit_code != 0:
        return exit_code
    project_root = find_project_root()
    report_path = resolve_report_path(module, project_root, args)
    artifacts = [relative_path(project_root, report_path)] if report_path and report_path.exists() else []
    append_wiki_log_event(
        project_root,
        {
            "source_skill": "weekly-report-author",
            "event_type": "reporting",
            "title": "Weekly report generated",
            "summary": f"Generated weekly report for program `{args.program_id}` over the last {args.days} day(s).",
            "program_id": args.program_id,
            "artifacts": artifacts,
            "window_end_date": str(args.end_date or "").strip(),
            "days": int(args.days),
        },
        generated_by="weekly-report-author",
    )
    rebuild_wiki_index_markdown(project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from collections.abc import Iterator
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

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, load_yaml, print_resolved_project_roots, write_text_if_changed
from research import journal as research_journal
from research.learnings import load_learnings, render_recall_digest
from research.core import checkpoint_and_report, iter_records, kb_root, project_root, user_root


CURRENT_STATE_STDOUT_LINES = 40


@contextmanager
def navigation_transaction(root: Path, op_type: str, target_paths: list[Path]) -> Iterator[None]:
    """Use the shared exact-path transaction once the recovery track is merged."""
    transaction = getattr(research_journal, "mutation_transaction", research_journal.journaled_op)
    with transaction(root, op_type, target_paths):
        yield


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh core user-facing navigation pages.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("refresh")
    subparsers.add_parser("current-state")
    subparsers.add_parser("reading-list")
    return parser


def load_program_states(root: Path) -> list[dict]:
    programs_root = kb_root(root) / "programs"
    if not programs_root.exists():
        return []
    states = []
    for path in sorted(programs_root.glob("*/state.yaml")):
        payload = load_yaml(path, default={})
        if isinstance(payload, dict):
            payload.setdefault("program_id", path.parent.name)
            states.append(payload)
    return states


def render_current(
    records: list[dict],
    program_states: list[dict] | None = None,
    recall_digest: str = "",
) -> str:
    lines = ["# Current State", "", "## Programs", ""]
    states = sorted(program_states or [], key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    for state in states[:12]:
        counts = state.get("counts") if isinstance(state.get("counts"), dict) else {}
        lines.append(
            f"- `{state.get('program_id')}` · stage={state.get('stage', 'init')} · "
            f"OQ={counts.get('open_questions', 0)} · evidence={counts.get('evidence_requests', 0)} · "
            f"{state.get('goal') or state.get('question') or ''}"
        )
    if len(lines) == 4:
        lines.append("- 暂无 program state")
    lines.extend(["", "## Confirmed Highlights", ""])
    confirmed = [item for item in records if item.get("confirmation_status") == "confirmed"]
    start = len(lines)
    for item in confirmed[:12]:
        lines.append(f"- `{item['id']}` · {item['kind']} · {item['title']} · {item.get('summary', '')}")
    if len(lines) == start:
        lines.append("- 暂无已确认条目")
    if recall_digest.strip():
        lines.extend(["", recall_digest.strip()])
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


def print_current_state_summary(root: Path, content: str) -> None:
    del root
    lines = content.strip().splitlines()
    for line in lines[:CURRENT_STATE_STDOUT_LINES]:
        print(line)
    if len(lines) > CURRENT_STATE_STDOUT_LINES:
        print("... 以上为当前实时状态的摘要。")
    else:
        print("以上为当前实时状态。")


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command != "current-state":
        print_resolved_project_roots(root)
    records = iter_records(root)
    program_states = load_program_states(root)
    recall_digest = render_recall_digest(load_learnings(root), kind="all", limit=5)
    current_path = user_root(root) / "current-state.md"
    nav_path = user_root(root) / "navigation.md"
    reading_path = user_root(root) / "reading-lists" / "current-reading.md"

    current_content = render_current(records, program_states, recall_digest)
    if args.command == "refresh":
        targets = [current_path, nav_path, reading_path]
        with navigation_transaction(root, "refresh_user_navigation", targets):
            write_text_if_changed(current_path, current_content)
            write_text_if_changed(nav_path, render_navigation(records))
            write_text_if_changed(reading_path, render_reading_list(records))
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: refresh user navigation",
            target_paths=targets,
        )
        print(current_path.relative_to(root))
        print(nav_path.relative_to(root))
        print(reading_path.relative_to(root))
        return 0
    if args.command == "current-state":
        print_current_state_summary(root, current_content)
        return 0
    with navigation_transaction(root, "refresh_reading_list", [reading_path]):
        write_text_if_changed(reading_path, render_reading_list(records))
    checkpoint_and_report(
        root,
        trigger="milestone",
        message="milestone: refresh reading list",
        target_paths=[reading_path],
    )
    print(reading_path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

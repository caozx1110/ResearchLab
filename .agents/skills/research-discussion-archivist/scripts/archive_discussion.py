#!/usr/bin/env python3
"""Archive technical discussions into durable program notes."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break


def _maybe_reexec_preferred_runtime() -> None:
    if os.environ.get("RESEARCH_RUNTIME_REEXEC") == "1":
        return
    try:
        import yaml  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    current = Path.cwd().resolve()
    project_root = None
    for candidate in [current] + list(current.parents):
        if (candidate / ".agents").exists() and (
            (candidate / "kb").exists() or (candidate / "doc").exists() or (candidate / "AGENTS.md").exists()
        ):
            project_root = candidate
            break
    if project_root is None:
        return
    runtime_root = project_root / "kb"
    if not runtime_root.exists():
        runtime_root = project_root / "doc" / "research"
    runtime_path = runtime_root / "memory" / "runtime-environments.yaml"
    if not runtime_path.exists():
        return
    match = re.search(r"^\s*python:\s*(.+?)\s*$", runtime_path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if not match:
        return
    runtime_python = match.group(1).strip().strip("'\"")
    if not runtime_python or not Path(runtime_python).exists():
        return
    env = dict(os.environ)
    env["RESEARCH_RUNTIME_REEXEC"] = "1"
    os.execvpe(runtime_python, [runtime_python, __file__, *sys.argv[1:]], env)


_maybe_reexec_preferred_runtime()

from research_v11.common import (
    find_project_root,
    load_yaml,
    research_root,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)


def relative_to_project(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def safe_load_yaml(path: Path, default: Any) -> Any:
    return load_yaml(path, default=default, allow_simple_fallback=True)


def safe_load_list_document(path: Path, doc_id: str, generated_by: str) -> dict[str, Any]:
    payload = safe_load_yaml(path, {})
    if not isinstance(payload, dict):
        return {**yaml_default(doc_id, generated_by), "items": []}
    payload.setdefault("id", doc_id)
    payload.setdefault("status", "ready")
    payload.setdefault("generated_by", generated_by)
    payload.setdefault("generated_at", utc_now_iso())
    payload["inputs"] = [str(item) for item in payload.get("inputs", []) if str(item).strip()] if isinstance(payload.get("inputs"), list) else []
    payload.setdefault("confidence", 1.0)
    payload["items"] = payload.get("items") if isinstance(payload.get("items"), list) else []
    return payload


def safe_append_program_reporting_event(project_root: Path, program_id: str, event: dict[str, Any], *, generated_by: str) -> None:
    path = research_root(project_root) / "programs" / program_id / "workflow" / "reporting-events.yaml"
    payload = safe_load_list_document(path, f"{program_id}-reporting-events", generated_by)
    payload["program_id"] = program_id
    payload["generated_by"] = generated_by
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(event)
    write_yaml_if_changed(path, payload)


def load_user_profile(project_root: Path) -> dict[str, Any]:
    payload = safe_load_yaml(research_root(project_root) / "memory" / "user-profile.yaml", {})
    return payload if isinstance(payload, dict) else {}


def prefers_chinese(project_root: Path) -> bool:
    return "zh" in str(load_user_profile(project_root).get("language_preference") or "").lower()


def program_root(project_root: Path, program_id: str) -> Path:
    path = research_root(project_root) / "programs" / program_id
    if not path.exists():
        raise SystemExit(f"Program not found: {program_id}")
    return path


def discussion_path(program_root_path: Path, title: str, when: datetime, slug: str) -> Path:
    safe_slug = slug or slugify(title, max_words=8)
    return program_root_path / "discussions" / f"{when.date().isoformat()}-{safe_slug}.md"


def note_sections(lines: list[str], heading: str, items: list[str]) -> None:
    if not items:
        return
    lines.extend([heading, ""])
    for item in items:
        value = " ".join(str(item or "").split()).strip()
        if value:
            lines.append(f"- {value}")
    lines.append("")


def build_discussion_markdown(
    project_root: Path,
    program_id: str,
    program_root_path: Path,
    title: str,
    summary: str,
    context: list[str],
    decisions: list[str],
    tradeoffs: list[str],
    open_questions: list[str],
    next_actions: list[str],
    artifacts: list[str],
    when: datetime,
    zh: bool,
) -> str:
    charter = safe_load_yaml(program_root_path / "charter.yaml", {})
    state = safe_load_yaml(program_root_path / "workflow" / "state.yaml", {})
    lines = [
        f"# 技术讨论：{title}" if zh else f"# Technical Discussion: {title}",
        "",
        f"- 日期: `{when.date().isoformat()}`" if zh else f"- Date: `{when.date().isoformat()}`",
        f"- Program: `{program_id}`",
        f"- 当前阶段: `{state.get('stage') or 'unknown'}`" if zh else f"- Current stage: `{state.get('stage') or 'unknown'}`",
        f"- 生成时间: `{utc_now_iso()}`" if zh else f"- Generated at: `{utc_now_iso()}`",
        "",
        "## 背景" if zh else "## Background",
        "",
        " ".join(str(summary or "").split()).strip() or ("待补充" if zh else "TBD"),
        "",
    ]
    if charter:
        question = " ".join(str(charter.get("question") or "").split()).strip()
        if question:
            lines.extend(
                [
                    "## 所属研究问题" if zh else "## Program Question",
                    "",
                    question,
                    "",
                ]
            )
    note_sections(lines, "## 讨论要点" if zh else "## Discussion Points", context)
    note_sections(lines, "## 本次结论" if zh else "## Current Conclusions", decisions)
    note_sections(lines, "## Tradeoffs", tradeoffs)
    note_sections(lines, "## 未决问题" if zh else "## Open Questions", open_questions)
    note_sections(lines, "## 下一步验证" if zh else "## Next Validation Actions", next_actions)
    if artifacts:
        lines.extend(["## 关联产物" if zh else "## Linked Artifacts", ""])
        for artifact in artifacts:
            path = Path(artifact)
            candidate = project_root / path if not path.is_absolute() else path
            label = artifact
            if candidate.exists():
                rel = os.path.relpath(candidate, start=discussion_path(program_root_path, title, when, "").parent).replace(os.sep, "/")
                lines.append(f"- [{label}]({rel})")
            else:
                lines.append(f"- `{artifact}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def refresh_index(program_root_path: Path, zh: bool) -> Path:
    discussions_root = program_root_path / "discussions"
    note_paths = sorted([path for path in discussions_root.glob("*.md") if path.name != "index.md"], reverse=True)
    lines = [
        "# Discussions Index" if not zh else "# 技术讨论索引",
        "",
    ]
    for path in note_paths:
        first_line = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip() if path.exists() else path.stem
        lines.append(f"- [{first_line}]({path.name})")
    lines.append("")
    index_path = discussions_root / "index.md"
    write_text_if_changed(index_path, "\n".join(lines))
    return index_path


def archive(args: argparse.Namespace) -> None:
    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root()
    program_root_path = program_root(project_root, args.program_id)
    when = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc) if args.date else datetime.now(timezone.utc)
    zh = prefers_chinese(project_root)
    target_path = discussion_path(program_root_path, args.title, when, args.slug)
    markdown = build_discussion_markdown(
        project_root,
        args.program_id,
        program_root_path,
        args.title,
        args.summary,
        args.context,
        args.decision,
        args.tradeoff,
        args.open_question,
        args.next_action,
        args.artifact,
        when,
        zh,
    )
    if args.command == "preview":
        print(relative_to_project(project_root, target_path))
        print()
        print(markdown)
        return

    write_text_if_changed(target_path, markdown)
    index_path = refresh_index(program_root_path, zh)
    state = safe_load_yaml(program_root_path / "workflow" / "state.yaml", {})
    safe_append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "research-discussion-archivist",
            "event_type": "discussion-archived",
            "title": "技术讨论已归档",
            "summary": f"归档讨论 `{args.title}`，记录 {len(args.decision)} 条结论、{len(args.open_question)} 个未决问题。",
            "artifacts": [
                relative_to_project(project_root, target_path),
                relative_to_project(project_root, index_path),
            ],
            "idea_ids": [str(state.get("selected_idea_id") or "")] if str(state.get("selected_idea_id") or "").strip() else [],
            "stage": str(state.get("stage") or ""),
            "tags": ["discussion", "tradeoff", "durable-notes"],
            "timestamp": utc_now_iso(),
        },
        generated_by="research-discussion-archivist",
    )
    print(relative_to_project(project_root, target_path))
    print(relative_to_project(project_root, index_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default="", help="Optional explicit project root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--program-id", required=True)
        subparser.add_argument("--title", required=True)
        subparser.add_argument("--summary", required=True)
        subparser.add_argument("--context", action="append", default=[])
        subparser.add_argument("--decision", action="append", default=[])
        subparser.add_argument("--tradeoff", action="append", default=[])
        subparser.add_argument("--open-question", action="append", default=[])
        subparser.add_argument("--next-action", action="append", default=[])
        subparser.add_argument("--artifact", action="append", default=[])
        subparser.add_argument("--slug", default="")
        subparser.add_argument("--date", default="", help="Optional ISO date such as 2026-04-11")

    add_common(subparsers.add_parser("archive", help="Write a durable discussion note"))
    add_common(subparsers.add_parser("preview", help="Print the discussion note without writing"))
    return parser.parse_args()


def main() -> None:
    archive(parse_args())


if __name__ == "__main__":
    main()

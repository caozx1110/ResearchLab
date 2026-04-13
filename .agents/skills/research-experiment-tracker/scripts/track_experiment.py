#!/usr/bin/env python3
"""Track experiment runs and maintain follow-up views."""

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


VALID_STATUSES = {"planned", "running", "completed", "failed", "blocked"}


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


def parse_metrics(values: list[str]) -> list[dict[str, str]]:
    metrics: list[dict[str, str]] = []
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"Invalid --metric value: {raw}. Expected key=value.")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise SystemExit(f"Invalid --metric value: {raw}. Expected key=value.")
        metrics.append({"name": key, "value": value})
    return metrics


def run_note_path(program_root_path: Path, title: str, when: datetime, slug: str) -> Path:
    safe_slug = slug or slugify(title, max_words=8)
    return program_root_path / "experiments" / "runs" / f"{when.date().isoformat()}-{safe_slug}.md"


def build_run_markdown(
    project_root: Path,
    program_id: str,
    program_root_path: Path,
    title: str,
    intent: str,
    status: str,
    config_notes: list[str],
    result_summary: str,
    failure_modes: list[str],
    next_actions: list[str],
    metrics: list[dict[str, str]],
    artifacts: list[str],
    when: datetime,
    zh: bool,
) -> str:
    state = safe_load_yaml(program_root_path / "workflow" / "state.yaml", {})
    lines = [
        f"# 实验记录：{title}" if zh else f"# Experiment Run: {title}",
        "",
        f"- 日期: `{when.date().isoformat()}`" if zh else f"- Date: `{when.date().isoformat()}`",
        f"- Program: `{program_id}`",
        f"- 当前阶段: `{state.get('stage') or 'unknown'}`" if zh else f"- Current stage: `{state.get('stage') or 'unknown'}`",
        f"- 状态: `{status}`" if zh else f"- Status: `{status}`",
        f"- 生成时间: `{utc_now_iso()}`" if zh else f"- Generated at: `{utc_now_iso()}`",
        "",
        "## 实验意图" if zh else "## Intent",
        "",
        " ".join(intent.split()).strip(),
        "",
    ]
    if config_notes:
        lines.extend(["## 配置与改动" if zh else "## Config and Changes", ""])
        for note in config_notes:
            cleaned = " ".join(str(note or "").split()).strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        lines.append("")
    lines.extend(["## 结果摘要" if zh else "## Result Summary", "", " ".join(result_summary.split()).strip() or ("待补充" if zh else "TBD"), ""])
    if metrics:
        lines.extend(["## 指标" if zh else "## Metrics", ""])
        for metric in metrics:
            lines.append(f"- `{metric['name']}` = `{metric['value']}`")
        lines.append("")
    if failure_modes:
        lines.extend(["## 失败模式 / 风险" if zh else "## Failure Modes / Risks", ""])
        for item in failure_modes:
            cleaned = " ".join(str(item or "").split()).strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        lines.append("")
    if next_actions:
        lines.extend(["## 下一步" if zh else "## Next Actions", ""])
        for item in next_actions:
            cleaned = " ".join(str(item or "").split()).strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        lines.append("")
    if artifacts:
        lines.extend(["## 关联产物" if zh else "## Linked Artifacts", ""])
        for artifact in artifacts:
            path = Path(artifact)
            candidate = project_root / path if not path.is_absolute() else path
            if candidate.exists():
                rel = os.path.relpath(candidate, start=run_note_path(program_root_path, title, when, "").parent).replace(os.sep, "/")
                lines.append(f"- [{artifact}]({rel})")
            else:
                lines.append(f"- `{artifact}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def refresh_follow_up(program_root_path: Path, payload: dict[str, Any], zh: bool) -> Path:
    items = list(payload.get("items", []))
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    counts: dict[str, int] = {status: 0 for status in sorted(VALID_STATUSES)}
    for item in items:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    lines = [
        "# 实验 follow-up 视图" if zh else "# Experiment Follow-up",
        "",
        f"- 生成时间: `{utc_now_iso()}`" if zh else f"- Generated at: `{utc_now_iso()}`",
        "",
        "## 状态统计" if zh else "## Status Counts",
        "",
    ]
    for status, count in counts.items():
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## 近期运行" if zh else "## Recent Runs", ""])
    for item in items[:12]:
        note_path = program_root_path / str(item.get("note_path") or "")
        rel = note_path.name if note_path.exists() else str(item.get("note_path") or "")
        next_actions = item.get("next_actions", [])
        summary = " ".join(str(item.get("result_summary") or "").split()).strip()
        action_suffix = f" | next: {next_actions[0]}" if next_actions else ""
        if note_path.exists():
            lines.append(f"- [{item.get('title')}]({rel}) | `{item.get('status')}` | {summary}{action_suffix}")
        else:
            lines.append(f"- `{item.get('title')}` | `{item.get('status')}` | {summary}{action_suffix}")
    lines.append("")
    output_path = program_root_path / "experiments" / "follow-up.md"
    write_text_if_changed(output_path, "\n".join(lines))
    return output_path


def track(args: argparse.Namespace) -> None:
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"Invalid --status: {args.status}. Expected one of {sorted(VALID_STATUSES)}")
    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root()
    program_root_path = program_root(project_root, args.program_id)
    when = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc) if args.date else datetime.now(timezone.utc)
    zh = prefers_chinese(project_root)
    metrics = parse_metrics(args.metric)
    note_path = run_note_path(program_root_path, args.title, when, args.slug)
    markdown = build_run_markdown(
        project_root,
        args.program_id,
        program_root_path,
        args.title,
        args.intent,
        args.status,
        args.config,
        args.result_summary,
        args.failure_mode,
        args.next_action,
        metrics,
        args.artifact,
        when,
        zh,
    )
    if args.command == "preview":
        print(relative_to_project(project_root, note_path))
        print()
        print(markdown)
        return

    write_text_if_changed(note_path, markdown)
    log_path = program_root_path / "experiments" / "run-log.yaml"
    payload = safe_load_list_document(log_path, f"{args.program_id}-run-log", "research-experiment-tracker")
    payload["program_id"] = args.program_id
    payload["generated_by"] = "research-experiment-tracker"
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(
        {
            "run_id": note_path.stem,
            "title": args.title,
            "status": args.status,
            "timestamp": when.isoformat(),
            "intent": args.intent,
            "result_summary": args.result_summary,
            "failure_modes": args.failure_mode,
            "next_actions": args.next_action,
            "metrics": metrics,
            "artifacts": args.artifact,
            "note_path": relative_to_project(program_root_path, note_path),
        }
    )
    payload["items"].sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    write_yaml_if_changed(log_path, payload)
    follow_up_path = refresh_follow_up(program_root_path, payload, zh)

    state = safe_load_yaml(program_root_path / "workflow" / "state.yaml", {})
    safe_append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "research-experiment-tracker",
            "event_type": "experiment-run-logged",
            "title": "实验运行已记录",
            "summary": f"记录实验 `{args.title}`，状态 `{args.status}`。",
            "artifacts": [
                relative_to_project(project_root, note_path),
                relative_to_project(project_root, log_path),
                relative_to_project(project_root, follow_up_path),
            ],
            "idea_ids": [str(state.get("selected_idea_id") or "")] if str(state.get("selected_idea_id") or "").strip() else [],
            "stage": str(state.get("stage") or ""),
            "tags": ["experiment", "run-log", args.status],
            "timestamp": utc_now_iso(),
        },
        generated_by="research-experiment-tracker",
    )
    print(relative_to_project(project_root, note_path))
    print(relative_to_project(project_root, log_path))
    print(relative_to_project(project_root, follow_up_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default="", help="Optional explicit project root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--program-id", required=True)
        subparser.add_argument("--title", required=True)
        subparser.add_argument("--intent", required=True)
        subparser.add_argument("--status", default="planned")
        subparser.add_argument("--config", action="append", default=[])
        subparser.add_argument("--result-summary", default="")
        subparser.add_argument("--failure-mode", action="append", default=[])
        subparser.add_argument("--next-action", action="append", default=[])
        subparser.add_argument("--metric", action="append", default=[])
        subparser.add_argument("--artifact", action="append", default=[])
        subparser.add_argument("--slug", default="")
        subparser.add_argument("--date", default="", help="Optional ISO date such as 2026-04-11")

    add_common(subparsers.add_parser("log-run", help="Write a durable experiment run note"))
    add_common(subparsers.add_parser("preview", help="Print the run note without writing"))
    return parser.parse_args()


def main() -> None:
    track(parse_args())


if __name__ == "__main__":
    main()

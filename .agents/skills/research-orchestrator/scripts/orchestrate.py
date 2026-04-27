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

from research.common import (
    append_program_reporting_event,
    blank_list_document,
    blank_reporting_events,
    ensure_dir,
    load_list_document,
    load_yaml,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)
from research.v2 import ensure_v2_workspace, kb_root, project_root

ROUTE_HINTS = {
    "论文": "paper-analyst",
    "paper": "paper-analyst",
    "仓库": "repo-analyst",
    "repo": "repo-analyst",
    "博客": "blog-analyst",
    "blog": "blog-analyst",
    "综述": "literature-synthesizer",
    "idea": "idea-workbench",
    "实验": "experiment-workbench",
    "周报": "report-author",
    "ppt": "report-author",
    "导航": "research-navigator",
    "讨论": "discussion-archivist",
    "discussion": "discussion-archivist",
    "wiki": "wiki-adapter",
    "知识库": "wiki-adapter",
}


def program_root(root: Path, program_id: str) -> Path:
    return kb_root(root) / "programs" / program_id


def workflow_root(root: Path, program_id: str) -> Path:
    return program_root(root, program_id) / "workflow"


def state_path(root: Path, program_id: str) -> Path:
    return program_root(root, program_id) / "state.yaml"


def open_questions_path(root: Path, program_id: str) -> Path:
    return workflow_root(root, program_id) / "open-questions.yaml"


def evidence_requests_path(root: Path, program_id: str) -> Path:
    return workflow_root(root, program_id) / "evidence-requests.yaml"


def reporting_events_path(root: Path, program_id: str) -> Path:
    return workflow_root(root, program_id) / "reporting-events.yaml"


def decision_log_path(root: Path, program_id: str) -> Path:
    return workflow_root(root, program_id) / "decision-log.md"


def normalize_list(values: list[str] | None) -> list[str]:
    return [str(item).strip() for item in values or [] if str(item).strip()]


def load_state(root: Path, program_id: str) -> dict:
    payload = load_yaml(state_path(root, program_id), default={})
    if not isinstance(payload, dict) or not payload:
        payload = {
            **yaml_default(f"{program_id}-state-v2", "research-orchestrator", status="active"),
            "program_id": program_id,
            "question": "",
            "goal": "",
            "stage": "init",
            "active_unit_ids": [],
            "blockers": [],
            "next_actions": [],
            "resource_constraints": [],
            "selected_idea_id": "",
            "selected_repo_id": "",
            "workflow_files": {
                "open_questions": f"kb/programs/{program_id}/workflow/open-questions.yaml",
                "evidence_requests": f"kb/programs/{program_id}/workflow/evidence-requests.yaml",
                "decision_log": f"kb/programs/{program_id}/workflow/decision-log.md",
                "reporting_events": f"kb/programs/{program_id}/workflow/reporting-events.yaml",
            },
            "counts": {
                "open_questions": 0,
                "evidence_requests": 0,
                "reporting_events": 0,
                "decisions": 0,
            },
        }
    return payload


def list_items(path: Path, doc_id: str, generated_by: str) -> list[dict[str, Any]]:
    payload = load_list_document(path, doc_id, generated_by)
    return [item for item in payload.get("items", []) if isinstance(item, dict)]


def ensure_program_files(root: Path, program_id: str) -> None:
    ensure_dir(program_root(root, program_id))
    ensure_dir(workflow_root(root, program_id))
    ensure_dir(program_root(root, program_id) / "design")
    ensure_dir(program_root(root, program_id) / "experiments")
    ensure_dir(program_root(root, program_id) / "reports")
    defaults = {
        open_questions_path(root, program_id): blank_list_document(f"{program_id}-open-questions", "research-orchestrator"),
        evidence_requests_path(root, program_id): blank_list_document(f"{program_id}-evidence-requests", "research-orchestrator"),
        reporting_events_path(root, program_id): blank_reporting_events(program_id, "research-orchestrator"),
    }
    for path, payload in defaults.items():
        if not path.exists():
            write_yaml_if_changed(path, payload)
    if not decision_log_path(root, program_id).exists():
        write_text_if_changed(
            decision_log_path(root, program_id),
            "# Decision Log\n\n"
            "AI 推断、评估和取舍理由如果不是用户明确确认，默认保持待确认语义。\n",
        )


def refresh_state_counts(root: Path, program_id: str, payload: dict) -> dict:
    ensure_program_files(root, program_id)
    open_questions = list_items(open_questions_path(root, program_id), f"{program_id}-open-questions", "research-orchestrator")
    evidence_requests = list_items(evidence_requests_path(root, program_id), f"{program_id}-evidence-requests", "research-orchestrator")
    reporting_events = list_items(reporting_events_path(root, program_id), f"{program_id}-reporting-events", "research-orchestrator")
    decision_log = decision_log_path(root, program_id).read_text(encoding="utf-8") if decision_log_path(root, program_id).exists() else ""
    payload.setdefault("workflow_files", {})
    payload["workflow_files"].update(
        {
            "open_questions": open_questions_path(root, program_id).relative_to(root).as_posix(),
            "evidence_requests": evidence_requests_path(root, program_id).relative_to(root).as_posix(),
            "decision_log": decision_log_path(root, program_id).relative_to(root).as_posix(),
            "reporting_events": reporting_events_path(root, program_id).relative_to(root).as_posix(),
        }
    )
    payload["counts"] = {
        "open_questions": len([item for item in open_questions if item.get("status", "open") != "closed"]),
        "evidence_requests": len([item for item in evidence_requests if item.get("status", "open") != "closed"]),
        "reporting_events": len(reporting_events),
        "decisions": decision_log.count("\n## "),
    }
    payload["updated_at"] = utc_now_iso()
    return payload


def append_list_item(path: Path, doc_id: str, generated_by: str, item: dict[str, Any]) -> Path:
    payload = load_list_document(path, doc_id, generated_by)
    items = [entry for entry in payload.get("items", []) if isinstance(entry, dict)]
    normalized = dict(item)
    normalized.setdefault("id", f"{doc_id}-{len(items) + 1:03d}")
    normalized.setdefault("created_at", utc_now_iso())
    normalized.setdefault("status", "open")
    items.append(normalized)
    payload["items"] = items
    payload["generated_by"] = generated_by
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(path, payload)
    return path


def append_decision(root: Path, program_id: str, item: dict[str, Any]) -> Path:
    path = decision_log_path(root, program_id)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Decision Log\n\n"
    lines = [
        existing.rstrip(),
        "",
        f"## {item['timestamp']} · {item['decision']}",
        "",
        f"- Stage: `{item.get('stage', '') or 'unknown'}`",
        f"- Rationale: {item.get('rationale', '') or '待补充'}",
        f"- Information types: {', '.join(item.get('information_types', []))}",
    ]
    if item.get("evidence"):
        lines.append(f"- Evidence: {', '.join(item['evidence'])}")
    if item.get("alternatives"):
        lines.append(f"- Alternatives: {', '.join(item['alternatives'])}")
    if item.get("confirmation_status"):
        lines.append(f"- Confirmation: `{item['confirmation_status']}`")
    write_text_if_changed(path, "\n".join(lines).strip() + "\n")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage v2 research programs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init-program", help="Create a new program")
    init_cmd.add_argument("--program-id", required=True)
    init_cmd.add_argument("--question", required=True)
    init_cmd.add_argument("--goal", required=True)

    stage = subparsers.add_parser("set-stage", help="Update program stage")
    stage.add_argument("--program-id", required=True)
    stage.add_argument("--stage", required=True)

    status = subparsers.add_parser("status", help="Show program status")
    status.add_argument("--program-id", required=True)

    route = subparsers.add_parser("route", help="Suggest the right v2 skill for a task")
    route.add_argument("--task", required=True)

    attach = subparsers.add_parser("attach-unit", help="Attach a unit id to a program")
    attach.add_argument("--program-id", required=True)
    attach.add_argument("--unit-id", required=True)

    query = subparsers.add_parser("query-program", help="Write a durable query note for a program")
    query.add_argument("--program-id", required=True)
    query.add_argument("--question", required=True)

    question = subparsers.add_parser("add-open-question", help="Append a program open question")
    question.add_argument("--program-id", required=True)
    question.add_argument("--question", required=True)
    question.add_argument("--context", default="")
    question.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"])
    question.add_argument("--owner", default="")
    question.add_argument("--related-unit", action="append", default=[])

    evidence = subparsers.add_parser("request-evidence", help="Append an evidence request")
    evidence.add_argument("--program-id", required=True)
    evidence.add_argument("--question", required=True)
    evidence.add_argument("--needed", required=True)
    evidence.add_argument("--source-type", default="unknown", choices=["paper", "repo", "blog", "experiment", "benchmark", "user", "unknown"])
    evidence.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"])
    evidence.add_argument("--blocking", action="store_true")
    evidence.add_argument("--related-unit", action="append", default=[])

    decision = subparsers.add_parser("log-decision", help="Append a program decision")
    decision.add_argument("--program-id", required=True)
    decision.add_argument("--decision", required=True)
    decision.add_argument("--rationale", default="")
    decision.add_argument("--stage", default="")
    decision.add_argument("--evidence", action="append", default=[])
    decision.add_argument("--alternative", action="append", default=[])
    decision.add_argument("--confirmation-status", default="pending_user_confirmation", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])

    event = subparsers.add_parser("add-reporting-event", help="Append a reportable program event")
    event.add_argument("--program-id", required=True)
    event.add_argument("--title", required=True)
    event.add_argument("--summary", required=True)
    event.add_argument("--event-type", default="update")
    event.add_argument("--stage", default="")
    event.add_argument("--artifact", action="append", default=[])
    event.add_argument("--tag", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    ensure_v2_workspace(root)

    if args.command == "init-program":
        ensure_program_files(root, args.program_id)
        payload = load_state(root, args.program_id)
        payload["question"] = args.question
        payload["goal"] = args.goal
        payload["stage"] = "init"
        payload = refresh_state_counts(root, args.program_id, payload)
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "research-orchestrator",
                "event_type": "program-created",
                "title": "Program initialized",
                "summary": args.goal,
                "stage": "init",
                "tags": ["program-state"],
                "artifacts": [state_path(root, args.program_id).relative_to(root).as_posix()],
            },
            generated_by="research-orchestrator",
        )
        payload = refresh_state_counts(root, args.program_id, payload)
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(f"[ok] created program {args.program_id}")
        return 0
    if args.command == "set-stage":
        ensure_program_files(root, args.program_id)
        payload = load_state(root, args.program_id)
        payload["stage"] = args.stage
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "research-orchestrator",
                "event_type": "stage-changed",
                "title": f"Stage changed to {args.stage}",
                "summary": f"Program stage updated to `{args.stage}`.",
                "stage": args.stage,
                "tags": ["program-state"],
            },
            generated_by="research-orchestrator",
        )
        payload = refresh_state_counts(root, args.program_id, payload)
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(f"[ok] updated stage to {args.stage}")
        return 0
    if args.command == "status":
        ensure_program_files(root, args.program_id)
        payload = load_state(root, args.program_id)
        payload = refresh_state_counts(root, args.program_id, payload)
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(f"program_id: {payload['program_id']}")
        print(f"stage: {payload['stage']}")
        print(f"question: {payload['question']}")
        print(f"goal: {payload['goal']}")
        print(f"active_unit_ids: {payload.get('active_unit_ids', [])}")
        print(f"counts: {payload.get('counts', {})}")
        print(f"workflow_files: {payload.get('workflow_files', {})}")
        return 0
    if args.command == "route":
        lower = args.task.lower()
        for key, skill in ROUTE_HINTS.items():
            if key in lower:
                print(skill)
                return 0
        print("research-orchestrator")
        return 0
    if args.command == "attach-unit":
        payload = load_state(root, args.program_id)
        ensure_program_files(root, args.program_id)
        unit_ids = normalize_list(payload.get("active_unit_ids"))
        if args.unit_id not in unit_ids:
            unit_ids.append(args.unit_id)
        payload["active_unit_ids"] = sorted(set(unit_ids))
        payload = refresh_state_counts(root, args.program_id, payload)
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(f"[ok] attached {args.unit_id} to {args.program_id}")
        return 0
    if args.command == "query-program":
        query_root = program_root(root, args.program_id) / "queries"
        ensure_dir(query_root)
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in args.question).strip("-")[:64] or "query"
        query_path = query_root / f"{slug}.md"
        state = load_state(root, args.program_id)
        lines = [
            f"# Program Query: {args.question}",
            "",
            f"- program_id: `{args.program_id}`",
            f"- stage: `{state.get('stage', 'init')}`",
            f"- active_unit_ids: {', '.join(state.get('active_unit_ids', [])) or '-'}",
            "",
            "## Notes",
            "",
            "- 待补充基于当前 units / decisions / evidence requests 的回答。",
            "",
        ]
        write_text_if_changed(query_path, "\n".join(lines))
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "research-orchestrator",
                "event_type": "program-query",
                "title": args.question,
                "summary": "Created a durable program query note.",
                "stage": str(state.get("stage") or ""),
                "artifacts": [query_path.relative_to(root).as_posix()],
                "tags": ["query", "program"],
            },
            generated_by="research-orchestrator",
        )
        payload = refresh_state_counts(root, args.program_id, state)
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(query_path.relative_to(root))
        return 0
    if args.command == "add-open-question":
        ensure_program_files(root, args.program_id)
        path = append_list_item(
            open_questions_path(root, args.program_id),
            f"{args.program_id}-open-questions",
            "research-orchestrator",
            {
                "question": args.question,
                "context": args.context,
                "priority": args.priority,
                "owner": args.owner,
                "related_unit_ids": normalize_list(args.related_unit),
                "information_types": ["fact", "unverified"],
            },
        )
        payload = refresh_state_counts(root, args.program_id, load_state(root, args.program_id))
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(path.relative_to(root))
        return 0
    if args.command == "request-evidence":
        ensure_program_files(root, args.program_id)
        path = append_list_item(
            evidence_requests_path(root, args.program_id),
            f"{args.program_id}-evidence-requests",
            "research-orchestrator",
            {
                "question": args.question,
                "needed": args.needed,
                "source_type": args.source_type,
                "priority": args.priority,
                "blocking": bool(args.blocking),
                "related_unit_ids": normalize_list(args.related_unit),
                "information_types": ["fact", "unverified"],
            },
        )
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "research-orchestrator",
                "event_type": "evidence-requested",
                "title": args.question,
                "summary": args.needed,
                "stage": load_state(root, args.program_id).get("stage", ""),
                "tags": ["evidence-request", args.source_type],
                "artifacts": [path.relative_to(root).as_posix()],
            },
            generated_by="research-orchestrator",
        )
        payload = refresh_state_counts(root, args.program_id, load_state(root, args.program_id))
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(path.relative_to(root))
        return 0
    if args.command == "log-decision":
        ensure_program_files(root, args.program_id)
        state = load_state(root, args.program_id)
        item = {
            "timestamp": utc_now_iso(),
            "decision": args.decision,
            "rationale": args.rationale,
            "stage": args.stage or state.get("stage", ""),
            "evidence": normalize_list(args.evidence),
            "alternatives": normalize_list(args.alternative),
            "confirmation_status": args.confirmation_status,
            "information_types": ["fact"] if args.confirmation_status in {"auto_confirmed", "confirmed"} else ["fact", "inference", "evaluation", "unverified"],
        }
        path = append_decision(root, args.program_id, item)
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "research-orchestrator",
                "event_type": "decision",
                "title": args.decision,
                "summary": args.rationale,
                "stage": item["stage"],
                "tags": ["decision"],
                "artifacts": [path.relative_to(root).as_posix(), *item["evidence"]],
            },
            generated_by="research-orchestrator",
        )
        state = refresh_state_counts(root, args.program_id, state)
        state["last_decision"] = {"decision": args.decision, "timestamp": item["timestamp"], "confirmation_status": args.confirmation_status}
        write_yaml_if_changed(state_path(root, args.program_id), state)
        print(path.relative_to(root))
        return 0
    if args.command == "add-reporting-event":
        ensure_program_files(root, args.program_id)
        path = append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "research-orchestrator",
                "event_type": args.event_type,
                "title": args.title,
                "summary": args.summary,
                "stage": args.stage or load_state(root, args.program_id).get("stage", ""),
                "tags": normalize_list(args.tag),
                "artifacts": normalize_list(args.artifact),
            },
            generated_by="research-orchestrator",
        )
        payload = refresh_state_counts(root, args.program_id, load_state(root, args.program_id))
        write_yaml_if_changed(state_path(root, args.program_id), payload)
        print(path.relative_to(root))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

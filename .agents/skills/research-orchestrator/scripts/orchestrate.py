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
    append_list_item,
    append_program_reporting_event,
    blank_list_document,
    blank_reporting_events,
    ensure_dir,
    load_list_document,
    load_yaml,
    normalize_list,
    program_file_lock,
    simple_slug,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)
from research.v2 import append_history, ensure_v2_workspace, kb_root, locate_record, checkpoint_and_report, project_root, write_record

OPEN_QUESTION_OPEN_STATUSES = {"open"}
EVIDENCE_REQUEST_OPEN_STATUSES = {"open"}

ROUTE_HINTS = {
    "source": "source-intake",
    "intake": "source-intake",
    "staging": "source-intake",
    "入库": "source-intake",
    "摄入": "source-intake",
    "新论文": "source-intake",
    "新 paper": "source-intake",
    "new paper": "source-intake",
    "新仓库": "source-intake",
    "新 repo": "source-intake",
    "new repo": "source-intake",
    "新博客": "source-intake",
    "新 blog": "source-intake",
    "new blog": "source-intake",
    "论文": "paper-analyst",
    "paper": "paper-analyst",
    "仓库": "repo-analyst",
    "repo": "repo-analyst",
    "博客": "blog-analyst",
    "blog": "blog-analyst",
    "综述": "literature-synthesizer",
    "idea": "idea-workbench",
    "方法": "method-designer",
    "method": "method-designer",
    "design": "method-designer",
    "baseline": "method-designer",
    "interface": "method-designer",
    "实验": "experiment-workbench",
    "周报": "report-author",
    "ppt": "report-author",
    "配置": "research-config-manager",
    "config": "research-config-manager",
    "偏好": "research-config-manager",
    "runtime": "research-config-manager",
    "taxonomy seed": "research-config-manager",
    "pool seed": "research-config-manager",
    "治理": "knowledge-base-manager",
    "索引": "knowledge-base-manager",
    "schema": "knowledge-base-manager",
    "lint": "knowledge-base-manager",
    "governance": "knowledge-base-manager",
    "导航": "research-navigator",
    "讨论": "discussion-archivist",
    "discussion": "discussion-archivist",
    "skill evolution": "skill-evolution-advisor",
    "技能演化": "skill-evolution-advisor",
    "skill drift": "skill-evolution-advisor",
    "retrospective": "skill-evolution-advisor",
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
            "time_policy": {
                "storage_timezone": "UTC",
                "display_note": "human-facing markdown may localize when needed",
            },
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
    payload.setdefault(
        "time_policy",
        {
            "storage_timezone": "UTC",
            "display_note": "human-facing markdown may localize when needed",
        },
    )
    return payload


def write_state(root: Path, program_id: str, payload: dict[str, Any]) -> Path:
    payload = refresh_state_counts(root, program_id, payload)
    write_yaml_if_changed(state_path(root, program_id), payload)
    return state_path(root, program_id)


def print_normalized_unit_id(requested_id: str, resolved_id: str, path: Path, root: Path) -> None:
    if requested_id == resolved_id:
        return
    print(f"normalized unit id: {requested_id} -> {resolved_id}")
    print(f"canonical unit record: {path.relative_to(root)}")


def ensure_unit_program_link(root: Path, program_id: str, unit_id: str) -> tuple[str, str]:
    try:
        record, record_path = locate_record(root, unit_id)
    except SystemExit as exc:
        return "", f"[warn] attach-unit could not sync reverse link for `{unit_id}`: {exc}"
    canonical_id = str(record.get("id") or unit_id)
    program_ids = normalize_list(record.get("program_ids"))
    if program_id not in program_ids:
        program_ids.append(program_id)
        record["program_ids"] = sorted(set(program_ids))
        append_history(
            record,
            action="program-attached",
            summary=f"Attached unit to program `{program_id}`.",
            information_types=["fact"],
        )
        write_record(root, record)
    return canonical_id, ""


def list_items(path: Path, doc_id: str, generated_by: str) -> list[dict[str, Any]]:
    payload = load_list_document(path, doc_id, generated_by)
    return [item for item in payload.get("items", []) if isinstance(item, dict)]


def write_list_items(path: Path, doc_id: str, generated_by: str, items: list[dict[str, Any]]) -> Path:
    payload = load_list_document(path, doc_id, generated_by)
    payload["items"] = items
    payload["generated_by"] = generated_by
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(path, payload)
    return path


def update_list_item_status(
    path: Path,
    doc_id: str,
    generated_by: str,
    item_id: str,
    *,
    status: str,
    note_key: str,
    note: str,
) -> tuple[Path, dict[str, Any]]:
    items = list_items(path, doc_id, generated_by)
    for item in items:
        if str(item.get("id") or "") != item_id:
            continue
        item["status"] = status
        item["updated_at"] = utc_now_iso()
        if note:
            item[note_key] = note
        write_list_items(path, doc_id, generated_by, items)
        return path, item
    raise SystemExit(f"Could not find workflow item `{item_id}` in {path}")


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
            "AI 推断、评估和取舍理由如果不是用户明确确认，默认保持待确认语义。\n\n"
            "All script-generated timestamps are stored in UTC.\n",
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
        "open_questions": len([item for item in open_questions if str(item.get("status") or "open") in OPEN_QUESTION_OPEN_STATUSES]),
        "evidence_requests": len([item for item in evidence_requests if str(item.get("status") or "open") in EVIDENCE_REQUEST_OPEN_STATUSES]),
        "reporting_events": len(reporting_events),
        "decisions": decision_log.count("\n## "),
    }
    payload["updated_at"] = utc_now_iso()
    return payload


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

    answer = subparsers.add_parser("answer-question", help="Mark a program open question as answered")
    answer.add_argument("--program-id", required=True)
    answer.add_argument("--question-id", required=True)
    answer.add_argument("--answer", required=True)

    drop_question = subparsers.add_parser("drop-question", help="Drop a program open question")
    drop_question.add_argument("--program-id", required=True)
    drop_question.add_argument("--question-id", required=True)
    drop_question.add_argument("--reason", default="")

    evidence = subparsers.add_parser("request-evidence", help="Append an evidence request")
    evidence.add_argument("--program-id", required=True)
    evidence.add_argument("--question", required=True)
    evidence.add_argument("--needed", required=True)
    evidence.add_argument("--source-type", default="unknown", choices=["paper", "repo", "blog", "experiment", "benchmark", "user", "unknown"])
    evidence.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"])
    evidence.add_argument("--blocking", action="store_true")
    evidence.add_argument("--related-unit", action="append", default=[])

    resolve = subparsers.add_parser("resolve-evidence", help="Mark an evidence request as fulfilled")
    resolve.add_argument("--program-id", required=True)
    resolve.add_argument("--evidence-id", required=True)
    resolve.add_argument("--result", required=True)
    resolve.add_argument("--artifact", action="append", default=[])

    drop_evidence = subparsers.add_parser("drop-evidence", help="Drop an evidence request")
    drop_evidence.add_argument("--program-id", required=True)
    drop_evidence.add_argument("--evidence-id", required=True)
    drop_evidence.add_argument("--reason", default="")

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
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            payload = load_state(root, args.program_id)
            payload["question"] = args.question
            payload["goal"] = args.goal
            payload["stage"] = "init"
            write_state(root, args.program_id, payload)
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
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(f"[ok] created program {args.program_id}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: init program {args.program_id}")
        return 0
    if args.command == "set-stage":
        with program_file_lock(root, args.program_id):
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
            write_state(root, args.program_id, payload)
        print(f"[ok] updated stage to {args.stage}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: set program stage {args.program_id} -> {args.stage}")
        return 0
    if args.command == "status":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            payload = load_state(root, args.program_id)
            write_state(root, args.program_id, payload)
            payload = load_state(root, args.program_id)
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
        warning = ""
        canonical_id = args.unit_id
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            payload = load_state(root, args.program_id)
            canonical_id, warning = ensure_unit_program_link(root, args.program_id, args.unit_id)
            if not canonical_id:
                if warning:
                    print(warning)
                return 1
            unit_ids = normalize_list(payload.get("active_unit_ids"))
            if canonical_id not in unit_ids:
                unit_ids.append(canonical_id)
            payload["active_unit_ids"] = sorted(set(unit_ids))
            write_state(root, args.program_id, payload)
            try:
                resolved_record, resolved_path = locate_record(root, canonical_id)
                print_normalized_unit_id(args.unit_id, str(resolved_record.get("id") or canonical_id), resolved_path, root)
            except SystemExit:
                pass
        if warning:
            print(warning)
        print(f"[ok] attached {canonical_id} to {args.program_id}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: attach {canonical_id} to {args.program_id}")
        return 0
    if args.command == "query-program":
        with program_file_lock(root, args.program_id):
            query_root = program_root(root, args.program_id) / "queries"
            ensure_dir(query_root)
            slug = simple_slug(args.question, "query")
            query_path = query_root / f"{slug}.md"
            state = load_state(root, args.program_id)
            lines = [
                f"# Program Query: {args.question}",
                "",
                f"- program_id: `{args.program_id}`",
                f"- stage: `{state.get('stage', 'init')}`",
                f"- active_unit_ids: {', '.join(state.get('active_unit_ids', [])) or '-'}",
                "- time_policy: `UTC storage`",
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
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(query_path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: query program {args.program_id}")
        return 0
    if args.command == "add-open-question":
        with program_file_lock(root, args.program_id):
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
                default_status="open",
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: add open question {args.program_id}")
        return 0
    if args.command == "answer-question":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            path, item = update_list_item_status(
                open_questions_path(root, args.program_id),
                f"{args.program_id}-open-questions",
                "research-orchestrator",
                args.question_id,
                status="answered",
                note_key="answer",
                note=args.answer,
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(f"[ok] answered {item.get('id')}")
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: answer open question {args.program_id}")
        return 0
    if args.command == "drop-question":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            path, item = update_list_item_status(
                open_questions_path(root, args.program_id),
                f"{args.program_id}-open-questions",
                "research-orchestrator",
                args.question_id,
                status="dropped",
                note_key="drop_reason",
                note=args.reason,
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(f"[ok] dropped {item.get('id')}")
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: drop open question {args.program_id}")
        return 0
    if args.command == "request-evidence":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            current_state = load_state(root, args.program_id)
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
                default_status="open",
            )
            append_program_reporting_event(
                root,
                args.program_id,
                {
                    "source_skill": "research-orchestrator",
                    "event_type": "evidence-requested",
                    "title": args.question,
                    "summary": args.needed,
                    "stage": current_state.get("stage", ""),
                    "tags": ["evidence-request", args.source_type],
                    "artifacts": [path.relative_to(root).as_posix()],
                },
                generated_by="research-orchestrator",
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: request evidence {args.program_id}")
        return 0
    if args.command == "resolve-evidence":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            current_state = load_state(root, args.program_id)
            path, item = update_list_item_status(
                evidence_requests_path(root, args.program_id),
                f"{args.program_id}-evidence-requests",
                "research-orchestrator",
                args.evidence_id,
                status="fulfilled",
                note_key="result",
                note=args.result,
            )
            artifacts = normalize_list(args.artifact)
            if artifacts:
                items = list_items(path, f"{args.program_id}-evidence-requests", "research-orchestrator")
                for saved_item in items:
                    if str(saved_item.get("id") or "") == args.evidence_id:
                        saved_item["artifacts"] = sorted(set(normalize_list(saved_item.get("artifacts")) + artifacts))
                        item = saved_item
                        break
                write_list_items(path, f"{args.program_id}-evidence-requests", "research-orchestrator", items)
            append_program_reporting_event(
                root,
                args.program_id,
                {
                    "source_skill": "research-orchestrator",
                    "event_type": "evidence-fulfilled",
                    "title": str(item.get("question") or args.evidence_id),
                    "summary": args.result,
                    "stage": current_state.get("stage", ""),
                    "tags": ["evidence-request", "fulfilled"],
                    "artifacts": artifacts,
                },
                generated_by="research-orchestrator",
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(f"[ok] fulfilled {item.get('id')}")
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: resolve evidence {args.program_id}")
        return 0
    if args.command == "drop-evidence":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            path, item = update_list_item_status(
                evidence_requests_path(root, args.program_id),
                f"{args.program_id}-evidence-requests",
                "research-orchestrator",
                args.evidence_id,
                status="dropped",
                note_key="drop_reason",
                note=args.reason,
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(f"[ok] dropped {item.get('id')}")
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: drop evidence {args.program_id}")
        return 0
    if args.command == "log-decision":
        with program_file_lock(root, args.program_id):
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
            state = load_state(root, args.program_id)
            state["last_decision"] = {"decision": args.decision, "timestamp": item["timestamp"], "confirmation_status": args.confirmation_status}
            write_state(root, args.program_id, state)
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: log decision {args.program_id}")
        return 0
    if args.command == "add-reporting-event":
        with program_file_lock(root, args.program_id):
            ensure_program_files(root, args.program_id)
            current_state = load_state(root, args.program_id)
            path = append_program_reporting_event(
                root,
                args.program_id,
                {
                    "source_skill": "research-orchestrator",
                    "event_type": args.event_type,
                    "title": args.title,
                    "summary": args.summary,
                    "stage": args.stage or current_state.get("stage", ""),
                    "tags": normalize_list(args.tag),
                    "artifacts": normalize_list(args.artifact),
                },
                generated_by="research-orchestrator",
            )
            write_state(root, args.program_id, load_state(root, args.program_id))
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: add reporting event {args.program_id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

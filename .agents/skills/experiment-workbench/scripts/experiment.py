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
    load_list_document,
    normalize_list,
    write_text_if_changed,
)
from research.v2 import append_history, apply_confirmation, build_index, default_record, ensure_v2_workspace, locate_record, project_root, rel, write_record

RUN_OUTCOME_CHOICES = ["success", "partial", "failed", "blocked", "inconclusive"]
CLASSIFICATION_CHOICES = ["method", "implementation", "data", "evaluation", "resource", "environment", "process", "unknown"]
FOLLOW_UP_STATUS_CHOICES = ["open", "blocked", "done"]
FOLLOW_UP_PRIORITY_CHOICES = ["low", "normal", "high", "critical"]


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--evidence", action="append", required=True)


def parse_metrics(items: list[str]) -> dict[str, str]:
    payload = {}
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            payload[key] = value
    return payload


def list_document_path(unit_root: Path, name: str) -> Path:
    return unit_root / f"{name}.yaml"


def next_numbered_path(root: Path, prefix: str, suffix: str) -> Path:
    index = 1
    while True:
        path = root / f"{prefix}-{index:03d}{suffix}"
        if not path.exists():
            return path
        index += 1


def summarize_yaml_list(path: Path, *, title: str, rows: list[str]) -> None:
    lines = [f"# {title}", ""]
    lines.extend(rows or ["- 暂无条目"])
    write_text_if_changed(path, "\n".join(lines).strip() + "\n")


def sync_run_log_summary(unit_root: Path) -> None:
    payload = load_list_document(list_document_path(unit_root, "run-log"), f"{unit_root.name}-run-log", "experiment-workbench")
    rows = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            f"- `{item.get('id', '')}` · outcome={item.get('outcome', 'unknown')} · "
            f"classification={', '.join(item.get('classifications', [])) or 'unknown'} · "
            f"{item.get('result_summary', '')}"
        )
    summarize_yaml_list(unit_root / "run-log.md", title=f"Run Log: {unit_root.name}", rows=rows)


def sync_follow_up_summary(unit_root: Path) -> None:
    payload = load_list_document(list_document_path(unit_root, "follow-ups"), f"{unit_root.name}-follow-ups", "experiment-workbench")
    rows = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            f"- `{item.get('id', '')}` · status={item.get('status', 'open')} · "
            f"priority={item.get('priority', 'normal')} · category={item.get('category', 'unknown')} · "
            f"{item.get('action', '')}"
        )
    summarize_yaml_list(unit_root / "follow-ups.md", title=f"Follow-ups: {unit_root.name}", rows=rows)


def sync_diagnosis_summary(unit_root: Path) -> None:
    payload = load_list_document(list_document_path(unit_root, "diagnoses"), f"{unit_root.name}-diagnoses", "experiment-workbench")
    lines = [f"# Diagnosis: {unit_root.name}", ""]
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    if not items:
        lines.extend(
            [
                "- 当前最可能原因：待确认",
                "- 更像方法问题 / 实现问题 / 数据问题 / 资源问题：待确认",
                "- 已排除原因：",
                "- 未确认问题：",
                "- 下一步建议：",
            ]
        )
    else:
        for item in items[-5:]:
            lines.extend(
                [
                    f"## {item.get('id', '')} · {item.get('summary', '')}",
                    "",
                    f"- Categories: {', '.join(item.get('categories', [])) or 'unknown'}",
                    f"- Likely causes: {', '.join(item.get('likely_causes', [])) or '待确认'}",
                    f"- Ruled out: {', '.join(item.get('ruled_out_causes', [])) or '无'}",
                    f"- Unknowns: {', '.join(item.get('unknowns', [])) or '无'}",
                    f"- Next actions: {', '.join(item.get('next_actions', [])) or '无'}",
                    f"- Confirmation: `{item.get('confirmation_status', 'pending_user_confirmation')}`",
                    "",
                ]
            )
    write_text_if_changed(unit_root / "diagnosis.md", "\n".join(lines).strip() + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage experiment units in v2.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--title", required=True)
    plan.add_argument("--program-id", required=True)
    plan.add_argument("--goal", default="")
    plan.add_argument("--idea-id", default="")
    plan.add_argument("--hypothesis", default="")

    log_run = subparsers.add_parser("log-run")
    log_run.add_argument("--experiment-id", required=True)
    log_run.add_argument("--change", action="append", default=[])
    log_run.add_argument("--metric", action="append", default=[])
    log_run.add_argument("--result-summary", required=True)
    log_run.add_argument("--next-action", action="append", default=[])
    log_run.add_argument("--artifact", action="append", default=[])
    log_run.add_argument("--outcome", default="inconclusive", choices=RUN_OUTCOME_CHOICES)
    log_run.add_argument("--classification", action="append", default=[], choices=CLASSIFICATION_CHOICES)
    log_run.add_argument("--why-this-run", default="")
    log_run.add_argument("--tested-hypothesis", default="")

    follow_up = subparsers.add_parser("follow-up")
    follow_up.add_argument("--experiment-id", required=True)
    follow_up.add_argument("--action", required=True)
    follow_up.add_argument("--category", default="unknown", choices=CLASSIFICATION_CHOICES)
    follow_up.add_argument("--priority", default="normal", choices=FOLLOW_UP_PRIORITY_CHOICES)
    follow_up.add_argument("--status", default="open", choices=FOLLOW_UP_STATUS_CHOICES)
    follow_up.add_argument("--evidence-needed", action="append", default=[])

    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--experiment-id", required=True)
    diagnose.add_argument("--summary", default="Created diagnosis scaffold pending confirmation.")
    diagnose.add_argument("--category", action="append", default=[], choices=CLASSIFICATION_CHOICES)
    diagnose.add_argument("--likely-cause", action="append", default=[])
    diagnose.add_argument("--ruled-out", action="append", default=[])
    diagnose.add_argument("--unknown", action="append", default=[])
    diagnose.add_argument("--next-action", action="append", default=[])

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--experiment-id", required=True)
    add_confirmation_arguments(confirm)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    ensure_v2_workspace(root)

    if args.command == "plan":
        record = default_record("experiment", title=args.title, maturity="lightweight", source={"original_uri": f"program:{args.program_id}"})
        record["status"] = "planned"
        record["confirmation_status"] = "auto_confirmed"
        record["payload"]["basic_info"]["program_id"] = args.program_id
        record["payload"]["basic_info"]["idea_id"] = args.idea_id
        record["payload"]["basic_info"]["goal"] = args.goal
        record["payload"]["process"]["tested_hypothesis"] = args.hypothesis
        record["program_ids"] = [args.program_id]
        record["summary"] = args.goal or f"Planned experiment: {args.title}"
        path = write_record(root, record)
        build_index(root)
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "experiment-workbench",
                "event_type": "experiment-planned",
                "title": args.title,
                "summary": record["summary"],
                "stage": "experiment-design",
                "idea_ids": normalize_list([args.idea_id]),
                "artifacts": [rel(root, path)],
                "tags": ["experiment", "plan"],
            },
            generated_by="experiment-workbench",
        )
        print(path.relative_to(root))
        return 0

    record, path = locate_record(root, args.experiment_id, kind="experiment")
    if record.get("kind") != "experiment":
        raise SystemExit(f"{args.experiment_id} is not an experiment record")
    unit_root = path.parent

    if args.command == "log-run":
        runs_dir = unit_root / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_path = next_numbered_path(runs_dir, "run", ".md")
        write_text_if_changed(
            run_path,
            "\n".join(
                [
                    f"# Run for {record.get('title', '')}",
                    "",
                    "## Changes",
                    *[f"- {item}" for item in args.change],
                    "",
                    "## Result Summary",
                    f"- {args.result_summary}",
                    "",
                    "## Classification",
                    f"- Outcome: {args.outcome}",
                    *[f"- {item}" for item in normalize_list(args.classification)],
                    "",
                    "## Metrics",
                    *[f"- {item}" for item in args.metric],
                    "",
                    "## Artifacts",
                    *[f"- {item}" for item in normalize_list(args.artifact)],
                    "",
                    "## Next Actions",
                    *[f"- {item}" for item in args.next_action],
                    "",
                ]
            ).strip()
            + "\n",
        )
        run_log_path = append_list_item(
            list_document_path(unit_root, "run-log"),
            f"{args.experiment_id}-run-log",
            "experiment-workbench",
            {
                "result_summary": args.result_summary,
                "outcome": args.outcome,
                "classifications": normalize_list(args.classification) or ["unknown"],
                "changes": normalize_list(args.change),
                "metrics": parse_metrics(args.metric),
                "why_this_run": args.why_this_run,
                "tested_hypothesis": args.tested_hypothesis,
                "artifacts": [rel(root, run_path), *normalize_list(args.artifact)],
                "next_actions": normalize_list(args.next_action),
                "information_types": ["fact"],
            },
        )
        sync_run_log_summary(unit_root)
        record["status"] = "running"
        record["payload"]["process"]["change_summary"] = args.change
        record["payload"]["process"]["why_this_run"] = args.why_this_run
        record["payload"]["process"]["tested_hypothesis"] = args.tested_hypothesis
        record["payload"]["results"]["metrics"] = parse_metrics(args.metric)
        record["payload"]["results"]["artifacts"] = normalize_list(args.artifact)
        record["payload"]["results"]["met_expectation"] = "yes" if args.outcome == "success" else ("no" if args.outcome in {"failed", "blocked"} else "unknown")
        record["payload"]["results"]["abnormalities"] = normalize_list(args.classification)
        record["payload"]["diagnosis"]["next_actions"] = args.next_action
        record["summary"] = args.result_summary
        record.setdefault("artifacts", [])
        for artifact in [rel(root, run_path), rel(root, run_log_path)]:
            if artifact not in record["artifacts"]:
                record["artifacts"].append(artifact)
        append_history(record, action="experiment-run-logged", summary=args.result_summary, information_types=["fact"], artifacts=[rel(root, run_path), rel(root, run_log_path)])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-run",
                    "title": record.get("title", args.experiment_id),
                    "summary": args.result_summary,
                    "stage": "experiment-running",
                    "artifacts": [rel(root, run_path), rel(root, run_log_path)],
                    "tags": ["experiment", "run", args.outcome, *(normalize_list(args.classification) or ["unknown"])],
                },
                generated_by="experiment-workbench",
            )
        print(run_path.relative_to(root))
        return 0

    if args.command == "follow-up":
        follow_up_path = append_list_item(
            list_document_path(unit_root, "follow-ups"),
            f"{args.experiment_id}-follow-ups",
            "experiment-workbench",
            {
                "action": args.action,
                "category": args.category,
                "priority": args.priority,
                "status": args.status,
                "evidence_needed": normalize_list(args.evidence_needed),
                "information_types": ["fact", "unverified"],
            },
        )
        sync_follow_up_summary(unit_root)
        record["payload"]["diagnosis"]["next_actions"] = normalize_list(record["payload"]["diagnosis"].get("next_actions", [])) + [args.action]
        append_history(record, action="experiment-follow-up-added", summary=args.action, information_types=["fact", "unverified"], artifacts=[rel(root, follow_up_path)])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-follow-up",
                    "title": record.get("title", args.experiment_id),
                    "summary": args.action,
                    "stage": "experiment-follow-up",
                    "artifacts": [rel(root, follow_up_path)],
                    "tags": ["experiment", "follow-up", args.category, args.status],
                },
                generated_by="experiment-workbench",
            )
        print(follow_up_path.relative_to(root))
        return 0

    if args.command == "diagnose":
        diagnosis_path = append_list_item(
            list_document_path(unit_root, "diagnoses"),
            f"{args.experiment_id}-diagnoses",
            "experiment-workbench",
            {
                "summary": args.summary,
                "categories": normalize_list(args.category) or ["unknown"],
                "likely_causes": normalize_list(args.likely_cause),
                "ruled_out_causes": normalize_list(args.ruled_out),
                "unknowns": normalize_list(args.unknown),
                "next_actions": normalize_list(args.next_action),
                "confirmation_status": "pending_user_confirmation",
                "information_types": ["inference", "evaluation", "unverified"],
            },
        )
        sync_diagnosis_summary(unit_root)
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        record["payload"]["diagnosis"]["failure_modes"] = normalize_list(args.category) or ["unknown"]
        record["payload"]["diagnosis"]["likely_causes"] = normalize_list(args.likely_cause)
        record["payload"]["diagnosis"]["ruled_out_causes"] = normalize_list(args.ruled_out)
        record["payload"]["diagnosis"]["unknowns"] = normalize_list(args.unknown)
        record["payload"]["diagnosis"]["next_actions"] = normalize_list(args.next_action)
        append_history(record, action="experiment-diagnosed", summary=args.summary, information_types=["inference", "evaluation", "unverified"], artifacts=[rel(root, diagnosis_path), rel(root, unit_root / "diagnosis.md")])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-diagnosis",
                    "title": record.get("title", args.experiment_id),
                    "summary": args.summary,
                    "stage": "experiment-diagnosis",
                    "artifacts": [rel(root, diagnosis_path), rel(root, unit_root / "diagnosis.md")],
                    "tags": ["experiment", "diagnosis", *(normalize_list(args.category) or ["unknown"])],
                },
                generated_by="experiment-workbench",
            )
        print(diagnosis_path.relative_to(root))
        return 0

    if args.command == "confirm":
        record = apply_confirmation(record, confirmed_by=args.confirmed_by, evidence=args.evidence, method="experiment.py confirm")
        if record.get("status") == "running":
            record["status"] = "completed"
        append_history(record, action="experiment-confirmed", summary="Experiment findings confirmed by user.", information_types=["fact"])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-confirmed",
                    "title": record.get("title", args.experiment_id),
                    "summary": "Experiment findings confirmed by user.",
                    "stage": "experiment-confirmed",
                    "artifacts": [rel(root, path)],
                    "tags": ["experiment", "confirmed"],
                },
                generated_by="experiment-workbench",
            )
        print(f"[ok] confirmed {args.experiment_id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

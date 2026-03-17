#!/usr/bin/env python3
"""Bootstrap and maintain the research v1.1 workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    bootstrap_program,
    bootstrap_workspace,
    current_runtime_capabilities,
    ensure_research_runtime,
    find_project_root,
    format_runtime_report,
    inspect_python_runtime,
    load_list_document,
    load_runtime_registry,
    load_yaml,
    preferred_runtime_record,
    remember_runtime as remember_runtime_record,
    research_root,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)

DEFAULT_STAGES = (
    "problem-framing",
    "literature-analysis",
    "idea-generation",
    "idea-review",
    "method-design",
    "implementation-planning",
)


def existing_program_root(project_root: Path, program_id: str) -> Path:
    path = research_root(project_root) / "programs" / program_id
    if not path.exists():
        raise SystemExit(f"Program not found: {program_id}")
    return path


def monthly_history_path(project_root: Path) -> Path:
    stamp = utc_now_iso()[:7]
    return research_root(project_root) / "memory" / "history" / f"{stamp}.yaml"


def landscape_report_path(project_root: Path, survey_id: str) -> Path:
    return research_root(project_root) / "library" / "landscapes" / survey_id / "landscape-report.yaml"


def append_history(project_root: Path, event: dict[str, Any]) -> None:
    path = monthly_history_path(project_root)
    payload = load_list_document(path, f"history-{path.stem}", "research-conductor")
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(event)
    write_yaml_if_changed(path, payload)


def append_decision_log_entry(project_root: Path, program_id: str, stage: str, summary: str) -> None:
    program_root = existing_program_root(project_root, program_id)
    path = program_root / "workflow" / "decision-log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Decision Log\n\n"
    entry = f"- {utc_now_iso()}: [{stage}] {summary}\n"
    write_text_if_changed(path, existing + entry)


def init_workspace(_: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    print(f"[ok] initialized research workspace at {(research_root(project_root)).as_posix()}")
    return 0


def create_program(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    constraints = {"compute": args.compute, "data": args.data, "hardware": args.hardware}
    program_root = bootstrap_program(
        project_root,
        args.program_id,
        question=args.question,
        goal=args.goal,
        constraints=constraints,
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "program-created",
            "program_id": args.program_id,
            "question": args.question,
        },
    )
    print(f"[ok] prepared program at {program_root.as_posix()}")
    return 0


def set_profile(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    profile_path = research_root(project_root) / "memory" / "user-profile.yaml"
    payload = load_yaml(profile_path, default={})
    if not isinstance(payload, dict):
        payload = {**yaml_default("user-profile", "research-conductor", status="active")}
    payload["generated_at"] = utc_now_iso()
    payload[args.field] = args.value
    write_yaml_if_changed(profile_path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "profile-updated",
            "field": args.field,
            "value": args.value,
        },
    )
    print(f"[ok] updated user profile field {args.field}")
    return 0


def set_preference(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    if args.scope == "global":
        pref_path = research_root(project_root) / "memory" / "skill-preferences.yaml"
        payload = load_yaml(pref_path, default={})
        if not isinstance(payload, dict):
            payload = {**yaml_default("skill-preferences", "research-conductor", status="active")}
        payload.setdefault("preferences", {})
        payload["preferences"].setdefault(args.target, {})
        payload["preferences"][args.target][args.key] = args.value
    else:
        pref_path = research_root(project_root) / "programs" / args.program_id / "workflow" / "preferences.yaml"
        payload = load_yaml(pref_path, default={})
        if not isinstance(payload, dict):
            payload = {
                **yaml_default(f"{args.program_id}-preferences", "research-conductor"),
                "preferences": {},
            }
        payload.setdefault("preferences", {})
        payload["preferences"][args.key] = args.value
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(pref_path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "preference-updated",
            "scope": args.scope,
            "target": args.target if args.scope == "global" else args.program_id,
            "key": args.key,
            "value": args.value,
        },
    )
    print(f"[ok] updated {args.scope} preference {args.key}")
    return 0


def append_decision(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    append_decision_log_entry(project_root, args.program_id, args.stage, args.summary)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "decision-log-entry",
            "program_id": args.program_id,
            "stage": args.stage,
            "summary": args.summary,
        },
    )
    print(f"[ok] appended decision for program {args.program_id}")
    return 0


def load_candidate_program(project_root: Path, survey_id: str, *, program_seed_id: str, candidate_index: int | None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    report_path = landscape_report_path(project_root, survey_id)
    payload = load_yaml(report_path, default={})
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid landscape report: {report_path}")
    candidates = payload.get("candidate_programs", [])
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit(f"No candidate programs found in landscape report: {report_path}")

    seed: dict[str, Any] | None = None
    if candidate_index is not None:
        zero_index = candidate_index - 1
        if zero_index < 0 or zero_index >= len(candidates):
            raise SystemExit(f"--candidate-index out of range for {report_path}")
        item = candidates[zero_index]
        if isinstance(item, dict):
            seed = item
    elif program_seed_id:
        for item in candidates:
            if isinstance(item, dict) and str(item.get("program_seed_id") or "") == program_seed_id:
                seed = item
                break

    if seed is None:
        available = ", ".join(
            str(item.get("program_seed_id") or f"candidate-{idx + 1}")
            for idx, item in enumerate(candidates)
            if isinstance(item, dict)
        )
        raise SystemExit(f"Candidate program not found in {report_path}. Available: {available}")
    return report_path, payload, seed


def create_program_from_landscape(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    report_path, report_payload, seed = load_candidate_program(
        project_root,
        args.survey_id,
        program_seed_id=args.program_seed_id,
        candidate_index=args.candidate_index,
    )
    program_id = args.program_id or str(seed.get("program_seed_id") or "") or slugify(str(seed.get("title") or "landscape-program"), max_words=8)
    constraints = {"compute": args.compute, "data": args.data, "hardware": args.hardware}
    program_root = bootstrap_program(
        project_root,
        program_id,
        question=str(seed.get("question") or ""),
        goal=str(seed.get("goal") or ""),
        constraints=constraints,
    )

    report_rel = report_path.relative_to(project_root).as_posix()
    charter_path = program_root / "charter.yaml"
    charter = load_yaml(charter_path, default={})
    if not isinstance(charter, dict):
        charter = {
            **yaml_default(program_id, "research-conductor", status="active"),
            "program_id": program_id,
        }
    charter["generated_at"] = utc_now_iso()
    charter["inputs"] = [
        report_rel,
        *[f"lit:{item}" for item in seed.get("literature_refs", []) if str(item).strip()],
        *[f"repo:{item}" for item in seed.get("repo_refs", []) if str(item).strip()],
    ]
    charter["seed_context"] = {
        "survey_id": args.survey_id,
        "program_seed_id": seed.get("program_seed_id", ""),
        "title": seed.get("title", ""),
        "why_now": seed.get("why_now", ""),
        "suggested_tags": seed.get("suggested_tags", []),
        "bootstrap_prompt": seed.get("bootstrap_prompt", ""),
        "field": report_payload.get("field", ""),
        "scope": report_payload.get("scope", ""),
    }
    write_yaml_if_changed(charter_path, charter)

    state_path = program_root / "workflow" / "state.yaml"
    state = load_yaml(state_path, default={})
    if not isinstance(state, dict):
        state = {
            **yaml_default(f"{program_id}-state", "research-conductor", status="active"),
            "program_id": program_id,
            "stage": "problem-framing",
            "active_idea_id": "",
            "selected_idea_id": "",
            "selected_repo_id": "",
        }
    state["generated_at"] = utc_now_iso()
    state["inputs"] = [charter_path.relative_to(project_root).as_posix(), report_rel]
    state["stage"] = "problem-framing"
    write_yaml_if_changed(state_path, state)

    append_decision_log_entry(
        project_root,
        program_id,
        "problem-framing",
        (
            f"Program bootstrapped from landscape survey `{args.survey_id}` candidate "
            f"`{seed.get('program_seed_id', '') or seed.get('title', '')}`."
        ),
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "program-created-from-landscape",
            "program_id": program_id,
            "survey_id": args.survey_id,
            "program_seed_id": seed.get("program_seed_id", ""),
            "field": report_payload.get("field", ""),
        },
    )
    print(f"[ok] prepared program from landscape seed at {program_root.as_posix()}")
    return 0


def add_evidence_request(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    program_root = existing_program_root(project_root, args.program_id)
    path = program_root / "workflow" / "evidence-requests.yaml"
    payload = load_list_document(path, f"{args.program_id}-evidence-requests", "research-conductor")
    payload["generated_at"] = utc_now_iso()
    payload["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root))]
    payload["items"].append(
        {
            "request_id": args.request_id,
            "priority": args.priority,
            "blocking_reason": args.blocking_reason,
            "suggested_skill": args.suggested_skill,
            "notes": args.notes,
            "status": "open",
        }
    )
    write_yaml_if_changed(path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "evidence-request-added",
            "program_id": args.program_id,
            "request_id": args.request_id,
        },
    )
    print(f"[ok] added evidence request {args.request_id}")
    return 0


def set_stage(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    program_root = existing_program_root(project_root, args.program_id)
    path = program_root / "workflow" / "state.yaml"
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict):
        payload = {
            **yaml_default(f"{args.program_id}-state", "research-conductor", status="active"),
            "program_id": args.program_id,
            "stage": "problem-framing",
            "active_idea_id": "",
            "selected_idea_id": "",
            "selected_repo_id": "",
        }
    payload["generated_at"] = utc_now_iso()
    payload["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root))]
    payload["stage"] = args.stage
    for field in ("active_idea_id", "selected_idea_id", "selected_repo_id"):
        value = getattr(args, field)
        if value is not None:
            payload[field] = value
    write_yaml_if_changed(path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "stage-updated",
            "program_id": args.program_id,
            "stage": args.stage,
            "active_idea_id": payload.get("active_idea_id", ""),
            "selected_idea_id": payload.get("selected_idea_id", ""),
            "selected_repo_id": payload.get("selected_repo_id", ""),
        },
    )
    print(f"[ok] set stage for program {args.program_id} to {args.stage}")
    return 0


def add_open_question(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    program_root = existing_program_root(project_root, args.program_id)
    path = program_root / "workflow" / "open-questions.yaml"
    payload = load_list_document(path, f"{args.program_id}-open-questions", "research-conductor")
    payload["generated_at"] = utc_now_iso()
    payload["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root))]
    payload["items"].append(
        {
            "question_id": args.question_id,
            "question": args.question,
            "owner": args.owner,
            "notes": args.notes,
            "status": "open",
        }
    )
    write_yaml_if_changed(path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "open-question-added",
            "program_id": args.program_id,
            "question_id": args.question_id,
        },
    )
    print(f"[ok] added open question {args.question_id}")
    return 0


def remember_runtime(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    record = remember_runtime_record(
        project_root,
        args.python or sys.executable,
        label=args.label,
        notes=args.notes,
        set_default=not args.no_set_default,
    )
    preferred = preferred_runtime_record(project_root)
    print("[ok] remembered research runtime")
    print(format_runtime_report(record))
    if preferred and preferred.get("runtime_id") == record.get("runtime_id"):
        print("preferred: true")
    return 0


def show_runtime(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    registry = load_runtime_registry(project_root)
    runtime_id = args.runtime_id or registry.get("preferred_runtime_id", "")
    if runtime_id:
        record = registry["items"].get(runtime_id)
        if not isinstance(record, dict):
            raise SystemExit(f"Runtime not found: {runtime_id}")
        print(format_runtime_report(record))
        print(f"preferred: {runtime_id == registry.get('preferred_runtime_id', '')}")
        return 0

    current = current_runtime_capabilities()
    print(format_runtime_report({**current, "runtime_id": "current", "label": "current"}))
    print("preferred: false")
    return 0


def check_runtime(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    if args.python:
        status = inspect_python_runtime(args.python)
        status.setdefault("runtime_id", "probe")
        status.setdefault("label", args.label or "probe")
    else:
        status = {
            **current_runtime_capabilities(),
            "runtime_id": "current",
            "label": args.label or "current",
        }
    print(format_runtime_report(status))
    missing: list[str] = []
    if not status.get("yaml_support"):
        missing.append("PyYAML")
    if args.require_pdf and not status.get("pdf_support"):
        missing.append("PyPDF2 or pypdf")
    if missing:
        print(f"ready: false ({', '.join(missing)} missing)")
        preferred = preferred_runtime_record(project_root)
        if preferred:
            print(
                "hint: remembered preferred runtime -> "
                f"{preferred.get('label', '') or preferred.get('runtime_id', '')} @ {preferred.get('python', '')}"
            )
        return 1
    print("ready: true")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the research v1.1 workspace and program state.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init-workspace", help="Create the shared research workspace skeleton")
    init_cmd.set_defaults(func=init_workspace)

    create_cmd = subparsers.add_parser("create-program", help="Create a new program workspace")
    create_cmd.add_argument("--program-id", required=True)
    create_cmd.add_argument("--question", required=True)
    create_cmd.add_argument("--goal", required=True)
    create_cmd.add_argument("--compute", default="")
    create_cmd.add_argument("--data", default="")
    create_cmd.add_argument("--hardware", default="")
    create_cmd.set_defaults(func=create_program)

    create_from_landscape_cmd = subparsers.add_parser(
        "create-program-from-landscape",
        help="Create a new program from a research-landscape-analyst candidate program seed",
    )
    create_from_landscape_cmd.add_argument("--survey-id", required=True)
    seed_selector = create_from_landscape_cmd.add_mutually_exclusive_group(required=True)
    seed_selector.add_argument("--program-seed-id", default="")
    seed_selector.add_argument("--candidate-index", type=int, default=None)
    create_from_landscape_cmd.add_argument("--program-id", default="")
    create_from_landscape_cmd.add_argument("--compute", default="")
    create_from_landscape_cmd.add_argument("--data", default="")
    create_from_landscape_cmd.add_argument("--hardware", default="")
    create_from_landscape_cmd.set_defaults(func=create_program_from_landscape)

    profile_cmd = subparsers.add_parser("set-profile", help="Update a field on memory/user-profile.yaml")
    profile_cmd.add_argument("--field", required=True)
    profile_cmd.add_argument("--value", required=True)
    profile_cmd.set_defaults(func=set_profile)

    pref_cmd = subparsers.add_parser("set-preference", help="Update global or program preferences")
    pref_cmd.add_argument("--scope", choices=["global", "program"], required=True)
    pref_cmd.add_argument("--target", default="", help="Skill name for global preferences")
    pref_cmd.add_argument("--program-id", default="")
    pref_cmd.add_argument("--key", required=True)
    pref_cmd.add_argument("--value", required=True)
    pref_cmd.set_defaults(func=set_preference)

    decision_cmd = subparsers.add_parser("append-decision", help="Append a markdown decision log entry")
    decision_cmd.add_argument("--program-id", required=True)
    decision_cmd.add_argument("--stage", required=True)
    decision_cmd.add_argument("--summary", required=True)
    decision_cmd.set_defaults(func=append_decision)

    request_cmd = subparsers.add_parser("add-evidence-request", help="Create a new evidence request")
    request_cmd.add_argument("--program-id", required=True)
    request_cmd.add_argument("--request-id", required=True)
    request_cmd.add_argument("--priority", default="medium")
    request_cmd.add_argument("--blocking-reason", required=True)
    request_cmd.add_argument("--suggested-skill", default="literature-scout")
    request_cmd.add_argument("--notes", default="")
    request_cmd.set_defaults(func=add_evidence_request)

    stage_cmd = subparsers.add_parser("set-stage", help="Update workflow/state.yaml for a program")
    stage_cmd.add_argument("--program-id", required=True)
    stage_cmd.add_argument("--stage", required=True, choices=DEFAULT_STAGES)
    stage_cmd.add_argument("--active-idea-id", default=None)
    stage_cmd.add_argument("--selected-idea-id", default=None)
    stage_cmd.add_argument("--selected-repo-id", default=None)
    stage_cmd.set_defaults(func=set_stage)

    question_cmd = subparsers.add_parser("add-open-question", help="Append an open question for a program")
    question_cmd.add_argument("--program-id", required=True)
    question_cmd.add_argument("--question-id", required=True)
    question_cmd.add_argument("--question", required=True)
    question_cmd.add_argument("--owner", default="research-conductor")
    question_cmd.add_argument("--notes", default="")
    question_cmd.set_defaults(func=add_open_question)

    remember_runtime_cmd = subparsers.add_parser(
        "remember-runtime",
        help="Validate and remember a research Python runtime for future skill runs",
    )
    remember_runtime_cmd.add_argument("--python", default="", help="Python executable to validate and store")
    remember_runtime_cmd.add_argument("--label", default="research-default")
    remember_runtime_cmd.add_argument("--notes", default="")
    remember_runtime_cmd.add_argument("--no-set-default", action="store_true")
    remember_runtime_cmd.set_defaults(func=remember_runtime)

    show_runtime_cmd = subparsers.add_parser(
        "show-runtime",
        help="Show the preferred remembered runtime or a named runtime record",
    )
    show_runtime_cmd.add_argument("--runtime-id", default="")
    show_runtime_cmd.set_defaults(func=show_runtime)

    check_runtime_cmd = subparsers.add_parser(
        "check-runtime",
        help="Check whether a Python runtime satisfies research skill requirements",
    )
    check_runtime_cmd.add_argument("--python", default="", help="Optional Python executable to probe")
    check_runtime_cmd.add_argument("--label", default="")
    check_runtime_cmd.add_argument("--require-pdf", action="store_true")
    check_runtime_cmd.set_defaults(func=check_runtime)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

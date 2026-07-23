#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
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

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import (
    add_project_root_argument,
    append_list_item,
    append_program_reporting_event,
    blank_list_document,
    blank_reporting_events,
    confirm_command as confirm_command_for_record,
    ensure_dir,
    load_list_document,
    load_yaml,
    normalize_list,
    print_resolved_project_roots,
    shell_command,
    simple_slug,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)
from research.core import apply_confirmation, append_history, ensure_workspace, is_ready_for_human_review, iter_records, kb_root, load_runtime_preferences, locate_record, checkpoint_and_report, project_root, record_workflow_state, write_record
from research.evidence import attach_claims, build_verification_receipt, validate_claims, verify_claim_evidence
from research.judgements import apply_judgement_rejection, confirmation_binding, readiness_violations, require_judgement_snapshot
from research.journal import mutation_transaction

OPEN_QUESTION_OPEN_STATUSES = {"open"}
EVIDENCE_REQUEST_OPEN_STATUSES = {"open"}
PRIORITY_SCORE = {"critical": 40, "high": 30, "normal": 10, "low": 5}
TERMINAL_PROGRAM_STAGES = {"done", "completed", "archived", "published"}
SEMANTIC_READ_COMMANDS = {"status", "dashboard", "next", "route"}

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
    "新数据集": "source-intake",
    "新 dataset": "source-intake",
    "new dataset": "source-intake",
    "新博客": "source-intake",
    "新 blog": "source-intake",
    "new blog": "source-intake",
    "论文": "paper-analyst",
    "paper": "paper-analyst",
    "仓库": "repo-analyst",
    "repo": "repo-analyst",
    "数据集": "dataset-analyst",
    "dataset": "dataset-analyst",
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

COMMAND_PREFIX = "${RESEARCH_PYTHON:-python3}"
# Governance cap: runtime preferences may narrow this scope, but cannot add steps
# beyond this set.
GOVERNANCE_MAX_AUTO_STEPS = {"screen", "build-index", "refresh", "generate-note"}
ROOT_AWARE_AUTO_SCRIPTS = {
    ".agents/skills/blog-analyst/scripts/blog.py",
    ".agents/skills/dataset-analyst/scripts/dataset.py",
    ".agents/skills/discussion-archivist/scripts/archive.py",
    ".agents/skills/experiment-workbench/scripts/experiment.py",
    ".agents/skills/idea-workbench/scripts/idea.py",
    ".agents/skills/knowledge-base-manager/scripts/kb.py",
    ".agents/skills/literature-synthesizer/scripts/synthesize.py",
    ".agents/skills/method-designer/scripts/method.py",
    ".agents/skills/paper-analyst/scripts/paper.py",
    ".agents/skills/repo-analyst/scripts/repo.py",
    ".agents/skills/research-config-manager/scripts/config.py",
    ".agents/skills/research-navigator/scripts/navigate.py",
    ".agents/skills/research-orchestrator/scripts/orchestrate.py",
    ".agents/skills/source-intake/scripts/intake.py",
    ".agents/skills/wiki-adapter/scripts/wiki.py",
}


def executable_command(parts: list[str]) -> list[str]:
    command = list(parts)
    if command and command[0] == COMMAND_PREFIX:
        command[0] = sys.executable or "python3"
    return command


def accepts_project_root_argument(script: str) -> bool:
    normalized = script.replace(os.sep, "/")
    return normalized in ROOT_AWARE_AUTO_SCRIPTS or any(
        normalized.endswith(f"/{root_aware_script}")
        for root_aware_script in ROOT_AWARE_AUTO_SCRIPTS
    )


def command_with_project_root(parts: list[str], root: Path) -> list[str]:
    command = list(parts)
    for part in command:
        if accepts_project_root_argument(part):
            cleaned: list[str] = []
            cursor = 0
            while cursor < len(command):
                if command[cursor] == "--root":
                    cursor += 2
                    continue
                cleaned.append(command[cursor])
                cursor += 1
            script_index = next(
                cleaned_index
                for cleaned_index, cleaned_part in enumerate(cleaned)
                if accepts_project_root_argument(cleaned_part)
            )
            return [
                *cleaned[: script_index + 1],
                "--root",
                str(root),
                *cleaned[script_index + 1 :],
            ]
    return command


def command_for_dashboard_item(item: dict[str, Any]) -> str:
    command = str(item.get("recommended_command") or "").strip()
    if command:
        return command
    program_id = str(item.get("program_id") or "")
    if program_id:
        return shell_command([COMMAND_PREFIX, ".agents/skills/research-orchestrator/scripts/orchestrate.py", "status", "--program-id", program_id])
    return ""


def full_note_status(record: dict[str, Any]) -> str:
    payload = record.get("payload", {})
    state = payload.get("state", {}) if isinstance(payload, dict) else {}
    return str(state.get("full_note_status") or "") if isinstance(state, dict) else ""


def is_user_confirmable(record: dict[str, Any]) -> bool:
    return is_ready_for_human_review(record)


def safe_unit_step(record: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    status = str(record.get("status") or "")
    note_status = full_note_status(record) if kind == "paper" else ""
    workflow_state = record_workflow_state(record)
    if workflow_state == "done":
        return None
    if workflow_state in {"awaiting_agent_fill", "ready_to_verify"}:
        return {
            "kind": "agent-work",
            "step_type": "agent-fill" if workflow_state == "awaiting_agent_fill" else "agent-verify",
            "record_id": unit_id,
            "title": str(record.get("title") or ""),
            "reason": (
                f"资料「{record.get('title') or unit_id}」（{unit_id}）需要 Agent 补全分析。"
                if workflow_state == "awaiting_agent_fill"
                else f"资料「{record.get('title') or unit_id}」（{unit_id}）需要 Agent 核验逐字证据。"
            ),
            "command_parts": [],
            "safe_execute": False,
        }
    if workflow_state == "ready_for_review":
        return {
            "kind": "human-gate",
            "step_type": "human-decision",
            "record_id": unit_id,
            "title": str(record.get("title") or ""),
            "reason": f"资料「{record.get('title') or unit_id}」（{unit_id}）已有经过核验的判断，等待你确认。",
            # Single confirm renderer (research.common.confirm_command via the
            # confirm_command_for_record alias): analyzer confirm for paper/repo/dataset/blog,
            # else kb.py promote --confirmation-status confirmed. Keeps `kb next` in
            # lockstep with `kb find` / `kb review` — no hand-copied confirm command (F5).
            "recommended_command": confirm_command_for_record(record),
            "command_parts": [],
            "safe_execute": False,
        }
    if kind == "paper":
        payload = record.get("payload", {})
        quick = payload.get("quick_screen", {}) if isinstance(payload, dict) else {}
        if not str(quick.get("screening_mode") or "").strip() and not quick.get("judgement_reason"):
            return {
                "kind": kind,
                "step_type": "screen",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "reason": f"unscreened paper `{unit_id}`",
                "command_parts": [
                    COMMAND_PREFIX,
                    ".agents/skills/paper-analyst/scripts/paper.py",
                    "screen",
                    "--paper-id",
                    unit_id,
                ],
                "safe_execute": True,
            }
        if note_status == "not_started":
            return {
                "kind": kind,
                "step_type": "generate-note",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "reason": f"screened paper `{unit_id}` lacks a complete note",
                "command_parts": [
                    COMMAND_PREFIX,
                    ".agents/skills/paper-analyst/scripts/paper.py",
                    "complete-note",
                    "--paper-id",
                    unit_id,
                    "--mode",
                    "auto",
                ],
                "safe_execute": True,
            }
    if kind == "repo":
        payload = record.get("payload", {})
        structure = payload.get("structure", {}) if isinstance(payload, dict) else {}
        if (
            str(structure.get("scan_status") or "not_started") == "not_started"
            and str(structure.get("scan_applicability") or "unknown") == "applicable"
        ):
            return {
                "kind": kind,
                "step_type": "refresh",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "reason": f"repo `{unit_id}` lacks structure scan",
                "command_parts": [
                    COMMAND_PREFIX,
                    ".agents/skills/repo-analyst/scripts/repo.py",
                    "scan-structure",
                    "--repo-id",
                    unit_id,
                ],
                "safe_execute": True,
            }
        state = payload.get("state", {}) if isinstance(payload, dict) else {}
        if str(state.get("capability_fill_status") or "not_started") == "not_started":
            return {
                "kind": kind,
                "step_type": "generate-note",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "reason": f"repo `{unit_id}` needs an agent-filled capability map",
                "command_parts": [
                    COMMAND_PREFIX,
                    ".agents/skills/repo-analyst/scripts/repo.py",
                    "map-capability",
                    "--repo-id",
                    unit_id,
                    "--phase",
                    "prepare",
                ],
                "safe_execute": True,
            }
    if kind == "dataset" and workflow_state == "source_ready":
        return {
            "kind": kind,
            "step_type": "generate-note",
            "record_id": unit_id,
            "title": str(record.get("title") or ""),
            "reason": f"数据集「{record.get('title') or unit_id}」（{unit_id}）已有数据卡，等待 Agent 整理有逐字证据支持的数据画像。",
            "command_parts": [
                COMMAND_PREFIX,
                ".agents/skills/dataset-analyst/scripts/dataset.py",
                "profile",
                "--dataset-id",
                unit_id,
                "--phase",
                "prepare",
            ],
            "safe_execute": True,
        }
    if kind == "blog" and (workflow_state == "source_ready" or status == "draft"):
        return {
            "kind": kind,
            "step_type": "generate-note",
            "record_id": unit_id,
            "title": str(record.get("title") or ""),
            "reason": f"博客「{record.get('title') or unit_id}」（{unit_id}）已有原始资料，等待 Agent 整理有逐字证据支持的摘要。",
            "command_parts": [
                COMMAND_PREFIX,
                ".agents/skills/blog-analyst/scripts/blog.py",
                "complete-note",
                "--blog-id",
                unit_id,
            ],
            "safe_execute": True,
        }
    if kind == "idea":
        payload = record.get("payload", {})
        analysis = payload.get("analysis", {}) if isinstance(payload, dict) else {}
        review = payload.get("review", {}) if isinstance(payload, dict) else {}
        if status == "draft" and not str(analysis.get("novelty") or ""):
            return {
                "kind": kind,
                "step_type": "refresh",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "reason": f"idea `{unit_id}` needs analysis",
                "command_parts": [
                    COMMAND_PREFIX,
                    ".agents/skills/idea-workbench/scripts/idea.py",
                    "analyze",
                    "--idea-id",
                    unit_id,
                ],
                "safe_execute": True,
            }
        if status == "pending" and str(review.get("review_status") or "not_started") == "not_started":
            return {
                "kind": kind,
                "step_type": "refresh",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "reason": f"idea `{unit_id}` needs review artifact",
                "command_parts": [
                    COMMAND_PREFIX,
                    ".agents/skills/idea-workbench/scripts/idea.py",
                    "review",
                    "--idea-id",
                    unit_id,
                ],
                "safe_execute": True,
            }
    return None


def auto_plan(root: Path) -> dict[str, Any]:
    build_index_command = {
        "kind": "kb",
        "step_type": "build-index",
        "record_id": "",
        "title": "Build KB index",
        "reason": "KB has records but index should be refreshed before deeper orchestration",
        "command_parts": [COMMAND_PREFIX, ".agents/skills/knowledge-base-manager/scripts/kb.py", "index"],
        "safe_execute": True,
    }
    records = iter_records(root)
    if not records:
        return {
            "status": "empty",
            "message": "KB 为空，第一步：告诉 AI 一篇论文的来源（链接或文件），或运行 kb ingest",
            "command_parts": [
                COMMAND_PREFIX,
                ".agents/skills/source-intake/scripts/intake.py",
                "add",
                "--kind",
                "paper",
                "--source",
                "${RESEARCH_SOURCE:?set-paper-source}",
            ],
            "safe_execute": False,
        }
    for record in records:
        step = safe_unit_step(record)
        if step:
            return {"status": "planned", **step}
    return {"status": "planned", **build_index_command}


def format_auto_plan(plan: dict[str, Any]) -> str:
    lines = ["# Orchestrate Auto", ""]
    message = str(plan.get("message") or plan.get("reason") or "")
    if message:
        lines.append(f"- next: {message}")
    if not bool(plan.get("safe_execute")):
        lines.append("- execute: stop for human decision")
    else:
        lines.append(f"- execute: safe {plan.get('step_type')}；让 AI 执行即可")
    return "\n".join(lines).strip()


def execute_auto_plan(root: Path, plan: dict[str, Any]) -> int:
    if not bool(plan.get("safe_execute")):
        print(format_auto_plan(plan))
        print("[stop] human decision required; not executing")
        return 0
    step_type = str(plan.get("step_type") or "")
    try:
        configured_scope = load_runtime_preferences(root).get("autonomy", {}).get("auto_execute_scope", [])
    except Exception:  # noqa: BLE001
        configured_scope = sorted(GOVERNANCE_MAX_AUTO_STEPS)
    if not isinstance(configured_scope, list):
        configured_scope = sorted(GOVERNANCE_MAX_AUTO_STEPS)
    effective_scope = {str(item).strip() for item in configured_scope if str(item).strip()} & GOVERNANCE_MAX_AUTO_STEPS
    if step_type not in effective_scope:
        print(format_auto_plan(plan))
        print("[stop] step is not in the safe auto-execute allowlist")
        return 0
    command_parts = [str(part) for part in plan.get("command_parts") or []]
    print(format_auto_plan(plan))
    child_env = {**os.environ, "RESEARCH_PROJECT_ROOT": str(root)}
    child_command = command_with_project_root(command_parts, root)
    result = subprocess.run(
        executable_command(child_command),
        cwd=root,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.strip():
            print(f"[exec] {line}")
    for line in result.stderr.splitlines():
        if line.strip():
            print(f"[exec:err] {line}")
    return result.returncode


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


def decisions_path(root: Path, program_id: str) -> Path:
    return workflow_root(root, program_id) / "decisions.yaml"


def legacy_decision_items(root: Path, program_id: str) -> list[dict[str, Any]]:
    """Read old markdown decisions as pending/unverified migration records.

    A legacy ``confirmed`` label is preserved only as audit metadata and never
    trusted as confirmation.
    """
    path = decision_log_path(root, program_id)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s+·\s+(.+?)\s*$", text))
    items: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        timestamp, decision_text = match.group(1).strip(), match.group(2).strip()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : block_end]

        def field(label: str) -> str:
            found = re.search(rf"(?m)^-\s+{re.escape(label)}:\s*(.*?)\s*$", block)
            return found.group(1).strip().strip("`") if found else ""

        explicit_id = field("Decision ID")
        decision_id = explicit_id or "decision-legacy-" + hashlib.sha256(
            f"{program_id}\n{timestamp}\n{decision_text}".encode("utf-8")
        ).hexdigest()[:12]
        original_confirmation = field("Confirmation")
        items.append(
            {
                "id": decision_id,
                "kind": "program_decision",
                "timestamp": timestamp,
                "program_id": program_id,
                "evidence": normalize_list(field("Evidence")),
                "confirmation_status": "pending_user_confirmation",
                "needs_human_confirmation": True,
                "information_types": ["inference", "evaluation", "unverified"],
                "payload": {
                    "decision": {
                        "text": decision_text,
                        "rationale": field("Rationale"),
                        "stage": field("Stage"),
                        "alternatives": normalize_list(field("Alternatives")),
                    }
                },
                "legacy_import": {
                    "source": path.relative_to(root).as_posix(),
                    "original_confirmation_status": original_confirmation,
                    "trust": "pending_unverified",
                },
            }
        )
    return items


def decision_items_with_legacy(root: Path, program_id: str) -> list[dict[str, Any]]:
    canonical = list_items(
        decisions_path(root, program_id),
        f"{program_id}-decisions",
        "research-orchestrator",
    )
    by_id = {str(item.get("id") or ""): item for item in canonical}
    for legacy in legacy_decision_items(root, program_id):
        by_id.setdefault(str(legacy["id"]), legacy)
    return list(by_id.values())


def program_checkpoint_paths(root: Path, program_id: str, *extra: Path) -> list[Path]:
    """Complete, explicit path set for one program-scoped mutation."""
    return [
        state_path(root, program_id),
        open_questions_path(root, program_id),
        evidence_requests_path(root, program_id),
        reporting_events_path(root, program_id),
        decisions_path(root, program_id),
        decision_log_path(root, program_id),
        *extra,
    ]


@contextmanager
def program_mutation(root: Path, program_id: str, operation: str, *extra_targets: Path):
    """Run one program mutation through the canonical exact-path transaction."""
    targets = program_checkpoint_paths(root, program_id, *extra_targets)
    with mutation_transaction(root, f"research-orchestrator:{operation}", targets):
        yield


def program_ids(root: Path) -> list[str]:
    programs_root = kb_root(root) / "programs"
    if not programs_root.exists():
        return []
    return sorted(path.name for path in programs_root.iterdir() if path.is_dir())


def load_state(root: Path, program_id: str) -> dict:
    payload = load_yaml(state_path(root, program_id), default={})
    if not isinstance(payload, dict) or not payload:
        payload = {
            **yaml_default(f"{program_id}-state", "research-orchestrator", status="active"),
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
                "decisions": f"kb/programs/{program_id}/workflow/decisions.yaml",
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


def _open_workflow_items(items: list[dict[str, Any]], open_statuses: set[str]) -> list[dict[str, Any]]:
    return [item for item in items if str(item.get("status") or "open") in open_statuses]


def _priority_value(item: dict[str, Any]) -> int:
    return PRIORITY_SCORE.get(str(item.get("priority") or "normal"), 10)


def _program_unit_ids(program_id: str, state: dict[str, Any], records: list[dict[str, Any]]) -> set[str]:
    unit_ids = set(normalize_list(state.get("active_unit_ids")))
    for key in ("selected_idea_id", "selected_repo_id"):
        value = str(state.get(key) or "").strip()
        if value:
            unit_ids.add(value)
    for record in records:
        if program_id in normalize_list(record.get("program_ids")):
            unit_ids.add(str(record.get("id") or ""))
    return {unit_id for unit_id in unit_ids if unit_id}


def program_dashboard_items(root: Path) -> list[dict[str, Any]]:
    records = iter_records(root)
    record_by_id = {str(record.get("id") or ""): record for record in records}
    items: list[dict[str, Any]] = []
    attached_unit_ids: set[str] = set()
    for program_id in program_ids(root):
        state = load_state(root, program_id)
        open_questions = _open_workflow_items(
            list_items(open_questions_path(root, program_id), f"{program_id}-open-questions", "research-orchestrator"),
            OPEN_QUESTION_OPEN_STATUSES,
        )
        evidence_requests = _open_workflow_items(
            list_items(evidence_requests_path(root, program_id), f"{program_id}-evidence-requests", "research-orchestrator"),
            EVIDENCE_REQUEST_OPEN_STATUSES,
        )
        blocking_evidence = [item for item in evidence_requests if bool(item.get("blocking"))]
        high_questions = [item for item in open_questions if str(item.get("priority") or "") in {"critical", "high"}]
        unit_ids = _program_unit_ids(program_id, state, records)
        attached_unit_ids.update(unit_ids)
        agent_units: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for unit_id in sorted(unit_ids):
            record = record_by_id.get(unit_id)
            if record is None:
                continue
            step = safe_unit_step(record)
            if step and str(step.get("kind") or "") == "agent-work":
                agent_units.append((record, step))
        pending_units = [
            record_by_id[unit_id]
            for unit_id in sorted(unit_ids)
            if unit_id in record_by_id and is_user_confirmable(record_by_id[unit_id])
        ]
        detail_score = (
            sum(_priority_value(item) for item in evidence_requests)
            + sum(_priority_value(item) for item in open_questions)
        )
        if blocking_evidence:
            score = 400 + min(detail_score, 99)
        elif agent_units:
            score = 300 + min(detail_score, 99)
        elif high_questions:
            score = 200 + min(detail_score, 99)
        elif pending_units:
            score = 100 + min(detail_score + 10 * len(pending_units), 99)
        elif normalize_list(state.get("next_actions")):
            score = 50 + min(detail_score, 49)
        else:
            score = detail_score
        reasons: list[str] = []
        if blocking_evidence:
            reasons.append(f"{len(blocking_evidence)} blocking evidence")
        if high_questions:
            reasons.append(f"{len(high_questions)} high-priority open question")
        if agent_units:
            verification_count = sum(
                1 for _record, step in agent_units if str(step.get("step_type") or "") == "agent-verify"
            )
            fill_count = len(agent_units) - verification_count
            if verification_count:
                reasons.append(f"{verification_count} 项待 Agent 重核验")
            if fill_count:
                reasons.append(f"{fill_count} 项待 Agent 补全")
        if pending_units:
            reasons.append(f"{len(pending_units)} pending confirmation")
        if normalize_list(state.get("next_actions")):
            reasons.append("persisted next action")
        if not reasons and str(state.get("stage") or "") not in TERMINAL_PROGRAM_STAGES:
            reasons.append("stage review")
            score += 1

        step_type = "program-work"
        action_kind = "program-work"
        decision_record: dict[str, Any] = {}
        if blocking_evidence:
            next_action = f"Resolve blocking evidence: {blocking_evidence[0].get('needed') or blocking_evidence[0].get('question')}"
            recommended_command = shell_command(
                [COMMAND_PREFIX, ".agents/skills/research-orchestrator/scripts/orchestrate.py", "status", "--program-id", program_id]
            )
        elif agent_units:
            decision_record, agent_step = agent_units[0]
            next_action = str(agent_step.get("reason") or "Agent 需要继续核验这项资料。")
            recommended_command = ""
            step_type = str(agent_step.get("step_type") or "agent-fill")
            action_kind = "agent-work"
        elif high_questions:
            next_action = f"Answer high-priority question: {high_questions[0].get('question')}"
            recommended_command = shell_command(
                [COMMAND_PREFIX, ".agents/skills/research-orchestrator/scripts/orchestrate.py", "status", "--program-id", program_id]
            )
        elif pending_units:
            next_action = f"Review pending confirmation: {pending_units[0].get('id')}"
            recommended_command = confirm_command_for_record(pending_units[0])
            step_type = "human-decision"
            action_kind = "human-gate"
            decision_record = pending_units[0]
        elif normalize_list(state.get("next_actions")):
            next_action = normalize_list(state.get("next_actions"))[0]
            recommended_command = shell_command(
                [COMMAND_PREFIX, ".agents/skills/research-orchestrator/scripts/orchestrate.py", "status", "--program-id", program_id]
            )
        else:
            next_action = "Review program stage and next actions."
            recommended_command = shell_command(
                [COMMAND_PREFIX, ".agents/skills/research-orchestrator/scripts/orchestrate.py", "status", "--program-id", program_id]
            )
        items.append(
            {
                "program_id": program_id,
                "record_id": str(decision_record.get("id") or ""),
                "title": str(decision_record.get("title") or ""),
                "step_type": step_type,
                "action_kind": action_kind,
                "safe_execute": False,
                "stage": str(state.get("stage") or ""),
                "goal": str(state.get("goal") or ""),
                "question": str(state.get("question") or ""),
                "updated_at": str(state.get("updated_at") or ""),
                "counts": state.get("counts") if isinstance(state.get("counts"), dict) else {},
                "open_question_count": len(open_questions),
                "evidence_request_count": len(evidence_requests),
                "blocking_evidence_count": len(blocking_evidence),
                "pending_confirmation_count": len(pending_units),
                "score": score,
                "reasons": reasons,
                "next_action": next_action,
                "recommended_command": recommended_command,
            }
        )
    for record in records:
        unit_id = str(record.get("id") or "")
        if not unit_id or unit_id in attached_unit_ids or normalize_list(record.get("program_ids")):
            continue
        step = safe_unit_step(record)
        if not step:
            continue
        score = 20 if bool(step.get("safe_execute")) else 30
        items.append(
            {
                "program_id": f"loose:{unit_id}",
                "record_id": unit_id,
                "title": str(record.get("title") or ""),
                "step_type": str(step.get("step_type") or ""),
                "action_kind": str(step.get("kind") or ""),
                "safe_execute": bool(step.get("safe_execute")),
                "stage": "loose-unit",
                "goal": str(record.get("title") or ""),
                "question": "",
                "updated_at": str(record.get("updated_at") or ""),
                "counts": {},
                "open_question_count": 0,
                "evidence_request_count": 0,
                "blocking_evidence_count": 0,
                "pending_confirmation_count": 1 if str(step.get("kind") or "") == "human-gate" else 0,
                "score": score,
                "reasons": ["loose unit", str(step.get("step_type") or "")],
                "next_action": str(step.get("reason") or ""),
                "recommended_command": str(step.get("recommended_command") or "")
                or shell_command([str(part) for part in step.get("command_parts") or []]),
            }
        )
    return sorted(items, key=lambda item: (-int(item.get("score") or 0), str(item.get("updated_at") or ""), str(item.get("program_id") or "")))


def format_dashboard(items: list[dict[str, Any]], *, limit: int = 20) -> str:
    selected = items[:limit] if limit > 0 else items
    lines = ["# Program Dashboard", ""]
    if not selected:
        lines.append("- KB 为空，第一步：告诉 AI 一篇论文的来源（链接或文件），或运行 kb ingest")
        lines.append("  操作：告诉 AI 论文来源，或运行 kb ingest。")
        return "\n".join(lines).strip()
    for item in selected:
        reasons = ", ".join(item.get("reasons", [])) or "no urgent blocker"
        lines.append(
            f"- `{item['program_id']}` · stage={item.get('stage') or 'init'} · "
            f"score={item.get('score', 0)} · {reasons}"
        )
        lines.append(f"  next: {item.get('next_action')}")
        lines.append("  操作：可运行 kb next，或直接让 AI 推进上述事项。")
    return "\n".join(lines).strip()


def format_next(
    items: list[dict[str, Any]],
    *,
    limit: int = 5,
    has_records: bool = False,
) -> str:
    selected = items[:limit] if limit > 0 else items
    lines = ["# Next Actions", ""]
    if not selected:
        if has_records:
            lines.append("- 知识库已有资料，但目前没有待处理事项。")
        else:
            lines.append("- KB 为空。请告诉 AI 一篇论文、一个代码仓或一篇博客的来源，或使用 kb ingest 添加资料。")
        return "\n".join(lines).strip()
    for item in selected:
        program_id = str(item.get("program_id") or "")
        if program_id.startswith("loose:"):
            record_id = str(item.get("record_id") or program_id.split(":", 1)[-1])
            title = str(item.get("title") or item.get("goal") or record_id)
            subject = f"资料「{title}」（{record_id}）"
        else:
            subject = f"研究计划「{program_id}」"
        lines.append(f"- {subject}：{item.get('next_action')}")
        if str(item.get("step_type") or "") == "human-decision":
            lines.append("  请直接用自然语言告诉我你的决定。")
        else:
            lines.append("  可以直接告诉 Agent 继续推进。")
    return "\n".join(lines).strip()


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
    canonical_decisions = list_items(
        decisions_path(root, program_id),
        f"{program_id}-decisions",
        "research-orchestrator",
    )
    by_id = {str(item.get("id") or ""): item for item in canonical_decisions}
    for legacy in legacy_decision_items(root, program_id):
        by_id.setdefault(str(legacy["id"]), legacy)
    if not decisions_path(root, program_id).exists() or len(by_id) != len(canonical_decisions):
        write_list_items(
            decisions_path(root, program_id),
            f"{program_id}-decisions",
            "research-orchestrator",
            list(by_id.values()),
        )


def refresh_state_counts(root: Path, program_id: str, payload: dict, *, materialize: bool = True) -> dict:
    if materialize:
        ensure_program_files(root, program_id)
    open_questions = list_items(open_questions_path(root, program_id), f"{program_id}-open-questions", "research-orchestrator")
    evidence_requests = list_items(evidence_requests_path(root, program_id), f"{program_id}-evidence-requests", "research-orchestrator")
    reporting_events = list_items(reporting_events_path(root, program_id), f"{program_id}-reporting-events", "research-orchestrator")
    decisions = decision_items_with_legacy(root, program_id)
    payload.setdefault("workflow_files", {})
    payload["workflow_files"].update(
        {
            "open_questions": open_questions_path(root, program_id).relative_to(root).as_posix(),
            "evidence_requests": evidence_requests_path(root, program_id).relative_to(root).as_posix(),
            "decisions": decisions_path(root, program_id).relative_to(root).as_posix(),
            "decision_log": decision_log_path(root, program_id).relative_to(root).as_posix(),
            "reporting_events": reporting_events_path(root, program_id).relative_to(root).as_posix(),
        }
    )
    payload["counts"] = {
        "open_questions": len([item for item in open_questions if str(item.get("status") or "open") in OPEN_QUESTION_OPEN_STATUSES]),
        "evidence_requests": len([item for item in evidence_requests if str(item.get("status") or "open") in EVIDENCE_REQUEST_OPEN_STATUSES]),
        "reporting_events": len(reporting_events),
        "decisions": len(decisions),
    }
    payload["updated_at"] = utc_now_iso()
    return payload


def _decision_source_roots(root: Path, program_id: str, claims: list[dict[str, Any]]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    program_source_id = f"program:{program_id}"
    for claim in claims:
        for evidence_ref in claim.get("evidence_refs") or []:
            if not isinstance(evidence_ref, dict):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            if not source_unit_id or source_unit_id in roots:
                continue
            if source_unit_id == program_source_id:
                roots[source_unit_id] = program_root(root, program_id)
                continue
            _source_record, source_path = locate_record(root, source_unit_id, fuzzy=False)
            roots[source_unit_id] = source_path.parent
    return roots


def load_decision_claims(root: Path, program_id: str, claims_file: str) -> list[dict[str, Any]]:
    if not claims_file:
        return []
    path = Path(claims_file).expanduser()
    if not path.is_absolute():
        path = root / path
    payload = load_yaml(path, default=[])
    claims = payload.get("claims") if isinstance(payload, dict) else payload
    violations = validate_claims(claims)
    normalized = [dict(claim) for claim in claims if isinstance(claim, dict)] if isinstance(claims, list) else []
    source_roots: dict[str, Path] = {}
    if normalized:
        try:
            source_roots = _decision_source_roots(root, program_id, normalized)
        except SystemExit as exc:
            violations.append(str(exc))
    for claim in normalized:
        if str(claim.get("confirmation_status") or "") != "pending_user_confirmation":
            violations.append(f"decision claim {claim.get('id')!r} must remain pending_user_confirmation")
        violations.extend(verify_claim_evidence(claim, program_root(root, program_id), source_roots=source_roots))
    if violations:
        raise SystemExit("Program decision claims failed verification:\n  - " + "\n  - ".join(violations))
    return normalized


def write_decision_fill_scaffold(
    root: Path,
    program_id: str,
    *,
    decision: str,
    rationale: str,
    stage: str,
    alternatives: list[str],
    evidence: list[str],
) -> Path:
    """Persist a recoverable Agent fill request, never a hollow decision item."""
    path = program_root(root, program_id) / "workflow" / "decision-fill.yaml"
    write_yaml_if_changed(
        path,
        {
            "kind": "program_decision_fill",
            "program_id": program_id,
            "status": "awaiting_agent_fill",
            "decision": {
                "text": decision,
                "rationale": rationale,
                "stage": stage,
                "alternatives": alternatives,
            },
            "evidence_hints": evidence,
            "claims": [
                {
                    "id": "decision-claim-001",
                    "text": "",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [],
                }
            ],
        },
    )
    return path


def _write_decision_projection(root: Path, program_id: str, items: list[dict[str, Any]]) -> Path:
    lines = [
        "# Decision Log",
        "",
        "AI 推断、评估和取舍理由如果不是用户明确确认，默认保持待确认语义。",
        "",
        "All script-generated timestamps are stored in UTC.",
    ]
    for item in items:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        decision = payload.get("decision") if isinstance(payload, dict) else {}
        decision = decision if isinstance(decision, dict) else {}
        receipt = item.get("confirmation") if isinstance(item.get("confirmation"), dict) else {}
        lines.extend(
            [
                "",
                f"## {item.get('timestamp', '')} · {decision.get('text', '')}",
                "",
                f"- Decision ID: `{item.get('id', '')}`",
                f"- Stage: `{decision.get('stage', '') or 'unknown'}`",
                f"- Rationale: {decision.get('rationale', '') or '待补充'}",
                f"- Information types: {', '.join(item.get('information_types', []))}",
                f"- Confirmation: `{item.get('confirmation_status', 'pending_user_confirmation')}`",
            ]
        )
        if decision.get("alternatives"):
            lines.append(f"- Alternatives: {', '.join(decision['alternatives'])}")
        if receipt:
            lines.append(f"- Confirmed by: {receipt.get('by', '')}")
            lines.append(f"- User authorization: {receipt.get('user_authorization', '')}")
    path = decision_log_path(root, program_id)
    write_text_if_changed(path, "\n".join(lines).strip() + "\n")
    return path


def write_decisions(root: Path, program_id: str, items: list[dict[str, Any]]) -> tuple[Path, Path]:
    yaml_path = write_list_items(
        decisions_path(root, program_id),
        f"{program_id}-decisions",
        "research-orchestrator",
        items,
    )
    return yaml_path, _write_decision_projection(root, program_id, items)


def append_decision(root: Path, program_id: str, item: dict[str, Any]) -> tuple[Path, Path]:
    items = list_items(decisions_path(root, program_id), f"{program_id}-decisions", "research-orchestrator")
    items.append(item)
    return write_decisions(root, program_id, items)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage research programs.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init-program", help="Create a new program")
    init_cmd.add_argument("--program-id", required=True)
    init_cmd.add_argument("--question", required=True)
    init_cmd.add_argument("--goal", required=True)

    stage = subparsers.add_parser("set-stage", help="Update program stage")
    stage.add_argument("--program-id", required=True)
    stage.add_argument("--stage", required=True)

    add_next_action = subparsers.add_parser("add-next-action", help="Persist one resumable program action")
    add_next_action.add_argument("--program-id", required=True)
    add_next_action.add_argument("--action", required=True)

    resolve_next_action = subparsers.add_parser("resolve-next-action", help="Remove one completed program action")
    resolve_next_action.add_argument("--program-id", required=True)
    resolve_next_action.add_argument("--action", required=True)

    status = subparsers.add_parser("status", help="Show program status")
    status.add_argument("--program-id", required=True)

    dashboard = subparsers.add_parser("dashboard", help="Show prioritized program dashboard")
    dashboard.add_argument("--limit", type=int, default=20)

    next_cmd = subparsers.add_parser("next", help="Show prioritized next actions across programs")
    next_cmd.add_argument("--limit", type=int, default=5)
    next_cmd.add_argument("--program-id")
    next_cmd.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    auto = subparsers.add_parser("auto", help="Plan or execute the next safe orchestration step")
    auto.add_argument("--max-steps", type=int, default=1)
    auto.add_argument("--execute", action="store_true")

    route = subparsers.add_parser("route", help="Suggest the right skill for a task")
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
    evidence.add_argument("--source-type", default="unknown", choices=["paper", "repo", "dataset", "blog", "experiment", "benchmark", "user", "unknown"])
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
    decision.add_argument("--claims-file", default="")
    decision.add_argument("--alternative", action="append", default=[])
    decision.add_argument("--confirmation-status", default="pending_user_confirmation", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])

    confirm_decision = subparsers.add_parser("confirm-decision", help="Confirm a pending program decision")
    confirm_decision.add_argument("--program-id", required=True)
    confirm_decision.add_argument("--decision-id", required=True)
    confirm_decision.add_argument("--confirmed-by", default="")
    confirm_decision.add_argument("--evidence", action="append", required=True)
    confirm_decision.add_argument("--user-authorization", required=True)
    confirm_decision.add_argument("--authorization-source", default="user_message")
    confirm_decision.add_argument("--expected-snapshot", required=True)

    reject_decision = subparsers.add_parser("reject-decision", help="Reject a verified pending program decision")
    reject_decision.add_argument("--program-id", required=True)
    reject_decision.add_argument("--decision-id", required=True)
    reject_decision.add_argument("--reason", default="")
    reject_decision.add_argument("--expected-snapshot", required=True)

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
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if not (args.command == "next" and args.json):
        print_resolved_project_roots(root)
    semantic_read = args.command in SEMANTIC_READ_COMMANDS or (
        args.command == "auto" and not args.execute
    )
    if not semantic_read:
        ensure_workspace(root)

    if args.command == "init-program":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: init program {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "set-stage":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: set program stage {args.program_id} -> {args.stage}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command in {"add-next-action", "resolve-next-action"}:
        changed = False
        with program_mutation(root, args.program_id, args.command):
            ensure_program_files(root, args.program_id)
            payload = load_state(root, args.program_id)
            actions = normalize_list(payload.get("next_actions"))
            if args.command == "add-next-action":
                if args.action not in actions:
                    actions.append(args.action)
                    changed = True
                event_type = "next-action-added"
                event_title = "Next action persisted"
            else:
                if args.action in actions:
                    actions = [item for item in actions if item != args.action]
                    changed = True
                event_type = "next-action-resolved"
                event_title = "Next action resolved"
            if changed:
                payload["next_actions"] = actions
                append_program_reporting_event(
                    root,
                    args.program_id,
                    {
                        "source_skill": "research-orchestrator",
                        "event_type": event_type,
                        "title": event_title,
                        "summary": args.action,
                        "stage": str(payload.get("stage") or "init"),
                        "tags": ["program-state"],
                    },
                    generated_by="research-orchestrator",
                )
                write_state(root, args.program_id, payload)
        if not changed:
            status = "already persisted" if args.command == "add-next-action" else "already resolved"
            print(f"[ok] next action {status}; no changes")
            return 0
        print(f"[ok] {'persisted' if args.command == 'add-next-action' else 'resolved'} next action")
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: {args.command} {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "status":
        if not program_root(root, args.program_id).is_dir():
            existing = ", ".join(program_ids(root)) or "(none)"
            raise SystemExit(
                f"program `{args.program_id}` not found; existing: {existing}. "
                "Use init-program to create it."
            )
        # Status is a strict read: no ensure/write, no lock-file creation, and no
        # refreshed timestamp. Mutating commands own materialization/migration.
        payload = refresh_state_counts(
            root,
            args.program_id,
            load_state(root, args.program_id),
            materialize=False,
        )
        print(f"program_id: {payload.get('program_id') or args.program_id}")
        print(f"stage: {payload.get('stage') or 'init'}")
        print(f"question: {payload.get('question') or ''}")
        print(f"goal: {payload.get('goal') or ''}")
        print(f"active_unit_ids: {payload.get('active_unit_ids', [])}")
        print(f"counts: {payload.get('counts', {})}")
        print(f"workflow_files: {payload.get('workflow_files', {})}")
        return 0
    if args.command == "dashboard":
        print(format_dashboard(program_dashboard_items(root), limit=args.limit))
        return 0
    if args.command == "next":
        has_records = bool(iter_records(root))
        items = program_dashboard_items(root)
        if args.program_id:
            if not program_root(root, args.program_id).is_dir():
                existing = ", ".join(program_ids(root)) or "(none)"
                raise SystemExit(
                    f"program `{args.program_id}` not found; existing: {existing}. "
                    "Use init-program to create it."
                )
            items = [item for item in items if item.get("program_id") == args.program_id]
            if not items and not args.json:
                print(f"# Next Actions\n\n- No actions for program `{args.program_id}`.")
                return 0
        if args.json:
            print(
                json.dumps(
                    {"has_records": has_records, "items": items[: args.limit] if args.limit > 0 else items},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(format_next(items, limit=args.limit, has_records=has_records))
        return 0
    if args.command == "auto":
        exit_code = 0
        for _ in range(max(1, int(args.max_steps or 1))):
            plan = auto_plan(root)
            if args.execute:
                exit_code = execute_auto_plan(root, plan)
                if exit_code != 0 or not bool(plan.get("safe_execute")):
                    return exit_code
            else:
                print(format_auto_plan(plan))
                return 0
        if args.execute:
            follow_up = auto_plan(root)
            if not bool(follow_up.get("safe_execute")):
                print(format_auto_plan(follow_up))
                print("[stop] human decision required; not executing")
        return exit_code
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
        try:
            attached_record, attached_record_path = locate_record(root, args.unit_id)
        except SystemExit as exc:
            print(f"[warn] attach-unit could not resolve `{args.unit_id}`: {exc}")
            return 1
        canonical_id = str(attached_record.get("id") or args.unit_id)
        with program_mutation(root, args.program_id, args.command, attached_record_path):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: attach {canonical_id} to {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id, attached_record_path),
        )
        return 0
    if args.command == "query-program":
        query_root = program_root(root, args.program_id) / "queries"
        slug = simple_slug(args.question, "query")
        query_path = query_root / f"{slug}.md"
        with program_mutation(root, args.program_id, args.command, query_path):
            ensure_dir(query_root)
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: query program {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id, query_path),
        )
        return 0
    if args.command == "add-open-question":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: add open question {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "answer-question":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: answer open question {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "drop-question":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: drop open question {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "request-evidence":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: request evidence {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "resolve-evidence":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: resolve evidence {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "drop-evidence":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: drop evidence {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "log-decision":
        if args.confirmation_status in {"confirmed", "auto_confirmed"}:
            raise SystemExit(
                "Program decisions cannot be created confirmed/auto_confirmed; "
                "log a pending decision, then use confirm-decision."
            )
        claims = load_decision_claims(root, args.program_id, args.claims_file)
        if not claims:
            with program_mutation(root, args.program_id, args.command):
                ensure_program_files(root, args.program_id)
                state = load_state(root, args.program_id)
                fill_path = write_decision_fill_scaffold(
                    root,
                    args.program_id,
                    decision=args.decision,
                    rationale=args.rationale,
                    stage=args.stage or state.get("stage", ""),
                    alternatives=normalize_list(args.alternative),
                    evidence=normalize_list(args.evidence),
                )
            print(fill_path.relative_to(root))
            checkpoint_and_report(
                root,
                trigger="milestone",
                message=f"milestone: prepare decision fill {args.program_id}",
                target_paths=[fill_path],
            )
            return 0
        with program_mutation(root, args.program_id, args.command):
            ensure_program_files(root, args.program_id)
            state = load_state(root, args.program_id)
            timestamp = utc_now_iso()
            decision_id = "decision-" + hashlib.sha256(
                f"{args.program_id}\n{timestamp}\n{args.decision}".encode("utf-8")
            ).hexdigest()[:12]
            item = {
                "id": decision_id,
                "kind": "program_decision",
                "owner": "research-orchestrator",
                "timestamp": timestamp,
                "program_id": args.program_id,
                "evidence": normalize_list(args.evidence),
                "confirmation_status": args.confirmation_status,
                "needs_human_confirmation": args.confirmation_status != "rejected",
                "information_types": ["inference", "evaluation", "unverified"],
                "payload": {
                    "decision": {
                        "text": args.decision,
                        "rationale": args.rationale,
                        "stage": args.stage or state.get("stage", ""),
                        "alternatives": normalize_list(args.alternative),
                    },
                },
            }
            if claims:
                attach_claims(item["payload"], claims)
                build_verification_receipt(
                    item,
                    program_root(root, args.program_id),
                    source_roots=_decision_source_roots(root, args.program_id, claims),
                )
            decisions_yaml, path = append_decision(root, args.program_id, item)
            append_program_reporting_event(
                root,
                args.program_id,
                {
                    "source_skill": "research-orchestrator",
                    "event_type": "decision",
                    "title": args.decision,
                    "summary": args.rationale,
                    "stage": item["payload"]["decision"]["stage"],
                    "tags": ["decision", "pending"],
                    "artifacts": [
                        decisions_yaml.relative_to(root).as_posix(),
                        path.relative_to(root).as_posix(),
                        *item["evidence"],
                    ],
                    "epistemic_type": "judgement",
                    "information_types": ["inference", "evaluation", "unverified"],
                    "confirmation_status": "pending_user_confirmation",
                    "confirmation_binding": confirmation_binding(
                        item,
                        owner="research-orchestrator",
                        path=decisions_yaml.relative_to(root).as_posix(),
                    ),
                },
                generated_by="research-orchestrator",
            )
            state = load_state(root, args.program_id)
            state["last_decision"] = {
                "id": decision_id,
                "decision": args.decision,
                "timestamp": item["timestamp"],
                "confirmation_status": args.confirmation_status,
            }
            write_state(root, args.program_id, state)
        print(path.relative_to(root))
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: log decision {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    if args.command == "confirm-decision":
        decision_targets = [
            decisions_path(root, args.program_id),
            decision_log_path(root, args.program_id),
            reporting_events_path(root, args.program_id),
            state_path(root, args.program_id),
        ]
        with mutation_transaction(root, f"research-orchestrator:{args.command}", decision_targets):
            items = list_items(
                decisions_path(root, args.program_id),
                f"{args.program_id}-decisions",
                "research-orchestrator",
            )
            matches = [item for item in items if str(item.get("id") or "") == args.decision_id]
            if not matches:
                raise SystemExit(f"Program decision not found: {args.decision_id}")
            if len(matches) != 1:
                raise SystemExit(f"Program decision id is duplicated and requires repair: {args.decision_id}")
            selected = matches[0]
            violations = readiness_violations(root, selected, decisions_path(root, args.program_id))
            if violations:
                raise SystemExit("Program decision is not ready for confirmation:\n  - " + "\n  - ".join(violations))
            try:
                require_judgement_snapshot(
                    selected,
                    expected_snapshot=args.expected_snapshot,
                    owner="research-orchestrator",
                    path=decisions_path(root, args.program_id).relative_to(root).as_posix(),
                    root=root,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            claims = selected.get("payload", {}).get("claims", [])
            source_roots = _decision_source_roots(root, args.program_id, claims)
            apply_confirmation(
                selected,
                confirmed_by=args.confirmed_by,
                evidence=args.evidence,
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
                method="orchestrate.py confirm-decision",
                project_root=root,
                verification_root=program_root(root, args.program_id),
                trusted_source_roots=source_roots,
            )
            decisions_yaml, path = write_decisions(root, args.program_id, items)
            decision_payload = selected.get("payload", {}).get("decision", {})
            binding = confirmation_binding(
                selected,
                owner="research-orchestrator",
                path=decisions_yaml.relative_to(root).as_posix(),
            )
            append_program_reporting_event(
                root,
                args.program_id,
                {
                    "source_skill": "research-orchestrator",
                    "event_type": "decision-confirmed",
                    "title": str(decision_payload.get("text") or args.decision_id),
                    "summary": str(decision_payload.get("rationale") or ""),
                    "stage": str(decision_payload.get("stage") or ""),
                    "tags": ["decision", "confirmed"],
                    "artifacts": [
                        decisions_yaml.relative_to(root).as_posix(),
                        path.relative_to(root).as_posix(),
                    ],
                    "epistemic_type": "judgement",
                    "information_types": ["inference", "evaluation"],
                    "confirmation_status": "confirmed",
                    "confirmation_binding": binding,
                },
                generated_by="research-orchestrator",
            )
            state = load_state(root, args.program_id)
            state["last_decision"] = {
                "id": args.decision_id,
                "decision": str(decision_payload.get("text") or ""),
                "timestamp": str(selected.get("timestamp") or ""),
                "confirmation_status": "confirmed",
            }
            write_state(root, args.program_id, state)
        print(path.relative_to(root))
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: confirm decision {args.program_id} {args.decision_id}",
            target_paths=decision_targets,
        )
        return 0
    if args.command == "reject-decision":
        decision_targets = [
            decisions_path(root, args.program_id),
            decision_log_path(root, args.program_id),
            state_path(root, args.program_id),
        ]
        with mutation_transaction(root, f"research-orchestrator:{args.command}", decision_targets):
            decisions_yaml = decisions_path(root, args.program_id)
            items = list_items(
                decisions_yaml,
                f"{args.program_id}-decisions",
                "research-orchestrator",
            )
            matches = [item for item in items if str(item.get("id") or "") == args.decision_id]
            if not matches:
                raise SystemExit(f"Program decision not found: {args.decision_id}")
            if len(matches) != 1:
                raise SystemExit(f"Program decision id is duplicated and requires repair: {args.decision_id}")
            selected = matches[0]
            violations = readiness_violations(root, selected, decisions_yaml)
            if violations:
                raise SystemExit("Program decision is not ready for rejection:\n  - " + "\n  - ".join(violations))
            try:
                require_judgement_snapshot(
                    selected,
                    expected_snapshot=args.expected_snapshot,
                    owner="research-orchestrator",
                    path=decisions_yaml.relative_to(root).as_posix(),
                    root=root,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            apply_judgement_rejection(selected, reason=args.reason)
            selected["updated_at"] = utc_now_iso()
            _yaml_path, path = write_decisions(root, args.program_id, items)
            state = load_state(root, args.program_id)
            decision_payload = selected.get("payload", {}).get("decision", {})
            state["last_decision"] = {
                "id": args.decision_id,
                "decision": str(decision_payload.get("text") or ""),
                "timestamp": str(selected.get("timestamp") or ""),
                "confirmation_status": "rejected",
            }
            write_state(root, args.program_id, state)
        print(path.relative_to(root))
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: reject decision {args.program_id} {args.decision_id}",
            target_paths=decision_targets,
        )
        return 0
    if args.command == "add-reporting-event":
        with program_mutation(root, args.program_id, args.command):
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
        checkpoint = checkpoint_and_report(
            root, trigger="milestone", message=f"milestone: add reporting event {args.program_id}",
            target_paths=program_checkpoint_paths(root, args.program_id),
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

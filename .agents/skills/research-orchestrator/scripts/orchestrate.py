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
from datetime import datetime
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
from research.judgements import apply_judgement_rejection, confirmation_binding, discover_pending_judgements, judgement_confirmation_is_current, judgement_snapshot_binding, readiness_violations, require_judgement_snapshot
from research.journal import mutation_transaction
from research.monitoring import due_subscriptions, unresolved_monitor_outcomes
from research.preference_selection import load_effective_selection

OPEN_QUESTION_OPEN_STATUSES = {"open"}
EVIDENCE_REQUEST_OPEN_STATUSES = {"open"}
PRIORITY_SCORE = {"critical": 40, "high": 30, "normal": 10, "low": 5}
TERMINAL_PROGRAM_STAGES = {"done", "completed", "archived", "published"}
SEMANTIC_READ_COMMANDS = {
    "status",
    "dashboard",
    "next",
    "route",
    "prepare-next-selection",
    "verify-next-selection",
}
PORTFOLIO_HISTORY_ID = "portfolio-next-selections"
PORTFOLIO_DECISION_KIND = "portfolio_decision"
PORTFOLIO_DECISION_SCOPES = {"procedural_planning", "research_judgement"}

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
    "文献检索": "literature-search",
    "检索文献": "literature-search",
    "找论文": "literature-search",
    "搜论文": "literature-search",
    "补相关工作": "literature-search",
    "literature search": "literature-search",
    "find papers": "literature-search",
    "search papers": "literature-search",
    "related papers": "literature-search",
    "分析论文": "paper-analyst",
    "analyze paper": "paper-analyst",
    "论文": "paper-analyst",
    "paper": "paper-analyst",
    "仓库": "repo-analyst",
    "repo": "repo-analyst",
    "数据集": "dataset-analyst",
    "dataset": "dataset-analyst",
    "博客": "blog-analyst",
    "blog": "blog-analyst",
    "文献综述": "literature-synthesizer",
    "系统综述": "literature-synthesizer",
    "横向综述": "literature-synthesizer",
    "综述": "literature-synthesizer",
    "survey": "literature-synthesizer",
    "systematic literature review": "literature-synthesizer",
    "systematic review": "literature-synthesizer",
    "scoping review": "literature-synthesizer",
    "meta-analysis": "literature-synthesizer",
    "meta analysis": "literature-synthesizer",
    "literature review": "literature-synthesizer",
    "review recent papers": "literature-synthesizer",
    "related work": "literature-synthesizer",
    "evidence synthesis": "literature-synthesizer",
    "rapid review": "literature-synthesizer",
    "narrative review": "literature-synthesizer",
    "review of the literature": "literature-synthesizer",
    "systematic mapping study": "literature-synthesizer",
    "state-of-the-art review": "literature-synthesizer",
    "相关工作": "literature-synthesizer",
    "元分析": "literature-synthesizer",
    "证据综合": "literature-synthesizer",
    "系统映射研究": "literature-synthesizer",
    "taxonomy": "literature-synthesizer",
    "趋势与空白": "literature-synthesizer",
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
    "讨论": "discussion-archivist",
    "discussion": "discussion-archivist",
    "skill evolution": "skill-evolution-advisor",
    "技能演化": "skill-evolution-advisor",
    "skill drift": "skill-evolution-advisor",
    "retrospective": "skill-evolution-advisor",
    "监测": "research-monitor",
    "监控": "research-monitor",
    "定期追踪": "research-monitor",
    "定期关注": "research-monitor",
    "每周": "research-monitor",
    "每两周": "research-monitor",
    "每月": "research-monitor",
    "monitor": "research-monitor",
    "subscription": "research-monitor",
    "wiki": "wiki-adapter",
    "知识库": "wiki-adapter",
}

ROUTE_COMPOSITION_MARKERS = (
    "然后",
    "之后",
    "同时",
    "并且",
    "以及",
    "并做",
    "并分析",
    "后再",
    " and ",
    "and then",
    " then ",
    " after ",
)
ROUTE_NEGATION_MARKERS = ("不要", "不需要", "无需", "跳过", "别用", "without ", "skip ")
ROUTE_GENERIC_ENTITY_HINTS = {"论文", "paper", "仓库", "repo", "数据集", "dataset", "博客", "blog"}

COMMAND_PREFIX = "${RESEARCH_PYTHON:-python3}"


def route_candidate_snapshot(task: str) -> dict[str, Any]:
    """Expose factual route hints; leave ambiguous or composed routing to the Agent."""
    text = str(task or "").strip()
    lower = text.casefold()
    composition_markers = [marker for marker in ROUTE_COMPOSITION_MARKERS if marker in lower]
    negation_markers = [marker for marker in ROUTE_NEGATION_MARKERS if marker in lower]
    if re.search(r"\b(?:not|don't|do not|never)\b", lower):
        negation_markers.append("english-negation")
    raw_hits = [
        {"hint": hint, "owner_skill": skill, "start": lower.find(hint)}
        for hint, skill in ROUTE_HINTS.items()
        if hint in lower
    ]
    effective_hits: list[dict[str, Any]] = []
    for hit in raw_hits:
        hint = str(hit["hint"])
        suppressed = not composition_markers and any(
            hint != str(other["hint"])
            and (
                (hint in str(other["hint"]) and len(str(other["hint"])) > len(hint))
                or (
                    hint in ROUTE_GENERIC_ENTITY_HINTS
                    and str(other["owner_skill"]) != str(hit["owner_skill"])
                )
            )
            for other in raw_hits
        )
        effective_hits.append({**hit, "suppressed_by_specific_hint": suppressed})
    candidate_skills = sorted(
        {
            str(hit["owner_skill"])
            for hit in effective_hits
            if not bool(hit["suppressed_by_specific_hint"])
        }
    )
    planning_required = (
        len(candidate_skills) != 1
        or bool(composition_markers)
        or bool(negation_markers)
    )
    direct_owner = candidate_skills[0] if not planning_required else "research-orchestrator"
    digest_input = {
        "schema_version": 1,
        "task": text,
        "matched_hints": sorted(
            effective_hits,
            key=lambda item: (int(item["start"]), -len(str(item["hint"])), str(item["hint"])),
        ),
        "candidate_skills": candidate_skills,
        "composition_markers": sorted(set(composition_markers)),
        "negation_markers": sorted(set(negation_markers)),
    }
    return {
        **digest_input,
        "route_snapshot_digest": _canonical_digest(digest_input),
        "planning_required": planning_required,
        "direct_owner": direct_owner,
    }


def route_decision_fill_template(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_snapshot_digest": str(snapshot.get("route_snapshot_digest") or ""),
        "steps": [],
        "rationale": "",
    }


def validate_route_decision(decision: object, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate an Agent-authored ordered route without judging its semantics."""
    if not isinstance(decision, dict):
        raise SystemExit("Route decision fill must be a mapping")
    if str(decision.get("route_snapshot_digest") or "") != str(
        snapshot.get("route_snapshot_digest") or ""
    ):
        raise SystemExit("Route decision is stale: task snapshot changed")
    rationale = str(decision.get("rationale") or "").strip()
    if not rationale:
        raise SystemExit("Route decision requires a rationale")
    raw_steps = decision.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > 12:
        raise SystemExit("Route decision requires one to twelve ordered steps")
    allowed_owners = set(snapshot.get("candidate_skills") or [])
    if not allowed_owners:
        allowed_owners = {"research-orchestrator"}
    normalized_steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise SystemExit("Route decision steps must be mappings")
        step_id = str(raw_step.get("step_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", step_id) or step_id in seen:
            raise SystemExit("Route decision step ids must be unique safe identifiers")
        owner = str(raw_step.get("owner_skill") or "").strip()
        if owner not in allowed_owners:
            raise SystemExit("Route decision selected an owner outside the task snapshot")
        instruction = str(raw_step.get("instruction") or "").strip()
        if not instruction:
            raise SystemExit("Route decision steps require an instruction")
        dependencies = raw_step.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise SystemExit("Route decision depends_on must be a list")
        depends_on = [str(item or "").strip() for item in dependencies]
        if any(not item or item not in seen for item in depends_on) or len(set(depends_on)) != len(depends_on):
            raise SystemExit("Route decision dependencies must name unique earlier steps")
        gate = str(raw_step.get("governance_gate") or "none").strip()
        if gate not in {"none", "human-decision", "agent-verification"}:
            raise SystemExit("Route decision governance_gate is invalid")
        seen.add(step_id)
        normalized_steps.append(
            {
                "order": index,
                "step_id": step_id,
                "owner_skill": owner,
                "instruction": instruction,
                "depends_on": depends_on,
                "governance_gate": gate,
            }
        )
    return {
        "route_snapshot_digest": str(snapshot.get("route_snapshot_digest") or ""),
        "steps": normalized_steps,
        "rationale": rationale,
        "generated_by": "runtime-agent",
    }


def route_task(task: str) -> str:
    return str(route_candidate_snapshot(task).get("direct_owner") or "research-orchestrator")
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
    snapshot = portfolio_candidate_snapshot(root)
    current = current_portfolio_decision(root, snapshot)
    if current is None or str(current.get("effective_status") or "") != "current":
        return {
            "status": "planning_required",
            "kind": "agent-work",
            "step_type": "portfolio-planning",
            "record_id": "",
            "title": "Agent portfolio planning required",
            "reason": "Agent must compare the current candidate snapshot before any auto execution.",
            "candidate_snapshot_digest": snapshot["candidate_snapshot_digest"],
            "command_parts": [],
            "safe_execute": False,
        }
    selected = [item for item in current.get("selected_actions", []) if isinstance(item, dict)]
    if len(selected) != 1:
        return {
            "status": "selection_requires_dispatch",
            "kind": "agent-work",
            "step_type": "portfolio-dispatch",
            "record_id": "",
            "title": "Agent-selected actions require explicit dispatch",
            "reason": "Auto execution requires exactly one current Agent-selected action.",
            "portfolio_decision_id": str(current.get("decision_id") or ""),
            "command_parts": [],
            "safe_execute": False,
        }
    candidate = selected[0]
    command_parts = [str(item) for item in candidate.get("command_parts") or []]
    safe = (
        bool(candidate.get("safe_execute_capability"))
        and str(candidate.get("governance_gate") or "none") == "none"
        and bool(command_parts)
    )
    subject = candidate.get("subject") if isinstance(candidate.get("subject"), dict) else {}
    return {
        "status": "planned" if safe else "selected_action_requires_agent",
        "kind": str(subject.get("kind") or "agent-work"),
        "step_type": str(candidate.get("action_type") or "portfolio-action"),
        "record_id": str(subject.get("id") or ""),
        "title": str(candidate.get("title") or ""),
        "reason": str(candidate.get("reason") or "Agent-selected portfolio action."),
        "portfolio_decision_id": str(current.get("decision_id") or ""),
        "selected_action_id": str(candidate.get("action_id") or ""),
        "command_parts": command_parts,
        "safe_execute": safe,
    }


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


def portfolio_history_path(root: Path) -> Path:
    """Canonical append-only history for cross-program planning decisions."""
    return kb_root(root) / "programs" / "portfolio-next-selections.yaml"


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
    if programs_root.is_symlink() or not programs_root.is_dir():
        raise SystemExit("Programs root must be a regular directory")
    return sorted(path.name for path in programs_root.iterdir() if path.is_dir() and not path.is_symlink())


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


def _validate_portfolio_program_scope(root: Path, program_id: str) -> None:
    identifier = str(program_id or "").strip()
    if (
        not identifier
        or Path(identifier).name != identifier
        or identifier in {".", ".."}
        or "\\" in identifier
    ):
        raise SystemExit("Program id is not a canonical path component")
    programs = kb_root(root) / "programs"
    path = program_root(root, identifier)
    if programs.is_symlink() or path.is_symlink():
        raise SystemExit("Program candidate scope cannot traverse a symlink")
    if not path.is_dir():
        raise SystemExit(f"Program `{identifier}` does not exist")
    try:
        path.resolve().relative_to(programs.resolve())
    except ValueError as exc:
        raise SystemExit("Program candidate scope must stay inside kb/programs") from exc
    workflow = workflow_root(root, identifier)
    guarded = [
        state_path(root, identifier),
        workflow,
        open_questions_path(root, identifier),
        evidence_requests_path(root, identifier),
        decisions_path(root, identifier),
        reporting_events_path(root, identifier),
    ]
    if any(candidate.is_symlink() for candidate in guarded):
        raise SystemExit("Program candidate inputs cannot be symlinks")


def program_dashboard_items(root: Path) -> list[dict[str, Any]]:
    """Legacy ranked projection for pre-R6 private protocol compatibility only.

    New planning must consume :func:`portfolio_candidate_snapshot`; neither
    ``next``'s plain renderer nor an R6-aware adapter may treat this list as a
    PortfolioDecision.
    """
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


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _portfolio_action_id(*, program_id: str, action_type: str, subject_id: str, discriminator: str = "") -> str:
    identity = {
        "program_id": program_id,
        "action_type": action_type,
        "subject_id": subject_id,
        "discriminator": discriminator,
    }
    return "action-" + _canonical_digest(identity)[:20]


def _unit_owner_skill(kind: str) -> str:
    return {
        "paper": "paper-analyst",
        "repo": "repo-analyst",
        "dataset": "dataset-analyst",
        "blog": "blog-analyst",
        "idea": "idea-workbench",
        "experiment": "experiment-workbench",
    }.get(kind, "knowledge-base-manager")


def _candidate(
    *,
    program_id: str,
    action_type: str,
    subject_id: str,
    discriminator: str = "",
    owner_skill: str,
    stage: str,
    goal: str,
    question: str,
    reason: str,
    title: str = "",
    subject_kind: str = "",
    priority: str = "normal",
    blocking: bool = False,
    dependencies: list[dict[str, Any]] | None = None,
    governance_gate: str = "none",
    safe_execute_capability: bool = False,
    command_parts: list[str] | None = None,
    recommended_command: str = "",
) -> dict[str, Any]:
    # This structure is factual context for a runtime Agent.  In particular it
    # contains no semantic value score and does not name a winner.
    if governance_gate != "none":
        safe_execute_capability = False
    payload = {
        "action_id": _portfolio_action_id(
            program_id=program_id,
            action_type=action_type,
            subject_id=subject_id,
            discriminator=discriminator,
        ),
        "program_id": program_id,
        "action_type": action_type,
        "owner_skill": owner_skill,
        "subject": {"kind": subject_kind, "id": subject_id},
        "title": title,
        "stage": stage,
        "goal": goal,
        "question": question,
        "reason": reason,
        "priority": priority if priority in PRIORITY_SCORE else "normal",
        "blocking": bool(blocking),
        "dependencies": dependencies or [],
        "governance_gate": governance_gate,
        "safe_execute_capability": bool(safe_execute_capability),
        "command_parts": [str(part) for part in command_parts or []],
        "recommended_command": recommended_command,
    }
    payload["binding_digest"] = _canonical_digest(
        {key: value for key, value in payload.items() if key not in {"command_parts", "recommended_command"}}
    )
    return payload


def _judgement_card_program_ids(
    card: dict[str, Any],
    record_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    subject = card.get("subject") if isinstance(card.get("subject"), dict) else {}
    route = card.get("confirm_route") if isinstance(card.get("confirm_route"), dict) else {}
    result: set[str] = set()
    if str(route.get("program_id") or ""):
        result.add(str(route["program_id"]))
    subject_id = str(subject.get("id") or "")
    idea_id = str(route.get("idea_id") or "")
    for record_id in (subject_id, idea_id):
        record = record_by_id.get(record_id)
        if record is not None:
            result.update(str(item) for item in normalize_list(record.get("program_ids")) if str(item))
    path_parts = Path(str(subject.get("path") or "")).parts
    if len(path_parts) >= 3 and path_parts[:2] == ("kb", "programs"):
        result.add(path_parts[2])
    return sorted(result)


def _judgement_candidate(
    card: dict[str, Any],
    *,
    program_id: str,
    stage: str,
    goal: str,
    question: str,
    record_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    subject = card.get("subject") if isinstance(card.get("subject"), dict) else {}
    subject_id = str(subject.get("id") or "")
    subject_kind = str(subject.get("kind") or "")
    record = record_by_id.get(subject_id, {})
    return _candidate(
        program_id=program_id,
        action_type="review-judgement",
        subject_id=subject_id,
        discriminator=subject_kind,
        owner_skill=str(subject.get("owner") or "knowledge-base-manager"),
        stage=stage,
        goal=goal,
        question=question,
        reason="A verified judgement is waiting for the user's decision.",
        title=str(record.get("title") or subject_id),
        subject_kind=subject_kind,
        priority=str(card.get("priority") or "normal"),
        dependencies=[
            {
                "kind": "judgement-snapshot",
                "id": f"{subject_kind}:{subject_id}",
                "snapshot_binding": card.get("snapshot_binding")
                if isinstance(card.get("snapshot_binding"), dict)
                else {},
            }
        ],
        governance_gate="human-decision",
    )


def portfolio_candidates(root: Path, *, selected_program_id: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enumerate all legal actions and factual context without ranking them."""
    records = iter_records(root)
    record_by_id = {str(record.get("id") or ""): record for record in records}
    candidates: list[dict[str, Any]] = []
    program_contexts: list[dict[str, Any]] = []
    attached_unit_ids: set[str] = set()
    judgement_cards = discover_pending_judgements(root)
    judgement_programs = {
        (str(card.get("subject", {}).get("kind") or ""), str(card.get("subject", {}).get("id") or "")):
        _judgement_card_program_ids(card, record_by_id)
        for card in judgement_cards
        if isinstance(card.get("subject"), dict)
    }
    judgement_keys = set(judgement_programs)
    attached_judgements: set[tuple[str, str]] = set()

    selected_ids = [selected_program_id] if selected_program_id else program_ids(root)
    for program_id in selected_ids:
        _validate_portfolio_program_scope(root, program_id)
        state = load_state(root, program_id)
        unit_ids = _program_unit_ids(program_id, state, records)
        attached_unit_ids.update(unit_ids)
        stage = str(state.get("stage") or "")
        context = {
            "program_id": program_id,
            "status": str(state.get("status") or "active"),
            "stage": stage,
            "question": str(state.get("question") or ""),
            "goal": str(state.get("goal") or ""),
            "blockers": normalize_list(state.get("blockers")),
            "active_unit_ids": sorted(unit_ids),
            "selected_idea_id": str(state.get("selected_idea_id") or ""),
            "selected_repo_id": str(state.get("selected_repo_id") or ""),
            "resource_constraints": state.get("resource_constraints")
            if isinstance(state.get("resource_constraints"), (list, dict))
            else [],
        }
        program_contexts.append(context)
        if stage in TERMINAL_PROGRAM_STAGES or context["status"] in {"completed", "archived"}:
            continue

        open_questions = _open_workflow_items(
            list_items(open_questions_path(root, program_id), f"{program_id}-open-questions", "research-orchestrator"),
            OPEN_QUESTION_OPEN_STATUSES,
        )
        evidence_requests = _open_workflow_items(
            list_items(evidence_requests_path(root, program_id), f"{program_id}-evidence-requests", "research-orchestrator"),
            EVIDENCE_REQUEST_OPEN_STATUSES,
        )
        before_count = len(candidates)

        for item in evidence_requests:
            item_id = str(item.get("id") or "") or _canonical_digest(item)[:16]
            needed = str(item.get("needed") or item.get("question") or "")
            related_ids = normalize_list(item.get("related_unit_ids"))
            candidates.append(
                _candidate(
                    program_id=program_id,
                    action_type="resolve-evidence-request",
                    subject_id=item_id,
                    owner_skill="research-orchestrator",
                    stage=stage,
                    goal=context["goal"],
                    question=str(item.get("question") or context["question"]),
                    reason=f"Resolve evidence request: {needed}",
                    priority=str(item.get("priority") or "normal"),
                    blocking=bool(item.get("blocking")),
                    dependencies=[{"kind": "unit", "id": unit_id} for unit_id in related_ids],
                )
            )

        for unit_id in sorted(unit_ids):
            record = record_by_id.get(unit_id)
            if record is None:
                continue
            step = safe_unit_step(record)
            if not step or str(step.get("kind") or "") == "human-gate":
                continue
            kind = str(record.get("kind") or "")
            candidates.append(
                _candidate(
                    program_id=program_id,
                    action_type=str(step.get("step_type") or "agent-work"),
                    subject_id=unit_id,
                    owner_skill=_unit_owner_skill(kind),
                    stage=stage,
                    goal=context["goal"],
                    question=context["question"],
                    reason=str(step.get("reason") or "Agent work is required."),
                    title=str(record.get("title") or ""),
                    subject_kind=kind,
                    dependencies=[
                        {
                            "kind": "unit-state",
                            "id": unit_id,
                            "workflow_state": record_workflow_state(record),
                            "record_digest": _canonical_digest(record),
                        }
                    ],
                    safe_execute_capability=bool(step.get("safe_execute")),
                    command_parts=[str(part) for part in step.get("command_parts") or []],
                )
            )

        for item in open_questions:
            item_id = str(item.get("id") or "") or _canonical_digest(item)[:16]
            related_ids = normalize_list(item.get("related_unit_ids"))
            candidates.append(
                _candidate(
                    program_id=program_id,
                    action_type="answer-open-question",
                    subject_id=item_id,
                    owner_skill=str(item.get("owner") or "research-orchestrator"),
                    stage=stage,
                    goal=context["goal"],
                    question=str(item.get("question") or ""),
                    reason=f"Answer open question: {item.get('question') or ''}",
                    priority=str(item.get("priority") or "normal"),
                    dependencies=[{"kind": "unit", "id": unit_id} for unit_id in related_ids],
                )
            )

        for card in judgement_cards:
            subject = card.get("subject") if isinstance(card.get("subject"), dict) else {}
            key = (str(subject.get("kind") or ""), str(subject.get("id") or ""))
            if program_id not in judgement_programs.get(key, []) and key[1] not in unit_ids:
                continue
            candidates.append(
                _judgement_candidate(
                    card,
                    program_id=program_id,
                    stage=stage,
                    goal=context["goal"],
                    question=context["question"],
                    record_by_id=record_by_id,
                )
            )
            attached_judgements.add(key)

        for action in normalize_list(state.get("next_actions")):
            candidates.append(
                _candidate(
                    program_id=program_id,
                    action_type="persisted-program-action",
                    subject_id="next-action",
                    discriminator=action,
                    owner_skill="research-orchestrator",
                    stage=stage,
                    goal=context["goal"],
                    question=context["question"],
                    reason=action,
                    dependencies=[{"kind": "program-stage", "id": stage or "init"}],
                )
            )

        if len(candidates) == before_count:
            candidates.append(
                _candidate(
                    program_id=program_id,
                    action_type="review-program-stage",
                    subject_id=f"program:{program_id}",
                    owner_skill="research-orchestrator",
                    stage=stage,
                    goal=context["goal"],
                    question=context["question"],
                    reason="Review the current program stage and identify the next grounded action.",
                    dependencies=[{"kind": "program-stage", "id": stage or "init"}],
                )
            )

    if not selected_program_id:
        for record in records:
            unit_id = str(record.get("id") or "")
            if not unit_id or unit_id in attached_unit_ids or normalize_list(record.get("program_ids")):
                continue
            step = safe_unit_step(record)
            if not step:
                continue
            kind = str(record.get("kind") or "")
            governance_gate = "human-decision" if str(step.get("kind") or "") == "human-gate" else "none"
            if governance_gate == "human-decision" and (kind, unit_id) in judgement_keys:
                continue
            candidates.append(
                _candidate(
                    program_id=f"loose:{unit_id}",
                    action_type=str(step.get("step_type") or "unit-work"),
                    subject_id=unit_id,
                    owner_skill=_unit_owner_skill(kind),
                    stage="loose-unit",
                    goal=str(record.get("title") or ""),
                    question="",
                    reason=str(step.get("reason") or ""),
                    title=str(record.get("title") or ""),
                    subject_kind=kind,
                    dependencies=[
                        {
                            "kind": "unit-state",
                            "id": unit_id,
                            "workflow_state": record_workflow_state(record),
                            "record_digest": _canonical_digest(record),
                        }
                    ],
                    governance_gate=governance_gate,
                    safe_execute_capability=bool(step.get("safe_execute")),
                    command_parts=[str(part) for part in step.get("command_parts") or []],
                    recommended_command=str(step.get("recommended_command") or ""),
                )
            )

        for card in judgement_cards:
            subject = card.get("subject") if isinstance(card.get("subject"), dict) else {}
            key = (str(subject.get("kind") or ""), str(subject.get("id") or ""))
            if key in attached_judgements:
                continue
            candidates.append(
                _judgement_candidate(
                    card,
                    program_id=f"review:{key[0]}:{key[1]}",
                    stage="pending-review",
                    goal="Review a verified research judgement.",
                    question="",
                    record_by_id=record_by_id,
                )
            )
            attached_judgements.add(key)

    for due in due_subscriptions(root):
        linked_program_ids = [str(item) for item in due.get("program_ids") or [] if str(item)]
        if selected_program_id and selected_program_id not in linked_program_ids:
            continue
        subscription_id = str(due.get("subscription_id") or "")
        candidates.append(
            _candidate(
                program_id=f"monitor:{subscription_id}",
                action_type="run-due-monitor",
                subject_id=subscription_id,
                owner_skill="research-monitor",
                stage="monitor-due",
                goal=str(due.get("title") or subscription_id),
                question="",
                reason="A saved research subscription is due for an Agent-led monitoring run.",
                title=str(due.get("title") or subscription_id),
                subject_kind="research-monitor-subscription",
                dependencies=[
                    {
                        "kind": "monitor-due-window",
                        "id": subscription_id,
                        "due_at": str(due.get("due_at") or ""),
                        "overdue_windows": int(due.get("overdue_windows") or 0),
                        "subscription_revision": int(due.get("subscription_revision") or 0),
                        "scope_digest": str(due.get("scope_digest") or ""),
                        "program_ids": linked_program_ids,
                    }
                ],
                safe_execute_capability=False,
            )
        )

    for outcome in unresolved_monitor_outcomes(root):
        linked_program_ids = [str(item) for item in outcome.get("program_ids") or [] if str(item)]
        if selected_program_id and selected_program_id not in linked_program_ids:
            continue
        run_id = str(outcome.get("run_id") or "")
        outcome_id = str(outcome.get("outcome_id") or "")
        classification = str(outcome.get("classification") or "")
        candidates.append(
            _candidate(
                program_id=f"monitor:{outcome.get('subscription_id') or run_id}",
                action_type="resolve-monitor-outcome",
                subject_id=f"{run_id}:{outcome_id}",
                discriminator=classification,
                owner_skill="research-monitor",
                stage="monitor-outcome",
                goal=str(outcome.get("subscription_title") or "Resolve a monitoring result."),
                question="",
                reason=str(outcome.get("rationale") or "A completed monitor result needs disposition."),
                title=str(outcome.get("subject_ref") or outcome_id),
                subject_kind="research-monitor-outcome",
                dependencies=[
                    {
                        "kind": "monitor-outcome-binding",
                        "id": f"{run_id}:{outcome_id}",
                        "run_revision": int(outcome.get("run_revision") or 0),
                        "run_content_digest": str(outcome.get("run_content_digest") or ""),
                        "outcome_binding_digest": str(outcome.get("outcome_binding_digest") or ""),
                        "classification": classification,
                        "program_ids": linked_program_ids,
                    }
                ],
                governance_gate="human-decision"
                if classification in {"new", "worth_reviewing", "contradiction_candidate"}
                else "none",
                safe_execute_capability=False,
            )
        )

    action_ids = [str(item.get("action_id") or "") for item in candidates]
    if len(action_ids) != len(set(action_ids)):
        raise SystemExit("Portfolio candidate identities are not unique")
    candidates.sort(key=lambda item: str(item.get("action_id") or ""))
    program_contexts.sort(key=lambda item: str(item.get("program_id") or ""))
    return candidates, program_contexts


def portfolio_candidate_snapshot(root: Path, *, selected_program_id: str = "") -> dict[str, Any]:
    candidates, program_contexts = portfolio_candidates(root, selected_program_id=selected_program_id)
    scope = {
        "program_ids": [selected_program_id] if selected_program_id else [],
        "include_loose_units": not bool(selected_program_id),
    }
    digest_input = {
        "schema_version": 1,
        "scope": scope,
        "program_contexts": program_contexts,
        "candidates": candidates,
    }
    return {
        **digest_input,
        "candidate_snapshot_digest": _canonical_digest(digest_input),
        "candidate_count": len(candidates),
    }


def portfolio_decision_fill_template(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": "",
        "candidate_snapshot_digest": str(snapshot.get("candidate_snapshot_digest") or ""),
        "selected_action_ids": [],
        "rationale": "",
        "expected_information_gain": "",
        "cost_and_risk": "",
        "preference_selection_id": "",
        "decision_scope": "procedural_planning",
        "program_decision_ids": [],
        "decided_at": "",
    }


def _load_portfolio_history(root: Path) -> dict[str, Any]:
    path = portfolio_history_path(root)
    if path.parent.is_symlink() or path.is_symlink() or (path.exists() and not path.is_file()):
        raise SystemExit("Portfolio history must be a regular file")
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict):
        return {"id": PORTFOLIO_HISTORY_ID, "generated_by": "research-orchestrator", "items": []}
    items = payload.get("items", [])
    payload["items"] = [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    payload.setdefault("id", PORTFOLIO_HISTORY_ID)
    payload.setdefault("generated_by", "research-orchestrator")
    return payload


def _validate_preference_selection_reference(root: Path, selection_id: str, task_context_digest: str) -> None:
    if not selection_id:
        raise SystemExit("Portfolio decision requires an effective preference selection")
    try:
        load_effective_selection(
            root,
            selection_id=selection_id,
            skill="research-orchestrator",
            operation="plan",
            expected_task_context_digest=task_context_digest,
        )
    except ValueError as exc:
        raise SystemExit("Referenced preference selection is unavailable, invalid, or stale") from exc


def _validate_program_decision_references(
    root: Path,
    decision_ids: list[str],
    selected: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not decision_ids:
        raise SystemExit("Research-judgement planning requires a program decision reference")
    selected_programs = {
        str(item.get("program_id") or "")
        for item in selected
        if str(item.get("program_id") or "") and not str(item.get("program_id") or "").startswith("loose:")
    }
    bindings: dict[str, dict[str, Any]] = {}
    for reference in decision_ids:
        program_id, separator, decision_id = str(reference).partition(":")
        if not separator or program_id not in selected_programs or not decision_id:
            raise SystemExit("Program decision reference is not bound to a selected program")
        matches = [
            item
            for item in decision_items_with_legacy(root, program_id)
            if str(item.get("id") or "") == decision_id and not item.get("legacy_import")
        ]
        if len(matches) != 1:
            raise SystemExit("Program decision reference is unavailable or unverified")
        record = matches[0]
        confirmation_status = str(record.get("confirmation_status") or "")
        if confirmation_status not in {
            "pending_user_confirmation",
            "confirmed",
        }:
            raise SystemExit("Program decision reference has an invalid confirmation state")
        artifact_path = decisions_path(root, program_id)
        if confirmation_status == "pending_user_confirmation":
            if readiness_violations(root, record, artifact_path):
                raise SystemExit("Program decision reference is unavailable or unverified")
        elif not judgement_confirmation_is_current(root, record, artifact_path):
            raise SystemExit("Program decision confirmation is unavailable or stale")
        binding = judgement_snapshot_binding(
            record,
            owner="research-orchestrator",
            path=artifact_path.relative_to(root).as_posix(),
        )
        binding["confirmation_digest"] = _canonical_digest(record.get("confirmation") or {})
        bindings[reference] = binding
    return bindings


def _aware_iso_timestamp(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit("Portfolio decision decided_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit("Portfolio decision decided_at must include a timezone")
    return text


def validate_portfolio_decision(
    root: Path,
    decision: object,
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(decision, dict):
        raise SystemExit("Portfolio decision fill must be a mapping")
    decision_id = str(decision.get("decision_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", decision_id):
        raise SystemExit("Portfolio decision id is invalid")
    expected_digest = str(snapshot.get("candidate_snapshot_digest") or "")
    if str(decision.get("candidate_snapshot_digest") or "") != expected_digest:
        raise SystemExit("Portfolio decision is stale: candidate snapshot changed")
    raw_selected = decision.get("selected_action_ids")
    if not isinstance(raw_selected, list) or not raw_selected:
        raise SystemExit("Portfolio decision must select at least one candidate action")
    selected_ids = [str(item or "").strip() for item in raw_selected]
    if any(not item for item in selected_ids) or len(set(selected_ids)) != len(selected_ids):
        raise SystemExit("Portfolio decision selected_action_ids must be unique non-empty ids")
    candidate_by_id = {
        str(item.get("action_id") or ""): item
        for item in snapshot.get("candidates", [])
        if isinstance(item, dict)
    }
    unknown = [item for item in selected_ids if item not in candidate_by_id]
    if unknown:
        raise SystemExit("Portfolio decision selected an action outside the current snapshot")
    selected = [candidate_by_id[item] for item in selected_ids]
    for field in ("rationale", "expected_information_gain", "cost_and_risk"):
        if not str(decision.get(field) or "").strip():
            raise SystemExit(f"Portfolio decision requires non-empty {field}")
    preference_selection_id = str(decision.get("preference_selection_id") or "").strip()
    _validate_preference_selection_reference(root, preference_selection_id, expected_digest)
    decision_scope = str(decision.get("decision_scope") or "procedural_planning").strip()
    if decision_scope not in PORTFOLIO_DECISION_SCOPES:
        raise SystemExit("Portfolio decision_scope is invalid")
    raw_program_decision_ids = decision.get("program_decision_ids", [])
    if not isinstance(raw_program_decision_ids, list):
        raise SystemExit("Portfolio decision program_decision_ids must be a list")
    program_decision_ids = [str(item or "").strip() for item in raw_program_decision_ids if str(item or "").strip()]
    if len(set(program_decision_ids)) != len(program_decision_ids):
        raise SystemExit("Portfolio decision program_decision_ids must be unique")
    program_decision_bindings: dict[str, dict[str, Any]] = {}
    if decision_scope == "research_judgement":
        program_decision_bindings = _validate_program_decision_references(
            root,
            program_decision_ids,
            selected,
        )
    elif program_decision_ids:
        raise SystemExit("Procedural planning cannot attach research decision references")
    decided_at = _aware_iso_timestamp(decision.get("decided_at"))
    normalized = {
        "decision_id": decision_id,
        "kind": PORTFOLIO_DECISION_KIND,
        "candidate_snapshot_digest": expected_digest,
        "scope": snapshot.get("scope") if isinstance(snapshot.get("scope"), dict) else {},
        "selected_action_ids": selected_ids,
        "selected_action_bindings": {
            str(item.get("action_id") or ""): str(item.get("binding_digest") or "") for item in selected
        },
        "selected_action_summaries": [
            {
                "action_id": str(item.get("action_id") or ""),
                "program_id": str(item.get("program_id") or ""),
                "action_type": str(item.get("action_type") or ""),
                "owner_skill": str(item.get("owner_skill") or ""),
                "subject": item.get("subject") if isinstance(item.get("subject"), dict) else {},
                "governance_gate": str(item.get("governance_gate") or "none"),
                "safe_execute_capability": bool(item.get("safe_execute_capability")),
                "binding_digest": str(item.get("binding_digest") or ""),
            }
            for item in selected
        ],
        "rationale": str(decision.get("rationale") or "").strip(),
        "expected_information_gain": str(decision.get("expected_information_gain") or "").strip(),
        "cost_and_risk": str(decision.get("cost_and_risk") or "").strip(),
        "preference_selection_id": preference_selection_id,
        "decision_scope": decision_scope,
        "program_decision_ids": program_decision_ids,
        "program_decision_bindings": program_decision_bindings,
        "decided_at": decided_at,
        "generated_by": "runtime-agent",
        "status": "recorded",
        "safe_to_continue": bool(selected)
        and decision_scope == "procedural_planning"
        and all(bool(item.get("safe_execute_capability")) and item.get("governance_gate") == "none" for item in selected),
    }
    return normalized, selected


def load_portfolio_decision_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Portfolio decision fill must be a regular file")
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict):
        raise SystemExit("Portfolio decision fill must contain a mapping")
    return payload


def current_portfolio_decision(root: Path, snapshot: dict[str, Any]) -> dict[str, Any] | None:
    scope = snapshot.get("scope") if isinstance(snapshot.get("scope"), dict) else {}
    matching = [
        item
        for item in _load_portfolio_history(root).get("items", [])
        if isinstance(item, dict) and item.get("scope") == scope
    ]
    if not matching:
        return None
    current = dict(matching[-1])
    stale_reasons: list[str] = []
    if str(current.get("candidate_snapshot_digest") or "") != str(snapshot.get("candidate_snapshot_digest") or ""):
        stale_reasons.append("candidate_snapshot_changed")
    current_candidates = {
        str(item.get("action_id") or ""): item
        for item in snapshot.get("candidates", [])
        if isinstance(item, dict)
    }
    bindings = current.get("selected_action_bindings") if isinstance(current.get("selected_action_bindings"), dict) else {}
    for action_id in current.get("selected_action_ids", []):
        candidate = current_candidates.get(str(action_id))
        if candidate is None:
            stale_reasons.append("selected_action_missing")
            continue
        if str(bindings.get(str(action_id)) or "") != str(candidate.get("binding_digest") or ""):
            stale_reasons.append("selected_action_changed")
    if str(current.get("decision_scope") or "") == "research_judgement":
        selected = [
            current_candidates[str(action_id)]
            for action_id in current.get("selected_action_ids", [])
            if str(action_id) in current_candidates
        ]
        try:
            current_program_bindings = _validate_program_decision_references(
                root,
                [str(item) for item in current.get("program_decision_ids", [])],
                selected,
            )
        except SystemExit:
            stale_reasons.append("program_decision_stale")
        else:
            stored_program_bindings = current.get("program_decision_bindings")
            if not isinstance(stored_program_bindings, dict) or stored_program_bindings != current_program_bindings:
                stale_reasons.append("program_decision_changed")
    try:
        _validate_preference_selection_reference(
            root,
            str(current.get("preference_selection_id") or ""),
            str(snapshot.get("candidate_snapshot_digest") or ""),
        )
    except SystemExit:
        stale_reasons.append("preference_selection_stale")
    current["effective_status"] = "stale" if stale_reasons else "current"
    current["stale_reasons"] = sorted(set(stale_reasons))
    if not stale_reasons:
        current["selected_actions"] = [
            current_candidates[str(action_id)]
            for action_id in current.get("selected_action_ids", [])
            if str(action_id) in current_candidates
        ]
    else:
        current["selected_actions"] = []
        current["safe_to_continue"] = False
    return current


def _validate_portfolio_history_target(root: Path) -> Path:
    programs = kb_root(root) / "programs"
    path = portfolio_history_path(root)
    if programs.is_symlink() or path.is_symlink():
        raise SystemExit("Portfolio history target cannot be a symlink")
    resolved_root = kb_root(root).resolve()
    try:
        path.resolve().relative_to(resolved_root)
    except ValueError as exc:
        raise SystemExit("Portfolio history target must stay inside kb") from exc
    return path


def record_portfolio_decision(
    root: Path,
    decision: dict[str, Any],
    *,
    selected_program_id: str = "",
) -> tuple[dict[str, Any], bool]:
    # Validate once before a mutation is opened, then recompute and validate
    # under the workspace/exact-target transaction to close the stale-write gap.
    initial_snapshot = portfolio_candidate_snapshot(root, selected_program_id=selected_program_id)
    validate_portfolio_decision(root, decision, initial_snapshot)
    path = _validate_portfolio_history_target(root)
    changed = False
    stored: dict[str, Any] = {}
    with mutation_transaction(root, "research-orchestrator:record-next-selection", [path]):
        current_snapshot = portfolio_candidate_snapshot(root, selected_program_id=selected_program_id)
        normalized, selected = validate_portfolio_decision(root, decision, current_snapshot)
        history = _load_portfolio_history(root)
        existing = [
            item
            for item in history.get("items", [])
            if isinstance(item, dict) and str(item.get("decision_id") or "") == normalized["decision_id"]
        ]
        if existing:
            comparable = dict(existing[0])
            comparable.pop("recorded_at", None)
            if comparable != normalized:
                raise SystemExit("Portfolio decision id is already bound to different content")
            stored = existing[0]
        else:
            stored = {**normalized, "recorded_at": utc_now_iso()}
            history.setdefault("items", []).append(stored)
            history["generated_at"] = utc_now_iso()
            write_yaml_if_changed(path, history)
            changed = True
    if changed:
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: record portfolio decision {stored['decision_id']}",
            target_paths=[path],
        )
    return stored, changed


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
            f"- `{item['program_id']}` · stage={item.get('stage') or 'init'} · {reasons}"
        )
        lines.append(f"  next: {item.get('next_action')}")
        lines.append("  操作：可运行 kb next，或直接让 AI 推进上述事项。")
    return "\n".join(lines).strip()


def _portfolio_public_action_label(candidate: dict[str, Any]) -> str:
    return {
        "resolve-evidence-request": "补齐一项证据请求",
        "agent-fill": "补全一项有证据支撑的分析",
        "agent-verify": "重新核验一项分析及其证据",
        "answer-open-question": "回答一个尚未解决的研究问题",
        "human-decision": "请你审阅一项已经核验的判断",
        "persisted-program-action": "继续一项已经保存的研究工作",
        "review-program-stage": "检查当前阶段并形成有依据的后续行动",
        "screen": "对一项资料做初步筛选",
        "generate-note": "整理一项资料的完整分析",
        "refresh": "刷新一项资料的结构或分析",
        "run-due-monitor": "执行一项已到期的研究跟踪",
    }.get(str(candidate.get("action_type") or ""), "继续一项当前可行的研究工作")


def format_portfolio_dashboard(snapshot: dict[str, Any]) -> str:
    candidates = [item for item in snapshot.get("candidates", []) if isinstance(item, dict)]
    if not candidates:
        return "# Program Dashboard\n\n- 当前没有待比较的研究行动。"
    grouped: dict[str, int] = {}
    for item in candidates:
        program_id = str(item.get("program_id") or "")
        grouped[program_id] = grouped.get(program_id, 0) + 1
    lines = ["# Program Dashboard", "", "以下是供 Agent 比较的事实候选，不代表优先级："]
    for program_id in sorted(grouped):
        lines.append(f"- 研究计划「{program_id}」：{grouped[program_id]} 项可行行动")
    return "\n".join(lines).strip()


def format_portfolio_next(
    snapshot: dict[str, Any],
    current: dict[str, Any] | None,
    *,
    has_records: bool,
) -> str:
    candidates = [item for item in snapshot.get("candidates", []) if isinstance(item, dict)]
    if not candidates:
        if has_records:
            return "知识库已有资料，但目前没有待处理事项。"
        return "知识库还是空的。请告诉我一篇论文、一个代码仓或一篇博客的来源，或使用 kb ingest 添加资料。"
    if current is None:
        return f"Agent 需要先比较当前 {len(candidates)} 项可行行动，再说明为什么选择其中的下一步。"
    if str(current.get("effective_status") or "") != "current":
        return "研究状态已发生变化，旧的下一步选择不再有效；Agent 需要根据当前信息重新规划。"
    lines = ["Agent 已根据当前研究状态选择下一步："]
    for candidate in current.get("selected_actions", []):
        if not isinstance(candidate, dict):
            continue
        program_id = str(candidate.get("program_id") or "")
        lines.append(f"- 研究计划「{program_id}」：{_portfolio_public_action_label(candidate)}。")
    has_human_gate = any(
        isinstance(candidate, dict) and str(candidate.get("governance_gate") or "") != "none"
        for candidate in current.get("selected_actions", [])
    )
    if has_human_gate:
        lines.append("其中包含需要你决定的事项，Agent 会先向你说明再继续。")
    elif str(current.get("decision_scope") or "") == "research_judgement":
        lines.append("这个选择涉及研究判断，必须继续走现有确认流程，不能自动执行。")
    else:
        lines.append("Agent 可以按这个选择继续推进；执行前仍会重新核对当前状态。")
    return "\n".join(lines)


def _legacy_next_item(candidate: dict[str, Any]) -> dict[str, Any]:
    subject = candidate.get("subject") if isinstance(candidate.get("subject"), dict) else {}
    gate = str(candidate.get("governance_gate") or "none")
    return {
        "program_id": str(candidate.get("program_id") or ""),
        "record_id": str(subject.get("id") or ""),
        "title": str(candidate.get("title") or ""),
        "step_type": "human-decision" if gate == "human-decision" else str(candidate.get("action_type") or ""),
        "action_kind": "human-gate" if gate == "human-decision" else "agent-work",
        "safe_execute": bool(candidate.get("safe_execute_capability")) and gate == "none",
        "stage": str(candidate.get("stage") or ""),
        "goal": str(candidate.get("goal") or ""),
        "question": str(candidate.get("question") or ""),
        "next_action": str(candidate.get("reason") or ""),
        "recommended_command": str(candidate.get("recommended_command") or ""),
        "portfolio_action_id": str(candidate.get("action_id") or ""),
    }


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

    dashboard = subparsers.add_parser("dashboard", help="Show factual program candidate context")
    dashboard.add_argument("--limit", type=int, default=20)

    next_cmd = subparsers.add_parser("next", help="Show the current Agent-selected next action or request planning")
    next_cmd.add_argument("--limit", type=int, default=5)
    next_cmd.add_argument("--program-id")
    next_cmd.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    prepare_next = subparsers.add_parser(
        "prepare-next-selection",
        help="Prepare an Agent-fillable portfolio decision without choosing a winner",
    )
    prepare_next.add_argument("--program-id")
    prepare_next.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    verify_next = subparsers.add_parser(
        "verify-next-selection",
        help="Verify an Agent-authored portfolio decision against current state",
    )
    verify_next.add_argument("--selection-file", required=True)
    verify_next.add_argument("--program-id")
    verify_next.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    record_next = subparsers.add_parser(
        "record-next-selection",
        help="Record a verified Agent-authored portfolio decision",
    )
    record_next.add_argument("--selection-file", required=True)
    record_next.add_argument("--program-id")

    auto = subparsers.add_parser("auto", help="Plan or execute the next safe orchestration step")
    auto.add_argument("--max-steps", type=int, default=1)
    auto.add_argument("--execute", action="store_true")

    route = subparsers.add_parser("route", help="Suggest the right skill for a task")
    route.add_argument("--task", required=True)
    route.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    route.add_argument("--decision-file", help=argparse.SUPPRESS)

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


def _program_decision_context(
    root: Path,
    program_id: str,
    decision_id: str,
    expected_snapshot: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    decisions_yaml = decisions_path(root, program_id)
    items = list_items(decisions_yaml, f"{program_id}-decisions", "research-orchestrator")
    matches = [item for item in items if str(item.get("id") or "") == decision_id]
    if len(matches) != 1:
        raise ValueError("program decision is no longer uniquely available")
    selected = matches[0]
    violations = readiness_violations(root, selected, decisions_yaml)
    if violations:
        raise ValueError("program decision is no longer ready")
    require_judgement_snapshot(
        selected,
        expected_snapshot=expected_snapshot,
        owner="research-orchestrator",
        path=decisions_yaml.relative_to(root).as_posix(),
        root=root,
    )
    return items, selected, decisions_yaml


def prepare_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> dict:
    route = item.get("confirm_route" if decision == "confirm" else "reject_route")
    route = route if isinstance(route, dict) else {}
    expected_action = "confirm-decision" if decision == "confirm" else "reject-decision"
    if route.get("owner") != "research-orchestrator" or route.get("action") != expected_action:
        raise ValueError("program decision route is invalid")
    snapshot = item.get("snapshot_binding")
    if not isinstance(snapshot, dict):
        raise ValueError("program decision snapshot is missing")
    program_id = str(route.get("program_id") or "")
    decision_id = str(route.get("decision_id") or "")
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _items, selected, decisions_yaml = _program_decision_context(root, program_id, decision_id, snapshot_text)
    candidate = dict(selected)
    if decision == "confirm":
        claims = candidate.get("payload", {}).get("claims", [])
        apply_confirmation(
            candidate,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="orchestrate.py confirm-decision",
            project_root=root,
            verification_root=program_root(root, program_id),
            trusted_source_roots=_decision_source_roots(root, program_id, claims),
        )
        targets = [decisions_yaml, decision_log_path(root, program_id), reporting_events_path(root, program_id), state_path(root, program_id)]
    elif decision == "reject":
        apply_judgement_rejection(candidate, reason=rejection_reason)
        targets = [decisions_yaml, decision_log_path(root, program_id), state_path(root, program_id)]
    else:
        raise ValueError("program decision is invalid")
    return {
        "owner": "research-orchestrator",
        "decision": decision,
        "program_id": program_id,
        "decision_id": decision_id,
        "target_paths": targets,
    }


def apply_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> list[Path]:
    plan = prepare_review_batch_decision(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        rejection_reason=rejection_reason,
    )
    snapshot_text = json.dumps(item["snapshot_binding"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    items, selected, decisions_yaml = _program_decision_context(
        root, plan["program_id"], plan["decision_id"], snapshot_text
    )
    if decision == "confirm":
        claims = selected.get("payload", {}).get("claims", [])
        apply_confirmation(
            selected,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="orchestrate.py confirm-decision",
            project_root=root,
            verification_root=program_root(root, plan["program_id"]),
            trusted_source_roots=_decision_source_roots(root, plan["program_id"], claims),
        )
        decisions_yaml, log_path = write_decisions(root, plan["program_id"], items)
        decision_payload = selected.get("payload", {}).get("decision", {})
        append_program_reporting_event(
            root,
            plan["program_id"],
            {
                "source_skill": "research-orchestrator",
                "event_type": "decision-confirmed",
                "title": str(decision_payload.get("text") or plan["decision_id"]),
                "summary": str(decision_payload.get("rationale") or ""),
                "stage": str(decision_payload.get("stage") or ""),
                "tags": ["decision", "confirmed"],
                "artifacts": [decisions_yaml.relative_to(root).as_posix(), log_path.relative_to(root).as_posix()],
                "epistemic_type": "judgement",
                "information_types": ["inference", "evaluation"],
                "confirmation_status": "confirmed",
                "confirmation_binding": confirmation_binding(
                    selected, owner="research-orchestrator", path=decisions_yaml.relative_to(root).as_posix()
                ),
            },
            generated_by="research-orchestrator",
        )
        confirmation_status = "confirmed"
    else:
        apply_judgement_rejection(selected, reason=rejection_reason)
        selected["updated_at"] = utc_now_iso()
        _yaml_path, _log_path = write_decisions(root, plan["program_id"], items)
        decision_payload = selected.get("payload", {}).get("decision", {})
        confirmation_status = "rejected"
    state = load_state(root, plan["program_id"])
    state["last_decision"] = {
        "id": plan["decision_id"],
        "decision": str(decision_payload.get("text") or ""),
        "timestamp": str(selected.get("timestamp") or ""),
        "confirmation_status": confirmation_status,
    }
    # The root Obsidian transaction has already declared every mutable target.
    # Do not let the general state writer materialize unrelated workflow files
    # behind the coordinator's back.
    state = refresh_state_counts(root, plan["program_id"], state, materialize=False)
    write_yaml_if_changed(state_path(root, plan["program_id"]), state)
    return list(plan["target_paths"])


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
        print(format_portfolio_dashboard(portfolio_candidate_snapshot(root)))
        return 0
    if args.command in {
        "next",
        "prepare-next-selection",
        "verify-next-selection",
        "record-next-selection",
    }:
        selected_program_id = str(getattr(args, "program_id", None) or "")
        if selected_program_id and not program_root(root, selected_program_id).is_dir():
            existing = ", ".join(program_ids(root)) or "(none)"
            raise SystemExit(
                f"program `{selected_program_id}` not found; existing: {existing}. "
                "Use init-program to create it."
            )
        snapshot = portfolio_candidate_snapshot(root, selected_program_id=selected_program_id)
        has_records = bool(iter_records(root))
        if args.command == "prepare-next-selection":
            payload = {
                "candidate_snapshot": snapshot,
                "portfolio_decision_fill": portfolio_decision_fill_template(snapshot),
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            else:
                print(
                    f"Agent 可以从当前 {snapshot['candidate_count']} 项可行行动中进行比较；"
                    "脚本尚未选择任何下一步。"
                )
            return 0
        if args.command in {"verify-next-selection", "record-next-selection"}:
            fill_path = Path(args.selection_file).expanduser()
            if not fill_path.is_absolute():
                fill_path = root / fill_path
            decision = load_portfolio_decision_file(fill_path)
            if args.command == "verify-next-selection":
                normalized, selected = validate_portfolio_decision(root, decision, snapshot)
                payload = {"status": "verified", "decision": normalized, "selected_actions": selected}
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                else:
                    print("Agent 提交的下一步选择与当前状态一致，可以记录。")
                return 0
            stored, changed = record_portfolio_decision(
                root,
                decision,
                selected_program_id=selected_program_id,
            )
            status = "recorded" if changed else "already recorded"
            print(f"[ok] portfolio decision {stored['decision_id']} {status}")
            return 0
        current = current_portfolio_decision(root, snapshot)
        planning_required = current is None or str(current.get("effective_status") or "") != "current"
        if not planning_required:
            items = [_legacy_next_item(item) for item in current.get("selected_actions", [])]
            if str(current.get("decision_scope") or "") == "research_judgement":
                for item in items:
                    item["safe_execute"] = False
                    item["action_kind"] = "human-gate"
        else:
            items = []
        if args.json:
            print(
                json.dumps(
                    {
                        "has_records": has_records,
                        "items": items,
                        "candidate_snapshot": snapshot,
                        "portfolio_decision_fill": portfolio_decision_fill_template(snapshot),
                        "portfolio_decision": current,
                        "planning_required": planning_required,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(format_portfolio_next(snapshot, current, has_records=has_records))
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
        snapshot = route_candidate_snapshot(args.task)
        decision = None
        if args.decision_file:
            fill_path = Path(args.decision_file).expanduser()
            if not fill_path.is_absolute():
                fill_path = root / fill_path
            decision = validate_route_decision(load_portfolio_decision_file(fill_path), snapshot)
        if args.json:
            print(
                json.dumps(
                    {
                        "route_snapshot": snapshot,
                        "route_decision_fill": route_decision_fill_template(snapshot),
                        "route_decision": decision,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(str(snapshot.get("direct_owner") or "research-orchestrator"))
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

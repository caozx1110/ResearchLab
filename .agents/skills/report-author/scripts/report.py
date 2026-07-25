#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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

from research.common import add_project_root_argument, load_program_reporting_events, load_yaml, print_resolved_project_roots, write_text_if_changed
from research.core import command_mutation, ensure_workspace, checkpoint_and_report, project_root, user_root
from research.evidence import read_claims, validate_claims
from research.judgements import confirmation_binding, judgement_confirmation_is_current, load_bound_judgement
from research.preference_selection import resolve_task_preferences, selection_binding
from research.records import (
    CanonicalRecordSnapshot,
    iter_canonical_record_snapshots,
    normalize_record_snapshot,
    snapshot_canonical_unit_artifacts,
)
from research.surveys import survey_staleness


UNIT_ID_FIELDS = {
    "unit_id",
    "unit_ids",
    "related_unit_ids",
    "active_unit_ids",
    "blog_id",
    "blog_ids",
    "dataset_id",
    "dataset_ids",
    "experiment_id",
    "experiment_ids",
    "idea_id",
    "idea_ids",
    "paper_id",
    "paper_ids",
    "repo_id",
    "repo_ids",
}
UNIT_PATH_RE = re.compile(r"(?:^|/)kb/units/(?:papers|repos|datasets|blogs|ideas|experiments)/([^/]+)(?:/|$)")
DECISION_HEADING_RE = re.compile(r"^##\s+(.+)$", flags=re.MULTILINE)
CONCISE_STYLE_SIGNALS = ("简洁", "concise", "brief")
DETAILED_STYLE_SIGNALS = ("详细", "detailed", "full")
DEFAULT_REPORT_LANGUAGE = "zh-CN"
REPORT_PRESENTATION_CONTRACT = "report-presentation/v2"
ENGLISH_LANGUAGE_RE = re.compile(r"(?:en(?:[-_][a-z0-9]+)*|english(?:\b.*)?)", re.IGNORECASE)
CONCISE_DECISION_LIMIT = 3
CONCISE_SOURCE_LIMIT = 3
CONCISE_CLAIM_LIMIT = 3
CONCISE_EVENT_LIMIT = 5
JUDGEMENT_INFORMATION_TYPES = {"inference", "evaluation", "user_opinion", "unverified"}
JUDGEMENT_EVENT_TOKENS = {
    "decision",
    "diagnosis",
    "evaluation",
    "inference",
    "novelty",
    "conclusion",
    "survey",
}
JUDGEMENT_OWNER_BY_KIND = {
    "paper": "paper-analyst",
    "repo": "repo-analyst",
    "dataset": "dataset-analyst",
    "blog": "blog-analyst",
    "idea": "idea-workbench",
    "experiment": "experiment-workbench",
    "program_decision": "research-orchestrator",
    "idea_discussion_conclusion": "idea-workbench",
    "method_selection": "method-designer",
    "survey_judgement": "literature-synthesizer",
}
OPERATIONAL_EVENT_TYPES = {
    "program-created",
    "stage-changed",
    "next-action-added",
    "next-action-resolved",
    "evidence-requested",
    "evidence-fulfilled",
    "experiment-planned",
    "experiment-run",
    "experiment-follow-up",
    "phase-completed",
}


@dataclass
class ClaimSource:
    unit_id: str
    title: str
    kind: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    binding_digest: str = ""


@dataclass
class ReportInputs:
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_judgement_events: list[dict[str, Any]] = field(default_factory=list)
    claim_sources: list[ClaimSource] = field(default_factory=list)
    decisions: list[dict[str, str]] = field(default_factory=list)
    missing_units: list[str] = field(default_factory=list)
    reporting_style: str = "default"
    language: str = DEFAULT_REPORT_LANGUAGE
    preference_binding: dict[str, object] = field(default_factory=dict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate evidence-backed reports.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("weekly", "ppt-materials", "stage-summary", "writing-materials", "outline"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--program-id", required=True)
        cmd.add_argument("--stage", default="")
        cmd.add_argument("--limit", type=int, default=20)
        cmd.add_argument("--preference-selection-id", default="")
    return parser


def normalize_events(events: list[dict[str, Any]], *, stage: str = "", limit: int = 20) -> list[dict[str, Any]]:
    filtered = []
    for item in events:
        if stage and str(item.get("stage") or "").strip() != stage:
            continue
        filtered.append(item)
    if limit > 0:
        filtered = filtered[-limit:]
    return filtered


def _event_is_judgement(event: dict[str, Any]) -> bool:
    epistemic_type = str(event.get("epistemic_type") or "").strip().casefold()
    information_types = {item.casefold() for item in _text_items(event.get("information_types"))}
    event_type_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", str(event.get("event_type") or "").casefold())
        if token
    }
    event_type = str(event.get("event_type") or "").strip().casefold()
    has_governance_binding = any(
        field in event
        for field in ("confirmation_binding", "confirmation_status", "needs_human_confirmation")
    )
    if (
        epistemic_type == "judgement"
        or bool(information_types & JUDGEMENT_INFORMATION_TYPES)
        or bool(event_type_tokens & JUDGEMENT_EVENT_TOKENS)
        or has_governance_binding
    ):
        return True
    if epistemic_type in {"fact", "factual", "operational"}:
        return False
    if event_type in {"fact", "factual", "operational"}:
        return False
    if event_type in OPERATIONAL_EVENT_TYPES:
        return False
    # Unknown/untyped report events are not entitled to the factual lane.
    return True


def _confirmed_judgement_event(root: Path, event: dict[str, Any]) -> tuple[bool, str]:
    binding = event.get("confirmation_binding")
    binding = binding if isinstance(binding, dict) else {}
    subject = binding.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    subject_id = str(subject.get("id") or "").strip()
    subject_kind = str(subject.get("kind") or "").strip()
    bound_claim_ids = sorted(_text_items(binding.get("claim_ids")))
    bound_content_digest = str(binding.get("content_digest") or "").strip()
    bound_verification = binding.get("verification")
    bound_verification = bound_verification if isinstance(bound_verification, dict) else {}
    recorded_status = str(event.get("confirmation_status") or "").strip() or "missing"
    if not subject_id or not subject_kind:
        return False, (
            f"confirmation_status={recorded_status}; "
            "missing: canonical confirmation subject and claim/evidence binding"
        )
    if not bound_claim_ids:
        return False, f"confirmation_status={recorded_status}; missing: canonical claim/evidence binding"
    try:
        record, artifact_path = load_bound_judgement(root, subject)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return False, f"confirmation_status={recorded_status}; missing: bound record {subject_id}"
    if str(record.get("id") or "") != subject_id or str(record.get("kind") or "") != subject_kind:
        return False, f"confirmation_status={recorded_status}; missing: matching canonical subject"
    if str(record.get("confirmation_status") or "") != "confirmed":
        return False, f"confirmation_status={recorded_status}; missing: current ConfirmationReceipt"
    if not judgement_confirmation_is_current(root, record, artifact_path):
        return False, "confirmation_status=stale; missing: current ConfirmationReceipt"
    canonical_owner = JUDGEMENT_OWNER_BY_KIND.get(subject_kind)
    try:
        canonical_path = artifact_path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return False, "confirmation_status=stale; missing: canonical judgement binding"
    if not canonical_owner:
        return False, "confirmation_status=stale; missing: canonical judgement owner"
    expected_binding = confirmation_binding(
        record,
        owner=canonical_owner,
        path=canonical_path,
    )
    if binding != expected_binding:
        return False, "confirmation_status=stale; missing: exact current judgement binding"
    receipt = record.get("confirmation")
    receipt = receipt if isinstance(receipt, dict) else {}
    receipt_claim_ids = sorted(_text_items(receipt.get("claim_ids")))
    if bound_claim_ids != receipt_claim_ids:
        return False, "confirmation_status=stale; missing: current receipt for the event claim binding"
    if not bound_content_digest or bound_content_digest != str(receipt.get("content_digest") or ""):
        return False, "confirmation_status=stale; missing: current receipt for the event content binding"
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    current_verification = payload.get("verification")
    current_verification = current_verification if isinstance(current_verification, dict) else {}
    for field_name in ("verified_at", "claims_digest", "evidence_digest"):
        bound_value = str(bound_verification.get(field_name) or "")
        if not bound_value or bound_value != str(current_verification.get(field_name) or ""):
            return False, f"confirmation_status=stale; missing: current {field_name} event binding"
    return True, "confirmation_status=confirmed; current ConfirmationReceipt"


def _survey_event_staleness(root: Path, event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(event.get("event_type") or "").casefold()
    binding = event.get("confirmation_binding")
    binding = binding if isinstance(binding, dict) else {}
    subject = binding.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    subject_kind = str(subject.get("kind") or "").casefold()
    if "survey" not in event_type and "survey" not in subject_kind:
        return None
    raw_path = str(subject.get("path") or "").strip()
    if not raw_path:
        return {"stale": True, "reasons": ["missing survey path"], "new_unit_ids": []}
    project = root.resolve()
    synthesis = (project / "kb" / "synthesis").resolve()
    unresolved = project / raw_path
    try:
        relative = unresolved.relative_to(project)
    except ValueError:
        return {"stale": True, "reasons": ["unsafe survey path"], "new_unit_ids": []}
    cursor = project
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return {"stale": True, "reasons": ["unsafe survey path"], "new_unit_ids": []}
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(synthesis)
    except ValueError:
        return {"stale": True, "reasons": ["unsafe survey path"], "new_unit_ids": []}
    if candidate.is_symlink() or not candidate.is_file() or candidate.name != "survey.yaml":
        return {"stale": True, "reasons": ["missing survey artifact"], "new_unit_ids": []}
    try:
        payload = load_yaml(candidate, default={})
    except (OSError, RuntimeError, UnicodeError, yaml.YAMLError):
        return {"stale": True, "reasons": ["invalid survey artifact"], "new_unit_ids": []}
    if not isinstance(payload, dict):
        return {"stale": True, "reasons": ["invalid survey artifact"], "new_unit_ids": []}
    try:
        return survey_staleness(payload, root)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError, SystemExit):
        return {"stale": True, "reasons": ["unreadable survey upstream binding"], "new_unit_ids": []}


def partition_reporting_events(
    root: Path,
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordinary: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for event in events:
        normalized = dict(event)
        if not _event_is_judgement(normalized):
            ordinary.append(normalized)
            continue
        freshness = _survey_event_staleness(root, normalized)
        if isinstance(freshness, dict) and freshness.get("stale"):
            reasons = freshness.get("reasons")
            reason_count = len(reasons) if isinstance(reasons, list) else 1
            normalized["_epistemic_reason"] = (
                f"confirmation_status=stale; survey upstream binding changed ({reason_count} reason(s))"
            )
            pending.append(normalized)
            continue
        confirmed, reason = _confirmed_judgement_event(root, normalized)
        normalized["_epistemic_reason"] = reason
        if confirmed:
            normalized["_effective_confirmation_status"] = "confirmed"
            ordinary.append(normalized)
        else:
            pending.append(normalized)
    return ordinary, pending


def _normalize_reporting_style(value: object) -> str:
    style = str(value or "").casefold()
    if any(signal in style for signal in CONCISE_STYLE_SIGNALS):
        return "concise"
    if any(signal in style for signal in DETAILED_STYLE_SIGNALS):
        return "detailed"
    return "default"


def _normalize_report_language(value: object) -> str:
    """Return the only opt-in language override supported by the renderer.

    Chinese is the product default.  A canonical profile value is not enough:
    callers pass only values resolved from the current task-bound selection.
    Unknown, missing, or non-English values therefore remain Chinese.
    """
    language = str(value or "").strip()
    if language and ENGLISH_LANGUAGE_RE.fullmatch(language):
        return "en-US"
    return DEFAULT_REPORT_LANGUAGE


def _is_english(language: str) -> bool:
    return _normalize_report_language(language) == "en-US"


def _resolved_report_preferences(
    root: Path,
    *,
    preference_selection_id: str,
    operation: str,
    canonical_inputs: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    if not preference_selection_id:
        return {}, {}
    effective = resolve_task_preferences(
        root,
        selection_id=preference_selection_id,
        skill="report-author",
        operation=operation,
        canonical_inputs=canonical_inputs,
    )
    selected = {
        str(item.get("path") or ""): item.get("value")
        for item in effective.get("effective_items", [])
        if isinstance(item, dict)
    }
    return selected, selection_binding(effective)


def load_reporting_style(
    root: Path,
    *,
    preference_selection_id: str = "",
    operation: str = "",
    canonical_inputs: dict[str, object] | None = None,
) -> str:
    selected, _binding = _resolved_report_preferences(
        root,
        preference_selection_id=preference_selection_id,
        operation=operation,
        canonical_inputs=canonical_inputs or {},
    )
    if selected:
        return _normalize_reporting_style(selected.get("profile.personalization.reporting_style"))
    # A canonical profile is only a catalog.  Unselected soft style must be
    # neutral, including legacy top-level reporting_style values.
    return "default"


def load_report_language(
    root: Path,
    *,
    preference_selection_id: str = "",
    operation: str = "",
    canonical_inputs: dict[str, object] | None = None,
) -> str:
    selected, _binding = _resolved_report_preferences(
        root,
        preference_selection_id=preference_selection_id,
        operation=operation,
        canonical_inputs=canonical_inputs or {},
    )
    return _normalize_report_language(selected.get("profile.preferences.language_preference"))


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def report_input_snapshot(inputs: ReportInputs) -> dict[str, object]:
    """Return the exact pure-read input view consumed by report rendering.

    The caller places only this view's digest and bounded counts in the
    preference task context.  Raw event text, claims, and decisions therefore
    never get copied into the durable preference receipt.
    """
    return {
        "accepted_events": inputs.events,
        "pending_judgement_events": inputs.pending_judgement_events,
        "claim_sources": [
            {
                "unit_id": source.unit_id,
                "title": source.title,
                "kind": source.kind,
                "claims": source.claims,
                "issues": source.issues,
                "binding_digest": source.binding_digest,
            }
            for source in inputs.claim_sources
        ],
        "decisions": inputs.decisions,
        "missing_units": sorted(inputs.missing_units),
    }


def report_preference_context(
    program_id: str,
    *,
    operation: str,
    stage: str = "",
    limit: int = 20,
    inputs: ReportInputs,
) -> dict[str, object]:
    """Canonical owner inputs for one report preference binding."""
    snapshot = report_input_snapshot(inputs)
    return {
        "program_id": str(program_id),
        "operation": str(operation),
        "stage": str(stage),
        "limit": int(limit),
        "presentation_contract": REPORT_PRESENTATION_CONTRACT,
        "input_snapshot": {
            "digest": _canonical_digest(snapshot),
            "accepted_event_count": len(inputs.events),
            "pending_judgement_event_count": len(inputs.pending_judgement_events),
            "claim_source_count": len(inputs.claim_sources),
            "decision_count": len(inputs.decisions),
            "missing_unit_count": len(inputs.missing_units),
        },
    }


def _text_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _collect_unit_ids(value: Any, *, key: str = "") -> set[str]:
    unit_ids: set[str] = set()
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_name = str(child_key)
            if child_name in UNIT_ID_FIELDS:
                unit_ids.update(_text_items(child_value))
            unit_ids.update(_collect_unit_ids(child_value, key=child_name))
    elif isinstance(value, (list, tuple)):
        for child in value:
            unit_ids.update(_collect_unit_ids(child, key=key))
    elif isinstance(value, str):
        match = UNIT_PATH_RE.search(value)
        if match:
            unit_ids.add(match.group(1))
    return unit_ids


def program_unit_ids(root: Path, program_id: str, events: list[dict[str, Any]]) -> list[str]:
    state = load_yaml(root / "kb" / "programs" / program_id / "state.yaml", default={})
    unit_ids = _collect_unit_ids(state)
    unit_ids.update(_collect_unit_ids(events))
    return sorted(unit_ids)


def _same_record_snapshot(
    left: CanonicalRecordSnapshot,
    right: CanonicalRecordSnapshot,
) -> bool:
    return (
        left.kind == right.kind
        and left.unit_id == right.unit_id
        and left.path == right.path
        and left.raw_bytes == right.raw_bytes
        and left.file_identity == right.file_identity
    )


def _record_snapshot_is_current(root: Path, snapshot: CanonicalRecordSnapshot) -> bool:
    current = snapshot_canonical_unit_artifacts(
        root,
        snapshot.kind,
        snapshot.unit_id,
        (),
    )
    return bool(
        current is not None
        and _same_record_snapshot(snapshot, current.record)
        and current.is_current()
    )


def _load_exact_record_snapshot(
    root: Path,
    unit_id: str,
) -> tuple[CanonicalRecordSnapshot, dict[str, Any]] | None:
    matches = [
        snapshot
        for snapshot in iter_canonical_record_snapshots(root)
        if snapshot.unit_id == unit_id
    ]
    if len(matches) != 1:
        return None
    snapshot = matches[0]
    record = normalize_record_snapshot(snapshot, root)
    if record is None or not _record_snapshot_is_current(root, snapshot):
        return None
    return snapshot, record


def load_confirmed_claim_sources(root: Path, unit_ids: list[str]) -> tuple[list[ClaimSource], list[str]]:
    sources: list[ClaimSource] = []
    missing_units: list[str] = []
    for unit_id in unit_ids:
        selected = _load_exact_record_snapshot(root, unit_id)
        if selected is None:
            missing_units.append(unit_id)
            continue
        snapshot, record = selected
        canonical_claims = read_claims(record.get("payload"))
        receipt = record.get("confirmation") if isinstance(record.get("confirmation"), dict) else {}
        receipt_claim_ids = {
            str(claim_id)
            for claim_id in receipt.get("claim_ids", [])
            if str(claim_id).strip()
        }
        receipt_current = (
            str(record.get("confirmation_status") or "") == "confirmed"
            and judgement_confirmation_is_current(
                root,
                record,
                snapshot.path,
                record_snapshot=snapshot,
            )
        )
        if not _record_snapshot_is_current(root, snapshot):
            missing_units.append(unit_id)
            continue
        confirmed_claims = [
            claim
            for claim in canonical_claims
            if receipt_current and str(claim.get("id") or "") in receipt_claim_ids
        ]
        valid_claims: list[dict[str, Any]] = []
        issues: list[str] = []
        if canonical_claims and not receipt_current:
            issues.append("canonical claims are not bound to a current ConfirmationReceipt")
        for claim in confirmed_claims:
            violations = validate_claims([claim])
            if violations:
                issues.extend(violations)
            else:
                valid_claims.append({**claim, "confirmation_status": "confirmed"})
        sources.append(
            ClaimSource(
                unit_id=str(record.get("id") or unit_id),
                title=str(record.get("title") or unit_id),
                kind=str(record.get("kind") or "unit"),
                claims=valid_claims,
                issues=issues,
                binding_digest=_canonical_digest(
                    {
                        "source": record.get("source"),
                        "sources": record.get("sources"),
                        "confirmation": receipt,
                        "verification": (
                            record.get("payload", {}).get("verification")
                            if isinstance(record.get("payload"), dict)
                            else None
                        ),
                    }
                ),
            )
        )
    return sources, missing_units


def load_confirmed_survey_claim_source(
    root: Path,
    program_id: str,
    event: dict[str, Any],
) -> tuple[ClaimSource | None, str]:
    """Transport one exact current survey confirmation into report claims.

    The survey owner remains authoritative for the judgement.  This consumer
    only re-resolves the event subject, revalidates its current receipt/evidence
    bytes, and carries receipt-bound canonical claims into the report.
    """
    if str(event.get("event_type") or "") != "survey-confirmed":
        return None, ""
    binding = event.get("confirmation_binding")
    binding = binding if isinstance(binding, dict) else {}
    subject = binding.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    if str(subject.get("kind") or "") != "survey_judgement":
        return None, "confirmation_status=stale; missing: canonical survey subject"
    try:
        record, artifact_path = load_bound_judgement(root, subject)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None, "confirmation_status=stale; missing: bound survey judgement"
    confirmed, reason = _confirmed_judgement_event(root, event)
    if not confirmed:
        return None, reason
    program_ids = record.get("program_ids")
    if not isinstance(program_ids, list) or program_id not in program_ids:
        return None, "confirmation_status=stale; missing: survey binding for this program"
    canonical_claims = read_claims(record.get("payload"))
    receipt = record.get("confirmation")
    receipt = receipt if isinstance(receipt, dict) else {}
    receipt_claim_ids = sorted(_text_items(receipt.get("claim_ids")))
    current_claim_ids = sorted(
        str(claim.get("id") or "").strip()
        for claim in canonical_claims
        if str(claim.get("id") or "").strip()
    )
    if not canonical_claims or receipt_claim_ids != current_claim_ids:
        return None, "confirmation_status=stale; missing: receipt-bound canonical survey claims"
    violations = validate_claims(canonical_claims)
    if violations:
        return None, "confirmation_status=stale; missing: structurally valid survey claims and evidence"
    canonical_path = artifact_path.relative_to(root.resolve()).as_posix()
    expected_binding = confirmation_binding(
        record,
        owner="literature-synthesizer",
        path=canonical_path,
    )
    if binding != expected_binding or not judgement_confirmation_is_current(root, record, artifact_path):
        return None, "confirmation_status=stale; missing: exact current survey binding"
    return (
        ClaimSource(
            unit_id=str(record.get("id") or ""),
            title=str(record.get("slug") or record.get("id") or "survey"),
            kind="survey_judgement",
            claims=[{**claim, "confirmation_status": "confirmed"} for claim in canonical_claims],
            binding_digest=_canonical_digest(
                {
                    "confirmation_binding": expected_binding,
                    "survey_content_digest": record.get("survey_content_digest"),
                    "confirmation": receipt,
                    "verification": (
                        record.get("payload", {}).get("verification")
                        if isinstance(record.get("payload"), dict)
                        else None
                    ),
                }
            ),
        ),
        "",
    )


def attach_confirmed_survey_claim_sources(
    root: Path,
    program_id: str,
    events: list[dict[str, Any]],
    pending: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[ClaimSource]]:
    accepted: list[dict[str, Any]] = []
    pending_events = list(pending)
    sources: list[ClaimSource] = []
    seen_bindings: set[str] = set()
    for event in events:
        if str(event.get("event_type") or "") != "survey-confirmed":
            accepted.append(event)
            continue
        source, reason = load_confirmed_survey_claim_source(root, program_id, event)
        if source is None:
            normalized = dict(event)
            normalized.pop("_effective_confirmation_status", None)
            normalized["_epistemic_reason"] = reason or "confirmation_status=stale; missing: current survey claims"
            pending_events.append(normalized)
            continue
        accepted.append(event)
        if source.binding_digest not in seen_bindings:
            sources.append(source)
            seen_bindings.add(source.binding_digest)
    return accepted, pending_events, sources


def _decision_value(lines: list[str], label: str) -> str:
    prefix = f"- {label}:"
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip("`")
    return ""


def load_decisions(root: Path, program_id: str) -> list[dict[str, str]]:
    path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    payload = load_yaml(path, default={})
    items = payload.get("items") if isinstance(payload, dict) else None
    items = items if isinstance(items, list) else []
    decisions: list[dict[str, str]] = []
    known_ids = {str(item.get("id") or "") for item in items if isinstance(item, dict)}
    for item in items:
        if not isinstance(item, dict):
            continue
        decision = item.get("payload", {}).get("decision", {})
        decision = decision if isinstance(decision, dict) else {}
        if isinstance(item.get("legacy_import"), dict) and str(item.get("confirmation_status") or "") != "confirmed":
            decisions.append(
                {
                    "title": str(decision.get("text") or item.get("id") or "legacy decision"),
                    "stage": str(decision.get("stage") or ""),
                    "rationale": str(decision.get("rationale") or ""),
                    "alternatives": "",
                    "confirmation": "pending_user_confirmation",
                    "legacy_pending": "true",
                }
            )
            continue
        if str(item.get("confirmation_status") or "") != "confirmed":
            continue
        if not judgement_confirmation_is_current(root, item, path):
            continue
        if not decision:
            continue
        decisions.append(
            {
                "title": str(decision.get("text") or ""),
                "stage": str(decision.get("stage") or ""),
                "rationale": str(decision.get("rationale") or ""),
                "alternatives": ", ".join(str(value) for value in decision.get("alternatives", [])),
                "confirmation": "confirmed",
                "_binding_digest": _canonical_digest(
                    {
                        "confirmation": item.get("confirmation"),
                        "verification": (
                            item.get("payload", {}).get("verification")
                            if isinstance(item.get("payload"), dict)
                            else None
                        ),
                    }
                ),
            }
        )
    legacy_path = root / "kb" / "programs" / program_id / "workflow" / "decision-log.md"
    if legacy_path.is_file():
        text = legacy_path.read_text(encoding="utf-8")
        headings = list(re.finditer(r"(?m)^##\s+(.+?)\s+·\s+(.+?)\s*$", text))
        for index, heading in enumerate(headings):
            block_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            lines = [line.strip() for line in text[heading.end() : block_end].splitlines()]
            decision_id = _decision_value(lines, "Decision ID")
            if decision_id and decision_id in known_ids:
                continue
            decisions.append(
                {
                    "title": heading.group(2).strip(),
                    "stage": _decision_value(lines, "Stage"),
                    "rationale": _decision_value(lines, "Rationale"),
                    "alternatives": _decision_value(lines, "Alternatives"),
                    "confirmation": "pending_user_confirmation",
                    "legacy_pending": "true",
                }
            )
    return decisions


def load_report_inputs(
    root: Path,
    program_id: str,
    *,
    stage: str = "",
    limit: int = 20,
    preference_selection_id: str = "",
    preference_operation: str = "",
) -> ReportInputs:
    loaded_events = normalize_events(load_program_reporting_events(root, program_id), stage=stage, limit=limit)
    events, pending_judgement_events = partition_reporting_events(root, loaded_events)
    events, pending_judgement_events, survey_claim_sources = attach_confirmed_survey_claim_sources(
        root,
        program_id,
        events,
        pending_judgement_events,
    )
    unit_ids = program_unit_ids(root, program_id, loaded_events)
    claim_sources, missing_units = load_confirmed_claim_sources(root, unit_ids)
    inputs = ReportInputs(
        events=events,
        pending_judgement_events=pending_judgement_events,
        claim_sources=[*claim_sources, *survey_claim_sources],
        decisions=load_decisions(root, program_id),
        missing_units=missing_units,
    )
    canonical_inputs = report_preference_context(
        program_id,
        operation=preference_operation,
        stage=stage,
        limit=limit,
        inputs=inputs,
    )
    selected, binding = _resolved_report_preferences(
        root,
        preference_selection_id=preference_selection_id,
        operation=preference_operation,
        canonical_inputs=canonical_inputs,
    )
    if preference_selection_id:
        inputs.reporting_style = _normalize_reporting_style(
            selected.get("profile.personalization.reporting_style")
        )
        inputs.language = _normalize_report_language(
            selected.get("profile.preferences.language_preference")
        )
        inputs.preference_binding = binding
    return inputs


def concise_report_inputs(inputs: ReportInputs) -> ReportInputs:
    if inputs.reporting_style != "concise":
        return inputs
    claim_sources = [
        ClaimSource(
            unit_id=source.unit_id,
            title=source.title,
            kind=source.kind,
            claims=source.claims[:CONCISE_CLAIM_LIMIT],
            issues=source.issues,
            binding_digest=source.binding_digest,
        )
        for source in inputs.claim_sources[:CONCISE_SOURCE_LIMIT]
    ]
    return ReportInputs(
        events=inputs.events[-CONCISE_EVENT_LIMIT:],
        pending_judgement_events=inputs.pending_judgement_events[-CONCISE_EVENT_LIMIT:],
        claim_sources=claim_sources,
        decisions=inputs.decisions[-CONCISE_DECISION_LIMIT:],
        missing_units=inputs.missing_units,
        reporting_style=inputs.reporting_style,
        language=inputs.language,
        preference_binding=inputs.preference_binding,
    )


def _missing(label: str, *, language: str) -> str:
    return f"missing: {label}" if _is_english(language) else f"缺少：{label}"


def _pending_reason(reason: str, *, language: str) -> str:
    if _is_english(language):
        return reason
    if "stale" in reason.casefold() or "changed" in reason.casefold():
        return "当前确认回执或其证据绑定已失效。"
    return "当前缺少有效的确认回执或证据绑定。"


def report_title(report_kind: str, program_id: str, *, language: str) -> str:
    if _is_english(language):
        labels = {
            "weekly": "Weekly Report",
            "ppt-materials": "PPT Materials",
            "writing-materials": "Writing Materials",
            "stage-summary": "Stage Summary",
        }
        return f"{labels.get(report_kind, 'Report')}: {program_id}"
    labels = {
        "weekly": "周报",
        "ppt-materials": "PPT 素材",
        "writing-materials": "写作素材",
        "stage-summary": "阶段总结",
    }
    return f"{labels.get(report_kind, '报告')}：{program_id}"


def render_event_line(event: dict[str, Any], *, language: str = "en-US") -> str:
    if str(event.get("_effective_confirmation_status") or "") == "confirmed":
        binding = event.get("confirmation_binding")
        binding = binding if isinstance(binding, dict) else {}
        subject = binding.get("subject")
        subject = subject if isinstance(subject, dict) else {}
        subject_kind = str(subject.get("kind") or "judgement").replace("_", " ")
        subject_id = str(subject.get("id") or "confirmed subject")
        if _is_english(language):
            return (
                f"- Confirmed judgement · {subject_kind}: {subject_id} "
                "(confirmation: current receipt)"
            )
        return f"- 已确认判断 · {subject_kind}：{subject_id}（确认：当前回执）"
    timestamp = str(event.get("timestamp") or ("unknown time" if _is_english(language) else "时间未知"))
    source_skill = str(event.get("source_skill") or ("unknown source" if _is_english(language) else "来源未知"))
    event_type = str(event.get("event_type") or "update")
    title = str(event.get("title") or ("Untitled event" if _is_english(language) else "未命名事件"))
    summary = str(event.get("summary") or "").strip()
    stage = str(event.get("stage") or "").strip()
    details = (
        [f"type: {event_type}", f"source: {source_skill}"]
        if _is_english(language)
        else [f"类型：{event_type}", f"来源：{source_skill}"]
    )
    if stage:
        details.append(f"stage: {stage}" if _is_english(language) else f"阶段：{stage}")
    suffix = f" — {summary}" if summary else ""
    if _is_english(language):
        return f"- {timestamp} · {title} ({'; '.join(details)}){suffix}"
    return f"- {timestamp} · {title}（{'；'.join(details)}）{suffix}"


def render_decisions(decisions: list[dict[str, str]], *, language: str = "en-US") -> list[str]:
    lines = ["## Decisions" if _is_english(language) else "## 决策", ""]
    if not decisions:
        return [*lines, f"- {_missing('decisions' if _is_english(language) else '决策', language=language)}"]
    for decision in decisions:
        if decision.get("legacy_pending") == "true":
            if _is_english(language):
                lines.append(
                    f"- pending/unverified legacy decision requires two-stage confirmation: {decision['title']}"
                )
            else:
                lines.append(f"- 待确认 / 未核验的历史决策需要完成两阶段确认：{decision['title']}")
            continue
        lines.append(f"### {decision['title']}")
        lines.append("")
        if _is_english(language):
            lines.append(f"- Stage: {decision['stage'] or 'missing: decision stage'}")
            lines.append(f"- Rationale: {decision['rationale'] or 'missing: decision rationale'}")
            lines.append(f"- Alternatives: {decision['alternatives'] or 'missing: decision alternatives'}")
            lines.append(f"- Confirmation: {decision['confirmation'] or 'missing: decision confirmation'}")
        else:
            lines.append(f"- 阶段：{decision['stage'] or '缺少：决策阶段'}")
            lines.append(f"- 理由：{decision['rationale'] or '缺少：决策理由'}")
            lines.append(f"- 备选方案：{decision['alternatives'] or '缺少：决策备选方案'}")
            lines.append(f"- 确认状态：{decision['confirmation'] or '缺少：决策确认状态'}")
        lines.append("")
    return lines[:-1]


def render_claims(
    claim_sources: list[ClaimSource],
    missing_units: list[str],
    *,
    heading: str,
    language: str = "en-US",
) -> list[str]:
    lines = [f"## {heading}", ""]
    claims_found = False
    for source in claim_sources:
        if not source.claims and not source.issues:
            continue
        source_title = source.title
        if source.kind == "survey_judgement":
            source_title = (
                f"Confirmed survey: {source.title}"
                if _is_english(language)
                else f"已确认综述：{source.title}"
            )
        if _is_english(language):
            unit_line = f"- Unit: {source.unit_id} ({source.kind})"
        else:
            unit_line = f"- 单元：{source.unit_id}（{source.kind}）"
        lines.extend([f"### {source_title}", "", unit_line])
        for issue in source.issues:
            if _is_english(language):
                lines.append(f"- missing: structurally valid confirmed claim ({issue})")
            else:
                lines.append("- 缺少：结构合法且已确认的判断（结构或证据核验未通过）")
        for claim in source.claims:
            claims_found = True
            claim_id = str(claim.get("id") or "unnamed claim")
            claim_type = str(claim.get("claim_type") or "unspecified")
            status = str(claim.get("confirmation_status") or "unspecified")
            claim_text = str(claim.get("text") or "").strip()
            if _is_english(language):
                lines.append(f"- Claim {claim_id} [{claim_type}; {status}]: {claim_text}")
            else:
                lines.append(f"- 判断 {claim_id} [{claim_type}; {status}]：{claim_text}")
            evidence_refs = [ref for ref in claim.get("evidence_refs", []) if isinstance(ref, dict)]
            if not evidence_refs:
                if _is_english(language):
                    lines.append(f"  - missing: evidence for claim {claim_id}")
                else:
                    lines.append(f"  - 缺少：判断 {claim_id} 的证据")
            for index, evidence in enumerate(evidence_refs, start=1):
                quote = str(evidence.get("quote") or "").strip()
                locator = str(evidence.get("locator") or "").strip()
                source_unit_id = str(evidence.get("source_unit_id") or source.unit_id).strip()
                summary = str(evidence.get("summary") or "").strip()
                detail = f"source {source_unit_id}" if _is_english(language) else f"来源 {source_unit_id}"
                if locator:
                    detail += f", {locator}" if _is_english(language) else f"，{locator}"
                missing_quote = "missing: verbatim quote" if _is_english(language) else "缺少：逐字证据摘录"
                if _is_english(language):
                    lines.append(f"  - Evidence {index} ({detail}): {quote or missing_quote}")
                else:
                    lines.append(f"  - 证据 {index}（{detail}）：{quote or missing_quote}")
                if summary:
                    if _is_english(language):
                        lines.append(f"    - Context: {summary}")
                    else:
                        lines.append(f"    - 上下文：{summary}")
        lines.append("")
    if missing_units:
        if _is_english(language):
            lines.append(f"- missing: records for linked units {', '.join(missing_units)}")
        else:
            lines.append(f"- 缺少：关联单元的记录 {', '.join(missing_units)}")
    if not claims_found:
        lines.append("- missing: confirmed claims" if _is_english(language) else "- 缺少：已确认判断")
    return lines


def render_events(events: list[dict[str, Any]], *, heading: str, language: str = "en-US") -> list[str]:
    lines = [f"## {heading}", ""]
    if not events:
        return [*lines, "- missing: reporting events" if _is_english(language) else "- 缺少：报告事件"]
    lines.extend(render_event_line(event, language=language) for event in events)
    return lines


def render_pending_judgement_events(events: list[dict[str, Any]], *, language: str = "en-US") -> list[str]:
    if not events:
        return []
    lines = ["## Pending / Unverified judgements" if _is_english(language) else "## 待确认 / 未核验的判断", ""]
    for event in events:
        reason = str(event.get("_epistemic_reason") or "missing: current ConfirmationReceipt")
        summary = str(event.get("summary") or "").strip()
        title = str(event.get("title") or ("Untitled event" if _is_english(language) else "未命名事件")).strip()
        prefix = "PENDING / UNVERIFIED JUDGEMENT" if _is_english(language) else "待确认 / 未核验的判断"
        lines.append(f"- {prefix} — {summary or title}")
        metadata_event = {**event, "summary": ""}
        event_label = "Event" if _is_english(language) else "事件"
        lines.append(f"  - {event_label}: {render_event_line(metadata_event, language=language)[2:]}")
        lines.append(f"  - {_pending_reason(reason, language=language)}")
    return lines


def report_headings(report_kind: str, *, language: str = "en-US") -> tuple[str, str]:
    if not _is_english(language):
        if report_kind == "ppt-materials":
            return "有证据支撑的幻灯片素材", "研究计划事件"
        if report_kind == "writing-materials":
            return "写作判断与证据", "研究计划事件"
        if report_kind == "stage-summary":
            return "已确认判断与证据", "阶段事件"
        return "已确认判断与证据", "报告事件"
    if report_kind == "ppt-materials":
        return "Evidence-backed Slide Inputs", "Program Events"
    if report_kind == "writing-materials":
        return "Writing Claims & Evidence", "Program Events"
    if report_kind == "stage-summary":
        return "Confirmed Claims & Evidence", "Stage Events"
    return "Confirmed Claims & Evidence", "Reporting Events"


def render_report(title: str, inputs: ReportInputs, *, report_kind: str) -> str:
    inputs = concise_report_inputs(inputs)
    language = inputs.language
    claims_heading, events_heading = report_headings(report_kind, language=language)
    sections = [
        [f"# {title}", ""],
        render_decisions(inputs.decisions, language=language),
        render_claims(inputs.claim_sources, inputs.missing_units, heading=claims_heading, language=language),
        render_events(inputs.events, heading=events_heading, language=language),
        render_pending_judgement_events(inputs.pending_judgement_events, language=language),
    ]
    lines: list[str] = []
    for section in sections:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(section)
    return "\n".join(lines).strip() + "\n"


def _event_matches(event: dict[str, Any], terms: set[str]) -> bool:
    if str(event.get("_effective_confirmation_status") or "") == "confirmed":
        binding = event.get("confirmation_binding")
        binding = binding if isinstance(binding, dict) else {}
        subject = binding.get("subject")
        subject = subject if isinstance(subject, dict) else {}
        searchable = " ".join(
            [
                "judgement confirmed",
                str(subject.get("kind") or ""),
                str(subject.get("id") or ""),
            ]
        ).casefold()
        return any(term in searchable for term in terms)
    searchable = " ".join(
        [
            str(event.get("event_type") or ""),
            str(event.get("title") or ""),
            str(event.get("summary") or ""),
            " ".join(_text_items(event.get("tags"))),
        ]
    ).casefold()
    return any(term in searchable for term in terms)


def render_outline_event_inputs(
    events: list[dict[str, Any]],
    *,
    section: str,
    terms: set[str],
    language: str = "en-US",
) -> list[str]:
    matched = [event for event in events if _event_matches(event, terms)]
    lines = [f"### {section} Inputs" if _is_english(language) else f"### {section}素材", ""]
    if not matched:
        if _is_english(language):
            return [*lines, f"- missing: {section.casefold()} events or evidence"]
        return [*lines, f"- 缺少：{section}事件或证据"]
    lines.extend(render_event_line(event, language=language) for event in matched)
    return lines


def render_outline(program_id: str, inputs: ReportInputs) -> str:
    inputs = concise_report_inputs(inputs)
    language = inputs.language
    english = _is_english(language)
    related_work = render_claims(
        inputs.claim_sources,
        inputs.missing_units,
        heading="Related Work: Confirmed Claims & Evidence" if english else "相关工作：已确认判断与证据",
        language=language,
    )
    if not any(source.claims for source in inputs.claim_sources):
        related_work.append("- missing: related-work claims and evidence" if english else "- 缺少：相关工作判断与证据")
    if english:
        title = f"Paper Outline: {program_id}"
        introduction = [
            "## Introduction",
            "",
            "- Fill in: research problem, motivation, gap, contribution thesis, and paper roadmap.",
            "- missing: introduction narrative",
        ]
        method_intro = "- Fill in: method overview, components, interfaces, assumptions, and implementation choices."
        experiment_intro = "- Fill in: research questions, datasets, baselines, metrics, ablations, and reproducibility details."
        result_intro = "- Fill in: confirmed results, comparisons, uncertainty, and negative findings."
        discussion = [
            "## Discussion",
            "",
            "- Fill in: interpretation, limitations, threats to validity, and broader implications.",
            "- missing: discussion narrative",
        ]
        conclusion = [
            "## Conclusion",
            "",
            "- Fill in: concise answer to the research question and evidence-backed takeaways.",
            "- missing: conclusion narrative",
        ]
        section_labels = {"method": "Method", "experiment": "Experiments", "experiment_input": "Experiment", "result": "Results", "result_input": "Result"}
        event_heading = "Program Events"
    else:
        title = f"论文大纲：{program_id}"
        introduction = [
            "## 引言",
            "",
            "- 待填写：研究问题、动机、缺口、贡献主张与全文路线。",
            "- 缺少：引言叙事",
        ]
        method_intro = "- 待填写：方法概览、组成部分、接口、假设与实现选择。"
        experiment_intro = "- 待填写：研究问题、数据集、基线、指标、消融与可复现细节。"
        result_intro = "- 待填写：已确认结果、对比、不确定性与负面发现。"
        discussion = [
            "## 讨论",
            "",
            "- 待填写：结果解释、局限、有效性威胁与更广泛影响。",
            "- 缺少：讨论叙事",
        ]
        conclusion = [
            "## 结论",
            "",
            "- 待填写：对研究问题的简洁回答与有证据支撑的要点。",
            "- 缺少：结论叙事",
        ]
        section_labels = {"method": "方法", "experiment": "实验", "experiment_input": "实验", "result": "结果", "result_input": "结果"}
        event_heading = "研究计划事件"
    sections = [
        [f"# {title}", ""],
        introduction,
        related_work,
        [
            f"## {section_labels['method']}",
            "",
            method_intro,
            *render_outline_event_inputs(
                inputs.events,
                section=section_labels["method"],
                terms={"method", "design", "implementation", "baseline", "architecture"},
                language=language,
            ),
        ],
        [
            f"## {section_labels['experiment']}",
            "",
            experiment_intro,
            *render_outline_event_inputs(
                inputs.events,
                section=section_labels["experiment_input"],
                terms={"experiment", "evaluation", "benchmark", "ablation", "metric"},
                language=language,
            ),
        ],
        [
            f"## {section_labels['result']}",
            "",
            result_intro,
            *render_outline_event_inputs(
                inputs.events,
                section=section_labels["result_input"],
                terms={"result", "finding", "completed", "failure", "comparison"},
                language=language,
            ),
        ],
        discussion,
        conclusion,
        render_decisions(inputs.decisions, language=language),
        render_events(inputs.events, heading=event_heading, language=language),
        render_pending_judgement_events(inputs.pending_judgement_events, language=language),
    ]
    lines: list[str] = []
    for section in sections:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(section)
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_workspace(root)
    reports_root = root / "kb" / "programs" / args.program_id / "reports"
    inputs = load_report_inputs(
        root,
        args.program_id,
        stage=args.stage,
        limit=args.limit,
        preference_selection_id=args.preference_selection_id,
        preference_operation=args.command,
    )
    if args.command == "weekly":
        path = reports_root / "weekly.md"
    elif args.command == "ppt-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-ppt-materials.md"
    elif args.command == "writing-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-writing-materials.md"
    elif args.command == "outline":
        path = reports_root / "paper-outline.md"
    else:
        path = reports_root / "stage-summary.md"
    title = report_title(args.command, args.program_id, language=inputs.language)
    text = render_outline(args.program_id, inputs) if args.command == "outline" else render_report(title, inputs, report_kind=args.command)
    if inputs.preference_binding:
        binding_text = json.dumps(inputs.preference_binding, ensure_ascii=False, sort_keys=True)
        text = f"<!-- effective-preferences: {binding_text} -->\n" + text
    with command_mutation(root, f"report-author:{args.command}", [path]):
        write_text_if_changed(path, text)
    print(path.relative_to(root))
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: generate {args.command} for {args.program_id}",
        target_paths=[path],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

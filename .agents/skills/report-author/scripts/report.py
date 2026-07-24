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
from research.judgements import judgement_confirmation_is_current, load_bound_judgement
from research.preference_selection import resolve_task_preferences, selection_binding
from research.records import trusted_unit_record_path
from research.surveys import survey_staleness


UNIT_ID_FIELDS = {"unit_id", "unit_ids", "related_unit_ids", "active_unit_ids"}
UNIT_PATH_RE = re.compile(r"(?:^|/)kb/units/(?:papers|repos|datasets|blogs|ideas|experiments)/([^/]+)(?:/|$)")
DECISION_HEADING_RE = re.compile(r"^##\s+(.+)$", flags=re.MULTILINE)
CONCISE_STYLE_SIGNALS = ("简洁", "concise", "brief")
DETAILED_STYLE_SIGNALS = ("详细", "detailed", "full")
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
    except (OSError, ValueError):
        return False, f"confirmation_status={recorded_status}; missing: bound record {subject_id}"
    if str(record.get("id") or "") != subject_id or str(record.get("kind") or "") != subject_kind:
        return False, f"confirmation_status={recorded_status}; missing: matching canonical subject"
    if str(record.get("confirmation_status") or "") != "confirmed":
        return False, f"confirmation_status={recorded_status}; missing: current ConfirmationReceipt"
    if not judgement_confirmation_is_current(root, record, artifact_path):
        return False, "confirmation_status=stale; missing: current ConfirmationReceipt"
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
    payload = load_yaml(candidate, default={})
    if not isinstance(payload, dict):
        return {"stale": True, "reasons": ["invalid survey artifact"], "new_unit_ids": []}
    return survey_staleness(payload, root)


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


def load_reporting_style(
    root: Path,
    *,
    preference_selection_id: str = "",
    operation: str = "",
    canonical_inputs: dict[str, object] | None = None,
) -> str:
    if preference_selection_id:
        effective = resolve_task_preferences(
            root,
            selection_id=preference_selection_id,
            skill="report-author",
            operation=operation,
            canonical_inputs=canonical_inputs or {},
        )
        selected = {
            str(item.get("path") or ""): item.get("value")
            for item in effective.get("effective_items", [])
            if isinstance(item, dict)
        }
        return _normalize_reporting_style(selected.get("profile.personalization.reporting_style"))
    # A canonical profile is only a catalog.  Unselected soft style must be
    # neutral, including legacy top-level reporting_style values.
    return "default"


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
            if child_name in UNIT_ID_FIELDS or child_name.endswith("_ids"):
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


def load_confirmed_claim_sources(root: Path, unit_ids: list[str]) -> tuple[list[ClaimSource], list[str]]:
    sources: list[ClaimSource] = []
    missing_units: list[str] = []
    for unit_id in unit_ids:
        try:
            path = trusted_unit_record_path(root, unit_id)
            record = load_yaml(path, default={})
            if not isinstance(record, dict):
                raise ValueError("canonical record is not a mapping")
        except ValueError:
            missing_units.append(unit_id)
            continue
        canonical_claims = read_claims(record.get("payload"))
        receipt = record.get("confirmation") if isinstance(record.get("confirmation"), dict) else {}
        receipt_claim_ids = {
            str(claim_id)
            for claim_id in receipt.get("claim_ids", [])
            if str(claim_id).strip()
        }
        receipt_current = (
            str(record.get("confirmation_status") or "") == "confirmed"
            and judgement_confirmation_is_current(root, record, path)
        )
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
    unit_ids = program_unit_ids(root, program_id, loaded_events)
    claim_sources, missing_units = load_confirmed_claim_sources(root, unit_ids)
    inputs = ReportInputs(
        events=events,
        pending_judgement_events=pending_judgement_events,
        claim_sources=claim_sources,
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
    if preference_selection_id:
        effective = resolve_task_preferences(
            root,
            selection_id=preference_selection_id,
            skill="report-author",
            operation=preference_operation,
            canonical_inputs=canonical_inputs,
        )
        selected = {
            str(item.get("path") or ""): item.get("value")
            for item in effective.get("effective_items", [])
            if isinstance(item, dict)
        }
        inputs.reporting_style = _normalize_reporting_style(
            selected.get("profile.personalization.reporting_style")
        )
        inputs.preference_binding = selection_binding(effective)
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
        preference_binding=inputs.preference_binding,
    )


def render_event_line(event: dict[str, Any]) -> str:
    timestamp = str(event.get("timestamp") or "unknown time")
    source_skill = str(event.get("source_skill") or "unknown source")
    event_type = str(event.get("event_type") or "update")
    title = str(event.get("title") or "Untitled event")
    summary = str(event.get("summary") or "").strip()
    stage = str(event.get("stage") or "").strip()
    details = [f"type: {event_type}", f"source: {source_skill}"]
    if stage:
        details.append(f"stage: {stage}")
    if str(event.get("_effective_confirmation_status") or "") == "confirmed":
        details.extend(["epistemic: judgement", "confirmation: current receipt"])
    suffix = f" — {summary}" if summary else ""
    return f"- {timestamp} · {title} ({'; '.join(details)}){suffix}"


def render_decisions(decisions: list[dict[str, str]]) -> list[str]:
    lines = ["## Decisions", ""]
    if not decisions:
        return [*lines, "- missing: decisions"]
    for decision in decisions:
        if decision.get("legacy_pending") == "true":
            lines.append(
                f"- pending/unverified legacy decision requires two-stage confirmation: {decision['title']}"
            )
            continue
        lines.append(f"### {decision['title']}")
        lines.append("")
        lines.append(f"- Stage: {decision['stage'] or 'missing: decision stage'}")
        lines.append(f"- Rationale: {decision['rationale'] or 'missing: decision rationale'}")
        lines.append(f"- Alternatives: {decision['alternatives'] or 'missing: decision alternatives'}")
        lines.append(f"- Confirmation: {decision['confirmation'] or 'missing: decision confirmation'}")
        lines.append("")
    return lines[:-1]


def render_claims(claim_sources: list[ClaimSource], missing_units: list[str], *, heading: str) -> list[str]:
    lines = [f"## {heading}", ""]
    claims_found = False
    for source in claim_sources:
        if not source.claims and not source.issues:
            continue
        lines.extend([f"### {source.title}", "", f"- Unit: {source.unit_id} ({source.kind})"])
        for issue in source.issues:
            lines.append(f"- missing: structurally valid confirmed claim ({issue})")
        for claim in source.claims:
            claims_found = True
            claim_id = str(claim.get("id") or "unnamed claim")
            claim_type = str(claim.get("claim_type") or "unspecified")
            status = str(claim.get("confirmation_status") or "unspecified")
            lines.append(f"- Claim {claim_id} [{claim_type}; {status}]: {str(claim.get('text') or '').strip()}")
            evidence_refs = [ref for ref in claim.get("evidence_refs", []) if isinstance(ref, dict)]
            if not evidence_refs:
                lines.append(f"  - missing: evidence for claim {claim_id}")
            for index, evidence in enumerate(evidence_refs, start=1):
                quote = str(evidence.get("quote") or "").strip()
                locator = str(evidence.get("locator") or "").strip()
                source_unit_id = str(evidence.get("source_unit_id") or source.unit_id).strip()
                summary = str(evidence.get("summary") or "").strip()
                detail = f"source {source_unit_id}"
                if locator:
                    detail += f", {locator}"
                lines.append(f"  - Evidence {index} ({detail}): {quote or 'missing: verbatim quote'}")
                if summary:
                    lines.append(f"    - Context: {summary}")
        lines.append("")
    if missing_units:
        lines.append(f"- missing: records for linked units {', '.join(missing_units)}")
    if not claims_found:
        lines.append("- missing: confirmed claims")
    return lines


def render_events(events: list[dict[str, Any]], *, heading: str) -> list[str]:
    lines = [f"## {heading}", ""]
    if not events:
        return [*lines, "- missing: reporting events"]
    lines.extend(render_event_line(event) for event in events)
    return lines


def render_pending_judgement_events(events: list[dict[str, Any]]) -> list[str]:
    if not events:
        return []
    lines = ["## Pending / Unverified judgements", ""]
    for event in events:
        reason = str(event.get("_epistemic_reason") or "missing: current ConfirmationReceipt")
        summary = str(event.get("summary") or "").strip()
        title = str(event.get("title") or "Untitled event").strip()
        lines.append(f"- PENDING / UNVERIFIED JUDGEMENT — {summary or title}")
        metadata_event = {**event, "summary": ""}
        lines.append(f"  - Event: {render_event_line(metadata_event)[2:]}")
        lines.append(f"  - {reason}")
    return lines


def report_headings(report_kind: str) -> tuple[str, str]:
    if report_kind == "ppt-materials":
        return "Evidence-backed Slide Inputs", "Program Events"
    if report_kind == "writing-materials":
        return "Writing Claims & Evidence", "Program Events"
    if report_kind == "stage-summary":
        return "Confirmed Claims & Evidence", "Stage Events"
    return "Confirmed Claims & Evidence", "Reporting Events"


def render_report(title: str, inputs: ReportInputs, *, report_kind: str) -> str:
    inputs = concise_report_inputs(inputs)
    claims_heading, events_heading = report_headings(report_kind)
    sections = [
        [f"# {title}", ""],
        render_decisions(inputs.decisions),
        render_claims(inputs.claim_sources, inputs.missing_units, heading=claims_heading),
        render_events(inputs.events, heading=events_heading),
        render_pending_judgement_events(inputs.pending_judgement_events),
    ]
    lines: list[str] = []
    for section in sections:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(section)
    return "\n".join(lines).strip() + "\n"


def _event_matches(event: dict[str, Any], terms: set[str]) -> bool:
    searchable = " ".join(
        [
            str(event.get("event_type") or ""),
            str(event.get("title") or ""),
            str(event.get("summary") or ""),
            " ".join(_text_items(event.get("tags"))),
        ]
    ).casefold()
    return any(term in searchable for term in terms)


def render_outline_event_inputs(events: list[dict[str, Any]], *, section: str, terms: set[str]) -> list[str]:
    matched = [event for event in events if _event_matches(event, terms)]
    lines = [f"### {section} Inputs", ""]
    if not matched:
        return [*lines, f"- missing: {section.casefold()} events or evidence"]
    lines.extend(render_event_line(event) for event in matched)
    return lines


def render_outline(program_id: str, inputs: ReportInputs) -> str:
    inputs = concise_report_inputs(inputs)
    related_work = render_claims(
        inputs.claim_sources,
        inputs.missing_units,
        heading="Related Work: Confirmed Claims & Evidence",
    )
    if not any(source.claims for source in inputs.claim_sources):
        related_work.append("- missing: related-work claims and evidence")
    sections = [
        [f"# Paper Outline: {program_id}", ""],
        [
            "## Introduction",
            "",
            "- Fill in: research problem, motivation, gap, contribution thesis, and paper roadmap.",
            "- missing: introduction narrative",
        ],
        related_work,
        [
            "## Method",
            "",
            "- Fill in: method overview, components, interfaces, assumptions, and implementation choices.",
            *render_outline_event_inputs(
                inputs.events,
                section="Method",
                terms={"method", "design", "implementation", "baseline", "architecture"},
            ),
        ],
        [
            "## Experiments",
            "",
            "- Fill in: research questions, datasets, baselines, metrics, ablations, and reproducibility details.",
            *render_outline_event_inputs(
                inputs.events,
                section="Experiment",
                terms={"experiment", "evaluation", "benchmark", "ablation", "metric"},
            ),
        ],
        [
            "## Results",
            "",
            "- Fill in: confirmed results, comparisons, uncertainty, and negative findings.",
            *render_outline_event_inputs(
                inputs.events,
                section="Result",
                terms={"result", "finding", "completed", "failure", "comparison"},
            ),
        ],
        [
            "## Discussion",
            "",
            "- Fill in: interpretation, limitations, threats to validity, and broader implications.",
            "- missing: discussion narrative",
        ],
        [
            "## Conclusion",
            "",
            "- Fill in: concise answer to the research question and evidence-backed takeaways.",
            "- missing: conclusion narrative",
        ],
        render_decisions(inputs.decisions),
        render_events(inputs.events, heading="Program Events"),
        render_pending_judgement_events(inputs.pending_judgement_events),
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
        title = f"Weekly Report: {args.program_id}"
    elif args.command == "ppt-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-ppt-materials.md"
        title = f"PPT Materials: {args.program_id}"
    elif args.command == "writing-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-writing-materials.md"
        title = f"Writing Materials: {args.program_id}"
    elif args.command == "outline":
        path = reports_root / "paper-outline.md"
        title = ""
    else:
        path = reports_root / "stage-summary.md"
        title = f"Stage Summary: {args.program_id}"
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

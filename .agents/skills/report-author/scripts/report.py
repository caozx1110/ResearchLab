#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from research.core import ensure_workspace, checkpoint_and_report, project_root, user_root
from research.evidence import read_claims, validate_claims
from research.records import locate_record


CONFIRMED_CLAIM_STATUSES = {"confirmed", "auto_confirmed"}
UNIT_ID_FIELDS = {"unit_id", "unit_ids", "related_unit_ids", "active_unit_ids"}
UNIT_PATH_RE = re.compile(r"(?:^|/)kb/units/(?:papers|repos|blogs|ideas|experiments)/([^/]+)(?:/|$)")
DECISION_HEADING_RE = re.compile(r"^##\s+(.+)$", flags=re.MULTILINE)


@dataclass
class ClaimSource:
    unit_id: str
    title: str
    kind: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class ReportInputs:
    events: list[dict[str, Any]] = field(default_factory=list)
    claim_sources: list[ClaimSource] = field(default_factory=list)
    decisions: list[dict[str, str]] = field(default_factory=list)
    missing_units: list[str] = field(default_factory=list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate evidence-backed reports.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("weekly", "ppt-materials", "stage-summary", "writing-materials"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--program-id", required=True)
        cmd.add_argument("--stage", default="")
        cmd.add_argument("--limit", type=int, default=20)
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
            record, _ = locate_record(root, unit_id, fuzzy=False)
        except SystemExit:
            missing_units.append(unit_id)
            continue
        confirmed_claims = [
            claim
            for claim in read_claims(record.get("payload"))
            if str(claim.get("confirmation_status") or "") in CONFIRMED_CLAIM_STATUSES
        ]
        valid_claims: list[dict[str, Any]] = []
        issues: list[str] = []
        for claim in confirmed_claims:
            violations = validate_claims([claim])
            if violations:
                issues.extend(violations)
            else:
                valid_claims.append(claim)
        sources.append(
            ClaimSource(
                unit_id=str(record.get("id") or unit_id),
                title=str(record.get("title") or unit_id),
                kind=str(record.get("kind") or "unit"),
                claims=valid_claims,
                issues=issues,
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
    path = root / "kb" / "programs" / program_id / "workflow" / "decision-log.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    matches = list(DECISION_HEADING_RE.finditer(text))
    decisions: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        lines = [line.strip() for line in text[match.end() : body_end].splitlines() if line.strip()]
        decisions.append(
            {
                "title": match.group(1).strip(),
                "stage": _decision_value(lines, "Stage"),
                "rationale": _decision_value(lines, "Rationale"),
                "alternatives": _decision_value(lines, "Alternatives"),
                "confirmation": _decision_value(lines, "Confirmation"),
            }
        )
    return decisions


def load_report_inputs(root: Path, program_id: str, *, stage: str = "", limit: int = 20) -> ReportInputs:
    events = normalize_events(load_program_reporting_events(root, program_id), stage=stage, limit=limit)
    unit_ids = program_unit_ids(root, program_id, events)
    claim_sources, missing_units = load_confirmed_claim_sources(root, unit_ids)
    return ReportInputs(
        events=events,
        claim_sources=claim_sources,
        decisions=load_decisions(root, program_id),
        missing_units=missing_units,
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
    suffix = f" — {summary}" if summary else ""
    return f"- {timestamp} · {title} ({'; '.join(details)}){suffix}"


def render_decisions(decisions: list[dict[str, str]]) -> list[str]:
    lines = ["## Decisions", ""]
    if not decisions:
        return [*lines, "- missing: decisions"]
    for decision in decisions:
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


def report_headings(report_kind: str) -> tuple[str, str]:
    if report_kind == "ppt-materials":
        return "Evidence-backed Slide Inputs", "Program Events"
    if report_kind == "writing-materials":
        return "Writing Claims & Evidence", "Program Events"
    if report_kind == "stage-summary":
        return "Confirmed Claims & Evidence", "Stage Events"
    return "Confirmed Claims & Evidence", "Reporting Events"


def render_report(title: str, inputs: ReportInputs, *, report_kind: str) -> str:
    claims_heading, events_heading = report_headings(report_kind)
    sections = [
        [f"# {title}", ""],
        render_decisions(inputs.decisions),
        render_claims(inputs.claim_sources, inputs.missing_units, heading=claims_heading),
        render_events(inputs.events, heading=events_heading),
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
    reports_root.mkdir(parents=True, exist_ok=True)
    inputs = load_report_inputs(root, args.program_id, stage=args.stage, limit=args.limit)
    if args.command == "weekly":
        path = reports_root / "weekly.md"
        title = f"Weekly Report: {args.program_id}"
    elif args.command == "ppt-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-ppt-materials.md"
        title = f"PPT Materials: {args.program_id}"
    elif args.command == "writing-materials":
        path = user_root(root) / "report-materials" / f"{args.program_id}-writing-materials.md"
        title = f"Writing Materials: {args.program_id}"
    else:
        path = reports_root / "stage-summary.md"
        title = f"Stage Summary: {args.program_id}"
    write_text_if_changed(path, render_report(title, inputs, report_kind=args.command))
    print(path.relative_to(root))
    checkpoint_and_report(root, trigger="milestone", message=f"milestone: generate {args.command} for {args.program_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

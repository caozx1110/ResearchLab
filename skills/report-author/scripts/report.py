#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

import yaml

from research.bibliography import BibliographyError, bibliography_from_records
from research.common import add_project_root_argument, load_program_reporting_events, load_yaml, print_resolved_project_roots, utc_now_iso, write_text_if_changed, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.core import command_mutation, ensure_workspace, checkpoint_and_report, project_root, user_root
from research.evidence import build_verification_receipt, read_claims, validate_claims
from research.figures import FigureIndexError, load_current_figure_index
from research.judgements import (
    BoundJudgementBatchSnapshot,
    BoundJudgementContainerSnapshot,
    BoundJudgementSnapshot,
    confirmation_binding,
    apply_judgement_rejection,
    judgement_confirmation_matches_bound,
    judgement_confirmation_is_current,
    load_bound_judgement_batch_snapshot,
    load_bound_judgement_container_snapshot,
    load_bound_judgement_snapshot,
    readiness_violations,
    require_judgement_snapshot,
)
from research.paper_drafts import (
    SECTION_IDENTITIES,
    build_draft_manifest,
    build_publication_manifest,
    build_section_fill_scaffold,
    paper_draft_section_lifecycle_violations,
    render_paper_draft_latex,
    render_paper_draft_markdown,
    validate_publication_sections,
    verify_section_fill,
)
from research.paper_draft_runtime import (
    PaperDraftInputs,
    PaperDraftRuntimeError,
    load_current_draft_manifest,
    load_paper_draft_inputs,
    paper_draft_fill_path,
    paper_draft_manifest_path,
    paper_draft_root,
    paper_draft_section_currentness_violations,
    paper_draft_section_path,
)
from research.preference_selection import resolve_task_preferences, selection_binding
from research.report_editorial import (
    EditorialError,
    build_editorial_fill_scaffold,
    build_editorial_manifest,
    editorial_manifest_violations,
    fill_matches_manifest,
    render_ppt_editorial,
    render_weekly_editorial,
    validate_editorial_fill,
)
from research.records import (
    CanonicalRecordSnapshot,
    ProjectFileSnapshot,
    canonical_record_snapshot_for_identity,
    canonical_record_snapshot_for_unit_id,
    iter_canonical_record_snapshots,
    normalize_record_snapshot,
    snapshot_canonical_unit_artifacts,
    snapshot_project_file,
    trusted_claim_source_roots,
)
from research.yaml_io import StrictYamlError, load_yaml_mapping_bytes_strict
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
UNIT_PATH_RE = re.compile(r"(?:^|/)kb/units/(?:papers|repos|datasets|blogs|ideas|experiments|concepts)/([^/]+)(?:/|$)")
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
    "experiment-run-import",
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
    validate_current: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    def is_current(self) -> bool:
        if self.validate_current is None:
            return False
        try:
            return bool(self.validate_current())
        except (OSError, RuntimeError, ValueError):
            return False


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
    formal_validators: tuple[Callable[[], bool], ...] = field(default_factory=tuple, repr=False)
    formal_lane_pending: bool = False

    def formal_inputs_are_current(self) -> bool:
        if self.formal_lane_pending:
            return False
        try:
            return all(bool(validator()) for validator in self.formal_validators)
        except (OSError, RuntimeError, ValueError):
            return False


@dataclass
class BibliographyInputs:
    program_id: str
    selected_unit_ids: tuple[str, ...]
    paper_snapshots: tuple[CanonicalRecordSnapshot, ...]
    entries: list[dict[str, Any]]
    rendered: str
    state_snapshot: ProjectFileSnapshot
    events_snapshot: ProjectFileSnapshot | None

    def is_current(self) -> bool:
        try:
            if not self.state_snapshot.is_current():
                return False
            if self.events_snapshot is None:
                events_relative = (
                    f"kb/programs/{self.program_id}/workflow/reporting-events.yaml"
                )
                if snapshot_project_file(self.state_snapshot.project_root, events_relative) is not None:
                    return False
            elif not self.events_snapshot.is_current():
                return False
            captured = {snapshot.unit_id: snapshot for snapshot in self.paper_snapshots}
            for unit_id in self.selected_unit_ids:
                current = canonical_record_snapshot_for_identity(
                    self.state_snapshot.project_root, "paper", unit_id
                )
                expected = captured.get(unit_id)
                if expected is None:
                    if current is not None:
                        return False
                    continue
                if current is None or not (
                    current.path == expected.path
                    and current.raw_bytes == expected.raw_bytes
                    and current.file_identity == expected.file_identity
                    and current.directory_capabilities == expected.directory_capabilities
                ):
                    return False
            return True
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate evidence-backed reports.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("weekly", "ppt-materials", "stage-summary", "writing-materials", "outline", "bib"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--program-id", required=True)
        cmd.add_argument("--stage", default="")
        cmd.add_argument("--limit", type=int, default=20)
        cmd.add_argument("--preference-selection-id", default="")
    for name in ("weekly-prepare", "ppt-prepare"):
        cmd = subparsers.add_parser(name, help=argparse.SUPPRESS)
        cmd.add_argument("--program-id", required=True)
        cmd.add_argument("--stage", default="")
        cmd.add_argument("--limit", type=int, default=20)
        cmd.add_argument("--preference-selection-id", default="")
    for name in ("weekly-verify", "ppt-verify"):
        cmd = subparsers.add_parser(name, help=argparse.SUPPRESS)
        cmd.add_argument("--program-id", required=True)
    prepare = subparsers.add_parser("draft-prepare")
    prepare.add_argument("--program-id", required=True)
    verify = subparsers.add_parser("draft-verify")
    verify.add_argument("--program-id", required=True)
    verify.add_argument("--section-id", required=True, choices=SECTION_IDENTITIES)
    export = subparsers.add_parser("draft-export")
    export.add_argument("--program-id", required=True)
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


def _event_bound_snapshot(root: Path, event: dict[str, Any]) -> BoundJudgementSnapshot:
    binding = event.get("confirmation_binding")
    binding = binding if isinstance(binding, dict) else {}
    subject = binding.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    return load_bound_judgement_snapshot(
        root,
        {
            "kind": str(subject.get("kind") or "").strip(),
            "id": str(subject.get("id") or "").strip(),
        },
    )


def _event_subject(event: dict[str, Any]) -> dict[str, str]:
    binding = event.get("confirmation_binding")
    binding = binding if isinstance(binding, dict) else {}
    subject = binding.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    return {
        "kind": str(subject.get("kind") or "").strip(),
        "id": str(subject.get("id") or "").strip(),
        "owner": str(subject.get("owner") or "").strip(),
        "path": str(subject.get("path") or "").strip(),
    }


def _confirmed_judgement_event(
    root: Path,
    event: dict[str, Any],
    *,
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> tuple[bool, str]:
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
        bound = bound_snapshot or _event_bound_snapshot(root, event)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return False, f"confirmation_status={recorded_status}; missing: bound record {subject_id}"
    record = bound.record
    artifact_path = bound.path
    if str(record.get("id") or "") != subject_id or str(record.get("kind") or "") != subject_kind:
        return False, f"confirmation_status={recorded_status}; missing: matching canonical subject"
    if str(record.get("confirmation_status") or "") != "confirmed":
        return False, f"confirmation_status={recorded_status}; missing: current ConfirmationReceipt"
    if not judgement_confirmation_is_current(
        root,
        record,
        artifact_path,
        bound_snapshot=bound,
    ):
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
    if not bound.is_current():
        return False, "confirmation_status=stale; missing: exact current judgement binding"
    return True, "confirmation_status=confirmed; current ConfirmationReceipt"


def _survey_event_staleness(
    root: Path,
    event: dict[str, Any],
    *,
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> dict[str, Any] | None:
    event_type = str(event.get("event_type") or "").casefold()
    binding = event.get("confirmation_binding")
    binding = binding if isinstance(binding, dict) else {}
    subject = binding.get("subject")
    subject = subject if isinstance(subject, dict) else {}
    subject_kind = str(subject.get("kind") or "").casefold()
    if "survey" not in event_type and "survey" not in subject_kind:
        return None
    if bound_snapshot is None or str(bound_snapshot.record.get("kind") or "") != "survey_judgement":
        return {"stale": True, "reasons": ["missing survey artifact"], "new_unit_ids": []}
    try:
        freshness = survey_staleness(bound_snapshot.record, root)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError, SystemExit):
        return {"stale": True, "reasons": ["unreadable survey upstream binding"], "new_unit_ids": []}
    if not bound_snapshot.is_current():
        return {"stale": True, "reasons": ["survey artifact changed during validation"], "new_unit_ids": []}
    return freshness


def _accepted_judgement_event_is_current(
    root: Path,
    event: dict[str, Any],
    bound: BoundJudgementSnapshot,
) -> bool:
    freshness = _survey_event_staleness(root, event, bound_snapshot=bound)
    if isinstance(freshness, dict) and freshness.get("stale"):
        return False
    confirmed, _reason = _confirmed_judgement_event(
        root,
        event,
        bound_snapshot=bound,
    )
    return bool(confirmed and bound.is_current())


def _partition_reporting_events_with_snapshots(
    root: Path,
    events: list[dict[str, Any]],
    *,
    snapshot_batch: BoundJudgementBatchSnapshot | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, BoundJudgementSnapshot],
    BoundJudgementBatchSnapshot,
]:
    batch = snapshot_batch or load_bound_judgement_batch_snapshot(
        root,
        [_event_subject(event) for event in events if _event_is_judgement(event)],
    )
    ordinary: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    bound_by_event: dict[int, BoundJudgementSnapshot] = {}
    for event in events:
        normalized = dict(event)
        if not _event_is_judgement(normalized):
            ordinary.append(normalized)
            continue
        event_subject = _event_subject(normalized)
        bound = batch.resolve(
            {"kind": event_subject["kind"], "id": event_subject["id"]}
        )
        freshness = _survey_event_staleness(root, normalized, bound_snapshot=bound)
        if isinstance(freshness, dict) and freshness.get("stale"):
            reasons = freshness.get("reasons")
            reason_count = len(reasons) if isinstance(reasons, list) else 1
            normalized["_epistemic_reason"] = (
                f"confirmation_status=stale; survey upstream binding changed ({reason_count} reason(s))"
            )
            pending.append(normalized)
            continue
        confirmed, reason = _confirmed_judgement_event(
            root,
            normalized,
            bound_snapshot=bound,
        )
        normalized["_epistemic_reason"] = reason
        if confirmed:
            normalized["_effective_confirmation_status"] = "confirmed"
            ordinary.append(normalized)
            if bound is not None:
                bound_by_event[id(normalized)] = bound
        else:
            pending.append(normalized)
    return ordinary, pending, bound_by_event, batch


def partition_reporting_events(
    root: Path,
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordinary, pending, _bound_by_event, _batch = _partition_reporting_events_with_snapshots(root, events)
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


def _strict_snapshot_mapping(snapshot: ProjectFileSnapshot, *, label: str) -> dict[str, Any]:
    try:
        payload = load_yaml_mapping_bytes_strict(snapshot.raw_bytes)
    except (RuntimeError, StrictYamlError) as exc:
        raise BibliographyError(f"{label} is not a strict YAML mapping") from exc
    return payload


def load_bibliography_inputs(root: Path, program_id: str) -> BibliographyInputs:
    """Capture the exact factual program/paper selection used by one .bib export."""
    state_relative = f"kb/programs/{program_id}/state.yaml"
    events_relative = f"kb/programs/{program_id}/workflow/reporting-events.yaml"
    state_snapshot = snapshot_project_file(root, state_relative)
    if state_snapshot is None:
        raise BibliographyError("program state is missing or unsafe")
    state = _strict_snapshot_mapping(state_snapshot, label="program state")
    if str(state.get("program_id") or program_id) != program_id:
        raise BibliographyError("program state identity does not match the requested program")
    events_snapshot = snapshot_project_file(root, events_relative)
    event_document: dict[str, Any] = {}
    if events_snapshot is not None:
        event_document = _strict_snapshot_mapping(events_snapshot, label="reporting events")
        recorded_program = str(event_document.get("program_id") or program_id)
        if recorded_program != program_id:
            raise BibliographyError("reporting events identity does not match the requested program")
    events = event_document.get("items", []) if isinstance(event_document, dict) else []
    if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
        raise BibliographyError("reporting events items must be a list of mappings")
    selected_unit_ids = tuple(sorted(_collect_unit_ids(state) | _collect_unit_ids(events)))
    snapshots: list[CanonicalRecordSnapshot] = []
    records: list[dict[str, Any]] = []
    for unit_id in selected_unit_ids:
        snapshot = canonical_record_snapshot_for_unit_id(root, unit_id)
        if snapshot is None or snapshot.kind != "paper":
            continue
        record = normalize_record_snapshot(snapshot, root)
        if record is None or str(record.get("kind") or "") != "paper":
            raise BibliographyError("selected paper record is not a current canonical snapshot")
        snapshots.append(snapshot)
        records.append(record)
    entries, rendered = bibliography_from_records(records)
    inputs = BibliographyInputs(
        program_id=program_id,
        selected_unit_ids=selected_unit_ids,
        paper_snapshots=tuple(snapshots),
        entries=entries,
        rendered=rendered,
        state_snapshot=state_snapshot,
        events_snapshot=events_snapshot,
    )
    if not inputs.is_current():
        raise BibliographyError("bibliography inputs changed while they were captured")
    return inputs


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


def _confirmed_record_source_is_current(
    root: Path,
    snapshot: CanonicalRecordSnapshot,
    record: dict[str, Any],
    evidence_validators: tuple[Callable[[], bool], ...],
) -> bool:
    try:
        captured_evidence_current = all(
            bool(validator()) for validator in evidence_validators
        )
        evidence_current = judgement_confirmation_is_current(
            root,
            record,
            snapshot.path,
            record_snapshot=snapshot,
        )
        record_current = _record_snapshot_is_current(root, snapshot)
        return bool(captured_evidence_current and evidence_current and record_current)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return False


def _load_exact_record_snapshot(
    root: Path,
    unit_id: str,
    snapshot_index: dict[str, CanonicalRecordSnapshot | None],
) -> tuple[CanonicalRecordSnapshot, dict[str, Any]] | None:
    snapshot = snapshot_index.get(unit_id)
    if snapshot is None:
        return None
    record = normalize_record_snapshot(snapshot, root)
    if record is None or not _record_snapshot_is_current(root, snapshot):
        return None
    return snapshot, record


def load_confirmed_claim_sources(root: Path, unit_ids: list[str]) -> tuple[list[ClaimSource], list[str]]:
    sources: list[ClaimSource] = []
    missing_units: list[str] = []
    snapshot_index: dict[str, CanonicalRecordSnapshot | None] = {}
    for snapshot in iter_canonical_record_snapshots(root):
        if snapshot.unit_id in snapshot_index:
            snapshot_index[snapshot.unit_id] = None
        else:
            snapshot_index[snapshot.unit_id] = snapshot
    for unit_id in dict.fromkeys(unit_ids):
        selected = _load_exact_record_snapshot(root, unit_id, snapshot_index)
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
        try:
            evidence_roots = trusted_claim_source_roots(
                root,
                record,
                verification_root=snapshot.path.parent,
                expected_record_snapshot=snapshot,
            )
        except ValueError:
            evidence_roots = {}
            receipt_current = False
        evidence_validators = tuple(
            source.is_current
            for source in evidence_roots.values()
            if callable(getattr(source, "is_current", None))
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
        source = ClaimSource(
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
            validate_current=lambda snapshot=snapshot, record=record, evidence_validators=evidence_validators: _confirmed_record_source_is_current(
                root,
                snapshot,
                record,
                evidence_validators,
            ),
        )
        if not _record_snapshot_is_current(root, snapshot):
            missing_units.append(unit_id)
            continue
        sources.append(source)
    return sources, missing_units


def load_confirmed_survey_claim_source(
    root: Path,
    program_id: str,
    event: dict[str, Any],
    *,
    bound_snapshot: BoundJudgementSnapshot | None = None,
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
        bound = bound_snapshot or _event_bound_snapshot(root, event)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None, "confirmation_status=stale; missing: bound survey judgement"
    record = bound.record
    artifact_path = bound.path
    confirmed, reason = _confirmed_judgement_event(
        root,
        event,
        bound_snapshot=bound,
    )
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
    if binding != expected_binding:
        return None, "confirmation_status=stale; missing: exact current survey binding"
    source = ClaimSource(
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
        validate_current=lambda: _accepted_judgement_event_is_current(root, event, bound),
    )
    if not bound.is_current():
        return None, "confirmation_status=stale; missing: exact current judgement binding"
    return source, ""


def attach_confirmed_survey_claim_sources(
    root: Path,
    program_id: str,
    events: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    *,
    bound_snapshots: dict[int, BoundJudgementSnapshot] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[ClaimSource]]:
    accepted: list[dict[str, Any]] = []
    pending_events = list(pending)
    sources: list[ClaimSource] = []
    seen_bindings: set[str] = set()
    for event in events:
        if str(event.get("event_type") or "") != "survey-confirmed":
            accepted.append(event)
            continue
        source, reason = load_confirmed_survey_claim_source(
            root,
            program_id,
            event,
            bound_snapshot=(bound_snapshots or {}).get(id(event)),
        )
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


def load_decisions(
    root: Path,
    program_id: str,
    *,
    snapshot_batch: BoundJudgementBatchSnapshot | None = None,
    validators: list[Callable[[], bool]] | None = None,
) -> list[dict[str, str]]:
    clean_program_id = str(program_id or "").strip()
    if (
        not clean_program_id
        or Path(clean_program_id).name != clean_program_id
        or clean_program_id in {".", ".."}
    ):
        return []
    decisions_relative = Path("kb") / "programs" / clean_program_id / "workflow" / "decisions.yaml"
    decisions: list[dict[str, str]] = []
    current_container_decisions: list[dict[str, str]] = []
    current_container_validators: list[Callable[[], bool]] = []
    known_ids: set[str] = set()
    if snapshot_batch is not None:
        target_path = root.resolve() / decisions_relative
        matching_containers = [
            container
            for container in snapshot_batch.side_containers
            if container.path == target_path
        ]
        if len(matching_containers) == 1:
            batch = BoundJudgementContainerSnapshot(
                container=matching_containers[0],
                judgements=tuple(
                    bound
                    for bound in snapshot_batch.judgements
                    if bound.project_yaml_snapshot is not None
                    and bound.path == target_path
                    and str(bound.record.get("kind") or "") == "program_decision"
                ),
                validate_current=snapshot_batch.is_current,
            )
        else:
            batch = None
    else:
        try:
            batch = load_bound_judgement_container_snapshot(
                root,
                decisions_relative,
                owner="research-orchestrator",
                expected_kind="program_decision",
            )
        except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
            batch = None
    if batch is not None:
        raw_items = batch.container.payload.get("items")
        if isinstance(raw_items, list):
            known_ids = {
                str(item.get("id") or "")
                for item in raw_items
                if isinstance(item, dict) and str(item.get("id") or "")
            }
            for item in raw_items:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("legacy_import"), dict)
                    or str(item.get("confirmation_status") or "") == "confirmed"
                ):
                    continue
                decision = item.get("payload", {}).get("decision", {})
                decision = decision if isinstance(decision, dict) else {}
                current_container_decisions.append(
                    {
                        "title": str(decision.get("text") or item.get("id") or "legacy decision"),
                        "stage": str(decision.get("stage") or ""),
                        "rationale": str(decision.get("rationale") or ""),
                        "alternatives": "",
                        "confirmation": "pending_user_confirmation",
                        "legacy_pending": "true",
                    }
                )
    for bound in batch.judgements if batch is not None else ():
        item = bound.record
        decision = item.get("payload", {}).get("decision", {})
        decision = decision if isinstance(decision, dict) else {}
        if isinstance(item.get("legacy_import"), dict) and str(item.get("confirmation_status") or "") != "confirmed":
            continue
        if str(item.get("confirmation_status") or "") != "confirmed":
            continue
        if not judgement_confirmation_matches_bound(root, bound):
            continue
        if not decision:
            continue
        current_container_decisions.append(
            {
                "_ref_id": str(item.get("id") or ""),
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
        current_container_validators.append(
            lambda bound=bound: judgement_confirmation_matches_bound(root, bound)
            and bound.is_current()
        )
    legacy_relative = Path("kb") / "programs" / clean_program_id / "workflow" / "decision-log.md"
    legacy_snapshot = snapshot_project_file(root, legacy_relative)
    legacy_decisions: list[tuple[str, dict[str, str]]] = []
    if legacy_snapshot is not None:
        try:
            text = legacy_snapshot.raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        headings = list(re.finditer(r"(?m)^##\s+(.+?)\s+·\s+(.+?)\s*$", text))
        for index, heading in enumerate(headings):
            block_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            lines = [line.strip() for line in text[heading.end() : block_end].splitlines()]
            decision_id = _decision_value(lines, "Decision ID")
            legacy_decisions.append(
                (
                    decision_id,
                    {
                        "title": heading.group(2).strip(),
                        "stage": _decision_value(lines, "Stage"),
                        "rationale": _decision_value(lines, "Rationale"),
                        "alternatives": _decision_value(lines, "Alternatives"),
                        "confirmation": "pending_user_confirmation",
                        "legacy_pending": "true",
                    },
                )
            )
    legacy_current = legacy_snapshot is not None and legacy_snapshot.is_current()
    container_current = batch is not None and batch.is_current()
    if container_current:
        decisions.extend(current_container_decisions)
        if current_container_decisions and validators is not None and batch is not None:
            validators.append(batch.is_current)
            validators.extend(current_container_validators)
    if legacy_current:
        effective_known_ids = known_ids if container_current else set()
        accepted_legacy = [
            item
            for decision_id, item in legacy_decisions
            if not decision_id or decision_id not in effective_known_ids
        ]
        decisions.extend(accepted_legacy)
        if accepted_legacy and validators is not None and legacy_snapshot is not None:
            validators.append(legacy_snapshot.is_current)
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
    judgement_batch = load_bound_judgement_batch_snapshot(
        root,
        [_event_subject(event) for event in loaded_events if _event_is_judgement(event)],
    )
    events, pending_judgement_events, bound_event_snapshots, _batch = _partition_reporting_events_with_snapshots(
        root,
        loaded_events,
        snapshot_batch=judgement_batch,
    )
    events, pending_judgement_events, survey_claim_sources = attach_confirmed_survey_claim_sources(
        root,
        program_id,
        events,
        pending_judgement_events,
        bound_snapshots=bound_event_snapshots,
    )
    unit_ids = program_unit_ids(root, program_id, loaded_events)
    claim_sources, missing_units = load_confirmed_claim_sources(root, unit_ids)
    formal_validators: list[Callable[[], bool]] = [
        source.is_current
        for source in [*claim_sources, *survey_claim_sources]
        # Issues-only sources are projected in the pending lane.  They do not
        # publish formal claims and therefore must not gate the formal lane.
        if source.claims
    ]
    for event in events:
        if not _event_is_judgement(event):
            continue
        bound = bound_event_snapshots.get(id(event))
        if bound is None:
            formal_validators.append(lambda: False)
            continue
        formal_validators.append(
            lambda event=event, bound=bound: _accepted_judgement_event_is_current(
                root,
                event,
                bound,
            )
        )
    if any(_event_is_judgement(event) for event in events):
        formal_validators.append(judgement_batch.is_current)
    decisions = load_decisions(
        root,
        program_id,
        snapshot_batch=judgement_batch,
        validators=formal_validators,
    )
    inputs = ReportInputs(
        events=events,
        pending_judgement_events=pending_judgement_events,
        claim_sources=[*claim_sources, *survey_claim_sources],
        decisions=decisions,
        missing_units=missing_units,
        formal_validators=tuple(formal_validators),
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
    if not inputs.formal_inputs_are_current():
        _mark_formal_lane_pending(inputs)
    return inputs


def _mark_formal_lane_pending(inputs: ReportInputs) -> ReportInputs:
    inputs.events = [event for event in inputs.events if not _event_is_judgement(event)]
    inputs.pending_judgement_events = []
    inputs.claim_sources = []
    inputs.decisions = []
    inputs.missing_units = []
    inputs.formal_lane_pending = True
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
            validate_current=source.validate_current,
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
        formal_validators=inputs.formal_validators,
        formal_lane_pending=inputs.formal_lane_pending,
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


def _render_aggregate_pending_document(
    title: str,
    inputs: ReportInputs,
    *,
    report_kind: str,
) -> str:
    language = inputs.language
    _claims_heading, events_heading = report_headings(report_kind, language=language)
    pending_heading = (
        "## Pending / Unverified judgements"
        if _is_english(language)
        else "## 待确认 / 未核验的判断"
    )
    pending_line = (
        "- Formal judgement inputs changed during report generation; refresh them before publishing."
        if _is_english(language)
        else "- 报告生成期间正式判断来源已变化；刷新后才能发布。"
    )
    factual_events = [event for event in inputs.events if not _event_is_judgement(event)]
    sections = [
        [f"# {title}", ""],
        [pending_heading, "", pending_line],
        render_events(factual_events, heading=events_heading, language=language),
    ]
    lines: list[str] = []
    for section in sections:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(section)
    return "\n".join(lines).strip() + "\n"


def _render_report_document(title: str, inputs: ReportInputs, *, report_kind: str) -> str:
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


def render_report(title: str, inputs: ReportInputs, *, report_kind: str) -> str:
    if not inputs.formal_inputs_are_current():
        return _render_aggregate_pending_document(title, inputs, report_kind=report_kind)
    rendered = _render_report_document(title, inputs, report_kind=report_kind)
    if not inputs.formal_inputs_are_current():
        return _render_aggregate_pending_document(title, inputs, report_kind=report_kind)
    return rendered


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


def _render_outline_document(program_id: str, inputs: ReportInputs) -> str:
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


def render_outline(program_id: str, inputs: ReportInputs) -> str:
    title = (
        f"Paper Outline: {program_id}"
        if _is_english(inputs.language)
        else f"论文大纲：{program_id}"
    )
    if not inputs.formal_inputs_are_current():
        return _render_aggregate_pending_document(title, inputs, report_kind="outline")
    rendered = _render_outline_document(program_id, inputs)
    if not inputs.formal_inputs_are_current():
        return _render_aggregate_pending_document(title, inputs, report_kind="outline")
    return rendered


def _strict_project_mapping(
    root: Path,
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], ProjectFileSnapshot]:
    try:
        relative = path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError as exc:
        raise PaperDraftRuntimeError(f"{label} escaped the workspace") from exc
    snapshot = snapshot_project_file(root, relative)
    if snapshot is None:
        raise PaperDraftRuntimeError(f"{label} is missing or unsafe")
    try:
        payload = load_yaml_mapping_bytes_strict(snapshot.raw_bytes)
    except (RuntimeError, StrictYamlError) as exc:
        raise PaperDraftRuntimeError(f"{label} is not a strict YAML mapping") from exc
    return payload, snapshot


def prepare_paper_draft(root: Path, program_id: str) -> int:
    inputs = load_paper_draft_inputs(root, program_id)
    manifest_path = paper_draft_manifest_path(root, program_id)
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest, manifest_snapshot, inputs = load_current_draft_manifest(
            root, program_id, inputs
        )
        manifest_target: list[Path] = []
    else:
        manifest = build_draft_manifest(
            program_id=program_id,
            outline_bytes=inputs.outline_snapshot.raw_bytes,
            claim_catalog=inputs.claim_catalog,
            bibliography_catalog=inputs.bibliography_catalog,
            figure_catalog=inputs.figure_catalog,
            as_of=utc_now_iso(),
        )
        manifest_snapshot = None
        manifest_target = [manifest_path]
    fill_paths = [
        paper_draft_fill_path(root, program_id, section_id)
        for section_id in SECTION_IDENTITIES
    ]
    unsafe_fills: list[Path] = []
    for fill_path in fill_paths:
        if not (fill_path.exists() or fill_path.is_symlink()):
            continue
        relative = fill_path.absolute().relative_to(root.absolute()).as_posix()
        if snapshot_project_file(root, relative) is None:
            unsafe_fills.append(fill_path)
    if unsafe_fills:
        names = "、".join(path.name for path in unsafe_fills)
        raise PaperDraftRuntimeError(f"分节待填路径不安全或不是普通文件：{names}")
    missing_fills = [fill_path for fill_path in fill_paths if not fill_path.exists()]
    targets = [*manifest_target, *missing_fills]
    if not targets:
        print("七个分节的写作待填结构已是当前版本。")
        return 0

    def require_current() -> None:
        if not inputs.is_current() or (
            manifest_snapshot is not None and not manifest_snapshot.is_current()
        ):
            raise RuntimeError("paper draft inputs changed during preparation")

    with command_mutation(
        root,
        "report-author:draft-prepare",
        targets,
        commit_guard=require_current,
    ):
        require_current()
        if manifest_target:
            write_yaml_if_changed(manifest_path, manifest)
        for fill_path in missing_fills:
            section_id = fill_path.name.removesuffix("-fill.yaml")
            write_yaml_if_changed(
                fill_path,
                build_section_fill_scaffold(manifest, section_id),
            )
        require_current()
        load_current_draft_manifest(root, program_id, inputs)
    print(f"已准备 {len(missing_fills)} 个分节待填结构；正文仍需由 Agent 依据已确认判断填写。")
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: prepare paper draft for {program_id}",
        target_paths=targets,
    )
    return 0


def verify_paper_draft_section(root: Path, program_id: str, section_id: str) -> int:
    inputs = load_paper_draft_inputs(root, program_id)
    manifest, manifest_snapshot, inputs = load_current_draft_manifest(
        root, program_id, inputs
    )
    fill_path = paper_draft_fill_path(root, program_id, section_id)
    fill, fill_snapshot = _strict_project_mapping(
        root, fill_path, label="paper draft section fill"
    )
    violations, record = verify_section_fill(
        fill,
        manifest,
        resolve_support=inputs.claim_catalog.get,
        resolve_citation=inputs.bibliography_catalog.get,
        resolve_figure=inputs.figure_catalog.get,
        verified_at=utc_now_iso(),
    )
    if violations or record is None:
        raise PaperDraftRuntimeError("分节草稿未通过核验：" + "；".join(violations))
    try:
        build_verification_receipt(
            record,
            paper_draft_root(root, program_id),
            source_roots=inputs.source_roots,
        )
    except SystemExit as exc:
        raise PaperDraftRuntimeError(
            f"分节草稿的逐字证据字节无法核验：{exc}"
        ) from exc
    record["status"] = "ready_for_review"
    record["updated_at"] = utc_now_iso()
    section_path = paper_draft_section_path(root, program_id, section_id)
    if section_path.exists() or section_path.is_symlink():
        current, _current_snapshot = _strict_project_mapping(
            root, section_path, label="paper draft section"
        )
        if str(current.get("confirmation_status") or "") == "confirmed":
            raise PaperDraftRuntimeError("该分节已确认；未明确要求重填时保留原内容。")

    def require_current() -> None:
        if (
            not inputs.is_current()
            or not manifest_snapshot.is_current()
            or not fill_snapshot.is_current()
        ):
            raise RuntimeError("paper draft inputs changed during section verification")

    with command_mutation(
        root,
        "report-author:draft-verify",
        [section_path],
        commit_guard=require_current,
    ):
        require_current()
        write_yaml_if_changed(section_path, record)
        require_current()
        currentness = paper_draft_section_currentness_violations(
            root, record, section_path
        )
        if currentness:
            raise RuntimeError("paper draft section became stale during verification")
    print("分节草稿已通过证据与引用绑定校验，现等待你确认。")
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: verify paper draft section {program_id}:{section_id}",
        target_paths=[section_path],
    )
    return 0


def _paper_draft_review_context(
    root: Path,
    item: Mapping[str, Any],
    decision: str,
) -> tuple[dict[str, Any], Path, PaperDraftInputs]:
    route_key = "confirm_route" if decision == "confirm" else "reject_route"
    route = item.get(route_key) if isinstance(item, Mapping) else None
    route = route if isinstance(route, Mapping) else {}
    expected_action = "confirm-section" if decision == "confirm" else "reject-section"
    if route.get("owner") != "report-author" or route.get("action") != expected_action:
        raise ValueError("paper draft review route is invalid")
    program_id = str(route.get("program_id") or "")
    section_id = str(route.get("section_id") or "")
    subject_id = str(route.get("subject_id") or "")
    if subject_id != f"paper-draft-section:{program_id}:{section_id}":
        raise ValueError("paper draft review identity is invalid")
    bound = load_bound_judgement_snapshot(
        root, {"kind": "paper_draft_section", "id": subject_id}
    )
    record = bound.record
    path = bound.path
    if readiness_violations(
        root,
        record,
        path,
        bound_snapshot=bound,
    ):
        raise ValueError("paper draft section is no longer ready for review")
    snapshot = item.get("snapshot_binding")
    if not isinstance(snapshot, Mapping):
        raise ValueError("paper draft review snapshot is missing")
    require_judgement_snapshot(
        record,
        expected_snapshot=dict(snapshot),
        owner="report-author",
        path=path.relative_to(root.absolute()).as_posix(),
        root=root,
    )
    inputs = load_paper_draft_inputs(root, program_id)
    return record, path, inputs


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
    """Pure-read preflight for section confirmation in the public coordinator."""
    record, path, inputs = _paper_draft_review_context(root, item, decision)
    candidate = copy.deepcopy(record)
    if decision == "confirm":
        apply_confirmation(
            candidate,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="report-author confirm-section",
            project_root=root,
            verification_root=path.parent,
            trusted_source_roots=inputs.source_roots,
        )
    elif decision == "reject":
        apply_judgement_rejection(candidate, reason=rejection_reason)
    else:
        raise ValueError("paper draft review decision is invalid")
    return {
        "owner": "report-author",
        "decision": decision,
        "program_id": str(record.get("program_id") or ""),
        "section_id": str(record.get("section_id") or ""),
        "target_paths": [path],
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
    """Apply one section decision inside the coordinator's root transaction."""
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
    record, path, inputs = _paper_draft_review_context(root, item, decision)
    if decision == "confirm":
        apply_confirmation(
            record,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="report-author confirm-section",
            project_root=root,
            verification_root=path.parent,
            trusted_source_roots=inputs.source_roots,
        )
        record["status"] = "confirmed"
    else:
        apply_judgement_rejection(record, reason=rejection_reason)
        record["status"] = "rejected"
    record["updated_at"] = utc_now_iso()
    write_yaml_if_changed(path, record)
    if paper_draft_section_currentness_violations(root, record, path):
        raise ValueError("paper draft section became stale while applying review")
    if decision == "confirm" and not judgement_confirmation_is_current(root, record, path):
        raise ValueError("paper draft section confirmation receipt is not current")
    return list(plan["target_paths"])


def _load_publication_sections(
    root: Path,
    program_id: str,
    inputs: PaperDraftInputs,
    manifest: Mapping[str, Any],
    manifest_snapshot: ProjectFileSnapshot,
) -> tuple[
    list[dict[str, Any]],
    Callable[[Mapping[str, Any]], bool],
    Callable[[Mapping[str, Any]], bool],
]:
    records: list[dict[str, Any]] = []
    snapshots: dict[str, ProjectFileSnapshot] = {}
    paths: dict[str, Path] = {}
    for section_id in SECTION_IDENTITIES:
        path = paper_draft_section_path(root, program_id, section_id)
        record, snapshot = _strict_project_mapping(
            root, path, label=f"paper draft section {section_id}"
        )
        records.append(record)
        snapshots[str(record.get("id") or "")] = snapshot
        paths[str(record.get("id") or "")] = path

    def section_is_current(record: Mapping[str, Any]) -> bool:
        record_id = str(record.get("id") or "")
        snapshot = snapshots.get(record_id)
        if snapshot is None or not snapshot.is_current():
            return False
        violations = paper_draft_section_lifecycle_violations(
            record,
            manifest,
            resolve_support=inputs.claim_catalog.get,
            resolve_citation=inputs.bibliography_catalog.get,
            resolve_figure=inputs.figure_catalog.get,
            manifest_is_current=lambda _manifest: bool(
                manifest_snapshot.is_current() and inputs.is_current()
            ),
        )
        return not violations and manifest_snapshot.is_current() and inputs.is_current()

    def confirmation_is_current(record: Mapping[str, Any]) -> bool:
        path = paths.get(str(record.get("id") or ""))
        return bool(
            path is not None
            and judgement_confirmation_is_current(root, dict(record), path)
        )

    return records, section_is_current, confirmation_is_current


def export_paper_draft(root: Path, program_id: str) -> int:
    inputs = load_paper_draft_inputs(root, program_id)
    manifest, manifest_snapshot, inputs = load_current_draft_manifest(
        root, program_id, inputs
    )
    records, section_is_current, confirmation_is_current = _load_publication_sections(
        root, program_id, inputs, manifest, manifest_snapshot
    )

    def publication_is_current() -> bool:
        return bool(
            inputs.is_current()
            and manifest_snapshot.is_current()
            and not validate_publication_sections(
                manifest,
                records,
                section_is_current=section_is_current,
                confirmation_is_current=confirmation_is_current,
            )
        )

    if not publication_is_current():
        raise PaperDraftRuntimeError("发布需要七节全部唯一、当前且已确认。")
    output_root = root / "kb" / "output" / program_id
    markdown_path = output_root / "paper-draft.md"
    latex_path = output_root / "paper-draft.tex"
    bibliography_path = output_root / "references.bib"
    publication_path = output_root / "publication-manifest.yaml"
    targets = [markdown_path, latex_path, bibliography_path, publication_path]

    def require_publication_current() -> None:
        if not publication_is_current():
            raise RuntimeError("paper draft inputs changed during publication")

    with command_mutation(
        root,
        "report-author:draft-export",
        targets,
        commit_guard=require_publication_current,
    ):
        if not publication_is_current():
            raise RuntimeError("paper draft inputs changed before rendering")
        markdown = render_paper_draft_markdown(
            manifest,
            records,
            title=program_id,
            section_is_current=section_is_current,
            confirmation_is_current=confirmation_is_current,
        )
        latex = render_paper_draft_latex(
            manifest,
            records,
            title=program_id,
            section_is_current=section_is_current,
            confirmation_is_current=confirmation_is_current,
        )
        bibliography = inputs.bibliography_text
        if not publication_is_current():
            raise RuntimeError("paper draft inputs changed after rendering")
        publication = build_publication_manifest(
            manifest,
            records,
            markdown_bytes=markdown.encode("utf-8"),
            latex_bytes=latex.encode("utf-8"),
            bibliography_bytes=bibliography.encode("utf-8"),
            published_at=utc_now_iso(),
            section_is_current=section_is_current,
            confirmation_is_current=confirmation_is_current,
        )
        write_text_if_changed(markdown_path, markdown)
        write_text_if_changed(latex_path, latex)
        write_text_if_changed(bibliography_path, bibliography)
        write_yaml_if_changed(publication_path, publication)
        if not publication_is_current():
            raise RuntimeError("paper draft inputs changed during publication")
    print("七节草稿已原子发布为 Markdown、LaTeX、引用库和发布回执。")
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: export paper draft for {program_id}",
        target_paths=targets,
    )
    return 0


def _safe_editorial_program_id(program_id: str) -> str:
    clean = str(program_id or "").strip()
    if not clean or Path(clean).name != clean or clean in {".", ".."}:
        raise EditorialError("program id must be a safe single path component")
    return clean


def _editorial_root(root: Path, program_id: str, output_kind: str) -> Path:
    clean = _safe_editorial_program_id(program_id)
    if output_kind not in {"weekly", "ppt-materials"}:
        raise EditorialError("unsupported editorial output kind")
    return root / "kb" / "programs" / clean / "reports" / "editorial" / output_kind


def _editorial_paths(root: Path, program_id: str, output_kind: str) -> tuple[Path, Path, Path]:
    control_root = _editorial_root(root, program_id, output_kind)
    manifest_path = control_root / "manifest.yaml"
    fill_path = control_root / "fill.yaml"
    output_path = (
        root / "kb" / "programs" / _safe_editorial_program_id(program_id) / "reports" / "weekly.md"
        if output_kind == "weekly"
        else user_root(root) / "report-materials" / f"{program_id}-ppt-materials.md"
    )
    return manifest_path, fill_path, output_path


def _same_project_snapshot(left: ProjectFileSnapshot | None, right: ProjectFileSnapshot | None) -> bool:
    if left is None or right is None:
        return left is right
    return bool(
        left.relative_path == right.relative_path
        and left.raw_bytes == right.raw_bytes
        and left.file_identity == right.file_identity
        and left.directory_capabilities == right.directory_capabilities
    )


def _editorial_snapshot_mapping(snapshot: ProjectFileSnapshot | None, *, label: str) -> dict[str, Any]:
    if snapshot is None:
        raise EditorialError(f"{label} is missing or unsafe")
    try:
        return load_yaml_mapping_bytes_strict(snapshot.raw_bytes)
    except (RuntimeError, StrictYamlError) as exc:
        raise EditorialError(f"{label} must be a strict YAML mapping") from exc


def _event_support_catalog(inputs: ReportInputs) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    catalog: dict[str, dict[str, Any]] = {}
    missing_identity: list[dict[str, Any]] = []
    for event in inputs.events:
        if _event_is_judgement(event):
            continue
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            missing_identity.append(event)
            continue
        ref = f"event:{event_id}"
        if ref in catalog:
            raise EditorialError(f"duplicate factual event ref: {ref}")
        catalog[ref] = {
            "ref": ref,
            "kind": "event",
            "title": str(event.get("title") or event.get("event_type") or event_id),
            "text": str(event.get("summary") or event.get("event_type") or ""),
            "epistemic_label": "fact",
            "event_type": str(event.get("event_type") or ""),
            "binding_digest": _canonical_digest(event),
        }
    return catalog, missing_identity


def _editorial_support_catalog(inputs: ReportInputs) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    catalog: dict[str, dict[str, Any]] = {}
    for source in inputs.claim_sources:
        for claim in source.claims:
            claim_id = str(claim.get("id") or "").strip()
            if not claim_id:
                raise EditorialError("confirmed report claim is missing a stable id")
            ref = f"claim:{source.unit_id}:{claim_id}"
            if ref in catalog:
                raise EditorialError(f"duplicate confirmed claim ref: {ref}")
            catalog[ref] = {
                "ref": ref,
                "kind": "claim",
                "title": source.title,
                "source_title": source.title,
                "source_kind": source.kind,
                "source_unit_id": source.unit_id,
                "text": str(claim.get("text") or ""),
                "epistemic_label": str(claim.get("claim_type") or "synthesis"),
                "evidence_refs": copy.deepcopy(list(claim.get("evidence_refs") or [])),
                "binding_digest": _canonical_digest(
                    {"source_binding": source.binding_digest, "claim": claim}
                ),
            }
    event_catalog, missing_identity = _event_support_catalog(inputs)
    for ref, entry in event_catalog.items():
        if ref in catalog:
            raise EditorialError(f"duplicate support ref: {ref}")
        catalog[ref] = entry
    for decision in inputs.decisions:
        if str(decision.get("confirmation") or "") != "confirmed":
            continue
        decision_id = str(decision.get("_ref_id") or "").strip()
        if not decision_id:
            raise EditorialError("confirmed program decision is missing a stable id")
        ref = f"decision:{decision_id}"
        if ref in catalog:
            raise EditorialError(f"duplicate confirmed decision ref: {ref}")
        catalog[ref] = {
            "ref": ref,
            "kind": "decision",
            "title": str(decision.get("title") or decision_id),
            "text": str(decision.get("title") or ""),
            "rationale": str(decision.get("rationale") or ""),
            "epistemic_label": "synthesis",
            "binding_digest": str(decision.get("_binding_digest") or ""),
        }
    return catalog, missing_identity


def _editorial_risk_catalog(
    inputs: ReportInputs,
    missing_factual_identity: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for source in inputs.claim_sources:
        for index, issue in enumerate(source.issues, start=1):
            ref = f"risk:source:{source.unit_id}:{index}"
            catalog[ref] = {
                "ref": ref,
                "kind": "risk_hint",
                "title": source.title,
                "text": str(issue),
                "epistemic_label": "risk",
                "formal_support": False,
                "binding_digest": _canonical_digest(
                    {"source_binding": source.binding_digest, "issue": issue, "index": index}
                ),
            }
    for index, event in enumerate(inputs.pending_judgement_events, start=1):
        event_id = str(event.get("id") or "").strip()
        identity = event_id or _canonical_digest(
            {"index": index, "event_type": event.get("event_type"), "reason": event.get("_epistemic_reason")}
        )[:16]
        ref = f"risk:event:{identity}"
        if ref in catalog:
            raise EditorialError(f"duplicate pending risk ref: {ref}")
        catalog[ref] = {
            "ref": ref,
            "kind": "risk_hint",
            "title": str(event.get("event_type") or "pending judgement"),
            "text": str(event.get("_epistemic_reason") or "confirmation_status=pending_user_confirmation"),
            "epistemic_label": "risk",
            "formal_support": False,
            "binding_digest": _canonical_digest(
                {"id": event_id, "reason": event.get("_epistemic_reason"), "event_type": event.get("event_type")}
            ),
        }
    for unit_id in sorted(set(inputs.missing_units)):
        ref = f"risk:missing:{unit_id}"
        catalog[ref] = {
            "ref": ref,
            "kind": "risk_hint",
            "title": "missing unit",
            "text": f"canonical unit is missing or not current: {unit_id}",
            "epistemic_label": "risk",
            "formal_support": False,
            "binding_digest": _canonical_digest({"missing_unit_id": unit_id}),
        }
    if inputs.formal_lane_pending:
        catalog["risk:formal-lane"] = {
            "ref": "risk:formal-lane",
            "kind": "risk_hint",
            "title": "formal lane pending",
            "text": "formal report inputs are stale or unavailable; no formal claim was admitted",
            "epistemic_label": "risk",
            "formal_support": False,
            "binding_digest": _canonical_digest({"formal_lane_pending": True}),
        }
    for index, event in enumerate(missing_factual_identity, start=1):
        ref = f"risk:unidentified-event:{_canonical_digest({'index': index, 'event': event})[:16]}"
        catalog[ref] = {
            "ref": ref,
            "kind": "risk_hint",
            "title": "unidentified factual event",
            "text": "a factual event was excluded because it has no stable id",
            "epistemic_label": "risk",
            "formal_support": False,
            "binding_digest": _canonical_digest(event),
        }
    return catalog


def _figure_entry_binding(index: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    source = index.get("source") if isinstance(index.get("source"), Mapping) else {}
    return {
        "paper_id": str(index.get("paper_id") or ""),
        "index_digest": str(index.get("index_digest") or ""),
        "source_digest": str(source.get("sha256") or ""),
        "caption_digest": str(entry.get("caption_digest") or ""),
        "asset_digests": [
            str(asset.get("sha256") or "")
            for asset in list(entry.get("assets") or [])
            if isinstance(asset, Mapping)
        ],
    }


def _load_editorial_figures(
    root: Path,
    unit_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], tuple[Callable[[], bool], ...]]:
    catalog: dict[str, dict[str, Any]] = {}
    validators: list[Callable[[], bool]] = []
    for unit_id in unit_ids:
        snapshot = canonical_record_snapshot_for_unit_id(root, unit_id)
        if snapshot is None or snapshot.kind != "paper":
            continue
        record = normalize_record_snapshot(snapshot, root)
        if record is None:
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
        projection = payload.get("figures") if isinstance(payload.get("figures"), Mapping) else {}
        expected_digest = str(projection.get("index_digest") or "")
        if (
            projection.get("schema") != "figure-index/v1"
            or projection.get("index_artifact") != "figures.yaml"
            or not expected_digest
        ):
            continue
        paper_root = snapshot.path.parent
        index_path = paper_root / "figures.yaml"
        try:
            index = load_current_figure_index(
                index_path,
                unit_root=paper_root,
                project_root=root,
                expected_index_digest=expected_digest,
            )
        except FigureIndexError:
            continue
        frozen: dict[str, dict[str, Any]] = {}
        for entry in index.get("entries", []):
            if not isinstance(entry, Mapping):
                continue
            ref_key = str(entry.get("ref_key") or "")
            ref = f"figure:{ref_key}"
            if not ref_key or ref in catalog:
                raise EditorialError(f"duplicate or empty current figure ref: {ref}")
            binding = _figure_entry_binding(index, entry)
            frozen[ref_key] = binding
            catalog[ref] = {
                "ref": ref,
                "kind": "figure",
                "ref_key": ref_key,
                "paper_id": unit_id,
                "title": str(record.get("title") or unit_id),
                "caption": str(entry.get("caption") or ""),
                "figure_kind": str(entry.get("kind") or "figure"),
                "number": str(entry.get("number") or ""),
                "page": entry.get("page"),
                "binding_digest": _canonical_digest(binding),
            }

        def current(
            snapshot: CanonicalRecordSnapshot = snapshot,
            index_path: Path = index_path,
            paper_root: Path = paper_root,
            expected_digest: str = expected_digest,
            frozen: dict[str, dict[str, Any]] = frozen,
        ) -> bool:
            try:
                if not _record_snapshot_is_current(root, snapshot):
                    return False
                loaded = load_current_figure_index(
                    index_path,
                    unit_root=paper_root,
                    project_root=root,
                    expected_index_digest=expected_digest,
                )
                current_bindings = {
                    str(entry.get("ref_key") or ""): _figure_entry_binding(loaded, entry)
                    for entry in loaded.get("entries", [])
                    if isinstance(entry, Mapping)
                }
                return current_bindings == frozen
            except (FigureIndexError, OSError, RuntimeError, ValueError):
                return False

        validators.append(current)
    return catalog, tuple(validators)


def _load_editorial_runtime(
    root: Path,
    program_id: str,
    output_kind: str,
    *,
    stage: str,
    limit: int,
    preference_selection_id: str,
    as_of: str,
) -> tuple[dict[str, Any], ReportInputs]:
    clean_program = _safe_editorial_program_id(program_id)
    state_relative = f"kb/programs/{clean_program}/state.yaml"
    events_relative = f"kb/programs/{clean_program}/workflow/reporting-events.yaml"
    state_snapshot = snapshot_project_file(root, state_relative)
    state = _editorial_snapshot_mapping(state_snapshot, label="program state")
    if str(state.get("program_id") or clean_program) != clean_program:
        raise EditorialError("program state identity does not match the requested report")
    events_snapshot = snapshot_project_file(root, events_relative)
    events_payload: dict[str, Any] = {}
    if events_snapshot is not None:
        events_payload = _editorial_snapshot_mapping(events_snapshot, label="reporting events")
        if str(events_payload.get("program_id") or clean_program) != clean_program:
            raise EditorialError("reporting events identity does not match the requested report")
        if not isinstance(events_payload.get("items", []), list):
            raise EditorialError("reporting events items must be a list")
    operation = output_kind
    inputs = load_report_inputs(
        root,
        clean_program,
        stage=stage,
        limit=limit,
        preference_selection_id=preference_selection_id,
        preference_operation=operation,
    )
    state_after = snapshot_project_file(root, state_relative)
    events_after = snapshot_project_file(root, events_relative)
    if not _same_project_snapshot(state_snapshot, state_after) or not _same_project_snapshot(events_snapshot, events_after):
        raise EditorialError("report state or events changed while editorial inputs were captured")
    loaded_events = events_payload.get("items", []) if isinstance(events_payload, dict) else []
    selected_unit_ids = sorted(_collect_unit_ids(state) | _collect_unit_ids(loaded_events))
    support_catalog, missing_factual_identity = _editorial_support_catalog(inputs)
    risk_catalog = _editorial_risk_catalog(inputs, missing_factual_identity)
    figure_catalog, figure_validators = _load_editorial_figures(root, selected_unit_ids)
    if state_snapshot is None or not state_snapshot.is_current():
        raise EditorialError("program state changed while editorial inputs were captured")
    if events_snapshot is None:
        if snapshot_project_file(root, events_relative) is not None:
            raise EditorialError("reporting events appeared while editorial inputs were captured")
    elif not events_snapshot.is_current():
        raise EditorialError("reporting events changed while editorial inputs were captured")
    if not inputs.formal_lane_pending and not inputs.formal_inputs_are_current():
        raise EditorialError("formal report inputs changed while editorial catalogs were built")
    if not all(validator() for validator in figure_validators):
        raise EditorialError("figure inputs changed while editorial catalogs were built")
    report_snapshot = report_input_snapshot(inputs)
    manifest = build_editorial_manifest(
        program_id=clean_program,
        output_kind=output_kind,
        as_of=as_of,
        request={
            "stage": str(stage or ""),
            "limit": int(limit),
            "preference_selection_id": str(preference_selection_id or ""),
            "program_title": str(state.get("title") or state.get("question") or clean_program),
        },
        input_bindings={
            "state": {"byte_sha256": state_snapshot.byte_sha256, "byte_count": len(state_snapshot.raw_bytes)},
            "events": (
                {"status": "present", "byte_sha256": events_snapshot.byte_sha256, "byte_count": len(events_snapshot.raw_bytes)}
                if events_snapshot is not None
                else {"status": "absent", "byte_sha256": "", "byte_count": 0}
            ),
            "report_snapshot_digest": _canonical_digest(report_snapshot),
            "preference_binding": copy.deepcopy(inputs.preference_binding),
            "presentation": {"language": inputs.language, "reporting_style": inputs.reporting_style},
            "formal_lane_pending": bool(inputs.formal_lane_pending),
        },
        support_catalog=support_catalog,
        risk_catalog=risk_catalog,
        figure_catalog=figure_catalog,
    )
    return manifest, inputs


def _reload_current_editorial_manifest(
    root: Path,
    expected: Mapping[str, Any],
) -> tuple[dict[str, Any], ReportInputs]:
    request = expected.get("request") if isinstance(expected.get("request"), Mapping) else {}
    try:
        current, inputs = _load_editorial_runtime(
            root,
            str(expected.get("program_id") or ""),
            str(expected.get("output_kind") or ""),
            stage=str(request.get("stage") or ""),
            limit=int(request.get("limit", 20)),
            preference_selection_id=str(request.get("preference_selection_id") or ""),
            as_of=str(expected.get("as_of") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise EditorialError("editorial request binding is invalid or stale") from exc
    if current != expected:
        raise EditorialError("editorial manifest inputs changed; prepare a fresh fill")
    return current, inputs


def prepare_editorial_report(
    root: Path,
    program_id: str,
    output_kind: str,
    *,
    stage: str,
    limit: int,
    preference_selection_id: str,
) -> int:
    manifest_path, fill_path, _output_path = _editorial_paths(root, program_id, output_kind)
    manifest: dict[str, Any] | None = None
    prior_manifest_snapshot = snapshot_project_file(root, manifest_path.relative_to(root).as_posix())
    if prior_manifest_snapshot is not None:
        try:
            prior_manifest = _editorial_snapshot_mapping(prior_manifest_snapshot, label="editorial manifest")
            prior_request = prior_manifest.get("request") if isinstance(prior_manifest.get("request"), Mapping) else {}
            if (
                not editorial_manifest_violations(prior_manifest)
                and prior_manifest.get("program_id") == program_id
                and prior_manifest.get("output_kind") == output_kind
                and str(prior_request.get("stage") or "") == str(stage or "")
                and int(prior_request.get("limit", 20)) == int(limit)
                and str(prior_request.get("preference_selection_id") or "") == str(preference_selection_id or "")
            ):
                candidate, _candidate_inputs = _load_editorial_runtime(
                    root,
                    program_id,
                    output_kind,
                    stage=stage,
                    limit=limit,
                    preference_selection_id=preference_selection_id,
                    as_of=str(prior_manifest.get("as_of") or ""),
                )
                if candidate == prior_manifest:
                    manifest = candidate
        except (EditorialError, TypeError, ValueError):
            manifest = None
    if manifest is None:
        manifest, _inputs = _load_editorial_runtime(
            root,
            program_id,
            output_kind,
            stage=stage,
            limit=limit,
            preference_selection_id=preference_selection_id,
            as_of=utc_now_iso(),
        )

    def require_current() -> None:
        _reload_current_editorial_manifest(root, manifest)

    preserved = False
    with command_mutation(
        root,
        f"report-author:{output_kind}-prepare",
        [manifest_path, fill_path],
        commit_guard=require_current,
    ):
        require_current()
        if prior_manifest_snapshot is not None and not prior_manifest_snapshot.is_current():
            raise EditorialError("editorial manifest changed before prepare acquired the workspace lock")
        existing_manifest_snapshot = snapshot_project_file(root, manifest_path.relative_to(root).as_posix())
        if prior_manifest_snapshot is None and existing_manifest_snapshot is not None:
            raise EditorialError("editorial manifest appeared before prepare acquired the workspace lock")
        existing_manifest = None
        if existing_manifest_snapshot is not None:
            existing_manifest = _editorial_snapshot_mapping(existing_manifest_snapshot, label="editorial manifest")
        existing_fill_snapshot = snapshot_project_file(root, fill_path.relative_to(root).as_posix())
        if existing_manifest == manifest and existing_fill_snapshot is not None:
            existing_fill = _editorial_snapshot_mapping(existing_fill_snapshot, label="editorial fill")
            if not fill_matches_manifest(existing_fill, manifest):
                raise EditorialError("current editorial fill is malformed; use recovery before preparing again")
            preserved = True
        write_yaml_if_changed(manifest_path, manifest)
        if not preserved:
            write_yaml_if_changed(fill_path, build_editorial_fill_scaffold(manifest))
        require_current()
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: prepare {output_kind} editorial fill for {program_id}",
        target_paths=[manifest_path, fill_path],
    )
    kind_label = "周报" if output_kind == "weekly" else "PPT"
    print(f"{kind_label}编辑材料已准备；{'保留了当前 Agent 填写内容' if preserved else '等待 Agent 填写'}。")
    return 0


def verify_editorial_report(root: Path, program_id: str, output_kind: str) -> int:
    manifest_path, fill_path, output_path = _editorial_paths(root, program_id, output_kind)
    manifest_snapshot = snapshot_project_file(root, manifest_path.relative_to(root).as_posix())
    manifest = _editorial_snapshot_mapping(manifest_snapshot, label="editorial manifest")
    violations = editorial_manifest_violations(manifest)
    if violations:
        raise EditorialError("editorial manifest is invalid: " + "; ".join(violations))
    if manifest.get("program_id") != program_id or manifest.get("output_kind") != output_kind:
        raise EditorialError("editorial manifest identity does not match this verification request")
    _current, inputs = _reload_current_editorial_manifest(root, manifest)
    fill_snapshot = snapshot_project_file(root, fill_path.relative_to(root).as_posix())
    fill = _editorial_snapshot_mapping(fill_snapshot, label="editorial fill")
    fill_violations = validate_editorial_fill(fill, manifest)
    if fill_violations:
        raise EditorialError("editorial fill failed verification: " + "; ".join(fill_violations))
    text = (
        render_weekly_editorial(fill, manifest, language=inputs.language)
        if output_kind == "weekly"
        else render_ppt_editorial(fill, manifest, language=inputs.language)
    )

    def require_current() -> None:
        if manifest_snapshot is None or fill_snapshot is None:
            raise EditorialError("editorial manifest or fill snapshot is unavailable")
        if not manifest_snapshot.is_current() or not fill_snapshot.is_current():
            raise EditorialError("editorial manifest or fill changed during verification")
        _reload_current_editorial_manifest(root, manifest)
        current_fill = _editorial_snapshot_mapping(fill_snapshot, label="editorial fill")
        current_violations = validate_editorial_fill(current_fill, manifest)
        if current_violations:
            raise EditorialError("editorial fill changed or became invalid during publication")

    with command_mutation(
        root,
        f"report-author:{output_kind}-verify",
        [fill_path, output_path],
        commit_guard=require_current,
    ):
        require_current()
        write_text_if_changed(output_path, text)
        require_current()
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: publish {output_kind} editorial report for {program_id}",
        target_paths=[fill_path, output_path],
    )
    print("周报已通过引用校验并发布。" if output_kind == "weekly" else "PPT 素材已通过引用校验并发布。")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_workspace(root)
    if args.command in {"weekly-prepare", "weekly-verify", "ppt-prepare", "ppt-verify"}:
        output_kind = "weekly" if args.command.startswith("weekly-") else "ppt-materials"
        try:
            if args.command.endswith("-prepare"):
                return prepare_editorial_report(
                    root,
                    args.program_id,
                    output_kind,
                    stage=args.stage,
                    limit=args.limit,
                    preference_selection_id=args.preference_selection_id,
                )
            return verify_editorial_report(root, args.program_id, output_kind)
        except EditorialError as exc:
            kind_label = "周报" if output_kind == "weekly" else "PPT 素材"
            if args.command.endswith("-verify"):
                raise SystemExit(
                    f"{kind_label}尚未发布：请让 Agent 补齐准备材料中的正文与依据；"
                    "问题与风险使用风险标记，下周计划使用计划标记，然后重试。"
                ) from exc
            raise SystemExit(
                f"{kind_label}准备未完成：研究材料可能已变化，请重新发起本次报告。"
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit("报告编辑操作未完成：输入已变化或工作区不安全，请重新准备后重试。") from exc
    if args.command in {"draft-prepare", "draft-verify", "draft-export"}:
        try:
            if args.command == "draft-prepare":
                return prepare_paper_draft(root, args.program_id)
            if args.command == "draft-verify":
                return verify_paper_draft_section(
                    root, args.program_id, args.section_id
                )
            return export_paper_draft(root, args.program_id)
        except PaperDraftRuntimeError as exc:
            raise SystemExit(f"论文草稿操作未完成：{exc}") from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(
                "论文草稿操作未完成：输入在操作期间发生变化或工作区不安全，请重新准备后重试。"
            ) from exc
    if args.command == "bib":
        try:
            bibliography = load_bibliography_inputs(root, args.program_id)
        except BibliographyError as exc:
            raise SystemExit(f"无法导出引用：{exc}") from exc
        path = root / "kb" / "output" / args.program_id / "references.bib"

        def require_bibliography_current_at_commit() -> None:
            if not bibliography.is_current():
                raise RuntimeError("bibliography inputs changed during publication")

        with command_mutation(
            root,
            "report-author:bib",
            [path],
            commit_guard=require_bibliography_current_at_commit,
        ):
            if not bibliography.is_current():
                raise RuntimeError("bibliography inputs changed before publication")
            rendered = bibliography.rendered
            if not bibliography.is_current():
                raise RuntimeError("bibliography inputs changed after rendering")
            write_text_if_changed(path, rendered)
            if not bibliography.is_current():
                raise RuntimeError("bibliography inputs changed during publication")
        missing_year = sum(
            1 for entry in bibliography.entries if not str(entry.get("fields", {}).get("year") or "")
        )
        print(f"已导出 {len(bibliography.entries)} 条去重引用，其中 {missing_year} 条缺少年份。")
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: export bibliography for {args.program_id}",
            target_paths=[path],
        )
        return 0
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
    publishes_formal_lane = False

    def require_formal_inputs_current_at_commit() -> None:
        if publishes_formal_lane and not inputs.formal_inputs_are_current():
            raise RuntimeError("formal report inputs changed during publication")

    with command_mutation(
        root,
        f"report-author:{args.command}",
        [path],
        commit_guard=require_formal_inputs_current_at_commit,
    ):
        title = report_title(args.command, args.program_id, language=inputs.language)
        text = render_outline(args.program_id, inputs) if args.command == "outline" else render_report(title, inputs, report_kind=args.command)
        publishes_formal_lane = inputs.formal_inputs_are_current()
        if not publishes_formal_lane:
            pending_title = (
                f"Paper Outline: {args.program_id}"
                if args.command == "outline" and _is_english(inputs.language)
                else f"论文大纲：{args.program_id}"
                if args.command == "outline"
                else title
            )
            text = _render_aggregate_pending_document(
                pending_title,
                inputs,
                report_kind=args.command,
            )
        if inputs.preference_binding:
            binding_text = json.dumps(inputs.preference_binding, ensure_ascii=False, sort_keys=True)
            text = f"<!-- effective-preferences: {binding_text} -->\n" + text
        write_text_if_changed(path, text)
        if publishes_formal_lane and not inputs.formal_inputs_are_current():
            raise RuntimeError("formal report inputs changed during publication")
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

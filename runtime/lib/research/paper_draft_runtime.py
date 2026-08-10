"""Read-only, snapshot-bound inputs for the paper-draft owner integration.

This module never authors prose and never writes canonical state.  It captures
the exact outline, program selection, confirmed source claims, bibliography,
and current figure bindings consumed by section verification/publication.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .bibliography import BibliographyError, bibliography_from_records
from .confirm import has_complete_confirmation_receipt
from .evidence import (
    confirmation_claims,
    confirmation_content_digest,
    record_external_source_contract,
    validate_claims,
)
from .figures import FigureIndexError, load_current_figure_index
from .paper_drafts import (
    SECTION_IDENTITIES,
    draft_manifest_currentness_violations,
    paper_draft_section_lifecycle_violations,
)
from .paths import kb_root, unit_root
from .records import (
    CanonicalRecordSnapshot,
    ProjectFileSnapshot,
    canonical_record_snapshot_for_identity,
    iter_canonical_record_snapshots,
    normalize_record_snapshot,
    snapshot_project_file,
    trusted_claim_source_roots,
)
from .yaml_io import StrictYamlError, load_yaml_mapping_bytes_strict


_UNIT_ID_FIELDS = {
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


class PaperDraftRuntimeError(ValueError):
    """Stable fail-closed error for stale or unsafe paper-draft inputs."""


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_program_id(value: Any) -> str:
    program_id = str(value or "").strip()
    if (
        not program_id
        or Path(program_id).name != program_id
        or program_id in {".", ".."}
        or "\x00" in program_id
    ):
        raise PaperDraftRuntimeError("paper draft program id is unsafe")
    return program_id


def paper_draft_root(root: Path, program_id: str) -> Path:
    return kb_root(root) / "programs" / _safe_program_id(program_id) / "reports" / "paper-draft"


def paper_draft_manifest_path(root: Path, program_id: str) -> Path:
    return paper_draft_root(root, program_id) / "manifest.yaml"


def paper_draft_outline_path(root: Path, program_id: str) -> Path:
    return kb_root(root) / "programs" / _safe_program_id(program_id) / "reports" / "paper-outline.md"


def _safe_section_id(value: Any) -> str:
    section_id = str(value or "").strip()
    if section_id not in SECTION_IDENTITIES:
        raise PaperDraftRuntimeError("paper draft section id is invalid")
    return section_id


def paper_draft_fill_path(root: Path, program_id: str, section_id: str) -> Path:
    return paper_draft_root(root, program_id) / "fills" / f"{_safe_section_id(section_id)}-fill.yaml"


def paper_draft_section_path(root: Path, program_id: str, section_id: str) -> Path:
    return paper_draft_root(root, program_id) / "sections" / f"{_safe_section_id(section_id)}.yaml"


def _strict_mapping(snapshot: ProjectFileSnapshot, *, label: str) -> dict[str, Any]:
    try:
        return load_yaml_mapping_bytes_strict(snapshot.raw_bytes)
    except (RuntimeError, StrictYamlError) as exc:
        raise PaperDraftRuntimeError(f"{label} is not a strict YAML mapping") from exc


def _collect_unit_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in _UNIT_ID_FIELDS:
                if isinstance(child, str) and child.strip():
                    result.add(child.strip())
                elif isinstance(child, (list, tuple, set)):
                    result.update(str(item).strip() for item in child if str(item).strip())
            result.update(_collect_unit_ids(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.update(_collect_unit_ids(child))
    return result


def _same_record_snapshot(left: CanonicalRecordSnapshot, right: CanonicalRecordSnapshot) -> bool:
    return bool(
        left.kind == right.kind
        and left.unit_id == right.unit_id
        and left.path == right.path
        and left.raw_bytes == right.raw_bytes
        and left.file_identity == right.file_identity
        and left.directory_capabilities == right.directory_capabilities
    )


def _claim_binding(record: Mapping[str, Any], claim: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
    verification = payload.get("verification") if isinstance(payload.get("verification"), Mapping) else {}
    receipt = record.get("confirmation") if isinstance(record.get("confirmation"), Mapping) else {}
    return {
        "source_unit_id": str(record.get("id") or ""),
        "claim_id": str(claim.get("id") or ""),
        "confirmation_status": "confirmed",
        "claim_digest": _digest(claim),
        "record_content_digest": confirmation_content_digest(dict(record)),
        "confirmation_receipt_digest": _digest(receipt),
        "evidence_digest": str(verification.get("evidence_digest") or ""),
        "evidence_refs": copy.deepcopy(list(claim.get("evidence_refs") or [])),
    }


def _figure_binding(index: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
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


@dataclass(frozen=True)
class PaperDraftInputs:
    root: Path
    program_id: str
    selected_unit_ids: tuple[str, ...]
    outline_snapshot: ProjectFileSnapshot
    state_snapshot: ProjectFileSnapshot
    events_snapshot: ProjectFileSnapshot | None
    record_snapshots: tuple[CanonicalRecordSnapshot, ...]
    claim_catalog: dict[str, dict[str, Any]]
    bibliography_catalog: dict[str, dict[str, Any]]
    figure_catalog: dict[str, dict[str, Any]]
    bibliography_text: str
    source_roots: dict[str, Any] = field(repr=False, compare=False)
    validators: tuple[Callable[[], bool], ...] = field(repr=False, compare=False)

    def is_current(self) -> bool:
        try:
            if not self.outline_snapshot.is_current() or not self.state_snapshot.is_current():
                return False
            events_relative = f"kb/programs/{self.program_id}/workflow/reporting-events.yaml"
            if self.events_snapshot is None:
                if snapshot_project_file(self.root, events_relative) is not None:
                    return False
            elif not self.events_snapshot.is_current():
                return False
            captured = {snapshot.unit_id: snapshot for snapshot in self.record_snapshots}
            selected = set(self.selected_unit_ids)
            current_index: dict[str, CanonicalRecordSnapshot | None] = {}
            for snapshot in iter_canonical_record_snapshots(self.root):
                if snapshot.unit_id not in selected:
                    continue
                if snapshot.unit_id in current_index:
                    current_index[snapshot.unit_id] = None
                else:
                    current_index[snapshot.unit_id] = snapshot
            for unit_id in self.selected_unit_ids:
                expected = captured.get(unit_id)
                if unit_id not in current_index:
                    if expected is not None:
                        return False
                    continue
                current = current_index[unit_id]
                if (
                    expected is None
                    or current is None
                    or not _same_record_snapshot(expected, current)
                ):
                    return False
            return all(bool(validator()) for validator in self.validators)
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return False


def load_paper_draft_inputs(root: Path, program_id: str) -> PaperDraftInputs:
    """Capture every current upstream used by section verification/export."""
    project_root = root.absolute()
    clean_program_id = _safe_program_id(program_id)
    state_relative = f"kb/programs/{clean_program_id}/state.yaml"
    events_relative = f"kb/programs/{clean_program_id}/workflow/reporting-events.yaml"
    outline_relative = f"kb/programs/{clean_program_id}/reports/paper-outline.md"
    state_snapshot = snapshot_project_file(project_root, state_relative)
    outline_snapshot = snapshot_project_file(project_root, outline_relative)
    if state_snapshot is None:
        raise PaperDraftRuntimeError("program state is missing or unsafe")
    if outline_snapshot is None:
        raise PaperDraftRuntimeError("paper outline is missing or unsafe")
    state = _strict_mapping(state_snapshot, label="program state")
    if str(state.get("program_id") or clean_program_id) != clean_program_id:
        raise PaperDraftRuntimeError("program state identity does not match the draft")
    events_snapshot = snapshot_project_file(project_root, events_relative)
    events: dict[str, Any] = {}
    if events_snapshot is not None:
        events = _strict_mapping(events_snapshot, label="reporting events")
        if str(events.get("program_id") or clean_program_id) != clean_program_id:
            raise PaperDraftRuntimeError("reporting events identity does not match the draft")
    selected_ids = sorted(_collect_unit_ids(state) | _collect_unit_ids(events))

    snapshot_index: dict[str, CanonicalRecordSnapshot | None] = {}
    for snapshot in iter_canonical_record_snapshots(project_root):
        if snapshot.unit_id in snapshot_index:
            snapshot_index[snapshot.unit_id] = None
        else:
            snapshot_index[snapshot.unit_id] = snapshot
    selected_snapshots: list[CanonicalRecordSnapshot] = []
    records: list[dict[str, Any]] = []
    for unit_id in selected_ids:
        snapshot = snapshot_index.get(unit_id)
        if snapshot is None:
            continue
        record = normalize_record_snapshot(snapshot, project_root)
        if record is None:
            continue
        selected_snapshots.append(snapshot)
        records.append(record)

    claim_catalog: dict[str, dict[str, Any]] = {}
    source_roots: dict[str, Any] = {}
    validators: list[Callable[[], bool]] = []
    for snapshot, record in zip(selected_snapshots, records):
        if str(record.get("confirmation_status") or "") != "confirmed":
            continue
        try:
            roots = trusted_claim_source_roots(
                project_root,
                record,
                verification_root=snapshot.path.parent,
                expected_record_snapshot=snapshot,
            )
        except ValueError:
            continue
        if not has_complete_confirmation_receipt(
            record,
            verification_root=snapshot.path.parent,
            source_roots=roots,
            external_source=record_external_source_contract(record),
        ):
            continue
        receipt = record.get("confirmation") if isinstance(record.get("confirmation"), Mapping) else {}
        covered = {str(item) for item in list(receipt.get("claim_ids") or []) if str(item)}
        for claim in confirmation_claims(record):
            claim_id = str(claim.get("id") or "")
            if (
                claim_id not in covered
                or validate_claims([claim])
            ):
                continue
            claim_catalog[f"{record['id']}:{claim_id}"] = _claim_binding(record, claim)
        for source_id, source in roots.items():
            source_roots.setdefault(str(source_id), source)
        validators.extend(
            source.is_current
            for source in roots.values()
            if callable(getattr(source, "is_current", None))
        )

    paper_records = [record for record in records if record.get("kind") == "paper"]
    try:
        bibliography_entries, bibliography_text = bibliography_from_records(paper_records)
    except BibliographyError as exc:
        raise PaperDraftRuntimeError(f"bibliography inputs are invalid: {exc}") from exc
    snapshot_by_id = {snapshot.unit_id: snapshot for snapshot in selected_snapshots}
    bibliography_catalog: dict[str, dict[str, Any]] = {}
    for entry in bibliography_entries:
        unit_id = str(entry.get("unit_id") or "")
        snapshot = snapshot_by_id.get(unit_id)
        if snapshot is None:
            raise PaperDraftRuntimeError("bibliography entry lost its canonical record binding")
        bibliography_catalog[str(entry["citation_key"])] = {
            "unit_id": unit_id,
            "entry_digest": _digest(entry),
            "record_digest": hashlib.sha256(snapshot.raw_bytes).hexdigest(),
        }

    figure_catalog: dict[str, dict[str, Any]] = {}
    for record in paper_records:
        unit_id = str(record.get("id") or "")
        payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
        projection = payload.get("figures") if isinstance(payload.get("figures"), Mapping) else {}
        expected_digest = str(projection.get("index_digest") or "")
        if (
            projection.get("schema") != "figure-index/v1"
            or projection.get("index_artifact") != "figures.yaml"
            or not expected_digest
        ):
            continue
        paper_root = unit_root(project_root, "paper", unit_id)
        index_path = paper_root / "figures.yaml"
        try:
            index = load_current_figure_index(
                index_path,
                unit_root=paper_root,
                project_root=project_root,
                expected_index_digest=expected_digest,
            )
        except FigureIndexError as exc:
            raise PaperDraftRuntimeError(f"figure index for {unit_id} is stale: {exc}") from exc
        frozen_bindings: dict[str, dict[str, Any]] = {}
        for entry in index.get("entries", []):
            if not isinstance(entry, Mapping):
                continue
            ref_key = str(entry.get("ref_key") or "")
            binding = _figure_binding(index, entry)
            figure_catalog[ref_key] = binding
            frozen_bindings[ref_key] = binding

        def figure_current(
            index_path: Path = index_path,
            paper_root: Path = paper_root,
            expected_digest: str = expected_digest,
            frozen_bindings: dict[str, dict[str, Any]] = frozen_bindings,
        ) -> bool:
            try:
                current = load_current_figure_index(
                    index_path,
                    unit_root=paper_root,
                    project_root=project_root,
                    expected_index_digest=expected_digest,
                )
                current_bindings = {
                    str(entry.get("ref_key") or ""): _figure_binding(current, entry)
                    for entry in current.get("entries", [])
                    if isinstance(entry, Mapping)
                }
                return current_bindings == frozen_bindings
            except (FigureIndexError, OSError, ValueError):
                return False

        validators.append(figure_current)

    captured = PaperDraftInputs(
        root=project_root,
        program_id=clean_program_id,
        selected_unit_ids=tuple(selected_ids),
        outline_snapshot=outline_snapshot,
        state_snapshot=state_snapshot,
        events_snapshot=events_snapshot,
        record_snapshots=tuple(selected_snapshots),
        claim_catalog=claim_catalog,
        bibliography_catalog=bibliography_catalog,
        figure_catalog=figure_catalog,
        bibliography_text=bibliography_text,
        source_roots=source_roots,
        validators=tuple(validators),
    )
    if not captured.is_current():
        raise PaperDraftRuntimeError("paper draft inputs changed while they were captured")
    return captured


def load_current_draft_manifest(
    root: Path,
    program_id: str,
    inputs: PaperDraftInputs | None = None,
) -> tuple[dict[str, Any], ProjectFileSnapshot, PaperDraftInputs]:
    current_inputs = inputs or load_paper_draft_inputs(root, program_id)
    relative = paper_draft_manifest_path(root, program_id).relative_to(root).as_posix()
    snapshot = snapshot_project_file(root, relative)
    if snapshot is None:
        raise PaperDraftRuntimeError("paper draft manifest is missing or unsafe")
    manifest = _strict_mapping(snapshot, label="paper draft manifest")
    violations = draft_manifest_currentness_violations(
        manifest,
        outline_bytes=current_inputs.outline_snapshot.raw_bytes,
        claim_catalog=current_inputs.claim_catalog,
        bibliography_catalog=current_inputs.bibliography_catalog,
        figure_catalog=current_inputs.figure_catalog,
    )
    if violations:
        raise PaperDraftRuntimeError("paper draft manifest is stale: " + "; ".join(violations))
    if not snapshot.is_current() or not current_inputs.is_current():
        raise PaperDraftRuntimeError("paper draft manifest changed while it was captured")
    return manifest, snapshot, current_inputs


def paper_draft_section_currentness_violations(
    root: Path,
    record: Mapping[str, Any],
    artifact_path: Path,
) -> list[str]:
    """Rebuild current catalogs before exposing or consuming one section."""
    program_id = str(record.get("program_id") or "")
    try:
        inputs = load_paper_draft_inputs(root, program_id)
        manifest, manifest_snapshot, inputs = load_current_draft_manifest(
            root, program_id, inputs
        )
    except PaperDraftRuntimeError as exc:
        return [str(exc)]
    expected_path = paper_draft_section_path(
        root, program_id, str(record.get("section_id") or "")
    ).absolute()
    if artifact_path.absolute() != expected_path:
        return ["paper draft section path is not canonical"]
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
    if not manifest_snapshot.is_current() or not inputs.is_current():
        violations.append("paper draft inputs changed during currentness validation")
    return violations


__all__ = [
    "PaperDraftInputs",
    "PaperDraftRuntimeError",
    "load_current_draft_manifest",
    "load_paper_draft_inputs",
    "paper_draft_fill_path",
    "paper_draft_manifest_path",
    "paper_draft_outline_path",
    "paper_draft_root",
    "paper_draft_section_currentness_violations",
    "paper_draft_section_path",
]

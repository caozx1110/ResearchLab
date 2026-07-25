"""Shared discovery and binding contract for cross-owner judgement artifacts.

Owner files remain authoritative for their domain-specific fields.  This module
only recognizes the governance envelope shared by every judgement:
canonical ``payload.claims``, a current verification receipt, and (after human
approval) a current ConfirmationReceipt.  Discovery is deliberately
fail-closed: incomplete, stale, rejected, or already-confirmed artifacts never
become public review cards.
"""
from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .common import load_yaml, utc_now_iso
from .confirm import has_complete_confirmation_receipt
from .evidence import (
    CONFIRMABLE_CONTENT_FIELDS,
    CONFIRMABLE_CONTENT_SECTIONS,
    JUDGEMENT_CLAIM_TYPES,
    UNCONFIRMABLE_CLAIM_TYPES,
    confirmation_claim_ids,
    confirmation_claims,
    confirmation_content_digest,
    record_external_source_contract,
    validate_claims,
    verification_receipt_violations,
)
from .records import (
    CanonicalRecordSnapshot,
    ProjectFileSnapshot,
    ProjectYamlMappingSnapshot,
    canonical_record_snapshot_for_identity,
    iter_canonical_record_snapshots,
    normalize_record_snapshot,
    require_current_record_snapshot,
    snapshot_project_file,
    trusted_claim_source_roots,
    trusted_program_root,
    trusted_project_path,
    trusted_unit_record_path,
)
from .surveys import (
    survey_artifact_path,
    survey_content_digest,
    survey_lifecycle_violations,
    survey_source_roots,
)
from .yaml_io import StrictYamlError, load_yaml_mapping_bytes_strict


UNIT_OWNER_BY_KIND = {
    "paper": "paper-analyst",
    "repo": "repo-analyst",
    "dataset": "dataset-analyst",
    "blog": "blog-analyst",
    "idea": "idea-workbench",
    "experiment": "experiment-workbench",
}
UNIT_DIR_BY_KIND = {
    "paper": "papers",
    "repo": "repos",
    "dataset": "datasets",
    "blog": "blogs",
    "idea": "ideas",
    "experiment": "experiments",
}
SIDE_OWNER_BY_KIND = {
    "program_decision": "research-orchestrator",
    "idea_discussion_conclusion": "idea-workbench",
    "method_selection": "method-designer",
    "survey_judgement": "literature-synthesizer",
}
REQUIRED_SIDE_SUBSTANCE_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "program_decision": (("decision", "text"),),
    "idea_discussion_conclusion": (("discussion_conclusion", "text"),),
    "method_selection": (
        ("method_selection", "proposed_repo_id"),
        ("method_selection", "selection_reason"),
    ),
}


@dataclass(frozen=True)
class BoundJudgementSnapshot:
    """One judgement bound to the exact canonical bytes that produced it."""

    record: dict[str, Any]
    path: Path
    owner: str
    unit_record_snapshot: CanonicalRecordSnapshot | None = None
    project_yaml_snapshot: ProjectYamlMappingSnapshot | None = None
    validate_unique_current: Callable[[], bool] = field(repr=False, compare=False, default=lambda: False)

    def is_current(self) -> bool:
        try:
            return bool(self.validate_unique_current())
        except (OSError, ValueError):
            return False


@dataclass(frozen=True)
class BoundJudgementContainerSnapshot:
    """Side judgements selected from one exact strict-YAML container capture."""

    container: ProjectYamlMappingSnapshot
    judgements: tuple[BoundJudgementSnapshot, ...]
    validate_current: Callable[[], bool] = field(repr=False, compare=False)

    def is_current(self) -> bool:
        try:
            return bool(self.validate_current())
        except (OSError, ValueError):
            return False


@dataclass(frozen=True)
class BoundJudgementBatchSnapshot:
    """One globally indexed capture shared by many judgement consumers."""

    root: Path
    judgements: tuple[BoundJudgementSnapshot, ...]
    side_containers: tuple[ProjectYamlMappingSnapshot, ...]
    unit_judgements: tuple[BoundJudgementSnapshot, ...]
    validate_side_current: Callable[[], bool] = field(repr=False, compare=False)
    subject_index: dict[tuple[str, str], BoundJudgementSnapshot | None] = field(
        repr=False,
        compare=False,
        default_factory=dict,
    )

    def resolve(self, subject: Any) -> BoundJudgementSnapshot | None:
        if not isinstance(subject, dict):
            return None
        subject_kind = _text(subject.get("kind"))
        subject_id = _text(subject.get("id"))
        bound = self.subject_index.get((subject_kind, subject_id))
        if bound is None:
            return None
        supplied_owner = _text(subject.get("owner"))
        supplied_path = _text(subject.get("path"))
        if supplied_owner and supplied_owner != bound.owner:
            return None
        if supplied_path:
            try:
                canonical_path = bound.path.relative_to(self.root).as_posix()
            except ValueError:
                return None
            if supplied_path != canonical_path:
                return None
        return bound

    def is_current(self) -> bool:
        try:
            return bool(self.validate_side_current()) and all(
                bound.is_current() for bound in self.unit_judgements
            )
        except (OSError, ValueError):
            return False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_project_root(root: str | Path) -> Path:
    lexical_root = Path(root).absolute()
    try:
        lexical_stat = lexical_root.lstat()
    except OSError as exc:
        raise ValueError("project root is not an existing ordinary directory") from exc
    if stat.S_ISLNK(lexical_stat.st_mode) or not stat.S_ISDIR(lexical_stat.st_mode):
        raise ValueError("project root itself must be a real directory, not a symlink")
    try:
        canonical_root = lexical_root.resolve(strict=True)
        canonical_stat = canonical_root.lstat()
    except OSError as exc:
        raise ValueError("project root cannot be canonicalized safely") from exc
    if (
        not stat.S_ISDIR(canonical_stat.st_mode)
        or (canonical_stat.st_dev, canonical_stat.st_ino)
        != (lexical_stat.st_dev, lexical_stat.st_ino)
    ):
        raise ValueError("project root changed while it was being canonicalized")
    return canonical_root


def _safe_relative_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved = trusted_project_path(
        resolved_root,
        path,
        allowed_root=resolved_root / "kb",
        require="file",
    )
    return resolved.relative_to(resolved_root).as_posix()


def _unit_path(root: Path, unit_id: str) -> Path | None:
    try:
        return trusted_unit_record_path(root, unit_id)
    except ValueError:
        return None


def _identity_violations(root: Path, record: dict[str, Any], owner: str, artifact_path: Path) -> list[str]:
    kind = _text(record.get("kind"))
    subject_id = _text(record.get("id"))
    violations: list[str] = []
    try:
        _safe_relative_path(root, artifact_path)
    except ValueError:
        violations.append("judgement artifact path escapes the project root")
    if not subject_id:
        return ["judgement subject id is empty"]
    expected_owner = UNIT_OWNER_BY_KIND.get(kind)
    expected_path: Path | None = None
    if expected_owner:
        expected_path = root / "kb" / "units" / UNIT_DIR_BY_KIND[kind] / subject_id / "record.yaml"
    elif kind == "program_decision":
        program_id = _text(record.get("program_id"))
        expected_owner = "research-orchestrator"
        if not program_id:
            violations.append("program decision has no program_id")
        else:
            expected_path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    elif kind == "idea_discussion_conclusion":
        idea_id = _text(record.get("idea_id"))
        expected_owner = "idea-workbench"
        if not idea_id:
            violations.append("discussion conclusion has no idea_id")
        else:
            expected_path = root / "kb" / "units" / "ideas" / idea_id / "discussion-judgements.yaml"
    elif kind == "method_selection":
        program_id = _text(record.get("program_id"))
        idea_id = _text(record.get("idea_id"))
        expected_owner = "method-designer"
        if not program_id or not idea_id:
            violations.append("method selection has no canonical program_id/idea_id")
        else:
            if subject_id != f"method-selection:{program_id}:{idea_id}":
                violations.append("method selection id does not match program_id/idea_id")
            expected_path = root / "kb" / "programs" / program_id / "design" / f"{idea_id}-repo-choice.yaml"
        payload = record.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        selection = payload.get("method_selection")
        selection = selection if isinstance(selection, dict) else {}
        proposed_repo_id = _text(record.get("proposed_repo_id"))
        if proposed_repo_id != _text(selection.get("proposed_repo_id")):
            violations.append("method selection operative and confirmable proposed_repo_id differ")
        if _text(record.get("selected_repo_id")) or _text(selection.get("selected_repo_id")):
            violations.append("pending method selection already contains selected_repo_id")
    elif kind == "survey_judgement":
        expected_owner = "literature-synthesizer"
        slug = _text(record.get("slug"))
        mode = _text(record.get("mode"))
        if subject_id != f"survey:{mode}:{slug}":
            violations.append("survey judgement id does not match mode/slug")
        try:
            expected_path = survey_artifact_path(root, slug, mode)
        except ValueError:
            violations.append("survey judgement has no canonical mode/slug")
    else:
        violations.append(f"unsupported judgement kind: {kind or '<empty>'}")
    if expected_owner and owner != expected_owner:
        violations.append("judgement owner does not match canonical kind owner")
    if kind not in UNIT_OWNER_BY_KIND and _text(record.get("owner")) != expected_owner:
        violations.append("side judgement record.owner does not match canonical kind owner")
    if expected_path is not None:
        try:
            safe_artifact = trusted_project_path(
                root,
                artifact_path,
                allowed_root=root / "kb",
                require="file",
            )
            safe_expected = trusted_project_path(
                root,
                expected_path,
                allowed_root=root / "kb",
                require="file",
            )
        except ValueError:
            violations.append("judgement artifact path is not a canonical safe file")
        else:
            if safe_artifact != safe_expected:
                violations.append("judgement artifact path does not match canonical subject identity")
    return violations


def _source_roots(
    root: Path,
    record: dict[str, Any],
    artifact_path: Path,
    *,
    record_snapshot: CanonicalRecordSnapshot | None = None,
) -> dict[str, Any]:
    if _text(record.get("kind")) == "survey_judgement":
        return survey_source_roots(root, record, artifact_path)
    return trusted_claim_source_roots(
        root,
        record,
        verification_root=_verification_root(root, record, artifact_path),
        expected_record_snapshot=record_snapshot,
    )


def _verification_root(root: Path, record: dict[str, Any], artifact_path: Path) -> Path:
    program_id = _text(record.get("program_id"))
    if _text(record.get("kind")) == "program_decision" and program_id:
        return trusted_program_root(root, program_id)
    return trusted_project_path(
        root,
        artifact_path.parent,
        allowed_root=root / "kb",
        require="dir",
    )


def readiness_violations(
    root: Path,
    record: Any,
    artifact_path: Path,
    *,
    record_snapshot: CanonicalRecordSnapshot | None = None,
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> list[str]:
    """Return why a judgement must not appear in the human review inbox."""
    def finish(violations: list[str]) -> list[str]:
        if bound_snapshot is not None and not bound_snapshot.is_current():
            violations.append("judgement bound snapshot is no longer current")
        return violations

    if bound_snapshot is not None:
        if bound_snapshot.record != record or bound_snapshot.path != artifact_path.absolute():
            return finish(["judgement does not match its bound canonical snapshot"])
        if record_snapshot is not None and record_snapshot != bound_snapshot.unit_record_snapshot:
            return finish(["judgement record snapshot conflicts with its bound snapshot"])
        record_snapshot = bound_snapshot.unit_record_snapshot
    if not isinstance(record, dict):
        return finish(["judgement artifact must be a mapping"])
    if _text(record.get("confirmation_status")) != "pending_user_confirmation":
        return finish(["confirmation_status is not pending_user_confirmation"])
    claims = confirmation_claims(record)
    if not claims:
        return finish(["canonical payload.claims must be non-empty"])
    violations = validate_claims(claims)
    claim_types = {_text(claim.get("claim_type")) for claim in claims}
    if claim_types & UNCONFIRMABLE_CLAIM_TYPES:
        violations.append("canonical claims still contain unverified claim types")
    if not claim_types & JUDGEMENT_CLAIM_TYPES:
        violations.append("artifact has no judgement-class canonical claim")
    if any(_text(claim.get("confirmation_status")) != "pending_user_confirmation" for claim in claims):
        violations.append("canonical claim confirmation status is not pending_user_confirmation")
    if _text(record.get("kind")) == "survey_judgement":
        violations.extend(survey_lifecycle_violations(record, root))
    try:
        verification_root = _verification_root(root, record, artifact_path)
        source_roots = _source_roots(
            root,
            record,
            artifact_path,
            record_snapshot=record_snapshot,
        )
    except ValueError:
        violations.append("judgement evidence source is not canonically contained")
    else:
        violations.extend(
            verification_receipt_violations(
                record,
                verification_root,
                external_source=record_external_source_contract(record),
                source_roots=source_roots,
            )
        )
    return finish(violations)


def _judgement_confirmation_matches(
    root: Path,
    record: dict[str, Any],
    artifact_path: Path,
    *,
    record_snapshot: CanonicalRecordSnapshot | None = None,
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> bool:
    root = root.absolute()
    artifact_path = artifact_path.absolute()
    valid = True
    if bound_snapshot is not None:
        if bound_snapshot.record != record or bound_snapshot.path != artifact_path:
            valid = False
        if record_snapshot is not None and record_snapshot != bound_snapshot.unit_record_snapshot:
            valid = False
        record_snapshot = bound_snapshot.unit_record_snapshot
    if _text(record.get("kind")) == "survey_judgement" and survey_lifecycle_violations(record, root):
        valid = False
    try:
        verification_root = _verification_root(root, record, artifact_path)
        source_roots = _source_roots(
            root,
            record,
            artifact_path,
            record_snapshot=record_snapshot,
        )
    except ValueError:
        valid = False
    else:
        receipt_current = has_complete_confirmation_receipt(
            record,
            verification_root=verification_root,
            source_roots=source_roots,
            external_source=record_external_source_contract(record),
        )
        valid = valid and receipt_current
    return valid


def judgement_confirmation_is_current(
    root: Path,
    record: dict[str, Any],
    artifact_path: Path,
    *,
    record_snapshot: CanonicalRecordSnapshot | None = None,
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> bool:
    """Validate a judgement receipt and finish on its exact source snapshot."""
    return _judgement_confirmation_matches(
        root,
        record,
        artifact_path,
        record_snapshot=record_snapshot,
        bound_snapshot=bound_snapshot,
    ) and (bound_snapshot is None or bound_snapshot.is_current())


def judgement_confirmation_matches_bound(
    root: Path,
    bound_snapshot: BoundJudgementSnapshot,
) -> bool:
    """Validate receipt/evidence from a bound item before its batch final-current gate."""
    return _judgement_confirmation_matches(
        root,
        bound_snapshot.record,
        bound_snapshot.path,
        record_snapshot=bound_snapshot.unit_record_snapshot,
        bound_snapshot=bound_snapshot,
    )


def _default_route(record: dict[str, Any], owner: str) -> dict[str, str]:
    subject_id = _text(record.get("id"))
    kind = _text(record.get("kind"))
    if kind == "program_decision":
        return {
            "owner": owner,
            "action": "confirm-decision",
            "program_id": _text(record.get("program_id")),
            "decision_id": subject_id,
        }
    if kind == "idea_discussion_conclusion":
        return {
            "owner": owner,
            "action": "discuss",
            "phase": "confirm",
            "idea_id": _text(record.get("idea_id")),
            "conclusion_id": subject_id,
        }
    if kind == "method_selection":
        return {
            "owner": owner,
            "action": "confirm-selection",
            "program_id": _text(record.get("program_id")),
            "idea_id": _text(record.get("idea_id")),
        }
    if kind == "survey_judgement":
        return {
            "owner": owner,
            "action": "confirm",
            "slug": _text(record.get("slug")),
            "mode": _text(record.get("mode")),
        }
    return {"owner": owner, "action": "confirm", "subject_id": subject_id}


def pending_judgement_card(
    root: Path,
    record: Any,
    *,
    owner: str,
    artifact_path: Path,
    record_snapshot: CanonicalRecordSnapshot | None = None,
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> dict[str, Any] | None:
    """Build one internal review card, or ``None`` unless it is truly ready."""
    if not isinstance(record, dict):
        return None
    if _identity_violations(root, record, owner, artifact_path) or readiness_violations(
        root,
        record,
        artifact_path,
        record_snapshot=record_snapshot,
        bound_snapshot=bound_snapshot,
    ):
        return None
    route = _default_route(record, owner)
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    substance = {
        section: payload.get(section)
        for section in CONFIRMABLE_CONTENT_SECTIONS.get(_text(record.get("kind")), ())
        if payload.get(section) not in (None, "", [], {})
    }
    if _text(record.get("kind")) == "survey_judgement":
        substance = {
            "filters": record.get("filters") if isinstance(record.get("filters"), dict) else {},
            "as_of": (record.get("kb_anchor") or {}).get("as_of") if isinstance(record.get("kb_anchor"), dict) else "",
            "sections": record.get("sections") if isinstance(record.get("sections"), list) else [],
            "comparison_matrix": record.get("comparison_matrix") if isinstance(record.get("comparison_matrix"), dict) else {},
        }
        if not substance["sections"] or not substance["comparison_matrix"]:
            return None
    selected_fields = CONFIRMABLE_CONTENT_FIELDS.get(_text(record.get("kind")), {})
    if selected_fields:
        has_substance = any(
            isinstance(payload.get(section), dict)
            and any(payload[section].get(field) not in (None, "", [], {}) for field in fields)
            for section, fields in selected_fields.items()
        )
        if not has_substance:
            return None
    for section, field in REQUIRED_SIDE_SUBSTANCE_FIELDS.get(_text(record.get("kind")), ()):
        section_value = payload.get(section)
        value = section_value.get(field) if isinstance(section_value, dict) else None
        if value in (None, "", [], {}) or (isinstance(value, str) and not value.strip()):
            return None
    snapshot_binding = judgement_snapshot_binding(
        record,
        owner=owner,
        path=_safe_relative_path(root, artifact_path),
        bound_snapshot=bound_snapshot,
    )
    card = {
        "subject": {
            "kind": _text(record.get("kind")),
            "id": _text(record.get("id")),
            "owner": owner,
            "path": _safe_relative_path(root, artifact_path),
        },
        "claims": confirmation_claims(record),
        "substance": substance,
        "content_digest": snapshot_binding["content_digest"],
        "verification": dict(payload.get("verification", {})),
        "snapshot_binding": snapshot_binding,
        "confirmation_status": "pending_user_confirmation",
        "priority": _text(record.get("priority")) or "normal",
        "updated_at": _text(record.get("updated_at") or record.get("timestamp")),
        "confirm_route": {str(key): _text(value) for key, value in route.items()},
    }
    if _text(record.get("kind")) == "survey_judgement":
        card["reject_route"] = {
            "owner": owner,
            "action": "reject",
            "slug": _text(record.get("slug")),
            "mode": _text(record.get("mode")),
        }
        card["program_ids"] = [
            _text(item) for item in record.get("program_ids", []) if _text(item)
        ]
    if bound_snapshot is not None and not bound_snapshot.is_current():
        return None
    return card


def _safe_candidate_file(root: Path, path: Path) -> Path | None:
    try:
        return trusted_project_path(
            root,
            path,
            allowed_root=root / "kb",
            require="file",
        )
    except ValueError:
        return None


def _list_items(root: Path, path: Path) -> Iterable[dict[str, Any]]:
    safe_path = _safe_candidate_file(root, path)
    if safe_path is None:
        return []
    try:
        payload = load_yaml(safe_path, default={})
    except (OSError, UnicodeError, yaml.YAMLError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


@dataclass(frozen=True)
class _SideJudgementCandidate:
    record: dict[str, Any]
    owner: str
    container: ProjectYamlMappingSnapshot


@dataclass(frozen=True)
class _SideJudgementDiscoverySnapshot:
    root: Path
    candidates: tuple[_SideJudgementCandidate, ...]
    containers: tuple[ProjectYamlMappingSnapshot, ...]
    files: tuple[ProjectFileSnapshot, ...]
    uncaptured_paths: tuple[str, ...]
    container_paths: tuple[Path, ...]

    def is_current(self) -> bool:
        try:
            current_paths = tuple(path.absolute() for path, _owner, _is_list in _side_container_specs(self.root))
            return (
                current_paths == self.container_paths
                and all(snapshot.is_current() for snapshot in self.files)
                and all(
                    snapshot_project_file(self.root, relative) is None
                    for relative in self.uncaptured_paths
                )
            )
        except (OSError, ValueError):
            return False


def _side_container_specs(root: Path) -> Iterable[tuple[Path, str, bool]]:
    for path in sorted((root / "kb" / "programs").glob("*/workflow/decisions.yaml")):
        yield path, "research-orchestrator", True
    for path in sorted((root / "kb" / "units" / "ideas").glob("*/discussion-judgements.yaml")):
        yield path, "idea-workbench", True
    for path in sorted((root / "kb" / "programs").glob("*/design/*-repo-choice.yaml")):
        yield path, "method-designer", False
    for path in sorted((root / "kb" / "synthesis").glob("*/*.yaml")):
        if not path.name.endswith("-fill.yaml"):
            yield path, "literature-synthesizer", False


def _side_judgement_candidates(
    root: Path,
) -> list[_SideJudgementCandidate]:
    return list(_capture_side_judgement_discovery(root).candidates)


def _capture_side_judgement_discovery(
    root: Path,
) -> _SideJudgementDiscoverySnapshot:
    candidates: list[_SideJudgementCandidate] = []
    containers: list[ProjectYamlMappingSnapshot] = []
    files: list[ProjectFileSnapshot] = []
    uncaptured_paths: list[str] = []
    specs = list(_side_container_specs(root))
    for path, owner, is_list in specs:
        try:
            relative = path.absolute().relative_to(root).as_posix()
        except ValueError:
            continue
        file_snapshot = snapshot_project_file(root, relative)
        if file_snapshot is None:
            uncaptured_paths.append(relative)
            continue
        files.append(file_snapshot)
        try:
            payload = load_yaml_mapping_bytes_strict(file_snapshot.raw_bytes)
        except (RuntimeError, StrictYamlError):
            continue
        container = ProjectYamlMappingSnapshot(file=file_snapshot, payload=payload)
        containers.append(container)
        if is_list:
            items = payload.get("items")
            if not isinstance(items, list):
                continue
            records = [item for item in items if isinstance(item, dict)]
        else:
            records = [payload]
        candidates.extend(
            _SideJudgementCandidate(record=record, owner=owner, container=container)
            for record in records
        )
    return _SideJudgementDiscoverySnapshot(
        root=root,
        candidates=tuple(candidates),
        containers=tuple(containers),
        files=tuple(files),
        uncaptured_paths=tuple(uncaptured_paths),
        container_paths=tuple(path.absolute() for path, _owner, _is_list in specs),
    )


def _candidate_artifacts(
    root: Path,
) -> Iterable[BoundJudgementSnapshot]:
    for snapshot in iter_canonical_record_snapshots(root):
        record = normalize_record_snapshot(snapshot, root)
        if record is None:
            continue
        try:
            yield _bound_unit_from_snapshot(
                root,
                snapshot,
                check_current=False,
            )
        except ValueError:
            continue

    side_candidates = _side_judgement_candidates(root)
    valid_candidates = [
        candidate
        for candidate in side_candidates
        if _text(candidate.record.get("kind")) in SIDE_OWNER_BY_KIND
        and not _identity_violations(root, candidate.record, candidate.owner, candidate.container.path)
    ]
    subject_counts: dict[tuple[str, str], int] = {}
    for candidate in valid_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        subject_counts[key] = subject_counts.get(key, 0) + 1
    for candidate in valid_candidates:
        kind = _text(candidate.record.get("kind"))
        subject_id = _text(candidate.record.get("id"))
        if subject_counts.get((kind, subject_id)) != 1:
            continue
        try:
            yield _bound_side_from_candidate(
                root,
                candidate,
                check_current=False,
            )
        except ValueError:
            continue


def discover_pending_judgements(root: str | Path) -> list[dict[str, Any]]:
    """Return all cross-owner ``ready_for_review`` cards in deterministic order."""
    project_root = _canonical_project_root(root)
    unit_candidates: list[dict[str, Any]] = []
    for snapshot in iter_canonical_record_snapshots(project_root):
        try:
            bound = _bound_unit_from_snapshot(project_root, snapshot, check_current=False)
        except ValueError:
            continue
        card = pending_judgement_card(
            project_root,
            bound.record,
            owner=bound.owner,
            artifact_path=bound.path,
            record_snapshot=bound.unit_record_snapshot,
            bound_snapshot=bound,
        )
        if card is not None:
            unit_candidates.append(card)
    side_discovery = _capture_side_judgement_discovery(project_root)
    valid_side_candidates = [
        candidate
        for candidate in side_discovery.candidates
        if _text(candidate.record.get("kind")) in SIDE_OWNER_BY_KIND
        and not _identity_violations(
            project_root,
            candidate.record,
            candidate.owner,
            candidate.container.path,
        )
    ]
    subject_counts: dict[tuple[str, str], int] = {}
    for candidate in valid_side_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        subject_counts[key] = subject_counts.get(key, 0) + 1
    side_cards: list[dict[str, Any]] = []
    for candidate in valid_side_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        if subject_counts.get(key) != 1:
            continue
        try:
            bound = _bound_side_from_candidate(
                project_root,
                candidate,
                check_current=False,
                validate_current=lambda: True,
            )
        except ValueError:
            continue
        card = pending_judgement_card(
            project_root,
            bound.record,
            owner=bound.owner,
            artifact_path=bound.path,
            bound_snapshot=bound,
        )
        if card is not None:
            side_cards.append(card)
    if not side_discovery.is_current():
        side_cards = []
    candidates = [*unit_candidates, *side_cards]
    priority = {"critical": 4, "high": 3, "normal": 2, "low": 1}
    return sorted(
        candidates,
        key=lambda card: (
            -priority.get(_text(card.get("priority")).casefold(), 2),
            _text(card.get("updated_at")),
            _text(card.get("subject", {}).get("id")),
        ),
    )


def confirmation_binding(record: dict[str, Any], *, owner: str = "", path: str = "") -> dict[str, Any]:
    """Build the event binding for a verified or confirmed judgement subject."""
    verification = record.get("payload", {}).get("verification", {})
    verification = verification if isinstance(verification, dict) else {}
    subject = {"kind": _text(record.get("kind")), "id": _text(record.get("id"))}
    if owner:
        subject["owner"] = owner
    if path:
        subject["path"] = path
    return {
        "subject": subject,
        "claim_ids": confirmation_claim_ids(record),
        "content_digest": confirmation_content_digest(record),
        "verification": {
            key: _text(verification.get(key))
            for key in ("verified_at", "claims_digest", "evidence_digest")
        },
    }


def apply_judgement_rejection(
    record: dict[str, Any],
    *,
    reason: str = "",
    rejected_at: str = "",
) -> None:
    """Reject one pending, substantive judgement without fabricating a receipt."""
    if _text(record.get("confirmation_status")) != "pending_user_confirmation":
        raise ValueError("only a pending judgement can be rejected")
    claims = confirmation_claims(record)
    if not claims:
        raise ValueError("a judgement without canonical claims cannot be rejected")
    for claim in claims:
        claim["confirmation_status"] = "rejected"
    record["confirmation_status"] = "rejected"
    # Rejection is terminal for the inbox but does not erase that this remains
    # judgement-class material governed by a human gate.
    record["needs_human_confirmation"] = True
    record.pop("confirmation", None)
    record["rejection"] = {
        "at": rejected_at or utc_now_iso(),
        "reason": _text(reason),
    }


def judgement_snapshot_binding(
    record: dict[str, Any],
    *,
    owner: str = "",
    path: str = "",
    bound_snapshot: BoundJudgementSnapshot | None = None,
) -> dict[str, Any]:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    verification = payload.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    content_digest = (
        survey_content_digest(record)
        if _text(record.get("kind")) == "survey_judgement"
        else confirmation_content_digest(record)
    )
    binding = {
        "subject": {
            "kind": _text(record.get("kind")),
            "id": _text(record.get("id")),
            "owner": _text(owner),
            "path": _text(path),
        },
        "confirmation_status": _text(record.get("confirmation_status")),
        "content_digest": content_digest,
        "verification": {
            key: _text(verification.get(key))
            for key in ("verified_at", "claims_digest", "evidence_digest")
        },
    }
    if bound_snapshot is not None:
        if bound_snapshot.record != record:
            raise ValueError("judgement does not match its bound source snapshot")
        if bound_snapshot.unit_record_snapshot is not None:
            raw_bytes = bound_snapshot.unit_record_snapshot.raw_bytes
        elif bound_snapshot.project_yaml_snapshot is not None:
            raw_bytes = bound_snapshot.project_yaml_snapshot.raw_bytes
        else:
            raise ValueError("judgement bound source snapshot is incomplete")
        binding["source_digest"] = hashlib.sha256(raw_bytes).hexdigest()
    return binding


def require_judgement_snapshot(
    record: dict[str, Any],
    *,
    expected_snapshot: str | dict[str, Any],
    owner: str,
    path: str,
    root: str | Path | None = None,
) -> None:
    if isinstance(expected_snapshot, str):
        try:
            expected = json.loads(expected_snapshot)
        except json.JSONDecodeError as exc:
            raise ValueError("review snapshot binding is not valid JSON") from exc
    else:
        expected = expected_snapshot
    if not isinstance(expected, dict):
        raise ValueError("review snapshot binding is incomplete")
    subject = expected.get("subject")
    verification = expected.get("verification")
    expected_subject_kind = _text(subject.get("kind")) if isinstance(subject, dict) else ""
    source_digest_required = root is not None and expected_subject_kind in SIDE_OWNER_BY_KIND
    judgement_claim_present = any(
        _text(claim.get("claim_type")) in JUDGEMENT_CLAIM_TYPES
        for claim in confirmation_claims(record)
    )
    if (
        not isinstance(subject, dict)
        or not isinstance(verification, dict)
        or _text(expected.get("confirmation_status")) != "pending_user_confirmation"
        or not _text(expected.get("content_digest"))
        or (source_digest_required and not _text(expected.get("source_digest")))
        or (
            judgement_claim_present
            and any(not _text(verification.get(key)) for key in ("verified_at", "claims_digest", "evidence_digest"))
        )
    ):
        raise ValueError("review snapshot binding is incomplete")
    if root is not None and judgement_claim_present:
        project_root = Path(root).resolve()
        artifact_path = (project_root / path).resolve()
        identity_owner = UNIT_OWNER_BY_KIND.get(_text(record.get("kind")), owner)
        if _identity_violations(project_root, record, identity_owner, artifact_path):
            raise ValueError("review subject no longer has its canonical owner or path identity")
        subject_kind = _text(record.get("kind"))
        subject_id = _text(record.get("id"))
        matches = [
            card
            for card in discover_pending_judgements(project_root)
            if _text(card.get("subject", {}).get("kind")) == subject_kind
            and _text(card.get("subject", {}).get("id")) == subject_id
        ]
        if len(matches) != 1:
            raise ValueError("review subject is no longer uniquely ready under its canonical owner")
        if source_digest_required or "source_digest" in expected:
            current_binding = matches[0].get("snapshot_binding")
            current_binding = dict(current_binding) if isinstance(current_binding, dict) else {}
            if current_binding != expected:
                raise ValueError("review snapshot is stale; show the current judgement before applying a decision")
    record_binding = judgement_snapshot_binding(record, owner=owner, path=path)
    expected_record_binding = dict(expected)
    expected_record_binding.pop("source_digest", None)
    if record_binding != expected_record_binding:
        raise ValueError("review snapshot is stale; show the current judgement before applying a decision")


def _bound_unit_from_snapshot(
    project_root: Path,
    snapshot: CanonicalRecordSnapshot,
    *,
    subject: dict[str, Any] | None = None,
    check_current: bool,
) -> BoundJudgementSnapshot:
    subject_kind = snapshot.kind
    subject_id = snapshot.unit_id
    record = normalize_record_snapshot(snapshot, project_root)
    if record is None:
        raise ValueError(f"bound judgement is not a valid canonical record: {subject_kind}:{subject_id}")
    owner = UNIT_OWNER_BY_KIND[subject_kind]
    relative_path = snapshot.path.relative_to(project_root).as_posix()
    supplied_owner = _text(subject.get("owner")) if subject is not None else ""
    supplied_path = _text(subject.get("path")) if subject is not None else ""
    if supplied_owner and supplied_owner != owner:
        raise ValueError("confirmation subject owner does not match canonical owner")
    if supplied_path and supplied_path != relative_path:
        raise ValueError("confirmation subject path does not match canonical record")
    if _identity_violations(project_root, record, owner, snapshot.path):
        raise ValueError(f"bound judgement has invalid canonical identity: {subject_kind}:{subject_id}")

    def validate_unique_current() -> bool:
        current = require_current_record_snapshot(project_root, snapshot)
        current_record = normalize_record_snapshot(current, project_root)
        return current_record is not None and current_record == record

    bound = BoundJudgementSnapshot(
        record=record,
        path=snapshot.path,
        owner=owner,
        unit_record_snapshot=snapshot,
        validate_unique_current=validate_unique_current,
    )
    if check_current and not bound.is_current():
        raise ValueError("bound judgement changed while it was being captured")
    return bound


def _bound_side_from_candidate(
    project_root: Path,
    selected: _SideJudgementCandidate,
    *,
    subject: dict[str, Any] | None = None,
    check_current: bool,
    validate_current: Callable[[], bool] | None = None,
) -> BoundJudgementSnapshot:
    record = selected.record
    subject_kind = _text(record.get("kind"))
    subject_id = _text(record.get("id"))
    owner = SIDE_OWNER_BY_KIND[subject_kind]
    container = selected.container
    relative_path = container.path.relative_to(project_root).as_posix()
    supplied_owner = _text(subject.get("owner")) if subject is not None else ""
    supplied_path = _text(subject.get("path")) if subject is not None else ""
    if supplied_owner and supplied_owner != owner:
        raise ValueError("confirmation subject owner does not match canonical owner")
    if supplied_path and supplied_path != relative_path:
        raise ValueError("confirmation subject path does not match canonical container")
    if _identity_violations(project_root, record, owner, container.path):
        raise ValueError(f"bound judgement has invalid canonical identity: {subject_kind}:{subject_id}")

    def validate_side_unique_current() -> bool:
        current_matches = [
            candidate
            for candidate in _side_judgement_candidates(project_root)
            if _text(candidate.record.get("kind")) == subject_kind
            and _text(candidate.record.get("id")) == subject_id
            and not _identity_violations(
                project_root,
                candidate.record,
                candidate.owner,
                candidate.container.path,
            )
        ]
        if len(current_matches) != 1:
            return False
        current = current_matches[0]
        expected_file = container.file
        current_file = current.container.file
        return (
            current.record == record
            and current.owner == owner
            and current_file.path == expected_file.path
            and current_file.raw_bytes == expected_file.raw_bytes
            and current_file.file_identity == expected_file.file_identity
            and current_file.directory_capabilities == expected_file.directory_capabilities
            and current.container.is_current()
        )

    bound = BoundJudgementSnapshot(
        record=record,
        path=container.path,
        owner=owner,
        project_yaml_snapshot=container,
        validate_unique_current=validate_current or validate_side_unique_current,
    )
    if check_current and not bound.is_current():
        raise ValueError("bound judgement changed while it was being captured")
    return bound


def load_bound_judgement_container_snapshot(
    root: str | Path,
    relative_path: str | Path,
    *,
    owner: str,
    expected_kind: str,
) -> BoundJudgementContainerSnapshot:
    """Capture one canonical side container and index its globally unique items."""
    project_root = _canonical_project_root(root)
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("side judgement container path is not canonical")
    target_path = project_root / relative
    matching_specs = [
        spec
        for spec in _side_container_specs(project_root)
        if spec[0].absolute() == target_path.absolute() and spec[1] == owner
    ]
    if len(matching_specs) != 1 or SIDE_OWNER_BY_KIND.get(expected_kind) != owner:
        raise ValueError("side judgement container is not canonical for its owner")
    discovery = _capture_side_judgement_discovery(project_root)
    target_containers = [
        container for container in discovery.containers if container.path == target_path.absolute()
    ]
    if len(target_containers) != 1:
        raise ValueError("side judgement container is not a strict YAML mapping")
    valid_candidates = [
        candidate
        for candidate in discovery.candidates
        if _text(candidate.record.get("kind")) in SIDE_OWNER_BY_KIND
        and not _identity_violations(
            project_root,
            candidate.record,
            candidate.owner,
            candidate.container.path,
        )
    ]
    subject_counts: dict[tuple[str, str], int] = {}
    for candidate in valid_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        subject_counts[key] = subject_counts.get(key, 0) + 1
    bound_items: list[BoundJudgementSnapshot] = []
    for candidate in valid_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        if (
            candidate.container.path != target_path.absolute()
            or key[0] != expected_kind
            or subject_counts.get(key) != 1
        ):
            continue
        bound_items.append(
            _bound_side_from_candidate(
                project_root,
                candidate,
                check_current=False,
                validate_current=discovery.is_current,
            )
        )
    return BoundJudgementContainerSnapshot(
        container=target_containers[0],
        judgements=tuple(bound_items),
        validate_current=discovery.is_current,
    )


def load_bound_judgement_snapshot(root: str | Path, subject: Any) -> BoundJudgementSnapshot:
    """Bind one judgement to its exact, globally unique canonical container."""
    project_root = _canonical_project_root(root)
    if not isinstance(subject, dict):
        raise ValueError("confirmation subject must be a mapping")
    subject_id = _text(subject.get("id"))
    subject_kind = _text(subject.get("kind"))
    if subject_kind not in UNIT_OWNER_BY_KIND and subject_kind not in SIDE_OWNER_BY_KIND:
        raise ValueError(f"snapshot-bearing judgement kind is not supported: {subject_kind or '<empty>'}")
    if subject_kind in SIDE_OWNER_BY_KIND:
        matches = [
            candidate
            for candidate in _side_judgement_candidates(project_root)
            if _text(candidate.record.get("kind")) == subject_kind
            and _text(candidate.record.get("id")) == subject_id
            and not _identity_violations(
                project_root,
                candidate.record,
                candidate.owner,
                candidate.container.path,
            )
        ]
        if len(matches) != 1:
            raise ValueError(f"bound judgement is not globally unique: {subject_kind}:{subject_id}")
        return _bound_side_from_candidate(
            project_root,
            matches[0],
            subject=subject,
            check_current=True,
        )

    snapshot = canonical_record_snapshot_for_identity(project_root, subject_kind, subject_id)
    if snapshot is None:  # pragma: no cover - allow_absent is false
        raise ValueError(f"bound judgement not found: {subject_kind}:{subject_id}")
    return _bound_unit_from_snapshot(
        project_root,
        snapshot,
        subject=subject,
        check_current=True,
    )


def load_bound_judgement_batch_snapshot(
    root: str | Path,
    subjects: Iterable[Any] = (),
) -> BoundJudgementBatchSnapshot:
    """Capture side containers once and index all globally unique subjects.

    Side candidates share their exact container validator while the aggregate
    validator rechecks the complete discovery capture once. Requested unit
    subjects retain their own canonical record validators.
    """
    project_root = _canonical_project_root(root)
    side_discovery = _capture_side_judgement_discovery(project_root)
    valid_side_candidates = [
        candidate
        for candidate in side_discovery.candidates
        if _text(candidate.record.get("kind")) in SIDE_OWNER_BY_KIND
        and not _identity_violations(
            project_root,
            candidate.record,
            candidate.owner,
            candidate.container.path,
        )
    ]
    subject_counts: dict[tuple[str, str], int] = {}
    for candidate in valid_side_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        subject_counts[key] = subject_counts.get(key, 0) + 1
    side_bounds: list[BoundJudgementSnapshot] = []
    for candidate in valid_side_candidates:
        key = (_text(candidate.record.get("kind")), _text(candidate.record.get("id")))
        if subject_counts.get(key) != 1:
            continue
        try:
            side_bounds.append(
                _bound_side_from_candidate(
                    project_root,
                    candidate,
                    check_current=False,
                    validate_current=candidate.container.is_current,
                )
            )
        except ValueError:
            continue

    requested_units: dict[tuple[str, str], dict[str, Any]] = {}
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        subject_kind = _text(subject.get("kind"))
        subject_id = _text(subject.get("id"))
        if subject_kind in UNIT_OWNER_BY_KIND and subject_id:
            requested_units[(subject_kind, subject_id)] = subject
    unit_bounds: list[BoundJudgementSnapshot] = []
    for (subject_kind, subject_id), subject in sorted(requested_units.items()):
        try:
            snapshot = canonical_record_snapshot_for_identity(
                project_root,
                subject_kind,
                subject_id,
            )
            if snapshot is None:
                continue
            unit_bounds.append(
                _bound_unit_from_snapshot(
                    project_root,
                    snapshot,
                    subject=subject,
                    check_current=True,
                )
            )
        except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
            continue
    all_bounds = tuple([*side_bounds, *unit_bounds])
    subject_index: dict[tuple[str, str], BoundJudgementSnapshot | None] = {
        key: None
        for key, count in subject_counts.items()
        if count != 1
    }
    for bound in all_bounds:
        key = (_text(bound.record.get("kind")), _text(bound.record.get("id")))
        subject_index[key] = bound if key not in subject_index else None
    return BoundJudgementBatchSnapshot(
        root=project_root,
        judgements=all_bounds,
        side_containers=side_discovery.containers,
        unit_judgements=tuple(unit_bounds),
        validate_side_current=side_discovery.is_current,
        subject_index=subject_index,
    )


def load_bound_judgement(root: str | Path, subject: Any) -> tuple[dict[str, Any], Path]:
    """Resolve a report binding without trusting an escaping path from the event."""
    if isinstance(subject, dict) and (
        _text(subject.get("kind")) in UNIT_OWNER_BY_KIND
        or _text(subject.get("kind")) in SIDE_OWNER_BY_KIND
    ):
        bound = load_bound_judgement_snapshot(root, subject)
        return bound.record, bound.path
    project_root = Path(root).resolve()
    if not isinstance(subject, dict):
        raise ValueError("confirmation subject must be a mapping")
    subject_id = _text(subject.get("id"))
    subject_kind = _text(subject.get("kind"))
    relative = _text(subject.get("path"))
    candidates: list[Path] = []
    if relative:
        candidate = project_root / relative
        candidates.append(
            trusted_project_path(
                project_root,
                candidate,
                allowed_root=project_root / "kb",
                require="file",
            )
        )
    unit = _unit_path(project_root, subject_id)
    if unit is not None:
        candidates.append(unit)
    if subject_kind == "program_decision":
        candidates.extend((project_root / "kb" / "programs").glob("*/workflow/decisions.yaml"))
    if subject_kind == "idea_discussion_conclusion":
        candidates.extend((project_root / "kb" / "units" / "ideas").glob("*/discussion-judgements.yaml"))
    if subject_kind == "survey_judgement":
        candidates.extend((project_root / "kb" / "synthesis").glob("*/*.yaml"))
    for path in candidates:
        try:
            safe_path = trusted_project_path(
                project_root,
                path,
                allowed_root=project_root / "kb",
                require="file",
            )
        except ValueError:
            continue
        payload = load_yaml(safe_path, default={})
        records = payload.get("items") if isinstance(payload, dict) and isinstance(payload.get("items"), list) else [payload]
        for record in records:
            if not isinstance(record, dict):
                continue
            if _text(record.get("id")) == subject_id and _text(record.get("kind")) == subject_kind:
                owner = _text(subject.get("owner")) or UNIT_OWNER_BY_KIND.get(subject_kind) or _text(record.get("owner"))
                if _identity_violations(project_root, record, owner, safe_path):
                    continue
                return record, safe_path
    raise ValueError(f"bound judgement not found: {subject_kind}:{subject_id}")


__all__ = [
    "BoundJudgementBatchSnapshot",
    "BoundJudgementContainerSnapshot",
    "BoundJudgementSnapshot",
    "apply_judgement_rejection",
    "confirmation_binding",
    "discover_pending_judgements",
    "judgement_snapshot_binding",
    "judgement_confirmation_is_current",
    "judgement_confirmation_matches_bound",
    "load_bound_judgement",
    "load_bound_judgement_batch_snapshot",
    "load_bound_judgement_container_snapshot",
    "load_bound_judgement_snapshot",
    "pending_judgement_card",
    "require_judgement_snapshot",
    "readiness_violations",
]

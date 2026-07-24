"""Task-scoped preference eligibility and Agent-authored effective selections.

This module never decides which soft preferences matter to a task.  It exposes
only an allowlisted eligible view and validates the Agent's selected subset.
Receipts keep identifiers and digests rather than copying preference values or
task text.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import load_yaml, utc_now_iso, write_yaml_if_changed
from .journal import mutation_transaction
from .paths import config_root, runtime_preferences_path
from .prefs import load_runtime_preferences


SELECTION_SCHEMA = "effective-preference-selection/v1"
SELECTION_ID_RE = re.compile(r"prefsel-[a-z0-9][a-z0-9-]{5,80}")
HEX_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
MAX_AGENT_EXPLANATION = 240
MAX_BINDING_FILE_BYTES = 64 * 1024 * 1024
MAX_BINDING_TREE_BYTES = 512 * 1024 * 1024
MAX_BINDING_TREE_ENTRIES = 20_000
MAX_BINDING_TREE_DEPTH = 64
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s'\"(])(?:/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._~ -]+)+|[A-Za-z]:[\\/])")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|token|credential|authorization|password|passwd|secret|private[_-]?key)"
    r"\s*[:=]\s*(?:bearer\s+)?\S+"
)
_OPAQUE_SECRET_RE = re.compile(r"(?=[A-Za-z0-9_+/=-]{32,})(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_+/=-]{32,}")


# This table is a disclosure allowlist, not a relevance model.  Runtime Agents
# select the task-relevant subset and explain that choice in a receipt.
SKILL_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "knowledge-base-manager": (),
    "research-config-manager": (),
    "source-intake": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.constraints",
        "runtime.paper",
        "runtime.pdf",
        "learned.*",
    ),
    "research-orchestrator": (
        "profile.personalization.research_focus",
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    "literature-search": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.constraints",
        "learned.*",
    ),
    "literature-synthesizer": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.reporting_style",
        "profile.personalization.term_style",
        "profile.constraints",
        "learned.*",
    ),
    "report-author": (
        "profile.preferences.language_preference",
        "profile.personalization.reporting_style",
        "profile.personalization.term_style",
        "profile.personalization.collaboration_boundaries",
        "learned.*",
    ),
    "method-designer": (
        "profile.personalization.research_focus",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    "experiment-workbench": (
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    "idea-workbench": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    "discussion-archivist": (),
    "kb-cli": (
        "profile.preferences.language_preference",
        "profile.personalization.reporting_style",
        "learned.*",
    ),
    "paper-analyst": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "runtime.paper",
        "runtime.pdf",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    "repo-analyst": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "learned.*",
    ),
    "dataset-analyst": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "learned.*",
    ),
    "blog-analyst": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "learned.*",
    ),
    "research-monitor": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    "research-navigator": (),
    "wiki-adapter": (),
    "skill-evolution-advisor": (),
}


# Preference-neutral shipping skills are an explicit product decision, not an
# implicit absence of implementation.  Reasons must describe the shipped owner
# boundary and must never be used to bypass hard governance enforced elsewhere.
SKILL_NEUTRALITY: dict[str, str] = {
    "knowledge-base-manager": "Mechanical schema, lifecycle, indexing, and governance owner.",
    "research-config-manager": "Canonical preference fact owner; it does not consume its own soft profile.",
    "discussion-archivist": "Transports caller-authored discussion content without rewriting its meaning.",
    "research-navigator": "Development-only derived projection with no canonical research judgement.",
    "wiki-adapter": "Thin router that delegates semantic work to the selected canonical owner.",
    "skill-evolution-advisor": "Governance and redacted diagnostics owner, not a soft research consumer.",
}


# Consumer operations are an enforcement boundary, rather than descriptive
# metadata.  This table lists only operations with an execution consumer that
# recomputes canonical task context and resolves the receipt.  Deterministic
# operations which do not vary with preferences are intentionally absent; do
# not add aspirational entries merely because a skill has an allowlist above.
SKILL_OPERATIONS: dict[str, tuple[str, ...]] = {
    "source-intake": ("add",),
    "research-orchestrator": ("plan",),
    "literature-search": ("search",),
    "literature-synthesizer": ("synthesize",),
    "report-author": ("weekly", "ppt-materials", "stage-summary", "writing-materials", "outline"),
    "method-designer": ("design",),
    "experiment-workbench": ("plan", "log-run", "follow-up", "diagnose"),
    "kb-cli": ("review-display",),
    "paper-analyst": ("prewarm-cache", "screen", "complete-note", "extract-figures", "refresh-structure"),
    "repo-analyst": ("map-capability",),
    "dataset-analyst": ("profile",),
    "blog-analyst": ("complete-note",),
    "idea-workbench": ("generate", "analyze", "review", "discuss"),
    "research-monitor": ("create-subscription",),
}


# Narrow an operation where the owner script has a smaller real consumer than
# the skill-wide disclosure catalog.  Unlisted pairs retain the skill allowlist
# for runtime-Agent consumers, but still require a declared operation above.
OPERATION_ELIGIBILITY: dict[tuple[str, str], tuple[str, ...]] = {
    ("source-intake", "add"): ("profile.constraints", "runtime.paper", "runtime.pdf", "learned.*"),
    **{
        ("report-author", operation): (
            "profile.preferences.language_preference",
            "profile.personalization.reporting_style",
            "learned.*",
        )
        for operation in SKILL_OPERATIONS["report-author"]
    },
    ("literature-search", "search"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.constraints",
        "learned.*",
    ),
    ("literature-synthesizer", "synthesize"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.reporting_style",
        "profile.personalization.term_style",
        "profile.constraints",
        "learned.*",
    ),
    ("method-designer", "design"): (
        "profile.personalization.research_focus",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    ("experiment-workbench", "plan"): (
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    ("experiment-workbench", "log-run"): (
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    ("experiment-workbench", "follow-up"): (
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    ("experiment-workbench", "diagnose"): (
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    ("kb-cli", "review-display"): (
        "profile.personalization.reporting_style",
        "learned.*",
    ),
    ("paper-analyst", "prewarm-cache"): ("runtime.paper", "learned.*"),
    ("paper-analyst", "screen"): (
        "runtime.paper",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    ("paper-analyst", "complete-note"): (
        "runtime.paper",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
    ("paper-analyst", "extract-figures"): ("runtime.pdf", "learned.*"),
    ("paper-analyst", "refresh-structure"): ("learned.*",),
    ("repo-analyst", "map-capability"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "learned.*",
    ),
    ("dataset-analyst", "profile"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "learned.*",
    ),
    ("blog-analyst", "complete-note"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "learned.*",
    ),
    ("idea-workbench", "generate"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    ("idea-workbench", "analyze"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    ("idea-workbench", "review"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    ("idea-workbench", "discuss"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.term_style",
        "profile.resources",
        "profile.constraints",
        "learned.*",
    ),
    ("research-monitor", "create-subscription"): (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
        "learned.*",
    ),
}


# Exact canonical-input fields for task-scoped consumers whose receipts are
# recomputed from analyzer-owned artifacts.  The flat shape is deliberate: it
# makes omissions and accidental new inputs fail closed, and gives the mutation
# matrix a complete registry rather than a hand-maintained list of examples.
OPERATION_CANONICAL_INPUTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("source-intake", "add"): (
        "kind",
        "source",
        "title",
        "maturity",
        "stage_id",
        "candidate_id",
        "canonical_pools",
        "source_content_digest",
        "source_input_digest",
        "candidate_binding_digest",
        "prepared_record_digest",
        "authorization_digest",
    ),
    ("research-orchestrator", "plan"): (
        "candidate_snapshot_digest",
        "scope",
        "candidate_action_ids",
    ),
    ("literature-search", "search"): (
        "stage_id",
        "request_digest",
        "mode",
        "run_id",
        "scope_digest",
        "budget_digest",
        "review_protocol_digest",
        "reviewers_digest",
        "monitor_binding_digest",
    ),
    ("literature-synthesizer", "synthesize"): (
        "mode",
        "discovery_mode",
        "search_protocol_digest",
        "selection_digest",
        "as_of",
        "program_ids",
        "input_units_digest",
    ),
    **{
        ("report-author", operation): (
            "program_id",
            "operation",
            "stage",
            "limit",
            "presentation_contract",
            "input_snapshot",
        )
        for operation in SKILL_OPERATIONS["report-author"]
    },
    ("method-designer", "design"): (
        "preference_task_inputs",
        "preference_task_inputs_digest",
    ),
    ("experiment-workbench", "plan"): (
        "program_id",
        "title_digest",
        "idea_id",
        "goal_digest",
        "hypothesis_digest",
    ),
    ("experiment-workbench", "log-run"): (
        "experiment_id",
        "record_digest",
        "config_revision",
        "seed",
        "run_input_digest",
        "artifact_facts_digest",
        "prior_runs_digest",
        "proposed_run_id",
        "proposed_run_path",
        "run_allocator_directory_digest",
    ),
    ("experiment-workbench", "follow-up"): (
        "experiment_id",
        "record_digest",
        "follow_up_digest",
    ),
    ("experiment-workbench", "diagnose"): (
        "experiment_id",
        "record_digest",
        "diagnosis_input_digest",
    ),
    ("kb-cli", "review-display"): (
        "review_snapshot_digest",
        "displayed_count",
        "hard_display_cap",
    ),
    **{
        ("paper-analyst", operation): (
            "paper_id",
            "operation",
            "phase",
            "mode",
            "force",
            "defer_post_actions",
            "record_content_digest",
            "source_identity_digest",
            "parse_cache",
            "source_artifacts",
            "auxiliary_artifacts",
            "fill_input",
        )
        for operation in SKILL_OPERATIONS["paper-analyst"]
    },
    ("repo-analyst", "map-capability"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_content_digest",
        "phase_contract_digest",
        "immutable_orientation_digest",
        "structure_scan_identity_digest",
        "structure_scan_bytes_digest",
        "repo_source_tree_identity_digest",
        "repo_source_tree_bytes_digest",
    ),
    ("dataset-analyst", "profile"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_content_digest",
        "phase_contract_digest",
        "immutable_orientation_digest",
        "parse_cache_identity_digest",
        "parse_cache_bytes_digest",
        "source_artifacts_identity_digest",
        "source_artifacts_bytes_digest",
    ),
    ("blog-analyst", "complete-note"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_content_digest",
        "phase_contract_digest",
        "immutable_orientation_digest",
        "parse_cache_identity_digest",
        "parse_cache_bytes_digest",
        "source_artifacts_identity_digest",
        "source_artifacts_bytes_digest",
    ),
    ("idea-workbench", "generate"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "request_context_digest",
        "candidate_count",
        "bundle_id_digest",
        "pool_digest",
        "source_digest",
        "phase_contract_digest",
        "immutable_orientation_identity_digest",
        "immutable_orientation_bytes_digest",
        "evidence_corpus_identity_digest",
        "evidence_corpus_bytes_digest",
    ),
    ("idea-workbench", "analyze"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_identity_digest",
        "record_bytes_digest",
        "phase_contract_digest",
        "immutable_orientation_identity_digest",
        "immutable_orientation_bytes_digest",
        "evidence_corpus_identity_digest",
        "evidence_corpus_bytes_digest",
    ),
    ("idea-workbench", "review"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_identity_digest",
        "record_bytes_digest",
        "phase_contract_digest",
        "immutable_orientation_identity_digest",
        "immutable_orientation_bytes_digest",
        "evidence_corpus_identity_digest",
        "evidence_corpus_bytes_digest",
    ),
    ("idea-workbench", "discuss"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_identity_digest",
        "record_bytes_digest",
        "phase_contract_digest",
        "immutable_orientation_identity_digest",
        "immutable_orientation_bytes_digest",
        "evidence_corpus_identity_digest",
        "evidence_corpus_bytes_digest",
    ),
    ("research-monitor", "create-subscription"): (
        "canonical_id",
        "canonical_kind",
        "operation",
        "request_digest",
        "subscription_id",
        "target_digest",
        "cadence_digest",
        "scope_digest",
        "budget_digest",
        "program_ids_digest",
        "reference_bindings_identity_digest",
        "reference_bindings_bytes_digest",
        "operation_contract_digest",
    ),
}


def validate_preference_registry() -> None:
    """Fail closed when a shipping entry is neither a real consumer nor neutral."""
    known = set(SKILL_ELIGIBILITY)
    consumers = {skill for skill, operations in SKILL_OPERATIONS.items() if operations}
    neutral = set(SKILL_NEUTRALITY)
    if consumers | neutral != known or consumers & neutral:
        raise RuntimeError("preference registry must partition every known skill exactly once")
    if set(SKILL_OPERATIONS) != consumers:
        raise RuntimeError("preference consumers must declare at least one real operation")
    for skill in consumers:
        if not SKILL_ELIGIBILITY[skill]:
            raise RuntimeError(f"preference consumer has an empty eligible catalog: {skill}")
    for skill, reason in SKILL_NEUTRALITY.items():
        if SKILL_ELIGIBILITY[skill]:
            raise RuntimeError(f"preference-neutral skill has a nonempty catalog: {skill}")
        if not str(reason).strip():
            raise RuntimeError(f"preference-neutral skill lacks a product reason: {skill}")
    for pair, paths in OPERATION_ELIGIBILITY.items():
        skill, operation = pair
        if operation not in SKILL_OPERATIONS.get(skill, ()) or not paths:
            raise RuntimeError(f"operation preference registry contains a dead entry: {pair}")
    expected_operations = {
        (skill, operation)
        for skill, operations in SKILL_OPERATIONS.items()
        for operation in operations
    }
    if set(OPERATION_CANONICAL_INPUTS) != expected_operations:
        missing = sorted(expected_operations - set(OPERATION_CANONICAL_INPUTS))
        unexpected = sorted(set(OPERATION_CANONICAL_INPUTS) - expected_operations)
        raise RuntimeError(
            "canonical task-input registry must cover every consumer operation exactly; "
            f"missing={missing}; unexpected={unexpected}"
        )
    for pair, fields in OPERATION_CANONICAL_INPUTS.items():
        if not fields or len(fields) != len(set(fields)) or any(not str(field).strip() for field in fields):
            raise RuntimeError(f"canonical task-input registry is invalid: {pair}")


validate_preference_registry()


OPERATION_POLICIES: dict[tuple[str, str], dict[str, object]] = {
    pair: {
        "soft_missing": "neutral-default",
        "hard_fallback_paths": [
            path
            for path in OPERATION_ELIGIBILITY.get(pair, SKILL_ELIGIBILITY[pair[0]])
            if path in {
                "profile.resources",
                "profile.constraints",
                "runtime.autonomy.auto_execute_scope",
                "runtime.diagnostics",
            }
        ],
    }
    for skill, operations in SKILL_OPERATIONS.items()
    for pair in ((skill, operation) for operation in operations)
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def canonical_digest(value: object) -> str:
    """Public value-free digest helper for owner-supplied contracts."""
    return _digest(value)


def _trusted_relative(path: Path, trusted_root: Path) -> Path:
    lexical_root = trusted_root.absolute()
    lexical_path = path.absolute()
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("canonical source artifact escaped its trusted root") from exc
    if relative == Path() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("canonical source artifact has an unsafe relative identity")
    return relative


def _open_trusted_directory(
    trusted_root: Path,
    relative_parts: Sequence[str],
    *,
    allow_missing: bool = False,
) -> int | None:
    """Open a descendant directory through no-follow dirfds for every component."""
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        root_metadata = trusted_root.lstat()
        if trusted_root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
            raise ValueError("trusted artifact root is not a safe directory")
        descriptor = os.open(trusted_root, directory_flags)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise ValueError("trusted artifact root is missing")
    except OSError as exc:
        raise ValueError("trusted artifact root is unsafe") from exc
    try:
        for part in relative_parts:
            try:
                next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            except FileNotFoundError:
                if allow_missing:
                    os.close(descriptor)
                    return None
                raise ValueError("canonical source artifact ancestor is missing")
            except OSError as exc:
                raise ValueError("canonical source artifact ancestor is unsafe") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _hash_regular_file_at(
    parent_descriptor: int,
    name: str,
    *,
    max_bytes: int = MAX_BINDING_FILE_BYTES,
) -> tuple[str, os.stat_result, int]:
    """Stream-hash one exact no-follow leaf without retaining its contents."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("canonical source artifact is missing or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("canonical source artifact is not a regular file")
        if before.st_size > max_bytes:
            raise ValueError("canonical source artifact exceeds the binding byte budget")
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            byte_count += len(chunk)
            if byte_count > max_bytes:
                raise ValueError("canonical source artifact exceeds the binding byte budget")
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity_before = (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after:
            raise ValueError("canonical source artifact changed while it was read")
        if byte_count != after.st_size:
            raise ValueError("canonical source artifact changed while it was read")
        try:
            path_after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("canonical source artifact changed while it was read") from exc
        path_identity_after = (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_mode,
            path_after.st_size,
            path_after.st_mtime_ns,
        )
        if path_identity_after != identity_after or not stat.S_ISREG(path_after.st_mode):
            raise ValueError("canonical source artifact changed while it was read")
        return digest.hexdigest(), after, byte_count
    finally:
        os.close(descriptor)


def _hash_regular_file(
    path: Path,
    *,
    trusted_root: Path,
    max_bytes: int = MAX_BINDING_FILE_BYTES,
) -> tuple[str, os.stat_result, int]:
    relative = _trusted_relative(path, trusted_root)
    parent_descriptor = _open_trusted_directory(trusted_root, relative.parts[:-1])
    if parent_descriptor is None:  # pragma: no cover - non-optional call
        raise ValueError("canonical source artifact ancestor is missing")
    try:
        binding = _hash_regular_file_at(parent_descriptor, relative.name, max_bytes=max_bytes)
        reopened_parent = _open_trusted_directory(trusted_root, relative.parts[:-1])
        if reopened_parent is None:  # pragma: no cover - non-optional call
            raise ValueError("canonical source artifact ancestor changed while it was read")
        try:
            original_parent = os.fstat(parent_descriptor)
            current_parent = os.fstat(reopened_parent)
            if (original_parent.st_dev, original_parent.st_ino) != (
                current_parent.st_dev,
                current_parent.st_ino,
            ):
                raise ValueError("canonical source artifact ancestor changed while it was read")
        finally:
            os.close(reopened_parent)
        return binding
    finally:
        os.close(parent_descriptor)


def regular_file_binding(
    path: Path,
    *,
    logical_identity: str,
    trusted_root: Path,
) -> dict[str, str]:
    """Return exact, value-free identity/byte digests for a safe regular file."""
    bytes_digest, metadata, _ = _hash_regular_file(path, trusted_root=trusted_root)
    return {
        "identity_digest": _digest(
            {
                "logical_identity": str(logical_identity),
                "device": metadata.st_dev,
                "inode": metadata.st_ino,
                "mode": stat.S_IMODE(metadata.st_mode),
            }
        ),
        "bytes_digest": bytes_digest,
    }


def regular_tree_binding(
    path: Path,
    *,
    logical_identity: str,
    trusted_root: Path,
) -> dict[str, str]:
    """Bind every byte in an optional immutable source-artifact directory.

    Missing source directories are represented explicitly.  Existing trees are
    closed over regular files/directories only; any symlink or special file fails
    before a consumer can write business state.
    """
    relative = _trusted_relative(path, trusted_root)
    root_descriptor = _open_trusted_directory(
        trusted_root, relative.parts, allow_missing=True
    )
    if root_descriptor is None:
        missing = {"logical_identity": str(logical_identity), "state": "absent"}
        return {"identity_digest": _digest(missing), "bytes_digest": _digest([])}
    root_metadata = os.fstat(root_descriptor)
    if not stat.S_ISDIR(root_metadata.st_mode):  # pragma: no cover - O_DIRECTORY already enforces this
        os.close(root_descriptor)
        raise ValueError("canonical source artifact tree is not a safe directory")

    identities: list[dict[str, object]] = []
    contents: list[dict[str, str]] = []
    budget = {"entries": 0, "bytes": 0}

    def bounded_entries(directory_descriptor: int) -> list[os.DirEntry[str]]:
        remaining = MAX_BINDING_TREE_ENTRIES - budget["entries"]
        entries: list[os.DirEntry[str]] = []
        try:
            with os.scandir(directory_descriptor) as iterator:
                for entry in iterator:
                    entries.append(entry)
                    if len(entries) > remaining:
                        raise ValueError("canonical source artifact tree exceeds the entry budget")
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("canonical source artifact tree is unreadable") from exc
        return sorted(entries, key=lambda item: item.name)

    def visit(directory_descriptor: int, relative_path: Path) -> None:
        directory_before = os.fstat(directory_descriptor)
        for entry in bounded_entries(directory_descriptor):
            child_relative = relative_path / entry.name
            if len(child_relative.parts) > MAX_BINDING_TREE_DEPTH:
                raise ValueError("canonical source artifact tree exceeds the depth budget")
            budget["entries"] += 1
            if entry.is_symlink():
                raise ValueError("canonical source artifact tree contains a symlink")
            if entry.is_dir(follow_symlinks=False):
                directory_flags = (
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    child_descriptor = os.open(
                        entry.name, directory_flags, dir_fd=directory_descriptor
                    )
                except OSError as exc:
                    raise ValueError("canonical source artifact tree changed while it was read") from exc
                try:
                    metadata = os.fstat(child_descriptor)
                    identities.append(
                        {
                            "relative": child_relative.as_posix(),
                            "type": "directory",
                            "device": metadata.st_dev,
                            "inode": metadata.st_ino,
                            "mode": stat.S_IMODE(metadata.st_mode),
                        }
                    )
                    visit(child_descriptor, child_relative)
                finally:
                    os.close(child_descriptor)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise ValueError("canonical source artifact tree contains a non-regular entry")
            remaining_bytes = MAX_BINDING_TREE_BYTES - budget["bytes"]
            if remaining_bytes < 0:
                raise ValueError("canonical source artifact tree exceeds the total byte budget")
            file_limit = min(MAX_BINDING_FILE_BYTES, remaining_bytes)
            bytes_digest, metadata, byte_count = _hash_regular_file_at(
                directory_descriptor,
                entry.name,
                max_bytes=file_limit,
            )
            budget["bytes"] += byte_count
            identities.append(
                {
                    "relative": child_relative.as_posix(),
                    "type": "file",
                    "device": metadata.st_dev,
                    "inode": metadata.st_ino,
                    "mode": stat.S_IMODE(metadata.st_mode),
                }
            )
            contents.append(
                {
                    "relative": child_relative.as_posix(),
                    "sha256": bytes_digest,
                }
            )
        directory_after = os.fstat(directory_descriptor)
        directory_identity_before = (
            directory_before.st_dev,
            directory_before.st_ino,
            directory_before.st_mode,
            directory_before.st_size,
            directory_before.st_mtime_ns,
        )
        directory_identity_after = (
            directory_after.st_dev,
            directory_after.st_ino,
            directory_after.st_mode,
            directory_after.st_size,
            directory_after.st_mtime_ns,
        )
        if directory_identity_before != directory_identity_after:
            raise ValueError("canonical source artifact tree changed while it was read")
    try:
        visit(root_descriptor, Path())
        reopened_root = _open_trusted_directory(trusted_root, relative.parts)
        if reopened_root is None:  # pragma: no cover - existing tree
            raise ValueError("canonical source artifact tree path changed while it was read")
        try:
            current_root = os.fstat(reopened_root)
            if (root_metadata.st_dev, root_metadata.st_ino) != (
                current_root.st_dev,
                current_root.st_ino,
            ):
                raise ValueError("canonical source artifact tree path changed while it was read")
        finally:
            os.close(reopened_root)
    finally:
        os.close(root_descriptor)
    return {
        "identity_digest": _digest(
            {
                "logical_identity": str(logical_identity),
                "root_device": root_metadata.st_dev,
                "root_inode": root_metadata.st_ino,
                "entries": identities,
            }
        ),
        "bytes_digest": _digest(contents),
    }


def _consumer_pair(skill: str, operation: str) -> tuple[str, str]:
    normalized_skill = str(skill or "").strip().casefold()
    normalized_operation = str(operation or "").strip().casefold()
    if normalized_skill not in SKILL_ELIGIBILITY:
        raise ValueError(f"unknown preference consumer skill: {skill}")
    if not normalized_operation or normalized_operation not in SKILL_OPERATIONS.get(normalized_skill, ()):
        raise ValueError(
            f"unknown preference consumer operation: {normalized_skill}:{normalized_operation or '<missing>'}"
        )
    return normalized_skill, normalized_operation


def task_context_digest(*, skill: str, operation: str, canonical_inputs: Mapping[str, object]) -> str:
    """Digest owner-supplied canonical inputs for one declared consumer operation."""
    normalized_skill, normalized_operation = _consumer_pair(skill, operation)
    if not isinstance(canonical_inputs, Mapping):
        raise ValueError("canonical task inputs must be an object")
    registered = OPERATION_CANONICAL_INPUTS.get((normalized_skill, normalized_operation))
    if registered is not None and set(canonical_inputs) != set(registered):
        missing = sorted(set(registered) - set(canonical_inputs))
        unexpected = sorted(set(canonical_inputs) - set(registered))
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise ValueError("canonical task inputs do not match the operation registry: " + "; ".join(detail))
    return _digest(
        {
            "skill": normalized_skill,
            "operation": normalized_operation,
            "canonical_inputs": dict(canonical_inputs),
        }
    )


def operation_contract(*, skill: str, operation: str) -> dict[str, object]:
    normalized_skill, normalized_operation = _consumer_pair(skill, operation)
    patterns = OPERATION_ELIGIBILITY.get(
        (normalized_skill, normalized_operation), SKILL_ELIGIBILITY[normalized_skill]
    )
    return {
        "skill": normalized_skill,
        "operation": normalized_operation,
        "eligible_paths": list(patterns),
        **OPERATION_POLICIES[(normalized_skill, normalized_operation)],
    }


def _profile_path(project_root: Path) -> Path:
    return config_root(project_root) / "user-profile.yaml"


def _selection_root(project_root: Path) -> Path:
    return config_root(project_root) / "effective-preferences"


def _assert_safe_preference_ancestors(project_root: Path, target: Path) -> None:
    """Reject lexical escapes and every symlink below the workspace root."""
    lexical_root = project_root.absolute()
    lexical_target = target.absolute()
    try:
        relative = lexical_target.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("preference path escaped the workspace") from exc
    current = lexical_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("preference path contains a symlink")
        if current.exists() and current != lexical_target and not current.is_dir():
            raise ValueError("preference path ancestor is not a directory")
    try:
        lexical_target.resolve(strict=False).relative_to(lexical_root.resolve())
    except ValueError as exc:
        raise ValueError("preference path escaped the workspace") from exc


def _safe_existing_mapping(path: Path) -> dict[str, Any]:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("preference source is not a safe regular file")
    payload = load_yaml(path, default={})
    return dict(payload) if isinstance(payload, dict) else {}


def _nested_value(payload: Mapping[str, object], dotted: str) -> object:
    current: object = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _catalog_item(
    *,
    preference_id: str,
    path: str,
    value: object,
    strength: str,
    source_type: str,
) -> dict[str, object]:
    return {
        "preference_id": preference_id,
        "path": path,
        "value": value,
        "value_digest": _digest(value),
        "strength": strength,
        "source_type": source_type,
    }


def _preference_id(path: str) -> str:
    suffix = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    label = re.sub(r"[^a-z0-9]+", "-", path.casefold()).strip("-")[-36:]
    return f"pref-{label}-{suffix}"


def _base_catalog(project_root: Path) -> list[dict[str, object]]:
    config = config_root(project_root)
    runtime_path = runtime_preferences_path(project_root)
    _assert_safe_preference_ancestors(project_root, config)
    _assert_safe_preference_ancestors(project_root, _profile_path(project_root))
    _assert_safe_preference_ancestors(project_root, runtime_path)
    if config.is_symlink() or (config.exists() and not config.is_dir()):
        raise ValueError("preference config root is unsafe")
    if runtime_path.is_symlink() or (runtime_path.exists() and not runtime_path.is_file()):
        raise ValueError("runtime preference source is unsafe")
    profile = _safe_existing_mapping(_profile_path(project_root))
    runtime = load_runtime_preferences(project_root)
    entries: list[dict[str, object]] = []
    canonical_paths = {
        "profile.preferences.language_preference": "soft",
        "profile.personalization.research_focus": "soft",
        "profile.personalization.reporting_style": "soft",
        "profile.personalization.term_style": "soft",
        "profile.personalization.collaboration_boundaries": "soft",
        "profile.resources": "hard",
        "profile.constraints": "hard",
        "runtime.autonomy.auto_execute_scope": "hard",
        "runtime.paper": "soft",
        "runtime.pdf": "soft",
        "runtime.browser": "soft",
        "runtime.diagnostics": "hard",
    }
    roots: dict[str, Mapping[str, object]] = {"profile": profile, "runtime": runtime}
    for path, strength in canonical_paths.items():
        root_name, nested = path.split(".", 1)
        value = _nested_value(roots[root_name], nested)
        if value in (None, "", [], {}):
            continue
        entries.append(
            _catalog_item(
                preference_id=_preference_id(path),
                path=path,
                value=value,
                strength=strength,
                source_type="canonical-config",
            )
        )

    learned = runtime.get("learned_preferences", {})
    learned_items = learned.get("items", []) if isinstance(learned, Mapping) else []
    if isinstance(learned_items, list):
        for raw in learned_items:
            if not isinstance(raw, Mapping):
                continue
            raw_id = str(raw.get("id") or "").strip()
            text = str(raw.get("text") or "").strip()
            if not raw_id or not text:
                continue
            skill = str(raw.get("skill") or "").strip()
            operations = raw.get("operations")
            if isinstance(operations, str):
                operation_hints = [operations.strip().casefold()] if operations.strip() else []
            elif isinstance(operations, list):
                operation_hints = [str(value).strip().casefold() for value in operations if str(value).strip()]
            else:
                operation = str(raw.get("operation") or "").strip().casefold()
                operation_hints = [operation] if operation else []
            path = f"learned.{raw_id}"
            item = _catalog_item(
                preference_id=f"pref-learned-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]}",
                path=path,
                value=text,
                strength="soft",
                source_type="confirmed-learning",
            )
            item["skill_hint"] = skill
            item["operation_hints"] = operation_hints
            entries.append(item)
    return sorted(entries, key=lambda item: str(item["preference_id"]))


def _path_eligible(path: str, patterns: Sequence[str]) -> bool:
    return any(path == pattern or (pattern.endswith(".*") and path.startswith(pattern[:-1])) for pattern in patterns)


def eligible_preferences(project_root: Path, *, skill: str, operation: str = "") -> dict[str, object]:
    """Return the mechanically eligible preference view for an Agent task."""
    normalized_skill, normalized_operation = _consumer_pair(skill, operation)
    patterns = OPERATION_ELIGIBILITY.get(
        (normalized_skill, normalized_operation), SKILL_ELIGIBILITY[normalized_skill]
    )
    selected: list[dict[str, object]] = []
    for item in _base_catalog(project_root):
        path = str(item.get("path") or "")
        if not _path_eligible(path, patterns):
            continue
        skill_hint = str(item.get("skill_hint") or "").strip().casefold()
        if path.startswith("learned."):
            operation_hints = item.get("operation_hints")
            operation_hints = operation_hints if isinstance(operation_hints, list) else []
            # Learned preferences are intentionally dark unless both hints bind
            # them to this exact consumer.  Missing hints must never broadcast.
            if skill_hint != normalized_skill or normalized_operation not in operation_hints:
                continue
        selected.append(item)
    source_view = {
        "skill": normalized_skill,
        "operation": normalized_operation,
        "items": [
            {
                "preference_id": item["preference_id"],
                "path": item["path"],
                "value_digest": item["value_digest"],
                "strength": item["strength"],
                "source_type": item["source_type"],
            }
            for item in selected
        ],
    }
    return {
        **source_view,
        "catalog_digest": _digest(source_view),
        "consumer_contract": operation_contract(skill=normalized_skill, operation=normalized_operation),
        "items": selected,
    }


def _validated_selection_path(project_root: Path, selection_id: str, *, create_root: bool) -> Path:
    if SELECTION_ID_RE.fullmatch(selection_id) is None:
        raise ValueError("invalid effective preference selection id")
    root = _selection_root(project_root)
    config = config_root(project_root)
    _assert_safe_preference_ancestors(project_root, config)
    _assert_safe_preference_ancestors(project_root, root)
    if config.is_symlink() or (config.exists() and not config.is_dir()):
        raise ValueError("preference config root is unsafe")
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("effective preference root is unsafe")
    if create_root:
        root.mkdir(parents=True, exist_ok=True)
    path = root / f"{selection_id}.yaml"
    _assert_safe_preference_ancestors(project_root, path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("effective preference receipt path is unsafe")
    return path


def _normalize_agent_rows(raw: object, *, field: str) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list")
    rows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field} contains a malformed item")
        preference_id = str(item.get("preference_id") or "").strip()
        reason = str(item.get("reason") or "").strip()
        application = str(item.get("application") or "").strip()
        if not preference_id or not reason:
            raise ValueError(f"{field} requires preference_id and reason")
        _validate_receipt_explanation(reason, field=f"{field}.reason")
        row = {"preference_id": preference_id, "reason": reason}
        if field == "selected":
            if not application:
                raise ValueError("selected preferences require an application")
            _validate_receipt_explanation(application, field="selected.application")
            row["application"] = application
        rows.append(row)
    if len({row["preference_id"] for row in rows}) != len(rows):
        raise ValueError(f"{field} contains duplicate preference ids")
    return rows


def _validate_receipt_explanation(value: str, *, field: str) -> None:
    if len(value) > MAX_AGENT_EXPLANATION or "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be a short single-line explanation")
    if (
        _ABSOLUTE_PATH_RE.search(value)
        or _SECRET_ASSIGNMENT_RE.search(value)
        or _OPAQUE_SECRET_RE.search(value)
        or "://" in value
    ):
        raise ValueError(f"{field} contains private or path-like material")


def validate_effective_selection(
    project_root: Path,
    payload: Mapping[str, object],
    *,
    require_current_catalog: bool = True,
) -> dict[str, object]:
    selection_id = str(payload.get("selection_id") or "").strip()
    if SELECTION_ID_RE.fullmatch(selection_id) is None:
        raise ValueError("invalid effective preference selection id")
    skill = str(payload.get("skill") or "").strip().casefold()
    operation = str(payload.get("operation") or "").strip().casefold()
    eligible = eligible_preferences(project_root, skill=skill, operation=operation)
    catalog_digest = str(payload.get("catalog_digest") or "").strip()
    if require_current_catalog and catalog_digest != eligible["catalog_digest"]:
        raise ValueError("effective preference selection uses a stale catalog")
    selected = _normalize_agent_rows(payload.get("selected"), field="selected")
    excluded = _normalize_agent_rows(payload.get("excluded"), field="excluded")
    selected_ids = {item["preference_id"] for item in selected}
    excluded_ids = {item["preference_id"] for item in excluded}
    if selected_ids & excluded_ids:
        raise ValueError("a preference cannot be both selected and excluded")
    eligible_by_id = {
        str(item["preference_id"]): item
        for item in eligible["items"]
        if isinstance(item, Mapping)
    }
    if selected_ids | excluded_ids != set(eligible_by_id):
        raise ValueError("effective selection must account for every eligible preference")
    hard_ids = {
        item_id
        for item_id, item in eligible_by_id.items()
        if str(item.get("strength") or "") == "hard"
    }
    if not hard_ids.issubset(selected_ids):
        raise ValueError("hard preferences cannot be omitted from an effective selection")
    canonical_inputs = payload.get("task_context")
    if isinstance(canonical_inputs, Mapping):
        computed_task_digest = task_context_digest(
            skill=skill,
            operation=operation,
            canonical_inputs=canonical_inputs,
        )
    elif str(payload.get("schema") or "") == SELECTION_SCHEMA and HEX_DIGEST_RE.fullmatch(
        str(payload.get("task_context_digest") or "").strip()
    ):
        # A persisted receipt intentionally omits raw task context.  Consumers
        # still recompute and compare this digest from owner canonical inputs.
        computed_task_digest = str(payload.get("task_context_digest") or "").strip()
    else:
        raise ValueError("effective selection requires canonical task_context inputs")
    supplied_task_digest = str(payload.get("task_context_digest") or "").strip()
    if supplied_task_digest and supplied_task_digest != computed_task_digest:
        raise ValueError("task_context_digest does not match canonical task inputs")
    created_at = str(payload.get("created_at") or utc_now_iso())
    receipt = {
        "id": selection_id,
        "status": "active",
        "generated_by": "research-config-manager",
        "generated_at": created_at,
        "inputs": [],
        "confidence": 1.0,
        "schema": SELECTION_SCHEMA,
        "selection_id": selection_id,
        "skill": skill,
        "operation": operation,
        "catalog_digest": eligible["catalog_digest"],
        "task_context_digest": computed_task_digest,
        "selected": [
            {
                **row,
                "value_digest": str(eligible_by_id[row["preference_id"]]["value_digest"]),
            }
            for row in selected
        ],
        "excluded": excluded,
        "created_at": created_at,
        "generated_by": "runtime-agent",
    }
    receipt["selection_digest"] = _digest(
        {key: value for key, value in receipt.items() if key not in {"selection_digest", "generated_at"}}
    )
    return receipt


def record_effective_selection(project_root: Path, payload: Mapping[str, object]) -> tuple[Path, dict[str, object]]:
    selection_id = str(payload.get("selection_id") or "").strip()
    path = _validated_selection_path(project_root, selection_id, create_root=False)
    receipt: dict[str, object] = {}
    with mutation_transaction(project_root, "record-effective-preferences", [path]):
        path = _validated_selection_path(project_root, selection_id, create_root=True)
        if path.exists():
            current = _safe_existing_mapping(path)
            retry_payload = dict(payload)
            retry_payload["created_at"] = current.get("created_at")
            receipt = validate_effective_selection(project_root, retry_payload)
            if current != receipt:
                raise ValueError("effective preference selection id already exists")
            return path, receipt
        # Re-read the canonical preference catalog under the workspace lock so
        # a concurrent profile edit cannot create an immediately stale receipt.
        receipt = validate_effective_selection(project_root, payload)
        write_yaml_if_changed(path, receipt)
    return path, receipt


def load_effective_selection(
    project_root: Path,
    *,
    selection_id: str,
    skill: str,
    operation: str = "",
    expected_task_context_digest: str,
) -> dict[str, object]:
    path = _validated_selection_path(project_root, selection_id, create_root=False)
    if not path.exists():
        raise ValueError("effective preference selection does not exist")
    payload = _safe_existing_mapping(path)
    if str(payload.get("skill") or "").casefold() != str(skill or "").strip().casefold():
        raise ValueError("effective preference selection is bound to another skill")
    if str(payload.get("operation") or "").casefold() != str(operation or "").strip().casefold():
        raise ValueError("effective preference selection is bound to another operation")
    if HEX_DIGEST_RE.fullmatch(str(expected_task_context_digest or "").strip()) is None:
        raise ValueError("expected task context digest must be a sha256 digest")
    if str(payload.get("task_context_digest") or "") != str(expected_task_context_digest).strip():
        raise ValueError("effective preference selection is bound to another task")
    current = validate_effective_selection(project_root, payload)
    if current.get("selection_digest") != payload.get("selection_digest"):
        raise ValueError("effective preference selection receipt was modified")
    return payload


def resolve_effective_preferences(
    project_root: Path,
    *,
    selection_id: str,
    skill: str,
    operation: str = "",
    expected_task_context_digest: str,
) -> dict[str, object]:
    """Return current selected values to the bound consumer without persisting copies."""
    receipt = load_effective_selection(
        project_root,
        selection_id=selection_id,
        skill=skill,
        operation=operation,
        expected_task_context_digest=expected_task_context_digest,
    )
    eligible = eligible_preferences(project_root, skill=skill, operation=operation)
    eligible_by_id = {
        str(item["preference_id"]): item
        for item in eligible["items"]
        if isinstance(item, Mapping)
    }
    effective_items: list[dict[str, object]] = []
    for selected in receipt.get("selected", []):
        if not isinstance(selected, Mapping):
            raise ValueError("effective preference receipt contains a malformed selection")
        preference_id = str(selected.get("preference_id") or "")
        item = eligible_by_id.get(preference_id)
        if item is None or str(item.get("value_digest") or "") != str(selected.get("value_digest") or ""):
            raise ValueError("effective preference selection no longer matches its canonical value")
        effective_items.append(
            {
                **dict(item),
                "reason": str(selected.get("reason") or ""),
                "application": str(selected.get("application") or ""),
            }
        )
    return {
        "selection_id": selection_id,
        "skill": str(skill or "").strip().casefold(),
        "operation": str(operation or "").strip().casefold(),
        "selection_digest": receipt.get("selection_digest"),
        "effective_items": effective_items,
    }


def resolve_task_preferences(
    project_root: Path,
    *,
    selection_id: str,
    skill: str,
    operation: str,
    canonical_inputs: Mapping[str, object],
) -> dict[str, object]:
    """Owner consumer API: bind a receipt to recomputed canonical inputs."""
    expected = task_context_digest(
        skill=skill,
        operation=operation,
        canonical_inputs=canonical_inputs,
    )
    effective = resolve_effective_preferences(
        project_root,
        selection_id=selection_id,
        skill=skill,
        operation=operation,
        expected_task_context_digest=expected,
    )
    effective["task_context_digest"] = expected
    return effective


def resolve_operation_preferences(
    project_root: Path,
    *,
    selection_id: str,
    skill: str,
    operation: str,
    canonical_inputs: Mapping[str, object],
) -> dict[str, object]:
    """Resolve one optional receipt while preserving every hard fallback.

    With no receipt, soft behavior is neutral and only current hard items are
    returned.  With a receipt, ``resolve_task_preferences`` performs all
    skill/operation/task/catalog checks and the Agent-selected soft subset is
    added.  Consumers may use the values during this operation, but persist
    only the returned binding/digests rather than copying the preference
    profile into per-skill state.
    """
    normalized_selection_id = str(selection_id or "").strip()
    normalized_skill, normalized_operation = _consumer_pair(skill, operation)
    contract = operation_contract(skill=normalized_skill, operation=normalized_operation)
    expected = task_context_digest(
        skill=normalized_skill,
        operation=normalized_operation,
        canonical_inputs=canonical_inputs,
    )
    binding: dict[str, object] = {}
    if normalized_selection_id:
        effective = resolve_task_preferences(
            project_root,
            selection_id=normalized_selection_id,
            skill=normalized_skill,
            operation=normalized_operation,
            canonical_inputs=canonical_inputs,
        )
        effective_items = [
            copy.deepcopy(item)
            for item in effective.get("effective_items", [])
            if isinstance(item, Mapping)
        ]
        binding = selection_binding(effective)
        hard_items = [
            copy.deepcopy(item)
            for item in effective_items
            if str(item.get("strength") or "") == "hard"
        ]
    else:
        # Neutral analyzer operations have no hard fallback and therefore do
        # not touch the canonical preference files at all.  Other operations
        # keep their established hard-only behavior through the eligible view.
        hard_paths = list(contract.get("hard_fallback_paths") or [])
        if hard_paths:
            eligible = eligible_preferences(
                project_root, skill=normalized_skill, operation=normalized_operation
            )
            hard_items = [
                copy.deepcopy(item)
                for item in eligible["items"]
                if isinstance(item, Mapping) and str(item.get("strength") or "") == "hard"
            ]
        else:
            hard_items = []
        effective_items = hard_items
    return {
        "skill": normalized_skill,
        "operation": normalized_operation,
        "task_context_digest": expected,
        "effective_items": effective_items,
        "hard_items": hard_items,
        "soft_items": [
            copy.deepcopy(item)
            for item in effective_items
            if str(item.get("strength") or "") == "soft"
        ],
        "values_by_path": {
            str(item.get("path") or ""): copy.deepcopy(item.get("value"))
            for item in effective_items
            if str(item.get("path") or "")
        },
        "hard_value_digests": {
            str(item.get("path") or ""): str(item.get("value_digest") or "")
            for item in hard_items
            if str(item.get("path") or "")
        },
        "binding": binding,
        "consumer_contract": copy.deepcopy(contract),
    }


def selection_binding(effective: Mapping[str, object]) -> dict[str, object]:
    """Stable persistence binding; intentionally excludes preference values."""
    return {
        "selection_id": str(effective.get("selection_id") or ""),
        "selection_digest": str(effective.get("selection_digest") or ""),
        "task_context_digest": str(effective.get("task_context_digest") or ""),
        "skill": str(effective.get("skill") or ""),
        "operation": str(effective.get("operation") or ""),
    }


__all__ = [
    "SELECTION_SCHEMA",
    "SKILL_ELIGIBILITY",
    "SKILL_NEUTRALITY",
    "SKILL_OPERATIONS",
    "OPERATION_ELIGIBILITY",
    "OPERATION_CANONICAL_INPUTS",
    "canonical_digest",
    "regular_file_binding",
    "regular_tree_binding",
    "eligible_preferences",
    "operation_contract",
    "task_context_digest",
    "validate_effective_selection",
    "record_effective_selection",
    "load_effective_selection",
    "resolve_effective_preferences",
    "resolve_task_preferences",
    "resolve_operation_preferences",
    "selection_binding",
    "validate_preference_registry",
]

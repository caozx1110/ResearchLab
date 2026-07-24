"""Task-scoped preference eligibility and Agent-authored effective selections.

This module never decides which soft preferences matter to a task.  It exposes
only an allowlisted eligible view and validates the Agent's selected subset.
Receipts keep identifiers and digests rather than copying preference values or
task text.
"""
from __future__ import annotations

import hashlib
import json
import re
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
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s'\"(])(?:/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._~ -]+)+|[A-Za-z]:[\\/])")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|token|credential|authorization|password|passwd|secret|private[_-]?key)"
    r"\s*[:=]\s*(?:bearer\s+)?\S+"
)
_OPAQUE_SECRET_RE = re.compile(r"(?=[A-Za-z0-9_+/=-]{32,})(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_+/=-]{32,}")


# This table is a disclosure allowlist, not a relevance model.  Runtime Agents
# select the task-relevant subset and explain that choice in a receipt.
SKILL_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "knowledge-base-manager": (
        "profile.preferences.language_preference",
        "profile.personalization.term_style",
        "learned.*",
    ),
    "research-config-manager": (
        "profile.preferences.language_preference",
        "profile.personalization.term_style",
        "learned.*",
    ),
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
    "discussion-archivist": (
        "profile.preferences.language_preference",
        "profile.personalization.research_focus",
        "profile.personalization.reporting_style",
        "profile.personalization.term_style",
        "learned.*",
    ),
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
    "research-navigator": (
        "profile.preferences.language_preference",
        "profile.personalization.reporting_style",
        "profile.personalization.term_style",
        "profile.personalization.collaboration_boundaries",
        "runtime.browser",
        "learned.*",
    ),
    "wiki-adapter": (
        "profile.preferences.language_preference",
        "profile.personalization.reporting_style",
        "profile.personalization.term_style",
        "learned.*",
    ),
    "skill-evolution-advisor": (
        "profile.preferences.language_preference",
        "profile.personalization.collaboration_boundaries",
        "runtime.diagnostics",
        "learned.*",
    ),
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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
            path = f"learned.{raw_id}"
            item = _catalog_item(
                preference_id=f"pref-learned-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]}",
                path=path,
                value=text,
                strength="soft",
                source_type="confirmed-learning",
            )
            item["skill_hint"] = skill
            entries.append(item)
    return sorted(entries, key=lambda item: str(item["preference_id"]))


def _path_eligible(path: str, patterns: Sequence[str]) -> bool:
    return any(path == pattern or (pattern.endswith(".*") and path.startswith(pattern[:-1])) for pattern in patterns)


def eligible_preferences(project_root: Path, *, skill: str, operation: str = "") -> dict[str, object]:
    """Return the mechanically eligible preference view for an Agent task."""
    normalized_skill = str(skill or "").strip().casefold()
    if normalized_skill not in SKILL_ELIGIBILITY:
        raise ValueError(f"unknown preference consumer skill: {skill}")
    patterns = SKILL_ELIGIBILITY[normalized_skill]
    selected: list[dict[str, object]] = []
    for item in _base_catalog(project_root):
        path = str(item.get("path") or "")
        if not _path_eligible(path, patterns):
            continue
        skill_hint = str(item.get("skill_hint") or "").strip().casefold()
        if skill_hint and skill_hint != normalized_skill:
            continue
        selected.append(item)
    source_view = {
        "skill": normalized_skill,
        "operation": str(operation or "").strip().casefold(),
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
    task_context_digest = str(payload.get("task_context_digest") or "").strip()
    if HEX_DIGEST_RE.fullmatch(task_context_digest) is None:
        raise ValueError("task_context_digest must be a sha256 digest")
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
        "task_context_digest": task_context_digest,
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


__all__ = [
    "SELECTION_SCHEMA",
    "SKILL_ELIGIBILITY",
    "eligible_preferences",
    "validate_effective_selection",
    "record_effective_selection",
    "load_effective_selection",
    "resolve_effective_preferences",
]

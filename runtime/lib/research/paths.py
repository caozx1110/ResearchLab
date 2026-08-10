"""Path resolution, storage-reference remapping, and shared list/dict helpers.

Lowest domain layer: depends only on research.common. Also hosts the shared
tiny list/dict helpers and kind/path constants so higher domain modules can
reuse them without import cycles (per refactor layering: base <- domain <- facade)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .common import (
    find_project_root,
    is_url,
    research_root,
    skills_root as common_skills_root,
    slugify,
    write_text_if_changed,
    workspace_root_roles,
)
from .path_contract import (
    PathContractError,
    PRIVATE_DIAGNOSTIC_PREFIX,
    WORKSPACE_GITIGNORE_LINES,
    logical_ref_to_physical_path,
    physical_path_to_logical_ref,
)

UNIT_KIND_DIRS = {
    "paper": "papers",
    "repo": "repos",
    "dataset": "datasets",
    "blog": "blogs",
    "idea": "ideas",
    "experiment": "experiments",
    "concept": "concepts",
}


TEXT_REWRITE_SUFFIXES = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json"}


KB_GITIGNORE_LINES = list(WORKSPACE_GITIGNORE_LINES)


def project_root(start: Path | None = None, *, explicit_root: str | Path | None = None) -> Path:
    return find_project_root(start, explicit_root=explicit_root)


def kb_root(project_root: Path) -> Path:
    return research_root(project_root)


def units_root(project_root: Path) -> Path:
    return kb_root(project_root) / "units"


def user_root(project_root: Path) -> Path:
    return kb_root(project_root) / "user"


def config_root(project_root: Path) -> Path:
    return kb_root(project_root) / "config"


def raw_storage_root(project_root: Path) -> Path:
    return kb_root(project_root) / "raw"


def output_storage_root(project_root: Path) -> Path:
    return kb_root(project_root) / "output"


def kb_runtime_root(project_root: Path) -> Path:
    return kb_root(project_root) / ".runtime"


def passage_search_cache_path(project_root: Path) -> Path:
    return kb_runtime_root(project_root) / "search" / "passages.sqlite3"


def synthesis_root(project_root: Path) -> Path:
    return kb_root(project_root) / "synthesis"


def source_search_root(project_root: Path) -> Path:
    return synthesis_root(project_root) / "source-search"


def topic_taxonomy_path(project_root: Path) -> Path:
    return config_root(project_root) / "topic-taxonomy.yaml"


def candidate_pools_path(project_root: Path) -> Path:
    return config_root(project_root) / "candidate-pools.yaml"


def runtime_preferences_path(project_root: Path) -> Path:
    return config_root(project_root) / "runtime-preferences.yaml"


def kb_gitignore_path(project_root: Path) -> Path:
    return kb_root(project_root) / ".gitignore"


def versioning_state_path(project_root: Path) -> Path:
    return kb_runtime_root(project_root) / "versioning-state.yaml"


def kind_dir(kind: str) -> str:
    if kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    return UNIT_KIND_DIRS[kind]


def unit_root(project_root: Path, kind: str, unit_id: str) -> Path:
    return units_root(project_root) / kind_dir(kind) / unit_id


def record_path(project_root: Path, kind: str, unit_id: str) -> Path:
    return unit_root(project_root, kind, unit_id) / "record.yaml"


def search_stage_path(project_root: Path, stage_id: str) -> Path:
    return source_search_root(project_root) / f"{stage_id}.yaml"


def skills_root(start: Path | None = None, *, explicit_home: str | Path | None = None) -> Path:
    return common_skills_root(start, explicit_home=explicit_home)


def rel(project_root: Path, path: Path) -> str:
    roots = workspace_root_roles(project_root).roots
    try:
        return physical_path_to_logical_ref(roots, path)
    except PathContractError as original:
        # macOS exposes /var as an ancestor alias of /private/var. A strict
        # reader may canonicalize the workspace capability while its caller
        # retains the alias (or vice versa). Rebase only that root identity;
        # never resolve artifact components or broaden containment.
        try:
            canonical_data_root = roots.data_root.resolve(strict=True)
            candidate = Path(path).absolute()
            relative = candidate.relative_to(canonical_data_root)
        except (OSError, ValueError):
            raise original
        return physical_path_to_logical_ref(
            roots,
            roots.data_root / relative,
        )


def ensure_kb_gitignore(project_root: Path) -> Path:
    path = kb_gitignore_path(project_root)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    merged = list(existing_lines)
    for line in KB_GITIGNORE_LINES:
        if line in merged:
            continue
        if line == "" and merged and merged[-1] == "":
            continue
        merged.append(line)
    while merged and merged[-1] == "":
        merged.pop()
    write_text_if_changed(path, "\n".join(merged).strip() + "\n")
    return path


def is_private_diagnostic_path(value: str) -> bool:
    """Return whether a KB-relative lexical path is local diagnostic detail."""

    normalized = str(value or "").strip().replace("\\", "/").strip("/")
    return normalized == PRIVATE_DIAGNOSTIC_PREFIX or normalized.startswith(
        f"{PRIVATE_DIAGNOSTIC_PREFIX}/"
    )


def _legacy_storage_map(project_root: Path, value: str) -> tuple[Path | None, Path | None]:
    text = str(value or "").strip()
    if not text or is_url(text):
        return None, None
    new_roots = {
        "raw": raw_storage_root(project_root).resolve(),
        "output": output_storage_root(project_root).resolve(),
    }
    legacy_roots = {
        "raw": (project_root / "raw").resolve(),
        "output": (project_root / "output").resolve(),
    }
    path = Path(text).expanduser()
    if path.is_absolute():
        try:
            resolved = path.resolve(strict=False)
        except RuntimeError:
            resolved = path
        for name, legacy_root in legacy_roots.items():
            if legacy_root == new_roots[name]:
                continue
            try:
                relative = resolved.relative_to(legacy_root)
            except ValueError:
                continue
            return resolved, new_roots[name] / relative
        for name, new_root in new_roots.items():
            try:
                relative = resolved.relative_to(new_root)
            except ValueError:
                continue
            return resolved, new_root / relative
        return resolved, None
    normalized = text.replace("\\", "/").lstrip("./")
    for name, new_root in new_roots.items():
        if normalized == name or normalized.startswith(f"{name}/"):
            relative = Path(normalized).relative_to(name) if normalized != name else Path()
            return project_root / normalized, new_root / relative
        kb_prefix = f"kb/{name}"
        if normalized == kb_prefix or normalized.startswith(f"{kb_prefix}/"):
            relative = Path(normalized).relative_to(kb_prefix) if normalized != kb_prefix else Path()
            return project_root / normalized, new_root / relative
    return project_root / normalized, None


def resolve_local_reference(project_root: Path, value: str) -> Path | None:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("kb/"):
        try:
            candidate = logical_ref_to_physical_path(
                workspace_root_roles(project_root).roots,
                text,
            )
        except (ValueError, SystemExit):
            return None
        try:
            return candidate.resolve() if candidate.exists() else None
        except OSError:
            return None
    original, remapped = _legacy_storage_map(project_root, value)
    candidates = [remapped, original]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            if candidate.exists():
                return candidate.resolve()
        except OSError:
            continue
    return None


def normalize_storage_reference(project_root: Path, value: str) -> str:
    text = str(value or "").strip()
    if not text or is_url(text):
        return text
    original, remapped = _legacy_storage_map(project_root, text)
    if remapped is not None and remapped.exists():
        return remapped.resolve().as_posix()
    if original is not None and original.exists():
        return original.resolve().as_posix()
    return text


def _slug_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = {slugify(str(item), max_words=12) for item in values if str(item).strip()}
    return sorted(item for item in cleaned if item)


def _text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _artifact_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _unique_text_list(values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for item in _text_list(values):
        if item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


def _deep_fill_missing(target: Any, defaults: Any) -> Any:
    if isinstance(defaults, dict):
        base = target if isinstance(target, dict) else {}
        for key, value in defaults.items():
            if key not in base:
                base[key] = copy.deepcopy(value)
            else:
                base[key] = _deep_fill_missing(base[key], value)
        return base
    return target if target is not None else copy.deepcopy(defaults)


__all__ = [
    "UNIT_KIND_DIRS",
    "TEXT_REWRITE_SUFFIXES",
    "KB_GITIGNORE_LINES",
    "PRIVATE_DIAGNOSTIC_PREFIX",
    "project_root",
    "kb_root",
    "units_root",
    "user_root",
    "config_root",
    "raw_storage_root",
    "output_storage_root",
    "kb_runtime_root",
    "passage_search_cache_path",
    "synthesis_root",
    "source_search_root",
    "topic_taxonomy_path",
    "candidate_pools_path",
    "runtime_preferences_path",
    "kb_gitignore_path",
    "versioning_state_path",
    "kind_dir",
    "unit_root",
    "record_path",
    "search_stage_path",
    "skills_root",
    "rel",
    "ensure_kb_gitignore",
    "is_private_diagnostic_path",
    "_legacy_storage_map",
    "resolve_local_reference",
    "normalize_storage_reference",
    "_slug_list",
    "_text_list",
    "_artifact_list",
    "_unique_text_list",
    "_deep_fill_missing",
]

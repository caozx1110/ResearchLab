from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SUMMARY_LIST_KEYS = {
    "frameworks",
    "entrypoints",
    "main_workflows",
    "key_modules",
    "extension_points",
    "datasets",
    "artifacts",
    "external_dependencies",
    "risks",
    "open_questions",
}

SUMMARY_KEYS = [
    "repo_name",
    "purpose",
    "repo_type",
    "primary_language",
    "frameworks",
    "entrypoints",
    "config_system",
    "main_workflows",
    "key_modules",
    "extension_points",
    "datasets",
    "artifacts",
    "external_dependencies",
    "risks",
    "open_questions",
]

DERIVED_KEYS = {
    "repo_name",
    "repo_type",
    "primary_language",
    "frameworks",
    "entrypoints",
    "key_modules",
    "external_dependencies",
}


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                if not item:
                    empty = "{}" if isinstance(item, dict) else "[]"
                    lines.append(f"{prefix}{key}: {empty}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(prefix + "-")
                lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {yaml_scalar(item)}")
        return lines
    return [prefix + yaml_scalar(value)]


def dump_yaml_text(value: Any) -> str:
    return "\n".join(yaml_lines(value)) + "\n"


def resolve_repo_paths(paths: list[str | Path]) -> list[Path]:
    repo_paths = [Path(path).resolve() for path in paths]
    for repo_path in repo_paths:
        if not repo_path.exists() or not repo_path.is_dir():
            raise SystemExit(f"Repository path does not exist or is not a directory: {repo_path}")
    return repo_paths


def default_doc_root(repo_paths: list[Path]) -> Path:
    common_parent = Path(os.path.commonpath([str(path.parent) for path in repo_paths]))
    return common_parent / "doc"


def relative_to_root(path: Path, doc_root: Path) -> str:
    return path.relative_to(doc_root).as_posix()


def load_facts(doc_dir: Path) -> dict[str, Any]:
    facts_path = doc_dir / "_scan" / "facts.json"
    if not facts_path.exists():
        raise FileNotFoundError(f"Missing scan facts: {facts_path}")
    return json.loads(facts_path.read_text(encoding="utf-8"))


def seed_summary(facts: dict[str, Any]) -> dict[str, Any]:
    entrypoints = [item["path"] for item in facts.get("entrypoints", [])[:8]]
    key_modules = []
    for subsystem in facts.get("subsystems", []):
        key_modules.append(subsystem["path"])
    for path in facts.get("key_dirs", []):
        if path not in key_modules:
            key_modules.append(path)
    frameworks = facts.get("framework_hints", [])[:10]
    external_dependencies = facts.get("external_dependencies", [])[:10]

    return {
        "repo_name": facts.get("repo_name", ""),
        "purpose": "",
        "repo_type": facts.get("repo_type_hint", ""),
        "primary_language": facts.get("primary_language", ""),
        "frameworks": frameworks,
        "entrypoints": entrypoints,
        "config_system": "",
        "main_workflows": [],
        "key_modules": key_modules[:12],
        "extension_points": [],
        "datasets": [],
        "artifacts": [],
        "external_dependencies": external_dependencies,
        "risks": [],
        "open_questions": [],
    }


def empty_summary() -> dict[str, Any]:
    data = {}
    for key in SUMMARY_KEYS:
        data[key] = [] if key in SUMMARY_LIST_KEYS else ""
    return data


def parse_scalar(text: str) -> str:
    if not text or text == "null":
        return ""
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text.strip('"')
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text


def load_summary(path: Path) -> dict[str, Any]:
    data = empty_summary()
    if not path.exists():
        return data

    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line.startswith("  - ") and current_list_key:
            data[current_list_key].append(parse_scalar(stripped[2:].strip()))
            continue
        if raw_line.startswith("-") and current_list_key:
            data[current_list_key].append(parse_scalar(stripped[1:].strip()))
            continue
        if raw_line.startswith(" "):
            continue
        key, sep, remainder = raw_line.partition(":")
        if not sep:
            current_list_key = None
            continue
        key = key.strip()
        if key not in data:
            current_list_key = None
            continue
        remainder = remainder.strip()
        if key in SUMMARY_LIST_KEYS:
            current_list_key = key
            if remainder and remainder != "[]":
                value = parse_scalar(remainder)
                if value:
                    data[key].append(value)
            continue
        data[key] = parse_scalar(remainder)
        current_list_key = None
    return data


def is_empty(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) == 0
    return value in ("", None)


def merge_summary(
    existing: dict[str, Any],
    seeded: dict[str, Any],
    sync_derived: bool,
) -> tuple[dict[str, Any], bool]:
    merged = empty_summary()
    changed = False
    for key in SUMMARY_KEYS:
        old_value = existing.get(key, [] if key in SUMMARY_LIST_KEYS else "")
        new_value = seeded.get(key, [] if key in SUMMARY_LIST_KEYS else "")
        if key == "repo_name":
            final_value = new_value or old_value
        elif sync_derived and key in DERIVED_KEYS and not is_empty(new_value):
            final_value = new_value
        elif is_empty(old_value) and not is_empty(new_value):
            final_value = new_value
        else:
            final_value = old_value
        merged[key] = final_value
        if final_value != old_value:
            changed = True
    return merged, changed


def list_from_summary_or_seed(summary: dict[str, Any], seeded: dict[str, Any], key: str) -> list[str]:
    value = summary.get(key, [])
    if isinstance(value, list) and value:
        return value
    seeded_value = seeded.get(key, [])
    return seeded_value if isinstance(seeded_value, list) else []

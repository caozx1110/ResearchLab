"""Quick structural validation for bundled research skills.

The OpenAI skill metadata specification defines ``short_description`` as a
25–64 character UI blurb. This validator enforces that range along with the
required skill frontmatter, interface fields, and discoverable script paths.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional, Sequence

import yaml


SHORT_DESCRIPTION_MIN = 25
SHORT_DESCRIPTION_MAX = 64
REQUIRED_INTERFACE_FIELDS = (
    "display_name",
    "short_description",
    "default_prompt",
)
SCRIPT_REFERENCE_RE = re.compile(
    r"(?:(?:\.agents/skills/)?(?P<skill>[a-z0-9-]+)/)?"
    r"(?P<path>scripts/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+)"
)


def _load_yaml(path: Path, label: str, errors: list[str]) -> Optional[object]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{label}: cannot parse YAML: {exc}")
        return None


def _frontmatter(skill_md: Path, errors: list[str]) -> tuple[dict[str, object], str]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{skill_md}: cannot read file: {exc}")
        return {}, ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        errors.append(f"{skill_md}: missing opening YAML frontmatter delimiter")
        return {}, text
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        errors.append(f"{skill_md}: missing closing YAML frontmatter delimiter")
        return {}, text
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as exc:
        errors.append(f"{skill_md}: cannot parse frontmatter YAML: {exc}")
        return {}, text
    if not isinstance(metadata, dict):
        errors.append(f"{skill_md}: frontmatter must be a mapping")
        return {}, text
    return metadata, text


def _required_string(
    mapping: dict[str, object], field: str, label: str, errors: list[str]
) -> Optional[str]:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: {field} must be a non-empty string")
        return None
    return value


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    openai_yaml = skill_dir / "agents" / "openai.yaml"

    metadata, skill_text = _frontmatter(skill_md, errors)
    name = _required_string(metadata, "name", str(skill_md), errors)
    _required_string(metadata, "description", str(skill_md), errors)
    if name is not None and name != skill_dir.name:
        errors.append(
            f"{skill_md}: name {name!r} does not match directory {skill_dir.name!r}"
        )

    if not openai_yaml.is_file():
        errors.append(f"{openai_yaml}: missing agents/openai.yaml")
    else:
        parsed = _load_yaml(openai_yaml, str(openai_yaml), errors)
        if parsed is not None:
            if not isinstance(parsed, dict):
                errors.append(f"{openai_yaml}: top level must be a mapping")
            else:
                interface = parsed.get("interface")
                if not isinstance(interface, dict):
                    errors.append(f"{openai_yaml}: interface must be a mapping")
                else:
                    values = {
                        field: _required_string(
                            interface, field, f"{openai_yaml}: interface", errors
                        )
                        for field in REQUIRED_INTERFACE_FIELDS
                    }
                    short_description = values["short_description"]
                    if short_description is not None and not (
                        SHORT_DESCRIPTION_MIN
                        <= len(short_description)
                        <= SHORT_DESCRIPTION_MAX
                    ):
                        errors.append(
                            f"{openai_yaml}: interface.short_description must be "
                            f"{SHORT_DESCRIPTION_MIN}-{SHORT_DESCRIPTION_MAX} characters "
                            f"(got {len(short_description)})"
                        )
                    default_prompt = values["default_prompt"]
                    if default_prompt is not None and f"${skill_dir.name}" not in default_prompt:
                        errors.append(
                            f"{openai_yaml}: interface.default_prompt must mention "
                            f"${skill_dir.name}"
                        )

    for match in SCRIPT_REFERENCE_RE.finditer(skill_text):
        referenced_skill = match.group("skill") or skill_dir.name
        script_path = skill_dir.parent / referenced_skill / match.group("path")
        if not script_path.is_file():
            errors.append(f"{skill_md}: referenced script does not exist: {script_path}")

    return errors


def skill_directories(skills_root: Path) -> list[Path]:
    return sorted(
        path for path in skills_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def validate_skills(skills_root: Path) -> list[str]:
    errors: list[str] = []
    for skill_dir in skill_directories(skills_root):
        errors.extend(validate_skill(skill_dir))
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skills_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "skills",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    errors = validate_skills(args.skills_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    count = len(skill_directories(args.skills_root))
    print(f"Validated {count} skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

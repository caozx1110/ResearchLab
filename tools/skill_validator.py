"""Structural validation for discoverable bundled research skills.

The OpenAI skill metadata specification defines ``short_description`` as a
25–64 character UI blurb. This validator enforces that range along with the
required skill frontmatter, interface fields, discoverable script paths, and
the generated-metadata contract rooted at ``skills/metadata.yaml``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional, Sequence

import yaml


SHORT_DESCRIPTION_MIN = 25
SHORT_DESCRIPTION_MAX = 64
SKILL_MAX_LINES = 500
SKILL_MAX_BYTES = 64 * 1024
LONG_REFERENCE_MIN_LINES = 200
REQUIRED_INTERFACE_FIELDS = (
    "display_name",
    "short_description",
    "default_prompt",
)
METADATA_SCHEMA = "research-skill-metadata/v1"
METADATA_FILENAME = "metadata.yaml"
SKILL_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
SCRIPT_REFERENCE_RE = re.compile(
    r"(?:(?:\.agents/skills/)?(?P<skill>[a-z0-9-]+)/)?"
    r"(?P<path>scripts/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+)"
)
MARKDOWN_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)"
)
EXPLICIT_ANCHOR_RE = re.compile(
    r"<a\s+(?:[^>]*?\s)?(?:id|name)=[\"'](?P<anchor>[^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$", re.MULTILINE)
TOC_HEADING_RE = re.compile(
    r"^##\s+(?:目录|Table of Contents)\s*$", re.IGNORECASE | re.MULTILINE
)
ON_DEMAND_RE = re.compile(r"按需加载|load only|on[- ]demand", re.IGNORECASE)


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


def _heading_slug(title: str) -> str:
    title = EXPLICIT_ANCHOR_RE.sub("", title)
    title = re.sub(r"`([^`]*)`", r"\1", title)
    title = re.sub(r"<[^>]+>", "", title)
    title = title.strip().lower()
    title = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    return re.sub(r"[\s-]+", "-", title).strip("-")


def _markdown_anchors(text: str) -> set[str]:
    anchors = {match.group("anchor") for match in EXPLICIT_ANCHOR_RE.finditer(text)}
    slug_counts: dict[str, int] = {}
    for match in HEADING_RE.finditer(text):
        slug = _heading_slug(match.group("title"))
        if not slug:
            continue
        duplicate = slug_counts.get(slug, 0)
        slug_counts[slug] = duplicate + 1
        anchors.add(slug if duplicate == 0 else f"{slug}-{duplicate}")
    return anchors


def _local_link_path(source: Path, raw_target: str, skill_dir: Path) -> tuple[Path, str] | None:
    target = raw_target[1:-1] if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
    if target.startswith(("http://", "https://", "mailto:", "data:")):
        return None
    path_text, separator, fragment = target.partition("#")
    if not path_text:
        return source, fragment if separator else ""
    if "\\" in path_text or Path(path_text).is_absolute():
        raise ValueError("link target must be a relative POSIX path")
    resolved = (source.parent / path_text).resolve(strict=False)
    try:
        resolved.relative_to(skill_dir.resolve())
    except ValueError as exc:
        raise ValueError("link target escapes the skill directory") from exc
    return resolved, fragment if separator else ""


def _validate_markdown_links(
    source: Path,
    text: str,
    skill_dir: Path,
    errors: list[str],
) -> set[Path]:
    linked_files: set[Path] = set()
    for match in MARKDOWN_LINK_RE.finditer(text):
        raw_target = match.group("target")
        try:
            resolved = _local_link_path(source, raw_target, skill_dir)
        except ValueError as exc:
            errors.append(f"{source}: invalid Markdown link {raw_target!r}: {exc}")
            continue
        if resolved is None:
            continue
        target_path, fragment = resolved
        if not target_path.is_file():
            errors.append(f"{source}: Markdown link target does not exist: {raw_target}")
            continue
        linked_files.add(target_path.resolve())
        if fragment:
            try:
                target_text = target_path.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"{source}: cannot read Markdown link target {target_path}: {exc}")
                continue
            if fragment not in _markdown_anchors(target_text):
                errors.append(
                    f"{source}: Markdown link anchor does not exist: {raw_target}"
                )
    return linked_files


def _validate_long_reference(path: Path, text: str, errors: list[str]) -> None:
    lines = text.splitlines()
    if len(lines) < LONG_REFERENCE_MIN_LINES:
        return
    navigation = "\n".join(lines[:80])
    if TOC_HEADING_RE.search(navigation) is None:
        errors.append(
            f"{path}: references with {LONG_REFERENCE_MIN_LINES}+ lines require a top-level table of contents"
        )
    if ON_DEMAND_RE.search(navigation) is None:
        errors.append(
            f"{path}: references with {LONG_REFERENCE_MIN_LINES}+ lines require on-demand loading guidance"
        )


def _validate_progressive_disclosure(
    skill_dir: Path,
    skill_text: str,
    errors: list[str],
) -> None:
    skill_md = skill_dir / "SKILL.md"
    byte_count = len(skill_text.encode("utf-8"))
    line_count = len(skill_text.splitlines())
    if line_count > SKILL_MAX_LINES:
        errors.append(
            f"{skill_md}: entry point exceeds {SKILL_MAX_LINES} lines (got {line_count})"
        )
    if byte_count > SKILL_MAX_BYTES:
        errors.append(
            f"{skill_md}: entry point exceeds {SKILL_MAX_BYTES} bytes (got {byte_count})"
        )

    direct_links = _validate_markdown_links(skill_md, skill_text, skill_dir, errors)
    reference_root = skill_dir / "references"
    references = sorted(reference_root.rglob("*.md")) if reference_root.is_dir() else []
    for reference in references:
        try:
            reference_text = reference.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{reference}: cannot read reference: {exc}")
            continue
        if reference.resolve() not in direct_links:
            errors.append(
                f"{reference}: reference must be linked directly from {skill_md}"
            )
        _validate_markdown_links(reference, reference_text, skill_dir, errors)
        _validate_long_reference(reference, reference_text, errors)

def _required_string(
    mapping: dict[str, object], field: str, label: str, errors: list[str]
) -> Optional[str]:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: {field} must be a non-empty string")
        return None
    return value


def render_openai_metadata(payload: dict[str, object]) -> str:
    """Render one generated ``agents/openai.yaml`` deterministically."""
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )


def load_metadata_catalog(
    skills_root: Path, errors: list[str]
) -> dict[str, dict[str, object]]:
    """Load and minimally validate the checked-in metadata SSOT."""
    path = skills_root / METADATA_FILENAME
    if not path.is_file():
        errors.append(f"{path}: missing metadata SSOT")
        return {}
    parsed = _load_yaml(path, str(path), errors)
    if not isinstance(parsed, dict):
        if parsed is not None:
            errors.append(f"{path}: top level must be a mapping")
        return {}
    if parsed.get("schema") != METADATA_SCHEMA:
        errors.append(f"{path}: schema must be {METADATA_SCHEMA!r}")
    raw_skills = parsed.get("skills")
    if not isinstance(raw_skills, dict):
        errors.append(f"{path}: skills must be a mapping")
        return {}
    catalog: dict[str, dict[str, object]] = {}
    for raw_name, raw_payload in raw_skills.items():
        name = str(raw_name or "")
        if not SKILL_NAME_RE.fullmatch(name):
            errors.append(f"{path}: invalid skill name in catalog: {raw_name!r}")
            continue
        if not isinstance(raw_payload, dict):
            errors.append(f"{path}: skills.{name} must be a mapping")
            continue
        catalog[name] = raw_payload
    return catalog


def generated_metadata_outputs(
    skills_root: Path, errors: list[str]
) -> dict[Path, str]:
    """Return the exact generated files after closing catalog/discovery sets."""
    catalog = load_metadata_catalog(skills_root, errors)
    discoverable = {path.name for path in skill_directories(skills_root)}
    configured = set(catalog)
    missing = sorted(discoverable - configured)
    extra = sorted(configured - discoverable)
    if missing:
        errors.append(
            f"{skills_root / METADATA_FILENAME}: missing discoverable skill metadata: {missing}"
        )
    if extra:
        errors.append(
            f"{skills_root / METADATA_FILENAME}: metadata exists for non-discoverable skills: {extra}"
        )
    return {
        skills_root / name / "agents" / "openai.yaml": render_openai_metadata(catalog[name])
        for name in sorted(discoverable & configured)
    }


def validate_skill(
    skill_dir: Path, *, expected_openai_text: Optional[str] = None
) -> list[str]:
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
        if expected_openai_text is not None:
            try:
                actual_openai_text = openai_yaml.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"{openai_yaml}: cannot read file: {exc}")
            else:
                if actual_openai_text != expected_openai_text:
                    errors.append(
                        f"{openai_yaml}: generated metadata drift; "
                        "run tools/generate_skill_metadata.py"
                    )
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

    _validate_progressive_disclosure(skill_dir, skill_text, errors)

    return errors


def skill_directories(skills_root: Path) -> list[Path]:
    return sorted(
        path
        for path in skills_root.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    )


def validate_skills(skills_root: Path) -> list[str]:
    errors: list[str] = []
    generated = generated_metadata_outputs(skills_root, errors)
    discoverable = {path.resolve() for path in skill_directories(skills_root)}
    for openai_yaml in sorted(skills_root.glob("*/agents/openai.yaml")):
        if openai_yaml.parent.parent.resolve() not in discoverable:
            errors.append(
                f"{openai_yaml}: orphan metadata for a non-discoverable skill directory"
            )
    for skill_dir in skill_directories(skills_root):
        errors.extend(
            validate_skill(
                skill_dir,
                expected_openai_text=generated.get(skill_dir / "agents" / "openai.yaml"),
            )
        )
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skills_root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "skills",
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

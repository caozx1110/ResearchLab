import shutil
from pathlib import Path

import yaml

from repo_paths import SKILLS_ROOT

from research.skill_validator import (
    LONG_REFERENCE_MIN_LINES,
    SKILL_MAX_BYTES,
    SKILL_MAX_LINES,
    skill_directories,
    validate_skills,
)


def test_all_skill_metadata_is_valid():
    skill_dirs = skill_directories(SKILLS_ROOT)

    assert len(skill_dirs) == 15
    assert validate_skills(SKILLS_ROOT) == []


def test_meta_skill_metadata_exposes_complementary_routing_boundaries():
    payload = yaml.safe_load((SKILLS_ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    catalog = payload["skills"]
    discussion = catalog["discussion-archivist"]["interface"]
    evolution = catalog["skill-evolution-advisor"]["interface"]
    orchestrator = catalog["research-orchestrator"]["interface"]

    assert "research-route" in discussion["default_prompt"]
    assert "skill/workflow" in discussion["default_prompt"]
    assert "skill/workflow" in evolution["default_prompt"]
    assert "model, method, or experiment" in evolution["default_prompt"]
    assert "ordered route decision" in orchestrator["default_prompt"]


def _copied_skills_root(tmp_path: Path) -> Path:
    copied = tmp_path / "skills"
    shutil.copytree(SKILLS_ROOT, copied)
    return copied


def test_skill_metadata_rejects_missing_catalog_entry(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    metadata_path = skills_root / "metadata.yaml"
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    del payload["skills"]["unit-analyst"]
    metadata_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    errors = validate_skills(skills_root)

    assert any("missing discoverable skill metadata" in error for error in errors)


def test_skill_metadata_rejects_extra_catalog_entry(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    metadata_path = skills_root / "metadata.yaml"
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    payload["skills"]["retired-skill"] = payload["skills"]["unit-analyst"]
    metadata_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    errors = validate_skills(skills_root)

    assert any("metadata exists for non-discoverable skills" in error for error in errors)


def test_skill_metadata_rejects_generated_file_drift(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    generated = skills_root / "unit-analyst" / "agents" / "openai.yaml"
    generated.write_text(
        generated.read_text(encoding="utf-8") + "# manual edit\n",
        encoding="utf-8",
    )

    errors = validate_skills(skills_root)

    assert any("generated metadata drift" in error for error in errors)


def test_skill_metadata_rejects_orphan_generated_file(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    orphan = skills_root / "retired-skill" / "agents" / "openai.yaml"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("interface: {}\n", encoding="utf-8")

    errors = validate_skills(skills_root)

    assert any("orphan metadata" in error for error in errors)


def _append_skill_text(skills_root: Path, name: str, text: str) -> Path:
    skill = skills_root / name / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + text, encoding="utf-8")
    return skill


def test_progressive_disclosure_rejects_skill_line_limit(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    skill = skills_root / "discussion-archivist" / "SKILL.md"
    current_lines = len(skill.read_text(encoding="utf-8").splitlines())
    _append_skill_text(
        skills_root,
        "discussion-archivist",
        "\n".join(f"line {index}" for index in range(SKILL_MAX_LINES - current_lines + 1)),
    )

    errors = validate_skills(skills_root)

    assert any("entry point exceeds 500 lines" in error for error in errors)


def test_progressive_disclosure_rejects_skill_byte_limit(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    _append_skill_text(
        skills_root,
        "discussion-archivist",
        "\n" + ("字" * SKILL_MAX_BYTES),
    )

    errors = validate_skills(skills_root)

    assert any("entry point exceeds 65536 bytes" in error for error in errors)


def test_progressive_disclosure_rejects_broken_link_and_anchor(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    _append_skill_text(
        skills_root,
        "discussion-archivist",
        "\n[missing](references/not-there.md)\n[bad anchor](SKILL.md#not-an-anchor)\n",
    )

    errors = validate_skills(skills_root)

    assert any("Markdown link target does not exist" in error for error in errors)
    assert any("Markdown link anchor does not exist" in error for error in errors)


def test_progressive_disclosure_requires_every_reference_one_hop_from_entry(
    tmp_path: Path,
):
    skills_root = _copied_skills_root(tmp_path)
    references = skills_root / "discussion-archivist" / "references"
    references.mkdir()
    (references / "first.md").write_text(
        "# First\n\n[second](second.md)\n",
        encoding="utf-8",
    )
    second = references / "second.md"
    second.write_text("# Second\n", encoding="utf-8")
    _append_skill_text(
        skills_root,
        "discussion-archivist",
        "\n[First reference](references/first.md)\n",
    )

    errors = validate_skills(skills_root)

    assert any(str(second) in error and "linked directly" in error for error in errors)


def test_progressive_disclosure_rejects_missing_or_unknown_protocol_anchor(
    tmp_path: Path,
):
    skills_root = _copied_skills_root(tmp_path)
    skill = skills_root / "discussion-archivist" / "SKILL.md"
    original = skill.read_text(encoding="utf-8")
    without_protocol = "\n".join(
        line for line in original.splitlines() if "SCHEMAS.md#" not in line
    ) + "\n"
    skill.write_text(without_protocol, encoding="utf-8")

    missing_errors = validate_skills(skills_root)

    assert any("missing direct SCHEMAS.md protocol reference" in error for error in missing_errors)

    skill.write_text(
        original.replace("SCHEMAS.md#program-files", "SCHEMAS.md#not-a-real-anchor"),
        encoding="utf-8",
    )
    unknown_errors = validate_skills(skills_root)

    assert any("referenced SCHEMAS.md anchor does not exist" in error for error in unknown_errors)

    skill.write_text(
        original.replace("`#ownership`", "`#not-a-secondary-anchor`"),
        encoding="utf-8",
    )
    secondary_errors = validate_skills(skills_root)

    assert any("#not-a-secondary-anchor" in error for error in secondary_errors)


def test_progressive_disclosure_allows_reasoned_protocol_exemption(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    skill = skills_root / "discussion-archivist" / "SKILL.md"
    text = "\n".join(
        line for line in skill.read_text(encoding="utf-8").splitlines() if "SCHEMAS.md#" not in line
    )
    skill.write_text(
        text + "\n<!-- protocol-reference-exempt: transports no canonical artifact -->\n",
        encoding="utf-8",
    )

    errors = validate_skills(skills_root)

    assert not any("missing direct SCHEMAS.md protocol reference" in error for error in errors)


def test_long_reference_requires_toc_and_on_demand_guidance(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    references = skills_root / "discussion-archivist" / "references"
    references.mkdir()
    long_reference = references / "long.md"
    long_reference.write_text(
        "# Long reference\n" + "\n".join(
            f"contract line {index}" for index in range(LONG_REFERENCE_MIN_LINES - 1)
        ),
        encoding="utf-8",
    )
    _append_skill_text(
        skills_root,
        "discussion-archivist",
        "\n[Long reference](references/long.md)\n",
    )

    errors = validate_skills(skills_root)

    assert any("require a top-level table of contents" in error for error in errors)
    assert any("require on-demand loading guidance" in error for error in errors)


def test_language_density_is_not_a_hard_failure(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    _append_skill_text(
        skills_root,
        "discussion-archivist",
        "\n## Dense prose\n\n" + "术语密集但仍由尺寸、链接与合同门判断。" * 200 + "\n",
    )

    errors = validate_skills(skills_root)

    assert errors == []

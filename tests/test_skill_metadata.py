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

EXPECTED_SHIPPING_SKILLS = {
    "research-analysis",
    "research-capture",
    "research-review",
    "research-vault",
    "research-workbench",
}


def test_all_skill_metadata_is_valid():
    skill_dirs = skill_directories(SKILLS_ROOT)

    assert {path.name for path in skill_dirs} == EXPECTED_SHIPPING_SKILLS
    assert validate_skills(SKILLS_ROOT) == []


def test_v2_skill_metadata_exposes_five_owner_boundaries():
    payload = yaml.safe_load((SKILLS_ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    catalog = payload["skills"]
    assert set(catalog) == EXPECTED_SHIPPING_SKILLS
    for skill_name in EXPECTED_SHIPPING_SKILLS:
        interface = catalog[skill_name]["interface"]
        assert interface["default_prompt"].startswith(f"Use ${skill_name}")


def _copied_skills_root(tmp_path: Path) -> Path:
    copied = tmp_path / "skills"
    shutil.copytree(SKILLS_ROOT, copied)
    return copied


def test_skill_metadata_rejects_missing_catalog_entry(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    metadata_path = skills_root / "metadata.yaml"
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    del payload["skills"]["research-vault"]
    metadata_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    errors = validate_skills(skills_root)

    assert any("missing discoverable skill metadata" in error for error in errors)


def test_skill_metadata_rejects_extra_catalog_entry(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    metadata_path = skills_root / "metadata.yaml"
    payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    payload["skills"]["retired-skill"] = payload["skills"]["research-vault"]
    metadata_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    errors = validate_skills(skills_root)

    assert any("metadata exists for non-discoverable skills" in error for error in errors)


def test_skill_metadata_rejects_generated_file_drift(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    generated = skills_root / "research-vault" / "agents" / "openai.yaml"
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
    skill = skills_root / "research-vault" / "SKILL.md"
    current_lines = len(skill.read_text(encoding="utf-8").splitlines())
    _append_skill_text(
        skills_root,
        "research-vault",
        "\n".join(f"line {index}" for index in range(SKILL_MAX_LINES - current_lines + 1)),
    )

    errors = validate_skills(skills_root)

    assert any("entry point exceeds 500 lines" in error for error in errors)


def test_progressive_disclosure_rejects_skill_byte_limit(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    _append_skill_text(
        skills_root,
        "research-vault",
        "\n" + ("字" * SKILL_MAX_BYTES),
    )

    errors = validate_skills(skills_root)

    assert any("entry point exceeds 65536 bytes" in error for error in errors)


def test_progressive_disclosure_rejects_broken_link_and_anchor(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    _append_skill_text(
        skills_root,
        "research-vault",
        "\n[missing](references/not-there.md)\n[bad anchor](SKILL.md#not-an-anchor)\n",
    )

    errors = validate_skills(skills_root)

    assert any("Markdown link target does not exist" in error for error in errors)
    assert any("Markdown link anchor does not exist" in error for error in errors)


def test_progressive_disclosure_requires_every_reference_one_hop_from_entry(
    tmp_path: Path,
):
    skills_root = _copied_skills_root(tmp_path)
    references = skills_root / "research-vault" / "references"
    references.mkdir(exist_ok=True)
    (references / "first.md").write_text(
        "# First\n\n[second](second.md)\n",
        encoding="utf-8",
    )
    second = references / "second.md"
    second.write_text("# Second\n", encoding="utf-8")
    _append_skill_text(
        skills_root,
        "research-vault",
        "\n[First reference](references/first.md)\n",
    )

    errors = validate_skills(skills_root)

    assert any(str(second) in error and "linked directly" in error for error in errors)


def test_progressive_disclosure_requires_local_reference_links(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    skill = skills_root / "research-vault" / "SKILL.md"
    original = skill.read_text(encoding="utf-8")
    skill.write_text(original.replace("references/v2-contract.md", "references/missing.md"), encoding="utf-8")

    errors = validate_skills(skills_root)

    assert any("Markdown link target does not exist" in error for error in errors)

    skill.write_text(original.replace("[Research Vault v2 contract](references/v2-contract.md)", ""), encoding="utf-8")
    errors = validate_skills(skills_root)
    assert any("reference must be linked directly" in error for error in errors)


def test_long_reference_requires_toc_and_on_demand_guidance(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    references = skills_root / "research-vault" / "references"
    references.mkdir(exist_ok=True)
    long_reference = references / "long.md"
    long_reference.write_text(
        "# Long reference\n" + "\n".join(
            f"contract line {index}" for index in range(LONG_REFERENCE_MIN_LINES - 1)
        ),
        encoding="utf-8",
    )
    _append_skill_text(
        skills_root,
        "research-vault",
        "\n[Long reference](references/long.md)\n",
    )

    errors = validate_skills(skills_root)

    assert any("require a top-level table of contents" in error for error in errors)
    assert any("require on-demand loading guidance" in error for error in errors)


def test_language_density_is_not_a_hard_failure(tmp_path: Path):
    skills_root = _copied_skills_root(tmp_path)
    _append_skill_text(
        skills_root,
        "research-vault",
        "\n## Dense prose\n\n" + "术语密集但仍由尺寸、链接与合同门判断。" * 200 + "\n",
    )

    errors = validate_skills(skills_root)

    assert errors == []

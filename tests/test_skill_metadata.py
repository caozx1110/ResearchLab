import shutil
from pathlib import Path

import yaml

from repo_paths import SKILLS_ROOT

from research.skill_validator import skill_directories, validate_skills


def test_all_skill_metadata_is_valid():
    skill_dirs = skill_directories(SKILLS_ROOT)

    assert len(skill_dirs) == 15
    assert validate_skills(SKILLS_ROOT) == []


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

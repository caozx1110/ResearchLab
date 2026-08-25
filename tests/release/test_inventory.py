from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from repo_paths import REPO_ROOT, SKILLS_ROOT
from support import load_skill_validator


EXPECTED_SKILLS = {
    "research-analysis",
    "research-capture",
    "research-review",
    "research-vault",
    "research-workbench",
}


def test_discoverable_inventory_is_exactly_five_and_validated() -> None:
    validator = load_skill_validator()
    discovered = {path.name for path in validator.skill_directories(SKILLS_ROOT)}

    assert discovered == EXPECTED_SKILLS
    assert set(validator.validate_skills(SKILLS_ROOT)) == set()

    metadata = yaml.safe_load((SKILLS_ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    assert set(metadata["skills"]) == EXPECTED_SKILLS
    for name in EXPECTED_SKILLS:
        interface = metadata["skills"][name]["interface"]
        assert interface["default_prompt"].startswith(f"Use ${name}")


def test_metadata_generator_has_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "generate_skill_metadata.py"), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_validator_rejects_an_extra_discoverable_skill(tmp_path: Path) -> None:
    import shutil

    skills = tmp_path / "skills"
    shutil.copytree(SKILLS_ROOT, skills)
    extra = skills / "retired-skill"
    extra.mkdir()
    (extra / "SKILL.md").write_text(
        "---\nname: retired-skill\ndescription: test\n---\n", encoding="utf-8"
    )

    errors = load_skill_validator().validate_skills(skills)

    assert any("missing discoverable skill metadata" in error for error in errors)

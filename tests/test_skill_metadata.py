from pathlib import Path

from repo_paths import REPO_ROOT

from research.skill_validator import skill_directories, validate_skills


REPO_ROOT = REPO_ROOT
SKILLS_ROOT = REPO_ROOT / ".agents" / "skills"


def test_all_skill_metadata_is_valid():
    skill_dirs = skill_directories(SKILLS_ROOT)

    assert len(skill_dirs) == 20
    assert validate_skills(SKILLS_ROOT) == []

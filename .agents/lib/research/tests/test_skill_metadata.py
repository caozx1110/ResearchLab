from pathlib import Path

from research.skill_validator import skill_directories, validate_skills


REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS_ROOT = REPO_ROOT / ".agents" / "skills"


def test_all_skill_metadata_is_valid():
    skill_dirs = skill_directories(SKILLS_ROOT)

    assert len(skill_dirs) == 17
    assert validate_skills(SKILLS_ROOT) == []

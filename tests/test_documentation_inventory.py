from __future__ import annotations

import re
import subprocess
from pathlib import Path

from repo_paths import REPO_ROOT


LEGACY_ANALYZER_PATH = re.compile(
    r"\.agents/skills/(?:paper|repo|dataset|blog)-analyst(?:/|`|\b)"
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _discoverable_skills() -> list[str]:
    skills_root = REPO_ROOT / ".agents" / "skills"
    return sorted(
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _current_markdown_files() -> list[Path]:
    files = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "SECURITY.md",
    ]
    for root in (REPO_ROOT / "docs", REPO_ROOT / ".agents", REPO_ROOT / "tools"):
        files.extend(root.rglob("*.md"))
    return sorted({path for path in files if path.is_file()})


def test_distributed_readme_matches_discoverable_skill_inventory() -> None:
    skills = _discoverable_skills()
    readme = (REPO_ROOT / ".agents" / "README.md").read_text(encoding="utf-8")

    assert len(skills) == 15
    assert "15 个可发现 skill" in readme
    for skill in skills:
        assert f"`{skill}`" in readme

    assert not LEGACY_ANALYZER_PATH.search(readme)
    assert "20 个本地 skill" not in readme
    assert "`wiki-adapter`" not in readme
    assert "`research-navigator`" not in readme


def test_current_docs_do_not_reference_removed_analyzer_paths() -> None:
    stale = []
    for path in _current_markdown_files():
        text = path.read_text(encoding="utf-8")
        if LEGACY_ANALYZER_PATH.search(text):
            stale.append(path.relative_to(REPO_ROOT).as_posix())
    assert stale == []


def test_current_local_markdown_links_resolve() -> None:
    missing: list[str] = []
    for path in _current_markdown_files():
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            resolved = (path.parent / relative).resolve()
            if not resolved.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)} -> {target}")
    assert missing == []


def test_dev_docs_are_local_only_and_not_git_tracked() -> None:
    ignore_lines = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "dev-docs/" in ignore_lines

    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "`dev-docs/`" in agents
    assert "`dev-docs/`" in contributing
    assert "`temp/SYSTEM_DESIGN_SSOT.md`" not in agents

    if not (REPO_ROOT / ".git").exists():
        return
    result = subprocess.run(
        ["git", "ls-files", "dev-docs"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""

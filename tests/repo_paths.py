"""Stable repository paths shared by tests.

Test modules must not infer repository layout from their own nesting depth.  Keep
that discovery here so moving the test tree does not silently redirect fixtures.
"""

from __future__ import annotations

from pathlib import Path


def _discover_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pytest.ini").is_file() and (candidate / ".agents").is_dir():
            return candidate
    raise RuntimeError(f"could not discover repository root from {start}")


REPO_ROOT = _discover_repo_root(Path(__file__).resolve().parent)
AGENTS_ROOT = REPO_ROOT / ".agents"
RESEARCH_LIB_ROOT = AGENTS_ROOT / "lib" / "research"
SKILLS_ROOT = AGENTS_ROOT / "skills"
MAINTAINER_NAVIGATOR_ROOT = REPO_ROOT / "tools" / "research-navigator"

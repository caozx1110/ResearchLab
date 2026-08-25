"""Stable repository paths shared by tests.

Test modules must not infer repository layout from their own nesting depth.  Keep
that discovery here so moving the test tree does not silently redirect fixtures.
"""

from __future__ import annotations

from pathlib import Path


def _discover_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (
            (candidate / "pytest.ini").is_file()
            and (candidate / "skills" / "metadata.yaml").is_file()
            and (candidate / "runtime" / "lib" / "research" / "__init__.py").is_file()
        ):
            return candidate
    raise RuntimeError(f"could not discover repository root from {start}")


REPO_ROOT = _discover_repo_root(Path(__file__).resolve().parent)
SKILLS_ROOT = REPO_ROOT / "skills"

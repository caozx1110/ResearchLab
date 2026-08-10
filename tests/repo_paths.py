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
RUNTIME_ROOT = REPO_ROOT / "runtime"
RUNTIME_LIB_ROOT = RUNTIME_ROOT / "lib"
RESEARCH_LIB_ROOT = RUNTIME_LIB_ROOT / "research"
SKILLS_ROOT = REPO_ROOT / "skills"
MAINTAINER_NAVIGATOR_ROOT = REPO_ROOT / "tools" / "research-navigator"


def source_path(relative_path: str | Path) -> Path:
    """Map an installed-form logical path to its tracked source location."""

    path = Path(relative_path)
    if path.parts[:2] == (".agents", "skills"):
        return SKILLS_ROOT.joinpath(*path.parts[2:])
    if path.parts[:3] == (".agents", "lib", "research"):
        return RESEARCH_LIB_ROOT.joinpath(*path.parts[3:])
    return REPO_ROOT / path


def install_test_workspace_rules(root: str | Path) -> Path:
    """Install the tracked minimal rule layer into an isolated test workspace."""

    workspace = Path(root).absolute()
    workspace.mkdir(parents=True, exist_ok=True)
    rules = workspace / ".agents" / "WORKSPACE_RULES.md"
    rules.parent.mkdir(parents=True, exist_ok=True)
    rules.write_bytes((REPO_ROOT / "runtime" / "WORKSPACE_RULES.md").read_bytes())
    return workspace


def initialize_test_workspace(root: str | Path) -> Path:
    """Activate and seed an isolated workspace through the explicit test owner."""

    workspace = install_test_workspace_rules(root)
    from research.workspace_layout import initialize_workspace_layout
    from research.prefs import ensure_workspace

    initialize_workspace_layout(workspace, REPO_ROOT)
    ensure_workspace(workspace)
    return workspace

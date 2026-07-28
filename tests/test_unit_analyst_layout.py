from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

from research.analyzer_registry import UNIT_ANALYZER_ROUTES


LEGACY_OWNER_BY_KIND = {
    "paper": "paper-analyst",
    "repo": "repo-analyst",
    "dataset": "dataset-analyst",
    "blog": "blog-analyst",
}

RUNTIME_ROUTE_CONSUMERS = (
    ".agents/lib/research/common.py",
    ".agents/skills/source-intake/scripts/intake.py",
    ".agents/skills/knowledge-base-manager/scripts/kb.py",
    ".agents/skills/kb-cli/scripts/kb",
    ".agents/skills/research-orchestrator/scripts/orchestrate.py",
)


def test_unit_analyzer_registry_owns_every_canonical_implementation() -> None:
    assert set(UNIT_ANALYZER_ROUTES) == set(LEGACY_OWNER_BY_KIND)
    for kind, route in UNIT_ANALYZER_ROUTES.items():
        assert route.owner == LEGACY_OWNER_BY_KIND[kind]
        assert route.script == f".agents/skills/unit-analyst/scripts/{kind}.py"
        implementation = REPO_ROOT / route.script
        assert implementation.is_file()
        assert route.owner in implementation.read_text(encoding="utf-8")


def test_old_analyzer_paths_are_thin_compatibility_launchers() -> None:
    for kind, owner in LEGACY_OWNER_BY_KIND.items():
        launcher = REPO_ROOT / ".agents" / "skills" / owner / "scripts" / f"{kind}.py"
        text = launcher.read_text(encoding="utf-8")
        tree = ast.parse(text)
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        assert functions == ["main"]
        assert "runpy.run_path" in text
        assert '"unit-analyst" / "scripts"' in text
        assert len(text.splitlines()) <= 15


def test_runtime_routes_do_not_reintroduce_legacy_script_paths() -> None:
    legacy_paths = {
        f".agents/skills/{owner}/scripts/{kind}.py"
        for kind, owner in LEGACY_OWNER_BY_KIND.items()
    }
    for relative_path in RUNTIME_ROUTE_CONSUMERS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert legacy_paths.isdisjoint(text.split())
        for legacy_path in legacy_paths:
            assert legacy_path not in text


def test_legacy_launchers_forward_to_the_same_cli() -> None:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_PYTHON": sys.executable,
    }
    for kind, owner in LEGACY_OWNER_BY_KIND.items():
        canonical = REPO_ROOT / UNIT_ANALYZER_ROUTES[kind].script
        legacy = REPO_ROOT / ".agents" / "skills" / owner / "scripts" / f"{kind}.py"
        results = [
            subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            for script in (canonical, legacy)
        ]
        assert [result.returncode for result in results] == [0, 0]
        assert results[0].stdout == results[1].stdout
        assert results[0].stderr == results[1].stderr

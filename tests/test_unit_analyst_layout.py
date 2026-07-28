from __future__ import annotations

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


def test_old_analyzer_resource_directories_are_removed() -> None:
    for owner in LEGACY_OWNER_BY_KIND.values():
        assert not (REPO_ROOT / ".agents" / "skills" / owner).exists()


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

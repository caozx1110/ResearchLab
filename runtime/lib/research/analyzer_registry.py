"""Canonical runtime routes for the unified unit-analyst facade.

Physical script ownership is unified here.  Durable owner names intentionally
remain the historical analyzer identities because they are persisted in
preferences, journals, receipts, provenance, and diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitAnalyzerRoute:
    kind: str
    owner: str
    script: str
    prepare_operation: str
    id_argument: str


UNIT_ANALYZER_ROUTES: dict[str, UnitAnalyzerRoute] = {
    "paper": UnitAnalyzerRoute(
        kind="paper",
        owner="paper-analyst",
        script=".agents/skills/unit-analyst/scripts/paper.py",
        prepare_operation="complete-note",
        id_argument="--paper-id",
    ),
    "repo": UnitAnalyzerRoute(
        kind="repo",
        owner="repo-analyst",
        script=".agents/skills/unit-analyst/scripts/repo.py",
        prepare_operation="map-capability",
        id_argument="--repo-id",
    ),
    "dataset": UnitAnalyzerRoute(
        kind="dataset",
        owner="dataset-analyst",
        script=".agents/skills/unit-analyst/scripts/dataset.py",
        prepare_operation="profile",
        id_argument="--dataset-id",
    ),
    "blog": UnitAnalyzerRoute(
        kind="blog",
        owner="blog-analyst",
        script=".agents/skills/unit-analyst/scripts/blog.py",
        prepare_operation="complete-note",
        id_argument="--blog-id",
    ),
}

UNIT_ANALYZER_SCRIPT_BY_KIND = {
    kind: route.script for kind, route in UNIT_ANALYZER_ROUTES.items()
}
UNIT_ANALYZER_PREPARE_BY_KIND = {
    kind: (route.script, route.prepare_operation, route.id_argument)
    for kind, route in UNIT_ANALYZER_ROUTES.items()
}
UNIT_ANALYZER_ID_ARG_BY_KIND = {
    kind: route.id_argument for kind, route in UNIT_ANALYZER_ROUTES.items()
}

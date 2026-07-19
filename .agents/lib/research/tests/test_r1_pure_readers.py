from __future__ import annotations

from pathlib import Path

from research.index import load_candidate_pools, load_topic_taxonomy
from research.prefs import load_runtime_preferences


def _snapshot(root: Path) -> list[tuple[str, bytes]]:
    if not root.exists():
        return []
    return [
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def test_semantic_loaders_return_defaults_without_creating_workspace(tmp_path: Path) -> None:
    root = tmp_path / "fresh-project"
    before = _snapshot(root)

    preferences = load_runtime_preferences(root)
    taxonomy = load_topic_taxonomy(root)
    pools = load_candidate_pools(root)

    assert preferences["autonomy"]["auto_execute_scope"]
    assert taxonomy["id"] == "topic-taxonomy"
    assert taxonomy["topics"] == {}
    assert pools["id"] == "candidate-pools"
    assert pools["pools"] == {}
    assert _snapshot(root) == before
    assert not root.exists()

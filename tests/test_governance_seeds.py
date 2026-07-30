from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

import research.index as index_module
from research.common import load_yaml, write_yaml_if_changed
from research.core import (
    ensure_workspace,
    load_candidate_pools,
    load_topic_taxonomy,
    rebuild_governance_catalogs,
    record_path,
    write_candidate_pools,
    write_topic_taxonomy,
)


def _load_config_module():
    script = REPO_ROOT / "skills" / "research-config-manager" / "scripts" / "config.py"
    spec = importlib.util.spec_from_file_location("governance_seed_config", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_record(root: Path, record: dict) -> None:
    write_yaml_if_changed(record_path(root, record["kind"], record["id"]), record)


def _seed_governance(root: Path) -> None:
    """Write zero-member taxonomy/pool seeds (as research-config-manager would)."""
    taxonomy = load_topic_taxonomy(root)
    taxonomy.setdefault("topics", {})["seed-topic"] = {
        "id": "seed-topic",
        "aliases": ["seed-alias"],
        "tags": [],
        "pools": [],
        "member_ids": [],
        "count": 0,
        "note": "pre-intake seed",
        "status": "seed",
    }
    taxonomy.setdefault("tags", {})["seed-tag"] = {
        "id": "seed-tag",
        "aliases": [],
        "topic_hints": [],
        "pools": [],
        "member_ids": [],
        "count": 0,
        "note": "",
        "status": "seed",
    }
    write_topic_taxonomy(root, taxonomy)

    pools = load_candidate_pools(root)
    pools.setdefault("pools", {})["seed-pool"] = {
        "id": "seed-pool",
        "summary": "pre-intake pool seed",
        "topic_hints": [],
        "tags": [],
        "member_ids": [],
        "kinds": [],
        "status": "seed",
    }
    write_candidate_pools(root, pools)


def test_config_seed_writers_advance_catalog_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _load_config_module()
    ensure_workspace(tmp_path)
    timestamps = iter(
        [
            "2026-07-29T01:00:00+00:00",
            "2026-07-29T01:00:01+00:00",
        ]
    )
    monkeypatch.setattr(index_module, "utc_now_iso", lambda: next(timestamps))

    taxonomy_path = config.upsert_taxonomy_seed(
        tmp_path,
        topic="robot learning",
        aliases=[],
        tags=[],
        note="",
        status="active",
    )
    pools_path = config.upsert_pool(
        tmp_path,
        pool="reading",
        topics=[],
        tags=[],
        description="",
        status="active",
    )

    assert load_yaml(taxonomy_path)["generated_at"] == "2026-07-29T01:00:00+00:00"
    assert load_yaml(pools_path)["generated_at"] == "2026-07-29T01:00:01+00:00"


def test_rebuild_preserves_zero_member_seeds(tmp_path: Path) -> None:
    """B2: rebuild_governance_catalogs must not drop config-manager's empty seeds."""
    ensure_workspace(tmp_path)
    _seed_governance(tmp_path)

    rebuild_governance_catalogs(tmp_path)

    taxonomy = load_topic_taxonomy(tmp_path)
    pools = load_candidate_pools(tmp_path)

    assert "seed-topic" in taxonomy.get("topics", {}), "zero-member topic seed was dropped"
    assert "seed-tag" in taxonomy.get("tags", {}), "zero-member tag seed was dropped"
    assert "seed-pool" in pools.get("pools", {}), "zero-member pool seed was dropped"
    # metadata is carried through, not blanked
    assert taxonomy["topics"]["seed-topic"]["note"] == "pre-intake seed"
    assert taxonomy["topics"]["seed-topic"]["aliases"] == ["seed-alias"]


def test_rebuild_still_aggregates_record_backed_entries(tmp_path: Path) -> None:
    """Seed preservation must not suppress normal record-driven rebuild."""
    ensure_workspace(tmp_path)
    _seed_governance(tmp_path)
    _write_record(
        tmp_path,
        {
            "id": "p-real-000001",
            "kind": "paper",
            "title": "Real Paper",
            "topics": ["real-topic"],
            "tags": ["real-tag"],
            "candidate_pools": ["real-pool"],
            "source": {"original_uri": "", "file_hash": ""},
        },
    )

    rebuild_governance_catalogs(tmp_path)

    taxonomy = load_topic_taxonomy(tmp_path)
    pools = load_candidate_pools(tmp_path)

    # record-backed entries are rebuilt with membership...
    assert "p-real-000001" in taxonomy["topics"]["real-topic"]["member_ids"]
    assert "p-real-000001" in pools["pools"]["real-pool"]["member_ids"]
    # ...while the empty seeds still survive alongside them
    assert "seed-topic" in taxonomy["topics"]
    assert "seed-pool" in pools["pools"]

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import time
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest
import yaml

import research.index as index_module
from research.index import (
    build_index,
    governance_catalog_drift,
    load_candidate_pools,
    load_topic_taxonomy,
)
from research.prefs import ensure_workspace
from research.core import default_record, write_record


def _load_intake():
    script = REPO_ROOT / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("r5_batch_intake", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_script(skill: str, script_name: str, module_name: str):
    script = REPO_ROOT / ".agents" / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    return root


def _item(kind: str, source: Path) -> str:
    return json.dumps(
        {"kind": kind, "source": str(source), "maturity": "lightweight"},
        sort_keys=True,
    )


def _canonical_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and "/.journal/" not in f"/{path.relative_to(root).as_posix()}/"
    }


def _root_journals(root: Path) -> list[dict]:
    rows = []
    for path in sorted((root / "kb" / ".journal").glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and int(payload.get("transaction_depth") or 0) == 0:
            rows.append(payload)
    return rows


def test_batch_add_materializes_two_items_under_one_root_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    first = source_root / "first.md"
    second = source_root / "second.md"
    first.write_text("# First\n\nBatch evidence one.\n", encoding="utf-8")
    second.write_text("# Second\n\nBatch evidence two.\n", encoding="utf-8")
    checkpoints: list[dict] = []
    monkeypatch.setattr(
        intake,
        "checkpoint_and_report",
        lambda *_args, **kwargs: checkpoints.append(kwargs) or {"committed": False},
    )

    payload = intake._run_batch_add(root, [_item("blog", first), _item("blog", second)])

    assert payload["created_count"] == 2
    assert payload["duplicate_count"] == 0
    records = list((root / "kb" / "units" / "blogs").glob("*/record.yaml"))
    assert len(records) == 2
    roots = [row for row in _root_journals(root) if row.get("op_type") == "source-intake-batch-add"]
    assert len(roots) == 1
    assert roots[0]["state"] == "commit"
    assert len(checkpoints) == 1
    checkpoint_targets = {Path(path) for path in checkpoints[0]["target_paths"]}
    assert checkpoint_targets == {
        *(path.parent for path in records),
        *(root / "kb" / ".runtime" / "intake-staging" / "legacy-failed-units" / path.parent.name for path in records),
        root / "kb" / "config" / "topic-taxonomy.yaml",
        root / "kb" / "config" / "candidate-pools.yaml",
        root / "kb" / "index.yaml",
        root / "kb" / "index.md",
    }


def test_batch_add_merges_same_byte_inputs_in_request_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    first = tmp_path / "same-a.md"
    second = tmp_path / "same-b.md"
    first.write_text("# Same\n\nIdentical frozen bytes.\n", encoding="utf-8")
    second.write_bytes(first.read_bytes())
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})

    payload = intake._run_batch_add(root, [_item("blog", first), _item("blog", second)])

    assert payload["created_count"] == 1
    assert payload["duplicate_count"] == 1
    assert [item["status"] for item in payload["results"]] == ["created", "merged"]
    assert payload["results"][0]["unit_id"] == payload["results"][1]["unit_id"]
    assert len(list((root / "kb" / "units" / "blogs").glob("*/record.yaml"))) == 1


def test_batch_add_current_canonical_duplicate_is_idempotent_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    source = tmp_path / "replay.md"
    source.write_text("# Replay\n\nStable frozen source.\n", encoding="utf-8")
    checkpoints: list[dict] = []
    monkeypatch.setattr(
        intake,
        "checkpoint_and_report",
        lambda *_args, **kwargs: checkpoints.append(kwargs) or {},
    )
    created = intake._run_batch_add(root, [_item("blog", source)])
    before_replay = _canonical_snapshot(root)

    replayed = intake._run_batch_add(root, [_item("blog", source)])

    assert created["created_count"] == 1
    assert replayed["created_count"] == 0
    assert replayed["duplicate_count"] == 1
    assert replayed["results"] == [
        {
            "status": "duplicate",
            "kind": "blog",
            "unit_id": created["results"][0]["unit_id"],
        }
    ]
    assert _canonical_snapshot(root) == before_replay
    assert len(checkpoints) == 1


def test_batch_add_stale_second_prepared_token_writes_no_canonical_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    first = tmp_path / "stale-a.md"
    second = tmp_path / "stale-b.md"
    first.write_text("# A\n\nFirst frozen source.\n", encoding="utf-8")
    second.write_text("# B\n\nSecond frozen source.\n", encoding="utf-8")
    before = _canonical_snapshot(root)
    original_claim = intake._claim_prepared_intake
    claims = 0

    def expire_second_before_claim(current_root: Path, token: str) -> None:
        nonlocal claims
        claims += 1
        if claims == 2:
            _expire_prepared_manifest(intake, intake._prepared_dir(current_root, token))
        original_claim(current_root, token)

    monkeypatch.setattr(intake, "_claim_prepared_intake", expire_second_before_claim)
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})

    with pytest.raises(SystemExit, match="expired"):
        intake._run_batch_add(root, [_item("blog", first), _item("blog", second)])

    assert _canonical_snapshot(root) == before
    assert not list((root / "kb" / "units" / "blogs").glob("*/record.yaml"))
    assert all(
        row.get("op_type") != "source-intake-batch-add" for row in _root_journals(root)
    )


def test_batch_add_late_write_failure_rolls_back_every_canonical_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    first = tmp_path / "rollback-a.md"
    second = tmp_path / "rollback-b.md"
    first.write_text("# A\n\nFirst frozen source.\n", encoding="utf-8")
    second.write_text("# B\n\nSecond frozen source.\n", encoding="utf-8")
    before = _canonical_snapshot(root)
    original = intake._materialize_staged_source
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second-item write fault")
        return original(*args, **kwargs)

    monkeypatch.setattr(intake, "_materialize_staged_source", fail_second)
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})

    with pytest.raises(OSError, match="second-item write fault"):
        intake._run_batch_add(root, [_item("blog", first), _item("blog", second)])

    assert _canonical_snapshot(root) == before
    assert not list((root / "kb" / "units" / "blogs").glob("*/record.yaml"))
    roots = [row for row in _root_journals(root) if row.get("op_type") == "source-intake-batch-add"]
    assert len(roots) == 1
    assert roots[0]["state"] == "abort"


def test_batch_add_late_source_drift_rolls_back_every_canonical_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    first = tmp_path / "drift-a.md"
    second = tmp_path / "drift-b.md"
    first.write_text("# A\n\nFirst frozen source.\n", encoding="utf-8")
    second.write_text("# B\n\nSecond frozen source.\n", encoding="utf-8")
    before = _canonical_snapshot(root)
    original = intake._materialize_staged_source
    calls = 0

    def drift_after_first(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            first.write_text("# A\n\nChanged after publication began.\n", encoding="utf-8")
        return result

    monkeypatch.setattr(intake, "_materialize_staged_source", drift_after_first)
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})

    with pytest.raises(RuntimeError, match="source changed before commit"):
        intake._run_batch_add(root, [_item("blog", first), _item("blog", second)])

    assert _canonical_snapshot(root) == before
    assert not list((root / "kb" / "units" / "blogs").glob("*/record.yaml"))
    roots = [row for row in _root_journals(root) if row.get("op_type") == "source-intake-batch-add"]
    assert len(roots) == 1
    assert roots[0]["state"] == "abort"


def test_batch_add_rejects_more_than_twenty_before_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    calls = 0

    def unexpected_prepare(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("preparation must not start")

    monkeypatch.setattr(intake, "_prepare_intake_snapshot", unexpected_prepare)

    with pytest.raises(SystemExit, match="1..20"):
        intake._run_batch_add(
            root,
            [json.dumps({"kind": "blog", "source": f"item-{index}"}) for index in range(21)],
        )

    assert calls == 0


def _expire_prepared_manifest(intake, prepared_root: Path) -> None:
    path = prepared_root / "prepared.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at_epoch"] = int(time.time()) - intake.PREPARED_INTAKE_TTL_SECONDS - 1
    payload.pop("manifest_digest", None)
    payload["manifest_digest"] = intake._canonical_digest(payload)
    intake._write_prepared_manifest(path, payload)


def test_prepared_gardening_removes_only_provably_safe_expired_tree(
    tmp_path: Path,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    source = tmp_path / "expired.md"
    source.write_text("# Expired\n\nFrozen source.\n", encoding="utf-8")
    args = intake._batch_item_args(_item("blog", source))
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    prepared_root = intake._prepared_dir(root, token)
    _expire_prepared_manifest(intake, prepared_root)

    result = intake._garden_prepared_intakes(root)

    assert result["removed_tokens"] == [token]
    assert result["active_tokens"] == []
    assert result["retained"] == []
    assert not prepared_root.exists()


def test_prepared_gardening_retains_active_symlink_special_and_unknown_trees(
    tmp_path: Path,
) -> None:
    intake = _load_intake()
    root = _workspace(tmp_path)
    source = tmp_path / "active.md"
    source.write_text("# Active\n\nFrozen source.\n", encoding="utf-8")
    args = intake._batch_item_args(_item("blog", source))

    active = intake._prepare_intake_snapshot(root, args)
    active_token = str(active["token"])
    active_root = intake._prepared_dir(root, active_token)
    _expire_prepared_manifest(intake, active_root)
    intake._claim_prepared_intake(root, active_token)

    linked = intake._prepare_intake_snapshot(root, args)
    linked_token = str(linked["token"])
    linked_root = intake._prepared_dir(root, linked_token)
    _expire_prepared_manifest(intake, linked_root)
    (linked_root / "unsafe-link").symlink_to(source)

    special = intake._prepare_intake_snapshot(root, args)
    special_token = str(special["token"])
    special_root = intake._prepared_dir(root, special_token)
    _expire_prepared_manifest(intake, special_root)
    os.mkfifo(special_root / "unsafe-fifo", 0o600)

    unknown_token = "f" * 32
    unknown_root = intake._prepared_dir(root, unknown_token)
    unknown_root.mkdir(mode=0o700)
    unknown_root.chmod(0o700)
    unknown_name_root = root.parent / (
        f".research-intake-{intake._prepared_scope(root)}-unknown-creating-tree"
    )
    unknown_name_root.mkdir(mode=0o700)

    result = intake._garden_prepared_intakes(root)

    assert active_token in result["active_tokens"]
    assert {item["name"] for item in result["retained"]} == {
        linked_root.name,
        special_root.name,
        unknown_root.name,
        unknown_name_root.name,
    }
    assert linked_root.is_dir()
    assert special_root.is_dir()
    assert stat.S_ISFIFO((special_root / "unsafe-fifo").lstat().st_mode)
    assert unknown_root.is_dir()
    assert unknown_name_root.is_dir()

    intake._safe_remove_prepared(root, active_token)
    (linked_root / "unsafe-link").unlink()
    intake._safe_remove_prepared(root, linked_token)
    (special_root / "unsafe-fifo").unlink()
    intake._safe_remove_prepared(root, special_token)
    intake._safe_remove_prepared(root, unknown_token)
    unknown_name_root.rmdir()


def test_governance_drift_candidate_disappears_after_mechanical_rebuild(
    tmp_path: Path,
) -> None:
    orchestrate = _load_script(
        "research-orchestrator",
        "orchestrate.py",
        "r5_gardening_orchestrator",
    )
    root = _workspace(tmp_path)
    record = default_record(
        "blog",
        title="Gardening Source",
        maturity="lightweight",
        source={"original_uri": "https://example.test/gardening"},
    )
    record["topics"] = ["robot-learning"]
    record["tags"] = ["taxonomy-drift"]
    record["candidate_pools"] = ["reading"]
    write_record(root, record)

    assert governance_catalog_drift(root)["stale"] is True
    stale_snapshot = orchestrate.portfolio_candidate_snapshot(root)
    candidate = next(
        item for item in stale_snapshot["candidates"] if item["action_type"] == "rebuild-taxonomy"
    )
    assert candidate["owner_skill"] == "knowledge-base-manager"
    assert candidate["safe_execute_capability"] is False

    build_index(root)

    assert governance_catalog_drift(root)["stale"] is False
    current_snapshot = orchestrate.portfolio_candidate_snapshot(root)
    assert all(item["action_type"] != "rebuild-taxonomy" for item in current_snapshot["candidates"])


def test_governance_drift_and_loaders_are_clock_independent_after_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    build_index(root)
    expected_taxonomy = load_topic_taxonomy(root)
    expected_pools = load_candidate_pools(root)
    expected_drift = governance_catalog_drift(root)
    assert expected_drift["stale"] is False

    def reject_read_time_clock() -> str:
        raise AssertionError("governance catalog readers must not consult the clock")

    monkeypatch.setattr(index_module, "utc_now_iso", reject_read_time_clock)

    assert load_topic_taxonomy(root) == expected_taxonomy
    assert load_candidate_pools(root) == expected_pools
    current_drift = governance_catalog_drift(root)
    assert current_drift == expected_drift


def test_rebuild_governance_checkpoints_exact_catalog_and_index_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _load_script(
        "knowledge-base-manager",
        "kb.py",
        "r5_gardening_manager",
    )
    root = _workspace(tmp_path)
    record = default_record(
        "blog",
        title="Checkpoint Source",
        maturity="lightweight",
        source={"original_uri": "https://example.test/checkpoint"},
    )
    record["topics"] = ["checkpoint-topic"]
    write_record(root, record)
    checkpoints: list[dict] = []
    monkeypatch.setattr(
        manager,
        "checkpoint_and_report",
        lambda *_args, **kwargs: checkpoints.append(kwargs) or {"committed": False},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(manager.SCRIPT_PATH), "--root", str(root), "rebuild-governance"],
    )

    assert manager.main() == 0

    assert governance_catalog_drift(root)["stale"] is False
    assert len(checkpoints) == 1
    assert set(checkpoints[0]["target_paths"]) == {
        root / "kb" / "config" / "topic-taxonomy.yaml",
        root / "kb" / "config" / "candidate-pools.yaml",
        root / "kb" / "index.yaml",
        root / "kb" / "index.md",
    }

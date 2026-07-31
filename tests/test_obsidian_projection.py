from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import os
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest
import yaml

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, link_records, record_path, undo_last_operation
from research.git_ops import restore_operation
from research.journal import begin_op, incomplete_ops
from research.obsidian import (
    OBSIDIAN_RENDERER_REVISION,
    obsidian_managed_root,
    obsidian_projection_status,
    preview_obsidian_base_presentation_reset,
    reset_obsidian_base_presentation_drift,
    update_obsidian_projection,
)
from research.relations import project_relation_edges
import research.obsidian as obsidian_module


class _ObsidianBaseDumper(yaml.SafeDumper):
    """Mirror the stable block-sequence indentation written by Obsidian 1.12.7."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)


def _load_kb_cli():
    project_root = REPO_ROOT
    script = project_root / "skills/kb-cli/scripts/kb"
    loader = importlib.machinery.SourceFileLoader("kb_cli_obsidian_tests", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _record(root: Path, unit_id: str, title: str, *, topic: str = "robotics") -> dict:
    record = default_record("paper", title=title, maturity="complete")
    record["id"] = unit_id
    record["status"] = "active"
    record["summary"] = f"Summary for {title}."
    record["topics"] = [topic]
    record["tags"] = ["vla"]
    record["confirmation_status"] = "auto_confirmed"
    record["needs_human_confirmation"] = False
    write_yaml_if_changed(record_path(root, "paper", unit_id), record)
    return record


def _write_program(root: Path, *unit_ids: str) -> None:
    write_yaml_if_changed(
        root / "kb/programs/humanoid-vla/state.yaml",
        {
            "id": "humanoid-vla-state",
            "program_id": "humanoid-vla",
            "status": "active",
            "stage": "survey",
            "goal": "Map the technical route.",
            "question": "How do the methods relate?",
            "active_unit_ids": list(unit_ids),
            "next_actions": [{"summary": "Compare the methods", "status": "open"}],
        },
    )


def _write_taxonomy(root: Path) -> None:
    write_yaml_if_changed(
        root / "kb/config/topic-taxonomy.yaml",
        {
            "id": "topic-taxonomy",
            "topics": {"robotics": {"id": "robotics", "aliases": ["Robotics"]}},
            "tags": {},
        },
    )


def _journal_entries(root: Path) -> list[Path]:
    return sorted((root / "kb/.journal").glob("*.yaml"))


def test_link_records_stores_one_forward_edge_with_block_locator(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    _record(tmp_path, "p-beta-12345678", "Beta")

    link_records(
        tmp_path,
        "p-alpha-12345678",
        "p-beta-12345678",
        "builds-on",
        source_locator={"kind": "heading", "value": "Claims"},
        target_locator={"kind": "block", "value": "Claim Beta"},
    )

    alpha = load_yaml(record_path(tmp_path, "paper", "p-alpha-12345678"), default={})
    beta = load_yaml(record_path(tmp_path, "paper", "p-beta-12345678"), default={})
    assert alpha["links"] == [
        {
            "target_id": "p-beta-12345678",
            "relation": "builds_on",
            "note": "",
            "source_locator": {"kind": "heading", "value": "Claims"},
            "target_locator": {"kind": "block", "value": "claim-beta"},
        }
    ]
    assert beta["links"] == []

    link_records(
        tmp_path,
        "p-alpha-12345678",
        "p-beta-12345678",
        "builds-on",
        note="Updated relationship note",
        source_locator={"kind": "heading", "value": "Claims"},
        target_locator={"kind": "block", "value": "Claim Beta"},
    )
    updated = load_yaml(record_path(tmp_path, "paper", "p-alpha-12345678"), default={})
    assert len(updated["links"]) == 1
    assert updated["links"][0]["note"] == "Updated relationship note"
    assert updated["history"][-1]["action"] == "link_updated"


def test_projector_builds_native_pages_bases_and_precise_backlinks(tmp_path: Path) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    beta = _record(tmp_path, "p-beta-12345678", "Beta")
    alpha["program_ids"] = ["humanoid-vla"]
    alpha["links"] = [
        {
            "target_id": beta["id"],
            "relation": "supports",
            "target_locator": {"kind": "block", "value": "claim-beta"},
            "note": "Independent result",
        }
    ]
    beta["payload"]["claims"] = [
        {
            "id": "claim-beta",
            "text": "Beta remains stable on the evaluated task.",
            "claim_type": "fact",
            "confirmation_status": "auto_confirmed",
            "evidence_refs": [
                {
                    "source_unit_id": beta["id"],
                    "artifact": "parse-cache.md",
                    "locator": "page=8;table=3",
                    "quote": "stable on the evaluated task",
                }
            ],
        }
    ]
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)
    write_yaml_if_changed(record_path(tmp_path, "paper", beta["id"]), beta)
    _write_program(tmp_path, alpha["id"], beta["id"])
    _write_taxonomy(tmp_path)
    canonical_before = {
        alpha["id"]: record_path(tmp_path, "paper", alpha["id"]).read_bytes(),
        beta["id"]: record_path(tmp_path, "paper", beta["id"]).read_bytes(),
    }

    result = update_obsidian_projection(tmp_path)

    assert result["changed"] is True
    assert result["status"]["status"] == "PASS"
    managed = obsidian_managed_root(tmp_path)
    alpha_page = (managed / "units/p-alpha-12345678.md").read_text(encoding="utf-8")
    beta_page = (managed / "units/p-beta-12345678.md").read_text(encoding="utf-8")
    assert "[[obsidian/managed/units/p-beta-12345678#^claim-beta|Beta]]" in alpha_page
    assert "### supported_by" in beta_page
    assert "[[obsidian/managed/units/p-alpha-12345678|Alpha]]" in beta_page
    assert "Beta remains stable on the evaluated task. ^claim-beta" in beta_page
    assert "^evidence-claim-beta-001" in beta_page
    assert "'[[obsidian/managed/topics/robotics|robotics]]'" in beta_page
    assert (managed / "programs/humanoid-vla.md").is_file()
    assert (managed / "topics/robotics.md").is_file()
    for base_name in ("All Units.base", "Pending Review.base", "By Topic.base"):
        payload = load_yaml(managed / "dashboards" / base_name, default={})
        assert payload["filters"]["and"][0] == 'file.inFolder("obsidian/managed/units")'
        assert payload["views"][0]["type"] == "table"
        assert "title" in payload["views"][0]["order"]
        assert all(not item.startswith("note.") for item in payload["views"][0]["order"])
    manifest = load_yaml(managed / "manifest.yaml", default={})
    assert manifest["schema"] == "research-kb-obsidian/v1"
    assert manifest["renderer_revision"] == OBSIDIAN_RENDERER_REVISION
    assert manifest["record_count"] == 2
    assert (tmp_path / "kb/obsidian/inbox").is_dir()
    assert (tmp_path / "kb/obsidian/annotations").is_dir()
    assert not (tmp_path / "kb/.obsidian").exists()
    assert "obsidian/managed/" in (tmp_path / "kb/.gitignore").read_text(encoding="utf-8")
    assert record_path(tmp_path, "paper", alpha["id"]).read_bytes() == canonical_before[alpha["id"]]
    assert record_path(tmp_path, "paper", beta["id"]).read_bytes() == canonical_before[beta["id"]]

    journals_before = _journal_entries(tmp_path)
    second = update_obsidian_projection(tmp_path)
    assert second["changed"] is False
    assert _journal_entries(tmp_path) == journals_before


def test_bases_are_byte_stable_after_obsidian_1_12_save_normalization(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)

    for base_name in ("All Units.base", "Pending Review.base", "By Topic.base"):
        path = managed / "dashboards" / base_name
        original = path.read_text(encoding="utf-8")
        payload = yaml.safe_load(original)
        normalized = yaml.dump(
            payload,
            Dumper=_ObsidianBaseDumper,
            allow_unicode=True,
            sort_keys=False,
            width=1_000_000,
        )
        assert normalized == original

    assert obsidian_projection_status(tmp_path)["status"] == "PASS"
    assert update_obsidian_projection(tmp_path)["changed"] is False


def _apply_obsidian_1_12_7_title_sort(path: Path, *, direction: str = "ASC") -> None:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["views"][0]["sort"] = [{"property": "title", "direction": direction}]
    path.write_text(
        yaml.dump(
            payload,
            Dumper=_ObsidianBaseDumper,
            allow_unicode=True,
            sort_keys=False,
            width=1_000_000,
        ),
        encoding="utf-8",
    )


def test_obsidian_1_12_7_sort_fixture_previews_and_resets_without_canonical_write(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, "p-alpha-12345678", "Alpha")
    canonical_path = record_path(tmp_path, "paper", record["id"])
    canonical_before = canonical_path.read_bytes()
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    annotation = tmp_path / "kb/obsidian/annotations/human-note.md"
    annotation.write_text("human note\n", encoding="utf-8")
    annotation_before = annotation.read_bytes()
    names = ("All Units.base", "Pending Review.base", "By Topic.base")
    fixture_root = REPO_ROOT / "tests/fixtures/obsidian-1.12.7-base-sort"
    fixture_metadata = load_yaml(fixture_root / "metadata.yaml", default={})
    assert fixture_metadata["version"] == "1.12.7"
    assert fixture_metadata["all_other_fields_equal"] is True
    expected_before = {
        "All Units.base": "225178cc9efdc7da8eaf19d8140bed725d46f8796c576d9e79848334458accce",
        "Pending Review.base": "89e0fc53eac06a784aa9d0a2b1f9649e2807928ccbf2c526bae1978ed18ba0d6",
        "By Topic.base": "120e04eab3289bd1db8093d9f50237fcae831a31e2970b1776d712cbe93b9837",
    }
    expected_after = {
        "All Units.base": "6101e230e01b7e1fa46ccbd4b4fe1578a87ee14be93bff1b31861e2af904b617",
        "Pending Review.base": "f37b705601bf4c65a7c88831fe6591a3e0ffa44ffbb7bcfce6537392fb856d46",
        "By Topic.base": "6767349dcc4455bbc8fa1b6b8458776d5b69acc279cba7ff9828a8b7ebdaf18e",
    }
    original_bytes: dict[str, bytes] = {}
    for name in names:
        path = managed / "dashboards" / name
        original_bytes[name] = path.read_bytes()
        assert hashlib.sha256(original_bytes[name]).hexdigest() == expected_before[name]
        if name == "All Units.base":
            assert original_bytes[name] == (fixture_root / "before.base").read_bytes()
        _apply_obsidian_1_12_7_title_sort(path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_after[name]
        if name == "All Units.base":
            assert path.read_bytes() == (fixture_root / "after.base").read_bytes()

    journals_before_preview = _journal_entries(tmp_path)
    ledger_root = tmp_path / "kb/.runtime/obsidian-base-presentation-reset"
    assert not ledger_root.exists()
    drift_bytes = {name: (managed / "dashboards" / name).read_bytes() for name in names}
    report = obsidian_projection_status(tmp_path)
    assert report["status"] == "WARN"
    assert [item["code"] for item in report["findings"]].count(
        "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT"
    ) == 3
    assert "OBSIDIAN_MANAGED_FILE_DRIFT" not in {item["code"] for item in report["findings"]}

    preview = preview_obsidian_base_presentation_reset(tmp_path)

    assert preview["status"] == "needs_user_authorization"
    assert preview["file_count"] == 3
    assert preview["sort_count"] == 3
    assert len(preview["preview_digest"]) == 64
    assert _journal_entries(tmp_path) == journals_before_preview
    assert not ledger_root.exists()
    assert {name: (managed / "dashboards" / name).read_bytes() for name in names} == drift_bytes
    with pytest.raises(SystemExit, match="human-edited"):
        update_obsidian_projection(tmp_path)
    with pytest.raises(SystemExit, match="current-message"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="Agent inferred approval",
            authorization_source="agent_inference",
        )
    assert {name: (managed / "dashboards" / name).read_bytes() for name in names} == drift_bytes

    reset = reset_obsidian_base_presentation_drift(
        tmp_path,
        expected_preview_digest=preview["preview_digest"],
        expected_preview_token=preview["preview_token"],
        user_authorization="请按刚才的预览重置这三个 Base 的展示排序并刷新视图",
        authorization_source="user_message",
    )

    assert reset["changed"] is True
    assert reset["file_count"] == 3
    assert reset["projection_changed"] is False
    assert reset["status"]["status"] == "PASS"
    assert {name: (managed / "dashboards" / name).read_bytes() for name in names} == original_bytes
    assert canonical_path.read_bytes() == canonical_before
    assert annotation.read_bytes() == annotation_before
    journals_after = _journal_entries(tmp_path)
    assert len(journals_after) == len(journals_before_preview) + 1
    repair_journal = load_yaml(journals_after[-1], default={})
    assert repair_journal["op_type"] == "reset_obsidian_base_presentation_sort"
    assert repair_journal["operation_role"] == "derived"
    assert set(repair_journal["target_paths"]) == {
        "obsidian/managed/dashboards/All Units.base",
        "obsidian/managed/dashboards/By Topic.base",
        "obsidian/managed/dashboards/Pending Review.base",
    }
    assert not ledger_root.exists()

    undo_last_operation(tmp_path)

    assert {name: (managed / "dashboards" / name).read_bytes() for name in names} == drift_bytes
    assert canonical_path.read_bytes() == canonical_before
    assert annotation.read_bytes() == annotation_before
    assert not ledger_root.exists()
    with pytest.raises(SystemExit, match="stale"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="replayed authorization after undo",
            authorization_source="user_message",
        )


def test_base_presentation_reset_rejects_stale_preview_and_semantic_or_unknown_sort(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    _apply_obsidian_1_12_7_title_sort(base, direction="DESC")
    changed_after_preview = base.read_bytes()

    with pytest.raises(SystemExit, match="stale"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按预览重置",
            authorization_source="user_message",
        )
    assert base.read_bytes() == changed_after_preview

    payload = yaml.safe_load(base.read_text(encoding="utf-8"))
    payload["views"][0]["name"] = "Semantic rename"
    write_yaml_if_changed(base, payload)
    semantic_bytes = base.read_bytes()
    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)
    report = obsidian_projection_status(tmp_path)
    assert "OBSIDIAN_MANAGED_FILE_DRIFT" in {item["code"] for item in report["findings"]}
    assert base.read_bytes() == semantic_bytes

    payload = yaml.safe_load(semantic_bytes)
    payload["views"][0]["name"] = "All units"
    payload["views"][0]["sort"] = [{"property": "unknown", "direction": "ASC"}]
    write_yaml_if_changed(base, payload)
    unknown_bytes = base.read_bytes()
    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)
    assert base.read_bytes() == unknown_bytes

    payload["views"][0]["sort"] = [{"property": "title", "direction": []}]
    write_yaml_if_changed(base, payload)
    malformed_bytes = base.read_bytes()
    report = obsidian_projection_status(tmp_path)
    assert "OBSIDIAN_MANAGED_FILE_DRIFT" in {item["code"] for item in report["findings"]}
    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)
    assert base.read_bytes() == malformed_bytes


@pytest.mark.parametrize(
    "semantic_mutation",
    ["filter", "order", "group_by", "property", "unknown_key"],
)
def test_base_presentation_sort_never_masks_semantic_drift(
    tmp_path: Path, semantic_mutation: str
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    payload = yaml.safe_load(base.read_text(encoding="utf-8"))
    if semantic_mutation == "filter":
        payload["filters"] = {"and": ['file.ext == "canvas"']}
    elif semantic_mutation == "order":
        payload["views"][0]["order"] = list(reversed(payload["views"][0]["order"]))
    elif semantic_mutation == "group_by":
        payload["views"][0]["groupBy"] = "topics"
    elif semantic_mutation == "property":
        payload["properties"]["manual"] = {"displayName": "Manual"}
    else:
        payload["views"][0]["unknown"] = True
    write_yaml_if_changed(base, payload)
    changed_bytes = base.read_bytes()

    report = obsidian_projection_status(tmp_path)

    assert "OBSIDIAN_MANAGED_FILE_DRIFT" in {item["code"] for item in report["findings"]}
    assert "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT" not in {
        item["code"] for item in report["findings"]
    }
    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)
    with pytest.raises(SystemExit, match="human-edited"):
        update_obsidian_projection(tmp_path)
    assert base.read_bytes() == changed_bytes


def test_base_presentation_reset_rejects_stale_canonical_inputs(tmp_path: Path) -> None:
    record = _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    drift_bytes = base.read_bytes()
    record["summary"] = "Canonical input changed after the preview."
    write_yaml_if_changed(record_path(tmp_path, "paper", record["id"]), record)

    with pytest.raises(SystemExit, match="stale"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按刚才的预览重置",
            authorization_source="user_message",
        )

    assert base.read_bytes() == drift_bytes


def test_base_presentation_reset_rolls_back_multi_file_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path, "p-alpha-12345678", "Alpha")
    canonical_path = record_path(tmp_path, "paper", record["id"])
    canonical_before = canonical_path.read_bytes()
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    paths = [
        managed / "dashboards/All Units.base",
        managed / "dashboards/Pending Review.base",
        managed / "dashboards/By Topic.base",
    ]
    for path in paths:
        _apply_obsidian_1_12_7_title_sort(path)
    drift_bytes = {path: path.read_bytes() for path in paths}
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    original_write = obsidian_module._replace_project_snapshot_bytes
    base_writes = 0

    def fail_second_base_write(
        snapshot,
        data: bytes,
        *,
        staging_fd: int,
        staging_is_current,
        temp_name: str | None = None,
    ) -> None:
        nonlocal base_writes
        base_writes += 1
        if base_writes == 2:
            raise RuntimeError("injected Base write failure")
        original_write(
            snapshot,
            data,
            staging_fd=staging_fd,
            staging_is_current=staging_is_current,
            temp_name=temp_name,
        )

    monkeypatch.setattr(
        obsidian_module,
        "_replace_project_snapshot_bytes",
        fail_second_base_write,
    )

    with pytest.raises(RuntimeError, match="injected Base write failure"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按刚才的预览重置",
            authorization_source="user_message",
        )

    assert {path: path.read_bytes() for path in paths} == drift_bytes
    assert canonical_path.read_bytes() == canonical_before
    report = obsidian_projection_status(tmp_path)
    assert [item["code"] for item in report["findings"]].count(
        "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT"
    ) == 3

    monkeypatch.setattr(
        obsidian_module,
        "_replace_project_snapshot_bytes",
        original_write,
    )
    with pytest.raises(SystemExit, match="stale"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="旧身份绑定不得在 journal 换 inode 后重试",
            authorization_source="user_message",
        )
    fresh = preview_obsidian_base_presentation_reset(tmp_path)
    retried = reset_obsidian_base_presentation_drift(
        tmp_path,
        expected_preview_digest=fresh["preview_digest"],
        expected_preview_token=fresh["preview_token"],
        user_authorization="确认按新的零写预览重试",
        authorization_source="user_message",
    )
    assert retried["changed"] is True
    assert obsidian_projection_status(tmp_path)["status"] == "PASS"


def test_base_presentation_preview_rejects_incomplete_root_journal_without_writes(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    begin_op(
        tmp_path,
        "synthetic-incomplete",
        [tmp_path / "kb/synthetic-incomplete.yaml"],
    )
    assert len(incomplete_ops(tmp_path)) == 1
    base_before = base.read_bytes()
    journal_before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / "kb/.journal").rglob("*")
        if path.is_file()
    }

    with pytest.raises(SystemExit, match="unfinished|incomplete|恢复"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert base.read_bytes() == base_before
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / "kb/.journal").rglob("*")
        if path.is_file()
    } == journal_before


def test_base_presentation_preview_rejects_malformed_journal_without_writes(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    malformed = tmp_path / "kb/.journal/malformed.yaml"
    malformed.write_text("op_id: malformed\nstate: [\n", encoding="utf-8")
    base_before = base.read_bytes()
    malformed_before = malformed.read_bytes()

    with pytest.raises(SystemExit, match="隔离|解析|journal"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert base.read_bytes() == base_before
    assert malformed.read_bytes() == malformed_before


def test_base_atomic_exchange_fails_closed_on_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.write_bytes(b"left\n")
    right.write_bytes(b"right\n")
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(obsidian_module.sys, "platform", "unsupported-test-platform")
    try:
        with pytest.raises(SystemExit, match="unavailable"):
            obsidian_module._atomic_exchange_at(
                descriptor,
                left.name,
                descriptor,
                right.name,
            )
    finally:
        os.close(descriptor)

    assert left.read_bytes() == b"left\n"
    assert right.read_bytes() == b"right\n"


def test_crashed_base_exchange_is_resumed_without_managed_staging_file(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    base = managed / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    drift_bytes = base.read_bytes()
    desired_bytes = obsidian_module._base_projection_files(
        obsidian_module._projection_inputs(tmp_path)
    )["dashboards/All Units.base"].encode("utf-8")
    op_id = begin_op(
        tmp_path,
        "synthetic-crashed-base-exchange",
        [base],
    )
    temp_name = obsidian_module._new_base_exchange_temp_name()
    with obsidian_module._anchored_journal_directory(
        tmp_path,
        f"{obsidian_module.SNAPSHOT_DIRNAME}/{op_id}",
    ) as staging_fd:
        descriptor = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=staging_fd,
        )
        try:
            os.write(descriptor, desired_bytes)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        target_fd = os.open(base.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            obsidian_module._atomic_exchange_at(
                staging_fd,
                temp_name,
                target_fd,
                base.name,
            )
        finally:
            os.close(target_fd)

    assert base.read_bytes() == desired_bytes
    assert list(managed.rglob(".presentation-reset-*.tmp")) == []
    assert len(incomplete_ops(tmp_path)) == 1
    with pytest.raises(SystemExit, match="unfinished|incomplete|恢复"):
        preview_obsidian_base_presentation_reset(tmp_path)

    recovered = restore_operation(tmp_path, op_id, recovery_type="resume")

    assert recovered["op_id"] == op_id
    assert base.read_bytes() == drift_bytes
    assert list(managed.rglob(".presentation-reset-*.tmp")) == []
    assert incomplete_ops(tmp_path) == []
    private_recovery = tmp_path / "kb/.journal/snapshots" / op_id / temp_name
    assert private_recovery.read_bytes() == drift_bytes
    assert preview_obsidian_base_presentation_reset(tmp_path)["status"] == "needs_user_authorization"


def test_public_obsidian_sort_reset_requires_preview_bound_current_authorization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kb = _load_kb_cli()
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    drift_bytes = base.read_bytes()

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "sort-preview.json",
            "obsidian",
            "update",
            "--preview-presentation-reset",
        ]
    ) == 0
    preview_output = capsys.readouterr().out
    assert "尚未修改文件" in preview_output
    assert "dashboards" not in preview_output
    assert base.read_bytes() == drift_bytes
    protocol = load_yaml(tmp_path / "kb/.runtime/sort-preview.json", default={})
    preview_digest = protocol["details"]["obsidian_presentation_reset"]["preview_digest"]
    preview_token = protocol["details"]["obsidian_presentation_reset"]["preview_token"]
    assert protocol["status"] == "needs_user_authorization"

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "sort-no-auth.json",
            "obsidian",
            "update",
            "--apply-presentation-reset",
            "--expected-preview-digest",
            preview_digest,
            "--expected-preview-token",
            preview_token,
        ]
    ) == 2
    assert "未执行" in capsys.readouterr().out
    assert base.read_bytes() == drift_bytes

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "sort-apply.json",
            "obsidian",
            "update",
            "--apply-presentation-reset",
            "--expected-preview-digest",
            preview_digest,
            "--expected-preview-token",
            preview_token,
            "--user-authorization",
            "请按刚才的展示排序预览重置并刷新",
        ]
    ) == 0
    applied_output = capsys.readouterr().out
    assert "已按你的确认安全重置" in applied_output
    assert "dashboards" not in applied_output
    assert obsidian_projection_status(tmp_path)["status"] == "PASS"


@pytest.mark.parametrize("failure_type", [RuntimeError, OSError])
def test_public_obsidian_sort_preview_redacts_expected_safety_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_type: type[BaseException],
) -> None:
    kb = _load_kb_cli()
    private_failure = (
        f"{failure_type.__name__}: reviewer-only /private/preview/path "
        "--expected-preview-token secret-token"
    )

    def fail_preview(*args, **kwargs):
        raise failure_type(private_failure)

    monkeypatch.setattr(kb, "preview_obsidian_base_presentation_reset", fail_preview)
    protocol_name = f"sort-preview-{failure_type.__name__.lower()}-failure.json"

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            protocol_name,
            "obsidian",
            "update",
            "--preview-presentation-reset",
        ]
    ) == 2

    public = capsys.readouterr()
    protocol_bytes = (tmp_path / "kb/.runtime" / protocol_name).read_text(encoding="utf-8")
    combined = public.out + public.err + protocol_bytes
    assert "Obsidian Base 展示排序修复预览未完成" in public.out
    assert private_failure not in combined
    assert "/private/preview/path" not in combined
    assert "secret-token" not in combined
    assert "--expected-preview-token" not in combined
    protocol = load_yaml(tmp_path / "kb/.runtime" / protocol_name, default={})
    assert protocol["status"] == "agent_action_required"
    assert protocol["details"]["obsidian_presentation_reset"] == {
        "status": "safety_failure",
        "code": "preview_safety_failure",
    }


@pytest.mark.parametrize("failure_type", [RuntimeError, OSError])
def test_public_obsidian_sort_reset_redacts_expected_safety_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_type: type[BaseException],
) -> None:
    kb = _load_kb_cli()
    private_failure = (
        f"{failure_type.__name__}: reviewer-only /private/reset/path "
        "--expected-preview-token secret-token"
    )

    def fail_reset(*args, **kwargs):
        raise failure_type(private_failure)

    monkeypatch.setattr(kb, "reset_obsidian_base_presentation_drift", fail_reset)
    protocol_name = f"sort-{failure_type.__name__.lower()}-failure.json"

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            protocol_name,
            "obsidian",
            "update",
            "--apply-presentation-reset",
            "--expected-preview-digest",
            "synthetic-preview-digest",
            "--expected-preview-token",
            "secret-token",
            "--user-authorization",
            "确认按刚才的展示排序预览重置",
        ]
    ) == 2

    public = capsys.readouterr()
    protocol_bytes = (tmp_path / "kb/.runtime" / protocol_name).read_text(encoding="utf-8")
    combined = public.out + public.err + protocol_bytes
    assert "Obsidian Base 展示排序修复未完成" in public.out
    assert private_failure not in combined
    assert "/private/reset/path" not in combined
    assert "secret-token" not in combined
    assert "--expected-preview-token" not in combined
    protocol = load_yaml(tmp_path / "kb/.runtime" / protocol_name, default={})
    assert protocol["status"] == "agent_action_required"
    assert protocol["details"]["obsidian_presentation_reset"] == {
        "status": "safety_failure",
        "code": "reset_safety_failure",
    }


@pytest.mark.parametrize(
    "failure",
    [KeyboardInterrupt(), GeneratorExit(), ValueError("programming error")],
    ids=["keyboard-interrupt", "generator-exit", "programming-error"],
)
@pytest.mark.parametrize("surface", ["preview", "apply"])
def test_public_obsidian_sort_reset_does_not_swallow_unrelated_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    surface: str,
) -> None:
    kb = _load_kb_cli()

    def fail_operation(*args, **kwargs):
        raise failure

    if surface == "preview":
        monkeypatch.setattr(kb, "preview_obsidian_base_presentation_reset", fail_operation)
        operation_args = ["--preview-presentation-reset"]
    else:
        monkeypatch.setattr(kb, "reset_obsidian_base_presentation_drift", fail_operation)
        operation_args = [
            "--apply-presentation-reset",
            "--expected-preview-digest",
            "synthetic-preview-digest",
            "--expected-preview-token",
            "synthetic-preview-token",
            "--user-authorization",
            "确认按刚才的展示排序预览重置",
        ]
    with pytest.raises(type(failure)):
        kb.main(
            [
                "--root",
                str(tmp_path),
                "obsidian",
                "update",
                *operation_args,
            ]
        )


def test_base_presentation_preview_rejects_symlink_special_or_ambiguous_yaml(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    renderer_bytes = base.read_bytes()
    outside = tmp_path / "outside.base"
    outside.write_bytes(renderer_bytes + b"# outside\n")
    outside_before = outside.read_bytes()
    base.unlink()
    base.symlink_to(outside)

    with pytest.raises(SystemExit, match="unsafe or unowned"):
        preview_obsidian_base_presentation_reset(tmp_path)
    assert outside.read_bytes() == outside_before

    base.unlink()
    base.write_bytes(
        renderer_bytes
        + b"views:\n"
        + b"  - type: table\n"
        + b"    name: duplicate\n"
        + b"    order: [title]\n"
        + b"    sort: [{property: title, direction: ASC}]\n"
    )
    ambiguous_before = base.read_bytes()
    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)
    assert base.read_bytes() == ambiguous_before

    if hasattr(os, "mkfifo"):
        base.unlink()
        os.mkfifo(base)
        with pytest.raises(SystemExit, match="unsafe or unowned"):
            preview_obsidian_base_presentation_reset(tmp_path)


def test_concurrent_base_presentation_reset_has_one_atomic_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    barrier = threading.Barrier(2)
    local = threading.local()
    original = obsidian_module._base_presentation_reset_preview

    def synchronized_preview(root, *, preview_token, allow_current_operation=False):
        result = original(
            root,
            preview_token=preview_token,
            allow_current_operation=allow_current_operation,
        )
        if not getattr(local, "initial_preview_complete", False):
            local.initial_preview_complete = True
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(obsidian_module, "_base_presentation_reset_preview", synchronized_preview)

    def apply_once():
        try:
            return reset_obsidian_base_presentation_drift(
                tmp_path,
                expected_preview_digest=preview["preview_digest"],
                expected_preview_token=preview["preview_token"],
                user_authorization="确认按预览重置",
                authorization_source="user_message",
            )
        except SystemExit as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: apply_once(), range(2)))

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, str) for result in results) == 1
    assert obsidian_projection_status(tmp_path)["status"] == "PASS"


def test_base_presentation_reset_preview_cannot_be_replayed_after_sort_reappears(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    first = preview_obsidian_base_presentation_reset(tmp_path)
    reset_obsidian_base_presentation_drift(
        tmp_path,
        expected_preview_digest=first["preview_digest"],
        expected_preview_token=first["preview_token"],
        user_authorization="确认第一次重置",
        authorization_source="user_message",
    )
    _apply_obsidian_1_12_7_title_sort(base)
    repeated_bytes = base.read_bytes()
    second = preview_obsidian_base_presentation_reset(tmp_path)

    assert second["preview_digest"] != first["preview_digest"]
    with pytest.raises(SystemExit, match="stale"):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=first["preview_digest"],
            expected_preview_token=first["preview_token"],
            user_authorization="replayed old authorization",
            authorization_source="user_message",
        )
    assert base.read_bytes() == repeated_bytes


def test_base_presentation_reset_never_writes_through_swapped_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    dashboards = managed / "dashboards"
    base = dashboards / "All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    detached = managed / "detached-dashboards"
    outside = tmp_path / "outside-dashboards"
    outside.mkdir()
    outside_base = outside / "All Units.base"
    outside_base.write_text("outside sentinel\n", encoding="utf-8")
    outside_before = outside_base.read_bytes()
    original_preview = obsidian_module._base_presentation_reset_preview
    preview_calls = 0

    def swap_after_locked_preview(
        root: Path,
        *,
        preview_token: str,
        allow_current_operation: bool = False,
    ):
        nonlocal preview_calls
        result = original_preview(
            root,
            preview_token=preview_token,
            allow_current_operation=allow_current_operation,
        )
        preview_calls += 1
        if preview_calls == 2:
            dashboards.rename(detached)
            dashboards.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(
        obsidian_module,
        "_base_presentation_reset_preview",
        swap_after_locked_preview,
    )

    with pytest.raises((SystemExit, RuntimeError)):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按预览重置",
            authorization_source="user_message",
        )

    assert outside_base.read_bytes() == outside_before


def test_base_presentation_reset_does_not_overwrite_concurrent_leaf_at_replace_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    sentinel_bytes = b"concurrent reviewer sentinel\n"
    original_replace = os.replace
    original_exchange = obsidian_module._atomic_exchange_at
    injected = False

    def inject_before_exchange(
        left_parent_fd: int,
        left: str,
        right_parent_fd: int,
        right: str,
    ) -> None:
        nonlocal injected
        if (
            not injected
            and left.startswith(".presentation-reset-")
            and right == "All Units.base"
        ):
            injected = True
            sentinel_name = ".reviewer-concurrent-sentinel.tmp"
            descriptor = os.open(
                sentinel_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=right_parent_fd,
            )
            try:
                os.write(descriptor, sentinel_bytes)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            original_replace(
                sentinel_name,
                right,
                src_dir_fd=right_parent_fd,
                dst_dir_fd=right_parent_fd,
            )
        original_exchange(left_parent_fd, left, right_parent_fd, right)

    monkeypatch.setattr(obsidian_module, "_atomic_exchange_at", inject_before_exchange)

    with pytest.raises((SystemExit, RuntimeError)):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按预览重置",
            authorization_source="user_message",
        )

    assert injected is True
    assert base.read_bytes() == sentinel_bytes
    assert list(base.parent.glob(".presentation-reset-*.tmp")) == []


@pytest.mark.parametrize("replacement_kind", ["absent", "symlink", "fifo"])
def test_base_presentation_reset_preserves_concurrent_non_regular_leaf_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    outside = tmp_path / "outside-reviewer-sentinel.base"
    outside.write_bytes(b"outside reviewer sentinel\n")
    outside_before = outside.read_bytes()
    original_exchange = obsidian_module._atomic_exchange_at
    injected = False

    def inject_non_regular_leaf_before_exchange(
        left_parent_fd: int,
        left: str,
        right_parent_fd: int,
        right: str,
    ) -> None:
        nonlocal injected
        if (
            not injected
            and left.startswith(".presentation-reset-")
            and right == "All Units.base"
        ):
            injected = True
            os.unlink(right, dir_fd=right_parent_fd)
            if replacement_kind == "symlink":
                os.symlink(str(outside), right, dir_fd=right_parent_fd)
            elif replacement_kind == "fifo":
                os.mkfifo(right, 0o600, dir_fd=right_parent_fd)
        original_exchange(left_parent_fd, left, right_parent_fd, right)

    monkeypatch.setattr(
        obsidian_module,
        "_atomic_exchange_at",
        inject_non_regular_leaf_before_exchange,
    )

    with pytest.raises((OSError, RuntimeError, SystemExit)):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按预览重置",
            authorization_source="user_message",
        )

    assert injected is True
    if replacement_kind == "absent":
        assert not base.exists()
        assert not base.is_symlink()
    elif replacement_kind == "symlink":
        assert base.is_symlink()
        assert base.readlink() == outside
    else:
        assert stat.S_ISFIFO(base.lstat().st_mode)
    assert outside.read_bytes() == outside_before
    assert list(
        (tmp_path / "kb/.journal/snapshots").rglob(".presentation-reset-*.tmp")
    ) == []


def test_base_presentation_reset_restores_detached_leaf_after_final_ancestor_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    dashboards = managed / "dashboards"
    base = dashboards / "All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    drift_bytes = base.read_bytes()
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    detached = managed / "detached-at-final-replace"
    outside = tmp_path / "outside-at-final-replace"
    outside.mkdir()
    outside_base = outside / "All Units.base"
    outside_base.write_bytes(b"outside reviewer sentinel\n")
    outside_before = outside_base.read_bytes()
    original_exchange = obsidian_module._atomic_exchange_at
    injected = False

    def swap_ancestor_before_exchange(
        left_parent_fd: int,
        left: str,
        right_parent_fd: int,
        right: str,
    ) -> None:
        nonlocal injected
        if (
            not injected
            and left.startswith(".presentation-reset-")
            and right == "All Units.base"
        ):
            injected = True
            dashboards.rename(detached)
            dashboards.symlink_to(outside, target_is_directory=True)
        original_exchange(left_parent_fd, left, right_parent_fd, right)

    monkeypatch.setattr(obsidian_module, "_atomic_exchange_at", swap_ancestor_before_exchange)

    with pytest.raises((SystemExit, RuntimeError)):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按预览重置",
            authorization_source="user_message",
        )

    assert injected is True
    assert outside_base.read_bytes() == outside_before
    assert (detached / "All Units.base").read_bytes() == drift_bytes
    assert list(detached.glob(".presentation-reset-*.tmp")) == []


def test_base_presentation_reset_restores_leaf_after_staging_directory_detach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    drift_bytes = base.read_bytes()
    preview = preview_obsidian_base_presentation_reset(tmp_path)
    detached = tmp_path / "detached-staging-op"
    original_exchange = obsidian_module._atomic_exchange_at
    injected = False

    def detach_staging_before_exchange(
        left_parent_fd: int,
        left: str,
        right_parent_fd: int,
        right: str,
    ) -> None:
        nonlocal injected
        if (
            not injected
            and left.startswith(".presentation-reset-")
            and right == "All Units.base"
        ):
            injected = True
            current = incomplete_ops(tmp_path)
            assert len(current) == 1
            op_id = str(current[0]["op_id"])
            staging = tmp_path / "kb/.journal/snapshots" / op_id
            staging.rename(detached)
            staging.mkdir(mode=0o700)
        original_exchange(left_parent_fd, left, right_parent_fd, right)

    monkeypatch.setattr(
        obsidian_module,
        "_atomic_exchange_at",
        detach_staging_before_exchange,
    )

    with pytest.raises((SystemExit, RuntimeError)):
        reset_obsidian_base_presentation_drift(
            tmp_path,
            expected_preview_digest=preview["preview_digest"],
            expected_preview_token=preview["preview_token"],
            user_authorization="确认按预览重置",
            authorization_source="user_message",
        )

    assert injected is True
    assert base.read_bytes() == drift_bytes
    assert list(detached.glob(".presentation-reset-*.tmp")) == []
    assert list(
        (tmp_path / "kb/.journal/snapshots").rglob(".presentation-reset-*.tmp")
    ) == []


def test_base_presentation_sort_with_yaml_comment_remains_protected_drift(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    base.write_bytes(base.read_bytes() + b"# human comment\n")
    commented_bytes = base.read_bytes()

    report = obsidian_projection_status(tmp_path)

    assert "OBSIDIAN_MANAGED_FILE_DRIFT" in {item["code"] for item in report["findings"]}
    assert "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT" not in {
        item["code"] for item in report["findings"]
    }
    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)
    assert base.read_bytes() == commented_bytes


def test_base_presentation_sort_with_reordered_view_keys_remains_protected_drift(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    payload = yaml.safe_load(base.read_text(encoding="utf-8"))
    view = payload["views"][0]
    payload["views"][0] = {
        "name": view["name"],
        "type": view["type"],
        "order": view["order"],
        "sort": [{"property": "title", "direction": "ASC"}],
    }
    base.write_text(
        yaml.dump(
            payload,
            Dumper=_ObsidianBaseDumper,
            allow_unicode=True,
            sort_keys=False,
            width=1_000_000,
        ),
        encoding="utf-8",
    )
    reordered_bytes = base.read_bytes()

    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert base.read_bytes() == reordered_bytes


def test_base_presentation_sort_with_reordered_sort_item_keys_remains_protected_drift(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    base = obsidian_managed_root(tmp_path) / "dashboards/All Units.base"
    payload = yaml.safe_load(base.read_text(encoding="utf-8"))
    payload["views"][0]["sort"] = [{"direction": "ASC", "property": "title"}]
    base.write_text(
        yaml.dump(
            payload,
            Dumper=_ObsidianBaseDumper,
            allow_unicode=True,
            sort_keys=False,
            width=1_000_000,
        ),
        encoding="utf-8",
    )
    reordered_bytes = base.read_bytes()

    with pytest.raises(SystemExit, match="not an allowlisted"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert base.read_bytes() == reordered_bytes


def test_base_presentation_preview_rejects_manifest_ownership_spoof(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    base = managed / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    manual = managed / "dashboards/Manual.base"
    manual.write_text("manual content\n", encoding="utf-8")
    manifest_path = managed / "manifest.yaml"
    manifest = load_yaml(manifest_path, default={})
    manifest["files"]["dashboards/Manual.base"] = hashlib.sha256(manual.read_bytes()).hexdigest()
    manifest["manual_extension"] = True
    write_yaml_if_changed(manifest_path, manifest)
    base_before = base.read_bytes()
    manual_before = manual.read_bytes()

    with pytest.raises(SystemExit, match="manifest is invalid"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert base.read_bytes() == base_before
    assert manual.read_bytes() == manual_before


def test_base_presentation_preview_rejects_reordered_manifest_bytes(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    base = managed / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    manifest_path = managed / "manifest.yaml"
    manifest = load_yaml(manifest_path, default={})
    reordered = dict(reversed(list(manifest.items())))
    manifest_path.write_text(
        obsidian_module.dump_yaml(reordered),
        encoding="utf-8",
    )
    manifest_bytes = manifest_path.read_bytes()
    base_bytes = base.read_bytes()

    with pytest.raises(SystemExit, match="manifest is invalid"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert manifest_path.read_bytes() == manifest_bytes
    assert base.read_bytes() == base_bytes


def test_base_presentation_preview_rejects_reordered_manifest_files_mapping(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    base = managed / "dashboards/All Units.base"
    _apply_obsidian_1_12_7_title_sort(base)
    manifest_path = managed / "manifest.yaml"
    manifest = load_yaml(manifest_path, default={})
    manifest["files"] = dict(reversed(list(manifest["files"].items())))
    manifest_path.write_text(
        obsidian_module.dump_yaml(manifest),
        encoding="utf-8",
    )
    manifest_bytes = manifest_path.read_bytes()
    base_bytes = base.read_bytes()

    with pytest.raises(SystemExit, match="manifest is invalid"):
        preview_obsidian_base_presentation_reset(tmp_path)

    assert manifest_path.read_bytes() == manifest_bytes
    assert base.read_bytes() == base_bytes


def test_projection_links_markdown_reading_view_and_local_repo_file(tmp_path: Path) -> None:
    paper = _record(tmp_path, "p-paper-12345678", "Readable Paper")
    document = tmp_path / "kb/units/papers/p-paper-12345678/source/document.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("# Full paper\n\n^source-page-1\n\nReadable source.\n", encoding="utf-8")
    source_map = document.parent / "source-map.yaml"
    conversion = document.parent / "conversion.yaml"
    archive = document.parent / "archive.html"
    archive.write_text("<!doctype html><title>Full paper</title><p>Readable source.</p>\n", encoding="utf-8")
    write_yaml_if_changed(
        source_map,
        {
            "schema": "research-source-map/v1",
            "blocks": [{"block_id": "source-page-1", "locator_kind": "page", "page": 1}],
        },
    )
    write_yaml_if_changed(conversion, {"schema": "research-source-markdown/v2", "status": "complete"})
    paper["source"].update(
        {
            "markdown_path": "kb/units/papers/p-paper-12345678/source/document.md",
            "markdown_hash": hashlib.sha256(document.read_bytes()).hexdigest(),
            "materialization": {
                "schema": "research-source-markdown/v2",
                "status": "complete",
                "converter": "test",
                "converter_version": "1",
                "source_map_path": "kb/units/papers/p-paper-12345678/source/source-map.yaml",
                "conversion_path": "kb/units/papers/p-paper-12345678/source/conversion.yaml",
                "archive_path": "kb/units/papers/p-paper-12345678/source/archive.html",
                "archive_hash": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "asset_paths": [],
            },
        }
    )
    paper["payload"]["claims"] = [
        {
            "id": "claim-paper",
            "text": "The paper has readable evidence.",
            "claim_type": "fact",
            "confirmation_status": "auto_confirmed",
            "evidence_refs": [
                {
                    "source_unit_id": paper["id"],
                    "artifact": "parse-cache.yaml",
                    "locator": "page=1",
                    "quote": "Readable source.",
                }
            ],
        }
    ]
    write_yaml_if_changed(record_path(tmp_path, "paper", paper["id"]), paper)

    repo_root = tmp_path / "local-repo"
    source_file = repo_root / "src/train.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("def train():\n    return True\n", encoding="utf-8")
    repo = default_record("repo", title="Local Repo", maturity="complete")
    repo["id"] = "r-local-12345678"
    repo["status"] = "active"
    repo["payload"]["structure"]["repo_root"] = repo_root.as_posix()
    repo["payload"]["claims"] = [
        {
            "id": "claim-entry",
            "text": "The training entry is local.",
            "claim_type": "fact",
            "confirmation_status": "auto_confirmed",
            "evidence_refs": [
                {
                    "source_unit_id": repo["id"],
                    "artifact": "src/train.py",
                    "locator": "line=1",
                    "quote": "def train():",
                    "external_source": {"kind": "repo"},
                }
            ],
        }
    ]
    write_yaml_if_changed(record_path(tmp_path, "repo", repo["id"]), repo)

    result = update_obsidian_projection(tmp_path)

    assert result["status"]["status"] == "PASS"
    paper_page = (obsidian_managed_root(tmp_path) / "units/p-paper-12345678.md").read_text(encoding="utf-8")
    repo_page = (obsidian_managed_root(tmp_path) / "units/r-local-12345678.md").read_text(encoding="utf-8")
    assert "[[units/papers/p-paper-12345678/source/document|Read material]]" in paper_page
    assert "[[units/papers/p-paper-12345678/source/document#^source-page-1|parse-cache.yaml]]" in paper_page
    assert source_file.resolve().as_uri() in repo_page
    assert "#L1" not in repo_page

    archive.write_text("drifted offline page\n", encoding="utf-8")
    drift_report = obsidian_projection_status(tmp_path)
    assert "OBSIDIAN_SOURCE_ARCHIVE_DRIFT" in {item["code"] for item in drift_report["findings"]}


def test_obsidian_status_rejects_missing_declared_source_document(tmp_path: Path) -> None:
    record = _record(tmp_path, "p-paper-12345678", "Missing Reading View")
    record["source"]["markdown_path"] = "kb/units/papers/p-paper-12345678/source/document.md"
    write_yaml_if_changed(record_path(tmp_path, "paper", record["id"]), record)

    report = obsidian_projection_status(tmp_path)

    assert report["status"] == "FAIL"
    assert "OBSIDIAN_SOURCE_DOCUMENT_MISSING" in {item["code"] for item in report["findings"]}


def test_projection_collapses_untrusted_heading_whitespace_to_one_line(tmp_path: Path) -> None:
    record = _record(tmp_path, "p-alpha-12345678", "Alpha\n## Injected")
    record["links"] = [
        {
            "target_id": record["id"],
            "relation": "related_to",
            "target_locator": {"kind": "heading", "value": "Claims\nInjected"},
        }
    ]
    write_yaml_if_changed(record_path(tmp_path, "paper", record["id"]), record)

    update_obsidian_projection(tmp_path)

    page = (obsidian_managed_root(tmp_path) / "units/p-alpha-12345678.md").read_text(encoding="utf-8")
    assert "# Alpha \\#\\# Injected" in page
    assert "\n## Injected\n" not in page
    assert "#Claims Injected" in page


def test_projection_preserves_markdown_literals_and_keeps_property_links_on_one_line(
    tmp_path: Path,
) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    beta = _record(
        tmp_path,
        "p-beta-12345678",
        "A deliberately long linked title about universal humanoid control and reusable training systems",
    )
    alpha["source"]["original_uri"] = "/private/tmp/psi0-intake/source"
    alpha["links"] = [{"target_id": beta["id"], "relation": "supports"}]
    alpha["payload"]["claims"] = [
        {
            "id": "claim-entry-map",
            "text": "Run scripts/train/psi0/*.sh through psi.config.train.<name> with [literal] and `code`.",
            "claim_type": "inference",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": alpha["id"],
                    "artifact": "scripts/train.py",
                    "locator": "line=354",
                    "quote": "module <name> uses *.sh and [x] with `code`",
                }
            ],
        }
    ]
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)
    write_yaml_if_changed(record_path(tmp_path, "paper", beta["id"]), beta)

    update_obsidian_projection(tmp_path)

    managed = obsidian_managed_root(tmp_path)
    page = (managed / "units/p-alpha-12345678.md").read_text(encoding="utf-8")
    assert r"scripts/train/psi0/\*.sh" in page
    assert r"psi.config.train.\<name\>" in page
    assert r"\[literal\]" in page
    assert r"\`code\`" in page
    assert r"> module \<name\> uses \*.sh and \[x\] with \`code\`" in page
    assert "- Type: Inference" in page
    assert "- Confirmation: Pending human confirmation" in page
    assert "#### Evidence" in page
    assert "- Source: Local source" in page
    assert "/private/tmp/psi0-intake" not in page
    frontmatter = page.split("---", 2)[1]
    relation_lines = [line for line in frontmatter.splitlines() if "[[" in line or "]]" in line]
    assert relation_lines
    assert all("[[" in line and "]]" in line for line in relation_lines)
    assert any(len(line) > 80 for line in relation_lines)

    home = (managed / "Home.md").read_text(encoding="utf-8")
    assert "Reading view" in home
    assert "book icon" in home


def test_unit_and_home_put_reading_health_and_next_action_before_technical_metadata(tmp_path: Path) -> None:
    record = _record(tmp_path, "p-paper-12345678", "Readable Paper")
    record["summary"] = "Lightweight paper intake for `Readable Paper`."
    document = tmp_path / "kb/units/papers/p-paper-12345678/source/document.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("# Paper\n\nReadable.\n", encoding="utf-8")
    conversion = document.parent / "conversion.yaml"
    write_yaml_if_changed(
        conversion,
        {
            "schema": "research-source-markdown/v2",
            "status": "degraded",
            "warnings": ["one image could not be localized"],
            "quality": {
                "output": {
                    "document_characters": 20,
                    "image_count": 2,
                    "local_asset_reference_count": 1,
                }
            },
        },
    )
    record["source"].update(
        {
            "original_uri": "https://example.com/paper",
            "markdown_path": "kb/units/papers/p-paper-12345678/source/document.md",
            "materialization": {
                "status": "degraded",
                "conversion_path": "kb/units/papers/p-paper-12345678/source/conversion.yaml",
            },
        }
    )
    write_yaml_if_changed(record_path(tmp_path, "paper", record["id"]), record)

    update_obsidian_projection(tmp_path)

    managed = obsidian_managed_root(tmp_path)
    page = (managed / "units/p-paper-12345678.md").read_text(encoding="utf-8")
    assert "The material is safely archived and readable" in page
    assert "Quick access" in page
    assert "Source health · Degraded" in page
    assert "Analysis · Awaiting AI analysis" in page
    assert "one image could not be localized" in page
    assert "Images: ` 1 ` local / ` 2 ` referenced" in page
    assert page.index("Quick access") < page.index("## Metadata")
    assert page.index("## Claims") < page.index("## Metadata")
    home = (managed / "Home.md").read_text(encoding="utf-8")
    assert "**1** sources need attention" in home
    assert "Recently updated" in home
    assert "Readable Paper" in home


def test_pending_record_without_claims_is_awaiting_analysis_not_human_confirmation(tmp_path: Path) -> None:
    record = _record(tmp_path, "p-paper-12345678", "Prepared but Unfilled")
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["payload"]["claims"] = []
    write_yaml_if_changed(record_path(tmp_path, "paper", record["id"]), record)

    update_obsidian_projection(tmp_path)

    managed = obsidian_managed_root(tmp_path)
    page = (managed / "units/p-paper-12345678.md").read_text(encoding="utf-8")
    home = (managed / "Home.md").read_text(encoding="utf-8")
    pending_base = load_yaml(managed / "dashboards/Pending Review.base", default={})
    assert "Analysis · Awaiting AI analysis" in page
    assert "Analysis · Awaiting human confirmation" not in page
    assert "**0** awaiting confirmation" in home
    assert pending_base["views"][0]["filters"] == {
        "and": ['analysis_stage == "awaiting_confirmation"']
    }


@pytest.mark.parametrize(
    ("record_status", "claim_status", "stage", "expected_summary"),
    [
        (
            "pending_user_confirmation",
            "pending_user_confirmation",
            "awaiting_confirmation",
            "下方已记录有逐字证据支持的判断，正在等待人工确认。",
        ),
        (
            "confirmed",
            "pending_user_confirmation",
            "evidence_recorded",
            "下方已列出有逐字证据支持的判断及其证据。",
        ),
    ],
)
def test_empty_summary_fallback_matches_analysis_stage(
    tmp_path: Path,
    record_status: str,
    claim_status: str,
    stage: str,
    expected_summary: str,
) -> None:
    write_yaml_if_changed(
        tmp_path / "kb/config/user-profile.yaml",
        {"preferences": {"language_preference": "zh-CN"}},
    )
    record = default_record("repo", title="Stage-consistent summary", maturity="complete")
    record["id"] = "r-summary-stage-12345678"
    record["status"] = "active"
    record["summary"] = ""
    record["confirmation_status"] = record_status
    record["needs_human_confirmation"] = record_status == "pending_user_confirmation"
    record["payload"]["claims"] = [
        {
            "id": "claim-summary-stage",
            "text": "This claim has a verbatim source quote.",
            "claim_type": "fact",
            "confirmation_status": claim_status,
            "evidence_refs": [
                {
                    "source_unit_id": "r-summary-stage-12345678",
                    "artifact": "record.yaml",
                    "locator": "record",
                    "quote": "Stage-consistent summary",
                }
            ],
        }
    ]
    if record_status == "confirmed":
        record["confirmation"] = {"claim_ids": ["claim-summary-stage"]}
    write_yaml_if_changed(record_path(tmp_path, "repo", record["id"]), record)

    update_obsidian_projection(tmp_path)

    page = (
        obsidian_managed_root(tmp_path) / "units/r-summary-stage-12345678.md"
    ).read_text(encoding="utf-8")
    assert f"analysis_stage: {stage}" in page
    assert expected_summary in page
    assert "AI 尚未完成内容分析" not in page


def test_chinese_profile_localizes_projection_and_repo_quick_access(tmp_path: Path) -> None:
    write_yaml_if_changed(
        tmp_path / "kb/config/user-profile.yaml",
        {"preferences": {"language_preference": "zh-CN"}},
    )
    record = default_record("repo", title="Click", maturity="lightweight")
    record["id"] = "r-click-12345678"
    record["status"] = "active"
    record["confirmation_status"] = "auto_confirmed"
    record["needs_human_confirmation"] = False
    snapshot = tmp_path / "kb/units/repos/r-click-12345678/source/click"
    snapshot.mkdir(parents=True)
    (snapshot / "README.md").write_text("# Click\n", encoding="utf-8")
    (snapshot / "pyproject.toml").write_text("[project]\nname='click'\n", encoding="utf-8")
    record["source"].update(
        {
            "original_uri": "/private/tmp/click",
            "backup_paths": ["kb/units/repos/r-click-12345678/source/click"],
            "backup_kind": "directory",
        }
    )
    write_yaml_if_changed(record_path(tmp_path, "repo", record["id"]), record)

    update_obsidian_projection(tmp_path)

    managed = obsidian_managed_root(tmp_path)
    page = (managed / "units/r-click-12345678.md").read_text(encoding="utf-8")
    home = (managed / "Home.md").read_text(encoding="utf-8")
    all_units = load_yaml(managed / "dashboards/All Units.base", default={})
    assert "## 概览" in page
    assert "> [!info] 快速入口" in page
    assert "[[units/repos/r-click-12345678/source/click/README|README.md]]" in page
    assert "pyproject.toml" in page and "打开本地源码目录" in page
    assert "/private/tmp/click" not in page
    assert "分析状态 · 等待 AI 分析" in page
    assert "# 研究知识库" in home
    assert "从这里开始" in home and "阅读视图" in home
    assert all_units["properties"]["title"]["displayName"] == "标题"
    assert all_units["views"][0]["name"] == "全部单元"


def test_renderer_revision_marks_old_projection_stale_and_forces_rebuild(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    manifest_path = obsidian_managed_root(tmp_path) / "manifest.yaml"
    manifest = load_yaml(manifest_path, default={})
    manifest["renderer_revision"] = OBSIDIAN_RENDERER_REVISION - 1
    write_yaml_if_changed(manifest_path, manifest)

    report = obsidian_projection_status(tmp_path)

    assert report["status"] == "WARN"
    assert "OBSIDIAN_PROJECTION_STALE" in {item["code"] for item in report["findings"]}
    rebuilt = update_obsidian_projection(tmp_path)
    assert rebuilt["changed"] is True
    assert rebuilt["status"]["status"] == "PASS"
    assert load_yaml(manifest_path, default={})["renderer_revision"] == OBSIDIAN_RENDERER_REVISION


def test_revision_three_bases_normalized_by_obsidian_converge_without_weakening_drift_guard(
    tmp_path: Path,
) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    managed = obsidian_managed_root(tmp_path)
    manifest_path = managed / "manifest.yaml"
    manifest = load_yaml(manifest_path, default={})
    manifest["renderer_revision"] = 3
    write_yaml_if_changed(manifest_path, manifest)
    for relative in (
        "dashboards/All Units.base",
        "dashboards/Pending Review.base",
        "dashboards/By Topic.base",
    ):
        write_yaml_if_changed(managed / relative, obsidian_module._legacy_obsidian_normalized_base(relative))

    rebuilt = update_obsidian_projection(tmp_path)

    assert rebuilt["changed"] is True
    assert rebuilt["status"]["status"] == "PASS"
    assert load_yaml(manifest_path, default={})["renderer_revision"] == OBSIDIAN_RENDERER_REVISION
    for relative in (
        "dashboards/All Units.base",
        "dashboards/Pending Review.base",
        "dashboards/By Topic.base",
    ):
        payload = load_yaml(managed / relative, default={})
        assert "analysis_stage" in payload["views"][0]["order"]

    all_units = managed / "dashboards/All Units.base"
    payload = load_yaml(all_units, default={})
    payload["views"][0]["name"] = "Human rename"
    write_yaml_if_changed(all_units, payload)
    record = load_yaml(record_path(tmp_path, "paper", "p-alpha-12345678"), default={})
    record["summary"] = "Canonical input changed."
    write_yaml_if_changed(record_path(tmp_path, "paper", record["id"]), record)
    with pytest.raises(SystemExit, match="human-edited"):
        update_obsidian_projection(tmp_path)


def test_status_is_zero_write_for_an_empty_missing_workspace(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    before = list(tmp_path.iterdir())

    report = obsidian_projection_status(root)

    assert report["status"] == "PASS"
    assert report["counts"]["records"] == 0
    assert not root.exists()
    assert list(tmp_path.iterdir()) == before


def test_status_fails_for_missing_target_and_unresolved_locator(tmp_path: Path) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    beta = _record(tmp_path, "p-beta-12345678", "Beta")
    alpha["program_ids"] = ["missing-program"]
    alpha["payload"]["claims"] = [
        {
            "id": "claim-alpha",
            "text": "Alpha claim.",
            "evidence_refs": [{"source_unit_id": "p-missing-source-12345678", "quote": "quote"}],
        }
    ]
    alpha["links"] = [
        {"target_id": "p-missing-12345678", "relation": "cites"},
        {
            "target_id": beta["id"],
            "relation": "supports",
            "target_locator": {"kind": "heading", "value": "Nonexistent section"},
        },
    ]
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)
    write_yaml_if_changed(
        tmp_path / "kb/programs/test-program/state.yaml",
        {"program_id": "test-program", "active_unit_ids": ["p-missing-active-12345678"]},
    )

    report = obsidian_projection_status(tmp_path)

    assert report["status"] == "FAIL"
    codes = {finding["code"] for finding in report["findings"]}
    assert "OBSIDIAN_LINK_TARGET_MISSING" in codes
    assert "OBSIDIAN_LOCATOR_UNRESOLVED" in codes
    assert "OBSIDIAN_PROGRAM_TARGET_MISSING" in codes
    assert "OBSIDIAN_EVIDENCE_SOURCE_MISSING" in codes
    assert "OBSIDIAN_PROGRAM_UNIT_MISSING" in codes
    assert "OBSIDIAN_PROJECTION_NOT_GENERATED" in codes


def test_legacy_reverse_pair_is_folded_but_orphan_is_preserved_and_warned(tmp_path: Path) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    beta = _record(tmp_path, "p-beta-12345678", "Beta")
    alpha["links"] = [{"target_id": beta["id"], "relation": "builds_on"}]
    beta["links"] = [{"target_id": alpha["id"], "relation": "reverse:builds_on"}]
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)
    write_yaml_if_changed(record_path(tmp_path, "paper", beta["id"]), beta)

    edges = project_relation_edges([alpha, beta])
    assert [(edge["source_id"], edge["relation"], edge["target_id"]) for edge in edges] == [
        (alpha["id"], "builds_on", beta["id"])
    ]
    assert "OBSIDIAN_LEGACY_REVERSE_LINK" not in {
        item["code"] for item in obsidian_projection_status(tmp_path)["findings"]
    }

    alpha["links"] = []
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)
    report = obsidian_projection_status(tmp_path)
    assert "OBSIDIAN_LEGACY_REVERSE_LINK" in {item["code"] for item in report["findings"]}
    orphan = project_relation_edges([alpha, beta])
    assert orphan[0]["provenance"] == "legacy_reverse"
    assert orphan[0]["source_id"] == alpha["id"]


def test_update_preserves_human_notes_cleans_only_manifest_owned_stale_files(tmp_path: Path) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    _record(tmp_path, "p-beta-12345678", "Beta")
    update_obsidian_projection(tmp_path)
    annotation = tmp_path / "kb/obsidian/annotations/my-note.md"
    annotation.write_text("Human note [[obsidian/managed/units/p-alpha-12345678]].\n", encoding="utf-8")

    record_path(tmp_path, "paper", "p-beta-12345678").unlink()
    alpha["summary"] = "Changed canonical summary."
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)
    assert obsidian_projection_status(tmp_path)["status"] == "WARN"

    update_obsidian_projection(tmp_path)

    managed = obsidian_managed_root(tmp_path)
    assert not (managed / "units/p-beta-12345678.md").exists()
    assert "Changed canonical summary." in (managed / "units/p-alpha-12345678.md").read_text(encoding="utf-8")
    assert annotation.read_text(encoding="utf-8").startswith("Human note")


def test_update_refuses_managed_drift_and_preserves_bytes(tmp_path: Path) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    page = obsidian_managed_root(tmp_path) / "units/p-alpha-12345678.md"
    page.write_text("human edit in managed area\n", encoding="utf-8")
    before = page.read_bytes()
    alpha["summary"] = "Canonical changed too."
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)

    with pytest.raises(SystemExit, match="human-edited"):
        update_obsidian_projection(tmp_path)

    assert page.read_bytes() == before
    report = obsidian_projection_status(tmp_path)
    assert "OBSIDIAN_MANAGED_FILE_DRIFT" in {item["code"] for item in report["findings"]}


def test_post_intake_refresh_managed_drift_preserves_canonical_success_and_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_cli()
    _record(tmp_path, "p-existing-12345678", "Existing")
    update_obsidian_projection(tmp_path)
    managed_page = obsidian_managed_root(tmp_path) / "units/p-existing-12345678.md"
    managed_page.write_text("human-managed-drift\n", encoding="utf-8")
    managed_before = managed_page.read_bytes()
    new_record_path = record_path(tmp_path, "paper", "p-new-12345678")
    canonical_bytes: list[bytes] = []
    monkeypatch.setattr(
        kb,
        "load_runtime_preferences",
        lambda root: {"autonomy": {"link_autodrive": "ask_first"}},
    )

    def fake_forward(root, relative_script, args, **kwargs):
        del kwargs
        _record(root, "p-new-12345678", "New intake")
        canonical_bytes.append(new_record_path.read_bytes())
        return kb.CommandResult(
            (relative_script, *args),
            0,
            "[ok] created kb/units/papers/p-new-12345678/record.yaml\n",
        )

    monkeypatch.setattr(kb, "forward_command", fake_forward)
    monkeypatch.setattr(kb, "_capture_runtime_failure", lambda root, **kwargs: None)

    assert kb.main(
        ["--root", str(tmp_path), "--agent-protocol", "drift-refresh.json", "add", "https://example.com/new.pdf"]
    ) == 0

    assert new_record_path.read_bytes() == canonical_bytes[0]
    assert managed_page.read_bytes() == managed_before
    public = capsys.readouterr()
    assert "资料已轻量加入知识库" in public.out
    assert "Obsidian 视图暂未刷新" in public.err
    assert "human-managed-drift" not in public.out + public.err
    protocol = load_yaml(tmp_path / "kb/.runtime/drift-refresh.json", default={})
    assert protocol["status"] == "needs_user_input"
    assert protocol["details"]["obsidian_refresh"] == {
        "failure_kind": "safety_check_failed",
        "status": "warning",
    }


def test_update_refuses_unowned_generated_file_but_never_scans_human_area(tmp_path: Path) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    unowned = obsidian_managed_root(tmp_path) / "manual.md"
    unowned.write_text("must survive\n", encoding="utf-8")
    annotation = tmp_path / "kb/obsidian/annotations/manual.md"
    annotation.write_text("human annotation\n", encoding="utf-8")

    report = obsidian_projection_status(tmp_path)
    assert "OBSIDIAN_MANAGED_FILE_UNOWNED" in {item["code"] for item in report["findings"]}
    with pytest.raises(SystemExit):
        update_obsidian_projection(tmp_path)
    assert unowned.read_text(encoding="utf-8") == "must survive\n"
    assert annotation.read_text(encoding="utf-8") == "human annotation\n"


def test_status_reports_unowned_managed_content_before_first_projection(tmp_path: Path) -> None:
    unowned = tmp_path / "kb/obsidian/managed/manual.md"
    unowned.parent.mkdir(parents=True)
    unowned.write_text("must survive\n", encoding="utf-8")

    report = obsidian_projection_status(tmp_path)

    assert report["status"] == "WARN"
    assert "OBSIDIAN_MANAGED_FILE_UNOWNED" in {item["code"] for item in report["findings"]}
    with pytest.raises(SystemExit, match="Unowned files"):
        update_obsidian_projection(tmp_path)
    assert unowned.read_text(encoding="utf-8") == "must survive\n"


def test_symlinked_managed_file_is_never_followed_or_overwritten(tmp_path: Path) -> None:
    alpha = _record(tmp_path, "p-alpha-12345678", "Alpha")
    update_obsidian_projection(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    page = obsidian_managed_root(tmp_path) / "units/p-alpha-12345678.md"
    page.unlink()
    page.symlink_to(outside)
    before = hashlib.sha256(outside.read_bytes()).hexdigest()
    alpha["summary"] = "Changed canonical summary."
    write_yaml_if_changed(record_path(tmp_path, "paper", alpha["id"]), alpha)

    report = obsidian_projection_status(tmp_path)
    assert report["status"] == "FAIL"
    with pytest.raises(SystemExit):
        update_obsidian_projection(tmp_path)
    assert hashlib.sha256(outside.read_bytes()).hexdigest() == before


def test_canonical_symlinks_fail_closed_without_reading_or_writing_targets(tmp_path: Path) -> None:
    outside = tmp_path / "outside-kb"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside secret\n", encoding="utf-8")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "kb").symlink_to(outside, target_is_directory=True)
    before = secret.read_bytes()

    report = obsidian_projection_status(root)
    assert report["status"] == "FAIL"
    assert report["findings"][0]["code"] == "OBSIDIAN_KB_ROOT_UNSAFE"
    with pytest.raises(SystemExit):
        update_obsidian_projection(root)
    assert secret.read_bytes() == before
    assert not (outside / "obsidian").exists()

    safe_root = tmp_path / "safe-workspace"
    unit = safe_root / "kb/units/papers/p-linked-12345678"
    unit.mkdir(parents=True)
    outside_record = tmp_path / "outside-record.yaml"
    outside_record.write_text("id: p-linked-12345678\nkind: paper\ntitle: Outside\n", encoding="utf-8")
    (unit / "record.yaml").symlink_to(outside_record)
    record_before = outside_record.read_bytes()
    linked_report = obsidian_projection_status(safe_root)
    assert "OBSIDIAN_CANONICAL_INPUT_UNSAFE" in {item["code"] for item in linked_report["findings"]}
    with pytest.raises(SystemExit):
        update_obsidian_projection(safe_root)
    assert outside_record.read_bytes() == record_before


def test_public_kb_obsidian_commands_are_conversational_and_keep_details_private(
    tmp_path: Path, capsys
) -> None:
    kb = _load_kb_cli()

    assert kb.main(["--root", str(tmp_path), "obsidian", "status"]) == 0
    empty_output = capsys.readouterr().out
    assert empty_output == "知识库目前为空；Obsidian 视图无需生成。\n"
    assert not (tmp_path / "kb").exists()

    _record(tmp_path, "p-alpha-12345678", "Alpha")
    assert kb.main(["--root", str(tmp_path), "obsidian", "update"]) == 0
    updated_output = capsys.readouterr().out
    assert "Obsidian 知识网络视图已更新" in updated_output
    assert ".agents/" not in updated_output
    assert "--root" not in updated_output
    assert "manifest" not in updated_output

    page = obsidian_managed_root(tmp_path) / "units/p-alpha-12345678.md"
    page.write_text("human edit\n", encoding="utf-8")
    assert kb.main(["--root", str(tmp_path), "obsidian", "update"]) == 1
    refused_output = capsys.readouterr().out
    assert "可能覆盖人工内容或不安全路径" in refused_output
    assert "units/" not in refused_output


def test_projection_update_is_undoable_without_touching_canonical_record(tmp_path: Path) -> None:
    record = _record(tmp_path, "p-alpha-12345678", "Alpha")
    canonical_path = record_path(tmp_path, "paper", record["id"])
    canonical_before = canonical_path.read_bytes()

    update_obsidian_projection(tmp_path)
    assert obsidian_managed_root(tmp_path).is_dir()
    undo_last_operation(tmp_path)

    assert not obsidian_managed_root(tmp_path).exists()
    assert not (tmp_path / "kb/obsidian/inbox").exists()
    assert not (tmp_path / "kb/obsidian/annotations").exists()
    assert canonical_path.read_bytes() == canonical_before


def test_concurrent_projection_updates_serialize_and_converge(tmp_path: Path, monkeypatch) -> None:
    _record(tmp_path, "p-alpha-12345678", "Alpha")
    barrier = threading.Barrier(2)
    original = obsidian_module._projection_files

    def synchronized_projection_files(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(obsidian_module, "_projection_files", synchronized_projection_files)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: update_obsidian_projection(tmp_path), range(2)))

    assert all(result["status"]["status"] == "PASS" for result in results)
    assert obsidian_projection_status(tmp_path)["status"] == "PASS"

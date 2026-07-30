from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, default_runtime_preferences, ensure_workspace, record_path
from research.evidence import build_verification_receipt
from research.paths import runtime_preferences_path
from research.obsidian import update_obsidian_projection
import research.review_batches as review_batches_module
from research.review_batches import (
    ReviewBatchError,
    create_obsidian_review_batch,
    preflight_obsidian_review_batch,
    preview_obsidian_review_batch,
)


def _load_kb_cli():
    project_root = REPO_ROOT
    script = project_root / "skills/kb-cli/scripts/kb"
    loader = importlib.machinery.SourceFileLoader("kb_cli_obsidian_review_roundtrip", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _preview_digest(root: Path, batch_ref: str) -> str:
    return preview_obsidian_review_batch(root, batch_ref).decision_digest


def _review_item(index: int) -> dict:
    unit_id = f"p-sheet-{index:02d}"
    binding = {
        "subject": {
            "kind": "paper",
            "id": unit_id,
            "owner": "knowledge-base-manager",
            "path": f"kb/units/papers/{unit_id}/record.yaml",
        },
        "confirmation_status": "pending_user_confirmation",
        "content_digest": hashlib.sha256(f"content-{index}".encode()).hexdigest(),
        "verification": {
            "verified_at": "2026-07-24T00:00:00Z",
            "claims_digest": hashlib.sha256(f"claims-{index}".encode()).hexdigest(),
            "evidence_digest": hashlib.sha256(f"evidence-{index}".encode()).hexdigest(),
        },
    }
    return {
        "subject": {"kind": "paper", "id": unit_id, "owner": "knowledge-base-manager"},
        "display": {"kind": "paper", "title": f"Paper {index}"},
        "confirm_route": {"owner": "knowledge-base-manager", "action": "confirm", "id": unit_id},
        "reject_route": {
            "owner": "knowledge-base-manager",
            "action": "promote",
            "id": unit_id,
            "confirmation_status": "rejected",
        },
        "snapshot_binding": binding,
    }


def _display_item(index: int) -> dict:
    return {
        "kind_label": "论文",
        "title": "Same title" if index <= 2 else f"Paper {index}",
        "subject_id": f"p-sheet-{index:02d}",
        "location_summary": f"来源位置 {index}",
        "fact_summary": "",
        "substance": [],
        "claims": [
            {
                "type_label": "评价",
                "text": f"完整判断 {index}",
                "evidence": f"逐字证据 {index}",
                "extra_evidence_count": index,
            }
        ],
    }


def _source_snapshot(
    root: Path,
    items: list[dict],
    *,
    token: str = "a" * 32,
    item_limit: int | None = None,
    governance_profile: str | None = None,
) -> str:
    path = root / f"kb/.runtime/review-snapshots/{token}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "kb-review-snapshot/v2",
        "created_at": "2026-07-24T00:00:00Z",
        "expires_at": "2099-07-25T00:00:00Z",
        "status": "unused",
        "review_items": items,
    }
    if item_limit is not None:
        payload["item_limit"] = item_limit
    if governance_profile is not None:
        payload["governance_profile"] = governance_profile
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return token


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        if path.is_symlink():
            digest.update(b"L" + path.readlink().as_posix().encode())
        elif path.is_file():
            digest.update(b"F" + path.read_bytes())
        else:
            digest.update(b"D")
    return digest.hexdigest()


def _create_batch(root: Path, count: int = 2) -> tuple[dict, list[dict]]:
    items = [_review_item(index) for index in range(1, count + 1)]
    token = _source_snapshot(root, items)
    created = create_obsidian_review_batch(
        root,
        source_snapshot_token=token,
        review_items=items,
        display_items=[_display_item(index) for index in range(1, count + 1)],
    )
    return created, items


def test_sheet_preview_is_checkbox_only_pure_read_and_preflights_all_items(tmp_path: Path) -> None:
    annotation = tmp_path / "kb/obsidian/annotations/human-note.md"
    annotation.parent.mkdir(parents=True)
    annotation.write_text("keep this human note\n", encoding="utf-8")
    created, items = _create_batch(tmp_path)
    sheet = tmp_path / created["sheet_relative_path"]
    text = sheet.read_text(encoding="utf-8")
    assert not text.startswith("---")
    assert "schema:" not in text
    assert "review_intent_draft" not in text
    assert "knowledge-base-manager" not in text
    assert "kb/units/" not in text
    assert "完整判断 1" in text and "逐字证据 2" in text
    assert "有效至：2099-07-25T00:00:00Z" in text
    assert "公共编号：p-sheet-01" in text and "公共编号：p-sheet-02" in text
    assert "来源 / 定位：来源位置 1" in text and "来源 / 定位：来源位置 2" in text
    assert text.count("Same title") == 2
    text = text.replace("- [ ] 确认", "- [x] 确认", 1)
    second = text.find("- [ ] 拒绝", text.find("<!-- kb-review-slot:", text.find("<!-- kb-review-slot:") + 1))
    assert second >= 0
    text = text[:second] + text[second:].replace("- [ ] 拒绝", "- [x] 拒绝", 1)
    sheet.write_text(text, encoding="utf-8")

    before = _tree_digest(tmp_path / "kb")
    preview = preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert [item["decision"] for item in preview.decisions] == ["confirm", "reject"]
    assert len(preview.decision_digest) == 64
    calls: list[str] = []

    def resolver(subject):
        calls.append(str(subject["id"]))
        return next(item for item in items if item["subject"] == subject)

    preflight = preflight_obsidian_review_batch(
        tmp_path,
        created["batch_ref"],
        current_item_resolver=resolver,
    )
    assert preflight.requires_owner_atomic_apply is True
    assert calls == ["p-sheet-01", "p-sheet-02"]
    assert _tree_digest(tmp_path / "kb") == before
    assert annotation.read_text(encoding="utf-8") == "keep this human note\n"
    sheet_before = sheet.read_bytes()
    update_obsidian_projection(tmp_path)
    assert sheet.read_bytes() == sheet_before
    assert annotation.read_text(encoding="utf-8") == "keep this human note\n"


def test_personal_batch_binds_a_limit_above_three_and_rejects_limit_mismatch(tmp_path: Path) -> None:
    items = [_review_item(index) for index in range(1, 11)]
    token = _source_snapshot(tmp_path, items, item_limit=10, governance_profile="personal")
    created = create_obsidian_review_batch(
        tmp_path,
        source_snapshot_token=token,
        review_items=items,
        display_items=[_display_item(index) for index in range(1, 11)],
        item_limit=10,
    )

    assert created["item_count"] == 10
    assert created["item_limit"] == 10
    registry = json.loads(
        (tmp_path / f"kb/.runtime/review-batches/{created['batch_ref']}.json").read_text(encoding="utf-8")
    )
    assert registry["item_limit"] == 10
    assert registry["governance_profile"] == "personal"

    other_root = tmp_path / "mismatch"
    other_token = _source_snapshot(other_root, items, item_limit=10, governance_profile="personal")
    with pytest.raises(ReviewBatchError) as mismatch:
        create_obsidian_review_batch(
            other_root,
            source_snapshot_token=other_token,
            review_items=items,
            display_items=[_display_item(index) for index in range(1, 11)],
            item_limit=9,
        )
    assert mismatch.value.code == "tampered_or_unknown"


def test_strict_obsidian_source_cannot_raise_the_three_item_limit(tmp_path: Path) -> None:
    items = [_review_item(index) for index in range(1, 5)]
    token = _source_snapshot(tmp_path, items, item_limit=10, governance_profile="strict")

    with pytest.raises(ReviewBatchError) as weakened:
        create_obsidian_review_batch(
            tmp_path,
            source_snapshot_token=token,
            review_items=items,
            display_items=[_display_item(index) for index in range(1, 5)],
            item_limit=10,
        )

    assert weakened.value.code == "tampered_or_unknown"


def test_legacy_batch_without_bound_limit_remains_readable_at_three_item_cap(tmp_path: Path) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    old_ref = created["batch_ref"]
    old_registry = tmp_path / f"kb/.runtime/review-batches/{old_ref}.json"
    payload = json.loads(old_registry.read_text(encoding="utf-8"))
    payload.pop("item_limit")
    payload.pop("governance_profile")
    payload.pop("batch_ref")
    legacy_ref = review_batches_module._batch_ref(payload)
    payload["batch_ref"] = legacy_ref
    legacy_registry = old_registry.with_name(f"{legacy_ref}.json")
    legacy_registry.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    old_registry.unlink()

    old_sheet = tmp_path / created["sheet_relative_path"]
    legacy_sheet = old_sheet.with_name(f"Pending Review {legacy_ref[:12]}.md")
    text = old_sheet.read_text(encoding="utf-8").replace(old_ref, legacy_ref)
    text = text.replace("- [ ] 暂缓", "- [x] 暂缓", 1)
    legacy_sheet.write_text(text, encoding="utf-8")
    old_sheet.unlink()

    preview = preview_obsidian_review_batch(tmp_path, legacy_ref)
    assert [item["decision"] for item in preview.decisions] == ["defer"]


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (lambda text: text, "invalid_decision"),
        (
            lambda text: text.replace("- [ ] 确认", "- [x] 确认", 1).replace("- [ ] 拒绝", "- [x] 拒绝", 1),
            "invalid_decision",
        ),
        (
            lambda text: text.replace("完整判断 1", "被修改的判断", 1).replace("- [ ] 确认", "- [x] 确认", 1),
            "sheet_tampered",
        ),
        (
            lambda text: text.replace("- [ ] 确认", "- [x] 确认\n- [x] 确认", 1),
            "sheet_tampered",
        ),
    ],
)
def test_sheet_rejects_missing_conflicting_and_non_checkbox_edits(tmp_path: Path, edit, code: str) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    sheet = tmp_path / created["sheet_relative_path"]
    sheet.write_text(edit(sheet.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ReviewBatchError) as exc:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert exc.value.code == code


def test_batch_expiry_replay_and_stale_binding_are_pure_failures(tmp_path: Path) -> None:
    created, items = _create_batch(tmp_path, count=1)
    sheet = tmp_path / created["sheet_relative_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 暂缓", "- [x] 暂缓", 1), encoding="utf-8")
    before = _tree_digest(tmp_path / "kb")
    with pytest.raises(ReviewBatchError) as expired:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"], now=4_200_000_000.0)
    assert expired.value.code == "expired"
    assert _tree_digest(tmp_path / "kb") == before

    with pytest.raises(ReviewBatchError) as stale:
        preflight_obsidian_review_batch(
            tmp_path,
            created["batch_ref"],
            current_item_resolver=lambda _subject: {
                **items[0],
                "snapshot_binding": {**items[0]["snapshot_binding"], "content_digest": "f" * 64},
            },
        )
    assert stale.value.code == "stale_content"
    assert _tree_digest(tmp_path / "kb") == before

    registry = tmp_path / f"kb/.runtime/review-batches/{created['batch_ref']}.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["status"] = "consumed"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReviewBatchError) as replay:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert replay.value.code == "already_applied"


def test_immutable_registry_and_source_snapshot_tampering_fail_closed(tmp_path: Path) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    sheet = tmp_path / created["sheet_relative_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 暂缓", "- [x] 暂缓", 1), encoding="utf-8")
    registry = tmp_path / f"kb/.runtime/review-batches/{created['batch_ref']}.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    source_token = payload["source_snapshot_token"]
    payload["review_items"][0]["display"]["title"] = "forged title"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReviewBatchError) as registry_error:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert registry_error.value.code == "tampered_or_unknown"

    created, _items = _create_batch(tmp_path / "source", count=1)
    source_root = tmp_path / "source"
    sheet = source_root / created["sheet_relative_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 暂缓", "- [x] 暂缓", 1), encoding="utf-8")
    registry = source_root / f"kb/.runtime/review-batches/{created['batch_ref']}.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    source_snapshot = source_root / f"kb/.runtime/review-snapshots/{payload['source_snapshot_token']}.json"
    source_payload = json.loads(source_snapshot.read_text(encoding="utf-8"))
    source_payload["review_items"][0]["display"]["title"] = "forged source title"
    source_snapshot.write_text(json.dumps(source_payload), encoding="utf-8")
    with pytest.raises(ReviewBatchError) as source_error:
        preview_obsidian_review_batch(source_root, created["batch_ref"])
    assert source_error.value.code == "tampered_or_unknown"


@pytest.mark.parametrize("unsafe_title", ["forged\n- [x] 确认", "<!-- kb-review-slot:abc -->", "safe\u202etext"])
def test_export_rejects_reserved_or_hidden_display_injection(tmp_path: Path, unsafe_title: str) -> None:
    items = [_review_item(1)]
    token = _source_snapshot(tmp_path, items)
    display = _display_item(1)
    display["title"] = unsafe_title
    with pytest.raises(ReviewBatchError) as exc:
        create_obsidian_review_batch(
            tmp_path,
            source_snapshot_token=token,
            review_items=items,
            display_items=[display],
    )
    assert exc.value.code == "unsafe_display"
    annotations = tmp_path / "kb/obsidian/annotations"
    if annotations.exists():
        assert not list(annotations.glob("Pending Review *.md"))


def test_sheet_and_registry_symlinks_fail_closed_without_touching_external_files(tmp_path: Path) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    sheet = tmp_path / created["sheet_relative_path"]
    external = tmp_path / "external.md"
    external.write_text("external sentinel\n", encoding="utf-8")
    sheet.unlink()
    sheet.symlink_to(external)
    with pytest.raises(ReviewBatchError) as exc:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert exc.value.code == "tampered_or_unknown"
    assert external.read_text(encoding="utf-8") == "external sentinel\n"

    sheet.unlink()
    sheet.write_text("irrelevant\n", encoding="utf-8")
    registry = tmp_path / f"kb/.runtime/review-batches/{created['batch_ref']}.json"
    external_registry = tmp_path / "external.json"
    external_registry.write_text(registry.read_text(encoding="utf-8"), encoding="utf-8")
    registry.unlink()
    registry.symlink_to(external_registry)
    with pytest.raises(ReviewBatchError) as registry_error:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert registry_error.value.code == "tampered_or_unknown"
    assert external_registry.is_file()


def test_intermediate_directory_swap_cannot_redirect_review_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    sheet = tmp_path / created["sheet_relative_path"]
    sheet.write_text(
        sheet.read_text(encoding="utf-8").replace("- [ ] 暂缓", "- [x] 暂缓", 1),
        encoding="utf-8",
    )
    batches = tmp_path / "kb/.runtime/review-batches"
    displaced = tmp_path / "kb/.runtime/review-batches-displaced"
    external = tmp_path / "external-review-batches"
    external.mkdir()
    external_registry = external / f"{created['batch_ref']}.json"
    external_registry.write_text("external sentinel\n", encoding="utf-8")
    original_open = review_batches_module._open_safe_directory
    swapped = False

    def swap_after_open(project_root: Path, relative: str, *, create: bool) -> int:
        nonlocal swapped
        descriptor = original_open(project_root, relative, create=create)
        if relative == review_batches_module._RUNTIME_BATCHES_DIR and not swapped:
            batches.rename(displaced)
            batches.symlink_to(external, target_is_directory=True)
            swapped = True
        return descriptor

    monkeypatch.setattr(review_batches_module, "_open_safe_directory", swap_after_open)
    with pytest.raises(ReviewBatchError) as exc:
        preview_obsidian_review_batch(tmp_path, created["batch_ref"])
    assert exc.value.code == "tampered_or_unknown"
    assert external_registry.read_text(encoding="utf-8") == "external sentinel\n"
    assert (displaced / f"{created['batch_ref']}.json").is_file()


def test_intermediate_directory_swap_cannot_redirect_registry_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    filename = f"{created['batch_ref']}.json"
    batches = tmp_path / "kb/.runtime/review-batches"
    original_bytes = (batches / filename).read_bytes()
    displaced = tmp_path / "kb/.runtime/review-batches-displaced"
    external = tmp_path / "external-review-batches"
    external.mkdir()
    external_registry = external / filename
    external_registry.write_text("external sentinel\n", encoding="utf-8")
    original_open = review_batches_module._open_safe_directory
    swapped = False

    def swap_after_open(project_root: Path, relative: str, *, create: bool) -> int:
        nonlocal swapped
        descriptor = original_open(project_root, relative, create=create)
        if relative == review_batches_module._RUNTIME_BATCHES_DIR and not swapped:
            batches.rename(displaced)
            batches.symlink_to(external, target_is_directory=True)
            swapped = True
        return descriptor

    monkeypatch.setattr(review_batches_module, "_open_safe_directory", swap_after_open)
    with pytest.raises(ReviewBatchError) as exc:
        review_batches_module._replace_regular_file_at(
            tmp_path,
            review_batches_module._RUNTIME_BATCHES_DIR,
            filename,
            b"replacement must not land outside\n",
        )
    assert exc.value.code == "tampered_or_unknown"
    assert external_registry.read_text(encoding="utf-8") == "external sentinel\n"
    assert (displaced / filename).read_bytes() == original_bytes


def test_late_directory_rename_cleans_new_file_before_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_batch(tmp_path, count=1)
    batches = tmp_path / "kb/.runtime/review-batches"
    moved = tmp_path / "moved/review-batches"
    moved.parent.mkdir()
    decoy = tmp_path / "decoy-review-batches"
    decoy.mkdir()
    original_assert = review_batches_module._assert_directory_fd_is_current
    checks = 0

    def rename_after_last_prewrite_check(project_root: Path, relative: str, descriptor: int) -> None:
        nonlocal checks
        original_assert(project_root, relative, descriptor)
        checks += 1
        if checks == 1:
            batches.rename(moved)
            batches.symlink_to(decoy, target_is_directory=True)

    monkeypatch.setattr(
        review_batches_module,
        "_assert_directory_fd_is_current",
        rename_after_last_prewrite_check,
    )
    with pytest.raises(ReviewBatchError) as exc:
        review_batches_module._write_new_regular_file_at(
            tmp_path,
            review_batches_module._RUNTIME_BATCHES_DIR,
            "late-swap.json",
            b"must be cleaned\n",
        )
    assert exc.value.code == "tampered_or_unknown"
    assert not (moved / "late-swap.json").exists()
    assert not (decoy / "late-swap.json").exists()


def test_late_directory_rename_restores_replaced_registry_before_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    filename = f"{created['batch_ref']}.json"
    batches = tmp_path / "kb/.runtime/review-batches"
    original_bytes = (batches / filename).read_bytes()
    moved = tmp_path / "moved/review-batches"
    moved.parent.mkdir()
    decoy = tmp_path / "decoy-review-batches"
    decoy.mkdir()
    original_assert = review_batches_module._assert_directory_fd_is_current
    checks = 0

    def rename_after_last_prereplace_check(project_root: Path, relative: str, descriptor: int) -> None:
        nonlocal checks
        original_assert(project_root, relative, descriptor)
        checks += 1
        if checks == 2:
            batches.rename(moved)
            batches.symlink_to(decoy, target_is_directory=True)

    monkeypatch.setattr(
        review_batches_module,
        "_assert_directory_fd_is_current",
        rename_after_last_prereplace_check,
    )
    with pytest.raises(ReviewBatchError) as exc:
        review_batches_module._replace_regular_file_at(
            tmp_path,
            review_batches_module._RUNTIME_BATCHES_DIR,
            filename,
            b"replacement must be rolled back\n",
        )
    assert exc.value.code == "tampered_or_unknown"
    assert (moved / filename).read_bytes() == original_bytes
    assert not (decoy / filename).exists()
    assert not list(moved.glob(f".{filename}.*"))


def test_directory_fsync_failure_restores_registry_before_reporting_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    filename = f"{created['batch_ref']}.json"
    batches = tmp_path / "kb/.runtime/review-batches"
    target = batches / filename
    original = target.read_bytes()
    real_fsync = review_batches_module.os.fsync
    failed = False

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal failed
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) and not failed:
            failed = True
            raise OSError("injected directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(review_batches_module.os, "fsync", fail_first_directory_fsync)
    with pytest.raises(OSError, match="injected directory fsync failure"):
        review_batches_module._replace_regular_file_at(
            tmp_path,
            review_batches_module._RUNTIME_BATCHES_DIR,
            filename,
            b"replacement must be rolled back\n",
        )
    assert target.read_bytes() == original
    assert not list(batches.glob(f".{filename}.*"))


def test_failed_rollback_fsync_preserves_old_inode_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    filename = f"{created['batch_ref']}.json"
    batches = tmp_path / "kb/.runtime/review-batches"
    target = batches / filename
    original = target.read_bytes()
    real_fsync = review_batches_module.os.fsync

    def fail_every_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("persistent directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(review_batches_module.os, "fsync", fail_every_directory_fsync)
    with pytest.raises(OSError, match="persistent directory fsync failure"):
        review_batches_module._replace_regular_file_at(
            tmp_path,
            review_batches_module._RUNTIME_BATCHES_DIR,
            filename,
            b"replacement must not become authoritative\n",
        )
    assert target.read_bytes() == original
    backups = list(batches.glob(f".{filename}.*.before"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_concurrent_registry_replace_between_check_and_backup_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _items = _create_batch(tmp_path, count=1)
    filename = f"{created['batch_ref']}.json"
    batches = tmp_path / "kb/.runtime/review-batches"
    target = batches / filename
    concurrent = batches / "concurrent.json"
    concurrent.write_bytes(b"CONCURRENT\n")
    real_link = review_batches_module.os.link
    swapped = False

    def swap_before_link(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            os.replace(concurrent, target)
            swapped = True
        return real_link(*args, **kwargs)

    monkeypatch.setattr(review_batches_module.os, "link", swap_before_link)
    with pytest.raises(ReviewBatchError) as exc:
        review_batches_module._replace_regular_file_at(
            tmp_path,
            review_batches_module._RUNTIME_BATCHES_DIR,
            filename,
            b"NEW\n",
        )
    assert exc.value.code == "tampered_or_unknown"
    assert target.read_bytes() == b"CONCURRENT\n"
    assert not list(batches.glob(f".{filename}.*"))


def _write_ready_unit(root: Path, unit_id: str = "p-obsidian-roundtrip-123456") -> Path:
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# isolated fixture\n", encoding="utf-8")
    ensure_workspace(root)
    preferences = default_runtime_preferences()
    preferences["identity"]["default_confirmed_by"] = "Human Reviewer"
    write_yaml_if_changed(runtime_preferences_path(root), preferences)
    path = record_path(root, "paper", unit_id)
    unit_root = path.parent
    (unit_root / "raw").mkdir(parents=True, exist_ok=True)
    quote = "The source supports the complete review-sheet judgement."
    (unit_root / "raw/source.txt").write_text(quote, encoding="utf-8")
    record = default_record("paper", title="Obsidian review sheet", maturity="complete", source={"original_uri": "fixture"})
    record.update(
        id=unit_id,
        status="screened",
        confirmation_status="pending_user_confirmation",
        needs_human_confirmation=True,
        information_types=["evaluation", "unverified"],
    )
    record["payload"]["core_content"]["research_problem"] = "Validate the no-plugin review exchange."
    record["payload"]["claims"] = [
        {
            "id": "obsidian-review-claim",
            "text": "The review sheet is ready for an explicit human decision.",
            "claim_type": "evaluation",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "raw/source.txt",
                    "locator": "fixture",
                    "quote": quote,
                }
            ],
        }
    ]
    build_verification_receipt(record, unit_root, source_roots={unit_id: unit_root})
    write_yaml_if_changed(path, record)
    return path


def test_kb_cli_exports_previews_and_atomically_applies_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_cli()
    record = _write_ready_unit(tmp_path)
    repo = tmp_path / "kb"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "obsidian-export.json",
            "review",
            "--obsidian-export",
        ]
    ) == 0
    export_public = capsys.readouterr()
    assert "已在 Obsidian 的人工批注区生成可编辑待确认表" in export_public.out
    assert "kb/obsidian" not in export_public.out
    protocol = json.loads((tmp_path / "kb/.runtime/obsidian-export.json").read_text(encoding="utf-8"))
    sheet_action = next(item for item in protocol["next_actions"] if item["action"] == "open_obsidian_review_sheet")
    batch_ref = sheet_action["batch_ref"]
    sheet = tmp_path / sheet_action["sheet_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 确认", "- [x] 确认", 1), encoding="utf-8")
    canonical_before = record.read_bytes()

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "obsidian-preview.json",
            "review",
            "--preview-obsidian-batch",
            batch_ref,
        ]
    ) == 0
    preview_public = capsys.readouterr()
    assert "这些勾选尚未修改知识库" in preview_public.out
    assert record.read_bytes() == canonical_before
    preview_protocol = json.loads((tmp_path / "kb/.runtime/obsidian-preview.json").read_text(encoding="utf-8"))
    preview_action = next(
        item for item in preview_protocol["next_actions"] if item["action"] == "present_obsidian_review_diff"
    )
    expected_preview_digest = preview_action["apply"]["expected_preview_digest"]

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "obsidian-apply.json",
            "review",
            "--apply-obsidian-batch",
            batch_ref,
            "--expected-preview-digest",
            expected_preview_digest,
            "--decision-evidence",
            "I reviewed the displayed evidence.",
            "--user-authorization",
            "按刚才预览的决定同步。",
        ]
    ) == 0
    apply_public = capsys.readouterr()
    assert "作为一个整体同步" in apply_public.out
    assert "git checkpoint" not in apply_public.out
    assert "[ok]" not in apply_public.out
    assert record.read_bytes() != canonical_before
    confirmed = load_yaml(record, default={})
    assert confirmed["confirmation_status"] == "confirmed"
    assert confirmed["confirmation"]["method"] == "kb review"
    batch_registry = json.loads(
        (tmp_path / f"kb/.runtime/review-batches/{batch_ref}.json").read_text(encoding="utf-8")
    )
    source_token = batch_registry["source_snapshot_token"]
    source_registry = json.loads(
        (tmp_path / f"kb/.runtime/review-snapshots/{source_token}.json").read_text(encoding="utf-8")
    )
    assert batch_registry["status"] == "consumed"
    assert source_registry["status"] == "consumed"
    applied_sheet = sheet.read_text(encoding="utf-8")
    assert "# 已处理判断" in applied_sheet
    assert "作为一个整体应用" in applied_sheet
    assert "- [x] 确认" in applied_sheet
    assert subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    applied = record.read_bytes()
    assert kb.main(
        [
            "--root", str(tmp_path), "--agent-protocol", "obsidian-replay.json", "review",
            "--apply-obsidian-batch", batch_ref, "--decision-evidence", "reviewed",
            "--expected-preview-digest", expected_preview_digest,
            "--user-authorization", "再次同步。",
        ]
    ) == 2
    replay_public = capsys.readouterr()
    assert "已经应用过" in replay_public.err
    assert record.read_bytes() == applied


def test_kb_cli_owner_failure_rolls_back_every_canonical_write_and_keeps_batch_unused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = _load_kb_cli()
    first = _write_ready_unit(tmp_path, "p-obsidian-rollback-000001")
    second = _write_ready_unit(tmp_path, "p-obsidian-rollback-000002")
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "rollback-export.json", "review", "--obsidian-export",
    ]) == 0
    capsys.readouterr()
    protocol = json.loads((tmp_path / "kb/.runtime/rollback-export.json").read_text(encoding="utf-8"))
    action = next(item for item in protocol["next_actions"] if item["action"] == "open_obsidian_review_sheet")
    batch_ref = action["batch_ref"]
    sheet = tmp_path / action["sheet_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 确认", "- [x] 确认"), encoding="utf-8")
    sheet_before = sheet.read_bytes()
    expected_preview_digest = _preview_digest(tmp_path, batch_ref)
    passage_cache = tmp_path / "kb/.runtime/search/passages.sqlite3"
    assert not passage_cache.exists()
    before = {first: first.read_bytes(), second: second.read_bytes()}

    module = kb._review_owner_module(tmp_path, "knowledge-base-manager")
    real_apply = module.apply_review_batch_decision
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-owner failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(module, "apply_review_batch_decision", fail_second)
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "rollback-apply.json", "review",
        "--apply-obsidian-batch", batch_ref, "--expected-preview-digest", expected_preview_digest,
        "--decision-evidence", "reviewed both",
        "--user-authorization", "按预览一次同步全部。",
    ]) == 2
    capsys.readouterr()
    assert calls == 2
    assert first.read_bytes() == before[first]
    assert second.read_bytes() == before[second]
    batch_registry = json.loads((tmp_path / f"kb/.runtime/review-batches/{batch_ref}.json").read_text(encoding="utf-8"))
    source_registry = json.loads(
        (tmp_path / f"kb/.runtime/review-snapshots/{batch_registry['source_snapshot_token']}.json").read_text(encoding="utf-8")
    )
    assert batch_registry["status"] == "unused"
    assert source_registry["status"] == "unused"
    assert sheet.read_bytes() == sheet_before
    assert "# 待确认判断" in sheet.read_text(encoding="utf-8")
    assert not passage_cache.exists()


def test_checkpoint_failure_is_private_and_protocol_reports_post_apply_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = _load_kb_cli()
    record = _write_ready_unit(tmp_path, "p-obsidian-checkpoint-failure-000001")
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "checkpoint-export.json", "review", "--obsidian-export",
    ]) == 0
    capsys.readouterr()
    exported = json.loads((tmp_path / "kb/.runtime/checkpoint-export.json").read_text(encoding="utf-8"))
    action = next(item for item in exported["next_actions"] if item["action"] == "open_obsidian_review_sheet")
    batch_ref = action["batch_ref"]
    sheet = tmp_path / action["sheet_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 确认", "- [x] 确认", 1), encoding="utf-8")
    preview_digest = _preview_digest(tmp_path, batch_ref)

    def fail_checkpoint(*args, **kwargs):
        print("[ok] git checkpoint: private-deadbeef")
        raise RuntimeError("injected checkpoint failure")

    monkeypatch.setattr(kb, "checkpoint_and_report", fail_checkpoint)
    with pytest.raises(RuntimeError, match="injected checkpoint failure"):
        kb.main([
            "--root", str(tmp_path), "--agent-protocol", "checkpoint-apply.json", "review",
            "--apply-obsidian-batch", batch_ref,
            "--expected-preview-digest", preview_digest,
            "--decision-evidence", "reviewed",
            "--user-authorization", "按预览同步。",
        ])
    public = capsys.readouterr()
    assert "checkpoint" not in public.out + public.err
    assert load_yaml(record, default={})["confirmation_status"] == "confirmed"
    registry = json.loads((tmp_path / f"kb/.runtime/review-batches/{batch_ref}.json").read_text(encoding="utf-8"))
    assert registry["status"] == "consumed"
    protocol = json.loads((tmp_path / "kb/.runtime/checkpoint-apply.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "error"
    assert protocol["exit_code"] == 1
    assert protocol["details"]["checkpoint_status"] == "failed_after_business_apply"
    assert protocol["details"]["business_state"] == "applied_before_checkpoint"


def test_apply_is_bound_to_previewed_choices_and_current_user_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_cli()
    record = _write_ready_unit(tmp_path, "p-obsidian-auth-binding-000001")
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "auth-export.json", "review", "--obsidian-export",
    ]) == 0
    capsys.readouterr()
    protocol = json.loads((tmp_path / "kb/.runtime/auth-export.json").read_text(encoding="utf-8"))
    action = next(item for item in protocol["next_actions"] if item["action"] == "open_obsidian_review_sheet")
    batch_ref = action["batch_ref"]
    sheet = tmp_path / action["sheet_path"]
    original = sheet.read_text(encoding="utf-8")
    sheet.write_text(original.replace("- [ ] 确认", "- [x] 确认", 1), encoding="utf-8")
    previewed_confirm = _preview_digest(tmp_path, batch_ref)
    canonical_before = record.read_bytes()

    changed = sheet.read_text(encoding="utf-8").replace("- [x] 确认", "- [ ] 确认", 1)
    changed = changed.replace("- [ ] 拒绝", "- [x] 拒绝", 1)
    sheet.write_text(changed, encoding="utf-8")
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "auth-stale.json", "review",
        "--apply-obsidian-batch", batch_ref,
        "--expected-preview-digest", previewed_confirm,
        "--user-authorization", "按刚才预览的确认决定同步。",
        "--decision-evidence", "reviewed",
        "--rejection-reason", "not suitable",
    ]) == 2
    assert "重新预览" in capsys.readouterr().err
    assert record.read_bytes() == canonical_before

    previewed_reject = _preview_digest(tmp_path, batch_ref)
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "auth-missing.json", "review",
        "--apply-obsidian-batch", batch_ref,
        "--expected-preview-digest", previewed_reject,
        "--rejection-reason", "not suitable",
    ]) == 2
    capsys.readouterr()
    assert record.read_bytes() == canonical_before
    registry = json.loads((tmp_path / f"kb/.runtime/review-batches/{batch_ref}.json").read_text(encoding="utf-8"))
    assert registry["status"] == "unused"


def test_concurrent_replay_has_exactly_one_winner(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb = _load_kb_cli()
    record = _write_ready_unit(tmp_path, "p-obsidian-concurrent-000001")
    assert kb.main([
        "--root", str(tmp_path), "--agent-protocol", "concurrent-export.json", "review", "--obsidian-export",
    ]) == 0
    capsys.readouterr()
    protocol = json.loads((tmp_path / "kb/.runtime/concurrent-export.json").read_text(encoding="utf-8"))
    action = next(item for item in protocol["next_actions"] if item["action"] == "open_obsidian_review_sheet")
    batch_ref = action["batch_ref"]
    sheet = tmp_path / action["sheet_path"]
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("- [ ] 确认", "- [x] 确认", 1), encoding="utf-8")
    expected_preview_digest = _preview_digest(tmp_path, batch_ref)
    monkeypatch.setattr(kb, "checkpoint_and_report", lambda *args, **kwargs: {"committed": False})
    args = kb.argparse.Namespace(
        apply_obsidian_batch=batch_ref,
        expected_preview_digest=expected_preview_digest,
        user_authorization="按预览同步。",
        decision_evidence=["reviewed"],
        rejection_reason="",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: kb.handle_obsidian_review_apply(args, tmp_path), range(2)))
    capsys.readouterr()
    assert sorted(results) == [0, 2]
    assert load_yaml(record, default={})["confirmation_status"] == "confirmed"
    registry = json.loads((tmp_path / f"kb/.runtime/review-batches/{batch_ref}.json").read_text(encoding="utf-8"))
    source = json.loads(
        (tmp_path / f"kb/.runtime/review-snapshots/{registry['source_snapshot_token']}.json").read_text(encoding="utf-8")
    )
    assert registry["status"] == source["status"] == "consumed"

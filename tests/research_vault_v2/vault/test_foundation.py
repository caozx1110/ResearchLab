from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[3] / "skills" / "research-vault" / "scripts" / "vault.py"
SKILL_PATH = MODULE_PATH.parents[1] / "SKILL.md"
CONTRACT_PATH = MODULE_PATH.parents[1] / "references" / "v2-contract.md"
SPEC = importlib.util.spec_from_file_location("research_vault_foundation", MODULE_PATH)
assert SPEC and SPEC.loader
vault = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vault
SPEC.loader.exec_module(vault)


@pytest.fixture
def fresh_vault(tmp_path: Path) -> Path:
    vault.initialize_vault(tmp_path)
    return tmp_path


def test_skill_uses_only_the_local_v2_contract_reference() -> None:
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    contract_text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "(references/v2-contract.md)" in skill_text
    assert "SCHEMAS.md" not in skill_text
    assert "SCHEMAS.md" not in contract_text
    assert "Visible ordinary Markdown is the only human semantic truth." in contract_text


def test_fresh_vault_has_root_layout_and_plain_markdown_home(fresh_vault: Path) -> None:
    expected_directories = {
        "Inbox",
        "Sources",
        "Notes",
        "Projects",
        "Decisions",
        "Experiments",
        "Reviews",
        "Reports",
        "Views",
        ".research/index",
        ".research/evidence",
        ".research/receipts",
        ".research/operations",
        ".research/experiments",
        ".research/recovery",
        ".research/cache",
        ".research/logs",
        ".research/locks",
    }
    assert all((fresh_vault / path).is_dir() for path in expected_directories)
    home = (fresh_vault / "Home.md").read_text(encoding="utf-8")
    assert home.startswith("# Research Home\n")
    assert "[Active projects][active-projects]" in home
    assert "[active-projects]: Views/Active%20Projects.md" in home
    assert not (fresh_vault / "Home.md").read_bytes().startswith(b"---")
    assert not (fresh_vault / "record.yaml").exists()
    assert not (fresh_vault / "kb").exists()


def test_initialization_is_idempotent_and_rejects_legacy_roots(tmp_path: Path) -> None:
    vault.initialize_vault(tmp_path)
    home_before = (tmp_path / "Home.md").read_bytes()
    (tmp_path / "Home.md").write_bytes(home_before + b"\nUser edit.\n")
    vault.initialize_vault(tmp_path)
    assert (tmp_path / "Home.md").read_bytes() == home_before + b"\nUser edit.\n"

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "kb").mkdir()
    with pytest.raises(vault.ReservedPathError):
        vault.initialize_vault(legacy)


def test_path_classes_keep_hidden_data_nonsemantic(fresh_vault: Path) -> None:
    assert vault.classify_path(fresh_vault, "Home.md") == vault.PathClass.SEMANTIC
    assert vault.classify_path(fresh_vault, "Sources/src-one/.source/manifest.json") == vault.PathClass.SOURCE
    assert vault.classify_path(fresh_vault, ".research/evidence/binding.json") == vault.PathClass.PERSISTENT_PROOF
    assert vault.classify_path(fresh_vault, ".research/index/pages.json") == vault.PathClass.DERIVED
    assert vault.classify_path(fresh_vault, ".research/locks/path.lock") == vault.PathClass.TEMPORARY
    assert vault.classify_path(fresh_vault, ".obsidian/app.json") == vault.PathClass.USER_OWNED
    assert vault.classify_path(fresh_vault, "kb/units/note/record.yaml") == vault.PathClass.RESERVED
    assert not vault.is_semantic_path(fresh_vault, ".research/evidence/binding.json")


def test_reserved_and_symlink_targets_fail_closed(fresh_vault: Path, tmp_path: Path) -> None:
    with pytest.raises(vault.ReservedPathError):
        vault.atomic_write(fresh_vault / "kb" / "record.yaml", "bad", root=fresh_vault)
    with pytest.raises(vault.ReservedPathError):
        vault.atomic_write(fresh_vault / "record.yaml", "bad", root=fresh_vault)
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    link = fresh_vault / "Notes" / "escape.md"
    link.symlink_to(outside)
    with pytest.raises(vault.ContainmentError):
        vault.atomic_write(link, "overwrite", root=fresh_vault)


def test_pages_keep_identity_across_path_changes_and_links_are_stable(fresh_vault: Path) -> None:
    page = vault.create_page(
        fresh_vault,
        "Notes/first-note.md",
        page_id="note-first",
        kind="analysis",
        status="pending-review",
        title="First Note",
    )
    moved_path = fresh_vault / "Notes" / "renamed-note.md"
    moved_path.write_bytes((fresh_vault / page.path).read_bytes())
    (fresh_vault / page.path).unlink()
    resolved = vault.resolve_id(fresh_vault, "note-first")
    assert resolved.path == Path("Notes/renamed-note.md")
    assert vault.stable_link(fresh_vault, "Home.md", resolved.path) == "Notes/renamed-note.md"
    assert vault.stable_link(fresh_vault, "Views/Active Projects.md", resolved.path) == "../Notes/renamed-note.md"


def test_atomic_write_and_cas_preserve_bytes_on_failure(fresh_vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = fresh_vault / "Notes" / "atomic.md"
    original = b"original\n"
    vault.atomic_write(target, original, expected_digest=None, root=fresh_vault)
    original_digest = vault.file_digest(target)
    with pytest.raises(vault.CASConflict):
        vault.atomic_write(target, "stale\n", expected_digest="0" * 64, root=fresh_vault)
    assert target.read_bytes() == original

    original_replace = vault.os.replace

    def fail_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr(vault.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        vault.atomic_write(target, "replacement\n", expected_digest=original_digest, root=fresh_vault)
    monkeypatch.setattr(vault.os, "replace", original_replace)
    assert target.read_bytes() == original
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_journal_abort_restores_exact_before_images(fresh_vault: Path) -> None:
    first = fresh_vault / "Notes" / "first.md"
    second = fresh_vault / "Notes" / "second.md"
    first.write_bytes(b"first-before\n")
    before_first = first.read_bytes()
    with pytest.raises(RuntimeError, match="stop"):
        with vault.journaled_operation(fresh_vault, "test-abort", [first, second]) as operation:
            operation.write(first, b"first-after\n")
            operation.write(second, b"second-after\n")
            raise RuntimeError("stop")
    assert first.read_bytes() == before_first
    assert not second.exists()
    journals = list((fresh_vault / ".research" / "operations").glob("*/journal.json"))
    journal = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in journals
        if json.loads(path.read_text(encoding="utf-8"))["name"] == "test-abort"
    )
    assert journal["state"] == "abort"
    assert journal["checkpoint"]["paths"] == ["Notes/first.md", "Notes/second.md"]


def test_recovery_restores_an_abandoned_operation(fresh_vault: Path) -> None:
    target = fresh_vault / "Notes" / "recover.md"
    target.write_bytes(b"before\n")
    operation = vault.begin_operation(fresh_vault, "test-recovery", [target])
    operation.write(target, b"after\n")
    operation.abandon()
    recovered = vault.recover_operation(fresh_vault, operation.operation_id)
    assert recovered["state"] == "recovered"
    assert target.read_bytes() == b"before\n"


def test_index_rebuild_is_derived_and_does_not_touch_home(fresh_vault: Path) -> None:
    home_before = (fresh_vault / "Home.md").read_bytes()
    result = vault.rebuild_index(fresh_vault)
    pages = json.loads((fresh_vault / ".research/index/pages.json").read_text(encoding="utf-8"))
    links = json.loads((fresh_vault / ".research/index/links.json").read_text(encoding="utf-8"))
    assert result["schema"] == "research-vault-index/v2"
    assert any(item["id"] == "project-vault-v2" for item in pages["pages"])
    assert any(item["source"] == "Home.md" for item in links["links"])
    assert (fresh_vault / "Home.md").read_bytes() == home_before
    assert vault.classify_path(fresh_vault, ".research/index/pages.json") == vault.PathClass.DERIVED
    assert vault.GENERATED_VIEW_MARKER in (fresh_vault / "Views/Active Projects.md").read_text(encoding="utf-8")


def test_rebuild_refuses_to_overwrite_edited_derived_view(fresh_vault: Path) -> None:
    view = fresh_vault / "Views" / "Active Projects.md"
    view.write_text("# User-owned view\n", encoding="utf-8")
    with pytest.raises(vault.OwnershipError):
        vault.rebuild_index(fresh_vault)

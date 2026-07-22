from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, link_records, record_path, undo_last_operation
from research.obsidian import (
    OBSIDIAN_RENDERER_REVISION,
    obsidian_managed_root,
    obsidian_projection_status,
    update_obsidian_projection,
)
from research.relations import project_relation_edges
import research.obsidian as obsidian_module


def _load_kb_cli():
    project_root = Path(__file__).resolve().parents[4]
    script = project_root / ".agents/skills/kb-cli/scripts/kb"
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

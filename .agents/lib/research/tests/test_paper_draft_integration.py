from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

from research.bibliography import citation_key_for_unit_id
from research.common import load_yaml, write_text_if_changed, write_yaml_if_changed
from research.confirm import apply_confirmation, write_record
from research.evidence import build_verification_receipt
from research.figures import build_asset_binding, build_figure_entry, build_figure_index
from research.judgements import discover_pending_judgements, judgement_confirmation_is_current
from research.paper_drafts import SECTION_IDENTITIES
from research.paper_draft_runtime import (
    PaperDraftRuntimeError,
    load_paper_draft_inputs,
    paper_draft_fill_path,
    paper_draft_section_path,
)
from research.prefs import ensure_workspace
from research.records import default_record, kind_payload_skeleton


def _report_module():
    root = Path(__file__).resolve().parents[4]
    path = root / ".agents" / "skills" / "report-author" / "scripts" / "report.py"
    spec = importlib.util.spec_from_file_location("paper_draft_report_integration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _kb_module():
    root = Path(__file__).resolve().parents[4]
    path = root / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    loader = importlib.machinery.SourceFileLoader(
        "paper_draft_kb_integration", str(path)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _confirmed_paper(root: Path, index: int, *, with_figure: bool = False) -> tuple[str, str, str]:
    unit_id = f"p-draft-source-{index}-abcdef"
    unit_root = root / "kb" / "units" / "papers" / unit_id
    note = unit_root / "note.md"
    quote = f"Paper {index} provides exact evidence for the draft."
    write_text_if_changed(note, quote + "\n")
    payload = kind_payload_skeleton("paper", f"Draft Source {index}")
    citation_key = citation_key_for_unit_id(unit_id)
    payload["basic_info"].update(
        {
            "title": f"Draft Source {index}",
            "authors": [f"Author {index}"],
            "year": str(2020 + index),
            "doi": f"10.5555/draft.{index}",
            "citation_key": citation_key,
        }
    )
    payload["core_content"]["method"] = f"Confirmed method statement {index}."
    claim_id = f"claim-draft-source-{index}"
    payload["claims"] = [
        {
            "id": claim_id,
            "text": f"Confirmed source claim {index}.",
            "claim_type": "inference",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "note.md",
                    "locator": "line=1",
                    "quote": quote,
                }
            ],
        }
    ]
    record = default_record("paper", title=f"Draft Source {index}", maturity="complete")
    record.update(
        {
            "id": unit_id,
            "status": "active",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["inference"],
            "payload": payload,
        }
    )
    if with_figure:
        source = unit_root / "source" / "document.pdf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"paper-draft-source-pdf")
        asset_bytes = b"paper-draft-figure-png"
        binding = build_asset_binding(asset_bytes, page=1, source_mode="caption-region")
        asset = unit_root / binding["path"]
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(asset_bytes)
        entry = build_figure_entry(
            unit_id,
            kind="figure",
            number="1",
            caption="Figure 1. Draft integration overview",
            page=1,
            assets=[binding],
        )
        figure_index = build_figure_index(
            unit_id,
            source_artifact="source/document.pdf",
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            extraction_settings={"mode": "caption-region", "render_scale": 2.0},
            entries=[entry],
        )
        write_yaml_if_changed(unit_root / "figures.yaml", figure_index)
        payload["figures"] = {
            "schema": "figure-index/v1",
            "extraction_status": "indexed",
            "index_artifact": "figures.yaml",
            "index_digest": figure_index["index_digest"],
            "available_ref_keys": [entry["ref_key"]],
            "key_figure_refs": [],
        }
    build_verification_receipt(record, unit_root)
    apply_confirmation(
        record,
        confirmed_by="researcher",
        evidence=["The researcher reviewed this source claim."],
        user_authorization="I confirm this source claim.",
        authorization_source="user_message",
        method="test fixture",
        project_root=root,
        verification_root=unit_root,
    )
    write_record(root, record)
    figure_ref = f"fig:{unit_id}:fig:1" if with_figure else ""
    return unit_id, claim_id, figure_ref


def test_draft_inputs_bind_missing_selection_and_paths_reject_unknown_sections(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    program_id = "paper-draft-late-source"
    late_unit_id = "p-draft-source-9-abcdef"
    write_yaml_if_changed(
        root / "kb" / "programs" / program_id / "state.yaml",
        {
            "program_id": program_id,
            "status": "active",
            "stage": "writing",
            "active_unit_ids": [late_unit_id],
        },
    )
    outline = root / "kb" / "programs" / program_id / "reports" / "paper-outline.md"
    outline.parent.mkdir(parents=True, exist_ok=True)
    outline.write_text("# Outline\n", encoding="utf-8")

    inputs = load_paper_draft_inputs(root, program_id)
    assert inputs.is_current()
    assert _confirmed_paper(root, 9)[0] == late_unit_id
    assert not inputs.is_current()
    with pytest.raises(PaperDraftRuntimeError, match="section id"):
        paper_draft_section_path(root, program_id, "../escape")


def test_outline_to_seven_confirmed_sections_and_atomic_publication(tmp_path: Path) -> None:
    report = _report_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    program_id = "paper-draft-integration"
    sources = [
        _confirmed_paper(root, index, with_figure=index == 1)
        for index in range(1, 6)
    ]
    write_yaml_if_changed(
        root / "kb" / "programs" / program_id / "state.yaml",
        {
            "program_id": program_id,
            "status": "active",
            "stage": "writing",
            "active_unit_ids": [unit_id for unit_id, _claim_id, _figure in sources],
        },
    )
    outline_path = root / "kb" / "programs" / program_id / "reports" / "paper-outline.md"
    outline_bytes = b"# Evidence-bound paper outline\n"
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_bytes(outline_bytes)

    assert report.prepare_paper_draft(root, program_id) == 0
    manifest = load_yaml(root / "kb" / "programs" / program_id / "reports" / "paper-draft" / "manifest.yaml")
    assert [item["id"] for item in manifest["sections"]] == list(SECTION_IDENTITIES)
    guarded_fill = paper_draft_fill_path(root, program_id, "conclusion")
    guarded_bytes = guarded_fill.read_bytes()
    outside_fill = tmp_path / "outside-fill.yaml"
    outside_fill.write_bytes(b"do not overwrite\n")
    guarded_fill.unlink()
    guarded_fill.symlink_to(outside_fill)
    with pytest.raises(PaperDraftRuntimeError, match="路径不安全"):
        report.prepare_paper_draft(root, program_id)
    assert outside_fill.read_bytes() == b"do not overwrite\n"
    guarded_fill.unlink()
    guarded_fill.write_bytes(guarded_bytes)
    fills_dir = guarded_fill.parent
    outside_fills = tmp_path / "outside-fills"
    fills_dir.rename(outside_fills)
    fills_dir.symlink_to(outside_fills, target_is_directory=True)
    with pytest.raises(PaperDraftRuntimeError, match="路径不安全"):
        report.prepare_paper_draft(root, program_id)
    assert (outside_fills / guarded_fill.name).read_bytes() == guarded_bytes
    fills_dir.unlink()
    outside_fills.rename(fills_dir)
    source_unit, source_claim, figure_ref = sources[0]
    support_ref = f"{source_unit}:{source_claim}"
    citation_key = citation_key_for_unit_id(source_unit)
    for section_id in SECTION_IDENTITIES:
        fill_path = paper_draft_fill_path(root, program_id, section_id)
        fill = load_yaml(fill_path)
        fill["paragraphs"][0].update(
            {
                "prose": f"Agent-authored {section_id} paragraph grounded in confirmed evidence.",
                "claim_type": "inference",
                "support_claim_refs": [support_ref],
                "citation_keys": [citation_key],
                "figure_refs": [figure_ref] if section_id == "introduction" else [],
            }
        )
        write_yaml_if_changed(fill_path, fill)
        assert report.verify_paper_draft_section(root, program_id, section_id) == 0

    output_root = root / "kb" / "output" / program_id
    with pytest.raises(PaperDraftRuntimeError, match="七节"):
        report.export_paper_draft(root, program_id)
    assert not output_root.exists()

    outline_path.write_bytes(b"# changed outline\n")
    assert not [
        card
        for card in discover_pending_judgements(root)
        if card["subject"]["kind"] == "paper_draft_section"
    ]
    outline_path.write_bytes(outline_bytes)
    cards = [
        card
        for card in discover_pending_judgements(root)
        if card["subject"]["kind"] == "paper_draft_section"
    ]
    assert len(cards) == 7
    kb = _kb_module()
    display = kb._review_card_record(cards[0])
    assert kb.public_review_projection(display, root)["status"] == "ready"
    owner_module, owner_plan = kb._review_batch_owner_plan(
        root,
        cards[0],
        "confirm",
        actor="researcher",
        evidence=["The researcher reviewed this draft section."],
        user_authorization="I confirm this draft section.",
        authorization_source="user_message",
        rejection_reason="",
    )
    assert owner_module.__name__.startswith("kb_review_owner_report_author_")
    assert owner_plan["owner"] == "report-author"
    assert len(owner_plan["target_paths"]) == 1
    for card in cards:
        report.apply_review_batch_decision(
            root,
            card,
            "confirm",
            actor="researcher",
            evidence=["The researcher reviewed this draft section."],
            user_authorization="I confirm this draft section.",
            authorization_source="user_message",
            rejection_reason="",
        )

    for section_id in SECTION_IDENTITIES:
        path = paper_draft_section_path(root, program_id, section_id)
        record = load_yaml(path)
        assert record["confirmation_status"] == "confirmed"
        assert judgement_confirmation_is_current(root, record, path)

    assert report.export_paper_draft(root, program_id) == 0
    markdown = (output_root / "paper-draft.md").read_text(encoding="utf-8")
    latex = (output_root / "paper-draft.tex").read_text(encoding="utf-8")
    bibliography = (output_root / "references.bib").read_text(encoding="utf-8")
    publication = load_yaml(output_root / "publication-manifest.yaml")
    assert markdown.count("\n## ") == 7
    assert figure_ref in markdown
    assert latex.count(r"\section{") == 7
    assert bibliography.count("@misc{") == 5
    assert len(publication["sections"]) == 7
    assert [item["filename"] for item in publication["artifacts"]] == [
        "paper-draft.md",
        "paper-draft.tex",
        "references.bib",
    ]

    published_bytes = {
        path.name: path.read_bytes()
        for path in output_root.iterdir()
        if path.is_file()
    }
    figure_asset = next(
        (root / "kb" / "units" / "papers" / source_unit / "figures" / "assets").glob("*.png")
    )
    figure_asset.write_bytes(b"tampered")
    with pytest.raises(PaperDraftRuntimeError, match="figure index"):
        report.export_paper_draft(root, program_id)
    assert published_bytes == {
        path.name: path.read_bytes()
        for path in output_root.iterdir()
        if path.is_file()
    }

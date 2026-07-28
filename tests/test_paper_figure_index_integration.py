from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml
from research.confirm import write_record
from research.figures import FigureIndexError, load_current_figure_index
from research.index import search_passages
from research.obsidian import update_obsidian_projection
from research.prefs import ensure_workspace
from research.records import kind_payload_skeleton


def _paper_module():
    root = REPO_ROOT
    path = root / ".agents" / "skills" / "unit-analyst" / "scripts" / "paper.py"
    spec = importlib.util.spec_from_file_location("paper_figure_index_integration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pdf(path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page(width=500, height=700)
    page.draw_rect(fitz.Rect(90, 100, 230, 360), color=(0.1, 0.2, 0.8), fill=(0.8, 0.9, 1.0))
    page.insert_text((90, 410), "Figure 1. Stable pipeline overview", fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    document.close()


def test_extract_figures_publishes_stable_hash_index_without_downgrading_paper(
    tmp_path: Path,
) -> None:
    paper = _paper_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    paper_id = "p-figure-integration-abcdef"
    unit_root = root / "kb" / "units" / "papers" / paper_id
    source = unit_root / "source" / "paper.pdf"
    _pdf(source)
    record = {
        "id": paper_id,
        "kind": "paper",
        "title": "Figure Integration",
        "status": "active",
        "maturity": "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "topics": ["figures"],
        "tags": ["paper"],
        "source": {
            "original_uri": "",
            "backup_paths": [source.relative_to(root).as_posix()],
            "file_hash": "",
        },
        "payload": kind_payload_skeleton("paper", "Figure Integration"),
    }
    write_record(root, record)
    current, _path = paper.locate_record(root, paper_id, kind="paper")

    assert paper._run_extract_figures(
        root,
        current,
        unit_root,
        [],
        defer_post_actions=True,
        pdf_preferences={
            "figure_include_tables": True,
            "filter_blank_and_mask_images": False,
            "figure_render_scale": 2.0,
            "figure_crop_padding_pt": 8.0,
        },
    ) == 0

    first_record = load_yaml(unit_root / "record.yaml")
    first_index = load_yaml(unit_root / "figures.yaml")
    projection = first_record["payload"]["figures"]
    assert first_record["confirmation_status"] == "auto_confirmed"
    assert first_record["needs_human_confirmation"] is False
    assert first_record["information_types"] == ["fact"]
    assert projection["extraction_status"] == "indexed"
    assert projection["available_ref_keys"] == [f"fig:{paper_id}:fig:1"]
    assert projection["key_figure_refs"] == []
    assert projection["index_digest"] == first_index["index_digest"]
    asset = first_index["entries"][0]["assets"][0]
    assert re.fullmatch(r"figures/assets/[0-9a-f]{64}\.png", asset["path"])
    assert (unit_root / asset["path"]).is_file()

    current, _path = paper.locate_record(root, paper_id, kind="paper")
    paper._run_extract_figures(
        root,
        current,
        unit_root,
        [],
        defer_post_actions=True,
        pdf_preferences={
            "figure_include_tables": True,
            "filter_blank_and_mask_images": False,
            "figure_render_scale": 2.0,
            "figure_crop_padding_pt": 8.0,
        },
    )
    second_index = load_yaml(unit_root / "figures.yaml")
    assert second_index["index_digest"] == first_index["index_digest"]
    assert second_index["entries"][0]["ref_key"] == first_index["entries"][0]["ref_key"]
    assert second_index["entries"][0]["assets"] == first_index["entries"][0]["assets"]

    ref_key = first_index["entries"][0]["ref_key"]
    search = search_passages(root, "Stable pipeline overview")
    assert any(
        result["artifact"].endswith("/figures.yaml")
        and result["locator"].endswith(f"figures.yaml#{ref_key}")
        and "Stable pipeline overview" in result["excerpt"]
        for result in search["results"]
    )
    update_obsidian_projection(root)
    page_path = root / "kb" / "obsidian" / "managed" / "units" / f"{paper_id}.md"
    page = page_path.read_text(encoding="utf-8")
    assert ref_key in page
    assert "Figure 1. Stable pipeline overview" in page
    assert f"![[units/papers/{paper_id}/{asset['path']}]]" in page

    asset_path = unit_root / asset["path"]
    asset_path.write_bytes(b"tampered")
    with pytest.raises(FigureIndexError, match="figure asset bytes changed"):
        load_current_figure_index(
            unit_root / "figures.yaml",
            unit_root=unit_root,
            project_root=root,
            expected_index_digest=first_index["index_digest"],
        )

    stale_search = search_passages(root, "Stable pipeline overview")
    assert not any(result["artifact"].endswith("/figures.yaml") for result in stale_search["results"])
    update_obsidian_projection(root)
    stale_page = page_path.read_text(encoding="utf-8")
    assert ref_key not in stale_page
    assert "Figure 1. Stable pipeline overview" not in stale_page

"""Regression for post-note steps in `docs/DESIGN.md` "Prepare / fill / verify".

- Default prefs (auto_refresh_structure_after_note=True) + full autonomy scope
  → refresh-structure runs (structure.yaml written) and the parse-cache is NOT
  truncated (F-a invariant).
- Autonomy scope without "refresh" → refresh does NOT auto-run.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import RESEARCH_LIB_ROOT, SKILLS_ROOT, initialize_test_workspace

LIB = RESEARCH_LIB_ROOT
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import yaml  # noqa: E402

from research.core import write_record, write_runtime_preferences, load_runtime_preferences  # noqa: E402

SKILL = SKILLS_ROOT / "unit-analyst" / "scripts"


def _paper_module():
    spec = importlib.util.spec_from_file_location("paper_autopost", SKILL / "paper.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _make_unit(tmp: Path, pages: int) -> tuple[Path, str, list[dict], Path]:
    initialize_test_workspace(tmp)
    pid = "p-autopost-00000000"
    ud = tmp / "units" / "papers" / pid
    ud.mkdir(parents=True)
    chunks = [
        {"label": f"src.pdf:page-{i}", "text": f"Page {i} discusses method component {i} in detail.", "locator_kind": "page", "locator": f"page={i}"}
        for i in range(1, pages + 1)
    ]
    cache = ud / "parse-cache.yaml"
    cache.write_text(yaml.safe_dump({"paper_id": pid, "source_type": "pdf", "locator_kind": "page", "chunks": chunks}))
    write_record(tmp, {
        "id": pid, "kind": "paper", "status": "screened", "maturity": "complete",
        "confirmation_status": "pending_user_confirmation", "information_types": ["fact"],
        "payload": {"basic_info": {"title": "T"}, "core_content": {}, "structure": {}},
        "source": {"original_uri": "src.pdf"}, "history": [],
    })
    record = yaml.safe_load((ud / "record.yaml").read_text())
    return ud, pid, chunks, cache


def _set_scope(root: Path, scope: list[str]) -> None:
    prefs = load_runtime_preferences(root)
    prefs.setdefault("autonomy", {})["auto_execute_scope"] = scope
    write_runtime_preferences(root, prefs)


def test_auto_post_note_runs_refresh_and_preserves_cache(tmp_path):
    paper = _paper_module()
    ud, pid, chunks, cache = _make_unit(tmp_path, pages=25)
    _set_scope(tmp_path, ["screen", "build-index", "refresh", "generate-note"])
    record = yaml.safe_load((ud / "record.yaml").read_text())
    before = len(yaml.safe_load(cache.read_text())["chunks"])

    paper._auto_post_note_steps(
        tmp_path, record, ud, chunks, cache,
        paper_preferences={"auto_refresh_structure_after_note": True, "auto_extract_figures_after_note": False},
        defer_post_actions=False,
    )

    assert (ud / "structure.yaml").exists(), "refresh-structure did not auto-run"
    after = len(yaml.safe_load(cache.read_text())["chunks"])
    assert after == before == 25, f"parse-cache truncated by auto-refresh: {before} -> {after}"
    assert not (ud / "figures.yaml").exists(), "figures should not auto-run when pref is off"


def test_auto_post_note_respects_autonomy_scope(tmp_path):
    paper = _paper_module()
    ud, pid, chunks, cache = _make_unit(tmp_path, pages=25)
    _set_scope(tmp_path, ["screen", "build-index"])  # no "refresh"
    record = yaml.safe_load((ud / "record.yaml").read_text())

    paper._auto_post_note_steps(
        tmp_path, record, ud, chunks, cache,
        paper_preferences={"auto_refresh_structure_after_note": True, "auto_extract_figures_after_note": False},
        defer_post_actions=False,
    )

    assert not (ud / "structure.yaml").exists(), "refresh auto-ran despite being outside auto_execute_scope"

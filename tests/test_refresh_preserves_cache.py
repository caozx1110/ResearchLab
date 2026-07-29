"""F-a regression: refresh-structure must NOT overwrite/truncate the parse-cache.

The full intake parse-cache is immutable derived evidence. refresh-structure
re-derives structure.yaml from the EXISTING cache; it must never re-parse the
source with the truncation prefs (front/back limits), which would delete later
pages and break evidence idempotency.
"""
from __future__ import annotations

import sys
from pathlib import Path

from repo_paths import RESEARCH_LIB_ROOT, SKILLS_ROOT

LIB = RESEARCH_LIB_ROOT
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import yaml  # noqa: E402

SKILL = SKILLS_ROOT / "unit-analyst" / "scripts"


def _load(mod_path: Path, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _make_unit(tmp: Path, pages: int) -> tuple[Path, str]:
    pid = "p-fa-test-00000000"
    ud = tmp / "kb" / "units" / "papers" / pid
    ud.mkdir(parents=True)
    chunks = [
        {"label": f"src.pdf:page-{i}", "text": f"page {i} body text sentence.", "locator_kind": "page", "locator": f"page={i}"}
        for i in range(1, pages + 1)
    ]
    (ud / "parse-cache.yaml").write_text(yaml.safe_dump({"paper_id": pid, "source_type": "pdf", "locator_kind": "page", "chunks": chunks}))
    (ud / "record.yaml").write_text(yaml.safe_dump({
        "id": pid, "kind": "paper", "status": "screened", "maturity": "complete",
        "confirmation_status": "pending_user_confirmation", "information_types": ["fact"],
        "payload": {"basic_info": {"title": "T"}, "core_content": {}},
        "source": {"original_uri": "src.pdf"}, "history": [],
    }))
    return ud, pid


def test_refresh_structure_preserves_full_parse_cache(tmp_path, monkeypatch):
    """refresh-structure keeps all cache pages and still writes structure.yaml."""
    paper = _load(SKILL / "paper.py", "paper_fa")
    ud, pid = _make_unit(tmp_path, pages=30)
    cache = ud / "parse-cache.yaml"
    before = len(yaml.safe_load(cache.read_text())["chunks"])
    assert before == 30

    monkeypatch.setattr(sys, "argv", [
        "paper.py", "--root", str(tmp_path), "refresh-structure", "--paper-id", pid, "--defer-post-actions",
    ])
    try:
        paper.main()
    except SystemExit as exc:  # main() may return via SystemExit(0)
        assert not exc.code

    after = len(yaml.safe_load(cache.read_text())["chunks"])
    assert after == before, f"refresh-structure truncated the cache: {before} -> {after}"
    assert (ud / "structure.yaml").exists(), "refresh-structure did not produce structure.yaml"

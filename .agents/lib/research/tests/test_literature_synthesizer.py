from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / ".agents" / "skills" / "literature-synthesizer" / "scripts" / "synthesize.py"


def load_synthesizer():
    spec = importlib.util.spec_from_file_location("literature_synthesizer_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_filled_survey(tmp_path: Path):
    module = load_synthesizer()
    records = [
        {"id": "p-alpha", "kind": "paper", "title": "Alpha Method"},
        {"id": "r-beta", "kind": "repo", "title": "Beta System"},
    ]
    scaffold = module.build_survey_scaffold(
        records,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-17T00:00:00Z",
    )
    quote = "Alpha uses a hierarchical controller for long-horizon tasks."
    for record in records:
        unit_dir = module.unit_root(tmp_path, record["kind"], record["id"])
        unit_dir.mkdir(parents=True)
        (unit_dir / "note.md").write_text(f"# Evidence\n\n{quote}\n", encoding="utf-8")
    _, entries = module.survey_claim_entries(scaffold)
    for _, cell, _ in entries:
        cell["content"] = f"Agent-authored content for {cell['id']}."
        cell["evidence_refs"] = [
            {
                "source_unit_id": "p-alpha",
                "artifact": "note.md",
                "locator": "section=evidence",
                "quote": quote,
            }
        ]
    scaffold["comparison_matrix"]["dimensions"][0]["label"] = "Control hierarchy"
    scaffold["comparison_matrix"]["methods"][0]["label"] = "Alpha Method"
    scaffold["comparison_matrix"]["methods"][0]["source_unit_ids"] = ["p-alpha"]
    return module, scaffold


def test_prepare_emits_seven_section_evidence_first_scaffold() -> None:
    module = load_synthesizer()
    scaffold = module.build_survey_scaffold(
        [{"id": "p-alpha", "kind": "paper", "title": "Alpha"}],
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-17T00:00:00Z",
    )

    assert [section["id"] for section in scaffold["sections"]] == [
        "scope_positioning",
        "background_terms",
        "taxonomy",
        "cross_cutting",
        "trends",
        "gaps_challenges",
        "conclusion",
    ]
    assert scaffold["kb_anchor"]["unit_ids"] == ["p-alpha"]
    assert scaffold["comparison_matrix"]["cells"]
    _, entries = module.survey_claim_entries(scaffold)
    assert entries
    assert all(cell["content"] == "" and cell["evidence_refs"] == [] for _, cell, _ in entries)
    serialized = yaml.safe_dump(scaffold, allow_unicode=True)
    assert "confidence: 0.68" not in serialized
    assert "当前结果仍偏索引级综合" not in serialized


def test_verify_accepts_verbatim_cross_unit_evidence(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)

    violations, verified = module.verify_survey_fill(scaffold, tmp_path)

    assert violations == []
    assert verified["status"] == "verified"
    _, entries = module.survey_claim_entries(verified)
    statuses = {cell["epistemic_status"] for _, cell, _ in entries}
    assert statuses == {"observed", "inferred"}
    summary = module.render_verified_summary(verified)
    assert "## Comparison Matrix" in summary
    assert "| Alpha Method |" in summary


def test_verify_rejects_fabricated_quote(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    scaffold["sections"][0]["claims"][0]["evidence_refs"][0]["quote"] = "Fabricated result at 99 percent."

    violations, verified = module.verify_survey_fill(scaffold, tmp_path)

    assert verified["status"] == "awaiting_agent_fill"
    assert any("not verbatim" in violation for violation in violations)


def test_verify_cli_persists_only_verified_survey(tmp_path: Path, monkeypatch) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    fill_path = tmp_path / "agent-filled.yaml"
    fill_path.write_text(yaml.safe_dump(scaffold, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--root", str(tmp_path), "survey", "verify", "--input", str(fill_path)],
    )

    assert module.main() == 0

    survey_path = tmp_path / "kb" / "synthesis" / "robot-learning" / "survey.yaml"
    summary_path = tmp_path / "kb" / "synthesis" / "robot-learning" / "summary.md"
    assert survey_path.exists()
    assert summary_path.exists()
    persisted = yaml.safe_load(survey_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "verified"
    assert "## Comparison Matrix" in summary_path.read_text(encoding="utf-8")

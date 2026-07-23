from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
    quotes = {
        "p-alpha": "Alpha uses a hierarchical controller for long-horizon tasks.",
        "r-beta": "Beta reports benchmark metrics for recovery tasks.",
    }
    for record in records:
        unit_dir = module.unit_root(tmp_path, record["kind"], record["id"])
        unit_dir.mkdir(parents=True)
        (unit_dir / "record.yaml").write_text(
            yaml.safe_dump({**record, "summary": "robot learning", "payload": {}}, allow_unicode=True),
            encoding="utf-8",
        )
        (unit_dir / "note.md").write_text(f"# Evidence\n\n{quotes[record['id']]}\n", encoding="utf-8")
    scaffold = module.build_survey_scaffold(
        records,
        root=tmp_path,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-17T00:00:00Z",
    )
    _, entries = module.survey_claim_entries(scaffold)
    for _, cell, _ in entries:
        cell["content"] = f"Agent-authored content for {cell['id']}."
        cell["evidence_refs"] = [
            {
                "source_unit_id": "p-alpha",
                "artifact": "note.md",
                "locator": "section=evidence",
                "quote": quotes["p-alpha"],
            }
        ]
    taxonomy = next(section for section in scaffold["sections"] if section["id"] == "taxonomy")
    taxonomy["cells"][0]["row_label"] = "Alpha Method"
    taxonomy["cells"][0]["column_label"] = "Hierarchical control"
    taxonomy["cells"][0]["evidence_refs"].append(
        {
            "source_unit_id": "r-beta",
            "artifact": "note.md",
            "locator": "section=evidence",
            "quote": quotes["r-beta"],
        }
    )
    trends = next(section for section in scaffold["sections"] if section["id"] == "trends")
    trends["items"][0]["trajectory"] = "flat control -> hierarchical control -> recovery-aware control"
    gaps = next(section for section in scaffold["sections"] if section["id"] == "gaps_challenges")
    gaps["items"][0]["gap_type"] = "benchmark coverage"
    scaffold["comparison_matrix"]["dimensions"][0]["label"] = "Control hierarchy"
    scaffold["comparison_matrix"]["methods"][0]["label"] = "Alpha Method"
    scaffold["comparison_matrix"]["methods"][0]["source_unit_ids"] = ["p-alpha"]
    return module, scaffold


def test_prepare_emits_seven_section_evidence_first_scaffold(tmp_path: Path) -> None:
    module = load_synthesizer()
    unit_dir = module.unit_root(tmp_path, "paper", "p-alpha")
    unit_dir.mkdir(parents=True)
    (unit_dir / "record.yaml").write_text(
        yaml.safe_dump({"id": "p-alpha", "kind": "paper", "title": "Alpha", "payload": {}}),
        encoding="utf-8",
    )
    (unit_dir / "note.md").write_text("# Alpha\n\nGrounded evidence.\n", encoding="utf-8")
    scaffold = module.build_survey_scaffold(
        [{"id": "p-alpha", "kind": "paper", "title": "Alpha"}],
        root=tmp_path,
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
    binding = scaffold["kb_anchor"]["units"][0]
    assert len(binding["record_content_digest"]) == 64
    assert binding["evidence_artifacts"] == [
        {"artifact": "note.md", "byte_sha256": module.file_sha256(unit_dir / "note.md")}
    ]
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
    assert verified["status"] == "pending_user_confirmation"
    assert verified["evidence_verification_status"] == "verified"
    assert verified["governance_status"] == "needs_agent_repair"
    _, entries = module.survey_claim_entries(verified)
    statuses = {cell["epistemic_status"] for _, cell, _ in entries}
    assert statuses == {"verified_pending_confirmation"}
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
    assert persisted["status"] == "pending_user_confirmation"
    assert persisted["evidence_verification_status"] == "verified"
    assert persisted["consumer_binding"]["selection_filters"]["query"] == "robot learning"
    assert "Pending / Unverified judgement" in (survey_path.parent / "summary.md").read_text(encoding="utf-8")
    assert "## Comparison Matrix" in summary_path.read_text(encoding="utf-8")


def test_verify_rejects_changed_bound_record_or_evidence(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    paper_dir = module.unit_root(tmp_path, "paper", "p-alpha")
    (paper_dir / "note.md").write_text("# Evidence\n\nChanged bytes.\n", encoding="utf-8")

    violations, _ = module.verify_survey_fill(scaffold, tmp_path)

    assert any("canonical unit content, confirmation, or evidence changed" in item for item in violations)


def test_survey_staleness_detects_changed_deleted_and_new_matching_units(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    violations, verified = module.verify_survey_fill(scaffold, tmp_path)
    assert violations == []
    assert module.survey_staleness(verified, tmp_path) == {
        "stale": False,
        "reasons": [],
        "new_unit_ids": [],
    }

    paper_dir = module.unit_root(tmp_path, "paper", "p-alpha")
    (paper_dir / "note.md").write_text("# Evidence\n\nChanged bytes.\n", encoding="utf-8")
    repo_dir = module.unit_root(tmp_path, "repo", "r-beta")
    (repo_dir / "record.yaml").unlink()
    new_dir = module.unit_root(tmp_path, "paper", "p-gamma")
    new_dir.mkdir(parents=True)
    (new_dir / "record.yaml").write_text(
        yaml.safe_dump(
            {"id": "p-gamma", "kind": "paper", "title": "Gamma", "summary": "robot learning", "payload": {}}
        ),
        encoding="utf-8",
    )

    stale = module.survey_staleness(verified, tmp_path)

    assert stale["stale"] is True
    assert stale["new_unit_ids"] == ["p-gamma"]
    assert "changed unit: p-alpha" in stale["reasons"]
    assert "deleted or unreadable unit: r-beta" in stale["reasons"]
    assert "new matching unit: p-gamma" in stale["reasons"]

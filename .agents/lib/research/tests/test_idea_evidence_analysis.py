from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path


def _load_idea_module():
    root = Path(__file__).resolve().parents[4]
    script = root / ".agents" / "skills" / "idea-workbench" / "scripts" / "idea.py"
    spec = importlib.util.spec_from_file_location("idea_workbench_script_for_analysis", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _setup(tmp_path: Path, idea) -> tuple[str, str]:
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    idea_record = default_record("idea", title="Evidence Idea", maturity="lightweight", source={"original_uri": "discussion"})
    idea_record["id"] = "i-evidence-123456"
    idea_record["payload"]["problem"]["problem_definition"] = "Improve transfer."
    idea_record["payload"]["hypothesis"]["core_hypothesis"] = "A structured bottleneck improves transfer."
    write_yaml_if_changed(record_path(tmp_path, "idea", idea_record["id"]), idea_record)

    repo_record = default_record("repo", title="Prior System", maturity="complete", source={"original_uri": "fixture"})
    repo_record["id"] = "r-prior-123456"
    repo_path = record_path(tmp_path, "repo", repo_record["id"])
    write_yaml_if_changed(repo_path, repo_record)
    (repo_path.parent / "evidence.txt").write_text(
        "The baseline loses accuracy under unseen camera viewpoints.\n",
        encoding="utf-8",
    )
    idea.PROJECT_ROOT = tmp_path
    idea.checkpoint_and_report = lambda *args, **kwargs: {}
    return idea_record["id"], repo_record["id"]


def _run(idea, monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["idea.py", *argv])
    return idea.main()


def _fill(path: Path, source_id: str, quote: str, *, selection_rank: int | None = None) -> dict:
    payload = load_yaml(path, default={})
    payload["reviewer"] = "runtime-agent"
    if selection_rank is not None:
        payload["selection_rank"] = selection_rank
    texts = {
        "novelty": "The idea differs by testing a structured bottleneck under viewpoint shift.",
        "feasibility": "A focused viewpoint-shift evaluation is feasible in the cited repo.",
        "recommendation": "Promising only if the bottleneck beats the cited baseline failure.",
        "killer-question": "Does the gain survive unseen camera viewpoints?",
    }
    for claim in payload["claims"]:
        claim["text"] = texts[claim["role"]]
        claim["evidence_refs"] = [
            {
                "source_unit_id": source_id,
                "artifact": "evidence.txt",
                "locator": "section:fixture",
                "quote": quote,
                "summary": "Grounds the comparison and test target.",
            }
        ]
    return payload


def test_analyze_prepare_is_fillable_and_has_no_verdict(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, _ = _setup(tmp_path, idea)

    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0

    fill = load_yaml(record_path(tmp_path, "idea", idea_id).parent / "analyze-fill.yaml", default={})
    assert all(claim["text"] == "" and claim["evidence_refs"] == [] for claim in fill["claims"])
    assert "score_breakdown" not in fill
    assert fill["descriptive_counts"]["note"].endswith("not scores or verdicts.")


def test_review_verify_persists_agent_judgements_without_heuristic_score(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "review-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints.", selection_rank=1),
    )

    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "verify") == 0

    updated = load_yaml(record_path(tmp_path, "idea", idea_id), default={})
    assert updated["payload"]["analysis"]["novelty"].startswith("The idea differs")
    assert updated["payload"]["review"]["recommendation"].startswith("Promising only")
    assert updated["payload"]["review"]["selection_rank"] == 1
    assert updated["payload"]["review"]["score_breakdown"] == {}
    assert len(updated["payload"]["review"]["claims"]) == 4


def test_analyze_verify_rejects_fabricated_evidence(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "Fabricated evidence."))

    with pytest.raises(SystemExit) as exc:
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")

    assert exc.value.code == 1
    updated = load_yaml(record_path(tmp_path, "idea", idea_id), default={})
    assert updated["payload"]["analysis"]["novelty"] == ""

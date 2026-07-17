from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_idea_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "idea-workbench" / "scripts" / "idea.py"
    spec = importlib.util.spec_from_file_location("idea_workbench_script_for_discussion", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _setup_records(tmp_path: Path, idea) -> tuple[str, str]:
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)

    idea_record = default_record("idea", title="Sparring Idea", maturity="lightweight", source={"original_uri": "discussion"})
    idea_record["id"] = "i-sparring-123456"
    idea_record["payload"]["problem"]["problem_definition"] = "Can this mechanism generalize?"
    idea_record["payload"]["hypothesis"]["core_hypothesis"] = "The mechanism improves transfer."
    write_yaml_if_changed(record_path(tmp_path, "idea", idea_record["id"]), idea_record)

    paper_record = default_record("paper", title="Counter Example", maturity="complete", source={"original_uri": "fixture"})
    paper_record["id"] = "p-counter-123456"
    paper_path = record_path(tmp_path, "paper", paper_record["id"])
    write_yaml_if_changed(paper_path, paper_record)
    write_yaml_if_changed(
        paper_path.parent / "parse-cache.yaml",
        {"chunks": [{"label": "paper:page-2", "text": "Transfer failed when the visual domain changed abruptly."}]},
    )

    idea.PROJECT_ROOT = tmp_path
    idea.checkpoint_and_report = lambda *args, **kwargs: {}
    return idea_record["id"], paper_record["id"]


def _run(idea, monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["idea.py", *argv])
    return idea.main()


def _filled_scaffold(path: Path, source_id: str, quote: str) -> dict:
    fill = load_yaml(path, default={})
    fill["reviewer"] = "runtime-agent"
    fill["conclusion"] = "The hypothesis needs a domain-shift boundary and a targeted ablation."
    for claim in fill["claims"]:
        claim["text"] = f"Filled {claim['role']} claim."
        claim["evidence_refs"] = [
            {
                "source_unit_id": source_id,
                "artifact": "parse-cache.yaml",
                "locator": "page=2",
                "quote": quote,
                "summary": "Relevant counter-evidence.",
            }
        ]
    return fill


def test_discuss_prepare_emits_empty_agent_fill_scaffold(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, _ = _setup_records(tmp_path, idea)

    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "prepare") == 0

    scaffold = load_yaml(record_path(tmp_path, "idea", idea_id).parent / "discussion-fill.yaml", default={})
    assert scaffold["conclusion"] == ""
    assert scaffold["reviewer"] == ""
    assert {claim["role"] for claim in scaffold["claims"]} == {
        "challenge",
        "probe",
        "counter-example",
        "constructive-suggestion",
    }
    assert all(claim["text"] == "" and claim["evidence_refs"] == [] for claim in scaffold["claims"])


def test_discuss_verify_accepts_verbatim_evidence_and_persists_one_conclusion(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup_records(tmp_path, idea)
    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "discussion-fill.yaml"
    fill = _filled_scaffold(fill_path, source_id, "Transfer failed when the visual domain changed abruptly.")
    write_yaml_if_changed(fill_path, fill)

    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "verify") == 0

    updated = load_yaml(record_path(tmp_path, "idea", idea_id), default={})
    conclusions = updated["payload"]["discussion"]["conclusions"]
    assert len(conclusions) == 1
    assert conclusions[0]["reviewer"] == "runtime-agent"
    assert conclusions[0]["verification"] == "evidence_verified"
    assert conclusions[0]["claims"][2]["evidence_refs"][0]["source_unit_id"] == source_id


def test_discuss_verify_rejects_fabricated_counter_example(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup_records(tmp_path, idea)
    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "discussion-fill.yaml"
    fill = _filled_scaffold(fill_path, source_id, "This fabricated result is absent from the source.")
    write_yaml_if_changed(fill_path, fill)

    with pytest.raises(SystemExit) as exc:
        _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "verify")

    assert exc.value.code == 1
    updated = load_yaml(record_path(tmp_path, "idea", idea_id), default={})
    assert updated["payload"].get("discussion", {}).get("conclusions", []) == []

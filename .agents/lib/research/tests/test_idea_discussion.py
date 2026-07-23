from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path
from research.judgements import judgement_snapshot_binding


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
        claim["text"] = fill["conclusion"] if claim["role"] == "conclusion" else f"Filled {claim['role']} claim."
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
        "conclusion",
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
    assert conclusions[0]["judgement_id"].startswith("discussion-")
    sidecar = load_yaml(record_path(tmp_path, "idea", idea_id).parent / "discussion-judgements.yaml")
    judgement = sidecar["items"][0]
    assert judgement["payload"]["claims"][-1]["text"] == fill["conclusion"]
    assert judgement["payload"]["verification"]["verified_at"]
    assert judgement["confirmation_status"] == "pending_user_confirmation"
    expected = judgement_snapshot_binding(
        judgement,
        owner="idea-workbench",
        path=(record_path(tmp_path, "idea", idea_id).parent / "discussion-judgements.yaml").relative_to(tmp_path).as_posix(),
    )

    assert _run(
        idea,
        monkeypatch,
        "discuss",
        "--id",
        idea_id,
        "--phase",
        "confirm",
        "--conclusion-id",
        judgement["id"],
        "--confirmed-by",
        "Human Reviewer",
        "--evidence",
        "discussion evidence reviewed",
        "--user-authorization",
        "I confirm this discussion conclusion.",
        "--authorization-source",
        "user_message",
        "--expected-snapshot",
        json.dumps(expected),
    ) == 0
    confirmed = load_yaml(record_path(tmp_path, "idea", idea_id).parent / "discussion-judgements.yaml")["items"][0]
    assert confirmed["confirmation_status"] == "confirmed"
    assert confirmed["confirmation"]["subject"] == {
        "kind": "idea_discussion_conclusion",
        "id": judgement["id"],
    }
    with pytest.raises(SystemExit, match="not ready for this decision"):
        _run(
            idea,
            monkeypatch,
            "discuss",
            "--id",
            idea_id,
            "--phase",
            "confirm",
            "--conclusion-id",
            judgement["id"],
            "--confirmed-by",
            "Human Reviewer",
            "--evidence",
            "discussion evidence reviewed",
            "--user-authorization",
            "I confirm this discussion conclusion.",
            "--authorization-source",
            "user_message",
            "--expected-snapshot",
            json.dumps(expected),
        )
    with pytest.raises(SystemExit, match="not ready for this decision"):
        _run(
            idea,
            monkeypatch,
            "discuss",
            "--id",
            idea_id,
            "--phase",
            "reject",
            "--conclusion-id",
            judgement["id"],
            "--expected-snapshot",
            json.dumps(expected),
        )


def test_discuss_reject_closes_verified_side_judgement_without_human_signature(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup_records(tmp_path, idea)
    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "prepare") == 0
    unit_root = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit_root / "discussion-fill.yaml"
    fill = _filled_scaffold(fill_path, source_id, "Transfer failed when the visual domain changed abruptly.")
    write_yaml_if_changed(fill_path, fill)
    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "verify") == 0
    judgement_id = load_yaml(unit_root / "discussion-judgements.yaml")["items"][0]["id"]
    expected = judgement_snapshot_binding(
        load_yaml(unit_root / "discussion-judgements.yaml")["items"][0],
        owner="idea-workbench",
        path=(unit_root / "discussion-judgements.yaml").relative_to(tmp_path).as_posix(),
    )

    assert _run(
        idea,
        monkeypatch,
        "discuss",
        "--id",
        idea_id,
        "--phase",
        "reject",
        "--conclusion-id",
        judgement_id,
        "--reason",
        "The boundary is too broad.",
        "--expected-snapshot",
        json.dumps(expected),
    ) == 0

    rejected = load_yaml(unit_root / "discussion-judgements.yaml")["items"][0]
    record = load_yaml(record_path(tmp_path, "idea", idea_id))
    projection = record["payload"]["discussion"]["conclusions"][0]
    assert rejected["confirmation_status"] == "rejected"
    assert rejected["needs_human_confirmation"] is True
    assert rejected["rejection"]["reason"] == "The boundary is too broad."
    assert {claim["confirmation_status"] for claim in rejected["payload"]["claims"]} == {"rejected"}
    assert projection["confirmation_status"] == "rejected"


def test_discussion_old_review_snapshot_cannot_confirm_changed_conclusion(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup_records(tmp_path, idea)
    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "prepare") == 0
    unit_root = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit_root / "discussion-fill.yaml"
    fill = _filled_scaffold(fill_path, source_id, "Transfer failed when the visual domain changed abruptly.")
    write_yaml_if_changed(fill_path, fill)
    assert _run(idea, monkeypatch, "discuss", "--id", idea_id, "--phase", "verify") == 0
    sidecar_path = unit_root / "discussion-judgements.yaml"
    sidecar = load_yaml(sidecar_path)
    judgement = sidecar["items"][0]
    expected = judgement_snapshot_binding(
        judgement,
        owner="idea-workbench",
        path=sidecar_path.relative_to(tmp_path).as_posix(),
    )
    judgement["payload"]["discussion_conclusion"]["text"] = "Changed after the user saw the review card."
    write_yaml_if_changed(sidecar_path, sidecar)

    with pytest.raises(SystemExit, match="review snapshot is stale"):
        _run(
            idea,
            monkeypatch,
            "discuss",
            "--id",
            idea_id,
            "--phase",
            "confirm",
            "--conclusion-id",
            judgement["id"],
            "--confirmed-by",
            "Human Reviewer",
            "--evidence",
            "discussion evidence reviewed",
            "--user-authorization",
            "I confirm the old displayed conclusion.",
            "--authorization-source",
            "user_message",
            "--expected-snapshot",
            json.dumps(expected),
        )
    assert "confirmation" not in load_yaml(sidecar_path)["items"][0]


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

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.judgements import discover_pending_judgements, judgement_confirmation_is_current
from research.surveys import (
    COMPOSITE_SURVEY_STAGES,
    composite_survey_state_violations,
    new_composite_survey_state,
    select_current_confirmed_survey_records,
    survey_lifecycle_violations,
    update_composite_survey_stage,
)


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / ".agents" / "skills" / "literature-synthesizer" / "scripts" / "synthesize.py"
QUOTE = "Alpha uses a hierarchical controller for long-horizon tasks."


def load_synthesizer():
    spec = importlib.util.spec_from_file_location("survey_lifecycle_synthesizer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_confirmed_source(module, root: Path, *, unit_id: str = "p-alpha", confirmed: bool = True) -> dict:
    unit_dir = module.unit_root(root, "paper", unit_id)
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "note.md").write_text(f"# Evidence\n\n{QUOTE}\n", encoding="utf-8")
    record = {
        "id": unit_id,
        "kind": "paper",
        "title": "Alpha Method",
        "summary": "robot learning",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "payload": {},
    }
    if confirmed:
        apply_confirmation(
            record,
            confirmed_by="Alice Researcher",
            evidence=["Reviewed source unit"],
            project_root=root,
        )
    write_yaml_if_changed(unit_dir / "record.yaml", record)
    return record


def build_verified_survey(root: Path):
    module = load_synthesizer()
    source = write_confirmed_source(module, root)
    scaffold = module.build_survey_scaffold(
        [source],
        root=root,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-24T00:00:00Z",
    )
    _, entries = module.survey_claim_entries(scaffold)
    for _, cell, _ in entries:
        cell["content"] = f"Agent-authored judgement for {cell['id']}."
        cell["evidence_refs"] = [
            {
                "source_unit_id": "p-alpha",
                "artifact": "note.md",
                "locator": "section=evidence",
                "quote": QUOTE,
            }
        ]
    taxonomy = next(section for section in scaffold["sections"] if section["id"] == "taxonomy")
    taxonomy["cells"][0]["row_label"] = "Alpha Method"
    taxonomy["cells"][0]["column_label"] = "Hierarchical control"
    trends = next(section for section in scaffold["sections"] if section["id"] == "trends")
    trends["items"][0]["trajectory"] = "flat -> hierarchical"
    gaps = next(section for section in scaffold["sections"] if section["id"] == "gaps_challenges")
    gaps["items"][0]["gap_type"] = "benchmark coverage"
    scaffold["comparison_matrix"]["dimensions"][0]["label"] = "Control hierarchy"
    scaffold["comparison_matrix"]["methods"][0]["label"] = "Alpha Method"
    scaffold["comparison_matrix"]["methods"][0]["source_unit_ids"] = ["p-alpha"]
    violations, verified = module.verify_survey_fill(scaffold, root)
    assert violations == []
    survey_path = root / "kb/synthesis/robot-learning/survey.yaml"
    survey_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(survey_path, verified)
    (survey_path.parent / "summary.md").write_text(module.render_verified_summary(verified), encoding="utf-8")
    return module, survey_path, verified


def test_prepare_zero_current_inputs_returns_structured_gap_without_scaffold(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_synthesizer()
    write_confirmed_source(module, tmp_path, confirmed=False)

    eligible, excluded = select_current_confirmed_survey_records(
        tmp_path,
        list(module.iter_records(tmp_path)),
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
    )
    assert eligible == []
    assert excluded[0]["reasons"] == ["unit is not confirmed"]

    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--root", str(tmp_path), "survey", "prepare", "--query", "robot learning", "--as-of", "2026-07-24"],
    )
    assert module.main() == 2
    output = capsys.readouterr().out.strip().splitlines()
    handoff = json.loads(output[-1])
    assert handoff["status"] == "evidence_gap"
    assert handoff["composite_handoff"]["ordered_stages"] == list(COMPOSITE_SURVEY_STAGES)
    assert not (tmp_path / "kb/synthesis/robot-learning/survey-fill.yaml").exists()


def test_verified_survey_is_discovered_and_batch_confirmed_with_receipt(tmp_path: Path) -> None:
    module, survey_path, verified = build_verified_survey(tmp_path)

    cards = discover_pending_judgements(tmp_path)
    assert [card["subject"] for card in cards] == [
        {
            "kind": "survey_judgement",
            "id": "survey:survey:robot-learning",
            "owner": "literature-synthesizer",
            "path": "kb/synthesis/robot-learning/survey.yaml",
        }
    ]
    card = cards[0]
    assert card["substance"]["sections"]
    assert card["confirm_route"]["action"] == "confirm"
    assert card["reject_route"]["action"] == "reject"

    plan = module.prepare_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed all displayed survey claims"],
        user_authorization="I confirm the displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    assert plan["target_paths"] == [survey_path, survey_path.parent / "summary.md"]
    module.apply_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed all displayed survey claims"],
        user_authorization="I confirm the displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    confirmed = load_yaml(survey_path)
    assert confirmed["confirmation_status"] == "confirmed"
    assert confirmed["confirmation"]["authorization_source"] == "user_message"
    assert confirmed["confirmation"]["claim_ids"]
    assert judgement_confirmation_is_current(tmp_path, confirmed, survey_path)
    assert discover_pending_judgements(tmp_path) == []
    assert "Confirmed judgement" in (survey_path.parent / "summary.md").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="no longer pending"):
        module.apply_review_batch_decision(
            tmp_path,
            card,
            "confirm",
            actor="Alice Researcher",
            evidence=["Reviewed all displayed survey claims"],
            user_authorization="I confirm the displayed survey.",
            authorization_source="user_message",
            rejection_reason="",
        )


def test_reject_is_terminal_without_fabricating_confirmation(tmp_path: Path) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]

    module.apply_review_batch_decision(
        tmp_path,
        card,
        "reject",
        actor="Alice Researcher",
        evidence=[],
        user_authorization="",
        authorization_source="",
        rejection_reason="Taxonomy needs revision.",
    )
    rejected = load_yaml(survey_path)
    assert rejected["confirmation_status"] == "rejected"
    assert "confirmation" not in rejected
    assert rejected["rejection"]["reason"] == "Taxonomy needs revision."
    assert discover_pending_judgements(tmp_path) == []


@pytest.mark.parametrize(
    ("actor", "evidence", "authorization", "source", "message"),
    [
        ("Codex Agent", ["reviewed"], "I confirm it.", "user_message", "Self-signing"),
        ("Alice Researcher", [], "I confirm it.", "user_message", "at least one --evidence"),
        ("Alice Researcher", ["reviewed"], "", "user_message", "user_authorization"),
        ("Alice Researcher", ["reviewed"], "I confirm it.", "", "authorization_source"),
    ],
)
def test_confirm_requires_human_current_message_provenance(
    tmp_path: Path,
    actor: str,
    evidence: list[str],
    authorization: str,
    source: str,
    message: str,
) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    before = survey_path.read_bytes()

    with pytest.raises(SystemExit, match=message):
        module.prepare_review_batch_decision(
            tmp_path,
            card,
            "confirm",
            actor=actor,
            evidence=evidence,
            user_authorization=authorization,
            authorization_source=source,
            rejection_reason="",
        )
    assert survey_path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["content", "claim", "upstream_evidence", "upstream_confirmation"])
def test_confirmed_survey_stales_on_every_bound_change(tmp_path: Path, mutation: str) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    module.apply_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed survey"],
        user_authorization="I confirm it.",
        authorization_source="user_message",
        rejection_reason="",
    )
    record = load_yaml(survey_path)
    if mutation == "content":
        record["sections"][0]["claims"][0]["content"] += " Changed."
        write_yaml_if_changed(survey_path, record)
    elif mutation == "claim":
        record["payload"]["claims"][0]["text"] += " Changed."
        write_yaml_if_changed(survey_path, record)
    elif mutation == "upstream_evidence":
        (tmp_path / "kb/units/papers/p-alpha/note.md").write_text("changed evidence bytes", encoding="utf-8")
    else:
        source_path = tmp_path / "kb/units/papers/p-alpha/record.yaml"
        source = load_yaml(source_path)
        source["confirmation"]["evidence"].append("changed receipt bytes")
        write_yaml_if_changed(source_path, source)
    current = load_yaml(survey_path)
    assert not judgement_confirmation_is_current(tmp_path, current, survey_path)


def test_snapshot_cas_fails_before_any_write(tmp_path: Path) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    before = survey_path.read_bytes()
    tampered = copy.deepcopy(card)
    tampered["snapshot_binding"]["content_digest"] = "0" * 64

    with pytest.raises(ValueError, match="stale"):
        module.prepare_review_batch_decision(
            tmp_path,
            tampered,
            "confirm",
            actor="Alice Researcher",
            evidence=["Reviewed survey"],
            user_authorization="I confirm it.",
            authorization_source="user_message",
            rejection_reason="",
        )
    assert survey_path.read_bytes() == before


def test_legacy_needs_agent_repair_is_readable_but_not_reviewable(tmp_path: Path) -> None:
    legacy_path = tmp_path / "kb/synthesis/legacy/survey.yaml"
    legacy_path.parent.mkdir(parents=True)
    legacy = {
        "mode": "survey",
        "slug": "legacy",
        "status": "pending_user_confirmation",
        "confirmation_status": "pending_user_confirmation",
        "governance_status": "needs_agent_repair",
        "sections": [],
    }
    write_yaml_if_changed(legacy_path, legacy)

    assert load_yaml(legacy_path)["governance_status"] == "needs_agent_repair"
    assert survey_lifecycle_violations(legacy, tmp_path) == [
        "legacy survey requires agent repair and re-verification"
    ]
    assert discover_pending_judgements(tmp_path) == []


def test_composite_survey_state_is_ordered_and_resumable() -> None:
    state = new_composite_survey_state(
        composite_id="survey-run-1",
        request_digest=hashlib.sha256(b"find papers then survey").hexdigest(),
        mode="discovery",
        filters={"query": "robot learning"},
    )
    assert composite_survey_state_violations(state) == []
    state = update_composite_survey_stage(
        state,
        "search",
        status="completed",
        outputs=[{"kind": "candidate_stage", "id": "search-1"}],
    )
    assert state["current_stage"] == "selection"
    state = update_composite_survey_stage(
        state,
        "selection",
        status="blocked",
        inputs=[{"kind": "candidate_stage", "id": "search-1"}],
        blocker={"code": "awaiting_current_user_selection"},
        resume_action="record_current_user_selection",
    )
    assert state["status"] == "blocked"
    assert composite_survey_state_violations(state) == []

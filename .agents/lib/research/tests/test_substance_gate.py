"""Confirmation gate: substance-check + two-track classification (SSOT §3.11 / Principle 3).

Covers the Wave-2 Track-Gate work that plugs the hollow confirmation gate:
  * substance-check on promote-to-confirmed (judgement track) — the core acceptance;
  * has_substantive_content emptiness caliber aligned with the G5 harness;
  * two-track classification (fact metadata vs judgement);
  * the four governance red lines: self-sign rejected / judgement-no-evidence rejected /
    substance rejected / fact-track light-confirm passes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.evidence import build_verification_receipt
from research.core import (
    apply_confirmation,
    confirmation_track,
    confirm_unit,
    ensure_workspace,
    has_substantive_content,
    promote_record,
    record_path,
    require_confirmation_provenance,
    write_record,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_g5_harness():
    """Load the read-only G5 research-value harness by path (not on pytest pythonpath)."""
    script = _project_root() / ".agents" / "skills" / "skill-evolution-advisor" / "scripts" / "eval_research_value.py"
    spec = importlib.util.spec_from_file_location("eval_research_value_for_substance_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Realistic judgement-track information_types (what real pending papers carry).
JUDGEMENT_INFO_TYPES = ["evaluation", "fact", "inference", "unverified", "user_opinion"]

FILLED_CORE_CONTENT = {
    "research_problem": "How to ground VLA action prediction in physical dynamics.",
    "method": "flow-matching policy over action chunks",
    "mechanism": "predicts short action horizons conditioned on vision+language",
}


def _paper_record(
    unit_id: str = "p-substance-123456",
    *,
    information_types: list[str] | None = None,
    core_content: dict | None = None,
    confirmation_status: str = "pending_user_confirmation",
    status: str = "screened",
) -> dict:
    payload: dict = {}
    if core_content is not None:
        payload = {"core_content": dict(core_content)}
    return {
        "id": unit_id,
        "kind": "paper",
        "title": "Substance Gate Paper",
        "status": status,
        "maturity": "lightweight",
        "confirmation_status": confirmation_status,
        "needs_human_confirmation": confirmation_status == "pending_user_confirmation",
        "information_types": list(information_types or ["fact"]),
        "source": {"original_uri": "", "file_hash": ""},
        "payload": payload,
    }


def _with_verified_judgement(
    project_root: Path,
    record: dict,
    *,
    claim_type: str = "evaluation",
) -> dict:
    evidence_root = record_path(project_root, "paper", record["id"]).parent
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "parse-cache.yaml").write_text("grounded analysis evidence", encoding="utf-8")
    record.setdefault("payload", {})["claims"] = [
        {
            "id": "claim-substance",
            "text": "The filled analysis is substantive.",
            "claim_type": claim_type,
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": record["id"],
                    "artifact": "parse-cache.yaml",
                    "locator": "section=analysis",
                    "quote": "grounded analysis evidence",
                }
            ],
        }
    ]
    build_verification_receipt(record, evidence_root)
    return record


# --------------------------------------------------------------------------- #
# Core acceptance: the hollow gate is plugged.
# --------------------------------------------------------------------------- #
def test_promote_empty_judgement_paper_to_confirmed_is_rejected_and_stays_pending(tmp_path: Path) -> None:
    """CORE ACCEPTANCE: an empty-core_content judgement paper cannot be promoted to
    confirmed even with valid provenance; it stays pending on disk (no write)."""
    ensure_workspace(tmp_path)
    unit_id = "p-hollow-judgement-123456"
    write_yaml_if_changed(
        record_path(tmp_path, "paper", unit_id),
        _paper_record(unit_id, information_types=JUDGEMENT_INFO_TYPES, core_content={}),
    )

    with pytest.raises(SystemExit, match="hollow"):
        promote_record(
            tmp_path,
            unit_id,
            confirmation_status="confirmed",
            confirmed_by="czx",
            evidence=["kb/programs/p/decision-log.md"],
        )

    # Rejection happens before any write: the record is untouched on disk.
    on_disk = load_yaml(record_path(tmp_path, "paper", unit_id), default={})
    assert on_disk["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in on_disk


def test_promote_substantive_judgement_paper_confirms_normally(tmp_path: Path) -> None:
    """A judgement paper with real core_content confirms normally through promote."""
    ensure_workspace(tmp_path)
    unit_id = "p-substantive-judgement-123456"
    write_yaml_if_changed(
        record_path(tmp_path, "paper", unit_id),
        _with_verified_judgement(
            tmp_path,
            _paper_record(unit_id, information_types=JUDGEMENT_INFO_TYPES, core_content=FILLED_CORE_CONTENT),
        ),
    )

    path = promote_record(
        tmp_path,
        unit_id,
        confirmation_status="confirmed",
        confirmed_by="czx",
        evidence=["kb/programs/p/decision-log.md"],
        user_authorization="I confirm this paper analysis.",
        authorization_source="user_message",
    )

    record = load_yaml(path, default={})
    assert record["confirmation_status"] == "confirmed"
    assert record["needs_human_confirmation"] is False
    assert record["confirmation"]["by"] == "czx"
    assert record["confirmation"]["evidence"] == ["kb/programs/p/decision-log.md"]


def test_promote_empty_fact_metadata_paper_to_confirmed_is_exempt(tmp_path: Path) -> None:
    """Fact-track basic metadata is exempt from the deep substance check (light confirm):
    an empty fact-track paper can still be promoted to confirmed with provenance."""
    ensure_workspace(tmp_path)
    unit_id = "p-fact-metadata-123456"
    write_yaml_if_changed(
        record_path(tmp_path, "paper", unit_id),
        _paper_record(unit_id, information_types=["fact"], core_content={}),
    )

    path = promote_record(
        tmp_path,
        unit_id,
        confirmation_status="confirmed",
        confirmed_by="czx",
        evidence=["kb/programs/p/decision-log.md"],
    )

    assert load_yaml(path, default={})["confirmation_status"] == "confirmed"


# --------------------------------------------------------------------------- #
# has_substantive_content emptiness caliber (aligned with the G5 harness).
# --------------------------------------------------------------------------- #
def test_has_substantive_content_matches_g5_paper_caliber() -> None:
    """has_substantive_content(paper) must be exactly `not paper_core_content_empty` in
    the G5 harness — both treat all-empty core_content as hollow (unified H1 caliber)."""
    g5 = _load_g5_harness()
    cases = [
        {},
        {"research_problem": ""},
        {"innovations": []},
        {"method": "   "},  # whitespace-only counts as empty in both
        {"method": "diffusion policy"},
        {"innovations": ["chunked action head"]},
        dict(FILLED_CORE_CONTENT),
    ]
    for core_content in cases:
        record = _paper_record(core_content=core_content)
        assert has_substantive_content(record, "paper") == (not g5.paper_core_content_empty(record)), core_content


def test_has_substantive_content_non_paper_kinds() -> None:
    """Non-paper kinds use their core analysis section(s); empty = hollow, filled = ok."""
    empty_by_kind = {
        "repo": {"capability": {}},
        "blog": {"content": {}},
        "idea": {"problem": {}, "hypothesis": {}},
        "experiment": {"results": {}, "diagnosis": {}},
    }
    for kind, payload in empty_by_kind.items():
        assert has_substantive_content({"kind": kind, "payload": payload}, kind) is False, kind

    filled_by_kind = {
        "repo": {"capability": {"boundary": "trains VLA policies"}},
        "blog": {"content": {"key_points": ["explains flow matching"]}},
        "idea": {"problem": {"problem_definition": "no physical grounding"}, "hypothesis": {}},
        "experiment": {"results": {"metrics": {"success": 0.8}}, "diagnosis": {}},
    }
    for kind, payload in filled_by_kind.items():
        assert has_substantive_content({"kind": kind, "payload": payload}, kind) is True, kind


def test_has_substantive_content_unknown_kind_is_not_blocked() -> None:
    """Unknown kinds are not judged (returns True) — the gate only tightens known kinds."""
    assert has_substantive_content({"kind": "mystery", "payload": {}}, "mystery") is True


# --------------------------------------------------------------------------- #
# Two-track classification (SSOT §3.11 decision ①).
# --------------------------------------------------------------------------- #
def test_confirmation_track_fact_metadata_is_fact() -> None:
    record = _paper_record(information_types=["fact"])
    assert confirmation_track(record) == "fact"


def test_confirmation_track_inference_or_evaluation_is_judgement() -> None:
    assert confirmation_track(_paper_record(information_types=["fact", "inference"])) == "judgement"
    assert confirmation_track(_paper_record(information_types=["evaluation"])) == "judgement"
    assert confirmation_track(_paper_record(information_types=JUDGEMENT_INFO_TYPES)) == "judgement"


def test_confirmation_track_ai_source_is_judgement() -> None:
    record = {"kind": "paper", "information_types": ["fact"], "source": {"kind": "ai"}}
    assert confirmation_track(record) == "judgement"


def test_canonical_user_opinion_claim_sets_non_downgradable_judgement_floor(tmp_path: Path) -> None:
    record = _with_verified_judgement(
        tmp_path,
        _paper_record(information_types=["fact"], core_content=FILLED_CORE_CONTENT),
        claim_type="user_opinion",
    )

    assert confirmation_track(record) == "judgement"


# --------------------------------------------------------------------------- #
# Governance red lines (regression).
# --------------------------------------------------------------------------- #
def test_red_line_self_sign_rejected() -> None:
    """An AI identity cannot confirm — even with evidence present."""
    for actor in ("ai", "assistant", "codex", "openai"):
        with pytest.raises(SystemExit, match="Self-signing is forbidden"):
            require_confirmation_provenance(confirmed_by=actor, evidence=["kb/x/note.md"])


def test_red_line_self_sign_rejected_end_to_end(tmp_path: Path) -> None:
    """Self-sign is blocked through apply_confirmation too (no confirmation stamped)."""
    record = _paper_record(information_types=JUDGEMENT_INFO_TYPES, core_content=FILLED_CORE_CONTENT)
    with pytest.raises(SystemExit, match="Self-signing is forbidden"):
        apply_confirmation(record, confirmed_by="codex", evidence=["kb/x/note.md"])
    assert record["confirmation_status"] == "pending_user_confirmation"


def test_red_line_judgement_confirm_without_evidence_rejected(tmp_path: Path) -> None:
    """Existing rule preserved: judgement confirmation still requires evidence, even
    when the record HAS substantive content (so substance is not the blocker here)."""
    ensure_workspace(tmp_path)
    unit_id = "p-no-evidence-123456"
    write_yaml_if_changed(
        record_path(tmp_path, "paper", unit_id),
        _paper_record(unit_id, information_types=JUDGEMENT_INFO_TYPES, core_content=FILLED_CORE_CONTENT),
    )

    with pytest.raises(SystemExit, match="--evidence"):
        promote_record(tmp_path, unit_id, confirmation_status="confirmed", confirmed_by="czx")

    assert load_yaml(record_path(tmp_path, "paper", unit_id), default={})["confirmation_status"] == "pending_user_confirmation"


def test_red_line_substance_rejected_independent_of_evidence(tmp_path: Path) -> None:
    """Substance is an added, independent gate: valid confirmer + evidence still cannot
    confirm a hollow judgement record."""
    ensure_workspace(tmp_path)
    unit_id = "p-substance-blocked-123456"
    write_yaml_if_changed(
        record_path(tmp_path, "paper", unit_id),
        _paper_record(unit_id, information_types=JUDGEMENT_INFO_TYPES, core_content={}),
    )

    with pytest.raises(SystemExit, match="core content is empty"):
        promote_record(
            tmp_path,
            unit_id,
            confirmation_status="confirmed",
            confirmed_by="czx",
            evidence=["kb/programs/p/decision-log.md"],
        )


def test_red_line_fact_track_light_confirm_passes(tmp_path: Path) -> None:
    """Fact-track basic metadata light-confirms successfully via the batch path (kb.py
    review-queue --confirm / apply_batch_confirmation → confirm_unit)."""
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    unit_id = "p-fact-light-123456"
    write_record(
        tmp_path,
        _paper_record(unit_id, information_types=["fact"], core_content={}, status="draft"),
    )

    [path] = kb.apply_batch_confirmation(
        tmp_path,
        [load_yaml(record_path(tmp_path, "paper", unit_id), default={})],
        confirmed_by="czx",
        evidence=["kb/programs/p/decision-log.md"],
        method="test fact light confirm",
    )

    assert load_yaml(path, default={})["confirmation_status"] == "confirmed"


# --------------------------------------------------------------------------- #
# confirm_unit — the PRIMARY user confirm path (paper.py confirm / kb.py confirm /
# interactive kb review). The substance gate must fire here too, evaluated on the
# original record BEFORE information_types is collapsed to ['fact'].
# --------------------------------------------------------------------------- #
def test_confirm_unit_rejects_hollow_judgement_paper_before_mutation() -> None:
    """confirm_unit rejects a hollow judgement paper and leaves the record untouched
    (not confirmed, information_types preserved)."""
    record = _paper_record(information_types=JUDGEMENT_INFO_TYPES, core_content={})
    with pytest.raises(SystemExit, match="hollow"):
        confirm_unit(record, "paper", confirmed_by="czx", evidence=["kb/x/note.md"])
    assert record["confirmation_status"] == "pending_user_confirmation"
    # gate ran on the ORIGINAL state and confirmation never changed epistemic type
    assert "inference" in record["information_types"]
    assert "confirmation" not in record


def test_confirm_unit_hollow_judgement_via_batch_stays_pending_on_disk(tmp_path: Path) -> None:
    """kb.py batch path (apply_batch_confirmation -> confirm_unit): a hollow judgement
    paper is rejected and stays pending_user_confirmation on disk (no confirmation)."""
    kb = _load_kb_module()
    ensure_workspace(tmp_path)
    unit_id = "p-hollow-confirm-unit-123456"
    write_yaml_if_changed(
        record_path(tmp_path, "paper", unit_id),
        _paper_record(unit_id, information_types=JUDGEMENT_INFO_TYPES, core_content={}),
    )

    with pytest.raises(SystemExit, match="hollow"):
        kb.apply_batch_confirmation(
            tmp_path,
            [load_yaml(record_path(tmp_path, "paper", unit_id), default={})],
            confirmed_by="czx",
            evidence=["kb/programs/p/decision-log.md"],
            method="test hollow via confirm_unit",
        )

    on_disk = load_yaml(record_path(tmp_path, "paper", unit_id), default={})
    assert on_disk["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in on_disk


def test_confirm_unit_confirms_substantive_judgement_paper_and_preserves_types(tmp_path: Path) -> None:
    """A substantive judgement paper confirms without erasing epistemic type."""
    record = _with_verified_judgement(
        tmp_path,
        _paper_record(information_types=JUDGEMENT_INFO_TYPES, core_content=FILLED_CORE_CONTENT),
    )
    out = confirm_unit(
        record,
        "paper",
        confirmed_by="czx",
        evidence=["kb/x/note.md"],
        user_authorization="I confirm this paper analysis.",
        authorization_source="user_message",
        project_root=tmp_path,
    )
    assert out["confirmation_status"] == "confirmed"
    assert out["information_types"] == JUDGEMENT_INFO_TYPES
    assert out["confirmation"]["by"] == "czx"
    assert out["confirmation"]["prior_information_types"] == JUDGEMENT_INFO_TYPES
    assert out["history"][-1]["information_types"] == JUDGEMENT_INFO_TYPES


def test_confirm_unit_confirms_fact_metadata_record() -> None:
    """Fact-track metadata is exempt from the deep substance check (light confirm)."""
    record = _paper_record(information_types=["fact"], core_content={})
    out = confirm_unit(record, "paper", confirmed_by="czx", evidence=["kb/x/note.md"])
    assert out["confirmation_status"] == "confirmed"


def test_confirm_unit_cannot_bypass_user_opinion_claim_with_record_fact(tmp_path: Path) -> None:
    record = _with_verified_judgement(
        tmp_path,
        _paper_record(information_types=["fact"], core_content=FILLED_CORE_CONTENT),
        claim_type="user_opinion",
    )

    with pytest.raises(SystemExit, match="user_authorization"):
        confirm_unit(
            record,
            "paper",
            confirmed_by="czx",
            evidence=["kb/x/note.md"],
            project_root=tmp_path,
        )

    assert record["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in record


def test_apply_confirmation_cannot_bypass_user_opinion_claim_with_record_fact(tmp_path: Path) -> None:
    record = _with_verified_judgement(
        tmp_path,
        _paper_record(information_types=["fact"], core_content=FILLED_CORE_CONTENT),
        claim_type="user_opinion",
    )

    with pytest.raises(SystemExit, match="user_authorization"):
        apply_confirmation(
            record,
            confirmed_by="czx",
            evidence=["kb/x/note.md"],
            project_root=tmp_path,
        )

    assert record["confirmation_status"] == "pending_user_confirmation"


def test_promote_cannot_bypass_user_opinion_claim_with_record_fact(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    unit_id = "p-user-opinion-floor-123456"
    record = _with_verified_judgement(
        tmp_path,
        _paper_record(
            unit_id,
            information_types=["fact"],
            core_content=FILLED_CORE_CONTENT,
        ),
        claim_type="user_opinion",
    )
    write_yaml_if_changed(record_path(tmp_path, "paper", unit_id), record)

    with pytest.raises(SystemExit, match="user_authorization"):
        promote_record(
            tmp_path,
            unit_id,
            confirmation_status="confirmed",
            confirmed_by="czx",
            evidence=["kb/x/note.md"],
        )

    on_disk = load_yaml(record_path(tmp_path, "paper", unit_id), default={})
    assert on_disk["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in on_disk


def test_apply_confirmation_rejects_unverified_claim_even_on_fact_record() -> None:
    record = _paper_record(information_types=["fact"], core_content=FILLED_CORE_CONTENT)
    record.setdefault("payload", {})["claims"] = [
        {
            "id": "claim-unverified",
            "text": "This claim still needs verification.",
            "claim_type": "unverified",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [],
        }
    ]

    with pytest.raises(SystemExit, match="unverified claims"):
        apply_confirmation(record, confirmed_by="czx", evidence=["kb/x/note.md"])

    assert record["confirmation_status"] == "pending_user_confirmation"


def test_promote_rejects_unverified_claim_and_preserves_disk_state(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    unit_id = "p-unverified-floor-123456"
    record = _paper_record(unit_id, information_types=["fact"], core_content=FILLED_CORE_CONTENT)
    record.setdefault("payload", {})["claims"] = [
        {
            "id": "claim-unverified",
            "text": "This claim still needs verification.",
            "claim_type": "unverified",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [],
        }
    ]
    write_yaml_if_changed(record_path(tmp_path, "paper", unit_id), record)

    with pytest.raises(SystemExit, match="unverified claims"):
        promote_record(
            tmp_path,
            unit_id,
            confirmation_status="confirmed",
            confirmed_by="czx",
            evidence=["kb/x/note.md"],
        )

    on_disk = load_yaml(record_path(tmp_path, "paper", unit_id), default={})
    assert on_disk["confirmation_status"] == "pending_user_confirmation"
    assert "confirmation" not in on_disk


# --------------------------------------------------------------------------- #
# review-queue two-track display (kb.py) — grouping + fact-track batch scoping.
# --------------------------------------------------------------------------- #
def _load_kb_module():
    script = _project_root() / ".agents" / "skills" / "knowledge-base-manager" / "scripts" / "kb.py"
    spec = importlib.util.spec_from_file_location("kb_script_for_substance_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_partition_review_tracks_splits_fact_and_judgement() -> None:
    kb = _load_kb_module()
    fact = _paper_record("p-fact-000001", information_types=["fact"])
    judgement = _paper_record("p-judge-000002", information_types=JUDGEMENT_INFO_TYPES)

    fact_track, judgement_track = kb.partition_review_tracks([fact, judgement])

    assert [r["id"] for r in fact_track] == ["p-fact-000001"]
    assert [r["id"] for r in judgement_track] == ["p-judge-000002"]


def test_review_queue_confirm_only_touches_fact_track(tmp_path: Path, monkeypatch, capsys) -> None:
    """review-queue --confirm batch-confirms only fact-track metadata; a judgement
    item is skipped (and left pending) with a notice."""
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(tmp_path, "paper", "p-fact-000001"),
        _paper_record("p-fact-000001", information_types=["fact"], core_content={}, status="draft"),
    )
    write_yaml_if_changed(
        record_path(tmp_path, "paper", "p-judge-000002"),
        _paper_record("p-judge-000002", information_types=JUDGEMENT_INFO_TYPES, core_content={}),
    )
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(kb, "checkpoint_and_report", lambda *a, **k: {})
    monkeypatch.setattr(
        sys,
        "argv",
        ["kb.py", "review-queue", "--confirm", "--confirmed-by", "czx", "--evidence", "kb/programs/p/decision-log.md"],
    )

    assert kb.main() == 0

    out = capsys.readouterr().out
    assert "judgement-track item(s) need per-item" in out
    assert load_yaml(record_path(tmp_path, "paper", "p-fact-000001"), default={})["confirmation_status"] == "confirmed"
    assert load_yaml(record_path(tmp_path, "paper", "p-judge-000002"), default={})["confirmation_status"] == "pending_user_confirmation"


def test_review_queue_display_groups_two_tracks(tmp_path: Path, monkeypatch, capsys) -> None:
    kb = _load_kb_module()
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(tmp_path, "paper", "p-fact-000001"),
        _paper_record("p-fact-000001", information_types=["fact"], core_content={}, status="draft"),
    )
    write_yaml_if_changed(
        record_path(tmp_path, "paper", "p-judge-000002"),
        _paper_record("p-judge-000002", information_types=JUDGEMENT_INFO_TYPES, core_content={}),
    )
    monkeypatch.setattr(kb, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["kb.py", "review-queue"])

    assert kb.main() == 0

    out = capsys.readouterr().out
    assert "fact-track metadata" in out
    assert "judgement-track" in out
    assert "hollow" in out  # the empty judgement paper is flagged
    assert "建议主动请用户拍板" in out

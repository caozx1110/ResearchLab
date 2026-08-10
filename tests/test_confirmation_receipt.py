from __future__ import annotations

from research.evidence import (
    build_verification_receipt,
    confirmation_claim_ids,
    confirmation_content_digest,
    confirmation_evidence_digest,
    verification_receipt_violations,
)
from research.paper_notes import PAPER_DEEP_READ_SCHEMA, PAPER_NOTE_CLAIM_SCHEMA
from research.confirm import apply_confirmation
from research.paths import unit_root
from research.records import normalize_record_schema
from repo_paths import initialize_test_workspace


def _record() -> dict:
    return {
        "id": "p-receipt-123456",
        "kind": "paper",
        "payload": {
            "core_content": {
                "research_problem": "  Bind   confirmation\n to content. ",
                "innovations": ["receipt", "invalidation"],
            },
            "claims": [
                {
                    "id": "claim-002",
                    "text": "Second claim",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "p-receipt-123456",
                            "artifact": "parse-cache.yaml",
                            "locator": "page=2",
                            "quote": " exact\n quote ",
                            "summary": "ignored by evidence receipt",
                        }
                    ],
                },
                {
                    "id": "claim-001",
                    "text": "First claim",
                    "claim_type": "fact",
                    "confirmation_status": "auto_confirmed",
                    "evidence_refs": [],
                },
            ],
        },
    }


def _write_verified_artifact(project_root) -> None:
    initialize_test_workspace(project_root)
    root = unit_root(project_root, "paper", "p-receipt-123456")
    root.mkdir(parents=True, exist_ok=True)
    (root / "parse-cache.yaml").write_text("source text with exact quote included", encoding="utf-8")


def _verified_record(project_root) -> dict:
    record = _record()
    _write_verified_artifact(project_root)
    build_verification_receipt(record, unit_root(project_root, "paper", record["id"]))
    return record


def _confirm(record: dict, project_root, **kwargs):
    return apply_confirmation(
        record,
        confirmed_by="czx",
        evidence=["kb/x.md"],
        user_authorization="I confirm this analysis.",
        authorization_source="user_message",
        project_root=project_root,
        **kwargs,
    )


def test_confirmation_content_digest_is_canonical_and_content_sensitive() -> None:
    record = _record()
    reordered = _record()
    reordered["payload"]["core_content"] = {
        "innovations": ["receipt", "invalidation"],
        "research_problem": "Bind confirmation to   content.",
    }
    reordered["payload"]["claims"].reverse()

    assert confirmation_content_digest(record) == confirmation_content_digest(reordered)

    reordered["payload"]["core_content"]["innovations"].append("versioning")
    assert confirmation_content_digest(record) != confirmation_content_digest(reordered)


def test_confirmation_digest_helpers_bind_claims_and_evidence_set() -> None:
    record = _record()
    assert confirmation_claim_ids(record) == ["claim-001", "claim-002"]
    assert confirmation_evidence_digest(record, [" kb/x.md ", "kb/y.md"]) == confirmation_evidence_digest(
        record, ["kb/y.md", "kb/x.md", "kb/x.md"]
    )

    changed = _record()
    changed["payload"]["claims"][0]["evidence_refs"][0]["locator"] = "page=3"
    assert confirmation_content_digest(record) != confirmation_content_digest(changed)
    assert confirmation_evidence_digest(record, ["kb/x.md"]) != confirmation_evidence_digest(
        changed, ["kb/x.md"]
    )


def test_v2_paper_receipts_bind_sections_and_critique_without_changing_v1_digest(
    tmp_path,
) -> None:
    legacy = _record()
    legacy_with_workflow_metadata = _record()
    legacy_with_workflow_metadata["payload"]["deep_read"] = {
        "paper_type": "method_system"
    }
    legacy_with_workflow_metadata["payload"]["critique"] = {
        "weak_spots": ["Legacy v1 critique was outside the old digest contract."]
    }
    assert confirmation_content_digest(legacy) == confirmation_content_digest(
        legacy_with_workflow_metadata
    )

    record = _record()
    record["payload"]["deep_read"] = {
        "schema": PAPER_DEEP_READ_SCHEMA,
        "paper_type": "method_system",
        "sections": [
            {
                "section_id": "research_problem",
                "status": "assessed",
                "summary": "Bind every current v2 section.",
                "not_applicable_reason": "",
                "claim_ids": ["claim-002"],
            }
        ],
    }
    record["payload"]["critique"] = {"reliability_risks": ["One current risk."]}
    record["payload"]["claims"][0].update(
        {
            "paper_note_schema": PAPER_NOTE_CLAIM_SCHEMA,
            "paper_section_id": "research_problem",
            "paper_section_status": "assessed",
            "paper_local_claim_id": "primary",
        }
    )
    _write_verified_artifact(tmp_path)
    receipt = build_verification_receipt(
        record,
        unit_root(tmp_path, "paper", record["id"]),
    )
    assert len(receipt["content_digest"]) == 64
    assert verification_receipt_violations(
        record,
        unit_root(tmp_path, "paper", record["id"]),
    ) == []

    record["payload"]["deep_read"]["sections"][0]["summary"] = "Changed after verify."
    violations = verification_receipt_violations(record, None, check_artifacts=False)
    assert any("content_digest does not match current analysis" in item for item in violations)


def test_apply_confirmation_stamps_full_version_bound_receipt(tmp_path, monkeypatch) -> None:
    import research.confirm as confirm

    record = _verified_record(tmp_path)
    record["information_types"] = ["inference", "evaluation"]
    monkeypatch.setattr(confirm, "utc_now_iso", lambda: "2026-07-16T00:00:00+00:00")

    out = _confirm(record, tmp_path, method="test")

    assert out["confirmation_status"] == "confirmed"
    assert out["confirmation"] == {
        "by": "czx",
        "at": "2026-07-16T00:00:00+00:00",
        "evidence": ["kb/x.md"],
        "method": "test",
        "decision": "confirmed",
        "subject": {"kind": "paper", "id": "p-receipt-123456"},
        "claim_ids": ["claim-001", "claim-002"],
        "content_digest": confirmation_content_digest(record),
        "evidence_digest": confirmation_evidence_digest(record, ["kb/x.md"]),
        "prior_information_types": ["inference", "evaluation"],
        "verified_at": record["payload"]["verification"]["verified_at"],
        "user_authorization": "I confirm this analysis.",
        "authorization_source": "user_message",
    }


def test_normalize_invalidates_receipt_after_confirmable_content_change(tmp_path) -> None:
    record = _verified_record(tmp_path)
    record["information_types"] = ["inference"]
    confirmed = _confirm(record, tmp_path)
    assert normalize_record_schema(confirmed)["confirmation_status"] == "confirmed"

    confirmed["payload"]["core_content"]["method"] = "mutated after confirmation"
    normalized = normalize_record_schema(confirmed)

    assert normalized["confirmation_status"] == "pending_user_confirmation"
    assert normalized["needs_human_confirmation"] is True
    assert normalized["confirmation"]["invalidation"] == {
        "reason": "confirmable_content_changed",
        "stored_content_digest": confirmed["confirmation"]["content_digest"],
        "current_content_digest": confirmation_content_digest(normalized),
    }


def test_normalize_invalidates_receipt_after_claim_evidence_change(tmp_path) -> None:
    confirmed = _confirm(_verified_record(tmp_path), tmp_path)
    confirmed["payload"]["claims"][0]["evidence_refs"][0]["quote"] = "different quote"

    normalized = normalize_record_schema(confirmed)

    assert normalized["confirmation_status"] == "pending_user_confirmation"
    assert normalized["confirmation"]["invalidation"]["reason"] == "confirmable_content_changed"


def test_apply_confirmation_rejects_fabricated_claim_quote(tmp_path) -> None:
    record = _verified_record(tmp_path)
    record["payload"]["claims"][0]["evidence_refs"][0]["quote"] = "fabricated quote"

    import pytest

    with pytest.raises(SystemExit, match="not verbatim"):
        _confirm(record, tmp_path)

    assert record.get("confirmation_status") != "confirmed"
    assert "confirmation" not in record


def test_normalize_leaves_legacy_confirmation_without_digest_unchanged() -> None:
    legacy = _record()
    legacy["confirmation_status"] = "confirmed"
    legacy["needs_human_confirmation"] = False
    legacy["confirmation"] = {
        "by": "czx",
        "at": "2026-07-01T00:00:00+00:00",
        "evidence": ["kb/x.md"],
        "method": "legacy",
    }

    normalized = normalize_record_schema(legacy)

    assert normalized["confirmation_status"] == "confirmed"
    assert "invalidation" not in normalized["confirmation"]

from __future__ import annotations

from research.evidence import (
    confirmation_claim_ids,
    confirmation_content_digest,
    confirmation_evidence_digest,
)
from research.confirm import apply_confirmation
from research.paths import unit_root
from research.records import normalize_record_schema


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
    root = unit_root(project_root, "paper", "p-receipt-123456")
    root.mkdir(parents=True, exist_ok=True)
    (root / "parse-cache.yaml").write_text("source text with exact quote included", encoding="utf-8")


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


def test_apply_confirmation_stamps_full_version_bound_receipt(tmp_path, monkeypatch) -> None:
    import research.confirm as confirm

    record = _record()
    record["information_types"] = ["inference", "evaluation"]
    _write_verified_artifact(tmp_path)
    monkeypatch.setattr(confirm, "utc_now_iso", lambda: "2026-07-16T00:00:00+00:00")

    out = apply_confirmation(
        record,
        confirmed_by="czx",
        evidence=["kb/x.md"],
        method="test",
        project_root=tmp_path,
    )

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
    }


def test_normalize_invalidates_receipt_after_confirmable_content_change(tmp_path) -> None:
    record = _record()
    record["information_types"] = ["inference"]
    _write_verified_artifact(tmp_path)
    confirmed = apply_confirmation(record, confirmed_by="czx", evidence=["kb/x.md"], project_root=tmp_path)
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
    _write_verified_artifact(tmp_path)
    confirmed = apply_confirmation(_record(), confirmed_by="czx", evidence=["kb/x.md"], project_root=tmp_path)
    confirmed["payload"]["claims"][0]["evidence_refs"][0]["quote"] = "different quote"

    normalized = normalize_record_schema(confirmed)

    assert normalized["confirmation_status"] == "pending_user_confirmation"
    assert normalized["confirmation"]["invalidation"]["reason"] == "confirmable_content_changed"


def test_apply_confirmation_rejects_fabricated_claim_quote(tmp_path) -> None:
    _write_verified_artifact(tmp_path)
    record = _record()
    record["payload"]["claims"][0]["evidence_refs"][0]["quote"] = "fabricated quote"

    import pytest

    with pytest.raises(SystemExit, match="not verbatim"):
        apply_confirmation(record, confirmed_by="czx", evidence=["kb/x.md"], project_root=tmp_path)

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

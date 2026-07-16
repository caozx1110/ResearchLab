from __future__ import annotations

from research.evidence import (
    confirmation_claim_ids,
    confirmation_content_digest,
    confirmation_evidence_digest,
)


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

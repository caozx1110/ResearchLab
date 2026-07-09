from __future__ import annotations

from pathlib import Path

import yaml

from research.evidence import EVIDENCE_SCHEMA, verify_claim_evidence
import research.core as core


def test_verify_claim_evidence_is_noop_stub(tmp_path: Path) -> None:
    """Wave 2 landing pad: the stub performs no verification and returns []."""
    claim = {
        "id": "claim-001",
        "text": "example",
        "claim_type": "inference",
        "evidence_refs": [
            {"source_unit_id": "p-x-123456", "artifact": "parse-cache.yaml", "locator": "page=3", "quote": "absent"}
        ],
    }
    assert verify_claim_evidence(claim, tmp_path) == []
    # A missing quote is NOT reported yet — proves the stub is a behavioral no-op.
    assert verify_claim_evidence({"evidence_refs": []}, str(tmp_path)) == []


def test_evidence_schema_is_valid_yaml_with_locked_fields() -> None:
    parsed = yaml.safe_load(EVIDENCE_SCHEMA)
    claim = parsed["claim"]
    assert set(claim) >= {"id", "text", "claim_type", "confidence", "confirmation_status", "evidence_refs"}
    ref = claim["evidence_refs"][0]
    assert set(ref) == {"source_unit_id", "artifact", "locator", "quote", "summary"}


def test_evidence_symbols_reexported_through_core_facade() -> None:
    assert core.verify_claim_evidence is verify_claim_evidence
    assert core.EVIDENCE_SCHEMA == EVIDENCE_SCHEMA


def test_schemas_md_has_evidence_claims_section_matching_ssot_block() -> None:
    project_root = Path(__file__).resolve().parents[4]
    text = (project_root / ".agents/lib/research/SCHEMAS.md").read_text(encoding="utf-8")
    assert "## Evidence / Claims" in text
    assert '<a id="evidence-claims"></a>' in text
    # The locked YAML block from SSOT Part 2 Principle 2 appears verbatim.
    assert EVIDENCE_SCHEMA.strip() in text

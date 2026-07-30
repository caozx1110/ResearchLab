from __future__ import annotations

from pathlib import Path

from repo_paths import REPO_ROOT

import yaml

from research.evidence import EVIDENCE_SCHEMA, verify_claim_evidence
import research.core as core


def test_verify_claim_evidence_reports_missing_quote(tmp_path: Path) -> None:
    """Wave 2 (implemented): a quote absent from the artifact is a violation."""
    (tmp_path / "parse-cache.yaml").write_text(
        "chunks:\n- label: 'x:page-3'\n  text: 'the real text on page three'\n",
        encoding="utf-8",
    )
    claim = {
        "id": "claim-001",
        "text": "example",
        "claim_type": "inference",
        "evidence_refs": [
            {"source_unit_id": "p-x-123456", "artifact": "parse-cache.yaml", "locator": "page=3", "quote": "absent"}
        ],
    }
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "claim-001" in violations[0] and "not verbatim" in violations[0]
    # No evidence_refs => nothing to verify => [] (degenerate input never raises).
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
    project_root = REPO_ROOT
    text = (project_root / "runtime/lib/research/SCHEMAS.md").read_text(encoding="utf-8")
    assert "## Evidence / Claims" in text
    assert '<a id="evidence-claims"></a>' in text
    # The block from runtime/lib/research/SCHEMAS.md#evidence-claims is verbatim.
    assert EVIDENCE_SCHEMA.strip() in text

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills" / "research-review"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = SKILL_ROOT / "scripts" / "review.py"
SPEC = importlib.util.spec_from_file_location("research_review_v2_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review
SPEC.loader.exec_module(review)


def test_skill_is_concise_and_exposes_both_contracts_one_hop() -> None:
    entry = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    expected = {
        "references/evidence-audit-and-packets.md",
        "references/authorization-decisions-and-receipts.md",
    }
    assert len(entry.splitlines()) < 100
    assert "protocol-reference-exempt:" in entry
    assert "scripts/" not in entry
    for relative in expected:
        assert f"]({relative})" in entry
        reference = SKILL_ROOT / relative
        assert reference.is_file()
        assert len(reference.read_text(encoding="utf-8").splitlines()) < 200

    combined = entry + "\n" + "\n".join(
        (SKILL_ROOT / relative).read_text(encoding="utf-8") for relative in sorted(expected)
    )
    for phrase in (
        "current_user_message",
        "confirm",
        "reject",
        "defer",
        "claim-block semantic digest",
        "evidence-set digest",
        "stale",
        "AI/tool",
        "普通 Markdown",
    ):
        assert phrase in combined

    metadata = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]
    assert interface["display_name"] == "Research Review"
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$research-review" in interface["default_prompt"]
    assert SCRIPT.is_file()


def test_authorization_cases_use_the_production_parser() -> None:
    cases = json.loads((FIXTURES / "authorization-cases.json").read_text(encoding="utf-8"))
    observed: dict[str, bool] = {}
    for case in cases:
        message = (
            f"Review: {case['review_id']}\n"
            "Claim: claim-alpha\n"
            f"Decision: {case['decision']}\n"
            f"Signer: {case['actor']}\n"
        )
        try:
            review.parse_current_user_authorization(
                message,
                trusted_role=case["role"],
                message_origin=case["authorization_source"],
                is_current=case["authorization_source"] == "current_user_message",
                expected_review_id="review-anydoc-c001",
                expected_claim_id="claim-alpha",
            )
        except review.ReviewContractError:
            observed[case["id"]] = False
        else:
            observed[case["id"]] = True

    assert observed == {case["id"]: case["expected"] for case in cases}


@pytest.mark.parametrize(
    "actor",
    ("Claude Fable", "Sonnet latest", "Kimi", "Research Review Tool", "人工智能助手"),
)
def test_production_actor_screening_rejects_ai_and_tool_identities(actor: str) -> None:
    assert review.actor_is_allowed(actor) is False


def test_production_contract_has_no_helper_only_v1_schema() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "research-analysis/evidence-binding/v2" in source
    assert "research-review/confirmation-receipt/v2" in source
    assert "research-evidence-binding/v1" not in source

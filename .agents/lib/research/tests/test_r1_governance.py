from __future__ import annotations

from pathlib import Path

import pytest

from research.confirm import apply_confirmation, is_ai_signer
from research.evidence import build_verification_receipt, verify_claim_evidence
from research.paths import unit_root
from research.records import normalize_record_schema


def _claim(artifact: str, *, external: bool = False) -> dict:
    ref = {
        "source_unit_id": "p-r1-123456",
        "artifact": artifact,
        "locator": "section:test",
        "quote": "grounded words",
    }
    if external:
        ref["external_source"] = {"kind": "repo"}
    return {
        "id": "claim-r1",
        "text": "A grounded judgement.",
        "claim_type": "evaluation",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [ref],
    }


def test_r1_evidence_containment_rejects_absolute_parent_and_symlink_escape(tmp_path: Path) -> None:
    unit_root = tmp_path / "unit"
    unit_root.mkdir()
    (unit_root / "inside.md").write_text("grounded words", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("grounded words", encoding="utf-8")
    (unit_root / "escape.md").symlink_to(outside)

    assert verify_claim_evidence(_claim("inside.md"), unit_root) == []
    assert "absolute path" in verify_claim_evidence(_claim(outside.as_posix()), unit_root)[0]
    assert "must not contain '..'" in verify_claim_evidence(_claim("../outside.md"), unit_root)[0]
    assert "escapes allowed unit root" in verify_claim_evidence(_claim("escape.md"), unit_root)[0]


def test_r1_repo_external_source_requires_trusted_matching_base_root(tmp_path: Path) -> None:
    unit_root = tmp_path / "unit"
    repo_root = tmp_path / "repo"
    unit_root.mkdir()
    repo_root.mkdir()
    (repo_root / "README.md").write_text("grounded words", encoding="utf-8")
    claim = _claim("README.md", external=True)

    assert "trusted base-root contract" in verify_claim_evidence(claim, unit_root)[0]
    assert verify_claim_evidence(
        claim,
        unit_root,
        external_source={"kind": "repo", "base_root": repo_root.as_posix()},
    ) == []

    escaped = _claim("../unit/inside.md", external=True)
    assert "must not contain '..'" in verify_claim_evidence(
        escaped,
        unit_root,
        external_source={"kind": "repo", "base_root": repo_root.as_posix()},
    )[0]


def _verified_paper(project_root: Path) -> dict:
    record = {
        "id": "p-r1-123456",
        "kind": "paper",
        "information_types": ["fact", "inference", "evaluation"],
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "payload": {
            "core_content": {"method": "A grounded method."},
            "claims": [_claim("parse-cache.yaml")],
        },
    }
    root = unit_root(project_root, "paper", record["id"])
    root.mkdir(parents=True, exist_ok=True)
    (root / "parse-cache.yaml").write_text("source with grounded words", encoding="utf-8")
    build_verification_receipt(record, root, verified_at="2026-07-18T00:00:00+00:00")
    return record


def test_r1_judgement_confirmation_requires_current_verification_and_user_message(tmp_path: Path) -> None:
    record = _verified_paper(tmp_path)
    verification = record["payload"].pop("verification")
    with pytest.raises(SystemExit, match="user_authorization"):
        apply_confirmation(record, confirmed_by="Human Reviewer", evidence=["decision-log.md"], project_root=tmp_path)
    with pytest.raises(SystemExit, match="missing payload.verification"):
        apply_confirmation(
            record,
            confirmed_by="Human Reviewer",
            evidence=["decision-log.md"],
            user_authorization="I confirm this analysis.",
            authorization_source="user_message",
            project_root=tmp_path,
        )

    record["payload"]["verification"] = verification
    with pytest.raises(SystemExit, match="authorization_source=user_message"):
        apply_confirmation(
            record,
            confirmed_by="Human Reviewer",
            evidence=["decision-log.md"],
            user_authorization="I confirm this analysis.",
            authorization_source="",
            project_root=tmp_path,
        )

    confirmed = apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["decision-log.md"],
        user_authorization="I confirm this analysis.",
        authorization_source="user_message",
        project_root=tmp_path,
    )
    receipt = confirmed["confirmation"]
    assert receipt["claim_ids"] == ["claim-r1"]
    assert receipt["verified_at"] == "2026-07-18T00:00:00+00:00"
    assert receipt["user_authorization"] == "I confirm this analysis."
    assert receipt["authorization_source"] == "user_message"


def test_r1_artifact_byte_change_invalidates_confirmation(tmp_path: Path) -> None:
    record = _verified_paper(tmp_path)
    confirmed = apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["decision-log.md"],
        user_authorization="Confirmed.",
        authorization_source="user_message",
        project_root=tmp_path,
    )
    artifact = unit_root(tmp_path, "paper", record["id"]) / "parse-cache.yaml"
    artifact.write_text("source with grounded words and changed bytes", encoding="utf-8")

    normalized = normalize_record_schema(confirmed, project_root=tmp_path)

    assert normalized["confirmation_status"] == "pending_user_confirmation"
    assert normalized["payload"]["verification"]["invalidation"]["reason"] == "verification_stale"


@pytest.mark.parametrize(
    "actor",
    ["Codex Agent", "OpenAI Codex", "assistant-1", "GPT-5.6", "Claude Code"],
)
def test_r1_compound_ai_actor_is_rejected(actor: str) -> None:
    assert is_ai_signer(actor) is True


def test_r1_common_human_name_is_not_rejected() -> None:
    assert is_ai_signer("Claude Martin") is False

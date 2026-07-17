from __future__ import annotations

from pathlib import Path

from research.evidence import verify_claim_evidence


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

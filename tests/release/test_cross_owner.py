from __future__ import annotations

import json
from pathlib import Path

from support import load_module, REPO_ROOT


vault = load_module("release_cross_owner_vault", REPO_ROOT / "skills/research-vault/scripts/vault.py")
capture = load_module("release_cross_owner_capture", REPO_ROOT / "skills/research-capture/scripts/capture.py")
analysis = load_module("release_cross_owner_analysis", REPO_ROOT / "skills/research-analysis/scripts/analysis.py")
review = load_module("release_cross_owner_review", REPO_ROOT / "skills/research-review/scripts/review.py")


def test_capture_analysis_review_share_one_current_evidence_chain(tmp_path: Path) -> None:
    vault.initialize_vault(tmp_path)
    quote = "The frozen run reports 91 percent accuracy."
    captured = capture.capture_bytes(
        tmp_path,
        "source-alpha",
        "markdown",
        f"# Results\n{quote}\n".encode("utf-8"),
        filename="source.md",
    )
    assert captured.reader_path is not None
    reader_relative = captured.reader_path.relative_to(tmp_path).as_posix()
    reader_digest = analysis.sha256_digest(captured.reader_path.read_bytes())
    source = analysis.SourceRevision(
        source_id="source-alpha",
        revision=captured.revision_id,
        artifact_path=reader_relative,
        artifact_digest=reader_digest,
        reader_digest=reader_digest,
        source_kind="markdown",
        current=True,
    )
    evidence = analysis.Evidence(
        evidence_id="evidence-alpha",
        source_id=source.source_id,
        revision=source.revision,
        artifact_path=source.artifact_path,
        locator={"kind": "markdown", "line": 2},
        quote=quote,
        artifact_digest=source.artifact_digest,
        reader_digest=source.reader_digest,
    )
    claim = analysis.Claim(
        claim_id="claim-alpha",
        text="The frozen run reports 91 percent accuracy.",
        claim_class="observation",
        epistemic_state="factual",
        evidence_ids=(evidence.evidence_id,),
    )
    subject_path = tmp_path / "Notes" / "analysis-alpha.md"
    subject = analysis.render_analysis(
        analysis_id="analysis-alpha",
        subject="Frozen benchmark result",
        kind="single-source",
        sources=(source,),
        scope="The captured revision only.",
        claims=(claim,),
        evidence=(evidence,),
    )
    subject_path.write_text(subject, encoding="utf-8")
    bindings = analysis.build_bindings(
        subject,
        (source,),
        subject_markdown="Notes/analysis-alpha.md",
        base_dir=tmp_path,
    )
    analysis.write_bindings(bindings, tmp_path / ".research" / "evidence")

    packet = review.write_review_packet(
        tmp_path,
        subject_path="Notes/analysis-alpha.md",
        binding_path=".research/evidence/claim-alpha.json",
        review_path="Reviews/review-alpha.md",
        review_id="review-alpha",
        claim_id="claim-alpha",
    )
    assert packet.outcome == "pass"
    decision = review.apply_decision(
        tmp_path,
        subject_path="Notes/analysis-alpha.md",
        binding_path=".research/evidence/claim-alpha.json",
        review_path="Reviews/review-alpha.md",
        review_id="review-alpha",
        claim_id="claim-alpha",
        current_user_message=(
            "Review: review-alpha\nClaim: claim-alpha\nDecision: confirm\nSigner: Lin Chen\n"
        ),
        trusted_role="user",
        message_origin="current_user_message",
        is_current_message=True,
        interaction_ref="release-cross-owner",
        issued_at="2026-08-25T00:00:00Z",
    )

    assert "- Review state: `confirmed`" in subject_path.read_text(encoding="utf-8")
    receipt = json.loads((tmp_path / decision.receipt_path).read_text(encoding="utf-8"))
    assert receipt["subject"] == {
        "path": "Notes/analysis-alpha.md",
        "claim_id": "claim-alpha",
    }
    assert review.validate_receipt(
        tmp_path,
        subject_path="Notes/analysis-alpha.md",
        binding_path=".research/evidence/claim-alpha.json",
        review_path="Reviews/review-alpha.md",
        receipt_path=decision.receipt_path,
        review_id="review-alpha",
        claim_id="claim-alpha",
    ).valid

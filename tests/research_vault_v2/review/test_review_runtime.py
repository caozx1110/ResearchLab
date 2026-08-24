from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, relative: str) -> ModuleType:
    script = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vault = _load_module(
    "research_review_runtime_vault",
    "skills/research-vault/scripts/vault.py",
)
capture = _load_module(
    "research_review_runtime_capture",
    "skills/research-capture/scripts/capture.py",
)
analysis = _load_module(
    "research_review_runtime_analysis",
    "skills/research-analysis/scripts/analysis.py",
)
review = _load_module(
    "research_review_runtime_review",
    "skills/research-review/scripts/review.py",
)


SUBJECT_PATH = "Notes/analysis-alpha.md"
BINDING_PATH = ".research/evidence/claim-alpha.json"
REVIEW_PATH = "Reviews/review-alpha.md"
CLAIM_ID = "claim-alpha"
REVIEW_ID = "review-alpha"
QUOTE = "Exact reviewed sentence."


def _authorization(decision: str) -> str:
    return (
        f"Review: {REVIEW_ID}\n"
        f"Claim: {CLAIM_ID}\n"
        f"Decision: {decision}\n"
        "Signer: Lin Chen\n"
    )


def _build_workspace(tmp_path: Path, *, locator_line: int = 2) -> dict[str, object]:
    vault.initialize_vault(tmp_path)
    captured = capture.capture_bytes(
        tmp_path,
        "source-alpha",
        "markdown",
        f"# Source\n{QUOTE}\n".encode("utf-8"),
        filename="source.md",
    )
    assert captured.reader_path is not None
    assert captured.source_map_path is not None
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
        locator={"kind": "markdown", "line": locator_line},
        quote=QUOTE,
        artifact_digest=source.artifact_digest,
        reader_digest=source.reader_digest,
    )
    claim = analysis.Claim(
        claim_id=CLAIM_ID,
        text="The captured source contains the reviewed sentence.",
        claim_class="observation",
        epistemic_state="factual",
        evidence_ids=(evidence.evidence_id,),
    )
    markdown = analysis.render_analysis(
        analysis_id="analysis-alpha",
        subject="Production review interoperability",
        kind="single-source",
        sources=(source,),
        scope="The captured source revision only.",
        claims=(claim,),
        evidence=(evidence,),
    )
    subject = tmp_path / SUBJECT_PATH
    subject.write_text(markdown, encoding="utf-8")
    bindings = analysis.build_bindings(
        markdown,
        (source,),
        subject_markdown=SUBJECT_PATH,
        base_dir=tmp_path,
    )
    analysis.write_bindings(bindings, tmp_path / ".research" / "evidence")
    return {
        "captured": captured,
        "source": source,
        "evidence": evidence,
        "claim": claim,
        "binding": bindings[CLAIM_ID],
    }


def _write_packet(tmp_path: Path) -> object:
    return review.write_review_packet(
        tmp_path,
        subject_path=SUBJECT_PATH,
        binding_path=BINDING_PATH,
        review_path=REVIEW_PATH,
        review_id=REVIEW_ID,
        claim_id=CLAIM_ID,
    )


def _apply(tmp_path: Path, decision: str) -> object:
    return review.apply_decision(
        tmp_path,
        subject_path=SUBJECT_PATH,
        binding_path=BINDING_PATH,
        review_path=REVIEW_PATH,
        review_id=REVIEW_ID,
        claim_id=CLAIM_ID,
        current_user_message=_authorization(decision),
        trusted_role="user",
        message_origin="current_user_message",
        is_current_message=True,
        interaction_ref=f"interaction-{decision}",
        issued_at="2026-08-24T00:00:00Z",
    )


def test_runtime_consumes_analysis_v2_binding_and_capture_source_map(tmp_path: Path) -> None:
    _build_workspace(tmp_path)

    audit = _write_packet(tmp_path)

    assert audit.outcome == "pass"
    assert audit.confirm_eligible is True
    assert audit.binding_digest is not None
    packet = (tmp_path / REVIEW_PATH).read_text(encoding="utf-8")
    assert "status: awaiting-decision" in packet
    assert QUOTE in packet
    assert audit.claim_digest in packet
    assert audit.evidence_set_digest in packet


def test_source_map_must_bind_the_visible_quote_and_locator(tmp_path: Path) -> None:
    _build_workspace(tmp_path, locator_line=999)

    audit = _write_packet(tmp_path)

    assert audit.outcome == "invalid"
    assert audit.confirm_eligible is False
    assert any("typed locator" in finding for finding in audit.findings)
    with pytest.raises(review.ReviewContractError, match="confirm requires"):
        _apply(tmp_path, "confirm")


def test_confirm_updates_subject_review_and_receipt_in_one_vault_operation(tmp_path: Path) -> None:
    context = _build_workspace(tmp_path)
    original_claim_digest = context["binding"]["claim_digest"]
    _write_packet(tmp_path)

    decision = _apply(tmp_path, "confirm")

    subject = (tmp_path / SUBJECT_PATH).read_text(encoding="utf-8")
    packet = (tmp_path / REVIEW_PATH).read_text(encoding="utf-8")
    assert "- Review state: `confirmed`" in subject
    assert "status: confirmed" in packet
    assert "Confirmed by Lin Chen" in packet
    receipt = json.loads((tmp_path / decision.receipt_path).read_text(encoding="utf-8"))
    assert receipt["claim_digest"] == original_claim_digest
    validated = review.validate_receipt(
        tmp_path,
        subject_path=SUBJECT_PATH,
        binding_path=BINDING_PATH,
        review_path=REVIEW_PATH,
        receipt_path=decision.receipt_path,
        review_id=REVIEW_ID,
        claim_id=CLAIM_ID,
    )
    assert validated.valid, validated.reasons
    assert validated.state == "current"


def test_review_decision_rolls_back_all_visible_and_hidden_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_workspace(tmp_path)
    _write_packet(tmp_path)
    before_subject = (tmp_path / SUBJECT_PATH).read_bytes()
    before_review = (tmp_path / REVIEW_PATH).read_bytes()
    real_write = vault.VaultOperation.write
    writes = 0

    def fail_second_write(operation: object, path: Path | str, payload: str | bytes) -> str:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("simulated review transaction interruption")
        return real_write(operation, path, payload)

    monkeypatch.setattr(review, "_load_vault_runtime", lambda: vault)
    monkeypatch.setattr(vault.VaultOperation, "write", fail_second_write)

    with pytest.raises(review.ReviewConflictError, match="transaction failed"):
        _apply(tmp_path, "confirm")

    assert (tmp_path / SUBJECT_PATH).read_bytes() == before_subject
    assert (tmp_path / REVIEW_PATH).read_bytes() == before_review
    assert list((tmp_path / ".research" / "receipts").glob("*.json")) == []


def test_reject_and_defer_do_not_borrow_the_confirm_gate(tmp_path: Path) -> None:
    _build_workspace(tmp_path, locator_line=999)
    invalid_audit = _write_packet(tmp_path)
    assert invalid_audit.outcome == "invalid"

    rejected = _apply(tmp_path, "reject")
    rejected_validation = review.validate_receipt(
        tmp_path,
        subject_path=SUBJECT_PATH,
        binding_path=BINDING_PATH,
        review_path=REVIEW_PATH,
        receipt_path=rejected.receipt_path,
        review_id=REVIEW_ID,
        claim_id=CLAIM_ID,
    )
    assert rejected_validation.valid, rejected_validation.reasons

    second_root = tmp_path / "blocked"
    _build_workspace(second_root)
    (second_root / BINDING_PATH).unlink()
    blocked_audit = _write_packet(second_root)
    assert blocked_audit.outcome == "blocked"

    deferred = _apply(second_root, "defer")
    deferred_validation = review.validate_receipt(
        second_root,
        subject_path=SUBJECT_PATH,
        binding_path=BINDING_PATH,
        review_path=REVIEW_PATH,
        receipt_path=deferred.receipt_path,
        review_id=REVIEW_ID,
        claim_id=CLAIM_ID,
    )
    assert deferred_validation.valid, deferred_validation.reasons

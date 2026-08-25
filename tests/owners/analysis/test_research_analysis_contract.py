from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "research-analysis" / "scripts" / "analysis.py"
VAULT_SCRIPT = REPO_ROOT / "skills" / "research-vault" / "scripts" / "vault.py"
SKILL = REPO_ROOT / "skills" / "research-analysis"
FIXTURES = Path(__file__).parent / "fixtures"
LIB_ROOT = REPO_ROOT / "runtime" / "lib"
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))

from support import load_skill_validator


validate_skill = load_skill_validator().validate_skill


def _load_analysis():
    spec = importlib.util.spec_from_file_location("research_analysis_v2_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


analysis = _load_analysis()


def _load_vault():
    spec = importlib.util.spec_from_file_location("research_vault_v2_interop", VAULT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vault = _load_vault()


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    for source_id in ("source-alpha", "source-beta"):
        target = tmp_path / "Sources" / source_id / ".source" / "revisions" / "rev-1" / "reader.md"
        target.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / f"{source_id}.md", target)
    return tmp_path


def _source(root: Path, source_id: str, revision: str = "rev-1", *, current: bool = True):
    relative = Path("Sources") / source_id / ".source" / "revisions" / revision / "reader.md"
    payload = (root / relative).read_bytes()
    digest = analysis.sha256_digest(payload)
    return analysis.SourceRevision(
        source_id=source_id,
        revision=revision,
        artifact_path=relative.as_posix(),
        artifact_digest=digest,
        reader_digest=digest,
        source_kind="markdown",
        current=current,
    )


def _evidence(source, evidence_id: str, quote: str, paragraph: int = 1):
    return analysis.Evidence(
        evidence_id=evidence_id,
        source_id=source.source_id,
        revision=source.revision,
        artifact_path=source.artifact_path,
        locator={"kind": "markdown", "heading": "Results", "paragraph": paragraph},
        quote=quote,
        artifact_digest=source.artifact_digest,
        reader_digest=source.reader_digest,
    )


def _claim(claim_id: str, text: str, evidence_id: str, *, claim_class: str = "observation"):
    state = "factual" if claim_class in {"observation", "extracted_fact"} else "interpretive"
    return analysis.Claim(
        claim_id=claim_id,
        text=text,
        claim_class=claim_class,
        epistemic_state=state,
        evidence_ids=(evidence_id,),
        limitations="Bound to the quoted frozen revision.",
    )


def _single_document(root: Path):
    source = _source(root, "source-alpha")
    evidence = _evidence(
        source,
        "evidence-alpha",
        "The system reports 91 percent accuracy on the frozen benchmark.",
    )
    claim = _claim(
        "claim-alpha",
        "The source reports 91 percent accuracy on the frozen benchmark.",
        evidence.evidence_id,
    )
    markdown = analysis.render_analysis(
        analysis_id="analysis-alpha",
        subject="Frozen benchmark result",
        kind="single-source",
        sources=(source,),
        scope="Reported benchmark result only.",
        non_goals=("No deployment claim.",),
        selection_boundary="One explicitly selected source revision.",
        claims=(claim,),
        evidence=(evidence,),
    )
    return source, evidence, claim, markdown


def _synthesis_document(root: Path):
    alpha = _source(root, "source-alpha")
    beta = _source(root, "source-beta")
    evidence_alpha = _evidence(
        alpha,
        "evidence-alpha",
        "The system reports 91 percent accuracy on the frozen benchmark.",
    )
    evidence_beta = _evidence(
        beta,
        "evidence-beta",
        "The comparison uses the same frozen benchmark and reports 88 percent accuracy.",
    )
    claims = (
        _claim("claim-alpha", "Source alpha reports 91 percent.", evidence_alpha.evidence_id),
        _claim("claim-beta", "Source beta reports 88 percent.", evidence_beta.evidence_id),
    )
    markdown = analysis.render_synthesis(
        analysis_id="synthesis-benchmark",
        subject="Frozen benchmark comparison",
        sources=(alpha, beta),
        scope="Compare only the reported frozen benchmark.",
        non_goals=("No cross-environment ranking.",),
        selection_boundary="The two sources using the named frozen benchmark are included.",
        claims=claims,
        evidence=(evidence_alpha, evidence_beta),
        conflicts=("The reported values differ; no cause is inferred.",),
        gaps=("Neither source establishes deployment performance.",),
    )
    return (alpha, beta), claims, markdown


def test_standalone_skill_validator_accepts_v2_skill() -> None:
    assert validate_skill(SKILL) == []


def test_prepare_creates_only_visible_empty_scaffold(workspace: Path) -> None:
    source = _source(workspace, "source-alpha")
    prepared = analysis.prepare_analysis(
        analysis_id="analysis-empty",
        subject="Awaiting Agent reading",
        kind="single-source",
        sources=(source,),
        scope="Frozen source only.",
    )

    assert "### Source `source-alpha@rev-1`" in prepared
    assert "### Claim `" not in prepared
    assert "Agent fill required: claims" in prepared
    report = analysis.verify_analysis(prepared, (source,), bindings={}, base_dir=workspace)
    assert not report.ok
    assert "analysis requires at least one Agent-authored claim" in report.errors
    assert not (workspace / ".research").exists()


def test_prepared_analysis_is_accepted_by_vault_index_without_unknown_fields(workspace: Path) -> None:
    vault_root = workspace / "vault"
    vault.initialize_vault(vault_root)
    source = _source(workspace, "source-alpha")
    prepared = analysis.prepare_analysis(
        analysis_id="analysis-interop",
        subject="Production schema interoperability",
        kind="single-source",
        sources=(source,),
        scope="Frozen source only.",
    )
    target = vault_root / "Notes" / "analysis-interop.md"
    target.write_text(prepared, encoding="utf-8")

    rebuilt = vault.rebuild_index(vault_root)

    page = next(item for item in rebuilt["pages"] if item["path"] == "Notes/analysis-interop.md")
    assert page == {
        "id": "analysis-interop",
        "kind": "single-source",
        "path": "Notes/analysis-interop.md",
        "status": "draft",
        "title": "Analysis: Production schema interoperability",
    }

    invalid = prepared.replace("subject:", "unknown_field: forbidden\nsubject:", 1)
    with pytest.raises(analysis.AnalysisContractError, match="unsupported"):
        analysis.parse_analysis(invalid)
    target.write_text(invalid, encoding="utf-8")
    with pytest.raises(vault.VaultError, match="unsupported"):
        vault.rebuild_index(vault_root)


def test_write_bindings_rejects_symlinked_evidence_directory(workspace: Path, tmp_path: Path) -> None:
    research = workspace / ".research"
    research.mkdir()
    outside = tmp_path / "outside-evidence"
    outside.mkdir()
    (research / "evidence").symlink_to(outside, target_is_directory=True)

    with pytest.raises(analysis.AnalysisContractError):
        analysis.write_bindings({"claim-alpha": {"claim_id": "claim-alpha"}}, research / "evidence")

    assert not (outside / "claim-alpha.json").exists()


def test_write_bindings_rechecks_evidence_directory_identity_at_commit(
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = workspace / ".research" / "evidence"
    evidence.mkdir(parents=True)
    detached = workspace / ".research" / "evidence.detached"
    outside = tmp_path / "outside-binding-race"
    outside.mkdir()
    original_boundary_check = analysis._assert_analysis_directory_binding
    swapped = False

    def swap_before_commit(*args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped:
            evidence.rename(detached)
            evidence.symlink_to(outside, target_is_directory=True)
            swapped = True
        original_boundary_check(*args, **kwargs)

    monkeypatch.setattr(analysis, "_assert_analysis_directory_binding", swap_before_commit)

    with pytest.raises(analysis.AnalysisContractError, match="evidence"):
        analysis.write_bindings(
            {"claim-alpha": {"claim_id": "claim-alpha"}},
            evidence,
        )

    assert swapped
    assert not (outside / "claim-alpha.json").exists()
    assert not (detached / "claim-alpha.json").exists()


@pytest.mark.parametrize(
    ("claim_class", "epistemic_state"),
    (("observation", "interpretive"), ("inference", "factual")),
)
def test_claim_classes_separate_factual_interpretive_and_uncertain(
    claim_class: str, epistemic_state: str
) -> None:
    with pytest.raises(analysis.AnalysisContractError):
        analysis.Claim(
            claim_id="claim-invalid",
            text="This combination is not allowed.",
            claim_class=claim_class,
            epistemic_state=epistemic_state,
            evidence_ids=("evidence-1",),
        )
    uncertain = analysis.Claim(
        claim_id="claim-uncertain",
        text="The available evidence does not resolve this point.",
        claim_class=claim_class,
        epistemic_state="uncertain",
        evidence_ids=("evidence-1",),
    )
    assert uncertain.epistemic_state == "uncertain"
    governed = analysis.Claim(
        claim_id="claim-confirmed",
        text="An Agent cannot confirm this claim.",
        claim_class="observation",
        epistemic_state="factual",
        evidence_ids=("evidence-1",),
        review_state="confirmed",
    )
    with pytest.raises(analysis.AnalysisContractError, match="self-authorize"):
        analysis.render_analysis(
            analysis_id="analysis-confirmed",
            subject="Governed state",
            kind="single-source",
            claims=(governed,),
        )


def test_exact_quote_locator_revision_and_digest_binding(workspace: Path) -> None:
    source, evidence, claim, markdown = _single_document(workspace)
    bindings = analysis.build_bindings(
        markdown,
        (source,),
        subject_markdown="Notes/analysis-alpha.md",
        base_dir=workspace,
    )

    binding = bindings[claim.claim_id]
    row = binding["evidence"][0]
    assert binding["claim_digest"] == claim.claim_digest
    assert row["source_revision"] == "rev-1"
    assert row["locator"] == evidence.locator
    assert row["exact_quote"] == evidence.quote
    assert row["quote_digest"] == analysis.sha256_digest(evidence.quote)
    assert row["evidence_digest"] == evidence.evidence_digest
    assert not {"claim_text", "class", "epistemic_state", "review_state"}.intersection(binding)
    analysis.write_bindings(bindings, workspace / ".research" / "evidence")
    persisted = json.loads(
        (workspace / ".research" / "evidence" / "claim-alpha.json").read_text(encoding="utf-8")
    )
    assert persisted == binding

    report = analysis.verify_analysis(
        markdown,
        (source,),
        bindings=bindings,
        base_dir=workspace,
        subject_markdown="Notes/analysis-alpha.md",
    )
    assert report.ok, (report.errors, report.stale_by_claim)


def test_quote_and_locator_fail_closed(workspace: Path) -> None:
    source = _source(workspace, "source-alpha")
    evidence = _evidence(source, "evidence-wrong", "This quote does not exist.")
    claim = _claim("claim-wrong", "A claim with fabricated evidence.", evidence.evidence_id)
    markdown = analysis.render_analysis(
        analysis_id="analysis-wrong",
        subject="Invalid evidence",
        kind="single-source",
        sources=(source,),
        scope="Failure fixture.",
        selection_boundary="One source.",
        claims=(claim,),
        evidence=(evidence,),
    )
    with pytest.raises(analysis.AnalysisContractError, match="not exact source text"):
        analysis.build_bindings(markdown, (source,), base_dir=workspace)
    with pytest.raises(analysis.AnalysisContractError, match="identify a location"):
        analysis.Evidence(
            evidence_id="evidence-no-location",
            source_id=source.source_id,
            revision=source.revision,
            artifact_path=source.artifact_path,
            locator={"kind": "pdf"},
            quote="quote",
            artifact_digest=source.artifact_digest,
            reader_digest=source.reader_digest,
        )


def test_synthesis_requires_boundaries_conflicts_and_gaps(workspace: Path) -> None:
    sources, claims, valid_markdown = _synthesis_document(workspace)
    valid_bindings = analysis.build_bindings(valid_markdown, sources, base_dir=workspace)
    assert analysis.verify_analysis(
        valid_markdown,
        sources,
        bindings=valid_bindings,
        base_dir=workspace,
    ).ok

    parsed = analysis.parse_analysis(valid_markdown)
    invalid_markdown = analysis.render_synthesis(
        analysis_id=parsed.analysis_id,
        subject=parsed.subject,
        sources=parsed.source_revisions,
        scope=parsed.scope,
        claims=parsed.claims,
        evidence=parsed.evidence,
    )
    invalid_bindings = analysis.build_bindings(invalid_markdown, sources, base_dir=workspace)
    report = analysis.verify_analysis(
        invalid_markdown,
        sources,
        bindings=invalid_bindings,
        base_dir=workspace,
    )
    assert not report.ok
    assert any("selection boundary" in error for error in report.errors)
    assert any("conflicts" in error for error in report.errors)
    assert any("coverage gaps" in error for error in report.errors)


def test_stale_propagation_is_limited_to_dependent_claim(workspace: Path) -> None:
    sources, _, markdown = _synthesis_document(workspace)
    bindings = analysis.build_bindings(markdown, sources, base_dir=workspace)
    alpha_old, beta = sources

    new_path = workspace / "Sources/source-alpha/.source/revisions/rev-2/reader.md"
    new_path.parent.mkdir(parents=True)
    new_path.write_text("# Results\n\nA newly published result.\n", encoding="utf-8")
    alpha_old = analysis.SourceRevision(**{**alpha_old.__dict__, "current": False})
    alpha_new = _source(workspace, "source-alpha", "rev-2")
    report = analysis.verify_analysis(
        markdown,
        (alpha_old, alpha_new, beta),
        bindings=bindings,
        base_dir=workspace,
    )

    assert report.stale_claims == ("claim-alpha",)
    assert report.effective_state("claim-alpha") == "stale"
    assert report.effective_state("claim-beta") == "pending"
    assert not report.errors


def test_visible_claim_edit_stales_binding_without_rewriting_markdown(workspace: Path) -> None:
    sources, _, markdown = _synthesis_document(workspace)
    bindings = analysis.build_bindings(markdown, sources, base_dir=workspace)
    edited = markdown.replace(
        "Source alpha reports 91 percent.",
        "Source alpha reports a benchmark value of 91 percent.",
    )

    report = analysis.verify_analysis(
        edited,
        sources,
        bindings=bindings,
        base_dir=workspace,
    )
    assert report.stale_claims == ("claim-alpha",)
    assert "Source alpha reports a benchmark value" in edited
    assert bindings["claim-alpha"]["binding_state"] == "current"


def test_source_material_is_never_executed() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert imported.isdisjoint({"subprocess", "runpy", "importlib"})
    assert called_names.isdisjoint({"eval", "exec", "compile", "__import__"})

from __future__ import annotations

import copy

import pytest

from research.confirm import has_substantive_content
from research.paper_drafts import (
    SECTION_IDENTITIES,
    build_draft_manifest,
    build_publication_manifest,
    build_section_fill_scaffold,
    draft_manifest_currentness_violations,
    paper_draft_section_content_digest,
    paper_draft_section_lifecycle_violations,
    render_paper_draft_latex,
    render_paper_draft_markdown,
    section_fill_shape_violations,
    validate_publication_sections,
    verify_section_fill,
)


QUOTE = "Frozen evidence bytes support this paragraph."


def _support_binding(suffix: str = "a") -> dict:
    return {
        "source_unit_id": f"p-source-{suffix}",
        "claim_id": f"claim-source-{suffix}",
        "confirmation_status": "confirmed",
        "claim_digest": suffix * 64,
        "record_content_digest": suffix * 64,
        "confirmation_receipt_digest": suffix * 64,
        "evidence_digest": suffix * 64,
        "evidence_refs": [
            {
                "source_unit_id": f"p-source-{suffix}",
                "artifact": "note.md",
                "locator": "line=1",
                "quote": QUOTE,
            }
        ],
    }


def _catalogs() -> tuple[dict, dict, dict]:
    claims = {
        "p-source-b:claim-source-b": _support_binding("b"),
        "p-source-a:claim-source-a": _support_binding("a"),
    }
    bibliography = {
        "cite_p_source_b": {"entry_digest": "b" * 64, "record_digest": "b" * 64},
        "cite_p_source_a": {"entry_digest": "a" * 64, "record_digest": "a" * 64},
    }
    figures = {
        "fig:p-source-a:fig:1": {
            "index_digest": "a" * 64,
            "source_digest": "b" * 64,
            "asset_digests": ["c" * 64],
        }
    }
    return claims, bibliography, figures


def _manifest(outline: bytes = b"# exact outline\n") -> dict:
    claims, bibliography, figures = _catalogs()
    return build_draft_manifest(
        program_id="draft-program",
        outline_bytes=outline,
        claim_catalog=claims,
        bibliography_catalog=bibliography,
        figure_catalog=figures,
        as_of="2026-07-27T00:00:00Z",
    )


def _resolvers(manifest: dict):
    catalogs = manifest["catalogs"]

    def index(name: str, key_name: str) -> dict:
        return {item[key_name]: copy.deepcopy(item["binding"]) for item in catalogs[name]}

    claims = index("claims", "ref_key")
    bibliography = index("bibliography", "citation_key")
    figures = index("figures", "ref_key")
    return claims.get, bibliography.get, figures.get


def _filled(manifest: dict, section_id: str = "introduction", *, prose: str = "Agent wrote this paragraph.") -> dict:
    fill = build_section_fill_scaffold(manifest, section_id)
    fill["paragraphs"][0].update(
        {
            "prose": prose,
            "claim_type": "inference",
            "support_claim_refs": ["p-source-a:claim-source-a"],
            "citation_keys": ["cite_p_source_a"],
            "figure_refs": ["fig:p-source-a:fig:1"],
        }
    )
    return fill


def _pending_record(manifest: dict, section_id: str, *, prose: str = "Agent wrote this paragraph.") -> dict:
    support, citation, figure = _resolvers(manifest)
    violations, record = verify_section_fill(
        _filled(manifest, section_id, prose=prose),
        manifest,
        resolve_support=support,
        resolve_citation=citation,
        resolve_figure=figure,
        verified_at="2026-07-27T01:00:00Z",
    )
    assert violations == [], violations
    assert record is not None
    return record


def _confirmed_sections(manifest: dict, *, special_first: str = "Agent wrote this paragraph.") -> list[dict]:
    records = []
    for section_id in SECTION_IDENTITIES:
        prose = special_first if section_id == "introduction" else f"Agent-authored {section_id} paragraph."
        record = _pending_record(manifest, section_id, prose=prose)
        record["confirmation_status"] = "confirmed"
        record["needs_human_confirmation"] = False
        record["payload"]["verification"] = {
            "verified_at": "2026-07-27T01:00:00Z",
            "claims_digest": "a" * 64,
            "evidence_digest": "b" * 64,
            "artifacts": [{"identity": "fixture"}],
        }
        record["confirmation"] = {
            "decision": "confirmed",
            "content_digest": paper_draft_section_content_digest(record),
        }
        records.append(record)
    return records


def test_manifest_is_deterministic_sorted_and_exact_outline_bound() -> None:
    first = _manifest()
    claims, bibliography, figures = _catalogs()
    reordered = build_draft_manifest(
        program_id="draft-program",
        outline_bytes=b"# exact outline\n",
        claim_catalog=dict(reversed(list(claims.items()))),
        bibliography_catalog=dict(reversed(list(bibliography.items()))),
        figure_catalog=figures,
        as_of="2026-07-27T00:00:00Z",
    )

    assert first == reordered
    assert [item["ref_key"] for item in first["catalogs"]["claims"]] == sorted(claims)
    current_claims, current_bib, current_figures = _catalogs()
    assert draft_manifest_currentness_violations(
        first,
        outline_bytes=b"# exact outline\n",
        claim_catalog=current_claims,
        bibliography_catalog=current_bib,
        figure_catalog=current_figures,
    ) == []
    violations = draft_manifest_currentness_violations(
        first,
        outline_bytes=b"# changed outline\n",
        claim_catalog=current_claims,
        bibliography_catalog=current_bib,
        figure_catalog=current_figures,
    )
    assert any("outline bytes changed" in item for item in violations)


def test_scaffold_is_hollow_and_raw_latex_or_extra_shape_is_rejected() -> None:
    manifest = _manifest()
    fill = build_section_fill_scaffold(manifest, "method")
    assert fill["paragraphs"][0]["prose"] == ""
    support, citation, figure = _resolvers(manifest)

    violations, record = verify_section_fill(
        fill,
        manifest,
        resolve_support=support,
        resolve_citation=citation,
        resolve_figure=figure,
    )
    assert record is None
    assert any("runtime-Agent authored text" in item for item in violations)

    fill["paragraphs"][0]["raw_latex"] = r"\input{/etc/passwd}"
    violations = section_fill_shape_violations(fill, manifest)
    assert any("unexpected fields" in item for item in violations)


def test_verify_rejects_unknown_and_stale_refs_and_copies_no_forged_evidence() -> None:
    manifest = _manifest()
    fill = _filled(manifest)
    fill["paragraphs"][0]["support_claim_refs"] = ["p-source-z:claim-source-z"]
    support, citation, figure = _resolvers(manifest)
    violations, record = verify_section_fill(
        fill,
        manifest,
        resolve_support=support,
        resolve_citation=citation,
        resolve_figure=figure,
    )
    assert record is None
    assert any("unknown claim" in item for item in violations)

    fill = _filled(manifest)
    stale_support = copy.deepcopy(support("p-source-a:claim-source-a"))
    stale_support["evidence_refs"][0]["quote"] = "forged current bytes"
    violations, record = verify_section_fill(
        fill,
        manifest,
        resolve_support=lambda _key: stale_support,
        resolve_citation=citation,
        resolve_figure=figure,
    )
    assert record is None
    assert any("support claim" in item and "binding changed" in item for item in violations)


def test_pending_record_has_fixed_identity_and_mechanical_evidence_projection() -> None:
    manifest = _manifest()
    record = _pending_record(manifest, "related-work")
    paragraph = record["payload"]["paper_draft_section"]["paragraphs"][0]
    claim = record["payload"]["claims"][0]
    frozen = _resolvers(manifest)[0]("p-source-a:claim-source-a")

    assert record["id"] == "paper-draft-section:draft-program:related-work"
    assert record["kind"] == "paper_draft_section"
    assert record["owner"] == "report-author"
    assert record["confirmation_status"] == "pending_user_confirmation"
    assert paragraph["prose"] == claim["text"]
    assert claim["evidence_refs"] == frozen["evidence_refs"]
    assert claim["evidence_refs"] is not frozen["evidence_refs"]
    digest = paper_draft_section_content_digest(record)
    record["payload"]["paper_draft_section"]["paragraphs"][0]["citation_keys"].append("cite_p_source_b")
    assert paper_draft_section_content_digest(record) != digest


def test_confirmation_substance_gate_requires_prose_support_and_citation() -> None:
    record = _pending_record(_manifest(), "method")
    assert has_substantive_content(record)

    for field, empty_value in (
        ("prose", ""),
        ("support_claim_refs", []),
        ("citation_keys", []),
    ):
        hollow = copy.deepcopy(record)
        hollow["payload"]["paper_draft_section"]["paragraphs"][0][field] = empty_value
        assert not has_substantive_content(hollow)


def test_lifecycle_detects_manifest_staleness_and_projection_tamper() -> None:
    manifest = _manifest()
    record = _pending_record(manifest, "experiments")
    support, citation, figure = _resolvers(manifest)
    assert paper_draft_section_lifecycle_violations(
        record,
        manifest,
        resolve_support=support,
        resolve_citation=citation,
        resolve_figure=figure,
        manifest_is_current=lambda _manifest: True,
    ) == []

    record["payload"]["claims"][0]["evidence_refs"][0]["quote"] = "forged"
    violations = paper_draft_section_lifecycle_violations(
        record,
        manifest,
        resolve_support=support,
        resolve_citation=citation,
        resolve_figure=figure,
        manifest_is_current=lambda _manifest: False,
    )
    assert any("manifest is stale" in item for item in violations)
    assert any("mechanical support projection" in item for item in violations)


def test_seven_section_gate_requires_unique_manifest_order_and_current_receipts() -> None:
    manifest = _manifest()
    records = _confirmed_sections(manifest)
    assert validate_publication_sections(
        manifest,
        records,
        section_is_current=lambda _record: True,
        confirmation_is_current=lambda _record: True,
    ) == []

    violations = validate_publication_sections(
        manifest,
        records[:-1],
        section_is_current=lambda _record: True,
        confirmation_is_current=lambda _record: True,
    )
    assert any("all seven" in item for item in violations)

    violations = validate_publication_sections(
        manifest,
        list(reversed(records)),
        section_is_current=lambda _record: True,
        confirmation_is_current=lambda record: record["section_id"] != "method",
    )
    assert any("manifest order" in item for item in violations)
    assert any("receipt" in item and "method" in item for item in violations)


def test_markdown_latex_and_publication_manifest_are_safe_and_byte_bound() -> None:
    manifest = _manifest()
    prose = r"Agent prose: x_1 & 50% #tag $5 {value} \input{bad} ^ ~."
    records = _confirmed_sections(manifest, special_first=prose)
    predicates = {
        "section_is_current": lambda _record: True,
        "confirmation_is_current": lambda _record: True,
    }
    markdown = render_paper_draft_markdown(manifest, records, title="Draft #1", **predicates)
    latex = render_paper_draft_latex(manifest, records, title="Draft #1", **predicates)

    assert markdown.startswith("# Draft \\#1\n")
    assert "\\#tag" in markdown
    assert r"x\_1 \& 50\% \#tag \$5 \{value\}" in latex
    assert r"\textbackslash{}input\{bad\}" in latex
    assert r"\input{bad}" not in latex
    assert latex.index(r"\section{Introduction}") < latex.index(r"\section{Related Work}")

    publication = build_publication_manifest(
        manifest,
        records,
        markdown_bytes=markdown.encode("utf-8"),
        latex_bytes=latex.encode("utf-8"),
        bibliography_bytes=b"@article{cite_p_source_a}\n",
        published_at="2026-07-27T02:00:00Z",
        **predicates,
    )
    assert [item["section_id"] for item in publication["sections"]] == list(SECTION_IDENTITIES)
    assert [item["filename"] for item in publication["artifacts"]] == [
        "paper-draft.md",
        "paper-draft.tex",
        "references.bib",
    ]
    assert all(len(item["byte_sha256"]) == 64 for item in publication["artifacts"])

    with pytest.raises(ValueError, match="publication gate failed"):
        render_paper_draft_markdown(
            manifest,
            records[:-1],
            section_is_current=lambda _record: True,
            confirmation_is_current=lambda _record: True,
        )

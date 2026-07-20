"""Evidence layer: verbatim quote verification + claim validation + attach.

Covers SSOT Part 2 Principle 2 (B3 short verbatim, B4 two locator families,
judgement empty-evidence rejection). All fixtures are synthetic temp dirs — kb/
is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research.evidence import (
    Claim,
    EvidenceRef,
    as_claim_dict,
    attach_claims,
    normalize_ws,
    read_claims,
    validate_claims,
    verify_claim_evidence,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

def _write_parse_cache(unit: Path) -> None:
    """A parse-cache with per-page chunks; page-1 text has a line-wrap + gap."""
    (unit / "parse-cache.yaml").write_text(
        "paper_id: p-demo-0001\n"
        "chunks:\n"
        "- label: 'demo:page-1'\n"
        "  text: |-\n"
        "    The foobar latent uses a widget encoder at 42 Hz\n"
        "    on the  gadget robot.\n"
        "- label: 'demo:page-2'\n"
        "  text: 'Ablations remove the widget encoder and accuracy drops sharply.'\n",
        encoding="utf-8",
    )


def _ref(**kw: object) -> dict:
    base = {"source_unit_id": "p-demo-0001", "artifact": "parse-cache.yaml", "locator": "page=1", "quote": ""}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# normalize_ws                                                                 #
# --------------------------------------------------------------------------- #

def test_normalize_ws_folds_whitespace_preserves_case_and_punctuation() -> None:
    assert normalize_ws("a   b\n\t c") == "a b c"
    assert normalize_ws("  Padded  ") == "Padded"
    # case + punctuation preserved (not folded)
    assert normalize_ws("Hz, on-the Robot.") == "Hz, on-the Robot."
    assert normalize_ws(None) == ""


# --------------------------------------------------------------------------- #
# verify_claim_evidence — grounded / fabricated / normalization                #
# --------------------------------------------------------------------------- #

def test_verbatim_hit_returns_no_violation(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [_ref(quote="Ablations remove the widget encoder", locator="page=2")]}
    assert verify_claim_evidence(claim, tmp_path) == []


def test_whitespace_normalized_quote_across_linewrap_hits(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    # quote spans the page-1 line wrap AND collapses the double space before "gadget"
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [_ref(quote="widget encoder at 42 Hz on the gadget robot")]}
    assert verify_claim_evidence(claim, tmp_path) == []


def test_fabricated_quote_returns_violation(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    claim = {"id": "c-fab", "claim_type": "fact",
             "evidence_refs": [_ref(quote="widget encoder running at 9000 Hz on the moon rover")]}
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "c-fab" in violations[0]
    assert "not verbatim" in violations[0]
    assert "parse-cache.yaml" in violations[0]


def test_case_difference_is_not_tolerated(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    # source says 'widget encoder'; upper-cased quote must miss (case-sensitive B3)
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [_ref(quote="WIDGET ENCODER at 42 Hz")]}
    assert len(verify_claim_evidence(claim, tmp_path)) == 1


def test_punctuation_difference_is_not_tolerated(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    # source has no comma after 'Hz'; adding one breaks the verbatim match
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [_ref(quote="widget encoder at 42 Hz, on the gadget robot")]}
    assert len(verify_claim_evidence(claim, tmp_path)) == 1


# --------------------------------------------------------------------------- #
# verify_claim_evidence — locator narrowing (B4 page=N)                         #
# --------------------------------------------------------------------------- #

def test_locator_page_match_is_clean(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [_ref(quote="Ablations remove the widget encoder", locator="page=2")]}
    assert verify_claim_evidence(claim, tmp_path) == []


def test_locator_page_mismatch_is_flagged(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    # quote is real but on page 2, cited as page 1
    claim = {"id": "c-mis", "claim_type": "fact",
             "evidence_refs": [_ref(quote="Ablations remove the widget encoder", locator="page=1")]}
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "locator page=1 is wrong" in violations[0]
    assert "page(s) [2]" in violations[0]


def test_non_page_locator_skips_narrowing(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    # HTML-style locator: no page narrowing, full-text verbatim hit is enough
    claim = {"id": "c1", "claim_type": "inference",
             "evidence_refs": [_ref(quote="Ablations remove the widget encoder", locator="section=results")]}
    assert verify_claim_evidence(claim, tmp_path) == []


# --------------------------------------------------------------------------- #
# verify_claim_evidence — artifact families + degenerate inputs                 #
# --------------------------------------------------------------------------- #

def test_plain_markdown_artifact_is_searched(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("# Note\n\nThe gadget robot runs at 42 Hz.\n", encoding="utf-8")
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [{"artifact": "note.md", "locator": "section=intro", "quote": "gadget robot runs at 42 Hz"}]}
    assert verify_claim_evidence(claim, tmp_path) == []


def test_yaml_without_chunks_falls_back_to_string_leaves(tmp_path: Path) -> None:
    (tmp_path / "meta.yaml").write_text("title: A Study of Widgets\nnotes: [alpha, beta gamma]\n", encoding="utf-8")
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [{"artifact": "meta.yaml", "locator": "section", "quote": "beta gamma"}]}
    assert verify_claim_evidence(claim, tmp_path) == []


@pytest.mark.parametrize(
    ("line", "quote"),
    [
        (1, "evidence_required: true"),
        (2, "threshold: 0.75"),
        (3, 'mode: "strict"'),
    ],
)
def test_yaml_raw_key_scalar_lines_are_searchable(tmp_path: Path, line: int, quote: str) -> None:
    (tmp_path / "config.yaml").write_text(
        "evidence_required: true\n"
        "threshold: 0.75\n"
        'mode: "strict"\n',
        encoding="utf-8",
    )
    claim = {
        "id": "c-yaml-raw",
        "claim_type": "fact",
        "evidence_refs": [
            {"artifact": "config.yaml", "locator": f"line={line}", "quote": quote},
        ],
    }

    assert verify_claim_evidence(claim, tmp_path) == []


def test_yaml_fabricated_key_value_line_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "evidence_required: true\nthreshold: 0.75\n",
        encoding="utf-8",
    )
    claim = {
        "id": "c-yaml-fabricated",
        "claim_type": "fact",
        "evidence_refs": [
            {
                "artifact": "config.yaml",
                "locator": "line=1",
                "quote": "evidence_required: false",
            },
        ],
    }

    violations = verify_claim_evidence(claim, tmp_path)

    assert len(violations) == 1
    assert "not verbatim" in violations[0]


def test_yaml_parse_cache_keeps_structured_chunk_and_page_narrowing(tmp_path: Path) -> None:
    # The raw YAML contains the two-character escape ``\\n``. Only the parsed
    # chunk view contains an actual line break, so this locks in the structured
    # search view while the raw YAML view is added for config-key evidence.
    (tmp_path / "parse-cache.yaml").write_text(
        "unit_id: p-structured\n"
        "chunks:\n"
        "- label: structured:page-4\n"
        '  text: "First chunk line\\nSecond chunk line"\n',
        encoding="utf-8",
    )
    ref = {
        "source_unit_id": "p-structured",
        "artifact": "parse-cache.yaml",
        "locator": "page=4",
        "quote": "First chunk line Second chunk line",
    }
    claim = {"id": "c-structured", "claim_type": "fact", "evidence_refs": [ref]}

    assert verify_claim_evidence(claim, tmp_path) == []

    ref["locator"] = "page=3"
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "locator page=3 is wrong" in violations[0]
    assert "page(s) [4]" in violations[0]


def test_missing_artifact_file_is_violation(tmp_path: Path) -> None:
    claim = {"id": "c1", "claim_type": "fact",
             "evidence_refs": [_ref(quote="anything")]}
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "not found" in violations[0]


def test_empty_quote_is_violation(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    claim = {"id": "c1", "claim_type": "fact", "evidence_refs": [_ref(quote="   ")]}
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "empty quote" in violations[0]


def test_missing_artifact_field_is_violation(tmp_path: Path) -> None:
    claim = {"id": "c1", "claim_type": "fact", "evidence_refs": [{"quote": "some text", "locator": "page=1"}]}
    violations = verify_claim_evidence(claim, tmp_path)
    assert len(violations) == 1
    assert "missing artifact" in violations[0]


def test_no_unit_dir_but_refs_present_is_violation() -> None:
    claim = {"id": "c1", "claim_type": "fact", "evidence_refs": [_ref(quote="some text")]}
    violations = verify_claim_evidence(claim, None)
    assert len(violations) == 1
    assert "no unit_dir" in violations[0]


def test_degenerate_inputs_never_raise(tmp_path: Path) -> None:
    assert verify_claim_evidence({}, None) == []
    assert verify_claim_evidence(None, None) == []
    assert verify_claim_evidence("not a dict", tmp_path) == []
    assert verify_claim_evidence({"evidence_refs": "bad"}, tmp_path)  # non-list refs -> one violation
    assert verify_claim_evidence({"evidence_refs": ["not-a-mapping"]}, tmp_path)[0].endswith("not a mapping")


def test_multiple_refs_accumulate_violations(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    claim = {
        "id": "c1", "claim_type": "fact",
        "evidence_refs": [
            _ref(quote="Ablations remove the widget encoder", locator="page=2"),  # ok
            _ref(quote="fabricated nonsense line"),  # miss
            _ref(quote=""),  # empty
        ],
    }
    assert len(verify_claim_evidence(claim, tmp_path)) == 2


# --------------------------------------------------------------------------- #
# validate_claims — structure + judgement empty-evidence rule                   #
# --------------------------------------------------------------------------- #

def _good_claim(**kw: object) -> dict:
    base = {
        "id": "claim-001",
        "text": "The widget encoder drives accuracy.",
        "claim_type": "inference",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [_ref(quote="x")],
    }
    base.update(kw)
    return base


def test_validate_claims_accepts_well_formed() -> None:
    assert validate_claims([_good_claim()]) == []


def test_judgement_class_empty_evidence_is_rejected() -> None:
    for ct in ("inference", "evaluation", "user_opinion"):
        violations = validate_claims([_good_claim(claim_type=ct, evidence_refs=[])])
        assert any("empty evidence_refs" in v for v in violations), ct


def test_fact_class_empty_evidence_is_allowed() -> None:
    claim = _good_claim(claim_type="fact", confirmation_status="auto_confirmed", evidence_refs=[])
    assert validate_claims([claim]) == []


def test_unverified_empty_evidence_is_structurally_allowed() -> None:
    assert validate_claims([_good_claim(claim_type="unverified", evidence_refs=[])]) == []


@pytest.mark.parametrize("field", ["source_unit_id", "artifact", "locator", "quote"])
@pytest.mark.parametrize("mode", ["missing", "empty"])
def test_validate_claims_requires_every_evidence_ref_field(field: str, mode: str) -> None:
    ref = _ref(quote="grounded quote")
    if mode == "missing":
        ref.pop(field)
    else:
        ref[field] = "   "
    violations = validate_claims([_good_claim(evidence_refs=[ref])])

    assert any(field in violation for violation in violations)


def test_validate_claims_rejects_placeholder_empty_evidence_ref() -> None:
    violations = validate_claims([_good_claim(evidence_refs=[{}])])

    for field in ("source_unit_id", "artifact", "locator", "quote"):
        assert any(f"missing required field '{field}'" in violation for violation in violations)


def test_validate_claims_flags_missing_and_bad_fields() -> None:
    bad = {"claim_type": "banana", "confirmation_status": "maybe"}  # missing id/text/evidence_refs
    violations = validate_claims([bad])
    joined = "\n".join(violations)
    assert "missing required field 'id'" in joined
    assert "missing required field 'text'" in joined
    assert "missing required field 'evidence_refs'" in joined
    assert "invalid claim_type 'banana'" in joined
    assert "invalid confirmation_status 'maybe'" in joined


def test_validate_claims_flags_non_list_evidence_refs() -> None:
    violations = validate_claims([_good_claim(evidence_refs={"not": "a list"})])
    assert any("evidence_refs must be a list" in v for v in violations)


def test_validate_claims_non_list_payload() -> None:
    assert validate_claims("nope") == ["claims payload must be a list"]
    assert validate_claims([42])[0].endswith("not a mapping")


# --------------------------------------------------------------------------- #
# attach_claims / read_claims / as_claim_dict                                   #
# --------------------------------------------------------------------------- #

def test_attach_and_read_claims_roundtrip_with_dataclasses() -> None:
    payload = {"core_content": {"method": "x"}}
    claim = Claim(
        id="claim-001",
        text="A grounded fact.",
        claim_type="fact",
        confirmation_status="auto_confirmed",
        evidence_refs=[EvidenceRef(source_unit_id="p-1", artifact="parse-cache.yaml", locator="page=1", quote="q")],
    )
    out = attach_claims(payload, [claim])
    assert out is payload  # in-place, additive
    assert payload["core_content"] == {"method": "x"}  # untouched
    got = read_claims(payload)
    assert len(got) == 1
    assert got[0]["id"] == "claim-001"
    assert got[0]["evidence_refs"][0]["quote"] == "q"
    # round-tripped claims validate + verify-shape cleanly against a real artifact
    assert validate_claims(got) == []


def test_attach_claims_accepts_plain_dicts_and_empty() -> None:
    payload: dict = {}
    attach_claims(payload, [_good_claim()])
    assert read_claims(payload)[0]["id"] == "claim-001"
    attach_claims(payload, None)
    assert read_claims(payload) == []


def test_read_claims_tolerates_missing_or_bad_payload() -> None:
    assert read_claims({}) == []
    assert read_claims({"claims": "nope"}) == []
    assert read_claims("not a dict") == []
    assert read_claims({"claims": [{"id": "a"}, "junk"]}) == [{"id": "a"}]


def test_as_claim_dict_rejects_bad_types() -> None:
    with pytest.raises(TypeError):
        as_claim_dict(42)
    with pytest.raises(TypeError):
        as_claim_dict({"id": "c", "evidence_refs": [123]})


def test_attach_claims_rejects_bad_payload_and_claims() -> None:
    with pytest.raises(TypeError):
        attach_claims("not a dict", [])
    with pytest.raises(TypeError):
        attach_claims({}, "not a list")


# --------------------------------------------------------------------------- #
# End-to-end: attach -> validate -> verify against a synthetic unit             #
# --------------------------------------------------------------------------- #

def test_end_to_end_grounded_vs_fabricated(tmp_path: Path) -> None:
    _write_parse_cache(tmp_path)
    grounded = _good_claim(
        id="claim-grounded", claim_type="inference",
        evidence_refs=[_ref(quote="Ablations remove the widget encoder", locator="page=2")],
    )
    fabricated = _good_claim(
        id="claim-fab", claim_type="inference",
        evidence_refs=[_ref(quote="the widget encoder is decorative", locator="page=2")],
    )
    payload: dict = {}
    attach_claims(payload, [grounded, fabricated])
    stored = read_claims(payload)
    assert validate_claims(stored) == []  # both structurally valid (judgement w/ evidence)
    assert verify_claim_evidence(stored[0], tmp_path) == []  # grounded
    assert len(verify_claim_evidence(stored[1], tmp_path)) == 1  # fabricated

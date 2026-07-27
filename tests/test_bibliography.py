from __future__ import annotations

import copy
from typing import Any

import pytest

from research.bibliography import (
    BibliographyError,
    bibliography_from_records,
    bibtex_entry_from_record,
    citation_key_for_unit_id,
    deduplicate_bibtex_entries,
    normalize_arxiv_id,
    normalize_doi,
    render_bibtex,
    strong_identity_tokens,
)


def _record(
    unit_id: str = "p-grounded-paper-abc123",
    *,
    doi: str = "10.1234/EXAMPLE.7",
    arxiv_id: str = "2401.01234v3",
    source_url: str = "https://arxiv.org/pdf/2401.01234v3.pdf",
) -> dict[str, Any]:
    return {
        "id": unit_id,
        "kind": "paper",
        "title": "Navigation title",
        "source": {"original_uri": source_url},
        "payload": {
            "basic_info": {
                "title": "A {Grounded} Paper",
                "authors": ["Ada Lovelace", "Grace Hopper"],
                "year": 2026,
                "venue": "Proceedings of Safe Systems",
                "doi": doi,
                "arxiv_id": arxiv_id,
                "source_url": source_url,
                "citation_key": citation_key_for_unit_id(unit_id),
                "bibtex": {
                    "entry_type": "inproceedings",
                    "venue_field": "booktitle",
                    "pages": "1--12",
                    "primary_class": "cs.AI",
                },
            }
        },
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("doi:10.1000/ABC.DEF", "10.1000/abc.def"),
        ("https://DX.doi.org/10.5555/A+B?utm_source=x", "10.5555/a+b"),
        ("10.1234/encoded%2Fpart", "10.1234/encoded/part"),
        ("not-a-doi", ""),
        ("10.12/too-short", ""),
        ("10.1234/good\n@book{evil", ""),
    ],
)
def test_normalize_doi(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("arXiv:2401.01234v7", "2401.01234"),
        ("https://arxiv.org/pdf/2607.12345v2.pdf", "2607.12345"),
        ("https://arxiv.org/abs/hep-th/9901001v3", "hep-th/9901001"),
        ("not-an-arxiv-id", ""),
        ("2401.01234\n@book{evil", ""),
    ],
)
def test_normalize_arxiv_is_versionless(raw: str, expected: str) -> None:
    assert normalize_arxiv_id(raw) == expected


def test_citation_key_depends_only_on_sanitized_unit_id() -> None:
    assert citation_key_for_unit_id("P/Safe Paper") == "cite_p_safe_paper"
    first = bibtex_entry_from_record(_record())
    changed = _record()
    changed["payload"]["basic_info"].update(
        {"title": "A renamed paper", "authors": ["Someone Else"], "year": 1999}
    )
    assert bibtex_entry_from_record(changed)["citation_key"] == first["citation_key"]


def test_entry_uses_only_canonical_and_whitelisted_structured_metadata() -> None:
    entry = bibtex_entry_from_record(_record())

    assert entry == {
        "schema": "bibtex-entry/v1",
        "unit_id": "p-grounded-paper-abc123",
        "citation_key": "cite_p-grounded-paper-abc123",
        "entry_type": "inproceedings",
        "fields": {
            "author": "Ada Lovelace and Grace Hopper",
            "title": "A {Grounded} Paper",
            "year": "2026",
            "booktitle": "Proceedings of Safe Systems",
            "pages": "1--12",
            "doi": "10.1234/example.7",
            "eprint": "2401.01234",
            "archiveprefix": "arXiv",
            "primaryclass": "cs.AI",
            "url": "https://arxiv.org/abs/2401.01234v3",
        },
        "identity": {
            "doi": "10.1234/example.7",
            "arxiv_id": "2401.01234",
            "source_urls": ["https://arxiv.org/abs/2401.01234v3"],
        },
    }
    assert strong_identity_tokens(entry) == (
        "arxiv:2401.01234",
        "doi:10.1234/example.7",
        "url:https://arxiv.org/abs/2401.01234v3",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw", "@book{evil}"),
        ("title", "provider override"),
        ("author", "provider override"),
        ("doi", "10.9999/provider"),
    ],
)
def test_entry_rejects_raw_or_duplicate_provider_bibtex(field: str, value: str) -> None:
    record = _record()
    record["payload"]["basic_info"]["bibtex"][field] = value
    with pytest.raises(BibliographyError, match="non-whitelisted|duplicate"):
        bibtex_entry_from_record(record)


def test_entry_rejects_mismatched_key_and_strong_identity_conflict() -> None:
    mismatched_key = _record()
    mismatched_key["payload"]["basic_info"]["citation_key"] = "cite_someone-else"
    with pytest.raises(BibliographyError, match="does not match"):
        bibtex_entry_from_record(mismatched_key)

    conflicting_doi = _record(source_url="https://doi.org/10.9999/other")
    with pytest.raises(BibliographyError, match="conflicting DOI"):
        bibtex_entry_from_record(conflicting_doi)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("doi", "not-a-doi", "valid DOI"),
        ("arxiv_id", "not-an-arxiv-id", "valid arXiv"),
    ],
)
def test_entry_rejects_malformed_explicit_strong_identities(
    field: str, value: str, message: str
) -> None:
    record = _record()
    record["payload"]["basic_info"][field] = value
    with pytest.raises(BibliographyError, match=message):
        bibtex_entry_from_record(record)


def test_missing_type_uses_neutral_misc_without_fabricating_a_specific_venue_type() -> None:
    record = _record()
    record["payload"]["basic_info"]["bibtex"].pop("entry_type")
    entry = bibtex_entry_from_record(record)
    assert entry["entry_type"] == "misc"
    rendered = render_bibtex([entry])
    assert rendered.startswith("@misc{cite_p-grounded-paper-abc123,")
    assert "journal =" not in rendered and "booktitle =" in rendered


def test_transitive_identity_closure_deduplicates_repeated_same_snapshot() -> None:
    entry = bibtex_entry_from_record(_record())
    left = copy.deepcopy(entry)
    left["identity"]["source_urls"] = []
    left["fields"].pop("url")
    middle = copy.deepcopy(entry)
    right = copy.deepcopy(entry)
    right["identity"]["doi"] = ""
    right["fields"].pop("doi")
    # The component is connected transitively, but differing canonical snapshots
    # are not silently merged because winner choice would otherwise be order-based.
    with pytest.raises(BibliographyError, match="contradictory snapshots"):
        deduplicate_bibtex_entries([right, left, middle])

    assert deduplicate_bibtex_entries([entry, copy.deepcopy(entry)]) == [entry]


def test_transitive_identity_closure_detects_hidden_doi_conflict() -> None:
    first = bibtex_entry_from_record(_record())
    first["identity"]["arxiv_id"] = ""
    first["fields"].pop("eprint")
    first["fields"].pop("archiveprefix")
    first["fields"].pop("primaryclass")
    bridge = copy.deepcopy(first)
    bridge["identity"]["doi"] = ""
    bridge["fields"].pop("doi")
    bridge["identity"]["arxiv_id"] = "2401.01234"
    bridge["fields"]["eprint"] = "2401.01234"
    bridge["fields"]["archiveprefix"] = "arXiv"
    conflicting = copy.deepcopy(first)
    conflicting["identity"]["doi"] = "10.9999/conflict"
    conflicting["fields"]["doi"] = "10.9999/conflict"
    conflicting["identity"]["arxiv_id"] = "2401.01234"
    conflicting["fields"]["eprint"] = "2401.01234"
    conflicting["fields"]["archiveprefix"] = "arXiv"
    conflicting["identity"]["source_urls"] = []
    conflicting["fields"].pop("url")

    with pytest.raises(BibliographyError, match="conflicting DOIs"):
        deduplicate_bibtex_entries([first, bridge, conflicting])


def test_shared_identity_with_different_unit_keys_fails_closed() -> None:
    first = bibtex_entry_from_record(_record("p-first-111111"))
    second_record = _record("p-second-222222")
    second = bibtex_entry_from_record(second_record)
    with pytest.raises(BibliographyError, match="conflicting citation keys"):
        deduplicate_bibtex_entries([second, first])


def test_no_strong_identity_falls_back_to_unit_id() -> None:
    record = _record(doi="", arxiv_id="", source_url="")
    entry = bibtex_entry_from_record(record)
    assert strong_identity_tokens(entry) == ()
    assert deduplicate_bibtex_entries([entry, copy.deepcopy(entry)]) == [entry]


def test_global_sanitized_key_collision_fails_even_without_shared_identity() -> None:
    first = bibtex_entry_from_record(_record("p/collision", doi="", arxiv_id="", source_url=""))
    second = bibtex_entry_from_record(_record("p_collision", doi="", arxiv_id="", source_url=""))
    assert first["citation_key"] == second["citation_key"]
    with pytest.raises(BibliographyError, match="collision"):
        deduplicate_bibtex_entries([first, second])


def test_render_is_stably_sorted_fixed_order_and_structurally_escaped() -> None:
    first_record = _record("p-zeta-999999", doi="10.1234/zeta", arxiv_id="", source_url="")
    first_record["payload"]["basic_info"]["title"] = "Attack } # @book{evil & 100%"
    second_record = _record("p-alpha-111111", doi="10.1234/alpha", arxiv_id="", source_url="")
    first = bibtex_entry_from_record(first_record)
    second = bibtex_entry_from_record(second_record)

    forward = render_bibtex([first, second])
    backward = render_bibtex([second, first])

    assert forward == backward
    assert forward.index("@inproceedings{cite_p-alpha-111111") < forward.index(
        "@inproceedings{cite_p-zeta-999999"
    )
    assert (
        "title = {Attack {\\char125} \\# @book{\\char123}evil \\& 100\\%},"
        in forward
    )
    assert forward.count("@inproceedings{") == 2
    assert forward.count("\n@inproceedings{") == 1
    assert "\n@book{" not in forward
    assert forward.endswith("\n")
    author_at = forward.index("  author =")
    title_at = forward.index("  title =")
    booktitle_at = forward.index("  booktitle =")
    year_at = forward.index("  year =")
    assert author_at < title_at < booktitle_at < year_at


def test_render_rejects_newline_macro_and_unknown_field_injection() -> None:
    entry = bibtex_entry_from_record(_record())
    newline = copy.deepcopy(entry)
    newline["fields"]["note"] = "safe},\n@book{evil"
    with pytest.raises(BibliographyError, match="one line"):
        render_bibtex([newline])

    raw_field = copy.deepcopy(entry)
    raw_field["fields"]["raw"] = "@book{evil}"
    with pytest.raises(BibliographyError, match="unknown fields"):
        render_bibtex([raw_field])

    raw_top_level = copy.deepcopy(entry)
    raw_top_level["raw_bibtex"] = "@book{evil}"
    with pytest.raises(BibliographyError, match="unknown keys"):
        render_bibtex([raw_top_level])


def test_convenience_pipeline_is_byte_stable() -> None:
    records = [
        _record("p-zeta-999999", doi="10.1234/zeta", arxiv_id="", source_url=""),
        _record("p-alpha-111111", doi="10.1234/alpha", arxiv_id="", source_url=""),
    ]
    entries, rendered = bibliography_from_records(records)
    reverse_entries, reverse_rendered = bibliography_from_records(list(reversed(records)))
    assert entries == reverse_entries
    assert rendered.encode("utf-8") == reverse_rendered.encode("utf-8")

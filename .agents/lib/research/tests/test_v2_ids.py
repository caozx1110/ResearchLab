from __future__ import annotations

from research.v2 import canonical_unit_id, canonical_unit_id_with_hash, compact_unit_slug, is_canonical_unit_id


def test_canonical_unit_id_is_deterministic_and_canonical() -> None:
    first = canonical_unit_id("paper", title="π0: A Vision-Language-Action Flow Model")
    second = canonical_unit_id("paper", title="π0: A Vision-Language-Action Flow Model")

    assert first == second
    assert first.startswith("p-pi-0-vision-")
    assert is_canonical_unit_id("paper", first)


def test_canonical_unit_id_uses_at_least_six_hash_chars() -> None:
    unit_id = canonical_unit_id("repo", title="OpenVLA", hash_size=2)

    assert unit_id.startswith("r-openvla-")
    assert len(unit_id.rsplit("-", 1)[-1]) == 6
    assert is_canonical_unit_id("repo", unit_id)


def test_canonical_unit_id_with_short_hash_falls_back_to_title_hash() -> None:
    fallback = canonical_unit_id("blog", title="Fallback Title", source="https://example.com/a")
    generated = canonical_unit_id_with_hash("blog", title="Fallback Title", source="https://example.com/a", hash_value="abc")

    assert generated == fallback


def test_compact_unit_slug_handles_stopwords_camelcase_and_greek_letters() -> None:
    assert compact_unit_slug("The AnatomyOf π0 Robotics System") == "anatomy-pi-0"
    assert compact_unit_slug("A Study of Methods and Systems") == "study-methods"


def test_compact_unit_slug_truncates_overlong_first_word() -> None:
    assert compact_unit_slug("Supercalifragilisticexpialidocious", max_chars=10) == "supercalif"

from __future__ import annotations

from pathlib import Path

import pytest

from research.common import canonicalize_url, dump_yaml, load_yaml, normalize_remote_url, parse_arxiv_id, yaml_duplicate_key_issues


def test_yaml_round_trip_uses_pyyaml_path(tmp_path: Path) -> None:
    payload = {
        "id": "doc",
        "title": "中文标题",
        "enabled": True,
        "items": [{"name": "alpha", "count": 2}],
    }
    path = tmp_path / "record.yaml"
    path.write_text(dump_yaml(payload), encoding="utf-8")

    assert load_yaml(path) == payload


def test_yaml_duplicate_key_issues_reports_nested_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("root:\n  item: 1\n  item: 2\n", encoding="utf-8")

    issues = yaml_duplicate_key_issues(path)

    assert len(issues) == 1
    assert "duplicate key `root.item`" in issues[0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://arxiv.org/pdf/2506.01844v2.pdf?download=1", "https://arxiv.org/abs/2506.01844v2"),
        ("https://openreview.net/forum?id=abc123&note=drop", "https://openreview.net/forum?id=abc123"),
        ("https://doi.org/10.1234/Example?utm_source=x", "https://doi.org/10.1234/Example"),
    ],
)
def test_canonicalize_url_special_cases(raw: str, expected: str) -> None:
    assert canonicalize_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("git@github.com:openvla/openvla.git", "https://github.com/openvla/openvla"),
        ("ssh://git@github.com/openvla/openvla.git", "https://github.com/openvla/openvla"),
        ("git://github.com/openvla/openvla.git", "https://github.com/openvla/openvla"),
    ],
)
def test_normalize_remote_url_github_forms(raw: str, expected: str) -> None:
    assert normalize_remote_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://arxiv.org/abs/2506.01844", "2506.01844"),
        ("https://arxiv.org/pdf/2506.01844v2.pdf", "2506.01844v2"),
        ("lit-arxiv-2506.01844v3.pdf", "2506.01844v3"),
        ("no-arxiv-here", ""),
    ],
)
def test_parse_arxiv_id(raw: str, expected: str) -> None:
    assert parse_arxiv_id(raw) == expected

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.openalex import OpenAlexClient, OpenAlexError, WORK_SELECT_FIELDS
from research.sources import stage_search_results


ROOT = Path(__file__).resolve().parents[4]
SCOUT_SCRIPT = ROOT / ".agents" / "skills" / "literature-scout" / "scripts" / "scout.py"


def _scout_module():
    spec = importlib.util.spec_from_file_location("literature_scout_script", SCOUT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _work(*, work_id: str = "https://openalex.org/W123", retracted: bool = False) -> dict:
    return {
        "id": work_id,
        "doi": "https://doi.org/10.1234/EXAMPLE",
        "display_name": "A Grounded Robotics Paper",
        "publication_date": "2026-01-02",
        "publication_year": 2026,
        "type": "article",
        "language": "en",
        "cited_by_count": 17,
        "is_retracted": retracted,
        "primary_location": {"landing_page_url": "https://publisher.example/paper"},
        "best_oa_location": {
            "landing_page_url": "https://repository.example/paper",
            "pdf_url": "https://repository.example/paper.pdf",
        },
    }


def _transport(payload: dict, *, status: int = 200, inspect=None):
    def transport(url: str, timeout: float) -> tuple[int, bytes]:
        if inspect:
            inspect(url, timeout)
        return status, json.dumps(payload).encode("utf-8")

    return transport


def test_openalex_search_is_bounded_selected_deduped_and_factual(monkeypatch) -> None:
    secret = "oa-secret-value"
    monkeypatch.setenv("OPENALEX_API_KEY", secret)

    def inspect(url: str, timeout: float) -> None:
        query = parse_qs(urlparse(url).query)
        assert query["per-page"] == ["25"]
        assert query["select"] == [",".join(WORK_SELECT_FIELDS)]
        assert query["api_key"] == [secret]
        assert "cursor" not in query
        assert "mailto" not in query
        assert timeout > 0

    client = OpenAlexClient(
        transport=_transport(
            {
                "results": [
                    _work(),
                    _work(),
                    _work(work_id="https://openalex.org/W124"),
                    _work(work_id="https://openalex.org/W999", retracted=True),
                ]
            },
            inspect=inspect,
        )
    )

    candidates = client.search_works("robot learning")

    assert len(candidates) == 1
    assert candidates[0]["candidate_id"] == "openalex-w123"
    facts = candidates[0]["provenance"]["openalex"]
    assert facts["doi"] == "https://doi.org/10.1234/example"
    assert facts["cited_by_count"] == 17
    assert facts["open_access_pdf_url"] == "https://repository.example/paper.pdf"
    assert secret not in json.dumps(candidates)


def test_missing_key_and_transport_exception_are_redacted(monkeypatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    called = False

    def should_not_call(url: str, timeout: float) -> tuple[int, bytes]:
        nonlocal called
        called = True
        return 200, b"{}"

    with pytest.raises(OpenAlexError, match="not configured"):
        OpenAlexClient(transport=should_not_call).search_works("robotics")
    assert called is False

    secret = "never-show-this-key"
    monkeypatch.setenv("OPENALEX_API_KEY", secret)

    def failing_transport(url: str, timeout: float) -> tuple[int, bytes]:
        raise RuntimeError(f"network failure for {url}")

    with pytest.raises(OpenAlexError) as caught:
        OpenAlexClient(transport=failing_transport).search_works("robotics")
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None

    with pytest.raises(OpenAlexError, match="between 1 and 100"):
        OpenAlexClient(transport=should_not_call).search_works("robotics", per_page=101)


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (429, {"error": "key=secret"}, "rate limit"),
        (200, {"not_results": []}, "invalid works response"),
    ],
)
def test_rate_limit_or_malformed_response_writes_no_stage(tmp_path: Path, monkeypatch, status, body, message) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "secret")
    scout = _scout_module()
    client = OpenAlexClient(transport=_transport(body, status=status))

    with pytest.raises(OpenAlexError, match=message):
        scout.pull_and_stage(tmp_path, query="robotics", client=client)

    assert not (tmp_path / "kb" / "synthesis" / "source-search").exists()


def test_rerun_preserves_manual_fields_and_dedupes_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "secret")
    scout = _scout_module()
    client = OpenAlexClient(transport=_transport({"results": [_work()]}))
    stage_path, _ = scout.pull_and_stage(tmp_path, query="robot learning", client=client)
    stage = load_yaml(stage_path)
    stage["candidates"][0]["status"] = "reviewed"
    stage["candidates"][0]["note"] = "keep this manual assessment"
    write_yaml_if_changed(stage_path, stage)

    scout.pull_and_stage(tmp_path, query="robot learning", client=client)
    rerun = load_yaml(stage_path)

    assert len(rerun["candidates"]) == 1
    assert rerun["candidates"][0]["status"] == "reviewed"
    assert rerun["candidates"][0]["note"] == "keep this manual assessment"
    assert rerun["candidates"][0]["provenance"]["openalex"]["work_id"] == "https://openalex.org/W123"


def test_source_stage_drops_unapproved_openalex_provenance(tmp_path: Path) -> None:
    stage_path = stage_search_results(
        tmp_path,
        kind="paper",
        query="safe provenance",
        candidates=[
            {
                "candidate_id": "openalex-w1",
                "title": "Safe",
                "url": "https://openalex.org/W1",
                "provenance": {
                    "openalex": {
                        "work_id": "https://openalex.org/W1",
                        "publication_year": 2026,
                        "api_key": "must-not-persist",
                        "raw_response": {"secret": True},
                    }
                },
            }
        ],
    )

    text = stage_path.read_text(encoding="utf-8")
    assert "must-not-persist" not in text
    assert "raw_response" not in text
    assert load_yaml(stage_path)["candidates"][0]["provenance"]["openalex"] == {
        "publication_year": 2026,
        "work_id": "https://openalex.org/W1",
    }


def test_malicious_openalex_values_and_unsafe_urls_never_reach_stage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "secret")
    scout = _scout_module()
    malicious = _work()
    malicious.update(
        {
            "publication_year": {"raw-secret": True},
            "cited_by_count": ["raw-secret"],
            "type": {"raw-secret": "type"},
            "language": ["raw-secret"],
            "primary_location": {"landing_page_url": "javascript:alert('raw-secret')"},
            "best_oa_location": {
                "landing_page_url": "file:///private/raw-secret",
                "pdf_url": "javascript:raw-secret",
            },
            "raw_response": {"token": "raw-secret"},
        }
    )
    unsafe_only = {
        "id": "javascript:raw-secret",
        "doi": "not-a-doi",
        "display_name": "Unsafe",
        "primary_location": {"landing_page_url": "file:///private/raw-secret"},
    }
    client = OpenAlexClient(transport=_transport({"results": [malicious, unsafe_only]}))

    stage_path, candidates = scout.pull_and_stage(tmp_path, query="adversarial", client=client)

    assert len(candidates) == 1
    persisted = stage_path.read_text(encoding="utf-8")
    assert "raw-secret" not in persisted
    assert "javascript:" not in persisted
    assert "file:///" not in persisted
    facts = load_yaml(stage_path)["candidates"][0]["provenance"]["openalex"]
    assert "publication_year" not in facts
    assert "cited_by_count" not in facts
    assert "type" not in facts
    assert "language" not in facts
    assert "open_access_landing_url" not in facts
    assert "open_access_pdf_url" not in facts


def test_public_success_message_is_natural_language_only(tmp_path: Path, monkeypatch, capsys) -> None:
    scout = _scout_module()
    fake = OpenAlexClient(transport=_transport({"results": [_work()]}))
    monkeypatch.setenv("OPENALEX_API_KEY", "secret")
    monkeypatch.setattr(scout, "OpenAlexClient", lambda: fake)
    monkeypatch.setattr(sys, "argv", [str(SCOUT_SCRIPT), "--root", str(tmp_path), "--query", "robotics"])

    assert scout.main() == 0

    output = capsys.readouterr().out
    assert output == "找到 1 个候选，已暂存；下一步将由 Agent 去重并阅读。\n"
    assert "--" not in output
    assert "OPENALEX" not in output
    assert str(tmp_path) not in output

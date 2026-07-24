from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import research.sources as sources
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


@pytest.mark.parametrize(
    ("kind", "query"),
    [("paper", "different query"), ("blog", "robot learning")],
)
def test_explicit_stage_id_rejects_identity_mismatch_without_mutation(
    tmp_path: Path,
    kind: str,
    query: str,
) -> None:
    stage_path = stage_search_results(
        tmp_path,
        kind="paper",
        query="robot learning",
        stage_id="shared-stage",
        candidates=[{"candidate_id": "first", "title": "First", "url": "https://example.test/first"}],
    )
    stage_before = stage_path.read_bytes()
    journal_root = tmp_path / "kb/.journal"
    journal_before = {path.name: path.read_bytes() for path in journal_root.glob("*.yaml")}

    with pytest.raises(SystemExit, match="identity does not match"):
        stage_search_results(
            tmp_path,
            kind=kind,
            query=query,
            stage_id="shared-stage",
            candidates=[{"candidate_id": "second", "title": "Second", "url": "https://example.test/second"}],
        )

    assert stage_path.read_bytes() == stage_before
    assert {path.name: path.read_bytes() for path in journal_root.glob("*.yaml")} == journal_before


def test_stage_identity_mismatch_precedes_workspace_seed_repairs(tmp_path: Path) -> None:
    stage_path = stage_search_results(
        tmp_path,
        kind="paper",
        query="robot learning",
        stage_id="shared-stage",
        candidates=[{"candidate_id": "first", "title": "First", "url": "https://example.test/first"}],
    )
    current_state = tmp_path / "kb/user/current-state.md"
    current_state.unlink()
    stage_before = stage_path.read_bytes()
    journal_before = {path.name: path.read_bytes() for path in (tmp_path / "kb/.journal").glob("*.yaml")}

    with pytest.raises(SystemExit, match="identity does not match"):
        stage_search_results(
            tmp_path,
            kind="paper",
            query="different query",
            stage_id="shared-stage",
            candidates=[{"candidate_id": "second", "title": "Second", "url": "https://example.test/second"}],
        )

    assert not current_state.exists()
    assert stage_path.read_bytes() == stage_before
    assert {path.name: path.read_bytes() for path in (tmp_path / "kb/.journal").glob("*.yaml")} == journal_before


def test_stage_identity_race_fails_while_locked_before_journal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    validate = sources._validate_search_stage_identity

    def fail_second_validation(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SystemExit("Search stage identity changed before the mutation lock.")
        validate(*args, **kwargs)

    monkeypatch.setattr(sources, "_validate_search_stage_identity", fail_second_validation)
    with pytest.raises(SystemExit, match="changed before the mutation lock"):
        sources.stage_search_results(
            tmp_path,
            kind="paper",
            query="robot learning",
            stage_id="shared-stage",
            candidates=[{"candidate_id": "first", "title": "First", "url": "https://example.test/first"}],
        )

    assert not (tmp_path / "kb/library/search/results/shared-stage.yaml").exists()
    assert not list((tmp_path / "kb/.journal").glob("*.yaml"))


def test_same_url_candidates_fold_within_one_batch(tmp_path: Path) -> None:
    path = stage_search_results(
        tmp_path,
        kind="paper",
        query="shared landing",
        candidates=[
            {"candidate_id": "first", "title": "Old title", "url": "https://example.test/shared"},
            {"candidate_id": "second", "title": "Corrected title", "url": "https://example.test/shared"},
        ],
    )

    candidates = load_yaml(path)["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["candidate_id"] == "first"
    assert candidates[0]["title"] == "Corrected title"


def test_persisted_candidates_dedupe_by_doi_across_different_openalex_work_ids(tmp_path: Path) -> None:
    first = {
        "candidate_id": "openalex-w1",
        "title": "First title",
        "url": "https://openalex.org/W1",
        "provenance": {
            "openalex": {
                "work_id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1234/shared",
                "cited_by_count": 3,
            }
        },
    }
    stage_path = stage_search_results(tmp_path, kind="paper", query="shared doi", candidates=[first])
    stage = load_yaml(stage_path)
    stage["candidates"][0]["status"] = "reviewed"
    stage["candidates"][0]["note"] = "manual assessment"
    write_yaml_if_changed(stage_path, stage)

    second = {
        "candidate_id": "openalex-w2",
        "title": "Second title",
        "url": "https://openalex.org/W2",
        "provenance": {
            "openalex": {
                "work_id": "https://openalex.org/W2",
                "doi": "doi:10.1234/SHARED",
                "cited_by_count": 9,
            }
        },
    }
    stage_search_results(tmp_path, kind="paper", query="shared doi", candidates=[second])
    merged = load_yaml(stage_path)["candidates"]

    assert len(merged) == 1
    assert merged[0]["status"] == "reviewed"
    assert merged[0]["note"] == "manual assessment"
    assert merged[0]["title"] == "Second title"
    assert merged[0]["url"] == "https://openalex.org/W2"
    assert merged[0]["provenance"]["openalex"]["work_id"] == "https://openalex.org/W1"
    assert merged[0]["provenance"]["openalex"]["doi"] == "https://doi.org/10.1234/shared"
    assert merged[0]["provenance"]["openalex"]["cited_by_count"] == 9


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

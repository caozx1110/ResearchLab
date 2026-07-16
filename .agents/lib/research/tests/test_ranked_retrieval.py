from __future__ import annotations

from pathlib import Path

from research.common import write_text_if_changed, write_yaml_if_changed
from research.core import ensure_workspace, record_path, search_records, unit_root
from research.retrieval import tokenize_query


def _write_record(root: Path, record: dict) -> None:
    write_yaml_if_changed(record_path(root, record["kind"], record["id"]), record)


def _record(unit_id: str, title: str, *, summary: str = "", payload: dict | None = None) -> dict:
    return {
        "id": unit_id,
        "kind": "paper",
        "title": title,
        "status": "active",
        "maturity": "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "summary": summary,
        "tags": [],
        "topics": [],
        "candidate_pools": [],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": payload or {},
    }


def test_search_records_ranks_title_match_above_markdown_match(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-title-123456", "Dexterous Recovery", summary="short"))
    _write_record(tmp_path, _record("p-note-123456", "Other Paper", summary="short"))
    note_path = unit_root(tmp_path, "paper", "p-note-123456") / "paper-note.md"
    write_text_if_changed(note_path, "This note mentions dexterous recovery in a detailed paragraph.\n")

    hits = search_records(tmp_path, "dexterous recovery")

    assert [item["id"] for item in hits] == ["p-title-123456", "p-note-123456"]
    assert hits[0]["_search_score"] > hits[1]["_search_score"]
    assert any(reason.startswith("title:") for reason in hits[0]["_search_reasons"])
    assert any(reason.startswith("markdown:") for reason in hits[1]["_search_reasons"])


def test_search_records_finds_payload_leaf_text(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record(
            "p-payload-123456",
            "Payload Paper",
            payload={"quick_screen": {"takeaways": ["Contains latent interface evidence."]}},
        ),
    )

    hits = search_records(tmp_path, "latent interface")

    assert [item["id"] for item in hits] == ["p-payload-123456"]
    assert any(reason.startswith("payload:") for reason in hits[0]["_search_reasons"])


def test_cjk_search_filters_and_scores_matching_records(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-cjk-123456", "灵巧手恢复策略"))
    _write_record(tmp_path, _record("p-other-123456", "视觉语言模型"))

    hits = search_records(tmp_path, "灵巧手")

    assert [item["id"] for item in hits] == ["p-cjk-123456"]
    assert hits[0]["_search_score"] > 0


def test_mixed_cjk_ascii_query_tokenizes_and_searches(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-mixed-123456", "灵巧手 recovery"))
    _write_record(tmp_path, _record("p-other-123456", "视觉语言模型"))

    assert tokenize_query("灵巧手recovery") == ["灵巧手", "recovery"]

    hits = search_records(tmp_path, "灵巧手 recovery")

    assert [item["id"] for item in hits] == ["p-mixed-123456"]
    assert hits[0]["_search_score"] > 0


def test_empty_search_keeps_filter_only_behavior_for_review_queue(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-filter-123456", "Filter Paper"))

    hits = search_records(tmp_path, "", confirmation_status="auto_confirmed")

    assert tokenize_query("  ") == []
    assert [item["id"] for item in hits] == ["p-filter-123456"]
    assert "_search_score" not in hits[0]

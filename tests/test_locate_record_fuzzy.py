from __future__ import annotations

from repo_paths import initialize_test_workspace

import os
import time
from pathlib import Path

import pytest

from research.common import write_yaml_if_changed
from research.core import ensure_workspace, lint_records, locate_record, record_path


def _record(
    unit_id: str,
    title: str,
    *,
    kind: str = "paper",
    legacy_ids: list[str] | None = None,
    updated_at: str = "2026-01-01T00:00:00+00:00",
) -> dict:
    return {
        "id": unit_id,
        "kind": kind,
        "title": title,
        "status": "active",
        "maturity": "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "summary": f"{title} summary",
        "tags": [],
        "topics": [],
        "candidate_pools": [],
        "legacy_ids": legacy_ids or [],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": {"state": {}},
        "updated_at": updated_at,
    }


def _write_record(root: Path, record: dict) -> Path:
    path = record_path(root, record["kind"], record["id"])
    write_yaml_if_changed(path, record)
    return path


def test_locate_record_keeps_exact_id_and_legacy_id_resolution(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _record("p-openvla-abcdef12", "OpenVLA", legacy_ids=["old-openvla-id"]))

    exact, exact_path = locate_record(tmp_path, "p-openvla-abcdef12")
    legacy, legacy_path = locate_record(tmp_path, "old-openvla-id")

    assert exact["id"] == "p-openvla-abcdef12"
    assert legacy["id"] == "p-openvla-abcdef12"
    assert exact_path == legacy_path


def test_locate_record_resolves_unique_id_prefix(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _record("p-openvla-abcdef12", "OpenVLA"))

    record, _ = locate_record(tmp_path, "p-openvla")

    assert record["id"] == "p-openvla-abcdef12"


def test_locate_record_resolves_case_insensitive_id_prefix(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _record("p-openvla-abcdef12", "OpenVLA"))

    record, _ = locate_record(tmp_path, "P-OPENVLA")

    assert record["id"] == "p-openvla-abcdef12"


def test_locate_record_resolves_unique_hash_suffix_prefix(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _record("p-openvla-abcdef12", "OpenVLA"))

    record, _ = locate_record(tmp_path, "abcd")

    assert record["id"] == "p-openvla-abcdef12"


def test_locate_record_resolves_unique_case_insensitive_title_substring(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _record("p-openvla-abcdef12", "OpenVLA: An Open Vision-Language-Action Model"))

    record, _ = locate_record(tmp_path, "vision-language-action")

    assert record["id"] == "p-openvla-abcdef12"


def test_lint_reports_partial_wikilink_target_as_broken(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    record_path_written = _write_record(
        tmp_path,
        _record("p-openvla-abcdef12", "OpenVLA: An Open Vision-Language-Action Model"),
    )
    (record_path_written.parent / "note.md").write_text("See [[vision-language-action]] for details.\n", encoding="utf-8")

    status, issues = lint_records(tmp_path)

    assert status == "FAIL"
    assert any("broken wikilink `vision-language-action`" in issue for issue in issues)


def test_locate_record_last_is_kind_scoped_most_recently_modified_record(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    older = _write_record(tmp_path, _record("p-older-abcdef12", "Older"))
    time.sleep(0.01)
    newer = _write_record(tmp_path, _record("p-newer-fedcba98", "Newer"))
    time.sleep(0.01)
    repo = _write_record(tmp_path, _record("r-repo-11112222", "Repo", kind="repo"))
    now = time.time()
    os.utime(older, (now - 30, now - 30))
    os.utime(newer, (now - 20, now - 20))
    os.utime(repo, (now - 10, now - 10))

    record, _ = locate_record(tmp_path, "last", kind="paper")

    assert record["id"] == "p-newer-fedcba98"


def test_locate_record_last_reserved_word_precedes_title_matching(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    titled_last = _write_record(tmp_path, _record("p-last-title-abcdef12", "Last Robot Policy"))
    newer = _write_record(tmp_path, _record("p-newer-fedcba98", "Newer"))
    now = time.time()
    os.utime(titled_last, (now - 30, now - 30))
    os.utime(newer, (now - 10, now - 10))

    record, _ = locate_record(tmp_path, "last", kind="paper")

    assert record["id"] == "p-newer-fedcba98"


def test_locate_record_ambiguity_lists_matching_candidate_ids(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _record("p-openvla-abcdef12", "OpenVLA Alpha"))
    _write_record(tmp_path, _record("p-openvla-fedcba98", "OpenVLA Beta"))

    with pytest.raises(SystemExit) as exc_info:
        locate_record(tmp_path, "p-openvla")

    message = str(exc_info.value)
    assert "Ambiguous record reference: p-openvla" in message
    assert "p-openvla-abcdef12" in message
    assert "p-openvla-fedcba98" in message

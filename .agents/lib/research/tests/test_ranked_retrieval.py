from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from research.common import write_text_if_changed, write_yaml_if_changed
from research.core import build_index, ensure_workspace, passage_search_cache_path, record_path, search_passages, search_records, unit_root
from research.retrieval import PASSAGE_MAX_CHARS, PASSAGE_OVERLAP_CHARS, tokenize_query
import research.index as index_mod


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

    passage_payload = search_passages(tmp_path, "latent interface")
    assert passage_payload["results"][0]["locator"].endswith("record.yaml#summary")


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


def _tree_bytes(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(name for name in dirnames if not (current_path / name).is_symlink())
        for name in sorted(filenames):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                snapshot[relative] = f"symlink:{os.readlink(path)}"
            else:
                snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def test_passage_search_builds_fts_cache_with_heading_and_line_locator(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record("p-passages-123456", "Dexterous Paper", summary="A recovery overview."),
    )
    note = unit_root(tmp_path, "paper", "p-passages-123456") / "paper-note.md"
    write_text_if_changed(
        note,
        "# Motivation\n\nBackground paragraph.\n\n## Recovery Policy\n\n"
        "The controller uses tactile residual recovery after a failed grasp.\n",
    )

    build_index(tmp_path)
    payload = search_passages(tmp_path, "tactile residual")

    assert payload["health"] == "current"
    assert payload["results"][0]["unit_id"] == "p-passages-123456"
    assert payload["results"][0]["heading"] == "Recovery Policy"
    assert payload["results"][0]["artifact"] == "kb/units/papers/p-passages-123456/paper-note.md"
    assert payload["results"][0]["locator"].startswith(
        "kb/units/papers/p-passages-123456/paper-note.md#L"
    )
    assert "tactile residual recovery" in payload["results"][0]["excerpt"]
    assert not Path(payload["results"][0]["artifact"]).is_absolute()
    assert "_search_score" in payload["results"][0]

    cache = passage_search_cache_path(tmp_path)
    assert cache.is_file() and not cache.is_symlink()
    connection = sqlite3.connect(cache)
    try:
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'passages'"
        ).fetchone()[0]
        sources = connection.execute("SELECT artifact, digest FROM sources ORDER BY artifact").fetchall()
    finally:
        connection.close()
    assert "fts5" in schema.lower() and "unicode61" in schema.lower()
    assert "content=" not in schema.lower()
    assert [item[0] for item in sources] == [
        "kb/units/papers/p-passages-123456/paper-note.md",
        "kb/units/papers/p-passages-123456/record.yaml",
    ]
    assert all(len(item[1]) == 64 for item in sources)


def test_title_and_summary_are_indexed_as_first_class_passages(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record(
            "p-metadata-123456",
            "Rare Quaternion Controller",
            summary="Calibrated fingertip alignment without demonstrations.",
        ),
    )
    build_index(tmp_path)

    title = search_passages(tmp_path, "Rare Quaternion")
    summary = search_passages(tmp_path, "fingertip alignment")

    assert title["results"][0]["locator"].endswith("record.yaml#title")
    assert summary["results"][0]["locator"].endswith("record.yaml#summary")


def test_title_match_does_not_promote_unrelated_body_passages(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record("p-title-scope-123456", "Rare Query Planning", summary="A database article."),
    )
    note = unit_root(tmp_path, "paper", "p-title-scope-123456") / "paper-note.md"
    write_text_if_changed(
        note,
        "# Introduction\n\nTable of contents.\n\n## Searching\n\nA sequential scan description.\n",
    )

    missing = search_passages(tmp_path, "Rare Query Planning")
    assert missing["health"] == "missing"
    assert [item["locator"] for item in missing["results"]] == [
        "kb/units/papers/p-title-scope-123456/record.yaml#title"
    ]

    build_index(tmp_path)
    current = search_passages(tmp_path, "Rare Query Planning")
    assert current["health"] == "current"
    assert [item["locator"] for item in current["results"]] == [
        "kb/units/papers/p-title-scope-123456/record.yaml#title"
    ]


def test_missing_stale_and_corrupt_cache_fall_back_without_writes(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-fallback-123456", "Fallback Paper"))
    note = unit_root(tmp_path, "paper", "p-fallback-123456") / "paper-note.md"
    write_text_if_changed(note, "# Finding\n\nA deterministic impedance controller stabilizes contact.\n")

    before_missing = _tree_bytes(tmp_path)
    missing = search_passages(tmp_path, "impedance controller")
    assert missing["health"] == "missing"
    assert missing["results"] and _tree_bytes(tmp_path) == before_missing

    build_index(tmp_path)
    write_text_if_changed(note, "# Finding\n\nA revised impedance controller stabilizes contact robustly.\n")
    before_stale = _tree_bytes(tmp_path)
    stale = search_passages(tmp_path, "revised impedance")
    assert stale["health"] == "stale"
    assert "revised impedance" in stale["results"][0]["excerpt"]
    assert _tree_bytes(tmp_path) == before_stale

    cache = passage_search_cache_path(tmp_path)
    cache.write_bytes(b"not a sqlite database")
    before_corrupt = _tree_bytes(tmp_path)
    corrupt = search_passages(tmp_path, "revised impedance")
    assert corrupt["health"] == "corrupt"
    assert corrupt["results"] and _tree_bytes(tmp_path) == before_corrupt


def test_valid_sqlite_with_tampered_passage_rows_is_corrupt_and_cannot_hide_results(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record("p-row-tamper-123456", "Tamper Paper", summary="canonical force-feedback result"),
    )
    build_index(tmp_path)
    cache = passage_search_cache_path(tmp_path)
    connection = sqlite3.connect(cache)
    try:
        connection.execute("UPDATE passages SET body = 'scrubbed cache row'")
        connection.commit()
    finally:
        connection.close()

    payload = search_passages(tmp_path, "force-feedback")

    assert payload["health"] == "corrupt"
    assert payload["results"][0]["unit_id"] == "p-row-tamper-123456"
    assert "force-feedback" in payload["results"][0]["excerpt"]


def test_valid_sqlite_with_tampered_source_manifest_is_corrupt(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record("p-source-table-tamper-123456", "Source table", summary="canonical actuator result"),
    )
    build_index(tmp_path)
    cache = passage_search_cache_path(tmp_path)
    connection = sqlite3.connect(cache)
    try:
        connection.execute("UPDATE sources SET digest = ?", ("0" * 64,))
        connection.commit()
    finally:
        connection.close()

    payload = search_passages(tmp_path, "actuator result")

    assert payload["health"] == "corrupt"
    assert payload["results"][0]["unit_id"] == "p-source-table-tamper-123456"


@pytest.mark.parametrize(
    ("column", "value"),
    [("digest", "not-a-sha256"), ("artifact", "../outside.yaml")],
)
def test_coherently_tampered_source_manifest_schema_is_corrupt(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-source-schema-123456", "Source schema", summary="manifest fallback"))
    build_index(tmp_path)
    cache = passage_search_cache_path(tmp_path)
    connection = sqlite3.connect(cache)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(f"UPDATE sources SET {column} = ?", (value,))
        manifest = [
            {"artifact": row["artifact"], "digest": row["digest"]}
            for row in connection.execute("SELECT artifact, digest FROM sources ORDER BY artifact")
        ]
        from research.index import _passage_corpus_digest

        connection.execute("UPDATE metadata SET corpus_digest = ?", (_passage_corpus_digest(manifest),))
        connection.commit()
    finally:
        connection.close()

    payload = search_passages(tmp_path, "manifest fallback")
    assert payload["health"] == "corrupt"
    assert payload["results"][0]["unit_id"] == "p-source-schema-123456"


def test_coherently_tampered_passage_rows_are_corrupt_not_stale(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-coherent-tamper-123456", "Coherent tamper", summary="canonical needle"))
    build_index(tmp_path)
    cache = passage_search_cache_path(tmp_path)
    connection = sqlite3.connect(cache)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("UPDATE passages SET body = 'tampered cached body' WHERE passage_id = (SELECT passage_id FROM passages LIMIT 1)")
        rows = [
            {
                "passage_id": row["passage_id"],
                "unit_id": row["unit_id"],
                "kind": row["kind"],
                "title": row["title"],
                "summary": row["summary"],
                "heading": row["heading"],
                "text": row["body"],
                "artifact": row["artifact"],
                "locator": row["locator"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "source_digest": row["source_digest"],
            }
            for row in connection.execute("SELECT * FROM passages ORDER BY passage_id")
        ]
        from research.index import _passages_digest

        connection.execute("UPDATE metadata SET passages_digest = ?", (_passages_digest(rows),))
        connection.commit()
    finally:
        connection.close()

    payload = search_passages(tmp_path, "canonical needle")
    assert payload["health"] == "corrupt"
    assert payload["results"][0]["unit_id"] == "p-coherent-tamper-123456"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE metadata SET source_count = 'garbage'",
        "UPDATE metadata SET passage_count = 'garbage'",
        "UPDATE passages SET line_start = 'garbage' WHERE passage_id = (SELECT passage_id FROM passages LIMIT 1)",
    ],
)
def test_malformed_cache_scalar_is_corrupt_and_falls_back(tmp_path: Path, statement: str) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-malformed-cache-123456", "Malformed cache", summary="fallback needle"))
    build_index(tmp_path)
    connection = sqlite3.connect(passage_search_cache_path(tmp_path))
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()

    payload = search_passages(tmp_path, "fallback needle")
    assert payload["health"] == "corrupt"
    assert payload["results"][0]["unit_id"] == "p-malformed-cache-123456"


@pytest.mark.parametrize("build_cache", [False, True], ids=["fallback", "current-cache"])
def test_standalone_obsidian_block_ids_are_locator_metadata_not_passages(
    tmp_path: Path,
    build_cache: bool,
) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-block-id-123456", "Block ID paper"))
    note = unit_root(tmp_path, "paper", "p-block-id-123456") / "source" / "document.md"
    write_text_if_changed(
        note,
        "# Routing notes\n\nAurora routing chooses the stable actuator path.\n^source-section-aurora-routing-notes\n",
    )
    if build_cache:
        build_index(tmp_path)

    anchor = search_passages(tmp_path, "source-section-aurora-routing-notes")
    content = search_passages(tmp_path, "Aurora routing")

    assert anchor["results"] == []
    assert content["results"]
    assert "Aurora routing chooses" in content["results"][0]["excerpt"]
    assert "^source-section" not in content["results"][0]["excerpt"]


def test_block_id_filter_uses_the_canonical_locator_grammar() -> None:
    from research.retrieval import markdown_passages

    passages = markdown_passages(
        {"id": "p-grammar-123456", "kind": "paper", "title": "Grammar", "summary": ""},
        artifact="source/document.md",
        text="^literal_token\n^-canonical-anchor\n",
        source_digest="digest",
    )

    assert any("^literal_token" in passage["text"] for passage in passages)
    assert all("^-canonical-anchor" not in passage["text"] for passage in passages)


def test_fts_unavailable_falls_back_and_reports_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-nofts-123456", "No FTS Paper", summary="mixed tactile recovery"))
    build_index(tmp_path)
    monkeypatch.setattr(
        index_mod,
        "_query_passage_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("no such module: fts5")),
    )

    payload = search_passages(tmp_path, "tactile recovery")

    assert payload["health"] == "unavailable"
    assert payload["results"][0]["unit_id"] == "p-nofts-123456"


def test_mixed_cjk_ascii_passage_fallback_and_filters(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    first = _record("p-cjk-passage-123456", "触觉策略", summary="灵巧手 recovery policy")
    first["candidate_pools"] = ["reading"]
    second = _record("p-cjk-other-123456", "视觉策略", summary="灵巧手 recovery policy")
    second["candidate_pools"] = ["other"]
    _write_record(tmp_path, first)
    _write_record(tmp_path, second)

    payload = search_passages(tmp_path, "灵巧手recovery", pool="reading")

    assert payload["health"] == "missing"
    assert payload["results"]
    assert {item["unit_id"] for item in payload["results"]} == {"p-cjk-passage-123456"}


def test_passage_walk_excludes_source_raw_output_obsidian_and_symlinks(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-safe-walk-123456", "Safe Walk"))
    root = unit_root(tmp_path, "paper", "p-safe-walk-123456")
    write_text_if_changed(root / "paper-note.md", "# Included\n\nvisible needle phrase\n")
    for dirname in ["source", "raw", "output", "obsidian", ".runtime", ".journal"]:
        write_text_if_changed(root / dirname / "hidden.md", f"hidden-{dirname} forbidden-only-token\n")
    outside = tmp_path / "outside.md"
    write_text_if_changed(outside, "symlink forbidden-only-token\n")
    (root / "linked.md").symlink_to(outside)
    (root / "linked-dir").symlink_to(outside.parent, target_is_directory=True)

    visible = search_passages(tmp_path, "visible needle")
    forbidden = search_passages(tmp_path, "forbidden-only-token")

    assert visible["results"]
    assert forbidden["results"] == []


def test_canonical_source_document_and_parse_cache_are_searchable_but_archives_are_not(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-fulltext-123456", "Full Text"))
    root = unit_root(tmp_path, "paper", "p-fulltext-123456")
    source = root / "source"
    write_text_if_changed(
        source / "document.md",
        "# Canonical source\n\nThe full paper explains a manifold-residual controller.\n",
    )
    write_text_if_changed(source / "original-document.md", "original-only-secret\n")
    write_text_if_changed(source / "raw.md", "raw-markdown-secret\n")
    write_text_if_changed(source / "archive.html", "<p>archive-html-secret</p>\n")
    write_yaml_if_changed(
        root / "parse-cache.yaml",
        {
            "unit_id": "p-fulltext-123456",
            "chunks": [
                {
                    "label": "source.pdf:page-7",
                    "text": "The ablation identifies a contact-gating threshold.",
                    "page": 7,
                }
            ],
        },
    )

    document_hit = search_passages(tmp_path, "manifold-residual")
    cache_hit = search_passages(tmp_path, "contact-gating")

    assert document_hit["results"][0]["artifact"].endswith("source/document.md")
    assert cache_hit["results"][0]["artifact"].endswith("parse-cache.yaml")
    assert cache_hit["results"][0]["locator"].endswith("#source.pdf:page-7")
    for hidden in ("original-only-secret", "raw-markdown-secret", "archive-html-secret"):
        assert search_passages(tmp_path, hidden)["results"] == []


def test_read_path_rejects_runtime_parent_symlink_without_opening_external_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_workspace(tmp_path)
    _write_record(
        tmp_path,
        _record("p-parent-link-123456", "Parent Link", summary="safe fallback phrase"),
    )
    build_index(tmp_path)
    runtime = tmp_path / "kb" / ".runtime"
    outside_runtime = tmp_path / "outside-runtime"
    runtime.rename(outside_runtime)
    runtime.symlink_to(outside_runtime, target_is_directory=True)
    monkeypatch.setattr(
        index_mod,
        "_read_only_cache_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external cache must not be opened")),
    )

    payload = search_passages(tmp_path, "safe fallback")

    assert payload["health"] == "corrupt"
    assert payload["results"][0]["unit_id"] == "p-parent-link-123456"


def test_long_markdown_block_uses_fixed_overlapping_windows(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-window-123456", "Window Paper"))
    marker = "A" * (PASSAGE_MAX_CHARS - 20) + " overlap-token " + "B" * 300
    note = unit_root(tmp_path, "paper", "p-window-123456") / "paper-note.md"
    write_text_if_changed(note, f"# Long block\n\n{marker}\n")

    passages, _, _ = index_mod.passage_corpus(tmp_path)
    note_passages = [item for item in passages if item["artifact"].endswith("paper-note.md")]

    assert len(note_passages) == 2
    assert all(len(item["text"]) <= PASSAGE_MAX_CHARS for item in note_passages)
    assert note_passages[0]["text"][-PASSAGE_OVERLAP_CHARS:] in note_passages[1]["text"]
    assert all(item["heading"] == "Long block" for item in note_passages)


def test_passage_capture_rejects_real_unit_replacement_after_record_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_workspace(tmp_path)
    unit_id = "p-passage-race-123456"
    _write_record(tmp_path, _record(unit_id, "Snapshot-bound paper"))
    unit = unit_root(tmp_path, "paper", unit_id)
    write_text_if_changed(unit / "paper-note.md", "Benign original passage.\n")
    replacement = tmp_path / "replacement-unit"
    shutil.copytree(unit, replacement)
    write_text_if_changed(replacement / "paper-note.md", "TOPSECRET_PUBLIC_TOKEN\n")
    parked = tmp_path / "parked-unit"
    original_capture = index_mod.snapshot_canonical_unit_artifacts
    swapped = False

    def racing_capture(project_root, kind, captured_id, artifacts):
        nonlocal swapped
        if captured_id == unit_id and not swapped:
            swapped = True
            unit.rename(parked)
            replacement.rename(unit)
        return original_capture(project_root, kind, captured_id, artifacts)

    monkeypatch.setattr(index_mod, "snapshot_canonical_unit_artifacts", racing_capture)

    payload = search_passages(tmp_path, "TOPSECRET_PUBLIC_TOKEN")

    assert payload["results"] == []
    assert swapped


def test_passage_leaf_open_rejects_unit_symlink_swap_without_external_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_workspace(tmp_path)
    unit_id = "p-passage-open-race-123456"
    _write_record(tmp_path, _record(unit_id, "Open-race paper"))
    unit = unit_root(tmp_path, "paper", unit_id)
    write_text_if_changed(unit / "paper-note.md", "Original anchored passage.\n")
    outside = tmp_path / "outside-passage-unit"
    shutil.copytree(unit, outside)
    write_text_if_changed(outside / "paper-note.md", "TOPSECRET_EXTERNAL_PASSAGE\n")
    parked = tmp_path / "parked-passage-unit"
    import research.records as records_mod

    original_open = records_mod.os.open
    swapped = False

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if name == "paper-note.md" and dir_fd is not None and not swapped:
            swapped = True
            unit.rename(parked)
            unit.symlink_to(outside, target_is_directory=True)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(records_mod.os, "open", racing_open)

    payload = search_passages(tmp_path, "TOPSECRET_EXTERNAL_PASSAGE")

    assert payload["results"] == []
    assert swapped


def test_failed_atomic_replace_preserves_prior_passage_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-atomic-123456", "Atomic Cache"))
    build_index(tmp_path)
    cache = passage_search_cache_path(tmp_path)
    before = hashlib.sha256(cache.read_bytes()).hexdigest()
    original_replace = index_mod.os.replace

    def fail_cache_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == cache:
            raise OSError("injected replace failure")
        original_replace(source, target)

    monkeypatch.setattr(index_mod.os, "replace", fail_cache_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        index_mod.rebuild_passage_cache(tmp_path)

    assert hashlib.sha256(cache.read_bytes()).hexdigest() == before
    assert list(cache.parent.glob(".passages-*.sqlite3")) == []


def test_passage_cache_symlink_collision_is_rejected(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    _write_record(tmp_path, _record("p-collision-123456", "Collision"))
    cache = passage_search_cache_path(tmp_path)
    cache.parent.mkdir(parents=True)
    target = tmp_path / "outside.sqlite3"
    target.write_bytes(b"do not replace")
    cache.symlink_to(target)

    with pytest.raises(index_mod.PassageCacheError, match="symlink"):
        index_mod.rebuild_passage_cache(tmp_path)

    assert target.read_bytes() == b"do not replace"

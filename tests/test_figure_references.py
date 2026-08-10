from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from research.figures import (
    FigureIndexError,
    asset_relative_path,
    build_asset_binding,
    build_figure_entry,
    build_figure_index,
    canonical_figure_index_digest,
    load_current_figure_index,
    merge_logical_entries,
    normalize_caption_number,
    normalize_caption_text,
    resolve_figure_ref,
    stable_figure_ref_key,
    validate_figure_index,
)


PAPER_ID = "p-stable-figure-123456"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(
    *,
    kind: str = "figure",
    number: str = "1",
    caption: str = "Figure 1. Stable caption",
    page: int = 2,
    data: bytes = b"png-one",
    caption_bbox: list[float] | None = None,
) -> dict:
    return build_figure_entry(
        PAPER_ID,
        kind=kind,
        number=number,
        caption=caption,
        page=page,
        assets=[
            build_asset_binding(
                data,
                page=page,
                caption_bbox=caption_bbox,
                crop_bbox=[10, 20, 110, 220],
                source_mode="caption-region",
            )
        ],
    )


def _index(entries: list[dict], *, settings: dict | None = None) -> dict:
    return build_figure_index(
        PAPER_ID,
        source_artifact="source/document.pdf",
        source_sha256=_sha(b"source-pdf"),
        extraction_settings=settings or {"mode": "caption-region", "render_scale": 2.5},
        entries=entries,
    )


def _materialize_index(root: Path, index: dict) -> tuple[Path, Path]:
    unit_root = root / "units" / "papers" / PAPER_ID
    source = unit_root / "source" / "document.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source-pdf")
    for entry in index["entries"]:
        for asset in entry["assets"]:
            path = unit_root / asset["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            content = b"png-one" if asset["sha256"] == _sha(b"png-one") else b"png-two"
            assert _sha(content) == asset["sha256"]
            path.write_bytes(content)
    index_path = unit_root / "figures.yaml"
    index_path.write_text(yaml.safe_dump(index, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return unit_root, index_path


def test_caption_number_and_ref_keys_are_logical_not_traversal_based() -> None:
    assert normalize_caption_number("Figure 001(a)") == "1"
    assert normalize_caption_number("1-b") == "1"
    assert normalize_caption_number("IVa") == "4"
    assert normalize_caption_number("S01b") == "s1"
    assert normalize_caption_number("unknown") == ""
    assert normalize_caption_text("Fig. 2(b) (continued): Shared Pipeline") == "shared pipeline"

    first = stable_figure_ref_key(
        PAPER_ID,
        "figure",
        "01a",
        caption="Figure 1(a). First traversal caption",
        page=9,
    )
    second = stable_figure_ref_key(
        PAPER_ID,
        "fig",
        "1-b",
        caption="Figure 1(b). Different panel text",
        page=2,
    )
    assert first == second == f"fig:{PAPER_ID}:fig:1"

    fallback = stable_figure_ref_key(
        PAPER_ID,
        "table",
        "unknown",
        caption="Table. Ablations without a printed number",
        page=7,
    )
    assert fallback == f"fig:{PAPER_ID}:tbl:u-p7-" + hashlib.sha256(
        b"ablations without a printed number"
    ).hexdigest()[:8]
    assert fallback != stable_figure_ref_key(
        PAPER_ID,
        "table",
        "",
        caption="Table. Ablations without a printed number",
        page=8,
    )


def test_index_and_digest_are_stable_under_extraction_traversal_reordering() -> None:
    figure = _entry(data=b"png-one")
    table = _entry(
        kind="table",
        number="2",
        caption="Table 2. Quantitative results",
        page=5,
        data=b"png-two",
    )
    forward = _index([figure, table])
    reverse = _index([table, figure])

    assert forward == reverse
    assert [entry["ref_key"] for entry in forward["entries"]] == sorted(
        entry["ref_key"] for entry in forward["entries"]
    )
    assert forward["index_digest"] == canonical_figure_index_digest(forward)

    changed_settings = _index([figure, table], settings={"mode": "caption-region", "render_scale": 3.0})
    assert changed_settings["index_digest"] != forward["index_digest"]


def test_panel_and_continued_crops_merge_into_one_logical_entry() -> None:
    panel_a = _entry(
        number="02a",
        caption="Figure 2(a). Shared pipeline",
        page=3,
        data=b"png-one",
    )
    panel_b = _entry(
        number="2-b",
        caption="Fig. 2(b) (continued): Shared pipeline",
        page=4,
        data=b"png-two",
    )
    index = _index([panel_b, panel_a])
    reverse_index = _index([panel_a, panel_b])

    assert index == reverse_index
    assert len(index["entries"]) == 1
    entry = index["entries"][0]
    assert entry["ref_key"] == f"fig:{PAPER_ID}:fig:2"
    assert entry["caption"] == "Figure 2. Shared pipeline"
    assert entry["page"] == 3
    assert entry["pages"] == [3, 4]
    assert [asset["sha256"] for asset in entry["assets"]] == sorted(
        [_sha(b"png-one"), _sha(b"png-two")]
    )
    assert all(asset["path"] == asset_relative_path(asset["sha256"]) for asset in entry["assets"])


def test_same_ref_conflicts_fail_closed() -> None:
    first = _entry(number="3a", caption="Figure 3(a). First meaning")
    changed_caption = _entry(number="3b", caption="Figure 3(b). Different meaning", data=b"png-two")
    with pytest.raises(FigureIndexError, match="conflicting caption_digest"):
        _index([first, changed_caption])

    changed_type = dict(first)
    changed_type["kind"] = "table"
    with pytest.raises(FigureIndexError, match="conflicting kind"):
        merge_logical_entries(first, changed_type)


def test_current_loader_and_resolver_recheck_source_index_and_asset_bytes(tmp_path: Path) -> None:
    index = _index([_entry(data=b"png-one")])
    unit_root, index_path = _materialize_index(tmp_path, index)
    index_bytes = _sha(index_path.read_bytes())

    loaded = load_current_figure_index(
        index_path,
        unit_root=unit_root,
        project_root=tmp_path,
        expected_index_digest=index["index_digest"],
        expected_index_byte_sha256=index_bytes,
        expected_source_sha256=_sha(b"source-pdf"),
    )
    resolved = resolve_figure_ref(
        loaded,
        f"fig:{PAPER_ID}:fig:1",
        unit_root=unit_root,
        expected_index_digest=index["index_digest"],
    )
    assert resolved["caption"] == "Figure 1. Stable caption"

    asset_path = unit_root / loaded["entries"][0]["assets"][0]["path"]
    asset_path.write_bytes(b"tampered-crop")
    with pytest.raises(FigureIndexError, match="figure asset bytes changed"):
        resolve_figure_ref(
            loaded,
            f"fig:{PAPER_ID}:fig:1",
            unit_root=unit_root,
        )
    asset_path.write_bytes(b"png-one")

    source_path = unit_root / "source" / "document.pdf"
    source_path.write_bytes(b"tampered-source")
    with pytest.raises(FigureIndexError, match="source artifact bytes changed"):
        resolve_figure_ref(
            loaded,
            f"fig:{PAPER_ID}:fig:1",
            unit_root=unit_root,
        )
    source_path.write_bytes(b"source-pdf")

    index_path.write_text(index_path.read_text(encoding="utf-8") + "# formatting drift\n", encoding="utf-8")
    with pytest.raises(FigureIndexError, match="index artifact bytes changed"):
        load_current_figure_index(
            index_path,
            unit_root=unit_root,
            expected_index_byte_sha256=index_bytes,
        )


def test_semantic_and_path_tampering_are_rejected_without_fallback(tmp_path: Path) -> None:
    index = _index([_entry(data=b"png-one")])
    unit_root, index_path = _materialize_index(tmp_path, index)

    changed = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    changed["entries"][0]["caption"] = "Figure 1. Forged replacement caption"
    assert "caption digest changed" in "\n".join(
        validate_figure_index(changed, unit_root=unit_root)
    )
    with pytest.raises(FigureIndexError, match="caption digest changed"):
        resolve_figure_ref(
            changed,
            f"fig:{PAPER_ID}:fig:1",
            unit_root=unit_root,
        )

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png-one")
    asset_path = unit_root / index["entries"][0]["assets"][0]["path"]
    asset_path.unlink()
    asset_path.symlink_to(outside)
    with pytest.raises(FigureIndexError, match="must not traverse a symlink"):
        load_current_figure_index(index_path, unit_root=unit_root)

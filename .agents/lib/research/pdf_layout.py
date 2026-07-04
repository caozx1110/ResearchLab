"""PDF layout helpers for caption-region figure extraction."""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path
from typing import Any

from .common import clean_text

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    Image = None  # type: ignore[assignment]

try:
    import fitz
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    fitz = None  # type: ignore[assignment]

WHITE_RATIO_THRESHOLD = 0.98
GRAY_RATIO_THRESHOLD = 0.98
LOW_COLOR_THRESHOLD = 4
CAPTION_PATTERN = re.compile(r"^(figure|fig\.|table)\s*([0-9ivxlcdm]+[a-z]?)?\s*[:.]?\s*(.*)$", re.IGNORECASE | re.DOTALL)
LAYOUT_CLUSTER_GAP_PT = 14.0
LAYOUT_MAX_CAPTION_GAP_PT = 120.0
LAYOUT_MIN_REGION_AREA = 1500.0
LAYOUT_DEFAULT_RENDER_SCALE = 2.5
LAYOUT_DEFAULT_CROP_PADDING_PT = 12.0


def _ensure_layout_backend() -> None:
    if fitz is None:
        raise SystemExit("PyMuPDF is required for caption-region figure extraction. Install it into the research runtime first.")


def _rect_area(rect: tuple[float, float, float, float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _x_overlap(rect: tuple[float, float, float, float], band: tuple[float, float]) -> float:
    return max(0.0, min(rect[2], band[1]) - max(rect[0], band[0]))


def _rect_center_x(rect: tuple[float, float, float, float]) -> float:
    return (rect[0] + rect[2]) / 2.0


def _rects_connected(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    *,
    pad: float,
) -> bool:
    return not (
        left[2] + pad < right[0]
        or right[2] + pad < left[0]
        or left[3] + pad < right[1]
        or right[3] + pad < left[1]
    )


def _merge_rects(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(rect[0] for rect in rects),
        min(rect[1] for rect in rects),
        max(rect[2] for rect in rects),
        max(rect[3] for rect in rects),
    )


def _round_rect(rect: tuple[float, float, float, float], digits: int = 2) -> list[float]:
    return [round(value, digits) for value in rect]


def _is_near_white(color: tuple[float, float, float] | None, *, threshold: float = 0.97) -> bool:
    return bool(color) and all(channel >= threshold for channel in color)


def _band_for_caption(page_rect: Any, caption_bbox: tuple[float, float, float, float]) -> tuple[tuple[float, float], bool]:
    page_width = float(page_rect.width)
    x0, _, x1, _ = caption_bbox
    width = x1 - x0
    center = (x0 + x1) / 2.0
    margin = max(24.0, page_width * 0.06)
    gutter = max(12.0, page_width * 0.025)
    full_width = width >= page_width * 0.68 or (x0 <= page_width * 0.25 and x1 >= page_width * 0.75)
    if full_width:
        return (margin, page_width - margin), True
    if center < page_width / 2.0:
        return (margin, page_width / 2.0 - gutter), False
    return (page_width / 2.0 + gutter, page_width - margin), False


def _collect_text_blocks(page: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in page.get_text("blocks"):
        text = clean_text(str(item[4] or ""))
        if not text:
            continue
        blocks.append(
            {
                "kind": "text",
                "bbox": (float(item[0]), float(item[1]), float(item[2]), float(item[3])),
                "text": text,
            }
        )
    return blocks


def _collect_image_elements(page: Any) -> list[dict[str, Any]]:
    seen: set[tuple[int, tuple[float, float, float, float]]] = set()
    elements: list[dict[str, Any]] = []
    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox")
        if not bbox:
            continue
        rect = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        if _rect_area(rect) < 20.0:
            continue
        key = (int(info.get("xref") or 0), tuple(_round_rect(rect, digits=1)))
        if key in seen:
            continue
        seen.add(key)
        elements.append({"kind": "image", "bbox": rect})
    return elements


def _collect_drawing_elements(page: Any) -> list[dict[str, Any]]:
    page_area = float(page.rect.width) * float(page.rect.height)
    elements: list[dict[str, Any]] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect:
            continue
        bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
        area = _rect_area(bbox)
        if area < 20.0:
            continue
        if area > page_area * 0.6 and _is_near_white(drawing.get("fill")) and drawing.get("color") is None:
            continue
        elements.append({"kind": "drawing", "bbox": bbox})
    return elements


def _collect_table_elements(page: Any) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            finder = page.find_tables()
    except Exception:  # noqa: BLE001
        return tables
    for table in getattr(finder, "tables", []):
        bbox = getattr(table, "bbox", None)
        if not bbox:
            continue
        rect = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        if _rect_area(rect) < 40.0:
            continue
        tables.append({"kind": "table", "bbox": rect})
    return tables


def _cluster_elements(elements: list[dict[str, Any]], *, pad: float) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    used = [False] * len(elements)
    for index, item in enumerate(elements):
        if used[index]:
            continue
        used[index] = True
        cluster = [item]
        stack = [index]
        while stack:
            current = stack.pop()
            current_rect = elements[current]["bbox"]
            for candidate_index, candidate in enumerate(elements):
                if used[candidate_index]:
                    continue
                if _rects_connected(current_rect, candidate["bbox"], pad=pad):
                    used[candidate_index] = True
                    stack.append(candidate_index)
                    cluster.append(candidate)
        clusters.append(cluster)
    return clusters


def _select_cluster(
    elements: list[dict[str, Any]],
    *,
    caption_bbox: tuple[float, float, float, float],
    direction: str,
    band: tuple[float, float],
    full_width: bool,
    max_gap_pt: float,
) -> tuple[list[dict[str, Any]], tuple[float, float, float, float]] | None:
    filtered: list[dict[str, Any]] = []
    for item in elements:
        bbox = item["bbox"]
        overlap = _x_overlap(bbox, band)
        if overlap < min(18.0, (bbox[2] - bbox[0]) * 0.2):
            continue
        if not full_width and not (band[0] <= _rect_center_x(bbox) <= band[1]):
            continue
        if direction == "above" and bbox[3] > caption_bbox[1] + 10.0:
            continue
        if direction == "below" and bbox[1] < caption_bbox[3] - 4.0:
            continue
        filtered.append(item)
    best_cluster: list[dict[str, Any]] | None = None
    best_bbox: tuple[float, float, float, float] | None = None
    best_score: tuple[float, float, float] | None = None
    for cluster in _cluster_elements(filtered, pad=LAYOUT_CLUSTER_GAP_PT):
        cluster_bbox = _merge_rects([item["bbox"] for item in cluster])
        if _rect_area(cluster_bbox) < LAYOUT_MIN_REGION_AREA:
            continue
        if direction == "above":
            gap = max(0.0, caption_bbox[1] - cluster_bbox[3])
        else:
            gap = max(0.0, cluster_bbox[1] - caption_bbox[3])
        if gap > max_gap_pt:
            continue
        area = _rect_area(cluster_bbox)
        width = cluster_bbox[2] - cluster_bbox[0]
        score = (gap, -area, -width)
        if best_score is None or score < best_score:
            best_score = score
            best_cluster = cluster
            best_bbox = cluster_bbox
    if best_cluster is None or best_bbox is None:
        return None
    return best_cluster, best_bbox


def _expand_bbox_with_text(
    bbox: tuple[float, float, float, float],
    text_blocks: list[dict[str, Any]],
    *,
    band: tuple[float, float],
    full_width: bool,
) -> tuple[float, float, float, float]:
    padded = (bbox[0] - 8.0, bbox[1] - 8.0, bbox[2] + 8.0, bbox[3] + 8.0)
    additions = [bbox]
    for block in text_blocks:
        rect = block["bbox"]
        if _x_overlap(rect, band) <= 0.0:
            continue
        if not full_width and not (band[0] <= _rect_center_x(rect) <= band[1]):
            continue
        if _rects_connected(padded, rect, pad=8.0):
            additions.append(rect)
    return _merge_rects(additions)


def _finalize_crop_bbox(
    bbox: tuple[float, float, float, float],
    *,
    page_rect: Any,
    band: tuple[float, float],
    full_width: bool,
    padding_pt: float,
    clamp_bottom: float | None = None,
    clamp_top: float | None = None,
) -> tuple[float, float, float, float]:
    x0 = max(0.0, bbox[0] - padding_pt)
    y0 = max(0.0, bbox[1] - padding_pt)
    x1 = min(float(page_rect.width), bbox[2] + padding_pt)
    y1 = min(float(page_rect.height), bbox[3] + padding_pt)
    if not full_width:
        x0 = max(x0, band[0] - padding_pt)
        x1 = min(x1, band[1] + padding_pt)
    if clamp_bottom is not None:
        y1 = min(y1, clamp_bottom)
    if clamp_top is not None:
        y0 = max(y0, clamp_top)
    return (x0, y0, x1, y1)


def _caption_entries(page: Any, page_number: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for block in _collect_text_blocks(page):
        text = block["text"]
        match = CAPTION_PATTERN.match(text)
        if not match:
            continue
        raw_kind = match.group(1).lower()
        kind = "table" if raw_kind == "table" else "figure"
        label = clean_text(match.group(2) or "").lower() or "unknown"
        entries.append(
            {
                "kind": kind,
                "label": label,
                "page": page_number,
                "caption": text,
                "bbox": block["bbox"],
            }
        )
    return entries


def _render_crop(page: Any, bbox: tuple[float, float, float, float], target: Path, *, scale: float) -> None:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=fitz.Rect(*bbox), alpha=False)
    pixmap.save(str(target))


def extract_caption_region_assets(
    rel_path,
    pdf_path: Path,
    figures_root: Path,
    *,
    include_tables: bool,
    render_scale: float,
    crop_padding_pt: float,
    filter_blank_and_mask: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    _ensure_layout_backend()
    document = fitz.open(pdf_path)
    assets: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    figures_root.mkdir(parents=True, exist_ok=True)
    for old in list(figures_root.glob("figure-*.png")) + list(figures_root.glob("table-*.png")):
        old.unlink()
    asset_counter: dict[str, int] = {"figure": 0, "table": 0}
    captions_detected = 0
    for page_index, page in enumerate(document):
        text_blocks = _collect_text_blocks(page)
        visual_elements = _collect_image_elements(page) + _collect_drawing_elements(page)
        table_elements = _collect_table_elements(page)
        for caption in _caption_entries(page, page_index + 1):
            if caption["kind"] == "table" and not include_tables:
                continue
            captions_detected += 1
            band, full_width = _band_for_caption(page.rect, caption["bbox"])
            selected_bbox: tuple[float, float, float, float] | None = None
            source_mode = "caption-region"
            if caption["kind"] == "figure":
                cluster = _select_cluster(
                    visual_elements,
                    caption_bbox=caption["bbox"],
                    direction="above",
                    band=band,
                    full_width=full_width,
                    max_gap_pt=LAYOUT_MAX_CAPTION_GAP_PT,
                ) or _select_cluster(
                    visual_elements,
                    caption_bbox=caption["bbox"],
                    direction="below",
                    band=band,
                    full_width=full_width,
                    max_gap_pt=LAYOUT_MAX_CAPTION_GAP_PT,
                )
                if cluster:
                    _, cluster_bbox = cluster
                    if cluster_bbox[3] <= caption["bbox"][1]:
                        selected_bbox = _finalize_crop_bbox(
                            cluster_bbox,
                            page_rect=page.rect,
                            band=band,
                            full_width=full_width,
                            padding_pt=crop_padding_pt,
                            clamp_bottom=caption["bbox"][1] - 4.0,
                        )
                    else:
                        selected_bbox = _finalize_crop_bbox(
                            cluster_bbox,
                            page_rect=page.rect,
                            band=band,
                            full_width=full_width,
                            padding_pt=crop_padding_pt,
                            clamp_top=caption["bbox"][3] + 4.0,
                        )
            else:
                cluster = _select_cluster(
                    table_elements,
                    caption_bbox=caption["bbox"],
                    direction="below",
                    band=band,
                    full_width=full_width,
                    max_gap_pt=LAYOUT_MAX_CAPTION_GAP_PT,
                ) or _select_cluster(
                    [
                        *visual_elements,
                        *[block for block in text_blocks if not CAPTION_PATTERN.match(str(block.get("text") or ""))],
                    ],
                    caption_bbox=caption["bbox"],
                    direction="below",
                    band=band,
                    full_width=full_width,
                    max_gap_pt=LAYOUT_MAX_CAPTION_GAP_PT,
                ) or _select_cluster(
                    [
                        *visual_elements,
                        *[block for block in text_blocks if not CAPTION_PATTERN.match(str(block.get("text") or ""))],
                    ],
                    caption_bbox=caption["bbox"],
                    direction="above",
                    band=band,
                    full_width=full_width,
                    max_gap_pt=LAYOUT_MAX_CAPTION_GAP_PT,
                )
                if cluster:
                    _, cluster_bbox = cluster
                    expanded = _expand_bbox_with_text(cluster_bbox, text_blocks, band=band, full_width=full_width)
                    if cluster_bbox[1] >= caption["bbox"][3]:
                        selected_bbox = _finalize_crop_bbox(
                            expanded,
                            page_rect=page.rect,
                            band=band,
                            full_width=full_width,
                            padding_pt=crop_padding_pt,
                            clamp_top=caption["bbox"][3] + 4.0,
                        )
                    else:
                        selected_bbox = _finalize_crop_bbox(
                            expanded,
                            page_rect=page.rect,
                            band=band,
                            full_width=full_width,
                            padding_pt=crop_padding_pt,
                            clamp_bottom=caption["bbox"][1] - 4.0,
                        )
            if not selected_bbox or _rect_area(selected_bbox) < LAYOUT_MIN_REGION_AREA:
                filtered.append(
                    {
                        "status": "skipped-caption",
                        "kind": caption["kind"],
                        "label": caption["label"],
                        "page": caption["page"],
                        "caption": caption["caption"],
                        "reason": "no-stable-layout-region",
                    }
                )
                continue
            asset_counter[caption["kind"]] += 1
            target = figures_root / f"{caption['kind']}-{asset_counter[caption['kind']]:03d}.png"
            _render_crop(page, selected_bbox, target, scale=render_scale)
            quality = image_quality(target) if filter_blank_and_mask else {"status": "unchecked", "keep": True}
            if not quality.get("keep", False):
                filtered.append(
                    {
                        "status": "filtered-layout-crop",
                        "kind": caption["kind"],
                        "label": caption["label"],
                        "page": caption["page"],
                        "caption": caption["caption"],
                        "source_name": target.name,
                        **quality,
                    }
                )
                target.unlink(missing_ok=True)
                continue
            assets.append(
                {
                    "id": target.stem,
                    "kind": caption["kind"],
                    "label": caption["label"],
                    "page": caption["page"],
                    "caption": caption["caption"],
                    "caption_bbox": _round_rect(caption["bbox"]),
                    "crop_bbox": _round_rect(selected_bbox),
                    "path": rel_path(target),
                    "source_mode": source_mode,
                    "quality": quality,
                }
            )
    return assets, filtered, {"mode": "caption-region", "captions_detected": captions_detected}


def image_quality(path: Path) -> dict[str, Any]:
    if Image is None:
        return {"status": "unchecked", "reason": "Pillow not installed", "keep": True}
    try:
        image = Image.open(path).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable", "reason": str(exc), "keep": False}
    width, height = image.size
    pixels = max(1, width * height)
    colors = image.getcolors(maxcolors=10_000_000) or []
    unique_colors = len(colors)
    white = black = grayish = 0
    for count, (red, green, blue) in colors:
        if red >= 250 and green >= 250 and blue >= 250:
            white += count
        if red <= 5 and green <= 5 and blue <= 5:
            black += count
        if max(red, green, blue) - min(red, green, blue) <= 3:
            grayish += count
    white_ratio = white / pixels
    black_ratio = black / pixels
    gray_ratio = grayish / pixels
    reasons = []
    if white_ratio > WHITE_RATIO_THRESHOLD:
        reasons.append("near-white")
    if unique_colors <= LOW_COLOR_THRESHOLD:
        reasons.append("very-low-color")
    if gray_ratio > GRAY_RATIO_THRESHOLD and white_ratio <= WHITE_RATIO_THRESHOLD:
        reasons.append("mask-like")
    return {
        "status": "filtered" if reasons else "kept",
        "keep": not reasons,
        "reason": ",".join(reasons),
        "width": width,
        "height": height,
        "unique_colors": unique_colors,
        "white_ratio": round(white_ratio, 4),
        "black_ratio": round(black_ratio, 4),
        "gray_ratio": round(gray_ratio, 4),
    }

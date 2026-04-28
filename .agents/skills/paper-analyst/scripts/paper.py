#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.common import clean_text, extract_pdf_context_pages, load_yaml, read_text_excerpt, write_text_if_changed, write_yaml_if_changed
from research.v2 import (
    append_history,
    apply_record_governance,
    build_index,
    locate_record,
    maybe_auto_checkpoint,
    project_root,
    rel,
    resolve_local_reference,
    write_record,
)

try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    Image = None  # type: ignore[assignment]

SECTION_PATTERNS = (
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "approach",
    "model",
    "experiment",
    "results",
    "analysis",
    "discussion",
    "limitation",
    "conclusion",
    "appendix",
)

WHITE_RATIO_THRESHOLD = 0.98
GRAY_RATIO_THRESHOLD = 0.98
LOW_COLOR_THRESHOLD = 4


def _source_paths(root: Path, record: dict) -> list[Path]:
    paths: list[Path] = []
    source = record.get("source", {})
    for backup in source.get("backup_paths", []):
        path = root / str(backup)
        if path.exists():
            paths.append(path)
    original_uri = str(source.get("original_uri") or "")
    if original_uri and not original_uri.startswith("http"):
        path = resolve_local_reference(root, original_uri) or Path(original_uri).expanduser()
        if path.exists():
            paths.append(path.resolve())
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _load_source_chunks(root: Path, record: dict) -> list[dict]:
    chunks: list[dict] = []
    for path in _source_paths(root, record):
        if path.suffix.lower() == ".pdf":
            try:
                payload = extract_pdf_context_pages(path, front_limit=10, back_limit=0, per_page_char_limit=3000)
            except Exception:
                payload = {"pages": []}
            for page in payload.get("pages", []):
                text = clean_text(str(page.get("text") or ""))
                if text:
                    chunks.append({"label": f"{path.name}:page-{page['page']}", "text": text, "page": page["page"]})
        elif path.is_file():
            text = clean_text(read_text_excerpt(path, limit=12000))
            if text:
                chunks.append({"label": path.name, "text": text, "page": None})
    return chunks


def _cache_path(unit_root: Path) -> Path:
    return unit_root / "parse-cache.yaml"


def _load_or_refresh_cache(root: Path, record: dict, unit_root: Path, *, force: bool = False) -> tuple[list[dict], Path]:
    cache_path = _cache_path(unit_root)
    if not force and cache_path.exists():
        payload = load_yaml(cache_path, default={})
        if isinstance(payload, dict) and isinstance(payload.get("chunks"), list):
            return payload["chunks"], cache_path
    chunks = _load_source_chunks(root, record)
    write_yaml_if_changed(
        cache_path,
        {
            "paper_id": record["id"],
            "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "chunks": chunks,
        },
    )
    return chunks, cache_path


def screening_payload(record: dict, source_chunks: list[dict]) -> dict:
    title = record.get("title", "")
    topics = ", ".join(record.get("topics", [])) or "uncategorized"
    excerpt = clean_text(" ".join(chunk.get("text", "") for chunk in source_chunks[:2]))[:400]
    return {
        "paper_id": record["id"],
        "status": "pending_user_confirmation",
        "information_types": ["evaluation", "inference", "unverified"],
        "worth_deep_reading": "pending_confirmation",
        "judgement_reason": [
            f"需要结合 `{title}` 的方法新意、实验完整度与当前课题相关性来判断是否值得精读。",
            f"当前 topic/tag 信号为：{topics}。",
        ],
        "evidence_snapshot": excerpt,
        "novelty_signal": "待人工结合 related work 与核心机制确认。",
        "experiment_signal": "待人工确认实验设置、对比基线和 failure case 是否充分。",
        "relevance_signal": "待人工确认与当前 program / idea 的贴合度。",
        "risks": ["可能只有标题级 topic/tag 信号，尚未形成稳定判断。"],
        "takeaways": [
            "先确认作者/机构背景、benchmark 与主要方法切口。",
            "如果与当前 program 强相关，再进入完整笔记与结构刷新。",
        ],
        "recommended_next_action": "quick-screen-reviewed",
    }


def _note_context(record: dict, source_chunks: list[dict]) -> str:
    lines = [
        f"# 论文上下文：{record.get('title', '')}",
        "",
        f"- paper_id: `{record.get('id')}`",
        f"- topics: {', '.join(record.get('topics', [])) or '-'}",
        f"- tags: {', '.join(record.get('tags', [])) or '-'}",
        f"- source: {record.get('source', {}).get('original_uri') or '-'}",
        "",
        "## 源摘录",
        "",
    ]
    if not source_chunks:
        lines.append("- 当前未找到可读 source 文本；请人工补充 PDF / 原文链接上下文。")
    for chunk in source_chunks[:6]:
        title = chunk["label"]
        if chunk.get("page"):
            title = f"{title} (page {chunk['page']})"
        lines.extend([f"### {title}", "", chunk["text"], ""])
    return "\n".join(lines).rstrip() + "\n"


def note_template(record: dict) -> str:
    title = record.get("title", "")
    return f"""# {title}

## 快速判断

- 是否值得细读：待人工确认
- 当前 topics：{", ".join(record.get("topics", [])) or "-"}
- 当前 tags：{", ".join(record.get("tags", [])) or "-"}
- 与当前研究方向的相关性：

## Problem / Motivation


## 故事线 / 论文结构


## 核心方法与关键机制


## 关键实验与结果


## Figure 级线索


## 可靠性 / 薄弱点 / Failure Case


## 与我当前 program / idea 的关系


## 可复用结论


## 待确认问题


"""


def detect_structure(source_chunks: list[dict], note_path: Path) -> dict:
    sections: list[dict] = []
    seen: set[str] = set()
    if note_path.exists():
        for line in note_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("## "):
                heading = clean_text(line[3:])
                key = heading.lower()
                if key and key not in seen:
                    seen.add(key)
                    sections.append({"heading": heading, "source": "note.md"})
    for chunk in source_chunks:
        for raw_line in chunk.get("text", "").splitlines():
            line = clean_text(raw_line).lower()
            if len(line) > 80:
                continue
            if any(pattern == line or line.startswith(pattern + " ") for pattern in SECTION_PATTERNS):
                if line not in seen:
                    seen.add(line)
                    sections.append({"heading": line, "source": chunk["label"], "page": chunk.get("page")})
    return {
        "status": "pending_user_confirmation",
        "information_types": ["fact", "inference", "unverified"],
        "detected_sections": sections,
        "paper_outline": [item["heading"] for item in sections],
        "open_questions": ["章节结构是否因 PDF 文本抽取而漏掉子节？"],
    }


def extract_figure_mentions(source_chunks: list[dict], *, extracted_assets: list[dict[str, Any]] | None = None) -> dict:
    mentions: list[dict] = []
    seen: set[str] = set()
    pattern = re.compile(r"(?:figure|fig\.)\s*(\d+[a-z]?)", re.IGNORECASE)
    for chunk in source_chunks:
        text = chunk.get("text", "")
        for match in pattern.finditer(text):
            label = match.group(1)
            key = f"{chunk['label']}::{label}"
            if key in seen:
                continue
            seen.add(key)
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 160)
            snippet = clean_text(text[start:end])
            mentions.append(
                {
                    "figure": f"figure-{label.lower()}",
                    "source": chunk["label"],
                    "page": chunk.get("page"),
                    "snippet": snippet,
                    "status": "pending_user_confirmation",
                }
            )
    return {
        "status": "pending_user_confirmation",
        "information_types": ["fact", "inference", "unverified"],
        "candidate_figures": mentions,
        "key_figures": extracted_assets or [],
        "open_questions": ["是否需要后续补真正的图像裁剪或 caption 对齐？"],
    }


def _pdfimages_install_hint() -> str:
    return (
        "pdfimages not found. Install Poppler first. "
        "On macOS with Homebrew: `HOMEBREW_NO_AUTO_UPDATE=1 brew install poppler`. "
        "Then verify with `which pdfimages`."
    )


def ensure_pdfimages_available() -> str:
    pdfimages = shutil.which("pdfimages")
    if pdfimages:
        return pdfimages
    raise SystemExit(_pdfimages_install_hint())


def _image_quality(path: Path) -> dict[str, Any]:
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


def _extract_pdf_images(root: Path, record: dict, unit_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pdf_path = next((path for path in _source_paths(root, record) if path.suffix.lower() == ".pdf"), None)
    if pdf_path is None:
        return [], [{"status": "missing-pdf", "reason": "No PDF source found"}]
    pdfimages = ensure_pdfimages_available()
    figures_root = unit_root / "figures"
    figures_root.mkdir(parents=True, exist_ok=True)
    for old in figures_root.glob("figure-*.png"):
        old.unlink()
    assets = []
    filtered = []
    kept_index = 1
    with tempfile.TemporaryDirectory(prefix="paper-figures-") as tmp:
        tmp_root = Path(tmp)
        prefix = tmp_root / "figure"
        subprocess.run([pdfimages, "-png", str(pdf_path), str(prefix)], check=False)
        for path in sorted(tmp_root.glob("figure-*.png")):
            quality = _image_quality(path)
            if not quality.get("keep", False):
                filtered.append({"source_name": path.name, **quality})
                continue
            target = figures_root / f"figure-{kept_index:03d}.png"
            shutil.move(str(path), str(target))
            assets.append({"id": f"figure-{kept_index:03d}", "path": rel(root, target), "quality": quality})
            kept_index += 1
    return assets, filtered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze paper units in v2.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ensure-pdfimages", help="Check pdfimages availability and print install instructions when missing")
    for name in ("screen", "complete-note", "extract-figures", "refresh-structure", "confirm", "reject"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--paper-id", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    if args.command == "ensure-pdfimages":
        print(ensure_pdfimages_available())
        return 0
    record, path = locate_record(root, args.paper_id)
    if record.get("kind") != "paper":
        raise SystemExit(f"{args.paper_id} is not a paper record")
    unit_root = path.parent
    source_chunks, cache_path = _load_or_refresh_cache(root, record, unit_root, force=args.command == "refresh-structure")

    if args.command == "screen":
        screen_path = unit_root / "screening.yaml"
        payload = screening_payload(record, source_chunks)
        write_yaml_if_changed(screen_path, payload)
        record = apply_record_governance(root, record, infer_missing=True, source_label="paper-analyst")
        record["payload"]["quick_screen"]["worth_deep_reading"] = "pending_confirmation"
        record["payload"]["quick_screen"]["judgement_reason"] = payload["judgement_reason"]
        record["payload"]["quick_screen"]["takeaways"] = payload["takeaways"]
        record["payload"]["quick_screen"]["novelty"] = payload["novelty_signal"]
        record["payload"]["quick_screen"]["experiment_quality"] = payload["experiment_signal"]
        record["payload"]["quick_screen"]["relevance_to_current_research"] = payload["relevance_signal"]
        record["payload"]["quick_screen"]["recommended_next_action"] = payload["recommended_next_action"]
        record["status"] = "screened"
        record["maturity"] = "lightweight"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "evaluation", "inference", "unverified"]
        record["summary"] = payload["judgement_reason"][0]
        append_history(
            record,
            action="paper-screened",
            summary="Generated quick screening judgement.",
            information_types=["evaluation", "inference", "unverified"],
            artifacts=[rel(root, screen_path), rel(root, cache_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {screen_path.relative_to(root)}")
        checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: quick screen {args.paper_id}")
        if checkpoint.get("committed"):
            print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
        return 0

    if args.command == "complete-note":
        note_path = unit_root / "note.md"
        context_path = unit_root / "note-context.md"
        write_text_if_changed(note_path, note_template(record))
        write_text_if_changed(context_path, _note_context(record, source_chunks))
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "user_opinion", "unverified"]
        append_history(
            record,
            action="paper-note-created",
            summary="Created full paper note scaffold from cached parse.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, note_path), rel(root, context_path), rel(root, cache_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {note_path.relative_to(root)}")
        print(f"[ok] wrote {context_path.relative_to(root)}")
        checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: complete paper note {args.paper_id}")
        if checkpoint.get("committed"):
            print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
        return 0

    if args.command == "extract-figures":
        figures_path = unit_root / "figures.yaml"
        extracted_assets, filtered_assets = _extract_pdf_images(root, record, unit_root)
        payload = extract_figure_mentions(source_chunks, extracted_assets=extracted_assets)
        payload["filtered_assets"] = filtered_assets
        payload["asset_counts"] = {
            "kept": len(extracted_assets),
            "filtered": len(filtered_assets),
        }
        payload["filter_policy"] = {
            "white_ratio_threshold": WHITE_RATIO_THRESHOLD,
            "gray_ratio_threshold": GRAY_RATIO_THRESHOLD,
            "low_color_threshold": LOW_COLOR_THRESHOLD,
            "discard_filtered_files": True,
        }
        write_yaml_if_changed(figures_path, payload)
        record["payload"]["figures"]["extraction_status"] = "pending_user_confirmation"
        record["payload"]["figures"]["candidate_figures"] = payload["candidate_figures"]
        record["payload"]["figures"]["key_figures"] = payload["key_figures"]
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = sorted(set(record.get("information_types", [])) | {"fact", "inference", "unverified"})
        append_history(
            record,
            action="paper-figures-extracted",
            summary="Extracted figure assets when possible and indexed figure mentions.",
            information_types=["fact", "inference", "unverified"],
            artifacts=[rel(root, figures_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {figures_path.relative_to(root)}")
        checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: extract paper figures {args.paper_id}")
        if checkpoint.get("committed"):
            print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
        return 0

    if args.command == "refresh-structure":
        structure_path = unit_root / "structure.yaml"
        note_path = unit_root / "note.md"
        payload = detect_structure(source_chunks, note_path)
        write_yaml_if_changed(structure_path, payload)
        record["payload"]["structure"]["refresh_status"] = "pending_user_confirmation"
        record["payload"]["structure"]["detected_sections"] = payload["detected_sections"]
        record["payload"]["structure"]["paper_outline"] = payload["paper_outline"]
        record["payload"]["structure"]["open_questions"] = payload["open_questions"]
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        append_history(
            record,
            action="paper-structure-refreshed",
            summary="Refreshed paper structure hints and parse cache.",
            information_types=["fact", "inference", "unverified"],
            artifacts=[rel(root, structure_path), rel(root, cache_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {structure_path.relative_to(root)}")
        checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: refresh paper structure {args.paper_id}")
        if checkpoint.get("committed"):
            print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
        return 0

    if args.command == "confirm":
        record["confirmation_status"] = "confirmed"
        record["needs_human_confirmation"] = False
        record["status"] = "active"
        append_history(record, action="paper-confirmed", summary="Paper analysis confirmed by user.", information_types=["fact"])
        write_record(root, record)
        build_index(root)
        print(f"[ok] confirmed {args.paper_id}")
        checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: confirm paper {args.paper_id}")
        if checkpoint.get("committed"):
            print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
        return 0

    if args.command == "reject":
        record["confirmation_status"] = "rejected"
        record["status"] = "rejected"
        append_history(record, action="paper-rejected", summary="Paper analysis rejected or deferred.", information_types=["evaluation"])
        write_record(root, record)
        build_index(root)
        print(f"[ok] rejected {args.paper_id}")
        checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: reject paper {args.paper_id}")
        if checkpoint.get("committed"):
            print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

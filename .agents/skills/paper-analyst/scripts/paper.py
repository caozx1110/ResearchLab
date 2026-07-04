#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
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
from research.pdf_layout import (
    GRAY_RATIO_THRESHOLD,
    LAYOUT_DEFAULT_CROP_PADDING_PT,
    LAYOUT_DEFAULT_RENDER_SCALE,
    LOW_COLOR_THRESHOLD,
    WHITE_RATIO_THRESHOLD,
    extract_caption_region_assets,
)
from research.v2 import (
    append_history,
    apply_confirmation,
    apply_record_governance,
    build_index,
    load_runtime_preferences,
    locate_record,
    checkpoint_and_report,
    project_root,
    rel,
    resolve_local_reference,
    write_record,
)

SECTION_PATTERNS = (
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "approach",
    "experiment",
    "results",
    "analysis",
    "discussion",
    "limitation",
    "conclusion",
    "appendix",
)


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--evidence", action="append", required=True)

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


def _load_source_chunks(
    root: Path,
    record: dict,
    *,
    front_limit: int,
    back_limit: int,
    per_page_char_limit: int,
) -> list[dict]:
    chunks: list[dict] = []
    for path in _source_paths(root, record):
        if path.suffix.lower() == ".pdf":
            try:
                payload = extract_pdf_context_pages(
                    path,
                    front_limit=front_limit,
                    back_limit=back_limit,
                    per_page_char_limit=per_page_char_limit,
                )
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


def _paper_preferences(root: Path) -> dict[str, Any]:
    return load_runtime_preferences(root).get("paper", {})


def _load_or_refresh_cache(root: Path, record: dict, unit_root: Path, *, force: bool = False) -> tuple[list[dict], Path]:
    preferences = _paper_preferences(root)
    cache_path = _cache_path(unit_root)
    if not force and cache_path.exists():
        payload = load_yaml(cache_path, default={})
        if isinstance(payload, dict) and isinstance(payload.get("chunks"), list):
            return payload["chunks"], cache_path
    front_limit = int(preferences.get("parse_cache_front_limit") or 8)
    back_limit = int(preferences.get("parse_cache_back_limit") or 0)
    per_page_char_limit = int(preferences.get("parse_cache_per_page_char_limit") or 3000)
    chunks = _load_source_chunks(
        root,
        record,
        front_limit=front_limit,
        back_limit=back_limit,
        per_page_char_limit=per_page_char_limit,
    )
    write_yaml_if_changed(
        cache_path,
        {
            "paper_id": record["id"],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "cache_policy": {
                "front_limit": front_limit,
                "back_limit": back_limit,
                "per_page_char_limit": per_page_char_limit,
            },
            "chunks": chunks,
        },
    )
    return chunks, cache_path


def _grade(count: int, *, strong_at: int = 3) -> str:
    if count >= strong_at:
        return "strong"
    if count > 0:
        return "moderate"
    return "weak"


def _match_keywords(text: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        if keyword in text and keyword not in hits:
            hits.append(keyword)
    return hits


def _screen_excerpt(source_chunks: list[dict], *, page_limit: int, max_chars: int) -> tuple[str, list[int]]:
    selected: list[str] = []
    pages: list[int] = []
    current = 0
    for chunk in source_chunks[:page_limit]:
        text = clean_text(chunk.get("text", ""))
        if not text:
            continue
        remaining = max_chars - current
        if remaining <= 0:
            break
        selected.append(text[:remaining])
        current += len(selected[-1])
        page = chunk.get("page")
        if isinstance(page, int) and page not in pages:
            pages.append(page)
        if current >= max_chars:
            break
    return clean_text(" ".join(selected)), pages


def _screening_mode(requested_mode: str) -> tuple[str, str]:
    normalized = requested_mode.strip() or "heuristic_structured"
    if normalized == "auto":
        normalized = "heuristic_structured"
    if normalized == "heuristic_structured":
        return normalized, ""
    return "heuristic_structured", f"requested `{requested_mode}` but no LLM screening backend is configured; fell back to heuristic_structured"


def screening_payload(
    record: dict,
    source_chunks: list[dict],
    *,
    requested_mode: str,
    context_pages: int,
    max_chars: int,
) -> dict:
    basic_info = record.get("payload", {}).get("basic_info", {})
    title = record.get("title", "")
    abstract = clean_text(str(basic_info.get("abstract") or ""))
    topics = [str(item) for item in record.get("topics", []) if str(item).strip()]
    tags = [str(item) for item in record.get("tags", []) if str(item).strip()]
    topic_signal = ", ".join(topics) or "uncategorized"
    text, evidence_pages = _screen_excerpt(source_chunks, page_limit=context_pages, max_chars=max_chars)
    combined = clean_text(" ".join(part for part in [title, abstract, text, " ".join(tags), " ".join(topics)] if part)).lower()

    result_hits = _match_keywords(
        combined,
        ["state-of-the-art", "sota", "outperform", "improves", "improvement", "success rate", "better than"],
    )
    experiment_hits = _match_keywords(
        combined,
        ["ablation", "benchmark", "evaluation", "baseline", "real-world", "real robot", "simulation", "dataset"],
    )
    reliability_hits = _match_keywords(
        combined,
        ["analysis", "limitation", "failure", "open-source", "code", "appendix", "release"],
    )
    novelty_hits = _match_keywords(
        combined,
        ["novel", "first", "we propose", "introduce", "unified", "generalist", "open-world"],
    )
    relevance_terms = [
        term.lower()
        for term in [*topics, *tags]
        if term and term.lower() not in {"uncategorized", "research"}
    ]
    relevance_hits = _match_keywords(combined, relevance_terms)
    if not relevance_hits:
        relevance_hits = _match_keywords(
            combined,
            ["vision-language-action", "vla", "robot", "policy", "control", "manipulation", "humanoid"],
        )
    authors = [str(item).strip() for item in basic_info.get("authors", []) if str(item).strip()]
    backing_count = len(authors) + (1 if str(basic_info.get("venue") or "").strip() else 0) + (1 if str(basic_info.get("arxiv_id") or "").strip() else 0)
    backing_strength = "strong" if backing_count >= 3 else "moderate" if backing_count > 0 else "weak"
    result_strength = _grade(len(result_hits), strong_at=2)
    experiment_quality = _grade(len(experiment_hits), strong_at=3)
    reliability = _grade(len(reliability_hits), strong_at=2)
    novelty = _grade(len(novelty_hits), strong_at=2)
    relevance = "strong" if len(relevance_hits) >= 2 else "moderate" if relevance_hits or topics or tags else "weak"

    score = 0
    score += {"strong": 2, "moderate": 1, "weak": 0}[result_strength]
    score += {"strong": 2, "moderate": 1, "weak": 0}[experiment_quality]
    score += {"strong": 2, "moderate": 1, "weak": 0}[novelty]
    score += {"strong": 2, "moderate": 1, "weak": 0}[relevance]
    if relevance == "weak" and score <= 2:
        worth = "no"
    elif relevance == "strong" and score >= 4:
        worth = "yes"
    elif score >= 3:
        worth = "maybe"
    else:
        worth = "no"

    effective_mode, mode_warning = _screening_mode(requested_mode)
    judgement_reason = [
        f"`{title}` 的相关性信号为 {relevance}，当前 topic/tag 为：{topic_signal}。",
        f"实验信号={experiment_quality}，创新信号={novelty}，结果信号={result_strength}。",
    ]
    if mode_warning:
        judgement_reason.append(mode_warning)
    if not source_chunks:
        judgement_reason.append("当前没有稳定抽取到 PDF / 源文本，快速判断可信度较低。")
    risks = [
        "quick screen 基于局部页面与启发式信号，仍需人工确认。",
    ]
    if not abstract:
        risks.append("当前缺少摘要级上下文，方法与实验判断可能偏粗。")
    takeaways = [
        f"建议先看摘要、方法总览与实验章节，当前 worth-deep-reading={worth}。",
        "确认 benchmark、ablation、real-world / real-robot 证据是否真的支撑标题承诺。",
        "如果与你当前 program 强相关，再进入完整笔记与 Figure 资产整理。",
    ]
    return {
        "paper_id": record["id"],
        "status": "pending_user_confirmation",
        "information_types": ["evaluation", "inference", "unverified"],
        "screening_mode_requested": requested_mode,
        "screening_mode_effective": effective_mode,
        "screening_mode_warning": mode_warning,
        "worth_deep_reading": worth,
        "judgement_reason": judgement_reason,
        "evidence_snapshot": (abstract or text)[: min(max_chars, 1200)],
        "evidence_pages": evidence_pages,
        "backing_strength": backing_strength,
        "result_strength": result_strength,
        "novelty_signal": novelty,
        "experiment_signal": experiment_quality,
        "reliability_signal": reliability,
        "relevance_signal": relevance,
        "keyword_hits": {
            "result": result_hits,
            "experiment": experiment_hits,
            "reliability": reliability_hits,
            "novelty": novelty_hits,
            "relevance": relevance_hits,
        },
        "risks": risks,
        "takeaways": takeaways[:3],
        "recommended_next_action": "complete-note" if worth in {"yes", "maybe"} else "defer-or-confirm",
    }


def _source_preview(source_chunks: list[dict], *, max_chars: int = 900) -> str:
    preview, _ = _screen_excerpt(source_chunks, page_limit=2, max_chars=max_chars)
    return preview


def _markdown_bullets(items: list[str], fallback: str) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return fallback
    return "\n".join(f"- {item}" for item in cleaned)


def note_template(record: dict, source_chunks: list[dict], *, mode: str) -> str:
    title = record.get("title", "")
    payload = record.get("payload", {})
    basic_info = payload.get("basic_info", {})
    quick = payload.get("quick_screen", {})
    structure = payload.get("structure", {})
    figures = payload.get("figures", {})
    abstract = clean_text(str(basic_info.get("abstract") or ""))
    preview = _source_preview(source_chunks)
    outline = [str(item) for item in structure.get("paper_outline", []) if str(item).strip()]
    figure_labels = [
        str(item.get("id") or item.get("label") or "")
        for item in figures.get("key_figures", [])
        if isinstance(item, dict)
    ]
    if mode == "draft":
        return f"""# {title}

## 快速判断

- 生成模式：draft（AI 草稿，待人工确认）
- 是否值得细读：{quick.get("worth_deep_reading") or "unknown"}
- 创新性：{quick.get("novelty") or "-"}
- 实验扎实度：{quick.get("experiment_quality") or "-"}
- 可靠性：{quick.get("reliability") or "-"}
- 相关性：{quick.get("relevance_to_current_research") or "-"}
- 当前 topics：{", ".join(record.get("topics", [])) or "-"}
- 当前 tags：{", ".join(record.get("tags", [])) or "-"}

## Problem / Motivation

{abstract or preview or "待结合摘要和引言补全。"}

## 故事线 / 论文结构

{_markdown_bullets(outline, "待结合目录与 section heading 补全。")}

## 核心方法与关键机制

- 先抓方法主张、核心模块、信息流和关键训练 / 推理机制。
当前 quick-screen 理由：
{_markdown_bullets([str(item) for item in quick.get("judgement_reason", [])], "待补。")}

## 关键实验与结果

- 当前实验信号：{quick.get("experiment_quality") or "-"}
- 当前结果信号：{quick.get("result_strength") or "-"}
- 重点核对 benchmark、baseline、ablation、real-world 结果是否齐全。

## Figure 级线索

{_markdown_bullets(figure_labels, "待提取 Figure / Table 资产后补全。")}

## 可靠性 / 薄弱点 / Failure Case

- 当前可靠性信号：{quick.get("reliability") or "-"}
风险：
{_markdown_bullets([str(item) for item in quick.get("risks", [])], "待补。")}

## 与我当前 program / idea 的关系

- 结合当前 topics/tags 判断其是否能提供方法线索、实验设计线索或引用价值。

## 可复用结论

- 方法机制：
- 实验套路：
- 可引用表述：

## 待确认问题

- 哪个 claim 最值得二次核对？
- 是否需要补读 appendix / project page / code repo？

"""
    return f"""# {title}

## 快速判断

- 生成模式：scaffold（待补正文）
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
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()
    if extracted_assets:
        for asset in extracted_assets:
            kind = str(asset.get("kind") or "figure")
            label = str(asset.get("label") or asset.get("id") or "").strip().lower()
            key = f"{kind}:{label}:{asset.get('page')}"
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                {
                    "figure": asset.get("id") or f"{kind}-{label or 'unknown'}",
                    "kind": kind,
                    "label": label,
                    "source": asset.get("source_mode") or "caption-region",
                    "page": asset.get("page"),
                    "caption": asset.get("caption") or "",
                    "status": "pending_user_confirmation",
                }
            )
    if not mentions:
        pattern = re.compile(r"(?:figure|fig\.|table)\s*([0-9ivxlcdm]+[a-z]?)", re.IGNORECASE)
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
                        "kind": "figure",
                        "label": label.lower(),
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
        "open_questions": [
            "caption 裁剪是否已经覆盖了论文里真正需要复用的整张 Figure / Table？",
            "是否仍有极少数跨栏或无 caption 的对象需要人工补裁？",
        ],
    }
def _extract_pdf_images(root: Path, record: dict, unit_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    pdf_path = next((path for path in _source_paths(root, record) if path.suffix.lower() == ".pdf"), None)
    if pdf_path is None:
        return [], [{"status": "missing-pdf", "reason": "No PDF source found"}], {"mode": "none", "captions_detected": 0}
    preferences = load_runtime_preferences(root).get("pdf", {})
    include_tables = bool(preferences.get("figure_include_tables", True))
    filter_blank_and_mask = bool(preferences.get("filter_blank_and_mask_images", True))
    render_scale = float(preferences.get("figure_render_scale") or LAYOUT_DEFAULT_RENDER_SCALE)
    crop_padding_pt = float(preferences.get("figure_crop_padding_pt") or LAYOUT_DEFAULT_CROP_PADDING_PT)
    figures_root = unit_root / "figures"

    return extract_caption_region_assets(
        lambda path: rel(root, path),
        pdf_path,
        figures_root,
        include_tables=include_tables,
        render_scale=render_scale,
        crop_padding_pt=crop_padding_pt,
        filter_blank_and_mask=filter_blank_and_mask,
    )


def _finalize_post_actions(root: Path, *, trigger: str, message: str, defer_post_actions: bool) -> dict[str, Any]:
    if defer_post_actions:
        return {"committed": False, "status": "deferred"}
    build_index(root)
    return checkpoint_and_report(root, trigger=trigger, message=message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze paper units in v2.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prewarm = subparsers.add_parser("prewarm-cache")
    prewarm.add_argument("--paper-id", required=True)
    prewarm.add_argument("--force", action="store_true")
    prewarm.add_argument("--defer-post-actions", action="store_true")

    screen = subparsers.add_parser("screen")
    screen.add_argument("--paper-id", required=True)
    screen.add_argument("--mode", default="auto")
    screen.add_argument("--defer-post-actions", action="store_true")

    note = subparsers.add_parser("complete-note")
    note.add_argument("--paper-id", required=True)
    note.add_argument("--mode", default="auto")
    note.add_argument("--defer-post-actions", action="store_true")

    figures = subparsers.add_parser("extract-figures")
    figures.add_argument("--paper-id", required=True)
    figures.add_argument("--defer-post-actions", action="store_true")

    structure = subparsers.add_parser("refresh-structure")
    structure.add_argument("--paper-id", required=True)
    structure.add_argument("--defer-post-actions", action="store_true")

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--paper-id", required=True)
    add_confirmation_arguments(confirm)
    confirm.add_argument("--defer-post-actions", action="store_true")

    reject = subparsers.add_parser("reject")
    reject.add_argument("--paper-id", required=True)
    reject.add_argument("--defer-post-actions", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    runtime_preferences = load_runtime_preferences(root)
    paper_preferences = runtime_preferences.get("paper", {})
    record, path = locate_record(root, args.paper_id)
    if record.get("kind") != "paper":
        raise SystemExit(f"{args.paper_id} is not a paper record")
    unit_root = path.parent
    defer_post_actions = bool(getattr(args, "defer_post_actions", False))

    source_chunks: list[dict] = []
    cache_path = _cache_path(unit_root)
    if args.command in {"prewarm-cache", "screen", "complete-note", "extract-figures", "refresh-structure"}:
        source_chunks, cache_path = _load_or_refresh_cache(
            root,
            record,
            unit_root,
            force=bool(getattr(args, "force", False)) or args.command == "refresh-structure",
        )

    if args.command == "prewarm-cache":
        print(f"[ok] wrote {cache_path.relative_to(root)}")
        print(f"[ok] cached chunks: {len(source_chunks)}")
        return 0

    if args.command == "screen":
        screen_path = unit_root / "screening.yaml"
        requested_mode = str(args.mode or "auto")
        if requested_mode == "auto":
            requested_mode = str(paper_preferences.get("screening_mode") or "heuristic_structured")
        payload = screening_payload(
            record,
            source_chunks,
            requested_mode=requested_mode,
            context_pages=int(paper_preferences.get("screening_context_pages") or 6),
            max_chars=int(paper_preferences.get("screening_max_chars") or 12000),
        )
        write_yaml_if_changed(screen_path, payload)
        record = apply_record_governance(root, record, infer_missing=True, source_label="paper-analyst")
        record["payload"]["quick_screen"]["worth_deep_reading"] = payload["worth_deep_reading"]
        record["payload"]["quick_screen"]["judgement_reason"] = payload["judgement_reason"]
        record["payload"]["quick_screen"]["takeaways"] = payload["takeaways"]
        record["payload"]["quick_screen"]["backing_strength"] = payload["backing_strength"]
        record["payload"]["quick_screen"]["result_strength"] = payload["result_strength"]
        record["payload"]["quick_screen"]["novelty"] = payload["novelty_signal"]
        record["payload"]["quick_screen"]["experiment_quality"] = payload["experiment_signal"]
        record["payload"]["quick_screen"]["reliability"] = payload["reliability_signal"]
        record["payload"]["quick_screen"]["relevance_to_current_research"] = payload["relevance_signal"]
        record["payload"]["quick_screen"]["screening_mode"] = payload["screening_mode_effective"]
        record["payload"]["quick_screen"]["screening_evidence_pages"] = payload["evidence_pages"]
        record["payload"]["quick_screen"]["risks"] = payload["risks"]
        record["payload"]["quick_screen"]["keyword_hits"] = payload["keyword_hits"]
        record["payload"]["quick_screen"]["recommended_next_action"] = payload["recommended_next_action"]
        record["status"] = "screened"
        if record.get("maturity") != "complete":
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
        print(f"[ok] wrote {screen_path.relative_to(root)}")
        checkpoint = _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: quick screen {args.paper_id}",
            defer_post_actions=defer_post_actions,
        )
        return 0

    if args.command == "complete-note":
        note_path = unit_root / "note.md"
        mode = str(args.mode or "auto")
        if mode == "auto":
            mode = str(paper_preferences.get("complete_note_mode") or "scaffold")
        write_text_if_changed(note_path, note_template(record, source_chunks, mode=mode))
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "user_opinion", "unverified"]
        record["payload"]["state"]["full_note_status"] = "pending_user_confirmation"
        record["payload"]["state"]["note_generation_mode"] = mode
        append_history(
            record,
            action="paper-note-created",
            summary=f"Created full paper note {mode} from cached parse.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, note_path), rel(root, cache_path)],
        )
        write_record(root, record)
        print(f"[ok] wrote {note_path.relative_to(root)}")
        checkpoint = _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: complete paper note {args.paper_id}",
            defer_post_actions=defer_post_actions,
        )
        return 0

    if args.command == "extract-figures":
        figures_path = unit_root / "figures.yaml"
        extracted_assets, filtered_assets, extraction_meta = _extract_pdf_images(root, record, unit_root)
        payload = extract_figure_mentions(source_chunks, extracted_assets=extracted_assets)
        payload["filtered_assets"] = filtered_assets
        payload["asset_counts"] = {
            "kept": len(extracted_assets),
            "filtered": len(filtered_assets),
        }
        payload["filter_policy"] = {
            "mode": extraction_meta.get("mode"),
            "captions_detected": extraction_meta.get("captions_detected", 0),
            "fallback_used": extraction_meta.get("fallback_used", False),
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
        print(f"[ok] wrote {figures_path.relative_to(root)}")
        checkpoint = _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: extract paper figures {args.paper_id}",
            defer_post_actions=defer_post_actions,
        )
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
        print(f"[ok] wrote {structure_path.relative_to(root)}")
        checkpoint = _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: refresh paper structure {args.paper_id}",
            defer_post_actions=defer_post_actions,
        )
        return 0

    if args.command == "confirm":
        record = apply_confirmation(record, confirmed_by=args.confirmed_by, evidence=args.evidence, method="paper.py confirm")
        record["status"] = "active"
        append_history(record, action="paper-confirmed", summary="Paper analysis confirmed by user.", information_types=["fact"])
        write_record(root, record)
        print(f"[ok] confirmed {args.paper_id}")
        checkpoint = _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: confirm paper {args.paper_id}",
            defer_post_actions=defer_post_actions,
        )
        return 0

    if args.command == "reject":
        record["confirmation_status"] = "rejected"
        record["status"] = "rejected"
        append_history(record, action="paper-rejected", summary="Paper analysis rejected or deferred.", information_types=["evaluation"])
        write_record(root, record)
        print(f"[ok] rejected {args.paper_id}")
        checkpoint = _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: reject paper {args.paper_id}",
            defer_post_actions=defer_post_actions,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare close-reading note assets for canonical literature and repos."""

from __future__ import annotations

import argparse
import inspect
import re
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11 import common as research_common
from research_v11.common import (
    bootstrap_workspace,
    clean_text,
    ensure_research_runtime,
    extract_pdf_context_pages,
    find_project_root,
    load_legacy_repo_facts,
    load_yaml,
    read_text_excerpt,
    research_root,
    utc_now_iso,
    write_text_if_changed,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
LITERATURE_TEMPLATE_PATH = SKILL_ROOT / "assets" / "literature-note-template.md"
REPO_TEMPLATE_PATH = SKILL_ROOT / "assets" / "repo-note-template.md"
LITERATURE_NOTE_MARKER = "<!-- literature-note-scaffold -->"
REPO_NOTE_MARKER = "<!-- repo-note-scaffold -->"
LITERATURE_MANUAL_HEADERS = ("## 工作笔记 Working Notes", "## Working Notes", "## Manual Notes")
REPO_MANUAL_HEADERS = ("## 工作笔记 Working Notes", "## Working Notes", "## Manual Notes")


def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def append_wiki_log_event(project_root: Path, event: dict[str, Any], *, generated_by: str) -> None:
    helper = getattr(research_common, "append_wiki_log_event", None)
    if not callable(helper):
        return
    event_type = str(event.get("type") or event.get("event_type") or "event").strip() or "event"
    title = str(event.get("title") or event_type).strip() or event_type
    summary = str(event.get("summary") or event.get("message") or "").strip()
    occurred_at = event.get("timestamp") or event.get("occurred_at") or utc_now_iso()
    metadata = {
        key: value
        for key, value in event.items()
        if key not in {"type", "event_type", "title", "summary", "message", "timestamp", "occurred_at"}
    }
    signature: inspect.Signature | None = None
    try:
        signature = inspect.signature(helper)
    except (TypeError, ValueError):
        signature = None
    parameters = signature.parameters if signature is not None else {}
    if "event_type" in parameters and "title" in parameters:
        helper(
            project_root,
            event_type,
            title,
            summary=summary,
            metadata=metadata,
            occurred_at=occurred_at,
            generated_by=generated_by,
        )
        return
    if "event" in parameters:
        helper(project_root=project_root, event=event, generated_by=generated_by)
        return
    raise TypeError(
        "Unsupported append_wiki_log_event helper signature; expected "
        "`(project_root, event_type, title, ...)` or `(project_root, event, ...)`."
    )


def rebuild_wiki_index_markdown(project_root: Path) -> None:
    helper = getattr(research_common, "rebuild_wiki_index_markdown", None)
    if not callable(helper):
        return
    try:
        helper(project_root)
    except TypeError:
        helper(project_root=project_root)


def _render_template(path: Path, context: dict[str, str]) -> str:
    note = path.read_text(encoding="utf-8")
    for key, value in context.items():
        note = note.replace(f"{{{{{key}}}}}", value)
    return note.rstrip() + "\n"


def _utf8_safe(text: str) -> str:
    """Drop surrogate code points emitted by some PDF extractors before writing files."""
    return str(text or "").encode("utf-8", errors="ignore").decode("utf-8")


def _format_inline_values(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "n/a"
    return ", ".join(f"`{value}`" for value in cleaned)


def _render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _normalize_extracted_abstract(text: str) -> str:
    text = str(text or "").replace("\u00ad", "")
    match = re.search(r"(?i)\babstract\b\s*[:\-\u2013\u2014 ]*", text)
    if match and match.start() <= 600:
        text = text[match.end() :]
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    return clean_text(text)


def _is_noisy_abstract(text: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return True
    if len(re.findall(r"/C\d{1,3}", cleaned)) >= 5:
        return True
    if sum(ch.isalpha() for ch in cleaned) < 40:
        return True
    return False


def _clean_capture_excerpt(entry_root: Path, limit: int = 8000) -> str:
    capture_path = entry_root / "source" / "capture.md"
    if not capture_path.exists():
        return ""
    text = capture_path.read_text(encoding="utf-8", errors="ignore")[:limit]
    text = re.sub(r"(?s)^# Capture\s+", "", text)
    text = re.sub(r"- URL: .*?\n", "", text)
    text = re.sub(r"- Captured At: .*?\n", "", text)
    return clean_text(text)


def _literature_working_notes(note_path: Path) -> str:
    default_block = (
        "## 工作笔记 Working Notes\n\n"
        "- 读完原文和可选的辅助上下文后，再把上面的占位内容替换成正式笔记。\n"
        "- 如果你想保留快速审计线索，可以在这里记录具体页码、章节和原文证据。\n"
    )
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in LITERATURE_MANUAL_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                legacy_default = (
                    "## Working Notes\n\n"
                    "- Manual follow-up: verify motivation, method details, results, caveats, and future-work guesses against the full paper."
                )
                if preserved and preserved != legacy_default:
                    return preserved
    return default_block


def _repo_working_notes(note_path: Path) -> str:
    default_block = (
        "## 工作笔记 Working Notes\n\n"
        "- 读完 README、主入口文件和可选辅助上下文后，再把上面的占位内容替换成正式笔记。\n"
        "- 如果你想保留后续复用线索，可以在这里记录具体文件证据和未解决的架构问题。\n"
    )
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in REPO_MANUAL_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                legacy_default = (
                    "## Working Notes\n\n"
                    "- Manual follow-up: verify architecture, runnable workflows, strengths, risks, and extension points against the real source tree."
                )
                if preserved and preserved != legacy_default:
                    return preserved
    return default_block


def _is_generated_note(text: str, marker: str, legacy_phrase: str) -> bool:
    normalized = str(text or "")
    return marker in normalized or legacy_phrase in normalized


def _pdf_context_block(entry_root: Path) -> str:
    pdf_path = entry_root / "source" / "primary.pdf"
    if not pdf_path.exists():
        return "## PDF 摘录 PDF Excerpts\n\n该条目当前没有 `source/primary.pdf`。\n"
    payload = extract_pdf_context_pages(pdf_path, front_limit=8, back_limit=4, per_page_char_limit=3200)
    lines = [
        "## PDF 摘录 PDF Excerpts",
        "",
        "- 原始 PDF: `source/primary.pdf`",
        f"- 检测到总页数: `{payload.get('total_pages') or 'unknown'}`",
        f"- 纳入摘录页码: `{', '.join(str(item.get('page')) for item in payload.get('pages', [])) or 'none'}`",
    ]
    for item in payload.get("pages", []):
        text = clean_text(str(item.get("text") or ""))
        if not text:
            continue
        lines.extend(["", f"### 第 {item['page']} 页", "", text])
    return "\n".join(lines).rstrip() + "\n"


def build_literature_context(entry_root: Path, metadata: dict[str, Any]) -> str:
    source_id = str(metadata.get("id") or entry_root.name)
    abstract = _normalize_extracted_abstract(str(metadata.get("abstract") or ""))
    if _is_noisy_abstract(abstract):
        abstract = ""
    capture_excerpt = _clean_capture_excerpt(entry_root)
    authors = [str(author).strip() for author in metadata.get("authors", []) if str(author).strip()]
    lines = [
        f"# 精读上下文 Close-Reading Context: {metadata.get('canonical_title') or source_id}",
        "",
        f"- 来源 ID Source ID: `{source_id}`",
        "- 笔记目标: `note.md`",
        "- 辅助上下文: `note-context.md`",
        f"- Source kind: `{metadata.get('source_kind') or 'paper'}`",
    ]
    if authors:
        lines.append(f"- 作者 Authors: {', '.join(authors)}")
    if metadata.get("year"):
        lines.append(f"- 年份 Year: `{metadata['year']}`")
    if metadata.get("canonical_url"):
        lines.append(f"- 链接 URL: {metadata['canonical_url']}")
    lines.extend(
        [
            "",
            "## 写作目标 Writing Targets",
            "",
            "- 用你自己的话总结研究动机、方法主线、具体创新点、实验结果说明了什么、可改进之处，以及能长出的新 idea。",
            "- 如果有 PDF，优先依据正文证据而不是只依据摘要措辞。",
            "- 只要超出了作者原文明示的结论，就明确标注为你的推断。",
            "",
            "## 摘要 Abstract",
            "",
            abstract or "没有抽取到干净摘要，请结合下面的 PDF 摘录和落地页文本继续阅读。",
            "",
        ]
    )
    if capture_excerpt:
        lines.extend(["## 落地页摘录 Landing / Capture Excerpt", "", capture_excerpt, ""])
    lines.append(_pdf_context_block(entry_root).rstrip())
    return "\n".join(lines).rstrip() + "\n"


def build_literature_scaffold(entry_root: Path, metadata: dict[str, Any], *, with_context: bool = False) -> str:
    source_id = str(metadata.get("id") or entry_root.name)
    authors = [str(author).strip() for author in metadata.get("authors", []) if str(author).strip()]
    abstract = _normalize_extracted_abstract(str(metadata.get("abstract") or ""))
    if _is_noisy_abstract(abstract):
        abstract = _clean_capture_excerpt(entry_root, limit=5000) or "摘要抽取质量较差，请直接检查 PDF 或落地页。"
    retrieval_lines = [
        f"- 检索 tags: {_format_inline_values(metadata.get('tags', []))}",
        f"- 检索 topics: {_format_inline_values(metadata.get('topics', []))}",
    ]
    if authors:
        retrieval_lines.append(f"- 作者线索: `{authors[0]}`")
    if metadata.get("year"):
        retrieval_lines.append(f"- 时间线索: `{metadata['year']}`")
    source_reading_coverage = [
        f"- 原始 PDF: {'`source/primary.pdf`' if (entry_root / 'source' / 'primary.pdf').exists() else 'not available'}",
        f"- 落地页摘录: {'`source/capture.md`' if (entry_root / 'source' / 'capture.md').exists() else 'not available'}",
        f"- 辅助摘要: {'`note-context.md`' if with_context else '按需使用 `--with-context` 生成'}",
        "- 定稿前至少通读摘要、引言/问题设定、方法、实验/结果，以及结论/局限部分。",
    ]
    context = {
        "note_marker": LITERATURE_NOTE_MARKER,
        "title": str(metadata.get("canonical_title") or source_id),
        "source_id": source_id,
        "source_kind": str(metadata.get("source_kind") or "paper"),
        "year": str(metadata.get("year") or "unknown"),
        "authors": ", ".join(authors) if authors else "n/a",
        "canonical_url": str(metadata.get("canonical_url") or "n/a"),
        "tags": _format_inline_values(metadata.get("tags", [])),
        "topics": _format_inline_values(metadata.get("topics", [])),
        "source_reading_coverage": "\n".join(source_reading_coverage),
        "executive_summary": _render_bullets(
            [
                "完成精读后，用 4-8 句写出能让人快速进入论文的总结。",
                "至少回答：作者想解决什么、核心方法是什么、最硬的实验支撑是什么、最大的保留意见是什么。",
            ]
        ),
        "motivation": _render_bullets(
            [
                "解释作者为什么非做这篇工作不可：它想补哪个缺口、绕开什么限制、解决什么痛点。",
                "记录真正影响结论成立的前提假设，而不是泛泛复述背景。",
            ]
        ),
        "method_overview": _render_bullets(
            [
                "用尽量直白的话写出方法主线：输入是什么、经过哪些关键模块、输出是什么、训练和推理怎么闭环。",
                "优先解释真正决定性能的模块、接口和信息流，而不是把所有细节平铺。",
            ]
        ),
        "innovations": _render_bullets(
            [
                "用你自己的话列出这篇论文到底新在哪里。",
                "把核心创新、重要但次级的工程技巧、以及其实不算创新的部分区分开。",
            ]
        ),
        "results_takeaways": _render_bullets(
            [
                "不要只抄 headline 指标；要说明这些实验究竟证明了什么，以及还没有证明什么。",
                "指出最关键的 baseline、ablation、失败案例或泛化结果，它们分别支撑了哪条核心论点。",
            ]
        ),
        "improvement_opportunities": _render_bullets(
            [
                "优先记录作者自己承认的局限、实验盲区和方法短板。",
                "如果你补充自己的改进想法，请明确写出它针对的是哪一个薄弱点，并标注为阅读者推断。",
            ]
        ),
        "idea_seeds": _render_bullets(
            [
                "先记录论文自己显式提出的 future work 或自然延伸方向。",
                "再补充 2-5 个基于当前工作区真正可生长的新 idea，写清楚想改哪一块、预期收益是什么、最先怎么验证。",
            ]
        ),
        "retrieval_cues": "\n".join(retrieval_lines),
        "abstract": abstract or "尚未抽取到可用摘要。",
        "working_notes_block": _literature_working_notes(entry_root / "note.md"),
    }
    return _render_template(LITERATURE_TEMPLATE_PATH, context)


def _clean_repo_context(text: str) -> str:
    text = str(text or "").replace("\r", "")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line.startswith("#") or line.startswith("![") or line.startswith("<img") or line.startswith(">"):
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"https?://\S+", " ", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        if re.fullmatch(r"[-*_=\s]+", line):
            continue
        cleaned_lines.append(clean_text(line))
    return "\n".join(cleaned_lines).strip()


def _categorize_entrypoints(facts: dict[str, Any]) -> dict[str, list[str]]:
    categories = {"train": [], "eval": [], "deploy": [], "data": [], "other": []}
    for item in facts.get("entrypoints", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        lowered = path.lower()
        if any(token in lowered for token in ("train", "finetune", "fit")):
            categories["train"].append(path)
        elif any(token in lowered for token in ("eval", "benchmark", "rollout", "test")):
            categories["eval"].append(path)
        elif any(token in lowered for token in ("deploy", "serve", "server", "real", "onnx", "tensorrt", "export")):
            categories["deploy"].append(path)
        elif any(token in lowered for token in ("data", "convert", "dataset", "record", "collect", "prepare")):
            categories["data"].append(path)
        else:
            categories["other"].append(path)
    return categories


def _select_repo_context_files(source_root: Path, facts: dict[str, Any]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def add(rel_path: str) -> None:
        rel = str(rel_path or "").strip()
        if not rel or rel in seen or not (source_root / rel).exists():
            return
        seen.add(rel)
        selected.append(rel)

    readme = next(iter(sorted(source_root.glob("README*"))), None)
    if readme:
        add(readme.relative_to(source_root).as_posix())

    categorized = _categorize_entrypoints(facts)
    for bucket, limit in (("train", 2), ("eval", 1), ("deploy", 1), ("data", 1), ("other", 2)):
        for rel_path in categorized[bucket][:limit]:
            add(rel_path)
    return selected[:8]


def _context_language(path: Path) -> str:
    return {
        ".py": "python",
        ".sh": "bash",
        ".zsh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".json": "json",
        ".md": "markdown",
    }.get(path.suffix.lower(), "")


def build_repo_context(entry_root: Path, summary: dict[str, Any], facts: dict[str, Any]) -> str:
    repo_id = str(summary.get("repo_id") or entry_root.name)
    source_root = entry_root / "source"
    readme = next(iter(sorted(source_root.glob("README*"))), None)
    readme_excerpt = _clean_repo_context(read_text_excerpt(readme, limit=12000) if readme else "")
    selected_files = _select_repo_context_files(source_root, facts)
    lines = [
        f"# 精读上下文 Close-Reading Context: {summary.get('repo_name') or repo_id}",
        "",
        f"- 仓库 ID Repo ID: `{repo_id}`",
        "- 笔记目标: `repo-notes.md`",
        "- 辅助上下文: `repo-note-context.md`",
        f"- 远端 Remote: {summary.get('canonical_remote') or 'n/a'}",
        f"- 主要语言 Primary language: `{summary.get('primary_language') or facts.get('primary_language') or 'unknown'}`",
        f"- 仓库类型 Repo type: `{summary.get('repo_type') or facts.get('repo_type_hint') or 'unknown'}`",
        "",
        "## 写作目标 Writing Targets",
        "",
        "- 改写 `repo-notes.md` 前，先读 README 和有代表性的 train/eval/deploy 入口。",
        "- 聚焦这个仓库是做什么的、主流程怎么组织、哪里可复用、哪里仍然有风险或歧义。",
        "- 所有判断都尽量落在 README、可见入口文件和下面摘录的源码片段上。",
        "",
        "## 快照线索 Snapshot Cues",
        "",
        f"- 框架 Frameworks: {_format_inline_values(summary.get('frameworks', []))}",
        f"- 关键目录 Key dirs: {_format_inline_values(facts.get('key_dirs', []))}",
        f"- 配置根目录 Config roots: {_format_inline_values(facts.get('config_roots', []))}",
        f"- 文档目录 Docs dirs: {_format_inline_values(facts.get('docs_dirs', []))}",
        f"- 测试目录 Test dirs: {_format_inline_values(facts.get('test_dirs', []))}",
    ]
    if readme_excerpt:
        lines.extend(["", "## README 摘录 README Excerpt", "", readme_excerpt[:10000]])
    if selected_files:
        lines.extend(["", "## 选定文件摘录 Selected File Excerpts", ""])
        for rel_path in selected_files:
            path = source_root / rel_path
            excerpt = read_text_excerpt(path, limit=2800).rstrip()
            if not excerpt:
                continue
            lines.extend([f"### `{rel_path}`", "", f"```{_context_language(path)}".rstrip(), excerpt, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def build_repo_scaffold(entry_root: Path, summary: dict[str, Any], facts: dict[str, Any], *, with_context: bool = False) -> str:
    repo_id = str(summary.get("repo_id") or entry_root.name)
    source_root = entry_root / "source"
    selected_files = _select_repo_context_files(source_root, facts)
    entrypoint_lines = []
    for item in facts.get("entrypoints", [])[:5]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if path:
            entrypoint_lines.append(f"- `{path}` ({kind or 'entrypoint'})")
    if not entrypoint_lines:
        entrypoint_lines = ["- 未检测到明显入口"]
    structure_lines = [
        f"- Key dirs: {_format_inline_values(facts.get('key_dirs', []))}",
        f"- Config roots: {_format_inline_values(facts.get('config_roots', []))}",
        f"- Docs dirs: {_format_inline_values(facts.get('docs_dirs', []))}",
        f"- Test dirs: {_format_inline_values(facts.get('test_dirs', []))}",
    ]
    retrieval_lines = [
        f"- 检索 tags: {_format_inline_values(summary.get('tags', []))}",
        f"- 检索 topics: {_format_inline_values(summary.get('topics', []))}",
        f"- Framework hints: {_format_inline_values(summary.get('frameworks', []))}",
        f"- 仓库类型 Repo type: `{summary.get('repo_type') or facts.get('repo_type_hint') or 'unknown'}`",
        f"- Owner/name: `{summary.get('owner_name') or summary.get('repo_name') or repo_id}`",
    ]
    reading_lines = [
        f"- README: {'available' if next(iter(sorted(source_root.glob('README*'))), None) else 'missing'}",
        f"- 辅助摘要: {'`repo-note-context.md`' if with_context else '按需使用 `--with-context` 生成'}",
        f"- 建议下一步检查文件: {_format_inline_values(selected_files)}",
        "- 如果仓库暴露了 train/eval/deploy 入口，定稿前至少读一类入口文件。",
    ]
    context = {
        "note_marker": REPO_NOTE_MARKER,
        "repo_name": str(summary.get("repo_name") or repo_id),
        "repo_id": repo_id,
        "canonical_remote": str(summary.get("canonical_remote") or "n/a"),
        "import_type": str(summary.get("import_type") or "unknown"),
        "primary_language": str(summary.get("primary_language") or facts.get("primary_language") or "unknown"),
        "repo_type": str(summary.get("repo_type") or facts.get("repo_type_hint") or "unknown"),
        "frameworks": _format_inline_values(summary.get("frameworks", [])),
        "tags": _format_inline_values(summary.get("tags", [])),
        "topics": _format_inline_values(summary.get("topics", [])),
        "head_commit": str(summary.get("head_commit") or "n/a"),
        "source_reading_coverage": "\n".join(reading_lines),
        "executive_summary": _render_bullets(
            [
                "读完 README 和代表性源码后，用简洁专业的话总结这个仓库。",
                "说明它的范围、主工作流，以及对当前工作区的可复用价值。",
            ]
        ),
        "goal_scope": _render_bullets(
            [
                "说明这个仓库要解决什么问题、暴露了哪些主要交付物。",
                "指出它更偏训练代码、部署代码、数据工具，还是混合栈。",
            ]
        ),
        "architecture_analysis": _render_bullets(
            [
                "总结主要子系统边界，以及职责如何分布在不同包/脚本之间。",
                "指出配置根目录、核心模块和明显的集成缝。",
            ]
        ),
        "workflow_analysis": _render_bullets(
            [
                "沿着可运行路径解释：用户如何训练、评测或部署这个仓库。",
                "点出最重要的入口文件以及它们之间的 handoff。",
            ]
        ),
        "strengths": _render_bullets(
            ["记录这个仓库为什么值得复用，比如文档、模块化、测试覆盖或清晰接口。"]
        ),
        "limitations": _render_bullets(
            ["记录仍然存在的风险或歧义，比如缺测试、缺配置、环境脆弱或控制流不清楚。"]
        ),
        "future_work": _render_bullets(
            [
                "如果这个仓库可能成为实现底座，列出下一步值得看的文件或扩展点。",
                "记录哪些验证或重构会显著降低复用风险。",
            ]
        ),
        "retrieval_cues": "\n".join(retrieval_lines),
        "structure_cues": "\n".join(structure_lines),
        "entrypoints": "\n".join(entrypoint_lines),
        "working_notes_block": _repo_working_notes(entry_root / "repo-notes.md"),
    }
    return _render_template(REPO_TEMPLATE_PATH, context)


def prepare_literature_note(
    project_root: Path,
    source_ids: list[str],
    *,
    rewrite_generated_notes: bool = False,
    with_context: bool = False,
) -> int:
    changed = 0
    literature_root = research_root(project_root) / "library" / "literature"
    for source_id in source_ids:
        entry_root = literature_root / source_id
        metadata_path = entry_root / "metadata.yaml"
        metadata = load_yaml(metadata_path, default={})
        if not isinstance(metadata, dict) or not metadata.get("id"):
            raise SystemExit(f"Invalid literature metadata: {metadata_path}")
        if with_context:
            context_path = entry_root / "note-context.md"
            context_text = _utf8_safe(build_literature_context(entry_root, metadata))
            before_context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
            write_text_if_changed(context_path, context_text)
            if context_text != before_context:
                changed += 1
        note_path = entry_root / "note.md"
        should_write = not note_path.exists()
        if not should_write and rewrite_generated_notes:
            existing = note_path.read_text(encoding="utf-8")
            should_write = _is_generated_note(existing, LITERATURE_NOTE_MARKER, "Auto-generated analysis note.")
        if should_write:
            note_text = _utf8_safe(build_literature_scaffold(entry_root, metadata, with_context=with_context))
            before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            write_text_if_changed(note_path, note_text)
            if note_text != before_note:
                changed += 1
    return changed


def prepare_repo_note(
    project_root: Path,
    repo_ids: list[str],
    *,
    rewrite_generated_notes: bool = False,
    with_context: bool = False,
) -> int:
    changed = 0
    repo_root = research_root(project_root) / "library" / "repos"
    for repo_id in repo_ids:
        entry_root = repo_root / repo_id
        summary_path = entry_root / "summary.yaml"
        summary = load_yaml(summary_path, default={})
        if not isinstance(summary, dict) or not summary.get("repo_id"):
            raise SystemExit(f"Invalid repo summary: {summary_path}")
        facts = load_legacy_repo_facts(project_root, entry_root / "source")
        if with_context:
            context_path = entry_root / "repo-note-context.md"
            context_text = _utf8_safe(build_repo_context(entry_root, summary, facts))
            before_context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
            write_text_if_changed(context_path, context_text)
            if context_text != before_context:
                changed += 1
        note_path = entry_root / "repo-notes.md"
        should_write = not note_path.exists()
        if not should_write and rewrite_generated_notes:
            existing = note_path.read_text(encoding="utf-8")
            should_write = _is_generated_note(existing, REPO_NOTE_MARKER, "Auto-generated repo analysis note.")
        if should_write:
            note_text = _utf8_safe(build_repo_scaffold(entry_root, summary, facts, with_context=with_context))
            before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            write_text_if_changed(note_path, note_text)
            if note_text != before_note:
                changed += 1
    return changed


def prepare_literature_note_cmd(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    source_ids = list(args.source_id)
    changed = prepare_literature_note(
        project_root,
        source_ids,
        rewrite_generated_notes=args.rewrite_generated_notes,
        with_context=args.with_context,
    )
    artifacts: list[str] = []
    literature_root = research_root(project_root) / "library" / "literature"
    for source_id in source_ids:
        entry_root = literature_root / source_id
        note_path = entry_root / "note.md"
        metadata_path = entry_root / "metadata.yaml"
        if metadata_path.exists():
            artifacts.append(relative_path(project_root, metadata_path))
        if note_path.exists():
            artifacts.append(relative_path(project_root, note_path))
        if args.with_context:
            context_path = entry_root / "note-context.md"
            if context_path.exists():
                artifacts.append(relative_path(project_root, context_path))
    append_wiki_log_event(
        project_root,
        {
            "source_skill": "research-note-author",
            "event_type": "note",
            "title": "Literature note assets prepared",
            "summary": f"Prepared literature note assets for {len(source_ids)} source(s); changed {changed} file(s).",
            "source_id": source_ids[0] if len(source_ids) == 1 else "",
            "source_ids": source_ids,
            "artifacts": sorted({item for item in artifacts if item}),
        },
        generated_by="research-note-author",
    )
    rebuild_wiki_index_markdown(project_root)
    print(f"[ok] prepared literature note assets ({changed} file updates)")
    return 0


def prepare_repo_note_cmd(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    repo_ids = list(args.repo_id)
    changed = prepare_repo_note(
        project_root,
        repo_ids,
        rewrite_generated_notes=args.rewrite_generated_notes,
        with_context=args.with_context,
    )
    artifacts: list[str] = []
    repo_root = research_root(project_root) / "library" / "repos"
    for repo_id in repo_ids:
        entry_root = repo_root / repo_id
        note_path = entry_root / "repo-notes.md"
        summary_path = entry_root / "summary.yaml"
        if summary_path.exists():
            artifacts.append(relative_path(project_root, summary_path))
        if note_path.exists():
            artifacts.append(relative_path(project_root, note_path))
        if args.with_context:
            context_path = entry_root / "repo-note-context.md"
            if context_path.exists():
                artifacts.append(relative_path(project_root, context_path))
    append_wiki_log_event(
        project_root,
        {
            "source_skill": "research-note-author",
            "event_type": "note",
            "title": "Repository note assets prepared",
            "summary": f"Prepared repo note assets for {len(repo_ids)} repo(s); changed {changed} file(s).",
            "repo_id": repo_ids[0] if len(repo_ids) == 1 else "",
            "repo_ids": repo_ids,
            "artifacts": sorted({item for item in artifacts if item}),
        },
        generated_by="research-note-author",
    )
    rebuild_wiki_index_markdown(project_root)
    print(f"[ok] prepared repo note assets ({changed} file updates)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare close-reading note assets for canonical research entries.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_cmd = subparsers.add_parser("prepare-literature-note", help="Prepare a scaffold note for literature entries, with optional note-context.md")
    paper_cmd.add_argument("--source-id", action="append", required=True, help="Canonical literature source ID")
    paper_cmd.add_argument("--rewrite-generated-notes", action="store_true", help="Rewrite note.md only if it still looks generated")
    paper_cmd.add_argument("--with-context", action="store_true", help="Also generate note-context.md for reuse or audit")
    paper_cmd.set_defaults(func=prepare_literature_note_cmd)

    repo_cmd = subparsers.add_parser("prepare-repo-note", help="Prepare a scaffold note for repo entries, with optional repo-note-context.md")
    repo_cmd.add_argument("--repo-id", action="append", required=True, help="Canonical repo ID")
    repo_cmd.add_argument("--rewrite-generated-notes", action="store_true", help="Rewrite repo-notes.md only if it still looks generated")
    repo_cmd.add_argument("--with-context", action="store_true", help="Also generate repo-note-context.md for reuse or audit")
    repo_cmd.set_defaults(func=prepare_repo_note_cmd)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = find_project_root()
    require_pdf = args.command == "prepare-literature-note"
    ensure_research_runtime(project_root, "research-note-author", require_pdf_backend=require_pdf)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

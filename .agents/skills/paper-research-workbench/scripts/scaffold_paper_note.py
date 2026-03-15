#!/usr/bin/env python3
"""Generate Chinese first-pass note, idea, and feasibility docs for papers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _paper_utils import (
    compact_text,
    ensure_dir,
    find_project_root,
    find_skill_root,
    load_yaml,
    pick_sentence,
    resolve_from_project_or_skill,
    write_text_if_changed,
)


OLD_TEMPLATE_MARKERS = {
    "note": (
        "# Summary",
        "- Problem:",
        "Add direct facts from the PDF only.",
        "# Evidence Notes",
    ),
    "ideas": (
        "# Idea Backlog",
        "- Name:",
        "- One-line pitch:",
        "# Candidate Experiments",
    ),
    "feasibility": (
        "# Feasibility Checklist",
        "Core assumption is testable in your environment:",
        "# Go / No-Go Decision",
    ),
}


def project_root_from_script() -> Path:
    return find_project_root(Path(__file__).resolve())


def render(template: str, context: dict[str, str]) -> str:
    output = template
    for key, value in context.items():
        output = output.replace(f"{{{{{key}}}}}", value)
    return output


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[1]
    return text


def yaml_inline_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def today_string() -> str:
    return str(__import__("datetime").date.today())


def load_metadata_records(papers_root: Path, selected_paper_id: str | None) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if not isinstance(payload, dict):
            continue
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            continue
        if selected_paper_id and selected_paper_id != paper_id:
            continue
        records.append((metadata_path.parent, payload))
    return records


def load_relationship_lookup(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = load_yaml(path)
    if not isinstance(payload, dict):
        return {}
    neighbors: dict[str, list[dict[str, Any]]] = {}
    for edge in payload.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_paper_id") or "")
        target = str(edge.get("target_paper_id") or "")
        if not source or not target:
            continue
        forward = {
            "paper_id": target,
            "score": float(edge.get("score") or 0.0),
            "shared_topics": edge.get("shared_topics") or [],
            "shared_tags": edge.get("shared_tags") or [],
        }
        reverse = dict(forward)
        reverse["paper_id"] = source
        neighbors.setdefault(source, []).append(forward)
        neighbors.setdefault(target, []).append(reverse)
    for entries in neighbors.values():
        entries.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("paper_id") or "")))
    return neighbors


def load_sections(paper_dir: Path) -> list[str]:
    path = paper_dir / "_artifacts" / "sections.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [str(item) for item in payload if isinstance(item, str)]
    if isinstance(payload, dict):
        sections = payload.get("sections")
        if isinstance(sections, list):
            return [str(item) for item in sections if isinstance(item, str)]
    return []


def looks_like_placeholder(path: Path, kind: str, force: bool) -> bool:
    if force or not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return True
    if "{{" in text:
        return True
    if any(marker in text for marker in OLD_TEMPLATE_MARKERS[kind]):
        return True
    if not re.search(r'(?m)^status:\s*["\']auto-generated["\']\s*$', text):
        return False
    body = strip_frontmatter(text)
    compact = body.strip()
    if len(compact) < 260:
        return True
    if kind == "note":
        if re.search(r"(?m)^- (研究问题|核心方法|主要结论|自动判断的局限)：\s*$", body):
            return True
        if body.count("- ") < 10 or body.count("## ") < 3:
            return True
    elif kind == "ideas":
        if re.search(r"(?m)^- (名称|方向|可执行动作|预期收益|主要风险)：\s*$", body):
            return True
        if body.count("## Idea") >= 3 and body.count("- ") < 10:
            return True
    elif kind == "feasibility":
        if re.search(r"(?m)^- (总体建议|判断依据)：\s*$", body):
            return True
        if body.count("- ") < 8:
            return True
    return False


def first_author(authors: list[str]) -> str:
    return authors[0] if authors else "未知作者"


def title_lookup(records: list[tuple[Path, dict[str, Any]]]) -> dict[str, str]:
    return {
        str(payload.get("paper_id") or ""): str(payload.get("title") or payload.get("paper_id") or "")
        for _, payload in records
        if payload.get("paper_id")
    }


def topic_text(values: list[str]) -> str:
    return "、".join(values) if values else "未识别主题"


def tag_text(values: list[str]) -> str:
    return ", ".join(values) if values else "未识别标签"


def sentence_or_fallback(sentence: str, fallback: str, max_len: int = 220) -> str:
    if sentence:
        return compact_text(sentence, max_len=max_len)
    return fallback


def closest_neighbor_lines(
    *,
    paper_id: str,
    neighbors: dict[str, list[dict[str, Any]]],
    titles: dict[str, str],
) -> tuple[str, str]:
    entries = neighbors.get(paper_id, [])[:3]
    if not entries:
        return "- 未发现高置信相邻论文。", "当前库内尚未形成稳定邻居关系，后续可随着 corpus 扩充再观察。"

    bullets: list[str] = []
    short_lines: list[str] = []
    for item in entries:
        neighbor_id = str(item.get("paper_id") or "")
        title = titles.get(neighbor_id, neighbor_id)
        shared_topics = item.get("shared_topics") or []
        shared_tags = item.get("shared_tags") or []
        rationale_parts: list[str] = []
        if shared_topics:
            rationale_parts.append("共同主题=" + " / ".join(shared_topics))
        if shared_tags:
            rationale_parts.append("共同标签=" + " / ".join(shared_tags[:4]))
        rationale = "；".join(rationale_parts) if rationale_parts else "关系来自题目或年份接近"
        bullets.append(
            f"- `{neighbor_id}` | {title} | 关系分数={item.get('score')} | {rationale}"
        )
        short_lines.append(f"`{neighbor_id}`（{title}）")
    return "\n".join(bullets), "、".join(short_lines)


def infer_role(tags: list[str], topics: list[str]) -> str:
    if "action-tokenization" in tags or "flow-model" in tags:
        return "偏方法创新"
    if "open-world-generalization" in tags:
        return "偏开放环境泛化与部署"
    if "learning-from-experience" in tags:
        return "偏部署后持续学习"
    if "instruction-following" in tags or "vla" in tags:
        return "偏通用 VLA / 指令执行"
    if "robot-learning" in topics:
        return "偏机器人学习方法或系统"
    return "偏领域综述或系统工作"


def build_summary_problem(title: str, abstract: str, topics: list[str]) -> str:
    sentence = pick_sentence(
        abstract,
        ["however", "challenge", "poorly", "difficult", "require", "bottleneck"],
        fallback_index=0,
    )
    fallback = f"该工作围绕 {topic_text(topics)} 展开，核心关注点与标题“{title}”对应的问题设定有关。"
    if sentence:
        return f"摘要表明，该工作试图解决的问题是：{compact_text(sentence)}"
    return fallback


def build_summary_method(abstract: str, tags: list[str]) -> str:
    sentence = pick_sentence(
        abstract,
        ["we propose", "we present", "introduce", "our method", "our approach", "we release"],
        fallback_index=1,
    )
    fallback = f"从自动标签看，方法重心大致位于 {tag_text(tags)}，但具体模块和训练细节仍需结合正文确认。"
    if sentence:
        return f"摘要中的方法描述是：{compact_text(sentence)}"
    return fallback


def build_summary_result(abstract: str) -> str:
    sentence = pick_sentence(
        abstract,
        ["we show", "match", "improve", "reducing", "outperform", "scale", "enables"],
        fallback_index=2,
    )
    fallback = "摘要显示论文宣称获得了正向结果，但需要继续核对实验设置、baseline 和统计显著性。"
    if sentence:
        return f"摘要中的结果信号是：{compact_text(sentence)}"
    return fallback


def build_summary_limitation(
    *,
    urls: list[str],
    sections: list[str],
    abstract: str,
) -> str:
    missing: list[str] = []
    if not urls:
        missing.append("未发现显式项目链接")
    if "Limitations" not in sections:
        missing.append("未识别到 Limitations 章节")
    if "ablation" not in abstract.lower():
        missing.append("摘要未直接说明消融与失败案例")
    if not missing:
        return "解析结果没有明显缺口，但仍建议通读实验和局限章节后再下最终判断。"
    return "当前自动解析的主要缺口是：" + "；".join(missing) + "。"


def build_observed_bullets(
    *,
    payload: dict[str, Any],
    sections: list[str],
    neighbor_lines: str,
) -> str:
    abstract = str(payload.get("abstract") or "")
    sentences = [compact_text(sentence, 200) for sentence in re.split(r"(?<=[\.\?!])\s+", abstract) if sentence.strip()]
    abstract_bullets = sentences[:2]
    lines = [
        f"- 题目：{payload.get('title')}",
        f"- 作者与年份：{', '.join(payload.get('authors') or [])}；{payload.get('year') or '未知年份'}",
        f"- 自动标签：{tag_text(payload.get('tags') or [])}",
        f"- 自动主题：{topic_text(payload.get('topics') or [])}",
        f"- 原始 PDF：{(payload.get('source') or {}).get('pdf') or '未知'}",
    ]
    if sections:
        lines.append(f"- 已识别章节：{', '.join(sections)}")
    for index, sentence in enumerate(abstract_bullets, start=1):
        lines.append(f"- 摘要证据 {index}：{sentence}")
    if neighbor_lines:
        lines.append("- 关联最强论文：")
        lines.extend(neighbor_lines.splitlines())
    return "\n".join(lines)


def build_inferred_bullets(
    *,
    payload: dict[str, Any],
    neighbor_summary: str,
) -> str:
    tags = payload.get("tags") or []
    topics = payload.get("topics") or []
    role = infer_role(tags, topics)
    lines = [
        f"- 在当前库中，这篇论文的角色判断为：{role}。",
        f"- 如果把它放进现有论文库，它更像是围绕 {topic_text(topics)} 的一篇可复用方法节点。",
    ]
    if neighbor_summary:
        lines.append(f"- 建议与以下论文联读：{neighbor_summary}，优先看共同主题和不同标签带来的互补性。")
    if "action-tokenization" in tags and "vla" in tags:
        lines.append("- 这类工作通常适合作为高频控制、长时序决策和训练效率对比的切入点。")
    if "open-world-generalization" in tags:
        lines.append("- 这类工作通常更接近真实部署与分布外泛化问题，后续值得关注失败模式和恢复策略。")
    return "\n".join(lines)


def build_open_questions(
    *,
    payload: dict[str, Any],
    sections: list[str],
) -> str:
    lines = [
        "- 论文是否公开了代码、模型权重或数据处理脚本？",
        "- 实验使用的主要 benchmark、评测指标和 baseline 是什么？",
        "- 摘要里的提升是否来自模型结构、tokenization、数据规模还是训练策略？",
    ]
    if "Limitations" not in sections:
        lines.append("- 正文是否明确讨论 failure cases、部署边界和安全风险？")
    if not payload.get("doi"):
        lines.append("- 是否只有 arXiv 版本，后续是否存在正式发表版本需要跟踪？")
    return "\n".join(lines)


def build_repro_hooks(
    *,
    payload: dict[str, Any],
    sections: list[str],
    neighbor_summary: str,
) -> str:
    source = payload.get("source") or {}
    urls = payload.get("urls") or []
    lines = [
        f"- PDF 路径：{source.get('pdf') or '未知'}",
        f"- arXiv ID：{payload.get('arxiv_id') or '未识别'}",
        f"- DOI：{payload.get('doi') or '未识别'}",
        f"- 解析页数：{source.get('parsed_pages') or '未知'} / {source.get('pdf_pages') or '未知'}",
        f"- 章节线索：{', '.join(sections) if sections else '未识别'}",
        f"- 可见链接：{', '.join(urls) if urls else '未从 PDF 中提取到'}",
    ]
    if neighbor_summary:
        lines.append(f"- 可对照阅读的近邻论文：{neighbor_summary}")
    return "\n".join(lines)


def build_followup_ideas(
    *,
    payload: dict[str, Any],
    neighbor_summary: str,
) -> str:
    tags = payload.get("tags") or []
    topics = payload.get("topics") or []
    lines = [
        f"- 直接扩展：围绕 {tag_text(tags)} 设计一个更小规模但可复现的 ablation，先验证论文最关键的收益来源。",
        f"- 跨论文组合：结合 {neighbor_summary or '库内相邻论文'}，把共同主题 {topic_text(topics)} 下的互补方法拼成一个更完整的实验矩阵。",
        "- 高风险方向：把该工作最强的假设直接放到分布外任务、不同控制频率或更稀缺数据条件下，观察是否仍然成立。",
    ]
    return "\n".join(lines)


def build_idea_blocks(
    *,
    payload: dict[str, Any],
    neighbor_summary: str,
    titles: dict[str, str],
    neighbors: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    paper_id = str(payload.get("paper_id") or "")
    tags = payload.get("tags") or []
    topics = payload.get("topics") or []
    neighbor = neighbors.get(paper_id, [{}])[0]
    neighbor_id = str(neighbor.get("paper_id") or "")
    neighbor_title = titles.get(neighbor_id, neighbor_id) if neighbor_id else "暂无高置信相邻论文"

    idea_1 = "\n".join(
        [
            "- 名称：关键收益来源拆解实验",
            f"- 方向：围绕 {tag_text(tags)} 做最小可复现实验，确认论文主张到底来自结构改动、训练细节还是数据规模。",
            "- 可执行动作：先复做摘要中最核心的对比，再加一组简化 ablation。",
            "- 预期收益：快速判断这篇论文是否值得纳入你自己的方法栈。",
            "- 主要风险：如果正文缺少实现细节，复现实验可能需要较多工程猜测。",
        ]
    )

    idea_2 = "\n".join(
        [
            "- 名称：跨论文互补组合",
            f"- 方向：把当前论文与 {neighbor_title} 联合阅读，围绕共同主题 {topic_text(topics)} 做组合实验。",
            f"- 可执行动作：先对齐输入输出接口，再只替换一个关键模块，避免一次性改太多变量。",
            "- 预期收益：更容易做出比单篇复现更有新意、但仍可落地的中等风险项目。",
            "- 主要风险：两篇论文的训练设定和数据前提可能并不兼容。",
        ]
    )

    idea_3 = "\n".join(
        [
            "- 名称：面向真实部署的压力测试",
            "- 方向：把论文最强 claim 放到更长时序、更开放环境或更高控制频率下验证。",
            "- 可执行动作：设计一个小规模 stress test，只改变环境复杂度或动作频率中的一个变量。",
            "- 预期收益：更快识别这篇论文对真实机器人系统有没有外推价值。",
            "- 主要风险：需要你有稳定的 evaluation pipeline，否则很难归因。",
        ]
    )

    experiment_plan = "\n".join(
        [
            f"- 首轮建议：先在 {topic_text(topics)} 中选一个最贴近你现有资产的任务。",
            "- baseline：保留原论文最直接的 baseline，再加一个更简单的工程基线。",
            "- 成功标准：至少复现方向性收益，并能解释收益来源。",
            f"- 联读建议：{neighbor_summary or '先扩充 corpus，再决定联读对象。'}",
        ]
    )

    return {
        "IDEA_1": idea_1,
        "IDEA_2": idea_2,
        "IDEA_3": idea_3,
        "EXPERIMENT_PLAN": experiment_plan,
    }


def decision_payload(payload: dict[str, Any], sections: list[str], urls: list[str]) -> tuple[str, str, str]:
    tags = payload.get("tags") or []
    if urls and ("Experiments" in sections or "Results" in sections):
        return (
            "go",
            "建议推进",
            "论文同时具备可追踪链接和实验章节信号，适合作为近期可执行项目的候选。",
        )
    if "action-tokenization" in tags or "open-world-generalization" in tags or "learning-from-experience" in tags:
        return (
            "conditional-go",
            "条件性推进",
            "方向本身很值得做，但当前自动解析还无法确认代码可得性、实验细节和复现成本。",
        )
    return (
        "no-go",
        "暂缓推进",
        "目前更适合作为背景参考或对比阅读对象，除非你已经具备相应数据和评测基础设施。",
    )


def build_feasibility_blocks(
    *,
    payload: dict[str, Any],
    sections: list[str],
    neighbor_summary: str,
) -> dict[str, str]:
    urls = payload.get("urls") or []
    decision_key, decision_label, rationale = decision_payload(payload, sections, urls)
    checklist = "\n".join(
        [
            f"- 可复现性：{'中偏高' if urls else '中'}。{'已发现可追踪链接。' if urls else '还未发现明确项目链接。'}",
            f"- 数据准备度：中。当前仅能从标签推断任务方向为 {topic_text(payload.get('topics') or [])}，仍需核对 benchmark 和采集成本。",
            f"- 算力与硬件：{'中偏高' if 'vla' in (payload.get('tags') or []) else '中'}。VLA 或高频控制任务通常需要更完整的训练与评测资源。",
            f"- 评测清晰度：{'中偏高' if 'Experiments' in sections or 'Results' in sections else '中'}。需要继续确认 baseline 和 success metric。",
            "- 风险边界：需要在离线评测或安全约束充分的环境中先做小规模验证。",
        ]
    )
    effort_estimate = "\n".join(
        [
            "- 准备成本：中。主要花在读正文、对齐实验设定、补全实现细节。",
            "- 最小原型周期：约 3 到 10 天，取决于你是否已有相近数据和评测脚本。",
            "- 完整实验周期：约 2 到 6 周，取决于是否涉及机器人实机、长时序任务或新数据采集。",
        ]
    )
    preconditions = "\n".join(
        [
            "- 先核对正文中的训练细节、数据来源和 baseline。",
            "- 优先确认是否有代码、checkpoint 或可复现的伪代码线索。",
            f"- 如果要做跨论文组合，建议先联读：{neighbor_summary or '暂无明确近邻论文。'}",
            "- 在真正上机或大规模训练前，先做一个低成本 sanity check。",
        ]
    )
    return {
        "DECISION_KEY": decision_key,
        "DECISION_LABEL": decision_label,
        "DECISION_RATIONALE": rationale,
        "CHECKLIST": checklist,
        "EFFORT_ESTIMATE": effort_estimate,
        "PRECONDITIONS": preconditions,
    }


def note_context(
    *,
    payload: dict[str, Any],
    sections: list[str],
    neighbor_lines: str,
    neighbor_summary: str,
) -> dict[str, str]:
    title = str(payload.get("title") or payload.get("paper_id") or "")
    abstract = str(payload.get("abstract") or "")
    urls = payload.get("urls") or []
    return {
        "PAPER_ID": str(payload.get("paper_id") or ""),
        "TITLE": title,
        "YEAR": str(payload.get("year") or "null"),
        "ARXIV_ID": str(payload.get("arxiv_id") or ""),
        "DOI": str(payload.get("doi") or ""),
        "SOURCE_PDF": str((payload.get("source") or {}).get("pdf") or ""),
        "AUTHORS": ", ".join(payload.get("authors") or []),
        "TAGS_YAML": yaml_inline_list(payload.get("tags") or []),
        "TOPICS_YAML": yaml_inline_list(payload.get("topics") or []),
        "TODAY": today_string(),
        "AUTO_NOTICE": "> 自动生成初稿：该文件根据 metadata、abstract、章节线索和论文关系自动生成，适合快速筛选，不应替代全文精读。",
        "SUMMARY_PROBLEM": build_summary_problem(title, abstract, payload.get("topics") or []),
        "SUMMARY_METHOD": build_summary_method(abstract, payload.get("tags") or []),
        "SUMMARY_RESULT": build_summary_result(abstract),
        "SUMMARY_LIMITATION": build_summary_limitation(urls=urls, sections=sections, abstract=abstract),
        "OBSERVED_BULLETS": build_observed_bullets(payload=payload, sections=sections, neighbor_lines=neighbor_lines),
        "INFERRED_BULLETS": build_inferred_bullets(payload=payload, neighbor_summary=neighbor_summary),
        "OPEN_QUESTIONS": build_open_questions(payload=payload, sections=sections),
        "REPRO_HOOKS": build_repro_hooks(payload=payload, sections=sections, neighbor_summary=neighbor_summary),
        "FOLLOWUP_IDEAS": build_followup_ideas(payload=payload, neighbor_summary=neighbor_summary),
    }


def idea_context(
    *,
    payload: dict[str, Any],
    neighbor_summary: str,
    titles: dict[str, str],
    neighbors: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    context = {
        "PAPER_ID": str(payload.get("paper_id") or ""),
        "TITLE": str(payload.get("title") or payload.get("paper_id") or ""),
        "TODAY": today_string(),
        "AUTO_NOTICE": "> 自动生成初稿：这些 idea 用于快速发散，建议结合你的现有平台、数据和研究目标再做筛选。",
    }
    context.update(
        build_idea_blocks(
            payload=payload,
            neighbor_summary=neighbor_summary,
            titles=titles,
            neighbors=neighbors,
        )
    )
    return context


def feasibility_context(
    *,
    payload: dict[str, Any],
    sections: list[str],
    neighbor_summary: str,
) -> dict[str, str]:
    context = {
        "PAPER_ID": str(payload.get("paper_id") or ""),
        "TITLE": str(payload.get("title") or payload.get("paper_id") or ""),
        "TODAY": today_string(),
        "AUTO_NOTICE": "> 自动生成初判：该结论偏保守，主要用于帮助你排序，不应替代阅读全文后的人工判断。",
    }
    context.update(
        build_feasibility_blocks(
            payload=payload,
            sections=sections,
            neighbor_summary=neighbor_summary,
        )
    )
    return context


def write_if_needed(path: Path, content: str, kind: str, force: bool) -> bool:
    if not looks_like_placeholder(path, kind, force):
        return False
    return write_text_if_changed(path, content.rstrip() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Chinese first-pass notes and ideas for parsed papers.",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Paper root path (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--template-root",
        default="assets/templates",
        help="Template root path",
    )
    parser.add_argument(
        "--user-root",
        default="doc/papers/user",
        help="User-readable root path (default: doc/papers/user)",
    )
    parser.add_argument(
        "--relationships-path",
        default="doc/papers/index/relationships.yaml",
        help="Relationship file path",
    )
    parser.add_argument(
        "--paper-id",
        default=None,
        help="Only scaffold one paper id",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even non-placeholder generated content",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    skill_root = find_skill_root(Path(__file__).resolve())
    papers_root = (project_root / args.papers_root).resolve()
    template_root = resolve_from_project_or_skill(
        args.template_root,
        project_root=project_root,
        skill_root=skill_root,
    ).resolve()
    relationships_path = (project_root / args.relationships_path).resolve()
    user_root = (project_root / args.user_root).resolve()

    templates = {
        "note": (template_root / "paper-note-template.md").read_text(encoding="utf-8"),
        "ideas": (template_root / "idea-template.md").read_text(encoding="utf-8"),
        "feasibility": (template_root / "feasibility-template.md").read_text(encoding="utf-8"),
    }
    all_records = load_metadata_records(papers_root, None)
    if not all_records:
        raise SystemExit(f"No paper metadata found under: {papers_root}")
    records = [
        item
        for item in all_records
        if args.paper_id is None or str(item[1].get("paper_id") or "") == args.paper_id
    ]
    if not records:
        raise SystemExit(f"Paper id not found under {papers_root}: {args.paper_id}")

    neighbors = load_relationship_lookup(relationships_path)
    titles = title_lookup(all_records)
    written = 0

    for paper_dir, payload in records:
        ensure_dir(paper_dir)
        paper_id = str(payload.get("paper_id") or "")
        user_paper_dir = user_root / "papers" / paper_id
        ensure_dir(user_paper_dir)
        sections = load_sections(paper_dir)
        neighbor_lines, neighbor_summary = closest_neighbor_lines(
            paper_id=paper_id,
            neighbors=neighbors,
            titles=titles,
        )

        note_text = render(
            templates["note"],
            note_context(
                payload=payload,
                sections=sections,
                neighbor_lines=neighbor_lines,
                neighbor_summary=neighbor_summary,
            ),
        )
        if write_if_needed(user_paper_dir / "note.md", note_text, "note", args.force):
            written += 1

        ideas_text = render(
            templates["ideas"],
            idea_context(
                payload=payload,
                neighbor_summary=neighbor_summary,
                titles=titles,
                neighbors=neighbors,
            ),
        )
        if write_if_needed(user_paper_dir / "ideas.md", ideas_text, "ideas", args.force):
            written += 1

        feasibility_text = render(
            templates["feasibility"],
            feasibility_context(
                payload=payload,
                sections=sections,
                neighbor_summary=neighbor_summary,
            ),
        )
        if write_if_needed(user_paper_dir / "feasibility.md", feasibility_text, "feasibility", args.force):
            written += 1

    print(f"[OK] paper notes refreshed: files_written={written}")


if __name__ == "__main__":
    main()

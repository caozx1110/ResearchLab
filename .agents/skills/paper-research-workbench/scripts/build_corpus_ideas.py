#!/usr/bin/env python3
"""Build corpus-level research ideas in human-readable and AI-readable formats."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from _paper_utils import (
    compact_text,
    ensure_dir,
    find_project_root,
    load_yaml,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
)


def project_root_from_script() -> Path:
    return find_project_root(Path(__file__).resolve())


def load_metadata_records(papers_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if isinstance(payload, dict) and payload.get("paper_id"):
            records.append(payload)
    return records


def build_neighbor_map(relationships: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    neighbor_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in relationships.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_paper_id") or "")
        target = str(edge.get("target_paper_id") or "")
        if not source or not target:
            continue
        payload = {
            "paper_id": target,
            "score": float(edge.get("score") or 0.0),
            "shared_topics": edge.get("shared_topics") or [],
            "shared_tags": edge.get("shared_tags") or [],
        }
        reverse = dict(payload)
        reverse["paper_id"] = source
        neighbor_map[source].append(payload)
        neighbor_map[target].append(reverse)
    for values in neighbor_map.values():
        values.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("paper_id") or "")))
    return dict(neighbor_map)


def topic_counts(records: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        for topic in record.get("topics") or []:
            counts[str(topic)] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def tag_buckets(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for tag in record.get("tags") or []:
            buckets[str(tag)].append(record)
    return dict(buckets)


def choose_papers(bucket: dict[str, list[dict[str, Any]]], *tags: str) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for tag in tags:
        for record in bucket.get(tag, []):
            paper_id = str(record.get("paper_id") or "")
            if paper_id:
                selected[paper_id] = record
    return sorted(selected.values(), key=lambda item: (item.get("year") or 0, item.get("paper_id") or ""), reverse=True)


def default_topic(records: list[dict[str, Any]]) -> str:
    top = topic_counts(records)
    return top[0][0] if top else "robotics"


def idea_payloads(records: list[dict[str, Any]], relationships: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = tag_buckets(records)
    neighbor_map = build_neighbor_map(relationships)
    corpus_topic = default_topic(records)
    ideas: list[dict[str, Any]] = []

    pair_specs = [
        (
            "fast-open-world",
            ("action-tokenization", "open-world-generalization"),
            "把高频 action tokenization 引入 open-world VLA",
            "当前库里同时存在动作表示优化和开放环境泛化的论文，适合直接做组合验证。",
            "选一个开放环境任务，先只替换 action 表示或 tokenizer，再比较长时序成功率、训练速度和恢复能力。",
            "有机会在不明显增大模型规模的前提下，提高部署场景中的控制稳定性和泛化表现。",
            "两类论文的训练接口和数据预处理可能并不兼容，需要先做输入输出对齐。",
            "high",
            "medium",
        ),
        (
            "experience-open-world",
            ("learning-from-experience", "open-world-generalization"),
            "面向部署回流的 open-world 持续适配机制",
            "如果库里既有开放环境泛化，又有从经验中学习的工作，就值得把二者合并成真实部署闭环。",
            "构建一个小规模 online adaptation 流程，只允许模型使用近期失败轨迹做轻量更新，再看恢复效率是否提升。",
            "更接近真实机器人长期部署场景，也更容易形成你自己的持续学习主线。",
            "需要严格控制安全和漂移风险，否则 online update 很容易带来负迁移。",
            "high",
            "high",
        ),
        (
            "generalist-eval",
            ("generalist-robotics", "instruction-following"),
            "给通用 VLA 增加更细粒度的可执行评测切片",
            "当前很多通用 VLA 论文在总指标上有效，但在指令歧义、长时序和恢复策略上未必说得足够清楚。",
            "从现有论文中抽三类最常见任务，设计更细的子指标，例如子目标完成率、重规划次数和错误恢复时间。",
            "这是低风险、强执行性的方向，适合尽快形成一个稳定的内部 benchmark。",
            "创新上限不如新模型方向高，但落地快、复用价值大。",
            "medium",
            "low",
        ),
        (
            "flow-tokenization",
            ("flow-model", "action-tokenization"),
            "比较连续生成与离散 tokenization 在 VLA 中的边界",
            "如果库里同时有 flow-based policy 和 action tokenization 论文，就可以直接研究两种动作建模范式的分界线。",
            "固定视觉和语言编码器，只替换动作生成头，比较高频控制任务下的性能、训练稳定性和推理延迟。",
            "能够帮助你判断后续模型路线到底更该押注连续生成还是离散表示。",
            "需要较强的工程控制力，否则实验差异会被其他模块掩盖。",
            "medium",
            "high",
        ),
    ]

    for idea_id, required_tags, title, why_now, mve, gain, risk, priority, difficulty in pair_specs:
        supporting = choose_papers(buckets, *required_tags)
        if len(supporting) < 2:
            continue
        ideas.append(
            {
                "idea_id": idea_id,
                "title": title,
                "supporting_papers": [str(item.get("paper_id") or "") for item in supporting[:4]],
                "supporting_titles": [str(item.get("title") or item.get("paper_id") or "") for item in supporting[:4]],
                "topic_anchor": corpus_topic,
                "why_now": why_now,
                "minimum_viable_experiment": mve,
                "expected_gain": gain,
                "main_risk": risk,
                "priority": priority,
                "execution_difficulty": difficulty,
            }
        )

    if not ideas:
        records_sorted = sorted(records, key=lambda item: (item.get("year") or 0, item.get("paper_id") or ""), reverse=True)
        supporting = records_sorted[:3]
        ideas.append(
            {
                "idea_id": "corpus-baseline",
                "title": "围绕主主题建立最小可执行 benchmark",
                "supporting_papers": [str(item.get("paper_id") or "") for item in supporting],
                "supporting_titles": [str(item.get("title") or item.get("paper_id") or "") for item in supporting],
                "topic_anchor": corpus_topic,
                "why_now": f"当前库的主主题是 {corpus_topic}，先把评测和对照做扎实，比直接追逐复杂新模型更稳。",
                "minimum_viable_experiment": "挑 2 到 3 篇最相关论文，统一输入输出接口，先完成一个内部可复现 baseline 套件。",
                "expected_gain": "为之后任何新 idea 提供稳定评测底座，降低重复试错成本。",
                "main_risk": "短期内更偏工程基础设施建设，论文新颖度需要通过后续方法叠加来体现。",
                "priority": "medium",
                "execution_difficulty": "low",
            }
        )

    top_edge = None
    for edge in relationships.get("edges") or []:
        if isinstance(edge, dict):
            top_edge = edge
            break
    if top_edge:
        source_id = str(top_edge.get("source_paper_id") or "")
        target_id = str(top_edge.get("target_paper_id") or "")
        support_ids = [source_id, target_id]
        support_titles = []
        for paper_id in support_ids:
            record = next((item for item in records if str(item.get("paper_id") or "") == paper_id), None)
            support_titles.append(str(record.get("title") or paper_id) if record else paper_id)
        ideas.append(
            {
                "idea_id": "top-edge-composition",
                "title": "沿着当前最强论文关系边做模块组合实验",
                "supporting_papers": support_ids,
                "supporting_titles": support_titles,
                "topic_anchor": " / ".join(top_edge.get("shared_topics") or [corpus_topic]),
                "why_now": "库内已经存在一条高分关系边，说明这两篇论文的主题和标签高度接近，组合成本相对更低。",
                "minimum_viable_experiment": "只替换一个关键模块，在同一数据和评测协议下验证互补性是否真实存在。",
                "expected_gain": "最快得到跨论文组合的正反证据，适合作为近期 exploratory project。",
                "main_risk": "高关系分数只是检索信号，不代表两篇方法在工程上天然兼容。",
                "priority": "medium",
                "execution_difficulty": "medium",
            }
        )

    return ideas[:4]


def render_markdown(ideas: list[dict[str, Any]], records: list[dict[str, Any]]) -> str:
    topics = topic_counts(records)
    lines = [
        "# 全库前沿 Idea 推荐",
        "",
        f"- 生成时间：{utc_now_iso()}",
        f"- 论文数量：{len(records)}",
        f"- 高频主题：{', '.join(f'{topic} ({count})' for topic, count in topics[:5]) if topics else '未识别'}",
        "",
        "> 这些 idea 用于帮助你在整个论文库上做选题排序。它们强调组合价值、执行可行性和近期可推进性，而不是只做单篇论文复述。",
        "",
    ]
    for index, idea in enumerate(ideas, start=1):
        lines.extend(
            [
                f"## Idea {index}：{idea['title']}",
                "",
                f"- 主题锚点：{idea['topic_anchor']}",
                f"- 支持论文：{', '.join(f'`{paper_id}`' for paper_id in idea['supporting_papers'])}",
                f"- 对应题目：{'；'.join(compact_text(title, 120) for title in idea['supporting_titles'])}",
                f"- 为什么现在值得做：{idea['why_now']}",
                f"- 最小可执行实验：{idea['minimum_viable_experiment']}",
                f"- 预期收益：{idea['expected_gain']}",
                f"- 主要风险：{idea['main_risk']}",
                f"- 优先级：{idea['priority']}",
                f"- 执行难度：{idea['execution_difficulty']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build corpus-level research ideas from paper metadata and relationships.",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Paper metadata root (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--relationships-path",
        default="doc/papers/index/relationships.yaml",
        help="Relationship index path (default: doc/papers/index/relationships.yaml)",
    )
    parser.add_argument(
        "--output-root",
        default="doc/papers/user/syntheses",
        help="Human-readable synthesis output root (default: doc/papers/user/syntheses)",
    )
    parser.add_argument(
        "--kb-root",
        default="doc/papers/ai",
        help="AI-readable KB root (default: doc/papers/ai)",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    papers_root = (project_root / args.papers_root).resolve()
    relationships_path = (project_root / args.relationships_path).resolve()
    output_root = (project_root / args.output_root).resolve()
    kb_root = (project_root / args.kb_root).resolve()
    ensure_dir(output_root)
    ensure_dir(kb_root)

    records = load_metadata_records(papers_root)
    if not records:
        raise SystemExit(f"No metadata files found under: {papers_root}")
    relationships = load_yaml(relationships_path)
    if not isinstance(relationships, dict):
        raise SystemExit(f"Invalid or missing relationship index: {relationships_path}")

    ideas = idea_payloads(records, relationships)
    write_text_if_changed(output_root / "frontier-ideas.md", render_markdown(ideas, records))
    write_yaml_if_changed(
        kb_root / "frontier-ideas.yaml",
        {
            "schema_version": 1,
            "generated_at": utc_now_iso(),
            "paper_count": len(records),
            "ideas": ideas,
        },
    )
    print(f"[OK] corpus ideas built: ideas={len(ideas)}")


if __name__ == "__main__":
    main()

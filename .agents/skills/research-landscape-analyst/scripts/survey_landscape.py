#!/usr/bin/env python3
"""Analyze the shared research library for trends, candidate programs, and concise listings."""

from __future__ import annotations

import argparse
from collections import Counter
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    append_wiki_log_event,
    bootstrap_workspace,
    ensure_research_runtime,
    find_project_root,
    literature_index_path,
    literature_tag_taxonomy_path,
    load_literature_records,
    load_repo_summaries,
    normalize_title,
    query_keyword_terms,
    rebuild_wiki_index_markdown,
    repo_index_path,
    research_root,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)
from research_v11.retrieval import (
    load_query_tags,
    normalize_tag,
    record_tag_bank,
    score_literature_relevance,
)

QUERY_STOPWORDS = {
    "about",
    "after",
    "before",
    "between",
    "candidate",
    "current",
    "direction",
    "directions",
    "field",
    "fields",
    "paper",
    "papers",
    "program",
    "programs",
    "repo",
    "repos",
    "research",
    "summary",
    "survey",
    "trend",
    "trends",
    "with",
}
SCOPE_VALUES = {"macro", "focused", "micro"}


def normalized_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = normalize_tag(str(value))
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def query_terms(text: str) -> list[str]:
    return query_keyword_terms(text, stopwords=QUERY_STOPWORDS)


def field_profile(project_root: Path, field: str, tags: list[str]) -> dict[str, Any]:
    manual_tags = normalized_list(tags)
    query_text = " ".join(part for part in [field, " ".join(manual_tags)] if part.strip())
    query_tags = sorted(set(manual_tags + load_query_tags(project_root, query_text)))
    return {
        "field": field,
        "text": query_text,
        "normalized_text": normalize_title(query_text),
        "terms": query_terms(query_text),
        "tag_labels": query_tags,
    }


def repo_relevance(record: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    repo_terms = set(
        query_terms(
            " ".join(
                [
                    str(record.get("repo_name") or ""),
                    str(record.get("short_summary") or ""),
                    " ".join(str(item) for item in record.get("frameworks", [])),
                    " ".join(str(item) for item in record.get("entrypoints", [])),
                ]
            )
        )
    )
    tag_bank = record_tag_bank(record)
    topics = {normalize_title(str(topic)) for topic in record.get("topics", []) if str(topic).strip()}
    matched_tags = sorted(tag_bank & set(profile["tag_labels"]))
    matched_topics = sorted(topic for topic in topics if topic and topic in profile["normalized_text"])
    matched_terms = sorted(repo_terms & set(profile["terms"]))

    score = (6 * len(matched_tags)) + (5 * len(matched_topics)) + (3 * len(matched_terms))
    if record.get("frameworks"):
        score += 1
    if record.get("entrypoints"):
        score += 1

    reasons: list[str] = []
    if matched_tags:
        reasons.append(f"tag:{', '.join(matched_tags[:2])}")
    if matched_topics:
        reasons.append(f"topic:{', '.join(matched_topics[:2])}")
    if matched_terms:
        reasons.append(f"summary:{', '.join(matched_terms[:3])}")
    if record.get("frameworks"):
        reasons.append(f"framework:{', '.join(str(item) for item in record.get('frameworks', [])[:2])}")
    if not reasons and record.get("short_summary"):
        reasons.append("summary:generic-fit")

    return {
        "score": score,
        "reasons": reasons,
        "matched_tags": matched_tags,
        "matched_topics": matched_topics,
        "has_signal": bool(matched_tags or matched_topics or matched_terms),
    }


def selected_literature(project_root: Path, profile: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, str, dict[str, Any], dict[str, Any]]] = []
    for record in load_literature_records(project_root):
        breakdown = score_literature_relevance(
            record,
            normalized_query_text=profile["normalized_text"],
            query_terms=profile["terms"],
            query_tags=profile["tag_labels"],
            tokenize=query_terms,
        )
        if profile["tag_labels"] and not breakdown["matched_tags"] and not breakdown["matched_topics"]:
            continue
        if not breakdown["has_signal"] and profile["terms"]:
            continue
        ranked.append((breakdown["score"], int(record.get("year") or 0), str(record.get("id") or ""), record, breakdown))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    selected: list[dict[str, Any]] = []
    for score, _year, _record_id, record, breakdown in ranked[:limit]:
        selected.append(
            {
                "source_id": record.get("id", ""),
                "title": record.get("canonical_title", ""),
                "year": record.get("year"),
                "tags": record.get("tags", []),
                "topics": record.get("topics", []),
                "short_summary": record.get("short_summary", ""),
                "score": score,
                "reasons": breakdown["reasons"],
            }
        )
    return selected


def selected_repos(project_root: Path, profile: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    ranked: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
    for record in load_repo_summaries(project_root):
        breakdown = repo_relevance(record, profile)
        if profile["tag_labels"] and not breakdown["matched_tags"] and not breakdown["matched_topics"]:
            continue
        if not breakdown["has_signal"] and profile["terms"]:
            continue
        ranked.append((breakdown["score"], str(record.get("repo_id") or record.get("id") or ""), record, breakdown))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    for score, _repo_id, record, breakdown in ranked[:limit]:
        selected.append(
            {
                "repo_id": record.get("repo_id") or record.get("id", ""),
                "repo_name": record.get("repo_name", ""),
                "tags": record.get("tags", []),
                "topics": record.get("topics", []),
                "frameworks": record.get("frameworks", []),
                "entrypoints": record.get("entrypoints", []),
                "short_summary": record.get("short_summary", ""),
                "score": score,
                "reasons": breakdown["reasons"],
            }
        )
    return selected


def trend_candidates(literature: list[dict[str, Any]], repos: list[dict[str, Any]], query_tags: list[str], limit: int = 3) -> list[str]:
    topic_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    for record in literature:
        topic_counter.update(normalize_title(str(topic)) for topic in record.get("topics", []) if str(topic).strip())
        tag_counter.update(normalize_tag(str(tag)) for tag in record.get("tags", []) if str(tag).strip())
    for record in repos:
        topic_counter.update(normalize_title(str(topic)) for topic in record.get("topics", []) if str(topic).strip())
        tag_counter.update(normalize_tag(str(tag)) for tag in record.get("tags", []) if str(tag).strip())

    labels: list[str] = []
    for label, _count in topic_counter.most_common():
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            return labels
    for label, _count in tag_counter.most_common():
        if label and label not in labels and label not in query_tags:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels[:limit]


def support_literature(label: str, literature: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_label = normalize_title(label)
    normalized_tag = normalize_tag(label)
    out: list[dict[str, Any]] = []
    for record in literature:
        topics = {normalize_title(str(item)) for item in record.get("topics", []) if str(item).strip()}
        tags = {normalize_tag(str(item)) for item in record.get("tags", []) if str(item).strip()}
        haystack = normalize_title(" ".join([str(record.get("title") or ""), str(record.get("short_summary") or "")]))
        if normalized_label in topics or normalized_tag in tags or normalized_label in haystack:
            out.append(record)
    return out


def support_repos(label: str, repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_label = normalize_title(label)
    normalized_tag = normalize_tag(label)
    out: list[dict[str, Any]] = []
    for record in repos:
        topics = {normalize_title(str(item)) for item in record.get("topics", []) if str(item).strip()}
        tags = {normalize_tag(str(item)) for item in record.get("tags", []) if str(item).strip()}
        haystack = normalize_title(" ".join([str(record.get("repo_name") or ""), str(record.get("short_summary") or "")]))
        if normalized_label in topics or normalized_tag in tags or normalized_label in haystack:
            out.append(record)
    return out


def build_trends(field: str, scope: str, literature: list[dict[str, Any]], repos: list[dict[str, Any]], query_tags: list[str]) -> list[dict[str, Any]]:
    labels = trend_candidates(literature, repos, query_tags)
    if not labels and field.strip():
        labels = [field.strip()]
    trends: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        lit_support = support_literature(label, literature)
        repo_support = support_repos(label, repos)
        years = sorted({int(item["year"]) for item in lit_support if item.get("year")}, reverse=True)
        trends.append(
            {
                "trend_id": f"trend-{index + 1}",
                "label": label,
                "literature_refs": [item["source_id"] for item in lit_support[:5]],
                "repo_refs": [item["repo_id"] for item in repo_support[:3]],
                "Observed": [
                    f"当前库中有 {len(lit_support)} 条文献和 {len(repo_support)} 个 repo 与 `{label}` 对齐。",
                    *([f"相关论文年份主要分布在 {', '.join(str(year) for year in years[:3])}。"] if years else []),
                ],
                "Inferred": [
                    (
                        f"由于库里已经有可复用的 repo 线索，`{label}` 看起来更接近可实现状态。"
                        if repo_support
                        else f"`{label}` 目前更偏文献支撑，缺少稳定的实现锚点。"
                    ),
                    (
                        "这是一个更适合作为大 program 主轴的宽方向。"
                        if scope == "macro"
                        else "这是一个更适合做边界清晰 program 的窄主题。"
                    ),
                ],
                "Suggested": [
                    (
                        f"先把 `{label}` 作为主要 program 轴之一，再继续往具体机制收缩。"
                        if scope == "macro"
                        else f"把 `{label}` 收敛成一个候选 program，并明确 evidence pack 与 repo strategy。"
                    )
                ],
                "OpenQuestions": ["当前库覆盖是否已经足够，还是应该让 literature-scout 再补更新的证据？"],
            }
        )
    return trends


def program_seed(field: str, scope: str, trend: dict[str, Any], repos: list[dict[str, Any]], *, survey_id: str) -> dict[str, Any]:
    label = str(trend.get("label") or field).strip()
    repo_refs = list(trend.get("repo_refs", []))
    lit_refs = list(trend.get("literature_refs", []))
    repo_hint = repo_refs[0] if repo_refs else ""
    if scope == "macro":
        title = f"{field}：围绕 {label} 的路线图型 program"
        question = f"在更真实的任务和设定下，我们应该围绕 `{label}` 走哪条更宽的研究路线来推进 {field}？"
        goal = f"围绕 `{label}` 建立一个更大范围的 program，覆盖文献、benchmark framing 和实现锚点。"
        scope_hint = "broad"
    elif scope == "micro":
        title = f"{field}：围绕 {label} 的快周转 program"
        question = f"在尽量贴近现有 repo baseline 的前提下，围绕 `{label}` 最小的有效干预是什么？"
        goal = f"围绕 `{label}` 定义一个窄而快的 implementation-first program，追求快速验证和最小代码面。"
        scope_hint = "micro"
    else:
        title = f"{field}：围绕 {label} 的聚焦型 program"
        question = f"在现实约束下，围绕 `{label}` 哪种机制最值得优先推进，以改善 {field}？"
        goal = f"围绕 `{label}` 启动一个边界清晰的 program，并给出明确的文献支撑和可行 repo host。"
        scope_hint = "focused"

    bootstrap_prompt = (
        f"帮我创建一个新 program，问题是“{question}”，目标是“{goal}”"
        + (f"，优先复用仓库 {repo_hint}。" if repo_hint else "。")
    )
    seed_id = slugify(f"{field}-{label}-{scope_hint}", max_words=8)
    conductor_prompt = (
        f"基于 survey {survey_id} 里的候选 program {seed_id}，直接帮我创建真正的 program"
        f"；如果没有更好的命名，就用 program_id `{seed_id}`，并保留它的来源和 seed evidence。"
    )
    return {
        "program_seed_id": seed_id,
        "suggested_program_id": seed_id,
        "title": title,
        "scope": scope_hint,
        "question": question,
        "goal": goal,
        "suggested_tags": normalized_list([label])[:4],
        "literature_refs": lit_refs[:4],
        "repo_refs": repo_refs[:2],
        "why_now": (
            f"当前共享库里已经有围绕 `{label}` 的证据和 repo 上下文。"
            if repo_refs
            else f"当前共享库里已经能看到围绕 `{label}` 的有效文献支撑。"
        ),
        "initial_steps": [
            "先用 research-conductor 创建一个具体的 program 壳。",
            "如果需要，再用 literature-analyst 把这个 seed 扩成 program-scoped evidence map。",
            "如果已经有 repo context，第一轮实现面要尽量收窄。",
        ],
        "bootstrap_prompt": bootstrap_prompt,
        "conductor_prompt": conductor_prompt,
    }


def landscape_dir(project_root: Path, survey_id: str) -> Path:
    return research_root(project_root) / "library" / "landscapes" / survey_id


def build_landscape_report(project_root: Path, field: str, scope: str, tags: list[str], lit_limit: int, repo_limit: int, program_count: int, survey_id: str) -> tuple[dict[str, Any], str]:
    profile = field_profile(project_root, field, tags)
    literature = selected_literature(project_root, profile, lit_limit)
    repos = selected_repos(project_root, profile, repo_limit)
    trends = build_trends(field, scope, literature, repos, profile["tag_labels"])
    programs = [program_seed(field, scope, trend, repos, survey_id=survey_id) for trend in trends[:program_count]]

    report = {
        **yaml_default(survey_id, "research-landscape-analyst", status="ready", confidence=0.68),
        "inputs": [
            literature_index_path(project_root).relative_to(project_root).as_posix(),
            repo_index_path(project_root).relative_to(project_root).as_posix(),
            literature_tag_taxonomy_path(project_root).relative_to(project_root).as_posix(),
            *[f"lit:{item['source_id']}" for item in literature],
            *[f"repo:{item['repo_id']}" for item in repos],
        ],
        "field": field,
        "scope": scope,
        "filters": {"tags": normalized_list(tags)},
        "snapshot": {
            "matched_literature_count": len(literature),
            "matched_repo_count": len(repos),
            "latest_year": max((int(item["year"]) for item in literature if item.get("year")), default=None),
        },
        "retrieval": {
            "query_text": profile["text"],
            "query_terms": profile["terms"],
            "query_tags": profile["tag_labels"],
            "selected_literature": literature,
            "selected_repos": repos,
        },
        "Observed": [
            f"针对字段 `{field}` 匹配到 {len(literature)} 条文献和 {len(repos)} 个 repo。",
            (
                "当前已有 repo summary，因此候选 program 可以带上实现锚点。"
                if repos
                else "当前 canonical library 快照里还没有匹配到稳定的 repo 锚点。"
            ),
        ],
        "Inferred": [
            (
                f"当前库对 `{field}` 已经有足够信号，支持做一轮 {scope} 粒度的方向勘察并生成候选 program。"
                if literature
                else f"当前库对 `{field}` 覆盖偏薄，因此候选 program 都应视作临时假设。"
            )
        ],
        "Suggested": [
            "选定一个候选方向后，用 research-conductor 把它实例化为 concrete program。",
            "如果仍然觉得该方向覆盖不足，先跑 literature-scout，再承诺到更窄的 program。",
        ],
        "OpenQuestions": ["下一步更应该偏大路线图，还是偏 implementation-first 的窄 program？"],
        "trends": trends,
        "candidate_programs": programs,
    }
    summary_md = render_landscape_markdown(report)
    return report, summary_md


def render_landscape_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 方向地形图 Landscape Survey: {report.get('field', '')}",
        "",
        "## 快照 Snapshot",
        "",
        f"- Scope: `{report.get('scope', 'focused')}`",
        f"- 匹配文献数: `{report.get('snapshot', {}).get('matched_literature_count', 0)}`",
        f"- 匹配 repo 数: `{report.get('snapshot', {}).get('matched_repo_count', 0)}`",
        f"- Query tags: `{', '.join(report.get('retrieval', {}).get('query_tags', [])) or 'n/a'}`",
        "",
        "## 趋势 Trends",
        "",
    ]
    trends = report.get("trends", [])
    if not trends:
        lines.extend(["- 当前库快照里没有出现足够强的趋势信号。", ""])
    else:
        for trend in trends:
            lines.extend(
                [
                    f"### {trend.get('label', 'trend')}",
                    "",
                    f"- 文献引用 Literature refs: `{', '.join(trend.get('literature_refs', [])) or 'n/a'}`",
                    f"- Repo 引用 Repo refs: `{', '.join(trend.get('repo_refs', [])) or 'n/a'}`",
                    *[f"- {item}" for item in trend.get("Observed", [])],
                    *[f"- {item}" for item in trend.get("Inferred", [])],
                    "",
                ]
            )
    lines.extend(["## 候选 Programs Candidate Programs", ""])
    candidates = report.get("candidate_programs", [])
    if not candidates:
        lines.extend(["- 当前没有产出可用的 candidate program seed。", ""])
    else:
        for idx, program in enumerate(candidates, start=1):
            lines.extend(
                [
                    f"### {idx}. {program.get('title', '')}",
                    "",
                    f"- Scope: `{program.get('scope', '')}`",
                    f"- 建议 program_id Suggested program_id: `{program.get('suggested_program_id', program.get('program_seed_id', ''))}`",
                    f"- 问题 Question: {program.get('question', '')}",
                    f"- 目标 Goal: {program.get('goal', '')}",
                    f"- 文献引用 Literature refs: `{', '.join(program.get('literature_refs', [])) or 'n/a'}`",
                    f"- Repo 引用 Repo refs: `{', '.join(program.get('repo_refs', [])) or 'n/a'}`",
                    f"- 为什么现在做 Why now: {program.get('why_now', '')}",
                    "",
                    "启动提示 Bootstrap prompt:",
                    "",
                    "```text",
                    str(program.get("bootstrap_prompt", "")),
                    "```",
                    "",
                    "Conductor 提示 Conductor prompt:",
                    "",
                    "```text",
                    str(program.get("conductor_prompt", "")),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_survey(project_root: Path, report: dict[str, Any], summary_md: str) -> tuple[Path, Path]:
    survey_id = str(report.get("id") or "landscape-survey")
    root = landscape_dir(project_root, survey_id)
    yaml_path = root / "landscape-report.yaml"
    md_path = root / "summary.md"
    write_yaml_if_changed(yaml_path, report)
    write_text_if_changed(md_path, summary_md)
    return yaml_path, md_path


def format_listing(title: str, items: list[dict[str, Any]], *, kind: str, fmt: str) -> str:
    if fmt == "markdown":
        lines = [f"## {title}", ""]
        for item in items:
            label = item.get("source_id") or item.get("repo_id") or item.get("id") or "unknown"
            name = item.get("title") or item.get("repo_name") or "unknown"
            lines.extend(
                [
                    f"- `{label}` | {item.get('year', 'n/a')} | {name}",
                    f"  tags: `{', '.join(item.get('tags', [])) or 'n/a'}`",
                    f"  topics: `{', '.join(item.get('topics', [])) or 'n/a'}`",
                    f"  summary: {item.get('short_summary', 'n/a')}",
                ]
            )
            if kind == "repos":
                lines.append(f"  entrypoints: `{', '.join(item.get('entrypoints', [])) or 'n/a'}`")
        return "\n".join(lines).rstrip() + "\n"

    lines = [f"[{title}]"]
    for item in items:
        label = item.get("source_id") or item.get("repo_id") or item.get("id") or "unknown"
        name = item.get("title") or item.get("repo_name") or "unknown"
        lines.append(f"- {label} | {item.get('year', 'n/a')} | {name}")
        lines.append(f"  tags: {', '.join(item.get('tags', [])) or 'n/a'}")
        lines.append(f"  topics: {', '.join(item.get('topics', [])) or 'n/a'}")
        lines.append(f"  summary: {item.get('short_summary', 'n/a')}")
        if kind == "repos":
            lines.append(f"  entrypoints: {', '.join(item.get('entrypoints', [])) or 'n/a'}")
    return "\n".join(lines).rstrip() + "\n"


def handle_survey(args: argparse.Namespace) -> int:
    if args.scope not in SCOPE_VALUES:
        raise SystemExit(f"--scope must be one of {sorted(SCOPE_VALUES)}")
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    survey_id = args.survey_id or f"landscape-{slugify(args.field, max_words=6)}-{args.scope}"
    report, summary_md = build_landscape_report(
        project_root,
        field=args.field,
        scope=args.scope,
        tags=list(args.tag),
        lit_limit=args.literature_limit,
        repo_limit=args.repo_limit,
        program_count=args.program_count,
        survey_id=survey_id,
    )
    yaml_path, md_path = write_survey(project_root, report, summary_md)
    candidate_programs = report.get("candidate_programs", []) if isinstance(report, dict) else []
    append_wiki_log_event(
        project_root,
        "reporting",
        "方向地形图已刷新",
        summary=(
            f"已为 `{args.field}` 生成方向地形图 `{survey_id}`（scope=`{args.scope}`），"
            f"产出 {len(candidate_programs) if isinstance(candidate_programs, list) else 0} 个候选 program。"
        ),
        metadata={
            "source_skill": "research-landscape-analyst",
            "field": args.field,
            "scope": args.scope,
            "survey_id": survey_id,
            "artifacts": [
                relative_path(project_root, yaml_path),
                relative_path(project_root, md_path),
            ],
        },
        generated_by="research-landscape-analyst",
    )
    rebuild_wiki_index_markdown(project_root)
    print(f"[ok] wrote landscape survey -> {yaml_path.relative_to(project_root)}")
    print(f"[ok] wrote landscape summary -> {md_path.relative_to(project_root)}")
    return 0


def handle_list(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    profile = field_profile(project_root, args.query or "", list(args.tag))
    outputs: list[str] = []
    if args.kind in {"literature", "all"}:
        literature = selected_literature(project_root, profile, args.limit) if (args.query or args.tag) else [
            {
                "source_id": record.get("id", ""),
                "title": record.get("canonical_title", ""),
                "year": record.get("year"),
                "tags": record.get("tags", []),
                "topics": record.get("topics", []),
                "short_summary": record.get("short_summary", ""),
            }
            for record in sorted(load_literature_records(project_root), key=lambda item: (-(int(item.get("year") or 0)), str(item.get("id") or "")))[: args.limit]
        ]
        outputs.append(format_listing("Literature", literature, kind="literature", fmt=args.format))
    if args.kind in {"repos", "all"}:
        repos = selected_repos(project_root, profile, args.limit) if (args.query or args.tag) else [
            {
                "repo_id": record.get("repo_id") or record.get("id", ""),
                "repo_name": record.get("repo_name", ""),
                "tags": record.get("tags", []),
                "topics": record.get("topics", []),
                "entrypoints": record.get("entrypoints", []),
                "short_summary": record.get("short_summary", ""),
                "year": "n/a",
            }
            for record in sorted(load_repo_summaries(project_root), key=lambda item: str(item.get("repo_id") or item.get("id") or ""))[: args.limit]
        ]
        outputs.append(format_listing("Repos", repos, kind="repos", fmt=args.format))
    print("\n".join(part.rstrip() for part in outputs if part.strip()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze the shared research library and list relevant papers or repos.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    survey_cmd = subparsers.add_parser("survey", help="Write a field-level landscape survey and candidate programs")
    survey_cmd.add_argument("--field", required=True, help="Field, direction, or problem area to analyze")
    survey_cmd.add_argument("--scope", default="focused", choices=sorted(SCOPE_VALUES), help="How broad the candidate programs should be")
    survey_cmd.add_argument("--tag", action="append", default=[], help="Optional tag filter or emphasis cue")
    survey_cmd.add_argument("--literature-limit", type=int, default=10, help="Maximum number of literature entries to include")
    survey_cmd.add_argument("--repo-limit", type=int, default=5, help="Maximum number of repo entries to include")
    survey_cmd.add_argument("--program-count", type=int, default=3, help="How many candidate program seeds to generate")
    survey_cmd.add_argument("--survey-id", default="", help="Optional stable survey ID under kb/library/landscapes/")
    survey_cmd.set_defaults(func=handle_survey)

    list_cmd = subparsers.add_parser("list", help="List concise paper or repo inventory rows")
    list_cmd.add_argument("--kind", default="all", choices=["literature", "repos", "all"])
    list_cmd.add_argument("--query", default="", help="Optional field or direction text for relevance ranking")
    list_cmd.add_argument("--tag", action="append", default=[], help="Optional tag filter")
    list_cmd.add_argument("--limit", type=int, default=10)
    list_cmd.add_argument("--format", default="text", choices=["text", "markdown"])
    list_cmd.set_defaults(func=handle_list)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = find_project_root()
    ensure_research_runtime(project_root, "research-landscape-analyst")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

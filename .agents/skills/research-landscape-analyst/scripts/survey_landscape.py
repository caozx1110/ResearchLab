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
    bootstrap_workspace,
    ensure_research_runtime,
    find_project_root,
    literature_index_path,
    literature_tag_taxonomy_path,
    load_literature_records,
    load_repo_summaries,
    load_yaml,
    normalize_title,
    query_keyword_terms,
    repo_index_path,
    research_root,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
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


def normalize_tag(value: str) -> str:
    return normalize_title(value).replace(" ", "-")


def normalized_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = normalize_tag(str(value))
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def query_terms(text: str) -> list[str]:
    return query_keyword_terms(text, stopwords=QUERY_STOPWORDS)


def load_query_tags(project_root: Path, query_text: str) -> list[str]:
    payload = load_yaml(literature_tag_taxonomy_path(project_root), default={})
    if not isinstance(payload, dict):
        return []
    items = payload.get("items", {})
    if not isinstance(items, dict):
        return []
    normalized_query = normalize_title(query_text)
    hits: set[str] = set()
    for canonical, item in items.items():
        if not isinstance(item, dict):
            continue
        variants = [str(item.get("canonical_tag") or canonical), *[str(alias) for alias in item.get("aliases", [])]]
        for variant in variants:
            phrase = normalize_title(variant.replace("-", " "))
            if phrase and phrase in normalized_query:
                hits.add(normalize_tag(str(item.get("canonical_tag") or canonical)))
                break
    return sorted(hits)


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


def record_tag_bank(record: dict[str, Any]) -> set[str]:
    tags = {normalize_tag(str(tag)) for tag in record.get("tags", []) if str(tag).strip()}
    topics = {normalize_tag(str(topic)) for topic in record.get("topics", []) if str(topic).strip()}
    return tags | topics


def literature_relevance(record: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    title_terms = set(query_terms(str(record.get("canonical_title", ""))))
    summary_terms = set(query_terms(str(record.get("short_summary", ""))))
    abstract_terms = set(query_terms(str(record.get("abstract", ""))))
    tag_bank = record_tag_bank(record)
    topics = {normalize_title(str(topic)) for topic in record.get("topics", []) if str(topic).strip()}

    matched_tags = sorted(tag_bank & set(profile["tag_labels"]))
    matched_topics = sorted(topic for topic in topics if topic and topic in profile["normalized_text"])
    matched_title_terms = sorted(title_terms & set(profile["terms"]))
    matched_summary_terms = sorted(summary_terms & set(profile["terms"]))
    matched_abstract_terms = sorted(abstract_terms & set(profile["terms"]))

    score = (
        (6 * len(matched_tags))
        + (5 * len(matched_topics))
        + (4 * len(matched_title_terms))
        + (3 * len(matched_summary_terms))
        + (1 * len(matched_abstract_terms))
    )
    if record.get("year"):
        score += min(max(int(record["year"]) - 2021, 0), 4)

    reasons: list[str] = []
    if matched_tags:
        reasons.append(f"tag:{', '.join(matched_tags[:2])}")
    if matched_topics:
        reasons.append(f"topic:{', '.join(matched_topics[:2])}")
    if matched_title_terms:
        reasons.append(f"title:{', '.join(matched_title_terms[:3])}")
    if matched_summary_terms:
        reasons.append(f"summary:{', '.join(matched_summary_terms[:3])}")
    if not reasons and matched_abstract_terms:
        reasons.append(f"abstract:{', '.join(matched_abstract_terms[:3])}")
    if record.get("year"):
        reasons.append(f"year:{record['year']}")

    return {
        "score": score,
        "reasons": reasons,
        "matched_tags": matched_tags,
        "matched_topics": matched_topics,
        "has_signal": bool(matched_tags or matched_topics or matched_title_terms or matched_summary_terms or matched_abstract_terms),
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
        breakdown = literature_relevance(record, profile)
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
                    f"{len(lit_support)} literature entries and {len(repo_support)} repos in the current library align with `{label}`.",
                    *([f"Supporting papers span {', '.join(str(year) for year in years[:3])}."] if years else []),
                ],
                "Inferred": [
                    (
                        f"`{label}` looks implementation-ready because the library already includes reusable repo context."
                        if repo_support
                        else f"`{label}` is currently stronger on literature evidence than on reusable implementation anchors."
                    ),
                    (
                        "This is a broad umbrella direction suited for a larger program."
                        if scope == "macro"
                        else "This looks like a narrower theme that can support a bounded program."
                    ),
                ],
                "Suggested": [
                    (
                        f"Use `{label}` as one of the main program axes before narrowing into a concrete mechanism."
                        if scope == "macro"
                        else f"Turn `{label}` into one candidate program with a clear evidence pack and repo strategy."
                    )
                ],
                "OpenQuestions": ["Is the current library coverage enough, or should literature-scout fetch newer support?"],
            }
        )
    return trends


def program_seed(field: str, scope: str, trend: dict[str, Any], repos: list[dict[str, Any]], *, survey_id: str) -> dict[str, Any]:
    label = str(trend.get("label") or field).strip()
    repo_refs = list(trend.get("repo_refs", []))
    lit_refs = list(trend.get("literature_refs", []))
    repo_hint = repo_refs[0] if repo_refs else ""
    if scope == "macro":
        title = f"{field}: roadmap around {label}"
        question = f"What broad research roadmap should we pursue to improve {field} through `{label}` across realistic tasks and settings?"
        goal = f"Establish a larger-scope program around `{label}`, including literature coverage, benchmark framing, and implementation anchors."
        scope_hint = "broad"
    elif scope == "micro":
        title = f"{field}: quick-turn program on {label}"
        question = f"What smallest intervention can improve {field} on `{label}` while staying close to an existing repo baseline?"
        goal = f"Define one narrow, implementation-first program on `{label}` with fast validation and minimal code surface."
        scope_hint = "micro"
    else:
        title = f"{field}: focused program on {label}"
        question = f"Which mechanism most improves {field} on `{label}` under realistic constraints?"
        goal = f"Launch a bounded program around `{label}` with clear literature support and a plausible repo host."
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
            f"The current shared library already contains evidence and repo context around `{label}`."
            if repo_refs
            else f"The current shared library shows meaningful literature support around `{label}`."
        ),
        "initial_steps": [
            "Use research-conductor to create a concrete program shell.",
            "If needed, use literature-analyst to turn the seed into a program-scoped evidence map.",
            "If repo context is available, keep the first implementation surface narrow.",
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
            f"Matched {len(literature)} literature entries and {len(repos)} repos for field `{field}`.",
            (
                "Repo summaries are available, so candidate programs can include implementation anchors."
                if repos
                else "No matching canonical repo anchors were found in the current library snapshot."
            ),
        ],
        "Inferred": [
            (
                f"The current library supports a {scope} exploration of `{field}` with enough signal to seed candidate programs."
                if literature
                else f"The current library has thin coverage for `{field}`; candidate programs should be treated as provisional."
            )
        ],
        "Suggested": [
            "Use research-conductor to instantiate one selected candidate as a concrete program.",
            "If the field still feels under-covered, run literature-scout before committing to a narrow program.",
        ],
        "OpenQuestions": ["Should the next step favor a broader roadmap or a narrower implementation-first program?"],
        "trends": trends,
        "candidate_programs": programs,
    }
    summary_md = render_landscape_markdown(report)
    return report, summary_md


def render_landscape_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Landscape Survey: {report.get('field', '')}",
        "",
        "## Snapshot",
        "",
        f"- Scope: `{report.get('scope', 'focused')}`",
        f"- Matched literature: `{report.get('snapshot', {}).get('matched_literature_count', 0)}`",
        f"- Matched repos: `{report.get('snapshot', {}).get('matched_repo_count', 0)}`",
        f"- Query tags: `{', '.join(report.get('retrieval', {}).get('query_tags', [])) or 'n/a'}`",
        "",
        "## Trends",
        "",
    ]
    trends = report.get("trends", [])
    if not trends:
        lines.extend(["- No strong trend signal found in the current library snapshot.", ""])
    else:
        for trend in trends:
            lines.extend(
                [
                    f"### {trend.get('label', 'trend')}",
                    "",
                    f"- Literature refs: `{', '.join(trend.get('literature_refs', [])) or 'n/a'}`",
                    f"- Repo refs: `{', '.join(trend.get('repo_refs', [])) or 'n/a'}`",
                    *[f"- {item}" for item in trend.get("Observed", [])],
                    *[f"- {item}" for item in trend.get("Inferred", [])],
                    "",
                ]
            )
    lines.extend(["## Candidate Programs", ""])
    candidates = report.get("candidate_programs", [])
    if not candidates:
        lines.extend(["- No candidate program seeds were produced.", ""])
    else:
        for idx, program in enumerate(candidates, start=1):
            lines.extend(
                [
                    f"### {idx}. {program.get('title', '')}",
                    "",
                    f"- Scope: `{program.get('scope', '')}`",
                    f"- Suggested program_id: `{program.get('suggested_program_id', program.get('program_seed_id', ''))}`",
                    f"- Question: {program.get('question', '')}",
                    f"- Goal: {program.get('goal', '')}",
                    f"- Literature refs: `{', '.join(program.get('literature_refs', [])) or 'n/a'}`",
                    f"- Repo refs: `{', '.join(program.get('repo_refs', [])) or 'n/a'}`",
                    f"- Why now: {program.get('why_now', '')}",
                    "",
                    "Bootstrap prompt:",
                    "",
                    "```text",
                    str(program.get("bootstrap_prompt", "")),
                    "```",
                    "",
                    "Conductor prompt:",
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
    survey_cmd.add_argument("--survey-id", default="", help="Optional stable survey ID under doc/research/library/landscapes/")
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

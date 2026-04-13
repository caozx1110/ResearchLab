"""Shared retrieval helpers for literature/repo ranking across research skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .common import literature_tag_taxonomy_path, load_yaml, normalize_title


def normalize_tag(value: str) -> str:
    return normalize_title(value).replace(" ", "-")


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


def record_tag_bank(record: dict[str, Any]) -> set[str]:
    tags = {normalize_tag(str(tag)) for tag in record.get("tags", []) if str(tag).strip()}
    topics = {normalize_tag(str(topic)) for topic in record.get("topics", []) if str(topic).strip()}
    return tags | topics


def score_literature_relevance(
    record: dict[str, Any],
    *,
    normalized_query_text: str,
    query_terms: list[str],
    query_tags: list[str],
    tokenize: Callable[[str], list[str]],
) -> dict[str, Any]:
    title_terms = set(tokenize(str(record.get("canonical_title", ""))))
    summary_terms = set(tokenize(str(record.get("short_summary", ""))))
    abstract_terms = set(tokenize(str(record.get("abstract", ""))))
    tag_bank = record_tag_bank(record)
    topics = {normalize_title(str(topic)) for topic in record.get("topics", []) if str(topic).strip()}
    terms = set(query_terms)
    tags = set(query_tags)

    matched_tags = sorted(tag_bank & tags)
    matched_topics = sorted(topic for topic in topics if topic and topic in normalized_query_text)
    matched_title_terms = sorted(title_terms & terms)
    matched_summary_terms = sorted(summary_terms & terms)
    matched_abstract_terms = sorted(abstract_terms & terms)

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
        "matched_title_terms": matched_title_terms,
        "matched_summary_terms": matched_summary_terms,
        "matched_abstract_terms": matched_abstract_terms,
        "has_signal": bool(
            matched_tags or matched_topics or matched_title_terms or matched_summary_terms or matched_abstract_terms
        ),
    }

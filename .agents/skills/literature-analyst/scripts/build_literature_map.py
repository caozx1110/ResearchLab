#!/usr/bin/env python3
"""Build a program-scoped literature map from the shared literature library."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    append_program_reporting_event,
    bootstrap_workspace,
    ensure_research_runtime,
    find_project_root,
    load_literature_records,
    load_yaml,
    normalize_title,
    query_keyword_terms,
    research_root,
    utc_now_iso,
    write_yaml_if_changed,
    yaml_default,
)

QUERY_STOPWORDS = {
    "about",
    "after",
    "before",
    "between",
    "build",
    "current",
    "experiment",
    "experiments",
    "goal",
    "goals",
    "improve",
    "improving",
    "method",
    "methods",
    "paper",
    "papers",
    "problem",
    "question",
    "research",
    "result",
    "results",
    "system",
    "using",
    "with",
}


def normalize_tag(value: str) -> str:
    return normalize_title(value).replace(" ", "-")


def query_terms(text: str) -> list[str]:
    return query_keyword_terms(text, stopwords=QUERY_STOPWORDS)


def charter_query_text(charter: dict[str, Any]) -> str:
    parts = [
        str(charter.get("question") or ""),
        str(charter.get("goal") or ""),
    ]
    for item in charter.get("success_metrics", []):
        parts.append(str(item))
    for item in charter.get("non_goals", []):
        parts.append(str(item))
    constraints = charter.get("constraints", {})
    if isinstance(constraints, dict):
        parts.extend(str(value) for value in constraints.values() if str(value).strip())
    return "\n".join(part for part in parts if str(part).strip())


def load_query_tags(project_root: Path, query_text: str) -> list[str]:
    taxonomy_path = research_root(project_root) / "library" / "literature" / "tag-taxonomy.yaml"
    payload = load_yaml(taxonomy_path, default={})
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


def relevance_breakdown(record: dict[str, Any], query_profile: dict[str, Any]) -> dict[str, Any]:
    title_terms = set(query_terms(str(record.get("canonical_title", ""))))
    summary_terms = set(query_terms(str(record.get("short_summary", ""))))
    abstract_terms = set(query_terms(str(record.get("abstract", ""))))
    tags = {normalize_tag(str(tag)) for tag in record.get("tags", []) if str(tag).strip()}
    topics = {normalize_title(str(topic)) for topic in record.get("topics", []) if str(topic).strip()}

    matched_title_terms = sorted(title_terms & set(query_profile["terms"]))
    matched_summary_terms = sorted(summary_terms & set(query_profile["terms"]))
    matched_abstract_terms = sorted(abstract_terms & set(query_profile["terms"]))
    matched_tags = sorted(tags & set(query_profile["tag_labels"]))
    matched_topics = sorted(topic for topic in topics if topic and topic in query_profile["normalized_text"])

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
    }


def build_map(program_id: str) -> dict[str, Any]:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    charter_path = research_root(project_root) / "programs" / program_id / "charter.yaml"
    literature_index_path = research_root(project_root) / "library" / "literature" / "index.yaml"
    taxonomy_path = research_root(project_root) / "library" / "literature" / "tag-taxonomy.yaml"
    charter = load_yaml(charter_path, default={})
    if not isinstance(charter, dict):
        raise SystemExit(f"Missing program charter: {charter_path}")

    query = charter_query_text(charter)
    query_profile = {
        "text": query,
        "normalized_text": normalize_title(query),
        "terms": query_terms(query),
        "tag_labels": load_query_tags(project_root, query),
    }
    records = load_literature_records(project_root)
    ranked_records: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (record, relevance_breakdown(record, query_profile)) for record in records
    ]
    ranked = sorted(
        ranked_records,
        key=lambda item: (
            -item[1]["score"],
            -(int(item[0].get("year") or 0)),
            item[0].get("id", ""),
        ),
    )
    selected_pairs = ranked[: min(12, len(ranked))]
    selected = [record for record, _breakdown in selected_pairs]
    topic_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in selected:
        if record.get("topics"):
            for topic in record["topics"]:
                topic_buckets[str(topic)].append(record)
        else:
            topic_buckets["uncategorized"].append(record)
    topic_counts = Counter({topic: len(items) for topic, items in topic_buckets.items()})
    dominant_topics = [topic for topic, _count in topic_counts.most_common(3)]

    payload = {
        **yaml_default(f"{program_id}-literature-map", "literature-analyst", status="active", confidence=0.72),
        "inputs": [
            charter_path.relative_to(project_root).as_posix(),
            literature_index_path.relative_to(project_root).as_posix(),
            taxonomy_path.relative_to(project_root).as_posix(),
            *[f"lit:{item['id']}" for item in selected],
        ],
        "program_id": program_id,
        "retrieval": {
            "query_text": query,
            "query_terms": query_profile["terms"],
            "query_tags": query_profile["tag_labels"],
            "selected_sources": [
                {
                    "source_id": record["id"],
                    "title": record.get("canonical_title", ""),
                    "short_summary": record.get("short_summary", ""),
                    "tags": record.get("tags", []),
                    "topics": record.get("topics", []),
                    "score": breakdown["score"],
                    "reasons": breakdown["reasons"],
                }
                for record, breakdown in selected_pairs
            ],
        },
        "problem_frame": {
            "Observed": [
                f"Selected {len(selected)} literature entries for the current program.",
                "Retrieval weighted curated tags/topics and short summaries before full abstract text.",
            ],
            "Inferred": [f"Dominant themes are {', '.join(dominant_topics) or 'uncategorized'}."],
            "Suggested": ["Use the dominant themes to seed initial idea variants before adding niche directions."],
            "OpenQuestions": ["Are the most relevant newest works already present, or should the workflow trigger literature-scout?"],
        },
        "clusters": [
            {
                "cluster_id": f"{program_id}-cluster-{idx + 1}",
                "topic": topic,
                "literature_refs": [item["id"] for item in items[:6]],
                "Observed": [f"{len(items)} entries mention topic `{topic}`."],
                "Inferred": ["This cluster is likely a reusable baseline family."],
                "Suggested": ["Compare one representative source from this cluster against the selected idea."],
                "OpenQuestions": [],
            }
            for idx, (topic, items) in enumerate(sorted(topic_buckets.items(), key=lambda item: (-len(item[1]), item[0])))
        ],
        "agreements": [
            {
                "Observed": [f"Many selected entries converge on `{topic}` as a recurring theme."]
                if topic
                else ["Selected entries show thematic overlap."],
                "Inferred": ["This theme is a stable axis for comparison."],
                "Suggested": ["Anchor early ablations on this theme."],
                "OpenQuestions": [],
            }
            for topic in dominant_topics[:2]
        ],
        "conflicts": [
            {
                "Observed": ["Different source kinds are mixed in the current evidence pool."],
                "Inferred": ["Implementation guidance may be inconsistent across papers, blogs, and project pages."],
                "Suggested": ["Promote implementation-critical claims into note.md after manual verification."],
                "OpenQuestions": [],
            }
        ],
        "gaps": [
            {
                "Observed": ["The current map is built from locally available structured entries only."],
                "Inferred": ["Fresh novelty checks may still be missing if the topic moves quickly."],
                "Suggested": ["Trigger literature-scout when idea-review-board flags evidence gaps."],
                "OpenQuestions": ["Do we need recent outside sources before final idea selection?"],
            }
        ],
        "candidate_directions": [
            {
                "title": f"Probe {topic} with a lighter-weight implementation path",
                "Observed": [f"`{topic}` appears repeatedly in the selected evidence."],
                "Inferred": ["A constrained variant could be validated quickly against existing repos."],
                "Suggested": ["Let idea-forge branch one proposal from this direction."],
                "OpenQuestions": [],
            }
            for topic in dominant_topics[:3]
        ],
        "paper_refs": [item["id"] for item in selected],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a program-scoped literature map from the shared library.")
    parser.add_argument("--program-id", required=True)
    args = parser.parse_args()

    project_root = find_project_root()
    ensure_research_runtime(project_root, "literature-analyst")
    payload = build_map(args.program_id)
    program_root = research_root(project_root) / "programs" / args.program_id
    output_path = research_root(project_root) / "programs" / args.program_id / "evidence" / "literature-map.yaml"
    write_yaml_if_changed(output_path, payload)
    state_path = program_root / "workflow" / "state.yaml"
    state = load_yaml(state_path, default={})
    if isinstance(state, dict):
        state["generated_at"] = utc_now_iso()
        state["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root)), output_path.relative_to(project_root).as_posix()]
        state["stage"] = "literature-analysis"
        write_yaml_if_changed(state_path, state)
    retrieval = payload.get("retrieval", {}) if isinstance(payload, dict) else {}
    selected_sources = retrieval.get("selected_sources", []) if isinstance(retrieval, dict) else []
    query_tags = retrieval.get("query_tags", []) if isinstance(retrieval, dict) else []
    query_tags = query_tags if isinstance(query_tags, list) else []
    source_ids = [
        str(item.get("source_id") or "").strip()
        for item in selected_sources
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    ]
    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "literature-analyst",
            "event_type": "literature-map-updated",
            "title": "Literature map refreshed",
            "summary": (
                f"Selected {len(source_ids)} canonical sources for the literature map"
                + (f" around tags {', '.join(str(tag) for tag in query_tags[:3])}." if query_tags else ".")
            ),
            "artifacts": [
                output_path.relative_to(project_root).as_posix(),
                state_path.relative_to(project_root).as_posix(),
            ],
            "paper_ids": source_ids,
            "stage": "literature-analysis",
            "tags": [str(tag) for tag in query_tags if str(tag).strip()],
        },
        generated_by="literature-analyst",
    )
    print(f"[ok] wrote {output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

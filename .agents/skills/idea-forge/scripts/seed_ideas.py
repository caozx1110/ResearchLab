#!/usr/bin/env python3
"""Seed idea proposals from a program charter and literature map."""

from __future__ import annotations

import argparse
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
    load_index,
    load_yaml,
    normalize_title,
    query_keyword_terms,
    repo_index_path,
    research_root,
    slugify,
    utc_now_iso,
    write_yaml_if_changed,
    yaml_default,
)


STAGE_ORDER = (
    "problem-framing",
    "literature-analysis",
    "idea-generation",
    "idea-review",
    "method-design",
    "implementation-planning",
)


def idea_id_from_title(program_id: str, title: str) -> str:
    return f"{program_id}-{slugify(title, max_words=5)}"


def repo_refs(project_root: Path) -> list[str]:
    payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")
    return list(payload.get("items", {}).keys())


def query_terms(text: str) -> list[str]:
    return query_keyword_terms(text)


def first_observed_text(item: dict[str, Any], fallback: str = "gap") -> str:
    observed = item.get("Observed")
    if isinstance(observed, list):
        for candidate in observed:
            text = str(candidate).strip()
            if text:
                return text
        return fallback
    return fallback


def stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(str(stage or "").strip())
    except ValueError:
        return -1


def should_promote_stage(current_stage: str, target_stage: str) -> bool:
    current_rank = stage_rank(current_stage)
    target_rank = stage_rank(target_stage)
    if target_rank < 0:
        return False
    if current_rank < 0:
        return True
    return target_rank >= current_rank


def proposal_query_text(charter: dict[str, Any], literature_map: dict[str, Any], seed: str) -> str:
    retrieval = literature_map.get("retrieval", {}) if isinstance(literature_map, dict) else {}
    query_terms_block = retrieval.get("query_terms", []) if isinstance(retrieval, dict) else []
    return "\n".join(
        [
            str(seed or ""),
            str(charter.get("question") or ""),
            str(charter.get("goal") or ""),
            " ".join(str(item) for item in query_terms_block if str(item).strip()),
        ]
    )


def repo_relevance(repo_item: dict[str, Any], query_text: str, query_tags: list[str]) -> dict[str, Any]:
    repo_tags = {normalize_title(str(tag)).replace(" ", "-") for tag in repo_item.get("tags", []) if str(tag).strip()}
    repo_topics = {normalize_title(str(topic)) for topic in repo_item.get("topics", []) if str(topic).strip()}
    query_terms_set = set(query_terms(query_text))
    repo_text = " ".join(
        [
            str(repo_item.get("repo_name") or ""),
            str(repo_item.get("short_summary") or ""),
            " ".join(str(item) for item in repo_item.get("frameworks", [])),
            " ".join(str(item) for item in repo_item.get("entrypoints", [])),
            str(repo_item.get("import_type") or ""),
        ]
    )
    repo_terms = set(query_terms(repo_text))
    matched_tags = sorted(repo_tags & {normalize_title(tag).replace(" ", "-") for tag in query_tags if str(tag).strip()})
    normalized_query = normalize_title(query_text)
    matched_topics = sorted(topic for topic in repo_topics if topic and topic in normalized_query)
    matched_terms = sorted(repo_terms & query_terms_set)

    score = (6 * len(matched_tags)) + (4 * len(matched_topics)) + (2 * len(matched_terms))
    if repo_item.get("frameworks"):
        score += 1
    if repo_item.get("entrypoints"):
        score += 1

    reasons: list[str] = []
    if matched_tags:
        reasons.append(f"tag:{', '.join(matched_tags[:2])}")
    if matched_topics:
        reasons.append(f"topic:{', '.join(matched_topics[:2])}")
    if matched_terms:
        reasons.append(f"summary:{', '.join(matched_terms[:3])}")
    if repo_item.get("frameworks"):
        reasons.append(f"framework:{', '.join(str(item) for item in repo_item.get('frameworks', [])[:2])}")
    if not reasons and repo_item.get("short_summary"):
        reasons.append("summary:generic-fit")

    return {
        "score": score,
        "reasons": reasons,
        "matched_tags": matched_tags,
        "matched_topics": matched_topics,
        "matched_terms": matched_terms,
    }


def ranked_repo_contexts(project_root: Path, charter: dict[str, Any], literature_map: dict[str, Any], seed: str, limit: int = 3) -> list[dict[str, Any]]:
    repo_index = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")
    repo_items = list(repo_index.get("items", {}).values())
    retrieval = literature_map.get("retrieval", {}) if isinstance(literature_map, dict) else {}
    query_tags = retrieval.get("query_tags", []) if isinstance(retrieval, dict) else []
    query_text = proposal_query_text(charter, literature_map, seed)
    ranked: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for repo_item in repo_items:
        breakdown = repo_relevance(repo_item, query_text, query_tags if isinstance(query_tags, list) else [])
        ranked.append((breakdown["score"], repo_item, breakdown))
    ranked.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    contexts: list[dict[str, Any]] = []
    for score, repo_item, breakdown in ranked[:limit]:
        contexts.append(
            {
                "repo_id": repo_item.get("id", ""),
                "repo_name": repo_item.get("repo_name", ""),
                "short_summary": repo_item.get("short_summary", ""),
                "entrypoints": repo_item.get("entrypoints", [])[:3],
                "frameworks": repo_item.get("frameworks", []),
                "score": score,
                "reasons": breakdown["reasons"],
            }
        )
    return contexts


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed idea proposals for a program.")
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "idea-forge")
    program_root = research_root(project_root) / "programs" / args.program_id
    charter_path = program_root / "charter.yaml"
    literature_map_path = program_root / "evidence" / "literature-map.yaml"
    repo_index = repo_index_path(project_root)
    charter = load_yaml(program_root / "charter.yaml", default={})
    literature_map = load_yaml(program_root / "evidence" / "literature-map.yaml", default={})
    if not isinstance(charter, dict) or not isinstance(literature_map, dict):
        raise SystemExit("Program charter and literature map must exist before seeding ideas.")

    index_path = program_root / "ideas" / "index.yaml"
    index_payload = load_index(index_path, f"{args.program_id}-ideas", "idea-forge")
    paper_refs = list(literature_map.get("paper_refs", []))
    direction_titles = [item.get("title", "") for item in literature_map.get("candidate_directions", []) if isinstance(item, dict)]
    gap_titles = [first_observed_text(item) for item in literature_map.get("gaps", []) if isinstance(item, dict)]
    seeds = direction_titles or gap_titles or [charter.get("goal", "baseline direction")]

    created = 0
    report_repo_ids: set[str] = set()
    for seed in seeds:
        if created >= args.limit:
            break
        title = seed if seed else f"{charter.get('question', 'research question')} variant"
        idea_id = idea_id_from_title(args.program_id, title)
        proposal_path = program_root / "ideas" / idea_id / "proposal.yaml"
        if proposal_path.exists() and not args.force:
            continue
        repo_context = ranked_repo_contexts(project_root, charter, literature_map, title, limit=3)
        repo_candidates = [item["repo_id"] for item in repo_context if item.get("repo_id")]
        report_repo_ids.update(repo_candidates)
        top_repo = repo_context[0] if repo_context else {}
        novelty = 4 if "light" in title.lower() or "new" in title.lower() else 3
        proposal = {
            **yaml_default(idea_id, "idea-forge", status="proposed", confidence=0.6),
            "inputs": [
                charter_path.relative_to(project_root).as_posix(),
                literature_map_path.relative_to(project_root).as_posix(),
                repo_index.relative_to(project_root).as_posix(),
                *[f"lit:{ref}" for ref in paper_refs[:3]],
                *[f"repo:{ref}" for ref in repo_candidates[:2]],
            ],
            "idea_id": idea_id,
            "title": title,
            "core_hypothesis": f"If we focus on `{title}`, we can test a constrained but meaningful improvement for `{charter.get('question', '')}`.",
            "novelty_claim": "Combine the current evidence cluster with a narrower implementation surface instead of proposing a full-stack rewrite.",
            "mechanism": "Use one dominant literature cluster as the baseline and perturb a single module or evaluation slice first.",
            "required_changes": [
                "Select one compatible repo as the implementation host.",
                "Define a smallest viable experiment before expanding the scope.",
                *(
                    [f"Start from `{top_repo.get('repo_id')}` because it already looks aligned with the idea surface."]
                    if top_repo.get("repo_id")
                    else []
                ),
            ],
            "evidence_links": {
                "literature": [f"lit:{ref}" for ref in paper_refs[:3]],
                "repos": [f"repo:{ref}" for ref in repo_candidates[:2]],
            },
            "repo_context": repo_context,
            "scores": {
                "novelty": novelty,
                "feasibility": 3,
                "repo_fit": 4 if top_repo.get("score", 0) >= 10 else 3 if top_repo.get("score", 0) >= 5 else 2 if repo_candidates else 1,
                "validation_speed": 4,
            },
            "Observed": [
                f"Seeded from literature direction: {title}.",
                *(
                    [
                        "Top repo candidates: "
                        + "; ".join(
                            f"{item['repo_id']} ({item.get('short_summary') or 'no summary'}; {', '.join(item.get('reasons', [])[:2]) or 'generic fit'})"
                            for item in repo_context[:2]
                        )
                    ]
                    if repo_context
                    else ["No canonical repo candidates are available yet."]
                ),
            ],
            "Inferred": ["This proposal is intentionally scoped to be testable on an existing codebase."],
            "Suggested": ["Send this proposal to idea-review-board for novelty and kill-test review."],
            "OpenQuestions": ["Which repo gives the shortest path to a clean baseline?"],
        }
        write_yaml_if_changed(proposal_path, proposal)
        index_payload["items"][idea_id] = {
            "id": idea_id,
            "title": title,
            "status": "proposed",
            "proposal_path": proposal_path.relative_to(project_root).as_posix(),
            "updated_at": utc_now_iso(),
        }
        created += 1

    index_payload["generated_at"] = utc_now_iso()
    index_payload["inputs"] = [
        charter_path.relative_to(project_root).as_posix(),
        literature_map_path.relative_to(project_root).as_posix(),
        repo_index.relative_to(project_root).as_posix(),
    ]
    write_yaml_if_changed(index_path, index_payload)
    state_path = program_root / "workflow" / "state.yaml"
    state = load_yaml(state_path, default={})
    if isinstance(state, dict):
        state["generated_at"] = utc_now_iso()
        state["inputs"] = [literature_map_path.relative_to(project_root).as_posix(), index_path.relative_to(project_root).as_posix()]
        if should_promote_stage(str(state.get("stage") or ""), "idea-generation"):
            state["stage"] = "idea-generation"
        if len(index_payload.get("items", {})) == 1:
            state["active_idea_id"] = next(iter(index_payload["items"]))
        elif not state.get("selected_idea_id"):
            state["active_idea_id"] = ""
        write_yaml_if_changed(state_path, state)
    current_idea_ids = sorted(index_payload.get("items", {}).keys())
    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "idea-forge",
            "event_type": "ideas-seeded",
            "title": "Idea proposals refreshed",
            "summary": (
                f"Seeded {created} idea proposal(s)"
                + (f"; current inventory includes {', '.join(current_idea_ids[:3])}" if current_idea_ids else "")
                + "."
            ),
            "artifacts": [
                index_path.relative_to(project_root).as_posix(),
                *[
                    (program_root / "ideas" / idea_id / "proposal.yaml").relative_to(project_root).as_posix()
                    for idea_id in current_idea_ids[:6]
                ],
            ],
            "idea_ids": current_idea_ids,
            "repo_ids": sorted(report_repo_ids),
            "stage": "idea-generation",
        },
        generated_by="idea-forge",
    )
    print(f"[ok] seeded {created} idea(s) for program {args.program_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

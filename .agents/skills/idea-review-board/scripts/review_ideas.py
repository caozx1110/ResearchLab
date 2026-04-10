#!/usr/bin/env python3
"""Review, list, and collaboratively refine idea proposals for a program."""

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
    load_list_document,
    load_literature_records,
    load_yaml,
    normalize_title,
    research_root,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)


COLLAB_RECOMMENDATION_TO_STATUS = {
    "promising": "awaiting-user-decision",
    "needs-evidence": "needs-evidence",
    "needs-revision": "needs-revision",
}


def normalize_legacy_argv(argv: list[str]) -> list[str]:
    commands = {"list", "review", "select-best", "review-assist", "revise-assist"}
    if len(argv) <= 1 or "--help" in argv[1:] or "-h" in argv[1:]:
        return argv
    if len(argv) > 1 and argv[1] in commands:
        return argv
    normalized = [argv[0]]
    tail = list(argv[1:])
    if "--list" in tail:
        tail.remove("--list")
        return normalized + ["list", *tail]
    if "--review-assist" in tail:
        tail.remove("--review-assist")
        return normalized + ["review-assist", *tail]
    if "--revise-assist" in tail:
        tail.remove("--revise-assist")
        return normalized + ["revise-assist", *tail]
    if "--select-best" in tail:
        tail.remove("--select-best")
        return normalized + ["select-best", *tail]
    return normalized + ["review", *tail]


def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def compact_text(text: str, limit: int = 140) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def proposal_paths(program_root: Path, *, idea_ids: list[str] | None = None) -> list[Path]:
    paths = sorted(program_root.glob("ideas/*/proposal.yaml"))
    if not idea_ids:
        return paths
    allowed = set(idea_ids)
    return [path for path in paths if path.parent.name in allowed]


def overlap_signal(title: str, literature_titles: list[str]) -> int:
    title_key = set(normalize_title(title).split())
    hits = 0
    for literature_title in literature_titles:
        if len(title_key & set(normalize_title(literature_title).split())) >= 4:
            hits += 1
    return hits


def evidence_links_for(proposal: dict[str, Any]) -> tuple[list[str], list[str]]:
    links = proposal.get("evidence_links", {})
    if not isinstance(links, dict):
        return [], []
    literature_links = [str(item) for item in links.get("literature", []) if str(item).strip()]
    repo_links = [str(item) for item in links.get("repos", []) if str(item).strip()]
    return literature_links, repo_links


def proposal_scores(proposal: dict[str, Any]) -> dict[str, int]:
    payload = proposal.get("scores", {})
    if not isinstance(payload, dict):
        payload = {}
    return {
        key: int(payload.get(key, 0) or 0)
        for key in ("novelty", "feasibility", "repo_fit", "validation_speed")
    }


def existing_decision_status(decision_path: Path) -> str:
    payload = load_yaml(decision_path, default={})
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("decision") or payload.get("status") or "").strip()


def collaborative_recommendation(total: int, *, evidence_gap: bool, overlap_hits: int) -> str:
    if evidence_gap:
        return "needs-evidence"
    if total >= 12 and overlap_hits <= 1:
        return "promising"
    return "needs-revision"


def auto_decision_status(total: int) -> str:
    if total >= 12:
        return "shortlisted"
    if total >= 9:
        return "parked"
    return "killed"


def repo_summary(proposal: dict[str, Any]) -> str:
    repo_context = proposal.get("repo_context", [])
    if not isinstance(repo_context, list) or not repo_context:
        return "No repo context yet."
    parts: list[str] = []
    for item in repo_context[:2]:
        if not isinstance(item, dict):
            continue
        repo_id = str(item.get("repo_id") or "unknown-repo")
        summary = compact_text(item.get("short_summary", ""), 90)
        reasons = ", ".join(str(value) for value in item.get("reasons", [])[:2]) or "generic-fit"
        parts.append(f"{repo_id} ({summary or 'no summary'}; {reasons})")
    return "; ".join(parts) if parts else "No repo context yet."


def review_inputs(project_root: Path, proposal_path: Path, literature_map_path: Path, map_refs: list[str]) -> list[str]:
    return [
        relative_path(project_root, proposal_path),
        relative_path(project_root, literature_map_path),
        *[(ref if str(ref).startswith("lit:") else f"lit:{ref}") for ref in map_refs[:5]],
    ]


def build_review_payload(
    project_root: Path,
    proposal_path: Path,
    proposal: dict[str, Any],
    literature_map_path: Path,
    map_refs: list[str],
    literature_titles: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    idea_id = str(proposal.get("idea_id") or proposal_path.parent.name)
    title = str(proposal.get("title") or idea_id)
    scores = proposal_scores(proposal)
    total = sum(scores.values())
    overlap_hits = overlap_signal(title, literature_titles)
    if overlap_hits >= 2:
        total -= 2
    literature_links, repo_links = evidence_links_for(proposal)
    evidence_gap = len(literature_links) < 2
    novelty_label = "medium"
    if overlap_hits == 0 and total >= 12:
        novelty_label = "high"
    elif overlap_hits >= 2:
        novelty_label = "low"
    recommendation = collaborative_recommendation(total, evidence_gap=evidence_gap, overlap_hits=overlap_hits)
    status = COLLAB_RECOMMENDATION_TO_STATUS[recommendation]
    reason = f"Adjusted score={total}, novelty={novelty_label}, overlap_hits={overlap_hits}."
    next_action = "user-compare-and-pick" if recommendation == "promising" else "gather-more-evidence" if recommendation == "needs-evidence" else "revise-proposal"
    user_questions = [
        "Which part of the proposal would still matter if the gain only appears on one narrow benchmark slice?",
        "Is the novelty really in the mechanism, or mostly in the choice of benchmark, embodiment, or evaluation cut?",
    ]
    if repo_links:
        user_questions.append("Do we want the shortest path to a baseline, or the most novel repo integration surface?")
    if evidence_gap:
        user_questions.append("Which recent papers or project pages could quickly falsify this direction before we invest more effort?")
    revision_targets = [
        "Tighten the proposal to one falsifiable claim and one minimum viable experiment.",
        "Make the implementation host and edit surface explicit instead of leaving repo fit implicit.",
    ]
    if evidence_gap:
        revision_targets.append("Add at least one more directly relevant literature reference before selection.")
    if overlap_hits >= 2:
        revision_targets.append("Sharpen the novelty claim against nearby prior art instead of assuming the overlap is acceptable.")

    review = {
        **yaml_default(f"{idea_id}-review", "idea-review-board", status="reviewed", confidence=0.72),
        "inputs": review_inputs(project_root, proposal_path, literature_map_path, map_refs),
        "strengths": {
            "Observed": [
                f"Proposal references {len(literature_links)} literature entries and {len(repo_links)} repo entries.",
                f"Current repo context: {repo_summary(proposal)}",
            ],
            "Inferred": ["A bounded implementation cut should keep iteration speed acceptable."],
            "Suggested": ["Prefer a falsification-first first experiment over a broad method rollout."],
            "OpenQuestions": [],
        },
        "failure_modes": {
            "Observed": ["The proposal may still overlap with nearby prior art if novelty checks are stale."],
            "Inferred": ["Repo integration risk remains under-specified unless the host repo and seams are made explicit."],
            "Suggested": ["Treat the first experiment as a decision probe rather than a paper-ready study."],
            "OpenQuestions": [],
        },
        "killer_questions": [
            "Does the proposal still matter if it only improves one benchmark slice?",
            "Can we reject the idea with one constrained ablation instead of a full reimplementation?",
        ],
        "comparison": {
            "Observed": [
                f"Literature map currently tracks {len(map_refs)} paper refs.",
                "See ideas/index.yaml for the current reviewed inventory.",
            ],
            "Inferred": [],
            "Suggested": ["Use the list command before selecting so sibling ideas are compared on the same frame."],
            "OpenQuestions": [],
        },
        "novelty_assessment": {
            "Observed": [f"Overlap signal against current literature titles: {overlap_hits}."],
            "Inferred": [f"Novelty bar is currently assessed as `{novelty_label}`."],
            "Suggested": ["Trigger literature-scout if the novelty bar is low but the idea remains attractive."],
            "OpenQuestions": [],
        },
        "evidence_gaps": {
            "Observed": ["Literature evidence is thin for this proposal."] if evidence_gap else [],
            "Inferred": ["Fresh outside evidence may be needed before final selection."] if evidence_gap else [],
            "Suggested": ["Open an evidence request for literature-scout."] if evidence_gap else [],
            "OpenQuestions": ["Which recent papers could disprove this idea?"] if evidence_gap else [],
        },
        "collaboration": {
            "Observed": [f"Collaborative review recommendation: `{recommendation}`."],
            "Inferred": [f"Default handoff should be `{next_action}` rather than automatic selection."],
            "Suggested": revision_targets,
            "OpenQuestions": user_questions,
        },
        "kill_tests": [
            "Run the simplest possible baseline swap and stop if gains vanish under the same evaluation protocol.",
            "Measure whether the claimed improvement disappears when one supporting assumption is removed.",
        ],
        "score_breakdown": {
            "proposal_scores": scores,
            "adjusted_total": total,
            "novelty_label": novelty_label,
            "collab_recommendation": recommendation,
        },
        "recommendation": recommendation,
    }
    summary = {
        "idea_id": idea_id,
        "title": title,
        "adjusted_total": total,
        "novelty_label": novelty_label,
        "overlap_hits": overlap_hits,
        "evidence_gap": evidence_gap,
        "collab_recommendation": recommendation,
        "collab_status": status,
        "next_action": next_action,
        "reason": reason,
        "literature_links": literature_links,
        "repo_links": repo_links,
        "review": review,
    }
    return review, summary


def collaborative_decision_payload(
    idea_id: str,
    proposal_path: Path,
    review_path: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        **yaml_default(f"{idea_id}-decision", "idea-review-board", status=summary["collab_status"], confidence=0.66),
        "inputs": [proposal_path.as_posix(), review_path.as_posix()],
        "idea_id": idea_id,
        "decision": "pending-user-decision",
        "recommended_bucket": summary["collab_recommendation"],
        "reason": summary["reason"],
        "next_action": summary["next_action"],
        "selection_policy": "user-confirmation-required",
        "user_action_needed": "review-and-compare-ideas",
    }


def automatic_decision_payload(
    idea_id: str,
    proposal_path: Path,
    review_path: Path,
    summary: dict[str, Any],
    *,
    selected: bool,
) -> dict[str, Any]:
    status = "selected" if selected else auto_decision_status(summary["adjusted_total"])
    next_action = "send-to-method-designer" if selected else "gather-more-evidence" if status != "shortlisted" else "wait-for-user-confirmation"
    reason = f"Selected as top-ranked idea with adjusted score {summary['adjusted_total']}." if selected else summary["reason"]
    return {
        **yaml_default(f"{idea_id}-decision", "idea-review-board", status=status, confidence=0.68),
        "inputs": [proposal_path.as_posix(), review_path.as_posix()],
        "idea_id": idea_id,
        "decision": status,
        "recommended_bucket": summary["collab_recommendation"],
        "reason": reason,
        "next_action": next_action,
        "selection_policy": "auto-selected-by-user-request" if selected else "auto-ranked-by-user-request",
    }


def render_review_assist(proposal: dict[str, Any], summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# Review Assist: {proposal.get('title', summary['idea_id'])}",
            "",
            f"- Idea ID: `{summary['idea_id']}`",
            f"- Collaborative recommendation: `{summary['collab_recommendation']}`",
            f"- Adjusted score: `{summary['adjusted_total']}`",
            f"- Novelty label: `{summary['novelty_label']}`",
            f"- Overlap signal: `{summary['overlap_hits']}`",
            f"- Evidence gap: `{summary['evidence_gap']}`",
            "",
            "## Snapshot",
            "",
            f"- Hypothesis: {compact_text(proposal.get('core_hypothesis', ''), 200)}",
            f"- Mechanism: {compact_text(proposal.get('mechanism', ''), 200)}",
            f"- Repo context: {repo_summary(proposal)}",
            "",
            "## What To Pressure-Test",
            "",
            "- Is the core claim narrower than the implementation plan, or are we still trying to prove too many things at once?",
            "- Which assumption would fail first: novelty, feasibility, or repo integration?",
            "- If we had to reject this idea in one week, what is the cheapest decisive experiment?",
            "",
            "## User Questions",
            "",
            *[f"- {question}" for question in summary["review"]["collaboration"]["OpenQuestions"]],
            "",
            "## Suggested Next Move",
            "",
            f"- {summary['next_action']}",
            "",
        ]
    )


def render_revision_assist(proposal: dict[str, Any], summary: dict[str, Any]) -> str:
    required_changes = proposal.get("required_changes", [])
    change_lines = [f"- {item}" for item in required_changes[:4]] if isinstance(required_changes, list) and required_changes else ["- Add a more explicit edit surface."]
    return "\n".join(
        [
            f"# Revision Assist: {proposal.get('title', summary['idea_id'])}",
            "",
            f"- Idea ID: `{summary['idea_id']}`",
            f"- Current recommendation: `{summary['collab_recommendation']}`",
            "",
            "## Keep",
            "",
            f"- {compact_text(proposal.get('novelty_claim', ''), 180) or 'Keep the existing novelty claim, but make it more falsifiable.'}",
            f"- {compact_text(proposal.get('mechanism', ''), 180) or 'Keep the mechanism narrow and baseline-compatible.'}",
            "",
            "## Tighten",
            "",
            "- Rewrite the proposal around one core hypothesis, one host repo choice, and one minimum viable experiment.",
            "- Reduce any language that sounds like a full-stack rewrite unless that is truly necessary.",
            *[f"- {item}" for item in summary["review"]["collaboration"]["Suggested"]],
            "",
            "## Required Changes To Clarify",
            "",
            *change_lines,
            "",
            "## Suggested Revision Prompt",
            "",
            "```text",
            f"请基于当前 proposal `{summary['idea_id']}` 做一轮收紧，不要换题。保留最强的核心假设，但把 novelty claim、mechanism、required_changes 和最小实验改成更可证伪、更容易比较 sibling ideas 的版本；同时明确 host repo 和 edit surface。",
            "```",
            "",
        ]
    )


def ensure_program_paths(project_root: Path, program_id: str) -> dict[str, Path]:
    program_root = research_root(project_root) / "programs" / program_id
    return {
        "program_root": program_root,
        "literature_map_path": program_root / "evidence" / "literature-map.yaml",
        "index_path": program_root / "ideas" / "index.yaml",
        "evidence_requests_path": program_root / "workflow" / "evidence-requests.yaml",
        "state_path": program_root / "workflow" / "state.yaml",
    }


def load_review_context(project_root: Path, program_id: str, *, idea_ids: list[str] | None = None) -> dict[str, Any]:
    paths = ensure_program_paths(project_root, program_id)
    literature_records = load_literature_records(project_root)
    literature_titles = [str(record.get("canonical_title") or "") for record in literature_records]
    literature_map = load_yaml(paths["literature_map_path"], default={})
    if not isinstance(literature_map, dict):
        literature_map = {}
    map_refs = [str(ref) for ref in literature_map.get("paper_refs", []) if str(ref).strip()]
    proposals: list[dict[str, Any]] = []
    for proposal_path in proposal_paths(paths["program_root"], idea_ids=idea_ids):
        proposal = load_yaml(proposal_path, default={})
        if not isinstance(proposal, dict):
            continue
        idea_id = str(proposal.get("idea_id") or proposal_path.parent.name)
        review, summary = build_review_payload(
            project_root,
            proposal_path,
            proposal,
            paths["literature_map_path"],
            map_refs,
            literature_titles,
        )
        proposals.append(
            {
                "idea_id": idea_id,
                "proposal_path": proposal_path,
                "review_path": proposal_path.parent / "review.yaml",
                "decision_path": proposal_path.parent / "decision.yaml",
                "review_assist_path": proposal_path.parent / "review-assist.md",
                "revision_assist_path": proposal_path.parent / "revision-assist.md",
                "proposal": proposal,
                "review": review,
                "summary": summary,
            }
        )
    proposals.sort(key=lambda item: (-item["summary"]["adjusted_total"], item["idea_id"]))
    return {**paths, "literature_map": literature_map, "map_refs": map_refs, "proposals": proposals}


def open_evidence_requests(project_root: Path, payload: dict[str, Any]) -> None:
    evidence_requests = load_list_document(
        payload["evidence_requests_path"],
        f"{payload['program_root'].name}-evidence-requests",
        "research-conductor",
    )
    evidence_requests["inputs"] = [relative_path(project_root, payload["literature_map_path"])]
    for item in payload["proposals"]:
        summary = item["summary"]
        if not summary["evidence_gap"]:
            continue
        request_id = f"{item['idea_id']}-external-evidence"
        if any(entry.get("request_id") == request_id for entry in evidence_requests["items"]):
            continue
        evidence_requests["items"].append(
            {
                "request_id": request_id,
                "priority": "high",
                "blocking_reason": f"{item['idea_id']} needs more literature evidence before selection.",
                "suggested_skill": "literature-scout",
                "notes": "Look for the newest closely overlapping work.",
                "status": "open",
            }
        )
    evidence_requests["generated_at"] = utc_now_iso()
    write_yaml_if_changed(payload["evidence_requests_path"], evidence_requests)


def update_index(project_root: Path, payload: dict[str, Any], *, mode: str, selected_idea_id: str = "") -> None:
    index_payload = load_index(payload["index_path"], f"{payload['program_root'].name}-ideas", "idea-review-board")
    index_payload["generated_at"] = utc_now_iso()
    index_payload["inputs"] = [
        relative_path(project_root, payload["literature_map_path"]),
        *[relative_path(project_root, item["proposal_path"]) for item in payload["proposals"]],
    ]
    for item in payload["proposals"]:
        idea_id = item["idea_id"]
        summary = item["summary"]
        row = index_payload["items"].setdefault(idea_id, {})
        row["id"] = idea_id
        row["title"] = str(item["proposal"].get("title") or idea_id)
        row["proposal_path"] = relative_path(project_root, item["proposal_path"])
        row["review_path"] = relative_path(project_root, item["review_path"])
        row["decision_path"] = relative_path(project_root, item["decision_path"])
        row["updated_at"] = utc_now_iso()
        row["adjusted_total"] = summary["adjusted_total"]
        row["recommended_bucket"] = summary["collab_recommendation"]
        if mode == "select-best":
            row["status"] = "selected" if idea_id == selected_idea_id else auto_decision_status(summary["adjusted_total"])
        else:
            row["status"] = "selected" if existing_decision_status(item["decision_path"]) == "selected" else summary["collab_status"]
    write_yaml_if_changed(payload["index_path"], index_payload)


def update_state(project_root: Path, payload: dict[str, Any], *, mode: str, selected_idea_id: str = "") -> None:
    state = load_yaml(payload["state_path"], default={})
    if not isinstance(state, dict):
        state = yaml_default(f"{payload['program_root'].name}-state", "research-conductor")
    top_id = payload["proposals"][0]["idea_id"] if payload["proposals"] else ""
    state["generated_at"] = utc_now_iso()
    state["inputs"] = [relative_path(project_root, payload["index_path"]), relative_path(project_root, payload["literature_map_path"])]
    if mode == "select-best" and selected_idea_id:
        state["stage"] = "method-design"
        state["active_idea_id"] = selected_idea_id
        state["selected_idea_id"] = selected_idea_id
    else:
        if not state.get("selected_idea_id"):
            state["stage"] = "idea-review"
        if top_id:
            state["active_idea_id"] = top_id
    write_yaml_if_changed(payload["state_path"], state)


def command_review(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "idea-review-board")
    payload = load_review_context(project_root, args.program_id, idea_ids=list(args.idea_id))
    if not payload["proposals"]:
        raise SystemExit(f"No idea proposals found for program {args.program_id}.")
    for item in payload["proposals"]:
        write_yaml_if_changed(item["review_path"], item["review"])
        if existing_decision_status(item["decision_path"]) == "selected":
            continue
        decision = collaborative_decision_payload(
            item["idea_id"],
            item["proposal_path"].relative_to(project_root),
            item["review_path"].relative_to(project_root),
            item["summary"],
        )
        write_yaml_if_changed(item["decision_path"], decision)
    open_evidence_requests(project_root, payload)
    update_index(project_root, payload, mode="review")
    update_state(project_root, payload, mode="review")
    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "idea-review-board",
            "event_type": "ideas-reviewed",
            "title": "Idea review completed",
            "summary": (
                f"Reviewed {len(payload['proposals'])} idea proposal(s)"
                + (
                    f"; current top candidate is {payload['proposals'][0]['idea_id']}"
                    if payload["proposals"]
                    else ""
                )
                + "; selection still requires explicit confirmation."
            ),
            "artifacts": [
                relative_path(project_root, payload["index_path"]),
                *[relative_path(project_root, item["review_path"]) for item in payload["proposals"][:6]],
                *[relative_path(project_root, item["decision_path"]) for item in payload["proposals"][:6]],
            ],
            "idea_ids": [item["idea_id"] for item in payload["proposals"]],
            "paper_ids": sorted(
                {
                    link.split(":", 1)[1]
                    for item in payload["proposals"]
                    for link in evidence_links_for(item["proposal"])[0]
                    if link.startswith("lit:")
                }
            ),
            "repo_ids": sorted(
                {
                    link.split(":", 1)[1]
                    for item in payload["proposals"]
                    for link in evidence_links_for(item["proposal"])[1]
                    if link.startswith("repo:")
                }
            ),
            "stage": "idea-review",
        },
        generated_by="idea-review-board",
    )
    print(
        f"[ok] reviewed {len(payload['proposals'])} idea(s) for program {args.program_id}; "
        "selection still requires explicit user confirmation"
    )
    return 0


def command_select_best(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "idea-review-board")
    payload = load_review_context(project_root, args.program_id, idea_ids=list(args.idea_id))
    if not payload["proposals"]:
        raise SystemExit(f"No idea proposals found for program {args.program_id}.")
    best_id = payload["proposals"][0]["idea_id"]
    for item in payload["proposals"]:
        decision = automatic_decision_payload(
            item["idea_id"],
            item["proposal_path"].relative_to(project_root),
            item["review_path"].relative_to(project_root),
            item["summary"],
            selected=item["idea_id"] == best_id,
        )
        write_yaml_if_changed(item["review_path"], item["review"])
        write_yaml_if_changed(item["decision_path"], decision)
    open_evidence_requests(project_root, payload)
    update_index(project_root, payload, mode="select-best", selected_idea_id=best_id)
    update_state(project_root, payload, mode="select-best", selected_idea_id=best_id)
    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "idea-review-board",
            "event_type": "idea-selected",
            "title": "Idea selected for design",
            "summary": f"Auto-selected {best_id} after reviewing {len(payload['proposals'])} idea proposal(s).",
            "artifacts": [
                relative_path(project_root, payload["index_path"]),
                *[relative_path(project_root, item["review_path"]) for item in payload["proposals"][:6]],
                *[relative_path(project_root, item["decision_path"]) for item in payload["proposals"][:6]],
            ],
            "idea_ids": [item["idea_id"] for item in payload["proposals"]],
            "stage": "method-design",
        },
        generated_by="idea-review-board",
    )
    print(f"[ok] auto-selected `{best_id}` for program {args.program_id} at explicit user request")
    return 0


def command_list(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "idea-review-board")
    payload = load_review_context(project_root, args.program_id, idea_ids=list(args.idea_id))
    if not payload["proposals"]:
        raise SystemExit(f"No idea proposals found for program {args.program_id}.")
    print(f"ideas for program {args.program_id}:")
    for index, item in enumerate(payload["proposals"], start=1):
        summary = item["summary"]
        hypothesis = compact_text(item["proposal"].get("core_hypothesis", ""), 110)
        stored_decision = load_yaml(item["decision_path"], default={})
        stored_status = summary["collab_status"]
        if isinstance(stored_decision, dict):
            stored_status = str(stored_decision.get("status") or stored_decision.get("decision") or stored_status)
        print(f"[{index}] {item['idea_id']}")
        print(f"  title: {item['proposal'].get('title', item['idea_id'])}")
        print(f"  current_status: {stored_status}")
        print(f"  recommendation: {summary['collab_recommendation']} -> {summary['next_action']}")
        print(f"  adjusted_score: {summary['adjusted_total']} | novelty: {summary['novelty_label']} | evidence_gap: {summary['evidence_gap']}")
        print(f"  hypothesis: {hypothesis or 'n/a'}")
        print(f"  repos: {repo_summary(item['proposal'])}")
    return 0


def command_review_assist(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "idea-review-board")
    payload = load_review_context(project_root, args.program_id, idea_ids=list(args.idea_id))
    if not payload["proposals"]:
        raise SystemExit(f"No idea proposals found for program {args.program_id}.")
    for item in payload["proposals"]:
        write_text_if_changed(item["review_assist_path"], render_review_assist(item["proposal"], item["summary"]))
        print(f"[ok] wrote {relative_path(project_root, item['review_assist_path'])}")
    return 0


def command_revise_assist(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "idea-review-board")
    payload = load_review_context(project_root, args.program_id, idea_ids=list(args.idea_id))
    if not payload["proposals"]:
        raise SystemExit(f"No idea proposals found for program {args.program_id}.")
    for item in payload["proposals"]:
        write_text_if_changed(item["revision_assist_path"], render_revision_assist(item["proposal"], item["summary"]))
        print(f"[ok] wrote {relative_path(project_root, item['revision_assist_path'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review idea proposals for a program.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared_arguments(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--program-id", required=True)
        subparser.add_argument("--idea-id", action="append", default=[], help="Limit the command to one or more idea IDs")

    review_cmd = subparsers.add_parser("review", help="Review ideas collaboratively without auto-selecting one")
    add_shared_arguments(review_cmd)
    review_cmd.set_defaults(func=command_review)

    select_cmd = subparsers.add_parser("select-best", help="Auto-select the top idea only when the user explicitly requests it")
    add_shared_arguments(select_cmd)
    select_cmd.set_defaults(func=command_select_best)

    list_cmd = subparsers.add_parser("list", help="List current idea candidates with concise review context")
    add_shared_arguments(list_cmd)
    list_cmd.set_defaults(func=command_list)

    review_assist_cmd = subparsers.add_parser("review-assist", help="Write collaborative review prompts and pressure-test questions")
    add_shared_arguments(review_assist_cmd)
    review_assist_cmd.set_defaults(func=command_review_assist)

    revise_assist_cmd = subparsers.add_parser("revise-assist", help="Write proposal revision guidance without rewriting the proposal")
    add_shared_arguments(revise_assist_cmd)
    revise_assist_cmd.set_defaults(func=command_revise_assist)

    return parser


def main() -> int:
    argv = normalize_legacy_argv(sys.argv)
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

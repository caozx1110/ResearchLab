#!/usr/bin/env python3
"""Generate a design pack for the selected idea in a research program."""

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
    infer_repo_roles,
    load_index,
    load_yaml,
    normalize_title,
    query_keyword_terms,
    repo_index_path,
    research_root,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)


def choose_idea(program_root: Path, requested_idea_id: str) -> str:
    if requested_idea_id:
        return requested_idea_id
    state = load_yaml(program_root / "workflow" / "state.yaml", default={})
    if isinstance(state, dict) and state.get("selected_idea_id"):
        return str(state["selected_idea_id"])
    index_payload = load_index(program_root / "ideas" / "index.yaml", "ideas", "method-designer")
    for idea_id, item in index_payload.get("items", {}).items():
        if item.get("status") == "selected":
            return str(idea_id)
    raise SystemExit("No selected idea found. Run idea-review-board with --select-best or pass --idea-id.")


def query_terms(text: str) -> list[str]:
    return query_keyword_terms(text)


def load_selected_decision(decision_path: Path, idea_id: str, *, allow_unselected: bool = False) -> dict[str, Any]:
    decision = load_yaml(decision_path, default={})
    if not isinstance(decision, dict):
        raise SystemExit(
            f"Missing decision for idea {idea_id}. "
            "Run idea-forge to generate candidates, then run idea-review-board --select-best before method design."
        )
    if allow_unselected:
        return decision
    decision_label = str(decision.get("decision") or decision.get("status") or "").strip().lower()
    if decision_label != "selected":
        raise SystemExit(
            f"Idea {idea_id} is not explicitly selected yet ({decision_label or 'missing-status'}). "
            "Run idea-forge to generate candidates and idea-review-board --select-best before method design, "
            "or pass --allow-unselected only when you intentionally want a draft design."
        )
    return decision


def repo_role_hints(repo_item: dict[str, Any]) -> list[str]:
    text = normalize_title(
        " ".join(
            [
                str(repo_item.get("repo_name") or ""),
                str(repo_item.get("short_summary") or ""),
                " ".join(str(item) for item in repo_item.get("tags", [])),
                " ".join(str(item) for item in repo_item.get("topics", [])),
                " ".join(str(item) for item in repo_item.get("entrypoints", [])),
            ]
        )
    )
    return infer_repo_roles(text)


def collaborator_repo_candidates(
    selected_repo: dict[str, Any],
    ranked: list[tuple[int, dict[str, Any], dict[str, Any]]],
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    selected_id = str(selected_repo.get("id") or "")
    selected_roles = set(repo_role_hints(selected_repo))
    collaborators: list[dict[str, Any]] = []
    for score, item, breakdown in ranked[1:]:
        repo_id = str(item.get("id") or "")
        if not repo_id or repo_id == selected_id:
            continue
        roles = repo_role_hints(item)
        complementary = bool(set(roles) - selected_roles) or bool(selected_roles - set(roles))
        if not complementary and score < 6:
            continue
        collaborators.append(
            {
                "repo_id": repo_id,
                "repo_name": item.get("repo_name", ""),
                "role_hints": roles,
                "short_summary": item.get("short_summary", ""),
                "score": score,
                "reasons": breakdown.get("reasons", []),
                "entrypoints": item.get("entrypoints", [])[:3],
            }
        )
        if len(collaborators) >= limit:
            break
    return collaborators


def integration_contracts(host_repo: dict[str, Any], collaborators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    host_roles = set(repo_role_hints(host_repo))
    host_id = str(host_repo.get("id") or "")
    contracts: list[dict[str, Any]] = []
    for item in collaborators:
        collaborator_roles = set(str(role) for role in item.get("role_hints", []))
        collaborator_id = str(item.get("repo_id") or "")
        if "policy-stack" in host_roles and "control-stack" in collaborator_roles:
            contracts.append(
                {
                    "contract_id": f"{host_id}-to-{collaborator_id}",
                    "producer_repo": host_id,
                    "consumer_repo": collaborator_id,
                    "payload": "subgoal-conditioned action chunks or target trajectory proposals",
                    "feedback": "execution status, recovery events, and controller-side state summaries",
                }
            )
        elif "control-stack" in host_roles and "policy-stack" in collaborator_roles:
            contracts.append(
                {
                    "contract_id": f"{collaborator_id}-to-{host_id}",
                    "producer_repo": collaborator_id,
                    "consumer_repo": host_id,
                    "payload": "policy actions or high-level intent tokens",
                    "feedback": "low-level feasibility, latency, and failure labels from the control stack",
                }
            )
        else:
            contracts.append(
                {
                    "contract_id": f"{host_id}-with-{collaborator_id}",
                    "producer_repo": host_id,
                    "consumer_repo": collaborator_id,
                    "payload": "shared experiment configuration and aligned trajectory identifiers",
                    "feedback": "evaluation metrics, logs, and failure traces for cross-repo debugging",
                }
            )
    return contracts


def repo_choice_breakdown(idea: dict[str, Any], review: dict[str, Any], repo_item: dict[str, Any]) -> dict[str, Any]:
    preferred_repo_ids = {
        str(item.get("repo_id"))
        for item in idea.get("repo_context", [])
        if isinstance(item, dict) and str(item.get("repo_id") or "").strip()
    }
    idea_query = " ".join(
        [
            str(idea.get("title") or ""),
            str(idea.get("core_hypothesis") or ""),
            str(idea.get("mechanism") or ""),
            " ".join(str(item) for item in idea.get("required_changes", [])),
            " ".join(str(item) for item in review.get("Observed", [])) if isinstance(review, dict) else "",
        ]
    )
    query_terms_set = set(query_terms(idea_query))
    repo_terms = set(
        query_terms(
            " ".join(
                [
                    str(repo_item.get("repo_name") or ""),
                    str(repo_item.get("short_summary") or ""),
                    " ".join(str(item) for item in repo_item.get("frameworks", [])),
                    " ".join(str(item) for item in repo_item.get("entrypoints", [])),
                    str(repo_item.get("import_type") or ""),
                ]
            )
        )
    )
    normalized_query = normalize_title(idea_query)
    matched_tags = sorted(
        normalize_title(str(tag)).replace(" ", "-")
        for tag in repo_item.get("tags", [])
        if str(tag).strip() and normalize_title(str(tag).replace("-", " ")) in normalized_query
    )
    matched_topics = sorted(
        normalize_title(str(topic))
        for topic in repo_item.get("topics", [])
        if str(topic).strip() and normalize_title(str(topic)) in normalized_query
    )
    matched_terms = sorted(repo_terms & query_terms_set)
    preferred = str(repo_item.get("id") or "") in preferred_repo_ids
    score = (8 if preferred else 0) + (5 * len(matched_tags)) + (4 * len(matched_topics)) + (2 * len(matched_terms))
    if repo_item.get("frameworks"):
        score += 1
    if repo_item.get("entrypoints"):
        score += 1

    reasons: list[str] = []
    if preferred:
        reasons.append("proposal:recommended-repo")
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

    return {"score": score, "reasons": reasons}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a method design pack for a selected idea.")
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--idea-id", default="")
    parser.add_argument("--repo-id", default="")
    parser.add_argument("--allow-unselected", action="store_true")
    args = parser.parse_args()

    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "method-designer")
    program_root = research_root(project_root) / "programs" / args.program_id
    idea_id = choose_idea(program_root, args.idea_id)
    proposal_path = program_root / "ideas" / idea_id / "proposal.yaml"
    review_path = program_root / "ideas" / idea_id / "review.yaml"
    decision_path = program_root / "ideas" / idea_id / "decision.yaml"
    proposal = load_yaml(proposal_path, default={})
    review = load_yaml(review_path, default={})
    decision = load_selected_decision(decision_path, idea_id, allow_unselected=args.allow_unselected)
    decision_label = str(decision.get("decision") or decision.get("status") or "").strip().lower()
    design_status = "selected" if decision_label == "selected" else "draft"
    if not isinstance(proposal, dict):
        raise SystemExit(f"Missing proposal for idea {idea_id}")

    repo_index_file = repo_index_path(project_root)
    repo_index = load_index(repo_index_file, "repo-index", "repo-cataloger")
    repo_items = list(repo_index.get("items", {}).values())
    if args.repo_id:
        ranked = [
            (999, item, {"score": 999, "reasons": ["user:pinned-repo"]})
            for item in repo_items
            if item.get("id") == args.repo_id
        ]
    else:
        ranked = sorted(
            (
                (breakdown["score"], item, breakdown)
                for item in repo_items
                for breakdown in [repo_choice_breakdown(proposal, review if isinstance(review, dict) else {}, item)]
            ),
            reverse=True,
            key=lambda pair: (pair[0], pair[1].get("id", "")),
        )
    selected_repo = ranked[0][1] if ranked else {}
    selected_repo_breakdown = ranked[0][2] if ranked else {"score": 0, "reasons": []}
    selected_repo_roles = repo_role_hints(selected_repo) if selected_repo else []
    supporting_repos = collaborator_repo_candidates(selected_repo, ranked) if selected_repo else []
    integration_mode = "dual-repo" if supporting_repos else "single-repo"
    contracts = integration_contracts(selected_repo, supporting_repos) if selected_repo else []
    alternatives = [item.get("id", "") for _score, item, _breakdown in ranked[1:3]]
    candidate_repos = [
        {
            "repo_id": item.get("id", ""),
            "repo_name": item.get("repo_name", ""),
            "short_summary": item.get("short_summary", ""),
            "role_hints": repo_role_hints(item),
            "score": score,
            "reasons": breakdown.get("reasons", []),
        }
        for score, item, breakdown in ranked[:3]
    ]
    selected_repo_summary_path = (
        (research_root(project_root) / "library" / "repos" / selected_repo.get("id", "") / "summary.yaml").relative_to(project_root).as_posix()
        if selected_repo.get("id")
        else ""
    )

    selected_payload = {
        **yaml_default(f"{args.program_id}-selected-idea", "method-designer", status=design_status, confidence=0.72),
        "inputs": [
            proposal_path.relative_to(project_root).as_posix(),
            review_path.relative_to(project_root).as_posix(),
            decision_path.relative_to(project_root).as_posix(),
        ],
        "idea_id": idea_id,
        "title": proposal.get("title", ""),
        "reason": str(decision.get("reason") or "Selected for method design based on idea-review-board output."),
    }
    repo_choice = {
        **yaml_default(f"{args.program_id}-repo-choice", "method-designer", status=design_status, confidence=0.68),
        "inputs": [
            proposal_path.relative_to(project_root).as_posix(),
            repo_index_file.relative_to(project_root).as_posix(),
            *([selected_repo_summary_path] if selected_repo_summary_path else []),
            *([f"repo:{selected_repo.get('id', '')}"] if selected_repo.get("id") else []),
        ],
        "selected_repo": selected_repo.get("id", ""),
        "selected_repo_summary": selected_repo.get("short_summary", ""),
        "selected_repo_roles": selected_repo_roles,
        "integration_mode": integration_mode,
        "supporting_repos": supporting_repos,
        "coordination_contracts": contracts,
        "alternatives": alternatives,
        "candidate_repos": candidate_repos,
        "selection_reason": (
            f"Chose `{selected_repo.get('id')}` because {', '.join(selected_repo_breakdown.get('reasons', [])[:3]) or 'it had the strongest overall fit'}."
            if selected_repo
            else "No repo available yet."
        ),
        "edit_surfaces": selected_repo.get("entrypoints", [])[:3],
        "risks": [
            "Repository coverage may still be shallow; verify the main training or evaluation path manually.",
            "A quick baseline run should happen before deeper modifications.",
        ],
    }
    interfaces = {
        **yaml_default(f"{args.program_id}-interfaces", "method-designer", status="draft", confidence=0.62),
        "inputs": [
            proposal_path.relative_to(project_root).as_posix(),
            review_path.relative_to(project_root).as_posix(),
            repo_index_file.relative_to(project_root).as_posix(),
            *([selected_repo_summary_path] if selected_repo_summary_path else []),
        ],
        "integration_mode": integration_mode,
        "new_modules": ([f"{idea_id}-adapter"] if integration_mode == "single-repo" else [f"{idea_id}-adapter", "policy-control-bridge"]),
        "modified_modules": repo_choice["edit_surfaces"] + [path for item in supporting_repos for path in item.get("entrypoints", [])[:2]],
        "config_keys": ["experiment.variant", "model.adapter", "eval.slice"],
        "metrics": ["success_rate", "recovery_rate", "compute_cost"],
        "artifacts": ["checkpoints/", "tables/", "failure-cases/"],
        "interface_contracts": contracts,
    }
    coordination = {
        **yaml_default(f"{args.program_id}-coordination-contracts", "method-designer", status="draft", confidence=0.61),
        "inputs": [
            proposal_path.relative_to(project_root).as_posix(),
            review_path.relative_to(project_root).as_posix(),
            decision_path.relative_to(project_root).as_posix(),
            repo_index_file.relative_to(project_root).as_posix(),
            *([selected_repo_summary_path] if selected_repo_summary_path else []),
        ],
        "integration_mode": integration_mode,
        "host_repo": selected_repo.get("id", ""),
        "host_repo_roles": selected_repo_roles,
        "supporting_repos": supporting_repos,
        "contracts": contracts,
    }
    matrix = {
        **yaml_default(f"{args.program_id}-matrix", "method-designer", status="draft", confidence=0.62),
        "inputs": [
            proposal_path.relative_to(project_root).as_posix(),
            review_path.relative_to(project_root).as_posix(),
            repo_index_file.relative_to(project_root).as_posix(),
            *([selected_repo_summary_path] if selected_repo_summary_path else []),
        ],
        "baseline": (
            ["Run the selected repo's closest unmodified baseline."]
            if integration_mode == "single-repo"
            else [
                f"Run the host repo `{selected_repo.get('id', 'pending-repo')}` without cross-repo coordination.",
                *[
                    f"Run collaborator repo `{item.get('repo_id', '')}` in its nearest baseline mode."
                    for item in supporting_repos
                ],
            ]
        ),
        "main_experiment": (
            [f"Implement `{proposal.get('title', idea_id)}` on top of `{selected_repo.get('id', 'pending-repo')}`."]
            if integration_mode == "single-repo"
            else [
                (
                    f"Implement `{proposal.get('title', idea_id)}` with `{selected_repo.get('id', 'pending-repo')}` as the host repo "
                    f"and {', '.join(item.get('repo_id', '') for item in supporting_repos)} as collaborating stack(s)."
                )
            ]
        ),
        "ablations": [
            "Remove the proposed new module and keep the evaluation protocol fixed.",
            "Hold data and compute fixed while varying only the mechanism under test.",
            *(
                ["Freeze the collaborator stack and only change the host-repo bridge.", "Keep the bridge fixed and swap the collaborator control path back to baseline."]
                if integration_mode == "dual-repo"
                else []
            ),
        ],
        "success_criteria": [
            "Improvement on the target slice without unacceptable runtime regression.",
            "Effect survives at least one kill-test from idea-review-board.",
        ],
        "stop_conditions": [
            "No measurable gain after the minimal implementation path.",
            "Complexity explodes before baseline parity is reached.",
        ],
    }
    system_design = (
        f"# System Design: {proposal.get('title', idea_id)}\n\n"
        "## Goal\n\n"
        f"- Program: `{args.program_id}`\n"
        f"- Idea: `{idea_id}`\n"
        f"- Repo: `{selected_repo.get('id', 'pending')}`\n\n"
        "## Architecture\n\n"
        f"- Core hypothesis: {proposal.get('core_hypothesis', '')}\n"
        f"- Repo summary: {selected_repo.get('short_summary', 'No repo summary available yet.')}\n"
        f"- Repo choice rationale: {', '.join(selected_repo_breakdown.get('reasons', [])[:3]) or 'manual review required'}\n"
        f"- Integration mode: `{integration_mode}`\n"
        + (
            (
                "- Introduce one narrow module change first.\n"
                "- Keep the surrounding training and evaluation protocol stable.\n"
            )
            if integration_mode == "single-repo"
            else (
                f"- Host repo roles: {', '.join(selected_repo_roles) or 'general-stack'}\n"
                + "".join(
                    f"- Supporting repo `{item.get('repo_id', '')}` roles: {', '.join(item.get('role_hints', [])) or 'general-stack'}\n"
                    for item in supporting_repos
                )
                + "".join(
                    f"- Contract `{item.get('contract_id', '')}`: `{item.get('producer_repo', '')}` -> `{item.get('consumer_repo', '')}` using {item.get('payload', '')}; feedback via {item.get('feedback', '')}.\n"
                    for item in contracts
                )
            )
        )
        + "\n## Integration Focus\n\n"
        + (
            "- Keep the main training/evaluation path in one repo and add the smallest possible extension point.\n"
            if integration_mode == "single-repo"
            else "- Preserve a clear seam between the high-level policy stack and the low-level control stack, so each repo can still be validated independently.\n"
        )
        + "\n## Risks\n\n"
        + f"- {review.get('failure_modes', {}).get('Observed', ['Need manual risk review.'])[0] if isinstance(review, dict) else 'Need manual risk review.'}\n"
    )
    runbook = (
        f"# Runbook: {idea_id}\n\n"
        "1. Verify the chosen repo baseline still runs unchanged.\n"
        + (
            "2. Implement the smallest adapter or evaluation slice needed for the idea.\n"
            if integration_mode == "single-repo"
            else "2. Validate the host repo and each supporting repo independently before wiring the coordination bridge.\n"
        )
        + "3. Run the baseline, main experiment, then ablations from matrix.yaml.\n"
        + "4. Stop early if a listed stop condition triggers.\n"
    )

    write_yaml_if_changed(program_root / "design" / "selected-idea.yaml", selected_payload)
    write_yaml_if_changed(program_root / "design" / "repo-choice.yaml", repo_choice)
    write_yaml_if_changed(program_root / "design" / "interfaces.yaml", interfaces)
    write_yaml_if_changed(program_root / "design" / "coordination-contracts.yaml", coordination)
    write_yaml_if_changed(program_root / "experiments" / "matrix.yaml", matrix)
    write_text_if_changed(program_root / "design" / "system-design.md", system_design)
    write_text_if_changed(program_root / "experiments" / "runbook.md", runbook)

    state_path = program_root / "workflow" / "state.yaml"
    state = load_yaml(state_path, default={})
    if isinstance(state, dict):
        state["generated_at"] = utc_now_iso()
        state["inputs"] = [
            proposal_path.relative_to(project_root).as_posix(),
            review_path.relative_to(project_root).as_posix(),
            decision_path.relative_to(project_root).as_posix(),
        ]
        state["stage"] = "implementation-planning"
        state["active_idea_id"] = idea_id
        state["selected_idea_id"] = idea_id
        state["selected_repo_id"] = selected_repo.get("id", "")
        write_yaml_if_changed(state_path, state)

    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "method-designer",
            "event_type": "design-pack-generated",
            "title": "Design pack refreshed",
            "summary": (
                f"Generated a design pack for {idea_id} using host repo {selected_repo.get('id', 'pending-repo')}; "
                f"defined {len(interfaces.get('new_modules', []))} new modules and {len(interfaces.get('metrics', []))} tracked metrics."
            ),
            "artifacts": [
                (program_root / "design" / "selected-idea.yaml").relative_to(project_root).as_posix(),
                (program_root / "design" / "repo-choice.yaml").relative_to(project_root).as_posix(),
                (program_root / "design" / "interfaces.yaml").relative_to(project_root).as_posix(),
                (program_root / "design" / "coordination-contracts.yaml").relative_to(project_root).as_posix(),
                (program_root / "design" / "system-design.md").relative_to(project_root).as_posix(),
                (program_root / "experiments" / "matrix.yaml").relative_to(project_root).as_posix(),
                (program_root / "experiments" / "runbook.md").relative_to(project_root).as_posix(),
            ],
            "idea_ids": [idea_id],
            "repo_ids": [
                str(selected_repo.get("id") or "").strip(),
                *[
                    str(item.get("repo_id") or "").strip()
                    for item in supporting_repos
                    if isinstance(item, dict) and str(item.get("repo_id") or "").strip()
                ],
            ],
            "stage": "implementation-planning",
        },
        generated_by="method-designer",
    )

    print(f"[ok] generated design pack for {idea_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

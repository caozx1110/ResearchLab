#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, append_program_reporting_event, load_yaml, normalize_list, print_resolved_project_roots, program_reporting_events_path, utc_now_iso, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.confirm import apply_confirmation
from research.core import iter_records, locate_record, project_root, rel
from research.evidence import JUDGEMENT_CLAIM_TYPES, build_verification_receipt, validate_claims
from research.journal import mutation_transaction


DEFAULT_EXPERIMENT_SCALE = {
    "baseline": {"seed_count": 3, "model_size_tier": "repo-default", "parallelism": 1, "required_gpus": 1},
    "main": {"seed_count": 3, "model_size_tier": "repo-default", "parallelism": 1, "required_gpus": 1},
    "ablation": {"seed_count": 1, "model_size_tier": "repo-default", "parallelism": 1, "required_gpus": 1},
    "diagnostic": {"seed_count": 1, "model_size_tier": "repo-default", "parallelism": 1, "required_gpus": 1},
}

REQUIRED_METHOD_CLAIMS = {
    "method-repo-selection": "repo selection",
    "method-interfaces": "interfaces",
    "method-baselines": "baselines",
    "method-risks": "risks",
}


def profile_resources(root: Path) -> dict[str, Any]:
    profile = load_yaml(root / "kb" / "config" / "user-profile.yaml", default={})
    if not isinstance(profile, dict):
        return {}
    resources = profile.get("resources", {})
    return resources if isinstance(resources, dict) else {}


def _resource_text(resources: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in resources.items():
        parts.append(str(key))
        if isinstance(value, dict):
            parts.extend(f"{nested_key} {nested_value}" for nested_key, nested_value in value.items())
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def resource_capacity(resources: dict[str, Any]) -> dict[str, Any]:
    if not resources:
        return {"declared": False, "gpu_count": None, "gpu_memory_gb": None, "source": "default"}
    text = _resource_text(resources)
    gpu_count: int | None = None
    gpu_memory_gb: int | None = None
    for key in ("gpu_count", "gpus", "num_gpus"):
        value = resources.get(key)
        if isinstance(value, int):
            gpu_count = max(0, value)
            break
        if isinstance(value, str) and value.strip().isdigit():
            gpu_count = max(0, int(value.strip()))
            break
    if gpu_count is None:
        count_patterns = [
            r"\b(\d+)\s*[x×]\s*(?:nvidia\s+|amd\s+)?(?:a\d{2,3}|h\d{2,3}|v\d{2,3}|l\d{1,2}|rtx\s*\d{4}|gpu)s?\b",
            r"\b(\d+)\s*(?:gpu|gpus)\b",
        ]
        for pattern in count_patterns:
            match = re.search(pattern, text)
            if match:
                gpu_count = int(match.group(1))
                break
    if gpu_count is None and re.search(r"\b(?:cpu[- ]?only|no gpus?|without gpus?)\b", text):
        gpu_count = 0
    memory_match = re.search(r"\b(\d+)\s*gb\b", text)
    if memory_match:
        gpu_memory_gb = int(memory_match.group(1))
    return {
        "declared": True,
        "gpu_count": gpu_count,
        "gpu_memory_gb": gpu_memory_gb,
        "source": "profile.resources",
    }


def experiment_scale(resources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    capacity = resource_capacity(resources)
    gpu_count = capacity.get("gpu_count")
    if gpu_count is None:
        return {kind: dict(scale) for kind, scale in DEFAULT_EXPERIMENT_SCALE.items()}
    if gpu_count <= 1:
        seed_counts = {"baseline": 1, "main": 1, "ablation": 1, "diagnostic": 1}
        model_size_tier = "small"
        parallelism = 1
    elif gpu_count <= 3:
        seed_counts = {"baseline": 2, "main": 3, "ablation": 2, "diagnostic": 2}
        model_size_tier = "medium"
        parallelism = min(2, gpu_count)
    else:
        seed_counts = {"baseline": 3, "main": 5, "ablation": 3, "diagnostic": 5}
        model_size_tier = "large" if gpu_count >= 8 or (capacity.get("gpu_memory_gb") or 0) >= 40 else "medium"
        parallelism = min(4, gpu_count)
    required_gpus = {"baseline": 1, "main": 1, "ablation": 1, "diagnostic": 2}
    return {
        kind: {
            "seed_count": seed_counts[kind],
            "model_size_tier": model_size_tier,
            "parallelism": parallelism,
            "required_gpus": required_gpus[kind],
        }
        for kind in DEFAULT_EXPERIMENT_SCALE
    }


def apply_resource_feasibility(experiment: dict[str, Any], resources: dict[str, Any], scale: dict[str, Any]) -> dict[str, Any]:
    capacity = resource_capacity(resources)
    gpu_count = capacity.get("gpu_count")
    required_gpus = int(scale.get("required_gpus") or 0)
    experiment["scale"] = scale
    experiment["feasibility"] = "unknown" if gpu_count is None else "feasible"
    experiment["feasibility_reason"] = "No parseable GPU count was declared; verify capacity before launch." if gpu_count is None else "Fits declared GPU capacity."
    experiment["resource_request"] = ""
    if gpu_count is not None and required_gpus > gpu_count:
        deficit = required_gpus - gpu_count
        experiment["feasibility"] = "unrealistic"
        experiment["status_color"] = "red"
        experiment["feasibility_reason"] = f"Requires {required_gpus} GPUs but profile declares {gpu_count}."
        if deficit <= 4:
            experiment["resource_request"] = (
                f"This row needs {required_gpus} GPUs ({deficit} more than declared); worth requesting for the targeted diagnostic run."
            )
    else:
        experiment["status_color"] = "green" if gpu_count is not None else "gray"
    return experiment


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in str(text or "").replace("/", " ").replace("-", " ").split() if token.strip()}


def parse_name_detail(values: list[str], default_name: str) -> list[dict[str, str]]:
    items = []
    for index, raw in enumerate(values or [], start=1):
        text = str(raw).strip()
        if not text:
            continue
        if "=" in text:
            name, detail = text.split("=", 1)
        elif ":" in text:
            name, detail = text.split(":", 1)
        else:
            name, detail = f"{default_name}-{index}", text
        items.append({"name": name.strip() or f"{default_name}-{index}", "detail": detail.strip()})
    return items


def repo_candidates(
    root: Path,
    record: dict[str, Any],
    pinned_repo_ids: list[str],
    active_unit_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_repo_records = iter_records(root, kind="repo")
    repo_by_id = {str(repo.get("id") or ""): repo for repo in all_repo_records}
    active_repo_ids = [unit_id for unit_id in active_unit_ids if unit_id in repo_by_id]
    if active_repo_ids:
        repo_records = [repo_by_id[repo_id] for repo_id in active_repo_ids]
        corpus = {
            "scope": "program-active-units",
            "repo_ids": active_repo_ids,
            "fallback_used": False,
            "note": "Candidate ranking uses repository units attached to the program.",
        }
    else:
        repo_records = all_repo_records
        corpus = {
            "scope": "kb-wide-fallback",
            "repo_ids": [str(repo.get("id") or "") for repo in all_repo_records],
            "fallback_used": True,
            "note": "No repository units are attached to the program; candidate ranking fell back to KB-wide repository units.",
        }
    pinned_rank = {repo_id: index for index, repo_id in enumerate(pinned_repo_ids)}

    hypothesis = record.get("payload", {}).get("hypothesis", {})
    analysis = record.get("payload", {}).get("analysis", {})
    query_tokens = tokenize(
        " ".join(
            [
                str(record.get("title") or ""),
                str(hypothesis.get("core_hypothesis") or ""),
                str(hypothesis.get("key_mechanism") or ""),
                str(analysis.get("minimum_validation_path") or ""),
                " ".join(str(item) for item in analysis.get("related_work", [])),
                " ".join(str(item) for item in record.get("tags", [])),
                " ".join(str(item) for item in record.get("topics", [])),
            ]
        )
    )

    scored = []
    seen_ids: set[str] = set()
    for repo in repo_records:
        repo_id = str(repo.get("id") or "")
        seen_ids.add(repo_id)
        repo_text = " ".join(
            [
                repo_id,
                str(repo.get("title") or ""),
                str(repo.get("summary") or ""),
                " ".join(str(item) for item in repo.get("tags", [])),
                " ".join(str(item) for item in repo.get("topics", [])),
                " ".join(str(item) for item in repo.get("payload", {}).get("capability", {}).get("supported_tasks", [])),
                " ".join(str(item) for item in repo.get("payload", {}).get("structure", {}).get("entrypoints", [])),
            ]
        )
        overlap = sorted(query_tokens & tokenize(repo_text))
        score = len(overlap) + (6 if repo_id in pinned_repo_ids else 0)
        if pinned_repo_ids and repo_id not in pinned_repo_ids:
            score -= 1
        scored.append(
            {
                "id": repo_id,
                "title": str(repo.get("title") or ""),
                "summary": str(repo.get("summary") or ""),
                "tags": normalize_list(repo.get("tags", [])),
                "topics": normalize_list(repo.get("topics", [])),
                "entrypoints": normalize_list(repo.get("payload", {}).get("structure", {}).get("entrypoints", [])),
                "overlap": overlap,
                "score": score,
            }
        )
    for pinned_id in pinned_repo_ids:
        if pinned_id in seen_ids:
            continue
        scored.append(
            {
                "id": pinned_id,
                "title": "",
                "summary": "",
                "tags": [],
                "topics": [],
                "entrypoints": [],
                "overlap": [],
                "score": 6,
            }
        )
    if pinned_repo_ids:
        scored.sort(key=lambda item: (pinned_rank.get(str(item.get("id") or ""), len(pinned_rank)), -item["score"], item["id"]))
    else:
        scored.sort(key=lambda item: (-item["score"], item["id"]))
    return scored[:5], corpus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Design a method from a selected idea.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    design = subparsers.add_parser("design")
    design.add_argument("--phase", choices=("prepare", "verify"), default="prepare")
    design.add_argument("--idea-id", required=True)
    design.add_argument("--program-id", required=True)
    design.add_argument("--repo-id", action="append", default=[])
    design.add_argument("--interface", action="append", default=[])
    design.add_argument("--baseline", action="append", default=[])
    design.add_argument("--metric", action="append", default=[])
    design.add_argument("--risk", action="append", default=[])
    for command in ("confirm-selection", "confirm"):
        confirm = subparsers.add_parser(command)
        confirm.add_argument("--idea-id", required=True)
        confirm.add_argument("--program-id", required=True)
        confirm.add_argument("--confirmed-by", default="")
        confirm.add_argument("--evidence", action="append", default=[])
        confirm.add_argument("--user-authorization", default="")
        confirm.add_argument("--authorization-source", default="")
    return parser


def method_paths(root: Path, program_id: str, idea_id: str) -> dict[str, Path]:
    design_root = root / "kb" / "programs" / program_id / "design"
    return {
        "design_root": design_root,
        "method": design_root / f"{idea_id}-method.md",
        "choice": design_root / f"{idea_id}-repo-choice.yaml",
        "interfaces": design_root / f"{idea_id}-interfaces.yaml",
        "matrix": design_root / f"{idea_id}-experiment-matrix.yaml",
        "state": root / "kb" / "programs" / program_id / "state.yaml",
        "events": program_reporting_events_path(root, program_id),
    }


def selection_subject_id(program_id: str, idea_id: str) -> str:
    return f"method-selection:{program_id}:{idea_id}"


def default_program_state(program_id: str) -> dict[str, Any]:
    return {
        **yaml_default(f"{program_id}-state", "method-designer", status="active"),
        "program_id": program_id,
        "question": "",
        "goal": "",
        "stage": "idea-review",
        "active_unit_ids": [],
        "blockers": [],
        "next_actions": [],
        "resource_constraints": [],
    }


def load_program_state(path: Path, program_id: str) -> dict[str, Any]:
    state = load_yaml(path, default={})
    return state if isinstance(state, dict) and state else default_program_state(program_id)


def load_method_artifact(path: Path, *, label: str) -> dict[str, Any]:
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict) or not payload:
        raise SystemExit(f"Method {label} is missing; prepare the method proposal first.")
    return payload


def require_current_method_subject(choice: dict[str, Any], program_id: str, idea_id: str) -> None:
    expected_id = selection_subject_id(program_id, idea_id)
    if str(choice.get("kind") or "") != "method_selection" or str(choice.get("id") or "") != expected_id:
        if choice.get("selected_repo_id") or choice.get("selection_judgement"):
            raise SystemExit(
                "This method artifact predates the proposal/selection lifecycle and needs explicit migration; "
                "it will not be promoted automatically."
            )
        raise SystemExit("Method selection artifact has an unsupported or mismatched subject identity.")
    if str(choice.get("program_id") or "") != program_id or str(choice.get("idea_id") or "") != idea_id:
        raise SystemExit("Method selection artifact does not match the requested program and idea.")


def method_source_roots(
    root: Path,
    program_id: str,
    claims: list[dict[str, Any]],
) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    program_source_id = f"program:{program_id}"
    for claim in claims:
        for evidence_ref in claim.get("evidence_refs") or []:
            if not isinstance(evidence_ref, dict):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            if not source_unit_id or source_unit_id in roots:
                continue
            if source_unit_id == program_source_id:
                roots[source_unit_id] = root / "kb" / "programs" / program_id
                continue
            _record, source_path = locate_record(root, source_unit_id, fuzzy=False)
            roots[source_unit_id] = source_path.parent
    return roots


def validate_method_claims(choice: dict[str, Any], proposed_repo_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    payload = choice.get("payload")
    claims_value = payload.get("claims") if isinstance(payload, dict) else None
    claims = [dict(claim) for claim in claims_value if isinstance(claim, dict)] if isinstance(claims_value, list) else []
    violations = validate_claims(claims_value)
    claim_by_id: dict[str, dict[str, Any]] = {}
    for claim in claims:
        claim_id = str(claim.get("id") or "").strip()
        if claim_id in claim_by_id:
            violations.append(f"duplicate canonical claim id {claim_id!r}")
        elif claim_id:
            claim_by_id[claim_id] = claim
    for claim_id, label in REQUIRED_METHOD_CLAIMS.items():
        claim = claim_by_id.get(claim_id)
        if claim is None:
            violations.append(f"missing required {label} claim {claim_id!r}")
            continue
        if str(claim.get("claim_type") or "") not in JUDGEMENT_CLAIM_TYPES:
            violations.append(f"{claim_id}: method judgement must use an inference/evaluation/user_opinion claim type")
        if str(claim.get("confirmation_status") or "") != "pending_user_confirmation":
            violations.append(f"{claim_id}: claim must remain pending_user_confirmation until human confirmation")
    selection_claim = claim_by_id.get("method-repo-selection", {})
    if proposed_repo_id and proposed_repo_id.casefold() not in str(selection_claim.get("text") or "").casefold():
        violations.append("method-repo-selection must name the exact proposed_repo_id")
    selection_sources = {
        str(ref.get("source_unit_id") or "").strip()
        for ref in selection_claim.get("evidence_refs") or []
        if isinstance(ref, dict)
    }
    if proposed_repo_id and proposed_repo_id not in selection_sources:
        violations.append("method-repo-selection must cite evidence from the proposed repository unit")
    return claims, violations


def prepare_method(root: Path, record: dict[str, Any], args: argparse.Namespace) -> int:
    paths = method_paths(root, args.program_id, args.idea_id)
    if paths["choice"].exists():
        existing = load_method_artifact(paths["choice"], label="selection artifact")
        require_current_method_subject(existing, args.program_id, args.idea_id)
        raise SystemExit("A method proposal already exists; preserve it and continue with evidence verification.")
    state = load_program_state(paths["state"], args.program_id)
    existing_idea_id = str(state.get("selected_idea_id") or "").strip()
    if existing_idea_id and existing_idea_id != args.idea_id:
        raise SystemExit("The program already points to a different selected idea.")
    if str(state.get("selected_repo_id") or "").strip():
        raise SystemExit("The program already has a selected repository; a proposal cannot replace it implicitly.")

    repo_rankings, repo_corpus = repo_candidates(
        root,
        record,
        normalize_list(args.repo_id),
        normalize_list(state.get("active_unit_ids", [])),
    )
    proposed_repo = repo_rankings[0] if repo_rankings else {
        "id": normalize_list(args.repo_id)[0] if normalize_list(args.repo_id) else "",
        "title": "",
        "summary": "",
        "entrypoints": [],
        "score": 0,
        "overlap": [],
        "tags": [],
        "topics": [],
    }
    proposed_repo_id = str(proposed_repo.get("id") or "").strip()
    candidate_repos = repo_rankings if repo_rankings else ([proposed_repo] if proposed_repo_id else [])
    interfaces = parse_name_detail(args.interface, "interface")
    if not interfaces:
        interfaces = [
            {"name": "interface-1", "detail": "", "status": "pending_agent_fill"},
            {"name": "interface-2", "detail": "", "status": "pending_agent_fill"},
        ]
    else:
        interfaces = [{**item, "status": "provided_pending_verification"} for item in interfaces]
    baselines = normalize_list(args.baseline) or ["closest-unmodified-repo-baseline", "current-best-manual-baseline"]
    metrics = normalize_list(args.metric) or ["success_rate", "recovery_rate", "runtime_cost"]
    risks = normalize_list(args.risk) or normalize_list(record.get("payload", {}).get("analysis", {}).get("risks", []))
    problem = record.get("payload", {}).get("problem", {})
    hypothesis = record.get("payload", {}).get("hypothesis", {})
    analysis = record.get("payload", {}).get("analysis", {})
    resources = profile_resources(root)
    scale_by_kind = experiment_scale(resources)

    def proposal_row(row: dict[str, Any], kind: str) -> dict[str, Any]:
        row["repo_candidate_dependency"] = proposed_repo_id
        row["dependency_status"] = "proposal_pending_confirmation"
        row["status"] = "proposal"
        return apply_resource_feasibility(row, resources, scale_by_kind[kind])

    experiments = [
        proposal_row(
            {
                "name": "baseline-parity",
                "goal": "Check whether the proposed repository baseline can be reproduced.",
                "kind": "baseline",
                "interface_under_test": [],
                "metrics": metrics,
                "evidence_to_collect": ["baseline metrics", "runtime cost", "failure cases"],
                "decision_gate": "Runtime agent must supply a grounded baseline judgement before selection.",
            },
            "baseline",
        ),
        proposal_row(
            {
                "name": "minimal-idea-variant",
                "goal": "Test the smallest agent-specified interface change after repository selection.",
                "kind": "main",
                "interface_under_test": [item["name"] for item in interfaces[:2]],
                "metrics": metrics,
                "evidence_to_collect": ["delta vs baseline", "qualitative failures", "ablation-ready checkpoints"],
                "decision_gate": "Runtime agent must define the comparison and stop condition.",
            },
            "main",
        ),
        proposal_row(
            {
                "name": "interface-ablation",
                "goal": "Prepare one ablation row per agent-verified interface seam.",
                "kind": "ablation",
                "interface_under_test": [item["name"] for item in interfaces],
                "metrics": metrics,
                "evidence_to_collect": ["ablation table", "regression cases"],
                "decision_gate": "Runtime agent must justify which seams are methodologically relevant.",
            },
            "ablation",
        ),
        proposal_row(
            {
                "name": "stress-and-failure-slice",
                "goal": "Prepare a diagnostic row for an agent-identified risk slice.",
                "kind": "diagnostic",
                "interface_under_test": [item["name"] for item in interfaces[:1]],
                "metrics": metrics,
                "evidence_to_collect": ["failure taxonomy", "resource bottlenecks", "follow-up requests"],
                "decision_gate": "Runtime agent must ground the selected risk and diagnostic slice.",
            },
            "diagnostic",
        ),
    ]
    resource_requests = [item["resource_request"] for item in experiments if item.get("resource_request")]
    now = utc_now_iso()
    subject_id = selection_subject_id(args.program_id, args.idea_id)
    choice = {
        "id": subject_id,
        "kind": "method_selection",
        "owner": "method-designer",
        "generated_by": "method-designer",
        "updated_at": now,
        "priority": "high",
        "idea_id": args.idea_id,
        "program_id": args.program_id,
        "proposed_repo_id": proposed_repo_id,
        "status": "needs_agent_fill",
        "selection_status": "needs_agent_fill",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": False,
        "information_types": ["fact", "inference", "evaluation", "unverified"],
        "payload": {
            "method_selection": {
                "proposed_repo_id": proposed_repo_id,
                "selection_reason": "",
                "required_claim_ids": list(REQUIRED_METHOD_CLAIMS),
                "agent_fill_status": "pending",
            },
            "claims": [],
        },
        "ranking_basis": {
            "type": "deterministic-token-overlap",
            "leading_candidate_id": proposed_repo_id,
            "leading_candidate_score": proposed_repo.get("score", 0),
            "signals": proposed_repo.get("overlap", []),
        },
        "candidate_repos": [
            {
                "repo_id": item.get("id", ""),
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "score": item.get("score", 0),
                "entrypoints": item.get("entrypoints", []),
                "overlap": item.get("overlap", []),
            }
            for item in candidate_repos
        ],
        "repo_choice_policy": {
            "prefer_user_pinned_repo": bool(normalize_list(args.repo_id)),
            "prefer_program_active_unit_ids": True,
            "prefer_existing_repo_units": True,
            "fallback": "manual-selection-required",
        },
        "candidate_corpus": repo_corpus,
        "review_route": {
            "owner": "method-designer",
            "action": "confirm-selection",
            "program_id": args.program_id,
            "idea_id": args.idea_id,
            "subject_id": subject_id,
        },
    }
    interfaces_payload = {
        "idea_id": args.idea_id,
        "program_id": args.program_id,
        "proposed_repo_id": proposed_repo_id,
        "proposal_status": "pending_agent_evidence",
        "interfaces": interfaces,
        "config_keys": ["experiment.variant", "adapter.mode", "eval.slice"],
        "metrics": metrics,
        "artifacts": ["logs/", "checkpoints/", "tables/", "failure-cases/"],
        "candidate_edit_surfaces": normalize_list(proposed_repo.get("entrypoints", []))[:5],
        "judgement_claim_id": "method-interfaces",
        "information_types": ["fact", "inference", "unverified"],
        "confirmation_status": "pending_user_confirmation",
    }
    matrix_payload = {
        "idea_id": args.idea_id,
        "program_id": args.program_id,
        "proposed_repo_id": proposed_repo_id,
        "proposal_status": "pending_agent_evidence",
        "resource_profile": resource_capacity(resources),
        "resource_requests": resource_requests,
        "experiments": experiments,
        "baselines": baselines,
        "baseline_judgement_claim_id": "method-baselines",
        "risks": risks,
        "risk_judgement_claim_id": "method-risks",
        "information_types": ["fact", "inference", "evaluation", "unverified"],
        "confirmation_status": "pending_user_confirmation",
    }
    state["selected_idea_id"] = args.idea_id
    state["method_proposal"] = {
        "subject_id": subject_id,
        "proposed_repo_id": proposed_repo_id,
        "status": "needs_agent_fill",
    }
    if resources:
        state["resource_constraints"] = resources

    # The directory itself is a target so an aborted first prepare cannot leak an
    # empty design directory after its child files are restored as absent.
    with mutation_transaction(root, "method:prepare", [paths["design_root"], paths["state"]]):
        write_text_if_changed(
            paths["method"],
            (
                f"# Method Proposal: {record.get('title', '')}\n\n"
                "## Problem\n\n"
                f"{problem.get('problem_definition', '')}\n\n"
                "## Core Hypothesis\n\n"
                f"{hypothesis.get('core_hypothesis', '')}\n\n"
                "## Repository Proposal\n\n"
                f"- Deterministic leading candidate: `{proposed_repo_id or 'pending'}`\n"
                f"- Candidate corpus: {repo_corpus['note']}\n"
                f"- Ranking signals: {', '.join(proposed_repo.get('overlap', [])) or 'none'}\n"
                "- Status: proposal only; runtime-agent evidence and human confirmation are still required.\n\n"
                "## Agent Fill Slots\n\n"
                "- Repository selection judgement: pending\n"
                "- Interface judgement: pending\n"
                "- Baseline judgement: pending\n"
                "- Risk judgement: pending\n\n"
                "## Structural Inputs\n\n"
                f"- Minimum validation path from the selected idea: {analysis.get('minimum_validation_path', '') or 'pending'}\n"
                + "".join(f"- Interface slot `{item['name']}`: {item.get('detail') or 'pending runtime-agent fill'}\n" for item in interfaces)
                + "".join(f"- Candidate baseline: {item}\n" for item in baselines)
                + "".join(f"- Metric slot: {item}\n" for item in metrics)
                + "".join(f"- Candidate risk: {item}\n" for item in (risks or ["pending runtime-agent fill"]))
            ),
        )
        write_yaml_if_changed(paths["choice"], choice)
        write_yaml_if_changed(paths["interfaces"], interfaces_payload)
        write_yaml_if_changed(paths["matrix"], matrix_payload)
        write_yaml_if_changed(paths["state"], state)
    if repo_corpus["fallback_used"]:
        print(repo_corpus["note"])
    for request in resource_requests:
        print(f"Resource request: {request}")
    print("方法提案已准备；仓库、接口、基线和风险判断仍等待证据校验。")
    return 0


def verify_method(root: Path, args: argparse.Namespace) -> int:
    paths = method_paths(root, args.program_id, args.idea_id)
    targets = [paths["choice"], paths["interfaces"], paths["matrix"]]
    with mutation_transaction(root, "method:verify", targets):
        choice = load_method_artifact(paths["choice"], label="selection artifact")
        require_current_method_subject(choice, args.program_id, args.idea_id)
        if "selected_repo_id" in choice:
            raise SystemExit("Unconfirmed method artifacts must not contain selected_repo_id.")
        proposed_repo_id = str(choice.get("proposed_repo_id") or "").strip()
        if not proposed_repo_id:
            raise SystemExit("Method proposal has no proposed repository candidate.")
        _repo_record, _repo_path = locate_record(root, proposed_repo_id, kind="repo", fuzzy=False)
        candidate_ids = {
            str(item.get("repo_id") or "").strip()
            for item in choice.get("candidate_repos") or []
            if isinstance(item, dict)
        }
        if proposed_repo_id not in candidate_ids:
            raise SystemExit("The proposed repository is not present in the deterministic candidate set.")
        claims, violations = validate_method_claims(choice, proposed_repo_id)
        if violations:
            raise SystemExit("Method judgement verification failed:\n  - " + "\n  - ".join(violations))
        source_roots = method_source_roots(root, args.program_id, claims)
        build_verification_receipt(choice, paths["design_root"], source_roots=source_roots)
        choice["updated_at"] = utc_now_iso()
        choice["status"] = "ready_for_review"
        choice["selection_status"] = "ready_for_review"
        choice["needs_human_confirmation"] = True
        choice["payload"]["method_selection"]["agent_fill_status"] = "verified"
        interfaces = load_method_artifact(paths["interfaces"], label="interface artifact")
        matrix = load_method_artifact(paths["matrix"], label="experiment matrix")
        interfaces["proposal_status"] = "ready_for_review"
        matrix["proposal_status"] = "ready_for_review"
        write_yaml_if_changed(paths["choice"], choice)
        write_yaml_if_changed(paths["interfaces"], interfaces)
        write_yaml_if_changed(paths["matrix"], matrix)
    print("方法判断与逐字证据已通过校验，等待你的确认。")
    return 0


def confirm_method(root: Path, args: argparse.Namespace) -> int:
    paths = method_paths(root, args.program_id, args.idea_id)
    targets = [paths["method"], paths["choice"], paths["interfaces"], paths["matrix"], paths["state"], paths["events"]]
    with mutation_transaction(root, "method:confirm", targets):
        choice = load_method_artifact(paths["choice"], label="selection artifact")
        require_current_method_subject(choice, args.program_id, args.idea_id)
        if str(choice.get("status") or "") != "ready_for_review":
            raise SystemExit("Method selection is not ready for review; complete evidence verification first.")
        if "selected_repo_id" in choice:
            raise SystemExit("Method selection is already finalized or requires repair.")
        proposed_repo_id = str(choice.get("proposed_repo_id") or "").strip()
        claims, violations = validate_method_claims(choice, proposed_repo_id)
        if violations:
            raise SystemExit("Method judgement confirmation failed:\n  - " + "\n  - ".join(violations))
        source_roots = method_source_roots(root, args.program_id, claims)
        locate_record(root, proposed_repo_id, kind="repo", fuzzy=False)

        # Final selection fields are set before receipt creation, so the receipt
        # represents the exact state promoted by this transaction.
        choice["selected_repo_id"] = proposed_repo_id
        choice["selection_status"] = "confirmed"
        choice["status"] = "confirmed"
        choice["updated_at"] = utc_now_iso()
        choice["payload"]["method_selection"]["selected_repo_id"] = proposed_repo_id
        choice["payload"]["method_selection"]["agent_fill_status"] = "confirmed"
        apply_confirmation(
            choice,
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
            method="method-designer confirm-selection",
            project_root=root,
            verification_root=paths["design_root"],
            trusted_source_roots=source_roots,
        )

        interfaces = load_method_artifact(paths["interfaces"], label="interface artifact")
        matrix = load_method_artifact(paths["matrix"], label="experiment matrix")
        interfaces["selected_repo_id"] = proposed_repo_id
        interfaces["proposal_status"] = "confirmed"
        interfaces["confirmation_status"] = "confirmed"
        matrix["selected_repo_id"] = proposed_repo_id
        matrix["proposal_status"] = "confirmed"
        matrix["confirmation_status"] = "confirmed"
        for row in matrix.get("experiments") or []:
            if isinstance(row, dict):
                row["repo_dependency"] = proposed_repo_id
                row["dependency_status"] = "confirmed_selection"
                row["status"] = "planned"

        state = load_program_state(paths["state"], args.program_id)
        existing_repo_id = str(state.get("selected_repo_id") or "").strip()
        if existing_repo_id and existing_repo_id != proposed_repo_id:
            raise SystemExit("The program already selected a different repository; refusing to overwrite it.")
        state["selected_idea_id"] = args.idea_id
        state["selected_repo_id"] = proposed_repo_id
        method_proposal = state.get("method_proposal")
        if not isinstance(method_proposal, dict):
            method_proposal = {}
        method_proposal.update(
            {
                "subject_id": str(choice.get("id") or ""),
                "proposed_repo_id": proposed_repo_id,
                "selected_repo_id": proposed_repo_id,
                "status": "confirmed",
            }
        )
        state["method_proposal"] = method_proposal
        if str(state.get("stage") or "").strip() in {"", "init", "idea-review", "method-proposal", "method-review"}:
            state["stage"] = "implementation-planning"

        method_text = paths["method"].read_text(encoding="utf-8") if paths["method"].exists() else ""
        method_text = method_text.replace(
            f"- Deterministic leading candidate: `{proposed_repo_id}`",
            f"- Selected repository: `{proposed_repo_id}`",
        ).replace(
            "- Status: proposal only; runtime-agent evidence and human confirmation are still required.",
            "- Status: selected with a current human ConfirmationReceipt.",
        )
        receipt = choice.get("confirmation") if isinstance(choice.get("confirmation"), dict) else {}
        verification = choice.get("payload", {}).get("verification", {})
        subject_path = rel(root, paths["choice"])
        write_text_if_changed(paths["method"], method_text)
        write_yaml_if_changed(paths["choice"], choice)
        write_yaml_if_changed(paths["interfaces"], interfaces)
        write_yaml_if_changed(paths["matrix"], matrix)
        write_yaml_if_changed(paths["state"], state)
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "method-designer",
                "event_type": "method-selected",
                "title": f"Method repository selected for {args.idea_id}",
                "summary": f"The user confirmed repository {proposed_repo_id} for the method proposal.",
                "stage": str(state.get("stage") or "implementation-planning"),
                "idea_ids": [args.idea_id],
                "repo_ids": [proposed_repo_id],
                "artifacts": [subject_path, rel(root, paths["method"]), rel(root, paths["interfaces"]), rel(root, paths["matrix"]), rel(root, paths["state"])],
                "tags": ["method", "selection", "confirmed"],
                "epistemic_type": "judgement",
                "information_types": ["inference", "evaluation"],
                "confirmation_status": "confirmed",
                "confirmation_binding": {
                    "subject": {
                        "kind": str(choice.get("kind") or "method_selection"),
                        "id": str(choice.get("id") or ""),
                        "owner": "method-designer",
                        "path": subject_path,
                    },
                    "claim_ids": normalize_list(receipt.get("claim_ids", [])),
                    "content_digest": str(receipt.get("content_digest") or ""),
                    "verification": {
                        key: str(verification.get(key) or "")
                        for key in ("verified_at", "claims_digest", "evidence_digest")
                    },
                },
            },
            generated_by="method-designer",
        )
    print("方法选择已确认，实验规划阶段已经同步推进。下一步可运行 kb next。")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, _ = locate_record(root, args.idea_id, kind="idea")
    if record.get("kind") != "idea":
        raise SystemExit(f"{args.idea_id} is not an idea record")
    if record.get("status") != "selected":
        raise SystemExit(f"{args.idea_id} must be selected before method design")
    if args.command == "design" and args.phase == "prepare":
        return prepare_method(root, record, args)
    if args.command == "design" and args.phase == "verify":
        return verify_method(root, args)
    if args.command in {"confirm-selection", "confirm"}:
        return confirm_method(root, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

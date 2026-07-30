#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, append_program_reporting_event, load_yaml, normalize_list, program_reporting_events_path, utc_now_iso, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.confirm import apply_confirmation
from research.core import checkpoint_and_report, iter_records, locate_record, project_root, rel
from research.evidence import EvidenceSourceSnapshot, JUDGEMENT_CLAIM_TYPES, build_verification_receipt, validate_claims
from research.journal import mutation_transaction
from research.judgements import apply_judgement_rejection, readiness_violations, require_judgement_snapshot
from research.preference_selection import resolve_operation_preferences
from research.records import trusted_claim_source_roots


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


def profile_constraints(root: Path) -> list[str]:
    """Load only the canonical hard constraint field, never adjacent soft preferences."""
    profile = load_yaml(root / "kb" / "config" / "user-profile.yaml", default={})
    if not isinstance(profile, dict):
        return []
    constraints = profile.get("constraints", [])
    if not isinstance(constraints, list):
        return []
    return [str(value).strip() for value in constraints if str(value).strip()]


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
    selected_research_focus: str = "",
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
                selected_research_focus,
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
    design.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)
    for command in ("confirm-selection", "confirm"):
        confirm = subparsers.add_parser(command)
        confirm.add_argument("--idea-id", required=True)
        confirm.add_argument("--program-id", required=True)
        confirm.add_argument("--confirmed-by", default="")
        confirm.add_argument("--evidence", action="append", default=[])
        confirm.add_argument("--user-authorization", default="")
        confirm.add_argument("--authorization-source", default="")
        confirm.add_argument("--expected-snapshot", required=True)
    reject = subparsers.add_parser("reject-selection")
    reject.add_argument("--idea-id", required=True)
    reject.add_argument("--program-id", required=True)
    reject.add_argument("--reason", default="")
    reject.add_argument("--expected-snapshot", required=True)
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


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_method_values(values: object) -> list[str]:
    return [" ".join(item.split()) for item in normalize_list(values)]


def _repo_preference_corpus(root: Path, active_unit_ids: list[str]) -> dict[str, object]:
    """Describe the exact canonical repository corpus consumed by ranking."""
    all_repo_records = iter_records(root, kind="repo")
    repo_by_id = {str(repo.get("id") or ""): repo for repo in all_repo_records}
    active_repo_ids = [unit_id for unit_id in active_unit_ids if unit_id in repo_by_id]
    if active_repo_ids:
        scope = "program-active-units"
        repo_records = [repo_by_id[repo_id] for repo_id in active_repo_ids]
    else:
        scope = "kb-wide-fallback"
        repo_records = all_repo_records

    def consumed_repo_fields(repo: dict[str, Any]) -> dict[str, object]:
        payload = repo.get("payload") if isinstance(repo.get("payload"), dict) else {}
        capability = payload.get("capability") if isinstance(payload.get("capability"), dict) else {}
        structure = payload.get("structure") if isinstance(payload.get("structure"), dict) else {}
        return {
            "id": str(repo.get("id") or ""),
            "title": str(repo.get("title") or ""),
            "summary": str(repo.get("summary") or ""),
            "tags": normalize_list(repo.get("tags")),
            "topics": normalize_list(repo.get("topics")),
            "supported_tasks": normalize_list(capability.get("supported_tasks")),
            "entrypoints": normalize_list(structure.get("entrypoints")),
        }

    canonical_rows = sorted(
        (consumed_repo_fields(repo) for repo in repo_records),
        key=lambda item: str(item.get("id") or ""),
    )
    return {
        "scope": scope,
        "repo_ids": [str(item.get("id") or "") for item in canonical_rows],
        "corpus_digest": _canonical_digest(canonical_rows),
    }


def method_preference_task_inputs(
    root: Path,
    record: dict[str, Any],
    *,
    program_id: str,
    idea_id: str,
    state: dict[str, Any],
    repo_ids: object,
    interfaces: object,
    baselines: object,
    metrics: object,
    risks: object,
) -> dict[str, object]:
    """Build a value-free snapshot of every design input consumed by ranking."""
    canonical_idea = copy.deepcopy(record)
    # locate_record supplies the legacy-compatible default revision in memory;
    # absence and revision zero represent the same canonical record content.
    if canonical_idea.get("revision") in (None, 0):
        canonical_idea.pop("revision", None)
    active_unit_ids = _normalized_method_values(state.get("active_unit_ids", []))
    normalized_repo_ids = _normalized_method_values(repo_ids)
    normalized_interfaces = [
        {
            "name": " ".join(str(item.get("name") or "").split()),
            "detail": " ".join(str(item.get("detail") or "").split()),
        }
        for item in (interfaces if isinstance(interfaces, list) else [])
        if isinstance(item, dict)
    ]
    explicit_values = {
        "interfaces": normalized_interfaces,
        "baselines": _normalized_method_values(baselines),
        "metrics": _normalized_method_values(metrics),
        "risks": _normalized_method_values(risks),
    }
    return {
        "schema_version": 1,
        "program_id": str(program_id or ""),
        "idea_id": str(idea_id or ""),
        "idea_digest": _canonical_digest(canonical_idea),
        "explicit_repo_ids": normalized_repo_ids,
        "explicit_values_digest": _canonical_digest(explicit_values),
        "program_state_digest": _canonical_digest(
            {
                "program_id": str(state.get("program_id") or program_id or ""),
                "active_unit_ids": active_unit_ids,
            }
        ),
        "repo_corpus": _repo_preference_corpus(root, active_unit_ids),
    }


def method_preference_context(
    task_inputs: dict[str, object],
) -> dict[str, object]:
    return {
        "preference_task_inputs": task_inputs,
        "preference_task_inputs_digest": _canonical_digest(task_inputs),
    }


def resolve_method_preferences(
    root: Path,
    *,
    task_inputs: dict[str, object],
    selection_id: str,
) -> dict[str, object]:
    try:
        return resolve_operation_preferences(
            root,
            selection_id=selection_id,
            skill="method-designer",
            operation="design",
            canonical_inputs=method_preference_context(task_inputs),
        )
    except ValueError as exc:
        raise SystemExit(f"Method preference selection is invalid: {exc}") from exc


def method_preference_state(resolution: dict[str, object]) -> dict[str, object]:
    return {
        "task_context_digest": str(resolution.get("task_context_digest") or ""),
        "selection_binding": dict(resolution.get("binding") or {}),
        "hard_value_digests": dict(resolution.get("hard_value_digests") or {}),
    }


def require_current_method_preferences(
    root: Path,
    choice: dict[str, Any],
    *,
    program_id: str,
    idea_id: str,
) -> dict[str, object]:
    """Revalidate the prepare-time binding before verify or confirmation."""
    stored = choice.get("preference_context")
    if not isinstance(stored, dict):
        raise SystemExit("Method preference context is missing; prepare the method again.")
    binding = stored.get("selection_binding")
    binding = binding if isinstance(binding, dict) else {}
    stored_task_inputs = choice.get("preference_task_inputs")
    if not isinstance(stored_task_inputs, dict):
        raise SystemExit("Method preference task inputs are missing; prepare the method again.")
    paths = method_paths(root, program_id, idea_id)
    interfaces_payload = load_method_artifact(paths["interfaces"], label="interface artifact")
    matrix_payload = load_method_artifact(paths["matrix"], label="experiment matrix")
    idea_record, _idea_path = locate_record(root, idea_id, kind="idea", fuzzy=False)
    state = load_program_state(paths["state"], program_id)
    repo_policy = choice.get("repo_choice_policy")
    repo_policy = repo_policy if isinstance(repo_policy, dict) else {}
    input_sources = choice.get("preference_input_sources")
    if not isinstance(input_sources, dict):
        raise SystemExit("Method preference input sources are missing; prepare the method again.")
    current_task_inputs = method_preference_task_inputs(
        root,
        idea_record,
        program_id=program_id,
        idea_id=idea_id,
        state=state,
        repo_ids=repo_policy.get("pinned_repo_ids", []),
        interfaces=(
            interfaces_payload.get("interfaces", [])
            if input_sources.get("interfaces") == "explicit"
            else []
        ),
        baselines=(
            matrix_payload.get("baselines", [])
            if input_sources.get("baselines") == "explicit"
            else []
        ),
        metrics=(
            interfaces_payload.get("metrics", [])
            if input_sources.get("metrics") == "explicit"
            else []
        ),
        risks=(
            matrix_payload.get("risks", [])
            if input_sources.get("risks") == "explicit"
            else []
        ),
    )
    if current_task_inputs != stored_task_inputs:
        raise SystemExit("Method inputs changed after prepare; prepare the method again.")
    current = resolve_method_preferences(
        root,
        task_inputs=current_task_inputs,
        selection_id=str(binding.get("selection_id") or ""),
    )
    if method_preference_state(current) != stored:
        raise SystemExit("Method preferences changed after prepare; prepare the method again.")
    return stored


def selected_method_research_focus(resolution: dict[str, object]) -> str:
    values = resolution.get("values_by_path")
    values = values if isinstance(values, dict) else {}
    value = values.get("profile.personalization.research_focus")
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in sorted(value.items()))
    return str(value or "")


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
    payload = choice.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    selection = payload.get("method_selection")
    selection = selection if isinstance(selection, dict) else {}
    if str(choice.get("proposed_repo_id") or "").strip() != str(selection.get("proposed_repo_id") or "").strip():
        raise SystemExit("Method selection artifact has divergent operative and confirmable repository fields.")


def method_source_roots(
    root: Path,
    program_id: str,
    claims: list[dict[str, Any]],
) -> dict[str, Path | EvidenceSourceSnapshot]:
    expected_program_source = f"program:{program_id}"
    for claim in claims:
        for evidence_ref in claim.get("evidence_refs") or []:
            if not isinstance(evidence_ref, dict) or isinstance(evidence_ref.get("external_source"), dict):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            if source_unit_id.startswith("program:") and source_unit_id != expected_program_source:
                raise SystemExit("Method evidence must belong to the current program.")
    subject = {
        "id": f"method-selection:{program_id}",
        "kind": "method_selection",
        "program_id": program_id,
        "payload": {"claims": claims},
    }
    try:
        return trusted_claim_source_roots(
            root,
            subject,
            verification_root=root / "kb" / "programs" / program_id / "design",
        )
    except ValueError as exc:
        raise SystemExit(
            "Method evidence source is not a canonical safe unit or program."
        ) from exc


def require_proposed_repo_snapshot(
    source_roots: dict[str, Path | EvidenceSourceSnapshot],
    proposed_repo_id: str,
) -> None:
    proposed_repo = source_roots.get(proposed_repo_id)
    if not isinstance(proposed_repo, EvidenceSourceSnapshot) or proposed_repo.kind != "repo":
        raise SystemExit("The proposed repository is not a canonical evidence source.")


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
    state_before = load_yaml(paths["state"], default=None)
    state = load_program_state(paths["state"], args.program_id)
    existing_idea_id = str(state.get("selected_idea_id") or "").strip()
    if existing_idea_id and existing_idea_id != args.idea_id:
        raise SystemExit("The program already points to a different selected idea.")
    if str(state.get("selected_repo_id") or "").strip():
        raise SystemExit("The program already has a selected repository; a proposal cannot replace it implicitly.")

    explicit_interfaces = parse_name_detail(args.interface, "interface")
    interfaces = copy.deepcopy(explicit_interfaces)
    if not explicit_interfaces:
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
    constraints = profile_constraints(root)
    scale_by_kind = experiment_scale(resources)
    preference_task_inputs = method_preference_task_inputs(
        root,
        record,
        program_id=args.program_id,
        idea_id=args.idea_id,
        state=state,
        repo_ids=args.repo_id,
        interfaces=explicit_interfaces,
        baselines=args.baseline,
        metrics=args.metric,
        risks=args.risk,
    )
    preferences = resolve_method_preferences(
        root,
        task_inputs=preference_task_inputs,
        selection_id=str(getattr(args, "preference_selection_id", "") or ""),
    )
    preference_context = method_preference_state(preferences)
    selected_research_focus = selected_method_research_focus(preferences)

    repo_rankings, repo_corpus = repo_candidates(
        root,
        record,
        normalize_list(args.repo_id),
        normalize_list(state.get("active_unit_ids", [])),
        selected_research_focus,
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
            "pinned_repo_ids": normalize_list(args.repo_id),
            "prefer_program_active_unit_ids": True,
            "prefer_existing_repo_units": True,
            "fallback": "manual-selection-required",
        },
        "preference_input_sources": {
            "interfaces": "explicit" if args.interface else "default",
            "baselines": "explicit" if args.baseline else "default",
            "metrics": "explicit" if args.metric else "default",
            "risks": "explicit" if args.risk else "idea-derived",
        },
        "candidate_corpus": repo_corpus,
        "review_route": {
            "owner": "method-designer",
            "action": "confirm-selection",
            "program_id": args.program_id,
            "idea_id": args.idea_id,
            "subject_id": subject_id,
        },
        "preference_task_inputs": copy.deepcopy(preference_task_inputs),
        "preference_context": copy.deepcopy(preference_context),
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
        "preference_context": copy.deepcopy(preference_context),
    }
    matrix_payload = {
        "idea_id": args.idea_id,
        "program_id": args.program_id,
        "proposed_repo_id": proposed_repo_id,
        "proposal_status": "pending_agent_evidence",
        "resource_profile": resource_capacity(resources),
        "hard_constraints": constraints,
        "preference_contract": {
            "operation": "design",
            "hard_fallback_paths": ["profile.resources", "profile.constraints"],
            "soft_missing": "neutral-default",
        },
        "resource_requests": resource_requests,
        "experiments": experiments,
        "baselines": baselines,
        "baseline_judgement_claim_id": "method-baselines",
        "risks": risks,
        "risk_judgement_claim_id": "method-risks",
        "information_types": ["fact", "inference", "evaluation", "unverified"],
        "confirmation_status": "pending_user_confirmation",
        "preference_context": copy.deepcopy(preference_context),
    }
    state["selected_idea_id"] = args.idea_id
    state["method_proposal"] = {
        "subject_id": subject_id,
        "proposed_repo_id": proposed_repo_id,
        "status": "needs_agent_fill",
        "preference_context": copy.deepcopy(preference_context),
    }
    if resources:
        state["resource_constraints"] = resources
    if constraints:
        state["hard_constraints"] = constraints

    # A first prepare targets the absent directory so abort removes it entirely.
    # Once the directory exists, keep the target set exact and avoid checkpointing
    # unrelated method artifacts that may belong to another idea.
    prepare_targets = [paths["state"]]
    if paths["design_root"].exists():
        prepare_targets.extend([paths["method"], paths["choice"], paths["interfaces"], paths["matrix"]])
    else:
        prepare_targets.append(paths["design_root"])
    with mutation_transaction(root, "method:prepare", prepare_targets):
        if paths["choice"].exists():
            raise SystemExit("A method proposal was created concurrently; reload it instead of overwriting it.")
        if load_yaml(paths["state"], default=None) != state_before:
            raise SystemExit("Program state changed while preparing the method; reload before retrying.")
        current_record, _ = locate_record(root, args.idea_id, kind="idea", fuzzy=False)
        if current_record != record or str(current_record.get("status") or "") != "selected":
            raise SystemExit("Selected idea changed while preparing the method; reload before retrying.")
        current_rankings, current_corpus = repo_candidates(
            root,
            current_record,
            normalize_list(args.repo_id),
            normalize_list(state_before.get("active_unit_ids", [])) if isinstance(state_before, dict) else [],
            selected_research_focus,
        )
        current_preferences = resolve_method_preferences(
            root,
            task_inputs=method_preference_task_inputs(
                root,
                current_record,
                program_id=args.program_id,
                idea_id=args.idea_id,
                state=load_program_state(paths["state"], args.program_id),
                repo_ids=args.repo_id,
                interfaces=explicit_interfaces,
                baselines=args.baseline,
                metrics=args.metric,
                risks=args.risk,
            ),
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
        )
        if (
            current_rankings != repo_rankings
            or current_corpus != repo_corpus
            or profile_resources(root) != resources
            or profile_constraints(root) != constraints
            or method_preference_task_inputs(
                root,
                current_record,
                program_id=args.program_id,
                idea_id=args.idea_id,
                state=load_program_state(paths["state"], args.program_id),
                repo_ids=args.repo_id,
                interfaces=explicit_interfaces,
                baselines=args.baseline,
                metrics=args.metric,
                risks=args.risk,
            )
            != preference_task_inputs
            or method_preference_state(current_preferences) != preference_context
        ):
            raise SystemExit("Method inputs changed while preparing the proposal; reload before retrying.")
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
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: prepare method {args.program_id} {args.idea_id}",
        target_paths=[paths["method"], paths["choice"], paths["interfaces"], paths["matrix"], paths["state"]],
    )
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
        stored_preference_context = require_current_method_preferences(
            root,
            program_id=args.program_id,
            idea_id=args.idea_id,
            choice=choice,
        )
        if "selected_repo_id" in choice:
            raise SystemExit("Unconfirmed method artifacts must not contain selected_repo_id.")
        proposed_repo_id = str(choice.get("proposed_repo_id") or "").strip()
        if not proposed_repo_id:
            raise SystemExit("Method proposal has no proposed repository candidate.")
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
        require_proposed_repo_snapshot(source_roots, proposed_repo_id)
        build_verification_receipt(choice, paths["design_root"], source_roots=source_roots)
        choice["updated_at"] = utc_now_iso()
        choice["status"] = "ready_for_review"
        choice["selection_status"] = "ready_for_review"
        choice["needs_human_confirmation"] = True
        choice["payload"]["method_selection"]["agent_fill_status"] = "verified"
        interfaces = load_method_artifact(paths["interfaces"], label="interface artifact")
        matrix = load_method_artifact(paths["matrix"], label="experiment matrix")
        if (
            interfaces.get("preference_context") != stored_preference_context
            or matrix.get("preference_context") != stored_preference_context
        ):
            raise SystemExit("Method artifacts disagree on preference context; prepare the method again.")
        interfaces["proposal_status"] = "ready_for_review"
        matrix["proposal_status"] = "ready_for_review"
        write_yaml_if_changed(paths["choice"], choice)
        write_yaml_if_changed(paths["interfaces"], interfaces)
        write_yaml_if_changed(paths["matrix"], matrix)
    checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: verify method {args.program_id} {args.idea_id}",
        target_paths=targets,
    )
    print("方法判断与逐字证据已通过校验，等待你的确认。")
    return 0


def confirm_method(
    root: Path,
    args: argparse.Namespace,
    *,
    manage_transaction: bool = True,
    create_checkpoint: bool = True,
    emit_output: bool = True,
) -> int:
    paths = method_paths(root, args.program_id, args.idea_id)
    targets = [paths["method"], paths["choice"], paths["interfaces"], paths["matrix"], paths["state"], paths["events"]]
    transaction = mutation_transaction(root, "method:confirm", targets) if manage_transaction else nullcontext()
    with transaction:
        current_idea, _ = locate_record(root, args.idea_id, kind="idea", fuzzy=False)
        if str(current_idea.get("status") or "") != "selected":
            raise SystemExit("The idea is no longer selected; refusing to confirm this method proposal.")
        choice = load_method_artifact(paths["choice"], label="selection artifact")
        require_current_method_subject(choice, args.program_id, args.idea_id)
        require_current_method_preferences(
            root,
            choice,
            program_id=args.program_id,
            idea_id=args.idea_id,
        )
        if str(choice.get("status") or "") != "ready_for_review":
            raise SystemExit("Method selection is not ready for review; complete evidence verification first.")
        if "selected_repo_id" in choice:
            raise SystemExit("Method selection is already finalized or requires repair.")
        readiness = readiness_violations(root, choice, paths["choice"])
        if readiness:
            raise SystemExit("Method selection is not ready for confirmation:\n  - " + "\n  - ".join(readiness))
        try:
            require_judgement_snapshot(
                choice,
                expected_snapshot=args.expected_snapshot,
                owner="method-designer",
                path=rel(root, paths["choice"]),
                root=root,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        proposed_repo_id = str(choice.get("proposed_repo_id") or "").strip()
        claims, violations = validate_method_claims(choice, proposed_repo_id)
        if violations:
            raise SystemExit("Method judgement confirmation failed:\n  - " + "\n  - ".join(violations))
        source_roots = method_source_roots(root, args.program_id, claims)
        require_proposed_repo_snapshot(source_roots, proposed_repo_id)

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
        existing_idea_id = str(state.get("selected_idea_id") or "").strip()
        if existing_idea_id and existing_idea_id != args.idea_id:
            raise SystemExit("The program now points to a different selected idea; refusing to overwrite it.")
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
    if create_checkpoint:
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: confirm method {args.program_id} {args.idea_id}",
            target_paths=targets,
        )
    if emit_output:
        print("方法选择已确认，实验规划阶段已经同步推进。下一步可运行 kb next。")
    return 0


def reject_method(
    root: Path,
    args: argparse.Namespace,
    *,
    manage_transaction: bool = True,
    create_checkpoint: bool = True,
    emit_output: bool = True,
) -> int:
    paths = method_paths(root, args.program_id, args.idea_id)
    targets = [paths["method"], paths["choice"], paths["interfaces"], paths["matrix"], paths["state"]]
    transaction = mutation_transaction(root, "method:reject", targets) if manage_transaction else nullcontext()
    with transaction:
        current_idea, _ = locate_record(root, args.idea_id, kind="idea", fuzzy=False)
        if str(current_idea.get("status") or "") != "selected":
            raise SystemExit("The idea is no longer selected; refusing to reject this method proposal.")
        choice = load_method_artifact(paths["choice"], label="selection artifact")
        require_current_method_subject(choice, args.program_id, args.idea_id)
        violations = readiness_violations(root, choice, paths["choice"])
        if violations:
            raise SystemExit("Method selection is not ready for rejection:\n  - " + "\n  - ".join(violations))
        try:
            require_judgement_snapshot(
                choice,
                expected_snapshot=args.expected_snapshot,
                owner="method-designer",
                path=rel(root, paths["choice"]),
                root=root,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        apply_judgement_rejection(choice, reason=args.reason)
        choice["status"] = "rejected"
        choice["selection_status"] = "rejected"
        choice["updated_at"] = utc_now_iso()
        choice["payload"]["method_selection"]["agent_fill_status"] = "rejected"

        interfaces = load_method_artifact(paths["interfaces"], label="interface artifact")
        matrix = load_method_artifact(paths["matrix"], label="experiment matrix")
        for artifact in (interfaces, matrix):
            artifact["proposal_status"] = "rejected"
            artifact["confirmation_status"] = "rejected"

        state = load_program_state(paths["state"], args.program_id)
        existing_idea_id = str(state.get("selected_idea_id") or "").strip()
        if existing_idea_id and existing_idea_id != args.idea_id:
            raise SystemExit("The program now points to a different selected idea; refusing to overwrite it.")
        proposal = state.get("method_proposal")
        if not isinstance(proposal, dict):
            proposal = {}
        proposal.update(
            {
                "subject_id": str(choice.get("id") or ""),
                "proposed_repo_id": str(choice.get("proposed_repo_id") or ""),
                "status": "rejected",
            }
        )
        proposal.pop("selected_repo_id", None)
        state["method_proposal"] = proposal

        method_text = paths["method"].read_text(encoding="utf-8") if paths["method"].exists() else ""
        method_text = method_text.replace(
            "- Status: proposal only; runtime-agent evidence and human confirmation are still required.",
            "- Status: rejected by the user; no repository was selected and program stage did not advance.",
        )
        write_text_if_changed(paths["method"], method_text)
        write_yaml_if_changed(paths["choice"], choice)
        write_yaml_if_changed(paths["interfaces"], interfaces)
        write_yaml_if_changed(paths["matrix"], matrix)
        write_yaml_if_changed(paths["state"], state)
    if create_checkpoint:
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: reject method {args.program_id} {args.idea_id}",
            target_paths=targets,
        )
    if emit_output:
        print("方法选择已拒绝；没有选择仓库，也没有推进实验规划阶段。")
    return 0


def prepare_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> dict:
    """Pure-read method-selection preflight for the root Obsidian transaction."""
    route = item.get("confirm_route" if decision == "confirm" else "reject_route")
    route = route if isinstance(route, dict) else {}
    expected_action = "confirm-selection" if decision == "confirm" else "reject-selection"
    if route.get("owner") != "method-designer" or route.get("action") != expected_action:
        raise ValueError("method review route is invalid")
    program_id = str(route.get("program_id") or "")
    idea_id = str(route.get("idea_id") or "")
    paths = method_paths(root, program_id, idea_id)
    current_idea, _ = locate_record(root, idea_id, kind="idea", fuzzy=False)
    if str(current_idea.get("status") or "") != "selected":
        raise ValueError("the method idea is no longer selected")
    choice = load_method_artifact(paths["choice"], label="selection artifact")
    require_current_method_subject(choice, program_id, idea_id)
    violations = readiness_violations(root, choice, paths["choice"])
    if violations:
        raise ValueError("method selection is no longer ready")
    snapshot = item.get("snapshot_binding")
    if not isinstance(snapshot, dict):
        raise ValueError("method review snapshot is missing")
    require_judgement_snapshot(
        choice,
        expected_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        owner="method-designer",
        path=rel(root, paths["choice"]),
        root=root,
    )
    state = load_program_state(paths["state"], program_id)
    existing_idea_id = str(state.get("selected_idea_id") or "").strip()
    if existing_idea_id and existing_idea_id != idea_id:
        raise ValueError("program now points to another selected idea")
    if decision == "confirm":
        if str(choice.get("status") or "") != "ready_for_review" or "selected_repo_id" in choice:
            raise ValueError("method selection is no longer confirmable")
        proposed_repo_id = str(choice.get("proposed_repo_id") or "").strip()
        claims, claim_violations = validate_method_claims(choice, proposed_repo_id)
        if claim_violations:
            raise ValueError("method selection claims are invalid")
        existing_repo_id = str(state.get("selected_repo_id") or "").strip()
        if existing_repo_id and existing_repo_id != proposed_repo_id:
            raise ValueError("program already selected another repository")
        source_roots = method_source_roots(root, program_id, claims)
        require_proposed_repo_snapshot(source_roots, proposed_repo_id)
        candidate = copy.deepcopy(choice)
        candidate["selected_repo_id"] = proposed_repo_id
        candidate["selection_status"] = "confirmed"
        candidate["status"] = "confirmed"
        candidate["payload"]["method_selection"]["selected_repo_id"] = proposed_repo_id
        candidate["payload"]["method_selection"]["agent_fill_status"] = "confirmed"
        apply_confirmation(
            candidate,
            confirmed_by=actor,
            evidence=evidence,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            method="method-designer confirm-selection",
            project_root=root,
            verification_root=paths["design_root"],
            trusted_source_roots=source_roots,
        )
        targets = [paths["method"], paths["choice"], paths["interfaces"], paths["matrix"], paths["state"], paths["events"]]
    elif decision == "reject":
        candidate = copy.deepcopy(choice)
        apply_judgement_rejection(candidate, reason=rejection_reason)
        targets = [paths["method"], paths["choice"], paths["interfaces"], paths["matrix"], paths["state"]]
    else:
        raise ValueError("method review decision is invalid")
    load_method_artifact(paths["interfaces"], label="interface artifact")
    load_method_artifact(paths["matrix"], label="experiment matrix")
    return {
        "owner": "method-designer",
        "decision": decision,
        "program_id": program_id,
        "idea_id": idea_id,
        "target_paths": targets,
    }


def apply_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> list[Path]:
    """Apply one method decision under the coordinator's existing transaction."""
    plan = prepare_review_batch_decision(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        rejection_reason=rejection_reason,
    )
    args = argparse.Namespace(
        program_id=plan["program_id"],
        idea_id=plan["idea_id"],
        expected_snapshot=json.dumps(item["snapshot_binding"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        confirmed_by=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        reason=rejection_reason,
    )
    if decision == "confirm":
        confirm_method(root, args, manage_transaction=False, create_checkpoint=False, emit_output=False)
    else:
        reject_method(root, args, manage_transaction=False, create_checkpoint=False, emit_output=False)
    return list(plan["target_paths"])


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
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
    if args.command == "reject-selection":
        return reject_method(root, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

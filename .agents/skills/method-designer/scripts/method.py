#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

from research.common import add_project_root_argument, append_program_reporting_event, ensure_dir, load_yaml, normalize_list, print_resolved_project_roots, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.core import iter_records, locate_record, project_root, rel


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


def repo_candidates(root: Path, record: dict[str, Any], pinned_repo_ids: list[str]) -> list[dict[str, Any]]:
    repo_records = iter_records(root, kind="repo")
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
    return scored[:5]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Design a method from a selected idea.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    design = subparsers.add_parser("design")
    design.add_argument("--idea-id", required=True)
    design.add_argument("--program-id", required=True)
    design.add_argument("--repo-id", action="append", default=[])
    design.add_argument("--interface", action="append", default=[])
    design.add_argument("--baseline", action="append", default=[])
    design.add_argument("--metric", action="append", default=[])
    design.add_argument("--risk", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, _ = locate_record(root, args.idea_id, kind="idea")
    if record.get("kind") != "idea":
        raise SystemExit(f"{args.idea_id} is not an idea record")
    if record.get("status") != "selected":
        raise SystemExit(f"{args.idea_id} must be selected before method design")
    design_root = root / "kb" / "programs" / args.program_id / "design"
    ensure_dir(design_root)
    method_path = design_root / f"{args.idea_id}-method.md"
    repo_choice_path = design_root / f"{args.idea_id}-repo-choice.yaml"
    interfaces_path = design_root / f"{args.idea_id}-interfaces.yaml"
    matrix_path = design_root / f"{args.idea_id}-experiment-matrix.yaml"
    state_path = root / "kb" / "programs" / args.program_id / "state.yaml"
    repo_rankings = repo_candidates(root, record, normalize_list(args.repo_id))
    selected_repo = repo_rankings[0] if repo_rankings else {
        "id": normalize_list(args.repo_id)[0] if normalize_list(args.repo_id) else "",
        "title": "",
        "summary": "",
        "entrypoints": [],
        "score": 0,
        "overlap": [],
        "tags": [],
        "topics": [],
    }
    candidate_repos = repo_rankings if repo_rankings else ([selected_repo] if selected_repo.get("id") else [])
    interfaces = parse_name_detail(args.interface, "interface")
    if not interfaces:
        interfaces = [
            {"name": "data-flow", "detail": "Define how inputs, outputs, and evaluation traces move through the minimal variant."},
            {"name": "experiment-switch", "detail": "Expose one config surface that toggles baseline and idea variant."},
        ]
    baselines = normalize_list(args.baseline) or ["closest-unmodified-repo-baseline", "current-best-manual-baseline"]
    metrics = normalize_list(args.metric) or ["success_rate", "recovery_rate", "runtime_cost"]
    risks = normalize_list(args.risk) or normalize_list(record.get("payload", {}).get("analysis", {}).get("risks", []))
    problem = record.get("payload", {}).get("problem", {})
    hypothesis = record.get("payload", {}).get("hypothesis", {})
    analysis = record.get("payload", {}).get("analysis", {})

    write_text_if_changed(
        method_path,
        (
            f"# Method Design: {record.get('title', '')}\n\n"
            "## Problem\n\n"
            f"{problem.get('problem_definition', '')}\n\n"
            "## Core Hypothesis\n\n"
            f"{hypothesis.get('core_hypothesis', '')}\n\n"
            "## Repo Choice\n\n"
            f"- Selected repo: `{selected_repo.get('id') or 'pending'}`\n"
            f"- Repo summary: {selected_repo.get('summary', '') or '待补充'}\n"
            f"- Overlap signals: {', '.join(selected_repo.get('overlap', [])) or 'manual selection required'}\n\n"
            "## Minimal Design\n\n"
            f"- Base approach: {analysis.get('minimum_validation_path', '') or '从最小可验证实现开始'}\n"
            f"- Expected differentiator: {hypothesis.get('difference_from_prior_work', '') or '待补充'}\n"
            f"- Key mechanism: {hypothesis.get('key_mechanism', '') or '待补充'}\n\n"
            "## Interfaces\n\n"
            + "".join(f"- `{item['name']}`: {item['detail']}\n" for item in interfaces)
            + "\n## Validation Plan\n\n"
            + "".join(f"- Baseline: {item}\n" for item in baselines)
            + "".join(f"- Metric: {item}\n" for item in metrics)
            + "".join(f"- Risk: {item}\n" for item in (risks or ['待补充']))
            + "- Stop condition: Stop if baseline parity is not reached or the interface seam stays unstable.\n"
        ),
    )
    write_yaml_if_changed(
        repo_choice_path,
        {
            "idea_id": args.idea_id,
            "program_id": args.program_id,
            "selected_repo_id": selected_repo.get("id", ""),
            "selection_reason": (
                f"Selected `{selected_repo.get('id', '')}` with score={selected_repo.get('score', 0)} based on idea/repo token overlap."
                if selected_repo.get("id")
                else "No repo unit matched yet; manual repo selection required."
            ),
            "selection_status": "pending_user_confirmation",
            "information_types": ["fact", "inference", "evaluation", "unverified"],
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
                "prefer_existing_repo_units": True,
                "fallback": "manual-selection-required",
            },
        },
    )
    write_yaml_if_changed(
        interfaces_path,
        {
            "idea_id": args.idea_id,
            "program_id": args.program_id,
            "selected_repo_id": selected_repo.get("id", ""),
            "interfaces": interfaces,
            "config_keys": ["experiment.variant", "adapter.mode", "eval.slice"],
            "metrics": metrics,
            "artifacts": ["logs/", "checkpoints/", "tables/", "failure-cases/"],
            "edit_surfaces": normalize_list(selected_repo.get("entrypoints", []))[:5],
            "information_types": ["fact", "inference", "unverified"],
            "confirmation_status": "pending_user_confirmation",
        },
    )
    write_yaml_if_changed(
        matrix_path,
        {
            "idea_id": args.idea_id,
            "program_id": args.program_id,
            "selected_repo_id": selected_repo.get("id", ""),
            "experiments": [
                {
                    "name": "baseline-parity",
                    "goal": "Verify the chosen repo baseline still runs and reaches parity.",
                    "kind": "baseline",
                    "repo_dependency": selected_repo.get("id", ""),
                    "interface_under_test": [],
                    "metrics": metrics,
                    "evidence_to_collect": ["baseline metrics", "runtime cost", "failure cases"],
                    "decision_gate": "Must pass before deeper method changes.",
                    "status": "planned",
                },
                {
                    "name": "minimal-idea-variant",
                    "goal": "Validate the core hypothesis with the smallest interface change.",
                    "kind": "main",
                    "repo_dependency": selected_repo.get("id", ""),
                    "interface_under_test": [item["name"] for item in interfaces[:2]],
                    "metrics": metrics,
                    "evidence_to_collect": ["delta vs baseline", "qualitative failures", "ablation-ready checkpoints"],
                    "decision_gate": "Proceed only if at least one target metric improves without breaking baseline parity.",
                    "status": "planned",
                },
                {
                    "name": "interface-ablation",
                    "goal": "Turn off the new interface seams one by one.",
                    "kind": "ablation",
                    "repo_dependency": selected_repo.get("id", ""),
                    "interface_under_test": [item["name"] for item in interfaces],
                    "metrics": metrics,
                    "evidence_to_collect": ["ablation table", "regression cases"],
                    "decision_gate": "Keep only interfaces that show isolated value.",
                    "status": "planned",
                },
                {
                    "name": "stress-and-failure-slice",
                    "goal": "Collect targeted failure evidence for the most fragile slice.",
                    "kind": "diagnostic",
                    "repo_dependency": selected_repo.get("id", ""),
                    "interface_under_test": [item["name"] for item in interfaces[:1]],
                    "metrics": metrics,
                    "evidence_to_collect": ["failure taxonomy", "resource bottlenecks", "follow-up requests"],
                    "decision_gate": "Convert repeated failures into experiment-workbench diagnosis items.",
                    "status": "planned",
                },
            ],
            "baselines": baselines,
            "risks": risks,
            "information_types": ["fact", "inference", "evaluation", "unverified"],
            "confirmation_status": "pending_user_confirmation",
        },
    )
    state = load_yaml(state_path, default={})
    if not isinstance(state, dict) or not state:
        state = {
            **yaml_default(f"{args.program_id}-state", "method-designer", status="active"),
            "program_id": args.program_id,
            "question": "",
            "goal": "",
            "stage": "implementation-planning",
            "active_unit_ids": [],
            "blockers": [],
            "next_actions": [],
            "resource_constraints": [],
        }
    state["selected_idea_id"] = args.idea_id
    state["selected_repo_id"] = selected_repo.get("id", "")
    if str(state.get("stage") or "").strip() in {"", "init", "idea-review"}:
        state["stage"] = "implementation-planning"
    write_yaml_if_changed(state_path, state)
    append_program_reporting_event(
        root,
        args.program_id,
        {
            "source_skill": "method-designer",
            "event_type": "method-design",
            "title": record.get("title", args.idea_id),
            "summary": (
                f"Drafted method design with repo `{selected_repo.get('id', 'pending')}`, "
                f"{len(interfaces)} interfaces, and {4} planned matrix rows."
            ),
            "stage": "implementation-planning",
            "idea_ids": [args.idea_id],
            "repo_ids": normalize_list([selected_repo.get("id", "")]),
            "artifacts": [
                rel(root, method_path),
                rel(root, repo_choice_path),
                rel(root, interfaces_path),
                rel(root, matrix_path),
                rel(root, state_path),
            ],
            "tags": ["method-design", "repo-choice", "interfaces", "experiment-matrix"],
        },
        generated_by="method-designer",
    )
    print(method_path.relative_to(root))
    print(repo_choice_path.relative_to(root))
    print(interfaces_path.relative_to(root))
    print(matrix_path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

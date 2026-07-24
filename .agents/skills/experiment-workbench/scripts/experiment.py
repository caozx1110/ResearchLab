#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
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

from research.common import (
    add_project_root_argument,
    append_list_item,
    append_program_reporting_event,
    load_list_document,
    load_yaml,
    normalize_list,
    print_resolved_project_roots,
    write_text_if_changed,
    write_yaml_if_changed,
)
from research.core import append_history, build_index, build_unit_id, candidate_pools_path, command_mutation, confirm_unit, default_record, ensure_workspace, kb_root, locate_record, project_root, record_path, rel, topic_taxonomy_path, write_record
from research.evidence import attach_claims, build_verification_receipt, validate_claims, verify_claim_evidence
from research.judgements import confirmation_binding
from research.preference_selection import (
    eligible_preferences,
    load_effective_selection,
    resolve_operation_preferences,
    selection_binding,
)

RUN_OUTCOME_CHOICES = ["success", "partial", "failed", "blocked", "inconclusive"]
CLASSIFICATION_CHOICES = ["method", "implementation", "data", "evaluation", "resource", "environment", "process", "unknown"]
FOLLOW_UP_STATUS_CHOICES = ["open", "blocked", "done"]
FOLLOW_UP_PRIORITY_CHOICES = ["low", "normal", "high", "critical"]
METRIC_DIRECTION_CHOICES = ["higher-better", "lower-better", "neutral", "unknown"]
RUN_TAG_CHOICES = ["baseline", "milestone"]
DEFAULT_RECENT_RUNS = 5
RUN_EVIDENCE_ARTIFACT_RE = re.compile(r"^(?:run-log\.yaml|runs/run-\d{3}\.md)$")


def _index_targets(root: Path) -> list[Path]:
    return [
        kb_root(root) / "index.yaml",
        kb_root(root) / "index.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
    ]


def _program_event_path(root: Path, program_id: str) -> Path:
    return kb_root(root) / "programs" / program_id / "workflow" / "reporting-events.yaml"


def _experiment_command_targets(args, root: Path) -> list[Path]:
    if args.command == "plan":
        experiment_id = build_unit_id("experiment", args.title, f"program:{args.program_id}")
        return [
            record_path(root, "experiment", experiment_id),
            _program_event_path(root, args.program_id),
            *_index_targets(root),
        ]
    record, path = locate_record(root, args.experiment_id, kind="experiment")
    unit = path.parent
    program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
    targets = [path, *_index_targets(root)]
    if program_id:
        targets.append(_program_event_path(root, program_id))
    if args.command == "log-run":
        targets.extend(
            [
                unit / "runs",
                list_document_path(unit, "run-log"),
                unit / "run-log.md",
            ]
        )
    elif args.command == "follow-up":
        targets.extend([list_document_path(unit, "follow-ups"), unit / "follow-ups.md"])
    elif args.command == "diagnose":
        targets.extend([list_document_path(unit, "diagnoses"), unit / "diagnosis.md", unit / "diagnosis-fill.yaml"])
    return targets


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)
    parser.add_argument("--user-authorization", default="")
    parser.add_argument("--authorization-source", default="")


def parse_metrics(items: list[str]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for item in items:
        if "=" not in item:
            sys.stderr.write(f"[experiment.parse_metrics] WARN: ignoring --metric without '=': {item}\n")
            continue
        name, raw_value = item.split("=", 1)
        name = name.strip()
        if not name:
            sys.stderr.write(f"[experiment.parse_metrics] WARN: ignoring --metric without a name: {item}\n")
            continue
        value_text = raw_value.strip()
        direction = "unknown"
        direction_match = re.search(r"\s*:\s*([a-zA-Z_-]+)\s*$", value_text)
        if direction_match:
            candidate = direction_match.group(1).lower().replace("_", "-")
            if candidate in METRIC_DIRECTION_CHOICES:
                direction = candidate
                value_text = value_text[: direction_match.start()].strip()
            else:
                sys.stderr.write(
                    f"[experiment.parse_metrics] WARN: unknown direction '{direction_match.group(1)}' "
                    f"for metric '{name}'; keeping direction=unknown\n"
                )
        unit = ""
        unit_match = re.search(r"\[([^\[\]]+)\]\s*$", value_text)
        if unit_match:
            unit = unit_match.group(1).strip()
            value_text = value_text[: unit_match.start()].strip()
        try:
            value: float | str = float(value_text)
        except ValueError:
            value = value_text
            sys.stderr.write(
                f"[experiment.parse_metrics] WARN: metric '{name}' value '{value_text}' is not numeric; "
                "preserving it as a string for backward compatibility\n"
            )
        payload[name] = {"name": name, "value": value, "unit": unit, "direction": direction}
    return payload


def _contained_artifact_identity(root: Path, item: str) -> tuple[str, Path]:
    project = root.resolve()
    candidate = Path(item).expanduser()
    unresolved = candidate if candidate.is_absolute() else project / candidate
    resolved = unresolved.resolve(strict=False)
    try:
        identity = resolved.relative_to(project).as_posix()
    except ValueError as exc:
        raise SystemExit(f"Experiment artifact must remain inside the project workspace: {item}") from exc
    if not identity or identity == ".":
        raise SystemExit("Experiment artifact must identify a file or directory inside the project workspace.")
    return identity, resolved


def verify_artifacts(root: Path, items: list[str]) -> list[dict[str, Any]]:
    artifacts = []
    for item in normalize_list(items):
        identity, resolved = _contained_artifact_identity(root, item)
        present = resolved.exists()
        status = "present" if present else "missing"
        artifact = {"path": identity, "status": status, "generated": False}
        if present:
            artifact["kind"] = "directory" if resolved.is_dir() else "file"
        else:
            sys.stderr.write(f"[experiment.verify_artifacts] WARN: artifact does not exist: {item}\n")
        artifacts.append(artifact)
    return artifacts


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_content_digest(path: Path) -> str:
    if path.is_file():
        return _hash_file(path)
    rows: list[dict[str, str]] = []
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        identity = child.relative_to(path).as_posix()
        if child.is_symlink():
            rows.append(
                {
                    "identity": identity,
                    "kind": "symlink",
                    "content_digest": hashlib.sha256(os.readlink(child).encode("utf-8")).hexdigest(),
                }
            )
        elif child.is_file():
            rows.append({"identity": identity, "kind": "file", "content_digest": _hash_file(child)})
        elif child.is_dir():
            rows.append({"identity": identity, "kind": "directory", "content_digest": ""})
    return _sha256_payload({"tree": rows})


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _run_identity_payload(
    experiment_id: str,
    tested_hypothesis: str,
    changes: list[str],
    metrics: dict[str, dict[str, Any]],
    artifacts: list[dict[str, Any]],
    config_revision: str,
) -> dict[str, Any]:
    return {
        "experiment_id": _normalized_text(experiment_id),
        "tested_hypothesis": _normalized_text(tested_hypothesis),
        "changes": sorted({_normalized_text(item) for item in changes if _normalized_text(item)}),
        "metric_schema": sorted(
            (
                {
                    "name": _normalized_text(metric.get("name") or name),
                    "unit": _normalized_text(metric.get("unit")),
                    "direction": _normalized_text(metric.get("direction") or "unknown"),
                }
                for name, metric in metrics.items()
            ),
            key=lambda item: (item["name"], item["unit"], item["direction"]),
        ),
        "artifact_identities": sorted(
            {
                _normalized_text(item.get("path"))
                for item in artifacts
                if isinstance(item, dict) and _normalized_text(item.get("path"))
            }
        ),
        "config_revision": _normalized_text(config_revision),
    }


def _sha256_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def experiment_preference_context(
    args: argparse.Namespace,
    record: dict[str, Any] | None = None,
    prepared: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Return bounded canonical task inputs for one preference-sensitive action."""
    command = str(getattr(args, "command", "") or "")
    if command == "plan":
        return {
            "program_id": str(args.program_id or ""),
            "title_digest": _sha256_payload({"text": _normalized_text(args.title)}),
            "idea_id": str(args.idea_id or ""),
            "goal_digest": _sha256_payload({"text": _normalized_text(args.goal)}),
            "hypothesis_digest": _sha256_payload({"text": _normalized_text(args.hypothesis)}),
        }
    record = record if isinstance(record, dict) else {}
    prepared = prepared if isinstance(prepared, dict) else {}
    base: dict[str, object] = {
        "experiment_id": str(getattr(args, "experiment_id", "") or ""),
        "record_digest": _sha256_payload(
            {
                "id": record.get("id"),
                "status": record.get("status"),
                "summary": record.get("summary"),
                "payload": record.get("payload"),
            }
        ),
    }
    if command == "log-run":
        base.update(
            {
                "config_revision": _normalized_text(args.config_revision),
                "seed": args.seed,
                "run_input_digest": _sha256_payload(
                    {
                        "changes": normalize_list(args.change),
                        "metrics": normalize_list(args.metric),
                        "result_summary": _normalized_text(args.result_summary),
                        "outcome": args.outcome,
                        "classifications": normalize_list(args.classification),
                        "tested_hypothesis": _normalized_text(
                            prepared.get("tested_hypothesis", args.tested_hypothesis)
                        ),
                        "next_actions": normalize_list(args.next_action),
                        "why_this_run": _normalized_text(args.why_this_run),
                        "tags": normalize_list(args.tag),
                        "recent_runs": max(int(args.recent_runs or 0), 0),
                        "rerun": bool(args.rerun),
                        "rerun_reason": _normalized_text(args.rerun_reason),
                    }
                ),
                "artifact_facts_digest": _sha256_payload(
                    {"artifacts": prepared.get("artifact_facts", [])}
                ),
                "prior_runs_digest": _sha256_payload(
                    {"runs": prepared.get("prior_runs", [])}
                ),
            }
        )
    elif command == "follow-up":
        base["follow_up_digest"] = _sha256_payload(
            {
                "action": _normalized_text(args.action),
                "category": args.category,
                "priority": args.priority,
                "status": args.status,
                "evidence_needed": normalize_list(args.evidence_needed),
            }
        )
    elif command == "diagnose":
        base["diagnosis_input_digest"] = _sha256_payload(
            {
                "summary": _normalized_text(args.summary),
                "categories": normalize_list(args.category),
                "likely_causes": normalize_list(args.likely_cause),
                "ruled_out": normalize_list(args.ruled_out),
                "unknowns": normalize_list(args.unknown),
                "next_actions": normalize_list(args.next_action),
                "recent_runs": max(int(args.recent_runs or 0), 0),
                "claims_file_fact": prepared.get("claims_file_fact", {}),
                "run_log_digest": _sha256_payload(
                    {"runs": prepared.get("runs", [])}
                ),
            }
        )
    return base


def prepare_experiment_preference_inputs(
    root: Path,
    args: argparse.Namespace,
    record: dict[str, Any],
    unit_root: Path,
) -> dict[str, Any]:
    """Read and validate canonical inputs before resolving a task receipt."""
    if args.command == "log-run":
        if args.rerun and not _normalized_text(args.rerun_reason):
            raise SystemExit("Explicit rerun mode requires a non-empty rerun reason.")
        if not args.rerun and _normalized_text(args.rerun_reason):
            raise SystemExit("A rerun reason is only valid in explicit rerun mode.")
        run_log_document_path = list_document_path(unit_root, "run-log")
        prior_run_log = load_list_document(
            run_log_document_path,
            f"{args.experiment_id}-run-log",
            "experiment-workbench",
        )
        claimed_artifacts = verify_artifacts(root, args.artifact)
        return {
            "run_log_document_path": run_log_document_path,
            "prior_runs": [item for item in prior_run_log.get("items", []) if isinstance(item, dict)],
            "metrics": parse_metrics(args.metric),
            "claimed_artifacts": claimed_artifacts,
            "artifact_facts": [
                {
                    "identity_digest": _sha256_payload({"identity": item.get("path", "")}),
                    "status": str(item.get("status") or ""),
                    "kind": str(item.get("kind") or ""),
                    "content_digest": (
                        _artifact_content_digest(root / str(item.get("path") or ""))
                        if item.get("status") == "present"
                        else ""
                    ),
                }
                for item in claimed_artifacts
            ],
            "tested_hypothesis": _normalized_text(
                args.tested_hypothesis
                or record.get("payload", {}).get("process", {}).get("tested_hypothesis")
            ),
        }
    if args.command == "diagnose":
        run_log = load_list_document(
            list_document_path(unit_root, "run-log"),
            f"{args.experiment_id}-run-log",
            "experiment-workbench",
        )
        return {
            "runs": [item for item in run_log.get("items", []) if isinstance(item, dict)],
            "claims_file_fact": diagnosis_claims_file_fact(root, args.claims_file),
        }
    return {}


def resolve_experiment_preferences(
    root: Path,
    args: argparse.Namespace,
    record: dict[str, Any] | None = None,
    prepared: dict[str, Any] | None = None,
) -> dict[str, object]:
    command = str(getattr(args, "command", "") or "")
    if command not in {"plan", "log-run", "follow-up", "diagnose"}:
        return {}
    try:
        return resolve_operation_preferences(
            root,
            selection_id=str(getattr(args, "preference_selection_id", "") or ""),
            skill="experiment-workbench",
            operation=command,
            canonical_inputs=experiment_preference_context(args, record, prepared),
        )
    except ValueError as exc:
        raise SystemExit(f"Experiment preference selection is invalid: {exc}") from exc


def experiment_preference_state(resolution: dict[str, object]) -> dict[str, object]:
    if not resolution:
        return {}
    return {
        "task_context_digest": str(resolution.get("task_context_digest") or ""),
        "selection_binding": dict(resolution.get("binding") or {}),
        "hard_value_digests": dict(resolution.get("hard_value_digests") or {}),
    }


def _record_experiment_preference_state(
    record: dict[str, Any],
    resolution: dict[str, object],
) -> None:
    if not resolution:
        return
    payload = record.setdefault("payload", {})
    contexts = payload.setdefault("preference_contexts", {})
    contexts[str(resolution.get("operation") or "")] = experiment_preference_state(resolution)


def require_current_experiment_preference_state(
    root: Path,
    record: dict[str, Any],
    *,
    operation: str,
) -> None:
    """Check a verification-bound operation receipt before downstream confirmation.

    The original task context is intentionally not copied into the record.  At
    this later governance step its digest is already protected by the
    verification receipt, so this check only proves that the same selection and
    hard canonical values remain current.
    """
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    contexts = payload.get("preference_contexts") if isinstance(payload.get("preference_contexts"), dict) else {}
    stored = contexts.get(operation)
    if not isinstance(stored, dict):
        raise SystemExit("Experiment preference context is missing; repeat diagnosis before confirmation.")
    task_digest = str(stored.get("task_context_digest") or "")
    binding = stored.get("selection_binding")
    hard_digests = stored.get("hard_value_digests")
    if not isinstance(binding, dict) or not isinstance(hard_digests, dict):
        raise SystemExit("Experiment preference context is invalid; repeat diagnosis before confirmation.")
    eligible = eligible_preferences(root, skill="experiment-workbench", operation=operation)
    current_hard = {
        str(item.get("path") or ""): str(item.get("value_digest") or "")
        for item in eligible.get("items", [])
        if isinstance(item, dict) and str(item.get("strength") or "") == "hard"
    }
    if hard_digests != current_hard:
        raise SystemExit("Experiment hard preferences changed after diagnosis; repeat diagnosis before confirmation.")
    if not binding:
        return
    try:
        receipt = load_effective_selection(
            root,
            selection_id=str(binding.get("selection_id") or ""),
            skill="experiment-workbench",
            operation=operation,
            expected_task_context_digest=task_digest,
        )
    except ValueError as exc:
        raise SystemExit(f"Experiment preferences are stale: {exc}") from exc
    if selection_binding(receipt) != binding:
        raise SystemExit("Experiment preference binding changed after diagnosis; repeat diagnosis before confirmation.")


def build_run_identity(
    experiment_id: str,
    *,
    tested_hypothesis: str,
    changes: list[str],
    metrics: dict[str, dict[str, Any]],
    artifacts: list[dict[str, Any]],
    config_revision: str,
    seed: int | None,
) -> tuple[str, str]:
    """Return the seed-independent configuration fingerprint and repeat group."""
    if not _normalized_text(config_revision):
        raise SystemExit("Experiment run requires a non-empty config revision.")
    payload = _run_identity_payload(
        experiment_id,
        tested_hypothesis,
        changes,
        metrics,
        artifacts,
        config_revision,
    )
    fingerprint = _sha256_payload(payload)
    return fingerprint, fingerprint


def generated_artifact(root: Path, path: Path) -> dict[str, Any]:
    return {"path": rel(root, path), "status": "present", "generated": True, "kind": "file"}


def typed_metric_map(raw_metrics: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw_metrics, list):
        candidates = {str(item.get("name") or ""): item for item in raw_metrics if isinstance(item, dict)}
    elif isinstance(raw_metrics, dict):
        candidates = raw_metrics
    else:
        return {}
    metrics = {}
    for raw_name, raw_metric in candidates.items():
        name = str(raw_name or "").strip()
        if not name:
            continue
        if isinstance(raw_metric, dict):
            metric = dict(raw_metric)
            metric["name"] = str(metric.get("name") or name)
            metric.setdefault("unit", "")
            metric.setdefault("direction", "unknown")
            metrics[name] = metric
            continue
        value: float | str = raw_metric
        if isinstance(raw_metric, str):
            try:
                value = float(raw_metric)
            except ValueError:
                pass
        metrics[name] = {"name": name, "value": value, "unit": "", "direction": "unknown"}
    return metrics


def compare_metric(current: dict[str, Any], prior: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    result = {
        "run_id": str(run.get("id") or ""),
        "tags": normalize_list(run.get("tags")),
        "prior_value": prior.get("value"),
        "prior_unit": str(prior.get("unit") or ""),
        "delta": None,
        "directional_result": "not-comparable",
    }
    current_value = current.get("value")
    prior_value = prior.get("value")
    current_unit = str(current.get("unit") or "")
    prior_unit = str(prior.get("unit") or "")
    if current_unit and prior_unit and current_unit != prior_unit:
        result["reason"] = "unit-mismatch"
        return result
    if not isinstance(current_value, (int, float)) or isinstance(current_value, bool):
        result["reason"] = "current-value-not-numeric"
        return result
    if not isinstance(prior_value, (int, float)) or isinstance(prior_value, bool):
        result["reason"] = "prior-value-not-numeric"
        return result
    delta = float(current_value) - float(prior_value)
    result["delta"] = delta
    if delta == 0:
        result["directional_result"] = "unchanged"
        return result
    direction = str(current.get("direction") or "unknown")
    if direction == "unknown":
        direction = str(prior.get("direction") or "unknown")
    if direction == "higher-better":
        result["directional_result"] = "better" if delta > 0 else "worse"
    elif direction == "lower-better":
        result["directional_result"] = "better" if delta < 0 else "worse"
    else:
        result["directional_result"] = "increased" if delta > 0 else "decreased"
    return result


def build_run_comparison(metrics: dict[str, dict[str, Any]], prior_runs: list[dict[str, Any]], recent_n: int) -> list[dict[str, Any]]:
    recent_runs = prior_runs[-recent_n:] if recent_n > 0 else []
    anchor_runs = [run for run in prior_runs if set(normalize_list(run.get("tags"))) & set(RUN_TAG_CHOICES)]
    comparison = []
    for name, current in metrics.items():
        def against(run: dict[str, Any]) -> dict[str, Any] | None:
            prior = typed_metric_map(run.get("metrics")).get(name)
            return compare_metric(current, prior, run) if prior else None

        recent = [item for run in recent_runs if (item := against(run)) is not None]
        anchors = [item for run in anchor_runs if (item := against(run)) is not None]
        comparison.append(
            {
                "name": name,
                "current_value": current.get("value"),
                "unit": str(current.get("unit") or ""),
                "direction": str(current.get("direction") or "unknown"),
                "last_run": recent[-1] if recent else None,
                "recent_runs": recent,
                "anchors": anchors,
            }
        )
    return comparison


def summarize_run_for_diagnosis(run: dict[str, Any]) -> dict[str, Any]:
    raw_artifacts = run.get("artifacts", [])
    artifacts = [dict(item) if isinstance(item, dict) else str(item) for item in raw_artifacts] if isinstance(raw_artifacts, list) else []
    return {
        "run_id": str(run.get("id") or ""),
        "created_at": str(run.get("created_at") or ""),
        "result_summary": str(run.get("result_summary") or ""),
        "outcome": str(run.get("outcome") or "inconclusive"),
        "tags": normalize_list(run.get("tags")),
        "metrics": typed_metric_map(run.get("metrics")),
        "artifacts": artifacts,
    }


def build_diagnosis_context(runs: list[dict[str, Any]], recent_n: int) -> dict[str, Any]:
    recent_runs = runs[-recent_n:] if recent_n > 0 else []
    anchor_runs = [run for run in runs if set(normalize_list(run.get("tags"))) & set(RUN_TAG_CHOICES)]
    return {
        "recent_n": recent_n,
        "recent_runs": [summarize_run_for_diagnosis(run) for run in recent_runs],
        "anchors": [summarize_run_for_diagnosis(run) for run in anchor_runs],
    }


def load_diagnosis_claims(root: Path, unit_root: Path, experiment_id: str, claims_file: str) -> list[dict[str, Any]]:
    if not claims_file:
        return []
    claims_path = Path(claims_file).expanduser()
    if not claims_path.is_absolute():
        claims_path = root / claims_path
    payload = load_yaml(claims_path, default=[])
    claims = payload.get("claims", []) if isinstance(payload, dict) else payload
    violations = validate_claims(claims)
    if isinstance(claims, list):
        for claim_index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            if str(claim.get("confirmation_status") or "") != "pending_user_confirmation":
                violations.append(f"claims[{claim_index}]: diagnosis claim must remain pending_user_confirmation")
            refs = claim.get("evidence_refs") or []
            if isinstance(refs, (list, tuple)):
                for ref_index, evidence_ref in enumerate(refs):
                    if not isinstance(evidence_ref, dict):
                        continue
                    source_unit_id = str(evidence_ref.get("source_unit_id") or "")
                    artifact = str(evidence_ref.get("artifact") or "")
                    if source_unit_id != experiment_id:
                        violations.append(
                            f"claims[{claim_index}].evidence_refs[{ref_index}]: source_unit_id must be {experiment_id}"
                        )
                    if not RUN_EVIDENCE_ARTIFACT_RE.fullmatch(artifact):
                        violations.append(
                            f"claims[{claim_index}].evidence_refs[{ref_index}]: artifact must be run-log.yaml or runs/run-NNN.md"
                        )
            violations.extend(verify_claim_evidence(claim, unit_root))
    if violations:
        raise SystemExit("Diagnosis claims failed evidence verification:\n- " + "\n- ".join(violations))
    return claims


def diagnosis_claims_file_fact(root: Path, claims_file: str) -> dict[str, str]:
    if not claims_file:
        return {"status": "not-provided", "identity_digest": "", "content_digest": "", "kind": ""}
    candidate = Path(claims_file).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=False)
    identity_digest = _sha256_payload({"identity": resolved.as_posix()})
    if not resolved.exists():
        return {
            "status": "missing",
            "identity_digest": identity_digest,
            "content_digest": "",
            "kind": "",
        }
    kind = "directory" if resolved.is_dir() else "file"
    return {
        "status": "present",
        "identity_digest": identity_digest,
        "content_digest": _artifact_content_digest(resolved),
        "kind": kind,
    }


def write_diagnosis_fill_scaffold(
    unit_root: Path,
    experiment_id: str,
    *,
    summary: str,
    categories: list[str],
    likely_causes: list[str],
    ruled_out_causes: list[str],
    unknowns: list[str],
    next_actions: list[str],
    comparison_context: dict[str, Any],
    preference_context: dict[str, object],
) -> Path:
    """Prepare an agent-fill request without creating a hollow judgement."""
    path = unit_root / "diagnosis-fill.yaml"
    write_yaml_if_changed(
        path,
        {
            "kind": "experiment_diagnosis_fill",
            "experiment_id": experiment_id,
            "status": "awaiting_agent_fill",
            "summary": summary,
            "categories": categories or ["unknown"],
            "likely_causes": likely_causes,
            "ruled_out_causes": ruled_out_causes,
            "unknowns": unknowns,
            "next_actions": next_actions,
            "comparison_context": comparison_context,
            "preference_context": preference_context,
            "claims": [
                {
                    "id": "diagnosis-claim-001",
                    "text": "",
                    "claim_type": "inference",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [],
                }
            ],
        },
    )
    return path


def list_document_path(unit_root: Path, name: str) -> Path:
    return unit_root / f"{name}.yaml"


def next_numbered_path(root: Path, prefix: str, suffix: str) -> Path:
    index = 1
    while True:
        path = root / f"{prefix}-{index:03d}{suffix}"
        if not path.exists():
            return path
        index += 1


def summarize_yaml_list(path: Path, *, title: str, rows: list[str]) -> None:
    lines = [f"# {title}", ""]
    lines.extend(rows or ["- 暂无条目"])
    write_text_if_changed(path, "\n".join(lines).strip() + "\n")


def sync_run_log_summary(unit_root: Path) -> None:
    payload = load_list_document(list_document_path(unit_root, "run-log"), f"{unit_root.name}-run-log", "experiment-workbench")
    rows = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            f"- `{item.get('id', '')}` · outcome={item.get('outcome', 'unknown')} · "
            f"classification={', '.join(item.get('classifications', [])) or 'unknown'} · "
            f"{item.get('result_summary', '')}"
        )
    summarize_yaml_list(unit_root / "run-log.md", title=f"Run Log: {unit_root.name}", rows=rows)


def sync_follow_up_summary(unit_root: Path) -> None:
    payload = load_list_document(list_document_path(unit_root, "follow-ups"), f"{unit_root.name}-follow-ups", "experiment-workbench")
    rows = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            f"- `{item.get('id', '')}` · status={item.get('status', 'open')} · "
            f"priority={item.get('priority', 'normal')} · category={item.get('category', 'unknown')} · "
            f"{item.get('action', '')}"
        )
    summarize_yaml_list(unit_root / "follow-ups.md", title=f"Follow-ups: {unit_root.name}", rows=rows)


def sync_diagnosis_summary(unit_root: Path) -> None:
    payload = load_list_document(list_document_path(unit_root, "diagnoses"), f"{unit_root.name}-diagnoses", "experiment-workbench")
    lines = [f"# Diagnosis: {unit_root.name}", ""]
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    if not items:
        lines.extend(
            [
                "- 当前最可能原因：待确认",
                "- 更像方法问题 / 实现问题 / 数据问题 / 资源问题：待确认",
                "- 已排除原因：",
                "- 未确认问题：",
                "- 下一步建议：",
            ]
        )
    else:
        for item in items[-5:]:
            lines.extend(
                [
                    f"## {item.get('id', '')} · {item.get('summary', '')}",
                    "",
                    f"- Categories: {', '.join(item.get('categories', [])) or 'unknown'}",
                    f"- Likely causes: {', '.join(item.get('likely_causes', [])) or '待确认'}",
                    f"- Ruled out: {', '.join(item.get('ruled_out_causes', [])) or '无'}",
                    f"- Unknowns: {', '.join(item.get('unknowns', [])) or '无'}",
                    f"- Next actions: {', '.join(item.get('next_actions', [])) or '无'}",
                    f"- Confirmation: `{item.get('confirmation_status', 'pending_user_confirmation')}`",
                    "",
                ]
            )
    write_text_if_changed(unit_root / "diagnosis.md", "\n".join(lines).strip() + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage experiment units in core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--title", required=True)
    plan.add_argument("--program-id", required=True)
    plan.add_argument("--goal", default="")
    plan.add_argument("--idea-id", default="")
    plan.add_argument("--hypothesis", default="")
    plan.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)

    log_run = subparsers.add_parser("log-run")
    log_run.add_argument("--experiment-id", required=True)
    log_run.add_argument("--change", action="append", default=[])
    log_run.add_argument("--metric", action="append", default=[])
    log_run.add_argument("--result-summary", required=True)
    log_run.add_argument("--next-action", action="append", default=[])
    log_run.add_argument("--artifact", action="append", default=[])
    log_run.add_argument("--outcome", default="inconclusive", choices=RUN_OUTCOME_CHOICES)
    log_run.add_argument("--classification", action="append", default=[], choices=CLASSIFICATION_CHOICES)
    log_run.add_argument("--why-this-run", default="")
    log_run.add_argument("--tested-hypothesis", default="")
    log_run.add_argument("--tag", action="append", default=[], choices=RUN_TAG_CHOICES)
    log_run.add_argument("--recent-runs", type=int, default=DEFAULT_RECENT_RUNS)
    log_run.add_argument("--config-revision", required=True)
    log_run.add_argument("--seed", type=int)
    log_run.add_argument("--rerun", action="store_true")
    log_run.add_argument("--rerun-reason", default="")
    log_run.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)

    follow_up = subparsers.add_parser("follow-up")
    follow_up.add_argument("--experiment-id", required=True)
    follow_up.add_argument("--action", required=True)
    follow_up.add_argument("--category", default="unknown", choices=CLASSIFICATION_CHOICES)
    follow_up.add_argument("--priority", default="normal", choices=FOLLOW_UP_PRIORITY_CHOICES)
    follow_up.add_argument("--status", default="open", choices=FOLLOW_UP_STATUS_CHOICES)
    follow_up.add_argument("--evidence-needed", action="append", default=[])
    follow_up.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)

    diagnose = subparsers.add_parser("diagnose")
    diagnose.add_argument("--experiment-id", required=True)
    diagnose.add_argument("--summary", default="Created diagnosis scaffold pending confirmation.")
    diagnose.add_argument("--category", action="append", default=[], choices=CLASSIFICATION_CHOICES)
    diagnose.add_argument("--likely-cause", action="append", default=[])
    diagnose.add_argument("--ruled-out", action="append", default=[])
    diagnose.add_argument("--unknown", action="append", default=[])
    diagnose.add_argument("--next-action", action="append", default=[])
    diagnose.add_argument("--recent-runs", type=int, default=DEFAULT_RECENT_RUNS)
    diagnose.add_argument("--claims-file", default="")
    diagnose.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--experiment-id", required=True)
    add_confirmation_arguments(confirm)
    return parser


def _dispatch(args, root: Path) -> int:
    if args.command == "plan":
        preferences = resolve_experiment_preferences(root, args)
        record = default_record("experiment", title=args.title, maturity="lightweight", source={"original_uri": f"program:{args.program_id}"})
        record["status"] = "planned"
        record["confirmation_status"] = "auto_confirmed"
        record["payload"]["basic_info"]["program_id"] = args.program_id
        record["payload"]["basic_info"]["idea_id"] = args.idea_id
        record["payload"]["basic_info"]["goal"] = args.goal
        record["payload"]["process"]["tested_hypothesis"] = args.hypothesis
        record["program_ids"] = [args.program_id]
        record["summary"] = args.goal or f"Planned experiment: {args.title}"
        _record_experiment_preference_state(record, preferences)
        path = write_record(root, record)
        build_index(root)
        append_program_reporting_event(
            root,
            args.program_id,
            {
                "source_skill": "experiment-workbench",
                "event_type": "experiment-planned",
                "title": args.title,
                "summary": record["summary"],
                "stage": "experiment-design",
                "idea_ids": normalize_list([args.idea_id]),
                "artifacts": [rel(root, path)],
                "tags": ["experiment", "plan"],
            },
            generated_by="experiment-workbench",
        )
        print(path.relative_to(root))
        return 0

    record, path = locate_record(root, args.experiment_id, kind="experiment")
    if record.get("kind") != "experiment":
        raise SystemExit(f"{args.experiment_id} is not an experiment record")
    unit_root = path.parent

    prepared = prepare_experiment_preference_inputs(root, args, record, unit_root)
    preferences = resolve_experiment_preferences(root, args, record, prepared)

    if args.command == "log-run":
        runs_dir = unit_root / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_path = next_numbered_path(runs_dir, "run", ".md")
        run_id = run_path.stem
        run_log_document_path = prepared["run_log_document_path"]
        prior_runs = prepared["prior_runs"]
        metrics = prepared["metrics"]
        claimed_artifacts = prepared["claimed_artifacts"]
        tested_hypothesis = prepared["tested_hypothesis"]
        fingerprint, repeat_group_id = build_run_identity(
            args.experiment_id,
            tested_hypothesis=tested_hypothesis,
            changes=args.change,
            metrics=metrics,
            artifacts=claimed_artifacts,
            config_revision=args.config_revision,
            seed=args.seed,
        )
        duplicate_run_ids = [
            str(item.get("id") or "")
            for item in prior_runs
            if str(item.get("fingerprint") or "") == fingerprint
            and item.get("seed") == args.seed
            and _normalized_text(item.get("config_revision")) == _normalized_text(args.config_revision)
        ]
        if duplicate_run_ids and not args.rerun:
            raise SystemExit(
                "Duplicate experiment configuration and seed already logged; use explicit rerun mode with a reason."
            )
        repeated_runs = [
            str(item.get("id") or "")
            for item in prior_runs
            if str(item.get("repeat_group_id") or "") == repeat_group_id
        ]
        repeat_index = len(repeated_runs) + 1
        repeats_run_ids = [*repeated_runs, run_id]
        comparison = build_run_comparison(metrics, prior_runs, max(args.recent_runs, 0))
        logged_artifacts = [
            generated_artifact(root, run_path),
            generated_artifact(root, run_log_document_path),
            *claimed_artifacts,
        ]
        write_text_if_changed(
            run_path,
            "\n".join(
                [
                    f"# Run for {record.get('title', '')}",
                    "",
                    "## Run Identity",
                    f"- Run ID: {run_id}",
                    f"- Fingerprint: {fingerprint}",
                    f"- Repeat group: {repeat_group_id}",
                    f"- Repeat index: {repeat_index}",
                    f"- Seed: {args.seed if args.seed is not None else 'unspecified'}",
                    f"- Config revision: {_normalized_text(args.config_revision)}",
                    f"- Rerun reason: {_normalized_text(args.rerun_reason) or 'none'}",
                    "",
                    "## Changes",
                    *[f"- {item}" for item in args.change],
                    "",
                    "## Result Summary",
                    f"- {args.result_summary}",
                    "",
                    "## Classification",
                    f"- Outcome: {args.outcome}",
                    *[f"- {item}" for item in normalize_list(args.classification)],
                    "",
                    "## Metrics",
                    *[
                        f"- {metric['name']}={metric['value']} [{metric['unit'] or 'unitless'}] "
                        f"direction={metric['direction']}"
                        for metric in metrics.values()
                    ],
                    "",
                    "## Artifacts",
                    *[f"- {item['path']} · {item['status']}" for item in logged_artifacts],
                    "",
                    "## Next Actions",
                    *[f"- {item}" for item in args.next_action],
                    "",
                ]
            ).strip()
            + "\n",
        )
        run_log_path = append_list_item(
            run_log_document_path,
            f"{args.experiment_id}-run-log",
            "experiment-workbench",
            {
                "id": run_id,
                "fingerprint": fingerprint,
                "repeat_group_id": repeat_group_id,
                "repeat_index": repeat_index,
                "repeats_run_ids": repeats_run_ids,
                "seed": args.seed,
                "config_revision": _normalized_text(args.config_revision),
                "rerun_reason": _normalized_text(args.rerun_reason),
                "result_summary": args.result_summary,
                "outcome": args.outcome,
                "classifications": normalize_list(args.classification) or ["unknown"],
                "changes": normalize_list(args.change),
                "metrics": metrics,
                "why_this_run": args.why_this_run,
                "tested_hypothesis": tested_hypothesis,
                "tags": normalize_list(args.tag),
                "artifacts": logged_artifacts,
                "comparison": comparison,
                "next_actions": normalize_list(args.next_action),
                "information_types": ["fact"],
                "preference_context": experiment_preference_state(preferences),
            },
        )
        sync_run_log_summary(unit_root)
        record["status"] = "running"
        record["payload"]["process"]["change_summary"] = args.change
        record["payload"]["process"]["why_this_run"] = args.why_this_run
        record["payload"]["process"]["tested_hypothesis"] = tested_hypothesis
        record["payload"]["results"]["metrics"] = metrics
        record["payload"]["results"]["comparison"] = comparison
        record["payload"]["results"]["artifacts"] = logged_artifacts
        record["payload"]["results"]["met_expectation"] = "yes" if args.outcome == "success" else ("no" if args.outcome in {"failed", "blocked"} else "unknown")
        record["payload"]["results"]["abnormalities"] = normalize_list(args.classification)
        record["payload"]["diagnosis"]["next_actions"] = args.next_action
        record["summary"] = args.result_summary
        _record_experiment_preference_state(record, preferences)
        record.setdefault("artifacts", [])
        for artifact in [rel(root, run_path), rel(root, run_log_path)]:
            if artifact not in record["artifacts"]:
                record["artifacts"].append(artifact)
        append_history(record, action="experiment-run-logged", summary=args.result_summary, information_types=["fact"], artifacts=[rel(root, run_path), rel(root, run_log_path)])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-run",
                    "title": record.get("title", args.experiment_id),
                    "summary": args.result_summary,
                    "stage": "experiment-running",
                    "artifacts": [rel(root, run_path), rel(root, run_log_path)],
                    "tags": ["experiment", "run", args.outcome, *(normalize_list(args.classification) or ["unknown"])],
                },
                generated_by="experiment-workbench",
            )
        print(run_path.relative_to(root))
        return 0

    if args.command == "follow-up":
        follow_up_path = append_list_item(
            list_document_path(unit_root, "follow-ups"),
            f"{args.experiment_id}-follow-ups",
            "experiment-workbench",
            {
                "action": args.action,
                "category": args.category,
                "priority": args.priority,
                "status": args.status,
                "evidence_needed": normalize_list(args.evidence_needed),
                "information_types": ["fact", "unverified"],
                "preference_context": experiment_preference_state(preferences),
            },
        )
        sync_follow_up_summary(unit_root)
        record["payload"]["diagnosis"]["next_actions"] = normalize_list(record["payload"]["diagnosis"].get("next_actions", [])) + [args.action]
        _record_experiment_preference_state(record, preferences)
        append_history(record, action="experiment-follow-up-added", summary=args.action, information_types=["fact", "unverified"], artifacts=[rel(root, follow_up_path)])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-follow-up",
                    "title": record.get("title", args.experiment_id),
                    "summary": args.action,
                    "stage": "experiment-follow-up",
                    "artifacts": [rel(root, follow_up_path)],
                    "tags": ["experiment", "follow-up", args.category, args.status],
                },
                generated_by="experiment-workbench",
            )
        print(follow_up_path.relative_to(root))
        return 0

    if args.command == "diagnose":
        runs = prepared["runs"]
        comparison_context = build_diagnosis_context(runs, max(args.recent_runs, 0))
        claims = load_diagnosis_claims(root, unit_root, args.experiment_id, args.claims_file)
        if diagnosis_claims_file_fact(root, args.claims_file) != prepared["claims_file_fact"]:
            raise SystemExit("Diagnosis claims changed while preparing the diagnosis; retry with current claims.")
        if not claims:
            fill_path = write_diagnosis_fill_scaffold(
                unit_root,
                args.experiment_id,
                summary=args.summary,
                categories=normalize_list(args.category),
                likely_causes=normalize_list(args.likely_cause),
                ruled_out_causes=normalize_list(args.ruled_out),
                unknowns=normalize_list(args.unknown),
                next_actions=normalize_list(args.next_action),
                comparison_context=comparison_context,
                preference_context=experiment_preference_state(preferences),
            )
            print(fill_path.relative_to(root))
            return 0
        diagnosis_path = append_list_item(
            list_document_path(unit_root, "diagnoses"),
            f"{args.experiment_id}-diagnoses",
            "experiment-workbench",
            {
                "summary": args.summary,
                "categories": normalize_list(args.category) or ["unknown"],
                "likely_causes": normalize_list(args.likely_cause),
                "ruled_out_causes": normalize_list(args.ruled_out),
                "unknowns": normalize_list(args.unknown),
                "next_actions": normalize_list(args.next_action),
                "comparison_context": comparison_context,
                "claims": claims,
                "confirmation_status": "pending_user_confirmation",
                "information_types": ["inference", "evaluation", "unverified"],
                "preference_context": experiment_preference_state(preferences),
            },
        )
        sync_diagnosis_summary(unit_root)
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        record["payload"]["diagnosis"]["failure_modes"] = normalize_list(args.category) or ["unknown"]
        record["payload"]["diagnosis"]["likely_causes"] = normalize_list(args.likely_cause)
        record["payload"]["diagnosis"]["ruled_out_causes"] = normalize_list(args.ruled_out)
        record["payload"]["diagnosis"]["unknowns"] = normalize_list(args.unknown)
        record["payload"]["diagnosis"]["next_actions"] = normalize_list(args.next_action)
        record["payload"]["diagnosis"]["comparison_context"] = comparison_context
        record["payload"]["diagnosis"]["claims"] = claims
        _record_experiment_preference_state(record, preferences)
        record["payload"].pop("claims", None)
        record["payload"].pop("verification", None)
        if claims:
            attach_claims(record["payload"], claims)
            build_verification_receipt(record, unit_root)
        append_history(record, action="experiment-diagnosed", summary=args.summary, information_types=["inference", "evaluation", "unverified"], artifacts=[rel(root, diagnosis_path), rel(root, unit_root / "diagnosis.md")])
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-diagnosis",
                    "title": record.get("title", args.experiment_id),
                    "summary": args.summary,
                    "unit_id": args.experiment_id,
                    "stage": "experiment-diagnosis",
                    "artifacts": [rel(root, diagnosis_path), rel(root, unit_root / "diagnosis.md")],
                    "tags": ["experiment", "diagnosis", *(normalize_list(args.category) or ["unknown"])],
                    "epistemic_type": "judgement",
                    "information_types": ["inference", "evaluation", "unverified"],
                    "confirmation_status": "pending_user_confirmation",
                    "confirmation_binding": confirmation_binding(
                        record,
                        owner="experiment-workbench",
                        path=rel(root, path),
                    ),
                },
                generated_by="experiment-workbench",
            )
        print(diagnosis_path.relative_to(root))
        return 0

    if args.command == "confirm":
        require_current_experiment_preference_state(
            root,
            record,
            operation="diagnose",
        )
        record = confirm_unit(
            record,
            "experiment",
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
            method="experiment.py confirm",
            project_root=root,
        )
        write_record(root, record)
        build_index(root)
        program_id = str(record.get("payload", {}).get("basic_info", {}).get("program_id") or "").strip()
        if program_id:
            binding = confirmation_binding(
                record,
                owner="experiment-workbench",
                path=rel(root, path),
            )
            append_program_reporting_event(
                root,
                program_id,
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-confirmed",
                    "title": record.get("title", args.experiment_id),
                    "summary": "Experiment findings confirmed by user.",
                    "stage": "experiment-confirmed",
                    "artifacts": [rel(root, path)],
                    "tags": ["experiment", "confirmed"],
                    "epistemic_type": "judgement",
                    "information_types": ["inference", "evaluation"],
                    "confirmation_status": "confirmed",
                    "confirmation_binding": binding,
                },
                generated_by="experiment-workbench",
            )
        print(f"[ok] confirmed {args.experiment_id}")
        return 0
    return 1


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_workspace(root)
    with command_mutation(
        root,
        f"experiment-workbench:{args.command}",
        _experiment_command_targets(args, root),
    ):
        return _dispatch(args, root)


if __name__ == "__main__":
    raise SystemExit(main())

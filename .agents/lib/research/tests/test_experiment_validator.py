from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed


def _experiment_module():
    project_root = Path(__file__).resolve().parents[4]
    script = project_root / ".agents" / "skills" / "experiment-workbench" / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_workbench_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_experiment(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[4]
    script = project_root / ".agents" / "skills" / "experiment-workbench" / "scripts" / "experiment.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def test_typed_metric_parses_value_unit_and_direction() -> None:
    module = _experiment_module()

    metrics = module.parse_metrics(["success_rate=0.82[ratio]:higher-better"])

    assert metrics == {
        "success_rate": {
            "name": "success_rate",
            "value": 0.82,
            "unit": "ratio",
            "direction": "higher-better",
        }
    }


def test_bare_metric_remains_backward_compatible(capsys) -> None:
    module = _experiment_module()

    metrics = module.parse_metrics(["loss=1.25", "status=converged"])

    assert metrics["loss"]["value"] == 1.25
    assert metrics["loss"]["unit"] == ""
    assert metrics["loss"]["direction"] == "unknown"
    assert metrics["status"]["value"] == "converged"
    assert "preserving it as a string" in capsys.readouterr().err


def test_artifact_existence_is_recorded(tmp_path: Path, capsys) -> None:
    module = _experiment_module()
    existing = tmp_path / "checkpoint.pt"
    existing.write_text("weights", encoding="utf-8")

    artifacts = module.verify_artifacts(tmp_path, ["checkpoint.pt", "missing.log"])

    assert artifacts == [
        {"path": "checkpoint.pt", "status": "present", "generated": False, "kind": "file"},
        {"path": "missing.log", "status": "missing", "generated": False},
    ]
    assert "artifact does not exist: missing.log" in capsys.readouterr().err


def test_baseline_comparison_is_direction_aware() -> None:
    module = _experiment_module()
    baseline = {
        "id": "run-001",
        "tags": ["baseline"],
        "metrics": module.parse_metrics(["success_rate=0.70[ratio]:higher-better"]),
    }
    current = module.parse_metrics(["success_rate=0.82[ratio]:higher-better"])

    comparison = module.build_run_comparison(current, [baseline], 5)

    assert comparison[0]["last_run"]["delta"] == 0.12
    assert comparison[0]["last_run"]["directional_result"] == "better"
    assert comparison[0]["anchors"][0]["run_id"] == "run-001"


def test_bare_current_metric_inherits_anchor_direction() -> None:
    module = _experiment_module()
    baseline = {
        "id": "run-001",
        "tags": ["baseline"],
        "metrics": module.parse_metrics(["loss=2.0:lower-better"]),
    }

    comparison = module.build_run_comparison(module.parse_metrics(["loss=1.5"]), [baseline], 5)

    assert comparison[0]["anchors"][0]["directional_result"] == "better"


def test_diagnosis_context_contains_recent_runs_and_persistent_anchors() -> None:
    module = _experiment_module()
    runs = [
        {"id": "run-001", "tags": ["baseline"], "metrics": {"loss": "2.0"}},
        {"id": "run-002", "metrics": {"loss": "1.5"}},
        {"id": "run-003", "tags": ["milestone"], "metrics": {"loss": "1.0"}},
    ]

    context = module.build_diagnosis_context(runs, 1)

    assert [run["run_id"] for run in context["recent_runs"]] == ["run-003"]
    assert [run["run_id"] for run in context["anchors"]] == ["run-001", "run-003"]
    assert context["anchors"][0]["metrics"]["loss"]["value"] == 2.0


def test_diagnosis_claim_verifies_verbatim_run_evidence_and_rejects_fabrication(tmp_path: Path) -> None:
    _run_experiment(tmp_path, "plan", "--title", "grounded diagnosis", "--program-id", "program-test")
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    _run_experiment(
        tmp_path,
        "log-run",
        "--experiment-id",
        experiment_id,
        "--result-summary",
        "Observed validation loss spike after the data refresh.",
        "--outcome",
        "failed",
        "--classification",
        "data",
    )
    claims_path = tmp_path / "diagnosis-claims.yaml"
    claim = {
        "id": "diagnosis-data-refresh",
        "text": "The data refresh likely caused the validation regression.",
        "claim_type": "inference",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": experiment_id,
                "artifact": "runs/run-001.md",
                "locator": "Result Summary",
                "quote": "Observed validation loss spike after the data refresh.",
                "summary": "The run records the regression immediately after the refresh.",
            }
        ],
    }
    write_yaml_if_changed(claims_path, {"claims": [claim]})

    _run_experiment(
        tmp_path,
        "diagnose",
        "--experiment-id",
        experiment_id,
        "--summary",
        "Data refresh regression diagnosis",
        "--category",
        "data",
        "--claims-file",
        str(claims_path),
    )

    diagnoses = load_yaml(record_path.parent / "diagnoses.yaml")
    assert diagnoses["items"][-1]["claims"] == [claim]
    assert diagnoses["items"][-1]["confirmation_status"] == "pending_user_confirmation"

    fabricated_claim = dict(claim)
    fabricated_claim["id"] = "diagnosis-fabricated"
    fabricated_claim["evidence_refs"] = [dict(claim["evidence_refs"][0], quote="Fabricated loss explanation.")]
    write_yaml_if_changed(claims_path, {"claims": [fabricated_claim]})
    rejected = _run_experiment(
        tmp_path,
        "diagnose",
        "--experiment-id",
        experiment_id,
        "--summary",
        "Fabricated diagnosis",
        "--category",
        "data",
        "--claims-file",
        str(claims_path),
        check=False,
    )

    assert rejected.returncode != 0
    assert "not verbatim in artifact 'runs/run-001.md'" in rejected.stderr
    assert len(load_yaml(record_path.parent / "diagnoses.yaml")["items"]) == 1


def test_experiment_validator_lifecycle(tmp_path: Path) -> None:
    _run_experiment(tmp_path, "plan", "--title", "validator lifecycle", "--program-id", "program-test")
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    record = load_yaml(record_path)
    experiment_id = record["id"]
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_text("weights", encoding="utf-8")

    baseline = _run_experiment(
        tmp_path,
        "log-run",
        "--experiment-id",
        experiment_id,
        "--result-summary",
        "baseline",
        "--metric",
        "success_rate=0.70[ratio]:higher-better",
        "--artifact",
        "checkpoint.pt",
        "--artifact",
        "missing.log",
        "--tag",
        "baseline",
    )
    assert "artifact does not exist: missing.log" in baseline.stderr
    _run_experiment(
        tmp_path,
        "log-run",
        "--experiment-id",
        experiment_id,
        "--result-summary",
        "improved",
        "--metric",
        "success_rate=0.82[ratio]:higher-better",
    )
    claims_path = record_path.parent / "diagnosis-claims.yaml"
    write_yaml_if_changed(
        claims_path,
        {
            "claims": [
                {
                    "id": "claim-diagnosis-improved",
                    "text": "The latest run improved success rate.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": experiment_id,
                            "artifact": "run-log.yaml",
                            "locator": "run=latest",
                            "quote": "improved",
                        }
                    ],
                }
            ]
        },
    )
    _run_experiment(
        tmp_path,
        "diagnose",
        "--experiment-id",
        experiment_id,
        "--summary",
        "Agent-authored evaluation",
        "--category",
        "evaluation",
        "--recent-runs",
        "1",
        "--claims-file",
        str(claims_path),
    )

    record = load_yaml(record_path)
    run_log = load_yaml(record_path.parent / "run-log.yaml")
    diagnoses = load_yaml(record_path.parent / "diagnoses.yaml")
    comparison = record["payload"]["results"]["comparison"][0]
    assert comparison["last_run"]["delta"] == 0.12
    assert comparison["anchors"][0]["directional_result"] == "better"
    assert run_log["items"][0]["artifacts"][-2]["status"] == "present"
    assert run_log["items"][0]["artifacts"][-1]["status"] == "missing"
    context = diagnoses["items"][-1]["comparison_context"]
    assert diagnoses["items"][-1]["claims"][0]["id"] == "claim-diagnosis-improved"
    assert [item["run_id"] for item in context["recent_runs"]] == [run_log["items"][-1]["id"]]
    assert [item["run_id"] for item in context["anchors"]] == [run_log["items"][0]["id"]]
    assert context["anchors"][0]["artifacts"][-1]["status"] == "missing"

    evidence = str((record_path.parent / "run-log.yaml").relative_to(tmp_path))
    _run_experiment(
        tmp_path,
        "confirm",
        "--experiment-id",
        experiment_id,
        "--confirmed-by",
        "human-reviewer",
        "--evidence",
        evidence,
        "--user-authorization",
        "I confirm this experiment diagnosis.",
        "--authorization-source",
        "user_message",
    )
    assert load_yaml(record_path)["confirmation_status"] == "confirmed"

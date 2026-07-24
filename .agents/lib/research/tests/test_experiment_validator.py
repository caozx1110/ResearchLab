from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed
from research.paths import config_root


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


def _run_report(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[4]
    script = project_root / ".agents" / "skills" / "report-author" / "scripts" / "report.py"
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _markdown_section(text: str, heading: str) -> str:
    start = text.index(heading)
    next_heading = text.find("\n## ", start + len(heading))
    return text[start : next_heading if next_heading >= 0 else len(text)]


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


def test_run_fingerprint_excludes_observed_values_and_normalizes_change_order() -> None:
    module = _experiment_module()
    first, first_group = module.build_run_identity(
        "experiment-a",
        tested_hypothesis="  stable   hypothesis ",
        changes=["beta = 2", "alpha = 1"],
        metrics=module.parse_metrics(["loss=2.0[ratio]:lower-better"]),
        artifacts=[{"path": "outputs/checkpoint.pt"}],
        config_revision="rev-1",
        seed=7,
    )
    second, second_group = module.build_run_identity(
        "experiment-a",
        tested_hypothesis="stable hypothesis",
        changes=["alpha = 1", "beta = 2"],
        metrics=module.parse_metrics(["loss=0.5[ratio]:lower-better"]),
        artifacts=[{"path": "outputs/checkpoint.pt"}],
        config_revision="rev-1",
        seed=19,
    )

    assert first == second
    assert first_group == second_group


def test_duplicate_run_requires_reasoned_rerun_and_seed_forms_repeat_group(tmp_path: Path) -> None:
    _run_experiment(tmp_path, "plan", "--title", "fingerprinted", "--program-id", "program-test")
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    base_args = (
        "log-run",
        "--experiment-id",
        experiment_id,
        "--tested-hypothesis",
        "A deterministic hypothesis",
        "--change",
        "optimizer=adam",
        "--metric",
        "loss=1.0[ratio]:lower-better",
        "--config-revision",
        "config-rev-a",
        "--seed",
        "11",
    )
    _run_experiment(tmp_path, *base_args, "--result-summary", "first observation")

    duplicate = _run_experiment(
        tmp_path,
        *base_args,
        "--result-summary",
        "different observed value does not change identity",
        check=False,
    )
    assert duplicate.returncode != 0
    assert "Duplicate experiment configuration and seed" in duplicate.stderr
    no_reason = _run_experiment(
        tmp_path,
        *base_args,
        "--result-summary",
        "retry",
        "--rerun",
        check=False,
    )
    assert no_reason.returncode != 0
    assert "non-empty rerun reason" in no_reason.stderr
    _run_experiment(
        tmp_path,
        *base_args,
        "--result-summary",
        "reasoned retry",
        "--rerun",
        "--rerun-reason",
        "worker preemption",
    )
    _run_experiment(
        tmp_path,
        *base_args[:-1],
        "12",
        "--result-summary",
        "second seed",
    )

    items = load_yaml(record_path.parent / "run-log.yaml")["items"]
    assert [item["id"] for item in items] == ["run-001", "run-002", "run-003"]
    assert items[0]["fingerprint"] == items[1]["fingerprint"]
    assert items[2]["fingerprint"] == items[0]["fingerprint"]
    assert len({item["repeat_group_id"] for item in items}) == 1
    assert [item["repeat_index"] for item in items] == [1, 2, 3]
    assert items[1]["rerun_reason"] == "worker preemption"
    assert items[2]["repeats_run_ids"] == ["run-001", "run-002", "run-003"]


def test_concurrent_runs_allocate_unique_monotonic_ids(tmp_path: Path) -> None:
    _run_experiment(tmp_path, "plan", "--title", "concurrent runs", "--program-id", "program-test")
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    project_root = Path(__file__).resolve().parents[4]
    script = project_root / ".agents" / "skills" / "experiment-workbench" / "scripts" / "experiment.py"
    commands = [
        [
            sys.executable,
            str(script),
            "--root",
            str(tmp_path),
            "log-run",
            "--experiment-id",
            experiment_id,
            "--result-summary",
            f"seed {seed}",
            "--tested-hypothesis",
            "concurrency",
            "--config-revision",
            "config-rev-concurrent",
            "--seed",
            str(seed),
        ]
        for seed in (21, 22)
    ]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in commands]
    results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]

    assert [returncode for _, _, returncode in results] == [0, 0], results
    items = load_yaml(record_path.parent / "run-log.yaml")["items"]
    assert [item["id"] for item in items] == ["run-001", "run-002"]
    assert sorted(path.name for path in (record_path.parent / "runs").glob("run-*.md")) == ["run-001.md", "run-002.md"]


def test_run_rejects_artifact_outside_project_before_write(tmp_path: Path) -> None:
    _run_experiment(tmp_path, "plan", "--title", "contained artifact", "--program-id", "program-test")
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    rejected = _run_experiment(
        tmp_path,
        "log-run",
        "--experiment-id",
        experiment_id,
        "--result-summary",
        "outside",
        "--artifact",
        str(tmp_path.parent / "outside.pt"),
        "--config-revision",
        "config-v1",
        check=False,
    )

    assert rejected.returncode != 0
    assert "must remain inside the project workspace" in rejected.stderr
    assert not (record_path.parent / "run-log.yaml").exists()


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
        "--config-revision",
        "config-v1",
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


def test_reports_isolate_pending_diagnoses_and_require_current_receipt_for_judgement_progress(tmp_path: Path) -> None:
    program_id = "program-report-epistemics"
    run_summary = "Observed validation loss spike after the data refresh."
    pending_summary = "The failure was caused by dataset corruption."
    confirmed_summary = "The data refresh likely caused the validation regression."
    _run_experiment(tmp_path, "plan", "--title", "report epistemics", "--program-id", program_id)
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    _run_experiment(
        tmp_path,
        "log-run",
        "--experiment-id",
        experiment_id,
        "--result-summary",
        run_summary,
        "--outcome",
        "failed",
        "--classification",
        "data",
        "--config-revision",
        "config-v1",
    )
    claims_path = record_path.parent / "diagnosis-claims.yaml"
    pending_claim = {
        "id": "claim-pending-diagnosis",
        "text": pending_summary,
        "claim_type": "inference",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": experiment_id,
                "artifact": "runs/run-001.md",
                "locator": "Result Summary",
                "quote": run_summary,
            }
        ],
    }
    write_yaml_if_changed(claims_path, {"claims": [pending_claim]})
    _run_experiment(
        tmp_path,
        "diagnose",
        "--experiment-id",
        experiment_id,
        "--summary",
        pending_summary,
        "--category",
        "data",
        "--claims-file",
        str(claims_path),
    )

    _run_report(tmp_path, "weekly", "--program-id", program_id)
    report_path = tmp_path / "kb" / "programs" / program_id / "reports" / "weekly.md"
    pending_report = report_path.read_text(encoding="utf-8")
    ordinary_section = _markdown_section(pending_report, "## Reporting Events")
    pending_section = _markdown_section(pending_report, "## Pending / Unverified judgements")
    assert run_summary in ordinary_section
    assert pending_summary not in ordinary_section
    assert "PENDING / UNVERIFIED JUDGEMENT" in pending_section
    assert pending_summary in pending_section
    assert "missing: current ConfirmationReceipt" in pending_section

    events_path = tmp_path / "kb" / "programs" / program_id / "workflow" / "reporting-events.yaml"
    diagnosis_events = [
        item
        for item in load_yaml(events_path)["items"]
        if item.get("event_type") == "experiment-diagnosis"
    ]
    pending_event = diagnosis_events[-1]
    assert pending_event["epistemic_type"] == "judgement"
    assert pending_event["information_types"] == ["inference", "evaluation", "unverified"]
    assert pending_event["confirmation_status"] == "pending_user_confirmation"
    pending_binding = pending_event["confirmation_binding"]
    assert pending_binding["subject"]["kind"] == "experiment"
    assert pending_binding["subject"]["id"] == experiment_id
    assert pending_binding["subject"]["owner"] == "experiment-workbench"
    assert pending_binding["claim_ids"] == [pending_claim["id"]]
    assert len(pending_binding["content_digest"]) == 64
    assert all(pending_binding["verification"].values())

    claim = {
        "id": "claim-current-diagnosis",
        "text": confirmed_summary,
        "claim_type": "inference",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": experiment_id,
                "artifact": "runs/run-001.md",
                "locator": "Result Summary",
                "quote": run_summary,
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
        confirmed_summary,
        "--category",
        "data",
        "--claims-file",
        str(claims_path),
    )
    _run_experiment(
        tmp_path,
        "confirm",
        "--experiment-id",
        experiment_id,
        "--confirmed-by",
        "human-reviewer",
        "--evidence",
        str((record_path.parent / "run-log.yaml").relative_to(tmp_path)),
        "--user-authorization",
        "I confirm this experiment diagnosis.",
        "--authorization-source",
        "user_message",
    )
    _run_report(tmp_path, "weekly", "--program-id", program_id)
    confirmed_report = report_path.read_text(encoding="utf-8")
    ordinary_section = _markdown_section(confirmed_report, "## Reporting Events")
    pending_section = _markdown_section(confirmed_report, "## Pending / Unverified judgements")
    assert run_summary in ordinary_section
    assert confirmed_summary in ordinary_section
    assert "confirmation: current receipt" in ordinary_section
    assert confirmed_summary not in pending_section
    assert pending_summary in pending_section

    diagnosis_events = [
        item
        for item in load_yaml(events_path)["items"]
        if item.get("event_type") == "experiment-diagnosis"
    ]
    binding = diagnosis_events[-1]["confirmation_binding"]
    confirmed_record = load_yaml(record_path)
    assert binding["claim_ids"] == [claim["id"]]
    assert binding["content_digest"] == confirmed_record["confirmation"]["content_digest"]
    assert binding["verification"] == {
        key: confirmed_record["payload"]["verification"][key]
        for key in ("verified_at", "claims_digest", "evidence_digest")
    }


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
        "--config-revision",
        "config-v1",
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
        "--config-revision",
        "config-v2",
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


def test_experiment_confirmation_rejects_hard_preference_change(tmp_path: Path) -> None:
    _run_experiment(tmp_path, "plan", "--title", "preference freshness", "--program-id", "program-test")
    record_path = next((tmp_path / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    _run_experiment(
        tmp_path,
        "log-run",
        "--experiment-id",
        experiment_id,
        "--result-summary",
        "observed failure",
        "--config-revision",
        "config-v1",
    )
    claims_path = record_path.parent / "diagnosis-claims.yaml"
    write_yaml_if_changed(
        claims_path,
        {
            "claims": [
                {
                    "id": "claim-preference-freshness",
                    "text": "The run recorded an observed failure.",
                    "claim_type": "inference",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": experiment_id,
                            "artifact": "run-log.yaml",
                            "locator": "run=latest",
                            "quote": "observed failure",
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
        "preference-bound diagnosis",
        "--category",
        "unknown",
        "--claims-file",
        str(claims_path),
    )
    before = record_path.read_bytes()
    write_yaml_if_changed(
        config_root(tmp_path) / "user-profile.yaml",
        {"constraints": ["new offline-only boundary"]},
    )

    result = _run_experiment(
        tmp_path,
        "confirm",
        "--experiment-id",
        experiment_id,
        "--confirmed-by",
        "human-reviewer",
        "--evidence",
        str((record_path.parent / "run-log.yaml").relative_to(tmp_path)),
        "--user-authorization",
        "I confirm this experiment diagnosis.",
        "--authorization-source",
        "user_message",
        check=False,
    )

    assert result.returncode != 0
    assert "hard preferences changed" in result.stderr
    assert record_path.read_bytes() == before

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.evidence import build_verification_receipt
from research.judgements import confirmation_binding, discover_pending_judgements


ROOT = Path(__file__).resolve().parents[4]


def _run(script: str, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), "--root", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _report_module():
    path = ROOT / ".agents/skills/report-author/scripts/report.py"
    spec = importlib.util.spec_from_file_location("r2_report_module", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_claims_prepare_fill_files_without_hollow_judgements(tmp_path: Path) -> None:
    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "init-program",
        "--program-id",
        "p-r2",
        "--question",
        "Which route?",
        "--goal",
        "Choose a grounded route",
    )
    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "log-decision",
        "--program-id",
        "p-r2",
        "--decision",
        "Use route A",
    )
    workflow = tmp_path / "kb/programs/p-r2/workflow"
    assert load_yaml(workflow / "decision-fill.yaml")["status"] == "awaiting_agent_fill"
    assert load_yaml(workflow / "decisions.yaml")["items"] == []

    _run(
        ".agents/skills/experiment-workbench/scripts/experiment.py",
        tmp_path,
        "plan",
        "--title",
        "R2 experiment",
        "--program-id",
        "p-r2",
    )
    record_path = next((tmp_path / "kb/units/experiments").glob("*/record.yaml"))
    experiment_id = load_yaml(record_path)["id"]
    _run(
        ".agents/skills/experiment-workbench/scripts/experiment.py",
        tmp_path,
        "diagnose",
        "--experiment-id",
        experiment_id,
        "--summary",
        "Likely data issue",
    )
    assert load_yaml(record_path.parent / "diagnosis-fill.yaml")["status"] == "awaiting_agent_fill"
    assert not (record_path.parent / "diagnoses.yaml").exists()


def test_discovery_requires_current_verification_and_supports_side_artifacts(tmp_path: Path) -> None:
    program_root = tmp_path / "kb/programs/p-r2"
    design_root = program_root / "design"
    design_root.mkdir(parents=True)
    evidence_path = program_root / "evidence.md"
    evidence_path.write_text("route A has the strongest benchmark", encoding="utf-8")
    artifact_path = design_root / "i-r2-repo-choice.yaml"
    artifact = {
        "id": "method-selection:p-r2:i-r2",
        "kind": "method_selection",
        "owner": "method-designer",
        "program_id": "p-r2",
        "updated_at": "2026-07-23T00:00:00+00:00",
        "priority": "high",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "unverified"],
        "payload": {
            "claims": [
                {
                    "id": "claim-route-a",
                    "text": "Route A is the best current baseline.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "program:p-r2",
                            "artifact": "evidence.md",
                            "locator": "benchmark",
                            "quote": "route A has the strongest benchmark",
                        }
                    ],
                }
            ]
        },
        "review_route": {"owner": "method-designer", "action": "confirm-selection"},
    }
    build_verification_receipt(
        artifact,
        design_root,
        source_roots={"program:p-r2": program_root},
    )
    write_yaml_if_changed(artifact_path, artifact)

    cards = discover_pending_judgements(tmp_path)
    assert [card["subject"]["id"] for card in cards] == [artifact["id"]]
    assert cards[0]["subject"]["path"] == "kb/programs/p-r2/design/i-r2-repo-choice.yaml"

    evidence_path.write_text("route B superseded the old benchmark", encoding="utf-8")
    assert discover_pending_judgements(tmp_path) == []


def test_report_fail_closed_for_decision_unknown_and_stale_confirmation(tmp_path: Path) -> None:
    report = _report_module()
    workflow = tmp_path / "kb/programs/p-r2/workflow"
    workflow.mkdir(parents=True)
    events = [
        {"event_type": "decision", "summary": "Choose route A"},
        {"event_type": "mystery-update", "summary": "An untyped assertion"},
        {"event_type": "experiment-run", "summary": "Run 7 completed"},
    ]
    ordinary, pending = report.partition_reporting_events(tmp_path, events)
    assert [event["summary"] for event in ordinary] == ["Run 7 completed"]
    assert [event["summary"] for event in pending] == ["Choose route A", "An untyped assertion"]

    evidence_path = workflow / "decision-evidence.md"
    evidence_path.write_text("benchmark supports route A", encoding="utf-8")
    decision = {
        "id": "decision-r2",
        "kind": "program_decision",
        "program_id": "p-r2",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "unverified"],
        "payload": {
            "decision": {"text": "Choose route A"},
            "claims": [
                {
                    "id": "decision-claim-r2",
                    "text": "Route A is preferred.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "program:p-r2",
                            "artifact": "workflow/decision-evidence.md",
                            "locator": "benchmark",
                            "quote": "benchmark supports route A",
                        }
                    ],
                }
            ],
        },
    }
    roots = {"program:p-r2": tmp_path / "kb/programs/p-r2"}
    build_verification_receipt(decision, tmp_path / "kb/programs/p-r2", source_roots=roots)
    apply_confirmation(
        decision,
        confirmed_by="Human Reviewer",
        evidence=["kb/programs/p-r2/workflow/decision-evidence.md"],
        user_authorization="I confirm route A.",
        authorization_source="user_message",
        project_root=tmp_path,
        verification_root=tmp_path / "kb/programs/p-r2",
        trusted_source_roots=roots,
    )
    decisions_path = workflow / "decisions.yaml"
    write_yaml_if_changed(decisions_path, {"items": [decision]})
    event = {
        "event_type": "decision-confirmed",
        "summary": "Choose route A",
        "epistemic_type": "judgement",
        "confirmation_status": "confirmed",
        "confirmation_binding": confirmation_binding(
            decision,
            owner="research-orchestrator",
            path="kb/programs/p-r2/workflow/decisions.yaml",
        ),
    }
    ordinary, pending = report.partition_reporting_events(tmp_path, [event])
    assert len(ordinary) == 1 and pending == []

    decision["payload"]["claims"][0]["text"] = "Route B is preferred."
    write_yaml_if_changed(decisions_path, {"items": [decision]})
    ordinary, pending = report.partition_reporting_events(tmp_path, [event])
    assert ordinary == [] and len(pending) == 1
    assert "stale" in pending[0]["_epistemic_reason"]


def test_discussion_archive_is_explicitly_pending_until_migrated(tmp_path: Path) -> None:
    _run(
        ".agents/skills/discussion-archivist/scripts/archive.py",
        tmp_path,
        "archive",
        "--program-id",
        "p-r2",
        "--title",
        "Route tradeoff",
        "--summary",
        "Route A may be preferable.",
        "--decision",
        "Use route A",
    )
    note = tmp_path / "kb/programs/p-r2/discussions/route-tradeoff.md"
    assert "Pending / Unverified judgement" in note.read_text(encoding="utf-8")
    events = load_yaml(tmp_path / "kb/programs/p-r2/workflow/reporting-events.yaml")["items"]
    event = events[-1]
    assert event["event_type"] == "discussion-conclusion"
    assert event["governance_status"] == "needs_agent_repair"
    ordinary, pending = _report_module().partition_reporting_events(tmp_path, [event])
    assert ordinary == [] and len(pending) == 1

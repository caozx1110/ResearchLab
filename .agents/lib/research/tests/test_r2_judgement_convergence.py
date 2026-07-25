from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.core import default_record, record_path
from research.evidence import build_verification_receipt, confirmation_content_digest
from research.judgements import (
    confirmation_binding,
    discover_pending_judgements,
    judgement_snapshot_binding,
    load_bound_judgement_snapshot,
    require_judgement_snapshot,
)
from research.paths import runtime_preferences_path


ROOT = Path(__file__).resolve().parents[4]


def test_bound_unit_judgement_snapshot_rejects_same_bytes_directory_replacement(
    tmp_path: Path,
) -> None:
    unit_id = "p-bound-directory-replacement"
    path = record_path(tmp_path, "paper", unit_id)
    path.parent.mkdir(parents=True)
    record = default_record("paper", title="Bound paper", maturity="complete")
    record["id"] = unit_id
    write_yaml_if_changed(path, record)

    subject = {
        "kind": "paper",
        "id": unit_id,
        "owner": "paper-analyst",
        "path": f"kb/units/papers/{unit_id}/record.yaml",
    }
    bound = load_bound_judgement_snapshot(tmp_path, subject)
    assert bound.unit_record_snapshot is not None
    assert bound.record["id"] == unit_id
    assert bound.is_current()

    original_bytes = path.read_bytes()
    displaced = tmp_path / "displaced-unit"
    path.parent.rename(displaced)
    path.parent.mkdir()
    path.write_bytes(original_bytes)

    assert not bound.is_current()
    assert load_bound_judgement_snapshot(tmp_path, subject).is_current()


def _run(script: str, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), "--root", str(root), *args],
        check=check,
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


def test_side_judgement_content_digest_binds_domain_substance() -> None:
    method = {
        "kind": "method_selection",
        "payload": {
            "method_selection": {"proposed_repo_id": "r-a", "selected_repo_id": "r-a"},
            "claims": [],
        },
    }
    before = confirmation_content_digest(method)
    method["payload"]["method_selection"]["selected_repo_id"] = "r-b"
    assert confirmation_content_digest(method) != before

    discussion = {
        "kind": "idea_discussion_conclusion",
        "payload": {
            "discussion_conclusion": {"text": "Keep the current boundary.", "reviewer": "runtime-agent"},
            "claims": [],
        },
    }
    before = confirmation_content_digest(discussion)
    discussion["payload"]["discussion_conclusion"]["text"] = "Change the boundary."
    assert confirmation_content_digest(discussion) != before


def test_review_snapshot_binding_rejects_terminal_status_change() -> None:
    record = {
        "id": "p-status-bound",
        "kind": "paper",
        "confirmation_status": "pending_user_confirmation",
        "payload": {"core_content": {"research_problem": "A factual review subject."}, "claims": []},
    }
    expected = judgement_snapshot_binding(
        record,
        owner="knowledge-base-manager",
        path="kb/units/papers/p-status-bound/record.yaml",
    )
    record["confirmation_status"] = "confirmed"
    with pytest.raises(ValueError, match="stale"):
        require_judgement_snapshot(
            record,
            expected_snapshot=expected,
            owner="knowledge-base-manager",
            path="kb/units/papers/p-status-bound/record.yaml",
        )


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
        "idea_id": "i-r2",
        "updated_at": "2026-07-23T00:00:00+00:00",
        "priority": "high",
        "proposed_repo_id": "r-r2",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "unverified"],
        "payload": {
            "method_selection": {
                "proposed_repo_id": "r-r2",
                "selection_reason": "Route A has the strongest grounded benchmark.",
            },
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

    artifact["payload"]["method_selection"]["selection_reason"] = ""
    build_verification_receipt(
        artifact,
        design_root,
        source_roots={"program:p-r2": program_root},
    )
    write_yaml_if_changed(artifact_path, artifact)
    assert discover_pending_judgements(tmp_path) == []

    artifact["payload"]["method_selection"]["selection_reason"] = "Route A has the strongest grounded benchmark."
    build_verification_receipt(
        artifact,
        design_root,
        source_roots={"program:p-r2": program_root},
    )
    write_yaml_if_changed(artifact_path, artifact)
    evidence_path.write_text("route B superseded the old benchmark", encoding="utf-8")
    assert discover_pending_judgements(tmp_path) == []


def test_cross_unit_symlink_evidence_root_is_never_trusted(tmp_path: Path) -> None:
    unit_id = "p-symlink-source-123456"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-source"
    outside.mkdir()
    evidence_path = outside / "parse-cache.yaml"
    evidence_path.write_text("outside bytes must not become canonical evidence", encoding="utf-8")
    record = default_record("paper", title="Escaping paper", maturity="complete")
    record["id"] = unit_id
    record["status"] = "screened"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["evaluation", "unverified"]
    record["source"]["kind"] = "ai"
    record["payload"]["core_content"]["research_problem"] = "Whether escaped evidence is trusted."
    record["payload"]["claims"] = [
        {
            "id": "claim-symlink-source",
            "text": "Escaped evidence should be rejected.",
            "claim_type": "evaluation",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "parse-cache.yaml",
                    "locator": "section=outside",
                    "quote": "outside bytes must not become canonical evidence",
                }
            ],
        }
    ]
    build_verification_receipt(record, outside)
    write_yaml_if_changed(outside / "record.yaml", record)
    link = tmp_path / "kb/units/papers" / unit_id
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)

    assert discover_pending_judgements(tmp_path) == []
    with pytest.raises(SystemExit, match="Persisted unit confirmation snapshot is not current"):
        apply_confirmation(
            record,
            confirmed_by="Human Reviewer",
            evidence=["reviewed escaped evidence"],
            user_authorization="I confirm this displayed judgement.",
            authorization_source="user_message",
            project_root=tmp_path,
        )


def test_discovery_and_owner_fail_closed_on_duplicate_program_subject(tmp_path: Path) -> None:
    program_root = tmp_path / "kb/programs/p-duplicate"
    workflow = program_root / "workflow"
    workflow.mkdir(parents=True)
    evidence_path = program_root / "evidence.md"
    evidence_path.write_text("The benchmark supports the same decision subject.", encoding="utf-8")
    decision = {
        "id": "decision-duplicate",
        "kind": "program_decision",
        "owner": "research-orchestrator",
        "program_id": "p-duplicate",
        "timestamp": "2026-07-23T00:00:00+00:00",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "unverified"],
        "payload": {
            "decision": {"text": "Use route A", "rationale": "Benchmark coverage."},
            "claims": [
                {
                    "id": "duplicate-claim",
                    "text": "The supported route is A.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "program:p-duplicate",
                            "artifact": "evidence.md",
                            "locator": "benchmark",
                            "quote": "The benchmark supports the same decision subject.",
                        }
                    ],
                }
            ],
        },
    }
    build_verification_receipt(
        decision,
        program_root,
        source_roots={"program:p-duplicate": program_root},
    )
    decisions_path = workflow / "decisions.yaml"
    write_yaml_if_changed(decisions_path, {"items": [decision, dict(decision)]})

    assert discover_pending_judgements(tmp_path) == []
    expected = judgement_snapshot_binding(
        decision,
        owner="research-orchestrator",
        path=decisions_path.relative_to(tmp_path).as_posix(),
    )
    rejected = _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "reject-decision",
        "--program-id",
        "p-duplicate",
        "--decision-id",
        "decision-duplicate",
        "--expected-snapshot",
        json.dumps(expected),
        check=False,
    )
    assert rejected.returncode != 0
    assert "duplicated" in rejected.stderr


def test_discovery_ignores_canonical_artifact_symlink_that_escapes_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    workflow = root / "kb/programs/p-link/workflow"
    workflow.mkdir(parents=True)
    outside = tmp_path / "outside-decisions.yaml"
    write_yaml_if_changed(
        outside,
        {
            "items": [
                {
                    "id": "decision-link",
                    "kind": "program_decision",
                    "owner": "research-orchestrator",
                    "program_id": "p-link",
                    "confirmation_status": "pending_user_confirmation",
                    "payload": {"decision": {"text": "Escaping decision"}, "claims": []},
                }
            ]
        },
    )
    (workflow / "decisions.yaml").symlink_to(outside)

    assert discover_pending_judgements(root) == []


def test_discovery_rejects_unit_record_symlink_to_directory_before_read(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    unit = root / "kb/units/papers/p-directory-link"
    unit.mkdir(parents=True)
    outside = tmp_path / "outside-directory"
    outside.mkdir()
    (unit / "record.yaml").symlink_to(outside, target_is_directory=True)

    assert discover_pending_judgements(root) == []


@pytest.mark.parametrize(
    "relative",
    [
        "kb/units/papers/p-broken/record.yaml",
        "kb/programs/p-broken/workflow/decisions.yaml",
        "kb/units/ideas/i-broken/discussion-judgements.yaml",
        "kb/programs/p-broken/design/i-broken-repo-choice.yaml",
    ],
)
def test_discovery_skips_malformed_candidate_yaml_without_blocking_inbox(
    tmp_path: Path,
    relative: str,
) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text("items: [\n", encoding="utf-8")

    assert discover_pending_judgements(tmp_path) == []


def test_program_decision_reject_is_owner_owned_and_closes_pending_claims(tmp_path: Path) -> None:
    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "init-program",
        "--program-id",
        "p-reject",
        "--question",
        "Which route?",
        "--goal",
        "Choose a grounded route",
    )
    program_root = tmp_path / "kb/programs/p-reject"
    evidence_path = program_root / "evidence.md"
    evidence_path.write_text("The benchmark shows route A has the required coverage", encoding="utf-8")
    claims_path = program_root / "workflow/decision-claims.yaml"
    write_yaml_if_changed(
        claims_path,
        {
            "claims": [
                {
                    "id": "decision-route-a",
                    "text": "The preferred implementation choice is route A.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "program:p-reject",
                            "artifact": "evidence.md",
                            "locator": "benchmark coverage",
                            "quote": "The benchmark shows route A has the required coverage",
                        }
                    ],
                }
            ]
        },
    )
    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "log-decision",
        "--program-id",
        "p-reject",
        "--decision",
        "Use route A",
        "--claims-file",
        str(claims_path),
    )
    decisions_path = program_root / "workflow/decisions.yaml"
    decision_id = load_yaml(decisions_path)["items"][0]["id"]
    cards = discover_pending_judgements(tmp_path)
    assert [card["subject"]["id"] for card in cards] == [decision_id]
    expected = cards[0]["snapshot_binding"]
    assert len(expected["source_digest"]) == 64

    changed_container = load_yaml(decisions_path)
    changed_container["items"].append({"id": "unrelated-bookkeeping", "kind": "not-a-judgement"})
    write_yaml_if_changed(decisions_path, changed_container)
    stale = _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "reject-decision",
        "--program-id",
        "p-reject",
        "--decision-id",
        decision_id,
        "--reason",
        "Prefer a smaller first experiment.",
        "--expected-snapshot",
        json.dumps(expected),
        check=False,
    )
    assert stale.returncode != 0
    assert load_yaml(decisions_path)["items"][0]["confirmation_status"] == "pending_user_confirmation"
    refreshed_cards = discover_pending_judgements(tmp_path)
    assert len(refreshed_cards) == 1
    refreshed = refreshed_cards[0]["snapshot_binding"]
    assert refreshed["source_digest"] != expected["source_digest"]

    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "reject-decision",
        "--program-id",
        "p-reject",
        "--decision-id",
        decision_id,
        "--reason",
        "Prefer a smaller first experiment.",
        "--expected-snapshot",
        json.dumps(refreshed),
    )

    rejected = load_yaml(decisions_path)["items"][0]
    state = load_yaml(program_root / "state.yaml")
    assert rejected["confirmation_status"] == "rejected"
    assert rejected["needs_human_confirmation"] is True
    assert rejected["rejection"]["reason"] == "Prefer a smaller first experiment."
    assert {claim["confirmation_status"] for claim in rejected["payload"]["claims"]} == {"rejected"}
    assert state["last_decision"]["confirmation_status"] == "rejected"
    assert discover_pending_judgements(tmp_path) == []


def test_public_review_snapshot_rejects_unit_and_closes_canonical_claims(tmp_path: Path) -> None:
    unit_id = "p-review-reject-123456"
    path = record_path(tmp_path, "paper", unit_id)
    path.parent.mkdir(parents=True)
    evidence_path = path.parent / "parse-cache.yaml"
    evidence_path.write_text("The grounded analysis supports rejecting this route.", encoding="utf-8")
    record = default_record("paper", title="Rejectable paper", maturity="complete")
    record["id"] = unit_id
    record["status"] = "screened"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["inference", "evaluation", "unverified"]
    record["source"]["kind"] = "ai"
    record["payload"]["core_content"]["research_problem"] = "Whether this route should be retained."
    record["payload"]["claims"] = [
        {
            "id": "paper-route-evaluation",
            "text": "This paper should not remain on the active route.",
            "claim_type": "evaluation",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "parse-cache.yaml",
                    "locator": "section=analysis",
                    "quote": "The grounded analysis supports rejecting this route.",
                }
            ],
        }
    ]
    build_verification_receipt(record, path.parent)
    write_yaml_if_changed(path, record)
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "Human Reviewer"}})

    _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "--agent-protocol",
        "unit-review.json",
        "review",
    )
    protocol = json.loads((tmp_path / "kb/.runtime/unit-review.json").read_text(encoding="utf-8"))
    item = protocol["next_actions"][0]["review_items"][0]
    subject_ref = f"{item['subject']['kind']}:{item['subject']['id']}"
    applied = _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "--agent-protocol",
        "unit-applied.json",
        "review",
        "--apply-snapshot",
        "unit-review.json",
        "--reject-ref",
        subject_ref,
        "--rejection-reason",
        "Do not keep this route.",
        "--user-authorization",
        "Reject this displayed judgement.",
        check=False,
    )
    assert applied.returncode == 0, applied.stderr

    rejected = load_yaml(path)
    assert rejected["confirmation_status"] == "rejected"
    assert rejected["rejection"]["reason"] == "Do not keep this route."
    assert {claim["confirmation_status"] for claim in rejected["payload"]["claims"]} == {"rejected"}
    assert discover_pending_judgements(tmp_path) == []
    replay = _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "review",
        "--apply-snapshot",
        "unit-review.json",
        "--reject-ref",
        subject_ref,
        check=False,
    )
    assert replay.returncode != 0


def test_public_review_snapshot_executes_real_program_owner_route(tmp_path: Path) -> None:
    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "init-program",
        "--program-id",
        "p-apply",
        "--question",
        "Which route?",
        "--goal",
        "Apply one informed decision",
    )
    program_root = tmp_path / "kb/programs/p-apply"
    evidence_path = program_root / "evidence.md"
    evidence_path.write_text("The benchmark shows route A has the required coverage", encoding="utf-8")
    claims_path = program_root / "workflow/decision-claims.yaml"
    write_yaml_if_changed(
        claims_path,
        {
            "claims": [
                {
                    "id": "decision-route-a",
                    "text": "The preferred implementation choice is route A.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "program:p-apply",
                            "artifact": "evidence.md",
                            "locator": "benchmark coverage",
                            "quote": "The benchmark shows route A has the required coverage",
                        }
                    ],
                }
            ]
        },
    )
    _run(
        ".agents/skills/research-orchestrator/scripts/orchestrate.py",
        tmp_path,
        "log-decision",
        "--program-id",
        "p-apply",
        "--decision",
        "Use route A",
        "--rationale",
        "It covers the benchmark.",
        "--claims-file",
        str(claims_path),
    )
    write_yaml_if_changed(runtime_preferences_path(tmp_path), {"identity": {"default_confirmed_by": "Human Reviewer"}})
    decisions_path = program_root / "workflow/decisions.yaml"
    decision_id = load_yaml(decisions_path)["items"][0]["id"]

    listed = _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "--agent-protocol",
        "review.json",
        "review",
    )
    assert "决策内容：Use route A" in listed.stdout
    protocol = json.loads((tmp_path / "kb/.runtime/review.json").read_text(encoding="utf-8"))
    item = protocol["next_actions"][0]["review_items"][0]
    subject_ref = f"{item['subject']['kind']}:{item['subject']['id']}"

    changed_payload = load_yaml(decisions_path)
    changed_payload["items"][0]["payload"]["decision"]["text"] = "Use route B"
    write_yaml_if_changed(decisions_path, changed_payload)
    stale = _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "review",
        "--apply-snapshot",
        "review.json",
        "--confirm-ref",
        subject_ref,
        "--decision-evidence",
        "I reviewed the displayed decision and evidence.",
        "--user-authorization",
        "I confirm the displayed route A decision.",
        check=False,
    )
    assert stale.returncode == 2
    assert load_yaml(decisions_path)["items"][0]["confirmation_status"] == "pending_user_confirmation"
    changed_payload["items"][0]["payload"]["decision"]["text"] = "Use route A"
    write_yaml_if_changed(decisions_path, changed_payload)

    _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "--agent-protocol",
        "review-current.json",
        "review",
    )
    current_protocol = json.loads((tmp_path / "kb/.runtime/review-current.json").read_text(encoding="utf-8"))
    current_item = current_protocol["next_actions"][0]["review_items"][0]
    subject_ref = f"{current_item['subject']['kind']}:{current_item['subject']['id']}"

    applied = _run(
        ".agents/skills/kb-cli/scripts/kb",
        tmp_path,
        "--agent-protocol",
        "applied.json",
        "review",
        "--apply-snapshot",
        "review-current.json",
        "--confirm-ref",
        subject_ref,
        "--decision-evidence",
        "I reviewed the displayed decision and evidence.",
        "--user-authorization",
        "I confirm the displayed route A decision.",
    )
    assert "已应用 1 条拍板结果" in applied.stdout
    confirmed = load_yaml(decisions_path)["items"][0]
    assert confirmed["confirmation_status"] == "confirmed"
    assert confirmed["confirmation"]["user_authorization"] == "I confirm the displayed route A decision."


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
        "owner": "research-orchestrator",
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

    evidence_path.write_text("benchmark bytes changed after confirmation", encoding="utf-8")
    ordinary, pending = report.partition_reporting_events(tmp_path, [event])
    assert ordinary == [] and len(pending) == 1
    assert "stale" in pending[0]["_epistemic_reason"]
    evidence_path.write_text("benchmark supports route A", encoding="utf-8")

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

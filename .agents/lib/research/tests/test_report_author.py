from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import write_yaml_if_changed
from research.confirm import apply_confirmation
from research.evidence import build_verification_receipt
from research.preference_selection import eligible_preferences, record_effective_selection


def _write_confirmed_record(root: Path, unit_id: str, claims: list[dict]) -> None:
    record = {
        "id": unit_id,
        "kind": "paper",
        "title": "Grounded Paper",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "payload": {"claims": claims},
    }
    apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["kb/programs/grounded-report/workflow/decision-log.md"],
        project_root=root,
    )
    write_yaml_if_changed(root / "kb" / "units" / "papers" / unit_id / "record.yaml", record)


def _write_confirmed_decision(root: Path, program_id: str) -> None:
    program_root = root / "kb" / "programs" / program_id
    evidence_path = program_root / "workflow" / "decision-evidence.md"
    evidence_path.write_text("direct benchmark evidence", encoding="utf-8")
    decision = {
        "id": "decision-grounded-baseline",
        "kind": "program_decision",
        "program_id": program_id,
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["inference", "evaluation", "unverified"],
        "payload": {
            "decision": {
                "text": "Use the grounded baseline",
                "stage": "literature-review",
                "rationale": "It has direct benchmark evidence.",
                "alternatives": ["Delay baseline selection"],
            },
            "claims": [
                {
                    "id": "claim-grounded-decision",
                    "text": "Use the grounded baseline.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": f"program:{program_id}",
                            "artifact": "workflow/decision-evidence.md",
                            "locator": "decision-evidence",
                            "quote": "direct benchmark evidence",
                        }
                    ],
                }
            ],
        },
    }
    roots = {f"program:{program_id}": program_root}
    build_verification_receipt(decision, program_root, source_roots=roots)
    apply_confirmation(
        decision,
        confirmed_by="Human Reviewer",
        evidence=["kb/programs/grounded-report/workflow/decision-evidence.md"],
        user_authorization="I confirm this program decision.",
        authorization_source="user_message",
        project_root=root,
        verification_root=program_root,
        trusted_source_roots=roots,
    )
    write_yaml_if_changed(
        program_root / "workflow" / "decisions.yaml",
        {"id": f"{program_id}-decisions", "items": [decision]},
    )
    (program_root / "workflow" / "decision-log.md").write_text(
        "# Decision Log\n\n"
        "## 2026-07-17T01:00:00+00:00 · Use the grounded baseline\n\n"
        "- Decision ID: `decision-grounded-baseline`\n"
        "- Confirmation: `confirmed`\n",
        encoding="utf-8",
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_report_module():
    script = _project_root() / ".agents" / "skills" / "report-author" / "scripts" / "report.py"
    spec = importlib.util.spec_from_file_location("report_author_script_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stale_survey_event_isolated_by_pure_read_consumer(tmp_path: Path, monkeypatch) -> None:
    report = _load_report_module()
    root = tmp_path / "workspace"
    survey_path = root / "kb" / "synthesis" / "robot-learning" / "survey.yaml"
    write_yaml_if_changed(survey_path, {"slug": "robot-learning", "consumer_binding": {}})
    before = survey_path.read_bytes()
    monkeypatch.setattr(
        report,
        "survey_staleness",
        lambda payload, project_root: {"stale": True, "reasons": ["new matching unit"], "new_unit_ids": ["p-new"]},
    )
    event = {
        "event_type": "survey-inference",
        "confirmation_status": "confirmed",
        "confirmation_binding": {
            "subject": {
                "kind": "survey_inference",
                "id": "survey-robot-learning",
                "owner": "literature-synthesizer",
                "path": "kb/synthesis/robot-learning/survey.yaml",
            }
        },
    }

    ordinary, pending = report.partition_reporting_events(root, [event])

    assert ordinary == []
    assert len(pending) == 1
    assert "survey upstream binding changed" in pending[0]["_epistemic_reason"]
    assert survey_path.read_bytes() == before


def test_survey_consumer_rejects_symlinked_artifact(tmp_path: Path, monkeypatch) -> None:
    report = _load_report_module()
    root = tmp_path / "workspace"
    outside = tmp_path / "outside-survey.yaml"
    write_yaml_if_changed(outside, {"consumer_binding": {}})
    survey_path = root / "kb" / "synthesis" / "unsafe" / "survey.yaml"
    survey_path.parent.mkdir(parents=True)
    survey_path.symlink_to(outside)
    monkeypatch.setattr(
        report,
        "survey_staleness",
        lambda payload, project_root: (_ for _ in ()).throw(AssertionError("unsafe survey must not be opened")),
    )
    event = {
        "event_type": "survey-inference",
        "confirmation_binding": {
            "subject": {
                "kind": "survey_inference",
                "id": "survey-unsafe",
                "path": "kb/synthesis/unsafe/survey.yaml",
            }
        },
    }

    ordinary, pending = report.partition_reporting_events(root, [event])

    assert ordinary == []
    assert len(pending) == 1
    assert "survey upstream binding changed" in pending[0]["_epistemic_reason"]
    assert survey_path.is_symlink()


def _make_workspace(tmp_path: Path, *, with_claim: bool = True) -> tuple[Path, str, str]:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    program_id = "grounded-report"
    unit_id = "p-grounded-123456"
    workflow = root / "kb" / "programs" / program_id / "workflow"
    workflow.mkdir(parents=True)
    write_yaml_if_changed(
        root / "kb" / "programs" / program_id / "state.yaml",
        {"program_id": program_id, "active_unit_ids": [unit_id]},
    )
    write_yaml_if_changed(
        workflow / "reporting-events.yaml",
        {
            "id": f"{program_id}-reporting-events",
            "items": [
                {
                    "source_skill": "paper-analyst",
                    "event_type": "phase-completed",
                    "title": "Grounded review completed",
                    "summary": "The paper analysis is ready for reporting.",
                    "stage": "literature-review",
                    "paper_ids": [unit_id],
                    "timestamp": "2026-07-17T00:00:00+00:00",
                }
            ],
        },
    )
    _write_confirmed_decision(root, program_id)
    unit_dir = root / "kb" / "units" / "papers" / unit_id
    unit_dir.mkdir(parents=True)
    claims = []
    if with_claim:
        claims.append(
            {
                "id": "claim-baseline",
                "text": "The method improves benchmark success rate.",
                "claim_type": "fact",
                "confirmation_status": "confirmed",
                "evidence_refs": [
                    {
                        "source_unit_id": unit_id,
                        "artifact": "parse-cache.yaml",
                        "locator": "page=3",
                        "quote": "Success rate improves by 8 points.",
                        "summary": "Reported benchmark comparison.",
                    }
                ],
            }
        )
    write_yaml_if_changed(
        unit_dir / "parse-cache.yaml",
        {"chunks": [{"label": "page-3", "text": "Success rate improves by 8 points."}]},
    )
    if with_claim:
        _write_confirmed_record(root, unit_id, claims)
    else:
        write_yaml_if_changed(
            unit_dir / "record.yaml",
            {"id": unit_id, "kind": "paper", "title": "Grounded Paper", "payload": {"claims": []}},
        )
    return root, program_id, unit_id


def test_weekly_and_stage_reports_include_claims_evidence_events_and_decisions(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)

    inputs = report.load_report_inputs(root, program_id)
    weekly = report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly")
    stage = report.render_report(f"Stage Summary: {program_id}", inputs, report_kind="stage-summary")
    writing = report.render_report(f"Writing Materials: {program_id}", inputs, report_kind="writing-materials")

    for text in (weekly, stage, writing):
        assert "The method improves benchmark success rate." in text
        assert "Success rate improves by 8 points." in text
        assert "Grounded review completed" in text
        assert "Use the grounded baseline" in text
    assert "## Writing Claims & Evidence" in writing


def test_legacy_judgement_event_with_confirmed_string_fails_safe_without_canonical_binding(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    events_path = root / "kb" / "programs" / program_id / "workflow" / "reporting-events.yaml"
    write_yaml_if_changed(
        events_path,
        {
            "id": f"{program_id}-reporting-events",
            "items": [
                {
                    "source_skill": "paper-analyst",
                    "event_type": "phase-completed",
                    "title": "Grounded review completed",
                    "summary": "The paper analysis is ready for reporting.",
                    "paper_ids": [unit_id],
                    "timestamp": "2026-07-17T00:00:00+00:00",
                },
                {
                    "source_skill": "experiment-workbench",
                    "event_type": "experiment-diagnosis",
                    "title": "Legacy diagnosis",
                    "summary": "A stale legacy diagnosis asserted a likely cause.",
                    "confirmation_status": "confirmed",
                    "timestamp": "2026-07-17T00:01:00+00:00",
                },
            ],
        },
    )

    inputs = report.load_report_inputs(root, program_id)
    weekly = report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly")
    ordinary_section = weekly[weekly.index("## Reporting Events") : weekly.index("## Pending / Unverified judgements")]
    pending_section = weekly[weekly.index("## Pending / Unverified judgements") :]

    assert "The paper analysis is ready for reporting." in ordinary_section
    assert "A stale legacy diagnosis asserted a likely cause." not in ordinary_section
    assert "A stale legacy diagnosis asserted a likely cause." in pending_section
    assert "confirmation_status=confirmed" in pending_section
    assert "missing: canonical confirmation subject and claim/evidence binding" in pending_section


def test_outline_produces_evidence_backed_section_skeleton(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)

    outline = report.render_outline(program_id, report.load_report_inputs(root, program_id))

    for heading in ("## Introduction", "## Related Work", "## Method", "## Experiments", "## Results", "## Discussion", "## Conclusion"):
        assert heading in outline
    assert "The method improves benchmark success rate." in outline
    assert "Success rate improves by 8 points." in outline


def test_missing_inputs_are_explicit_and_never_fabricated(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path, with_claim=False)
    workflow = root / "kb" / "programs" / program_id / "workflow"
    write_yaml_if_changed(
        workflow / "reporting-events.yaml",
        {"id": f"{program_id}-reporting-events", "items": []},
    )
    (workflow / "decision-log.md").write_text("# Decision Log\n", encoding="utf-8")
    write_yaml_if_changed(workflow / "decisions.yaml", {"id": f"{program_id}-decisions", "items": []})

    inputs = report.load_report_inputs(root, program_id)
    weekly = report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly")
    outline = report.render_outline(program_id, inputs)

    assert "missing: confirmed claims" in weekly
    assert "missing: reporting events" in weekly
    assert "missing: decisions" in weekly
    assert "missing: related-work claims and evidence" in outline
    assert "improves benchmark success rate" not in weekly


def test_reporting_style_controls_verbosity_and_preserves_missing_markers(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path, with_claim=False)
    unit_dir = root / "kb" / "units" / "papers" / unit_id
    claims = [
        {
            "id": f"claim-{index}",
            "text": f"Confirmed claim {index}.",
            "claim_type": "fact",
            "confirmation_status": "confirmed",
            "evidence_refs": [],
        }
        for index in range(6)
    ]
    _write_confirmed_record(root, unit_id, claims)
    events_path = root / "kb" / "programs" / program_id / "workflow" / "reporting-events.yaml"
    write_yaml_if_changed(
        events_path,
        {
            "id": f"{program_id}-reporting-events",
            "items": [
                {
                    "source_skill": "paper-analyst",
                    "event_type": "phase-completed",
                    "title": f"Reporting event {index}",
                    "summary": "Grounded event summary.",
                    "timestamp": f"2026-07-17T00:{index:02d}:00+00:00",
                    "paper_ids": [unit_id],
                }
                for index in range(8)
            ],
        },
    )
    profile_path = root / "kb" / "config" / "user-profile.yaml"

    def selected_style(selection_id: str) -> str:
        eligible = eligible_preferences(root, skill="report-author", operation="weekly")
        record_effective_selection(
            root,
            {
                "selection_id": selection_id,
                "skill": "report-author",
                "operation": "weekly",
                "catalog_digest": eligible["catalog_digest"],
                "task_context": report.report_preference_context(
                    program_id,
                    operation="weekly",
                    stage="",
                    limit=20,
                    inputs=report.load_report_inputs(root, program_id),
                ),
                "selected": [
                    {
                        "preference_id": item["preference_id"],
                        "reason": "controls requested report density",
                        "application": "apply to report presentation only",
                    }
                    for item in eligible["items"]
                ],
                "excluded": [],
            },
        )
        return selection_id

    write_yaml_if_changed(profile_path, {"personalization": {"reporting_style": "详细 / detailed"}})
    detailed_inputs = report.load_report_inputs(
        root,
        program_id,
        preference_selection_id=selected_style("prefsel-report-detailed"),
        preference_operation="weekly",
    )
    detailed = report.render_report(f"Weekly Report: {program_id}", detailed_inputs, report_kind="weekly")

    write_yaml_if_changed(profile_path, {"personalization": {"reporting_style": "简洁 concise"}})
    concise_inputs = report.load_report_inputs(
        root,
        program_id,
        preference_selection_id=selected_style("prefsel-report-concise"),
        preference_operation="weekly",
    )
    concise = report.render_report(f"Weekly Report: {program_id}", concise_inputs, report_kind="weekly")

    # Canonical soft preference remains configured, but without a selection it
    # must not affect the consumer.
    default_inputs = report.load_report_inputs(root, program_id)
    default = report.render_report(f"Weekly Report: {program_id}", default_inputs, report_kind="weekly")

    assert concise_inputs.reporting_style == "concise"
    assert detailed_inputs.reporting_style == "detailed"
    assert default_inputs.reporting_style == "default"
    assert len(concise) < len(detailed)
    assert detailed == default
    assert "Reporting event 0" in detailed
    assert "Reporting event 0" not in concise
    assert "Confirmed claim 5." in detailed
    assert "Confirmed claim 5." not in concise
    assert "missing: evidence for claim claim-0" in concise
    assert "missing: evidence for claim claim-0" in detailed


def test_unparseable_reporting_style_uses_default_behavior(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)
    expected = report.render_report(
        f"Weekly Report: {program_id}",
        report.load_report_inputs(root, program_id),
        report_kind="weekly",
    )
    profile_path = root / "kb" / "config" / "user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text("reporting_style: [broken\n", encoding="utf-8")

    inputs = report.load_report_inputs(root, program_id)
    actual = report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly")

    assert inputs.reporting_style == "default"
    assert actual == expected


def test_generated_documents_do_not_leak_raw_commands(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)
    inputs = report.load_report_inputs(root, program_id)
    documents = [
        report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly"),
        report.render_report(f"Stage Summary: {program_id}", inputs, report_kind="stage-summary"),
        report.render_report(f"PPT Materials: {program_id}", inputs, report_kind="ppt-materials"),
        report.render_report(f"Writing Materials: {program_id}", inputs, report_kind="writing-materials"),
        report.render_outline(program_id, inputs),
    ]

    forbidden = ("python3 ", ".agents/skills/", "--program-id", "${", "NEXT FOR AGENT:", "kb/units/")
    for document in documents:
        assert not any(token in document for token in forbidden)


def test_outline_cli_writes_report_without_raw_command_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["report.py", "--root", str(root), "outline", "--program-id", program_id],
    )

    assert report.main() == 0
    text = (root / "kb" / "programs" / program_id / "reports" / "paper-outline.md").read_text(encoding="utf-8")
    stdout = capsys.readouterr().out

    assert "## Related Work: Confirmed Claims & Evidence" in text
    assert "Success rate improves by 8 points." in text
    for token in ("python3 ", ".agents/skills/", "--program-id", "${", "NEXT FOR AGENT:"):
        assert token not in stdout

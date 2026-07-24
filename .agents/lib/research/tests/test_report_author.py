from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.evidence import build_verification_receipt
from research.judgements import confirmation_binding
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


def _load_synthesizer_module():
    script = _project_root() / ".agents" / "skills" / "literature-synthesizer" / "scripts" / "synthesize.py"
    spec = importlib.util.spec_from_file_location("report_survey_synthesizer_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SURVEY_QUOTE = "Alpha uses a hierarchical controller for long-horizon tasks."


def _write_confirmed_program_survey(root: Path, *, program_id: str = "program-survey") -> tuple[Path, Path]:
    synth = _load_synthesizer_module()
    program_root = root / "kb" / "programs" / program_id
    (program_root / "workflow").mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(program_root / "state.yaml", {"program_id": program_id, "active_unit_ids": []})

    unit_id = "p-survey-alpha"
    unit_root = root / "kb" / "units" / "papers" / unit_id
    unit_root.mkdir(parents=True, exist_ok=True)
    (unit_root / "note.md").write_text(f"# Evidence\n\n{SURVEY_QUOTE}\n", encoding="utf-8")
    source = {
        "id": unit_id,
        "kind": "paper",
        "title": "Alpha Method",
        "summary": "robot learning",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "payload": {},
    }
    apply_confirmation(
        source,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed source unit."],
        project_root=root,
    )
    write_yaml_if_changed(unit_root / "record.yaml", source)

    survey = synth.build_survey_scaffold(
        [source],
        root=root,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-24T00:00:00Z",
        program_ids=[program_id],
    )
    for _, cell, _ in synth.survey_claim_entries(survey)[1]:
        cell["content"] = f"Agent-authored survey judgement for {cell['id']}."
        cell["evidence_refs"] = [
            {
                "source_unit_id": unit_id,
                "artifact": "note.md",
                "locator": "section=evidence",
                "quote": SURVEY_QUOTE,
            }
        ]
    taxonomy = next(section for section in survey["sections"] if section["id"] == "taxonomy")
    taxonomy["cells"][0].update({"row_label": "Alpha Method", "column_label": "Hierarchical control"})
    trends = next(section for section in survey["sections"] if section["id"] == "trends")
    trends["items"][0]["trajectory"] = "flat to hierarchical"
    gaps = next(section for section in survey["sections"] if section["id"] == "gaps_challenges")
    gaps["items"][0]["gap_type"] = "benchmark coverage"
    survey["comparison_matrix"]["dimensions"][0]["label"] = "Control hierarchy"
    survey["comparison_matrix"]["methods"][0].update(
        {"label": "Alpha Method", "source_unit_ids": [unit_id]}
    )
    violations, verified = synth.verify_survey_fill(survey, root)
    assert violations == [], violations
    survey_path = root / "kb" / "synthesis" / "robot-learning" / "survey.yaml"
    survey_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(survey_path, verified)
    apply_confirmation(
        verified,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed every displayed survey claim."],
        user_authorization="Confirm this displayed survey judgement.",
        authorization_source="user_message",
        project_root=root,
        verification_root=survey_path.parent,
        trusted_source_roots={unit_id: unit_root},
    )
    write_yaml_if_changed(survey_path, verified)
    events_path = synth._append_survey_reporting_events(root, verified, survey_path)[0]
    return survey_path, events_path


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


def test_program_survey_claims_and_verbatim_evidence_survive_reload(tmp_path: Path) -> None:
    report = _load_report_module()
    program_id = "program-survey"
    _survey_path, _events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)

    first = report.render_report(
        f"Stage Summary: {program_id}",
        report.load_report_inputs(tmp_path, program_id, stage="survey"),
        report_kind="stage-summary",
    )
    reloaded = _load_report_module()
    second = reloaded.render_report(
        f"Stage Summary: {program_id}",
        reloaded.load_report_inputs(tmp_path, program_id, stage="survey"),
        report_kind="stage-summary",
    )

    for text in (first, second):
        assert "Agent-authored survey judgement for background_terms-1." in text
        assert SURVEY_QUOTE in text
        assert "missing: records for linked units background_terms-1" not in text
        assert "missing: confirmed claims" not in text
        assert "## Pending / Unverified judgements" not in text
    assert first == second


def test_unit_discovery_uses_only_exact_unit_identity_namespaces() -> None:
    report = _load_report_module()
    discovered = report._collect_unit_ids(
        {
            "unit_id": "u-one",
            "unit_ids": ["u-two"],
            "active_unit_ids": ["u-three"],
            "related_unit_ids": ["u-four"],
            "paper_id": "p-four",
            "paper_ids": ["p-five"],
            "repo_id": "r-five",
            "repo_ids": ["r-six"],
            "dataset_id": "d-six",
            "dataset_ids": ["d-seven"],
            "blog_id": "b-seven",
            "blog_ids": ["b-eight"],
            "idea_id": "i-eight",
            "idea_ids": ["i-nine"],
            "experiment_id": "e-nine",
            "experiment_ids": ["e-ten"],
            "claim_ids": ["background_terms-1"],
            "program_ids": ["program-not-a-unit"],
            "selected_action_ids": ["action-not-a-unit"],
            "candidate_ids": ["candidate-not-a-unit"],
            "artifacts": ["kb/units/repos/r-from-path/record.yaml"],
        }
    )

    assert discovered == {
        "u-one",
        "u-two",
        "u-three",
        "u-four",
        "p-four",
        "p-five",
        "r-five",
        "r-six",
        "d-six",
        "d-seven",
        "b-seven",
        "b-eight",
        "i-eight",
        "i-nine",
        "e-nine",
        "e-ten",
        "r-from-path",
    }


def test_confirmed_event_prose_is_neutral_and_exact_binding_mutation_is_pending(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _unit_id = _make_workspace(tmp_path)
    path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    decisions = load_yaml(path)
    record = decisions["items"][0]
    record["owner"] = "research-orchestrator"
    write_yaml_if_changed(path, decisions)
    event = {
        "source_skill": "research-orchestrator",
        "event_type": "decision-confirmed",
        "title": "INJECTED TITLE MUST NOT RENDER",
        "summary": "INJECTED SUMMARY MUST NOT RENDER",
        "tags": ["INJECTED-TAG"],
        "confirmation_status": "confirmed",
        "confirmation_binding": confirmation_binding(
            record,
            owner="research-orchestrator",
            path=path.relative_to(root).as_posix(),
        ),
    }

    ordinary, pending = report.partition_reporting_events(root, [event])
    assert pending == []
    rendered = report.render_events(ordinary, heading="Reporting Events")
    text = "\n".join(rendered)
    assert "Confirmed judgement" in text
    assert "INJECTED" not in text

    event["confirmation_binding"]["content_digest"] = "0" * 64
    ordinary, pending = report.partition_reporting_events(root, [event])
    assert ordinary == []
    assert len(pending) == 1
    assert "exact current judgement binding" in pending[0]["_epistemic_reason"]


def test_mutable_survey_event_prose_never_enters_formal_timeline_in_two_rounds(tmp_path: Path) -> None:
    program_id = "program-survey"
    _survey_path, events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)
    payload = load_yaml(events_path)
    payload["items"][0]["title"] = "INJECTED SURVEY TITLE"
    payload["items"][0]["summary"] = "INJECTED SURVEY SUMMARY"
    payload["items"][0]["tags"] = ["INJECTED-SURVEY-TAG"]
    write_yaml_if_changed(events_path, payload)

    for _round in range(2):
        report = _load_report_module()
        text = report.render_report(
            f"Stage Summary: {program_id}",
            report.load_report_inputs(tmp_path, program_id, stage="survey"),
            report_kind="stage-summary",
        )
        assert "Agent-authored survey judgement for background_terms-1." in text
        assert "INJECTED SURVEY" not in text
        assert "INJECTED-SURVEY-TAG" not in text


def test_copied_survey_event_is_pending_for_the_wrong_program_after_reload(tmp_path: Path) -> None:
    _survey_path, events_path = _write_confirmed_program_survey(tmp_path, program_id="program-a")
    copied_event = load_yaml(events_path)["items"][0]
    other_events = tmp_path / "kb" / "programs" / "program-b" / "workflow" / "reporting-events.yaml"
    write_yaml_if_changed(
        other_events,
        {"id": "program-b-reporting-events", "program_id": "program-b", "items": [copied_event]},
    )
    write_yaml_if_changed(
        tmp_path / "kb" / "programs" / "program-b" / "state.yaml",
        {"program_id": "program-b", "active_unit_ids": []},
    )

    for _round in range(2):
        report = _load_report_module()
        inputs = report.load_report_inputs(tmp_path, "program-b", stage="survey")
        text = report.render_report("Stage Summary: program-b", inputs, report_kind="stage-summary")
        assert inputs.claim_sources == []
        assert len(inputs.pending_judgement_events) == 1
        assert "survey binding for this program" in text
        assert "Agent-authored survey judgement" not in text


@pytest.mark.parametrize(
    "mutation",
    ["content", "confirmation", "verification", "evidence", "upstream_binding"],
)
def test_stale_or_tampered_survey_never_reaches_formal_claims(tmp_path: Path, mutation: str) -> None:
    report = _load_report_module()
    program_id = "program-survey"
    survey_path, _events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)
    survey = load_yaml(survey_path)
    original_claim = "Agent-authored survey judgement for background_terms-1."
    if mutation == "content":
        survey["payload"]["claims"][0]["text"] = "TAMPERED SURVEY CLAIM"
        write_yaml_if_changed(survey_path, survey)
    elif mutation == "confirmation":
        survey["confirmation"]["content_digest"] = "0" * 64
        write_yaml_if_changed(survey_path, survey)
    elif mutation == "verification":
        survey["payload"]["verification"]["claims_digest"] = "0" * 64
        write_yaml_if_changed(survey_path, survey)
    elif mutation == "evidence":
        evidence_path = tmp_path / "kb" / "units" / "papers" / "p-survey-alpha" / "note.md"
        evidence_path.write_text("# Evidence\n\nChanged after confirmation.\n", encoding="utf-8")
    else:
        survey["consumer_binding"]["unit_ids"] = []
        write_yaml_if_changed(survey_path, survey)

    inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")
    text = report.render_report(
        f"Stage Summary: {program_id}",
        inputs,
        report_kind="stage-summary",
    )

    assert inputs.claim_sources == []
    assert len(inputs.pending_judgement_events) == 1
    assert "## Pending / Unverified judgements" in text
    assert original_claim not in text
    assert "TAMPERED SURVEY CLAIM" not in text


def test_survey_claim_source_binding_stales_old_report_preference_receipt(tmp_path: Path) -> None:
    report = _load_report_module()
    program_id = "program-survey"
    survey_path, _events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)
    inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")
    assert len(inputs.claim_sources) == 1
    assert len(inputs.claim_sources[0].binding_digest) == 64
    context = report.report_preference_context(
        program_id,
        operation="stage-summary",
        stage="survey",
        limit=20,
        inputs=inputs,
    )
    eligible = eligible_preferences(tmp_path, skill="report-author", operation="stage-summary")
    selected = []
    excluded = []
    for item in eligible["items"]:
        choice = {
            "preference_id": item["preference_id"],
            "reason": "bounded report preference regression",
        }
        if item["strength"] == "hard":
            selected.append({**choice, "application": "enforce for this report only"})
        else:
            excluded.append(choice)
    selection_id = "prefsel-survey-report-binding"
    record_effective_selection(
        tmp_path,
        {
            "selection_id": selection_id,
            "skill": "report-author",
            "operation": "stage-summary",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    assert report.load_report_inputs(
        tmp_path,
        program_id,
        stage="survey",
        preference_selection_id=selection_id,
        preference_operation="stage-summary",
    ).claim_sources

    survey = load_yaml(survey_path)
    survey["confirmation"]["content_digest"] = "0" * 64
    write_yaml_if_changed(survey_path, survey)
    with pytest.raises(ValueError, match="bound to another task"):
        report.load_report_inputs(
            tmp_path,
            program_id,
            stage="survey",
            preference_selection_id=selection_id,
            preference_operation="stage-summary",
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing_owner", "extra_field", "content_digest", "missing_path", "decoy_path"],
)
def test_mutated_survey_confirmation_binding_moves_event_to_pending(
    tmp_path: Path,
    mutation: str,
) -> None:
    program_id = "program-survey"
    survey_path, events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)
    payload = load_yaml(events_path)
    binding = payload["items"][0]["confirmation_binding"]
    if mutation == "missing_owner":
        binding["subject"].pop("owner")
    elif mutation == "extra_field":
        binding["unexpected"] = "not receipt-bound"
    elif mutation == "content_digest":
        binding["content_digest"] = "0" * 64
    elif mutation == "missing_path":
        binding["subject"]["path"] = "kb/synthesis/robot-learning/review.yaml"
    else:
        decoy = tmp_path / "kb" / "synthesis" / "decoy" / "survey.yaml"
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_bytes(survey_path.read_bytes())
        binding["subject"]["path"] = decoy.relative_to(tmp_path).as_posix()
    write_yaml_if_changed(events_path, payload)

    for _round in range(2):
        report = _load_report_module()
        inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")
        assert inputs.claim_sources == []
        assert len(inputs.pending_judgement_events) == 1
        text = report.render_report(
            f"Stage Summary: {program_id}",
            inputs,
            report_kind="stage-summary",
        )
        assert "Pending / Unverified" in text
        assert "Agent-authored survey judgement" not in text
        if mutation in {"missing_owner", "extra_field", "content_digest", "decoy_path"}:
            assert "exact current judgement binding" in text


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

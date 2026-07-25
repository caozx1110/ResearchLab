from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import research.judgements as judgements_module
import research.records as records_module
from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation, write_record
from research.evidence import build_verification_receipt
from research.judgements import confirmation_binding
from research.preference_selection import eligible_preferences, record_effective_selection
from research.records import canonical_record_snapshot_for_record, normalize_record_snapshot


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
    record_path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
    write_yaml_if_changed(record_path, record)
    expected_record_snapshot = canonical_record_snapshot_for_record(root, record)
    normalized = normalize_record_snapshot(expected_record_snapshot, root)
    assert normalized is not None
    record = normalized
    apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["kb/programs/grounded-report/workflow/decision-log.md"],
        project_root=root,
        expected_record_snapshot=expected_record_snapshot,
    )
    write_record(root, record, expected_record_snapshot=expected_record_snapshot)


def _write_confirmed_repo_record(root: Path, unit_id: str) -> Path:
    repo_root = root / "repo-fixtures" / unit_id
    repo_root.mkdir(parents=True)
    evidence_path = repo_root / "README.md"
    evidence_path.write_text("External repo evidence remains current.", encoding="utf-8")
    unit_root = root / "kb" / "units" / "repos" / unit_id
    unit_root.mkdir(parents=True)
    record = {
        "id": unit_id,
        "kind": "repo",
        "title": "External Evidence Repo",
        "source": {"original_uri": repo_root.as_posix()},
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "unverified"],
        "payload": {
            "structure": {"repo_root": repo_root.resolve().as_posix()},
            "claims": [
                {
                    "id": "claim-external-repo",
                    "text": "The external repository supports the selected route.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": unit_id,
                            "artifact": "README.md",
                            "locator": "line=1",
                            "quote": "External repo evidence remains current.",
                            "external_source": {"kind": "repo"},
                        }
                    ],
                }
            ],
        },
    }
    build_verification_receipt(
        record,
        unit_root,
        external_source={"kind": "repo", "base_root": repo_root.resolve().as_posix()},
        source_roots={unit_id: unit_root},
    )
    record_path = unit_root / "record.yaml"
    write_yaml_if_changed(record_path, record)
    expected_record_snapshot = canonical_record_snapshot_for_record(root, record)
    normalized = normalize_record_snapshot(expected_record_snapshot, root)
    assert normalized is not None
    apply_confirmation(
        normalized,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed the external repository evidence."],
        user_authorization="Confirm this repository judgement.",
        authorization_source="user_message",
        project_root=root,
        verification_root=unit_root,
        expected_record_snapshot=expected_record_snapshot,
    )
    write_record(root, normalized, expected_record_snapshot=expected_record_snapshot)
    return evidence_path


def _write_confirmed_decision(root: Path, program_id: str) -> None:
    program_root = root / "kb" / "programs" / program_id
    evidence_path = program_root / "workflow" / "decision-evidence.md"
    evidence_path.write_text("direct benchmark evidence", encoding="utf-8")
    decision = {
        "id": "decision-grounded-baseline",
        "kind": "program_decision",
        "owner": "research-orchestrator",
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


def test_confirmed_survey_report_captures_bound_subject_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    program_id = "program-survey"
    _write_confirmed_program_survey(tmp_path, program_id=program_id)
    original_load = report.load_bound_judgement_batch_snapshot
    captures = 0

    def count_bound_capture(*args, **kwargs):
        nonlocal captures
        captures += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr(report, "load_bound_judgement_batch_snapshot", count_bound_capture)

    inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")

    assert captures == 1
    assert [source.kind for source in inputs.claim_sources].count("survey_judgement") == 1


def test_survey_replacement_after_event_binding_is_pending_without_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    program_id = "program-survey"
    survey_path, _events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)
    survey_dir = survey_path.parent
    displaced = tmp_path / "displaced-survey"
    replacement = tmp_path / "replacement-survey"
    replacement.mkdir()
    replacement_payload = load_yaml(survey_path)
    replacement_payload["payload"]["claims"][0]["text"] = "REPLACEMENT SURVEY SENTINEL"
    write_yaml_if_changed(replacement / "survey.yaml", replacement_payload)
    original_binding = report.confirmation_binding
    swapped = False

    def swap_after_binding(*args, **kwargs):
        nonlocal swapped
        result = original_binding(*args, **kwargs)
        if not swapped and str(args[0].get("kind") or "") == "survey_judgement":
            swapped = True
            survey_dir.rename(displaced)
            replacement.rename(survey_dir)
        return result

    monkeypatch.setattr(report, "confirmation_binding", swap_after_binding)

    inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")
    rendered = report.render_report(
        f"Stage Summary: {program_id}",
        inputs,
        report_kind="stage-summary",
    )

    assert swapped
    assert inputs.claim_sources == []
    assert len(inputs.pending_judgement_events) == 1
    assert "exact current judgement binding" in inputs.pending_judgement_events[0]["_epistemic_reason"]
    assert "REPLACEMENT SURVEY SENTINEL" not in rendered


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
        assert "survey binding for this program" in inputs.pending_judgement_events[0]["_epistemic_reason"]
        assert "## 待确认 / 未核验的判断" in text
        assert "当前确认回执或其证据绑定已失效" in text
        assert "Agent-authored survey judgement" not in text


@pytest.mark.parametrize(
    "mutation",
    [
        "content",
        "confirmation",
        "verification",
        "evidence",
        "upstream_binding",
        "invalid_survey_yaml",
        "invalid_upstream_yaml",
    ],
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
    elif mutation == "upstream_binding":
        survey["consumer_binding"]["unit_ids"] = []
        write_yaml_if_changed(survey_path, survey)
    elif mutation == "invalid_survey_yaml":
        survey_path.write_text("kind: survey_judgement\npayload: [unterminated\n", encoding="utf-8")
    else:
        upstream = tmp_path / "kb" / "units" / "papers" / "p-survey-alpha" / "record.yaml"
        upstream.write_text("kind: paper\npayload: [unterminated\n", encoding="utf-8")

    inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")
    text = report.render_report(
        f"Stage Summary: {program_id}",
        inputs,
        report_kind="stage-summary",
    )

    assert inputs.claim_sources == []
    assert len(inputs.pending_judgement_events) == 1
    assert "## 待确认 / 未核验的判断" in text
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
        assert "待确认 / 未核验" in text
        assert "Agent-authored survey judgement" not in text
        if mutation in {"missing_owner", "extra_field", "content_digest", "decoy_path"}:
            assert "exact current judgement binding" in inputs.pending_judgement_events[0]["_epistemic_reason"]


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


@pytest.mark.parametrize("event_type", ["fact", "factual", "operational"])
def test_literal_factual_and_operational_event_types_enter_ordinary_lane(
    tmp_path: Path,
    event_type: str,
) -> None:
    report = _load_report_module()
    event = {
        "event_type": event_type,
        "title": f"Explicit {event_type} event",
        "summary": "A mechanically recorded reporting fact.",
    }

    ordinary, pending = report.partition_reporting_events(tmp_path, [event])

    assert ordinary == [event]
    assert pending == []


@pytest.mark.parametrize(
    "event",
    [
        {
            "event_type": "factual",
            "information_types": ["evaluation"],
        },
        {
            "event_type": "decision-factual",
            "epistemic_type": "factual",
        },
        {
            "event_type": "operational",
            "confirmation_binding": {"subject": {"kind": "program_decision", "id": "d-1"}},
        },
    ],
)
def test_factual_labels_cannot_downgrade_judgement_signals(event: dict) -> None:
    report = _load_report_module()

    assert report._event_is_judgement(event) is True


def test_report_rejects_unit_replaced_after_snapshot_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    unit_dir = root / "kb" / "units" / "papers" / unit_id
    original_dir = tmp_path / "original-unit"
    replacement_dir = tmp_path / "outside-replacement"
    replacement_dir.mkdir()
    write_yaml_if_changed(
        replacement_dir / "record.yaml",
        {
            "id": unit_id,
            "kind": "paper",
            "title": "OUTSIDE SENTINEL TITLE",
            "confirmation_status": "confirmed",
            "payload": {
                "claims": [
                    {
                        "id": "outside-claim",
                        "text": "OUTSIDE SENTINEL CLAIM",
                        "claim_type": "fact",
                        "confirmation_status": "confirmed",
                        "evidence_refs": [],
                    }
                ]
            },
        },
    )
    original_current_check = report.judgement_confirmation_is_current
    swapped = False

    def replace_before_current_check(*args, **kwargs):
        nonlocal swapped
        record = args[1]
        if record.get("id") == unit_id:
            selected_snapshot = kwargs.get("record_snapshot")
            assert selected_snapshot is not None
            assert selected_snapshot.unit_id == unit_id
            if not swapped:
                unit_dir.rename(original_dir)
                replacement_dir.rename(unit_dir)
                swapped = True
        return original_current_check(*args, **kwargs)

    monkeypatch.setattr(
        report,
        "judgement_confirmation_is_current",
        replace_before_current_check,
    )

    inputs = report.load_report_inputs(root, program_id)
    rendered = report.render_report(
        f"Stage Summary: {program_id}",
        inputs,
        report_kind="stage-summary",
    )

    assert inputs.claim_sources == []
    assert inputs.missing_units == [unit_id]
    assert "OUTSIDE SENTINEL TITLE" not in rendered
    assert "OUTSIDE SENTINEL CLAIM" not in rendered


def test_report_revalidates_unit_after_claim_source_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    unit_dir = root / "kb" / "units" / "papers" / unit_id
    displaced = tmp_path / "displaced-after-binding"
    replacement = tmp_path / "replacement-after-binding"
    replacement.mkdir()
    replacement_record = load_yaml(unit_dir / "record.yaml")
    replacement_record["title"] = "POST-BINDING REPLACEMENT SENTINEL"
    write_yaml_if_changed(replacement / "record.yaml", replacement_record)
    (replacement / "parse-cache.yaml").write_bytes((unit_dir / "parse-cache.yaml").read_bytes())
    original_digest = report._canonical_digest
    swapped = False

    def replace_while_binding(value):
        nonlocal swapped
        digest = original_digest(value)
        if isinstance(value, dict) and "source" in value and not swapped:
            swapped = True
            unit_dir.rename(displaced)
            replacement.rename(unit_dir)
        return digest

    monkeypatch.setattr(report, "_canonical_digest", replace_while_binding)

    inputs = report.load_report_inputs(root, program_id)
    rendered = report.render_report(
        f"Stage Summary: {program_id}",
        inputs,
        report_kind="stage-summary",
    )

    assert swapped
    assert inputs.claim_sources == []
    assert inputs.missing_units == [unit_id]
    assert "POST-BINDING REPLACEMENT SENTINEL" not in rendered


def test_load_decisions_captures_container_once_and_isolates_bad_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, _unit_id = _make_workspace(tmp_path)
    path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    payload = load_yaml(path)
    payload["items"].append({"id": "bad-sibling", "kind": "not-a-judgement"})
    write_yaml_if_changed(path, payload)
    original_snapshot = judgements_module.snapshot_project_file
    target_captures = 0

    def count_target_capture(project_root, relative_path, **kwargs):
        nonlocal target_captures
        if Path(relative_path).as_posix() == path.relative_to(root).as_posix():
            target_captures += 1
        return original_snapshot(project_root, relative_path, **kwargs)

    monkeypatch.setattr(judgements_module, "snapshot_project_file", count_target_capture)

    decisions = report.load_decisions(root, program_id)

    assert target_captures == 1
    assert [item["title"] for item in decisions] == ["Use the grounded baseline"]


def test_load_decisions_rejects_container_replacement_without_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, _unit_id = _make_workspace(tmp_path)
    path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    displaced = tmp_path / "displaced-decisions.yaml"
    replacement = tmp_path / "replacement-decisions.yaml"
    replacement_payload = load_yaml(path)
    replacement_payload["items"][0]["payload"]["decision"]["text"] = "REPLACEMENT DECISION SENTINEL"
    write_yaml_if_changed(replacement, replacement_payload)
    original_match = report.judgement_confirmation_matches_bound
    swapped = False

    def replace_after_item_capture(*args, **kwargs):
        nonlocal swapped
        result = original_match(*args, **kwargs)
        if not swapped:
            swapped = True
            path.rename(displaced)
            replacement.rename(path)
        return result

    monkeypatch.setattr(report, "judgement_confirmation_matches_bound", replace_after_item_capture)

    decisions = report.load_decisions(root, program_id)

    assert swapped
    assert decisions
    assert all(item["confirmation"] != "confirmed" for item in decisions)
    assert all("REPLACEMENT DECISION SENTINEL" not in item.get("title", "") for item in decisions)


def test_load_decisions_revalidates_container_after_legacy_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, _unit_id = _make_workspace(tmp_path)
    path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    displaced = tmp_path / "displaced-during-legacy.yaml"
    replacement = tmp_path / "replacement-during-legacy.yaml"
    replacement_payload = load_yaml(path)
    replacement_payload["items"][0]["payload"]["decision"]["text"] = "LEGACY-PARSE SENTINEL"
    write_yaml_if_changed(replacement, replacement_payload)
    original_value = report._decision_value
    swapped = False

    def replace_during_legacy(lines, label):
        nonlocal swapped
        result = original_value(lines, label)
        if label == "Decision ID" and not swapped:
            swapped = True
            path.rename(displaced)
            replacement.rename(path)
        return result

    monkeypatch.setattr(report, "_decision_value", replace_during_legacy)

    decisions = report.load_decisions(root, program_id)

    assert swapped
    assert decisions
    assert all(item["confirmation"] != "confirmed" for item in decisions)
    assert all("LEGACY-PARSE SENTINEL" not in item.get("title", "") for item in decisions)


def test_load_decisions_invalid_same_id_sibling_still_suppresses_legacy_duplicate(
    tmp_path: Path,
) -> None:
    report = _load_report_module()
    root = tmp_path / "workspace"
    program_id = "compat-known-ids"
    workflow = root / "kb" / "programs" / program_id / "workflow"
    workflow.mkdir(parents=True)
    write_yaml_if_changed(
        workflow / "decisions.yaml",
        {"items": [{"id": "legacy-duplicate", "kind": "not-a-judgement"}]},
    )
    (workflow / "decision-log.md").write_text(
        "# Decision Log\n\n"
        "## 2026-07-25 · Must stay deduplicated\n\n"
        "- Decision ID: `legacy-duplicate`\n",
        encoding="utf-8",
    )

    assert report.load_decisions(root, program_id) == []


def test_legacy_decision_log_replacement_is_not_rendered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root = tmp_path / "workspace"
    program_id = "legacy-snapshot"
    workflow = root / "kb" / "programs" / program_id / "workflow"
    workflow.mkdir(parents=True)
    legacy_path = workflow / "decision-log.md"
    legacy_path.write_text(
        "# Decision Log\n\n## 2026-07-25 · Stable legacy decision\n\n- Decision ID: `legacy-1`\n",
        encoding="utf-8",
    )
    replacement = tmp_path / "replacement-decision-log.md"
    replacement.write_text(
        "# Decision Log\n\n## 2026-07-25 · REPLACEMENT LEGACY SENTINEL\n",
        encoding="utf-8",
    )
    displaced = tmp_path / "displaced-decision-log.md"
    original_is_current = records_module.ProjectFileSnapshot.is_current
    swapped = False

    def replace_before_legacy_final(snapshot) -> bool:
        nonlocal swapped
        if snapshot.path == legacy_path and not swapped:
            swapped = True
            legacy_path.rename(displaced)
            replacement.rename(legacy_path)
        return original_is_current(snapshot)

    monkeypatch.setattr(
        records_module.ProjectFileSnapshot,
        "is_current",
        replace_before_legacy_final,
    )

    decisions = report.load_decisions(root, program_id)

    assert swapped
    assert decisions == []


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
    assert "## 写作判断与证据" in writing


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
    ordinary_section = weekly[weekly.index("## 报告事件") : weekly.index("## 待确认 / 未核验的判断")]
    pending_section = weekly[weekly.index("## 待确认 / 未核验的判断") :]

    assert "The paper analysis is ready for reporting." in ordinary_section
    assert "A stale legacy diagnosis asserted a likely cause." not in ordinary_section
    assert "A stale legacy diagnosis asserted a likely cause." in pending_section
    assert "当前缺少有效的确认回执或证据绑定" in pending_section
    assert "confirmation_status=confirmed" in inputs.pending_judgement_events[0]["_epistemic_reason"]
    assert "missing: canonical confirmation subject and claim/evidence binding" in inputs.pending_judgement_events[0]["_epistemic_reason"]


def test_outline_produces_evidence_backed_section_skeleton(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)

    outline = report.render_outline(program_id, report.load_report_inputs(root, program_id))

    for heading in ("## 引言", "## 相关工作", "## 方法", "## 实验", "## 结果", "## 讨论", "## 结论"):
        assert heading in outline
    assert "The method improves benchmark success rate." in outline
    assert "Success rate improves by 8 points." in outline


@pytest.mark.parametrize(
    ("operation", "expected_title"),
    [
        ("weekly", "周报"),
        ("stage-summary", "阶段总结"),
        ("ppt-materials", "PPT 素材"),
        ("writing-materials", "写作素材"),
    ],
)
def test_default_report_templates_are_chinese_without_translating_grounded_bytes(
    tmp_path: Path,
    operation: str,
    expected_title: str,
) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)
    inputs = report.load_report_inputs(root, program_id)

    text = report.render_report(
        report.report_title(operation, program_id, language=inputs.language),
        inputs,
        report_kind=operation,
    )

    assert text.startswith(f"# {expected_title}：{program_id}\n")
    assert "## 决策" in text
    assert "## 已确认判断与证据" in text or "## 写作判断与证据" in text or "## 有证据支撑的幻灯片素材" in text
    assert "- 阶段：literature-review" in text
    assert "- 证据 1（来源 p-grounded-123456，page=3）：Success rate improves by 8 points." in text
    assert "The method improves benchmark success rate." in text
    assert "Success rate improves by 8 points." in text
    assert "Grounded review completed" in text
    assert "Use the grounded baseline" in text


def test_default_outline_is_chinese_and_preserves_claim_and_evidence_bytes(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)
    inputs = report.load_report_inputs(root, program_id)

    outline = report.render_outline(program_id, inputs)

    for heading in ("## 引言", "## 相关工作", "## 方法", "## 实验", "## 结果", "## 讨论", "## 结论"):
        assert heading in outline
    assert outline.startswith(f"# 论文大纲：{program_id}\n")
    assert "The method improves benchmark success rate." in outline
    assert "Success rate improves by 8 points." in outline


@pytest.mark.parametrize(
    ("operation", "expected_title", "expected_heading"),
    [
        ("weekly", "Weekly Report", "## Decisions"),
        ("stage-summary", "Stage Summary", "## Confirmed Claims & Evidence"),
        ("ppt-materials", "PPT Materials", "## Evidence-backed Slide Inputs"),
        ("writing-materials", "Writing Materials", "## Writing Claims & Evidence"),
        ("outline", "Paper Outline", "## Introduction"),
    ],
)
def test_language_requires_current_task_bound_selection_and_explicit_english(
    tmp_path: Path,
    operation: str,
    expected_title: str,
    expected_heading: str,
) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)
    profile_path = root / "kb" / "config" / "user-profile.yaml"
    write_yaml_if_changed(
        profile_path,
        {
            "preferences": {"language_preference": "en-US"},
            "personalization": {"reporting_style": "detailed"},
        },
    )
    baseline = report.load_report_inputs(root, program_id)
    assert baseline.language == "zh-CN"
    context = report.report_preference_context(
        program_id,
        operation=operation,
        stage="",
        limit=20,
        inputs=baseline,
    )
    eligible = eligible_preferences(root, skill="report-author", operation=operation)
    language_item = next(
        item for item in eligible["items"] if item["path"] == "profile.preferences.language_preference"
    )
    style_item = next(
        item for item in eligible["items"] if item["path"] == "profile.personalization.reporting_style"
    )
    style_only_id = f"prefsel-report-style-only-{operation}"
    record_effective_selection(
        root,
        {
            "selection_id": style_only_id,
            "skill": "report-author",
            "operation": operation,
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": [
                {
                    "preference_id": style_item["preference_id"],
                    "reason": "detail level is relevant to this report",
                    "application": "render all report inputs",
                }
            ],
            "excluded": [
                {
                    "preference_id": item["preference_id"],
                    "reason": "not relevant to this report",
                }
                for item in eligible["items"]
                if item is not style_item
            ],
        },
    )
    style_only_inputs = report.load_report_inputs(
        root,
        program_id,
        preference_selection_id=style_only_id,
        preference_operation=operation,
    )
    assert style_only_inputs.reporting_style == "detailed"
    assert style_only_inputs.language == "zh-CN"

    selection_id = f"prefsel-report-english-{operation}"
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "report-author",
            "operation": operation,
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": [
                {
                    "preference_id": language_item["preference_id"],
                    "reason": "English is relevant to this report audience",
                    "application": "render this report in English",
                }
            ],
            "excluded": [
                {
                    "preference_id": item["preference_id"],
                    "reason": "not relevant to this report",
                }
                for item in eligible["items"]
                if item is not language_item
            ],
        },
    )

    english_inputs = report.load_report_inputs(
        root,
        program_id,
        preference_selection_id=selection_id,
        preference_operation=operation,
    )
    english = (
        report.render_outline(program_id, english_inputs)
        if operation == "outline"
        else report.render_report(
            report.report_title(operation, program_id, language=english_inputs.language),
            english_inputs,
            report_kind=operation,
        )
    )

    assert english_inputs.language == "en-US"
    assert english.startswith(f"# {expected_title}: {program_id}\n")
    assert expected_heading in english
    assert "Evidence 1 (source p-grounded-123456, page=3): Success rate improves by 8 points." in english
    assert "The method improves benchmark success rate." in english
    assert "Success rate improves by 8 points." in english


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

    assert "缺少：已确认判断" in weekly
    assert "缺少：报告事件" in weekly
    assert "缺少：决策" in weekly
    assert "缺少：相关工作判断与证据" in outline
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
    assert "缺少：判断 claim-0 的证据" in concise
    assert "缺少：判断 claim-0 的证据" in detailed


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


def _assert_aggregate_pending_report(report, inputs, *, absent: list[str]) -> None:
    text = report.render_report("Stage Summary: aggregate-gate", inputs, report_kind="stage-summary")
    assert inputs.formal_lane_pending is True
    assert "待确认 / 未核验" in text
    assert "报告生成期间正式判断来源已变化" in text
    for sentinel in absent:
        assert sentinel not in text


def test_aggregate_gate_rejects_survey_replaced_after_attach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    program_id = "program-survey"
    survey_path, _events_path = _write_confirmed_program_survey(tmp_path, program_id=program_id)
    original_attach = report.attach_confirmed_survey_claim_sources

    def replace_after_attach(*args, **kwargs):
        result = original_attach(*args, **kwargs)
        payload = load_yaml(survey_path)
        payload["slug"] = "replacement-survey"
        write_yaml_if_changed(survey_path, payload)
        return result

    monkeypatch.setattr(report, "attach_confirmed_survey_claim_sources", replace_after_attach)

    inputs = report.load_report_inputs(tmp_path, program_id, stage="survey")

    _assert_aggregate_pending_report(
        report,
        inputs,
        absent=["Agent-authored survey judgement", SURVEY_QUOTE],
    )


def test_aggregate_gate_rejects_unit_replaced_after_source_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    record_path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
    original_load = report.load_confirmed_claim_sources

    def replace_after_source_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        payload = load_yaml(record_path)
        payload["title"] = "REPLACEMENT UNIT TITLE"
        write_yaml_if_changed(record_path, payload)
        return result

    monkeypatch.setattr(report, "load_confirmed_claim_sources", replace_after_source_load)

    inputs = report.load_report_inputs(root, program_id)

    _assert_aggregate_pending_report(
        report,
        inputs,
        absent=["Grounded Paper", "The method improves benchmark success rate."],
    )


def test_aggregate_gate_rejects_local_evidence_replaced_after_source_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    evidence_path = root / "kb" / "units" / "papers" / unit_id / "parse-cache.yaml"
    original_load = report.load_confirmed_claim_sources

    def replace_evidence_after_source_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        write_yaml_if_changed(evidence_path, {"chunks": [{"label": "page-3", "text": "Changed evidence."}]})
        return result

    monkeypatch.setattr(report, "load_confirmed_claim_sources", replace_evidence_after_source_load)

    inputs = report.load_report_inputs(root, program_id)

    _assert_aggregate_pending_report(
        report,
        inputs,
        absent=["Grounded Paper", "The method improves benchmark success rate."],
    )


def test_aggregate_gate_rejects_external_repo_evidence_replaced_after_source_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root = tmp_path / "workspace"
    program_id = "external-evidence-report"
    unit_id = "r-external-evidence-123456"
    workflow = root / "kb" / "programs" / program_id / "workflow"
    workflow.mkdir(parents=True)
    write_yaml_if_changed(
        root / "kb" / "programs" / program_id / "state.yaml",
        {"program_id": program_id, "active_unit_ids": [unit_id]},
    )
    write_yaml_if_changed(workflow / "reporting-events.yaml", {"items": []})
    evidence_path = _write_confirmed_repo_record(root, unit_id)
    original_load = report.load_confirmed_claim_sources

    def replace_external_evidence_after_source_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        evidence_path.write_text("Replacement external repo bytes.", encoding="utf-8")
        return result

    monkeypatch.setattr(
        report,
        "load_confirmed_claim_sources",
        replace_external_evidence_after_source_load,
    )

    inputs = report.load_report_inputs(root, program_id)

    _assert_aggregate_pending_report(
        report,
        inputs,
        absent=["External Evidence Repo", "external repository supports the selected route"],
    )


def test_aggregate_gate_rejects_direct_decision_replaced_after_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, _unit_id = _make_workspace(tmp_path)
    decisions_path = root / "kb" / "programs" / program_id / "workflow" / "decisions.yaml"
    original_load = report.load_decisions

    def replace_after_decision_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        payload = load_yaml(decisions_path)
        payload["items"][0]["payload"]["decision"]["text"] = "REPLACEMENT DECISION"
        write_yaml_if_changed(decisions_path, payload)
        return result

    monkeypatch.setattr(report, "load_decisions", replace_after_decision_load)

    inputs = report.load_report_inputs(root, program_id)

    _assert_aggregate_pending_report(
        report,
        inputs,
        absent=["Use the grounded baseline", "The method improves benchmark success rate."],
    )


def test_final_gate_discards_text_built_before_source_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    inputs = report.load_report_inputs(root, program_id)
    record_path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
    original_render = report._render_report_document
    swapped = False

    def replace_after_text_construction(*args, **kwargs):
        nonlocal swapped
        text = original_render(*args, **kwargs)
        if not swapped:
            swapped = True
            payload = load_yaml(record_path)
            payload["title"] = "REPLACEMENT AFTER RENDER"
            write_yaml_if_changed(record_path, payload)
        return text

    monkeypatch.setattr(report, "_render_report_document", replace_after_text_construction)

    text = report.render_report("Stage Summary: aggregate-gate", inputs, report_kind="stage-summary")

    assert swapped
    assert "报告生成期间正式判断来源已变化" in text
    assert "Grounded Paper" not in text
    assert "The method improves benchmark success rate." not in text
    assert "Use the grounded baseline" not in text


@pytest.mark.parametrize("event_count", [4, 8, 16])
def test_report_side_event_batch_capture_and_resolution_are_linear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_count: int,
) -> None:
    report = _load_report_module()
    report_program_id = "aggregate-events"
    report_workflow = tmp_path / "kb" / "programs" / report_program_id / "workflow"
    report_workflow.mkdir(parents=True)
    write_yaml_if_changed(
        tmp_path / "kb" / "programs" / report_program_id / "state.yaml",
        {"program_id": report_program_id, "active_unit_ids": []},
    )
    events = []
    for index in range(event_count):
        program_id = f"side-event-{index}"
        program_root = tmp_path / "kb" / "programs" / program_id
        workflow = program_root / "workflow"
        workflow.mkdir(parents=True)
        evidence_path = workflow / "evidence.md"
        evidence_path.write_text(f"grounded evidence {index}", encoding="utf-8")
        decision = {
            "id": f"decision-side-event-{index}",
            "kind": "program_decision",
            "owner": "research-orchestrator",
            "program_id": program_id,
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["evaluation", "unverified"],
            "payload": {
                "decision": {"text": f"Choose route {index}"},
                "claims": [
                    {
                        "id": f"claim-side-event-{index}",
                        "text": f"Route {index} is grounded.",
                        "claim_type": "evaluation",
                        "confirmation_status": "pending_user_confirmation",
                        "evidence_refs": [
                            {
                                "source_unit_id": f"program:{program_id}",
                                "artifact": "workflow/evidence.md",
                                "locator": "line:1",
                                "quote": f"grounded evidence {index}",
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
            evidence=[f"Reviewed side event {index}."],
            user_authorization=f"Confirm side event {index}.",
            authorization_source="user_message",
            project_root=tmp_path,
            verification_root=program_root,
            trusted_source_roots=roots,
        )
        decisions_path = workflow / "decisions.yaml"
        write_yaml_if_changed(decisions_path, {"items": [decision]})
        events.append(
            {
                "event_type": "decision-confirmed",
                "confirmation_status": "confirmed",
                "confirmation_binding": confirmation_binding(
                    decision,
                    owner="research-orchestrator",
                    path=decisions_path.relative_to(tmp_path).as_posix(),
                ),
            }
        )
    write_yaml_if_changed(report_workflow / "reporting-events.yaml", {"items": events})

    original_snapshot = judgements_module.snapshot_project_file
    captures = 0

    def count_snapshot(*args, **kwargs):
        nonlocal captures
        captures += 1
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(judgements_module, "snapshot_project_file", count_snapshot)

    inputs = report.load_report_inputs(tmp_path, report_program_id)

    assert captures == event_count
    assert len(inputs.events) == event_count
    assert all(event["_effective_confirmation_status"] == "confirmed" for event in inputs.events)
    assert inputs.formal_lane_pending is False
    assert inputs.formal_inputs_are_current()
    assert captures == event_count


@pytest.mark.skipif(not Path("/private/var").exists(), reason="macOS /var alias contract")
def test_confirmed_survey_report_accepts_var_alias_root(tmp_path: Path) -> None:
    canonical_root = tmp_path.resolve()
    if not str(canonical_root).startswith("/private/var/"):
        pytest.skip("temporary directory is not under the macOS /var alias")
    alias_root = Path("/var") / canonical_root.relative_to("/private/var")
    report = _load_report_module()
    program_id = "program-survey"
    _write_confirmed_program_survey(canonical_root, program_id=program_id)

    inputs = report.load_report_inputs(alias_root, program_id, stage="survey")
    text = report.render_report(
        f"Stage Summary: {program_id}",
        inputs,
        report_kind="stage-summary",
    )

    assert inputs.formal_lane_pending is False
    assert "Agent-authored survey judgement for background_terms-1." in text
    assert SURVEY_QUOTE in text
    assert "Pending / Unverified" not in text


def test_report_input_snapshot_never_serializes_validators(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _unit_id = _make_workspace(tmp_path)
    inputs = report.load_report_inputs(root, program_id)
    snapshot = report.report_input_snapshot(inputs)

    def assert_no_callable(value) -> None:
        assert not callable(value)
        if isinstance(value, dict):
            for child in value.values():
                assert_no_callable(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_callable(child)

    assert_no_callable(snapshot)
    serialized = report.json.dumps(snapshot, sort_keys=True, default=str)

    assert "validator" not in serialized


def _report_output_path(root: Path, program_id: str, command: str) -> Path:
    if command == "weekly":
        return root / "kb" / "programs" / program_id / "reports" / "weekly.md"
    if command == "stage-summary":
        return root / "kb" / "programs" / program_id / "reports" / "stage-summary.md"
    if command == "outline":
        return root / "kb" / "programs" / program_id / "reports" / "paper-outline.md"
    suffix = "ppt-materials" if command == "ppt-materials" else "writing-materials"
    return root / "kb" / "user" / "report-materials" / f"{program_id}-{suffix}.md"


def _replace_report_source(record_path: Path, mutation: str) -> None:
    if mutation == "content":
        payload = load_yaml(record_path)
        payload["title"] = "REPLACEMENT DURING PUBLICATION"
        write_yaml_if_changed(record_path, payload)
        return
    before = record_path.stat()
    replacement = record_path.with_name(".record-publication-replacement.yaml")
    replacement.write_bytes(record_path.read_bytes())
    replacement.replace(record_path)
    after = record_path.stat()
    assert (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)


@pytest.mark.parametrize(
    ("command", "renderer"),
    [
        ("weekly", "render_report"),
        ("stage-summary", "render_report"),
        ("ppt-materials", "render_report"),
        ("writing-materials", "render_report"),
        ("outline", "render_outline"),
    ],
)
@pytest.mark.parametrize("mutation", ["content", "same-bytes-new-inode"])
def test_cli_rechecks_after_render_before_publishing_any_report_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    renderer: str,
    mutation: str,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    record_path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
    original_render = getattr(report, renderer)
    original_load = report.load_report_inputs
    replaced = False

    def replace_after_render(*args, **kwargs):
        nonlocal replaced
        text = original_render(*args, **kwargs)
        if not replaced:
            replaced = True
            _replace_report_source(record_path, mutation)
        return text

    def load_with_preference_binding(*args, **kwargs):
        inputs = original_load(*args, **kwargs)
        inputs.preference_binding = {"selection_id": "test-publication-preference"}
        return inputs

    monkeypatch.setattr(report, renderer, replace_after_render)
    monkeypatch.setattr(report, "load_report_inputs", load_with_preference_binding)
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["report.py", "--root", str(root), command, "--program-id", program_id],
    )

    assert report.main() == 0

    text = _report_output_path(root, program_id, command).read_text(encoding="utf-8")
    assert replaced
    assert text.startswith("<!-- effective-preferences:")
    assert "报告生成期间正式判断来源已变化" in text
    assert "Grounded Paper" not in text
    assert "The method improves benchmark success rate." not in text
    assert "Use the grounded baseline" not in text
    assert "The paper analysis is ready for reporting." in text


@pytest.mark.parametrize("mutation", ["content", "same-bytes-new-inode"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_cli_post_write_gate_rolls_back_exact_report_before_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    preexisting: bool,
) -> None:
    report = _load_report_module()
    root, program_id, unit_id = _make_workspace(tmp_path)
    record_path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
    output = _report_output_path(root, program_id, "weekly")
    if preexisting:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"exact report before-image\n")
        output.chmod(0o640)
    original_write = report.write_text_if_changed
    replaced = False

    def replace_after_write(path: Path, text: str) -> None:
        nonlocal replaced
        original_write(path, text)
        if not replaced:
            replaced = True
            _replace_report_source(record_path, mutation)

    monkeypatch.setattr(report, "write_text_if_changed", replace_after_write)
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["report.py", "--root", str(root), "weekly", "--program-id", program_id],
    )

    with pytest.raises(RuntimeError, match="formal report inputs changed during publication"):
        report.main()

    assert replaced
    if preexisting:
        assert output.read_bytes() == b"exact report before-image\n"
        assert output.stat().st_mode & 0o777 == 0o640
    else:
        assert not output.exists()


@pytest.mark.parametrize("unit_count", [4, 8, 16])
def test_unit_claim_source_snapshot_enumeration_is_linear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unit_count: int,
) -> None:
    report = _load_report_module()
    unit_ids = [f"p-linear-{index:02d}" for index in range(unit_count)]
    for unit_id in unit_ids:
        write_yaml_if_changed(
            tmp_path / "kb" / "units" / "papers" / unit_id / "record.yaml",
            {"id": unit_id, "kind": "paper", "title": unit_id, "payload": {"claims": []}},
        )
    original_iter = report.iter_canonical_record_snapshots
    yields = 0

    def count_yields(*args, **kwargs):
        nonlocal yields
        for snapshot in original_iter(*args, **kwargs):
            yields += 1
            yield snapshot

    monkeypatch.setattr(report, "iter_canonical_record_snapshots", count_yields)

    sources, missing = report.load_confirmed_claim_sources(tmp_path, [*unit_ids, unit_ids[0]])

    assert [source.unit_id for source in sources] == unit_ids
    assert missing == []
    assert yields == unit_count


def test_unit_claim_source_duplicate_identity_fails_closed(tmp_path: Path) -> None:
    report = _load_report_module()
    unit_id = "duplicate-unit"
    record = {"id": unit_id, "title": "Ambiguous", "payload": {"claims": []}}
    write_yaml_if_changed(
        tmp_path / "kb" / "units" / "papers" / unit_id / "record.yaml",
        {**record, "kind": "paper"},
    )
    write_yaml_if_changed(
        tmp_path / "kb" / "units" / "repos" / unit_id / "record.yaml",
        {**record, "kind": "repo"},
    )

    sources, missing = report.load_confirmed_claim_sources(tmp_path, [unit_id, unit_id])

    assert sources == []
    assert missing == [unit_id]


def test_pending_issue_and_factual_lanes_survive_without_formal_claims() -> None:
    report = _load_report_module()
    inputs = report.ReportInputs(
        events=[
            {
                "event_type": "operational",
                "title": "Factual milestone",
                "summary": "The local run completed.",
            }
        ],
        pending_judgement_events=[
            {
                "event_type": "decision",
                "title": "Pending route",
                "summary": "Awaiting a user choice.",
            }
        ],
        claim_sources=[
            report.ClaimSource(
                unit_id="p-issues-only",
                title="Issues-only source",
                kind="paper",
                issues=["canonical claims are not bound to a current ConfirmationReceipt"],
            )
        ],
    )

    text = report.render_report("Stage Summary: lanes", inputs, report_kind="stage-summary")

    assert "The local run completed." in text
    assert "Awaiting a user choice." in text
    assert "Issues-only source" in text
    assert "结构或证据核验未通过" in text


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

    assert "## 相关工作：已确认判断与证据" in text
    assert "Success rate improves by 8 points." in text
    for token in ("python3 ", ".agents/skills/", "--program-id", "${", "NEXT FOR AGENT:"):
        assert token not in stdout

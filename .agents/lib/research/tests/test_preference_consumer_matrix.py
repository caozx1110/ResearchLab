from __future__ import annotations

import argparse
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.paths import config_root, runtime_preferences_path
from research.preference_selection import eligible_preferences, record_effective_selection
from research.core import default_record, record_path
from research.prefs import default_runtime_preferences, ensure_workspace


def _script(skill: str, filename: str):
    root = Path(__file__).resolve().parents[4]
    path = root / ".agents" / "skills" / skill / "scripts" / filename
    name = f"preference_matrix_{skill.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {
            "personalization": {"reporting_style": "concise"},
            "resources": {"gpu_count": 1},
            "constraints": ["no cloud upload"],
        },
    )
    runtime = default_runtime_preferences()
    runtime["paper"]["screening_context_pages"] = 2
    write_yaml_if_changed(runtime_preferences_path(root), runtime)
    return root


def _record(
    root: Path,
    *,
    selection_id: str,
    skill: str,
    operation: str,
    task_context: dict[str, object],
    selected_paths: set[str],
) -> str:
    eligible = eligible_preferences(root, skill=skill, operation=operation)
    selected = []
    excluded = []
    for item in eligible["items"]:
        path = str(item["path"])
        if str(item["strength"]) == "hard" or path in selected_paths:
            selected.append(
                {
                    "preference_id": item["preference_id"],
                    "reason": "relevant to this bounded operation",
                    "application": "apply within the declared consumer policy",
                }
            )
        else:
            excluded.append(
                {"preference_id": item["preference_id"], "reason": "not relevant to this operation"}
            )
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": skill,
            "operation": operation,
            "catalog_digest": eligible["catalog_digest"],
            "task_context": task_context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    return selection_id


def test_real_report_consumer_is_neutral_until_selected_and_rejects_wrong_binding(tmp_path: Path) -> None:
    report = _script("report-author", "report.py")
    root = _workspace(tmp_path)
    context = report.report_preference_context("program-a", operation="weekly", stage="", limit=20)
    selection_id = _record(
        root,
        selection_id="prefsel-matrix-report",
        skill="report-author",
        operation="weekly",
        task_context=context,
        selected_paths={"profile.personalization.reporting_style"},
    )

    assert report.load_reporting_style(root, operation="weekly", canonical_inputs=context) == "default"
    assert (
        report.load_reporting_style(
            root,
            preference_selection_id=selection_id,
            operation="weekly",
            canonical_inputs=context,
        )
        == "concise"
    )
    with pytest.raises(ValueError, match="another operation"):
        report.load_reporting_style(
            root,
            preference_selection_id=selection_id,
            operation="stage-summary",
            canonical_inputs=report.report_preference_context(
                "program-a", operation="stage-summary", stage="", limit=20
            ),
        )
    with pytest.raises(ValueError, match="another task"):
        report.load_reporting_style(
            root,
            preference_selection_id=selection_id,
            operation="weekly",
            canonical_inputs=report.report_preference_context(
                "program-b", operation="weekly", stage="", limit=20
            ),
        )


def test_real_source_and_paper_consumers_do_not_direct_read_runtime_soft_preferences(tmp_path: Path) -> None:
    intake = _script("source-intake", "intake.py")
    paper = _script("paper-analyst", "paper.py")
    root = _workspace(tmp_path)
    intake_args = argparse.Namespace(
        kind="paper",
        maturity="lightweight",
        stage_id="",
        candidate_id="",
        preference_selection_id="",
    )
    assert intake.resolve_intake_preferences(root, intake_args, source="paper.pdf", title="Paper") == ({}, {})
    intake_context = intake.intake_preference_context(intake_args, source="paper.pdf", title="Paper")
    intake_args.preference_selection_id = _record(
        root,
        selection_id="prefsel-matrix-intake",
        skill="source-intake",
        operation="add",
        task_context=intake_context,
        selected_paths={"runtime.paper"},
    )
    selected_paper, binding = intake.resolve_intake_preferences(
        root, intake_args, source="paper.pdf", title="Paper"
    )
    assert selected_paper["screening_context_pages"] == 2
    assert binding["selection_id"] == "prefsel-matrix-intake"

    record = {"id": "paper-1", "sources": [], "payload": {"basic_info": {"title": "Paper"}}}
    paper_args = argparse.Namespace(
        command="screen",
        phase="prepare",
        mode="auto",
        force=False,
        preference_selection_id="",
    )
    assert paper.resolve_paper_preferences(root, paper_args, record) == ({}, {}, {})
    paper_args.preference_selection_id = _record(
        root,
        selection_id="prefsel-matrix-paper",
        skill="paper-analyst",
        operation="screen",
        task_context=paper.paper_preference_context(paper_args, record),
        selected_paths={"runtime.paper"},
    )
    selected_paper, selected_pdf, binding = paper.resolve_paper_preferences(root, paper_args, record)
    assert selected_paper["screening_context_pages"] == 2
    assert selected_pdf == {}
    assert binding["operation"] == "screen"


def test_catalog_change_stales_real_report_consumer_and_hard_resource_stays_eligible(tmp_path: Path) -> None:
    report = _script("report-author", "report.py")
    method = _script("method-designer", "method.py")
    root = _workspace(tmp_path)
    context = report.report_preference_context("program-a", operation="weekly", stage="", limit=20)
    selection_id = _record(
        root,
        selection_id="prefsel-matrix-stale",
        skill="report-author",
        operation="weekly",
        task_context=context,
        selected_paths={"profile.personalization.reporting_style"},
    )
    profile_path = config_root(root) / "user-profile.yaml"
    write_yaml_if_changed(
        profile_path,
        {
            "personalization": {"reporting_style": "detailed"},
            "resources": {"gpu_count": 1},
            "constraints": ["no cloud upload"],
        },
    )
    with pytest.raises(ValueError, match="stale catalog"):
        report.load_reporting_style(
            root,
            preference_selection_id=selection_id,
            operation="weekly",
            canonical_inputs=context,
        )

    resources = method.profile_resources(root)
    assert resources == {"gpu_count": 1}
    assert method.profile_constraints(root) == ["no cloud upload"]
    assert method.resource_capacity(resources)["source"] == "profile.resources"
    hard = eligible_preferences(root, skill="experiment-workbench", operation="plan")
    assert {item["path"] for item in hard["items"] if item["strength"] == "hard"} == {
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
    }


def test_literature_synthesis_persists_selected_binding_and_hard_fallback(
    tmp_path: Path,
) -> None:
    synth = _script("literature-synthesizer", "synthesize.py")
    root = _workspace(tmp_path)
    context = synth.synthesis_preference_context(
        query="robot learning",
        kind="paper",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-24",
        program_ids=[],
    )
    selection_id = _record(
        root,
        selection_id="prefsel-matrix-synthesis",
        skill="literature-synthesizer",
        operation="synthesize",
        task_context=context,
        selected_paths={"profile.personalization.reporting_style"},
    )
    selected = synth.resolve_synthesis_preferences(
        root,
        selection_id=selection_id,
        query="robot learning",
        kind="paper",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-24",
        program_ids=[],
    )
    assert {item["path"] for item in selected["soft_items"]} == {
        "profile.personalization.reporting_style"
    }
    assert selected["values_by_path"]["profile.constraints"] == ["no cloud upload"]
    preference_context = synth.synthesis_preference_state(selected)
    binding = synth.ensure_evidence_gap_composite(
        root,
        slug="robot-learning",
        filters={"query": "robot learning", "kind": "paper", "topic": "", "tag": "", "pool": ""},
        as_of="2026-07-24",
        preference_context=preference_context,
    )
    state = load_yaml(root / str(binding["state_path"]))
    assert state["stages"][0]["inputs"][0]["context"] == preference_context

    with pytest.raises(SystemExit, match="another task"):
        synth.resolve_synthesis_preferences(
            root,
            selection_id=selection_id,
            query="another question",
            kind="paper",
            topic="",
            tag="",
            pool="",
            mode="survey",
            as_of="2026-07-24",
            program_ids=[],
        )


def test_experiment_consumers_bind_each_operation_and_neutral_keeps_hard_context(
    tmp_path: Path,
) -> None:
    experiment = _script("experiment-workbench", "experiment.py")
    root = _workspace(tmp_path)
    runtime = load_yaml(runtime_preferences_path(root))
    runtime["learned_preferences"]["items"] = [
        {
            "id": "experiment-format",
            "text": "keep operation notes compact",
            "source": "user",
            "skill": "experiment-workbench",
            "operations": ["plan", "log-run", "follow-up", "diagnose"],
        }
    ]
    write_yaml_if_changed(runtime_preferences_path(root), runtime)

    plan_args = experiment.build_parser().parse_args(
        ["plan", "--title", "preference route", "--program-id", "program-a", "--goal", "measure"]
    )
    neutral = experiment.resolve_experiment_preferences(root, plan_args)
    assert neutral["soft_items"] == []
    assert set(neutral["values_by_path"]) == {
        "profile.resources",
        "profile.constraints",
        "runtime.autonomy.auto_execute_scope",
    }
    plan_args.preference_selection_id = _record(
        root,
        selection_id="prefsel-experiment-plan",
        skill="experiment-workbench",
        operation="plan",
        task_context=experiment.experiment_preference_context(plan_args),
        selected_paths={"learned.experiment-format"},
    )
    assert experiment._dispatch(plan_args, root) == 0
    record_path = next((root / "kb/units/experiments").glob("*/record.yaml"))
    record = load_yaml(record_path)
    experiment_id = str(record["id"])
    assert record["payload"]["preference_contexts"]["plan"]["selection_binding"]["selection_id"] == plan_args.preference_selection_id

    operation_args = [
        experiment.build_parser().parse_args(
            [
                "log-run",
                "--experiment-id",
                experiment_id,
                "--result-summary",
                "completed",
                "--config-revision",
                "config-v1",
            ]
        ),
        experiment.build_parser().parse_args(
            ["follow-up", "--experiment-id", experiment_id, "--action", "inspect metrics"]
        ),
        experiment.build_parser().parse_args(
            ["diagnose", "--experiment-id", experiment_id, "--summary", "inspect failure"]
        ),
    ]
    for index, args in enumerate(operation_args, start=1):
        current = load_yaml(record_path)
        prepared = experiment.prepare_experiment_preference_inputs(
            root,
            args,
            current,
            record_path.parent,
        )
        args.preference_selection_id = _record(
            root,
            selection_id=f"prefsel-experiment-op-{index}",
            skill="experiment-workbench",
            operation=args.command,
            task_context=experiment.experiment_preference_context(args, current, prepared),
            selected_paths={"learned.experiment-format"},
        )
        assert experiment._dispatch(args, root) == 0

    run_log = load_yaml(record_path.parent / "run-log.yaml")
    follow_ups = load_yaml(record_path.parent / "follow-ups.yaml")
    diagnosis_fill = load_yaml(record_path.parent / "diagnosis-fill.yaml")
    assert run_log["items"][-1]["preference_context"]["selection_binding"]["operation"] == "log-run"
    assert follow_ups["items"][-1]["preference_context"]["selection_binding"]["operation"] == "follow-up"
    assert diagnosis_fill["preference_context"]["selection_binding"]["operation"] == "diagnose"

    wrong = experiment.build_parser().parse_args(
        ["follow-up", "--experiment-id", experiment_id, "--action", "wrong binding"]
    )
    wrong.preference_selection_id = plan_args.preference_selection_id
    with pytest.raises(SystemExit, match="another operation"):
        experiment.resolve_experiment_preferences(root, wrong, load_yaml(record_path))


def test_method_design_consumed_input_mutation_matrix_rejects_old_selection(
    tmp_path: Path,
) -> None:
    method = _script("method-designer", "method.py")
    root = _workspace(tmp_path)
    idea_id = "i-preference-method-matrix"
    repo_id = "r-preference-method-matrix"
    idea = default_record(
        "idea", title="Bound method idea", maturity="lightweight", source={"original_uri": "discussion"}
    )
    idea["id"] = idea_id
    idea["status"] = "selected"
    idea["payload"]["analysis"]["risks"] = ["base risk"]
    repo = default_record(
        "repo", title="Bound repository", maturity="lightweight", source={"original_uri": "https://example.com/repo"}
    )
    repo["id"] = repo_id
    repo["summary"] = "canonical repository summary"
    write_yaml_if_changed(record_path(root, "idea", idea_id), idea)
    repo_path = record_path(root, "repo", repo_id)
    write_yaml_if_changed(repo_path, repo)
    state = method.default_program_state("program-method-matrix")
    base_values = {
        "repo_ids": [repo_id],
        "interfaces": [{"name": "adapter", "detail": "insert after encoder"}],
        "baselines": ["repo baseline"],
        "metrics": ["success rate"],
        "risks": ["base risk"],
    }

    def task_inputs(
        *,
        idea_record: dict | None = None,
        state_value: dict | None = None,
        values: dict | None = None,
    ) -> dict[str, object]:
        selected = values or base_values
        return method.method_preference_task_inputs(
            root,
            idea_record or idea,
            program_id="program-method-matrix",
            idea_id=idea_id,
            state=state_value or state,
            **selected,
        )

    cases = ["idea", "repo_ids", "interfaces", "baselines", "metrics", "risks", "program_state", "repo_corpus"]
    for index, field in enumerate(cases, start=1):
        base = task_inputs()
        selection_id = _record(
            root,
            selection_id=f"prefsel-method-mutation-{index}",
            skill="method-designer",
            operation="design",
            task_context=method.method_preference_context(base),
            selected_paths=set(),
        )
        changed_idea = copy.deepcopy(idea)
        changed_state = copy.deepcopy(state)
        changed_values = copy.deepcopy(base_values)
        if field == "idea":
            changed_idea["summary"] = "changed idea bytes"
        elif field == "program_state":
            changed_state["active_unit_ids"] = [repo_id]
        elif field == "repo_corpus":
            changed_repo = copy.deepcopy(repo)
            changed_repo["summary"] = "changed canonical repository bytes"
            write_yaml_if_changed(repo_path, changed_repo)
        else:
            changed_values[field] = [f"changed {field}"]
        changed = task_inputs(
            idea_record=changed_idea,
            state_value=changed_state,
            values=changed_values,
        )
        if field == "repo_corpus":
            write_yaml_if_changed(repo_path, repo)
        assert method.method_preference_context(changed) != method.method_preference_context(base), field
        with pytest.raises(SystemExit, match="another task"):
            method.resolve_method_preferences(
                root,
                task_inputs=changed,
                selection_id=selection_id,
            )


def test_experiment_operation_consumed_input_mutation_matrix_rejects_old_selection(
    tmp_path: Path,
) -> None:
    experiment = _script("experiment-workbench", "experiment.py")
    root = _workspace(tmp_path)
    unit_root = root / "kb/units/experiments/x-preference-matrix"
    unit_root.mkdir(parents=True)
    artifact = root / "artifact.bin"
    artifact.write_bytes(b"artifact-v1")
    claims_path = root / "claims.yaml"
    write_yaml_if_changed(claims_path, {"claims": []})
    record = default_record(
        "experiment", title="Preference matrix", maturity="lightweight", source={"original_uri": "program:p"}
    )
    record["id"] = "x-preference-matrix"
    record["payload"]["process"]["tested_hypothesis"] = "record hypothesis"

    operation_cases = {
        "plan": ["title", "program_id", "goal", "idea_id", "hypothesis"],
        "log-run": [
            "experiment_id",
            "record",
            "change",
            "metric",
            "result_summary",
            "next_action",
            "artifact_identity",
            "artifact_content",
            "artifact_status",
            "outcome",
            "classification",
            "why_this_run",
            "tested_hypothesis",
            "tag",
            "recent_runs",
            "config_revision",
            "seed",
            "rerun",
            "rerun_reason",
            "prior_runs",
        ],
        "follow-up": ["experiment_id", "record", "action", "category", "priority", "status", "evidence_needed"],
        "diagnose": [
            "experiment_id",
            "record",
            "summary",
            "category",
            "likely_cause",
            "ruled_out",
            "unknown",
            "next_action",
            "recent_runs",
            "claims_identity",
            "claims_content",
            "claims_status",
            "runs",
        ],
    }

    def args_for(operation: str):
        if operation == "plan":
            return experiment.build_parser().parse_args(
                ["plan", "--title", "bound plan", "--program-id", "p", "--goal", "measure", "--idea-id", "i", "--hypothesis", "h"]
            )
        if operation == "log-run":
            return experiment.build_parser().parse_args(
                [
                    "log-run", "--experiment-id", record["id"], "--change", "adapter", "--metric", "score=1",
                    "--result-summary", "completed", "--next-action", "inspect", "--artifact", "artifact.bin",
                    "--outcome", "partial", "--classification", "method", "--why-this-run", "ablation",
                    "--tested-hypothesis", "explicit hypothesis", "--tag", "baseline", "--recent-runs", "3",
                    "--config-revision", "config-v1", "--seed", "7", "--rerun", "--rerun-reason", "controlled repeat",
                ]
            )
        if operation == "follow-up":
            return experiment.build_parser().parse_args(
                [
                    "follow-up", "--experiment-id", record["id"], "--action", "inspect metrics",
                    "--category", "evaluation", "--priority", "high", "--status", "blocked",
                    "--evidence-needed", "failure trace",
                ]
            )
        return experiment.build_parser().parse_args(
            [
                "diagnose", "--experiment-id", record["id"], "--summary", "failure summary",
                "--category", "implementation", "--likely-cause", "cache", "--ruled-out", "data",
                "--unknown", "seed effect", "--next-action", "rerun", "--recent-runs", "3",
                "--claims-file", str(claims_path),
            ]
        )

    index = 0
    for operation, fields in operation_cases.items():
        for field in fields:
            index += 1
            args = args_for(operation)
            prepared = experiment.prepare_experiment_preference_inputs(root, args, record, unit_root)
            base_context = experiment.experiment_preference_context(args, record, prepared)
            selection_id = _record(
                root,
                selection_id=f"prefsel-experiment-mutation-{index}",
                skill="experiment-workbench",
                operation=operation,
                task_context=base_context,
                selected_paths=set(),
            )
            changed_args = copy.deepcopy(args)
            changed_record = copy.deepcopy(record)
            changed_prepared = copy.deepcopy(prepared)
            if field == "record":
                changed_record["title"] = "changed canonical record title"
            elif field == "artifact_identity":
                changed_prepared["artifact_facts"][0]["identity_digest"] = "a" * 64
            elif field == "artifact_content":
                changed_prepared["artifact_facts"][0]["content_digest"] = "b" * 64
            elif field == "artifact_status":
                changed_prepared["artifact_facts"][0]["status"] = "missing"
            elif field == "prior_runs":
                changed_prepared["prior_runs"] = [{"id": "run-prior"}]
            elif field == "claims_identity":
                changed_prepared["claims_file_fact"]["identity_digest"] = "c" * 64
            elif field == "claims_content":
                changed_prepared["claims_file_fact"]["content_digest"] = "d" * 64
            elif field == "claims_status":
                changed_prepared["claims_file_fact"]["status"] = "missing"
            elif field == "runs":
                changed_prepared["runs"] = [{"id": "run-prior"}]
            else:
                current = getattr(changed_args, field)
                if isinstance(current, list):
                    setattr(changed_args, field, [*current, f"changed-{field}"])
                elif isinstance(current, bool):
                    setattr(changed_args, field, not current)
                elif isinstance(current, int):
                    setattr(changed_args, field, current + 1)
                else:
                    setattr(changed_args, field, f"changed-{field}")
                if field == "tested_hypothesis":
                    changed_prepared["tested_hypothesis"] = changed_args.tested_hypothesis
            changed_context = experiment.experiment_preference_context(
                changed_args,
                changed_record,
                changed_prepared,
            )
            assert changed_context != base_context, f"{operation}:{field}"
            changed_args.preference_selection_id = selection_id
            with pytest.raises(SystemExit, match="another task"):
                experiment.resolve_experiment_preferences(
                    root,
                    changed_args,
                    changed_record,
                    changed_prepared,
                )


def test_experiment_stale_receipts_write_no_run_follow_up_or_diagnosis_artifacts(
    tmp_path: Path,
) -> None:
    experiment = _script("experiment-workbench", "experiment.py")
    root = _workspace(tmp_path)
    plan = experiment.build_parser().parse_args(
        ["plan", "--title", "stale write gate", "--program-id", "program-stale"]
    )
    assert experiment._dispatch(plan, root) == 0
    path = next((root / "kb/units/experiments").glob("*/record.yaml"))
    record = load_yaml(path)
    experiment_id = str(record["id"])
    artifact = root / "bound-artifact.txt"
    artifact.write_text("v1", encoding="utf-8")

    log_args = experiment.build_parser().parse_args(
        [
            "log-run", "--experiment-id", experiment_id, "--result-summary", "done",
            "--artifact", "bound-artifact.txt", "--config-revision", "config-v1",
        ]
    )
    log_prepared = experiment.prepare_experiment_preference_inputs(root, log_args, record, path.parent)
    log_args.preference_selection_id = _record(
        root,
        selection_id="prefsel-stale-log-write-gate",
        skill="experiment-workbench",
        operation="log-run",
        task_context=experiment.experiment_preference_context(log_args, record, log_prepared),
        selected_paths=set(),
    )
    artifact.write_text("v2", encoding="utf-8")
    with pytest.raises(SystemExit, match="another task"):
        experiment._dispatch(log_args, root)
    assert not (path.parent / "runs").exists()
    assert not (path.parent / "run-log.yaml").exists()
    assert load_yaml(path) == record

    follow_args = experiment.build_parser().parse_args(
        ["follow-up", "--experiment-id", experiment_id, "--action", "inspect"]
    )
    follow_args.preference_selection_id = _record(
        root,
        selection_id="prefsel-stale-follow-write-gate",
        skill="experiment-workbench",
        operation="follow-up",
        task_context=experiment.experiment_preference_context(follow_args, record),
        selected_paths=set(),
    )
    follow_args.evidence_needed = ["new evidence"]
    with pytest.raises(SystemExit, match="another task"):
        experiment._dispatch(follow_args, root)
    assert not (path.parent / "follow-ups.yaml").exists()
    assert load_yaml(path) == record

    claims = root / "diagnosis-claims.yaml"
    write_yaml_if_changed(claims, {"claims": []})
    diagnose_args = experiment.build_parser().parse_args(
        ["diagnose", "--experiment-id", experiment_id, "--claims-file", str(claims)]
    )
    diagnose_prepared = experiment.prepare_experiment_preference_inputs(
        root,
        diagnose_args,
        record,
        path.parent,
    )
    diagnose_args.preference_selection_id = _record(
        root,
        selection_id="prefsel-stale-diagnose-write-gate",
        skill="experiment-workbench",
        operation="diagnose",
        task_context=experiment.experiment_preference_context(diagnose_args, record, diagnose_prepared),
        selected_paths=set(),
    )
    write_yaml_if_changed(claims, {"claims": [], "revision": 1})
    with pytest.raises(SystemExit, match="another task"):
        experiment._dispatch(diagnose_args, root)
    assert not (path.parent / "diagnosis-fill.yaml").exists()
    assert not (path.parent / "diagnoses.yaml").exists()
    assert not (path.parent / "diagnosis.md").exists()
    assert load_yaml(path) == record


@pytest.mark.parametrize("through_symlink", [False, True])
def test_diagnosis_claims_outside_workspace_fail_closed_without_writes(
    tmp_path: Path,
    through_symlink: bool,
) -> None:
    experiment = _script("experiment-workbench", "experiment.py")
    root = _workspace(tmp_path)
    plan = experiment.build_parser().parse_args(
        ["plan", "--title", "claims containment", "--program-id", "program-containment"]
    )
    assert experiment._dispatch(plan, root) == 0
    path = next((root / "kb/units/experiments").glob("*/record.yaml"))
    record = load_yaml(path)
    outside = tmp_path / "outside-claims.yaml"
    write_yaml_if_changed(outside, {"claims": []})
    claims_arg = outside
    if through_symlink:
        claims_arg = root / "claims-link.yaml"
        claims_arg.symlink_to(outside)
    args = experiment.build_parser().parse_args(
        ["diagnose", "--experiment-id", str(record["id"]), "--claims-file", str(claims_arg)]
    )

    with pytest.raises(SystemExit, match="must remain inside the project workspace"):
        experiment._dispatch(args, root)

    assert not (path.parent / "diagnosis-fill.yaml").exists()
    assert not (path.parent / "diagnoses.yaml").exists()
    assert not (path.parent / "diagnosis.md").exists()
    assert load_yaml(path) == record

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import write_yaml_if_changed
from research.paths import config_root, runtime_preferences_path
from research.preference_selection import eligible_preferences, record_effective_selection
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
    assert method.resource_capacity(resources)["source"] == "profile.resources"
    hard = eligible_preferences(root, skill="method-designer", operation="design")
    assert {item["path"] for item in hard["items"] if item["strength"] == "hard"} == {
        "profile.resources",
        "profile.constraints",
    }

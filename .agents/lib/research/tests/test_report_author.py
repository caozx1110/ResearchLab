from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import write_yaml_if_changed


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
    (workflow / "decision-log.md").write_text(
        "# Decision Log\n\n"
        "## 2026-07-17T01:00:00+00:00 · Use the grounded baseline\n\n"
        "- Stage: `literature-review`\n"
        "- Rationale: It has direct benchmark evidence.\n"
        "- Alternatives: Delay baseline selection\n"
        "- Confirmation: `confirmed`\n",
        encoding="utf-8",
    )
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
        unit_dir / "record.yaml",
        {"id": unit_id, "kind": "paper", "title": "Grounded Paper", "payload": {"claims": claims}},
    )
    write_yaml_if_changed(
        unit_dir / "parse-cache.yaml",
        {"chunks": [{"label": "page-3", "text": "Success rate improves by 8 points."}]},
    )
    return root, program_id, unit_id


def test_weekly_and_stage_reports_include_claims_evidence_events_and_decisions(tmp_path: Path) -> None:
    report = _load_report_module()
    root, program_id, _ = _make_workspace(tmp_path)

    inputs = report.load_report_inputs(root, program_id)
    weekly = report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly")
    stage = report.render_report(f"Stage Summary: {program_id}", inputs, report_kind="stage-summary")

    for text in (weekly, stage):
        assert "The method improves benchmark success rate." in text
        assert "Success rate improves by 8 points." in text
        assert "Grounded review completed" in text
        assert "Use the grounded baseline" in text


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

    inputs = report.load_report_inputs(root, program_id)
    weekly = report.render_report(f"Weekly Report: {program_id}", inputs, report_kind="weekly")
    outline = report.render_outline(program_id, inputs)

    assert "missing: confirmed claims" in weekly
    assert "missing: reporting events" in weekly
    assert "missing: decisions" in weekly
    assert "missing: related-work claims and evidence" in outline
    assert "improves benchmark success rate" not in weekly

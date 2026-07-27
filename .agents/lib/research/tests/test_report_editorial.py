from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from research.common import append_program_reporting_event, load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation, write_record
from research.evidence import build_verification_receipt
from research.figures import build_asset_binding, build_figure_entry, build_figure_index
from research.records import canonical_record_snapshot_for_record, default_record, normalize_record_snapshot
from research.report_editorial import (
    build_editorial_fill_scaffold,
    build_editorial_manifest,
    render_ppt_editorial,
    render_weekly_editorial,
    validate_editorial_fill,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
REPORT_SCRIPT = PROJECT_ROOT / ".agents" / "skills" / "report-author" / "scripts" / "report.py"


def _report_module():
    name = f"report_editorial_owner_{id(object())}"
    spec = importlib.util.spec_from_file_location(name, REPORT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _base_manifest(output_kind: str) -> dict:
    return build_editorial_manifest(
        program_id="program-editorial",
        output_kind=output_kind,
        as_of="2026-07-27T00:00:00Z",
        request={"stage": "", "limit": 20, "preference_selection_id": ""},
        input_bindings={"state": {"byte_sha256": "a" * 64}, "events": {"byte_sha256": "b" * 64}},
        support_catalog={
            "claim:p-one:c-one": {
                "ref": "claim:p-one:c-one",
                "kind": "claim",
                "title": "Paper One",
                "text": "A confirmed result.",
                "evidence_refs": [{"quote": "exact evidence"}],
                "binding_digest": "c" * 64,
            }
        },
        risk_catalog={
            "risk:event:r-one": {
                "ref": "risk:event:r-one",
                "kind": "risk_hint",
                "title": "Pending",
                "text": "confirmation is pending",
                "formal_support": False,
                "binding_digest": "d" * 64,
            }
        },
        figure_catalog={
            "figure:fig:p-one:fig:1": {
                "ref": "figure:fig:p-one:fig:1",
                "kind": "figure",
                "caption": "Figure 1. Overview",
                "binding_digest": "e" * 64,
            }
        },
    )


def _ready_weekly(manifest: dict, *, text: str = "Grounded editorial sentence.") -> dict:
    fill = build_editorial_fill_scaffold(manifest)
    fill["status"] = "ready_for_verify"
    support = manifest["catalogs"]["support"][0]["ref"]
    fill["sections"] = {
        "executive_summary": [{"text": text, "refs": [support], "epistemic_label": "synthesis"}],
        "progress": [{"text": "Progress is evidence-bound.", "refs": [support], "epistemic_label": "fact"}],
        "problems_and_risks": [{"text": "A pending item remains.", "refs": ["risk:event:r-one"], "epistemic_label": "risk"}],
        "next_steps": [{"text": "Run the next bounded check.", "refs": [support], "epistemic_label": "plan"}],
    }
    return fill


def _ready_ppt(manifest: dict) -> dict:
    fill = build_editorial_fill_scaffold(manifest)
    fill["status"] = "ready_for_verify"
    fill["figure_status"] = "cited"
    fill["slides"] = [
        {
            "order": 1,
            "title": "One claim",
            "conclusion": "The confirmed result is the slide conclusion.",
            "evidence_refs": ["claim:p-one:c-one"],
            "figure_refs": ["figure:fig:p-one:fig:1"],
            "speaker_note": "Explain the evidence before interpretation.",
            "transition": "Move from result to implication.",
        }
    ]
    return fill


def test_fill_contract_rejects_unknown_refs_markup_latex_and_absolute_paths() -> None:
    weekly_manifest = _base_manifest("weekly")
    fill = _ready_weekly(weekly_manifest)
    fill["sections"]["progress"][0]["refs"] = ["claim:unknown:claim"]
    fill["sections"]["executive_summary"][0]["text"] = "<script>alert(1)</script>"
    fill["sections"]["next_steps"][0]["text"] = r"Use \input{secret} from /Users/person/private.txt"
    fill["sections"]["problems_and_risks"][0]["text"] = "Inspect .agents/private.py with --unsafe=${TOKEN}"

    violations = validate_editorial_fill(fill, weekly_manifest)

    assert any("unknown refs" in item for item in violations)
    assert any("raw markup" in item for item in violations)
    assert any("raw LaTeX" in item for item in violations)
    assert any("absolute machine path" in item for item in violations)
    assert any("internal path, flag, or template token" in item for item in violations)


def test_weekly_and_ppt_render_distinct_editorial_structures() -> None:
    weekly_manifest = _base_manifest("weekly")
    ppt_manifest = _base_manifest("ppt-materials")
    weekly = render_weekly_editorial(_ready_weekly(weekly_manifest), weekly_manifest, language="zh-CN")
    ppt = render_ppt_editorial(_ready_ppt(ppt_manifest), ppt_manifest, language="zh-CN")

    assert "## 本周摘要" in weekly and "## 证据附录" in weekly
    assert "逐字证据：exact evidence" in weekly
    assert "## Slide 1" not in weekly
    assert "## Slide 1" in ppt and "- 结论：" in ppt and "- 讲述：" in ppt and "- 过渡：" in ppt
    assert "figure:fig:p-one:fig:1" in ppt
    assert "## 本周摘要" not in ppt and "## 证据附录" not in ppt


def test_ppt_without_current_figures_requires_and_renders_explicit_missing_state() -> None:
    manifest = _base_manifest("ppt-materials")
    manifest = build_editorial_manifest(
        program_id=manifest["program_id"],
        output_kind="ppt-materials",
        as_of=manifest["as_of"],
        request=manifest["request"],
        input_bindings=manifest["input_bindings"],
        support_catalog={item["ref"]: item for item in manifest["catalogs"]["support"]},
        risk_catalog={item["ref"]: item for item in manifest["catalogs"]["risks"]},
        figure_catalog={},
    )
    fill = build_editorial_fill_scaffold(manifest)
    fill["status"] = "ready_for_verify"
    fill["figure_status"] = "missing"
    fill["slides"] = [
        {
            "order": 1,
            "title": "No current figure",
            "conclusion": "The conclusion remains evidence-bound without a figure.",
            "evidence_refs": ["claim:p-one:c-one"],
            "figure_refs": [],
            "speaker_note": "State the missing visual explicitly.",
            "transition": "Continue to the evidence.",
        }
    ]

    assert validate_editorial_fill(fill, manifest) == []
    assert "缺少：当前没有可引用图示" in render_ppt_editorial(fill, manifest, language="zh-CN")


def _write_confirmed_paper_with_figure(root: Path, program_id: str, unit_id: str) -> str:
    unit_root = root / "kb" / "units" / "papers" / unit_id
    unit_root.mkdir(parents=True)
    evidence_text = "Success rate improves by 8 points."
    write_yaml_if_changed(unit_root / "parse-cache.yaml", {"chunks": [{"label": "page-3", "text": evidence_text}]})
    source_bytes = b"%PDF-1.4 editorial fixture"
    source_path = unit_root / "source" / "document.pdf"
    source_path.parent.mkdir()
    source_path.write_bytes(source_bytes)
    asset_bytes = b"editorial-png-bytes"
    binding = build_asset_binding(asset_bytes, page=3, source_mode="test")
    asset_path = unit_root / binding["path"]
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(asset_bytes)
    figure_entry = build_figure_entry(
        unit_id,
        kind="figure",
        number="1",
        caption="Figure 1. Editorial result overview",
        page=3,
        assets=[binding],
    )
    figure_index = build_figure_index(
        unit_id,
        source_artifact="source/document.pdf",
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        extraction_settings={"mode": "test"},
        entries=[figure_entry],
    )
    write_yaml_if_changed(unit_root / "figures.yaml", figure_index)
    record = {
        "id": unit_id,
        "kind": "paper",
        "title": "Editorial Grounded Paper",
        "program_ids": [program_id],
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact", "unverified"],
        "payload": {
            "claims": [
                {
                    "id": "claim-editorial-result",
                    "text": "The method improves benchmark success rate.",
                    "claim_type": "fact",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": unit_id,
                            "artifact": "parse-cache.yaml",
                            "locator": "page=3",
                            "quote": evidence_text,
                        }
                    ],
                }
            ],
            "figures": {
                "schema": "figure-index/v1",
                "extraction_status": "indexed",
                "index_artifact": "figures.yaml",
                "index_digest": figure_index["index_digest"],
                "available_ref_keys": [figure_entry["ref_key"]],
                "key_figure_refs": [],
            },
        },
    }
    build_verification_receipt(record, unit_root)
    record_path = unit_root / "record.yaml"
    write_yaml_if_changed(record_path, record)
    expected = canonical_record_snapshot_for_record(root, record)
    normalized = normalize_record_snapshot(expected, root)
    assert normalized is not None
    apply_confirmation(
        normalized,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed the displayed claim and evidence."],
        user_authorization="I confirm this paper claim.",
        authorization_source="user_message",
        project_root=root,
        verification_root=unit_root,
        expected_record_snapshot=expected,
    )
    write_record(root, normalized, expected_record_snapshot=expected)
    return figure_entry["ref_key"]


def _write_confirmed_decision(root: Path, program_id: str) -> None:
    program_root = root / "kb" / "programs" / program_id
    evidence_path = program_root / "workflow" / "decision-evidence.md"
    evidence_path.write_text("direct benchmark evidence", encoding="utf-8")
    decision = {
        "id": "decision-editorial-baseline",
        "kind": "program_decision",
        "owner": "research-orchestrator",
        "program_id": program_id,
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["inference", "evaluation", "unverified"],
        "payload": {
            "decision": {
                "text": "Use the grounded baseline",
                "stage": "evaluation",
                "rationale": "It has direct benchmark evidence.",
                "alternatives": ["Delay selection"],
            },
            "claims": [
                {
                    "id": "claim-editorial-decision",
                    "text": "Use the grounded baseline.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": f"program:{program_id}",
                            "artifact": "workflow/decision-evidence.md",
                            "locator": "line=1",
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
        evidence=["Reviewed the displayed decision."],
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


def _workspace(tmp_path: Path) -> tuple[Path, str, str, str]:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    program_id = "program-editorial"
    unit_id = "p-editorial-123456"
    experiment_id = "x-editorial-123456"
    workflow = root / "kb" / "programs" / program_id / "workflow"
    workflow.mkdir(parents=True)
    write_yaml_if_changed(
        root / "kb" / "programs" / program_id / "state.yaml",
        {"program_id": program_id, "stage": "evaluation", "active_unit_ids": [unit_id, experiment_id]},
    )
    append_program_reporting_event(
        root,
        program_id,
        {
            "source_skill": "experiment-workbench",
            "event_type": "phase-completed",
            "title": "Evaluation completed",
            "summary": "The bounded evaluation run completed.",
            "stage": "evaluation",
            "paper_ids": [unit_id],
            "epistemic_type": "factual",
            "information_types": ["fact"],
        },
        generated_by="experiment-workbench",
    )
    figure_ref = _write_confirmed_paper_with_figure(root, program_id, unit_id)
    experiment = default_record("experiment", title="Editorial experiment", maturity="lightweight")
    experiment["id"] = experiment_id
    experiment["status"] = "active"
    experiment["confirmation_status"] = "auto_confirmed"
    experiment["program_ids"] = [program_id]
    write_record(root, experiment)
    _write_confirmed_decision(root, program_id)
    return root, program_id, unit_id, figure_ref


def _commit_kb_fixture(root: Path) -> None:
    kb = root / "kb"
    subprocess.run(["git", "init", str(kb)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(kb), "config", "user.email", "editorial@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(kb), "config", "user.name", "Editorial Test"], check=True)
    subprocess.run(["git", "-C", str(kb), "add", "--all"], check=True)
    subprocess.run(
        ["git", "-C", str(kb), "commit", "-m", "fixture baseline"],
        check=True,
        capture_output=True,
        text=True,
    )


def _fill_real_weekly(manifest: dict) -> dict:
    support = [item["ref"] for item in manifest["catalogs"]["support"]]
    assert any(ref.startswith("claim:") for ref in support)
    assert any(ref.startswith("decision:") for ref in support)
    assert any(ref.startswith("event:") for ref in support)
    fill = build_editorial_fill_scaffold(manifest)
    fill["status"] = "ready_for_verify"
    fill["sections"] = {
        "executive_summary": [{"text": "本周完成了有证据约束的评估。", "refs": [support[0]], "epistemic_label": "synthesis"}],
        "progress": [{"text": "基准评估已完成。", "refs": [next(ref for ref in support if ref.startswith("event:"))], "epistemic_label": "fact"}],
        "problems_and_risks": [{"text": "仍需扩大重复实验范围。", "refs": [next(ref for ref in support if ref.startswith("claim:"))], "epistemic_label": "risk"}],
        "next_steps": [{"text": "按已确认基线继续实验。", "refs": [next(ref for ref in support if ref.startswith("decision:"))], "epistemic_label": "plan"}],
    }
    return fill


def _fill_real_ppt(manifest: dict) -> dict:
    support = [item["ref"] for item in manifest["catalogs"]["support"]]
    figures = [item["ref"] for item in manifest["catalogs"]["figures"]]
    assert figures
    fill = build_editorial_fill_scaffold(manifest)
    fill["status"] = "ready_for_verify"
    fill["figure_status"] = "cited"
    fill["slides"] = [
        {
            "order": 1,
            "title": "评估结论",
            "conclusion": "方法在当前基准上取得更高成功率。",
            "evidence_refs": [next(ref for ref in support if ref.startswith("claim:"))],
            "figure_refs": [figures[0]],
            "speaker_note": "先讲结论，再展示逐字证据与图示。",
            "transition": "随后说明基线选择。",
        },
        {
            "order": 2,
            "title": "下一步路线",
            "conclusion": "后续实验沿用已确认基线。",
            "evidence_refs": [next(ref for ref in support if ref.startswith("decision:"))],
            "figure_refs": [],
            "speaker_note": "说明决策依据和仍需验证的边界。",
            "transition": "结束并进入讨论。",
        },
    ]
    return fill


def test_prepare_preserves_fill_and_verify_publishes_distinct_direct_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report_module()
    root, program_id, _unit_id, figure_ref = _workspace(tmp_path)
    checkpoints: list[dict] = []
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *args, **kwargs: checkpoints.append(kwargs) or {"committed": False})

    assert report.prepare_editorial_report(root, program_id, "weekly", stage="", limit=20, preference_selection_id="") == 0
    assert report.prepare_editorial_report(root, program_id, "ppt-materials", stage="", limit=20, preference_selection_id="") == 0
    weekly_manifest_path, weekly_fill_path, weekly_output = report._editorial_paths(root, program_id, "weekly")
    ppt_manifest_path, ppt_fill_path, ppt_output = report._editorial_paths(root, program_id, "ppt-materials")
    weekly_manifest = load_yaml(weekly_manifest_path)
    ppt_manifest = load_yaml(ppt_manifest_path)
    weekly_fill = _fill_real_weekly(weekly_manifest)
    ppt_fill = _fill_real_ppt(ppt_manifest)
    write_yaml_if_changed(weekly_fill_path, weekly_fill)
    write_yaml_if_changed(ppt_fill_path, ppt_fill)

    fill_before = weekly_fill_path.read_bytes()
    manifest_before = weekly_manifest_path.read_bytes()
    assert report.prepare_editorial_report(root, program_id, "weekly", stage="", limit=20, preference_selection_id="") == 0
    assert weekly_fill_path.read_bytes() == fill_before
    assert weekly_manifest_path.read_bytes() == manifest_before

    assert report.verify_editorial_report(root, program_id, "weekly") == 0
    assert report.verify_editorial_report(root, program_id, "ppt-materials") == 0
    weekly_text = weekly_output.read_text(encoding="utf-8")
    ppt_text = ppt_output.read_text(encoding="utf-8")
    outline = report.render_outline(program_id, report.load_report_inputs(root, program_id))

    assert all(heading in weekly_text for heading in ("## 本周摘要", "## 进展", "## 问题与风险", "## 下周计划", "## 证据附录"))
    assert "Success rate improves by 8 points." in weekly_text
    assert weekly_text.count("## Slide") == 0
    assert ppt_text.count("## Slide") == 2
    assert ppt_text.count("- 结论：") == 2
    assert ppt_text.count("- 讲述：") == 2
    assert ppt_text.count("- 过渡：") == 2
    assert f"figure:{figure_ref}" in ppt_text
    assert "## 本周摘要" not in ppt_text and "## 证据附录" not in ppt_text
    assert "## 引言" in outline and "## 本周摘要" not in outline and "## Slide" not in outline
    assert weekly_text != ppt_text != outline
    assert len(checkpoints) == 5


@pytest.mark.parametrize("output_kind", ["weekly", "ppt-materials"])
def test_verify_checkpoints_agent_fill_in_mixed_program(tmp_path: Path, output_kind: str) -> None:
    report = _report_module()
    root, program_id, _unit_id, _figure_ref = _workspace(tmp_path)
    report.prepare_editorial_report(root, program_id, output_kind, stage="", limit=20, preference_selection_id="")
    manifest_path, fill_path, _output_path = report._editorial_paths(root, program_id, output_kind)
    _commit_kb_fixture(root)
    fill = (
        _fill_real_weekly(load_yaml(manifest_path))
        if output_kind == "weekly"
        else _fill_real_ppt(load_yaml(manifest_path))
    )
    write_yaml_if_changed(fill_path, fill)

    report.verify_editorial_report(root, program_id, output_kind)

    status = subprocess.run(
        ["git", "-C", str(root / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status == ""


def test_stale_figure_or_input_race_never_overwrites_previous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report_module()
    root, program_id, unit_id, _figure_ref = _workspace(tmp_path)
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *args, **kwargs: {"committed": False})
    report.prepare_editorial_report(root, program_id, "ppt-materials", stage="", limit=20, preference_selection_id="")
    manifest_path, fill_path, output_path = report._editorial_paths(root, program_id, "ppt-materials")
    write_yaml_if_changed(fill_path, _fill_real_ppt(load_yaml(manifest_path)))
    report.verify_editorial_report(root, program_id, "ppt-materials")
    old_output = output_path.read_bytes()

    asset_path = next((root / "kb" / "units" / "papers" / unit_id / "figures" / "assets").glob("*.png"))
    asset_path.write_bytes(b"tampered figure bytes")
    with pytest.raises(report.EditorialError, match="manifest inputs changed"):
        report.verify_editorial_report(root, program_id, "ppt-materials")
    assert output_path.read_bytes() == old_output

    # Build a fresh workspace for a race that occurs after rendering/write.
    report = _report_module()
    root, program_id, _unit_id, _figure_ref = _workspace(tmp_path / "race")
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *args, **kwargs: {"committed": False})
    report.prepare_editorial_report(root, program_id, "weekly", stage="", limit=20, preference_selection_id="")
    manifest_path, fill_path, output_path = report._editorial_paths(root, program_id, "weekly")
    write_yaml_if_changed(fill_path, _fill_real_weekly(load_yaml(manifest_path)))
    report.verify_editorial_report(root, program_id, "weekly")
    old_output = output_path.read_bytes()
    fill = load_yaml(fill_path)
    fill["sections"]["executive_summary"][0]["text"] = "这段新正文不应在 stale race 后覆盖旧产物。"
    write_yaml_if_changed(fill_path, fill)
    events_path = root / "kb" / "programs" / program_id / "workflow" / "reporting-events.yaml"
    original_write = report.write_text_if_changed
    raced = False

    def write_then_race(path: Path, text: str):
        nonlocal raced
        result = original_write(path, text)
        if path == output_path and not raced:
            raced = True
            payload = load_yaml(events_path)
            payload["items"][0]["summary"] = "changed during publication"
            write_yaml_if_changed(events_path, payload)
        return result

    monkeypatch.setattr(report, "write_text_if_changed", write_then_race)
    with pytest.raises(report.EditorialError, match="manifest inputs changed"):
        report.verify_editorial_report(root, program_id, "weekly")
    assert raced
    assert output_path.read_bytes() == old_output

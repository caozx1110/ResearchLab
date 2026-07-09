"""Smoke test for the research-value Tier-1 eval harness (G5).

Read-only harness; this test builds a tiny synthetic workspace in tmp_path (so it
does not depend on the gitignored real kb/) and asserts the harness runs without
crashing and produces a report with the expected metric fields.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
HARNESS_PATH = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "skill-evolution-advisor"
    / "scripts"
    / "eval_research_value.py"
)


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("eval_research_value", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_workspace(root: Path) -> None:
    # one paper unit with empty core_content but real note + parse-cache text
    unit = root / "kb" / "units" / "papers" / "p-smoke-0001"
    _write(
        unit / "record.yaml",
        "id: p-smoke-0001\n"
        "kind: paper\n"
        "title: Smoke Test Paper on Foobar Latents\n"
        "status: active\n"
        "maturity: complete\n"
        "confirmation_status: auto_confirmed\n"
        "information_types: [fact]\n"
        "tags: [research]\n"
        "topics: [uncategorized]\n"
        "summary: smoke foobar latent paper\n"
        "payload:\n"
        "  core_content:\n"
        "    research_problem: ''\n"
        "    motivation: ''\n"
        "    story: ''\n"
        "    method: ''\n"
        "    innovations: []\n"
        "    changes_and_effects: []\n"
        "    mechanism: ''\n"
        "    why_it_might_work: ''\n",
    )
    _write(
        unit / "note.md",
        "# Smoke Test Paper\n\n> 审查状态：REWRITTEN.\n\n"
        "The foobar latent uses a widget encoder at 42 Hz on the gadget robot.\n",
    )
    _write(
        unit / "parse-cache.yaml",
        "paper_id: p-smoke-0001\n"
        "chunks:\n"
        "- label: smoke:page-1\n"
        "  text: 'The foobar latent uses a widget encoder at 42 Hz on the gadget robot.'\n",
    )

    # one program with state + workflow
    prog = root / "kb" / "programs" / "smoke-prog"
    _write(
        prog / "state.yaml",
        "id: smoke-prog-state\n"
        "program_id: smoke-prog\n"
        "stage: literature-review\n"
        "active_unit_ids: []\n"
        "next_actions: []\n",
    )
    _write(
        prog / "workflow" / "open-questions.yaml",
        "items:\n- question: how does the widget encoder work?\n  status: open\n",
    )

    # dataset: one tier-1 unit fact, one program fact, one no-data control
    _write(
        root / "kb" / "eval" / "research-value" / "dataset" / "smoke-prog.yaml",
        "dataset_id: smoke-prog\n"
        "program_id: smoke-prog\n"
        "questions:\n"
        "- id: q-smoke-001\n"
        "  program_id: smoke-prog\n"
        "  axis: A\n"
        "  tier: 1\n"
        "  question: what encoder and frequency does the foobar latent use?\n"
        "  gold_facts:\n"
        "  - text: The foobar latent uses a widget encoder at 42 Hz.\n"
        "    source_unit_id: p-smoke-0001\n"
        "    locator: page=1\n"
        "    auto_gradeable: true\n"
        "  expected_units: [p-smoke-0001]\n"
        "  gold_status: confirmed\n"
        "  gold_drafted_from: smoke\n"
        "- id: q-smoke-002\n"
        "  program_id: smoke-prog\n"
        "  axis: F\n"
        "  tier: 1\n"
        "  question: what stage is the smoke program in?\n"
        "  gold_facts:\n"
        "  - text: The smoke-prog program is in literature-review stage with no active units.\n"
        "    source_unit_id: smoke-prog\n"
        "    locator: state.yaml\n"
        "    auto_gradeable: false\n"
        "  expected_units: []\n"
        "  gold_status: confirmed\n"
        "  gold_drafted_from: smoke\n"
        "- id: q-smoke-003\n"
        "  program_id: smoke-prog\n"
        "  axis: A\n"
        "  tier: 1\n"
        "  no_data_expected: true\n"
        "  question: what reward does the nonexistent Xyzzy system use?\n"
        "  gold_facts:\n"
        "  - text: NOT IN KB. No Xyzzy unit exists.\n"
        "    source_unit_id: smoke-prog\n"
        "    locator: none\n"
        "    auto_gradeable: false\n"
        "  expected_units: []\n"
        "  gold_status: confirmed\n"
        "  gold_drafted_from: smoke\n",
    )


def test_harness_runs_and_reports_expected_fields(harness, tmp_path):
    _build_workspace(tmp_path)
    result = harness.evaluate(tmp_path, None)

    # top-level metric structure
    for key in ("recall", "grounding", "empty_program_control", "gate_integrity", "axis_summary", "questions"):
        assert key in result, f"missing result key: {key}"

    # recall: the one expected unit is retrievable in top-5
    assert result["recall"]["denom"] == 1
    assert result["recall"]["at5"] == 1.0

    # grounding: the auto-gradeable unit fact is found in note/parse-cache
    assert result["grounding"]["total"] == 1
    assert result["grounding"]["hit"] == 1
    # the source note carries the REWRITTEN marker -> manual bucket
    assert result["grounding"]["source_distribution"]["manual_rewritten"] == 1

    # program-state fact recorded separately (not folded into unit rate)
    assert result["grounding"]["program_state"]["total"] == 1

    # empty-program control: the no-data question is counted
    assert result["empty_program_control"]["questions"] == 1

    # H1 gate integrity: the auto_confirmed paper has empty core_content
    gi = result["gate_integrity"]
    assert gi["settled"]["auto_confirmed"]["count"] == 1
    assert gi["settled"]["auto_confirmed"]["empty"] == 1
    assert gi["papers_empty_core_content"] == 1
    assert gi["papers_total"] == 1


def test_render_report_has_sections(harness, tmp_path):
    _build_workspace(tmp_path)
    result = harness.evaluate(tmp_path, None)
    meta = {
        "utc": "2026-07-09T00:00:00Z",
        "kb_head": "smoke",
        "repo_head": "smoke",
        "n_questions": len(result["questions"]),
        "programs": ["smoke-prog"],
        "pdf": harness.probe_pdf_backends(),
    }
    report = harness.render_report(tmp_path, result, meta)
    assert "Tier-1 metrics" in report
    assert "H1 gate integrity" in report
    assert "Per-axis summary" in report
    assert "Retrieval recall@5" in report
    assert "Grounding rate" in report

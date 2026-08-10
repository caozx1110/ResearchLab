from __future__ import annotations

from pathlib import Path

import yaml

from repo_paths import REPO_ROOT, SKILLS_ROOT


DIRECT_REFERENCE_INVENTORY = {
    "kb-cli": {
        "references/dispatcher-and-init.md",
        "references/review-contract.md",
        "references/recovery-and-output.md",
    },
    "literature-search": {
        "references/stage-contract.md",
        "references/selection-contract.md",
    },
    "literature-synthesizer": {
        "references/survey-contract.md",
        "references/concept-and-composite.md",
    },
    "report-author": {
        "references/reporting-workflows.md",
        "references/paper-draft-contract.md",
        "references/output-and-quality.md",
    },
    "idea-workbench": {
        "references/generation-and-analysis.md",
        "references/discussion-and-selection.md",
        "references/private-operations.md",
    },
    "method-designer": {
        "references/selection-workflow.md",
        "references/resource-and-claims.md",
    },
    "experiment-workbench": {
        "references/runs-and-imports.md",
        "references/diagnosis-and-feedback.md",
        "references/preferences-and-private-operations.md",
    },
}


def test_runtime_rule_layers_are_pointer_plus_minimal_workspace_rules() -> None:
    pointer_path = REPO_ROOT / "runtime" / "AGENTS.md"
    pointer = pointer_path.read_text(encoding="utf-8")
    rules = (REPO_ROOT / "runtime" / "WORKSPACE_RULES.md").read_text(encoding="utf-8")

    assert pointer.splitlines() == [
        "Before any knowledge-base operation, load `.agents/WORKSPACE_RULES.md`. "
        "If it is missing or unreadable, do not write to the workspace; only use "
        "the read-only `kb help` or `kb doctor` rescue path until the installation is repaired."
    ]
    assert rules.startswith("# WORKSPACE_RULES ")
    assert len(rules.splitlines()) < 100
    assert not (REPO_ROOT / "runtime" / "AGENT_GUIDE.md").exists()


def test_multi_operation_skills_expose_required_references_one_hop() -> None:
    for owner, expected_references in DIRECT_REFERENCE_INVENTORY.items():
        skill_dir = SKILLS_ROOT / owner
        entry = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for relative in expected_references:
            assert f"]({relative})" in entry, (owner, relative)
            assert (skill_dir / Path(relative)).is_file(), (owner, relative)


def test_progressive_disclosure_preserves_meta_skill_routing_boundaries() -> None:
    metadata = yaml.safe_load((SKILLS_ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    catalog = metadata["skills"]
    evolution = " ".join(
        (
            catalog["skill-evolution-advisor"]["interface"]["default_prompt"],
            (SKILLS_ROOT / "skill-evolution-advisor" / "SKILL.md").read_text(encoding="utf-8"),
        )
    )
    discussion = " ".join(
        (
            catalog["discussion-archivist"]["interface"]["default_prompt"],
            (SKILLS_ROOT / "discussion-archivist" / "SKILL.md").read_text(encoding="utf-8"),
        )
    )
    orchestrator = " ".join(
        (
            catalog["research-orchestrator"]["interface"]["default_prompt"],
            (SKILLS_ROOT / "research-orchestrator" / "SKILL.md").read_text(encoding="utf-8"),
        )
    )

    for phrase in (
        "skill/workflow",
        "pending improvements",
        "workflow friction",
        "model, method, or experiment",
    ):
        assert phrase in evolution
    assert "不得由本 owner 单独吞并" in discussion
    assert "ordered route decision" in orchestrator

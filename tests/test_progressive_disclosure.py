from __future__ import annotations

from pathlib import Path

import yaml

from repo_paths import REPO_ROOT, SKILLS_ROOT


DIRECT_REFERENCE_INVENTORY = {
    "research-analysis": {"references/contract.md"},
    "research-capture": {"references/contract.md"},
    "research-review": {
        "references/authorization-decisions-and-receipts.md",
        "references/evidence-audit-and-packets.md",
    },
    "research-vault": {"references/v2-contract.md"},
    "research-workbench": {
        "references/discussions-decisions-reports.md",
        "references/experiments-and-results.md",
        "references/mutation-and-no-overwrite.md",
        "references/pages-and-lifecycle.md",
    },
}


def test_runtime_rule_layers_are_pointer_plus_minimal_workspace_rules() -> None:
    pointer_path = REPO_ROOT / "runtime" / "AGENTS.md"
    pointer = pointer_path.read_text(encoding="utf-8")
    rules = (REPO_ROOT / "runtime" / "WORKSPACE_RULES.md").read_text(encoding="utf-8")

    assert pointer.splitlines() == [
        "Before any Research Vault operation, load `.agents/WORKSPACE_RULES.md`. "
        "If it is missing or unreadable, do not write to the workspace; explain that "
        "the installation must be repaired."
    ]
    assert rules.startswith("# WORKSPACE_RULES ")
    assert len(rules.splitlines()) < 100
    assert not (REPO_ROOT / "runtime" / "AGENT_GUIDE.md").exists()


def test_five_skills_expose_required_references_one_hop() -> None:
    for owner, expected_references in DIRECT_REFERENCE_INVENTORY.items():
        skill_dir = SKILLS_ROOT / owner
        entry = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for relative in expected_references:
            assert f"]({relative})" in entry, (owner, relative)
            assert (skill_dir / Path(relative)).is_file(), (owner, relative)


def test_v2_routing_boundaries_are_discoverable_without_legacy_schema() -> None:
    metadata = yaml.safe_load((SKILLS_ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    assert set(metadata["skills"]) == set(DIRECT_REFERENCE_INVENTORY)
    combined = "\n".join(
        (SKILLS_ROOT / owner / "SKILL.md").read_text(encoding="utf-8")
        for owner in DIRECT_REFERENCE_INVENTORY
    )

    for phrase in ("Markdown", ".research", ".source", "evidence", "review"):
        assert phrase in combined
    assert "SCHEMAS.md" not in combined
    assert "record.yaml" not in combined
    assert "obsidian/managed" not in combined

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path
from research.paths import config_root
from research.preference_selection import (
    OPERATION_CANONICAL_INPUTS,
    eligible_preferences,
    record_effective_selection,
    task_context_digest,
)


def _idea_module(name: str):
    repo = Path(__file__).resolve().parents[4]
    path = repo / ".agents/skills/idea-workbench/scripts/idea.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path, idea) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(root)
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {
            "preferences": {"language_preference": "zh-CN"},
            "personalization": {
                "research_focus": "embodied agents",
                "term_style": "keep English terms",
            },
            "resources": {"gpu_count": 1},
            "constraints": ["local only"],
        },
    )
    idea.PROJECT_ROOT = root
    idea.checkpoint_and_report = lambda *args, **kwargs: {}
    return root


def _run(idea, monkeypatch: pytest.MonkeyPatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["idea.py", "--root", str(root), *argv])
    return idea.main()


def _selection(root: Path, operation: str, context: dict[str, object], suffix: str) -> str:
    eligible = eligible_preferences(root, skill="idea-workbench", operation=operation)
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {
            "preference_id": item["preference_id"],
            "reason": "relevant to this bounded idea authoring task",
        }
        if item["strength"] == "hard" or item["path"] == "profile.personalization.research_focus":
            selected.append({**row, "application": "respect the explicit task while authoring"})
        else:
            excluded.append(row)
    selection_id = f"prefsel-idea-{suffix}"
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "idea-workbench",
            "operation": operation,
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    return selection_id


def _setup_semantic_records(root: Path) -> tuple[str, str, str]:
    idea_record = default_record(
        "idea",
        title="Preference-bound idea",
        maturity="lightweight",
        source={"original_uri": "discussion"},
    )
    idea_record["id"] = "i-preference-123456"
    idea_record["payload"]["problem"]["problem_definition"] = "Improve long-horizon recall."
    idea_record["payload"]["hypothesis"]["core_hypothesis"] = "A learned memory gate helps."
    write_yaml_if_changed(record_path(root, "idea", idea_record["id"]), idea_record)

    paper = default_record(
        "paper",
        title="Evidence paper",
        maturity="complete",
        source={"original_uri": "fixture"},
    )
    paper["id"] = "p-preference-123456"
    paper_path = record_path(root, "paper", paper["id"])
    write_yaml_if_changed(paper_path, paper)
    quote = "Memory gates improved recall under delayed observations."
    (paper_path.parent / "evidence.txt").write_text(quote + "\n", encoding="utf-8")
    return idea_record["id"], paper["id"], quote


def _fill_semantic(path: Path, operation: str, source_id: str, quote: str) -> None:
    fill = load_yaml(path, default={})
    fill["reviewer"] = "runtime-agent"
    if operation == "discuss":
        fill["conclusion"] = "A memory gate needs a delayed-observation ablation."
    for claim in fill["claims"]:
        role = str(claim["role"])
        claim["text"] = (
            fill["conclusion"]
            if role == "conclusion"
            else f"Agent-authored {role} judgement."
        )
        claim["evidence_refs"] = [
            {
                "source_unit_id": source_id,
                "artifact": "evidence.txt",
                "locator": "section:fixture",
                "quote": quote,
                "summary": "Grounds this bounded judgement.",
            }
        ]
    if operation == "review":
        fill["selection_rank"] = 1
    write_yaml_if_changed(path, fill)


def test_generate_is_agent_authored_two_phase_and_materializes_all_candidates_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idea = _idea_module("idea_generation_preference_success")
    root = _workspace(tmp_path, idea)
    common = (
        "generate",
        "--title",
        "Adaptive agents",
        "--problem",
        "Original problem exactly",
        "--hypothesis",
        "Original hypothesis exactly",
        "--source",
        "discussion",
        "--count",
        "2",
        "--pool",
        "current-ideas",
        "--bundle-id",
        "idea-bundle-agent-authored",
    )
    assert _run(idea, monkeypatch, root, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools/idea-bundle-agent-authored"
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    assert fill["request_context"]["problem"] == "Original problem exactly"
    assert fill["request_context"]["hypothesis"] == "Original hypothesis exactly"
    assert all(
        item["title"] == ""
        and item["strategy"] == ""
        and item["problem"] == ""
        and item["hypothesis"] == ""
        and item["next_actions"] == []
        for item in fill["candidates"]
    )
    forbidden = {"narrow-scope", "repo-first", "evaluation-first", "mechanism-first"}
    assert all(term not in json.dumps(fill, ensure_ascii=False) for term in forbidden)

    selection_id = _selection(
        root,
        "generate",
        dict(fill["preference_consumer"]["task_context"]),
        "generate01",
    )
    fill["candidates"][0].update(
        {
            "title": "Adaptive memory policy",
            "strategy": "Learn a bounded memory gate",
            "problem": "When should an agent retain observations?",
            "hypothesis": "A learned gate improves long-horizon recall.",
            "next_actions": ["Train the gate", "Run a delayed-observation ablation"],
        }
    )
    fill["candidates"][1].update(
        {
            "title": "Counterfactual retrieval agent",
            "strategy": "Retrieve counterfactual failures",
            "problem": "Which failures expose brittle retrieval?",
            "hypothesis": "Counterfactual negatives improve robustness.",
            "next_actions": ["Build a failure set", "Measure robustness"],
        }
    )
    write_yaml_if_changed(fill_path, fill)
    assert (
        _run(
            idea,
            monkeypatch,
            root,
            *common,
            "--phase",
            "verify",
            "--preference-selection-id",
            selection_id,
        )
        == 0
    )

    records = [load_yaml(path) for path in sorted((root / "kb/units/ideas").glob("*/record.yaml"))]
    assert len(records) == 2
    assert {record["payload"]["candidate"]["strategy"] for record in records} == {
        "Learn a bounded memory gate",
        "Retrieve counterfactual failures",
    }
    assert all(record["payload"]["preference_selections"]["generate"]["selection_id"] == selection_id for record in records)
    serialized = json.dumps(records, ensure_ascii=False)
    assert all(term not in serialized for term in forbidden)
    bundle = load_yaml(working / "index.yaml")
    assert bundle["generation_context"]["problem"] == "Original problem exactly"
    assert bundle["preference_selection"]["selection_id"] == selection_id


def test_generate_invalid_slot_has_no_partial_candidate_or_bundle_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idea = _idea_module("idea_generation_atomic_failure")
    root = _workspace(tmp_path, idea)
    common = (
        "generate",
        "--title",
        "Atomic candidates",
        "--count",
        "2",
        "--bundle-id",
        "idea-bundle-atomic",
    )
    _run(idea, monkeypatch, root, *common, "--phase", "prepare")
    working = root / "kb/synthesis/idea-pools/idea-bundle-atomic"
    fill_path = working / "generation-fill.yaml"
    prepared_index = working / "index.yaml"
    prepared_bytes = prepared_index.read_bytes()
    fill = load_yaml(fill_path)
    fill["candidates"][0].update(
        {
            "title": "Only valid candidate",
            "strategy": "Agent strategy",
            "problem": "A real problem",
            "hypothesis": "A falsifiable hypothesis",
            "next_actions": ["Run one test"],
        }
    )
    write_yaml_if_changed(fill_path, fill)

    with pytest.raises(SystemExit, match="candidate-02.title"):
        _run(idea, monkeypatch, root, *common, "--phase", "verify")

    assert prepared_index.read_bytes() == prepared_bytes
    prepared = load_yaml(prepared_index)
    assert prepared["status"] == "prepared"
    assert prepared["authoring_contract"]["schema"] == "idea-authoring-anchor/v1"
    assert list((root / "kb/units/ideas").glob("*/record.yaml")) == []

    retry_fill = load_yaml(fill_path)
    retry_fill["candidates"][1].update(
        {
            "title": "Second valid candidate",
            "strategy": "Retry the same anchored fill",
            "problem": "The first verify was incomplete",
            "hypothesis": "Prepared state remains retryable",
            "next_actions": ["Materialize both candidates"],
        }
    )
    write_yaml_if_changed(fill_path, retry_fill)
    assert _run(idea, monkeypatch, root, *common, "--phase", "verify") == 0
    assert load_yaml(prepared_index)["status"] == "active"
    assert len(list((root / "kb/units/ideas").glob("*/record.yaml"))) == 2


def test_generate_stale_preference_receipt_rejects_before_candidate_or_bundle_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idea = _idea_module("idea_generation_stale_receipt")
    root = _workspace(tmp_path, idea)
    common = (
        "generate",
        "--title",
        "Stale generation",
        "--count",
        "1",
        "--bundle-id",
        "idea-bundle-stale",
    )
    _run(idea, monkeypatch, root, *common, "--phase", "prepare")
    working = root / "kb/synthesis/idea-pools/idea-bundle-stale"
    prepared_index = working / "index.yaml"
    prepared_bytes = prepared_index.read_bytes()
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path)
    selection_id = _selection(
        root,
        "generate",
        dict(fill["preference_consumer"]["task_context"]),
        "generate02",
    )
    fill["candidates"][0].update(
        {
            "title": "Agent-only candidate",
            "strategy": "Agent-only strategy",
            "problem": "Agent-only problem",
            "hypothesis": "Agent-only hypothesis",
            "next_actions": ["Agent-only next action"],
        }
    )
    write_yaml_if_changed(fill_path, fill)
    profile_path = config_root(root) / "user-profile.yaml"
    profile = load_yaml(profile_path)
    profile["personalization"]["research_focus"] = "mutated after receipt"
    write_yaml_if_changed(profile_path, profile)

    with pytest.raises(SystemExit):
        _run(
            idea,
            monkeypatch,
            root,
            *common,
            "--phase",
            "verify",
            "--preference-selection-id",
            selection_id,
        )

    assert prepared_index.read_bytes() == prepared_bytes
    prepared = load_yaml(prepared_index)
    assert prepared["status"] == "prepared"
    assert prepared["authoring_contract"]["schema"] == "idea-authoring-anchor/v1"
    assert list((root / "kb/units/ideas").glob("*/record.yaml")) == []


@pytest.mark.parametrize("operation", ["analyze", "review", "discuss"])
def test_semantic_idea_operations_consume_bound_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    idea = _idea_module(f"idea_preference_{operation}_success")
    root = _workspace(tmp_path, idea)
    idea_id, source_id, quote = _setup_semantic_records(root)
    id_flag = "--id" if operation == "discuss" else "--idea-id"
    assert _run(idea, monkeypatch, root, operation, id_flag, idea_id, "--phase", "prepare") == 0
    unit = record_path(root, "idea", idea_id).parent
    fill_path = unit / ("discussion-fill.yaml" if operation == "discuss" else f"{operation}-fill.yaml")
    fill = load_yaml(fill_path)
    selection_id = _selection(
        root,
        operation,
        dict(fill["preference_consumer"]["task_context"]),
        f"{operation}01",
    )
    _fill_semantic(fill_path, operation, source_id, quote)

    assert (
        _run(
            idea,
            monkeypatch,
            root,
            operation,
            id_flag,
            idea_id,
            "--phase",
            "verify",
            "--preference-selection-id",
            selection_id,
        )
        == 0
    )
    record = load_yaml(record_path(root, "idea", idea_id))
    assert record["payload"]["preference_selections"][operation]["selection_id"] == selection_id
    if operation == "discuss":
        judgement = load_yaml(unit / "discussion-judgements.yaml")["items"][0]
        assert judgement["preference_selection"]["selection_id"] == selection_id
    else:
        result = load_yaml(unit / f"{operation}.yaml")
        assert result["preference_selection"]["selection_id"] == selection_id


@pytest.mark.parametrize("operation", ["analyze", "review", "discuss"])
def test_stale_semantic_idea_preference_receipt_rejects_before_business_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    idea = _idea_module(f"idea_preference_{operation}_stale")
    root = _workspace(tmp_path, idea)
    idea_id, source_id, quote = _setup_semantic_records(root)
    id_flag = "--id" if operation == "discuss" else "--idea-id"
    _run(idea, monkeypatch, root, operation, id_flag, idea_id, "--phase", "prepare")
    unit = record_path(root, "idea", idea_id).parent
    fill_path = unit / ("discussion-fill.yaml" if operation == "discuss" else f"{operation}-fill.yaml")
    fill = load_yaml(fill_path)
    selection_id = _selection(
        root,
        operation,
        dict(fill["preference_consumer"]["task_context"]),
        f"{operation}02",
    )
    _fill_semantic(fill_path, operation, source_id, quote)
    record_before = record_path(root, "idea", idea_id).read_bytes()
    profile_path = config_root(root) / "user-profile.yaml"
    profile = load_yaml(profile_path)
    profile["personalization"]["research_focus"] = "changed after selection"
    write_yaml_if_changed(profile_path, profile)

    with pytest.raises(SystemExit):
        _run(
            idea,
            monkeypatch,
            root,
            operation,
            id_flag,
            idea_id,
            "--phase",
            "verify",
            "--preference-selection-id",
            selection_id,
        )

    assert record_path(root, "idea", idea_id).read_bytes() == record_before
    if operation == "discuss":
        assert not (unit / "discussion-judgements.yaml").exists()
    else:
        assert not (unit / f"{operation}.yaml").exists()


@pytest.mark.parametrize("operation", ["generate", "analyze", "review", "discuss"])
def test_idea_consumed_input_registry_mutation_matrix(operation: str) -> None:
    fields = OPERATION_CANONICAL_INPUTS[("idea-workbench", operation)]
    context: dict[str, object] = {field: f"value-{field}" for field in fields}
    if "candidate_count" in context:
        context["candidate_count"] = 2
    baseline = task_context_digest(
        skill="idea-workbench",
        operation=operation,
        canonical_inputs=context,
    )
    for field in fields:
        mutated = copy.deepcopy(context)
        mutated[field] = 3 if field == "candidate_count" else f"changed-{field}"
        assert task_context_digest(
            skill="idea-workbench",
            operation=operation,
            canonical_inputs=mutated,
        ) != baseline

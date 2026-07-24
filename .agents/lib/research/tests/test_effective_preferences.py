from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.common import write_yaml_if_changed
from research.paths import config_root, runtime_preferences_path
from research.preference_selection import (
    OPERATION_CANONICAL_INPUTS,
    SKILL_ELIGIBILITY,
    SKILL_NEUTRALITY,
    SKILL_OPERATIONS,
    eligible_preferences,
    load_effective_selection,
    record_effective_selection,
    resolve_effective_preferences,
    resolve_task_preferences,
    task_context_digest,
)


def test_every_shipping_skill_has_an_explicit_preference_eligibility_rule() -> None:
    skills_root = Path(__file__).resolve().parents[3] / "skills"
    shipping = {path.name for path in skills_root.iterdir() if (path / "SKILL.md").is_file()}

    assert set(SKILL_ELIGIBILITY) == shipping
    consumers = set(SKILL_OPERATIONS)
    neutral = set(SKILL_NEUTRALITY)
    assert consumers | neutral == shipping
    assert consumers.isdisjoint(neutral)
    assert all(SKILL_ELIGIBILITY[skill] for skill in consumers)
    assert all(not SKILL_ELIGIBILITY[skill] and SKILL_NEUTRALITY[skill].strip() for skill in neutral)


def test_declared_consumer_operations_are_real_not_aspirational() -> None:
    assert SKILL_OPERATIONS == {
        "source-intake": ("add",),
        "research-orchestrator": ("plan",),
        "literature-search": ("search",),
        "literature-synthesizer": ("synthesize",),
        "report-author": ("weekly", "ppt-materials", "stage-summary", "writing-materials", "outline"),
        "method-designer": ("design",),
        "experiment-workbench": ("plan", "log-run", "follow-up", "diagnose"),
        "kb-cli": ("review-display",),
        "paper-analyst": (
            "prewarm-cache",
            "screen",
            "complete-note",
            "extract-figures",
            "refresh-structure",
        ),
        "repo-analyst": ("map-capability",),
        "dataset-analyst": ("profile",),
        "blog-analyst": ("complete-note",),
        "idea-workbench": ("generate", "analyze", "review", "discuss"),
        "research-monitor": ("create-subscription",),
    }


def test_semantic_consumers_have_closed_canonical_input_registries() -> None:
    expected_pairs = {
        (skill, operation)
        for skill, operations in SKILL_OPERATIONS.items()
        for operation in operations
    }
    assert set(OPERATION_CANONICAL_INPUTS) == expected_pairs
    for skill, operation in sorted(expected_pairs):
        fields = OPERATION_CANONICAL_INPUTS[(skill, operation)]
        canonical = {field: None for field in fields}
        assert len(task_context_digest(skill=skill, operation=operation, canonical_inputs=canonical)) == 64
        with pytest.raises(ValueError, match="unexpected=unregistered"):
            task_context_digest(
                skill=skill,
                operation=operation,
                canonical_inputs={**canonical, "unregistered": None},
            )
        missing = dict(canonical)
        missing.pop(fields[0])
        with pytest.raises(ValueError, match="missing="):
            task_context_digest(skill=skill, operation=operation, canonical_inputs=missing)

    common = {
        "canonical_id",
        "canonical_kind",
        "operation",
        "record_content_digest",
        "phase_contract_digest",
        "immutable_orientation_digest",
    }
    analyzer_pairs = {
        ("repo-analyst", "map-capability"),
        ("dataset-analyst", "profile"),
        ("blog-analyst", "complete-note"),
    }
    assert analyzer_pairs.issubset(OPERATION_CANONICAL_INPUTS)
    for pair in analyzer_pairs:
        fields = OPERATION_CANONICAL_INPUTS[pair]
        assert common.issubset(fields)
    assert {
        ("idea-workbench", "generate"),
        ("idea-workbench", "analyze"),
        ("idea-workbench", "review"),
        ("idea-workbench", "discuss"),
        ("research-monitor", "create-subscription"),
    }.issubset(OPERATION_CANONICAL_INPUTS)


def test_bound_consumer_resolves_selected_values_without_copying_them_into_receipt(
    tmp_path: Path,
) -> None:
    root = _configured_workspace(tmp_path)
    eligible = eligible_preferences(root, skill="report-author", operation="weekly")
    selected = eligible["items"][:1]
    selection_id = "prefsel-report01"
    report_context = {
        "program_id": "p1",
        "operation": "weekly",
        "stage": "",
        "limit": 20,
        "input_snapshot": {
            "digest": "0" * 64,
            "accepted_event_count": 0,
            "pending_judgement_event_count": 0,
            "claim_source_count": 0,
            "decision_count": 0,
            "missing_unit_count": 0,
        },
    }
    path, receipt = record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "report-author",
            "operation": "weekly",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": report_context,
            "selected": [
                {
                    "preference_id": item["preference_id"],
                    "reason": "matches the requested audience",
                    "application": "use the requested language",
                }
                for item in selected
            ],
            "excluded": [
                {"preference_id": item["preference_id"], "reason": "not relevant to this report"}
                for item in eligible["items"]
                if item not in selected
            ],
        },
    )

    effective = resolve_effective_preferences(
        root,
        selection_id=selection_id,
        skill="report-author",
        operation="weekly",
        expected_task_context_digest=task_context_digest(
            skill="report-author",
            operation="weekly",
            canonical_inputs=report_context,
        ),
    )

    assert effective["effective_items"][0]["value"] == selected[0]["value"]
    assert "value" not in receipt["selected"][0]
    assert str(selected[0]["value"]) not in path.read_text(encoding="utf-8")
from research.prefs import default_runtime_preferences, ensure_workspace


def _configured_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {
            "preferences": {"language_preference": "zh-CN"},
            "personalization": {
                "research_focus": "robot learning",
                "reporting_style": "concise",
                "term_style": "keep English terms",
            },
            "resources": {"gpu": "8xA100"},
            "constraints": ["no cloud upload"],
        },
    )
    return root


def _selection(root: Path, skill: str, operation: str = "plan") -> dict[str, object]:
    eligible = eligible_preferences(root, skill=skill, operation=operation)
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {
            "preference_id": item["preference_id"],
            "reason": "relevant to this task" if item["strength"] == "hard" else "not needed now",
        }
        if item["strength"] == "hard":
            row["application"] = "respect this hard boundary"
            selected.append(row)
        else:
            excluded.append(row)
    return {
        "selection_id": "prefsel-abcdef01",
        "skill": skill,
        "operation": operation,
        "catalog_digest": eligible["catalog_digest"],
        "task_context": {
            "program_id": "program-1",
            "title_digest": "1" * 64,
            "idea_id": "idea-1",
            "goal_digest": "2" * 64,
            "hypothesis_digest": "3" * 64,
        },
        "selected": selected,
        "excluded": excluded,
    }


def test_eligible_preferences_are_skill_scoped_and_exclude_identity_and_diagnostics(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    runtime = default_runtime_preferences()
    runtime["identity"]["default_confirmed_by"] = "Human Researcher"
    runtime["diagnostics"]["mode"] = "developer"
    write_yaml_if_changed(runtime_preferences_path(root), runtime)

    experiment = eligible_preferences(root, skill="experiment-workbench", operation="plan")
    paths = {str(item["path"]) for item in experiment["items"]}

    assert "profile.resources" in paths
    assert "profile.constraints" in paths
    assert "runtime.autonomy.auto_execute_scope" in paths
    assert all(not path.startswith("runtime.identity") for path in paths)
    assert all(not path.startswith("runtime.diagnostics") for path in paths)
    assert "profile.personalization.reporting_style" not in paths


def test_agent_selection_receipt_keeps_only_ids_digests_and_reasons(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    payload = _selection(root, "experiment-workbench")

    path, receipt = record_effective_selection(root, payload)
    loaded = load_effective_selection(
        root,
        selection_id="prefsel-abcdef01",
        skill="experiment-workbench",
        operation="plan",
        expected_task_context_digest=task_context_digest(
            skill="experiment-workbench",
            operation="plan",
            canonical_inputs=payload["task_context"],
        ),
    )

    assert path.is_file()
    assert loaded == receipt
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert "8xA100" not in serialized
    assert "no cloud upload" not in serialized
    assert str(root) not in serialized
    assert "runtime-agent" in serialized


def test_hard_preferences_cannot_be_omitted_and_all_eligible_items_are_accounted_for(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    payload = _selection(root, "experiment-workbench")
    selected = payload["selected"]
    assert isinstance(selected, list) and selected
    payload["excluded"].append(selected.pop())

    with pytest.raises(ValueError, match="hard preferences"):
        record_effective_selection(root, payload)

    payload = _selection(root, "experiment-workbench")
    payload["selected"].pop()
    with pytest.raises(ValueError, match="account for every eligible"):
        record_effective_selection(root, payload)


def test_profile_change_makes_existing_selection_stale(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    record_effective_selection(root, _selection(root, "experiment-workbench"))
    profile_path = config_root(root) / "user-profile.yaml"
    profile = {
        "preferences": {"language_preference": "zh-CN"},
        "personalization": {"research_focus": "robot learning"},
        "resources": {"gpu": "1xCPU"},
        "constraints": ["no cloud upload"],
    }
    write_yaml_if_changed(profile_path, profile)

    with pytest.raises(ValueError, match="stale catalog"):
        load_effective_selection(
            root,
            selection_id="prefsel-abcdef01",
            skill="experiment-workbench",
            operation="plan",
            expected_task_context_digest=task_context_digest(
                skill="experiment-workbench",
                operation="plan",
                canonical_inputs=_selection(root, "experiment-workbench")["task_context"],
            ),
        )


def test_confirmed_learned_preferences_follow_their_skill_hint(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    runtime = default_runtime_preferences()
    runtime["learned_preferences"]["items"] = [
        {
            "id": "learning-1",
            "text": "show a compact comparison first",
            "source": "user",
            "skill": "report-author",
            "operation": "weekly",
            "context": "",
        }
    ]
    write_yaml_if_changed(runtime_preferences_path(root), runtime)

    report_paths = {str(item["path"]) for item in eligible_preferences(root, skill="report-author", operation="weekly")["items"]}
    experiment_paths = {str(item["path"]) for item in eligible_preferences(root, skill="experiment-workbench", operation="plan")["items"]}

    assert "learned.learning-1" in report_paths
    assert "learned.learning-1" not in experiment_paths


def test_unknown_consumer_and_unsafe_receipt_root_fail_closed(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    with pytest.raises(ValueError, match="unknown preference consumer"):
        eligible_preferences(root, skill="unknown-skill")

    external = tmp_path / "external"
    external.mkdir()
    selection_root = config_root(root) / "effective-preferences"
    selection_root.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe|symlink"):
        record_effective_selection(root, _selection(root, "experiment-workbench"))


def test_kb_ancestor_symlink_cannot_read_or_write_preferences_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    (outside / "config").mkdir(parents=True)
    write_yaml_if_changed(outside / "config/user-profile.yaml", {"resources": {"secret": "outside"}})
    (root / "kb").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        eligible_preferences(root, skill="experiment-workbench", operation="plan")
    assert not (outside / "config/effective-preferences").exists()


def test_receipt_is_task_bound_private_and_idempotent(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    payload = _selection(root, "experiment-workbench")
    path, first = record_effective_selection(root, payload)
    path_again, second = record_effective_selection(root, payload)

    assert path_again == path
    assert second == first
    with pytest.raises(ValueError, match="another task"):
        load_effective_selection(
            root,
            selection_id="prefsel-abcdef01",
            skill="experiment-workbench",
            operation="plan",
            expected_task_context_digest="b" * 64,
        )
    unsafe = _selection(root, "report-author", operation="weekly")
    unsafe["selection_id"] = "prefsel-private01"
    unsafe["excluded"][0]["reason"] = f"copied from {root}/private.txt"
    with pytest.raises(ValueError, match="private or path-like"):
        record_effective_selection(root, unsafe)


def test_eligibility_is_a_pure_read_on_an_uninitialized_workspace(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

    result = eligible_preferences(root, skill="literature-search", operation="search")

    after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    assert result["skill"] == "literature-search"
    assert before == after == []

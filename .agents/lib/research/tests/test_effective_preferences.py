from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.common import write_yaml_if_changed
from research.paths import config_root, runtime_preferences_path
from research.preference_selection import (
    SKILL_ELIGIBILITY,
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


def test_bound_consumer_resolves_selected_values_without_copying_them_into_receipt(
    tmp_path: Path,
) -> None:
    root = _configured_workspace(tmp_path)
    eligible = eligible_preferences(root, skill="report-author", operation="weekly")
    selected = eligible["items"][:1]
    selection_id = "prefsel-report01"
    path, receipt = record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "report-author",
            "operation": "weekly",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": {"program_id": "p1", "operation": "weekly", "stage": "", "limit": 20},
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
            canonical_inputs={"program_id": "p1", "operation": "weekly", "stage": "", "limit": 20},
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


def _selection(root: Path, skill: str, operation: str = "design") -> dict[str, object]:
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
        "task_context": {"subject_id": "subject-1"},
        "selected": selected,
        "excluded": excluded,
    }


def test_eligible_preferences_are_skill_scoped_and_exclude_identity_and_diagnostics(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    runtime = default_runtime_preferences()
    runtime["identity"]["default_confirmed_by"] = "Human Researcher"
    runtime["diagnostics"]["mode"] = "developer"
    write_yaml_if_changed(runtime_preferences_path(root), runtime)

    method = eligible_preferences(root, skill="method-designer", operation="design")
    paths = {str(item["path"]) for item in method["items"]}

    assert "profile.resources" in paths
    assert "profile.constraints" in paths
    assert "profile.personalization.research_focus" in paths
    assert all(not path.startswith("runtime.identity") for path in paths)
    assert all(not path.startswith("runtime.diagnostics") for path in paths)
    assert "profile.personalization.reporting_style" not in paths


def test_agent_selection_receipt_keeps_only_ids_digests_and_reasons(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    payload = _selection(root, "method-designer")

    path, receipt = record_effective_selection(root, payload)
    loaded = load_effective_selection(
        root,
        selection_id="prefsel-abcdef01",
        skill="method-designer",
        operation="design",
        expected_task_context_digest=task_context_digest(
            skill="method-designer", operation="design", canonical_inputs={"subject_id": "subject-1"}
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
    payload = _selection(root, "method-designer")
    selected = payload["selected"]
    assert isinstance(selected, list) and selected
    payload["excluded"].append(selected.pop())

    with pytest.raises(ValueError, match="hard preferences"):
        record_effective_selection(root, payload)

    payload = _selection(root, "method-designer")
    payload["excluded"].pop()
    with pytest.raises(ValueError, match="account for every eligible"):
        record_effective_selection(root, payload)


def test_profile_change_makes_existing_selection_stale(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    record_effective_selection(root, _selection(root, "method-designer"))
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
            skill="method-designer",
            operation="design",
            expected_task_context_digest=task_context_digest(
                skill="method-designer", operation="design", canonical_inputs={"subject_id": "subject-1"}
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
    method_paths = {str(item["path"]) for item in eligible_preferences(root, skill="method-designer", operation="design")["items"]}

    assert "learned.learning-1" in report_paths
    assert "learned.learning-1" not in method_paths


def test_unknown_consumer_and_unsafe_receipt_root_fail_closed(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    with pytest.raises(ValueError, match="unknown preference consumer"):
        eligible_preferences(root, skill="unknown-skill")

    external = tmp_path / "external"
    external.mkdir()
    selection_root = config_root(root) / "effective-preferences"
    selection_root.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe|symlink"):
        record_effective_selection(root, _selection(root, "method-designer"))


def test_kb_ancestor_symlink_cannot_read_or_write_preferences_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    (outside / "config").mkdir(parents=True)
    write_yaml_if_changed(outside / "config/user-profile.yaml", {"resources": {"secret": "outside"}})
    (root / "kb").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        eligible_preferences(root, skill="method-designer", operation="design")
    assert not (outside / "config/effective-preferences").exists()


def test_receipt_is_task_bound_private_and_idempotent(tmp_path: Path) -> None:
    root = _configured_workspace(tmp_path)
    payload = _selection(root, "method-designer")
    path, first = record_effective_selection(root, payload)
    path_again, second = record_effective_selection(root, payload)

    assert path_again == path
    assert second == first
    with pytest.raises(ValueError, match="another task"):
        load_effective_selection(
            root,
            selection_id="prefsel-abcdef01",
            skill="method-designer",
            operation="design",
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

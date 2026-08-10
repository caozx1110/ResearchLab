from __future__ import annotations

from repo_paths import initialize_test_workspace

import importlib.util
import os
import re
import stat
import sys
from pathlib import Path

from repo_paths import REPO_ROOT
from typing import Any

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import ensure_workspace, record_path, write_record
from research.paths import config_root
from research.preference_selection import (
    OPERATION_CANONICAL_INPUTS,
    eligible_preferences,
    record_effective_selection,
    regular_file_binding,
    regular_tree_binding,
    resolve_task_preferences,
)
from research.records import kind_payload_skeleton


PREFERENCE_SENTINEL = "R11-SOFT-PREFERENCE-MUST-NOT-BE-COPIED"


def _load_script(skill: str, filename: str):
    repository = REPO_ROOT
    path = repository / "skills" / skill / "scripts" / filename
    name = f"r11_{skill.replace('-', '_')}_{id(path)}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(base: Path) -> Path:
    root = base / "workspace"
    root.mkdir()
    initialize_test_workspace(root)
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {
            "preferences": {"language_preference": "zh-CN"},
            "personalization": {
                "research_focus": PREFERENCE_SENTINEL,
                "reporting_style": "concise",
                "term_style": "keep English terms",
            },
        },
    )
    return root


def _base_record(kind: str, unit_id: str, title: str, source: dict[str, object]) -> dict[str, object]:
    return {
        "id": unit_id,
        "kind": kind,
        "title": title,
        "status": "screened",
        "maturity": "lightweight",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact", "inference", "evaluation", "unverified"],
        "topics": ["r11"],
        "tags": ["preference-consumer"],
        "source": source,
        "payload": kind_payload_skeleton(kind, title),
    }


def _repo_elements(unit_id: str) -> list[dict[str, object]]:
    return [
        {
            "element": "capability",
            "claim_type": "evaluation",
            "content": "A compact manipulation baseline.",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "README.md",
                    "locator": "line=2",
                    "quote": "compact manipulation baseline",
                }
            ],
        },
        {
            "element": "reuse_points",
            "claim_type": "evaluation",
            "content": "The policy module is reusable.",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "src/policy.py",
                    "locator": "line=2",
                    "quote": "reusable policy module",
                }
            ],
        },
        {
            "element": "entry_map",
            "claim_type": "inference",
            "content": "Training starts in train.py.",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "train.py",
                    "locator": "line=2",
                    "quote": "training entrypoint",
                }
            ],
        },
    ]


def _document_elements(kind: str, unit_id: str) -> list[dict[str, object]]:
    names = (
        ("positioning", "composition", "schema_access", "suitability_risks")
        if kind == "dataset"
        else ("positioning", "key_points", "credibility", "reusable_explanation")
    )
    return [
        {
            "element": name,
            "claim_type": "evaluation" if name in {"suitability_risks", "credibility"} else "inference",
            "content": f"Agent-authored {name} judgement.",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "parse-cache.yaml",
                    "locator": "section:main",
                    "quote": "Canonical source evidence for analyzer testing.",
                }
            ],
        }
        for name in names
    ]


def _run(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch, phase: str, *, selection_id: str = "") -> int:
    argv = [
        case["filename"],
        "--root",
        str(case["root"]),
        case["command"],
        case["id_flag"],
        case["unit_id"],
        "--phase",
        phase,
        "--defer-post-actions",
    ]
    if selection_id:
        argv.extend(["--preference-selection-id", selection_id])
    monkeypatch.setattr(sys, "argv", argv)
    return case["module"].main()


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skill: str) -> dict[str, Any]:
    root = _workspace(tmp_path)
    if skill == "repo-analyst":
        module = _load_script("unit-analyst", "repo.py")
        unit_id = "r-r11-consumer-0001"
        source_root = root / "archives" / "repo-source"
        (source_root / "src").mkdir(parents=True)
        (source_root / "README.md").write_text(
            "# Repo\nA compact manipulation baseline.\n", encoding="utf-8"
        )
        (source_root / "train.py").write_text(
            "def main():\n    # training entrypoint\n", encoding="utf-8"
        )
        (source_root / "src" / "policy.py").write_text(
            "class Policy:\n    # reusable policy module\n", encoding="utf-8"
        )
        record = _base_record(
            "repo",
            unit_id,
            "R11 Repo",
            {
                "original_uri": "",
                "backup_kind": "directory",
                "backup_paths": ["archives/repo-source"],
                "file_hash": "",
            },
        )
        write_record(root, record)
        case = {
            "module": module,
            "filename": "repo.py",
            "root": root,
            "skill": skill,
            "operation": "map-capability",
            "command": "map-capability",
            "id_flag": "--repo-id",
            "unit_id": unit_id,
            "unit_root": record_path(root, "repo", unit_id).parent,
            "fill_name": "capability-fill.yaml",
            "orientation_name": "capability-orientation.yaml",
            "primary_name": "structure-scan.yaml",
            "source_mutation": source_root / "src" / "policy.py",
            "source_root": source_root,
            "elements": _repo_elements(unit_id),
        }
    else:
        kind = "dataset" if skill == "dataset-analyst" else "blog"
        filename = "dataset.py" if kind == "dataset" else "blog.py"
        module = _load_script("unit-analyst", filename)
        unit_id = f"{'d' if kind == 'dataset' else 'b'}-r11-consumer-0001"
        record = _base_record(
            kind,
            unit_id,
            f"R11 {kind.title()}",
            {"original_uri": f"https://example.invalid/{kind}", "file_hash": ""},
        )
        write_record(root, record)
        unit_root = record_path(root, kind, unit_id).parent
        write_yaml_if_changed(
            unit_root / "parse-cache.yaml",
            {
                f"{kind}_id": unit_id,
                "source_type": "html",
                "locator_kind": "section",
                "chunks": [
                    {
                        "label": "section:main",
                        "anchor": "main",
                        "locator_kind": "section",
                        "text": "Canonical source evidence for analyzer testing.",
                    }
                ],
            },
        )
        source_root = unit_root / "source"
        source_root.mkdir()
        (source_root / "document.md").write_text(
            "# Canonical reading artifact\n\nSource body.\n", encoding="utf-8"
        )
        case = {
            "module": module,
            "filename": filename,
            "root": root,
            "skill": skill,
            "operation": "profile" if kind == "dataset" else "complete-note",
            "command": "profile" if kind == "dataset" else "complete-note",
            "id_flag": "--dataset-id" if kind == "dataset" else "--blog-id",
            "unit_id": unit_id,
            "unit_root": unit_root,
            "fill_name": f"{kind}-fill.yaml",
            "orientation_name": f"{kind}-orientation.yaml",
            "primary_name": "parse-cache.yaml",
            "source_mutation": source_root / "document.md",
            "source_root": source_root,
            "elements": _document_elements(kind, unit_id),
        }

    assert _run(case, monkeypatch, "prepare") == 0
    fill_path = case["unit_root"] / case["fill_name"]
    scaffold = load_yaml(fill_path)
    case["task_context"] = dict(scaffold["preference_consumer"]["task_context"])
    scaffold["elements"] = case["elements"]
    write_yaml_if_changed(fill_path, scaffold)
    return case


def _selection(case: dict[str, Any], suffix: str = "selected") -> str:
    safe_suffix = re.sub(r"[^a-z0-9-]+", "-", suffix.casefold()).strip("-")
    selection_id = f"prefsel-r11-{safe_suffix}"
    eligible = eligible_preferences(
        case["root"], skill=case["skill"], operation=case["operation"]
    )
    selected: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    for index, item in enumerate(eligible["items"]):
        if index == 0 or str(item["strength"]) == "hard":
            selected.append(
                {
                    "preference_id": str(item["preference_id"]),
                    "reason": "relevant to this authoring task",
                    "application": "adjust Agent emphasis only",
                }
            )
        else:
            excluded.append(
                {
                    "preference_id": str(item["preference_id"]),
                    "reason": "not relevant to this authoring task",
                }
            )
    record_effective_selection(
        case["root"],
        {
            "selection_id": selection_id,
            "skill": case["skill"],
            "operation": case["operation"],
            "catalog_digest": eligible["catalog_digest"],
            "task_context": case["task_context"],
            "selected": selected,
            "excluded": excluded,
        },
    )
    return selection_id


def _business_snapshot(unit_root: Path) -> dict[str, tuple[str, object]]:
    result: dict[str, tuple[str, object]] = {}
    for path in sorted(unit_root.rglob("*")):
        relative = path.relative_to(unit_root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            result[relative] = ("symlink", os.readlink(path))
        elif stat.S_ISREG(metadata.st_mode):
            result[relative] = ("file", path.read_bytes())
        elif stat.S_ISDIR(metadata.st_mode):
            result[relative] = ("directory", None)
        else:
            result[relative] = ("special", metadata.st_mode)
    return result


@pytest.mark.parametrize("skill", ["repo-analyst", "dataset-analyst", "blog-analyst"])
def test_analyzer_receipt_success_persists_only_value_free_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skill: str
) -> None:
    case = _case(tmp_path, monkeypatch, skill)
    selection_id = _selection(case, skill)
    # The receipt binds the immutable orientation, never the Agent-fillable file.
    fill_path = case["unit_root"] / case["fill_name"]
    fill = load_yaml(fill_path)
    fill["elements"][0]["content"] += " Revised after preference selection."
    write_yaml_if_changed(fill_path, fill)

    assert _run(case, monkeypatch, "verify", selection_id=selection_id) == 0

    record = load_yaml(case["unit_root"] / "record.yaml")
    binding = record["payload"]["preference_contexts"][case["operation"]]
    assert set(binding) == {
        "selection_id",
        "selection_digest",
        "task_context_digest",
        "skill",
        "operation",
    }
    assert binding["selection_id"] == selection_id
    for kind, value in _business_snapshot(case["unit_root"]).values():
        if kind == "file":
            assert PREFERENCE_SENTINEL.encode() not in value


@pytest.mark.parametrize("skill", ["repo-analyst", "dataset-analyst", "blog-analyst"])
def test_analyzer_neutral_verify_recomputes_context_without_reading_soft_preferences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skill: str
) -> None:
    case = _case(tmp_path, monkeypatch, skill)
    import research.preference_selection as preference_selection

    def forbidden(*args, **kwargs):
        raise AssertionError("neutral analyzer path read the soft preference catalog")

    monkeypatch.setattr(preference_selection, "eligible_preferences", forbidden)
    assert _run(case, monkeypatch, "verify") == 0
    record = load_yaml(case["unit_root"] / "record.yaml")
    assert "preference_contexts" not in record["payload"]


@pytest.mark.parametrize("skill", ["repo-analyst", "dataset-analyst", "blog-analyst"])
def test_analyzer_owner_rejects_valid_receipt_bound_to_another_skill_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skill: str
) -> None:
    case = _case(tmp_path, monkeypatch, skill)
    eligible = eligible_preferences(case["root"], skill="report-author", operation="weekly")
    selection_id = f"prefsel-r11-wrong-{skill.split('-')[0]}"
    record_effective_selection(
        case["root"],
        {
            "selection_id": selection_id,
            "skill": "report-author",
            "operation": "weekly",
            "catalog_digest": eligible["catalog_digest"],
                "task_context": {
                    "program_id": "p-r11",
                    "operation": "weekly",
                    "stage": "",
                    "limit": 20,
                    "presentation_contract": "report-presentation/v2",
                    "input_snapshot": {
                        "digest": "0" * 64,
                        "accepted_event_count": 0,
                        "pending_judgement_event_count": 0,
                        "claim_source_count": 0,
                        "decision_count": 0,
                        "missing_unit_count": 0,
                    },
                },
            "selected": [
                {
                    "preference_id": item["preference_id"],
                    "reason": "relevant to report rendering",
                    "application": "render the report only",
                }
                for item in eligible["items"]
            ],
            "excluded": [],
        },
    )
    before = _business_snapshot(case["unit_root"])

    with pytest.raises(SystemExit) as exc:
        _run(case, monkeypatch, "verify", selection_id=selection_id)

    assert exc.value.code == 1
    assert _business_snapshot(case["unit_root"]) == before


@pytest.mark.parametrize("skill", ["repo-analyst", "dataset-analyst", "blog-analyst"])
def test_registered_analyzer_input_mutation_matrix_rejects_every_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skill: str
) -> None:
    case = _case(tmp_path, monkeypatch, skill)
    selection_id = _selection(case, f"{skill}-matrix")
    fields = OPERATION_CANONICAL_INPUTS[(skill, case["operation"])]
    assert set(case["task_context"]) == set(fields)

    for field in fields:
        mutated = dict(case["task_context"])
        mutated[field] = "f" * 64 if mutated[field] != "f" * 64 else "e" * 64
        with pytest.raises(ValueError, match="another task"):
            resolve_task_preferences(
                case["root"],
                selection_id=selection_id,
                skill=skill,
                operation=case["operation"],
                canonical_inputs=mutated,
            )


def _mutate(case: dict[str, Any], mutation: str, outside: Path) -> None:
    unit_root = case["unit_root"]
    if mutation == "record-bytes":
        record = load_yaml(unit_root / "record.yaml")
        record["tags"] = [*record.get("tags", []), "changed"]
        write_yaml_if_changed(unit_root / "record.yaml", record)
    elif mutation == "orientation-bytes":
        orientation = load_yaml(unit_root / case["orientation_name"])
        orientation["tampered"] = True
        write_yaml_if_changed(unit_root / case["orientation_name"], orientation)
    elif mutation == "structure-or-parse-bytes":
        path = unit_root / case["primary_name"]
        payload = load_yaml(path)
        payload["tampered"] = True
        write_yaml_if_changed(path, payload)
    elif mutation == "source-bytes":
        path = case["source_mutation"]
        path.write_bytes(path.read_bytes() + b"# byte mutation\n")
    elif mutation == "canonical-preference":
        profile_path = config_root(case["root"]) / "user-profile.yaml"
        profile = load_yaml(profile_path)
        profile["personalization"]["research_focus"] = "changed focus"
        write_yaml_if_changed(profile_path, profile)
    elif mutation == "primary-symlink":
        path = unit_root / case["primary_name"]
        outside.mkdir()
        sentinel = outside / "do-not-read.yaml"
        sentinel.write_text("outside: sentinel\n", encoding="utf-8")
        path.unlink()
        path.symlink_to(sentinel)
    elif mutation == "primary-nonregular":
        path = unit_root / case["primary_name"]
        path.unlink()
        path.mkdir()
    else:  # pragma: no cover - test table is closed
        raise AssertionError(mutation)


@pytest.mark.parametrize(
    ("skill", "mutation"),
    [
        (skill, mutation)
        for skill in ("repo-analyst", "dataset-analyst", "blog-analyst")
        for mutation in (
            "record-bytes",
            "orientation-bytes",
            "structure-or-parse-bytes",
            "source-bytes",
            "canonical-preference",
            "primary-symlink",
            "primary-nonregular",
        )
    ],
)
def test_analyzer_receipt_artifact_mutations_fail_with_zero_business_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skill: str,
    mutation: str,
) -> None:
    case = _case(tmp_path, monkeypatch, skill)
    selection_id = _selection(case, f"{skill}-{mutation}")
    _mutate(case, mutation, tmp_path / "outside")
    before = _business_snapshot(case["unit_root"])

    with pytest.raises(SystemExit) as exc:
        _run(case, monkeypatch, "verify", selection_id=selection_id)

    assert exc.value.code == 1
    assert _business_snapshot(case["unit_root"]) == before


@pytest.mark.parametrize("skill", ["repo-analyst", "dataset-analyst", "blog-analyst"])
@pytest.mark.parametrize("mutation", ["orientation-bytes", "primary-symlink"])
def test_neutral_analyzer_tamper_and_symlink_fail_with_zero_business_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skill: str,
    mutation: str,
) -> None:
    case = _case(tmp_path, monkeypatch, skill)
    _mutate(case, mutation, tmp_path / "outside")
    before = _business_snapshot(case["unit_root"])

    with pytest.raises(SystemExit) as exc:
        _run(case, monkeypatch, "verify")

    assert exc.value.code == 1
    assert _business_snapshot(case["unit_root"]) == before


def test_workspace_artifact_binding_rejects_leaf_and_ancestor_symlinks_without_following(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    nested = root / "safe" / "nested"
    nested.mkdir(parents=True)
    (nested / "artifact.yaml").write_text("inside: true\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "artifact.yaml").write_text("outside: sentinel\n", encoding="utf-8")

    (nested / "artifact.yaml").unlink()
    (nested / "artifact.yaml").symlink_to(outside / "artifact.yaml")
    with pytest.raises(ValueError, match="missing or unsafe"):
        regular_file_binding(
            nested / "artifact.yaml", logical_identity="artifact", trusted_root=root
        )

    (nested / "artifact.yaml").unlink()
    nested.rmdir()
    nested.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestor is unsafe"):
        regular_file_binding(
            nested / "artifact.yaml", logical_identity="artifact", trusted_root=root
        )
    with pytest.raises(ValueError, match="ancestor is unsafe"):
        regular_tree_binding(nested, logical_identity="tree", trusted_root=root)

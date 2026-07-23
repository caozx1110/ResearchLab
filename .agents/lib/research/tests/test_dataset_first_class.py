from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

from research.core import (
    dataset_migration_plan,
    dataset_migration_targets,
    default_record,
    ensure_workspace,
    load_yaml,
    migrate_repo_to_dataset,
    record_path,
    undo_last_operation,
    write_record,
)
from research.journal import mutation_transaction


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_script(relative: str, module_name: str):
    path = _project_root() / relative
    loader = importlib.machinery.SourceFileLoader(module_name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_huggingface_dataset_url_infers_first_class_dataset() -> None:
    kb = _load_script(".agents/skills/kb-cli/scripts/kb", "kb_dataset_inference")

    assert kb.infer_add_kind("https://huggingface.co/datasets/BitRobot/HIW-500") == "dataset"
    assert kb.infer_add_kind("https://huggingface.co/physical-intelligence/pi0") == "blog"


def test_dataset_profile_scaffold_and_verbatim_verification(tmp_path: Path) -> None:
    dataset = _load_script(
        ".agents/skills/dataset-analyst/scripts/dataset.py",
        "dataset_analyst_first_class",
    )
    record = default_record(
        "dataset",
        title="HIW-500",
        maturity="lightweight",
        source={"original_uri": "https://huggingface.co/datasets/BitRobot/HIW-500"},
    )
    unit = record_path(tmp_path, "dataset", record["id"]).parent
    unit.mkdir(parents=True)
    cache = {
        "unit_id": record["id"],
        "locator_kind": "section",
        "chunks": [
            {
                "label": "section:dataset-card",
                "text": (
                    "HIW-500 contains 500+ hours and 23K+ episodes. "
                    "It provides Raw ROS bag / MCAP recordings and a LeRobot format."
                ),
            }
        ],
    }
    (unit / "parse-cache.yaml").write_text(yaml.safe_dump(cache, sort_keys=False), encoding="utf-8")
    scaffold = dataset.build_note_scaffold(record, cache["chunks"], digest_chunks=12, digest_chars=1200)
    quotes = {
        "positioning": "HIW-500 contains 500+ hours and 23K+ episodes.",
        "composition": "500+ hours and 23K+ episodes",
        "schema_access": "Raw ROS bag / MCAP recordings and a LeRobot format.",
        "suitability_risks": "It provides Raw ROS bag / MCAP recordings",
    }
    for element in scaffold["elements"]:
        name = element["element"]
        element["content"] = f"Agent-authored {name} judgement."
        element["evidence_refs"] = [
            {
                "source_unit_id": record["id"],
                "artifact": "parse-cache.yaml",
                "locator": "section:dataset-card",
                "quote": quotes[name],
                "summary": "Dataset-card evidence.",
            }
        ]

    violations, claims = dataset.verify_note_fill(scaffold, unit)

    assert violations == []
    assert [claim["id"] for claim in claims] == [
        "claim-positioning",
        "claim-composition",
        "claim-schema_access",
        "claim-suitability_risks",
    ]
    dataset._apply_note_fill_to_payload(record, claims)
    assert record["payload"]["profile"]["positioning"]
    assert record["payload"]["composition"]["summary"]
    assert record["payload"]["access"]["schema_access"]
    assert record["payload"]["quality"]["suitability_risks"]


def test_dataset_verify_checkpoints_dirty_unit_owned_fill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dataset = _load_script(
        ".agents/skills/dataset-analyst/scripts/dataset.py",
        "dataset_analyst_checkpoint_fill",
    )
    ensure_workspace(tmp_path)
    record = default_record("dataset", title="Checkpoint Dataset", maturity="lightweight")
    dataset_id = record["id"]
    record_file = write_record(tmp_path, record)
    unit = record_file.parent
    source_text = (
        "The dataset contains 500 hours of robot demonstrations. "
        "It covers manipulation and navigation tasks. "
        "Files are available in Parquet with train and validation splits. "
        "Known risk: camera calibration varies across sites."
    )
    (unit / "parse-cache.yaml").write_text(
        yaml.safe_dump(
            {
                "unit_id": dataset_id,
                "locator_kind": "section",
                "chunks": [{"label": "section:card", "text": source_text}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["dataset.py", "--root", str(tmp_path), "profile", "--dataset-id", dataset_id, "--phase", "prepare"],
    )
    assert dataset.main() == 0

    fill_path = unit / "dataset-fill.yaml"
    fill = load_yaml(fill_path)
    quotes = {
        "positioning": "500 hours of robot demonstrations",
        "composition": "manipulation and navigation tasks",
        "schema_access": "Parquet with train and validation splits",
        "suitability_risks": "camera calibration varies across sites",
    }
    for element in fill["elements"]:
        name = element["element"]
        element["content"] = f"Agent-authored {name} judgement."
        element["evidence_refs"] = [
            {
                "source_unit_id": dataset_id,
                "artifact": "parse-cache.yaml",
                "locator": "section:card",
                "quote": quotes[name],
                "summary": "Dataset card evidence.",
            }
        ]
    fill_path.write_text(yaml.safe_dump(fill, sort_keys=False), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        ["dataset.py", "--root", str(tmp_path), "profile", "--dataset-id", dataset_id, "--phase", "verify"],
    )
    assert dataset.main() == 0

    committed = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "show", "--format=", "--name-only", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    relative_fill = f"units/datasets/{dataset_id}/dataset-fill.yaml"
    assert relative_fill in committed
    assert "dataset-fill.yaml" not in subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_repo_dataset_migration_is_dry_run_then_journaled_and_undoable(tmp_path: Path) -> None:
    ensure_workspace(tmp_path)
    repo = default_record(
        "repo",
        title="HIW-500",
        maturity="complete",
        source={
            "original_uri": "https://huggingface.co/datasets/BitRobot/HIW-500",
            "backup_paths": [],
            "backup_kind": "url",
            "file_hash": "",
        },
    )
    repo["status"] = "active"
    repo["payload"]["capability"]["core_capabilities"] = ["Legacy dataset positioning."]
    repo["payload"]["structure"]["entrypoints"] = ["Legacy LeRobot access note."]
    repo["payload"]["reuse"]["directly_reusable"] = ["Legacy reuse note."]
    old_path = write_record(tmp_path, repo)
    source_dir = old_path.parent / "source"
    source_dir.mkdir()
    (source_dir / "snapshot.md").write_text("HIW-500 dataset card", encoding="utf-8")
    parse_cache = old_path.parent / "parse-cache.yaml"
    parse_cache.write_text(
        yaml.safe_dump({"repo_id": repo["id"], "chunks": [{"text": "HIW-500 dataset card"}]}),
        encoding="utf-8",
    )
    parse_cache_bytes = parse_cache.read_bytes()
    program_state = tmp_path / "kb/programs/humanoid-review/state.yaml"
    program_state.parent.mkdir(parents=True)
    program_state.write_text(
        yaml.safe_dump({"program_id": "humanoid-review", "active_unit_ids": [repo["id"]]}),
        encoding="utf-8",
    )
    before = tuple(sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")))

    plan = dataset_migration_plan(tmp_path, repo["id"])

    assert plan["new_id"].startswith("d-hiw-500-")
    assert tuple(sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))) == before

    targets = dataset_migration_targets(tmp_path, plan)
    with mutation_transaction(tmp_path, "test_repo_to_dataset", targets):
        result = migrate_repo_to_dataset(tmp_path, repo["id"])

    new_path = record_path(tmp_path, "dataset", result["new_id"])
    migrated = load_yaml(new_path)
    assert not old_path.exists()
    assert migrated["kind"] == "dataset"
    assert repo["id"] in migrated["legacy_ids"]
    assert migrated["confirmation_status"] == "pending_user_confirmation"
    assert migrated["payload"]["state"]["profile_status"] == "awaiting_agent_fill"
    assert (new_path.parent / "source/snapshot.md").read_text(encoding="utf-8") == "HIW-500 dataset card"
    assert (new_path.parent / "parse-cache.yaml").read_bytes() == parse_cache_bytes
    assert load_yaml(program_state)["active_unit_ids"] == [result["new_id"]]

    undo_last_operation(tmp_path)

    assert old_path.exists()
    assert not new_path.exists()
    assert load_yaml(program_state)["active_unit_ids"] == [repo["id"]]


def test_repo_html_snapshot_is_not_a_structure_scan_target(tmp_path: Path) -> None:
    repo_module = _load_script(
        ".agents/skills/repo-analyst/scripts/repo.py",
        "repo_scan_applicability_dataset_guard",
    )
    repo = default_record(
        "repo",
        title="Remote Dataset Page",
        maturity="complete",
        source={
            "original_uri": "https://huggingface.co/datasets/example/data",
            "backup_paths": ["kb/units/repos/r-remote/source/snapshot.md"],
            "backup_kind": "url",
        },
    )
    snapshot = tmp_path / "kb/units/repos/r-remote/source/snapshot.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("dataset card", encoding="utf-8")

    applicable, reason = repo_module.structure_scan_applicability(tmp_path, repo)

    assert applicable is False
    assert reason == "remote_page_without_source_tree"

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.experiment_imports import load_import_batch
from research.index import audit_workspace


PROJECT_ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT_SCRIPT = PROJECT_ROOT / ".agents" / "skills" / "experiment-workbench" / "scripts" / "experiment.py"


def _experiment_module():
    spec = importlib.util.spec_from_file_location("experiment_import_owner", EXPERIMENT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _main(module, monkeypatch: pytest.MonkeyPatch, root: Path, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", [str(EXPERIMENT_SCRIPT), "--root", str(root), *args])
    return module.main()


def _plan(module, monkeypatch: pytest.MonkeyPatch, root: Path, title: str = "import target") -> tuple[str, Path]:
    assert _main(module, monkeypatch, root, "plan", "--title", title, "--program-id", "program-import") == 0
    record_path = next((root / "kb" / "units" / "experiments").glob("*/record.yaml"))
    experiment_id = str(load_yaml(record_path)["id"])
    write_yaml_if_changed(
        root / "kb" / "programs" / "program-import" / "state.yaml",
        {"program_id": "program-import", "stage": "experiment", "active_unit_ids": [experiment_id]},
    )
    return experiment_id, record_path


def _runs(count: int = 10) -> list[dict[str, object]]:
    return [
        {
            "id": f"wandb-{index:03d}",
            "state": "finished",
            "seed": index,
            "config": {"optimizer": "adam", "lr": 0.001},
            "tested_hypothesis": "Adam improves the fixed benchmark configuration.",
            "changes": ["optimizer=adam", "lr=0.001"],
            "summary": {"success_rate": 0.5 + index / 100},
            "result_summary": f"Observed imported run {index}.",
        }
        for index in range(count)
    ]


def _business_snapshot(unit_root: Path, program_root: Path) -> dict[str, bytes]:
    paths = [
        *sorted(path for path in unit_root.rglob("*") if path.is_file()),
        *sorted(path for path in program_root.rglob("*") if path.is_file()),
    ]
    return {path.relative_to(unit_root.parent.parent.parent.parent).as_posix(): path.read_bytes() for path in paths}


def test_wandb_json_normalization_is_factual_and_stable(tmp_path: Path) -> None:
    source = tmp_path / "staging" / "wandb.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"runs": _runs(10)}), encoding="utf-8")

    first = load_import_batch(tmp_path, "staging/wandb.json")
    second = load_import_batch(tmp_path, "staging/wandb.json")

    assert first["batch_digest"] == second["batch_digest"]
    assert len(first["runs"]) == 10
    assert first["runs"][0]["outcome"] == "success"
    assert first["runs"][0]["metrics"]["success_rate"]["direction"] == "unknown"
    assert first["runs"][0]["config_revision"].startswith("config-sha256:")
    assert "diagnos" not in json.dumps(first["runs"], ensure_ascii=False).lower()


def test_csv_rejects_duplicate_header_and_nonfinite_metrics(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("external_id,external_id\na,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate columns"):
        load_import_batch(tmp_path, "duplicate.csv")

    nonfinite = tmp_path / "nonfinite.csv"
    nonfinite.write_text("external_id,metric.loss\na,nan\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be numeric|finite"):
        load_import_batch(tmp_path, "nonfinite.csv")


def test_csv_and_flat_json_directory_are_supported(tmp_path: Path) -> None:
    csv_source = tmp_path / "runs.csv"
    csv_source.write_text(
        "external_id,seed,config_revision,state,metric.loss,metric.loss.unit,metric.loss.direction\n"
        "csv-a,1,rev-a,finished,1.25,ratio,lower-better\n"
        "csv-b,2,rev-a,running,1.10,ratio,lower-better\n",
        encoding="utf-8",
    )
    csv_batch = load_import_batch(tmp_path, "runs.csv")
    assert [item["outcome"] for item in csv_batch["runs"]] == ["success", "inconclusive"]
    assert csv_batch["runs"][0]["metrics"]["loss"] == {
        "name": "loss", "value": 1.25, "unit": "ratio", "direction": "lower-better"
    }

    directory = tmp_path / "run-directory"
    directory.mkdir()
    for index, item in enumerate(_runs(2), start=1):
        (directory / f"run-{index:03d}.json").write_text(json.dumps(item), encoding="utf-8")
    directory_batch = load_import_batch(tmp_path, "run-directory")
    assert directory_batch["format"] == "json-directory"
    assert [item["external_id"] for item in directory_batch["runs"]] == ["wandb-000", "wandb-001"]


def test_json_duplicate_fields_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.json"
    source.write_text('[{"id":"first","id":"second","config_revision":"rev"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_import_batch(tmp_path, "duplicate.json")


def test_directory_source_rejects_symlink_and_unexpected_entry(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "run-a.json").write_text(json.dumps(_runs(1)[0]), encoding="utf-8")
    (staging / "notes.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="only single-level"):
        load_import_batch(tmp_path, "staging")
    (staging / "notes.txt").unlink()
    (staging / "run-link.json").symlink_to(staging / "run-a.json")
    with pytest.raises(ValueError, match="regular file|symlink"):
        load_import_batch(tmp_path, "staging")


def test_imports_ten_runs_idempotently_and_conflicts_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _experiment_module()
    experiment_id, record_path = _plan(module, monkeypatch, tmp_path)
    source = tmp_path / "staging" / "wandb.json"
    source.parent.mkdir()
    source.write_text(json.dumps(_runs(10)), encoding="utf-8")

    assert _main(
        module,
        monkeypatch,
        tmp_path,
        "import-runs",
        "--experiment-id",
        experiment_id,
        "--source",
        "staging/wandb.json",
    ) == 0
    assert "导入 10 条，跳过 0 条，冲突 0 条" in capsys.readouterr().out

    unit_root = record_path.parent
    run_log = load_yaml(unit_root / "run-log.yaml")
    items = run_log["items"]
    assert [item["id"] for item in items] == [f"run-{index:03d}" for index in range(1, 11)]
    assert all(item["source"] == "imported" for item in items)
    assert all(item["information_types"] == ["fact"] for item in items)
    assert all(item["import_provenance"]["source_artifact"].startswith("kb/units/experiments/") for item in items)
    assert str(tmp_path) not in json.dumps(run_log, ensure_ascii=False)
    assert len(list((unit_root / "runs").glob("run-*.md"))) == 10
    assert len(list((unit_root / "imports").glob("*.json"))) == 1
    events_path = tmp_path / "kb" / "programs" / "program-import" / "workflow" / "reporting-events.yaml"
    events = [item for item in load_yaml(events_path)["items"] if item["event_type"] == "experiment-run-import"]
    assert len(events) == 1
    audit = audit_workspace(tmp_path)
    assert audit["counts"]["error"] == 0, json.dumps(audit, ensure_ascii=False, indent=2)
    assert not [
        item for item in audit["findings"]
        if "experiment" in item["subject"].lower() or "experiment" in item["code"].lower()
    ]

    before = _business_snapshot(unit_root, events_path.parents[1])
    assert _main(
        module,
        monkeypatch,
        tmp_path,
        "import-runs",
        "--experiment-id",
        experiment_id,
        "--source",
        "staging/wandb.json",
    ) == 0
    assert "导入 0 条，跳过 10 条，冲突 0 条" in capsys.readouterr().out
    assert _business_snapshot(unit_root, events_path.parents[1]) == before

    changed = _runs(10)
    changed[0]["result_summary"] = "Different source bytes for the same imported identity."
    source.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(SystemExit, match="conflict"):
        _main(
            module,
            monkeypatch,
            tmp_path,
            "import-runs",
            "--experiment-id",
            experiment_id,
            "--source",
            "staging/wandb.json",
        )
    assert _business_snapshot(unit_root, events_path.parents[1]) == before


def test_mid_batch_failure_rolls_back_raw_archive_and_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _experiment_module()
    experiment_id, record_path = _plan(module, monkeypatch, tmp_path, "rollback target")
    source = tmp_path / "staging" / "wandb.json"
    source.parent.mkdir()
    source.write_text(json.dumps(_runs(10)), encoding="utf-8")
    original = module._write_run_files_exclusive_batch

    def fail_after_run_writes(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after run writes")

    monkeypatch.setattr(module, "_write_run_files_exclusive_batch", fail_after_run_writes)
    with pytest.raises(RuntimeError, match="injected"):
        _main(
            module,
            monkeypatch,
            tmp_path,
            "import-runs",
            "--experiment-id",
            experiment_id,
            "--source",
            "staging/wandb.json",
        )

    unit_root = record_path.parent
    assert not (unit_root / "run-log.yaml").exists()
    assert not (unit_root / "run-log.md").exists()
    assert not (unit_root / "runs").exists()
    assert not (unit_root / "imports").exists()
    assert load_yaml(record_path)["status"] == "planned"


def test_malformed_late_item_performs_zero_business_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _experiment_module()
    experiment_id, record_path = _plan(module, monkeypatch, tmp_path, "preflight target")
    bad = _runs(10)
    bad.append({"id": "bad", "config": [], "summary": {"loss": 1.0}})
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(SystemExit, match="config must be an object"):
        _main(
            module,
            monkeypatch,
            tmp_path,
            "import-runs",
            "--experiment-id",
            experiment_id,
            "--source",
            "bad.json",
        )
    assert not (record_path.parent / "runs").exists()
    assert not (record_path.parent / "imports").exists()
    assert not (record_path.parent / "run-log.yaml").exists()

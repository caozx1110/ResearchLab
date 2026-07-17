from __future__ import annotations

import importlib.util
from pathlib import Path


def _experiment_module():
    project_root = Path(__file__).resolve().parents[4]
    script = project_root / ".agents" / "skills" / "experiment-workbench" / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_workbench_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_typed_metric_parses_value_unit_and_direction() -> None:
    module = _experiment_module()

    metrics = module.parse_metrics(["success_rate=0.82[ratio]:higher-better"])

    assert metrics == {
        "success_rate": {
            "name": "success_rate",
            "value": 0.82,
            "unit": "ratio",
            "direction": "higher-better",
        }
    }


def test_bare_metric_remains_backward_compatible(capsys) -> None:
    module = _experiment_module()

    metrics = module.parse_metrics(["loss=1.25", "status=converged"])

    assert metrics["loss"]["value"] == 1.25
    assert metrics["loss"]["unit"] == ""
    assert metrics["loss"]["direction"] == "unknown"
    assert metrics["status"]["value"] == "converged"
    assert "preserving it as a string" in capsys.readouterr().err

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from research.v2 import load_runtime_preferences


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def test_pdf_figure_extraction_mode_surfaces_in_runtime_preferences_and_config_guide(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    preferences = load_runtime_preferences(root)

    assert preferences["pdf"]["figure_extraction_mode"] == "caption-region"

    script = _project_root() / ".agents" / "skills" / "research-config-manager" / "scripts" / "config.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "guide", "--focus", "paper-intake"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(_project_root() / ".agents" / "lib")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "- PDF Figure 模式: caption-region" in result.stdout
    assert "- PDF Figure 模式: None" not in result.stdout

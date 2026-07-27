from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT


def _project_root() -> Path:
    return REPO_ROOT


def _load_script_module(skill: str, script_name: str, module_name: str):
    script = _project_root() / ".agents" / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wiki_add_forward_uses_skills_home_without_workspace_agents(tmp_path: Path, monkeypatch) -> None:
    wiki = _load_script_module("wiki-adapter", "wiki.py", "wiki_adapter_script_for_skills_home_forward_test")
    captured_argv: list[str] = []
    kb_workspace = tmp_path / "kb-workspace"
    kb_workspace.mkdir()
    monkeypatch.setenv("RESEARCH_PROJECT_ROOT", str(kb_workspace))

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wiki.subprocess, "run", fake_run)
    args = argparse.Namespace(
        kind="paper",
        source="https://example.com/paper.pdf",
        maturity="lightweight",
        title="Demo Paper",
        pool=[],
    )

    assert wiki.run_intake_add(kb_workspace, args) == 0

    expected_script = _project_root() / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
    assert captured_argv[1] == str(expected_script)
    assert Path(captured_argv[1]).exists()
    assert captured_argv[2:4] == ["--root", str(kb_workspace)]
    assert captured_argv[4:] == [
        "add",
        "--kind",
        "paper",
        "--source",
        "https://example.com/paper.pdf",
        "--maturity",
        "lightweight",
        "--title",
        "Demo Paper",
    ]

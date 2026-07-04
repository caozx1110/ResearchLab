from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.v2 import project_root


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_script_module(skill: str, script_name: str, module_name: str):
    root = _project_root()
    script = root / ".agents" / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_project_root_env_and_flag_overrides_do_not_require_agents_marker(tmp_path: Path, monkeypatch) -> None:
    env_root = tmp_path / "env-root"
    flag_root = tmp_path / "flag-root"
    env_root.mkdir()
    flag_root.mkdir()
    monkeypatch.setenv("RESEARCH_PROJECT_ROOT", str(env_root))

    assert project_root(tmp_path) == env_root.resolve()
    assert project_root(tmp_path, explicit_root=flag_root) == flag_root.resolve()


def test_kb_init_warns_when_cwd_differs_from_explicit_root(tmp_path: Path, monkeypatch, capsys) -> None:
    kb = _load_script_module("knowledge-base-manager", "kb.py", "kb_script_for_root_test")
    root = tmp_path / "project"
    cwd = tmp_path / "elsewhere"
    root.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["kb.py", "--root", str(root), "init"])

    assert kb.main() == 0

    captured = capsys.readouterr()
    assert "[root] project:" in captured.out
    assert "[root] kb:" in captured.out
    assert "[warn] kb.py init: cwd differs from resolved project root" in captured.out


def test_config_init_warns_when_cwd_differs_from_explicit_root(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _load_script_module("research-config-manager", "config.py", "config_script_for_root_test")
    root = tmp_path / "project"
    cwd = tmp_path / "elsewhere"
    root.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "argv", ["config.py", "--root", str(root), "init"])

    assert config.main() == 0

    captured = capsys.readouterr()
    assert "[root] project:" in captured.out
    assert "[root] kb:" in captured.out
    assert "[warn] config.py init: cwd differs from resolved project root" in captured.out

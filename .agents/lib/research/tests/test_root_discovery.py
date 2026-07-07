from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from research.common import skill_script_for_command
from research.core import project_root, skills_root


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


def test_skills_root_ignores_decoupled_kb_workspace(tmp_path: Path, monkeypatch) -> None:
    real_root = _project_root()
    kb_workspace = tmp_path / "kb-workspace"
    kb_workspace.mkdir()
    monkeypatch.setenv("RESEARCH_PROJECT_ROOT", str(kb_workspace))
    monkeypatch.chdir(kb_workspace)

    assert skills_root() == real_root
    assert skills_root() != project_root()
    assert (skills_root() / ".agents" / "skills").is_dir()


def test_skills_root_env_override(tmp_path: Path, monkeypatch) -> None:
    skills_home = tmp_path / "skills-home"
    (skills_home / ".agents" / "skills").mkdir(parents=True)
    monkeypatch.setenv("RESEARCH_SKILLS_HOME", str(skills_home))

    assert skills_root() == skills_home.resolve()
    assert skill_script_for_command(".agents/skills/source-intake/scripts/intake.py") == (
        skills_home.resolve() / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
    ).as_posix()


def test_write_command_root_and_env_override_symlinked_agents_target(tmp_path: Path) -> None:
    real_root = _project_root()
    symlink_target = tmp_path / "symlink-target"
    sandbox_root = tmp_path / "sandbox"
    symlink_target.mkdir()
    sandbox_root.mkdir()
    (symlink_target / ".agents").symlink_to(real_root / ".agents", target_is_directory=True)
    (symlink_target / "AGENTS.md").write_text("# target\n", encoding="utf-8")
    (sandbox_root / ".agents").symlink_to(symlink_target / ".agents", target_is_directory=True)
    (sandbox_root / "AGENTS.md").write_text("# sandbox\n", encoding="utf-8")
    script = sandbox_root / ".agents" / "skills" / "knowledge-base-manager" / "scripts" / "kb.py"
    env = {**os.environ, "PYTHONPATH": str(real_root / ".agents" / "lib")}

    root_result = subprocess.run(
        [sys.executable, str(script), "--root", str(sandbox_root), "init"],
        cwd=sandbox_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert root_result.returncode == 0, root_result.stderr
    assert (sandbox_root / "kb" / "index.yaml").exists()
    assert not (symlink_target / "kb").exists()

    (sandbox_root / "kb").rename(sandbox_root / "kb-root-flag")
    env_result = subprocess.run(
        [sys.executable, str(script), "init"],
        cwd=sandbox_root,
        env={**env, "RESEARCH_PROJECT_ROOT": str(sandbox_root)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert env_result.returncode == 0, env_result.stderr
    assert (sandbox_root / "kb" / "index.yaml").exists()
    assert not (symlink_target / "kb").exists()


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

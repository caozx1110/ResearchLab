from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT
from research.common import resolve_skill_script_path
from research.skill_validator import validate_skills


def _load_ws_sync():
    install_lib = REPO_ROOT / "install-lib"
    if str(install_lib) not in sys.path:
        sys.path.insert(0, str(install_lib))
    path = install_lib / "ws_sync.py"
    spec = importlib.util.spec_from_file_location("source_layout_ws_sync", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_agent_plan():
    install_lib = REPO_ROOT / "install-lib"
    if str(install_lib) not in sys.path:
        sys.path.insert(0, str(install_lib))
    path = install_lib / "agent_plan.py"
    spec = importlib.util.spec_from_file_location("source_layout_agent_plan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_rule_checker():
    path = REPO_ROOT / "tools" / "check_rule_tokens.py"
    spec = importlib.util.spec_from_file_location("source_layout_rule_checker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_source(root: Path) -> None:
    _write(root / ".gitignore", "/.agents/\n")
    _write(root / "LICENSE", "test license\n")
    _write(root / "install.sh", "#!/bin/sh\n")
    _write(root / "requirements.txt", "PyYAML\n")
    _write(root / "install-lib" / "placeholder", "installer input\n")
    _write(root / "skills" / "metadata.yaml", "skills: {}\n")
    _write(root / "skills" / "kb-cli" / "SKILL.md", "---\nname: kb-cli\n---\n")
    _write(root / "skills" / "kb-cli" / "scripts" / "kb", "#!/usr/bin/env python3\n")
    _write(root / "runtime" / "AGENTS.md", "# Installed rules\n")
    _write(root / "runtime" / "AGENT_GUIDE.md", "# Installed guide\n")
    _write(root / "runtime" / "VERSION", "0.2.0-test\n")
    _write(root / "runtime" / "requirements.txt", "PyYAML\n")
    _write(root / "runtime" / "lib" / "research" / "__init__.py", "")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "add",
            ".gitignore",
            "LICENSE",
            "install.sh",
            "requirements.txt",
            "install-lib",
            "skills",
            "runtime",
        ],
        check=True,
    )


def test_repository_tracks_product_sources_but_not_local_agent_tools() -> None:
    tracked_local = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", ".agents"],
        check=True,
        capture_output=True,
        text=True,
    )
    ignored_local = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "check-ignore",
            "-q",
            "--",
            ".agents/skills/local-only/SKILL.md",
        ],
        check=False,
    )

    assert tracked_local.stdout == ""
    assert ignored_local.returncode == 0
    assert len(list((REPO_ROOT / "skills").glob("*/SKILL.md"))) == 15
    assert (REPO_ROOT / "runtime" / "AGENTS.md").is_file()


def test_release_mapping_is_explicit_and_excludes_developer_only_files() -> None:
    ws_sync = _load_ws_sync()

    assert ws_sync.release_destination("skills/kb-cli/scripts/kb") == ".agents/skills/kb-cli/scripts/kb"
    assert ws_sync.release_destination("runtime/lib/research/common.py") == ".agents/lib/research/common.py"
    assert ws_sync.release_destination("runtime/AGENTS.md") == ".agents/AGENTS.md"
    assert ws_sync.release_destination("runtime/VERSION") == ".agents/VERSION"
    assert ws_sync.release_destination("LICENSE") == ".agents/LICENSE"
    assert ws_sync.release_destination("runtime/README.md") is None
    assert ws_sync.release_destination("runtime/lib/research/skill_validator.py") is None
    assert ws_sync.release_destination("skills/skill-evolution-advisor/scripts/eval_research_value.py") is None
    assert ws_sync.release_destination(".agents/skills/kb-cli/scripts/kb") is None


def test_ignored_same_name_local_skill_cannot_change_release_or_plan_digest(tmp_path: Path) -> None:
    ws_sync = _load_ws_sync()
    agent_plan = _load_agent_plan()
    source = tmp_path / "source"
    _minimal_source(source)

    before_files = ws_sync.tracked_release_files(source)
    before_items = ws_sync.source_items(source, source)
    before_tree = agent_plan.distributable_tree(source)

    local_decoy = source / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    _write(local_decoy, "#!/bin/sh\necho hijacked\n")

    assert ws_sync.tracked_release_files(source) == before_files
    assert ws_sync.source_items(source, source) == before_items
    assert agent_plan.distributable_tree(source) == before_tree
    assert all(not path.startswith(".agents/") for path in before_files)
    assert all(
        not source_path.relative_to(source).as_posix().startswith(".agents/")
        for source_path, _digest in before_items.values()
    )


def test_local_agent_churn_cannot_change_validator_or_rule_budget(tmp_path: Path) -> None:
    checker = _load_rule_checker()
    source = tmp_path / "source"
    shutil.copytree(REPO_ROOT / "skills", source / "skills")
    _write(source / "runtime" / "AGENTS.md", (REPO_ROOT / "runtime" / "AGENTS.md").read_text(encoding="utf-8"))
    _write(
        source / "runtime" / "AGENT_GUIDE.md",
        (REPO_ROOT / "runtime" / "AGENT_GUIDE.md").read_text(encoding="utf-8"),
    )
    before_errors = validate_skills(source / "skills")
    before_budget = checker.measure_rule_bundles(source)

    _write(
        source / ".agents" / "skills" / "kb-cli" / "SKILL.md",
        "---\nname: kb-cli\ndescription: local decoy\n---\n",
    )
    _write(
        source / ".agents" / "skills" / "gh-collaborate" / "SKILL.md",
        "---\nname: gh-collaborate\ndescription: local tool\n---\n",
    )

    assert validate_skills(source / "skills") == before_errors == []
    assert checker.measure_rule_bundles(source) == before_budget
    assert before_budget["discoverable_skill_count"] == 15


def test_skill_route_resolver_rejects_untrusted_or_escaping_routes(tmp_path: Path) -> None:
    home = tmp_path / "installed"
    _write(home / ".agents" / "skills" / "metadata.yaml", "skills: {}\n")
    _write(home / ".agents" / "lib" / "research" / "__init__.py", "")
    outside = tmp_path / "outside.py"
    _write(outside, "raise SystemExit('hijacked')\n")
    linked = home / ".agents" / "skills" / "demo" / "scripts" / "run.py"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(outside)

    for route in ("skills/demo/scripts/run.py", "/tmp/run.py", ".agents/skills/../outside.py"):
        with pytest.raises(ValueError):
            resolve_skill_script_path(route, explicit_home=home)
    with pytest.raises(ValueError, match="escaped"):
        resolve_skill_script_path(".agents/skills/demo/scripts/run.py", explicit_home=home)

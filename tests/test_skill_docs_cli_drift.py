from __future__ import annotations

import ast
import re
from pathlib import Path

from repo_paths import REPO_ROOT


SKILL_SCRIPTS = {
    "discussion-archivist": "archive.py",
    "experiment-workbench": "experiment.py",
    "idea-workbench": "idea.py",
    "knowledge-base-manager": "kb.py",
    "method-designer": "method.py",
    "research-config-manager": "config.py",
    "research-orchestrator": "orchestrate.py",
    "skill-evolution-advisor": "create_retrospective.py",
}

IMPLEMENTATION_DOCS = {
    "dataset-analyst": ("dataset.py", "unit-analyst"),
    "paper-analyst": ("paper.py", "unit-analyst"),
}


def _project_root() -> Path:
    return REPO_ROOT


def _argparse_subcommands(skill: str, script_name: str) -> set[str]:
    script = _project_root() / ".agents" / "skills" / skill / "scripts" / script_name
    tree = ast.parse(script.read_text(encoding="utf-8"))
    subcommands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_parser":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            continue
        subcommands.add(node.args[0].value)
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, (ast.List, ast.Tuple)):
            continue
        values = [item.value for item in node.iter.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        if not values:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if not isinstance(func, ast.Attribute) or func.attr != "add_parser":
                continue
            if child.args and isinstance(child.args[0], ast.Name) and child.args[0].id == node.target.id:
                subcommands.update(values)
    return subcommands


def _documented_subcommands(skill: str, script_name: str, *, doc_skill: str | None = None) -> set[str]:
    text = (_project_root() / ".agents" / "skills" / (doc_skill or skill) / "SKILL.md").read_text(encoding="utf-8")
    pattern = re.compile(rf"scripts/{re.escape(script_name)}\s+([^\s\\]+)")
    return {match.group(1) for match in pattern.finditer(text) if not match.group(1).startswith("-")}


def test_skill_docs_only_reference_argparse_subcommands() -> None:
    for skill, script_name in SKILL_SCRIPTS.items():
        documented = _documented_subcommands(skill, script_name)
        argparse_subcommands = _argparse_subcommands(skill, script_name)
        assert documented <= argparse_subcommands, f"{skill}: {sorted(documented - argparse_subcommands)}"
    for skill, (script_name, doc_skill) in IMPLEMENTATION_DOCS.items():
        documented = _documented_subcommands(skill, script_name, doc_skill=doc_skill)
        argparse_subcommands = _argparse_subcommands(skill, script_name)
        assert documented <= argparse_subcommands, f"{skill}: {sorted(documented - argparse_subcommands)}"

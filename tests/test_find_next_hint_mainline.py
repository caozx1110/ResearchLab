"""F7: `kb find` / review `next:` hints must point at current mainline verbs.

The old-flow blog verb `summarize` was renamed to the fillable `complete-note`
prepare; the analyzer no longer exposes `summarize`, so rendering it as the next
step produced a broken command. These tests lock every kind's next verb to a
verb the corresponding analyzer actually exposes.
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT


def _project_root() -> Path:
    return REPO_ROOT


def _load_kb_module():
    script = _project_root() / "skills" / "knowledge-base-manager" / "scripts" / "kb.py"
    loader = importlib.machinery.SourceFileLoader("kb_manager_next_hint_under_test", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _analyzer_verbs(skill: str, script_name: str) -> set[str]:
    script = _project_root() / "skills" / skill / "scripts" / script_name
    module_name = f"{skill}_{script_name.removesuffix('.py')}_verbs_under_test"
    loader = importlib.machinery.SourceFileLoader(module_name, str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)

    parser = module.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return set(subparsers.choices)


def test_blog_next_hint_is_not_the_removed_summarize_verb() -> None:
    kb = _load_kb_module()
    assert kb.NEXT_COMMAND_BY_KIND["blog"] != "summarize"
    assert kb.NEXT_COMMAND_BY_KIND["blog"] == "complete-note"


def test_every_next_verb_exists_on_its_analyzer() -> None:
    kb = _load_kb_module()
    verbs_by_kind = {
        "paper": _analyzer_verbs("unit-analyst", "paper.py"),
        "repo": _analyzer_verbs("unit-analyst", "repo.py"),
        "blog": _analyzer_verbs("unit-analyst", "blog.py"),
    }
    for kind, verbs in verbs_by_kind.items():
        next_verb = kb.NEXT_COMMAND_BY_KIND[kind]
        assert next_verb in verbs, f"kb find next hint for {kind} points at non-existent verb {next_verb!r}"


def test_blog_next_command_renders_runnable_prepare() -> None:
    kb = _load_kb_module()
    record = {"id": "b-langwbc-123456", "kind": "blog"}
    command = kb.next_unit_command(record)
    assert ".agents/skills/unit-analyst/scripts/blog.py complete-note --blog-id b-langwbc-123456" in command
    assert "summarize" not in command

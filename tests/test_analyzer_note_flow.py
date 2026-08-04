from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT, source_path
from research.analyzer_note_flow import AnalyzerNoteFlow
from research.core import ensure_workspace


def _load_adapter(relative: str, module_name: str):
    path = source_path(relative)
    loader = importlib.machinery.SourceFileLoader(module_name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_blog_and_dataset_delegate_to_one_shared_lifecycle() -> None:
    blog = _load_adapter(
        ".agents/skills/unit-analyst/scripts/blog.py",
        "shared_flow_blog_adapter",
    )
    dataset = _load_adapter(
        ".agents/skills/unit-analyst/scripts/dataset.py",
        "shared_flow_dataset_adapter",
    )

    assert isinstance(blog.FLOW, AnalyzerNoteFlow)
    assert isinstance(dataset.FLOW, AnalyzerNoteFlow)
    for name in (
        "build_note_scaffold",
        "verify_note_fill",
        "apply_note_fill_to_payload",
        "finalize_post_actions",
        "run_note",
        "run_confirm",
    ):
        blog_method = getattr(blog.FLOW, name)
        dataset_method = getattr(dataset.FLOW, name)
        assert blog_method.__func__ is getattr(AnalyzerNoteFlow, name)
        assert dataset_method.__func__ is getattr(AnalyzerNoteFlow, name)


def test_shared_owner_uses_narrow_modules_not_core_facade() -> None:
    source = (
        REPO_ROOT / "runtime" / "lib" / "research" / "analyzer_note_flow.py"
    ).read_text(encoding="utf-8")

    assert "research.core" not in source
    assert "from .core" not in source


def test_shared_transaction_rolls_back_adapter_write(tmp_path: Path) -> None:
    blog = _load_adapter(
        ".agents/skills/unit-analyst/scripts/blog.py",
        "shared_flow_rollback_blog_adapter",
    )
    ensure_workspace(tmp_path)
    target = tmp_path / "kb" / "notes" / "analyzer-rollback.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("before\n", encoding="utf-8")

    def fail_after_write() -> int:
        target.write_text("after\n", encoding="utf-8")
        raise RuntimeError("force analyzer rollback")

    with pytest.raises(RuntimeError, match="force analyzer rollback"):
        blog.FLOW._transaction("test-rollback", tmp_path, [target], fail_after_write)

    assert target.read_text(encoding="utf-8") == "before\n"


def test_shared_fill_scope_rejects_symlink_escape(tmp_path: Path) -> None:
    unit_root = tmp_path / "kb" / "units" / "blogs" / "b-test"
    unit_root.mkdir(parents=True)
    outside = tmp_path / "outside-fill.yaml"
    outside.write_text("elements: []\n", encoding="utf-8")
    linked = unit_root / "blog-fill.yaml"
    linked.symlink_to(outside)

    assert AnalyzerNoteFlow.unit_owned_fill_path(unit_root, linked) is None


def test_shared_deferred_post_actions_have_no_checkpoint_side_effect(
    tmp_path: Path,
) -> None:
    blog = _load_adapter(
        ".agents/skills/unit-analyst/scripts/blog.py",
        "shared_flow_deferred_blog_adapter",
    )
    original_checkpoint = blog.FLOW._checkpoint

    def unexpected_checkpoint(*_args, **_kwargs):
        raise AssertionError("deferred flow must not checkpoint")

    blog.FLOW._checkpoint = unexpected_checkpoint
    try:
        result = blog.FLOW.finalize_post_actions(
            tmp_path,
            trigger="milestone",
            message="must stay deferred",
            defer_post_actions=True,
            target_paths=[tmp_path / "kb" / "record.yaml"],
        )
    finally:
        blog.FLOW._checkpoint = original_checkpoint

    assert result == {"committed": False, "status": "deferred"}

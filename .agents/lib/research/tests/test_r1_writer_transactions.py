from __future__ import annotations

import importlib.util
import sys
from datetime import datetime as RealDateTime
from pathlib import Path

import pytest

from research.common import load_yaml, write_text_if_changed, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.core import default_record, ensure_workspace, record_path
from research.git_ops import dirty_kb_paths, undo_last_operation


ROOT = Path(__file__).resolve().parents[4]


def _load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _argv(monkeypatch, *values: str) -> None:
    monkeypatch.setattr(sys, "argv", list(values))


def _raise_after_text(path: Path, text: str) -> None:
    write_text_if_changed(path, text)
    raise RuntimeError("injected after first write")


def _workspace(root: Path) -> None:
    (root / ".agents").mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(root)


def _confirmed_survey_source(root: Path) -> None:
    unit_id = "p-survey-writer-123456"
    record = default_record("paper", title="Robot Learning", maturity="complete")
    record.update(
        id=unit_id,
        summary="robot learning",
        confirmation_status="pending_user_confirmation",
        needs_human_confirmation=True,
        information_types=["fact"],
    )
    apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed source unit"],
        project_root=root,
    )
    write_yaml_if_changed(record_path(root, "paper", unit_id), record)


def _tree_snapshot(root: Path) -> list[tuple[str, str, bytes]]:
    if not root.exists():
        return []
    snapshot = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot.append((relative, "symlink", str(path.readlink()).encode()))
        elif path.is_dir():
            snapshot.append((relative, "dir", b""))
        else:
            snapshot.append((relative, "file", path.read_bytes()))
    return snapshot


def test_core_init_checkpoints_every_created_product_file(tmp_path: Path, monkeypatch) -> None:
    module = _load(
        ".agents/skills/knowledge-base-manager/scripts/kb.py",
        "r1_core_init_checkpoint",
    )
    root = tmp_path / "workspace"
    (root / ".agents").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    _argv(monkeypatch, "kb.py", "--root", str(root), "init")

    assert module.main() == 0
    assert (root / "kb/.git").is_dir()
    assert dirty_kb_paths(root) == []
    assert (root / "kb/config/research-settings.md").is_file()
    assert (root / "kb/user/current-state.md").is_file()
    assert (root / "kb/user/navigation.md").is_file()
    navigation = (root / "kb/user/navigation.md").read_text(encoding="utf-8")
    assert "research-navigator" not in navigation
    assert "Agent 可在需要时生成研究入口" in navigation


def test_archive_fault_restores_note_and_reporting_event(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/discussion-archivist/scripts/archive.py", "r1_archive_fault")
    root = tmp_path / "workspace"
    _workspace(root)
    _argv(monkeypatch, "archive.py", "--root", str(root), "archive", "--program-id", "p-a", "--title", "Route", "--summary", "Summary")
    monkeypatch.setattr(module, "append_program_reporting_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected")))

    with pytest.raises(RuntimeError, match="injected"):
        module.main()

    assert not (root / "kb/programs/p-a/discussions/route.md").exists()
    assert not (root / "kb/programs/p-a/workflow/reporting-events.yaml").exists()


def test_synthesizer_fault_restores_single_prepare_output(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/literature-synthesizer/scripts/synthesize.py", "r1_synth_fault")
    root = tmp_path / "workspace"
    _workspace(root)
    _confirmed_survey_source(root)
    _argv(monkeypatch, "synthesize.py", "--root", str(root), "survey", "prepare", "--query", "robot learning", "--as-of", "2026-07-19")
    original = module.write_yaml_if_changed

    def fail(path, value):
        original(path, value)
        raise RuntimeError("injected after first write")

    monkeypatch.setattr(module, "write_yaml_if_changed", fail)
    with pytest.raises(RuntimeError, match="injected"):
        module.main()
    assert not (root / "kb/synthesis/robot-learning/survey-fill.yaml").exists()


def _selected_idea(root: Path) -> str:
    idea_id = "i-writer-123456"
    record = default_record(
        "idea",
        title="Transactional idea",
        maturity="lightweight",
        source={"original_uri": "discussion"},
    )
    record["id"] = idea_id
    record["status"] = "selected"
    write_yaml_if_changed(record_path(root, "idea", idea_id), record)
    return idea_id


def test_method_fault_restores_all_command_outputs(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/method-designer/scripts/method.py", "r1_method_fault")
    root = tmp_path / "workspace"
    _workspace(root)
    idea_id = _selected_idea(root)
    _argv(monkeypatch, "method.py", "--root", str(root), "design", "--idea-id", idea_id, "--program-id", "p-method")
    original = module.write_yaml_if_changed

    def fail(path, value):
        original(path, value)
        raise RuntimeError("injected after first yaml")

    monkeypatch.setattr(module, "write_yaml_if_changed", fail)
    with pytest.raises(RuntimeError, match="injected"):
        module.main()
    design = root / "kb/programs/p-method/design"
    assert not (design / f"{idea_id}-method.md").exists()
    assert not (design / f"{idea_id}-repo-choice.yaml").exists()
    assert not (root / "kb/programs/p-method/state.yaml").exists()
    assert not (root / "kb/programs/p-method/workflow/reporting-events.yaml").exists()


def test_wiki_fault_restores_query_note(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/wiki-adapter/scripts/wiki.py", "r1_wiki_fault")
    root = tmp_path / "workspace"
    _workspace(root)
    _argv(monkeypatch, "wiki.py", "--root", str(root), "query", "--question", "What is recovery?")
    monkeypatch.setattr(module, "write_text_if_changed", _raise_after_text)
    with pytest.raises(RuntimeError, match="injected"):
        module.main()
    assert not (root / "kb/synthesis/wiki/what-is-recovery.md").exists()


def test_wiki_lint_is_byte_identical_on_fresh_root(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/wiki-adapter/scripts/wiki.py", "r1_wiki_read")
    root = tmp_path / "fresh"
    before = _tree_snapshot(root)
    _argv(monkeypatch, "wiki.py", "--root", str(root), "lint")
    assert module.main() == 0
    assert _tree_snapshot(root) == before
    assert not root.exists()


def test_retrospective_fault_restores_note(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/skill-evolution-advisor/scripts/create_retrospective.py", "r1_retro_fault")
    root = tmp_path / "workspace"
    _workspace(root)
    note_root = root / "kb/memory/skill-evolution"
    _argv(monkeypatch, "create_retrospective.py", "--slug", "routing-gap", "--task-summary", "test", "--root", str(note_root))
    monkeypatch.setattr(module, "write_text_if_changed", _raise_after_text)
    with pytest.raises(RuntimeError, match="injected"):
        module.main()
    assert not list((note_root / "retrospectives").glob("*.md"))


def test_retrospective_collision_aborts_instead_of_committing_noop(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/skill-evolution-advisor/scripts/create_retrospective.py", "r1_retro_collision")
    root = tmp_path / "workspace"
    _workspace(root)
    note_root = root / "kb/memory/skill-evolution"

    class FixedDateTime:
        @classmethod
        def now(cls):
            return RealDateTime.fromisoformat("2026-07-19T12:00:00+08:00")

    monkeypatch.setattr(module, "datetime", FixedDateTime)
    args = ("create_retrospective.py", "--slug", "routing-gap", "--task-summary", "test", "--root", str(note_root))
    _argv(monkeypatch, *args)
    assert module.main() == 0
    _argv(monkeypatch, *args)
    assert module.main() == 1

    entries = [
        load_yaml(path, default={})
        for path in (root / "kb/.journal").glob("*.yaml")
    ]
    states = sorted(
        entry.get("state")
        for entry in entries
        if entry.get("op_type") == "create-skill-retrospective"
    )
    assert states == ["abort", "commit"]


def test_evaluator_fault_restores_report(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/skill-evolution-advisor/scripts/eval_research_value.py", "r1_eval_fault")
    root = tmp_path / "workspace"
    _workspace(root)
    _argv(monkeypatch, "eval.py", "--root", str(root))
    monkeypatch.setattr(module, "evaluate", lambda *args: {"questions": []})
    monkeypatch.setattr(module, "render_report", lambda *args: "report\n")
    monkeypatch.setattr(module, "probe_pdf_backends", lambda: {})
    monkeypatch.setattr(module, "git_short_head", lambda path: "test")
    monkeypatch.setattr(module, "write_text_if_changed", _raise_after_text)
    with pytest.raises(RuntimeError, match="injected"):
        module.main()
    assert not list((root / "kb/eval/research-value/reports").glob("*.md"))


def test_evaluator_no_write_is_byte_identical_on_fresh_root(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/skill-evolution-advisor/scripts/eval_research_value.py", "r1_eval_read")
    root = tmp_path / "fresh"
    before = _tree_snapshot(root)
    _argv(monkeypatch, "eval.py", "--root", str(root), "--no-write")
    monkeypatch.setattr(module, "evaluate", lambda *args: {"questions": []})
    monkeypatch.setattr(module, "render_report", lambda *args: "report\n")
    monkeypatch.setattr(module, "probe_pdf_backends", lambda: {})
    monkeypatch.setattr(module, "git_short_head", lambda path: "test")
    assert module.main() == 0
    assert _tree_snapshot(root) == before
    assert not root.exists()


def test_evaluator_same_timestamp_preserves_both_reports_and_undoes_only_last(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/skill-evolution-advisor/scripts/eval_research_value.py", "r1_eval_collision")
    root = tmp_path / "workspace"
    _workspace(root)

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            value = RealDateTime.fromisoformat("2026-07-19T12:00:00+00:00")
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        module,
        "evaluate",
        lambda _root, program: {"questions": [{"program_id": program or "all"}]},
    )
    monkeypatch.setattr(module, "render_report", lambda _root, _result, meta: f"report for {meta['programs'][0]}\n")
    monkeypatch.setattr(module, "probe_pdf_backends", lambda: {})
    monkeypatch.setattr(module, "git_short_head", lambda path: "test")

    _argv(monkeypatch, "eval.py", "--root", str(root), "--program", "alpha")
    assert module.main() == 0
    _argv(monkeypatch, "eval.py", "--root", str(root), "--program", "beta")
    assert module.main() == 0

    report_dir = root / "kb/eval/research-value/reports"
    first = report_dir / "20260719T120000Z-tier1.md"
    second = report_dir / "20260719T120000Z-tier1-2.md"
    assert first.read_text(encoding="utf-8") == "report for alpha\n"
    assert second.read_text(encoding="utf-8") == "report for beta\n"

    undo_last_operation(root)

    assert first.read_text(encoding="utf-8") == "report for alpha\n"
    assert not second.exists()


def test_single_file_prepare_is_undoable(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/literature-synthesizer/scripts/synthesize.py", "r1_synth_undo")
    root = tmp_path / "workspace"
    _workspace(root)
    _confirmed_survey_source(root)
    _argv(monkeypatch, "synthesize.py", "--root", str(root), "survey", "prepare", "--query", "robot learning", "--as-of", "2026-07-19")
    assert module.main() == 0
    output = root / "kb/synthesis/robot-learning/survey-fill.yaml"
    assert output.exists()
    undo_last_operation(root)
    assert not output.exists()


def test_multi_file_method_design_is_undoable(tmp_path: Path, monkeypatch) -> None:
    module = _load(".agents/skills/method-designer/scripts/method.py", "r1_method_undo")
    root = tmp_path / "workspace"
    _workspace(root)
    idea_id = _selected_idea(root)
    _argv(monkeypatch, "method.py", "--root", str(root), "design", "--idea-id", idea_id, "--program-id", "p-method")
    assert module.main() == 0
    design = root / "kb/programs/p-method/design"
    assert len(list(design.iterdir())) == 4
    undo_last_operation(root)
    # The first method proposal owns the newly-created design directory as one
    # recovery target, so undo restores the exact pre-operation state: absent.
    assert not design.exists()
    assert not (root / "kb/programs/p-method/state.yaml").exists()
    assert not (root / "kb/programs/p-method/workflow/reporting-events.yaml").exists()

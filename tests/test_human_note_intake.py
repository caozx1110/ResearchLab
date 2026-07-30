from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT

from research.common import load_yaml, write_yaml_if_changed
from research.prefs import ensure_workspace
from research.records import iter_records


def _load_intake_module():
    script = REPO_ROOT / "skills" / "source-intake" / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("source_intake_human_note_tests", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_kb_cli():
    script = REPO_ROOT / "skills" / "kb-cli" / "scripts" / "kb"
    loader = importlib.machinery.SourceFileLoader("kb_cli_human_note_tests", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _load_blog_module():
    script = REPO_ROOT / "skills" / "unit-analyst" / "scripts" / "blog.py"
    spec = importlib.util.spec_from_file_location("blog_analyst_human_note_tests", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    for area in ("inbox", "annotations"):
        (root / "kb" / "obsidian" / area).mkdir(parents=True, exist_ok=True)
    return root


def _run_human_note(
    intake,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    area: str = "inbox",
    filename: str = "My Note.md",
) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "intake.py",
            "--root",
            str(root),
            "human-note",
            "--area",
            area,
            "--filename",
            filename,
        ],
    )
    return intake.main()


def test_human_note_freezes_exact_bytes_with_provenance_and_exact_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    root = _workspace(tmp_path)
    note = root / "kb" / "obsidian" / "inbox" / "My Note.md"
    original = "# 我的观察\n\n这个控制器在接触切换时更稳定。\n".encode("utf-8")
    note.write_bytes(original)
    checkpoint_targets: list[Path] = []
    monkeypatch.setattr(
        intake,
        "checkpoint_and_report",
        lambda _root, **kwargs: checkpoint_targets.extend(kwargs["target_paths"]) or {},
    )

    assert _run_human_note(intake, root, monkeypatch) == 0

    records = list(iter_records(root, kind="blog"))
    assert len(records) == 1
    record = records[0]
    assert record["source"]["source_origin"] == "human-note"
    assert record["source"]["original_uri"] == "kb/obsidian/inbox/My Note.md"
    backup_paths = [root / value for value in record["source"]["backup_paths"]]
    assert any(path.read_bytes() == original for path in backup_paths)
    parse_cache = load_yaml(
        root / "kb" / "units" / "blogs" / record["id"] / "parse-cache.yaml",
        default={},
    )
    assert any("这个控制器在接触切换时更稳定" in str(row.get("text") or "") for row in parse_cache["chunks"])
    assert note.read_bytes() == original
    assert note not in checkpoint_targets
    assert all(not str(path).startswith(str(root / "kb" / "obsidian")) for path in checkpoint_targets)


@pytest.mark.parametrize(
    ("case", "filename"),
    [
        ("nested", "nested/Note.md"),
        ("non-utf8", "Bad Encoding.md"),
        ("oversize", "Too Large.md"),
        ("symlink", "Linked.md"),
        ("fifo", "Pipe.md"),
        ("review-name", "Pending Review abcdef.md"),
        ("review-schema", "Review Export.md"),
        ("review-marker", "Review Marker.md"),
    ],
)
def test_human_note_rejects_unsafe_or_review_inputs_without_canonical_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    filename: str,
) -> None:
    intake = _load_intake_module()
    root = _workspace(tmp_path)
    inbox = root / "kb" / "obsidian" / "inbox"
    target = inbox / filename
    if case == "nested":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Nested\n", encoding="utf-8")
    elif case == "non-utf8":
        target.write_bytes(b"# bad\n\xff\xfe")
    elif case == "oversize":
        target.write_bytes(b"x" * (intake.HUMAN_NOTE_MAX_BYTES + 1))
    elif case == "symlink":
        external = tmp_path / "outside.md"
        external.write_text("# outside\n", encoding="utf-8")
        target.symlink_to(external)
    elif case == "fifo":
        os.mkfifo(target)
    elif case == "review-name":
        target.write_text("# Review\n", encoding="utf-8")
    elif case == "review-schema":
        target.write_text("---\nschema: kb-obsidian-review-sheet/v1\n---\n# Review\n", encoding="utf-8")
    else:
        target.write_text(
            "# Review\n\n<!-- kb-review-batch:" + "a" * 64 + " -->\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    with pytest.raises(SystemExit):
        _run_human_note(intake, root, monkeypatch, filename=filename)

    assert list(iter_records(root, kind="blog")) == []
    assert not list((root / "kb" / ".runtime" / "intake-prepared").glob("*"))


def test_human_note_is_idempotent_within_origin_but_not_merged_into_generic_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    root = _workspace(tmp_path)
    note = root / "kb" / "obsidian" / "inbox" / "My Note.md"
    note.write_text("# Same bytes\n\nA human observation.\n", encoding="utf-8")
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "intake.py",
            "--root",
            str(root),
            "add",
            "--kind",
            "blog",
            "--source",
            str(note),
        ],
    )
    assert intake.main() == 0
    assert _run_human_note(intake, root, monkeypatch) == 0
    after_first_human = list(iter_records(root, kind="blog"))
    assert len(after_first_human) == 2
    assert sorted(str(row["source"].get("source_origin") or "") for row in after_first_human) == ["", "human-note"]

    assert _run_human_note(intake, root, monkeypatch) == 0
    assert len(list(iter_records(root, kind="blog"))) == 2


def test_human_note_runs_existing_blog_prepare_and_agent_fill_remains_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    blog = _load_blog_module()
    root = _workspace(tmp_path)
    note = root / "kb" / "obsidian" / "annotations" / "Controller Note.md"
    note.write_text(
        "# 接触控制观察\n\n控制器在脚掌切换接触时保持了更平滑的力矩变化。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(blog, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    assert _run_human_note(
        intake,
        root,
        monkeypatch,
        area="annotations",
        filename="Controller Note.md",
    ) == 0
    record = list(iter_records(root, kind="blog"))[0]
    unit_dir = root / "kb" / "units" / "blogs" / record["id"]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "blog.py",
            "--root",
            str(root),
            "complete-note",
            "--blog-id",
            record["id"],
            "--phase",
            "prepare",
        ],
    )
    assert blog.main() == 0
    scaffold = load_yaml(unit_dir / "blog-fill.yaml", default={})
    assert all(not str(element.get("content") or "") for element in scaffold["elements"])
    parse_cache = load_yaml(unit_dir / "parse-cache.yaml", default={})
    chunk = next(row for row in parse_cache["chunks"] if "更平滑的力矩变化" in str(row.get("text") or ""))
    quote = "控制器在脚掌切换接触时保持了更平滑的力矩变化"
    for index, element in enumerate(scaffold["elements"], start=1):
        element["claim_type"] = "inference"
        element["content"] = f"Agent 基于人工笔记形成的第 {index} 条结构化理解。"
        element["evidence_refs"] = [
            {
                "source_unit_id": record["id"],
                "artifact": "parse-cache.yaml",
                "locator": str(chunk.get("label") or "section:document"),
                "quote": quote,
                "summary": "人工笔记的逐字证据",
            }
        ]
    write_yaml_if_changed(unit_dir / "blog-fill.yaml", scaffold)
    sys.argv[-1] = "verify"
    assert blog.main() == 0

    verified = load_yaml(unit_dir / "record.yaml", default={})
    assert verified["source"]["source_origin"] == "human-note"
    assert verified["confirmation_status"] == "pending_user_confirmation"
    assert verified["needs_human_confirmation"] is True
    assert all(
        claim["confirmation_status"] == "pending_user_confirmation"
        for claim in verified["payload"]["claims"]
    )


def test_human_note_late_drift_rolls_back_canonical_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    root = _workspace(tmp_path)
    note = root / "kb" / "obsidian" / "inbox" / "My Note.md"
    note.write_text("# Before\n\nStable bytes.\n", encoding="utf-8")
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    original_materialize = intake._materialize_staged_source

    def mutate_after_materialize(*args, **kwargs):
        result = original_materialize(*args, **kwargs)
        note.write_text("# After\n\nChanged during commit.\n", encoding="utf-8")
        return result

    monkeypatch.setattr(intake, "_materialize_staged_source", mutate_after_materialize)
    with pytest.raises(RuntimeError, match="source bytes changed"):
        _run_human_note(intake, root, monkeypatch)

    assert list(iter_records(root, kind="blog")) == []
    assert note.read_text(encoding="utf-8").startswith("# After")


def test_kb_ingest_private_human_note_route_prepares_blog_without_public_path_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(kb, "effective_ingest_scope", lambda _root: {"ingest", "generate-note"})

    def fake_forward(root, relative_script, args, *, stream=True, extra_env=None):
        del root, stream, extra_env
        calls.append((relative_script, tuple(args)))
        if args[0] == "human-note":
            return kb.CommandResult(
                (relative_script, *args),
                0,
                "[ok] created kb/units/blogs/b-human-note-a1b2c3d4/record.yaml\n",
            )
        return kb.CommandResult((relative_script, *args), 0, "private prepare output\n")

    monkeypatch.setattr(kb, "forward_command", fake_forward)
    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "ingest",
            "--human-note-area",
            "inbox",
            "--human-note-filename",
            "My Note.md",
        ]
    ) == 0

    assert calls[0][1] == ("human-note", "--area", "inbox", "--filename", "My Note.md")
    assert calls[1][0].endswith("unit-analyst/scripts/blog.py")
    assert calls[1][1] == ("complete-note", "--blog-id", "b-human-note-a1b2c3d4", "--phase", "prepare")
    public = capsys.readouterr().out
    assert "My Note.md" not in public
    assert "--human-note" not in public
    assert "NEXT FOR AGENT" not in public
    assert "已入库并备好深读骨架" in public

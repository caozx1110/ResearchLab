from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.bibliography import BibliographyError, citation_key_for_unit_id
from research.common import write_yaml_if_changed
from research.core import default_record
from research.prefs import ensure_workspace


def _report_module():
    root = REPO_ROOT
    path = root / "skills" / "report-author" / "scripts" / "report.py"
    spec = importlib.util.spec_from_file_location("report_bibliography_integration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _paper(root: Path, index: int, *, title: str | None = None) -> str:
    unit_id = f"p-bib-paper-{index:02d}-abcdef"
    record = default_record("paper", title=title or f"Paper {index}", maturity="light")
    record["id"] = unit_id
    record["title"] = title or f"Paper {index}"
    basic = record["payload"]["basic_info"]
    basic.update(
        {
            "title": record["title"],
            "authors": [f"Author {index}"],
            "year": str(2020 + index),
            "source_url": f"https://doi.org/10.1234/paper-{index}",
            "doi": f"10.1234/paper-{index}",
            "citation_key": citation_key_for_unit_id(unit_id),
            "bibtex": {
                "entry_type": "misc",
                "venue_field": "",
                "volume": "",
                "number": "",
                "pages": "",
                "publisher": "",
                "primary_class": "",
            },
        }
    )
    write_yaml_if_changed(root / "kb" / "units" / "papers" / unit_id / "record.yaml", record)
    return unit_id


def _program(root: Path, ids: list[str], *, program_id: str = "program-bib") -> str:
    program_root = root / "kb" / "programs" / program_id
    write_yaml_if_changed(
        program_root / "state.yaml",
        {"program_id": program_id, "active_unit_ids": list(ids)},
    )
    write_yaml_if_changed(
        program_root / "workflow" / "reporting-events.yaml",
        {
            "id": f"{program_id}-reporting-events",
            "program_id": program_id,
            "items": [{"event_type": "paper-added", "paper_ids": [ids[0], ids[-1]]}],
        },
    )
    return program_id


def test_program_bibliography_exports_five_unique_stable_keys_byte_identically(
    tmp_path: Path,
) -> None:
    report = _report_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    ids = [_paper(root, index) for index in range(1, 6)]
    program_id = _program(root, ids)

    first = report.load_bibliography_inputs(root, program_id)
    assert len(first.entries) == 5
    assert first.rendered.count("@misc{") == 5
    assert {item["citation_key"] for item in first.entries} == {
        citation_key_for_unit_id(unit_id) for unit_id in ids
    }
    assert first.is_current()

    state_path = root / "kb" / "programs" / program_id / "state.yaml"
    write_yaml_if_changed(state_path, {"program_id": program_id, "active_unit_ids": list(reversed(ids))})
    assert not first.is_current()
    second = report.load_bibliography_inputs(root, program_id)
    assert second.rendered.encode("utf-8") == first.rendered.encode("utf-8")


def test_same_title_without_strong_identity_is_not_hard_deduplicated(tmp_path: Path) -> None:
    report = _report_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    ids = [_paper(root, index, title="Same title") for index in (1, 2)]
    for unit_id in ids:
        path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
        record = report.load_yaml(path)
        record["payload"]["basic_info"].update({"source_url": "", "doi": ""})
        write_yaml_if_changed(path, record)
    program_id = _program(root, ids)

    inputs = report.load_bibliography_inputs(root, program_id)
    assert len(inputs.entries) == 2
    assert inputs.rendered.count("@misc{") == 2


def test_bibliography_rejects_record_change_after_capture(tmp_path: Path) -> None:
    report = _report_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    unit_id = _paper(root, 1)
    program_id = _program(root, [unit_id])
    inputs = report.load_bibliography_inputs(root, program_id)

    path = root / "kb" / "units" / "papers" / unit_id / "record.yaml"
    record = report.load_yaml(path)
    record["payload"]["basic_info"]["year"] = "1999"
    write_yaml_if_changed(path, record)

    assert not inputs.is_current()


def test_bib_cli_writes_only_natural_language_status_and_no_internal_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _report_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    ids = [_paper(root, index) for index in range(1, 6)]
    program_id = _program(root, ids)
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        ["report.py", "--root", str(root), "bib", "--program-id", program_id],
    )

    assert report.main() == 0
    output = capsys.readouterr().out
    assert "已导出 5 条去重引用" in output
    assert "references.bib" not in output
    assert str(root) not in output
    artifact = root / "kb" / "output" / program_id / "references.bib"
    assert artifact.read_text(encoding="utf-8").count("@misc{") == 5


def test_bibliography_rejects_unsafe_program_identity(tmp_path: Path) -> None:
    report = _report_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    write_yaml_if_changed(
        root / "kb" / "programs" / "program-bib" / "state.yaml",
        {"program_id": "different-program", "active_unit_ids": []},
    )
    with pytest.raises(BibliographyError, match="identity"):
        report.load_bibliography_inputs(root, "program-bib")

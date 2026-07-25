from __future__ import annotations

from pathlib import Path

import pytest

from research.common import write_yaml_if_changed
from research.judgements import load_bound_judgement, load_bound_judgement_snapshot


def _side_case(root: Path, kind: str) -> tuple[Path, dict[str, object], dict[str, str]]:
    if kind == "program_decision":
        record: dict[str, object] = {
            "id": "decision-bound",
            "kind": kind,
            "owner": "research-orchestrator",
            "program_id": "p-bound",
        }
        path = root / "kb/programs/p-bound/workflow/decisions.yaml"
        subject = {"kind": kind, "id": "decision-bound", "owner": "research-orchestrator"}
    elif kind == "idea_discussion_conclusion":
        record = {
            "id": "discussion-bound",
            "kind": kind,
            "owner": "idea-workbench",
            "idea_id": "i-bound",
        }
        path = root / "kb/units/ideas/i-bound/discussion-judgements.yaml"
        subject = {"kind": kind, "id": "discussion-bound", "owner": "idea-workbench"}
    elif kind == "method_selection":
        record = {
            "id": "method-selection:p-bound:i-bound",
            "kind": kind,
            "owner": "method-designer",
            "program_id": "p-bound",
            "idea_id": "i-bound",
            "proposed_repo_id": "r-bound",
            "payload": {"method_selection": {"proposed_repo_id": "r-bound"}},
        }
        path = root / "kb/programs/p-bound/design/i-bound-repo-choice.yaml"
        subject = {"kind": kind, "id": record["id"], "owner": "method-designer"}
    else:
        record = {
            "id": "survey:survey:bound",
            "kind": "survey_judgement",
            "owner": "literature-synthesizer",
            "slug": "bound",
            "mode": "survey",
        }
        path = root / "kb/synthesis/bound/survey.yaml"
        subject = {
            "kind": "survey_judgement",
            "id": "survey:survey:bound",
            "owner": "literature-synthesizer",
        }
    path.parent.mkdir(parents=True)
    write_yaml_if_changed(
        path,
        {"items": [record]} if kind in {"program_decision", "idea_discussion_conclusion"} else record,
    )
    subject["path"] = path.relative_to(root).as_posix()
    return path, record, subject


@pytest.mark.parametrize(
    "kind",
    [
        "program_decision",
        "idea_discussion_conclusion",
        "method_selection",
        "survey_judgement",
    ],
)
def test_side_judgement_snapshot_stable_matrix(tmp_path: Path, kind: str) -> None:
    path, record, subject = _side_case(tmp_path, kind)

    bound = load_bound_judgement_snapshot(tmp_path, subject)

    assert bound.record == record
    assert bound.path == path
    assert bound.project_yaml_snapshot is not None
    assert bound.project_yaml_snapshot.raw_bytes == path.read_bytes()
    assert bound.is_current()
    assert load_bound_judgement(tmp_path, subject) == (record, path)


def test_side_list_snapshot_rejects_same_bytes_inode_replacement(tmp_path: Path) -> None:
    path, _record, subject = _side_case(tmp_path, "program_decision")
    bound = load_bound_judgement_snapshot(tmp_path, subject)
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)

    assert not bound.is_current()
    assert load_bound_judgement_snapshot(tmp_path, subject).is_current()


def test_side_single_snapshot_rejects_same_bytes_ancestor_replacement(tmp_path: Path) -> None:
    path, _record, subject = _side_case(tmp_path, "survey_judgement")
    bound = load_bound_judgement_snapshot(tmp_path, subject)
    raw_bytes = path.read_bytes()
    displaced = tmp_path / "displaced-survey"
    path.parent.rename(displaced)
    path.parent.mkdir()
    path.write_bytes(raw_bytes)

    assert not bound.is_current()
    assert load_bound_judgement_snapshot(tmp_path, subject).is_current()


def test_side_snapshot_rejects_duplicate_added_after_capture(tmp_path: Path) -> None:
    path, record, subject = _side_case(tmp_path, "program_decision")
    bound = load_bound_judgement_snapshot(tmp_path, subject)
    write_yaml_if_changed(path, {"items": [record, dict(record)]})

    assert not bound.is_current()
    with pytest.raises(ValueError, match="not globally unique"):
        load_bound_judgement_snapshot(tmp_path, subject)

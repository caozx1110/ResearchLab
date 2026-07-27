from __future__ import annotations

from pathlib import Path

import pytest

import research.judgements as judgement_module
from research.common import write_yaml_if_changed
from research.evidence import build_verification_receipt
from research.judgements import (
    load_bound_judgement,
    load_bound_judgement_batch_snapshot,
    load_bound_judgement_snapshot,
    pending_judgement_card,
)


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


@pytest.mark.parametrize("container_count", [4, 8, 16])
def test_side_judgement_batch_capture_is_linear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container_count: int,
) -> None:
    subjects: list[dict[str, str]] = []
    for index in range(container_count):
        program_id = f"p-batch-{index}"
        decision_id = f"decision-batch-{index}"
        path = tmp_path / f"kb/programs/{program_id}/workflow/decisions.yaml"
        path.parent.mkdir(parents=True)
        write_yaml_if_changed(
            path,
            {
                "items": [
                    {
                        "id": decision_id,
                        "kind": "program_decision",
                        "owner": "research-orchestrator",
                        "program_id": program_id,
                    }
                ]
            },
        )
        subjects.append({"kind": "program_decision", "id": decision_id})

    original_snapshot = judgement_module.snapshot_project_file
    captures = 0

    def count_snapshot(*args, **kwargs):
        nonlocal captures
        captures += 1
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(judgement_module, "snapshot_project_file", count_snapshot)

    batch = load_bound_judgement_batch_snapshot(tmp_path, subjects)

    assert captures == container_count
    class LookupSpy(dict):
        def __init__(self, values):
            super().__init__(values)
            self.get_calls = 0

        def get(self, key, default=None):
            self.get_calls += 1
            return super().get(key, default)

        def __iter__(self):
            raise AssertionError("resolve must not scan the subject index")

    lookup_spy = LookupSpy(batch.subject_index)
    object.__setattr__(batch, "subject_index", lookup_spy)
    assert [batch.resolve(subject).record["id"] for subject in subjects] == [
        subject["id"] for subject in subjects
    ]
    assert lookup_spy.get_calls == container_count
    assert batch.is_current()
    assert captures == container_count


@pytest.mark.skipif(not Path("/private/var").exists(), reason="macOS /var alias contract")
@pytest.mark.parametrize("kind", ["program_decision", "survey_judgement"])
def test_side_snapshot_alias_root_matches_canonical_root(tmp_path: Path, kind: str) -> None:
    canonical_root = tmp_path.resolve()
    if not str(canonical_root).startswith("/private/var/"):
        pytest.skip("temporary directory is not under the macOS /var alias")
    alias_root = Path("/var") / canonical_root.relative_to("/private/var")
    path, record, subject = _side_case(canonical_root, kind)

    canonical = load_bound_judgement_snapshot(canonical_root, subject)
    alias = load_bound_judgement_snapshot(alias_root, subject)

    assert alias.path == path
    assert alias.record == record == canonical.record
    assert alias.is_current()
    assert canonical.is_current()


def test_snapshot_bearing_entry_rejects_symlink_workspace_root(tmp_path: Path) -> None:
    canonical_root = tmp_path / "canonical-workspace"
    canonical_root.mkdir()
    _path, _record, subject = _side_case(canonical_root, "program_decision")
    alias_root = tmp_path / "workspace-link"
    alias_root.symlink_to(canonical_root, target_is_directory=True)

    with pytest.raises(ValueError, match="project root itself must be a real directory"):
        load_bound_judgement_snapshot(alias_root, subject)


@pytest.mark.parametrize("fault", ["malformed", "duplicate-key", "symlink"])
def test_bad_side_container_is_isolated_from_valid_sibling(
    tmp_path: Path,
    fault: str,
) -> None:
    _path, _record, valid_subject = _side_case(tmp_path, "program_decision")
    bad_path = tmp_path / "kb/synthesis/bad/survey.yaml"
    bad_path.parent.mkdir(parents=True)
    if fault == "malformed":
        bad_path.write_text("id: survey:survey:bad\nsections: [\n", encoding="utf-8")
    elif fault == "duplicate-key":
        bad_path.write_text(
            "id: survey:survey:bad\nid: survey:survey:bad\nkind: survey_judgement\n",
            encoding="utf-8",
        )
    else:
        outside = tmp_path / "outside-survey.yaml"
        write_yaml_if_changed(
            outside,
            {
                "id": "survey:survey:bad",
                "kind": "survey_judgement",
                "owner": "literature-synthesizer",
                "slug": "bad",
                "mode": "survey",
            },
        )
        bad_path.symlink_to(outside)

    valid = load_bound_judgement_snapshot(tmp_path, valid_subject)
    assert valid.is_current()
    with pytest.raises(ValueError, match="not globally unique"):
        load_bound_judgement_snapshot(
            tmp_path,
            {
                "kind": "survey_judgement",
                "id": "survey:survey:bad",
                "owner": "literature-synthesizer",
                "path": "kb/synthesis/bad/survey.yaml",
            },
        )
    assert valid.is_current()


def test_old_side_snapshot_cannot_emit_review_card_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_root = tmp_path / "kb/programs/p-bound-card"
    workflow = program_root / "workflow"
    workflow.mkdir(parents=True)
    evidence = program_root / "evidence.md"
    evidence.write_text("Route A has the strongest grounded benchmark.", encoding="utf-8")
    record = {
        "id": "decision-bound-card",
        "kind": "program_decision",
        "owner": "research-orchestrator",
        "program_id": "p-bound-card",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "unverified"],
        "payload": {
            "decision": {"text": "Use route A."},
            "claims": [
                {
                    "id": "claim-bound-card",
                    "text": "Route A is the best current route.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": "program:p-bound-card",
                            "artifact": "evidence.md",
                            "locator": "benchmark",
                            "quote": "Route A has the strongest grounded benchmark.",
                        }
                    ],
                }
            ],
        },
    }
    build_verification_receipt(
        record,
        program_root,
        source_roots={"program:p-bound-card": program_root},
    )
    path = workflow / "decisions.yaml"
    write_yaml_if_changed(path, {"items": [record]})
    subject = {
        "kind": "program_decision",
        "id": "decision-bound-card",
        "owner": "research-orchestrator",
        "path": path.relative_to(tmp_path).as_posix(),
    }
    bound = load_bound_judgement_snapshot(tmp_path, subject)
    assert pending_judgement_card(
        tmp_path,
        bound.record,
        owner=bound.owner,
        artifact_path=bound.path,
        bound_snapshot=bound,
    ) is not None

    def reject_second_loader(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("discovery must wrap its initially captured snapshot")

    monkeypatch.setattr(
        judgement_module,
        "load_bound_judgement_snapshot",
        reject_second_loader,
    )
    cards = judgement_module.discover_pending_judgements(tmp_path)
    assert [card["subject"]["id"] for card in cards] == ["decision-bound-card"]

    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)

    assert pending_judgement_card(
        tmp_path,
        bound.record,
        owner=bound.owner,
        artifact_path=bound.path,
        bound_snapshot=bound,
    ) is None

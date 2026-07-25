from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import ensure_workspace, record_path, write_record
from research.preference_selection import eligible_preferences, record_effective_selection
from research.records import kind_payload_skeleton


PAGE = "We study vision language action policies for robot manipulation."


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_paper_module():
    script = _project_root() / ".agents" / "skills" / "paper-analyst" / "scripts" / "paper.py"
    spec = importlib.util.spec_from_file_location("paper_containment_script_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _paper_record(paper_id: str) -> dict:
    return {
        "id": paper_id,
        "kind": "paper",
        "title": "Containment paper",
        "status": "screened",
        "maturity": "lightweight",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact", "evaluation", "inference", "unverified"],
        "topics": ["containment"],
        "tags": [],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": kind_payload_skeleton("paper", "Containment paper"),
    }


def _setup_paper(root: Path, paper_id: str) -> Path:
    ensure_workspace(root)
    write_record(root, _paper_record(paper_id))
    unit_root = record_path(root, "paper", paper_id).parent
    write_yaml_if_changed(
        unit_root / "parse-cache.yaml",
        {
            "paper_id": paper_id,
            "source_type": "pdf",
            "locator_kind": "page",
            "chunks": [{"label": "source.pdf:page-1", "text": PAGE, "page": 1}],
        },
    )
    return unit_root


def _screen_fill(paper, paper_id: str) -> dict:
    dimensions = {
        name: {
            "status": "not_applicable",
            "rating": "",
            "reason": "The excerpt does not support this dimension.",
            "claim_ids": [],
        }
        for name in paper.SCREENING_DIMENSION_RATINGS
    }
    return {
        "paper_id": paper_id,
        "paper_type": "method_system",
        "worth_deep_reading": "yes",
        "judgement_reason": ["The paper directly studies the target setting."],
        "relevance_to_current_research": "Directly relevant.",
        "claims": [
            {
                "id": "claim-contained-screen",
                "text": "The paper studies VLA policies for manipulation.",
                "claim_type": "evaluation",
                "confirmation_status": "pending_user_confirmation",
                "evidence_refs": [
                    {
                        "source_unit_id": paper_id,
                        "artifact": "parse-cache.yaml",
                        "locator": "page=1",
                        "quote": "vision language action policies for robot manipulation",
                        "summary": "scope evidence",
                    }
                ],
            }
        ],
        **dimensions,
    }


def _note_fill(paper, paper_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "paper_type": "method_system",
        "elements": [
            {
                "element": name,
                "claim_type": paper.ELEMENT_CLAIM_TYPE[name],
                "content": f"Agent-authored {name} judgement.",
                "evidence_refs": [
                    {
                        "source_unit_id": paper_id,
                        "artifact": "parse-cache.yaml",
                        "locator": "page=1",
                        "quote": "vision language action policies for robot manipulation",
                        "summary": f"{name} evidence",
                    }
                ],
            }
            for name in paper.NOTE_ELEMENTS
        ],
    }


def _record_selection(
    root: Path,
    paper,
    *,
    selection_id: str,
    args,
    paper_id: str,
    unit_root: Path,
) -> str:
    record = load_yaml(record_path(root, "paper", paper_id))
    eligible = eligible_preferences(root, skill="paper-analyst", operation=args.command)
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "paper-analyst",
            "operation": args.command,
            "catalog_digest": eligible["catalog_digest"],
            "task_context": paper.paper_preference_context(
                root, args, record, unit_root=unit_root
            ),
            "selected": [
                {
                    "preference_id": item["preference_id"],
                    "reason": "bounded paper verification",
                    "application": "apply only to this exact managed fill",
                }
                for item in eligible["items"]
            ],
            "excluded": [],
        },
    )
    return selection_id


def _run_cli(paper, monkeypatch: pytest.MonkeyPatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["paper.py", "--root", str(root), *argv])
    return paper.main()


def _workspace_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _workspace_snapshot_except(root: Path, excluded: Path) -> dict[str, bytes]:
    excluded_relative = excluded.relative_to(root).as_posix()
    return {
        key: value
        for key, value in _workspace_snapshot(root).items()
        if key != excluded_relative
    }


def test_screen_verify_rejects_workspace_external_absolute_fill_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / "workspace"
    paper_id = "p-external-fill"
    _setup_paper(root, paper_id)
    outside = tmp_path / "outside-screen.yaml"
    write_yaml_if_changed(outside, _screen_fill(paper, paper_id))
    before = _workspace_snapshot(root)

    with pytest.raises(ValueError, match="current paper unit"):
        _run_cli(
            paper,
            monkeypatch,
            root,
            "screen",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            str(outside),
            "--defer-post-actions",
        )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
def test_owner_direct_verify_rejects_external_fill_before_transaction(
    tmp_path: Path,
    round_index: int,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-direct-external-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    outside = tmp_path / f"outside-direct-{round_index}.yaml"
    write_yaml_if_changed(outside, _screen_fill(paper, paper_id))
    before = _workspace_snapshot(root)
    record = load_yaml(record_path(root, "paper", paper_id))
    cache_path = unit_root / "parse-cache.yaml"
    chunks = load_yaml(cache_path)["chunks"]
    args = SimpleNamespace(
        phase="verify",
        mode="auto",
        input=str(outside),
        paper_id=paper_id,
    )

    with pytest.raises(ValueError, match="current paper unit"):
        paper._run_screen(
            args,
            root,
            record,
            unit_root,
            cache_path,
            chunks,
            {},
            True,
        )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
@pytest.mark.parametrize("mutation", ("bytes", "same-bytes-new-inode"))
def test_owner_direct_verify_rejects_post_prevalidation_replacement_without_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
    mutation: str,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-direct-race-{mutation}-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    fill_path = unit_root / "agent-screen.yaml"
    write_yaml_if_changed(fill_path, _screen_fill(paper, paper_id))
    record = load_yaml(record_path(root, "paper", paper_id))
    cache_path = unit_root / "parse-cache.yaml"
    chunks = load_yaml(cache_path)["chunks"]
    args = SimpleNamespace(
        phase="verify",
        mode="auto",
        input=fill_path.name,
        paper_id=paper_id,
    )
    original_prevalidate = paper._prevalidate_bound_verify_fill

    def replace_after_prevalidation(*call_args, **call_kwargs):
        result = original_prevalidate(*call_args, **call_kwargs)
        original_bytes = fill_path.read_bytes()
        if mutation == "bytes":
            fill_path.write_bytes(original_bytes + b"\nraced-direct: true\n")
        else:
            fill_path.unlink()
            fill_path.write_bytes(original_bytes)
        return result

    monkeypatch.setattr(
        paper, "_prevalidate_bound_verify_fill", replace_after_prevalidation
    )
    before = _workspace_snapshot_except(root, fill_path)

    match = "metadata changed|bytes changed" if mutation == "bytes" else "inode changed"
    with pytest.raises(ValueError, match=match):
        paper._run_screen(
            args,
            root,
            record,
            unit_root,
            cache_path,
            chunks,
            {},
            True,
        )

    assert _workspace_snapshot_except(root, fill_path) == before
    assert not (unit_root / "screening.yaml").exists()


@pytest.mark.parametrize("round_index", (1, 2))
@pytest.mark.parametrize("escape", ("workspace-sibling", "parent-relative", "other-unit"))
def test_verify_fill_containment_rejects_escape_paths_in_two_rounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
    escape: str,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-containment-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    if escape == "workspace-sibling":
        candidate = root / "candidate.yaml"
        write_yaml_if_changed(candidate, _screen_fill(paper, paper_id))
        input_arg = str(candidate)
    elif escape == "parent-relative":
        candidate = unit_root.parent / "candidate.yaml"
        write_yaml_if_changed(candidate, _screen_fill(paper, paper_id))
        input_arg = "../candidate.yaml"
    else:
        other_unit = _setup_paper(root, f"p-other-{round_index}")
        candidate = other_unit / "candidate.yaml"
        write_yaml_if_changed(candidate, _screen_fill(paper, paper_id))
        input_arg = str(candidate)
    before = _workspace_snapshot(root)

    with pytest.raises(ValueError, match="current paper unit"):
        _run_cli(
            paper,
            monkeypatch,
            root,
            "screen",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            input_arg,
            "--defer-post-actions",
        )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
@pytest.mark.parametrize("attack", ("leaf-symlink", "ancestor-symlink", "hardlink"))
def test_verify_fill_rejects_link_attacks_in_two_rounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
    attack: str,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-link-{attack}-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    outside = tmp_path / f"outside-{attack}-{round_index}.yaml"
    write_yaml_if_changed(outside, _screen_fill(paper, paper_id))
    fill_path = unit_root / "agent-screen.yaml"
    if attack == "leaf-symlink":
        fill_path.symlink_to(outside)
    elif attack == "hardlink":
        os.link(outside, fill_path)
    else:
        parked = tmp_path / f"parked-unit-{round_index}"
        unit_root.rename(parked)
        unit_root.symlink_to(parked, target_is_directory=True)
        fill_path = unit_root / "agent-screen.yaml"
        write_yaml_if_changed(parked / "agent-screen.yaml", _screen_fill(paper, paper_id))
    before = _workspace_snapshot(root)

    if attack == "ancestor-symlink":
        # The strict canonical-record reader may quarantine the whole unit before
        # the later fill-path guard runs.  Both boundaries are fail-closed; do not
        # require the unsafe ancestor to remain discoverable just to name it.
        with pytest.raises((ValueError, SystemExit)) as exc_info:
            _run_cli(
                paper,
                monkeypatch,
                root,
                "screen",
                "--paper-id",
                paper_id,
                "--phase",
                "verify",
                "--input",
                fill_path.name,
                "--defer-post-actions",
            )
        assert "symlink" in str(exc_info.value) or "Record not found" in str(exc_info.value)
    else:
        match = "symlink" if attack == "leaf-symlink" else "unique managed file identity"
        with pytest.raises(ValueError, match=match):
            _run_cli(
                paper,
                monkeypatch,
                root,
                "screen",
                "--paper-id",
                paper_id,
                "--phase",
                "verify",
                "--input",
                fill_path.name,
                "--defer-post-actions",
            )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
@pytest.mark.parametrize("mutation", ("bytes", "same-bytes-new-inode"))
def test_verify_receipt_rejects_fill_drift_in_two_rounds_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
    mutation: str,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-receipt-drift-{mutation}-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    fill_path = unit_root / "agent-screen.yaml"
    write_yaml_if_changed(fill_path, _screen_fill(paper, paper_id))
    args = paper.build_parser().parse_args(
        [
            "screen",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            fill_path.name,
            "--defer-post-actions",
        ]
    )
    selection_id = _record_selection(
        root,
        paper,
        selection_id=f"prefsel-paper-drift-{mutation}-{round_index}",
        args=args,
        paper_id=paper_id,
        unit_root=unit_root,
    )
    original_bytes = fill_path.read_bytes()
    if mutation == "bytes":
        fill_path.write_bytes(original_bytes + b"\nchanged: true\n")
    else:
        fill_path.unlink()
        fill_path.write_bytes(original_bytes)
    before = _workspace_snapshot(root)

    with pytest.raises(ValueError, match="another task"):
        _run_cli(
            paper,
            monkeypatch,
            root,
            "screen",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            fill_path.name,
            "--preference-selection-id",
            selection_id,
            "--defer-post-actions",
        )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
@pytest.mark.parametrize("mutation", ("bytes", "same-bytes-new-inode"))
def test_verify_revalidates_bound_fill_immediately_before_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
    mutation: str,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-bound-drift-{mutation}-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    fill_path = unit_root / "agent-screen.yaml"
    write_yaml_if_changed(fill_path, _screen_fill(paper, paper_id))
    original_resolver = paper.resolve_paper_preferences

    def mutate_after_preference_resolution(*args, **kwargs):
        result = original_resolver(*args, **kwargs)
        original_bytes = fill_path.read_bytes()
        if mutation == "bytes":
            fill_path.write_bytes(original_bytes + b"\nraced: true\n")
        else:
            fill_path.unlink()
            fill_path.write_bytes(original_bytes)
        return result

    monkeypatch.setattr(paper, "resolve_paper_preferences", mutate_after_preference_resolution)
    before_record = record_path(root, "paper", paper_id).read_bytes()
    before_cache = (unit_root / "parse-cache.yaml").read_bytes()

    match = "metadata changed|bytes changed" if mutation == "bytes" else "inode changed"
    with pytest.raises(ValueError, match=match):
        _run_cli(
            paper,
            monkeypatch,
            root,
            "screen",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            fill_path.name,
            "--defer-post-actions",
        )

    assert record_path(root, "paper", paper_id).read_bytes() == before_record
    assert (unit_root / "parse-cache.yaml").read_bytes() == before_cache
    assert not (unit_root / "screening.yaml").exists()


@pytest.mark.parametrize("round_index", (1, 2))
def test_verify_wrong_phase_fill_is_rejected_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-wrong-phase-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    fill_path = unit_root / "screen-shaped.yaml"
    write_yaml_if_changed(fill_path, _screen_fill(paper, paper_id))
    before = _workspace_snapshot(root)

    with pytest.raises(SystemExit):
        _run_cli(
            paper,
            monkeypatch,
            root,
            "complete-note",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            fill_path.name,
            "--defer-post-actions",
        )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
def test_verify_rejects_fill_declared_for_another_unit_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-current-unit-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    fill = _screen_fill(paper, paper_id)
    fill["paper_id"] = f"p-wrong-unit-{round_index}"
    fill_path = unit_root / "wrong-unit.yaml"
    write_yaml_if_changed(fill_path, fill)
    before = _workspace_snapshot(root)

    with pytest.raises(SystemExit):
        _run_cli(
            paper,
            monkeypatch,
            root,
            "screen",
            "--paper-id",
            paper_id,
            "--phase",
            "verify",
            "--input",
            fill_path.name,
            "--defer-post-actions",
        )

    assert _workspace_snapshot(root) == before


@pytest.mark.parametrize("round_index", (1, 2))
def test_valid_managed_screen_and_note_verify_flows_succeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    round_index: int,
) -> None:
    paper = _load_paper_module()
    root = tmp_path / f"workspace-{round_index}"
    paper_id = f"p-valid-managed-{round_index}"
    unit_root = _setup_paper(root, paper_id)
    screen_path = unit_root / "agent-screen.yaml"
    write_yaml_if_changed(screen_path, _screen_fill(paper, paper_id))

    assert _run_cli(
        paper,
        monkeypatch,
        root,
        "screen",
        "--paper-id",
        paper_id,
        "--phase",
        "verify",
        "--input",
        screen_path.name,
        "--defer-post-actions",
    ) == 0
    assert load_yaml(unit_root / "screening.yaml")["status"] == "verified"

    note_path = unit_root / "agent-note.yaml"
    write_yaml_if_changed(note_path, _note_fill(paper, paper_id))
    assert _run_cli(
        paper,
        monkeypatch,
        root,
        "complete-note",
        "--paper-id",
        paper_id,
        "--phase",
        "verify",
        "--input",
        note_path.name,
        "--defer-post-actions",
    ) == 0
    assert (unit_root / "note.md").exists()
    assert load_yaml(record_path(root, "paper", paper_id))["payload"]["verification"]["claims_digest"]

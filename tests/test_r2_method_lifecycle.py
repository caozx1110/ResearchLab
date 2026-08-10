from __future__ import annotations

from repo_paths import initialize_test_workspace

import importlib.util
import json
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path
from research.evidence import EvidenceSourceSnapshot, verify_claim_evidence
from research.journal import committed_ops
from research.judgements import (
    discover_pending_judgements,
    judgement_confirmation_is_current,
)
from research.paths import config_root
from research.records import trusted_claim_source_roots as shared_source_roots


IDEA_ID = "i-r2-method-123456"
REPO_ID = "r-r2-method-123456"
PROGRAM_ID = "p-r2-method"


def _project_root() -> Path:
    return REPO_ROOT


def _load_method_module():
    script = _project_root() / "skills" / "method-designer" / "scripts" / "method.py"
    spec = importlib.util.spec_from_file_location("r2_method_designer_script_for_tests", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path
    (root / ".agents").mkdir()
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    initialize_test_workspace(root)
    idea = default_record("idea", title="R2 selected idea", maturity="lightweight", source={"original_uri": "discussion"})
    idea["id"] = IDEA_ID
    idea["status"] = "selected"
    idea["payload"]["hypothesis"]["core_hypothesis"] = "A small adapter improves recovery."
    idea["payload"]["analysis"]["minimum_validation_path"] = "Compare the adapter with the baseline."
    write_yaml_if_changed(record_path(root, "idea", IDEA_ID), idea)
    repo = default_record(
        "repo",
        title="R2 adapter repository",
        maturity="lightweight",
        source={"original_uri": "https://example.com/r2-repo"},
    )
    repo["id"] = REPO_ID
    repo["summary"] = "Adapter recovery baseline implementation."
    repo["payload"]["structure"]["entrypoints"] = ["train.py"]
    write_yaml_if_changed(record_path(root, "repo", REPO_ID), repo)
    return root


def _run(method, monkeypatch, root: Path, *args: str) -> int:
    monkeypatch.setattr(method, "PROJECT_ROOT", root)
    monkeypatch.setattr(sys, "argv", ["method.py", "--root", str(root), *args])
    return method.main()


def _paths(root: Path) -> dict[str, Path]:
    design = root / "programs" / PROGRAM_ID / "design"
    return {
        "design": design,
        "choice": design / f"{IDEA_ID}-repo-choice.yaml",
        "interfaces": design / f"{IDEA_ID}-interfaces.yaml",
        "matrix": design / f"{IDEA_ID}-experiment-matrix.yaml",
        "method": design / f"{IDEA_ID}-method.md",
        "state": root / "programs" / PROGRAM_ID / "state.yaml",
        "events": root / "programs" / PROGRAM_ID / "workflow" / "reporting-events.yaml",
    }


def _claim(claim_id: str, text: str, source_id: str, quote: str) -> dict:
    return {
        "id": claim_id,
        "text": text,
        "claim_type": "evaluation",
        "confidence": 0.8,
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": source_id,
                "artifact": "record.yaml",
                "locator": "record",
                "quote": quote,
            }
        ],
    }


def _fill_method_claims(root: Path) -> None:
    path = _paths(root)["choice"]
    choice = load_yaml(path, default={})
    choice["payload"]["claims"] = [
        _claim(
            "method-repo-selection",
            f"Repository {REPO_ID} is the grounded proposal for this method.",
            REPO_ID,
            "Adapter recovery baseline implementation.",
        ),
        _claim(
            "method-interfaces",
            "The first implementation interface should be anchored at the training entrypoint.",
            REPO_ID,
            "train.py",
        ),
        _claim(
            "method-baselines",
            "The repository baseline is the required first comparison.",
            REPO_ID,
            "Adapter recovery baseline implementation.",
        ),
        _claim(
            "method-risks",
            "Recovery improvement remains a hypothesis and needs a failure-slice test.",
            IDEA_ID,
            "A small adapter improves recovery.",
        ),
    ]
    choice["payload"]["method_selection"]["selection_reason"] = "Grounded by the canonical idea and repo records."
    write_yaml_if_changed(path, choice)


def _prepare(method, monkeypatch, root: Path) -> int:
    return _run(method, monkeypatch, root, "design", "--idea-id", IDEA_ID, "--program-id", PROGRAM_ID)


def _verify(method, monkeypatch, root: Path) -> int:
    return _run(
        method,
        monkeypatch,
        root,
        "design",
        "--phase",
        "verify",
        "--idea-id",
        IDEA_ID,
        "--program-id",
        PROGRAM_ID,
    )


def _review_snapshot(root: Path) -> dict:
    choice_id = str(load_yaml(_paths(root)["choice"], default={}).get("id") or "")
    matches = [
        card
        for card in discover_pending_judgements(root)
        if card["subject"]["kind"] == "method_selection"
        and card["subject"]["id"] == choice_id
    ]
    assert len(matches) == 1
    return matches[0]["snapshot_binding"]


def _confirm(method, monkeypatch, root: Path, *, expected: dict | None = None) -> int:
    expected = expected or _review_snapshot(root)
    return _run(
        method,
        monkeypatch,
        root,
        "confirm-selection",
        "--idea-id",
        IDEA_ID,
        "--program-id",
        PROGRAM_ID,
        "--confirmed-by",
        "Alice Researcher",
        "--evidence",
        "I reviewed the four grounded method claims.",
        "--user-authorization",
        "I confirm this repository selection and method evidence.",
        "--authorization-source",
        "user_message",
        "--expected-snapshot",
        json.dumps(expected),
    )


def _reject(method, monkeypatch, root: Path, *, expected: dict | None = None) -> int:
    expected = expected or _review_snapshot(root)
    return _run(
        method,
        monkeypatch,
        root,
        "reject-selection",
        "--idea-id",
        IDEA_ID,
        "--program-id",
        PROGRAM_ID,
        "--reason",
        "Use a different implementation base.",
        "--expected-snapshot",
        json.dumps(expected),
    )


def test_prepare_verify_confirm_promotes_state_and_event_only_at_confirmation(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)

    assert _prepare(method, monkeypatch, root) == 0
    choice = load_yaml(paths["choice"], default={})
    state = load_yaml(paths["state"], default={})
    assert choice["proposed_repo_id"] == REPO_ID
    assert "selected_repo_id" not in choice
    assert "selected_repo_id" not in state
    assert state["stage"] == "idea-review"
    assert not paths["events"].exists()

    repo_locates_after_prepare = 0
    original_locate = method.locate_record

    def count_repo_locates(*args, **kwargs):
        nonlocal repo_locates_after_prepare
        identifier = str(args[1] if len(args) > 1 else kwargs.get("identifier") or "")
        if identifier == REPO_ID:
            repo_locates_after_prepare += 1
        return original_locate(*args, **kwargs)

    monkeypatch.setattr(method, "locate_record", count_repo_locates)
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    assert repo_locates_after_prepare == 0
    choice = load_yaml(paths["choice"], default={})
    state = load_yaml(paths["state"], default={})
    assert choice["status"] == "ready_for_review"
    assert choice["needs_human_confirmation"] is True
    assert choice["payload"]["verification"]["verified_at"]
    assert "selected_repo_id" not in choice
    assert "selected_repo_id" not in state
    assert state["stage"] == "idea-review"
    assert not paths["events"].exists()

    expected = _review_snapshot(root)
    assert _confirm(method, monkeypatch, root, expected=expected) == 0
    assert repo_locates_after_prepare == 0
    choice = load_yaml(paths["choice"], default={})
    state = load_yaml(paths["state"], default={})
    interfaces = load_yaml(paths["interfaces"], default={})
    matrix = load_yaml(paths["matrix"], default={})
    events = load_yaml(paths["events"], default={})["items"]
    assert choice["selected_repo_id"] == REPO_ID
    assert choice["confirmation_status"] == "confirmed"
    assert judgement_confirmation_is_current(root, choice, paths["choice"])
    assert state["selected_repo_id"] == REPO_ID
    assert state["stage"] == "implementation-planning"
    assert interfaces["selected_repo_id"] == REPO_ID
    assert matrix["selected_repo_id"] == REPO_ID
    assert all(row["repo_dependency"] == REPO_ID for row in matrix["experiments"])
    assert "Selected repository" in paths["method"].read_text(encoding="utf-8")
    event = events[-1]
    assert event["event_type"] == "method-selected"
    assert event["confirmation_status"] == "confirmed"
    assert event["confirmation_binding"]["subject"] == {
        "kind": "method_selection",
        "id": f"method-selection:{PROGRAM_ID}:{IDEA_ID}",
        "owner": "method-designer",
        "path": paths["choice"].relative_to(root).as_posix(),
    }
    assert event["confirmation_binding"]["content_digest"] == choice["confirmation"]["content_digest"]
    op_types = {str(item.get("op_type") or "") for item in committed_ops(root)}
    assert {"method:prepare", "method:verify", "method:confirm"} <= op_types

    with pytest.raises(SystemExit, match="not ready for review|already finalized"):
        _confirm(method, monkeypatch, root, expected=expected)
    with pytest.raises(SystemExit, match="not ready for rejection"):
        _reject(method, monkeypatch, root, expected=expected)
    assert len(load_yaml(paths["events"], default={})["items"]) == 1

    choice["payload"]["claims"][0]["text"] += " Changed after confirmation."
    write_yaml_if_changed(paths["choice"], choice)
    assert not judgement_confirmation_is_current(
        root,
        load_yaml(paths["choice"], default={}),
        paths["choice"],
    )


def test_method_cross_unit_evidence_uses_anchored_snapshot(tmp_path: Path) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    claim = _claim(
        "method-repo-selection",
        f"Repository {REPO_ID} is the grounded proposal.",
        REPO_ID,
        "Adapter recovery baseline implementation.",
    )

    roots = method.method_source_roots(root, PROGRAM_ID, [claim])

    assert isinstance(roots[REPO_ID], EvidenceSourceSnapshot)
    assert verify_claim_evidence(
        claim,
        _paths(root)["design"],
        source_roots=roots,
    ) == []


def test_method_rejects_source_replaced_after_snapshot_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    repo_record = record_path(root, "repo", REPO_ID)
    replacement = tmp_path / "outside-method-source"
    replacement.mkdir()
    outside_repo = default_record("repo", title="OUTSIDE METHOD SENTINEL", maturity="lightweight")
    outside_repo["id"] = REPO_ID
    outside_repo["summary"] = "OUTSIDE METHOD SENTINEL"
    write_yaml_if_changed(replacement / "record.yaml", outside_repo)
    original_dir = tmp_path / "original-method-source"
    original_locate = method.locate_record

    swapped = False

    def replace_source_once() -> None:
        nonlocal swapped
        if swapped:
            return
        repo_record.parent.rename(original_dir)
        replacement.rename(repo_record.parent)
        swapped = True

    def locate_then_replace(*args, **kwargs):
        result = original_locate(*args, **kwargs)
        if str(args[1] if len(args) > 1 else kwargs.get("identifier") or "") == REPO_ID:
            replace_source_once()
        return result

    def snapshot_then_replace(*args, **kwargs):
        roots = shared_source_roots(*args, **kwargs)
        replace_source_once()
        return roots

    monkeypatch.setattr(method, "locate_record", locate_then_replace)
    monkeypatch.setattr(
        method,
        "trusted_claim_source_roots",
        snapshot_then_replace,
        raising=False,
    )
    claim = _claim(
        "method-repo-selection",
        f"Repository {REPO_ID} is the grounded proposal.",
        REPO_ID,
        "OUTSIDE METHOD SENTINEL",
    )

    roots = method.method_source_roots(root, PROGRAM_ID, [claim])
    violations = verify_claim_evidence(
        claim,
        _paths(root)["design"],
        source_roots=roots,
    )

    assert isinstance(roots[REPO_ID], EvidenceSourceSnapshot)
    assert any("anchored evidence snapshot is no longer current" in item for item in violations)


def test_method_input_change_after_prepare_stales_receipt_before_verify_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    repo_path = record_path(root, "repo", REPO_ID)
    repo = load_yaml(repo_path, default={})
    repo["summary"] = "changed at the same canonical repository path"
    write_yaml_if_changed(repo_path, repo)
    before = {
        key: path.read_bytes()
        for key, path in paths.items()
        if key in {"choice", "interfaces", "matrix"}
    }

    with pytest.raises(SystemExit, match="Method inputs changed after prepare"):
        _verify(method, monkeypatch, root)

    assert {
        key: paths[key].read_bytes()
        for key in before
    } == before
    assert not paths["events"].exists()


def test_confirm_rejects_claim_changes_after_verification_without_side_effects(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    expected = _review_snapshot(root)
    choice = load_yaml(paths["choice"], default={})
    choice["payload"]["claims"][0]["text"] += " Stale edit."
    write_yaml_if_changed(paths["choice"], choice)

    with pytest.raises(SystemExit, match="not ready for confirmation"):
        _confirm(method, monkeypatch, root, expected=expected)

    state = load_yaml(paths["state"], default={})
    choice = load_yaml(paths["choice"], default={})
    assert "selected_repo_id" not in state
    assert "selected_repo_id" not in choice
    assert state["stage"] == "idea-review"
    assert not paths["events"].exists()


def test_confirm_rejects_hard_preference_change_after_verification_without_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {"constraints": ["new local-only boundary"]},
    )

    with pytest.raises(SystemExit, match="preferences changed"):
        _confirm(method, monkeypatch, root)

    assert "selected_repo_id" not in load_yaml(paths["choice"], default={})
    assert "selected_repo_id" not in load_yaml(paths["state"], default={})
    assert not paths["events"].exists()


def test_reject_selection_closes_review_without_advancing_program(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0

    assert _reject(method, monkeypatch, root) == 0

    choice = load_yaml(paths["choice"], default={})
    state = load_yaml(paths["state"], default={})
    interfaces = load_yaml(paths["interfaces"], default={})
    matrix = load_yaml(paths["matrix"], default={})
    assert choice["confirmation_status"] == "rejected"
    assert choice["needs_human_confirmation"] is True
    assert choice["rejection"]["reason"] == "Use a different implementation base."
    assert {claim["confirmation_status"] for claim in choice["payload"]["claims"]} == {"rejected"}
    assert "selected_repo_id" not in choice
    assert "selected_repo_id" not in state
    assert state["stage"] == "idea-review"
    assert state["method_proposal"]["status"] == "rejected"
    assert interfaces["proposal_status"] == "rejected"
    assert matrix["proposal_status"] == "rejected"
    assert not paths["events"].exists()
    assert "method:reject" in {str(item.get("op_type") or "") for item in committed_ops(root)}


def test_method_old_review_snapshot_cannot_confirm_changed_selection_reason(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    choice = load_yaml(paths["choice"], default={})
    expected = _review_snapshot(root)
    choice["payload"]["method_selection"]["selection_reason"] = "Changed after the user saw the review card."
    write_yaml_if_changed(paths["choice"], choice)

    with pytest.raises(SystemExit, match="review snapshot is stale"):
        _confirm(method, monkeypatch, root, expected=expected)

    assert "selected_repo_id" not in load_yaml(paths["choice"], default={})
    assert "selected_repo_id" not in load_yaml(paths["state"], default={})
    assert not paths["events"].exists()


def test_method_review_blocks_mismatched_operative_repo_field(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    expected = _review_snapshot(root)
    choice = load_yaml(paths["choice"], default={})
    choice["proposed_repo_id"] = "r-different-operative-value"
    write_yaml_if_changed(paths["choice"], choice)

    assert discover_pending_judgements(root) == []
    with pytest.raises(SystemExit, match="divergent operative"):
        _confirm(method, monkeypatch, root, expected=expected)

    assert "selected_repo_id" not in load_yaml(paths["choice"], default={})
    assert "selected_repo_id" not in load_yaml(paths["state"], default={})
    assert not paths["events"].exists()


def test_prepare_abort_does_not_leave_empty_design_directory(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)

    def fail_first_yaml_write(_path: Path, _value: object) -> None:
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(method, "write_yaml_if_changed", fail_first_yaml_write)
    with pytest.raises(RuntimeError, match="injected write failure"):
        _prepare(method, monkeypatch, root)
    assert not paths["design"].exists()


def test_legacy_preselection_artifact_fails_closed(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    write_yaml_if_changed(
        paths["choice"],
        {
            "idea_id": IDEA_ID,
            "program_id": PROGRAM_ID,
            "selected_repo_id": REPO_ID,
            "selection_judgement": {"claim": "", "evidence": []},
        },
    )

    with pytest.raises(SystemExit, match="needs explicit migration"):
        _verify(method, monkeypatch, root)
    assert load_yaml(paths["choice"], default={})["selected_repo_id"] == REPO_ID
    assert not paths["events"].exists()

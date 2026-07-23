from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import has_complete_confirmation_receipt
from research.core import default_record, ensure_workspace, record_path
from research.journal import committed_ops


IDEA_ID = "i-r2-method-123456"
REPO_ID = "r-r2-method-123456"
PROGRAM_ID = "p-r2-method"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_method_module():
    script = _project_root() / ".agents" / "skills" / "method-designer" / "scripts" / "method.py"
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
    ensure_workspace(root)
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
    design = root / "kb" / "programs" / PROGRAM_ID / "design"
    return {
        "design": design,
        "choice": design / f"{IDEA_ID}-repo-choice.yaml",
        "interfaces": design / f"{IDEA_ID}-interfaces.yaml",
        "matrix": design / f"{IDEA_ID}-experiment-matrix.yaml",
        "method": design / f"{IDEA_ID}-method.md",
        "state": root / "kb" / "programs" / PROGRAM_ID / "state.yaml",
        "events": root / "kb" / "programs" / PROGRAM_ID / "workflow" / "reporting-events.yaml",
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


def _confirm(method, monkeypatch, root: Path) -> int:
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

    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    choice = load_yaml(paths["choice"], default={})
    state = load_yaml(paths["state"], default={})
    assert choice["status"] == "ready_for_review"
    assert choice["needs_human_confirmation"] is True
    assert choice["payload"]["verification"]["verified_at"]
    assert "selected_repo_id" not in choice
    assert "selected_repo_id" not in state
    assert state["stage"] == "idea-review"
    assert not paths["events"].exists()

    assert _confirm(method, monkeypatch, root) == 0
    choice = load_yaml(paths["choice"], default={})
    state = load_yaml(paths["state"], default={})
    interfaces = load_yaml(paths["interfaces"], default={})
    matrix = load_yaml(paths["matrix"], default={})
    events = load_yaml(paths["events"], default={})["items"]
    assert choice["selected_repo_id"] == REPO_ID
    assert choice["confirmation_status"] == "confirmed"
    assert has_complete_confirmation_receipt(choice)
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

    choice["payload"]["claims"][0]["text"] += " Changed after confirmation."
    write_yaml_if_changed(paths["choice"], choice)
    assert not has_complete_confirmation_receipt(load_yaml(paths["choice"], default={}))


def test_confirm_rejects_claim_changes_after_verification_without_side_effects(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root = _workspace(tmp_path)
    paths = _paths(root)
    assert _prepare(method, monkeypatch, root) == 0
    _fill_method_claims(root)
    assert _verify(method, monkeypatch, root) == 0
    choice = load_yaml(paths["choice"], default={})
    choice["payload"]["claims"][0]["text"] += " Stale edit."
    write_yaml_if_changed(paths["choice"], choice)

    with pytest.raises(SystemExit, match="verification receipt is missing or stale"):
        _confirm(method, monkeypatch, root)

    state = load_yaml(paths["state"], default={})
    choice = load_yaml(paths["choice"], default={})
    assert "selected_repo_id" not in state
    assert "selected_repo_id" not in choice
    assert state["stage"] == "idea-review"
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

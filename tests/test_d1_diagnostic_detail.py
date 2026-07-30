from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import research.diagnostics as diagnostics
from research.diagnostics import (
    apply_diagnostic_retrospective,
    capture_runtime_failure,
    diagnostic_detail_path,
    diagnostics_path,
    diagnostics_policy,
    export_diagnostic_preview,
    list_diagnostic_issues,
    load_diagnostic_detail,
)
from research.git_ops import dirty_kb_paths, ensure_kb_git_repo, git_checkpoint
from research.prefs import load_runtime_preferences, write_runtime_preferences
from research.yaml_io import load_yaml, write_yaml_if_changed


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents").mkdir(parents=True)
    (root / ".agents" / "VERSION").write_text("0.2.0-rc.7\n", encoding="utf-8")
    (root / ".agents" / ".install-manifest.json").write_text(
        json.dumps({"source_commit": "a" * 40}),
        encoding="utf-8",
    )
    return root


def _enable_detail(root: Path, *, mode: str = "errors-only", budget: int = 0) -> None:
    write_runtime_preferences(
        root,
        {
            "diagnostics": {
                "mode": mode,
                "detail_level": "local-detailed",
                "token_budget_per_task": budget,
            }
        },
    )


def _envelope(path: str = "skills/source-intake/scripts/intake.py") -> dict[str, object]:
    return {
        "schema": "diagnostic-mechanical-envelope/v1",
        "exception_class": "OwnerExit",
        "failure_stage": "materialization",
        "frames": [{"path": path, "line": 91, "function": "materialize"}],
        "events": ["owner-nonzero-exit", "dispatcher-capture"],
        "runtime_version": "python-3.13.5",
        "dependency_versions": {"pyyaml": "6.0.2"},
    }


def _capture(root: Path, *, envelope: dict[str, object] | None = None) -> dict[str, object]:
    issue = capture_runtime_failure(
        root,
        skill="source-intake",
        operation="add",
        returncode=1,
        public_summary="知识库操作未完成。",
        detail_envelope=envelope,
    )
    assert issue is not None
    return issue


def test_detail_policy_is_orthogonal_and_legacy_scalar_modes_survive_round_trip(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    write_yaml_if_changed(
        root / "kb/config/runtime-preferences.yaml",
        {
            "diagnostics": {
                "mode": "developer",
                "per_skill": {"source-intake": "errors-only"},
                "detail_level": "local-detailed",
                "per_skill_detail_level": {
                    "source-intake": "redacted",
                    "unit-analyst": "local-detailed",
                    "bad": "raw",
                },
            }
        },
    )

    source = diagnostics_policy(root, "source-intake")
    unit = diagnostics_policy(root, "unit-analyst")
    assert source["effective_mode"] == "errors-only"
    assert source["effective_detail_level"] == "redacted"
    assert source["persist_local_detail"] is False
    assert unit["effective_mode"] == "developer"
    assert unit["effective_detail_level"] == "local-detailed"
    assert unit["persist_local_detail"] is True

    write_runtime_preferences(root, {})
    stored = load_yaml(root / "kb/config/runtime-preferences.yaml")
    assert stored["diagnostics"]["per_skill"] == {"source-intake": "errors-only"}
    assert stored["diagnostics"]["per_skill_detail_level"] == {
        "source-intake": "redacted",
        "unit-analyst": "local-detailed",
    }
    assert "memory/skill-evolution/.private/" in stored["versioning"]["ignored_paths"]


def test_errors_only_detail_is_private_bounded_and_export_remains_summary_only(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    issue = _capture(root, envelope=_envelope())

    detail_path = diagnostic_detail_path(root, str(issue["id"]))
    assert stat.S_IMODE(detail_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(detail_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(detail_path.parent.parent.stat().st_mode) == 0o700
    assert issue["detail_ref"].startswith("memory/skill-evolution/.private/details/")
    assert issue["detail_digest"] == hashlib.sha256(detail_path.read_bytes()).hexdigest()
    assert issue["retrospective_status"] == "not-run"

    detail = load_diagnostic_detail(root, issue_id=str(issue["id"]))
    current = detail["occurrence_history"][-1]
    assert current["root_cause"] == {
        "status": "not-run",
        "reason": "mode-errors-only",
        "explanation": "",
    }
    assert current["relevant_trace"] == [
        {
            "path": "skills/source-intake/scripts/intake.py",
            "line": 91,
            "function": "materialize",
        }
    ]
    assert current["output_excerpt"] == []
    assert len(detail["occurrence_history"]) == 1

    preview = export_diagnostic_preview(root, authorized=True)
    serialized_preview = json.dumps(preview, ensure_ascii=False)
    for forbidden in ("detail_ref", "detail_digest", "retrospective_status", "relevant_trace"):
        assert forbidden not in serialized_preview


def test_developer_budget_states_and_digest_bound_hypothesis_apply(tmp_path: Path) -> None:
    zero_root = _workspace(tmp_path / "zero")
    _enable_detail(zero_root, mode="developer", budget=0)
    zero_issue = _capture(zero_root, envelope=_envelope())
    zero_detail = load_diagnostic_detail(zero_root, issue_id=str(zero_issue["id"]))
    assert zero_detail["occurrence_history"][-1]["root_cause"]["reason"] == "budget-zero"
    with pytest.raises(ValueError, match="not pending"):
        apply_diagnostic_retrospective(
            zero_root,
            issue_id=str(zero_issue["id"]),
            expected_detail_digest=str(zero_issue["detail_digest"]),
            explanation="A hypothesis",
            reproduction=[],
            optimization_candidates=["Add a boundary test"],
            next_validation=["Run the boundary test"],
        )

    root = _workspace(tmp_path / "pending")
    _enable_detail(root, mode="developer", budget=1200)
    issue = _capture(root, envelope=_envelope())
    assert issue["retrospective_status"] == "pending"
    result = apply_diagnostic_retrospective(
        root,
        issue_id=str(issue["id"]),
        expected_detail_digest=str(issue["detail_digest"]),
        explanation="Boundary ordering may be wrong at /Users/alice/private.py token=secret-value",
        reproduction=["Use a synthetic safe fixture"],
        optimization_candidates=["Add an explicit transaction boundary assertion"],
        next_validation=["Run the synthetic regression suite"],
    )
    assert result["retrospective_status"] == "hypothesis"
    detail = load_diagnostic_detail(root, issue_id=str(issue["id"]))
    current = detail["occurrence_history"][-1]
    assert current["root_cause"]["status"] == "hypothesis"
    serialized = diagnostic_detail_path(root, str(issue["id"])).read_text(encoding="utf-8")
    assert "/Users/alice" not in serialized
    assert "secret-value" not in serialized
    assert "<path>" in serialized
    with pytest.raises(ValueError, match="changed"):
        apply_diagnostic_retrospective(
            root,
            issue_id=str(issue["id"]),
            expected_detail_digest=str(issue["detail_digest"]),
            explanation="stale",
            reproduction=[],
            optimization_candidates=["stale"],
            next_validation=["stale"],
        )


def test_closed_envelope_rejects_arbitrary_output_and_falls_back_to_redacted_summary(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    unsafe = {
        **_envelope(),
        "stdout": "raw user/source/evidence text token=secret-value",
    }
    issue = _capture(root, envelope=unsafe)
    assert "detail_ref" not in issue
    assert not (root / "kb/memory/skill-evolution/.private").exists()
    serialized = diagnostics_path(root).read_text(encoding="utf-8")
    assert "raw user" not in serialized
    assert "secret-value" not in serialized


def test_detail_signature_splits_stable_roots_and_merges_equivalent_occurrences(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    first = _capture(root, envelope=_envelope("skills/source-intake/scripts/intake.py"))
    second = _capture(root, envelope=_envelope("runtime/lib/research/records.py"))
    assert first["id"] != second["id"]
    assert len(list_diagnostic_issues(root)) == 2

    for _ in range(7):
        first = _capture(root, envelope=_envelope("skills/source-intake/scripts/intake.py"))
    detail = load_diagnostic_detail(root, issue_id=str(first["id"]))
    assert first["occurrences"] == 8
    assert len(detail["occurrence_history"]) == 5
    assert detail["dropped_history_count"] == 3


def test_concurrent_equivalent_detail_capture_has_no_lost_occurrence(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    count = 20
    barrier = threading.Barrier(count)

    def run(_: int) -> dict[str, object]:
        barrier.wait(timeout=10)
        return _capture(root, envelope=_envelope())

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(run, range(count)))

    assert len({str(item["id"]) for item in results}) == 1
    issue = list_diagnostic_issues(root)[0]
    assert issue["occurrences"] == count
    detail = load_diagnostic_detail(root, issue_id=str(issue["id"]))
    assert len(detail["occurrence_history"]) == 5
    assert detail["dropped_history_count"] == count - 5


def test_detail_apply_fault_rolls_back_summary_and_private_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root, mode="developer", budget=1000)
    issue = _capture(root, envelope=_envelope())
    summary_before = diagnostics_path(root).read_bytes()
    detail_path = diagnostic_detail_path(root, str(issue["id"]))
    detail_before = detail_path.read_bytes()
    original_write = diagnostics.write_yaml_if_changed

    def fail_summary(target: Path, payload: object) -> None:
        original_write(target, payload)
        raise OSError("injected summary failure")

    monkeypatch.setattr(diagnostics, "write_yaml_if_changed", fail_summary)
    with pytest.raises(OSError, match="injected summary failure"):
        apply_diagnostic_retrospective(
            root,
            issue_id=str(issue["id"]),
            expected_detail_digest=str(issue["detail_digest"]),
            explanation="Safe hypothesis",
            reproduction=[],
            optimization_candidates=["Safe optimization"],
            next_validation=["Safe validation"],
        )
    assert diagnostics_path(root).read_bytes() == summary_before
    assert detail_path.read_bytes() == detail_before


def test_detail_create_fault_leaves_one_redacted_fallback_without_dangling_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    original_write = diagnostics.write_yaml_if_changed
    calls = 0

    def fail_first_summary(target: Path, payload: object) -> None:
        nonlocal calls
        calls += 1
        original_write(target, payload)
        if calls == 1:
            raise OSError("injected create summary failure")

    monkeypatch.setattr(diagnostics, "write_yaml_if_changed", fail_first_summary)
    issue = _capture(root, envelope=_envelope())
    assert "detail_ref" not in issue
    assert list_diagnostic_issues(root) == [issue]
    detail_root = root / "kb/memory/skill-evolution/.private/details"
    assert list(detail_root.glob("*.yaml")) == []
    operations = [
        load_yaml(path, default={})
        for path in (root / "kb/.journal").glob("*.yaml")
        if load_yaml(path, default={}).get("op_type") == "record-diagnostic-issue"
    ]
    assert sorted(item["state"] for item in operations) == ["abort", "commit"]


def test_unsafe_private_store_fails_soft_without_writing_outside(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    private_parent = root / "kb/memory/skill-evolution"
    private_parent.mkdir(parents=True, exist_ok=True)
    (private_parent / ".private").symlink_to(outside, target_is_directory=True)

    issue = _capture(root, envelope=_envelope())
    assert "detail_ref" not in issue
    assert list(outside.iterdir()) == []


def test_private_detail_leaf_symlink_is_not_replaced_or_followed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    outside = tmp_path / "outside.yaml"
    outside.write_text("sentinel\n", encoding="utf-8")
    first = _capture(root, envelope=_envelope())
    detail_path = diagnostic_detail_path(root, str(first["id"]))
    detail_path.unlink()
    detail_path.symlink_to(outside)

    fallback = _capture(root, envelope=_envelope())
    assert "detail_ref" not in fallback
    assert detail_path.is_symlink()
    assert outside.read_text(encoding="utf-8") == "sentinel\n"


def test_private_detail_is_hard_excluded_from_dirty_discovery_and_checkpoint(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _enable_detail(root)
    issue = _capture(root, envelope=_envelope())
    detail_path = diagnostic_detail_path(root, str(issue["id"]))
    ensure_kb_git_repo(root)

    # Simulate a path force-added by an older runtime: the hard boundary must
    # not rely on .gitignore alone.
    subprocess.run(
        [
            "git",
            "-C",
            str(root / "kb"),
            "add",
            "-f",
            "--",
            detail_path.relative_to(root / "kb").as_posix(),
        ],
        check=True,
    )
    assert detail_path not in dirty_kb_paths(root)
    result = git_checkpoint(
        root,
        "must not checkpoint private diagnostics",
        auto_init=False,
        target_paths=[detail_path],
    )
    assert result["status"] == "no-changes"

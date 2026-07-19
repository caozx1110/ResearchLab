from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

import research.diagnostics as diagnostics_module
from research.diagnostics import (
    capture_runtime_failure,
    diagnostics_path,
    diagnostics_policy,
    export_diagnostic_preview,
    list_diagnostic_issues,
    record_diagnostic_issue,
    redact_diagnostic_text,
    review_diagnostic_issue,
)
from research.prefs import load_runtime_preferences, write_runtime_preferences
from research.yaml_io import load_yaml


NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents").mkdir(parents=True)
    (root / ".agents" / "VERSION").write_text("0.2.0-rc.1\n", encoding="utf-8")
    (root / ".agents" / ".install-manifest.json").write_text(
        json.dumps({"source_commit": "9dcd1ad6134e7700fbfe641d938dae6958af71f4"}),
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _record(root: Path, summary: str, **overrides: object) -> tuple[dict, bool]:
    payload: dict[str, object] = {
        "category": "skill-defect",
        "severity": "medium",
        "skill": "paper-analyst",
        "summary": summary,
        "source": "agent",
        "now": NOW,
    }
    payload.update(overrides)
    return record_diagnostic_issue(root, **payload)  # type: ignore[arg-type]


def test_absent_root_policy_and_issue_reads_are_byte_identical(tmp_path: Path) -> None:
    root = tmp_path / "never-initialized"
    before = _snapshot(tmp_path)

    policy = diagnostics_policy(root, "paper-analyst")
    assert policy["mode"] == "off"
    assert policy["local_only"] is True
    assert policy["automatic_capture"] is False
    assert list_diagnostic_issues(root) == []
    assert diagnostics_path(root) == root / "kb" / "memory" / "skill-evolution" / "issues.yaml"

    assert _snapshot(tmp_path) == before
    assert not (root / "kb").exists()


def test_policy_normalizes_workspace_and_per_skill_override(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(
        root,
        {
            "diagnostics": {
                "mode": "developer",
                "per_skill": {
                    "paper-analyst": "off",
                    "repo-analyst": "errors-only",
                    "bad": "not-a-mode",
                },
                "local_only": False,
                "token_budget_per_task": -50,
                "max_issues_per_task": 0,
                "dedup_window_seconds": -1,
                "cooldown_seconds": -1,
            }
        },
    )

    paper = diagnostics_policy(root, "paper-analyst")
    repo = diagnostics_policy(root, "repo-analyst")
    other = diagnostics_policy(root, "blog-analyst")
    stored = load_runtime_preferences(root)["diagnostics"]
    assert paper["mode"] == "off"
    assert paper["skill_mode"] == "off"
    assert repo["mode"] == "errors-only"
    assert repo["automatic_capture"] is True
    assert other["mode"] == "developer"
    assert other["allow_agent_retrospective"] is False
    assert stored["per_skill"] == {"paper-analyst": "off", "repo-analyst": "errors-only"}
    assert stored["local_only"] is True
    assert stored["token_budget_per_task"] == 0
    assert stored["max_issues_per_task"] == 20
    assert stored["dedup_window_seconds"] == 0
    assert stored["cooldown_seconds"] == 0


def test_automatic_capture_respects_off_but_explicit_capture_does_not(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    assert capture_runtime_failure(
        root,
        skill="paper-analyst",
        operation="verify",
        returncode=2,
        public_summary="知识库操作未完成。",
    ) is None
    assert not diagnostics_path(root).exists()

    explicit, created = _record(root, "User explicitly asked to retain this defect.", source="user")
    assert created is True
    assert explicit["status"] == "pending"
    assert explicit["source"] == "user"

    write_runtime_preferences(root, {"diagnostics": {"mode": "errors-only"}})
    automatic = capture_runtime_failure(
        root,
        skill="paper-analyst",
        operation="verify",
        returncode=2,
        public_summary="知识库操作未完成。",
    )
    assert automatic is not None
    assert automatic["category"] == "runtime-failure"
    assert automatic["error_class"] == "owner-nonzero-exit"
    assert automatic["bundle_version"] == "0.2.0-rc.1"
    assert automatic["source_commit"] == "9dcd1ad6134e7700fbfe641d938dae6958af71f4"


def test_redaction_removes_paths_secrets_env_tracebacks_and_control_text(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    unsafe = (
        "Traceback (most recent call last):\n"
        '  File "/Users/alice/private/paper.py", line 9\n'
        "RuntimeError: failed /Users/alice/private/data.pdf "
        "API_KEY=sk-live-secret password=hunter2 HOME=/Users/alice \x1b[31mred\x1b[0m\u202e"
    )

    issue, _ = _record(
        root,
        "Parser failed at /Users/alice/private/data.pdf with token=top-secret",
        expected="No failure under C:\\Users\\alice\\paper.pdf",
        actual=unsafe,
        context="HOME=/Users/alice raw context /tmp/evidence.txt",
        error_class="RuntimeError at /Users/alice/private/paper.py",
    )
    serialized = diagnostics_path(root).read_text(encoding="utf-8")
    lowered = serialized.lower()
    for forbidden in ("/users/alice", "c:\\users", "sk-live-secret", "hunter2", "top-secret", "traceback (most"):
        assert forbidden not in lowered
    assert "<path>" in serialized
    assert "<secret-redacted>" in serialized
    assert "<env-redacted>" in serialized
    assert "\x1b" not in serialized
    assert "\u202e" not in serialized
    assert issue["privacy_classification"] == "local-redacted"
    assert issue["error_class"] == "runtimeerror-at-users-alice-private-paper.py"
    assert redact_diagnostic_text(unsafe) == redact_diagnostic_text(unsafe)


def test_deterministic_near_duplicate_merges_and_bumps_occurrences(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first, created_first = _record(root, "Owner failed (attempt 1).", trigger="verify!")
    second, created_second = _record(root, " owner FAILED attempt 1 ", trigger="VERIFY")
    third, created_third = _record(root, "Owner failed attempt 2", trigger="verify")

    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    assert second["occurrences"] == 2
    assert created_third is True
    assert third["id"] != first["id"]
    assert len(list_diagnostic_issues(root)) == 2


def test_review_statuses_listing_and_authorized_export_preview(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    issues = [_record(root, f"Issue {index}")[0] for index in range(3)]

    assert review_diagnostic_issue(root, issue_id=issues[0]["id"], status="confirmed")["status"] == "confirmed"
    assert review_diagnostic_issue(root, issue_id=issues[1]["id"], status="dismissed")["status"] == "dismissed"
    assert review_diagnostic_issue(root, issue_id=issues[2]["id"], status="resolved")["status"] == "resolved"
    assert [issue["id"] for issue in list_diagnostic_issues(root, status="resolved")] == [issues[2]["id"]]
    with pytest.raises(PermissionError, match="explicit current-user authorization"):
        export_diagnostic_preview(root)

    before = _snapshot(root)
    preview = export_diagnostic_preview(root, authorized=True)
    assert preview["local_only"] is True
    assert preview["redacted"] is True
    assert len(preview["issues"]) == 3
    assert all("context" not in issue and "fingerprint" not in issue for issue in preview["issues"])
    assert _snapshot(root) == before


def test_fifty_concurrent_distinct_captures_retain_every_issue(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    count = 50
    start = threading.Barrier(count)

    def capture(index: int) -> tuple[dict, bool]:
        start.wait(timeout=10)
        return _record(root, f"Distinct concurrency defect number {index}")

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(capture, range(count)))

    issues = list_diagnostic_issues(root)
    assert len(issues) == count
    assert len({issue["id"] for issue in issues}) == count
    assert all(created for _, created in results)
    assert all(issue["occurrences"] == 1 for issue in issues)


def test_fifty_concurrent_equivalent_captures_merge_without_lost_occurrence(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    count = 50
    start = threading.Barrier(count)

    def capture(_: int) -> tuple[dict, bool]:
        start.wait(timeout=10)
        return _record(root, "The same concurrent runtime defect.")

    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(capture, range(count)))

    issues = list_diagnostic_issues(root)
    assert len(issues) == 1
    assert issues[0]["occurrences"] == count
    assert sum(1 for _, created in results if created) == 1


def test_failed_write_rolls_back_without_half_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _workspace(tmp_path)
    path = diagnostics_path(root)
    original_write = diagnostics_module.write_yaml_if_changed

    def fail_after_write(target: Path, payload: object) -> None:
        original_write(target, payload)
        raise OSError("simulated diagnostic write fault")

    monkeypatch.setattr(diagnostics_module, "write_yaml_if_changed", fail_after_write)
    with pytest.raises(OSError, match="simulated diagnostic write fault"):
        _record(root, "This issue must roll back completely.")

    assert not path.exists()
    operations = [
        load_yaml(item, default={})
        for item in (root / "kb" / ".journal").glob("*.yaml")
        if load_yaml(item, default={}).get("op_type") == "record-diagnostic-issue"
    ]
    assert len(operations) == 1
    assert operations[0]["state"] == "abort"
    assert operations[0]["target_paths"] == ["memory/skill-evolution/issues.yaml"]

from __future__ import annotations

import json
import importlib.util
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from repo_paths import REPO_ROOT, source_path

import pytest

import research.diagnostics as diagnostics_module
from research.diagnostics import (
    capture_runtime_failure,
    diagnostics_path,
    diagnostics_policy,
    export_diagnostic_preview,
    list_diagnostic_issues,
    publish_runtime_failure_stage,
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


def _load_owner_script(relative_path: str, module_name: str):
    script = source_path(relative_path)
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_intake_failure_stage_handoff_is_allowlisted_private_and_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(root, {"diagnostics": {"mode": "errors-only"}})
    monkeypatch.setattr(diagnostics_module.os, "getppid", diagnostics_module.os.getpid)

    assert publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
        failure_stage="materialization",
    ) is True
    receipt_directory = root / "kb" / ".runtime" / "diagnostics" / "failure-stages"
    receipts = list(receipt_directory.glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="ascii"))
    assert set(receipt) == {
        "schema",
        "parent_pid",
        "skill",
        "operation",
        "failure_stage",
        "created_at_epoch",
    }
    assert receipt["failure_stage"] == "materialization"
    assert receipt["skill"] == "source-intake"
    assert receipt["operation"] == "add"
    assert receipts[0].stat().st_mode & 0o777 == 0o600

    issue = capture_runtime_failure(
        root,
        skill="source-intake",
        operation="add",
        returncode=1,
        public_summary="知识库操作未完成。",
    )
    assert issue is not None
    assert issue["failure_stage"] == "materialization"
    assert issue["error_class"] == "owner-nonzero-exit.materialization"
    assert list(receipt_directory.glob("*.json")) == []
    assert export_diagnostic_preview(root, authorized=True)["issues"][0]["failure_stage"] == "materialization"

    unknown = capture_runtime_failure(
        root,
        skill="source-intake",
        operation="add",
        returncode=1,
        public_summary="知识库操作未完成。",
    )
    assert unknown is not None
    assert unknown["failure_stage"] == "unknown"
    assert unknown["error_class"] == "owner-nonzero-exit.unknown"


def test_intake_failure_stage_handoff_has_exactly_one_concurrent_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(root, {"diagnostics": {"mode": "errors-only"}})
    monkeypatch.setattr(diagnostics_module.os, "getppid", diagnostics_module.os.getpid)
    assert publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
        failure_stage="checkpoint",
    ) is True
    original_claim = diagnostics_module._claim_failure_stage_receipt
    start = threading.Barrier(2)

    def gated_claim(
        directory: int,
        filename: str,
    ) -> tuple[str, tuple[int, int]] | None:
        start.wait(timeout=10)
        return original_claim(directory, filename)

    monkeypatch.setattr(diagnostics_module, "_claim_failure_stage_receipt", gated_claim)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda _index: diagnostics_module._consume_runtime_failure_stage(
                    root,
                    skill="source-intake",
                    operation="add",
                ),
                range(2),
            )
        )

    assert sorted(outcomes) == ["checkpoint", "unknown"]
    receipt_directory = root / "kb" / ".runtime" / "diagnostics" / "failure-stages"
    assert list(receipt_directory.iterdir()) == []


def test_intake_failure_stage_handoff_rejects_world_writable_final_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(root, {"diagnostics": {"mode": "errors-only"}})
    monkeypatch.setattr(diagnostics_module.os, "getppid", diagnostics_module.os.getpid)
    assert publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
        failure_stage="checkpoint",
    ) is True
    receipt_directory = root / "kb" / ".runtime" / "diagnostics" / "failure-stages"
    receipt = next(receipt_directory.glob("*.json"))
    before = receipt.read_bytes()
    receipt_directory.chmod(0o777)

    assert publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
        failure_stage="materialization",
    ) is False
    assert diagnostics_module._consume_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
    ) == "unknown"
    assert stat.S_IMODE(receipt_directory.stat().st_mode) == 0o777
    assert receipt.read_bytes() == before
    assert list(receipt_directory.iterdir()) == [receipt]


def test_intake_failure_stage_handoff_fails_closed_on_unsafe_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(root, {"diagnostics": {"mode": "errors-only"}})
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = root / "kb" / ".runtime" / "diagnostics"
    parent.mkdir(parents=True)
    (parent / "failure-stages").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(diagnostics_module.os, "getppid", diagnostics_module.os.getpid)

    assert publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
        failure_stage="checkpoint",
    ) is False
    assert list(outside.iterdir()) == []


def test_intake_failure_stage_handoff_off_mode_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr(diagnostics_module.os, "getppid", diagnostics_module.os.getpid)

    assert publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation="add",
        failure_stage="checkpoint",
    ) is False
    assert not (root / "kb").exists()


def test_personal_automatic_capture_keeps_only_normalized_mechanical_fields_and_export_strips_them(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(
        root,
        {
            "governance_profile": "personal",
            "diagnostics": {"mode": "errors-only"},
        },
    )

    automatic = capture_runtime_failure(
        root,
        skill="Paper Analyst /private/owner",
        operation="VERIFY /Users/alice/private.pdf",
        returncode=17,
        public_summary="Failed at /Users/alice/private.pdf with token=top-secret",
    )
    assert automatic is not None
    assert automatic["category"] == "runtime-failure"
    assert automatic["owner"] == "unknown-skill"
    assert automatic["operation"] == "unknown-operation"
    assert automatic["return_code"] == 17
    serialized = diagnostics_path(root).read_text(encoding="utf-8").lower()
    assert "/users/alice" not in serialized
    assert "alice" not in serialized
    assert "top-secret" not in serialized

    explicit, _created = _record(root, "Explicit issue remains fully redacted.")
    assert "owner" not in explicit
    assert "operation" not in explicit
    assert "return_code" not in explicit

    preview = export_diagnostic_preview(root, authorized=True)
    assert all("owner" not in issue and "operation" not in issue and "return_code" not in issue for issue in preview["issues"])


def test_strict_automatic_capture_preserves_existing_redacted_shape(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(
        root,
        {
            "governance_profile": "strict",
            "diagnostics": {"mode": "errors-only"},
        },
    )

    issue = capture_runtime_failure(
        root,
        skill="paper-analyst",
        operation="verify",
        returncode=2,
        public_summary="Knowledge operation failed.",
    )
    assert issue is not None
    assert "owner" not in issue
    assert "operation" not in issue
    assert "return_code" not in issue


def test_redaction_removes_paths_secrets_env_tracebacks_and_control_text(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    unsafe = (
        "Traceback (most recent call last):\n"
        '  File "/Users/alice/private/paper.py", line 9\n'
        "RuntimeError: failed /Users/alice/private/data.pdf "
        "API_KEY=sk-live-secret password=hunter2 HOME=/Users/alice "
        "contact=alice@example.com standalone=sk-test-ABCD1234567890 "
        "github_pat_ABCDEF1234567890 xoxb-1234567890-abcdefghij "
        "AKIAABCDEFGHIJKLMNOP \x1b[31mred\x1b[0m\u202e"
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
    for forbidden in (
        "/users/alice",
        "c:\\users",
        "sk-live-secret",
        "hunter2",
        "top-secret",
        "alice@example.com",
        "sk-test-abcd1234567890",
        "github_pat_abcdef1234567890",
        "xoxb-1234567890-abcdefghij",
        "akiaabcdefghijklmnop",
        "traceback (most",
        "alice",
        "evidence.txt",
    ):
        assert forbidden not in lowered
    assert "<path>" in serialized
    assert "<secret-redacted>" in serialized
    assert "<email-redacted>" in serialized
    assert "<credential-redacted>" in serialized
    assert "<env-redacted>" in serialized
    assert "\x1b" not in serialized
    assert "\u202e" not in serialized
    assert issue["privacy_classification"] == "local-redacted"
    assert issue["context"].startswith("context-sha256:")
    assert issue["error_class"] == "runtimeerror"
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


def test_config_owner_sets_normalized_diagnostics_in_one_root_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    config = _load_owner_script(
        ".agents/skills/research-config-manager/scripts/config.py",
        "d1_config_owner_script",
    )
    monkeypatch.setattr(config, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "config.py",
            "--root",
            str(root),
            "set-diagnostics",
            "--mode",
            "developer",
            "--detail-level",
            "local-detailed",
            "--skill",
            "paper-analyst",
            "--skill-mode",
            "errors-only",
            "--skill-detail-level",
            "redacted",
            "--token-budget-per-task",
            "1200",
            "--max-issues-per-task",
            "12",
        ],
    )

    assert config.main() == 0
    policy = diagnostics_policy(root, "paper-analyst")
    raw = load_yaml(root / "kb" / "config" / "runtime-preferences.yaml", default={})
    assert policy["workspace_mode"] == "developer"
    assert policy["mode"] == "errors-only"
    assert policy["workspace_detail_level"] == "local-detailed"
    assert policy["detail_level"] == "redacted"
    assert raw["diagnostics"]["per_skill"] == {"paper-analyst": "errors-only"}
    assert raw["diagnostics"]["per_skill_detail_level"] == {"paper-analyst": "redacted"}
    assert policy["token_budget_per_task"] == 1200
    assert policy["max_issues_per_task"] == 12
    assert raw["diagnostics"]["local_only"] is True
    operations = [
        load_yaml(item, default={})
        for item in (root / "kb" / ".journal").glob("*.yaml")
        if load_yaml(item, default={}).get("op_type") == "set-diagnostics"
    ]
    assert len(operations) == 1
    assert operations[0]["state"] == "commit"
    assert operations[0]["parent_op_id"] == ""
    assert operations[0]["target_paths"] == ["config/runtime-preferences.yaml"]


def test_diagnostics_owner_script_exposes_locked_operations(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    owner = _load_owner_script(
        ".agents/skills/skill-evolution-advisor/scripts/diagnostics.py",
        "d1_diagnostics_owner_script",
    )
    parser = owner.build_parser()

    assert parser.parse_args(["record", "--category", "skill-defect", "--severity", "low", "--skill", "paper-analyst", "--summary", "safe"]).command == "record"
    assert parser.parse_args(["capture-runtime-failure", "--skill", "repo-analyst", "--operation", "verify", "--returncode", "2"]).returncode == 2
    assert parser.parse_args(["review", "--id", "diag-123", "--status", "resolved"]).status == "resolved"
    assert parser.parse_args(["export-preview", "--authorized"]).authorized is True
    assert parser.parse_args(["detail", "--id", "diag-123"]).id == "diag-123"
    apply_args = parser.parse_args(
        [
            "apply-retrospective",
            "--id",
            "diag-123",
            "--expected-detail-digest",
            "a" * 64,
            "--analysis-file",
            "diagnostic-analysis.json",
        ]
    )
    assert apply_args.command == "apply-retrospective"
    analysis_path = root / "kb/.runtime/diagnostic-analysis.json"
    analysis_path.parent.mkdir(parents=True)
    analysis_path.write_text(
        json.dumps(
            {
                "explanation": "safe hypothesis",
                "reproduction": [],
                "optimization_candidates": ["safe candidate"],
                "next_validation": ["safe validation"],
            }
        ),
        encoding="utf-8",
    )
    analysis_path.chmod(0o600)
    assert owner._load_private_analysis(root, "diagnostic-analysis.json")["explanation"] == "safe hypothesis"
    analysis_path.chmod(0o644)
    with pytest.raises(SystemExit, match="regular private runtime file"):
        owner._load_private_analysis(root, "diagnostic-analysis.json")


def test_config_owner_accepts_detail_only_skill_override_without_rewriting_mode_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    write_runtime_preferences(
        root,
        {"diagnostics": {"per_skill": {"unit-analyst": "developer"}}},
    )
    config = _load_owner_script(
        ".agents/skills/research-config-manager/scripts/config.py",
        "d1_config_detail_only_owner_script",
    )
    monkeypatch.setattr(config, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "config.py",
            "--root",
            str(root),
            "set-diagnostics",
            "--skill",
            "unit-analyst",
            "--skill-detail-level",
            "local-detailed",
        ],
    )

    assert config.main() == 0
    raw = load_yaml(root / "kb/config/runtime-preferences.yaml", default={})
    assert raw["diagnostics"]["per_skill"] == {"unit-analyst": "developer"}
    expected_skills = {
        "unit-analyst",
        *config.SKILL_IMPLEMENTATION_ALIASES.get("unit-analyst", ()),
    }
    assert raw["diagnostics"]["per_skill_detail_level"] == {
        skill: "local-detailed" for skill in expected_skills
    }

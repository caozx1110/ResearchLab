from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

from research.diagnostics import load_diagnostic_detail, list_diagnostic_issues
from research.prefs import write_runtime_preferences


PUBLIC_VERBS = (
    "help",
    "init",
    "doctor",
    "update",
    "obsidian",
    "add",
    "ingest",
    "review",
    "status",
    "next",
    "find",
    "recall",
    "resume",
    "undo",
    "restore",
    "reject",
)


def _project_root() -> Path:
    return REPO_ROOT


def _load_kb_cli():
    script = _project_root() / "skills" / "kb-cli" / "scripts" / "kb"
    loader = importlib.machinery.SourceFileLoader("kb_cli_d1_public_tests", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _child_result(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class CaptureDependencyStub:
    """Minimal stateful stand-in for Track A; production policy stays in Track A."""

    def __init__(self, mode: str, *, skill_modes: dict[str, str] | None = None) -> None:
        self.mode = mode
        self.skill_modes = skill_modes or {}
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        project_root: Path,
        *,
        skill: str,
        operation: str,
        returncode: int,
        public_summary: str = "",
        detail_envelope: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        payload = {
            "skill": skill,
            "operation": operation,
            "returncode": returncode,
            "public_summary": public_summary,
            "detail_envelope": detail_envelope,
        }
        self.calls.append(payload)
        effective = self.skill_modes.get(skill, "inherit")
        effective = self.mode if effective == "inherit" else effective
        if effective == "off":
            return None

        issue_path = project_root / "memory" / "skill-evolution" / "issues.yaml"
        if issue_path.exists():
            stored = json.loads(issue_path.read_text(encoding="utf-8"))
        else:
            stored = {"issues": []}
        issues = stored["issues"]
        key = (skill, operation, returncode)
        existing = next(
            (
                issue
                for issue in issues
                if (issue["skill"], issue["operation"], issue["returncode"]) == key
            ),
            None,
        )
        if existing is None:
            existing = {**payload, "occurrences": 1}
            issues.append(existing)
        else:
            existing["occurrences"] += 1
        issue_path.parent.mkdir(parents=True, exist_ok=True)
        issue_path.write_text(json.dumps(stored, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return existing


def test_default_off_failure_creates_no_diagnostic_write(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    capture = CaptureDependencyStub("off")
    monkeypatch.setattr(kb, "_capture_runtime_failure", capture)
    monkeypatch.setattr(
        kb.subprocess,
        "run",
        lambda *args, **kwargs: _child_result(
            17,
            stdout="raw stdout must not enter diagnostics",
            stderr="/private/secret traceback --token user words",
        ),
    )

    assert kb.main(["--root", str(tmp_path), "status"]) == 17

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "知识库状态暂时无法读取；详细诊断已保留给 Agent。\n"
    assert capture.calls == [
        {
            "skill": "knowledge-base-manager",
            "operation": "status",
            "returncode": 17,
            "public_summary": "知识库操作未完成。",
            "detail_envelope": {
                "schema": "diagnostic-mechanical-envelope/v1",
                "exception_class": "owner-nonzero-exit",
                "failure_stage": "unknown",
                "frames": [],
                "events": ["owner-nonzero-exit", "dispatcher-capture"],
                "runtime_version": (
                    f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                ),
                "dependency_versions": {},
            },
        }
    ]
    assert not (tmp_path / "kb").exists()


def test_enabled_failure_creates_one_issue_and_repeat_bumps(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    capture = CaptureDependencyStub("errors-only")
    monkeypatch.setattr(kb, "_capture_runtime_failure", capture)
    monkeypatch.setattr(kb.subprocess, "run", lambda *args, **kwargs: _child_result(9))

    assert kb.main(["--root", str(tmp_path), "status"]) == 9
    capsys.readouterr()
    assert kb.main(["--root", str(tmp_path), "status"]) == 9
    capsys.readouterr()

    issue_path = tmp_path / "memory" / "skill-evolution" / "issues.yaml"
    issues = json.loads(issue_path.read_text(encoding="utf-8"))["issues"]
    assert len(issues) == 1
    assert issues[0]["occurrences"] == 2
    assert len(capture.calls) == 2


def test_per_skill_off_overrides_developer_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    capture = CaptureDependencyStub("developer", skill_modes={"knowledge-base-manager": "off"})
    monkeypatch.setattr(kb, "_capture_runtime_failure", capture)
    monkeypatch.setattr(kb.subprocess, "run", lambda *args, **kwargs: _child_result(5))

    assert kb.main(["--root", str(tmp_path), "status"]) == 5

    capsys.readouterr()
    assert len(capture.calls) == 1
    assert not (tmp_path / "kb").exists()


def test_success_does_not_call_capture_or_create_issue(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    capture = CaptureDependencyStub("developer")
    monkeypatch.setattr(kb, "_capture_runtime_failure", capture)
    monkeypatch.setattr(kb.subprocess, "run", lambda *args, **kwargs: _child_result(0))

    assert kb.main(["--root", str(tmp_path), "status"]) == 0

    assert "知识库尚未收录资料" in capsys.readouterr().out
    assert capture.calls == []
    assert not (tmp_path / "kb").exists()


def test_capture_exception_preserves_original_exit_and_public_text(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kb = _load_kb_cli()

    def fail_capture(*args, **kwargs):
        raise RuntimeError("secret traceback at /absolute/private/path")

    monkeypatch.setattr(kb, "_capture_runtime_failure", fail_capture)
    monkeypatch.setattr(kb.subprocess, "run", lambda *args, **kwargs: _child_result(23))

    assert kb.main(
        ["--root", str(tmp_path), "--agent-protocol", "failure.json", "status"]
    ) == 23

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "知识库状态暂时无法读取；详细诊断已保留给 Agent。\n"
    protocol_text = (tmp_path / ".runtime" / "failure.json").read_text(encoding="utf-8")
    protocol = json.loads(protocol_text)
    assert protocol["exit_code"] == 23
    assert protocol["details"]["diagnostic_events"] == [
        {
            "code": "runtime-failure-capture-failed",
            "operation": "status",
            "skill": "knowledge-base-manager",
        }
    ]
    assert "secret traceback" not in protocol_text
    assert "/absolute/private/path" not in protocol_text


def test_real_intake_child_hands_allowlisted_failure_stage_to_dispatcher(tmp_path: Path) -> None:
    kb = _load_kb_cli()
    write_runtime_preferences(
        tmp_path,
        {"diagnostics": {"mode": "errors-only", "detail_level": "local-detailed"}},
    )
    kb._ACTIVE_PUBLIC_VERB = "add"

    result = kb.forward_command(
        tmp_path,
        ".agents/skills/source-intake/scripts/intake.py",
        ["add", "--kind", "blog", "--source", ""],
        stream=False,
    )

    assert result.returncode == 1
    issues = list_diagnostic_issues(tmp_path, skill="source-intake")
    assert len(issues) == 1
    assert issues[0]["failure_stage"] == "source-recognition"
    assert issues[0]["error_class"] == "owner-nonzero-exit.source-recognition"
    detail = load_diagnostic_detail(tmp_path, issue_id=str(issues[0]["id"]))
    assert detail["occurrence_history"][-1]["observation"]["failure_stage"] == "source-recognition"
    serialized = (tmp_path / "memory" / "skill-evolution" / "issues.yaml").read_text(
        encoding="utf-8"
    )
    assert str(tmp_path) not in serialized
    assert list(
        (tmp_path / ".runtime" / "diagnostics" / "failure-stages").glob("*.json")
    ) == []


def test_dispatcher_hands_only_closed_mechanical_detail_to_private_store(
    monkeypatch,
    tmp_path: Path,
) -> None:
    kb = _load_kb_cli()
    write_runtime_preferences(
        tmp_path,
        {"diagnostics": {"mode": "errors-only", "detail_level": "local-detailed"}},
    )
    kb._ACTIVE_PUBLIC_VERB = "status"
    monkeypatch.setattr(
        kb.subprocess,
        "run",
        lambda *args, **kwargs: _child_result(
            19,
            stdout="private paper text token=unsafe-value",
            stderr=f'Traceback File "{tmp_path}/secret.py", line 7 user words',
        ),
    )

    result = kb.forward_command(
        tmp_path,
        ".agents/skills/knowledge-base-manager/scripts/kb.py",
        ["status", "--secret", "unsafe-value"],
        stream=False,
    )

    assert result.returncode == 19
    issue = list_diagnostic_issues(tmp_path, skill="knowledge-base-manager")[0]
    detail = load_diagnostic_detail(tmp_path, issue_id=str(issue["id"]))
    latest = detail["occurrence_history"][-1]
    assert latest["observation"]["exception_class"] == "owner-nonzero-exit"
    assert latest["observation"]["failure_stage"] == "unknown"
    assert latest["relevant_trace"] == []
    assert latest["safe_events"] == ["owner-nonzero-exit", "dispatcher-capture"]
    assert latest["output_excerpt"] == []
    private_text = (tmp_path / issue["detail_ref"]).read_text(encoding="utf-8")
    for forbidden in (
        "private paper text",
        "unsafe-value",
        "secret.py",
        str(tmp_path),
        "--secret",
    ):
        assert forbidden not in private_text


def test_developer_local_detail_emits_digest_bound_private_agent_action(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kb = _load_kb_cli()
    write_runtime_preferences(
        tmp_path,
        {
            "diagnostics": {
                "mode": "developer",
                "detail_level": "local-detailed",
                "token_budget_per_task": 128,
            }
        },
    )
    monkeypatch.setattr(
        kb.subprocess,
        "run",
        lambda *args, **kwargs: _child_result(
            29,
            stdout="private paper text token=unsafe-value",
            stderr=f'Traceback File "{tmp_path}/secret.py", line 7 user words',
        ),
    )

    assert kb.main(
        ["--root", str(tmp_path), "--agent-protocol", "failure.json", "status"]
    ) == 29

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "知识库状态暂时无法读取；详细诊断已保留给 Agent。\n"
    for forbidden in (
        "detail_digest",
        "detail_ref",
        "occurrence_history",
        "private paper text",
        "unsafe-value",
        "secret.py",
        str(tmp_path),
    ):
        assert forbidden not in captured.out + captured.err
    issue = list_diagnostic_issues(tmp_path, skill="knowledge-base-manager")[0]
    protocol = json.loads(
        (tmp_path / ".runtime" / "failure.json").read_text(encoding="utf-8")
    )
    assert protocol["next_actions"] == [
        {
            "action": "run_diagnostic_retrospective",
            "issue_id": issue["id"],
            "expected_detail_digest": issue["detail_digest"],
        }
    ]
    protocol_text = json.dumps(protocol, ensure_ascii=False)
    assert "detail_ref" not in protocol_text
    assert "occurrence_history" not in protocol_text


def test_noneligible_detail_states_emit_no_retrospective_action(
    monkeypatch,
    tmp_path: Path,
) -> None:
    for index, diagnostics in enumerate(
        (
            {"mode": "errors-only", "detail_level": "local-detailed"},
            {
                "mode": "developer",
                "detail_level": "local-detailed",
                "token_budget_per_task": 0,
            },
            {"mode": "developer", "detail_level": "redacted", "token_budget_per_task": 128},
        )
    ):
        root = tmp_path / f"case-{index}"
        kb = _load_kb_cli()
        write_runtime_preferences(root, {"diagnostics": diagnostics})
        monkeypatch.setattr(kb.subprocess, "run", lambda *args, **kwargs: _child_result(31))

        assert kb.main(
            ["--root", str(root), "--agent-protocol", "failure.json", "status"]
        ) == 31

        protocol = json.loads(
            (root / ".runtime" / "failure.json").read_text(encoding="utf-8")
        )
        assert protocol["next_actions"] == []


def test_plain_doctor_is_read_only_and_does_not_run_private_diagnostics(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb,
        "current_runtime_capabilities",
        lambda: {
            "yaml_support": True,
            "markdown_support": True,
            "pdf_backend": "pymupdf4llm",
            "modules": {"pymupdf4llm": True, "fitz": True},
        },
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("private diagnostics ran during ordinary doctor")

    monkeypatch.setattr(kb, "_diagnostics_policy", must_not_run)
    monkeypatch.setattr(kb, "_audit_workspace", must_not_run)

    assert kb.main(["--root", str(tmp_path), "doctor"]) == 0

    output = capsys.readouterr().out
    assert "研究能力包版本" in output
    assert "配置读写能力正常" in output
    assert "材料 Markdown 阅读层转换能力已就绪" in output
    assert "论文 PDF 深读能力已就绪" in output
    for forbidden in ("developer", "diagnostics", "audit", "/private/"):
        assert forbidden not in output
    assert not (tmp_path / "kb").exists()


def test_doctor_agent_protocol_contains_only_policy_and_mechanical_audit_summary(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb,
        "current_runtime_capabilities",
        lambda: {"yaml_support": True, "pdf_backend": "", "modules": {}},
    )
    monkeypatch.setattr(
        kb,
        "_diagnostics_policy",
        lambda root: {"effective_mode": "developer", "local_only": True, "secret": "/private/path"},
    )
    monkeypatch.setattr(
        kb,
        "_audit_workspace",
        lambda root: {
            "status": "WARN",
            "counts": {"total": 2, "warning": 2, "quality": 2, "unsafe": 99},
            "findings": [{"subject": "raw/private-paper.pdf", "message": "do not project me"}],
        },
    )

    assert kb.main(
        ["--root", str(tmp_path), "--agent-protocol", "doctor.json", "doctor"]
    ) == 0

    output = capsys.readouterr().out
    for forbidden in ("developer", "WARN", "quality", "private-paper", "/private/path"):
        assert forbidden not in output
    protocol_text = (tmp_path / ".runtime" / "doctor.json").read_text(encoding="utf-8")
    protocol = json.loads(protocol_text)
    assert protocol["details"]["diagnostics"] == {
        "audit": {
            "available": True,
            "counts": {"quality": 2, "total": 2, "warning": 2},
            "status": "WARN",
        },
        "local_only": True,
        "mode": "developer",
    }
    assert "private-paper" not in protocol_text
    assert "/private/path" not in protocol_text


def test_d1_keeps_exactly_sixteen_public_verbs() -> None:
    kb = _load_kb_cli()
    parser = kb.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, kb.argparse._SubParsersAction)
    )

    assert tuple(subparsers.choices) == PUBLIC_VERBS
    assert len(kb.VERB_REGISTRARS) == 16
    assert "diagnostics" not in subparsers.choices
    assert "lint" not in subparsers.choices


def test_d1_agent_rules_and_docs_keep_optional_diagnostics_honest() -> None:
    root = _project_root()
    agent_rules = (root / "runtime" / "AGENTS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    design = (root / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    schema = (root / "runtime" / "lib" / "research" / "SCHEMAS.md").read_text(
        encoding="utf-8"
    )
    decision = (
        root
        / "docs"
        / "decisions"
        / "0003-separate-diagnostic-capture-mode-from-local-detail.md"
    ).read_text(encoding="utf-8")
    assert "- Status: Accepted" in decision
    assert "- Status: Proposed" not in decision

    for mode in ("off", "errors-only", "developer"):
        assert mode in agent_rules
        assert mode in guide
        assert mode in design
    for phrase in (
        "开启开发者诊断",
        "仅在出错时记录",
        "关闭 unit-analyst 诊断",
        "检查知识库健康",
    ):
        assert phrase in agent_rules
        assert phrase in guide
    assert "local-only" in agent_rules
    assert "local-only" in readme
    assert "后台 telemetry" in guide
    assert "不增加 `lint` 或 `diagnostics` 入口" in guide
    assert "不存在新的 `kb lint` 或 `kb diagnostics`" in design
    assert "beta/scaffold" in readme
    assert "beta/scaffold" in changelog
    assert "never auto-edits a skill" in agent_rules
    assert "不能关闭 schema、evidence、confirmation" in guide
    for document in (agent_rules, guide, design, readme, changelog, schema, decision):
        assert "local-detailed" in document
        assert "redacted" in document
    assert "diagnostics.detail_level" in schema
    assert 'id="diagnostic-private-detail-yaml"' in schema
    assert "run_diagnostic_retrospective" in schema

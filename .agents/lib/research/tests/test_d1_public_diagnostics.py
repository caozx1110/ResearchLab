from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


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
    return Path(__file__).resolve().parents[4]


def _load_kb_cli():
    script = _project_root() / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
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
    ) -> dict[str, object] | None:
        payload = {
            "skill": skill,
            "operation": operation,
            "returncode": returncode,
            "public_summary": public_summary,
        }
        self.calls.append(payload)
        effective = self.skill_modes.get(skill, "inherit")
        effective = self.mode if effective == "inherit" else effective
        if effective == "off":
            return None

        issue_path = project_root / "kb" / "memory" / "skill-evolution" / "issues.yaml"
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
            "skill": "research-navigator",
            "operation": "status",
            "returncode": 17,
            "public_summary": "知识库操作未完成。",
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

    issue_path = tmp_path / "kb" / "memory" / "skill-evolution" / "issues.yaml"
    issues = json.loads(issue_path.read_text(encoding="utf-8"))["issues"]
    assert len(issues) == 1
    assert issues[0]["occurrences"] == 2
    assert len(capture.calls) == 2


def test_per_skill_off_overrides_developer_mode(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    capture = CaptureDependencyStub("developer", skill_modes={"research-navigator": "off"})
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
    protocol_text = (tmp_path / "kb" / ".runtime" / "failure.json").read_text(encoding="utf-8")
    protocol = json.loads(protocol_text)
    assert protocol["exit_code"] == 23
    assert protocol["details"]["diagnostic_events"] == [
        {
            "code": "runtime-failure-capture-failed",
            "operation": "status",
            "skill": "research-navigator",
        }
    ]
    assert "secret traceback" not in protocol_text
    assert "/absolute/private/path" not in protocol_text


def test_plain_doctor_is_read_only_and_does_not_run_private_diagnostics(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb,
        "current_runtime_capabilities",
        lambda: {"yaml_support": True, "pdf_backend": "pypdf", "modules": {}},
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("private diagnostics ran during ordinary doctor")

    monkeypatch.setattr(kb, "_diagnostics_policy", must_not_run)
    monkeypatch.setattr(kb, "_audit_workspace", must_not_run)

    assert kb.main(["--root", str(tmp_path), "doctor"]) == 0

    output = capsys.readouterr().out
    assert "研究能力包版本" in output
    assert "配置读写能力正常" in output
    assert "论文解析能力已就绪" in output
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
    protocol_text = (tmp_path / "kb" / ".runtime" / "doctor.json").read_text(encoding="utf-8")
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
    agent_rules = (root / ".agents" / "AGENTS.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    design = (root / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    for mode in ("off", "errors-only", "developer"):
        assert mode in agent_rules
        assert mode in guide
        assert mode in design
    for phrase in (
        "开启开发者诊断",
        "仅在出错时记录",
        "关闭 paper-analyst 诊断",
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

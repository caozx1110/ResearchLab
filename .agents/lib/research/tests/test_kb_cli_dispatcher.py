from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_kb_cli():
    root = _project_root()
    script = root / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    loader = importlib.machinery.SourceFileLoader("kb_cli_script_for_tests", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


class TTYStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


def _pending_record(unit_id: str, kind: str, title: str, summary: str = "AI summary") -> dict:
    return {
        "id": unit_id,
        "kind": kind,
        "title": title,
        "summary": summary,
        "confirmation_status": "pending_user_confirmation",
    }


def test_kb_help_snapshot_contains_group_headers() -> None:
    kb = _load_kb_cli()

    text = kb.render_help_menu()

    assert "# kb 快捷命令" in text
    for header in ["加材料", "检索", "idea", "实验", "报告", "确认", "状态", "记忆"]:
        assert f"## {header}" in text
    assert "kb init" in text
    assert "kb doctor" in text
    assert "也可以直接对 AI 说" in text


def test_kb_doctor_prints_runtime_capabilities(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb,
        "current_runtime_capabilities",
        lambda: {
            "python": "/usr/bin/python3",
            "version": "3.11.0",
            "modules": {"yaml": True, "PyPDF2": False, "pypdf": True},
            "yaml_support": True,
            "pdf_support": True,
            "pdf_backend": "pypdf",
        },
    )

    assert kb.main(["--root", str(tmp_path), "doctor"]) == 0

    captured = capsys.readouterr()
    assert "python: /usr/bin/python3" in captured.out
    assert "yaml: available" in captured.out
    assert "pdf: pypdf" in captured.out
    assert "module.PyPDF2: missing" in captured.out


def test_kb_init_forwards_workspace_and_config_inits_in_order(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(sys, "stdin", TTYStringIO("czx\nzh\nmilestone\ntrue\n"))
    monkeypatch.setattr(
        kb,
        "runtime_pref_defaults",
        lambda root: {"name": "", "lang": "zh", "auto_commit": "milestone", "auto_screen": "true"},
    )

    assert kb.main(["--root", str(tmp_path), "init"]) == 0

    assert calls == [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("init",)),
            (".agents/skills/research-config-manager/scripts/config.py", ("init",)),
        ],
        [
            (
                ".agents/skills/research-config-manager/scripts/config.py",
                ("set-runtime-pref", "--section", "identity", "--key", "default_confirmed_by", "--value", "czx"),
            ),
            (
                ".agents/skills/research-config-manager/scripts/config.py",
                ("set", "--key", "preferences.language_preference", "--value", "zh"),
            ),
            (
                ".agents/skills/research-config-manager/scripts/config.py",
                ("set-runtime-pref", "--section", "versioning", "--key", "auto_commit_mode", "--value", "milestone"),
            ),
            (
                ".agents/skills/research-config-manager/scripts/config.py",
                ("set-runtime-pref", "--section", "paper", "--key", "auto_screen_on_intake", "--value", "true"),
            ),
        ],
    ]


def test_kb_init_non_tty_degrades_to_inits_only(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(kb, "runtime_pref_defaults", lambda root: (_ for _ in ()).throw(AssertionError("should not prompt")))
    monkeypatch.setattr(sys, "stdin", io.StringIO("czx\nzh\nmilestone\ntrue\n"))

    assert kb.main(["init", "--non-interactive", "--root", str(tmp_path)]) == 0

    assert calls == [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("init",)),
            (".agents/skills/research-config-manager/scripts/config.py", ("init",)),
        ],
    ]


def test_kb_init_rejects_ai_signer_name_before_writing_prefs(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(sys, "stdin", TTYStringIO("codex\nczx\nen\nmanual\nfalse\n"))
    monkeypatch.setattr(
        kb,
        "runtime_pref_defaults",
        lambda root: {"name": "", "lang": "zh", "auto_commit": "milestone", "auto_screen": "true"},
    )

    assert kb.main(["--root", str(tmp_path), "init"]) == 0

    captured = capsys.readouterr()
    assert "not an AI tool name" in captured.out
    assert calls[-1] == [
        (
            ".agents/skills/research-config-manager/scripts/config.py",
            ("set-runtime-pref", "--section", "identity", "--key", "default_confirmed_by", "--value", "czx"),
        ),
        (
            ".agents/skills/research-config-manager/scripts/config.py",
            ("set", "--key", "preferences.language_preference", "--value", "en"),
        ),
        (
            ".agents/skills/research-config-manager/scripts/config.py",
            ("set-runtime-pref", "--section", "versioning", "--key", "auto_commit_mode", "--value", "manual"),
        ),
        (
            ".agents/skills/research-config-manager/scripts/config.py",
            ("set-runtime-pref", "--section", "paper", "--key", "auto_screen_on_intake", "--value", "false"),
        ),
    ]


def test_kb_status_forwards_current_state_and_program(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_forward(root: Path, relative_script: str, args: list[str]) -> kb.CommandResult:
        calls.append((relative_script, tuple(args)))
        return kb.CommandResult((relative_script, *args), 0)

    monkeypatch.setattr(kb, "forward_command", fake_forward)

    assert kb.main(["--root", str(tmp_path), "status", "p-demo"]) == 0

    assert calls == [
        (".agents/skills/research-navigator/scripts/navigate.py", ("current-state",)),
        (".agents/skills/research-orchestrator/scripts/orchestrate.py", ("status", "--program-id", "p-demo")),
    ]


def test_kb_status_stops_when_first_forward_fails(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_forward(root: Path, relative_script: str, args: list[str]) -> kb.CommandResult:
        calls.append((relative_script, tuple(args)))
        return kb.CommandResult((relative_script, *args), 17)

    monkeypatch.setattr(kb, "forward_command", fake_forward)

    assert kb.main(["--root", str(tmp_path), "status", "p-demo"]) == 17
    assert calls == [
        (".agents/skills/research-navigator/scripts/navigate.py", ("current-state",)),
    ]


def test_kb_next_forwards_to_orchestrator(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )

    assert kb.main(["--root", str(tmp_path), "next"]) == 0

    assert calls == [
        (".agents/skills/research-orchestrator/scripts/orchestrate.py", ("next",)),
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://arxiv.org/abs/2401.12345", "paper"),
        ("notes/My Paper.PDF", "paper"),
        ("https://github.com/org/repo", "repo"),
        ("git@github.com:org/repo.git", "repo"),
        ("https://example.com/post", "blog"),
    ],
)
def test_kb_add_infers_kind_table(source: str, expected: str) -> None:
    kb = _load_kb_cli()

    assert kb.infer_add_kind(source) == expected


def test_kb_add_forwards_inferred_kind(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )

    assert kb.main(["--root", str(tmp_path), "add", "https://github.com/org/repo"]) == 0

    assert calls == [
        (
            ".agents/skills/source-intake/scripts/intake.py",
            ("add", "--kind", "repo", "--source", "https://github.com/org/repo"),
        ),
    ]


def test_kb_add_allows_explicit_kind_override(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )

    assert kb.main(["--root", str(tmp_path), "add", "https://github.com/org/repo", "--kind", "paper"]) == 0

    assert calls == [
        (
            ".agents/skills/source-intake/scripts/intake.py",
            ("add", "--kind", "paper", "--source", "https://github.com/org/repo"),
        ),
    ]


def test_kb_review_interactive_batches_confirm_and_reject(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(
        kb,
        "load_review_records",
        lambda root, fuzzy: [
            _pending_record("p-one-123456", "paper", "One"),
            _pending_record("r-two-123456", "repo", "Two"),
            _pending_record("b-three-123456", "blog", "Three"),
            _pending_record("i-four-123456", "idea", "Four"),
        ],
    )
    monkeypatch.setattr(kb, "default_confirmed_by", lambda root: "czx-default")
    monkeypatch.setattr(sys, "stdin", TTYStringIO("y\nn\ns\nq\nkb/programs/p/decision-log.md\n"))

    assert kb.main(["--root", str(tmp_path), "review"]) == 0

    assert calls == [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("review-queue",)),
        ],
        [
            (
                ".agents/skills/knowledge-base-manager/scripts/kb.py",
                (
                    "confirm",
                    "--id",
                    "p-one-123456",
                    "--confirmed-by",
                    "czx-default",
                    "--evidence",
                    "kb/programs/p/decision-log.md",
                ),
            ),
            (
                ".agents/skills/knowledge-base-manager/scripts/kb.py",
                ("promote", "--id", "r-two-123456", "--confirmation-status", "rejected"),
            ),
        ],
    ]


def test_kb_review_empty_evidence_aborts_without_writes(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(kb, "load_review_records", lambda root, fuzzy: [_pending_record("p-one-123456", "paper", "One")])
    monkeypatch.setattr(kb, "default_confirmed_by", lambda root: "czx-default")
    monkeypatch.setattr(sys, "stdin", TTYStringIO("y\n\n"))

    assert kb.main(["--root", str(tmp_path), "review"]) == 1

    captured = capsys.readouterr()
    assert "[abort] evidence is required; no writes applied." in captured.out
    assert calls == [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("review-queue",)),
        ],
    ]


def test_kb_review_non_tty_degrades_to_list_only(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(kb, "load_review_records", lambda root, fuzzy: (_ for _ in ()).throw(AssertionError("should not prompt")))
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\nkb/programs/p/decision-log.md\n"))

    assert kb.main(["--root", str(tmp_path), "review"]) == 0

    assert calls == [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("review-queue",)),
        ],
    ]


def test_kb_find_forwards_joined_keywords(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )

    assert kb.main(["--root", str(tmp_path), "find", "policy", "gradient"]) == 0

    assert calls == [
        (".agents/skills/knowledge-base-manager/scripts/kb.py", ("query", "--query", "policy gradient")),
    ]


def test_kb_recall_forwards_default_and_explicit_kind(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )

    assert kb.main(["--root", str(tmp_path), "recall"]) == 0
    assert kb.main(["--root", str(tmp_path), "recall", "gotchas"]) == 0

    assert calls == [
        (".agents/skills/skill-evolution-advisor/scripts/learnings.py", ("recall", "--kind", "all")),
        (".agents/skills/skill-evolution-advisor/scripts/learnings.py", ("recall", "--kind", "gotchas")),
    ]


def test_kb_forward_command_prints_stderr_and_returns_nonzero(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 3, stdout="out\n", stderr="err\n")

    monkeypatch.setattr(kb.subprocess, "run", fake_run)

    result = kb.forward_command(tmp_path, ".agents/skills/fake/scripts/fake.py", ["demo"])

    captured = capsys.readouterr()
    assert result.returncode == 3
    assert "out\n" == captured.out
    assert "err\n" == captured.err


def test_kb_forward_command_uses_installed_script_when_target_root_has_no_agents(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    captured_argv: list[str] = []

    def fake_run(argv, **kwargs):
        captured_argv.extend(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(kb.subprocess, "run", fake_run)

    result = kb.forward_command(tmp_path, ".agents/skills/knowledge-base-manager/scripts/kb.py", ["init"])

    assert result.returncode == 0
    assert captured_argv[1] == str(kb.DEFAULT_PROJECT_ROOT / ".agents/skills/knowledge-base-manager/scripts/kb.py")
    assert captured_argv[2:] == ["--root", str(tmp_path), "init"]

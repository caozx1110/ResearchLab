from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
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
    for header in ["kb 动词（15 个）", "纯自然语言（无 kb 动词）"]:
        assert f"## {header}" in text
    for verb in ["kb help", "kb init", "kb doctor", "kb update", "kb status", "kb next", "kb find", "kb add", "kb ingest", "kb review", "kb reject", "kb recall", "kb resume", "kb undo", "kb restore"]:
        assert verb in text
    assert "请基于当前知识库给我 3 个候选 idea" in text
    assert "为这个 program 生成周报材料" in text
    assert "也可以直接对 AI 说" in text


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        *[[verb, "--help"] for verb in (
            "help",
            "init",
            "doctor",
            "update",
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
        )],
    ],
)
def test_every_argparse_help_surface_is_conversational(argv: list[str], capsys) -> None:
    kb = _load_kb_cli()

    with pytest.raises(SystemExit) as stopped:
        kb.main(argv)

    assert stopped.value.code == 0
    output = capsys.readouterr().out
    for forbidden in (
        "--",
        "<PROJECT_ROOT>",
        ".agents/",
        ".py",
        "${",
        "NEXT FOR AGENT",
        "confirm:",
        "TTY",
        "isatty",
    ):
        assert forbidden not in output


def test_argparse_errors_hide_internal_syntax(capsys) -> None:
    kb = _load_kb_cli()

    with pytest.raises(SystemExit) as stopped:
        kb.main(["review", "--root", "/tmp/internal"])

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "我没能理解这条 kb 请求。请使用 kb help 查看可用动词和示例。\n"


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

    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "doctor.json", "doctor"]) == 0

    captured = capsys.readouterr()
    assert "research skill 版本为 0.2.0-rc.1" in captured.out
    assert "YAML 支持正常" in captured.out
    assert "PDF 解析后端已就绪（pypdf）" in captured.out
    assert "/usr/bin/python3" not in captured.out
    protocol = json.loads((tmp_path / "kb" / ".runtime" / "doctor.json").read_text(encoding="utf-8"))
    assert protocol["details"]["runtime"]["python"] == "/usr/bin/python3"
    assert protocol["details"]["runtime"]["modules"]["PyPDF2"] is False


def test_kb_update_check_only_reports_available_without_user_facing_commands(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb.updater,
        "check",
        lambda _root, _cache: {"local": "0.1.0", "remote": "0.2.0", "status": "update_available"},
    )

    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "update.json", "update"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "当前 research skill 版本：0.1.0。" in lines
    assert "远端 research skill 版本：0.2.0。" in lines
    assert any("发现可用更新" in line for line in lines)
    for line in lines:
        assert not any(token in line for token in ("python3", ".py ", "--", "${", "git "))
    protocol = json.loads((tmp_path / "kb" / ".runtime" / "update.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "needs_user_authorization"
    assert protocol["next_actions"] == [
        {"action": "request_update_authorization", "then": {"apply": True, "verb": "update"}}
    ]


def test_kb_update_apply_uses_agent_confirmed_path(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[Path, Path]] = []

    def fake_apply(root: Path, cache_dir: Path):
        calls.append((root, cache_dir))
        return {"before": "0.1.0", "after": "0.2.0", "status": "updated"}

    monkeypatch.setattr(kb.updater, "apply", fake_apply)

    assert kb.main(["--root", str(tmp_path), "update", "--apply"]) == 0

    assert calls == [(tmp_path, kb.update_cache_dir())]
    assert "research skill 更新完成：0.1.0 → 0.2.0。" in capsys.readouterr().out


def test_kb_update_apply_reports_up_to_date_conversationally(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb.updater,
        "apply",
        lambda _root, _cache: {"before": "0.2.0", "after": "0.2.0", "status": "up_to_date"},
    )

    assert kb.main(["--root", str(tmp_path), "update", "--apply"]) == 0

    output = capsys.readouterr().out
    assert output == "当前 research skill 已是最新版本，无需更新。\n"
    assert not any(token in output for token in ("python3", ".py ", "--", "${", "git ", ".agents/"))


def test_kb_update_offline_reports_unknown_without_changes(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(
        kb.updater,
        "check",
        lambda _root, _cache: {"local": "0.1.0", "remote": "unknown", "status": "unknown"},
    )

    assert kb.main(["--root", str(tmp_path), "update"]) == 0

    output = capsys.readouterr().out
    assert "当前 research skill 版本：0.1.0。" in output
    assert "远端 research skill 版本：未知。" in output
    assert "当前安装未做任何改动" in output
    assert "NEXT FOR AGENT:" not in output


def test_kb_init_has_identical_no_tty_semantics_and_never_reads_input(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("must not prompt")))
    monkeypatch.setattr(
        kb,
        "runtime_pref_defaults",
        lambda root: {"name": "", "lang": "zh", "auto_commit": "milestone", "auto_screen": "true"},
    )

    monkeypatch.setattr(sys, "stdin", TTYStringIO("ignored\n"))
    assert kb.main(["--root", str(tmp_path), "init"]) == 0
    tty_output = capsys.readouterr().out
    calls_after_tty = list(calls)
    calls.clear()
    monkeypatch.setattr(sys, "stdin", io.StringIO("ignored\n"))
    assert kb.main(["--root", str(tmp_path), "init"]) == 0
    pipe_output = capsys.readouterr().out

    expected = [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("init",)),
            (".agents/skills/research-config-manager/scripts/config.py", ("init",)),
        ],
    ]
    assert calls_after_tty == expected
    assert calls == expected
    assert tty_output == pipe_output
    assert "还需要你告诉我确认人姓名" in tty_output
    assert "NEXT FOR AGENT:" not in tty_output


def test_kb_init_non_tty_scaffolds_and_guides_agent(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(
        kb,
        "runtime_pref_defaults",
        lambda root: {"name": "", "lang": "zh", "auto_commit": "milestone", "auto_screen": "true"},
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not prompt")))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert kb.main(["--agent-protocol", "init.json", "init", "--non-interactive", "--root", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "还需要你告诉我确认人姓名" in captured.out
    assert "NEXT FOR AGENT:" not in captured.out
    assert "--" not in captured.out
    protocol = json.loads((tmp_path / "kb" / ".runtime" / "init.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "needs_user_input"
    assert protocol["next_actions"][0]["required_fields"] == ["human_name"]
    assert calls == [
        [
            (".agents/skills/knowledge-base-manager/scripts/kb.py", ("init",)),
            (".agents/skills/research-config-manager/scripts/config.py", ("init",)),
        ],
    ]


def test_kb_init_headless_flags_persist_user_profile(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "init",
            "--name",
            "Researcher",
            "--lang",
            "zh",
            "--persona-focus",
            "robot learning and VLA",
        ]
    ) == 0

    profile = kb.load_yaml(tmp_path / "kb" / "config" / "user-profile.yaml", {})
    assert profile["preferences"]["language_preference"] == "zh"
    assert profile["personalization"]["research_focus"] == "robot learning and VLA"


def test_kb_init_rejects_ai_signer_name_before_writing_prefs(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    with pytest.raises(SystemExit, match="不能使用 AI 工具名称"):
        kb.main(["--root", str(tmp_path), "init", "--name", "codex"])
    assert calls == []


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


def test_kb_recovery_verbs_forward_without_raw_git_commands(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_forward(root: Path, relative_script: str, args: list[str]) -> kb.CommandResult:
        calls.append((relative_script, tuple(args)))
        return kb.CommandResult((relative_script, *args), 0)

    monkeypatch.setattr(kb, "forward_command", fake_forward)

    assert kb.main(["--root", str(tmp_path), "resume"]) == 0
    assert kb.main(["--root", str(tmp_path), "undo"]) == 0
    assert kb.main(["--root", str(tmp_path), "restore", "op-123"]) == 0
    assert calls == [
        (".agents/skills/knowledge-base-manager/scripts/kb.py", ("resume",)),
        (".agents/skills/knowledge-base-manager/scripts/kb.py", ("undo",)),
        (".agents/skills/knowledge-base-manager/scripts/kb.py", ("restore", "op-123")),
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


def test_kb_next_forwards_program_filter(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )

    assert kb.main(["--root", str(tmp_path), "next", "p-demo"]) == 0

    assert calls == [
        (".agents/skills/research-orchestrator/scripts/orchestrate.py", ("next", "--program-id", "p-demo")),
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


def test_kb_infers_local_directory_as_repo_not_blog(tmp_path: Path) -> None:
    """F1: a local checkout dir is a repo, never the blog fallback."""
    kb = _load_kb_cli()
    repo_dir = tmp_path / "langwbc-repo"
    (repo_dir / "src").mkdir(parents=True)
    (repo_dir / "README.md").write_text("# LangWBC\n", encoding="utf-8")
    (repo_dir / "src" / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")

    # absolute path
    assert kb.infer_add_kind(str(repo_dir)) == "repo"
    # relative path resolved against the project root
    assert kb.infer_add_kind("langwbc-repo", tmp_path) == "repo"
    # a .git bare marker / git url still maps to repo
    assert kb.infer_add_kind("git@github.com:org/repo.git") == "repo"
    assert kb.infer_add_kind("https://gitlab.com/org/repo") == "repo"


def test_kb_infers_local_non_pdf_file_as_blog_and_pdf_as_paper(tmp_path: Path) -> None:
    """F1 guard: local *file* still discriminates pdf(paper) vs other(blog); dir stays repo."""
    kb = _load_kb_cli()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    html = tmp_path / "post.html"
    html.write_text("<html></html>", encoding="utf-8")

    assert kb.infer_add_kind(str(pdf)) == "paper"
    assert kb.infer_add_kind(str(html)) == "blog"


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


def _capture_forward(kb, monkeypatch) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        kb,
        "forward_command",
        lambda root, relative_script, args: calls.append((relative_script, tuple(args)))
        or kb.CommandResult((relative_script, *args), 0),
    )
    return calls


def test_kb_reject_forwards_to_promote_rejected(monkeypatch, tmp_path: Path) -> None:
    """F1: `kb reject <id>` reuses knowledge-base-manager promote --confirmation-status rejected."""
    kb = _load_kb_cli()
    calls = _capture_forward(kb, monkeypatch)

    assert kb.main(["--root", str(tmp_path), "reject", "b-langwbc-repo-78d111a4", "--reason", "mis-created"]) == 0

    assert calls == [
        (
            ".agents/skills/knowledge-base-manager/scripts/kb.py",
            ("promote", "--id", "b-langwbc-repo-78d111a4", "--confirmation-status", "rejected", "--evidence", "mis-created"),
        ),
    ]


def test_kb_reject_without_reason_omits_evidence(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls = _capture_forward(kb, monkeypatch)

    assert kb.main(["--root", str(tmp_path), "reject", "b-x-1"]) == 0

    assert calls == [
        (
            ".agents/skills/knowledge-base-manager/scripts/kb.py",
            ("promote", "--id", "b-x-1", "--confirmation-status", "rejected"),
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


def test_kb_review_tty_and_pipe_are_identical_and_emit_private_protocol(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_forward(root: Path, script: str, args, **_kwargs):
        calls.append((script, tuple(args)))
        return kb.CommandResult((script, *args), 0, "# review queue\n")

    monkeypatch.setattr(kb, "forward_command", fake_forward)
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
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("must not prompt")))
    monkeypatch.setattr(sys, "stdin", TTYStringIO("ignored\n"))

    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "tty-review.json", "review"]) == 0
    tty_output = capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO("ignored\n"))
    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "pipe-review.json", "review"]) == 0
    pipe_output = capsys.readouterr().out

    assert calls == [
        (".agents/skills/knowledge-base-manager/scripts/kb.py", ("review-queue",)),
        (".agents/skills/knowledge-base-manager/scripts/kb.py", ("review-queue",)),
    ]
    assert tty_output == pipe_output
    assert "需要你用自然语言确认或拒绝" in tty_output
    for name in ("tty-review.json", "pipe-review.json"):
        protocol = json.loads((tmp_path / "kb" / ".runtime" / name).read_text(encoding="utf-8"))
        assert protocol["status"] == "needs_user_authorization"
        assert protocol["next_actions"][0]["decision_fields"] == [
            "decision",
            "user_authorization",
            "authorization_source",
            "evidence",
        ]


def test_kb_review_apply_builder_transmits_user_authorization(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    monkeypatch.setattr(kb, "default_confirmed_by", lambda root: "czx-default")
    commands = kb.build_review_apply_commands(
        tmp_path,
        ["p-one-123456"],
        [],
        "evidence-note",
        user_authorization="I confirm p-one-123456",
    )
    assert commands == [
        (
            ".agents/skills/knowledge-base-manager/scripts/kb.py",
            [
                "confirm",
                "--id",
                "p-one-123456",
                "--confirmed-by",
                "czx-default",
                "--evidence",
                "evidence-note",
                "--user-authorization",
                "I confirm p-one-123456",
                "--authorization-source",
                "user_message",
            ],
        )
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


# --------------------------------------------------------------------------- #
# kb ingest: chain intake -> prepare, STOP at prepare, never auto-verify.       #
# --------------------------------------------------------------------------- #

FULL_SCOPE = {"screen", "generate-note", "build-index", "refresh"}

_PAPER_ADD_STDOUT = (
    "[ok] created kb/units/papers/p-demo-abcd1234/record.yaml\n"
    "[source] parse-cache: kb/units/papers/p-demo-abcd1234/parse-cache.yaml (2 chunks)\n"
    "NEXT FOR AGENT: intake done for p-demo-abcd1234; kb ingest auto-continues to paper prepare\n"
)
_PAPER_PREPARE_STDOUT = (
    "[ok] wrote kb/units/papers/p-demo-abcd1234/note-fill.yaml\n"
    "下一步：runtime agent 为 5 要素填内容+证据。\n"
    "NEXT FOR AGENT: read kb/units/papers/p-demo-abcd1234/parse-cache.yaml (source quotes) then fill "
    "kb/units/papers/p-demo-abcd1234/note-fill.yaml elements [motivation,method,experiment,limitation,insight] "
    "— each needs content + >=1 verbatim quote+locator (PDF page=N / HTML section:<anchor>), then run: "
    "${RESEARCH_PYTHON:-python3} paper.py --root R complete-note --paper-id p-demo-abcd1234 --phase verify --input note-fill.yaml\n"
)


def _fake_ingest_forwarder(kb, recorder: list[dict]):
    def fake(root, relative_script, args, *, stream=True, extra_env=None):
        recorder.append(
            {
                "script": relative_script,
                "args": tuple(args),
                "stream": stream,
                "extra_env": dict(extra_env or {}),
            }
        )
        if relative_script.endswith("intake.py"):
            return kb.CommandResult((relative_script, *args), 0, _PAPER_ADD_STDOUT)
        return kb.CommandResult((relative_script, *args), 0, _PAPER_PREPARE_STDOUT)

    return fake


def test_kb_ingest_chains_intake_then_prepare_and_stops_before_verify(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[dict] = []
    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: set(FULL_SCOPE))
    monkeypatch.setattr(kb, "forward_command", _fake_ingest_forwarder(kb, calls))

    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "ingest.json", "ingest", "notes/demo.pdf"]) == 0

    # Exactly two scriptable steps ran: intake add, then analyzer prepare. No verify.
    assert [c["script"] for c in calls] == [
        ".agents/skills/source-intake/scripts/intake.py",
        ".agents/skills/paper-analyst/scripts/paper.py",
    ]
    assert calls[0]["args"] == ("add", "--kind", "paper", "--source", "notes/demo.pdf")
    assert calls[0]["extra_env"] == {"RESEARCH_INGEST_CHAIN": "1"}
    assert calls[1]["args"] == ("complete-note", "--paper-id", "p-demo-abcd1234", "--phase", "prepare")
    for call in calls:
        assert "verify" not in call["args"]

    out = capsys.readouterr().out
    assert "已入库并备好深读骨架" in out
    for forbidden in ("NEXT FOR AGENT:", "parse-cache.yaml", "--phase", ".py", "${"):
        assert forbidden not in out
    protocol = json.loads((tmp_path / "kb" / ".runtime" / "ingest.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "agent_action_required"
    action = protocol["next_actions"][0]
    assert action["unit_id"] == "p-demo-abcd1234"
    assert action["steps"][1]["arguments"][-2:] == ["--phase", "verify"]
    assert "parse-cache.yaml" in action["prepare_output"]


def test_kb_ingest_narrowed_scope_without_generate_note_runs_only_intake(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[dict] = []
    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: {"screen"})
    monkeypatch.setattr(kb, "forward_command", _fake_ingest_forwarder(kb, calls))

    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "paused.json", "ingest", "notes/demo.pdf"]) == 0

    # intake ran; prepare did NOT (narrowed autonomy).
    assert [c["script"] for c in calls] == [".agents/skills/source-intake/scripts/intake.py"]
    out = capsys.readouterr().out
    assert "自动化偏好暂停了深读准备" in out
    assert "--" not in out and "NEXT FOR AGENT:" not in out
    protocol = json.loads((tmp_path / "kb" / ".runtime" / "paused.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "paused_by_autonomy"
    assert protocol["next_actions"][0]["arguments"][-2:] == ["--phase", "prepare"]


def test_kb_ingest_narrowed_scope_without_screen_runs_nothing(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[dict] = []
    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: set())
    monkeypatch.setattr(kb, "forward_command", _fake_ingest_forwarder(kb, calls))

    assert kb.main(["--root", str(tmp_path), "--agent-protocol", "paused.json", "ingest", "notes/demo.pdf"]) == 0

    assert calls == []
    out = capsys.readouterr().out
    assert "自动化偏好暂停了这次入库" in out
    assert "--" not in out and "NEXT FOR AGENT:" not in out
    protocol = json.loads((tmp_path / "kb" / ".runtime" / "paused.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "paused_by_autonomy"


def test_kb_ingest_duplicate_stops_before_prepare(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[dict] = []

    def fake(root, relative_script, args, *, stream=True, extra_env=None):
        calls.append(relative_script)
        return kb.CommandResult((relative_script, *args), 0, "[ok] duplicate detected: p-demo-abcd1234\n")

    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: set(FULL_SCOPE))
    monkeypatch.setattr(kb, "forward_command", fake)

    assert kb.main(["--root", str(tmp_path), "ingest", "notes/demo.pdf"]) == 0

    assert calls == [".agents/skills/source-intake/scripts/intake.py"]
    out = capsys.readouterr().out
    assert "知识条目 p-demo-abcd1234 已存在" in out
    assert "没有重新生成骨架" in out


def test_kb_ingest_unit_id_extraction_variants() -> None:
    kb = _load_kb_cli()
    assert kb._extract_ingest_unit_id("[ok] created kb/units/repos/r-x-1234/record.yaml") == ("r-x-1234", "created")
    assert kb._extract_ingest_unit_id("[ok] duplicate detected: b-y-5678") == ("b-y-5678", "duplicate")
    assert kb._extract_ingest_unit_id("nothing useful here") == ("", "unknown")


def test_kb_ingest_effective_scope_is_capped_by_governance(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    # Even if a user lists a non-governed step, the intersection drops it.
    monkeypatch.setattr(
        kb,
        "load_runtime_preferences",
        lambda root: {"autonomy": {"auto_execute_scope": ["screen", "generate-note", "verify", "confirm", "deploy"]}},
    )
    scope = kb.effective_ingest_scope(tmp_path)
    assert scope == {"screen", "generate-note"}
    assert "verify" not in scope and "confirm" not in scope


def test_kb_ingest_prepare_failure_propagates_returncode(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()

    def fake(root, relative_script, args, *, stream=True, extra_env=None):
        if relative_script.endswith("intake.py"):
            return kb.CommandResult((relative_script, *args), 0, _PAPER_ADD_STDOUT)
        return kb.CommandResult((relative_script, *args), 5, "[reject] boom\n")

    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: set(FULL_SCOPE))
    monkeypatch.setattr(kb, "forward_command", fake)

    assert kb.main(["--root", str(tmp_path), "ingest", "notes/demo.pdf"]) == 5
    out = capsys.readouterr().out
    assert "[reject] boom" in out
    assert "NEXT FOR AGENT:" not in out

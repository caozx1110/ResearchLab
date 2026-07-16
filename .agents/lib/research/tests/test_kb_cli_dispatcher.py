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
    for header in ["kb 动词（13 个）", "纯自然语言（无 kb 动词）"]:
        assert f"## {header}" in text
    for verb in ["kb help", "kb init", "kb doctor", "kb status", "kb next", "kb find", "kb add", "kb ingest", "kb review", "kb reject", "kb recall", "kb undo", "kb restore"]:
        assert verb in text
    assert "请基于当前知识库给我 3 个候选 idea" in text
    assert "为这个 program 生成周报材料" in text
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


def test_kb_init_non_tty_scaffolds_and_guides_agent(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[list[tuple[str, tuple[str, ...]]]] = []

    def fake_run_forwarded(root: Path, commands):
        calls.append([(script, tuple(args)) for script, args in commands])
        return 0

    monkeypatch.setattr(kb, "run_forwarded", fake_run_forwarded)
    monkeypatch.setattr(kb, "runtime_pref_defaults", lambda root: (_ for _ in ()).throw(AssertionError("should not prompt")))
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not prompt")))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert kb.main(["init", "--non-interactive", "--root", str(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert "NEXT FOR AGENT:" in captured.out
    for flag in [
        "--name",
        "--lang",
        "--auto-commit",
        "--auto-screen",
        "--persona-focus",
        "--persona-resources",
        "--persona-report",
        "--persona-boundaries",
        "--persona-term",
    ]:
        assert flag in captured.out
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


def test_kb_recovery_verbs_forward_without_raw_git_commands(monkeypatch, tmp_path: Path) -> None:
    kb = _load_kb_cli()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_forward(root: Path, relative_script: str, args: list[str]) -> kb.CommandResult:
        calls.append((relative_script, tuple(args)))
        return kb.CommandResult((relative_script, *args), 0)

    monkeypatch.setattr(kb, "forward_command", fake_forward)

    assert kb.main(["--root", str(tmp_path), "undo"]) == 0
    assert kb.main(["--root", str(tmp_path), "restore", "op-123"]) == 0
    assert calls == [
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


def test_ingest_chain_guidance_paper_surfaces_full_chain(tmp_path: Path) -> None:
    """A: kb ingest guidance lists the WHOLE post-verify chain, incl. the screening second-fill."""
    kb = _load_kb_cli()
    text = "\n".join(
        kb._ingest_chain_guidance(tmp_path, "paper", "p-demo-123456", {"screen", "refresh", "generate-note", "build-index"})
    )
    # remaining safe auto-steps after note verify
    assert "extract-figures --paper-id p-demo-123456" in text
    assert "refresh-structure --paper-id p-demo-123456" in text
    # the screening SECOND-fill that ingest previously omitted (screen --phase verify)
    assert "screening SECOND-fill" in text
    assert "screen --paper-id p-demo-123456 --phase verify" in text
    assert "screening.yaml" in text
    # confirm gate, never self-signed; verify never auto-run
    assert "confirm gate" in text and "never self-signed" in text
    assert "never auto-run" in text


def test_ingest_chain_guidance_honors_autonomy_valve(tmp_path: Path) -> None:
    kb = _load_kb_cli()
    with_refresh = "\n".join(kb._ingest_chain_guidance(tmp_path, "paper", "p-x-1", {"screen", "refresh", "generate-note"}))
    without_refresh = "\n".join(kb._ingest_chain_guidance(tmp_path, "paper", "p-x-1", {"screen", "generate-note"}))

    assert "'refresh' is in your auto_execute_scope" in with_refresh
    assert "[safe auto] extract-figures + refresh-structure" in with_refresh
    # gated out: relabel + drop the safe-auto segment from the chain summary,
    # but still show the commands (labeled run-only-if-you-choose).
    assert "OUTSIDE your auto_execute_scope" in without_refresh
    assert "[safe auto] extract-figures + refresh-structure" not in without_refresh
    assert "extract-figures --paper-id p-x-1" in without_refresh


def test_ingest_chain_guidance_confirm_gate_uses_shared_helper(tmp_path: Path) -> None:
    kb = _load_kb_cli()
    text = "\n".join(kb._ingest_chain_guidance(tmp_path, "paper", "p-x-1", {"refresh"}))
    assert kb.confirm_command({"id": "p-x-1", "kind": "paper"}) in text


def test_ingest_chain_guidance_repo_and_blog_have_no_screening_or_figures(tmp_path: Path) -> None:
    kb = _load_kb_cli()
    repo = "\n".join(kb._ingest_chain_guidance(tmp_path, "repo", "r-x-1", {"refresh"}))
    blog = "\n".join(kb._ingest_chain_guidance(tmp_path, "blog", "b-x-1", {"refresh"}))

    assert "map-capability --phase verify" in repo
    assert "screening" not in repo and "extract-figures" not in repo
    assert kb.confirm_command({"id": "r-x-1", "kind": "repo"}) in repo

    assert "complete-note --phase verify" in blog
    assert "screening" not in blog and "extract-figures" not in blog
    assert kb.confirm_command({"id": "b-x-1", "kind": "blog"}) in blog


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

    assert kb.main(["--root", str(tmp_path), "ingest", "notes/demo.pdf"]) == 0

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
    assert "stopped before verify" in out
    # Aggregated NEXT FOR AGENT line carries parse-cache path + elements + verify command.
    assert "NEXT FOR AGENT: read kb/units/papers/p-demo-abcd1234/parse-cache.yaml" in out
    assert "[motivation,method,experiment,limitation,insight]" in out
    assert "--phase verify" in out


def test_kb_ingest_narrowed_scope_without_generate_note_runs_only_intake(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[dict] = []
    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: {"screen"})
    monkeypatch.setattr(kb, "forward_command", _fake_ingest_forwarder(kb, calls))

    assert kb.main(["--root", str(tmp_path), "ingest", "notes/demo.pdf"]) == 0

    # intake ran; prepare did NOT (narrowed autonomy).
    assert [c["script"] for c in calls] == [".agents/skills/source-intake/scripts/intake.py"]
    out = capsys.readouterr().out
    assert "prepare is outside the autonomy auto-execute scope" in out
    assert "NEXT FOR AGENT: when ready, run prepare yourself" in out
    assert "complete-note --paper-id p-demo-abcd1234 --phase prepare" in out


def test_kb_ingest_narrowed_scope_without_screen_runs_nothing(monkeypatch, tmp_path: Path, capsys) -> None:
    kb = _load_kb_cli()
    calls: list[dict] = []
    monkeypatch.setattr(kb, "effective_ingest_scope", lambda root: set())
    monkeypatch.setattr(kb, "forward_command", _fake_ingest_forwarder(kb, calls))

    assert kb.main(["--root", str(tmp_path), "ingest", "notes/demo.pdf"]) == 0

    assert calls == []
    out = capsys.readouterr().out
    assert "intake is outside the autonomy auto-execute scope" in out
    assert "run intake yourself" in out


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
    assert "duplicate detected (p-demo-abcd1234)" in out
    assert "stopping before prepare" in out


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
    assert "prepare failed for p-demo-abcd1234" in out

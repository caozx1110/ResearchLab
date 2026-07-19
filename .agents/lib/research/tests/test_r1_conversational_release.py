from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


PUBLIC_VERBS = (
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
)

FORBIDDEN_PUBLIC_TOKENS = (
    "--root",
    "--kind",
    "<PROJECT_ROOT>",
    ".agents/",
    ".py",
    "${",
    "NEXT FOR AGENT",
    "confirm:",
    "TTY",
    "isatty",
)

EXPECTED_RUNTIME_PINS = {
    "pyyaml": "6.0.3",
    "pymupdf4llm": "0.0.27",
    "pymupdf": "1.26.5",
}
EXPECTED_DEV_PINS = {"pytest": "8.4.2"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _kb_script(root: Path | None = None) -> Path:
    return (root or _project_root()) / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"


def _load_kb_cli():
    script = _kb_script()
    loader = importlib.machinery.SourceFileLoader("kb_cli_release_gate", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _safe_runtime_env() -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }


def _active_requirement_lines(path: Path) -> tuple[str, ...]:
    return tuple(
        stripped
        for line in path.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


def _parse_exact_pins(lines: tuple[str, ...]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in lines:
        if line.startswith(("-r ", "--requirement ")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9][A-Za-z0-9_.+-]*)", line)
        assert match, f"requirement is not an exact pin: {line}"
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        assert name not in pins, f"duplicate requirement pin: {name}"
        pins[name] = match.group(2)
    return pins


def test_public_verb_registry_and_docs_match_exactly() -> None:
    kb = _load_kb_cli()
    parser = kb.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, kb.argparse._SubParsersAction)
    )

    assert tuple(subparsers.choices) == PUBLIC_VERBS
    assert len(kb.VERB_REGISTRARS) == len(PUBLIC_VERBS)
    for relative in ("README.md", "docs/USER_GUIDE.md"):
        text = (_project_root() / relative).read_text(encoding="utf-8")
        for verb in PUBLIC_VERBS:
            assert f"`kb {verb}" in text, f"{relative} does not document kb {verb}"


def test_static_human_print_literals_and_input_model_are_safe() -> None:
    source = _kb_script().read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "input(" not in source
    assert ".isatty(" not in source
    assert "_ingest_chain_guidance" not in source
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
            continue
        literal = "".join(
            str(child.value)
            for argument in node.args
            for child in ast.walk(argument)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        )
        for token in FORBIDDEN_PUBLIC_TOKENS:
            assert token not in literal
        assert not re.search(r"(^|\s)--[A-Za-z]", literal)


@pytest.mark.parametrize("argv", [["--help"], *[[verb, "--help"] for verb in PUBLIC_VERBS]])
def test_all_blackbox_help_surfaces_hide_internal_syntax(argv: list[str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-B", str(_kb_script()), *argv],
        cwd=_project_root(),
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout + completed.stderr
    for token in FORBIDDEN_PUBLIC_TOKENS:
        assert token not in output


def test_blackbox_parse_error_is_conversational() -> None:
    completed = subprocess.run(
        [sys.executable, "-B", str(_kb_script()), "review", "--root", "/tmp/internal"],
        cwd=_project_root(),
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == "我没能理解这条 kb 请求。请使用 kb help 查看可用动词和示例。\n"


def test_read_only_help_creates_no_kb_or_agent_protocol(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-B", str(_kb_script()), "--root", str(tmp_path), "help"],
        cwd=_project_root(),
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "kb 动词（15 个）" in completed.stdout
    assert not (tmp_path / "kb").exists()
    for token in FORBIDDEN_PUBLIC_TOKENS:
        assert token not in completed.stdout


def test_kb_status_is_byte_identical_for_every_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user = workspace / "kb" / "user"
    reading = user / "reading-lists"
    reading.mkdir(parents=True)
    (user / "current-state.md").write_text("stale current state\n", encoding="utf-8")
    (user / "navigation.md").write_text("existing navigation\n", encoding="utf-8")
    (reading / "current-reading.md").write_text("existing reading list\n", encoding="utf-8")
    (workspace / "kb" / "sentinel.bin").write_bytes(b"\x00private\xff")
    before = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    completed = subprocess.run(
        [sys.executable, "-B", str(_kb_script()), "--root", str(workspace), "status"],
        cwd=_project_root(),
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    after = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert completed.returncode == 0, completed.stderr
    assert "# Current State" in completed.stdout
    assert before == after


def test_installed_copy_runs_help_without_creating_runtime_data(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "install",
            "--project",
            str(workspace),
            "--yes",
            "--codex",
        ],
        cwd=_project_root(),
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    help_result = subprocess.run(
        [sys.executable, "-B", str(_kb_script(workspace)), "help"],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "kb 动词（15 个）" in help_result.stdout
    assert not (workspace / "kb").exists()
    installed_rules = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Conversational contract" in installed_rules
    assert "## Editing Rules" not in installed_rules


def test_release_metadata_is_honest_rc_and_ci_is_cross_platform() -> None:
    root = _project_root()
    version = (root / ".agents" / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+-rc\.\d+", version)

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    assert version in changelog
    assert "not a stable release" in changelog

    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    assert "private vulnerability reporting" in security
    assert "/security/advisories/new" in security

    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in ci
    assert "macos-latest" in ci
    assert "test_r1_conversational_release.py" in ci


def test_runtime_and_test_dependencies_are_exactly_locked_in_both_ci_jobs() -> None:
    root = _project_root()
    runtime_lines = _active_requirement_lines(root / "requirements.txt")
    dev_lines = _active_requirement_lines(root / "requirements-dev.txt")

    assert _parse_exact_pins(runtime_lines) == EXPECTED_RUNTIME_PINS
    assert dev_lines == ("-r requirements.txt", "pytest==8.4.2")
    assert _parse_exact_pins(dev_lines) == EXPECTED_DEV_PINS

    ci = yaml.safe_load((root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for job_name in ("test", "macos-release-gate"):
        install_steps = [
            step
            for step in ci["jobs"][job_name]["steps"]
            if step.get("name") == "Install dependencies"
        ]
        assert install_steps == [
            {
                "name": "Install dependencies",
                "run": "python -m pip install -r requirements-dev.txt",
            }
        ]

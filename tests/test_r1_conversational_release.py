from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT, source_path

import pytest
import yaml


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
    "rejected",
)

EXPECTED_RUNTIME_PINS = {
    "pyyaml": "6.0.3",
    "pymupdf4llm": "0.0.27",
    "pymupdf": "1.26.5",
    "markdownify": "1.2.3",
    "beautifulsoup4": "4.15.0",
    "soupsieve": "2.8.4",
    "six": "1.17.0",
    "typing-extensions": "4.16.0",
}
CAPABILITY_MATURITY = {
    "kb-cli": "stable",
    "knowledge-base-manager": "stable",
    "source-intake": "beta",
    "literature-search": "beta",
    "research-monitor": "beta",
    "unit-analyst": "beta",
    "research-config-manager": "beta",
    "discussion-archivist": "beta",
    "research-orchestrator": "beta",
    "literature-synthesizer": "beta",
    "idea-workbench": "beta",
    "method-designer": "beta",
    "experiment-workbench": "beta",
    "report-author": "beta",
    "skill-evolution-advisor": "scaffold",
}


def _project_root() -> Path:
    return REPO_ROOT


def _kb_script(root: Path | None = None) -> Path:
    if root is None:
        return _project_root() / "skills" / "kb-cli" / "scripts" / "kb"
    return root / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"


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


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    if not root.exists() and not root.is_symlink():
        return ()
    entries: list[tuple[str, str, bytes]] = []
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path).encode()))
        elif path.is_dir():
            entries.append((relative, "directory", b""))
        elif path.is_file():
            entries.append((relative, "file", path.read_bytes()))
        else:
            entries.append((relative, "other", b""))
    return tuple(entries)


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
        text = source_path(relative).read_text(encoding="utf-8")
        for verb in PUBLIC_VERBS:
            assert f"`kb {verb}" in text, f"{relative} does not document kb {verb}"


def test_docs_disclose_every_skill_maturity_without_bundle_overclaim() -> None:
    for relative in ("README.md", "docs/USER_GUIDE.md"):
        text = source_path(relative).read_text(encoding="utf-8")
        for label in ("stable", "beta", "scaffold", "dev-only"):
            assert label in text, f"{relative} does not define {label}"
        for skill, maturity in CAPABILITY_MATURITY.items():
            row = rf"\|\s*`{re.escape(skill)}`\s*\|\s*{maturity}\s*\|"
            assert re.search(row, text), f"{relative} does not mark {skill} as {maturity}"
        assert "whole bundle" in text or "整个 bundle" in text
        assert "paper" in text and "repo" in text and "dataset" in text and "blog" in text


def test_user_guide_does_not_expose_raw_execution_or_internal_paths() -> None:
    guide = (_project_root() / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    for token in ("python3 ", ".agents/", "kb/", ".py ", "${", "NEXT FOR AGENT"):
        assert token not in guide
    assert not re.search(r"(^|\s)--[A-Za-z]", guide)


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


def test_dynamic_public_prints_do_not_read_raw_external_fields_directly() -> None:
    source = _kb_script().read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations: list[str] = []

    def expression_root(node: ast.AST) -> str:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node.id if isinstance(node, ast.Name) else ""

    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            continue
        for argument in call.args:
            if not isinstance(argument, ast.JoinedStr):
                continue
            for formatted in (node for node in ast.walk(argument) if isinstance(node, ast.FormattedValue)):
                expression = formatted.value
                for descendant in ast.walk(expression):
                    if isinstance(descendant, ast.Attribute) and expression_root(descendant) in {
                        "args",
                        "record",
                        "program_state",
                        "item",
                    }:
                        violations.append(ast.unparse(expression))
                    if isinstance(descendant, ast.Name) and descendant.id.startswith("raw_"):
                        violations.append(ast.unparse(expression))
                    if (
                        isinstance(descendant, ast.Call)
                        and isinstance(descendant.func, ast.Attribute)
                        and isinstance(descendant.func.value, ast.Name)
                        and descendant.func.value.id == "result"
                        and descendant.func.attr == "get"
                        and descendant.args
                        and isinstance(descendant.args[0], ast.Constant)
                        and descendant.args[0].value == "message"
                    ):
                        violations.append(ast.unparse(expression))

    assert violations == []


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
    assert "kb 动词（16 个）" in completed.stdout
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
    assert completed.stdout == (
        "知识库尚未收录资料。\n"
        "目前没有研究计划。\n"
        "待处理事项：0 条待确认判断、0 个到期监控、0 组文献候选待选择、"
        "0 个可继续文献检索、0 个可恢复综述流程、0 个过期综述待重建、"
        "0 个知识分类目录待刷新、0 个失败后可重试事项、"
        "0 个可由 Agent 继续推进的事项。\n"
    )
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

    help_results = [
        subprocess.run(
            [sys.executable, "-B", str(_kb_script(workspace)), *argv],
            cwd=workspace,
            env=_safe_runtime_env(),
            text=True,
            capture_output=True,
            check=False,
        )
        for argv in (["help"], ["--help"], ["init", "--help"], ["review", "--help"])
    ]

    for help_result in help_results:
        assert help_result.returncode == 0, help_result.stderr
        assert "kb 动词（16 个）" in help_result.stdout
        assert "positional arguments" not in help_result.stdout
        assert "options:" not in help_result.stdout
        assert help_result.stderr == ""
        for token in FORBIDDEN_PUBLIC_TOKENS:
            assert token not in help_result.stdout
    assert not (workspace / "kb").exists()
    installed_rules = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Conversational contract" in installed_rules
    assert "## Editing Rules" not in installed_rules


def test_installed_copy_repeated_init_preserves_preferences_and_tree(tmp_path: Path) -> None:
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

    optional_setup = subprocess.run(
        [sys.executable, "-B", str(_kb_script(workspace)), "init"],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert optional_setup.returncode == 0, optional_setup.stdout + optional_setup.stderr
    for expected_text in (
        "现在可以开始使用",
        "现在设置",
        "先跳过",
        "补充我的研究偏好",
        "第一次确认研究判断前仍会询问真实署名",
    ):
        assert expected_text in optional_setup.stdout
    for forbidden in ("还需要", "必填", "--", ".agents/", "NEXT FOR AGENT"):
        assert forbidden not in optional_setup.stdout
    before_defer = _tree_snapshot(workspace)

    deferred = subprocess.run(
        [sys.executable, "-B", str(_kb_script(workspace)), "init"],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert deferred.returncode == 0, deferred.stdout + deferred.stderr
    assert deferred.stdout == optional_setup.stdout
    assert _tree_snapshot(workspace) == before_defer

    profile_path = workspace / "kb" / "config" / "user-profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["resources"] = {"gpu_count": 2, "machine": "local"}
    profile["constraints"] = ["保留已有数据约束"]
    profile_path.write_text(
        yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    first = subprocess.run(
        [
            sys.executable,
            "-B",
            str(_kb_script(workspace)),
            "init",
            "--name",
            "Installed Researcher",
            "--lang",
            "en",
            "--auto-commit",
            "manual",
            "--auto-ingest-mode",
            "auto_deep_read",
            "--persona-focus",
            "VLA",
            "--persona-term",
            "bilingual",
            "--quick-resource",
            "4xH100 and a local robot",
            "--quick-constraint",
            "保留已有数据约束",
            "--quick-constraint",
            "不使用云服务",
        ],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert first.stdout == "知识库和基础偏好已准备好。\n"

    snapshot = subprocess.run(
        [
            sys.executable,
            "-B",
            str(_kb_script(workspace)),
            "--agent-protocol",
            "installed-init-snapshot.json",
            "init",
        ],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert snapshot.returncode == 0, snapshot.stdout + snapshot.stderr
    installed_protocol = yaml.safe_load(
        (workspace / "kb" / ".runtime" / "installed-init-snapshot.json").read_text(encoding="utf-8")
    )
    installed_defaults = installed_protocol["details"]["preferences"]
    assert installed_defaults["research_focus"] == "VLA"
    assert installed_defaults["resource_statement"] == "4xH100 and a local robot"
    assert installed_defaults["resources"] == {
        "gpu_count": 2,
        "machine": "local",
        "quick_setup": "4xH100 and a local robot",
    }
    assert installed_defaults["constraints"] == ["保留已有数据约束", "不使用云服务"]

    runtime_path = workspace / "kb" / "config" / "runtime-preferences.yaml"
    runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    runtime["autonomy"]["auto_execute_scope"] = ["ingest"]
    runtime_path.write_text(
        yaml.safe_dump(runtime, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    before = _tree_snapshot(workspace)

    second = subprocess.run(
        [sys.executable, "-B", str(_kb_script(workspace)), "init"],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert second.returncode == 0, second.stdout + second.stderr
    assert second.stdout == "知识库和基础偏好已准备好。\n"
    for token in ("[ok]", "created", "initial_commit", "kb/", "grounded"):
        assert token not in first.stdout + second.stdout
    assert _tree_snapshot(workspace) == before
    runtime_after = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    profile_after = yaml.safe_load(
        (workspace / "kb" / "config" / "user-profile.yaml").read_text(encoding="utf-8")
    )
    assert runtime_after["identity"]["default_confirmed_by"] == "Installed Researcher"
    assert "auto_screen_on_intake" not in runtime_after["paper"]
    assert runtime_after["autonomy"]["link_autodrive"] == "auto_deep_read"
    assert runtime_after["versioning"]["auto_commit_mode"] == "manual"
    assert runtime_after["autonomy"]["auto_execute_scope"] == ["ingest"]
    assert profile_after["preferences"]["language_preference"] == "en"
    assert profile_after["personalization"]["research_focus"] == "VLA"
    assert profile_after["personalization"]["term_style"] == "bilingual"
    assert profile_after["resources"] == {
        "gpu_count": 2,
        "machine": "local",
        "quick_setup": "4xH100 and a local robot",
    }
    assert profile_after["constraints"] == ["保留已有数据约束", "不使用云服务"]


def test_installed_copy_next_is_byte_identical_on_fresh_workspace(tmp_path: Path) -> None:
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
    before = _tree_snapshot(workspace)

    next_result = subprocess.run(
        [sys.executable, "-B", str(_kb_script(workspace)), "next"],
        cwd=workspace,
        env=_safe_runtime_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert next_result.returncode == 0, next_result.stdout + next_result.stderr
    assert "知识库还是空的" in next_result.stdout
    for token in FORBIDDEN_PUBLIC_TOKENS:
        assert token not in next_result.stdout
    assert _tree_snapshot(workspace) == before


def test_release_metadata_is_honest_rc_and_ci_is_cross_platform() -> None:
    root = _project_root()
    version = (root / "runtime" / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+-rc\.\d+", version)

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog
    assert version in changelog
    assert "not a stable release" in changelog
    assert re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE)

    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    assert "private vulnerability reporting" in security
    assert "/security/advisories/new" in security

    for relative in (
        "README.md",
        "docs/USER_GUIDE.md",
        "docs/DESIGN.md",
        "SECURITY.md",
        "CHANGELOG.md",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert version in text, f"{relative} does not declare the current candidate {version}"
        assert "GitHub Release" in text

    for relative in ("README.md", "docs/USER_GUIDE.md", "docs/DESIGN.md"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "CHANGELOG.md" in text
        assert "R17–R26" not in text
        assert "Obsidian 1.12.7" not in text

    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in ci
    assert "macos-latest" in ci
    assert "test_r1_conversational_release.py" in ci


def test_idea_skill_documents_link_refresh_and_fill_names() -> None:
    text = (_project_root() / "skills" / "idea-workbench" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    for token in (
        "link --from-id <idea-id> --to-id <unit-id> --relation evidence-for",
        "--refresh-corpus",
        "analyze-fill.yaml",
        "review-fill.yaml",
        "discussion-fill.yaml",
        "idea_context",
        "只读",
    ):
        assert token in text


def test_experiment_and_report_skills_document_private_minimum_invocations() -> None:
    root = _project_root() / "skills"
    experiment = (root / "experiment-workbench" / "SKILL.md").read_text(encoding="utf-8")
    report = (root / "report-author" / "SKILL.md").read_text(encoding="utf-8")
    for token in ("plan --title", "--program-id", "--hypothesis", "log-run --experiment-id", "--config-revision", "--seed"):
        assert token in experiment
    for token in ("weekly-prepare --program-id", "reports/editorial/weekly", "fill.yaml", "weekly-verify --program-id", "text", "refs"):
        assert token in report


def test_runtime_and_test_dependencies_are_exactly_locked_in_both_ci_jobs() -> None:
    root = _project_root()
    runtime_lines = _active_requirement_lines(root / "requirements.txt")
    shipped_runtime_lines = _active_requirement_lines(root / "runtime" / "requirements.txt")

    assert _parse_exact_pins(runtime_lines) == EXPECTED_RUNTIME_PINS
    assert _parse_exact_pins(shipped_runtime_lines) == EXPECTED_RUNTIME_PINS

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


def test_core_release_has_no_paid_provider_or_api_key_prerequisite() -> None:
    root = _project_root()
    runtime_packages = set(_parse_exact_pins(_active_requirement_lines(root / "requirements.txt")))
    assert runtime_packages.isdisjoint(
        {
            "anthropic",
            "google-cloud-discoveryengine",
            "openai",
            "openalex",
            "semanticscholar",
            "serpapi",
        }
    )

    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    for document in (readme, guide):
        assert "API Key" in document
        assert "paid" in document or "付费" in document
        assert "prerequisite" in document or "前置条件" in document

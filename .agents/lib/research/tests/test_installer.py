from __future__ import annotations

import errno
import json
import os
import pty
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _run_dry_install(tmp_path: Path, *, no_managed_venv: bool = False) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {**os.environ, "RESEARCH_PYTHON": "/bin/false", "NO_COLOR": "1"}
    if no_managed_venv:
        env["RESEARCH_NO_MANAGED_VENV"] = "1"
    return subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--dry-run",
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_pty_dialog(
    tmp_path: Path,
    *,
    args: list[str],
    exchanges: list[tuple[str, str]],
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "NO_COLOR": "1",
        "PATH": "/usr/bin:/bin",
        "RESEARCH_PYTHON": shutil.which("true") or "/usr/bin/true",
        "TERM": "dumb",
    }
    # A prior in-process bootstrap test may leave this readiness marker behind.
    # Each installer subprocess must prove its own configured runtime instead of
    # inheriting readiness from the pytest interpreter.
    env.pop("_RESEARCH_RUNTIME_READY", None)
    if env_overrides:
        env.update(env_overrides)
    command = ["bash", str(_project_root() / "install.sh"), *args]
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        command,
        cwd=_project_root(),
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    output = bytearray()
    search_from = 0

    def read_once(timeout: float) -> bool:
        ready, _, _ = select.select([master_fd], [], [], timeout)
        if not ready:
            return False
        try:
            chunk = os.read(master_fd, 65536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return False
            raise
        if chunk:
            output.extend(chunk)
            return True
        return False

    try:
        for marker, response in exchanges:
            encoded = marker.encode("utf-8")
            deadline = time.monotonic() + 10
            while output.find(encoded, search_from) < 0 and time.monotonic() < deadline:
                read_once(0.1)
                if process.poll() is not None:
                    break
            position = output.find(encoded, search_from)
            if position < 0:
                rendered = output.decode("utf-8", errors="replace")
                raise AssertionError(f"PTY prompt not found: {marker!r}\n{rendered}")
            search_from = position + len(encoded)
            os.write(master_fd, response.encode("utf-8"))

        deadline = time.monotonic() + 15
        while process.poll() is None and time.monotonic() < deadline:
            read_once(0.1)
        if process.poll() is None:
            process.kill()
            raise AssertionError("installer PTY session timed out")
        while read_once(0):
            pass
        returncode = process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)

    return subprocess.CompletedProcess(
        command,
        returncode,
        output.decode("utf-8", errors="replace"),
        "",
    )


def _run_shortcut_install(
    tmp_path: Path,
    *,
    shortcut_on_path: bool,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path_entries = ["/usr/bin", "/bin"]
    if shortcut_on_path:
        path_entries.insert(0, str(workspace / "bin"))
    result = _run_pty_dialog(
        tmp_path,
        args=[
            "install",
            "--codex",
            "--project",
            str(workspace),
            "--kb-on-path",
            "--yes",
        ],
        exchanges=[],
        env_overrides={
            "PATH": ":".join(path_entries),
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )
    return workspace, result


def _run_copy_action(
    tmp_path: Path,
    workspace: Path,
    *,
    action: str,
    source: Path | None = None,
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    workspace.mkdir(exist_ok=True)
    source_root = source or _project_root()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "NO_COLOR": "1",
        "PATH": "/usr/bin:/bin",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }
    # Bootstrap tests can set this marker directly in the pytest process.
    # A fresh installer subprocess must prove its own configured runtime.
    env.pop("_RESEARCH_RUNTIME_READY", None)
    command = ["bash", str(source_root / "install.sh"), action]
    if action == "install":
        command.append("--codex")
    command.extend(["--project", str(workspace), "--yes", *extra])
    return subprocess.run(
        command,
        cwd=source_root,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )


def _install_copy(
    tmp_path: Path,
    workspace: Path,
    *,
    source: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run_copy_action(tmp_path, workspace, action="install", source=source)


def _assert_private_sync_output_hidden(
    result: subprocess.CompletedProcess[str],
    *private_paths: Path,
) -> None:
    output = result.stdout + result.stderr
    for token in (
        "copy-project",
        "clean-sync",
        "[dry-run]",
        "warn:",
        "error:",
        "MODIFIED",
        "expected=",
        "actual=",
        "reason=",
        ".agents/",
    ):
        assert token not in output
    for path in private_paths:
        assert str(path) not in output


def _git_output(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_linked_source(tmp_path: Path) -> Path:
    primary = tmp_path / "source-primary"
    shutil.copytree(
        _project_root(),
        primary,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "*.pyc", "temp"),
    )
    subprocess.run(["git", "init", str(primary)], check=True, capture_output=True, text=True)
    _git_output(primary, "config", "user.name", "Installer Test")
    _git_output(primary, "config", "user.email", "installer@example.test")
    _git_output(primary, "checkout", "-b", "source-main")
    _git_output(primary, "add", ".")
    _git_output(primary, "commit", "-m", "source fixture")
    _git_output(primary, "remote", "add", "origin", "ssh://example.test/team/workspace-oss.git")
    linked = tmp_path / "source-linked"
    _git_output(primary, "worktree", "add", "-b", "linked-dev", str(linked), "source-main")
    return linked


def test_missing_system_yaml_continues_to_managed_runtime_fallback(tmp_path: Path) -> None:
    result = _run_dry_install(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "首次使用时会自动准备" in result.stderr
    assert "pip install" not in result.stderr


def test_missing_system_yaml_remains_fatal_when_managed_venv_disabled(tmp_path: Path) -> None:
    result = _run_dry_install(tmp_path, no_managed_venv=True)

    assert result.returncode == 1
    assert "已关闭自动运行环境" in result.stderr


def test_help_is_clear_and_colorless_for_first_time_users() -> None:
    result = subprocess.run(
        ["bash", str(_project_root() / "install.sh"), "--help"],
        cwd=_project_root(),
        env={**os.environ, "NO_COLOR": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "第一次使用" in result.stdout
    assert "直接运行 bash install.sh" in result.stdout
    assert "--project [DIR]" in result.stdout
    assert "\x1b[" not in result.stdout + result.stderr


def test_non_interactive_run_fails_fast_without_prompts() -> None:
    result = subprocess.run(
        ["bash", str(_project_root() / "install.sh")],
        cwd=_project_root(),
        env={**os.environ, "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 1
    assert "非交互运行时" in result.stderr
    assert "步骤 " not in result.stdout + result.stderr


def test_guided_dry_run_retries_invalid_choice_without_claiming_success(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=["--dry-run"],
        exchanges=[
            ("请选择 [1]：", "9\n"),
            ("请选择 [1]：", "1\n"),
            ("请选择 [3]：", "3\n"),
            ("请选择 [1]：", "1\n"),
            ("目录 [", f"{workspace}\n"),
            ("请选择 [1]：", "2\n"),
        ],
    )

    output = result.stdout
    assert result.returncode == 0, output
    assert "1) 首次安装" in output
    assert "2) 更新已安装的外部工作区" in output
    assert "3) 重装或修复已安装的外部工作区" in output
    assert "4) 卸载 skills 接入" in output
    assert "请输入 1、2、3 或 4" in output
    assert "预览完成" in output
    assert "没有写入任何文件" in output
    assert "安装完成" not in output
    assert "已为 Claude Code 和 Codex 完成配置" not in output
    assert "开始使用" not in output
    assert "[1/5]" not in output
    assert "底层文件操作：" in output
    assert ".agents/skills/kb-cli/scripts/kb" not in output
    assert "[dry-run]" not in output
    assert ".claude/skills" not in output
    assert "\x1b[" not in output
    assert len(output.splitlines()) < 60
    assert not any(workspace.iterdir())


def test_guided_cancel_writes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "1\n"),
            ("请选择 [3]：", "2\n"),
            ("请选择 [1]：", "1\n"),
            ("目录 [", f"{workspace}\n"),
            ("请选择 [1]：", "1\n"),
            ("确认执行？[Y/n]：", "n\n"),
        ],
    )

    assert result.returncode == 0, result.stdout
    assert "已取消，没有写入任何文件" in result.stdout
    assert not any(workspace.iterdir())


def test_guided_shortcut_choice_immediately_explains_terminal_usage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--dry-run", "--codex", "--project", str(workspace)],
        exchanges=[("请选择 [1]：", "2\n")],
    )

    output = result.stdout
    assert result.returncode == 0, output
    prompt_position = output.index("请选择 [1]：")
    help_position = output.index("kb help")
    init_position = output.index("kb init")
    preview_position = output.index("安装预览")
    assert prompt_position < help_position < init_position < preview_position
    assert not any(workspace.iterdir())


def test_shortcut_completion_reports_direct_terminal_usage_when_on_path(tmp_path: Path) -> None:
    workspace, result = _run_shortcut_install(tmp_path, shortcut_on_path=True)

    output = result.stdout
    assert result.returncode == 0, output
    completion = output.split("安装完成", 1)[1]
    terminal_guidance = completion.split("开始使用", 1)[0]
    assert "终端可直接运行" in terminal_guidance
    assert "kb help" in terminal_guidance
    assert "kb init" in terminal_guidance
    assert "不在 PATH" not in terminal_guidance
    assert (workspace / "bin" / "kb").is_symlink()
    for shell_config in (".zshrc", ".bashrc", ".profile"):
        assert not (tmp_path / "home" / shell_config).exists()


def test_shortcut_completion_explains_path_setup_when_not_on_path(tmp_path: Path) -> None:
    workspace, result = _run_shortcut_install(tmp_path, shortcut_on_path=False)

    output = result.stdout
    assert result.returncode == 0, output
    completion = output.split("安装完成", 1)[1]
    terminal_guidance = completion.split("开始使用", 1)[0]
    assert "不在 PATH" in terminal_guidance
    assert "加入 PATH" in terminal_guidance
    assert "重新打开终端" in terminal_guidance
    assert "kb help" in terminal_guidance
    assert "终端可直接运行" not in terminal_guidance
    assert str(workspace / "bin") in output
    assert (workspace / "bin" / "kb").is_symlink()
    for shell_config in (".zshrc", ".bashrc", ".profile"):
        assert not (tmp_path / "home" / shell_config).exists()


def test_external_install_prints_completion_without_bash_variable_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--codex", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "1\n")],
        env_overrides={
            "NO_COLOR": "1",
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "安装完成" in result.stdout
    assert f"工作区：{workspace}（独立工作区）" in result.stdout
    assert "unbound variable" not in result.stdout
    assert "copy-project" not in result.stdout
    assert "工作区文件已准备" in result.stdout
    terminal_guidance = result.stdout.split("安装完成", 1)[1].split("开始使用", 1)[0]
    assert "终端可直接运行" not in terminal_guidance
    assert "kb help" not in terminal_guidance
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    installed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert installed_manifest["source_strategy"] == "local-checkout"
    assert installed_manifest["source_checkout"] == str(_project_root())
    assert installed_manifest["source_origin"] == _git_output(_project_root(), "remote", "get-url", "origin")
    assert installed_manifest["source_branch"] == _git_output(
        _project_root(), "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    assert installed_manifest["source_commit"] == _git_output(_project_root(), "rev-parse", "HEAD")

    cancel = _run_pty_dialog(
        tmp_path,
        args=["uninstall", "--project", str(workspace)],
        exchanges=[("确认执行？[Y/n]：", "n\n")],
    )
    assert cancel.returncode == 0, cancel.stdout
    assert "已取消，没有写入任何文件" in cancel.stdout
    assert (workspace / ".agents" / ".install-manifest.json").is_file()

    update = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "2\n"),
            ("目录 [", f"{workspace}\n"),
            ("确认执行？[Y/n]：", "\n"),
        ],
    )
    assert update.returncode == 0, update.stdout
    assert "skills 已是最新版本，AI 工具配置已检查" in update.stdout
    assert "skills 和 AI 工具配置已更新" not in update.stdout
    assert "clean-sync" not in update.stdout
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["source_strategy"] == installed_manifest["source_strategy"]
    assert updated_manifest["source_origin"] == installed_manifest["source_origin"]
    assert updated_manifest["source_checkout"] == installed_manifest["source_checkout"]
    assert updated_manifest["source_branch"] == installed_manifest["source_branch"]


def test_noninteractive_copy_lifecycle_hides_sync_engine_output_and_preserves_semantics(tmp_path: Path) -> None:
    dry_workspace = tmp_path / "dry-workspace"
    dry_run = _run_copy_action(tmp_path, dry_workspace, action="install", extra=("--dry-run",))

    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    assert "底层文件操作：" in dry_run.stdout
    assert "预览完成" in dry_run.stdout
    _assert_private_sync_output_hidden(dry_run, _project_root(), dry_workspace / ".agents")
    assert not any(dry_workspace.iterdir())

    workspace = tmp_path / "workspace"
    install = _run_copy_action(tmp_path, workspace, action="install")

    assert install.returncode == 0, install.stdout + install.stderr
    assert "工作区文件已准备" in install.stdout
    assert "安装完成" in install.stdout
    _assert_private_sync_output_hidden(install, _project_root(), workspace / ".agents")
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    version_path = workspace / ".agents" / "VERSION"
    assert manifest_path.is_file()
    original_version = version_path.read_bytes()

    update = _run_copy_action(tmp_path, workspace, action="update")

    assert update.returncode == 0, update.stdout + update.stderr
    assert "skills 已是最新版本，AI 工具配置已检查" in update.stdout
    _assert_private_sync_output_hidden(update, _project_root(), workspace / ".agents")

    manifest_before_failure = manifest_path.read_bytes()
    version_path.write_text("locally drifted\n", encoding="utf-8")
    failed_update = _run_copy_action(tmp_path, workspace, action="update")

    assert failed_update.returncode == 3
    assert "工作区文件操作失败，请让 Agent 检查后重试" in failed_update.stderr
    _assert_private_sync_output_hidden(failed_update, _project_root(), workspace / ".agents")
    assert version_path.read_text(encoding="utf-8") == "locally drifted\n"
    assert manifest_path.read_bytes() == manifest_before_failure

    reinstall = _run_copy_action(tmp_path, workspace, action="reinstall")

    assert reinstall.returncode == 0, reinstall.stdout + reinstall.stderr
    assert "工作区文件已重新安装" in reinstall.stdout
    assert "重装完成" in reinstall.stdout
    _assert_private_sync_output_hidden(reinstall, _project_root(), workspace / ".agents")
    assert version_path.read_bytes() == original_version

    uninstall = _run_copy_action(tmp_path, workspace, action="uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert "安装器管理的工作区文件已移除" in uninstall.stdout
    assert "卸载完成" in uninstall.stdout
    _assert_private_sync_output_hidden(uninstall, _project_root(), workspace / ".agents")
    assert not manifest_path.exists()
    assert not version_path.exists()


def test_project_install_from_linked_worktree_preserves_linked_checkout(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    assert (source / ".git").is_file()
    workspace = tmp_path / "linked-workspace"

    installed = _install_copy(tmp_path, workspace, source=source)

    assert installed.returncode == 0, installed.stdout + installed.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_strategy"] == "local-checkout"
    assert manifest["source_checkout"] == str(source)
    assert manifest["source_origin"] == "ssh://example.test/team/workspace-oss.git"
    assert manifest["source_branch"] == "linked-dev"
    assert manifest["source_commit"] == _git_output(source, "rev-parse", "HEAD")


def test_ws_sync_rejects_unknown_source_strategy_before_writing(tmp_path: Path) -> None:
    workspace = tmp_path / "invalid-strategy-workspace"
    workspace.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "install",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
            "--source-strategy",
            "guess-from-origin",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert not (workspace / ".agents").exists()


def test_guided_reinstall_menu_runs_the_reinstall_action(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "3\n"),
            ("目录 [", f"{workspace}\n"),
            ("确认执行？[Y/n]：", "\n"),
        ],
        env_overrides={
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "操作：重装或修复" in result.stdout
    assert "AI 工具：Codex" in result.stdout
    assert "重装完成" in result.stdout


def test_interactive_duplicate_install_can_route_to_update_before_shortcut_prompt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "1\n")],
    )

    assert result.returncode == 0, result.stdout
    assert "这个工作区已经安装过" in result.stdout
    assert "操作：更新" in result.stdout
    assert "AI 工具：Codex" in result.stdout
    assert "更新完成" in result.stdout
    assert "是否创建终端快捷命令" not in result.stdout
    assert "终端快捷命令：" not in result.stdout


def test_interactive_duplicate_install_can_route_to_reinstall(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "2\n")],
        env_overrides={
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "操作：重装或修复" in result.stdout
    assert "AI 工具：Codex" in result.stdout
    assert "重装完成" in result.stdout
    assert "是否创建终端快捷命令" not in result.stdout


def test_interactive_duplicate_install_can_be_cancelled_without_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    manifest = workspace / ".agents" / ".install-manifest.json"
    manifest_before = manifest.read_bytes()

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace)],
        exchanges=[("请选择 [1]：", "3\n")],
    )

    assert result.returncode == 0, result.stdout
    assert "已取消，没有写入任何文件" in result.stdout
    assert "确认执行" not in result.stdout
    assert "是否创建终端快捷命令" not in result.stdout
    assert manifest.read_bytes() == manifest_before


def test_non_interactive_duplicate_install_still_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _install_copy(tmp_path, workspace)

    assert result.returncode != 0
    assert "这个工作区已经安装过" in result.stderr
    assert "更新" in result.stderr
    assert "重装" in result.stderr


def test_system_uninstall_removes_matching_shortcut_without_kb_flag_and_preserves_foreign_link(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    shortcut = home / ".local" / "bin" / "kb"
    shortcut.parent.mkdir(parents=True)
    kb_script = _project_root() / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    shortcut.symlink_to(kb_script)
    env = {**os.environ, "HOME": str(home), "NO_COLOR": "1", "PATH": "/usr/bin:/bin"}
    command = [
        "bash",
        str(_project_root() / "install.sh"),
        "--uninstall",
        "--system",
        "--codex",
        "--yes",
    ]

    removed = subprocess.run(
        command,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not shortcut.is_symlink()

    shortcut.symlink_to("/usr/bin/true")
    preserved = subprocess.run(
        command,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert preserved.returncode == 0, preserved.stdout + preserved.stderr
    assert shortcut.is_symlink()
    assert os.readlink(shortcut) == "/usr/bin/true"
    assert "链接目标与安装记录不一致，已保留" in preserved.stderr

    shortcut.unlink()
    shortcut.write_text("user-owned\n", encoding="utf-8")
    ordinary_file = subprocess.run(
        command,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert ordinary_file.returncode == 0, ordinary_file.stdout + ordinary_file.stderr
    assert shortcut.read_text(encoding="utf-8") == "user-owned\n"
    assert "kb 快捷入口不是安装器创建的链接，已保留" in ordinary_file.stderr


def test_legacy_project_uninstall_removes_matching_shortcut_without_kb_flag(tmp_path: Path) -> None:
    workspace = tmp_path / "legacy-workspace"
    workspace.mkdir()
    (workspace / ".agents").symlink_to(_project_root() / ".agents", target_is_directory=True)
    shortcut = workspace / "bin" / "kb"
    shortcut.parent.mkdir()
    shortcut.symlink_to(_project_root() / ".agents" / "skills" / "kb-cli" / "scripts" / "kb")

    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--uninstall",
            "--project",
            str(workspace),
            "--codex",
            "--yes",
        ],
        cwd=_project_root(),
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "NO_COLOR": "1",
            "PATH": "/usr/bin:/bin",
        },
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not shortcut.is_symlink()
    assert not (workspace / ".agents").exists()


def test_guided_system_uninstall_can_be_cancelled(tmp_path: Path) -> None:
    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "4\n"),
            ("请选择 [3]：", "2\n"),
            ("请选择 [1]：", "2\n"),
            ("确认执行？[Y/n]：", "n\n"),
        ],
    )

    assert result.returncode == 0, result.stdout
    assert "操作：卸载" in result.stdout
    assert "使用范围：当前用户的所有工作区" in result.stdout
    assert "已取消，没有写入任何文件" in result.stdout


def test_single_agent_conflict_stops_before_next_steps(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "skills").write_text("user-owned\n", encoding="utf-8")

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "1\n")],
        env_overrides={
            "NO_COLOR": "1",
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "配置因文件冲突被跳过" in result.stdout
    assert "请先处理上方文件冲突" in result.stdout
    assert "开始使用" not in result.stdout
    assert "kb init" not in result.stdout

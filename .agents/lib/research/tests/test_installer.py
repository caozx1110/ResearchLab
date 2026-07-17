from __future__ import annotations

import errno
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
    assert "请输入 1、2 或 3" in output
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


def test_guided_system_uninstall_can_be_cancelled(tmp_path: Path) -> None:
    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "3\n"),
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

#!/usr/bin/env python3
"""Terminal integrations for the research navigator browser."""

from __future__ import annotations

import fcntl
import os
import pty
import select
import shlex
import signal
import struct
import subprocess
import sys
import threading
import time
import termios
import uuid
from pathlib import Path
from typing import Any

TERMINAL_BUFFER_LIMIT = 220_000
TERMINAL_SELECT_TIMEOUT = 0.2


class TerminalSession:
    """A lightweight PTY-backed terminal session for the browser sidebar."""

    def __init__(self, project_root: Path, *, mode: str) -> None:
        self.project_root = project_root
        self.session_id = uuid.uuid4().hex
        self.mode = mode
        self.status = "starting"
        self.cwd = str(project_root)
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.last_error = ""
        self.base_offset = 0
        self.buffer = ""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._master_fd: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread = threading.Thread(target=self._read_loop, name=f"research-navigator-terminal-{self.session_id[:8]}", daemon=True)
        self._spawn(mode)
        self._reader_thread.start()

    def _shell_executable(self) -> str:
        shell = os.environ.get("SHELL") or "/bin/zsh"
        return shell

    def _spawn(self, mode: str) -> None:
        master_fd, slave_fd = pty.openpty()
        os.set_blocking(master_fd, False)
        shell = self._shell_executable()
        workspace = str(self.project_root)
        quoted_workspace = shlex.quote(workspace)
        quoted_shell = shlex.quote(shell)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["CLICOLOR"] = "1"
        if mode == "codex":
            startup = (
                f"cd {quoted_workspace} && "
                f"codex --no-alt-screen -C {quoted_workspace}; "
                f"exec {quoted_shell} -l"
            )
        else:
            startup = (
                f"cd {quoted_workspace} && "
                f"exec {quoted_shell} -l"
            )
        self._process = subprocess.Popen(
            [shell, "-lc", startup],
            cwd=self.project_root,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        self._master_fd = master_fd

    def _respond_to_terminal_queries(self, data: bytes) -> None:
        if self._master_fd is None:
            return
        responses: list[bytes] = []
        if b"\x1b[6n" in data:
            responses.append(b"\x1b[1;1R")
        if b"\x1b[c" in data:
            responses.append(b"\x1b[?1;2c")
        if b"\x1b]10;?" in data:
            responses.append(b"\x1b]10;rgb:dddd/dddd/dddd\x1b\\")
        if b"\x1b]11;?" in data:
            responses.append(b"\x1b]11;rgb:1111/1111/1111\x1b\\")
        if b'Continue anyway? [y/N]:' in data:
            responses.append(b"y\r")
        for payload in responses:
            try:
                os.write(self._master_fd, payload)
            except OSError:
                return

    def _append(self, text: str) -> None:
        with self._lock:
            self.buffer += text
            if len(self.buffer) > TERMINAL_BUFFER_LIMIT:
                trim = len(self.buffer) - TERMINAL_BUFFER_LIMIT
                self.buffer = self.buffer[trim:]
                self.base_offset += trim

    def _read_loop(self) -> None:
        if self._master_fd is None:
            self.status = "failed"
            self.last_error = "terminal master fd 未初始化"
            return
        while not self._stop_event.is_set():
            try:
                ready, _, _ = select.select([self._master_fd], [], [], TERMINAL_SELECT_TIMEOUT)
            except (OSError, ValueError):
                break
            if ready:
                try:
                    data = os.read(self._master_fd, 65536)
                except BlockingIOError:
                    data = b""
                except OSError:
                    break
                if not data:
                    if self._process and self._process.poll() is not None:
                        break
                    continue
                self._respond_to_terminal_queries(data)
                self._append(data.decode("utf-8", errors="replace"))
                self.status = "running"
            elif self._process and self._process.poll() is not None:
                break
        self.status = "exited" if not self.last_error else "failed"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cursor = self.base_offset + len(self.buffer)
        return {
            "ok": True,
            "session_id": self.session_id,
            "mode": self.mode,
            "status": self.status,
            "cwd": self.cwd,
            "cursor": cursor,
            "created_at": self.created_at,
            "last_error": self.last_error,
        }

    def poll(self, cursor: int) -> dict[str, Any]:
        with self._lock:
            current_cursor = self.base_offset + len(self.buffer)
            payload = {
                "ok": True,
                "session_id": self.session_id,
                "mode": self.mode,
                "status": self.status,
                "cwd": self.cwd,
                "created_at": self.created_at,
                "last_error": self.last_error,
            }
            if cursor < self.base_offset or cursor > current_cursor:
                return {
                    **payload,
                    "reset": True,
                    "data": self.buffer,
                    "cursor": current_cursor,
                }
            start = max(0, cursor - self.base_offset)
            return {
                **payload,
                "reset": False,
                "data": self.buffer[start:],
                "cursor": current_cursor,
            }

    def write(self, data: str) -> None:
        if self._master_fd is None:
            raise ValueError("终端尚未初始化")
        payload = data.encode("utf-8")
        os.write(self._master_fd, payload)

    def resize(self, cols: int, rows: int) -> None:
        if self._master_fd is None:
            raise ValueError("终端尚未初始化")
        cols = max(2, int(cols))
        rows = max(1, int(rows))
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def close(self) -> None:
        self._stop_event.set()
        process = self._process
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
        if self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.5)
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None


class TerminalManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._lock = threading.Lock()
        self._sessions: dict[str, TerminalSession] = {}

    def _cleanup_dead_sessions(self) -> None:
        stale = [mode for mode, session in self._sessions.items() if session.status in {"failed", "exited"}]
        for mode in stale:
            session = self._sessions.pop(mode, None)
            if session is not None:
                session.close()

    def _find_session_by_id(self, session_id: str) -> TerminalSession | None:
        for session in self._sessions.values():
            if session.session_id == session_id:
                return session
        return None

    def open(self, *, mode: str, force: bool = False) -> dict[str, Any]:
        if mode not in {"codex", "shell"}:
            mode = "shell"
        with self._lock:
            self._cleanup_dead_sessions()
            session = self._sessions.get(mode)
            if force or session is None:
                if session is not None:
                    session.close()
                session = TerminalSession(self.project_root, mode=mode)
                self._sessions[mode] = session
            return session.snapshot()

    def poll(self, session_id: str, cursor: int) -> dict[str, Any]:
        with self._lock:
            session = self._find_session_by_id(session_id)
            if session is None:
                raise ValueError("终端会话不存在或已过期")
            return session.poll(cursor)

    def write(self, session_id: str, data: str) -> dict[str, Any]:
        with self._lock:
            session = self._find_session_by_id(session_id)
            if session is None:
                raise ValueError("终端会话不存在或已过期")
            session.write(data)
            return session.snapshot()

    def resize(self, session_id: str, cols: int, rows: int) -> dict[str, Any]:
        with self._lock:
            session = self._find_session_by_id(session_id)
            if session is None:
                raise ValueError("终端会话不存在或已过期")
            session.resize(cols, rows)
            return session.snapshot()

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()


def _escape_applescript_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _mac_app_exists(*names: str) -> bool:
    for name in names:
        completed = subprocess.run(
            ["osascript", "-e", f'id of app "{name}"'],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return True
    return False


def system_terminal_targets() -> list[dict[str, Any]]:
    if sys.platform != "darwin":
        return []
    terminal_available = _mac_app_exists("Terminal")
    iterm_available = _mac_app_exists("iTerm", "iTerm2")
    return [
        {
            "id": "terminal",
            "label": "Terminal.app",
            "available": terminal_available,
            "reason": "" if terminal_available else "系统未检测到 Terminal.app",
        },
        {
            "id": "iterm2",
            "label": "iTerm2",
            "available": iterm_available,
            "reason": "" if iterm_available else "当前机器未安装 iTerm2",
        },
    ]


def open_system_terminal(project_root: Path, *, mode: str, target: str) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise ValueError("系统终端打开当前仅支持 macOS")
    targets = {item["id"]: item for item in system_terminal_targets()}
    selected = targets.get(target) or targets.get("terminal")
    if not selected or not selected.get("available"):
        raise ValueError(f"终端目标 `{target}` 当前不可用")
    workspace = str(project_root)
    if mode == "shell":
        command = f"cd {shlex.quote(workspace)} && exec $SHELL -l"
        description = "在系统终端打开当前工作区 shell"
    else:
        command = f"cd {shlex.quote(workspace)} && codex --no-alt-screen -C ."
        description = "在系统终端打开当前工作区 Codex CLI"
    if selected["id"] == "iterm2":
        script = f'''
tell application "iTerm2"
  activate
  create window with default profile command "{_escape_applescript_string(command)}"
end tell
'''
    else:
        script = f'''
tell application "Terminal"
  activate
  do script "{_escape_applescript_string(command)}"
end tell
'''
    subprocess.run(["osascript", "-e", script], check=True)
    return {"ok": True, "description": description, "mode": mode, "cwd": workspace, "target": selected["id"]}

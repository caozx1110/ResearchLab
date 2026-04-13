#!/usr/bin/env python3
"""Serve the research knowledge browser, editor APIs, and a lightweight terminal sidebar."""

from __future__ import annotations

import argparse
import fcntl
import json
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
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:
    FileSystemEvent = Any  # type: ignore[assignment]

    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass

    Observer = None  # type: ignore[assignment]
    WATCHDOG_IMPORT_ERROR = exc

from kb_browser_lib import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    SERVICE_NAME,
    WATCH_DEBOUNCE_SECONDS,
    browser_url,
    compact_text,
    kb_root,
    load_build_status,
    project_root_from_script,
    safe_rebuild,
    server_log_path,
    version_url,
    web_path,
    write_text_atomic,
)

WATCHED_SUFFIXES = {".yaml", ".yml", ".md", ".markdown", ".txt", ".log", ".json"}
READABLE_TEXT_SUFFIXES = {".md", ".markdown", ".yaml", ".yml", ".txt", ".log", ".json", ".py", ".sh", ".toml"}
WRITABLE_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
BLOCKED_WRITE_ROOTS = {
    ".git",
    "node_modules",
    "doc/research/user/kb",
}
MAX_TEXT_FILE_BYTES = 1_500_000
TERMINAL_BUFFER_LIMIT = 220_000
TERMINAL_SELECT_TIMEOUT = 0.2
TERMINAL_STARTUP_BANNER = ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def relevant_change(project_root: Path, raw_path: str) -> bool:
    if not raw_path:
        return False
    path = Path(raw_path)
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path.absolute()
    research_root = project_root / "doc" / "research"
    if not _is_relative_to(resolved, research_root):
        return False
    if _is_relative_to(resolved, kb_root(project_root)):
        return False
    if resolved.name.startswith("."):
        return False
    if resolved.name.endswith(("~", ".swp", ".swx", ".tmp", ".bak", ".part", ".crdownload")):
        return False
    if resolved.suffix.lower() not in WATCHED_SUFFIXES:
        return False
    if _is_relative_to(resolved, research_root / "library"):
        return True
    if _is_relative_to(resolved, research_root / "programs"):
        return True
    if _is_relative_to(resolved, research_root / "wiki"):
        return True
    if _is_relative_to(resolved, research_root / "user"):
        return True
    return resolved == (research_root / "memory" / "domain-profile.yaml")


def _mtime_iso(path: Path) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
    except OSError:
        return ""


def _clean_rel_path(raw_path: str) -> str:
    return str(raw_path or "").strip().lstrip("/")


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    rel_path = _clean_rel_path(raw_path)
    if not rel_path:
        raise ValueError("path 不能为空")
    resolved = (project_root / rel_path).resolve()
    if not _is_relative_to(resolved, project_root):
        raise ValueError("禁止访问工作区之外的路径")
    return resolved


def _read_text_file(path: Path) -> str:
    if path.stat().st_size > MAX_TEXT_FILE_BYTES:
        raise ValueError(f"文件过大，当前只支持打开 {MAX_TEXT_FILE_BYTES // 1000}KB 以内的文本文件")
    return path.read_text(encoding="utf-8")


def _file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix in READABLE_TEXT_SUFFIXES:
        return "text"
    return "binary"


def _is_writable_text(project_root: Path, path: Path) -> bool:
    if path.suffix.lower() not in WRITABLE_TEXT_SUFFIXES:
        return False
    rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    for blocked in BLOCKED_WRITE_ROOTS:
        blocked_root = (project_root / blocked).resolve()
        if _is_relative_to(path, blocked_root):
            return False
    return True


def _file_payload(project_root: Path, path: Path) -> dict[str, Any]:
    kind = _file_kind(path)
    if kind == "binary":
        raise ValueError("当前工作台只支持打开文本文件")
    content = _read_text_file(path)
    rel = path.resolve().relative_to(project_root.resolve()).as_posix()
    return {
        "ok": True,
        "path": rel,
        "href": web_path(rel),
        "kind": kind,
        "writable": _is_writable_text(project_root, path),
        "updated_at": _mtime_iso(path),
        "content": content,
    }


def _decode_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except ValueError:
        length = 0
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"请求体 JSON 非法：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON object")
    return payload


class BrowserBuildCoordinator:
    """Debounce rebuild requests and keep the last successful snapshot live."""

    def __init__(self, project_root: Path, *, debounce_seconds: float) -> None:
        self.project_root = project_root
        self.debounce_seconds = max(0.5, float(debounce_seconds))
        self._lock = threading.Lock()
        self._next_build_at = 0.0
        self._pending_reasons: list[str] = []
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="research-kb-browser-builder", daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def request_build(self, reason: str) -> None:
        with self._lock:
            self._next_build_at = time.monotonic() + self.debounce_seconds
            self._pending_reasons.append(compact_text(reason, limit=160))

    def build_now(self, reason: str) -> None:
        self.request_build(reason)
        with self._lock:
            self._next_build_at = time.monotonic()

    def _run(self) -> None:
        while not self._stop_event.wait(0.35):
            due = 0.0
            reasons: list[str] = []
            with self._lock:
                due = self._next_build_at
                if due and due <= time.monotonic():
                    reasons = self._pending_reasons[:]
                    self._pending_reasons.clear()
                    self._next_build_at = 0.0
            if not reasons:
                continue
            status = safe_rebuild(self.project_root, script_path=Path(__file__))
            state = "ok" if status.get("build_status") == "ready" else status.get("build_status")
            print(f"[watch] rebuild {state}: {', '.join(reasons[:3])}", flush=True)


class ResearchKbEventHandler(FileSystemEventHandler):
    """Watch research files and request debounced rebuilds."""

    def __init__(self, project_root: Path, coordinator: BrowserBuildCoordinator) -> None:
        super().__init__()
        self.project_root = project_root
        self.coordinator = coordinator

    def on_any_event(self, event: FileSystemEvent) -> None:
        candidates = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
        for raw_path in candidates:
            if relevant_change(self.project_root, raw_path):
                self.coordinator.request_build(f"{event.event_type}:{Path(raw_path).name}")
                return


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
        self.buffer = TERMINAL_STARTUP_BANNER
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._master_fd: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread = threading.Thread(target=self._read_loop, name=f"research-kb-terminal-{self.session_id[:8]}", daemon=True)
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


class BrowserHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class,
        *,
        project_root: Path,
        coordinator: BrowserBuildCoordinator,
        terminal_manager: TerminalManager,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.project_root = project_root
        self.coordinator = coordinator
        self.terminal_manager = terminal_manager


def _escape_applescript_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def system_terminal_targets() -> list[dict[str, Any]]:
    if sys.platform != "darwin":
      return []
    return [
        {
            "id": "terminal",
            "label": "Terminal.app",
            "available": Path("/System/Applications/Utilities/Terminal.app").exists() or Path("/Applications/Utilities/Terminal.app").exists() or Path("/Applications/Terminal.app").exists(),
            "reason": "" if (Path("/System/Applications/Utilities/Terminal.app").exists() or Path("/Applications/Utilities/Terminal.app").exists() or Path("/Applications/Terminal.app").exists()) else "系统未检测到 Terminal.app",
        },
        {
            "id": "iterm2",
            "label": "iTerm2",
            "available": Path("/Applications/iTerm.app").exists(),
            "reason": "" if Path("/Applications/iTerm.app").exists() else "当前机器未安装 iTerm2",
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


def create_handler(*, project_root: Path):
    class BrowserHandler(SimpleHTTPRequestHandler):
        server_version = "ResearchKBBrowser/2.0"

        def guess_type(self, path: str) -> str:  # noqa: D401
            content_type = super().guess_type(path)
            lower = path.lower()
            if lower.endswith(".md"):
                return "text/markdown; charset=utf-8"
            if lower.endswith(".yaml") or lower.endswith(".yml"):
                return "text/yaml; charset=utf-8"
            if lower.endswith(".json"):
                return "application/json; charset=utf-8"
            if content_type.startswith("text/") and "charset" not in content_type:
                return f"{content_type}; charset=utf-8"
            return content_type

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, message: str, *, status: int = HTTPStatus.BAD_REQUEST) -> None:
            self._send_json({"ok": False, "error": message}, status=status)

        def _handle_health(self) -> None:
            self._send_json(
                {
                    "ok": True,
                    "service": SERVICE_NAME,
                    "project_root": str(project_root),
                    "kb_root": str(kb_root(project_root)),
                }
            )

        def _handle_version(self) -> None:
            status_payload = load_build_status(project_root)
            self._send_json(status_payload)

        def _handle_system_terminal_targets(self) -> None:
            self._send_json({"ok": True, "targets": system_terminal_targets()})

        def _handle_file_get(self, parsed) -> None:
            query = parse_qs(parsed.query or "")
            raw_path = (query.get("path") or [""])[0]
            if not raw_path:
                self._send_error_json("缺少 path 参数")
                return
            try:
                path = _resolve_project_path(project_root, raw_path)
                if not path.exists() or not path.is_file():
                    raise FileNotFoundError("文件不存在")
                payload = _file_payload(project_root, path)
            except FileNotFoundError:
                self._send_error_json("文件不存在", status=HTTPStatus.NOT_FOUND)
                return
            except ValueError as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(payload)

        def _handle_file_put(self) -> None:
            try:
                payload = _decode_body(self)
                path = _resolve_project_path(project_root, str(payload.get("path") or ""))
                if not _is_writable_text(project_root, path):
                    raise ValueError("当前只允许在工作台内保存 Markdown / 文本文件，且不能写入生成目录")
                content = str(payload.get("content") or "")
                write_text_atomic(path, content)
                self.server.coordinator.build_now(f"editor-save:{path.name}")  # type: ignore[attr-defined]
                response = _file_payload(project_root, path)
            except ValueError as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(response)

        def _handle_terminal_open(self) -> None:
            try:
                payload = _decode_body(self)
                mode = str(payload.get("mode") or "codex")
                force = bool(payload.get("force"))
                response = self.server.terminal_manager.open(mode=mode, force=force)  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(response)

        def _handle_terminal_input(self) -> None:
            try:
                payload = _decode_body(self)
                session_id = str(payload.get("session_id") or "")
                data = str(payload.get("data") or "")
                response = self.server.terminal_manager.write(session_id, data)  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(response)

        def _handle_terminal_resize(self) -> None:
            try:
                payload = _decode_body(self)
                session_id = str(payload.get("session_id") or "")
                cols = int(payload.get("cols") or 0)
                rows = int(payload.get("rows") or 0)
                response = self.server.terminal_manager.resize(session_id, cols, rows)  # type: ignore[attr-defined]
            except (ValueError, TypeError) as exc:
                self._send_error_json(str(exc))
                return
            self._send_json(response)

        def _handle_system_terminal_open(self) -> None:
            try:
                payload = _decode_body(self)
                mode = str(payload.get("mode") or "codex")
                target = str(payload.get("target") or "terminal")
                response = open_system_terminal(project_root, mode=mode, target=target)
            except ValueError as exc:
                self._send_error_json(str(exc))
                return
            except subprocess.CalledProcessError as exc:
                self._send_error_json(f"打开系统终端失败：{exc}")
                return
            self._send_json(response)

        def _handle_terminal_poll(self, parsed) -> None:
            query = parse_qs(parsed.query or "")
            session_id = (query.get("session_id") or [""])[0]
            cursor_raw = (query.get("cursor") or ["0"])[0]
            try:
                cursor = int(cursor_raw)
            except ValueError:
                cursor = 0
            try:
                response = self.server.terminal_manager.poll(session_id, cursor)  # type: ignore[attr-defined]
            except ValueError as exc:
                self._send_error_json(str(exc), status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(response)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/healthz":
                self._handle_health()
                return
            if parsed.path == "/api/version":
                self._handle_version()
                return
            if parsed.path == "/api/system-terminal/targets":
                self._handle_system_terminal_targets()
                return
            if parsed.path == "/api/file":
                self._handle_file_get(parsed)
                return
            if parsed.path == "/api/terminal/poll":
                self._handle_terminal_poll(parsed)
                return
            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/terminal/open":
                self._handle_terminal_open()
                return
            if parsed.path == "/api/terminal/input":
                self._handle_terminal_input()
                return
            if parsed.path == "/api/terminal/resize":
                self._handle_terminal_resize()
                return
            if parsed.path == "/api/system-terminal/open":
                self._handle_system_terminal_open()
                return
            self._send_error_json("不支持的 POST 接口", status=HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/file":
                self._handle_file_put()
                return
            self._send_error_json("不支持的 PUT 接口", status=HTTPStatus.NOT_FOUND)

    return partial(BrowserHandler, directory=str(project_root))  # type: ignore[return-value]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the research knowledge browser.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port (default: 8787)")
    parser.add_argument("--project-root", default="", help="Project root path. Auto-detected when omitted.")
    parser.add_argument(
        "--debounce-seconds",
        type=float,
        default=WATCH_DEBOUNCE_SECONDS,
        help="Delay after the last watched event before rebuilding (default: 1.5).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    if WATCHDOG_IMPORT_ERROR is not None or Observer is None:
        raise SystemExit(
            "research-kb-browser serve requires the `watchdog` package. "
            "Use the remembered research runtime or install watchdog in the active interpreter."
        )
    coordinator = BrowserBuildCoordinator(project_root, debounce_seconds=args.debounce_seconds)
    terminal_manager = TerminalManager(project_root)
    initial_status = safe_rebuild(project_root, script_path=Path(__file__))
    print(f"[ok] initial build: {initial_status.get('build_status')}", flush=True)

    handler_cls = create_handler(project_root=project_root)
    server = BrowserHTTPServer(
        (args.host, args.port),
        handler_cls,
        project_root=project_root,
        coordinator=coordinator,
        terminal_manager=terminal_manager,
    )
    observer = Observer()
    observer.schedule(ResearchKbEventHandler(project_root, coordinator), str(project_root / "doc" / "research"), recursive=True)
    observer.start()
    coordinator.start()

    def shutdown(*_: object) -> None:
        observer.stop()
        coordinator.stop()
        terminal_manager.close()
        threading.Thread(target=server.shutdown, name="research-kb-browser-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(f"[ok] serving project root: {project_root}", flush=True)
    print(f"[ok] browser url: {browser_url(args.host, args.port)}", flush=True)
    print(f"[ok] version url: {version_url(args.host, args.port)}", flush=True)
    print(f"[ok] runtime log: {server_log_path(project_root)}", flush=True)
    try:
        server.serve_forever()
    finally:
        observer.stop()
        observer.join(timeout=3.0)
        coordinator.stop()
        terminal_manager.close()
        server.server_close()


if __name__ == "__main__":
    main()

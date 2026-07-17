#!/usr/bin/env python3
"""Serve the research navigator browser, editor APIs, and a lightweight terminal sidebar."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.cookies import SimpleCookie
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
    add_browser_project_root_argument,
    browser_url,
    compact_text,
    kb_root,
    load_build_status,
    path_is_relative_to,
    project_root_from_script,
    safe_rebuild,
    server_log_path,
    version_url,
    web_path,
    write_text_atomic,
)
from kb_browser_terminal import TerminalManager, open_system_terminal, system_terminal_targets
from research.bootstrap import ensure_managed_runtime  # type: ignore
from research.core import maybe_auto_checkpoint  # type: ignore
from research.journal import mutation_transaction  # type: ignore

WATCHED_SUFFIXES = {".yaml", ".yml", ".md", ".markdown", ".txt", ".log", ".json"}
READABLE_TEXT_SUFFIXES = {".md", ".markdown", ".yaml", ".yml", ".txt", ".log", ".json", ".py", ".sh", ".toml"}
WRITABLE_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
BLOCKED_WRITE_ROOTS = {
    ".git",
    "node_modules",
    "kb/user/kb",
    "kb/user/navigator",
}
MAX_TEXT_FILE_BYTES = 1_500_000


def relevant_change(project_root: Path, raw_path: str) -> bool:
    if not raw_path:
        return False
    path = Path(raw_path)
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path.absolute()
    research_root = project_root / "kb"
    if not path_is_relative_to(resolved, research_root):
        return False
    if path_is_relative_to(resolved, kb_root(project_root)):
        return False
    if resolved.name.startswith("."):
        return False
    if resolved.name.endswith(("~", ".swp", ".swx", ".tmp", ".bak", ".part", ".crdownload")):
        return False
    if resolved.suffix.lower() not in WATCHED_SUFFIXES:
        return False
    watched_roots = [
        research_root / "units",
        research_root / "programs",
        research_root / "synthesis",
        research_root / "user",
        research_root / "config",
        research_root / "intake",
    ]
    if any(path_is_relative_to(resolved, root) for root in watched_roots):
        return True
    return resolved in {
        research_root / "index.md",
        research_root / "index.yaml",
    }


def _mtime_iso(path: Path) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
    except OSError:
        return ""


def _clean_rel_path(raw_path: str) -> str:
    return str(raw_path or "").strip().lstrip("/")


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    if Path(str(raw_path or "")).is_absolute():
        raise ValueError("禁止使用绝对路径")
    rel_path = _clean_rel_path(raw_path)
    if not rel_path:
        raise ValueError("path 不能为空")
    resolved = (project_root / rel_path).resolve()
    if not path_is_relative_to(resolved, project_root):
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


def _is_immutable_unit_evidence(project_root: Path, path: Path) -> bool:
    units_root = (project_root / "kb/units").resolve()
    try:
        unit_relative = path.resolve().relative_to(units_root)
    except ValueError:
        return False
    parts = unit_relative.parts
    if len(parts) < 3:
        return False
    artifact_path = Path(*parts[2:])
    if artifact_path.parts[0] in {"raw", "source"}:
        return True
    return (
        len(artifact_path.parts) == 1
        and artifact_path.name.startswith("parse-cache")
        and artifact_path.suffix.lower() in {".yaml", ".yml"}
    )


def _is_writable_text(project_root: Path, path: Path) -> bool:
    if not path_is_relative_to(path.resolve(), (project_root / "kb").resolve()):
        return False
    if _is_immutable_unit_evidence(project_root, path):
        return False
    if path.suffix.lower() not in WRITABLE_TEXT_SUFFIXES:
        return False
    for blocked in BLOCKED_WRITE_ROOTS:
        blocked_root = (project_root / blocked).resolve()
        if path_is_relative_to(path, blocked_root):
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
        self._thread = threading.Thread(target=self._run, name="research-navigator-builder", daemon=True)

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


class ResearchNavigatorEventHandler(FileSystemEventHandler):
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


class BrowserHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class,
        *,
        project_root: Path,
        coordinator: BrowserBuildCoordinator,
        terminal_manager: TerminalManager | None,
        terminal_enabled: bool,
        auth_token: str,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.project_root = project_root
        self.coordinator = coordinator
        self.terminal_manager = terminal_manager
        self.terminal_enabled = terminal_enabled
        self.auth_token = auth_token

def create_handler(*, project_root: Path):
    class BrowserHandler(SimpleHTTPRequestHandler):
        server_version = "ResearchNavigator/2.0"

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

        def end_headers(self) -> None:
            cookie_token = getattr(self, "_auth_cookie_token", "")
            if cookie_token:
                self.send_header("Set-Cookie", f"kb_token={cookie_token}; Path=/; HttpOnly; SameSite=Strict")
                self._auth_cookie_token = ""
            super().end_headers()

        def log_message(self, format: str, *args: object) -> None:
            message = format % args
            token = self.server.auth_token  # type: ignore[attr-defined]
            super().log_message("%s", message.replace(token, "[redacted]"))

        def _send_error_json(self, message: str, *, status: int = HTTPStatus.BAD_REQUEST) -> None:
            self._send_json({"ok": False, "error": message}, status=status)

        def _authorized(self, parsed) -> bool:
            if parsed.path == "/api/healthz":
                return True
            query = parse_qs(parsed.query or "")
            query_token = (query.get("token") or [""])[0]
            header_token = self.headers.get("X-KB-Token", "")
            authorization = self.headers.get("Authorization", "")
            bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            cookie_token = cookies.get("kb_token").value if cookies.get("kb_token") else ""
            expected = self.server.auth_token  # type: ignore[attr-defined]
            authorized = any(
                candidate and secrets.compare_digest(candidate, expected)
                for candidate in (query_token, header_token, bearer_token, cookie_token)
            )
            if authorized and query_token:
                self._auth_cookie_token = expected
            return authorized

        def _handle_health(self) -> None:
            self._send_json(
                {
                    "ok": True,
                    "service": SERVICE_NAME,
                    "project_root": str(project_root),
                    "kb_root": str(kb_root(project_root)),
                    "pid": os.getpid(),
                }
            )

        def _handle_version(self) -> None:
            status_payload = load_build_status(project_root)
            status_payload["pid"] = os.getpid()
            self._send_json(status_payload)

        def _handle_rebuild(self) -> None:
            try:
                status_payload = safe_rebuild(project_root, script_path=Path(__file__))
                status_payload["pid"] = os.getpid()
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(f"重建快照失败：{exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json(status_payload)

        def _handle_system_terminal_targets(self) -> None:
            self._send_json({"ok": True, "targets": system_terminal_targets()})

        def _terminal_available(self) -> bool:
            if self.server.terminal_enabled:  # type: ignore[attr-defined]
                return True
            self._send_error_json("终端功能未启用", status=HTTPStatus.FORBIDDEN)
            return False

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
                with mutation_transaction(project_root, "browser-save", [path]):
                    write_text_atomic(path, content)
                self.server.coordinator.build_now(f"editor-save:{path.name}")  # type: ignore[attr-defined]
                response = _file_payload(project_root, path)
                checkpoint = maybe_auto_checkpoint(
                    project_root,
                    trigger="browser-save",
                    message=f"save: update {path.resolve().relative_to(project_root.resolve()).as_posix()}",
                    target_paths=[path],
                )
                if checkpoint.get("committed"):
                    response["git_checkpoint"] = checkpoint.get("commit")
            except ValueError as exc:
                self._send_error_json(str(exc))
                return
            except OSError as exc:
                self._send_error_json(f"保存文件失败：{exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)
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
            if not self._authorized(parsed):
                self._send_error_json("unauthorized", status=HTTPStatus.UNAUTHORIZED)
                return
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
                if not self._terminal_available():
                    return
                self._handle_terminal_poll(parsed)
                return
            return super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized(parsed):
                self._send_error_json("unauthorized", status=HTTPStatus.UNAUTHORIZED)
                return
            if parsed.path == "/api/terminal/open":
                if not self._terminal_available():
                    return
                self._handle_terminal_open()
                return
            if parsed.path == "/api/terminal/input":
                if not self._terminal_available():
                    return
                self._handle_terminal_input()
                return
            if parsed.path == "/api/terminal/resize":
                if not self._terminal_available():
                    return
                self._handle_terminal_resize()
                return
            if parsed.path == "/api/system-terminal/open":
                if not self._terminal_available():
                    return
                self._handle_system_terminal_open()
                return
            if parsed.path == "/api/rebuild":
                self._handle_rebuild()
                return
            self._send_error_json("不支持的 POST 接口", status=HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized(parsed):
                self._send_error_json("unauthorized", status=HTTPStatus.UNAUTHORIZED)
                return
            if parsed.path == "/api/file":
                self._handle_file_put()
                return
            self._send_error_json("不支持的 PUT 接口", status=HTTPStatus.NOT_FOUND)

    return partial(BrowserHandler, directory=str(project_root))  # type: ignore[return-value]


def _host_is_loopback(host: str) -> bool:
    normalized = str(host or "").strip()
    if not normalized:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_loopback for address in addresses)


def _print_browser_url(url: str) -> None:
    if sys.stdout.isatty():
        print(f"[ok] browser url: {url}", flush=True)
        return
    print("[ok] browser URL is available only in the interactive starting terminal.", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the research navigator browser.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="Allow remote network binding despite unauthenticated file-write and shell endpoints.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--enable-terminal",
        action="store_true",
        help="Enable the optional browser and system terminal integrations.",
    )
    add_browser_project_root_argument(parser)
    parser.add_argument(
        "--debounce-seconds",
        type=float,
        default=WATCH_DEBOUNCE_SECONDS,
        help="Delay after the last watched event before rebuilding (default: 1.5).",
    )
    args = parser.parse_args()
    if not args.allow_non_loopback and not _host_is_loopback(args.host):
        parser.error(
            f"refusing non-loopback host {args.host!r}: the workbench exposes unauthenticated file-write and shell endpoints; "
            "pass --allow-non-loopback only when remote access is explicit and intentional"
        )
    return args


def main() -> None:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    if WATCHDOG_IMPORT_ERROR is not None or Observer is None:
        raise SystemExit(
            "research-navigator browser serve requires the `watchdog` package. "
            "Use the remembered research runtime or install watchdog in the active interpreter."
        )
    coordinator = BrowserBuildCoordinator(project_root, debounce_seconds=args.debounce_seconds)
    terminal_manager = TerminalManager(project_root) if args.enable_terminal else None
    auth_token = secrets.token_urlsafe(32)
    initial_status = safe_rebuild(project_root, script_path=Path(__file__))
    print(f"[ok] initial build: {initial_status.get('build_status')}", flush=True)

    handler_cls = create_handler(project_root=project_root)
    server = BrowserHTTPServer(
        (args.host, args.port),
        handler_cls,
        project_root=project_root,
        coordinator=coordinator,
        terminal_manager=terminal_manager,
        terminal_enabled=args.enable_terminal,
        auth_token=auth_token,
    )
    observer = Observer()
    observer.schedule(ResearchNavigatorEventHandler(project_root, coordinator), str(kb_root(project_root).parents[1]), recursive=True)
    observer.start()
    coordinator.start()

    def shutdown(*_: object) -> None:
        observer.stop()
        coordinator.stop()
        if terminal_manager is not None:
            terminal_manager.close()
        threading.Thread(target=server.shutdown, name="research-navigator-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(f"[ok] serving project root: {project_root}", flush=True)
    _print_browser_url(browser_url(args.host, args.port, project_root, token=auth_token))
    print(f"[ok] version url: {version_url(args.host, args.port)}", flush=True)
    print(f"[ok] runtime log: {server_log_path(project_root)}", flush=True)
    try:
        server.serve_forever()
    finally:
        observer.stop()
        observer.join(timeout=3.0)
        coordinator.stop()
        if terminal_manager is not None:
            terminal_manager.close()
        server.server_close()


if __name__ == "__main__":
    ensure_managed_runtime(project_root_from_script(Path(__file__)))
    main()

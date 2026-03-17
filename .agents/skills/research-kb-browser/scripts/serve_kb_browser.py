#!/usr/bin/env python3
"""Serve the research knowledge browser and rebuild it on watched changes."""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
)


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
    if resolved.suffix.lower() not in {".yaml", ".yml", ".md"}:
        return False
    if _is_relative_to(resolved, research_root / "library"):
        return True
    if _is_relative_to(resolved, research_root / "programs"):
        return True
    return resolved == (research_root / "memory" / "domain-profile.yaml")


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
            print(
                f"[watch] rebuild {state}: {', '.join(reasons[:3])}",
                flush=True,
            )


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


class BrowserHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_class, *, project_root: Path) -> None:
        super().__init__(server_address, handler_class)
        self.project_root = project_root


def create_handler(*, project_root: Path) -> type[SimpleHTTPRequestHandler]:
    class BrowserHandler(SimpleHTTPRequestHandler):
        server_version = "ResearchKBBrowser/1.0"

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

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/healthz":
                self._handle_health()
                return
            if parsed.path == "/api/version":
                self._handle_version()
                return
            return super().do_GET()

    return partial(BrowserHandler, directory=str(project_root))  # type: ignore[return-value]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the research knowledge browser.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port (default: 8787)")
    parser.add_argument(
        "--project-root",
        default="",
        help="Project root path. Auto-detected when omitted.",
    )
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
    initial_status = safe_rebuild(project_root, script_path=Path(__file__))
    print(f"[ok] initial build: {initial_status.get('build_status')}", flush=True)

    handler_cls = create_handler(project_root=project_root)
    server = BrowserHTTPServer((args.host, args.port), handler_cls, project_root=project_root)
    observer = Observer()
    observer.schedule(ResearchKbEventHandler(project_root, coordinator), str(project_root / "doc" / "research"), recursive=True)
    observer.start()
    coordinator.start()

    def shutdown(*_: object) -> None:
        observer.stop()
        coordinator.stop()
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
        server.server_close()


if __name__ == "__main__":
    main()

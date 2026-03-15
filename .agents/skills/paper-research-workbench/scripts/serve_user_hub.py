#!/usr/bin/env python3
"""Serve user hub with local markdown read/write API."""

from __future__ import annotations

import argparse
import json
import threading
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from _paper_utils import find_project_root


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class IdleAwareThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server that shuts itself down after a period of inactivity."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class,
        *,
        idle_timeout_seconds: float,
        idle_poll_seconds: float = 2.0,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.idle_timeout_seconds = max(15.0, float(idle_timeout_seconds))
        self.idle_poll_seconds = max(0.5, float(idle_poll_seconds))
        self.last_activity_monotonic = time.monotonic()
        self._idle_stop_event = threading.Event()
        self._idle_monitor = threading.Thread(
            target=self._monitor_idle_shutdown,
            name="paper-hub-idle-monitor",
            daemon=True,
        )

    def mark_activity(self) -> None:
        self.last_activity_monotonic = time.monotonic()

    def start_idle_monitor(self) -> None:
        if not self._idle_monitor.is_alive():
            self._idle_monitor.start()

    def stop_idle_monitor(self) -> None:
        self._idle_stop_event.set()

    def _monitor_idle_shutdown(self) -> None:
        while not self._idle_stop_event.wait(self.idle_poll_seconds):
            idle_for = time.monotonic() - self.last_activity_monotonic
            if idle_for < self.idle_timeout_seconds:
                continue
            print(
                f"[OK] idle timeout reached after {idle_for:.1f}s without requests, shutting down hub server",
                flush=True,
            )
            self.shutdown()
            return


def create_handler(*, project_root: Path) -> type[SimpleHTTPRequestHandler]:
    user_root = (project_root / "doc" / "papers" / "user").resolve()

    class HubHandler(SimpleHTTPRequestHandler):
        server_version = "PaperHubServer/1.0"

        def _touch_activity(self) -> None:
            server = getattr(self, "server", None)
            if server and hasattr(server, "mark_activity"):
                server.mark_activity()

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

        def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _resolve_md_path(self, raw: str) -> Path | None:
            value = str(raw or "").strip()
            if not value:
                return None
            normalized = value.lstrip("/")
            resolved = (project_root / normalized).resolve()
            if not _is_relative_to(resolved, user_root):
                return None
            if resolved.suffix.lower() != ".md":
                return None
            return resolved

        def _handle_get_md(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            target = self._resolve_md_path((query.get("path") or [""])[0])
            if target is None:
                self._send_json({"ok": False, "error": "invalid path"}, HTTPStatus.BAD_REQUEST)
                return
            if not target.exists():
                self._send_json({"ok": False, "error": "file not found"}, HTTPStatus.NOT_FOUND)
                return
            content = target.read_text(encoding="utf-8")
            rel = target.relative_to(project_root).as_posix()
            self._send_json({"ok": True, "path": rel, "content": content})

        def _handle_healthz(self) -> None:
            self._send_json(
                {
                    "ok": True,
                    "service": "paper-research-workbench",
                    "project_root": str(project_root),
                    "user_root": str(user_root),
                }
            )

        def _handle_put_md(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/md":
                self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
                return

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                self._send_json({"ok": False, "error": "empty body"}, HTTPStatus.BAD_REQUEST)
                return

            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return

            target = self._resolve_md_path(payload.get("path", ""))
            if target is None:
                self._send_json({"ok": False, "error": "invalid path"}, HTTPStatus.BAD_REQUEST)
                return

            content = payload.get("content")
            if not isinstance(content, str):
                self._send_json({"ok": False, "error": "content must be string"}, HTTPStatus.BAD_REQUEST)
                return

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            rel = target.relative_to(project_root).as_posix()
            self._send_json({"ok": True, "path": rel, "bytes": len(content.encode('utf-8'))})

        def do_GET(self) -> None:  # noqa: N802
            self._touch_activity()
            parsed = urlparse(self.path)
            if parsed.path == "/api/md":
                self._handle_get_md()
                return
            if parsed.path == "/api/healthz":
                self._handle_healthz()
                return
            return super().do_GET()

        def do_PUT(self) -> None:  # noqa: N802
            self._touch_activity()
            parsed = urlparse(self.path)
            if parsed.path == "/api/md":
                self._handle_put_md()
                return
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            super().log_message(format, *args)

    return partial(HubHandler, directory=str(project_root))  # type: ignore[return-value]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve paper user hub with markdown editing API.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=90.0,
        help="Auto-stop after this many idle seconds without requests (default: 90)",
    )
    parser.add_argument(
        "--project-root",
        default="",
        help="Project root path. Auto-detected when omitted.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.project_root:
        project_root = Path(args.project_root).resolve()
    else:
        project_root = find_project_root(Path(__file__).resolve())

    handler_cls = create_handler(project_root=project_root)
    server = IdleAwareThreadingHTTPServer(
        (args.host, args.port),
        handler_cls,
        idle_timeout_seconds=args.idle_timeout,
    )
    base = f"http://{args.host}:{args.port}"
    print(f"[OK] serving project root: {project_root}")
    print(f"[OK] hub url: {base}/doc/papers/user/index.html")
    print(f"[OK] graph url: {base}/doc/papers/user/graph.html")
    print("[OK] markdown api: GET/PUT /api/md?path=doc/papers/user/papers/<paper-id>/note.md")
    print(f"[OK] idle timeout: {server.idle_timeout_seconds:.0f}s")
    server.start_idle_monitor()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_idle_monitor()
        server.server_close()


if __name__ == "__main__":
    main()

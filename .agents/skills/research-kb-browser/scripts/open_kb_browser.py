#!/usr/bin/env python3
"""Open the research knowledge browser, starting the daemon if needed."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from kb_browser_lib import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    READY_TIMEOUT_SECONDS,
    SERVICE_NAME,
    browser_url,
    choose_browser_runtime,
    choose_port,
    compact_text,
    is_matching_service,
    launcher_state_path,
    project_root_from_script,
    read_json,
    server_log_path,
    version_url,
    wait_until_ready,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start or reuse the research knowledge browser daemon.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Preferred port (default: 8787)")
    parser.add_argument("--project-root", default="", help="Project root path. Auto-detected when omitted.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")
    parser.add_argument("--print-url", action="store_true", help="Print the final browser URL.")
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=READY_TIMEOUT_SECONDS,
        help=f"Wait timeout in seconds for daemon readiness (default: {READY_TIMEOUT_SECONDS:.0f}).",
    )
    return parser.parse_args()


def tail_text(path: Path, max_lines: int = 40, max_chars: int = 5000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    if len(tail) <= max_chars:
        return tail
    return tail[-max_chars:]


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    state_path = launcher_state_path(project_root)
    previous_state = read_json(state_path) or {}
    log_path = server_log_path(project_root)
    ready_timeout = max(1.0, float(args.ready_timeout))
    preferred_port = args.port
    previous_port = int(previous_state.get("port") or 0)
    if args.port == DEFAULT_PORT and previous_port and is_matching_service(args.host, previous_port, project_root):
        preferred_port = previous_port
    port, reused = choose_port(args.host, preferred_port, project_root)
    pid = int(previous_state.get("pid") or 0) if reused and previous_port == port else 0
    runtime_python = ""
    if not reused:
        runtime_python = choose_browser_runtime(project_root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        script_path = Path(__file__).resolve().with_name("serve_kb_browser.py")
        with log_path.open("ab") as handle:
            process = subprocess.Popen(
                [
                    runtime_python,
                    str(script_path),
                    "--host",
                    args.host,
                    "--port",
                    str(port),
                    "--project-root",
                    str(project_root),
                ],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid = process.pid
        write_json_atomic(
            state_path,
            {
                "service": SERVICE_NAME,
                "project_root": str(project_root),
                "host": args.host,
                "port": port,
                "pid": pid,
                "browser_url": browser_url(args.host, port, project_root),
                "version_url": version_url(args.host, port),
                "log_path": str(log_path),
                "runtime_python": runtime_python,
                "status": "starting",
                "ready_timeout_seconds": ready_timeout,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        try:
            wait_until_ready(args.host, port, project_root, timeout_seconds=ready_timeout)
        except Exception as exc:
            exit_code = process.poll()
            lines = [
                f"{SERVICE_NAME} did not become ready within {ready_timeout:.1f}s at {args.host}:{port}.",
            ]
            if exit_code is not None:
                lines.append(f"Daemon exited early with code {exit_code}.")
            log_tail = tail_text(log_path)
            if log_tail:
                lines.append("Recent server log tail:")
                lines.append(log_tail)
            detail = "\n".join(lines)
            write_json_atomic(
                state_path,
                {
                    "service": SERVICE_NAME,
                    "project_root": str(project_root),
                    "host": args.host,
                    "port": port,
                    "pid": pid,
                    "browser_url": browser_url(args.host, port, project_root),
                    "version_url": version_url(args.host, port),
                    "log_path": str(log_path),
                    "runtime_python": runtime_python,
                    "status": "failed",
                    "ready_timeout_seconds": ready_timeout,
                    "last_error": compact_text(detail, limit=400),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            raise RuntimeError(detail) from exc
    url = browser_url(args.host, port, project_root)
    write_json_atomic(
        state_path,
        {
            "service": SERVICE_NAME,
            "project_root": str(project_root),
            "host": args.host,
            "port": port,
            "pid": pid,
            "browser_url": url,
            "version_url": version_url(args.host, port),
            "log_path": str(log_path),
            "runtime_python": runtime_python or str(previous_state.get("runtime_python") or ""),
            "status": "reused" if reused else "started",
            "ready_timeout_seconds": ready_timeout,
            "last_error": "",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    if not args.no_browser:
        webbrowser.open(url)
    if args.print_url:
        print(url)
    else:
        action = "reused" if reused else "started"
        print(f"[ok] {action} {SERVICE_NAME} at {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Open the research knowledge browser, starting the daemon if needed."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from kb_browser_lib import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    SERVICE_NAME,
    browser_url,
    choose_browser_runtime,
    choose_port,
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    state_path = launcher_state_path(project_root)
    previous_state = read_json(state_path) or {}
    preferred_port = args.port
    previous_port = int(previous_state.get("port") or 0)
    if args.port == DEFAULT_PORT and previous_port and is_matching_service(args.host, previous_port, project_root):
        preferred_port = previous_port
    port, reused = choose_port(args.host, preferred_port, project_root)
    pid = int(previous_state.get("pid") or 0) if reused and previous_port == port else 0
    runtime_python = ""
    if not reused:
        runtime_python = choose_browser_runtime(project_root)
        log_path = server_log_path(project_root)
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
        wait_until_ready(args.host, port, project_root)
    url = browser_url(args.host, port)
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
            "log_path": str(server_log_path(project_root)),
            "runtime_python": runtime_python or str(previous_state.get("runtime_python") or ""),
            "status": "reused" if reused else "started",
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

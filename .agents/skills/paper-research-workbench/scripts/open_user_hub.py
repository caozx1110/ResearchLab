#!/usr/bin/env python3
"""Launch the paper user hub in the background and open it in a browser."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from _paper_utils import ensure_dir, find_project_root

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_IDLE_TIMEOUT_SECONDS = 90.0
PORT_SCAN_LIMIT = 12
READY_TIMEOUT_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the paper hub server in the background and open the browser.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Preferred port (default: 8765)")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=DEFAULT_IDLE_TIMEOUT_SECONDS,
        help="Auto-stop after this many idle seconds without requests (default: 90)",
    )
    parser.add_argument(
        "--project-root",
        default="",
        help="Project root path. Auto-detected when omitted.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start or reuse the server but do not open a browser window.",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the final hub URL.",
    )
    return parser.parse_args()


def runtime_dir(project_root: Path) -> Path:
    return project_root / "doc" / "papers" / "user" / ".runtime"


def runtime_state_path(project_root: Path) -> Path:
    return runtime_dir(project_root) / "launcher-state.json"


def runtime_log_path(project_root: Path) -> Path:
    return runtime_dir(project_root) / "hub-server.log"


def write_runtime_state(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_runtime_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def hub_url(host: str, port: int) -> str:
    return f"{base_url(host, port)}/doc/papers/user/index.html"


def health_url(host: str, port: int) -> str:
    return f"{base_url(host, port)}/api/healthz"


def fetch_health(host: str, port: int, timeout: float = 0.6) -> dict[str, Any] | None:
    request = urllib.request.Request(health_url(host, port), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def port_is_busy(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_matching_hub(host: str, port: int, project_root: Path) -> bool:
    payload = fetch_health(host, port)
    return bool(
        payload
        and payload.get("ok") is True
        and payload.get("service") == "paper-research-workbench"
        and payload.get("project_root") == str(project_root)
    )


def choose_port(host: str, preferred_port: int, project_root: Path) -> tuple[int, bool]:
    if is_matching_hub(host, preferred_port, project_root):
        return preferred_port, True
    if not port_is_busy(host, preferred_port):
        return preferred_port, False

    for candidate in range(preferred_port + 1, preferred_port + PORT_SCAN_LIMIT + 1):
        if is_matching_hub(host, candidate, project_root):
            return candidate, True
        if not port_is_busy(host, candidate):
            return candidate, False

    raise RuntimeError(
        f"Could not find a free hub port near {preferred_port}. Please close the conflicting service and retry.",
    )


def launch_server(project_root: Path, host: str, port: int, idle_timeout_seconds: float) -> int:
    script_path = Path(__file__).resolve().with_name("serve_user_hub.py")
    log_path = runtime_log_path(project_root)
    ensure_dir(log_path.parent)

    with log_path.open("ab") as handle:
        process = subprocess.Popen(
            [
                sys.executable,
                str(script_path),
                "--host",
                host,
                "--port",
                str(port),
                "--idle-timeout",
                str(idle_timeout_seconds),
                "--project-root",
                str(project_root),
            ],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process.pid


def wait_until_ready(host: str, port: int, project_root: Path, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_matching_hub(host, port, project_root):
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        f"Hub server did not become ready within {timeout_seconds:.1f}s. Check {runtime_log_path(project_root)}.",
    )


def maybe_open_browser(url: str, no_browser: bool) -> None:
    if no_browser:
        return
    webbrowser.open(url)


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root(Path(__file__).resolve())

    state_path = runtime_state_path(project_root)
    previous_state = read_runtime_state(state_path) or {}
    previous_port = int(previous_state.get("port") or 0)
    preferred_port = args.port

    should_prefer_previous_port = args.port == DEFAULT_PORT
    if should_prefer_previous_port and previous_port and is_matching_hub(args.host, previous_port, project_root):
        preferred_port = previous_port

    port, reused = choose_port(args.host, preferred_port, project_root)
    if reused and previous_port == port:
        pid = int(previous_state.get("pid") or 0)
    else:
        pid = launch_server(project_root, args.host, port, args.idle_timeout)
        wait_until_ready(args.host, port, project_root, READY_TIMEOUT_SECONDS)

    url = hub_url(args.host, port)
    write_runtime_state(
        state_path,
        {
            "service": "paper-research-workbench",
            "project_root": str(project_root),
            "host": args.host,
            "port": port,
            "pid": pid,
            "hub_url": url,
            "log_path": str(runtime_log_path(project_root)),
            "idle_timeout_seconds": float(args.idle_timeout),
            "status": "reused" if reused else "started",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )

    if args.print_url:
        print(url)
    else:
        action = "Reused" if reused else "Started"
        print(f"[OK] {action} hub server at {url}")

    maybe_open_browser(url, args.no_browser)


if __name__ == "__main__":
    main()

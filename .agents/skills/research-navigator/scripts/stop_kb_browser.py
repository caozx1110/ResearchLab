#!/usr/bin/env python3
"""Stop the research navigator browser daemon."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

from kb_browser_lib import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PORT_SCAN_LIMIT,
    SERVICE_NAME,
    add_browser_project_root_argument,
    fetch_json,
    health_url,
    launcher_state_path,
    project_root_from_script,
    read_json,
)
from research.bootstrap import ensure_managed_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop the research navigator browser daemon.")
    add_browser_project_root_argument(parser)
    return parser.parse_args()


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def discover_service_pid(project_root: Path, host: str, preferred_port: int) -> int:
    candidates: list[int] = []
    seen: set[int] = set()

    def add_port(value: int) -> None:
        if value > 0 and value not in seen:
            candidates.append(value)
            seen.add(value)

    add_port(preferred_port)
    add_port(DEFAULT_PORT)
    for offset in range(PORT_SCAN_LIMIT + 1):
        add_port(DEFAULT_PORT + offset)

    for port in candidates:
        health = fetch_json(health_url(host, port), timeout=0.3) or {}
        if not (
            health.get("ok") is True
            and health.get("service") == SERVICE_NAME
            and health.get("project_root") == str(project_root)
        ):
            continue
        pid = int(health.get("pid") or 0)
        if pid > 0:
            return pid
        try:
            completed = subprocess.run(
                ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return 0
        for line in completed.stdout.splitlines():
            try:
                candidate_pid = int(line.strip())
            except ValueError:
                continue
            if candidate_pid > 0:
                return candidate_pid
    return 0


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    state_path = launcher_state_path(project_root)
    state = read_json(state_path) or {}
    pid = int(state.get("pid") or 0)
    if not pid_alive(pid):
        pid = discover_service_pid(
            project_root,
            str(state.get("host") or DEFAULT_HOST),
            int(state.get("port") or DEFAULT_PORT),
        )
    if not pid_alive(pid):
        if state_path.exists():
            state_path.unlink()
        print("[ok] research-navigator browser was not running")
        return 0
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not pid_alive(pid):
            break
        time.sleep(0.2)
    if pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
    if state_path.exists():
        state_path.unlink()
    print("[ok] stopped research-navigator browser")
    return 0


if __name__ == "__main__":
    ensure_managed_runtime(project_root_from_script(Path(__file__)))
    raise SystemExit(main())

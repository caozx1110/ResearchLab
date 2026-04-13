#!/usr/bin/env python3
"""Report status for the research knowledge browser daemon."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from kb_browser_lib import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PORT_SCAN_LIMIT,
    SERVICE_NAME,
    browser_url,
    fetch_json,
    health_url,
    launcher_state_path,
    load_build_status,
    project_root_from_script,
    read_json,
    server_log_path,
    version_url,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show research knowledge browser status.")
    parser.add_argument("--project-root", default="", help="Project root path. Auto-detected when omitted.")
    parser.add_argument("--json", action="store_true", help="Print status as JSON.")
    return parser.parse_args()


def discover_running(project_root: Path, host: str, state_port: int) -> tuple[int, dict]:
    candidates: list[int] = []
    seen: set[int] = set()

    def add_port(value: int) -> None:
        if value > 0 and value not in seen:
            candidates.append(value)
            seen.add(value)

    add_port(state_port)
    add_port(DEFAULT_PORT)
    for offset in range(PORT_SCAN_LIMIT + 1):
        add_port(DEFAULT_PORT + offset)

    for port in candidates:
        health = fetch_json(health_url(host, port), timeout=0.25) or {}
        if not (
            health.get("ok") is True
            and health.get("service") == SERVICE_NAME
            and health.get("project_root") == str(project_root)
        ):
            continue
        version_payload = fetch_json(version_url(host, port), timeout=0.6) or {}
        return port, version_payload
    return 0, {}


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    launcher_state = read_json(launcher_state_path(project_root)) or {}
    build_status = load_build_status(project_root)
    host = str(launcher_state.get("host") or DEFAULT_HOST)
    state_port = int(launcher_state.get("port") or 0)
    version_payload = fetch_json(str(launcher_state.get("version_url") or "")) if launcher_state.get("version_url") else None
    running = bool(version_payload and version_payload.get("service") == SERVICE_NAME)
    if not running:
        discovered_port, discovered_version = discover_running(project_root, host, state_port)
        if discovered_port:
            running = True
            if discovered_version:
                version_payload = discovered_version
            healed_state = {
                "service": SERVICE_NAME,
                "project_root": str(project_root),
                "host": host,
                "port": discovered_port,
                "pid": int(launcher_state.get("pid") or 0) if discovered_port == state_port else 0,
                "browser_url": browser_url(host, discovered_port, project_root),
                "version_url": version_url(host, discovered_port),
                "log_path": str(launcher_state.get("log_path") or server_log_path(project_root)),
                "runtime_python": str(launcher_state.get("runtime_python") or ""),
                "status": "discovered",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            write_json_atomic(launcher_state_path(project_root), healed_state)
            launcher_state = healed_state

    payload = {
        "service": SERVICE_NAME,
        "running": running,
        "host": launcher_state.get("host", host),
        "port": launcher_state.get("port", 0),
        "pid": launcher_state.get("pid", 0),
        "browser_url": launcher_state.get("browser_url", ""),
        "snapshot_version": (version_payload or build_status).get("snapshot_version", ""),
        "generated_at": (version_payload or build_status).get("generated_at", ""),
        "build_status": (version_payload or build_status).get("build_status", ""),
        "last_error": (version_payload or build_status).get("last_error", ""),
        "log_path": launcher_state.get("log_path", ""),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"service: {payload['service']}")
        print(f"running: {payload['running']}")
        print(f"host: {payload['host']}")
        print(f"port: {payload['port']}")
        print(f"pid: {payload['pid']}")
        print(f"browser_url: {payload['browser_url']}")
        print(f"snapshot_version: {payload['snapshot_version']}")
        print(f"generated_at: {payload['generated_at']}")
        print(f"build_status: {payload['build_status']}")
        print(f"last_error: {payload['last_error']}")
        print(f"log_path: {payload['log_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

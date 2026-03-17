#!/usr/bin/env python3
"""Report status for the research knowledge browser daemon."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kb_browser_lib import (
    SERVICE_NAME,
    fetch_json,
    launcher_state_path,
    load_build_status,
    project_root_from_script,
    read_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show research knowledge browser status.")
    parser.add_argument("--project-root", default="", help="Project root path. Auto-detected when omitted.")
    parser.add_argument("--json", action="store_true", help="Print status as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    launcher_state = read_json(launcher_state_path(project_root)) or {}
    build_status = load_build_status(project_root)
    version_payload = fetch_json(str(launcher_state.get("version_url") or "")) if launcher_state.get("version_url") else None
    running = bool(version_payload and version_payload.get("service") == SERVICE_NAME)
    payload = {
        "service": SERVICE_NAME,
        "running": running,
        "host": launcher_state.get("host", ""),
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

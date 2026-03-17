#!/usr/bin/env python3
"""Stop the research knowledge browser daemon."""

from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path

from kb_browser_lib import launcher_state_path, project_root_from_script, read_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop the research knowledge browser daemon.")
    parser.add_argument("--project-root", default="", help="Project root path. Auto-detected when omitted.")
    return parser.parse_args()


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    state_path = launcher_state_path(project_root)
    state = read_json(state_path) or {}
    pid = int(state.get("pid") or 0)
    if not pid_alive(pid):
        if state_path.exists():
            state_path.unlink()
        print("[ok] research-kb-browser was not running")
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
    print("[ok] stopped research-kb-browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

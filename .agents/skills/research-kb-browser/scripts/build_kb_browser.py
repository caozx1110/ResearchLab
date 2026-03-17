#!/usr/bin/env python3
"""Build a static snapshot for the research knowledge browser."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kb_browser_lib import build_site_once, index_html_path, project_root_from_script, write_failure_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the research knowledge browser snapshot.")
    parser.add_argument("--project-root", default="", help="Project root path. Auto-detected when omitted.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_from_script(Path(__file__), explicit_root=args.project_root)
    try:
        snapshot, _ = build_site_once(project_root, script_path=Path(__file__))
    except Exception as exc:  # noqa: BLE001
        status = write_failure_status(project_root, exc)
        print(f"[error] build failed: {status.get('last_error', '')}", file=sys.stderr)
        return 1
    print(
        f"[ok] built {index_html_path(project_root).relative_to(project_root).as_posix()} "
        f"(version={snapshot.get('snapshot_version', '')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

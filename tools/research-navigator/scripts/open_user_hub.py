#!/usr/bin/env python3
"""Backward-compatible alias for opening the research navigator browser.

Legacy workflows used `paper-research-workbench/scripts/open_user_hub.py`.
This script keeps that command shape available while delegating to the
current research-navigator browser launcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from kb_browser_lib import project_root_from_script
from open_kb_browser import main
from research.bootstrap import ensure_managed_runtime


if __name__ == "__main__":
    ensure_managed_runtime(project_root_from_script(Path(__file__)))
    print(
        "[shim] legacy research-navigator entrypoint; delegating to the browser launcher.",
        file=sys.stderr,
        flush=True,
    )
    raise SystemExit(main())

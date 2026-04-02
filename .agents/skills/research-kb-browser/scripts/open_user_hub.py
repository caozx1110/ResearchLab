#!/usr/bin/env python3
"""Backward-compatible alias for opening the research knowledge browser.

Legacy workflows used `paper-research-workbench/scripts/open_user_hub.py`.
This script keeps that command shape available while delegating to the
current research-kb-browser launcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from open_kb_browser import main


if __name__ == "__main__":
    raise SystemExit(main())

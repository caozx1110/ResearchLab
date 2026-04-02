#!/usr/bin/env python3
"""Legacy user-hub entrypoint that forwards to research-kb-browser."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    target = Path(__file__).resolve().parents[2] / "research-kb-browser" / "scripts" / "open_user_hub.py"
    if not target.exists():
        raise SystemExit(
            "Legacy shim failed: expected research-kb-browser entrypoint at "
            f"{target}"
        )
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

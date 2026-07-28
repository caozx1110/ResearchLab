#!/usr/bin/env python3
"""Compatibility launcher for the canonical unit-analyst repo implementation."""

from pathlib import Path
import runpy


def main() -> None:
    target = Path(__file__).resolve().parents[2] / "unit-analyst" / "scripts" / "repo.py"
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()

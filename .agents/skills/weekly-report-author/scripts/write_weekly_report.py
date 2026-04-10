#!/usr/bin/env python3
"""Write a weekly report for a research program."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any


def load_conductor_module() -> Any:
    skills_root = Path(__file__).resolve().parents[2]
    module_path = skills_root / "research-conductor" / "scripts" / "manage_workspace.py"
    if not module_path.exists():
        raise SystemExit(f"Missing research-conductor implementation: {module_path}")
    spec = importlib.util.spec_from_file_location("research_conductor_manage_workspace", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", default="", help="Optional inclusive UTC end date in YYYY-MM-DD format")
    parser.add_argument("--max-detailed-papers", type=int, default=8)
    parser.add_argument("--max-detailed-repos", type=int, default=6)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    module = load_conductor_module()
    return int(module.write_weekly_report(args))


if __name__ == "__main__":
    raise SystemExit(main())

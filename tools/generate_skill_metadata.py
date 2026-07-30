#!/usr/bin/env python3
"""Generate or check tracked OpenAI metadata for discoverable research skills."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
LIB_ROOT = REPO_ROOT / "runtime" / "lib"
sys.path.insert(0, str(LIB_ROOT))

from research.skill_validator import generated_metadata_outputs  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=REPO_ROOT / "skills",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if a generated file is missing or differs; do not write.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    skills_root = args.skills_root.resolve()
    errors: list[str] = []
    outputs = generated_metadata_outputs(skills_root, errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    changed: list[Path] = []
    for path, expected in sorted(outputs.items()):
        try:
            current = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        except OSError as exc:
            print(f"ERROR: {path}: cannot read file: {exc}", file=sys.stderr)
            return 1
        if current == expected:
            continue
        changed.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")

    if args.check and changed:
        for path in changed:
            print(f"ERROR: generated metadata drift: {path}", file=sys.stderr)
        return 1
    action = "checked" if args.check else "generated"
    print(f"{action.capitalize()} {len(outputs)} skill metadata files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

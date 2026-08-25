#!/usr/bin/env python3
"""Read-only post-install validation for the five Research Vault skills."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SHIPPING_SKILLS = frozenset(
    {
        "research-analysis",
        "research-capture",
        "research-review",
        "research-vault",
        "research-workbench",
    }
)

ENTRYPOINTS = (
    "research-vault/scripts/vault.py",
    "research-capture/scripts/capture.py",
    "research-analysis/scripts/analysis.py",
    "research-review/scripts/review.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-lib", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--skills", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sys.path.insert(0, str(args.runtime_lib))
    from research.v2_bootstrap import ensure_managed_runtime

    ensure_managed_runtime(args.workspace, allow_provision=True)
    import yaml

    metadata = yaml.safe_load((args.skills / "metadata.yaml").read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("skills"), dict):
        raise SystemExit("shipping skill metadata is invalid")
    if set(metadata["skills"]) != SHIPPING_SKILLS:
        raise SystemExit("shipping skill metadata does not match the five-skill contract")
    for name in SHIPPING_SKILLS:
        if not (args.skills / name / "SKILL.md").is_file():
            raise SystemExit(f"missing shipping skill: {name}")
    for relative in ENTRYPOINTS:
        result = subprocess.run(
            [sys.executable, "-B", str(args.skills / relative), "--help"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"skill entrypoint failed read-only smoke: {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

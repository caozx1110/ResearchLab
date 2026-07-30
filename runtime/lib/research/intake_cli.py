from __future__ import annotations

import argparse
from typing import Any

SOURCE_KIND_CHOICES = ("paper", "repo", "dataset", "blog")
MATURITY_CHOICES = ("lightweight", "complete")


def add_intake_add_arguments(
    parser: argparse.ArgumentParser,
    *,
    source_required: bool = False,
    include_stage_options: bool = False,
) -> argparse.ArgumentParser:
    parser.add_argument("--kind", required=True, choices=SOURCE_KIND_CHOICES)
    parser.add_argument("--source", required=source_required, default="" if not source_required else None)
    parser.add_argument("--maturity", default="lightweight", choices=MATURITY_CHOICES)
    parser.add_argument("--title", default="")
    if include_stage_options:
        parser.add_argument("--stage-id", default="")
        parser.add_argument("--candidate-id", default="")
    parser.add_argument("--pool", action="append", default=[])
    return parser


def intake_add_argv(args: argparse.Namespace | Any) -> list[str]:
    argv = [
        "add",
        "--kind",
        str(args.kind),
        "--source",
        str(args.source),
        "--maturity",
        str(args.maturity),
    ]
    if getattr(args, "title", ""):
        argv.extend(["--title", str(args.title)])
    for pool in getattr(args, "pool", []) or []:
        argv.extend(["--pool", str(pool)])
    return argv

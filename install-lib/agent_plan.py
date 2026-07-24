#!/usr/bin/env python3
"""Render the installer's exact, reviewable Agent plan artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--source-strategy", required=True)
    parser.add_argument("--source-checkout", required=True)
    parser.add_argument("--source-origin", required=True)
    parser.add_argument("--source-branch", default="")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--target-record",
        nargs=5,
        action="append",
        default=[],
        metavar=("KIND", "VALUE", "PATH", "SOURCE", "CONDITION"),
    )
    parser.add_argument("--conflict", action="append", default=[])
    parser.add_argument("--apply-arg", action="append", default=[])
    return parser


def normalize_target(raw: dict[str, Any]) -> dict[str, Any]:
    operation = str(raw.get("operation") or "").strip()
    path = str(raw.get("path") or "").strip()
    if not operation or not path:
        raise ValueError("plan target requires operation and path")
    target: dict[str, Any] = {"operation": operation, "path": path}
    source = str(raw.get("source") or "").strip()
    if source:
        target["source"] = source
    condition = str(raw.get("condition") or "").strip()
    if condition:
        target["condition"] = condition
    return target


def main() -> int:
    args = build_parser().parse_args()
    output = Path(args.output).expanduser()
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise SystemExit("plan output must be a regular file or a new path")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise SystemExit("plan output parent must be an existing regular directory")

    targets: list[dict[str, Any]] = []
    for kind, value, path, source, condition in args.target_record:
        if kind == "fields":
            targets.append(
                normalize_target(
                    {"operation": value, "path": path, "source": source, "condition": condition}
                )
            )
            continue
        if kind == "json":
            loaded = json.loads(value)
            if not isinstance(loaded, dict):
                raise ValueError("target JSON must be an object")
            targets.append(normalize_target(loaded))
            continue
        raise ValueError(f"unsupported target record kind: {kind}")

    conditional = [target for target in targets if target.get("condition")]
    payload: dict[str, Any] = {
        "schema": 1,
        "install_name": "workspace-oss",
        "mode": "agent-plan",
        "zero_write_scope": "workspace-home-and-runtime",
        "action": args.action,
        "scope": args.scope,
        "tools": sorted(set(args.tool)),
        "workspace": args.workspace,
        "source": {
            "strategy": args.source_strategy,
            "checkout": args.source_checkout,
            "origin": args.source_origin,
            "branch": args.source_branch,
            "commit": args.source_commit,
        },
        "target_count": len(targets),
        "targets": targets,
        "conflicts": sorted(set(str(item) for item in args.conflict if str(item).strip())),
        "conditional_runtime_changes": conditional,
        "apply_contract": {
            "executable": "bash",
            "argv": args.apply_arg,
            "requires_same_source_commit": args.source_commit,
            "requires_explicit_install_request": True,
            "requires_plan_review": True,
            "headless": True,
            "preserve_user_data": True,
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["plan_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
    print(payload["plan_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Private routed surface for explicit legacy workspace migration.

This is intentionally not reachable from the public ``kb`` dispatcher.  Its
JSON contains private receipts and must be consumed by the runtime Agent rather
than relayed to the user.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PRODUCT_ROOT = skills_dir.parent.parent
    lib = PRODUCT_ROOT / ".agents" / "lib"
else:
    PRODUCT_ROOT = skills_dir.parent
    lib = PRODUCT_ROOT / "runtime" / "lib"
if not (lib / "research" / "legacy_migration.py").is_file():
    raise SystemExit("Could not locate the managed migration runtime.")
sys.path.insert(0, str(lib))

from research.legacy_migration import (  # noqa: E402
    LegacyMigrationError,
    MigrationPlan,
    apply_legacy_migration,
    detect_legacy_layout,
    plan_legacy_migration,
    rollback_legacy_migration,
)


def _absolute_root(value: str) -> Path:
    candidate = Path(value).expanduser() if value else Path.cwd()
    return candidate.absolute()


def _read_plan(args: argparse.Namespace) -> MigrationPlan:
    if args.plan_json:
        return MigrationPlan.from_json(args.plan_json)
    content = Path(args.plan_file).read_text(encoding="utf-8")
    return MigrationPlan.from_json(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Private receipt-bound legacy workspace migration helper."
    )
    parser.add_argument("--root", default="")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("detect")
    subparsers.add_parser("plan")
    apply_parser = subparsers.add_parser("apply")
    plan_group = apply_parser.add_mutually_exclusive_group(required=True)
    plan_group.add_argument("--plan-json", default="")
    plan_group.add_argument("--plan-file", default="")
    apply_parser.add_argument("--user-authorization", required=True)
    apply_parser.add_argument(
        "--authorization-source",
        choices=("user_message",),
        required=True,
    )
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--recovery-material", required=True)
    rollback_parser.add_argument("--expected-receipt-sha256", required=True)
    rollback_parser.add_argument("--user-authorization", required=True)
    rollback_parser.add_argument(
        "--authorization-source",
        choices=("user_message",),
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _absolute_root(args.root)
    try:
        if args.command == "detect":
            payload = detect_legacy_layout(root).to_dict()
        elif args.command == "plan":
            payload = plan_legacy_migration(root).to_dict()
        elif args.command == "apply":
            payload = apply_legacy_migration(
                _read_plan(args),
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
            )
        elif args.command == "rollback":
            payload = rollback_legacy_migration(
                root,
                Path(args.recovery_material).absolute(),
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
                expected_receipt_sha256=args.expected_receipt_sha256,
            )
        else:  # pragma: no cover - argparse owns the closed command set
            raise LegacyMigrationError("unsupported private migration operation")
    except (LegacyMigrationError, OSError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

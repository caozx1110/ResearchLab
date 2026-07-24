#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate the managed research runtime.")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument
from research.core import project_root
from research.monitoring import (
    create_due_run,
    create_subscription,
    due_subscriptions,
    finish_run,
    load_run,
    load_subscription,
    set_subscription_status,
    transition_run,
)


MAX_PAYLOAD_BYTES = 512 * 1024
ACTIONS = {
    "create-subscription",
    "set-subscription-status",
    "create-due-run",
    "transition-run",
    "finish-run",
}


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        stat = path.lstat()
    except OSError:
        raise SystemExit("Research monitor input could not be read.") from None
    if path.is_symlink() or not path.is_file() or stat.st_size > MAX_PAYLOAD_BYTES:
        raise SystemExit("Research monitor input must be a bounded regular JSON file.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SystemExit("Research monitor input is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise SystemExit("Research monitor input must be a JSON object.")
    return payload


def _integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise SystemExit(f"Research monitor {field} must be an integer.")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Research monitor {field} must be an integer.") from None
    return result


def _apply(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    if action not in ACTIONS:
        raise SystemExit("Research monitor action is unsupported.")
    now = payload.get("now")
    if action == "create-subscription":
        if set(payload) - {"action", "subscription", "now"}:
            raise SystemExit("Research monitor request contains unsupported fields.")
        path = create_subscription(root, payload.get("subscription"), now=now)
        document = load_subscription(root, path.stem)
        return {"action": action, "subscription_id": document["id"], "revision": document["revision"]}
    if action == "set-subscription-status":
        if set(payload) - {"action", "subscription_id", "expected_revision", "status", "now"}:
            raise SystemExit("Research monitor request contains unsupported fields.")
        path = set_subscription_status(
            root,
            str(payload.get("subscription_id") or ""),
            expected_revision=_integer(payload.get("expected_revision"), field="expected_revision"),
            status=str(payload.get("status") or ""),
            now=now,
        )
        document = load_subscription(root, path.stem)
        return {"action": action, "subscription_id": document["id"], "revision": document["revision"]}
    if action == "create-due-run":
        if set(payload) - {"action", "subscription_id", "expected_subscription_revision", "now"}:
            raise SystemExit("Research monitor request contains unsupported fields.")
        path = create_due_run(
            root,
            str(payload.get("subscription_id") or ""),
            expected_subscription_revision=_integer(
                payload.get("expected_subscription_revision"),
                field="expected_subscription_revision",
            ),
            now=now,
        )
        document = load_run(root, path.stem)
        return {"action": action, "run_id": document["id"], "revision": document["revision"]}
    if action == "transition-run":
        if set(payload) - {"action", "run_id", "expected_revision", "state", "stop", "now"}:
            raise SystemExit("Research monitor request contains unsupported fields.")
        path = transition_run(
            root,
            str(payload.get("run_id") or ""),
            expected_revision=_integer(payload.get("expected_revision"), field="expected_revision"),
            state=str(payload.get("state") or ""),
            stop=payload.get("stop"),
            now=now,
        )
        document = load_run(root, path.stem)
        return {"action": action, "run_id": document["id"], "revision": document["revision"]}
    if set(payload) - {
        "action",
        "run_id",
        "expected_run_revision",
        "expected_subscription_revision",
        "state",
        "stop",
        "outputs",
        "review_outcomes",
        "now",
    }:
        raise SystemExit("Research monitor request contains unsupported fields.")
    path = finish_run(
        root,
        str(payload.get("run_id") or ""),
        expected_run_revision=_integer(
            payload.get("expected_run_revision"), field="expected_run_revision"
        ),
        expected_subscription_revision=_integer(
            payload.get("expected_subscription_revision"),
            field="expected_subscription_revision",
        ),
        state=str(payload.get("state") or ""),
        stop=payload.get("stop"),
        outputs=payload.get("outputs"),
        review_outcomes=payload.get("review_outcomes"),
        now=now,
    )
    document = load_run(root, path.stem)
    return {"action": action, "run_id": document["id"], "revision": document["revision"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private research-monitor state helper.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    due = subparsers.add_parser("due")
    due.add_argument("--now", default="")
    apply = subparsers.add_parser("apply")
    apply.add_argument("--input", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command == "due":
        result: Any = {"due": due_subscriptions(root, now=args.now or None)}
    else:
        result = _apply(root, _load_payload(args.input))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

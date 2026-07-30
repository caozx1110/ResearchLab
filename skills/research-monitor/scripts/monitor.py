#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

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
    set_outcome_disposition,
    set_subscription_status,
    transition_run,
    unresolved_monitor_outcomes,
)


MAX_PAYLOAD_BYTES = 512 * 1024
ACTIONS = {
    "create-subscription",
    "set-subscription-status",
    "create-due-run",
    "transition-run",
    "finish-run",
    "set-outcome-disposition",
}

TEMPLATE_KINDS = ("literature", "survey-freshness", "unit-recheck")

_TEMPLATE_TARGET_BLOCKS = {
    "literature": (
        "  # literature 目标：一个持续跟踪的检索问题（必填，自然语言）\n"
        "  target:\n"
        "    question: ''\n"
    ),
    "survey-freshness": (
        "  # survey-freshness 目标：被跟踪的综述文件（路径在 kb/synthesis/ 下）\n"
        "  target:\n"
        "    # 综述文件路径（必填）\n"
        "    survey_path: ''\n"
        "    # 该文件当前内容的小写 SHA-256（必填，64 位十六进制）\n"
        "    survey_sha256: ''\n"
    ),
    "unit-recheck": (
        "  # unit-recheck 目标：需要定期复核的已入库 unit\n"
        "  target:\n"
        "    # 至少一个真实存在的 canonical unit id\n"
        "    unit_ids:\n"
        "      - ''\n"
    ),
}


def render_subscription_template(kind: str, *, anchor_at: str) -> str:
    """One fill-in-and-apply YAML template mirroring create-subscription checks."""
    return (
        "# 研究监控订阅模板（由 monitor.py template 生成，可直接改填）\n"
        "# 用法：\n"
        "#   1. 按下方注释填写字段（保持 YAML 结构，不要新增未列出的字段——校验会拒绝未知字段）；\n"
        "#   2. 保存后运行：monitor.py apply --input <本文件路径>\n"
        "# 字段与 create-subscription 的校验规则一一对应。\n"
        "action: create-subscription\n"
        "# 偏好选择回执 id（可选；留空则按 canonical 配置兜底应用硬约束）\n"
        "preference_selection_id: ''\n"
        "subscription:\n"
        f"  # 订阅类型三选一：{' | '.join(TEMPLATE_KINDS)}（target 结构随之变化，见下）\n"
        f"  kind: {kind}\n"
        "  # 标题（可留空，最长 500 字符）\n"
        "  title: ''\n"
        "  # 关联的研究计划 id 列表（可为空列表；填写的 program 必须已存在）\n"
        "  program_ids: []\n"
        + _TEMPLATE_TARGET_BLOCKS[kind]
        + "  # scope：任意 JSON 对象，随订阅整体冻结（没有就保持 {}）\n"
        "  scope: {}\n"
        "  # budget：可选正整数字段 max_queries / max_candidates / max_full_reads / max_citation_hops（没有就保持 {}）\n"
        "  budget: {}\n"
        "  cadence:\n"
        "    # 复查间隔天数：1..3650\n"
        "    every_days: 7\n"
        "    # IANA 时区名，例如 Asia/Shanghai、UTC\n"
        "    timezone: UTC\n"
        "    # 锚点时间（ISO8601 带时区）；首次到期时间即此锚点\n"
        f"    anchor_at: '{anchor_at}'\n"
    )


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        stat = path.lstat()
    except OSError:
        raise SystemExit("Research monitor input could not be read.") from None
    if path.is_symlink() or not path.is_file() or stat.st_size > MAX_PAYLOAD_BYTES:
        raise SystemExit("Research monitor input must be a bounded regular JSON/YAML file.")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise SystemExit("Research monitor input could not be read.") from None
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        # The fill-in template is YAML with comments; accept it the same way.
        try:
            import yaml

            payload = yaml.safe_load(text)
        except Exception:
            raise SystemExit("Research monitor input is not valid JSON or YAML.") from None
    if not isinstance(payload, dict):
        raise SystemExit("Research monitor input must be a JSON or YAML object.")
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
        if set(payload) - {"action", "subscription", "now", "preference_selection_id"}:
            raise SystemExit("Research monitor request contains unsupported fields.")
        path = create_subscription(
            root,
            payload.get("subscription"),
            now=now,
            preference_selection_id=str(payload.get("preference_selection_id") or ""),
        )
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
    if action == "set-outcome-disposition":
        if set(payload) - {
            "action",
            "run_id",
            "outcome_id",
            "expected_run_revision",
            "expected_run_content_digest",
            "state",
            "actor",
            "reason",
            "target_ref",
            "user_authorization",
            "authorization_source",
            "now",
        }:
            raise SystemExit("Research monitor request contains unsupported fields.")
        path = set_outcome_disposition(
            root,
            str(payload.get("run_id") or ""),
            str(payload.get("outcome_id") or ""),
            expected_run_revision=_integer(
                payload.get("expected_run_revision"), field="expected_run_revision"
            ),
            expected_run_content_digest=str(payload.get("expected_run_content_digest") or ""),
            state=str(payload.get("state") or ""),
            actor=str(payload.get("actor") or ""),
            reason=str(payload.get("reason") or ""),
            target_ref=str(payload.get("target_ref") or ""),
            user_authorization=str(payload.get("user_authorization") or ""),
            authorization_source=str(payload.get("authorization_source") or ""),
            now=now,
        )
        document = load_run(root, path.stem)
        disposition = next(
            item.get("disposition")
            for item in document.get("review_outcomes", [])
            if isinstance(item, dict) and item.get("outcome_id") == payload.get("outcome_id")
        )
        return {
            "action": action,
            "run_id": document["id"],
            "revision": document["revision"],
            "content_digest": document["content_digest"],
            "outcome_id": str(payload.get("outcome_id") or ""),
            "disposition": disposition,
        }
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
    subparsers.add_parser("unresolved-outcomes")
    template = subparsers.add_parser(
        "template",
        help="Print a fill-in subscription YAML template for apply --input",
    )
    template.add_argument("--kind", choices=list(TEMPLATE_KINDS), default="literature")
    apply = subparsers.add_parser("apply")
    apply.add_argument("--input", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "template":
        # Read-only helper: needs no workspace and mutates nothing.
        from datetime import datetime, timezone

        anchor_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        sys.stdout.write(render_subscription_template(args.kind, anchor_at=anchor_at))
        return 0
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command == "due":
        result: Any = {"due": due_subscriptions(root, now=args.now or None)}
    elif args.command == "unresolved-outcomes":
        result = {"unresolved_outcomes": unresolved_monitor_outcomes(root)}
    else:
        result = _apply(root, _load_payload(args.input))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

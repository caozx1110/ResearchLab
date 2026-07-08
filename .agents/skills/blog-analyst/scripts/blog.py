#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, print_resolved_project_roots, write_text_if_changed, write_yaml_if_changed
from research.core import append_history, build_index, confirm_unit, locate_record, project_root, rel, write_record


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)


def summary_payload(record: dict) -> dict:
    return {
        "blog_id": record["id"],
        "status": "pending_user_confirmation",
        "information_types": ["fact", "inference", "evaluation", "unverified"],
        "main_value": "待确认该博客适合做概念解释、原理分析还是工程辅助。",
        "key_points": ["待提炼关键知识点", "待标记哪些结论需要核实"],
        "best_use": "待确认其更适合阅读辅助、汇报素材还是长期引用。",
    }


def note_template(record: dict) -> str:
    return f"""# {record.get('title', '')}\n\n## 内容定位\n\n- 主要解释什么：\n- 内容类型：\n- 适合在哪个阶段阅读：\n\n## 核心知识点\n\n\n## 直观 Insight\n\n\n## 可信度判断\n\n\n## 关联论文 / 仓库 / 方法\n\n\n## 可用于周报 / PPT 的素材\n\n\n## 用户批注\n\n\n"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze blog units in core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("summarize", "complete-note", "confirm"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--blog-id", required=True)
        if name == "confirm":
            add_confirmation_arguments(cmd)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, path = locate_record(root, args.blog_id, kind="blog")
    if record.get("kind") != "blog":
        raise SystemExit(f"{args.blog_id} is not a blog record")
    unit_root = path.parent

    if args.command == "summarize":
        summary_path = unit_root / "summary.yaml"
        payload = summary_payload(record)
        write_yaml_if_changed(summary_path, payload)
        record["payload"]["positioning"]["main_value"] = payload["main_value"]
        record["payload"]["content"]["key_points"] = payload["key_points"]
        record["status"] = "screened"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        record["summary"] = payload["main_value"]
        append_history(record, action="blog-summarized", summary="Generated blog summary artifact.", information_types=["inference", "evaluation", "unverified"], artifacts=[rel(root, summary_path)])
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {summary_path.relative_to(root)}")
        return 0

    if args.command == "complete-note":
        note_path = unit_root / "blog-note.md"
        write_text_if_changed(note_path, note_template(record))
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        append_history(record, action="blog-note-created", summary="Created full blog note scaffold.", information_types=["inference", "evaluation", "unverified"], artifacts=[rel(root, note_path)])
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {note_path.relative_to(root)}")
        return 0

    if args.command == "confirm":
        record = confirm_unit(record, "blog", confirmed_by=args.confirmed_by, evidence=args.evidence, method="blog.py confirm", project_root=root)
        write_record(root, record)
        build_index(root)
        print(f"[ok] confirmed {args.blog_id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

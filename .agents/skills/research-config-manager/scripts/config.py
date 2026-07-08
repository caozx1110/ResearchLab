#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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

from research.common import add_project_root_argument, load_yaml, print_resolved_project_roots, slugify, warn_if_cwd_differs_from_project_root, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.core import (
    candidate_pools_path,
    config_root,
    default_runtime_preferences,
    ensure_workspace,
    load_candidate_pools,
    load_runtime_preferences,
    load_topic_taxonomy,
    checkpoint_and_report,
    project_root,
    runtime_preferences_path,
    topic_taxonomy_path,
    write_runtime_preferences,
)


def profile_path(root: Path) -> Path:
    return config_root(root) / "user-profile.yaml"


def settings_path(root: Path) -> Path:
    return config_root(root) / "research-settings.md"


TOGGLE_RUNTIME_PREFS = {
    "新论文入库后自动快速筛选": [("paper", "auto_screen_on_intake", lambda on: on)],
    "intake 阶段预热 PDF 解析缓存": [("paper", "parse_cache_prewarm_on_intake", lambda on: on)],
    "自动生成详细论文笔记": [("paper", "auto_complete_note", lambda on: on)],
    "完整笔记后自动提取 Figure / Table": [("paper", "auto_extract_figures_after_note", lambda on: on)],
    "完整笔记后自动刷新结构": [("paper", "auto_refresh_structure_after_note", lambda on: on)],
}


def _default_profile() -> dict:
    return {
        **yaml_default("research-user-profile", "research-config-manager", status="active"),
        "preferences": {
            "language_preference": "zh-CN",
        },
        "resources": {},
        "constraints": [],
        "governance": {
            "default_candidate_pools": [],
            "topic_overrides": {},
            "tag_overrides": {},
        },
        "history": [],
    }


def load_profile(root: Path) -> dict:
    payload = load_yaml(profile_path(root), default={})
    if not isinstance(payload, dict) or not payload:
        payload = _default_profile()
    payload.setdefault("preferences", {})
    payload.setdefault("resources", {})
    payload.setdefault("constraints", [])
    payload.setdefault("governance", {})
    payload.setdefault("history", [])
    return payload


def set_nested(payload: dict, dotted_key: str, value: str) -> None:
    keys = [part for part in dotted_key.split(".") if part]
    if not keys:
        raise SystemExit("Invalid --key")
    current = payload
    for key in keys[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[keys[-1]] = value


def parse_value(raw: str) -> object:
    text = raw.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if text.lower() == "null":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return raw


def _apply_runtime_pref(payload: dict, section: str, key: str, value: object) -> None:
    payload.setdefault(section, {})
    if not isinstance(payload[section], dict):
        payload[section] = {}
    payload[section][key] = value


def sync_toggle_runtime_preferences(root: Path, *, key: str, on: bool) -> list[str]:
    updates = TOGGLE_RUNTIME_PREFS.get(key, [])
    if not updates:
        return []
    payload = load_runtime_preferences(root)
    touched: list[str] = []
    for section, pref_key, resolver in updates:
        _apply_runtime_pref(payload, section, pref_key, resolver(on))
        touched.append(f"{section}.{pref_key}")
    write_runtime_preferences(root, payload)
    return touched


def _onoff(value: bool) -> str:
    return "on" if value else "off"


def print_personalization(root: Path) -> None:
    profile = load_profile(root)
    personalization = profile.get("personalization", {})
    print("personalization:")
    if not isinstance(personalization, dict) or not personalization:
        print("  未设置，可在 kb init 时填写。")
        return
    for key in ("research_focus", "resources", "reporting_style", "collaboration_boundaries", "term_style"):
        value = personalization.get(key)
        if value not in (None, ""):
            print(f"  {key}: {value}")


def print_guide(root: Path, *, focus: str) -> None:
    runtime = load_runtime_preferences(root)
    paper = runtime.get("paper", {})
    pdf = runtime.get("pdf", {})
    versioning = runtime.get("versioning", {})
    if focus in {"all", "paper-intake"}:
        print("[paper-intake]")
        print(f"- 自动快速筛选: {_onoff(bool(paper.get('auto_screen_on_intake', True)))}")
        print(f"- intake 预热解析缓存: {_onoff(bool(paper.get('parse_cache_prewarm_on_intake', True)))}")
        print(f"- 自动完整笔记: {_onoff(bool(paper.get('auto_complete_note')))}")
        print(f"- 完整笔记触发条件: {paper.get('auto_complete_note_condition')}")
        print(f"- 完整笔记模式: {paper.get('complete_note_mode')}")
        print(f"- 完整笔记后自动提图: {_onoff(bool(paper.get('auto_extract_figures_after_note')))}")
        print(f"- 完整笔记后自动刷新结构: {_onoff(bool(paper.get('auto_refresh_structure_after_note', True)))}")
        print(f"- PDF Figure 模式: {pdf.get('figure_extraction_mode')}")
        print("")
        print("建议修改：")
        if not bool(paper.get("auto_complete_note")):
            print(
                "- 如果你希望值得读的论文默认自动生成完整笔记："
                " set-runtime-pref --section paper --key auto_complete_note --value true"
            )
        if str(paper.get("complete_note_mode") or "scaffold") != "draft":
            print(
                "- 如果你希望默认直接生成更饱满的草稿："
                " set-runtime-pref --section paper --key complete_note_mode --value draft"
            )
        if not bool(paper.get("auto_extract_figures_after_note")):
            print(
                "- 如果你希望完整笔记后顺手导出 Figure / Table："
                " set-runtime-pref --section paper --key auto_extract_figures_after_note --value true"
            )
        if str(versioning.get("auto_commit_mode") or "milestone") == "aggressive":
            print("- 当前 Git 自动提交较激进；如果你想少一点碎提交，可改回 milestone。")
        print("- 用 toggle 管布尔开关，用 set-runtime-pref 管模式类选项。")


def upsert_taxonomy_seed(root: Path, *, topic: str, aliases: list[str], tags: list[str], note: str, status: str) -> Path:
    payload = load_topic_taxonomy(root)
    topic_id = slugify(topic, max_words=12)
    if not topic_id:
        raise SystemExit("Invalid --topic")
    topic_item = payload["topics"].setdefault(
        topic_id,
        {"id": topic_id, "aliases": [], "tags": [], "pools": [], "member_ids": [], "count": 0, "note": "", "status": "active"},
    )
    topic_item["aliases"] = sorted(set(topic_item.get("aliases", [])) | {slugify(alias, max_words=12) for alias in aliases if slugify(alias, max_words=12)})
    topic_item["tags"] = sorted(set(topic_item.get("tags", [])) | {slugify(tag, max_words=12) for tag in tags if slugify(tag, max_words=12)})
    if note:
        topic_item["note"] = note
    topic_item["status"] = status

    for raw_tag in tags:
        tag_id = slugify(raw_tag, max_words=12)
        if not tag_id:
            continue
        tag_item = payload["tags"].setdefault(
            tag_id,
            {"id": tag_id, "aliases": [], "topic_hints": [], "pools": [], "member_ids": [], "count": 0, "note": "", "status": "active"},
        )
        tag_item["topic_hints"] = sorted(set(tag_item.get("topic_hints", [])) | {topic_id})
        if note and not tag_item.get("note"):
            tag_item["note"] = note
        tag_item["status"] = status
    write_yaml_if_changed(topic_taxonomy_path(root), payload)
    return topic_taxonomy_path(root)


def upsert_pool(root: Path, *, pool: str, topics: list[str], tags: list[str], description: str, status: str) -> Path:
    payload = load_candidate_pools(root)
    pool_id = slugify(pool, max_words=12)
    if not pool_id:
        raise SystemExit("Invalid --pool")
    item = payload["pools"].setdefault(
        pool_id,
        {"id": pool_id, "summary": "", "topic_hints": [], "tags": [], "member_ids": [], "kinds": [], "status": "active"},
    )
    item["topic_hints"] = sorted(set(item.get("topic_hints", [])) | {slugify(topic, max_words=12) for topic in topics if slugify(topic, max_words=12)})
    item["tags"] = sorted(set(item.get("tags", [])) | {slugify(tag, max_words=12) for tag in tags if slugify(tag, max_words=12)})
    if description:
        item["summary"] = description
    item["status"] = status
    write_yaml_if_changed(candidate_pools_path(root), payload)
    return candidate_pools_path(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage research configuration.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Initialize config files")

    show = subparsers.add_parser("show", help="Show current config paths")
    show.add_argument("--section", choices=["all", "profile", "settings", "taxonomy", "pools", "runtime"], default="all")
    show.add_argument("--dump", action="store_true")

    set_cmd = subparsers.add_parser("set", help="Set a profile key using dotted notation")
    set_cmd.add_argument("--key", required=True)
    set_cmd.add_argument("--value", required=True)

    toggle = subparsers.add_parser("toggle", help="Toggle a markdown setting")
    toggle.add_argument("--key", required=True)
    toggle.add_argument("--state", required=True, choices=["on", "off"])

    capture = subparsers.add_parser("capture-resources", help="Store a natural-language resource statement")
    capture.add_argument("--statement", required=True)
    capture.add_argument("--label", default="")

    seed = subparsers.add_parser("set-taxonomy-seed", help="Persist a topic/tag taxonomy seed")
    seed.add_argument("--topic", required=True)
    seed.add_argument("--alias", action="append", default=[])
    seed.add_argument("--tag", action="append", default=[])
    seed.add_argument("--note", default="")
    seed.add_argument("--status", default="active")

    pool = subparsers.add_parser("set-pool", help="Persist candidate pool metadata")
    pool.add_argument("--pool", required=True)
    pool.add_argument("--topic", action="append", default=[])
    pool.add_argument("--tag", action="append", default=[])
    pool.add_argument("--description", default="")
    pool.add_argument("--status", default="active")

    guide = subparsers.add_parser("guide", help="Show practical guidance for current runtime modes")
    guide.add_argument("--focus", choices=["all", "paper-intake"], default="all")

    runtime = subparsers.add_parser("set-runtime-pref", help="Persist browser / identity / autonomy / paper / pdf / versioning runtime preferences")
    runtime.add_argument("--section", required=True, choices=["browser", "identity", "autonomy", "paper", "pdf", "versioning"])
    runtime.add_argument("--key", required=True)
    runtime.add_argument("--value", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_workspace(root)

    if args.command == "init":
        warn_if_cwd_differs_from_project_root(root, command="config.py init")
        write_yaml_if_changed(profile_path(root), load_profile(root))
        load_topic_taxonomy(root)
        load_candidate_pools(root)
        write_yaml_if_changed(runtime_preferences_path(root), default_runtime_preferences())
        print(f"[ok] initialized {profile_path(root).relative_to(root)}")
        print(f"[ok] initialized {topic_taxonomy_path(root).relative_to(root)}")
        print(f"[ok] initialized {candidate_pools_path(root).relative_to(root)}")
        print(f"[ok] initialized {runtime_preferences_path(root).relative_to(root)}")
        return 0
    if args.command == "show":
        sections = {
            "profile": profile_path(root),
            "settings": settings_path(root),
            "taxonomy": topic_taxonomy_path(root),
            "pools": candidate_pools_path(root),
            "runtime": runtime_preferences_path(root),
        }
        selected = sections if args.section == "all" else {args.section: sections[args.section]}
        for name, path in selected.items():
            print(f"{name}: {path.relative_to(root)}")
            if args.dump and path.exists():
                print(path.read_text(encoding="utf-8").rstrip())
            if name == "profile":
                print_personalization(root)
        return 0
    if args.command == "set":
        payload = load_profile(root)
        set_nested(payload, args.key, parse_value(args.value))
        payload.setdefault("history", []).append({"action": "set", "key": args.key, "value": args.value})
        write_yaml_if_changed(profile_path(root), payload)
        print(f"[ok] set {args.key}")
        return 0
    if args.command == "toggle":
        path = settings_path(root)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        on = args.state == "on"
        marker = "[x]" if on else "[ ]"
        lines = []
        found = False
        for line in text.splitlines():
            if args.key in line:
                suffix = line.split("]", 1)[-1].strip()
                lines.append(f"- {marker} {suffix}")
                found = True
            else:
                lines.append(line)
        if not found:
            lines.append(f"- {marker} {args.key}")
        write_text_if_changed(path, "\n".join(lines).strip() + "\n")
        touched = sync_toggle_runtime_preferences(root, key=args.key, on=on)
        print(f"[ok] toggled {args.key} -> {args.state}")
        if touched:
            print(f"[ok] synced runtime prefs: {', '.join(touched)}")
        return 0
    if args.command == "capture-resources":
        payload = load_profile(root)
        label = args.label or f"captured_{len(payload['resources']) + 1}"
        payload["resources"][label] = args.statement
        payload.setdefault("history", []).append({"action": "capture-resources", "label": label, "statement": args.statement})
        write_yaml_if_changed(profile_path(root), payload)
        print(f"[ok] stored resource statement as {label}")
        return 0
    if args.command == "set-taxonomy-seed":
        path = upsert_taxonomy_seed(
            root,
            topic=args.topic,
            aliases=args.alias,
            tags=args.tag,
            note=args.note,
            status=args.status,
        )
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    if args.command == "set-pool":
        path = upsert_pool(
            root,
            pool=args.pool,
            topics=args.topic,
            tags=args.tag,
            description=args.description,
            status=args.status,
        )
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    if args.command == "guide":
        print_guide(root, focus=args.focus)
        return 0
    if args.command == "set-runtime-pref":
        payload = load_runtime_preferences(root)
        _apply_runtime_pref(payload, args.section, args.key, parse_value(args.value))
        write_runtime_preferences(root, payload)
        print(f"[ok] updated {runtime_preferences_path(root).relative_to(root)}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: update runtime pref {args.section}.{args.key}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

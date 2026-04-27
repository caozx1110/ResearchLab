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

from research.common import load_yaml, slugify, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.v2 import (
    candidate_pools_path,
    config_root,
    ensure_v2_workspace,
    load_candidate_pools,
    load_topic_taxonomy,
    project_root,
    topic_taxonomy_path,
)


def profile_path(root: Path) -> Path:
    return config_root(root) / "user-profile.yaml"


def settings_path(root: Path) -> Path:
    return config_root(root) / "research-settings.md"


def runtime_preferences_path(root: Path) -> Path:
    return config_root(root) / "runtime-preferences.yaml"


def _default_profile() -> dict:
    return {
        **yaml_default("research-user-profile-v2", "research-config-manager", status="active"),
        "preferences": {
            "language_preference": "zh-CN",
            "summary_style": "concise",
            "novelty_bar": "balanced",
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


def _default_runtime_preferences() -> dict:
    return {
        **yaml_default("runtime-preferences-v2", "research-config-manager", status="active"),
        "browser": {
            "default_workbench_mode": "preview",
            "default_terminal_mode": "codex",
            "auto_open_recent_file": True,
        },
        "pdf": {
            "prefer_structured_source": True,
            "auto_extract_figures": False,
            "reuse_cached_parse": True,
            "require_pdfimages": True,
            "filter_blank_and_mask_images": True,
        },
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
    parser = argparse.ArgumentParser(description="Manage v2 research configuration.")
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

    runtime = subparsers.add_parser("set-runtime-pref", help="Persist browser / pdf runtime preferences")
    runtime.add_argument("--section", required=True, choices=["browser", "pdf"])
    runtime.add_argument("--key", required=True)
    runtime.add_argument("--value", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    ensure_v2_workspace(root)

    if args.command == "init":
        write_yaml_if_changed(profile_path(root), load_profile(root))
        load_topic_taxonomy(root)
        load_candidate_pools(root)
        write_yaml_if_changed(runtime_preferences_path(root), _default_runtime_preferences())
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
        print(f"[ok] toggled {args.key} -> {args.state}")
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
    if args.command == "set-runtime-pref":
        payload = load_yaml(runtime_preferences_path(root), default={})
        if not isinstance(payload, dict) or not payload:
            payload = _default_runtime_preferences()
        payload.setdefault(args.section, {})
        if not isinstance(payload[args.section], dict):
            payload[args.section] = {}
        payload[args.section][args.key] = parse_value(args.value)
        write_yaml_if_changed(runtime_preferences_path(root), payload)
        print(f"[ok] updated {runtime_preferences_path(root).relative_to(root)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

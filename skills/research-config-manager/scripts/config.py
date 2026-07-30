#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

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

from research.common import add_project_root_argument, load_yaml, print_resolved_project_roots, slugify, warn_if_cwd_differs_from_project_root, write_text_if_changed, write_yaml_if_changed, yaml_default
from research.confirm import is_ai_signer
from research.journal import mutation_transaction
from research.core import (
    candidate_pools_path,
    config_root,
    ensure_workspace,
    kb_root,
    load_candidate_pools,
    load_runtime_preferences,
    load_topic_taxonomy,
    checkpoint_and_report,
    project_root,
    runtime_preferences_path,
    topic_taxonomy_path,
    write_candidate_pools,
    write_runtime_preferences,
    write_topic_taxonomy,
)
from research.prefs import (
    DEFAULT_DISCUSSION_STYLE,
    DIAGNOSTIC_MODES,
    DIAGNOSTIC_SKILL_MODES,
    DISCUSSION_STYLES,
    GOVERNANCE_PROFILES,
    LINK_AUTODRIVE_MODES,
    MAX_REVIEW_CARD_TTL_HOURS,
    MAX_REVIEW_ITEM_LIMIT,
    MIN_PERSONAL_REVIEW_ITEM_LIMIT,
    MIN_REVIEW_CARD_TTL_HOURS,
    effective_review_policy,
)
from research.preference_selection import (
    SKILL_IMPLEMENTATION_ALIASES,
    eligible_preferences,
    record_effective_selection,
    resolve_task_preferences,
    task_context_digest,
)


def profile_path(root: Path) -> Path:
    return config_root(root) / "user-profile.yaml"


def settings_path(root: Path) -> Path:
    return config_root(root) / "research-settings.md"


TOGGLE_RUNTIME_PREFS = {
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
        "personalization": {
            "discussion_style": DEFAULT_DISCUSSION_STYLE,
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


def _deep_fill_missing(current: object, defaults: object) -> object:
    """Fill absent config keys without replacing any user-owned value."""
    if not isinstance(current, dict) or not isinstance(defaults, dict):
        return copy.deepcopy(current)
    merged = copy.deepcopy(current)
    for key, default_value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(default_value)
        elif isinstance(merged[key], dict) and isinstance(default_value, dict):
            merged[key] = _deep_fill_missing(merged[key], default_value)
    return merged


def load_profile(root: Path) -> dict:
    payload = load_yaml(profile_path(root), default={})
    if not isinstance(payload, dict) or not payload:
        payload = _default_profile()
    return _deep_fill_missing(payload, _default_profile())


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
    for key in ("research_focus", "resources", "reporting_style", "collaboration_boundaries", "term_style", "discussion_style"):
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
        print(f"- intake 预热解析缓存: {_onoff(bool(paper.get('parse_cache_prewarm_on_intake', True)))}")
        print(f"- 自动完整笔记: {_onoff(bool(paper.get('auto_complete_note')))}")
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
    if focus in {"all", "governance"}:
        policy = effective_review_policy(root)
        if focus == "all":
            print("")
        print("[governance]")
        print(f"- 治理档位: {policy['governance_profile']}")
        print(f"- 每批待确认上限: {policy['item_limit']}")
        print(f"- 待确认卡片有效期: {policy['card_ttl_hours']} 小时")


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
    return write_topic_taxonomy(root, payload)


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
    return write_candidate_pools(root, payload)


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
    guide.add_argument("--focus", choices=["all", "paper-intake", "governance"], default="all")

    interaction = subparsers.add_parser(
        "set-interaction",
        help="Persist the canonical interaction preferences: link automation tier and discussion style",
    )
    interaction.add_argument(
        "--auto-ingest-mode",
        dest="auto_ingest_mode",
        choices=sorted(LINK_AUTODRIVE_MODES),
        help="Canonical write path for autonomy.link_autodrive (runtime preferences)",
    )
    interaction.add_argument(
        "--discussion-style",
        dest="discussion_style",
        choices=sorted(DISCUSSION_STYLES),
        help="Canonical write path for personalization.discussion_style (user profile)",
    )

    runtime = subparsers.add_parser("set-runtime-pref", help="Persist browser / identity / autonomy / paper / pdf / review / versioning runtime preferences")
    runtime.add_argument("--section", required=True, choices=["browser", "identity", "autonomy", "paper", "pdf", "review", "versioning", "diagnostics"])
    runtime.add_argument("--key", required=True)
    runtime.add_argument("--value", required=True)

    governance = subparsers.add_parser("set-governance", help="Set the workspace governance profile and personal review policy")
    governance.add_argument("--profile", choices=sorted(GOVERNANCE_PROFILES))
    governance.add_argument("--review-item-limit", type=int)
    governance.add_argument("--card-ttl-hours", type=int)

    diagnostics = subparsers.add_parser("set-diagnostics", help="Configure optional local-only diagnostics")
    diagnostics.add_argument("--mode", choices=sorted(DIAGNOSTIC_MODES))
    diagnostics.add_argument("--skill", default="")
    diagnostics.add_argument("--skill-mode", choices=sorted(DIAGNOSTIC_SKILL_MODES))
    diagnostics.add_argument("--token-budget-per-task", type=int)
    diagnostics.add_argument("--max-issues-per-task", type=int)
    diagnostics.add_argument("--dedup-window-seconds", type=int)
    diagnostics.add_argument("--cooldown-seconds", type=int)

    eligible = subparsers.add_parser("eligible-preferences", help="Return the task-scoped eligible preference view")
    eligible.add_argument("--skill", required=True)
    eligible.add_argument("--operation", default="")
    eligible.add_argument("--task-context-json", default="")

    record_effective = subparsers.add_parser("record-effective", help="Validate and persist an Agent preference selection")
    record_effective.add_argument("--selection-json", required=True)

    load_effective = subparsers.add_parser("load-effective", help="Load a current task-scoped preference selection")
    load_effective.add_argument("--selection-id", required=True)
    load_effective.add_argument("--skill", required=True)
    load_effective.add_argument("--operation", default="")
    load_effective.add_argument("--task-context-json", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    if args.command not in {"eligible-preferences", "load-effective"}:
        ensure_workspace(root)

    if args.command == "eligible-preferences":
        # Both known input mistakes (an unregistered consumer operation, and
        # canonical task inputs that miss/exceed the registered field set) must
        # fail as one readable line, never as a raw traceback.
        try:
            result = eligible_preferences(root, skill=args.skill, operation=args.operation)
        except ValueError as exc:
            raise SystemExit(f"eligible-preferences 输入无效（invalid consumer）：{exc}") from exc
        if args.task_context_json:
            try:
                task_context = json.loads(args.task_context_json)
            except json.JSONDecodeError as exc:
                raise SystemExit("Invalid canonical task context JSON") from exc
            if not isinstance(task_context, dict):
                raise SystemExit("Canonical task context must be an object")
            try:
                result["task_context_digest"] = task_context_digest(
                    skill=args.skill,
                    operation=args.operation,
                    canonical_inputs=task_context,
                )
            except ValueError as exc:
                raise SystemExit(f"eligible-preferences 输入无效（canonical task inputs）：{exc}") from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "record-effective":
        selection_text = str(args.selection_json or "")
        selection_reference = selection_text.strip()
        # --selection-json accepts either the inline JSON object or the path of
        # a JSON file; a value naming an existing file is read from disk.
        if selection_reference:
            try:
                selection_file = Path(selection_reference).expanduser()
                selection_is_file = selection_file.is_file()
            except OSError:
                selection_is_file = False
            if selection_is_file:
                try:
                    selection_text = selection_file.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    raise SystemExit(f"无法读取 selection JSON 文件：{selection_reference}") from exc
        try:
            selection = json.loads(selection_text)
        except json.JSONDecodeError as exc:
            raise SystemExit("Invalid effective preference selection JSON") from exc
        if not isinstance(selection, dict):
            raise SystemExit("Effective preference selection must be an object")
        try:
            path, receipt = record_effective_selection(root, selection)
        except ValueError as exc:
            raise SystemExit(f"record-effective selection 被拒绝：{exc}") from exc
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: record effective preferences {receipt['selection_id']}",
            target_paths=[path],
        )
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "load-effective":
        try:
            task_context = json.loads(args.task_context_json)
        except json.JSONDecodeError as exc:
            raise SystemExit("Invalid canonical task context JSON") from exc
        if not isinstance(task_context, dict):
            raise SystemExit("Canonical task context must be an object")
        effective = resolve_task_preferences(
            root,
            selection_id=args.selection_id,
            skill=args.skill,
            operation=args.operation,
            canonical_inputs=task_context,
        )
        print(json.dumps(effective, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "init":
        warn_if_cwd_differs_from_project_root(root, command="config.py init")
        targets = [
            kb_root(root) / ".gitignore",
            profile_path(root),
            topic_taxonomy_path(root),
            candidate_pools_path(root),
            runtime_preferences_path(root),
        ]
        with mutation_transaction(root, "config-init", targets):
            write_yaml_if_changed(profile_path(root), load_profile(root))
            load_topic_taxonomy(root)
            load_candidate_pools(root)
            write_yaml_if_changed(runtime_preferences_path(root), load_runtime_preferences(root))
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: initialize research configuration",
            target_paths=targets,
        )
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
        path = profile_path(root)
        with mutation_transaction(root, "config-set", [path]):
            payload = load_profile(root)
            set_nested(payload, args.key, parse_value(args.value))
            payload.setdefault("history", []).append({"action": "set", "key": args.key, "value": args.value})
            write_yaml_if_changed(path, payload)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: update profile {args.key}",
            target_paths=[path],
        )
        print(f"[ok] set {args.key}")
        return 0
    if args.command == "toggle":
        path = settings_path(root)
        targets = [path]
        if TOGGLE_RUNTIME_PREFS.get(args.key):
            targets.append(runtime_preferences_path(root))
        on = args.state == "on"
        with mutation_transaction(root, "config-toggle", targets):
            text = path.read_text(encoding="utf-8") if path.exists() else ""
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
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: toggle config {args.key}",
            target_paths=targets,
        )
        print(f"[ok] toggled {args.key} -> {args.state}")
        if touched:
            print(f"[ok] synced runtime prefs: {', '.join(touched)}")
        return 0
    if args.command == "capture-resources":
        path = profile_path(root)
        with mutation_transaction(root, "config-capture-resources", [path]):
            payload = load_profile(root)
            label = args.label or f"captured_{len(payload['resources']) + 1}"
            payload["resources"][label] = args.statement
            payload.setdefault("history", []).append({"action": "capture-resources", "label": label, "statement": args.statement})
            write_yaml_if_changed(path, payload)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: capture resource profile {label}",
            target_paths=[path],
        )
        print(f"[ok] stored resource statement as {label}")
        return 0
    if args.command == "set-taxonomy-seed":
        path = topic_taxonomy_path(root)
        with mutation_transaction(root, "config-set-taxonomy-seed", [path]):
            path = upsert_taxonomy_seed(
                root,
                topic=args.topic,
                aliases=args.alias,
                tags=args.tag,
                note=args.note,
                status=args.status,
            )
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: update taxonomy seed {args.topic}",
            target_paths=[path],
        )
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    if args.command == "set-pool":
        path = candidate_pools_path(root)
        with mutation_transaction(root, "config-set-pool", [path]):
            path = upsert_pool(
                root,
                pool=args.pool,
                topics=args.topic,
                tags=args.tag,
                description=args.description,
                status=args.status,
            )
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: update candidate pool {args.pool}",
            target_paths=[path],
        )
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    if args.command == "guide":
        print_guide(root, focus=args.focus)
        return 0
    if args.command == "set-interaction":
        auto_ingest_mode = getattr(args, "auto_ingest_mode", None)
        discussion_style = getattr(args, "discussion_style", None)
        if auto_ingest_mode is None and discussion_style is None:
            raise SystemExit("set-interaction requires --auto-ingest-mode and/or --discussion-style")
        targets = []
        if auto_ingest_mode is not None:
            targets.append(runtime_preferences_path(root))
        if discussion_style is not None:
            targets.append(profile_path(root))
        touched: list[str] = []
        with mutation_transaction(root, "set-interaction", targets):
            if auto_ingest_mode is not None:
                payload = load_runtime_preferences(root)
                _apply_runtime_pref(payload, "autonomy", "link_autodrive", auto_ingest_mode)
                write_runtime_preferences(root, payload)
                touched.append("autonomy.link_autodrive")
            if discussion_style is not None:
                profile = load_profile(root)
                previous = profile.get("personalization", {})
                previous = previous.get("discussion_style") if isinstance(previous, dict) else None
                set_nested(profile, "personalization.discussion_style", discussion_style)
                if previous != discussion_style:
                    profile.setdefault("history", []).append(
                        {
                            "action": "set-interaction",
                            "key": "personalization.discussion_style",
                            "value": discussion_style,
                        }
                    )
                write_yaml_if_changed(profile_path(root), profile)
                touched.append("personalization.discussion_style")
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: update interaction preferences",
            target_paths=targets,
        )
        print(f"[ok] updated interaction preferences: {', '.join(touched)}")
        return 0
    if args.command == "set-runtime-pref":
        path = runtime_preferences_path(root)
        value = parse_value(args.value)
        if args.section == "identity" and args.key == "default_confirmed_by":
            signer = str(value or "").strip()
            if not signer or is_ai_signer(signer):
                raise SystemExit("default confirmation identity must be a real human name")
        with mutation_transaction(root, "set-runtime-pref", [path]):
            payload = load_runtime_preferences(root)
            _apply_runtime_pref(payload, args.section, args.key, value)
            write_runtime_preferences(root, payload)
        print(f"[ok] updated {path.relative_to(root)}")
        checkpoint = checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: update runtime pref {args.section}.{args.key}",
            target_paths=[path],
        )
        return 0
    if args.command == "set-governance":
        if args.profile is None and args.review_item_limit is None and args.card_ttl_hours is None:
            raise SystemExit("set-governance requires at least one policy change")
        if args.review_item_limit is not None and not (
            MIN_PERSONAL_REVIEW_ITEM_LIMIT <= args.review_item_limit <= MAX_REVIEW_ITEM_LIMIT
        ):
            raise SystemExit(
                f"review item limit must be between {MIN_PERSONAL_REVIEW_ITEM_LIMIT} and {MAX_REVIEW_ITEM_LIMIT}"
            )
        if args.card_ttl_hours is not None and not (
            MIN_REVIEW_CARD_TTL_HOURS <= args.card_ttl_hours <= MAX_REVIEW_CARD_TTL_HOURS
        ):
            raise SystemExit(
                f"card TTL must be between {MIN_REVIEW_CARD_TTL_HOURS} and {MAX_REVIEW_CARD_TTL_HOURS} hours"
            )
        path = runtime_preferences_path(root)
        with mutation_transaction(root, "set-governance", [path]):
            update: dict[str, object] = {}
            if args.profile is not None:
                update["governance_profile"] = args.profile
            review: dict[str, int] = {}
            if args.review_item_limit is not None:
                review["batch_item_limit"] = args.review_item_limit
            if args.card_ttl_hours is not None:
                review["card_ttl_hours"] = args.card_ttl_hours
            if review:
                update["review"] = review
            write_runtime_preferences(root, update)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: update governance policy",
            target_paths=[path],
        )
        print("[ok] updated workspace governance policy")
        return 0
    if args.command == "set-diagnostics":
        if bool(args.skill) != bool(args.skill_mode):
            raise SystemExit("--skill and --skill-mode must be provided together")
        if all(
            value is None
            for value in (
                args.mode,
                args.skill_mode,
                args.token_budget_per_task,
                args.max_issues_per_task,
                args.dedup_window_seconds,
                args.cooldown_seconds,
            )
        ):
            raise SystemExit("set-diagnostics requires at least one policy change")
        path = runtime_preferences_path(root)
        with mutation_transaction(root, "set-diagnostics", [path]):
            payload = load_runtime_preferences(root)
            diagnostics = payload.get("diagnostics", {})
            if not isinstance(diagnostics, dict):
                diagnostics = {}
            if args.mode is not None:
                diagnostics["mode"] = args.mode
            if args.skill_mode is not None:
                overrides = diagnostics.get("per_skill", {})
                if not isinstance(overrides, dict):
                    overrides = {}
                requested_skill = str(args.skill).strip().lower()
                overrides[requested_skill] = args.skill_mode
                for implementation_skill in SKILL_IMPLEMENTATION_ALIASES.get(
                    requested_skill, ()
                ):
                    overrides[implementation_skill] = args.skill_mode
                diagnostics["per_skill"] = overrides
            for argument, key in (
                (args.token_budget_per_task, "token_budget_per_task"),
                (args.max_issues_per_task, "max_issues_per_task"),
                (args.dedup_window_seconds, "dedup_window_seconds"),
                (args.cooldown_seconds, "cooldown_seconds"),
            ):
                if argument is not None:
                    diagnostics[key] = argument
            # write_runtime_preferences normalizes numeric bounds and forces
            # local_only=true before bytes reach disk.
            write_runtime_preferences(root, {"diagnostics": diagnostics})
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: update local diagnostics policy",
            target_paths=[path],
        )
        print("[ok] updated local diagnostics policy")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

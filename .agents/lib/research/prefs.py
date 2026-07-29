"""Runtime preferences (incl. autonomy) and explicit workspace bootstrap.

Semantic loaders are pure reads.  Workspace creation remains the responsibility
of explicit initialization and mutation commands.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from .journal import mutation_transaction
from .common import (
    ensure_dir,
    load_yaml,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)
from .paths import (
    UNIT_KIND_DIRS,
    _deep_fill_missing,
    candidate_pools_path,
    config_root,
    ensure_kb_gitignore,
    kb_root,
    kb_runtime_root,
    output_storage_root,
    raw_storage_root,
    runtime_preferences_path,
    source_search_root,
    synthesis_root,
    topic_taxonomy_path,
    units_root,
    user_root,
)

DEFAULT_SETTINGS_MARKDOWN = """# Research Settings

- [x] 自动入库事实类基础信息
- [x] 默认维护 topic / tag / candidate pool 治理目录
- [x] 外部 source search 先进入 staging，再决定是否入库
- [x] intake 阶段预热 PDF 解析缓存
- [ ] 自动生成详细论文笔记
- [ ] 完整笔记后自动提取 Figure / Table
- [x] 完整笔记后自动刷新结构
- [ ] 自动生成周报素材
- [ ] 自动提炼 PPT 可用表述
- [ ] 自动记录中间讨论过程
- [x] PDF Figure / Table 默认按 caption 裁整块版面
- [x] PDF 图片导出时过滤纯白图和 mask-like 图
- [x] AI 推断默认等待人工确认
- [x] AI 评价默认等待人工确认
- [x] 论文结构刷新 / figure 提取默认等待人工确认
- [x] idea review / select-best 默认保留显式决策痕迹
- [x] 知识库独立 Git 仓库默认启用
- [x] 自动提交策略默认使用 milestone，可在 runtime preferences 调整

模式说明：

- 论文完整笔记模式（`scaffold` / `draft`）请使用 runtime preferences 管理。
"""


DEFAULT_TOPIC_TAXONOMY = {
    "id": "topic-taxonomy",
    "status": "active",
    "generated_by": "knowledge-base-manager",
    "policy": {
        "canonical_topic_style": "lowercase-hyphen-slug",
        "canonical_tag_style": "lowercase-hyphen-slug",
        "overwriteable_fields": ["topics", "tags", "candidate_pools", "summary"],
    },
    "topics": {},
    "tags": {},
}


DEFAULT_CANDIDATE_POOLS = {
    "id": "candidate-pools",
    "status": "active",
    "generated_by": "knowledge-base-manager",
    "policy": {
        "selection_requires_confirmation": True,
        "default_membership_mode": "overwriteable",
    },
    "pools": {},
}


VERSIONING_COMMIT_MODES = {"manual", "milestone", "aggressive"}


# Automation tier for a user-dropped link: either come back and ask before the
# deep read, or run the deep read automatically up to (never past) the
# user-confirmation gate.
LINK_AUTODRIVE_MODES = {"ask_first", "auto_deep_read"}

DEFAULT_LINK_AUTODRIVE = "ask_first"

# Conversational stance the user prefers when discussing research judgements.
DISCUSSION_STYLES = {"challenge", "refine", "adaptive"}

DEFAULT_DISCUSSION_STYLE = "adaptive"


DIAGNOSTIC_MODES = {"off", "errors-only", "developer"}


DIAGNOSTIC_SKILL_MODES = {"inherit", *DIAGNOSTIC_MODES}


PAPER_NOTE_MODES = {"scaffold", "draft"}


GOVERNANCE_PROFILES = {"personal", "strict"}
DEFAULT_GOVERNANCE_PROFILE = "personal"
LEGACY_GOVERNANCE_PROFILE = "strict"
STRICT_REVIEW_ITEM_LIMIT = 3
STRICT_REVIEW_CARD_TTL_HOURS = 24
PERSONAL_REVIEW_ITEM_LIMIT = 10
PERSONAL_REVIEW_CARD_TTL_HOURS = 24
MAX_REVIEW_ITEM_LIMIT = 20
MIN_PERSONAL_REVIEW_ITEM_LIMIT = 4
MIN_REVIEW_CARD_TTL_HOURS = 1
MAX_REVIEW_CARD_TTL_HOURS = 168


_RETIRED_PAPER_PREFERENCES = {
    "auto_screen_on_intake",
    "auto_complete_note_condition",
    "screening_mode",
    "screening_context_pages",
    "screening_max_chars",
}


def default_runtime_preferences() -> dict[str, Any]:
    return {
        **yaml_default("runtime-preferences", "research-config-manager", status="active"),
        # New workspaces opt into the lower-ceremony profile explicitly.
        # load_runtime_preferences keeps pre-profile workspaces strict.
        "governance_profile": DEFAULT_GOVERNANCE_PROFILE,
        "review": {
            "batch_item_limit": PERSONAL_REVIEW_ITEM_LIMIT,
            "card_ttl_hours": PERSONAL_REVIEW_CARD_TTL_HOURS,
        },
        "browser": {
            "default_workbench_mode": "preview",
            "default_terminal_mode": "codex",
            "auto_open_recent_file": True,
        },
        "identity": {
            "default_confirmed_by": "",
        },
        "learned_preferences": {
            "items": [],
        },
        "diagnostics": {
            "mode": "off",
            "per_skill": {},
            "local_only": True,
            "token_budget_per_task": 0,
            "max_issues_per_task": 20,
            "dedup_window_seconds": 604800,
            "cooldown_seconds": 0,
        },
        "autonomy": {
            "auto_execute_scope": ["ingest", "build-index", "refresh", "generate-note"],
            "link_autodrive": DEFAULT_LINK_AUTODRIVE,
        },
        "paper": {
            "auto_complete_note": False,
            "complete_note_mode": "scaffold",
            "auto_extract_figures_after_note": False,
            "auto_refresh_structure_after_note": True,
            "parse_cache_prewarm_on_intake": True,
            "parse_cache_front_limit": 8,
            "parse_cache_back_limit": 0,
            "parse_cache_per_page_char_limit": 3000,
            "prompt_for_preference_updates": True,
        },
        "pdf": {
            "prefer_structured_source": True,
            "auto_extract_figures": False,
            "figure_extraction_mode": "caption-region",
            "reuse_cached_parse": True,
            "figure_include_tables": True,
            "figure_render_scale": 2.5,
            "figure_crop_padding_pt": 12,
            "filter_blank_and_mask_images": True,
        },
        "versioning": {
            "enabled": True,
            "separate_repo": True,
            "auto_init_repo": True,
            "auto_commit_mode": "milestone",
            "commit_on_browser_save": False,
            "debounce_seconds": 30,
            "ignored_paths": ["raw/", "output/", "user/kb/", ".runtime/"],
        },
    }


def _normalize_diagnostics_preferences(value: object) -> dict[str, Any]:
    diagnostics = copy.deepcopy(value) if isinstance(value, dict) else {}
    mode = str(diagnostics.get("mode") or "off").strip().lower()
    diagnostics["mode"] = mode if mode in DIAGNOSTIC_MODES else "off"
    raw_per_skill = diagnostics.get("per_skill", {})
    per_skill: dict[str, str] = {}
    if isinstance(raw_per_skill, dict):
        for raw_skill, raw_mode in raw_per_skill.items():
            skill = str(raw_skill or "").strip().lower()
            skill_mode = str(raw_mode or "inherit").strip().lower()
            if skill and skill_mode in DIAGNOSTIC_SKILL_MODES:
                per_skill[skill] = skill_mode
    diagnostics["per_skill"] = per_skill
    # D1 is deliberately local-only.  Persisted attempts to disable this are
    # ignored so a malformed or older preference file cannot enable telemetry.
    diagnostics["local_only"] = True
    try:
        diagnostics["token_budget_per_task"] = max(0, int(diagnostics.get("token_budget_per_task") or 0))
    except (TypeError, ValueError):
        diagnostics["token_budget_per_task"] = 0
    try:
        diagnostics["max_issues_per_task"] = max(1, int(diagnostics.get("max_issues_per_task") or 20))
    except (TypeError, ValueError):
        diagnostics["max_issues_per_task"] = 20
    try:
        diagnostics["dedup_window_seconds"] = max(0, int(diagnostics.get("dedup_window_seconds") or 0))
    except (TypeError, ValueError):
        diagnostics["dedup_window_seconds"] = 604800
    try:
        diagnostics["cooldown_seconds"] = max(0, int(diagnostics.get("cooldown_seconds") or 0))
    except (TypeError, ValueError):
        diagnostics["cooldown_seconds"] = 0
    return diagnostics


def _bounded_integer(value: object, default: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        parsed = int(value.strip())
    else:
        return default
    return min(maximum, max(minimum, parsed))


def _normalize_review_preferences(value: object) -> dict[str, int]:
    review = copy.deepcopy(value) if isinstance(value, dict) else {}
    return {
        "batch_item_limit": _bounded_integer(
            review.get("batch_item_limit"),
            PERSONAL_REVIEW_ITEM_LIMIT,
            minimum=MIN_PERSONAL_REVIEW_ITEM_LIMIT,
            maximum=MAX_REVIEW_ITEM_LIMIT,
        ),
        "card_ttl_hours": _bounded_integer(
            review.get("card_ttl_hours"),
            PERSONAL_REVIEW_CARD_TTL_HOURS,
            minimum=MIN_REVIEW_CARD_TTL_HOURS,
            maximum=MAX_REVIEW_CARD_TTL_HOURS,
        ),
    }


def effective_review_policy(project_root: Path) -> dict[str, Any]:
    """Return the one normalized review policy consumed by public adapters.

    Callers must copy these values into the one-time review snapshot.  Apply
    paths consume that frozen snapshot and must not call this helper again.
    """

    preferences = load_runtime_preferences(project_root)
    profile = str(preferences.get("governance_profile") or LEGACY_GOVERNANCE_PROFILE)
    if profile != "personal":
        return {
            "governance_profile": "strict",
            "item_limit": STRICT_REVIEW_ITEM_LIMIT,
            "card_ttl_hours": STRICT_REVIEW_CARD_TTL_HOURS,
            "ttl_seconds": STRICT_REVIEW_CARD_TTL_HOURS * 60 * 60,
            "absolute_max_items": MAX_REVIEW_ITEM_LIMIT,
        }
    review = _normalize_review_preferences(preferences.get("review"))
    ttl_hours = review["card_ttl_hours"]
    return {
        "governance_profile": "personal",
        "item_limit": review["batch_item_limit"],
        "card_ttl_hours": ttl_hours,
        "ttl_seconds": ttl_hours * 60 * 60,
        "absolute_max_items": MAX_REVIEW_ITEM_LIMIT,
    }


def load_runtime_preferences(project_root: Path) -> dict[str, Any]:
    preferences_path = runtime_preferences_path(project_root)
    has_existing_config = preferences_path.exists()
    payload = load_yaml(preferences_path, default={})
    raw_profile = payload.get("governance_profile") if isinstance(payload, dict) else None
    has_existing_payload = isinstance(payload, dict) and bool(payload)
    if not has_existing_payload:
        payload = default_runtime_preferences()
    normalized = _deep_fill_missing(payload, default_runtime_preferences())
    if has_existing_config:
        profile = str(raw_profile or "").strip().lower()
        normalized["governance_profile"] = profile if profile in GOVERNANCE_PROFILES else LEGACY_GOVERNANCE_PROFILE
    else:
        normalized["governance_profile"] = DEFAULT_GOVERNANCE_PROFILE
    normalized["review"] = _normalize_review_preferences(normalized.get("review"))
    browser = normalized.get("browser", {})
    if not isinstance(browser, dict):
        browser = {}
    browser["default_workbench_mode"] = str(browser.get("default_workbench_mode") or "preview")
    browser["default_terminal_mode"] = str(browser.get("default_terminal_mode") or "codex")
    browser["auto_open_recent_file"] = bool(browser.get("auto_open_recent_file"))
    normalized["browser"] = browser

    identity = normalized.get("identity", {})
    if not isinstance(identity, dict):
        identity = {}
    identity["default_confirmed_by"] = str(identity.get("default_confirmed_by") or "").strip()
    normalized["identity"] = identity

    learned_preferences = normalized.get("learned_preferences", {})
    if not isinstance(learned_preferences, dict):
        learned_preferences = {}
    items = learned_preferences.get("items", [])
    learned_preferences["items"] = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    normalized["learned_preferences"] = learned_preferences

    normalized["diagnostics"] = _normalize_diagnostics_preferences(normalized.get("diagnostics"))

    autonomy = normalized.get("autonomy", {})
    if not isinstance(autonomy, dict):
        autonomy = copy.deepcopy(default_runtime_preferences()["autonomy"])
    scope = autonomy.get("auto_execute_scope", [])
    if not isinstance(scope, list):
        scope = copy.deepcopy(default_runtime_preferences()["autonomy"]["auto_execute_scope"])
    autonomy["auto_execute_scope"] = [
        str(item).strip() for item in scope if str(item).strip() and str(item).strip() != "screen"
    ]
    autodrive = str(autonomy.get("link_autodrive") or DEFAULT_LINK_AUTODRIVE).strip().lower()
    autonomy["link_autodrive"] = autodrive if autodrive in LINK_AUTODRIVE_MODES else DEFAULT_LINK_AUTODRIVE
    normalized["autonomy"] = autonomy

    paper = normalized.get("paper", {})
    if not isinstance(paper, dict):
        paper = {}
    for retired_key in _RETIRED_PAPER_PREFERENCES:
        paper.pop(retired_key, None)
    paper["auto_complete_note"] = bool(paper.get("auto_complete_note"))
    note_mode = str(paper.get("complete_note_mode") or "scaffold").strip()
    paper["complete_note_mode"] = note_mode if note_mode in PAPER_NOTE_MODES else "scaffold"
    paper["auto_extract_figures_after_note"] = bool(paper.get("auto_extract_figures_after_note"))
    paper["auto_refresh_structure_after_note"] = bool(paper.get("auto_refresh_structure_after_note", True))
    paper["parse_cache_prewarm_on_intake"] = bool(paper.get("parse_cache_prewarm_on_intake", True))
    try:
        paper["parse_cache_front_limit"] = max(1, int(paper.get("parse_cache_front_limit") or 8))
    except (TypeError, ValueError):
        paper["parse_cache_front_limit"] = 8
    try:
        paper["parse_cache_back_limit"] = max(0, int(paper.get("parse_cache_back_limit") or 0))
    except (TypeError, ValueError):
        paper["parse_cache_back_limit"] = 0
    try:
        paper["parse_cache_per_page_char_limit"] = max(500, int(paper.get("parse_cache_per_page_char_limit") or 3000))
    except (TypeError, ValueError):
        paper["parse_cache_per_page_char_limit"] = 3000
    paper["prompt_for_preference_updates"] = bool(paper.get("prompt_for_preference_updates", True))
    normalized["paper"] = paper

    pdf = normalized.get("pdf", {})
    if not isinstance(pdf, dict):
        pdf = {}
    pdf["prefer_structured_source"] = bool(pdf.get("prefer_structured_source"))
    pdf["auto_extract_figures"] = bool(pdf.get("auto_extract_figures"))
    pdf["figure_extraction_mode"] = "caption-region"
    pdf["reuse_cached_parse"] = bool(pdf.get("reuse_cached_parse"))
    pdf["figure_include_tables"] = bool(pdf.get("figure_include_tables", True))
    try:
        pdf["figure_render_scale"] = max(1.0, float(pdf.get("figure_render_scale") or 2.5))
    except (TypeError, ValueError):
        pdf["figure_render_scale"] = 2.5
    try:
        pdf["figure_crop_padding_pt"] = max(0.0, float(pdf.get("figure_crop_padding_pt") or 12))
    except (TypeError, ValueError):
        pdf["figure_crop_padding_pt"] = 12.0
    pdf["filter_blank_and_mask_images"] = bool(pdf.get("filter_blank_and_mask_images"))
    normalized["pdf"] = pdf

    versioning = normalized.get("versioning", {})
    if not isinstance(versioning, dict):
        versioning = {}
    versioning["enabled"] = bool(versioning.get("enabled"))
    versioning["separate_repo"] = bool(versioning.get("separate_repo"))
    versioning["auto_init_repo"] = bool(versioning.get("auto_init_repo"))
    mode = str(versioning.get("auto_commit_mode") or "milestone").strip().lower()
    versioning["auto_commit_mode"] = mode if mode in VERSIONING_COMMIT_MODES else "milestone"
    versioning["commit_on_browser_save"] = bool(versioning.get("commit_on_browser_save"))
    try:
        versioning["debounce_seconds"] = max(0, int(versioning.get("debounce_seconds") or 0))
    except (TypeError, ValueError):
        versioning["debounce_seconds"] = 30
    ignored = versioning.get("ignored_paths", [])
    normalized_ignored: list[str] = []
    if isinstance(ignored, list):
        for item in ignored:
            text = str(item).strip()
            if not text:
                continue
            if text.startswith("kb/"):
                text = text[3:]
            normalized_ignored.append(text)
    versioning["ignored_paths"] = normalized_ignored
    normalized["versioning"] = versioning
    return normalized


def write_runtime_preferences(project_root: Path, payload: dict[str, Any]) -> Path:
    path = runtime_preferences_path(project_root)
    with mutation_transaction(project_root, "write-runtime-preferences", [path]):
        current = load_runtime_preferences(project_root)
        merged = copy.deepcopy(current)
        if "governance_profile" in payload:
            profile = str(payload.get("governance_profile") or "").strip().lower()
            merged["governance_profile"] = profile if profile in GOVERNANCE_PROFILES else LEGACY_GOVERNANCE_PROFILE
        for key in ("review", "browser", "identity", "learned_preferences", "diagnostics", "autonomy", "paper", "pdf", "versioning"):
            value = payload.get(key)
            if isinstance(value, dict):
                target = merged.setdefault(key, {})
                if not isinstance(target, dict):
                    target = {}
                    merged[key] = target
                target.update(value)
        normalized = _deep_fill_missing(merged, default_runtime_preferences())
        profile = str(normalized.get("governance_profile") or "").strip().lower()
        normalized["governance_profile"] = profile if profile in GOVERNANCE_PROFILES else LEGACY_GOVERNANCE_PROFILE
        normalized["review"] = _normalize_review_preferences(normalized.get("review"))
        normalized["diagnostics"] = _normalize_diagnostics_preferences(normalized.get("diagnostics"))
        autonomy = normalized.get("autonomy", {})
        if isinstance(autonomy, dict):
            scope = autonomy.get("auto_execute_scope", [])
            autonomy["auto_execute_scope"] = [
                str(item).strip()
                for item in scope if str(item).strip() and str(item).strip() != "screen"
            ] if isinstance(scope, list) else copy.deepcopy(default_runtime_preferences()["autonomy"]["auto_execute_scope"])
        paper = normalized.get("paper", {})
        if isinstance(paper, dict):
            for retired_key in _RETIRED_PAPER_PREFERENCES:
                paper.pop(retired_key, None)
        write_yaml_if_changed(path, normalized)
    return path


def ensure_workspace(project_root: Path) -> None:
    ensure_dir(units_root(project_root))
    for kind in UNIT_KIND_DIRS.values():
        ensure_dir(units_root(project_root) / kind)
    ensure_dir(kb_root(project_root) / "programs")
    ensure_dir(user_root(project_root))
    ensure_dir(user_root(project_root) / "reading-lists")
    ensure_dir(user_root(project_root) / "report-materials")
    ensure_dir(config_root(project_root))
    ensure_dir(synthesis_root(project_root))
    ensure_dir(source_search_root(project_root))
    ensure_dir(raw_storage_root(project_root))
    ensure_dir(output_storage_root(project_root))
    ensure_dir(kb_runtime_root(project_root))
    ensure_kb_gitignore(project_root)
    settings = config_root(project_root) / "research-settings.md"
    if not settings.exists():
        write_text_if_changed(settings, DEFAULT_SETTINGS_MARKDOWN)
    navigation = user_root(project_root) / "navigation.md"
    if not navigation.exists():
        write_text_if_changed(
            navigation,
            "# Research Navigation\n\n- Agent 可在需要时生成研究入口；这里暂时没有内容。\n",
        )
    current_state = user_root(project_root) / "current-state.md"
    if not current_state.exists():
        write_text_if_changed(current_state, "# Current State\n\n尚未生成。\n")
    if not topic_taxonomy_path(project_root).exists():
        write_yaml_if_changed(topic_taxonomy_path(project_root), {**DEFAULT_TOPIC_TAXONOMY, "generated_at": utc_now_iso()})
    if not candidate_pools_path(project_root).exists():
        write_yaml_if_changed(candidate_pools_path(project_root), {**DEFAULT_CANDIDATE_POOLS, "generated_at": utc_now_iso()})
    if not runtime_preferences_path(project_root).exists():
        write_yaml_if_changed(runtime_preferences_path(project_root), default_runtime_preferences())


__all__ = [
    "DEFAULT_SETTINGS_MARKDOWN",
    "DEFAULT_TOPIC_TAXONOMY",
    "DEFAULT_CANDIDATE_POOLS",
    "VERSIONING_COMMIT_MODES",
    "LINK_AUTODRIVE_MODES",
    "DEFAULT_LINK_AUTODRIVE",
    "DISCUSSION_STYLES",
    "DEFAULT_DISCUSSION_STYLE",
    "DIAGNOSTIC_MODES",
    "DIAGNOSTIC_SKILL_MODES",
    "PAPER_NOTE_MODES",
    "GOVERNANCE_PROFILES",
    "DEFAULT_GOVERNANCE_PROFILE",
    "LEGACY_GOVERNANCE_PROFILE",
    "STRICT_REVIEW_ITEM_LIMIT",
    "STRICT_REVIEW_CARD_TTL_HOURS",
    "PERSONAL_REVIEW_ITEM_LIMIT",
    "PERSONAL_REVIEW_CARD_TTL_HOURS",
    "MAX_REVIEW_ITEM_LIMIT",
    "MIN_PERSONAL_REVIEW_ITEM_LIMIT",
    "MIN_REVIEW_CARD_TTL_HOURS",
    "MAX_REVIEW_CARD_TTL_HOURS",
    "effective_review_policy",
    "default_runtime_preferences",
    "load_runtime_preferences",
    "write_runtime_preferences",
    "ensure_workspace",
]
